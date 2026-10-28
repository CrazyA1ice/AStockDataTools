"""Synthetic-only bounded month shared key scan tests. Never paid OHLCVA."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def read_script(name, label):
    spec = importlib.util.spec_from_file_location(label, TOOLS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = read_script("plan-parquet-5min-multiday-shared-keys.py", "month_shared_test")
SINGLE = read_script(
    "plan-parquet-5min-multisymbol-day-keyscan.py", "single_day_shared_crosscheck")
TZ = timezone(timedelta(hours=8))


def ms(label):
    return int(datetime.strptime(label, "%Y-%m-%d %H:%M").replace(
        tzinfo=TZ).timestamp() * 1000)


class MultiDaySharedKeyScanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.root = self.home / "synthetic market with spaces"
        (self.root / "AllCycleAStockData").mkdir(parents=True)

    def row(self, date_and_time, symbol):
        return {
            "ts": ms(date_and_time), "symbol": symbol,
            "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
            "volume": 20.0, "amount": 200.0,
        }

    def write(self, entries, size=2):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow unavailable")
        target = self.root / "AllCycleAStockData" / "5min" / "2026-09.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(entries), str(target),
                       row_group_size=size)
        return target

    def fixture(self):
        self.write([
            self.row("2026-09-29 09:30", "600000.XSHG"),
            self.row("2026-09-29 09:30", "000001.XSHE"),
            self.row("2026-09-29 09:35", "600000.XSHG"),
            self.row("2026-09-29 09:35", "000002.XSHE"),
            self.row("2026-09-30 09:30", "600000.XSHG"),
            self.row("2026-09-30 09:30", "000001.XSHE"),
            self.row("2026-09-30 09:35", "600000.XSHG"),
            self.row("2026-09-30 09:35", "000001.XSHE"),
            self.row("2026-09-30 09:40", "000002.XSHE"),
            self.row("2026-09-30 09:40", "688999.XSHG"),
            self.row("2026-09-28 09:30", "600000.XSHG"),
            self.row("2026-09-28 09:30", "000001.XSHE"),
        ])

    def plan(self, a="2026-09-29", b="2026-09-30", **kwargs):
        return M.plan(
            self.root, ["SH600000", "SZ000001"], a, b, **kwargs)

    def test_two_stocks_two_dates_one_union_scan_exact_counts(self):
        self.fixture()
        out = self.plan()
        self.assertEqual(out["requested_distinct_symbol_count"], 2)
        self.assertEqual(out["requested_calendar_days"], 2)
        self.assertEqual(out["requested_symbol_day_count"], 4)
        self.assertEqual(out["matching_keys_all_stock_days"], 7)
        self.assertEqual(out["union_footer_candidate_row_groups"], 5)
        self.assertEqual(out["union_source_key_rows_examined_once"], 10)
        expected = {
            ("SH600000", "2026-09-29"): (2, [0, 1]),
            ("SH600000", "2026-09-30"): (2, [2, 3]),
            ("SZ000001", "2026-09-29"): (1, [0]),
            ("SZ000001", "2026-09-30"): (2, [2, 3]),
        }
        for entry in out["per_symbol_day"]:
            label = (entry["symbol"], entry["date"])
            count, gids = expected[label]
            self.assertEqual(entry["matching_source_keys"], count)
            self.assertEqual([e["row_group"] for e in entry[
                "nonempty_row_group_locators"]], gids)
        self.assertGreater(out[
            "theoretical_rows_avoided_vs_independent_symbol_scans"], 0)
        self.assertTrue(out["source_stat_manifest_stable_during_scan"])
        self.assertTrue(out["all_parquet_readers_explicitly_closed"])
        self.assertTrue(out["only_ts_and_symbol_columns_read"])
        wire = json.dumps(out)
        for key in ('"open":', '"close":', '"volume":', '"amount":',
                    '"source_timestamp_ms":'):
            self.assertNotIn(key, wire)

    def test_daily_locators_match_existing_single_day_shared_planner(self):
        self.fixture()
        month = self.plan()
        by_day = {}
        for day in ("2026-09-29", "2026-09-30"):
            single = SINGLE.plan(
                self.root, ["SH600000", "SZ000001"], day)
            for entry in single["per_symbol"]:
                by_day[(entry["symbol"], day)] = entry
        for entry in month["per_symbol_day"]:
            prev = by_day[(entry["symbol"], entry["date"])]
            self.assertEqual(entry["matching_source_keys"],
                             prev["matching_source_keys"])
            self.assertEqual(entry["nonempty_row_group_locators"],
                             prev["nonempty_row_group_locators"])
        self.assertEqual(month["matching_keys_all_stock_days"], 7)

    def test_zero_key_calendar_day_preserved_not_made_complete(self):
        self.fixture()
        plan = self.plan("2026-09-27", "2026-09-30")
        self.assertEqual(plan["requested_calendar_days"], 4)
        empty = [x for x in plan["per_symbol_day"]
                 if x["date"] == "2026-09-27"]
        self.assertEqual(len(empty), 2)
        self.assertTrue(all(x["matching_source_keys"] == 0 for x in empty))
        self.assertEqual(plan["matching_keys_all_stock_days"], 9)

    def test_reject_unbounded_month_crossovers_and_bad_codes(self):
        self.fixture()
        for args in (
            (["SH600000", "SZ000001"], "2026-09-30", "2026-10-01"),
            (["SH600000", "SZ000001"], "2026-09-30", "2026-09-29"),
            (["SH600000"], "2026-09-29", "2026-09-30"),
            (["SH600000", "SH600000"], "2026-09-29", "2026-09-30"),
            (["SH600000", "SZ200001"], "2026-09-29", "2026-09-30"),
            (["SH600000", "SZ000001"] * 5, "2026-09-29", "2026-09-30"),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                M.plan(self.root, *args)

    def test_budgets_and_duplicate_key_fail_closed(self):
        self.fixture()
        for kwargs, error in (
            ({"max_candidate_rows": 1}, "--max-candidate-rows"),
            ({"max_candidate_groups": 1}, "--max-candidate-groups"),
            ({"max_keys_per_stock_day": 1}, "--max-keys-per-stock-day"),
            ({"max_total_keys": 1}, "--max-total-keys"),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(
                    ValueError, error):
                self.plan(**kwargs)
        # Identical canonical stock/date/time across different source groups.
        self.write([
            self.row("2026-09-29 09:30", "600000.XSHG"),
            self.row("2026-09-29 09:35", "000001.XSHE"),
            self.row("2026-09-29 09:30", "600000.XSHG"),
            self.row("2026-09-30 09:30", "000001.XSHE"),
        ], size=1)
        with self.assertRaisesRegex(ValueError, "Duplicate selected"):
            self.plan()

    def test_manifest_drift_and_reader_closure_on_error(self):
        self.fixture()
        import pyarrow.parquet as pq
        original_pf = pq.ParquetFile
        held = []

        class Reader:
            def __init__(self, path):
                self.obj = original_pf(path)
                self.closed = 0
                held.append(self)

            def __getattr__(self, key):
                return getattr(self.obj, key)

            def iter_batches(self, *args, **kwargs):
                # No OHLCVA/paid market fields are ever projected.
                self_outer.assertEqual(kwargs.get("columns"), ["ts", "symbol"])
                return self.obj.iter_batches(*args, **kwargs)

            def close(self):
                self.closed += 1
                self.obj.close()

        self_outer = self
        with mock.patch.object(pq, "ParquetFile", Reader):
            self.assertEqual(self.plan()["matching_keys_all_stock_days"], 7)
        self.assertTrue(held)
        self.assertTrue(all(r.closed == 1 for r in held))

        held.clear()
        real = M.query.private_cache.source_signature
        calls = [0]

        def drift(*args, **kwargs):
            signature = real(*args, **kwargs)
            calls[0] += 1
            if calls[0] == 2:
                signature = dict(signature)
                signature["manifest_sha256_stat_only"] = "0" * 64
            return signature

        with (mock.patch.object(pq, "ParquetFile", Reader),
              mock.patch.object(M.query.private_cache,
                                "source_signature", side_effect=drift)):
            with self.assertRaisesRegex(ValueError, "manifest changed"):
                self.plan()
        self.assertTrue(held)
        self.assertTrue(all(r.closed == 1 for r in held))

    def test_cli_safe_new_json_and_never_overwrite(self):
        self.fixture()
        fake = self.home / "H5ParquetReconciler"
        (fake / "reports").mkdir(parents=True)
        with (mock.patch.object(M, "MODULE", fake),
              mock.patch.object(M.query.core, "resolve_module_artifact_paths",
                                side_effect=lambda path: (
                                    (fake / path).resolve(),
                                    (fake / "work" / "_union_scratch").resolve())),
              mock.patch.object(M.query.core, "resolve_safe_paths",
                                side_effect=lambda root, out, scratch: (
                                    self.root.resolve(), out, scratch))):
            args = [
                str(self.root), "--symbols", "SH600000,SZ000001",
                "--from-date", "2026-09-29",
                "--to-date", "2026-09-30", "--read-only",
                "--out", "reports/month-shared.json"]
            with redirect_stdout(StringIO()):
                M.main(args)
            saved = json.loads((fake / "reports" /
                                "month-shared.json").read_text())
            self.assertEqual(saved["matching_keys_all_stock_days"], 7)
            self.assertTrue(saved["no_raw_ohlcva_or_individual_intraday_time_keys_exported"])
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                M.main(args)


if __name__ == "__main__":
    unittest.main()
