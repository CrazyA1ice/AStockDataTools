"""Read-only eight purchased-cycle research query contracts.

Synthetic original Parquet has real ts/symbol/OHLCVA row data but no
licensed market content. Native 1m/5m H5 fallback is mocked in routing
tests; prior exact-key/SHA suite remains the authoritative minute gate.
"""
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "purchased_primary_all_cycle_query_tests",
    HERE.parent / "tools" / "query-purchased-primary-all-eight-cycles-readonly.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
UTC8 = timezone(timedelta(hours=8))


class AllCycleRealSyntheticParquetTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.pa, self.pq = pa, pq
        self.working = tempfile.TemporaryDirectory()
        self.addCleanup(self.working.cleanup)
        self.root = Path(self.working.name)
        self.symbol = "SH600000"
        self.direct = ("15min", "30min", "60min", "day", "week", "month")
        source = self.root / "AllCycleAStockData"
        for period in self.direct:
            (source / period).mkdir(parents=True)
            for year in (2025, 2026):
                hh, mm = (8, 0) if period in ("day", "week", "month") else (9, 30)
                dt = datetime(year, 9, 30, hh, mm, tzinfo=UTC8)
                self.pq.write_table(self.pa.table({
                    "ts": self.pa.array([int(dt.timestamp()*1000)], type=pa.int64()),
                    "symbol": [self.symbol],
                    "open": [10.0], "high": [11.0], "low": [9.0],
                    "close": [10.5], "volume": [200.0], "amount": [1000.0],
                }), source / period / (str(year) + ".parquet"))

    def test_six_real_synthetic_direct_cycles_for_two_years(self):
        for period in self.direct:
            for year in (2025, 2026):
                with self.subTest(period=period, year=year):
                    d = str(year) + "-09-30"
                    result = M.query_bars(self.root, self.symbol, period, d, d)
                    self.assertEqual(result["safe_summary"]["matching_bar_count"], 1)
                    self.assertEqual(result["safe_summary"]["bars_by_source"],
                                     {"purchased_parquet": 1})
                    self.assertEqual(result["bars"][0]["open"], 10.0)
                    self.assertEqual(result["bars"][0]["value_source"],
                                     "purchased_parquet")
                    self.assertFalse(result["safe_summary"]["vendor_physical_units_certified"])
                    self.assertFalse(result["safe_summary"]["production_query_activated"])

    def test_week_and_month_preserve_raw_0800_timestamp(self):
        for period in ("week", "month"):
            result = M.query_bars(self.root, self.symbol, period,
                                  "2025-09-30", "2025-09-30")
            self.assertEqual(result["bars"][0]["source_beijing_time"],
                             "2025-09-30 08:00")
            self.assertTrue(result["safe_summary"][
                "weekly_monthly_labels_are_raw_source_dates"])

    def test_no_cycle_requires_h5_for_direct_purchased_query(self):
        with patch.object(M.MINUTE, "query_bars",
                          side_effect=AssertionError("H5 unavailable")):
            result = M.query_bars(self.root, self.symbol, "15min",
                                  "2025-09-30", "2025-09-30")
        self.assertEqual(len(result["bars"]), 1)

    def test_no_cycle_automatically_generates_missing_adjusted_bars(self):
        result = M.query_bars(self.root, self.symbol, "month",
                              "2025-09-01", "2025-09-29")
        self.assertEqual(result["bars"], [])
        self.assertFalse(result["safe_summary"][
            "corporate_action_adjustments_certified"])

    def test_h5_fallback_must_be_rejected_for_nonminute_cycles(self):
        with self.assertRaisesRegex(ValueError, "only for"):
            M.query_bars(self.root, self.symbol, "15min",
                         "2025-09-30", "2025-09-30",
                         allow_verified_private_h5=True)

    def test_adjustment_factor_is_not_a_kline_period(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            M.query_bars(self.root, self.symbol, "复权因子",
                         "2025-09-30", "2025-09-30")

    def test_no_parquet_original_source_modified(self):
        file = self.root / "AllCycleAStockData" / "15min" / "2025.parquet"
        before = (file.stat().st_size, file.stat().st_mtime_ns)
        M.query_bars(self.root, self.symbol, "15min",
                     "2025-09-30", "2025-09-30")
        after = (file.stat().st_size, file.stat().st_mtime_ns)
        self.assertEqual(before, after)


class ExistingMinuteAdapterContracts(unittest.TestCase):
    def setUp(self):
        self.root = Path("D:/stock")
        self.d = "2026-10-13"

    def test_one_five_minute_routes_to_original_verified_engine(self):
        for period in ("1min", "5min"):
            with self.subTest(period=period):
                response = {
                    "bars": [{
                        "symbol": "SH600000", "period": period,
                        "source_timestamp_ms": 1791860000000,
                        "value_source": "h5_only_complete_stockday",
                    }],
                    "safe_summary": {
                        "bars_by_source": {"verified_private_h5_gap": 1},
                    },
                }
                with patch.object(M.MINUTE, "query_bars", return_value=response) as query:
                    out = M.query_bars(
                        self.root, "SH600000", period, self.d, self.d,
                        allow_verified_private_h5=True)
                self.assertEqual(out["safe_summary"]["matching_bar_count"], 1)
                self.assertEqual(out["safe_summary"]["bars_by_source"],
                                 {"verified_private_h5_gap": 1})
                self.assertTrue(query.call_args.kwargs["allow_verified_private_h5"])

    def test_missing_minute_index_exception_not_downgraded_to_empty(self):
        with patch.object(M.MINUTE, "query_bars",
                          side_effect=ValueError("No index")):
            with self.assertRaisesRegex(ValueError, "No index"):
                M.query_bars(self.root, "SH600000", "1min", self.d, self.d)

    def test_purchased_minute_routes_without_h5_permission_by_default(self):
        response = {"bars": [], "safe_summary": {"bars_by_source": {}}}
        with patch.object(M.MINUTE, "query_bars", return_value=response) as query:
            out = M.query_bars(self.root, "SH600000", "5min", self.d, self.d)
        self.assertFalse(query.call_args.kwargs["allow_verified_private_h5"])
        self.assertEqual(out["safe_summary"]["matching_bar_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
