"""Synthetic/Arrow read-only inventory tests; never touch paid market files."""
import importlib.util
import os
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "tools" /
       "inventory-parquet-primary-footers.py")
SPEC = importlib.util.spec_from_file_location(
    "parquet_footer_inventory_test_module", SRC)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
TZ = timezone(timedelta(hours=8))


def epoch(stamp):
    return int(datetime.strptime(str(stamp), "%Y%m%d%H%M").replace(
        tzinfo=TZ).timestamp() * 1000)


def rg(lo, hi):
    stats = None if lo is None else types.SimpleNamespace(
        has_min_max=True, min=epoch(lo), max=epoch(hi))
    return types.SimpleNamespace(
        num_columns=1,
        column=lambda i: types.SimpleNamespace(
            path_in_schema="ts", statistics=stats))


class FooterOnlyPrimaryInventoryTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name) / "stock"
        (self.root / "AllCycleAStockData").mkdir(parents=True)

    def parquet(self, period, name, stamps, statistics=True, group=2):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow unavailable in test interpreter")
        dest = self.root / "AllCycleAStockData" / period / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        rows = [{
            "ts": epoch(t), "symbol": "600000.XSHG",
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 7., "amount": 70.,
        } for t in stamps]
        pq.write_table(pa.Table.from_pylist(rows), str(dest),
                       row_group_size=group, write_statistics=statistics)
        return dest

    def test_footer_bounds_valid_missing_and_inverted(self):
        self.assertEqual(M.footer_bounds(rg(202609300930,202609301455)),
                         ("2026-09-30 09:30", "2026-09-30 14:55",
                          "2026-09-30", "2026-09-30"))
        self.assertIsNone(M.footer_bounds(rg(None,None)))
        self.assertIsNone(M.footer_bounds(rg(202609301455,202609300930)))
        self.assertIsNone(M.footer_bounds(types.SimpleNamespace(
            num_columns=0, column=lambda i: None)))

    def test_real_synthetic_arrow_2026_three_periods_footer_only(self):
        self.parquet("day","2026-09.parquet",[202609301500])
        self.parquet("1min","2026-09.parquet",[
            202609300930,202609300931,202609301500])
        self.parquet("5min","2026-09.parquet",[
            202609300930,202609300935,202609301455])
        report = M.inventory(self.root,2026,2026,
                             ("day","1min","5min"),10,10)
        self.assertEqual(report["files_with_supported_year_in_requested_range"],3)
        entries={row["period"]:row for row in
                 report["filename_year_and_period_footer_entries"]}
        self.assertEqual(entries["1min"]["source_rows_from_parquet_footers"],3)
        self.assertEqual(entries["5min"]["source_rows_from_parquet_footers"],3)
        self.assertEqual(entries["1min"]["row_groups"],2)
        self.assertEqual(entries["5min"]["earliest_known_raw_beijing_timestamp"],
                         "2026-09-30 09:30")
        self.assertEqual(entries["5min"]["latest_known_calendar_date"],
                         "2026-09-30")
        self.assertTrue(all(v["footer_envelope_complete_for_nonempty_row_groups"]
                            for v in entries.values()))
        self.assertTrue(all(len(v[
            "source_file_stat_identity_sha256_not_content_digest"]) == 64
            for v in entries.values()))
        self.assertTrue(report["only_parquet_file_footers_read"])
        self.assertTrue(report["no_parquet_row_batches_or_paid_ohlcva_read"])
        self.assertFalse(report["safe_to_automatically_fill_gaps"])
        self.assertFalse(report["automatic_union_or_import_performed"])

    def test_missing_ts_footer_is_not_claimed_complete(self):
        self.parquet("1min","2026-08.parquet",[
            202608240930,202608240931],statistics=False)
        report=M.inventory(self.root,2026,2026,("1min",),10,10)
        year=report["filename_year_and_period_footer_entries"][0]
        self.assertEqual(year["nonempty_row_groups_without_usable_ts_bounds"],1)
        self.assertIsNone(year["latest_known_calendar_date"])
        self.assertFalse(year["footer_envelope_complete_for_nonempty_row_groups"])
        self.assertFalse(year["actual_trading_day_completeness_validated"])

    def test_missing_year_is_not_assumed_zero_market_activity(self):
        self.parquet("day","2026-09.parquet",[202609301500])
        result=M.inventory(self.root,2025,2026,("day","5min"),10,10)
        self.assertEqual(len(result["filename_year_and_period_footer_entries"]),4)
        missing=next(v for v in result[
            "filename_year_and_period_footer_entries"]
            if v["filename_year"]==2025 and v["period"]=="5min")
        self.assertEqual(missing["files"],0)
        self.assertIsNone(missing["earliest_known_calendar_date"])
        self.assertFalse(missing["footer_envelope_complete_for_nonempty_row_groups"])
        self.assertTrue(result["absence_of_file_is_not_proof_of_no_exchange_trades"])

    def test_ambiguous_filename_is_quarantined_and_year_outside_counted(self):
        self.parquet("5min","unknown.parquet",[202609300930])
        self.parquet("5min","2025/2026-09.parquet",[202609300930])
        self.parquet("5min","2024-10.parquet",[202410301430])
        report=M.inventory(self.root,2026,2026,("5min",),10,10)
        self.assertEqual(report["files_with_supported_year_in_requested_range"],0)
        names=report["file_naming_caveats"]
        self.assertEqual(names[
            "year_ambiguous_or_absent_parquet_filenames_by_period"]["5min"],2)
        self.assertEqual(names[
            "file_year_outside_requested_range_by_period"]["5min"],1)

    def test_file_budget_blocks_before_any_parquet_footer(self):
        self.parquet("5min","2026-08.parquet",[202608240930])
        self.parquet("5min","2026-09.parquet",[202609300930])
        with self.assertRaisesRegex(ValueError,
                                    "exceeds --max-files"):
            M.inventory(self.root,2026,2026,("5min",),1,10)

    def test_row_group_budget_detects_excess(self):
        self.parquet("1min","2026-09.parquet",[
            202609300930,202609300931,202609300932],group=1)
        with self.assertRaisesRegex(ValueError, "exceed --max-row-groups"):
            M.inventory(self.root,2026,2026,("1min",),10,2)

    def test_year_mismatch_does_not_claim_complete_footer(self):
        self.parquet("day","2026-09.parquet",[202509301500])
        report=M.inventory(self.root,2026,2026,("day",),10,10)
        year=report["filename_year_and_period_footer_entries"][0]
        self.assertEqual(
            year["row_groups_with_any_ts_bounds_outside_named_year"],1)
        self.assertFalse(year["footer_envelope_complete_for_nonempty_row_groups"])

    def test_invalid_periods_and_range_are_rejected(self):
        for years, periods in [
            ((2026,2025),("day",)),
            ((2011,2100),("day",)),
            ((2026,2026),("invalid",)),
            ((2026,2026),("day","day")),
            ((2026,2026),()),
        ]:
            with self.subTest(years=years, periods=periods), self.assertRaises(ValueError):
                M.inventory(self.root,*years,periods,10,10)

    def test_paths_have_no_raw_market_ohlcva_and_no_local_absolute_root(self):
        self.parquet("day","2026-09.parquet",[202609301500])
        wire=__import__("json").dumps(M.inventory(
            self.root,2026,2026,("day",),10,10))
        self.assertIn('"raw_market_ohlcva_exported": false',wire)
        self.assertNotIn(str(self.root),wire)
        self.assertNotIn('"open": 10',wire)
        self.assertNotIn('"volume": 7',wire)
        self.assertIn('"per_security_date_keys_validated": false',wire)


if __name__ == "__main__":
    unittest.main()
