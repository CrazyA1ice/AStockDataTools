"""2025 purchased minute source-only index/grid integration regression tests.

Constructs real synthetic 2025 1m/5m Parquet with only ts and symbol
columns; cheap blank H5 paths are metadata-only snapshot sources, not data.
No licensed market file is read or modified.
"""
import contextlib
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "verified_2025_purchased_minute_source_grid",
    HERE.parent / "tools" / "audit-purchased-2025-minute-source-grid-readonly.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class Purchased2025MinuteGrid(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / "private-index-store"
        self.month = "2025-01"
        self.day = date(2025, 1, 2)
        (self.root / "HikyuuData").mkdir()
        for period in M.PERIODS:
            (self.root / "HikyuuData" / ("sh_" + period + ".h5")).touch()
            (self.root / "AllCycleAStockData" / period / "2025").mkdir(
                parents=True)
        self.symbol = "SH600000"

    def source(self, *, missing_one=False, different_stock_set=False,
               duplicate=False):
        for period in M.PERIODS:
            keys = sorted(M.D.normalized_native_keys(self.day, period).values())
            if period == "1min":
                keys = [M.I.day_epoch_ms(self.day) + 570 * 60000, *keys]
                if missing_one:
                    keys.pop()
            symbols = [self.symbol] * len(keys)
            if period == "5min" and different_stock_set:
                keys = [*keys, *keys]
                symbols = [*symbols, *(["SZ000001"] * (len(keys) // 2))]
            if period == "1min" and duplicate:
                keys.append(keys[-1])
                symbols.append(self.symbol)
            path = self.root / "AllCycleAStockData" / period / "2025" / "input.parquet"
            pq.write_table(pa.table({
                "ts": pa.array(keys, type=pa.int64()),
                "symbol": symbols}), path)

    @contextlib.contextmanager
    def private(self):
        with patch.object(M.I, "STORE", self.store):
            yield

    def test_full_grid_both_periods_and_index_reuse(self):
        self.source()
        sources = list((self.root / "AllCycleAStockData").rglob("*.parquet"))
        before = [(x.stat().st_size, x.stat().st_mtime_ns) for x in sources]
        with self.private():
            first = M.inspect(self.root, self.month, allow_build=True)
            second = M.inspect(self.root, self.month, allow_build=False)
        self.assertEqual(first["private_indexes_created"], 1)
        self.assertEqual(second["existing_indexes_reused"], 1)
        self.assertEqual(first["periods"]["1min"]["keys"], 241)
        self.assertEqual(first["periods"]["5min"]["keys"], 48)
        self.assertTrue(first["complete_time_grid_for_every_observed_stockday"])
        self.assertTrue(first["same_stock_symbols_in_both_periods_on_each_date"])
        self.assertIn("2025-01-01",
                      first["weekday_dates_without_purchased_source_evidence"])
        self.assertFalse(first["independent_exchange_calendar_checked"])
        self.assertFalse(first["full_exchange_calendar_coverage_certified"])
        self.assertEqual(first["purchased_market_bars_copied"], 0)
        self.assertFalse(first["new_market_parquet_or_h5_files_written"])
        self.assertEqual(before, [(x.stat().st_size, x.stat().st_mtime_ns)
                                  for x in sources])

    def test_incomplete_one_minute_stockday_is_reported_not_filled(self):
        self.source(missing_one=True)
        with self.private():
            out = M.inspect(self.root, self.month, allow_build=True)
        self.assertFalse(out["complete_time_grid_for_every_observed_stockday"])
        self.assertEqual(out["periods"]["1min"]["missing_expected_keys"], 1)
        self.assertEqual(out["periods"]["1min"]["nonstandard_stockdays"], 1)
        self.assertTrue(out["same_stock_symbols_in_both_periods_on_each_date"])

    def test_stockday_set_difference_reported(self):
        self.source(different_stock_set=True)
        with self.private():
            out = M.inspect(self.root, self.month, allow_build=True)
        self.assertFalse(out["same_stock_symbols_in_both_periods_on_each_date"])
        self.assertEqual(out["cross_period"][
            "day_with_different_1min_5min_security_sets"], 1)
        self.assertEqual(out["periods"]["5min"]["stockdays"], 2)

    def test_missing_source_index_fail_closed_without_build_flag(self):
        self.source()
        with self.private():
            with self.assertRaisesRegex(ValueError, "Unindexed"):
                M.inspect(self.root, self.month, allow_build=False)
        self.assertFalse(self.store.exists())

    def test_duplicate_source_minute_key_fails_index_build(self):
        self.source(duplicate=True)
        with self.private():
            with self.assertRaisesRegex(ValueError,
                                        "Duplicate purchased minute key"):
                M.inspect(self.root, self.month, allow_build=True)
        self.assertFalse(list(self.store.glob("*.sqlite")))

    def test_only_2025_month_permitted(self):
        for bad in ("2024-12", "2026-01", "2025-00", "2025-13", "x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                M._month(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
