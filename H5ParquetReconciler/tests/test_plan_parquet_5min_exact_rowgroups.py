"""Synthetic exact stock-day RG key locator tests. Never use paid OHLCVA."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

SCRIPT = (Path(__file__).resolve().parents[1] / "tools" /
          "plan-parquet-5min-exact-rowgroups.py")
SPEC = importlib.util.spec_from_file_location("parquet_exact_key_locator", SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
TZ = timezone(timedelta(hours=8))


def ms(timestamp):
    return int(datetime.strptime(timestamp, "%Y-%m-%d %H:%M").replace(
        tzinfo=TZ).timestamp()*1000)


class ExactStockDayKeyLocatorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "stock data with spaces"
        (self.root / "AllCycleAStockData").mkdir(parents=True)

    def row(self, stamp, symbol="600000.XSHG"):
        return {
            "ts": ms(stamp), "symbol": symbol,
            "open": 10.0, "high": 11.0, "low": 9.0,
            "close": 10.5, "volume": 10.0, "amount": 100.0,
        }

    def write(self, rows, row_group_size=2):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow unavailable")
        path = self.root / "AllCycleAStockData" / "5min" / "2026-09.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), str(path),
                       row_group_size=row_group_size)
        return path

    def test_exact_membership_prunes_absent_groups_only_with_full_key_scan(self):
        self.write([
            # Wide symbol min/max would allow the target symbol although
            # neither key in this RowGroup actually matches SH600000.
            self.row("2026-09-30 09:30", "000001.XSHE"),
            self.row("2026-09-30 09:35", "688999.XSHG"),
            self.row("2026-09-30 09:30"),
            self.row("2026-09-30 09:35", "000001.XSHE"),
            self.row("2026-09-30 09:40", "000001.XSHE"),
            self.row("2026-09-30 09:45"),
        ],row_group_size=2)
        plan = M.plan(self.root,"SH600000","2026-09-30")
        self.assertEqual(plan["candidate_row_groups"], 3)
        self.assertEqual(plan["exact_groups_containing_target_keys"], 2)
        self.assertEqual(plan["exact_groups_without_target_keys"], 1)
        self.assertEqual(plan["matching_source_keys"], 2)
        self.assertEqual(plan["two_key_columns_source_rows_examined"], 6)
        self.assertEqual([x["row_group"] for x in
                          plan["nonempty_source_row_group_locators"]], [1,2])
        self.assertTrue(plan["ALL_footer_candidate_groups_key_columns_scanned"])
        self.assertFalse(plan["current_production_query_modified"])
        self.assertFalse(plan["raw_ohlcva_exported"])
        output = json.dumps(plan)
        self.assertNotIn('"close":', output)
        self.assertNotIn('"volume":', output)
        self.assertEqual(len(plan["source_stat_manifest_sha256"]),64)

    def test_missing_target_does_not_fake_complete_market_day(self):
        self.write([self.row("2026-09-30 09:30", "000001.XSHE")])
        result = M.plan(self.root,"SH600000","2026-09-30")
        self.assertEqual(result["matching_source_keys"],0)
        self.assertEqual(result["exact_groups_containing_target_keys"],0)
        self.assertTrue(result["net_query_speedup_not_measured"])

    def test_duplicate_timestamp_across_groups_rejected(self):
        self.write([
            self.row("2026-09-30 09:30"),
            self.row("2026-09-30 09:30"),
        ],row_group_size=1)
        with self.assertRaisesRegex(ValueError,"Duplicate timestamp"):
            M.plan(self.root,"SH600000","2026-09-30")

    def test_budget_rejects_without_scanning_market_ohlcva(self):
        self.write([
            self.row("2026-09-30 09:30"),
            self.row("2026-09-30 09:35"),
        ],row_group_size=1)
        with self.assertRaisesRegex(ValueError,"--max-candidate-rows"):
            M.plan(self.root,"SH600000","2026-09-30",max_candidate_rows=1)
        with self.assertRaisesRegex(ValueError,"--max-candidate-groups"):
            M.plan(self.root,"SH600000","2026-09-30",max_candidate_groups=1)
        with self.assertRaisesRegex(ValueError,"--max-result-keys"):
            M.plan(self.root,"SH600000","2026-09-30",max_result_keys=1)

    def test_source_metadata_change_rejects_locator(self):
        self.write([self.row("2026-09-30 09:30")])
        original = M.query.private_cache.source_signature
        calls = [0]
        def moved(*args, **kwargs):
            value = original(*args, **kwargs)
            calls[0] += 1
            if calls[0] == 2:
                value = dict(value)
                value["manifest_sha256_stat_only"] = "0"*64
            return value
        with mock.patch.object(M.query.private_cache, "source_signature",
                               side_effect=moved):
            with self.assertRaisesRegex(ValueError,"manifest changed"):
                M.plan(self.root,"SH600000","2026-09-30")

    def test_cli_only_writes_safe_reports_new_file_not_source(self):
        self.write([self.row("2026-09-30 09:30")])
        fake_module = self.base / "H5ParquetReconciler"
        (fake_module / "reports").mkdir(parents=True)
        with (mock.patch.object(M, "MODULE", fake_module),
              mock.patch.object(M.query.core, "resolve_module_artifact_paths",
                                side_effect=lambda out: (
                                    (fake_module / out).resolve(),
                                    (fake_module / "work" / "_union_scratch").resolve())),
              mock.patch.object(M.query.core, "resolve_safe_paths",
                                side_effect=lambda root, out, scratch: (
                                    self.root.resolve(), out, scratch))):
            with redirect_stdout(StringIO()):
                M.main([str(self.root),"--symbol","SH600000",
                        "--date","2026-09-30", "--read-only",
                        "--out","reports/key-groups.json"])
            saved = (fake_module / "reports" / "key-groups.json")
            self.assertEqual(json.loads(saved.read_text())[
                "exact_groups_containing_target_keys"],1)
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                M.main([str(self.root),"--symbol","SH600000",
                        "--date","2026-09-30","--read-only",
                        "--out","reports/key-groups.json"])


if __name__ == "__main__":
    unittest.main()
