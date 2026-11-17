"""Offline 16:30 China-market-time eligibility and schedule safety checks."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import update_market as U
import local_layout as L


class EarlyMarketEligibilityTests(unittest.TestCase):
    def test_before_1630_keeps_prior_trading_day(self):
        now = datetime(2026, 11, 17, 16, 29, tzinfo=L.UTC8)
        self.assertEqual(U.last_eligible_day(now), date(2026, 11, 16))

    def test_at_1630_includes_today_only_as_candidate(self):
        now = datetime(2026, 11, 17, 16, 30, tzinfo=L.UTC8)
        self.assertEqual(U.last_eligible_day(now), date(2026, 11, 17))

    def test_converts_japan_local_time_to_china(self):
        jst = timezone(timedelta(hours=9))
        self.assertEqual(
            U.last_eligible_day(datetime(2026, 11, 17, 17, 29, tzinfo=jst)),
            date(2026, 11, 16))
        self.assertEqual(
            U.last_eligible_day(datetime(2026, 11, 17, 17, 30, tzinfo=jst)),
            date(2026, 11, 17))

    def test_weekends_roll_back_to_last_weekday(self):
        self.assertEqual(
            U.last_eligible_day(datetime(2026, 11, 22, 18, 0, tzinfo=L.UTC8)),
            date(2026, 11, 20))

    def test_rejects_naive_datetime(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            U.last_eligible_day(datetime(2026, 11, 17, 16, 30))

    def test_afternoon_runner_is_not_an_implicit_installer(self):
        runner = (HERE / "scheduled-afternoon-update.ps1").read_text(
            encoding="utf-8")
        installer = (HERE / "install-schedule.ps1").read_text(
            encoding="utf-8")
        self.assertIn("[switch]$Apply", runner)
        self.assertIn("MARKET_1630_PREVIEW_ONLY", runner)
        self.assertIn("EIGHT_PERIODS", runner)
        self.assertIn("SECTORS", runner)
        self.assertIn("ADJUSTMENTS_ROTATING", runner)
        self.assertIn("FINANCIAL_DAILY", runner)
        self.assertNotIn("Register-ScheduledTask", runner)
        self.assertIn("READONLY_PREVIEW_WORKTREE", runner)
        self.assertIn("financial-cache-progress.json", runner)
        self.assertIn("market_update\\commits.json", runner)
        self.assertIn("[switch]$AfternoonUnified", installer)
        self.assertIn("'scheduled-afternoon-update.ps1'", installer)
        self.assertIn("AStockDataTools-QMT-Financial-Daily", installer)


if __name__ == "__main__":
    unittest.main()
