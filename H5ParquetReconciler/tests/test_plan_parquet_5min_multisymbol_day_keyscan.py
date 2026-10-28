"""Synthetic-only shared single-day multiple-stock RowGroup key scan tests."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone, timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location(
    "shared_multi_symbol_key_pilot", TOOLS /
    "plan-parquet-5min-multisymbol-day-keyscan.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
TZ = timezone(timedelta(hours=8))


def millis(value):
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M").replace(
        tzinfo=TZ).timestamp() * 1000)


class SharedMultiStockDayKeyScanTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.root = self.home / "synthetic paid root with spaces"
        (self.root / "AllCycleAStockData").mkdir(parents=True)

    def row(self, stamp, symbol):
        return {
            "ts": millis(stamp), "symbol": symbol,
            "open": 10.0, "high": 11.0, "low": 9.0,
            "close": 10.5, "volume": 20.0, "amount": 150.0,
        }

    def write(self, rows, row_group_size=2):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow unavailable")
        target = self.root / "AllCycleAStockData" / "5min" / "2026-09.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), str(target),
                       row_group_size=row_group_size)
        return target

    def fixture(self):
        self.write([
            # All 3 same-day groups are a conservative union candidate
            # despite group 0 having no target keys.
            self.row("2026-09-30 09:30", "000002.XSHE"),
            self.row("2026-09-30 09:35", "688999.XSHG"),
            self.row("2026-09-30 09:30", "600000.XSHG"),
            self.row("2026-09-30 09:30", "000001.XSHE"),
            self.row("2026-09-30 09:35", "600000.XSHG"),
            self.row("2026-09-30 09:35", "000001.XSHE"),
            self.row("2026-09-29 09:30", "600000.XSHG"),
            self.row("2026-09-29 09:30", "000001.XSHE"),
        ])
        return M.plan(self.root, ["SH600000", "SZ000001"], "2026-09-30")

    def test_single_shared_two_key_scan_exact_membership_and_safety(self):
        result = self.fixture()
        self.assertEqual(result["requested_distinct_symbol_count"], 2)
        self.assertEqual(result["union_candidate_row_groups"], 3)
        self.assertEqual(result["union_source_key_rows_examined_once"], 6)
        self.assertEqual(result["union_candidate_source_rows_upper_bound"], 6)
        for record in result["per_symbol"]:
            self.assertEqual(record["matching_source_keys"], 2)
            self.assertEqual(record["exact_row_groups_containing_keys"], 2)
            self.assertEqual([x["row_group"] for x in record[
                "nonempty_row_group_locators"]], [1, 2])
            self.assertEqual([x["matching_key_count"] for x in record[
                "nonempty_row_group_locators"]], [1, 1])
        self.assertTrue(result["all_parquet_readers_explicitly_closed"])
        self.assertTrue(result["only_ts_and_symbol_columns_read"])
        self.assertFalse(result["source_market_files_modified"])
        self.assertGreater(result[
            "theoretical_rowgroup_row_upper_bound_saved_vs_independent_scans"], 0)
        wire = json.dumps(result)
        for key in ('"open":', '"close":', '"volume":', '"amount":',
                    '"source_timestamp_ms":'):
            self.assertNotIn(key, wire)

    def test_identical_individual_plans_in_synthetic_source(self):
        self.fixture()
        script = TOOLS / "plan-parquet-5min-exact-rowgroups.py"
        spec = importlib.util.spec_from_file_location(
            "individual_exact_key_plan_for_crosscheck", script)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        shared = M.plan(self.root, ["SH600000", "SZ000001"], "2026-09-30")
        for record in shared["per_symbol"]:
            single = old.plan(self.root, record["symbol"], "2026-09-30")
            self.assertEqual(record["matching_source_keys"],
                             single["matching_source_keys"])
            self.assertEqual(record["nonempty_row_group_locators"],
                             single["nonempty_source_row_group_locators"])
            self.assertEqual(record["individual_footer_candidate_row_groups"],
                             single["candidate_row_groups"])

    def test_duplicate_timestamp_and_bounded_budgets_fail_closed(self):
        self.write([
            self.row("2026-09-30 09:30", "600000.XSHG"),
            self.row("2026-09-30 09:35", "000001.XSHE"),
            self.row("2026-09-30 09:30", "600000.XSHG"),
            self.row("2026-09-30 09:40", "000001.XSHE"),
        ])
        with self.assertRaisesRegex(ValueError, "Duplicate source timestamp"):
            M.plan(self.root, ["SH600000", "SZ000001"], "2026-09-30")
        # Use a nonduplicate source for independent budget-failure tests.
        self.write([
            self.row("2026-09-30 09:30", "600000.XSHG"),
            self.row("2026-09-30 09:35", "000001.XSHE"),
            self.row("2026-09-30 09:40", "600000.XSHG"),
            self.row("2026-09-30 09:45", "000001.XSHE"),
        ])
        with self.assertRaisesRegex(ValueError, "--max-candidate-rows"):
            M.plan(self.root, ["SH600000", "SZ000001"], "2026-09-30",
                   max_candidate_rows=1)
        with self.assertRaisesRegex(ValueError, "--max-candidate-groups"):
            M.plan(self.root, ["SH600000", "SZ000001"], "2026-09-30",
                   max_candidate_groups=1)
        with self.assertRaisesRegex(ValueError, "--max-keys-per-symbol"):
            M.plan(self.root, ["SH600000", "SZ000001"], "2026-09-30",
                   max_keys_per_symbol=1)

    def test_input_rejects_noncanonical_duplicates_and_bshares(self):
        self.fixture()
        for symbols in (
            ["SH600000"], ["SH600000", "SH600000"],
            ["SH600000", "SZ200001"], ["BADCODE", "SZ000001"],
            ["SH600000", "SZ000001"] * 5,
        ):
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                M.plan(self.root, symbols, "2026-09-30")

    def test_drift_in_source_manifest_invalidates_report(self):
        self.fixture()
        original = M.query.private_cache.source_signature
        calls = [0]

        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            calls[0] += 1
            if calls[0] == 2:
                result = dict(result)
                result["manifest_sha256_stat_only"] = "0" * 64
            return result

        with mock.patch.object(M.query.private_cache, "source_signature",
                               side_effect=changed):
            with self.assertRaisesRegex(ValueError, "manifest changed"):
                M.plan(self.root, ["SH600000", "SZ000001"], "2026-09-30")

    def test_all_source_readers_closed_on_success_and_error(self):
        self.fixture()
        import pyarrow.parquet as pq
        original = pq.ParquetFile
        live = []

        class Reader:
            def __init__(self, file):
                self.reader = original(file)
                self.closes = 0
                live.append(self)
            def __getattr__(self, key):
                return getattr(self.reader, key)
            def close(self):
                self.reader.close()
                self.closes += 1

        with mock.patch.object(pq, "ParquetFile", Reader):
            self.assertEqual(M.plan(
                self.root, ["SH600000", "SZ000001"], "2026-09-30")[
                "union_source_key_rows_examined_once"], 6)
        self.assertTrue(live)
        self.assertTrue(all(r.closes == 1 for r in live))
        live.clear()
        with mock.patch.object(pq, "ParquetFile", Reader):
            with self.assertRaisesRegex(ValueError, "--max-candidate-rows"):
                M.plan(self.root, ["SH600000", "SZ000001"], "2026-09-30",
                       max_candidate_rows=1)
        self.assertTrue(live)
        self.assertTrue(all(r.closes == 1 for r in live))

    def test_cli_writes_new_safe_report_only_within_module(self):
        self.fixture()
        fake = self.home / "H5ParquetReconciler"
        (fake / "reports").mkdir(parents=True)
        with (mock.patch.object(M, "MODULE", fake),
              mock.patch.object(M.query.core, "resolve_module_artifact_paths",
                                side_effect=lambda out: (
                                    (fake / out).resolve(),
                                    (fake / "work" / "_union_scratch").resolve())),
              mock.patch.object(M.query.core, "resolve_safe_paths",
                                side_effect=lambda source, out, scratch: (
                                    self.root.resolve(), out, scratch))):
            with redirect_stdout(StringIO()):
                M.main([str(self.root), "--symbols", "SH600000,SZ000001",
                        "--date", "2026-09-30", "--read-only",
                        "--out", "reports/shared-keys.json"])
            out = fake / "reports" / "shared-keys.json"
            self.assertEqual(len(json.loads(out.read_text())["per_symbol"]), 2)
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                M.main([str(self.root), "--symbols", "SH600000,SZ000001",
                        "--date", "2026-09-30", "--read-only",
                        "--out", "reports/shared-keys.json"])


if __name__ == "__main__":
    unittest.main()
