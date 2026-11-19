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
        self.assertNotIn("[switch]$AfternoonUnified", installer)
        self.assertIn("'scheduled-afternoon-update.ps1'", installer)
        self.assertIn("AStockDataTools-QMT-Financial-Daily", installer)
        self.assertIn("([TimeSpan]::Zero)", installer)
        self.assertNotIn("New-TimeSpan -Hours", installer)
        self.assertIn("'notify-market-update.ps1'", installer)
        self.assertIn("notify-market-update.ps1", runner)
        self.assertIn("MARKET_1630_USER_NOTIFICATION_ATTEMPTED", runner)
        self.assertIn("}finally{", runner)
        self.assertNotIn("FinanceMaxMinutes", runner)
        self.assertNotIn("Before 16:30 China market time", runner)
        # The one scheduled entry executes all four independent stages.
        sequence = ["-Label 'EIGHT_PERIODS'", "-Label 'FINANCIAL_DAILY'",
                    "-Label 'SECTORS'", "-Label 'ADJUSTMENTS_ROTATING'"]
        positions = [runner.index(token) for token in sequence]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("UNIFIED_SINGLE_RUN", runner)
        self.assertNotIn("RETRY_MARKET_ONLY", runner)
        self.assertNotIn('20:45', runner)
        self.assertNotIn("marketRetryUtc", installer)
        self.assertIn("New-ScheduledTaskTrigger -Daily -At $at", installer)
        self.assertIn("$taskExecAction=New-ScheduledTaskAction", installer)
        self.assertIn("-Action $taskExecAction", installer)
        # PowerShell variable names are case-insensitive: $action and
        # parameter $Action would otherwise be the same ValidateSet variable.
        self.assertNotIn("$action=New-ScheduledTaskAction", installer)
        self.assertNotIn("-Action $action ", installer)
        self.assertNotIn('$triggers+=', installer)
        self.assertIn("last-afternoon-unified.json", runner)
    
    def test_financial_daily_has_no_default_wall_clock_cap(self):
        importer = (HERE / "qmt_extra_financial_cache_import.py").read_text(
            encoding="utf-8")
        wrapper = (HERE / "run-qmt-financial-daily.ps1").read_text(
            encoding="utf-8")
        self.assertIn("max_minutes=0", importer)
        self.assertIn("if max_minutes else None", importer)
        self.assertNotIn("PAUSED_SCHEDULE_PROTECTION", importer)
        self.assertIn("[int]$MaxMinutes = 0", wrapper)
        self.assertIn("'FINANCIAL_DAILY'", (HERE / "scheduled-afternoon-update.ps1").read_text(
            encoding="utf-8"))



if __name__ == "__main__":
    unittest.main()
