"""V2G guided seven-page UI: synthetic route/navigation and no-write checks."""
from __future__ import annotations

import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest import mock

import market_center_v2_preview as controller
import market_center_v2e_selected_ui as UI


class GuidedWorkflowWidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="v2g-synthetic-")
        self.addCleanup(self.temp.cleanup)
        module = Path(self.temp.name) / "ParquetLiveSync"
        module.mkdir()
        try:
            with mock.patch.object(
                    controller, "observe_qmt_connection",
                    side_effect=AssertionError("no automatic QMT check")), \
                 mock.patch.object(
                    controller, "inspect_recovery_prerequisites",
                    side_effect=AssertionError("no inventory on page startup")), \
                 mock.patch.object(
                    UI, "inventory_historical_versions",
                    side_effect=AssertionError("no historical scan on startup")):
                self.app = UI.MarketCenterV2SelectedUI(state_module=module)
        except tk.TclError as exc:
            if ("no display" in str(exc).lower() or
                    "couldn't connect" in str(exc).lower()):
                self.skipTest("Tk GUI is unavailable: " + str(exc))
            raise
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def test_four_large_task_entry_controls_exist(self):
        self.assertEqual(set(self.app.task_buttons),
                         {"update", "audit", "diagnose", "manage"})
        self.assertEqual(len(self.app.book.tabs()), 7)
        self.assertEqual(len(self.app.qmt_probe_buttons), 2)
        self.assertEqual(len(self.app.inventory_buttons), 2)

    def test_update_route_only_prepares_a_plan(self):
        self.app.open_workflow("update")
        self.assertEqual(self.app.mode.get(), "更新数据")
        self.assertEqual(self.app.book.index(self.app.book.select()),
                         UI.PAGE_MAP["更新 / 核验"])
        self.assertEqual(self.app.action_steps.index(
            self.app.action_steps.select()), 0)
        self.assertIn("下载及写入暂不可执行", self.app.workflow_tip.get())
        self.assertEqual(self.app.workflow_current_task, "update")

    def test_audit_route_opens_data_check_steps_without_running_audit(self):
        self.assertFalse(self.app.audit_running)
        self.app.open_workflow("audit")
        self.assertEqual(self.app.mode.get(), "数据核验")
        self.assertEqual(self.app.book.index(self.app.book.select()),
                         UI.PAGE_MAP["更新 / 核验"])
        self.assertFalse(self.app.audit_running)
        self.assertIn("只读核验", self.app.workflow_tip.get())

    def test_manual_mode_radio_switch_updates_guidance_consistently(self):
        self.assertEqual(self.app.mode.get(), "更新数据")
        self.assertIn("更新行情", self.app.workflow_tip.get())
        self.app.mode.set("数据核验")
        self.assertIn("检查数据", self.app.workflow_tip.get())
        self.app.mode.set("更新数据")
        self.assertIn("下载及写入暂不可执行",
                      self.app.workflow_tip.get())

    def test_error_and_management_routes_open_existing_pages(self):
        self.app.open_workflow("diagnose")
        self.assertEqual(self.app.book.index(self.app.book.select()),
                         UI.PAGE_MAP["故障诊断"])
        self.app.open_workflow("manage")
        self.assertEqual(self.app.book.index(self.app.book.select()),
                         UI.PAGE_MAP["数据管理"])

    def test_invalid_task_does_not_change_current_page(self):
        original = self.app.book.index(self.app.book.select())
        with self.assertRaises(ValueError):
            self.app.open_workflow("force_write")
        self.assertEqual(self.app.book.index(self.app.book.select()), original)

    def test_recommendation_button_only_navigates(self):
        self.app.recommended_task_id = "diagnose"
        self.app.follow_recommendation()
        self.assertEqual(self.app.book.index(self.app.book.select()),
                         UI.PAGE_MAP["故障诊断"])
        self.assertFalse(self.app.qmt_probe_running)
        self.assertFalse(self.app.inventory_running)

    def test_live_status_drives_recommended_task_not_hist_qmt(self):
        observed = {
            "execution_validation": "PARTIAL", "data_validation": "FAIL",
            "cross_validation": "UNVERIFIED",
            "qmt_recent_preflight": "CONNECTED",
            "stage_records": {},
        }
        with mock.patch.object(
                controller.MarketCenterV2, "refresh_overview"), \
             mock.patch.object(UI, "latest_status", return_value=observed), \
             mock.patch.object(UI, "source_info", return_value={}):
            self.app.refresh_overview()
        self.assertEqual(self.app.recommended_task_id, "diagnose")
        self.assertEqual(self.app.task_buttons["diagnose"].cget("style"),
                         "Primary.TButton")
        self.assertEqual(self.app.task_buttons["update"].cget("style"),
                         "TButton")
        self.assertIn("先看本轮故障", self.app.workflow_hint.get())

    def test_advanced_probes_are_collapsed_until_explicitly_expanded(self):
        self.assertFalse(self.app.quick_tools_shown)
        self.assertEqual(self.app.quick_tools_frame.winfo_manager(), "")
        self.app.toggle_home_tools()
        self.assertTrue(self.app.quick_tools_shown)
        self.assertEqual(self.app.quick_tools_frame.winfo_manager(), "grid")
        self.assertFalse(self.app.qmt_probe_running)
        self.assertFalse(self.app.inventory_running)
        self.app.toggle_home_tools()
        self.assertEqual(self.app.quick_tools_frame.winfo_manager(), "")

    def test_fault_raw_json_is_hidden_but_preserved_and_reopenable(self):
        self.assertFalse(self.app.fault_technical_visible)
        self.assertEqual(self.app.fault_technical_frame.winfo_manager(), "")
        self.app._set_fault_detail('{"status":"synthetic"}')
        self.app.toggle_fault_technical()
        self.assertEqual(self.app.fault_technical_frame.winfo_manager(), "pack")
        self.assertIn("synthetic", self.app.fault_detail_text.get("1.0", "end"))
        self.app.toggle_fault_technical()
        self.assertFalse(self.app.fault_technical_visible)

    def test_fault_instructions_are_four_separate_readable_steps(self):
        self.app.navigate(UI.PAGE_MAP["故障诊断"])
        steps = [label.cget("text") for label in self.app.fault_step_labels]
        self.assertEqual(
            steps,
            ["查看错误与同轮日志", "按需检查 QMT 当前连接",
             "核对代码与财务版本", "等待受控恢复入口"])
        self.assertEqual(self.app.fault_gate_frame.winfo_manager(), "")
        self.assertEqual(self.app.fault_technical_frame.winfo_manager(), "")

    def test_fault_gate_details_are_collapsed_without_triggering_probes(self):
        with mock.patch.object(
                self.app, "start_qmt_live_probe",
                side_effect=AssertionError("unexpected QMT check")), \
             mock.patch.object(
                self.app, "start_finance_inventory",
                side_effect=AssertionError("unexpected inventory")), \
             mock.patch.object(
                self.app, "start_historical_inventory",
                side_effect=AssertionError("unexpected history scan")):
            self.app.toggle_fault_gate_details()
            self.assertTrue(self.app.fault_gate_visible)
            self.assertEqual(self.app.fault_gate_frame.winfo_manager(), "pack")
            self.app.toggle_fault_gate_details()
            self.assertFalse(self.app.fault_gate_visible)
            self.assertEqual(self.app.fault_gate_frame.winfo_manager(), "")

    def test_side_navigation_clears_stale_current_goal_status(self):
        self.app.open_workflow("update")
        self.assertIn("当前目标：更新行情", self.app.status_line.get())
        self.app.navigate(UI.PAGE_MAP["故障诊断"])
        self.assertIn("当前页面：故障诊断", self.app.status_line.get())
        self.assertNotIn("当前目标：更新行情", self.app.status_line.get())
        self.app.navigate(UI.PAGE_MAP["运行总览"])
        self.assertIn("当前页面：运行总览", self.app.status_line.get())

    def test_fault_details_and_existing_write_block_remain_intact(self):
        self.app.navigate(UI.PAGE_MAP["故障诊断"])
        self.assertEqual(len(self.app.qmt_probe_buttons), 2)
        self.assertEqual(len(self.app.inventory_buttons), 2)
        self.assertEqual(len(self.app.historical_inventory_buttons), 1)
        self.assertEqual(
            str(self.app.fault_repair_disabled["state"]), "disabled")
        self.app._set_fault_detail('{"receipt":"synthetic-evidence"}')
        self.app.toggle_fault_technical()
        self.assertIn(
            "synthetic-evidence",
            self.app.fault_detail_text.get("1.0", "end"))
        self.app.toggle_fault_technical()

    def test_no_stale_scopes_or_additional_executors_created(self):
        source = inspect.getsource(UI.MarketCenterV2SelectedUI)
        for forbidden in ("subprocess.Popen", "download_financial_data2(",
                          "os.system(", "xtdata.download", "--apply"):
            self.assertNotIn(forbidden, source)
        self.assertEqual(str(self.app.fault_repair_disabled["state"]),
                         "disabled")
        self.assertIsNone(self.app.finance_inventory)
        self.assertIsNone(self.app.historical_inventory_result)

    def test_existing_seven_page_structure_and_view_features_retained(self):
        self.assertEqual(len(self.app.nav_controls), 7)
        self.assertEqual(len(self.app.action_steps.tabs()), 3)
        self.assertEqual(len(self.app.audit_split.panes()), 2)
        self.assertEqual(len(self.app.fault_split.panes()), 2)
        self.assertEqual(set(self.app.cards),
                         {"已提交最新交易日", "上次任务结果",
                          "当前安全截止", "QMT 最近预检", "财务待审"})

    def test_no_outer_home_scroll_or_auto_probing(self):
        self.assertFalse(any(isinstance(child, tk.Canvas)
                             for child in self.app.home.winfo_children()))
        self.assertFalse(self.app.qmt_probe_running)
        self.assertFalse(self.app.inventory_running)
        self.assertFalse(self.app.historical_inventory_running)


if __name__ == "__main__":
    unittest.main()
