"""Offline tests for status calculations and private log safety.

Never imports QMT, creates scheduled tasks or launches update pipelines.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

import market_update_dashboard as D


class MarketDashboardContractTests(unittest.TestCase):
    def test_last_accepted_day_is_ledger_based(self):
        state = {"periods": {"1min": {
            "2026-10": {"days": ["2026-10-13", "2026-10-31"]},
            "2026-11": {"days": ["2026-11-18", "2026-11-19"]},
        }}}
        self.assertEqual(D.accepted_minute_day(state), "2026-11-19")

    def test_empty_ledger_proves_nothing(self):
        self.assertEqual(D.accepted_minute_day({}), "")

    def test_pre_2005_china_time_cannot_target_same_day(self):
        china = timezone(timedelta(hours=8))
        x = datetime(2026, 11, 20, 19, 58, tzinfo=china)
        self.assertEqual(D.safe_refresh_limit(x).isoformat(), "2026-11-19")

    def test_2005_china_time_may_target_same_day(self):
        china = timezone(timedelta(hours=8))
        x = datetime(2026, 11, 20, 20, 5, tzinfo=china)
        self.assertEqual(D.safe_refresh_limit(x).isoformat(), "2026-11-20")

    def test_sunday_cutoff_uses_previous_friday_candidate(self):
        china = timezone(timedelta(hours=8))
        x = datetime(2026, 11, 22, 20, 10, tzinfo=china)
        self.assertEqual(D.safe_refresh_limit(x).isoformat(), "2026-11-20")

    def test_report_status_is_read_without_writing(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "last-afternoon-unified.json"
            path.write_text('{"status":"PARTIAL","market_data_writes":false}',encoding="utf-8")
            self.assertEqual(D.safe_json(path)["status"], "PARTIAL")

    def test_non_object_json_receipt_is_rejected(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "bad.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "object"):
                D.safe_json(path)

    def test_status_budget_fails_closed(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "huge.json"
            path.write_text('{"x":"long"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "budget"):
                D.safe_json(path, budget=2)

    def test_bounded_private_log_tail(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            log = root / "afternoon-20261120-200500.log"
            log.write_text("PRIVATE_A\n" + "line\n" * 100 + "FINAL_MARKER\n",
                           encoding="utf-8")
            with patch.object(D, "WORK", root):
                tail = D.log_tail(log, budget=50)
            self.assertIn("FINAL_MARKER", tail)
            self.assertNotIn("PRIVATE_A", tail)

    def test_log_reader_refuses_outside_workspace(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "work").mkdir()
            log = root / "not-in-work.log"
            log.write_text("PRIVATE", encoding="utf-8")
            with patch.object(D, "WORK", root / "work"):
                with self.assertRaisesRegex(ValueError, "outside"):
                    D.log_tail(log)

    def test_log_listing_does_not_browse_market_data(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "afternoon-20261120-200500.log").write_text(
                "synthetic\n", encoding="utf-8")
            (root / "unrelated-secret.txt").write_text(
                "private\n", encoding="utf-8")
            with patch.object(D, "WORK", root):
                self.assertEqual(len(D.private_logs()), 1)


if __name__ == "__main__":
    unittest.main()
