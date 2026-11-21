"""V2E seven-page visual port + latest V2-D2C controller integration contracts.

All tests are synthetic. GUI tests use temporary empty status folders.
Never start QMT, download financial data or write live Parquet / progress.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest import mock

import market_center_v2_preview as controller
import market_center_v2e_selected_ui as visual


class V2EBackendPreservationTests(unittest.TestCase):
    def test_exact_seven_selected_pages_and_original_user_layouts(self):
        self.assertEqual(
            tuple((page[0], page[2]) for page in visual.PAGES),
            (("运行总览", "A"), ("更新 / 核验", "B"),
             ("核验结果", "B"), ("故障诊断", "B"),
             ("运行日志", "B"), ("数据管理", "A"),
             ("高级设置", "A")))

    def test_current_v2d2a_connection_handler_is_inherited_unchanged(self):
        self.assertIs(
            visual.MarketCenterV2SelectedUI.start_qmt_live_probe,
            controller.MarketCenterV2.start_qmt_live_probe)

    def test_current_v2d2b_code_snapshot_inventory_is_inherited(self):
        self.assertIs(
            visual.MarketCenterV2SelectedUI.start_finance_inventory,
            controller.MarketCenterV2.start_finance_inventory)

    def test_safe_resume_clipboard_and_same_run_log_handler_are_inherited(self):
        self.assertIs(
            visual.MarketCenterV2SelectedUI.copy_finance_resume_preview,
            controller.MarketCenterV2.copy_finance_resume_preview)
        self.assertIs(
            visual.MarketCenterV2SelectedUI.show_selected_fault_log,
            controller.MarketCenterV2.show_selected_fault_log)

    def test_history_scope_only_invoked_by_explicit_control_not_startup(self):
        startup = inspect.getsource(visual.MarketCenterV2SelectedUI.make_widgets)
        method = inspect.getsource(
            visual.MarketCenterV2SelectedUI.start_historical_inventory)
        self.assertIn("command=self.start_historical_inventory", startup
                      + inspect.getsource(visual.MarketCenterV2SelectedUI.build_fault_page))
        self.assertNotIn("inventory_historical_versions(", startup)
        self.assertIn("inventory_historical_versions(", method)
        self.assertIn("threading.Thread(", method)
        self.assertIn("can_execute", inspect.getsource(
            visual.MarketCenterV2SelectedUI._poll_historical_inventory)
            + inspect.getsource(visual.inventory_historical_versions))

    def test_interface_contains_no_automatic_market_update_path(self):
        ui = inspect.getsource(visual.MarketCenterV2SelectedUI)
        self.assertNotIn("subprocess.Popen", ui)
        self.assertNotIn("download_financial_data2(", ui)
        self.assertNotIn("xtdata.download", ui)
        self.assertNotIn("--apply", ui)
        self.assertIn('state="disabled"', ui)

    def test_current_backend_has_actual_nonexecuting_software_recovery_gates(self):
        import market_center_v2_qmt_live as gates
        checked = gates.outstanding_resume_gates({
            "status": "PREVIEW_CHECKS_PASSED_EXECUTION_STILL_DISABLED",
            "allowed_to_execute": False, "blockers": [],
        })
        self.assertEqual(len(checked), 5)
        self.assertEqual([x["ok"] for x in checked],
                         [True, False, False, False, False])

    def test_eight_periods_are_unknown_without_actual_scan(self):
        coverage = visual.view_coverage_rows({})
        self.assertEqual(len(coverage), 8)
        self.assertTrue(all(x["certified"] is False for x in coverage))

    def test_finance_history_inventory_scope_includes_all_dates(self):
        import market_center_v2_finance_history_scope as history
        src = inspect.getsource(history.inventory_historical_versions)
        self.assertIn('"snapshots"', src)
        self.assertIn('"active"', src)
        self.assertNotIn("download_financial_data", src)
        self.assertNotIn("subprocess.", src)


class V2EIntegratedWidgetSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="v2e-integrated-local-fixture-")
        self.addCleanup(self.temp.cleanup)
        module = Path(self.temp.name) / "ParquetLiveSync"
        module.mkdir()
        self.module = module
        try:
            with mock.patch.object(
                    controller, "observe_qmt_connection",
                    side_effect=AssertionError("no automatic QMT probe")):
                with mock.patch.object(
                        controller, "inspect_recovery_prerequisites",
                        side_effect=AssertionError("no automatic inventory")):
                    with mock.patch.object(
                            visual, "inventory_historical_versions",
                            side_effect=AssertionError("no automatic history")):
                        self.app = visual.MarketCenterV2SelectedUI(
                            state_module=module)
        except tk.TclError as exc:
            reason = str(exc).lower()
            if "no display name" in reason or "couldn't connect to display" in reason:
                self.skipTest("GUI display unavailable: " + str(exc))
            raise
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def test_sidebar_notebook_and_three_action_steps_render(self):
        self.assertEqual(len(self.app.nav_controls), 7)
        self.assertEqual(len(self.app.book.tabs()), 7)
        self.assertEqual(len(self.app.action_steps.tabs()), 3)
        for index, (label, _subtitle, _style) in enumerate(visual.PAGES):
            self.app.navigate(index)
            self.assertEqual(self.app.page_heading.get(), label)

    def test_previous_qmt_and_finance_inventory_buttons_remain_visible(self):
        self.assertEqual(len(self.app.qmt_probe_buttons), 2)
        self.assertEqual(len(self.app.inventory_buttons), 2)
        self.assertEqual(len(self.app.historical_inventory_buttons), 1)
        self.assertEqual(str(self.app.fault_repair_disabled["state"]),
                         "disabled")
        self.assertIsNone(self.app.qmt_live_result)
        self.assertIsNone(self.app.finance_inventory)

    def test_two_split_panels_and_evidence_toggle_work(self):
        self.assertEqual(len(self.app.fault_split.panes()), 2)
        self.assertEqual(len(self.app.audit_split.panes()), 2)
        self.app._toggle_audit_details()
        self.assertEqual(len(self.app.audit_split.panes()), 1)
        self.app._toggle_audit_details()
        self.assertEqual(len(self.app.audit_split.panes()), 2)

    def test_home_is_direct_dashboard_without_page_canvas_scrollbar(self):
        self.assertIsInstance(self.app.home_dashboard, visual.ttk.Frame)
        self.assertIn(self.app.home_dashboard, self.app.home.winfo_children())
        self.assertFalse(any(
            isinstance(child, tk.Canvas) or isinstance(child, visual.ttk.Scrollbar)
            for child in self.app.home.winfo_children()))
        source = inspect.getsource(visual.MarketCenterV2SelectedUI.build_home)
        self.assertNotIn("self._scroll_content(self.home)", source)
        self.assertIn('text="三类结果独立判定"', source)
        self.assertIn('text="本轮四个阶段"', source)
        self.assertIn('text="待处理事项与下一步"', source)

    def test_home_keeps_all_five_metrics_four_phases_and_six_actions(self):
        self.assertEqual(set(self.app.cards), {
            "已提交最新交易日", "上次任务结果", "当前安全截止",
            "QMT 最近预检", "财务待审"})
        self.assertEqual(len(self.app.stage_labels), 4)
        self.assertEqual(set(self.app.validation_vars),
                         {"execution", "data", "cross"})
        self.assertEqual(len(self.app.qmt_probe_buttons), 2)
        self.assertEqual(len(self.app.inventory_buttons), 2)
        self.assertEqual(str(self.app.fault_repair_disabled["state"]), "disabled")

    def test_dashboard_cards_are_content_height_not_window_height(self):
        source = inspect.getsource(visual.MarketCenterV2SelectedUI.build_home)
        phases = source.split('text="本轮四个阶段"', 1)[1].split(
            'text="本次可信变化"', 1)[0]
        actions = source.split('text="常用操作 · 仅只读预检"', 1)[1].split(
            '# A short full-width diagnosis strip', 1)[0]
        self.assertIn('phases.pack(fill="x")', phases)
        self.assertIn('matrix.pack(fill="x")', phases)
        self.assertNotIn('matrix.rowconfigure(row, weight=1)', phases)
        self.assertIn('sticky="ew"', phases)
        self.assertIn('actions.pack(fill="x")', actions)
        self.assertNotIn('actions.pack(fill="both", expand=True)', actions)
        self.assertIn('center.pack(fill="x", pady=(0, 7))', source)
        self.assertIn('issues.pack(fill="x")', source)
        self.assertEqual(str(self.app.fault_repair_disabled["state"]), "disabled")

    def test_fault_summary_immediately_follows_compact_middle_content(self):
        source = inspect.getsource(visual.MarketCenterV2SelectedUI.build_home)
        self.assertIn('center.pack(fill="x", pady=(0, 7))', source)
        self.assertNotIn('center.pack(fill="both", expand=True)', source)
        self.assertIn('issues.pack(fill="x")', source)
        self.assertNotIn("self._scroll_content(self.home)", source)
        self.assertEqual(str(self.app.fault_repair_disabled["state"]), "disabled")

    def test_home_rewraps_at_narrow_width_without_losing_buttons(self):
        from types import SimpleNamespace
        self.app._resize_home_wrapping(SimpleNamespace(width=800))
        self.assertEqual(
            int(self.app.home_last_run_view.cget("wraplength")), 755)
        self.assertLessEqual(
            int(self.app.home_progress_view.cget("wraplength")), 320)
        self.assertGreaterEqual(
            int(next(iter(self.app.stage_widgets.values())).cget("wraplength")),
            145)
        self.assertEqual(len(self.app.qmt_probe_buttons), 2)
        self.assertEqual(len(self.app.inventory_buttons), 2)

    def test_data_settings_scrollbar_only_when_content_overflows(self):
        source = inspect.getsource(
            visual.MarketCenterV2SelectedUI._scroll_content)
        self.assertIn("inside.winfo_reqheight() > viewport + 2", source)
        self.assertIn("scroll.pack_forget()", source)
        self.assertIn('scroll.pack(side="right", fill="y", before=canvas)', source)
        self.assertNotIn('scroll.pack(side="right", fill="y")\n        canvas.pack', source)

    def test_no_market_root_still_disables_history_audit(self):
        self.assertIsNone(self.app.market_root)
        self.assertEqual(str(self.app.audit_button["state"]), "disabled")
        self.app.navigate(3)
        self.assertEqual(self.app.page_heading.get(), "故障诊断")
        self.assertFalse(self.app.historical_inventory_running)

    def test_refresh_invalidates_old_readonly_preflight_including_history(self):
        self.app.historical_inventory_result = {
            "status": "V2D2C_HISTORICAL_FINANCE_METADATA_NOT_RESTORABLE"}
        self.app.qmt_live_result = {"connected_now": True}
        self.app.finance_inventory = {"finance_scope_count": 45}
        self.app.refresh_fault_diagnosis()
        self.assertIsNone(self.app.historical_inventory_result)
        self.assertIsNone(self.app.qmt_live_result)
        self.assertIsNone(self.app.finance_inventory)
        self.assertEqual(str(self.app.fault_repair_disabled["state"]),
                         "disabled")


if __name__ == "__main__":
    unittest.main()
