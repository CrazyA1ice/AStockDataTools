"""Autopilot desktop presentation contract: true local evidence, no execution."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import inspect
import tkinter as tk
import unittest

import market_daily_autopilot_view as V
import market_daily_autopilot_shadow as S
import market_center_v2e_selected_ui as CENTER
import market_update_dashboard as DASH


def make_report(*, finance=85, remaining=5201):
    _, ledger = {}, {}
    day = "2026-11-21"
    return {
        "status": "DAILY_AUTOPILOT_SHADOW_REPORT_NO_EXECUTION",
        "execution_health": "ROUTINE_CONTINUATION",
        "receipt_execution_status": "PARTIAL",
        "run_day": day,
        "coverage": {
            "pending_total": finance,
            "financial_today_processed": 159,
            "financial_remaining_unvisited": remaining,
        },
        "data_quality": {
            "current_run_validation": "PARTIAL",
            "cross_source_validation": "UNVERIFIED",
        },
    }


class AutopilotViewModelTests(unittest.TestCase):
    def test_normal_rotation_does_not_claim_quality_passed(self):
        view = V.presentation(make_report())
        self.assertEqual(view["level"], "ROUTINE")
        self.assertIn("原始回执 PARTIAL", view["headline"])
        self.assertIn("5201", view["coverage"])
        self.assertIn("85", view["coverage"])
        self.assertIn("UNVERIFIED", view["quality"])
        self.assertIn("未启用", view["valuation"])

    def test_warning_when_execution_fails(self):
        report = make_report()
        report["execution_health"] = "ATTENTION_REQUIRED"
        report["stage_execution_errors"] = ["FINANCIAL_DAILY_NONZERO_EXIT"]
        view = V.presentation(report)
        self.assertEqual(view["level"], "ACTION")
        self.assertIn("FINANCIAL_DAILY_NONZERO_EXIT", view["action"])

    def test_missing_quality_stays_unknown(self):
        report = make_report()
        del report["data_quality"]
        with self.assertRaises(ValueError):
            V.presentation(report)

    def test_missing_canonical_receipt_is_never_green(self):
        with TemporaryDirectory() as tmp:
            module = Path(tmp) / "ParquetLiveSync"
            module.mkdir()
            result = V.read_view(module)
        self.assertEqual(result["level"], "UNKNOWN")
        self.assertIn("未确认", result["coverage"])

    def test_invalid_negative_coverage_rejected(self):
        report = make_report(finance=-1)
        with self.assertRaises(ValueError):
            V.presentation(report)

    def test_view_only_uses_shadow_health_model(self):
        source = inspect.getsource(V)
        self.assertNotIn("xtquant", source)
        self.assertNotIn("Popen(", source)
        self.assertNotIn(".write_text(", source)
        self.assertNotIn("download_financial_data", source)

    def test_two_desktop_surfaces_share_the_same_presenter(self):
        self.assertIn("read_view", inspect.getsource(CENTER.MarketCenterV2SelectedUI))
        self.assertIn("read_view", inspect.getsource(DASH.UpdaterDashboard))


class AutopilotGuiSmokeTests(unittest.TestCase):
    def test_selected_market_center_shows_readonly_auto_health(self):
        # The state-module fixture is a real empty directory, not a cached
        # home or live financial state. No QMT access occurs in this test.
        with TemporaryDirectory() as tmp:
            module = Path(tmp) / "ParquetLiveSync"
            module.mkdir()
            try:
                with patch.object(
                    CENTER, "read_view",
                    return_value=V.presentation(make_report())
                ):
                    root = CENTER.MarketCenterV2SelectedUI(
                        state_module=module)
            except tk.TclError as exc:
                if ("display" in str(exc).lower()
                        or "couldn't connect" in str(exc).lower()):
                    self.skipTest("no GUI display")
                raise
            try:
                root.withdraw()
                self.assertIn("85", root.autopilot_coverage.get())
                self.assertIn("未启用", root.autopilot_valuation.get())
                self.assertEqual(len(root.book.tabs()), 7)
            finally:
                root.destroy()


    def test_operator_dashboard_has_same_health_summary(self):
        with TemporaryDirectory() as tmp:
            module = Path(tmp) / "ParquetLiveSync"
            work = module / "work"
            work.mkdir(parents=True)
            try:
                with patch.object(DASH, "MODULE", module), \
                     patch.object(DASH, "WORK", work), \
                     patch.object(DASH, "read_view",
                                  return_value=V.presentation(make_report())):
                    root = DASH.UpdaterDashboard()
            except tk.TclError as exc:
                if ("display" in str(exc).lower()
                        or "couldn't connect" in str(exc).lower()):
                    self.skipTest("no GUI display")
                raise
            try:
                root.withdraw()
                self.assertIn("日常续扫正常", root.autopilot_status.get())
                self.assertIn("5201", root.autopilot_coverage.get())
                self.assertIn("UNVERIFIED", root.autopilot_quality.get())
                self.assertIn("尚未启用", root.autopilot_valuation.get())
            finally:
                root.destroy()

if __name__ == "__main__":
    unittest.main()
