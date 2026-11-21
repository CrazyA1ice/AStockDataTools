"""V2G3 ledger-bounded as-of extension, with old default freeze preserved."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest import mock

import market_center_v2_readonly_audit as A
import market_center_v2_audit_cli as CLI
import market_center_v2_preview as base
import market_center_v2e_selected_ui as UI


CN = timezone(timedelta(hours=8))
CROSSING_DATE = datetime(2026, 11, 21, 9, 30, tzinfo=CN)


class AcceptedAsOfModelTests(unittest.TestCase):
    def test_original_default_frozen_day_is_unchanged(self):
        self.assertEqual(A.read_only_ceiling(), date(2026, 11, 19))
        with self.assertRaises(A.AuditBlocked):
            A._validate_scope("2026-11-20", "2026-11-20",
                              ["000001.SZ"], ["day"])

    def test_committed_yesterday_can_be_read_only_bounded(self):
        self.assertEqual(
            A.read_only_ceiling("2026-11-20", now=CROSSING_DATE),
            date(2026, 11, 20))
        lo, hi, codes = A._validate_scope(
            "2026-11-20", "2026-11-20",
            ["000001.SZ", "600519.SH"], ["day"],
            accepted_asof="2026-11-20")
        self.assertEqual(hi, date(2026, 11, 20))
        self.assertEqual(len(codes), 2)

    def test_same_day_is_denied_even_after_2005(self):
        today_late = datetime(2026, 11, 20, 20, 30, tzinfo=CN)
        with self.assertRaisesRegex(
                A.AuditBlocked, "before_china_today"):
            A.read_only_ceiling("2026-11-20", now=today_late)

    def test_future_commit_claim_is_denied(self):
        for claimed in ("2026-11-21", "2026-11-22", "2027-01-01"):
            with self.subTest(claimed=claimed):
                with self.assertRaises(A.AuditBlocked):
                    A.read_only_ceiling(claimed, now=CROSSING_DATE)

    def test_invalid_ledger_day_fails_closed(self):
        for claim in ("未证明", "20261120", "2026-11-31", "", "2026-1-1"):
            with self.subTest(claim=claim):
                with self.assertRaises(A.AuditBlocked):
                    A.read_only_ceiling(claim, now=CROSSING_DATE)

    def test_extension_never_bypasses_one_month_or_twenty_stock_bound(self):
        with self.assertRaises(A.AuditBlocked):
            A._validate_scope("2026-10-01", "2026-11-20",
                              ["000001.SZ"], ["day"],
                              accepted_asof="2026-11-20")
        with self.assertRaises(A.AuditBlocked):
            A._validate_scope("2026-11-20", "2026-11-20",
                              [f"{i:06d}.SZ" for i in range(21)], ["day"],
                              accepted_asof="2026-11-20")

    def test_old_start_and_invalid_period_still_fail(self):
        with self.assertRaises(A.AuditBlocked):
            A._validate_scope("2026-11-20", "2026-11-19",
                              ["000001.SZ"], ["day"],
                              accepted_asof="2026-11-20")
        with self.assertRaises(A.AuditBlocked):
            A._validate_scope("2026-11-20", "2026-11-20",
                              ["000001.SZ"], ["fake"],
                              accepted_asof="2026-11-20")

    def test_cli_default_has_no_accepted_asof_argument_or_flag(self):
        self.assertIsNone(CLI.audited_query.__kwdefaults__["accepted_asof"])
        from inspect import getsource
        self.assertNotIn('"--accepted-asof"', getsource(CLI.main))

    def test_explicit_extension_is_still_guarded_and_has_no_extra_io(self):
        @contextmanager
        def guard():
            yield
        observation = {
            "status": "V2B_BOUNDED_READONLY_OBSERVATION_NOT_CERTIFIED",
            "allowed_market_write": False,
            "scope": {"start": "2026-11-20", "end": "2026-11-20",
                      "stocks": ["000001.SZ"], "periods": ["day"]},
            "observations": [],
        }
        with mock.patch.object(CLI, "shared_market_read_guard", guard), \
             mock.patch.object(CLI, "_read_budget_seconds", return_value=45.0), \
             mock.patch.object(CLI, "survey", return_value=observation) as survey, \
             mock.patch.object(CLI, "classify", return_value={
                 "status": "V2B2_EVIDENCE_GATED_CANDIDATES_NOT_CERTIFIED"
             }):
            result = CLI.audited_query(
                root=Path("C:/synthetic/AllCycleAStockData"),
                start="2026-11-20", end="2026-11-20",
                symbols=["000001.SZ"], periods=["day"],
                explicit_readonly=True, accepted_asof="2026-11-20")
            self.assertEqual(
                survey.call_args.kwargs["accepted_asof"], "2026-11-20")
            self.assertTrue(survey.call_args.kwargs["explicit_readonly"])
            self.assertIn("evidence_interpretation", result)


class AcceptedAsOfWidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="v2g3-asof-")
        self.addCleanup(self.temp.cleanup)
        status = Path(self.temp.name) / "ParquetLiveSync"
        status.mkdir()
        try:
            self.app = UI.MarketCenterV2SelectedUI(state_module=status)
        except tk.TclError as exc:
            if ("no display" in str(exc).lower()
                    or "couldn't connect" in str(exc).lower()):
                self.skipTest("Tk GUI not available: " + str(exc))
            raise
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def test_missing_commit_falls_back_to_original_frozen_day(self):
        chosen = self.app._sync_committed_readonly_ceiling({})
        self.assertEqual(chosen, date(2026, 11, 19))
        self.assertIsNone(self.app.audit_accepted_asof)
        self.assertIn("2026-11-19", self.app.audit_ceiling_note.get())

    def test_verified_ledger_candidate_shows_november_twentieth(self):
        chosen = self.app._sync_committed_readonly_ceiling({
            "last_accepted_trading_day": "2026-11-20"})
        self.assertEqual(chosen, date(2026, 11, 20))
        self.assertEqual(self.app.audit_accepted_asof, "2026-11-20")
        self.assertIn("2026-11-20", self.app.audit_ceiling_note.get())
        self.assertIn("不证明行情完整", self.app.audit_ceiling_note.get())

    def test_bad_or_current_day_from_ledger_is_ignored(self):
        for claimed in ("未证明", "2027-03-01", "2026-11-31"):
            with self.subTest(claim=claimed):
                chosen = self.app._sync_committed_readonly_ceiling({
                    "last_accepted_trading_day": claimed})
                self.assertEqual(chosen, date(2026, 11, 19))
                self.assertIsNone(self.app.audit_accepted_asof)

    def test_start_reads_ledger_again_and_delegates_to_old_guarded_runner(self):
        with mock.patch.object(
                UI, "latest_status",
                return_value={"last_accepted_trading_day": "2026-11-20"}), \
             mock.patch.object(base.MarketCenterV2, "run_readonly_audit",
                               return_value=None) as runner:
            self.app.run_readonly_audit()
        runner.assert_called_once_with()
        self.assertEqual(self.app.audit_accepted_asof, "2026-11-20")
        self.assertFalse(self.app.audit_running)
        self.assertEqual(str(self.app.audit_repair_disabled["state"]),
                         "disabled")


if __name__ == "__main__":
    unittest.main()
