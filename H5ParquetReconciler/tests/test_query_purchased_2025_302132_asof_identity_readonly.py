"""Real-synthetic original Parquet 2025 SZ302132 as-of issuer identity contracts."""
import importlib.util
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "source_302132_optin_asof_identity_test",
    HERE.parent / "tools" /
    "query-purchased-2025-302132-asof-identity-readonly.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class AsOfIssuerSourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.periods = ("1min", "5min")
        self.days = (date(2025, 2, 14), date(2025, 2, 17))
        self.files = {}
        for period in self.periods:
            file = self.root / "AllCycleAStockData" / period / "2025.parquet"
            file.parent.mkdir(parents=True)
            self.files[period] = file
            self.make(period)

    def make(self, period, *, missing_last_key=False, duplicate=False):
        times = []
        for day in self.days:
            keys = sorted(M.GRID.normalized_native_keys(day, period).values())
            if period == "1min":
                keys = [M.GRID.I.day_epoch_ms(day) + 570 * 60000, *keys]
            if missing_last_key and day == self.days[-1]:
                keys.pop()
            times.extend(keys)
        if duplicate:
            times.append(times[-1])
        pq.write_table(pa.table({
            "ts": pa.array(times, type=pa.int64()),
            "symbol": ["SZ302132"] * len(times),
            "open": [10.] * len(times), "high": [11.] * len(times),
            "low": [9.] * len(times), "close": [10.5] * len(times),
            "volume": [100.] * len(times), "amount": [1000.] * len(times),
        }), self.files[period], row_group_size=60)

    def test_original_5min_source_preserved_historical_asof_code_distinct(self):
        result = M.query_bars(self.root, "5min", "2025-02-14", "2025-02-17")
        safe = result["safe_summary"]
        self.assertEqual(safe["source_matching_bars"], 96)
        self.assertEqual(safe["observed_complete_source_stockdays"], 2)
        self.assertEqual(safe["source_bars_annotated_by_asof_code"],
                         {"SZ300114": 48, "SZ302132": 48})
        self.assertEqual(result["bars"][0]["vendor_source_symbol"], "SZ302132")
        self.assertEqual(result["bars"][0]["official_symbol_asof_trading_date"],
                         "SZ300114")
        self.assertEqual(result["bars"][-1]["official_symbol_asof_trading_date"],
                         "SZ302132")
        self.assertEqual(result["bars"][0]["open"], 10.)
        self.assertFalse(safe["production_identity_mapping_activated"])
        self.assertFalse(safe["private_licensed_bar_cache_written"])
        self.assertFalse(safe["raw_ohlcva_in_safe_summary"])
        self.assertNotIn("open", safe)

    def test_keyfirst_safety_evidence_is_forwarded_not_invented(self):
        result = M.query_bars(self.root, "5min", "2025-02-17", "2025-02-17")
        safe = result["safe_summary"]
        self.assertTrue(safe["native_session_grid_checked_before_ohlcva"])
        self.assertTrue(safe["key_only_to_ohlcva_exact_key_verified"])
        self.assertTrue(safe["generic_purchased_query_budget_unchanged"])
        self.assertEqual(
            safe["physical_ohlcva_exception_scope"],
            "2025_SZ302132_only_exact_matching_rowgroups")
        self.assertEqual(safe["source_ohlcva_rows_read"], 96)
        self.assertEqual(safe["source_ohlcva_rowgroups_read"], 2)
        self.assertEqual(safe["source_ohlcva_budget"], 2250000)

    def test_missing_keyfirst_evidence_fails_closed(self):
        expected = M.KEY_FIRST.query_bars(
            self.root, "SZ302132", "5min",
            "2025-02-17", "2025-02-17")
        expected["safe_summary"].pop("native_session_grid_checked_before_ohlcva")
        with patch.object(M.KEY_FIRST, "query_bars", return_value=expected):
            with self.assertRaises(KeyError):
                M.query_bars(self.root, "5min", "2025-02-17", "2025-02-17")

    def test_original_1min_241_grid_checked_without_changing_source(self):
        file = self.files["1min"]
        before = (file.stat().st_size, file.stat().st_mtime_ns)
        result = M.query_bars(self.root, "1min", "2025-02-14", "2025-02-17")
        self.assertEqual(result["safe_summary"]["source_matching_bars"], 482)
        self.assertEqual(result["safe_summary"]["observed_complete_source_stockdays"], 2)
        self.assertEqual(before, (file.stat().st_size, file.stat().st_mtime_ns))

    def test_source_code_exception_not_allowed_by_default(self):
        with self.assertRaisesRegex(ValueError, "A-share"):
            M.Q.query_bars(self.root, "SZ302132", "5min",
                           "2025-02-17", "2025-02-17")

    def test_non_documented_302_or_bshare_never_opted_in(self):
        for symbol in ("SZ302999", "SH900901", "SZ200123", "SZ300114"):
            with self.subTest(symbol=symbol), self.assertRaisesRegex(
                    ValueError, "strictly"):
                M.Q.request_dates(
                    symbol, "5min", "2025-02-17", "2025-02-17",
                    10000, 1000, allow_2025_302132_source=True)

    def test_2026_not_supported_for_documented_vendor_exception(self):
        with self.assertRaisesRegex(ValueError, "strictly"):
            M.Q.request_dates(
                "SZ302132", "5min", "2026-02-17", "2026-02-17",
                10000, 1000, allow_2025_302132_source=True)

    def test_2025_bad_daily_and_weekly_route_rejected(self):
        for period in ("day", "week", "month", "15min"):
            with self.subTest(period=period), self.assertRaisesRegex(
                    ValueError, "only 1min/5min"):
                M.query_bars(self.root, period, "2025-02-14", "2025-02-17")

    def test_incomplete_5min_vendor_stockday_fails_not_filled(self):
        self.make("5min", missing_last_key=True)
        with self.assertRaisesRegex(ValueError, "nonstandard time keys"):
            M.query_bars(self.root, "5min", "2025-02-14", "2025-02-17")

    def test_duplicate_vendor_source_time_key_fails(self):
        self.make("5min", duplicate=True)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            M.query_bars(self.root, "5min", "2025-02-14", "2025-02-17")

    def test_no_private_market_cache_for_source_identity(self):
        with self.assertRaisesRegex(ValueError, "must not cache"):
            M.Q.query_bars(
                self.root, "SZ302132", "5min", "2025-02-17", "2025-02-17",
                local_cache=True, allow_2025_302132_source=True)

    def test_source_identity_annotations_ignore_price_units(self):
        result = M.query_bars(self.root, "5min", "2025-02-17", "2025-02-17")
        self.assertFalse(result["safe_summary"]["vendor_ohlcva_unit_certified"])

    def test_source_date_policy_only_2025(self):
        for day in ("2024-12-31", "2026-01-01"):
            with self.subTest(day=day), self.assertRaises(ValueError):
                M.official_code_asof(day)

    def test_research_permission_requires_boolean(self):
        with self.assertRaisesRegex(ValueError, "boolean"):
            M.Q.request_dates("SZ302132", "5min", "2025-02-17",
                              "2025-02-17", 1000, 100,
                              allow_2025_302132_source=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
