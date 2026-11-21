"""V2G2 bounded audit-to-review GUI contracts, temporary fixtures only."""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest import mock

import market_center_v2_preview as controller
import market_center_v2e_selected_ui as UI
from market_center_v2g2_audit_review import (
    explain_observation, summarize_readonly_report,
)


def row(code="PHYSICAL_ANOMALY_NEEDS_REVIEW"):
    return {
        "symbol": "000001.SZ", "period": "day",
        "label_day": "2026-11-19", "rows": 1,
        "physical_status": "ANOMALY_OBSERVED",
        "interpretation": code,
        "anomalies": {"synthetic_bad_time_grid": 1},
    }


def report(*rows):
    return {
        "scope": {"start": "2026-11-19", "end": "2026-11-19",
                  "stocks": ["000001.SZ"], "periods": ["day"]},
        "market_file_writes": False, "qmt_calls": 0,
        "evidence_interpretation": {
            "status": "V2B2_EVIDENCE_GATED_CANDIDATES_NOT_CERTIFIED",
            "allowed_repair_or_backfill": False,
            "source_authenticity_certified": False,
            "confirmed_missing_count": 0,
            "observations": list(rows),
        },
    }


class V2G2ReviewWidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="v2g2-synthetic-")
        self.addCleanup(self.temp.cleanup)
        module = Path(self.temp.name) / "ParquetLiveSync"
        module.mkdir()
        try:
            with mock.patch.object(
                    controller, "observe_qmt_connection",
                    side_effect=AssertionError("unexpected live QMT")), \
                 mock.patch.object(
                    controller, "inspect_recovery_prerequisites",
                    side_effect=AssertionError("unexpected finance inventory")), \
                 mock.patch.object(
                    UI, "inventory_historical_versions",
                    side_effect=AssertionError("unexpected finance history")):
                self.app = UI.MarketCenterV2SelectedUI(state_module=module)
        except tk.TclError as exc:
            if ("no display" in str(exc).lower()
                    or "couldn't connect" in str(exc).lower()):
                self.skipTest("Tk not accessible: " + str(exc))
            raise
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def test_audit_has_three_step_guidance_and_no_auto_write(self):
        self.assertIn("步骤 1/3", self.app.audit_flow_title.get())
        self.assertIn("步骤 2/3", self.app.audit_selected_title.get())
        self.assertEqual(
            str(self.app.audit_repair_disabled["state"]), "disabled")
        self.assertEqual(
            str(self.app.audit_copy_review["state"]), "disabled")
        self.assertEqual(len(self.app.audit_split.panes()), 2)

    def test_completion_synthesizes_summary_without_new_scan(self):
        raw = report(row(), row("NO_ROWS_CALENDAR_AND_ELIGIBILITY_UNKNOWN"))
        self.app.audit_raw_report = json.dumps(raw)
        with mock.patch.object(controller.MarketCenterV2, "_poll_audit"):
            self.app._poll_audit()
        self.assertIn("1条行情异常观察", self.app.audit_flow_title.get())
        self.assertIn("已确认缺失：0", self.app.audit_flow_next.get())
        self.assertEqual(
            str(self.app.audit_repair_disabled["state"]), "disabled")

    def test_running_new_scan_clears_old_review_permission(self):
        self.app.audit_running = True
        self.app.audit_copy_review.configure(state="normal")
        self.app.audit_selected_review = {
            "can_download": False, "can_repair": False}
        try:
            with mock.patch.object(controller.MarketCenterV2, "_poll_audit"):
                self.app._poll_audit()
            self.assertIsNone(self.app.audit_selected_review)
            self.assertEqual(
                str(self.app.audit_copy_review["state"]), "disabled")
            self.assertIn("正在进行", self.app.audit_flow_title.get())
        finally:
            self.app.audit_running = False

    def test_physical_anomaly_row_shows_distinct_market_advice(self):
        observed = row()
        item = self.app.audit_table.insert(
            "", "end", values=("day", "000001.SZ", "2026-11-19",
                               1, "ANOMALY_OBSERVED", "物理异常待复核"))
        self.app.audit_table_rows[item] = observed
        self.app.audit_table.selection_set(item)
        self.app._select_audit_row()
        self.assertIn("行情物理异常待复核",
                      self.app.audit_selected_title.get())
        self.assertIn("权威来源",
                      self.app.audit_selected_next.get())
        self.assertIn("步骤 3/3", self.app.audit_selected_next.get())
        self.assertEqual(str(self.app.audit_copy_review["state"]), "normal")

    def test_missing_data_case_does_not_enable_auto_backfill(self):
        observed = row("MISSING_CANDIDATE_SOURCE_AUTHENTICITY_UNVERIFIED")
        item = self.app.audit_table.insert("", "end", values=(
            "day", "000001.SZ", "2026-11-19", 0, "NO_ROWS_OBSERVED", "疑似缺失"))
        self.app.audit_table_rows[item] = observed
        self.app.audit_table.selection_set(item)
        self.app._select_audit_row()
        self.assertIn("疑似行情缺失", self.app.audit_selected_title.get())
        self.assertIn("候选缺失", self.app.audit_selected_next.get())
        self.assertEqual(str(self.app.audit_repair_disabled["state"]), "disabled")

    def test_copy_checklist_never_invokes_qmt_and_contains_no_apply(self):
        observed = row()
        item = self.app.audit_table.insert(
            "", "end", values=("day", "000001.SZ", "2026-11-19",
                               1, "ANOMALY_OBSERVED", "物理异常待复核"))
        self.app.audit_table_rows[item] = observed
        self.app.audit_table.selection_set(item)
        recorded = []
        with mock.patch.object(
                self.app, "clipboard_clear", return_value=None), \
             mock.patch.object(
                self.app, "clipboard_append",
                side_effect=lambda value: recorded.append(value)), \
             mock.patch.object(self.app, "start_qmt_live_probe",
                               side_effect=AssertionError("unexpected probe")), \
             mock.patch.object(self.app, "start_finance_inventory",
                               side_effect=AssertionError("unexpected inventory")):
            self.app.copy_selected_audit_review()
        self.assertEqual(len(recorded), 1)
        self.assertIn("只读复核清单", recorded[0])
        self.assertIn("禁止自动下载", recorded[0])
        self.assertNotIn("--apply", recorded[0])

    def test_unknown_selection_never_creates_review_permission(self):
        item = self.app.audit_table.insert(
            "", "end", values=("day", "000001.SZ", "2026-11-19",
                               0, "NO_ROWS_OBSERVED", "未知状态"))
        self.app.audit_table_rows[item] = row("CERTIFIED_DOWNLOAD_MISSING")
        self.app.audit_table.selection_set(item)
        self.app._select_audit_row()
        self.assertIsNone(self.app.audit_selected_review)
        self.assertEqual(str(self.app.audit_copy_review["state"]), "disabled")

    def test_safe_return_to_audit_configuration_reuses_existing_wizard(self):
        self.app.open_workflow("audit")
        self.assertEqual(self.app.mode.get(), "数据核验")
        self.assertEqual(self.app.book.index(self.app.book.select()),
                         UI.PAGE_MAP["更新 / 核验"])
        self.assertEqual(self.app.action_steps.index(
            self.app.action_steps.select()), 0)
        self.assertEqual(str(self.app.audit_repair_disabled["state"]),
                         "disabled")

    def test_original_audit_reader_and_backend_limits_are_unchanged(self):
        # V2G3 adds a read-only committed-day bound, but must still
        # delegate actual guarded scans to the existing controller.
        self.assertIn(
            "super().run_readonly_audit()",
            inspect.getsource(
                UI.MarketCenterV2SelectedUI.run_readonly_audit))
        self.assertNotIn(
            "audited_query(",
            inspect.getsource(
                UI.MarketCenterV2SelectedUI.run_readonly_audit))
        self.assertEqual(len(self.app.qmt_probe_buttons), 2)
        self.assertEqual(len(self.app.inventory_buttons), 2)
        source = inspect.getsource(UI.MarketCenterV2SelectedUI._poll_audit)
        self.assertIn("super()._poll_audit()", source)
        self.assertNotIn("audited_query(", source)
        self.assertNotIn("subprocess.Popen", source)


if __name__ == "__main__":
    unittest.main()
