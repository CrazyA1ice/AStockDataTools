"""V2-C synthetic, no-network minute-label comparison tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import market_center_v2_minute_grid as G
import market_center_v2_readonly_audit as A

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = pq = None

CN = timezone(timedelta(hours=8))
DAY = "2026-11-19"


def milliseconds(hour, minute, second=0):
    return int(datetime(2026, 11, 19, hour, minute, second,
                        tzinfo=CN).timestamp() * 1000)


def stamps(period, profile):
    return {milliseconds(x // 60, x % 60) for x in
            G._expected(period, profile)}


class MinuteLabelGateTests(unittest.TestCase):
    def test_all_five_periods_have_two_120min_sessions(self):
        self.assertEqual(set(G.PERIOD_MINUTES),
                         {"1min", "5min", "15min", "30min", "60min"})
        for period, width in G.PERIOD_MINUTES.items():
            with self.subTest(period=period):
                for profile in ("OPEN", "CLOSE"):
                    self.assertEqual(len(G._expected(period, profile)), 240 // width)

    def test_exact_close_labels_still_not_certified(self):
        for period in G.PERIOD_MINUTES:
            with self.subTest(period=period):
                observed = stamps(period, "CLOSE")
                result = G.inspect_minute_labels(
                    period=period, day=DAY, timestamps_ms=observed)
                self.assertEqual(result["candidate_profile"], "CLOSE")
                self.assertEqual(result["candidate_missing_labels"], 0)
                self.assertEqual(result["candidate_extra_labels"], 0)
                self.assertFalse(result["minute_label_complete_certified"])
                self.assertFalse(result["allowed_to_backfill"])

    def test_exact_open_labels_still_not_certified(self):
        for period in G.PERIOD_MINUTES:
            with self.subTest(period=period):
                result = G.inspect_minute_labels(
                    period=period, day=DAY,
                    timestamps_ms=stamps(period, "OPEN"))
                self.assertEqual(result["candidate_profile"], "OPEN")
                self.assertFalse(result["grid_profile_source_certified"])

    def test_239_not_automatically_proved_missing(self):
        observed = stamps("1min", "CLOSE")
        observed.remove(milliseconds(9, 31))
        self.assertEqual(len(observed), 239)
        result = G.inspect_minute_labels(
            period="1min", day=DAY, timestamps_ms=observed)
        self.assertEqual(result["candidate_profile"], "CLOSE")
        self.assertEqual(result["candidate_missing_labels"], 1)
        self.assertEqual(result["missing_sample"], ["09:31"])
        self.assertFalse(result["minute_label_complete_certified"])
        self.assertFalse(result["allowed_to_backfill"])

    def test_241_has_extra_hypothesis_label_but_no_repair(self):
        observed = stamps("1min", "CLOSE")
        observed.add(milliseconds(9, 30))
        result = G.inspect_minute_labels(
            period="1min", day=DAY, timestamps_ms=observed)
        self.assertEqual(result["candidate_profile"], "CLOSE")
        self.assertEqual(result["candidate_extra_labels"], 1)
        self.assertIn("09:30", result["extra_sample"])
        self.assertFalse(result["allowed_to_backfill"])

    def test_outside_continuous_session_is_candidate_only(self):
        result = G.inspect_minute_labels(
            period="1min", day=DAY, timestamps_ms={
                milliseconds(9, 25), milliseconds(9, 31),
                milliseconds(15, 0)})
        self.assertEqual(result["outside_continuous_sessions_count"], 1)
        self.assertEqual(result["status"],
                         "TIME_LABEL_PROFILE_CANDIDATE_NOT_CERTIFIED")
        self.assertFalse(result["minute_label_complete_certified"])

    def test_midday_label_cannot_be_accepted_as_continuous_trading(self):
        result = G.inspect_minute_labels(
            period="5min", day=DAY, timestamps_ms={
                milliseconds(12, 10), milliseconds(9, 35)})
        self.assertEqual(result["outside_continuous_sessions_count"], 1)
        self.assertFalse(result["allowed_to_backfill"])

    def test_non_minute_aligned_label_reported(self):
        result = G.inspect_minute_labels(
            period="1min", day=DAY, timestamps_ms={
                milliseconds(9, 31, 32)})
        self.assertEqual(result["off_minute_boundary_count"], 1)
        self.assertFalse(result["grid_profile_source_certified"])

    def test_ambiguous_open_close_keeps_profile_unknown(self):
        result = G.inspect_minute_labels(
            period="1min", day=DAY, timestamps_ms={
                milliseconds(10, 0)})
        self.assertEqual(result["status"],
                         "TIME_LABEL_PROFILE_AMBIGUOUS_UNCERTIFIED")
        self.assertIsNone(result["candidate_missing_labels"])
        self.assertIsNone(result["candidate_profile"])

    def test_no_rows_is_not_full_day_gap(self):
        result = G.inspect_minute_labels(
            period="1min", day=DAY, timestamps_ms=set())
        self.assertEqual(result["status"],
                         "NO_MINUTE_ROWS_EXPECTATION_NOT_ESTABLISHED")
        self.assertIsNone(result["candidate_missing_labels"])
        self.assertFalse(result["allowed_to_backfill"])

    def test_wrong_day_or_nonint_rejected(self):
        for stamps_input in ({milliseconds(9, 31),
                              milliseconds(9, 31) + 86_400_000},
                             {1.2}, {"09:31"}):
            with self.subTest(stamps_input=stamps_input):
                with self.assertRaises(G.GridScopeError):
                    G.inspect_minute_labels(
                        period="1min", day=DAY, timestamps_ms=stamps_input)

    def test_duplicates_and_oversized_scope_fail_closed(self):
        with self.assertRaisesRegex(G.GridScopeError, "duplicate"):
            G.inspect_minute_labels(
                period="1min", day=DAY,
                timestamps_ms=[milliseconds(9, 31)] * 2)
        with self.assertRaisesRegex(G.GridScopeError, "bounded"):
            G.inspect_minute_labels(
                period="1min", day=DAY,
                timestamps_ms=list(range(513)))

    def test_no_write_or_qmt_calls_in_pure_gate(self):
        import inspect
        text = inspect.getsource(G)
        for forbidden in ("xtquant", "download_history", "write_table",
                          "os.replace", "subprocess.Popen"):
            self.assertNotIn(forbidden, text)


@unittest.skipIf(pa is None, "pyarrow is required for synthetic Parquet test")
class MinuteAuditIntegrationTests(unittest.TestCase):
    def test_readonly_day_period_does_not_generate_minute_candidates(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "AllCycleAStockData"
            for period in A.PERIODS:
                (root / period).mkdir(parents=True, exist_ok=True)
            result = A.survey(
                root=root, start=DAY, end=DAY,
                symbols=["000001.SZ"], periods=["day"],
                explicit_readonly=True)
            self.assertEqual(result["minute_grid_observations"], [])
            self.assertTrue(result["minute_grid_is_comparison_only"])

    def test_readonly_one_stock_one_day_minute_grid_is_observational(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "AllCycleAStockData"
            for period in A.PERIODS:
                (root / period).mkdir(parents=True, exist_ok=True)
            times = [milliseconds(9, 31), milliseconds(15, 0)]
            table = pa.table({
                "ts": pa.array(times, type=pa.int64()),
                "symbol": pa.array(["SZ000001"] * 2, type=pa.string()),
                **{x: pa.array([10.0, 10.0], type=pa.float64())
                   for x in A.REQUIRED[2:]},
            })
            path = root / "1min" / "2026-11.parquet"
            pq.write_table(table, path)
            before = path.read_bytes()
            result = A.survey(
                root=root, start=DAY, end=DAY,
                symbols=["000001.SZ"], periods=["1min"],
                explicit_readonly=True)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(result["qmt_calls"], 0)
            self.assertFalse(result["market_file_writes"])
            self.assertEqual(result["observations"][0]["rows"], 2)
            detail = result["minute_grid_observations"][0]
            self.assertEqual(detail["symbol"], "000001.SZ")
            self.assertEqual(detail["candidate_profile"], "CLOSE")
            self.assertEqual(detail["candidate_missing_labels"], 238)
            self.assertFalse(detail["minute_label_complete_certified"])
            self.assertFalse(detail["allowed_to_backfill"])


if __name__ == "__main__":
    unittest.main()
