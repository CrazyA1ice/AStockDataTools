"""Synthetic year/period Parquet FOOTER-only source inventory contracts."""
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "all_cycle_footer_survey_under_test",
    HERE.parent / "tools" / "survey-purchased-all-cycle-footers-readonly.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class AllCycleFooterSurveyTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.pa, self.pq = pa, pq
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "AllCycleAStockData"
        self.base.mkdir()
        self.periods = ("1min", "5min", "15min", "30min",
                        "60min", "day", "week", "month")
        start = datetime(2025, 4, 7, 9, 30, tzinfo=timezone(timedelta(hours=8)))
        for period in self.periods:
            target = self.base / period
            target.mkdir()
            self.pq.write_table(self.pa.table({
                "ts": self.pa.array([int(start.timestamp()*1000)],
                                    type=self.pa.int64()),
                "symbol": ["SH600000"],
                "open": [10.5], "high": [10.8], "low": [10.2],
                "close": [10.6], "volume": [100.], "amount": [1000.],
            }), target / "2025.parquet")

    def test_real_synthetic_parquet_footer_all_eight_periods(self):
        out = M.inventory(self.root, years=(2025, 2026))
        self.assertEqual(set(out["source_root_period_directories"]),
                         set(self.periods))
        self.assertEqual(out["total_year_assigned_parquet_files"], 8)
        for p in self.periods:
            self.assertEqual(out["period_years"][p]["2025"]["source_files"], 1)
            self.assertEqual(
                out["period_years"][p]["2025"][
                    "source_rows_from_parquet_footers"], 1)
            self.assertEqual(
                out["period_years"][p]["2025"][
                    "earliest_known_raw_beijing_timestamp"],
                "2025-04-07 09:30")
            self.assertEqual(out["period_years"][p]["2026"]["source_files"], 0)
            self.assertFalse(out["period_years"][p]["2026"][
                "full_calendar_coverage_certified"])
        self.assertTrue(out["no_ohlcva_rows_read_or_exported"])
        self.assertFalse(out["actual_stockday_and_full_exchange_calendar_coverage_certified"])

    def test_source_files_are_never_rewritten(self):
        files = [self.base/p/"2025.parquet" for p in self.periods]
        before = [(p.stat().st_size, p.stat().st_mtime_ns) for p in files]
        M.inventory(self.root, years=(2025,))
        after = [(p.stat().st_size, p.stat().st_mtime_ns) for p in files]
        self.assertEqual(before, after)

    def test_unknown_period_labels_are_discovered_not_invented(self):
        folder = self.base / "custom_cycle"
        folder.mkdir()
        out = M.inventory(self.root, years=(2025,))
        self.assertIn("custom_cycle", out["source_root_period_directories"])
        self.assertEqual(out["period_years"]["custom_cycle"]["2025"]["source_files"], 0)
        self.assertFalse(out["period_years"]["custom_cycle"]["2025"][
            "footer_envelope_complete_for_nonempty_row_groups"])

    def test_missing_root_rejected(self):
        with self.assertRaisesRegex(ValueError, "source|root"):
            M.inventory(self.root / "missing", years=(2025,))

    def test_invalid_year_and_file_budget_fail_closed(self):
        with self.assertRaises(ValueError):
            M.inventory(self.root, years=(1990,))
        with self.assertRaisesRegex(ValueError, "budget"):
            M.inventory(self.root, years=(2025,), max_total_files=2)

    def test_no_ohlcva_column_batch_reader_called(self):
        with patch.object(self.pq.ParquetFile, "iter_batches",
                          side_effect=AssertionError("Row batch read forbidden")), \
             patch.object(self.pq.ParquetFile, "read_row_group",
                          side_effect=AssertionError("OHLCVA group read forbidden")), \
             patch.object(M.F, "year_period_footer",
                          wraps=M.F.year_period_footer) as footer:
            out = M.inventory(self.root, years=(2025,))
        self.assertTrue(out["only_original_parquet_file_footers_read"])
        self.assertEqual(footer.call_count, len(self.periods))

    def test_spaces_and_noncanonical_folder_names_are_discovered_but_unmapped(self):
        (self.base / "NOT A PERIOD").mkdir()
        out = M.inventory(self.root, years=(2025,))
        self.assertIn("NOT A PERIOD", out["source_root_period_directories"])
        self.assertIn("NOT A PERIOD",
                      out["noncanonical_period_directory_labels_semantics_unverified"])
        self.assertTrue(out["noncanonical_directory_names_not_automatically_mapped"])
        self.assertEqual(out["period_years"]["NOT A PERIOD"]["2025"]["source_files"], 0)

    def test_chinese_named_real_parquet_cycle_is_not_dropped(self):
        name = "十五分钟 数据"
        folder = self.base / name
        folder.mkdir()
        sample = self.base / "15min" / "2025.parquet"
        import shutil
        shutil.copyfile(sample, folder / "2025.parquet")
        out = M.inventory(self.root, years=(2025,))
        self.assertIn(name, out["source_root_period_directories"])
        self.assertIn(name,
                      out["noncanonical_period_directory_labels_semantics_unverified"])
        self.assertEqual(out["period_years"][name]["2025"]["source_files"], 1)
        self.assertEqual(out["period_years"][name]["2025"][
            "source_rows_from_parquet_footers"], 1)
        self.assertFalse(out["period_years"][name]["2025"][
            "full_calendar_coverage_certified"])

    def test_root_symlink_cycle_is_not_traversed(self):
        folder = self.base / "symlink_cycle"
        try:
            folder.symlink_to(self.base / "15min", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Windows symlink creation is not permitted")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            M.inventory(self.root, years=(2025,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
