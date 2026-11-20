"""V2E seven-page visual preview contracts: all synthetic, no market writes."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import tkinter as tk

from market_center_v2e_selected_ui import (
    PAGE_MAP, PAGES, PERIOD_LABELS,
    MarketCenterV2SelectedUI, format_evidence_state,
    separated_run_evidence, view_coverage_rows, main,
)


class V2ELayoutContractTests(TestCase):
    def test_seven_actual_pages(self):
        self.assertEqual(len(PAGES), 7)
        self.assertEqual(set(PAGE_MAP), {x[0] for x in PAGES})

    def test_selected_design_matches_user_review(self):
        self.assertEqual(tuple(x[2] for x in PAGES),
                         ("A", "B", "B", "B", "B", "A", "A"))

    def test_pages_have_distinct_navigation_index(self):
        self.assertEqual(sorted(PAGE_MAP.values()), list(range(7)))

    def test_overview_goes_first(self):
        self.assertEqual(PAGES[0][0], "运行总览")

    def test_settings_go_last(self):
        self.assertEqual(PAGES[-1][0], "高级设置")

    def test_all_eight_periods_covered_by_cards(self):
        self.assertEqual(len(PERIOD_LABELS), 8)
        self.assertEqual({x[0] for x in PERIOD_LABELS},
                         {"1min", "5min", "15min", "30min",
                          "60min", "day", "week", "month"})

    def test_coverage_without_proof_does_not_claim_percentages(self):
        rows = view_coverage_rows({})
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(row["count"] is None for row in rows))
        self.assertTrue(all(row["certified"] is False for row in rows))
        self.assertTrue(all(row["coverage"] == "未逐周期核验" for row in rows))

    def test_execution_pass_is_not_per_period_coverage_pass(self):
        rows = view_coverage_rows({
            "stage_records": {"EIGHT_PERIODS": {
                "data_validation": "PASS",
                "exit_code": 0,
            }}
        })
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(not row["certified"] for row in rows))
        self.assertTrue(all(row["count"] is None for row in rows))
        self.assertTrue(all("PASS" in row["source_statement"]
                            for row in rows))

    def test_missing_stage_record_does_not_crash(self):
        self.assertEqual(len(view_coverage_rows({"stage_records": {}})), 8)

    def test_execution_quality_cross_source_are_distinct(self):
        result = separated_run_evidence({
            "execution_validation": "PASS",
            "data_validation": "PARTIAL",
            "cross_validation": "UNVERIFIED",
        })
        self.assertEqual(result["execution"], "PASS")
        self.assertEqual(result["data"], "PARTIAL")
        self.assertEqual(result["cross"], "UNVERIFIED")

    def test_qmt_live_never_inferred_from_historical_preflight(self):
        self.assertFalse(separated_run_evidence(
            {"qmt_last_preflight": "CONNECTED"}
        )["qmt_live"])

    def test_delta_unproven_is_not_displayed_as_comparable(self):
        self.assertFalse(separated_run_evidence(
            {"comparison_evidenced": False}
        )["comparison_evidenced"])

    def test_unrecorded_quality_returns_clear_unknown(self):
        self.assertEqual(format_evidence_state(None), "暂无可信记录")
        self.assertEqual(format_evidence_state(""), "暂无可信记录")

    def test_unknown_quality_is_not_green(self):
        self.assertEqual(format_evidence_state("UNVERIFIED"), "UNVERIFIED")

    def test_source_labels_bound_string_length(self):
        self.assertEqual(len(format_evidence_state("a" * 500)), 100)

    def test_main_rejects_missing_state_without_starting_ui(self):
        with mock.patch(
            "market_center_v2e_selected_ui.MarketCenterV2SelectedUI",
            side_effect=AssertionError("UI must not start"),
        ):
            with self.assertRaises(SystemExit):
                main(["--state-module", "relative/path"])

    def test_main_requires_evidence_flags_as_pair(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "ParquetLiveSync"
            path.mkdir()
            with mock.patch(
                "market_center_v2e_selected_ui.MarketCenterV2SelectedUI",
                side_effect=AssertionError("UI must not start"),
            ):
                with self.assertRaises(SystemExit):
                    main([
                        "--state-module", str(path),
                        "--evidence-sha256", "0" * 64,
                    ])

    def test_main_rejects_relative_market_root(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "ParquetLiveSync"
            path.mkdir()
            with mock.patch(
                "market_center_v2e_selected_ui.MarketCenterV2SelectedUI",
                side_effect=AssertionError("UI must not start"),
            ):
                with self.assertRaises(SystemExit):
                    main([
                        "--state-module", str(path),
                        "--market-root", "relative",
                    ])


class V2ERealWidgetSmokeTests(TestCase):
    """Uses an empty temporary status directory, never the production one."""

    def setUp(self):
        self.temp = TemporaryDirectory(prefix="market-v2e-synthetic-")
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / "ParquetLiveSync"
        path.mkdir()
        try:
            self.app = MarketCenterV2SelectedUI(state_module=path)
        except tk.TclError as exc:
            reason = str(exc).lower()
            if "no display name" in reason or "couldn't connect to display" in reason:
                self.skipTest("No GUI display available: " + str(exc))
            raise
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def test_sidebar_renders_all_seven_pages(self):
        self.assertEqual(len(self.app.nav_controls), 7)
        self.assertEqual(len(self.app.book.tabs()), 7)

    def test_default_is_overview_a(self):
        self.assertEqual(self.app.book.index(self.app.book.select()), 0)
        self.assertEqual(self.app.page_heading.get(), "运行总览")

    def test_navigation_updates_page_and_headline(self):
        for page, (name, _, _) in enumerate(PAGES):
            self.app.navigate(page)
            self.assertEqual(self.app.book.index(self.app.book.select()), page)
            self.assertEqual(self.app.page_heading.get(), name)

    def test_stepper_has_three_real_tabs(self):
        self.assertEqual(len(self.app.action_steps.tabs()), 3)

    def test_mode_switch_keeps_shared_dates_and_scope(self):
        self.app.start.set("2026-11-01")
        self.app.end.set("2026-11-19")
        self.app.scope.set("指定股票")
        self.app.stock_box.delete("1.0", "end")
        self.app.stock_box.insert("1.0", "000001.SZ, 600519.SH")
        self.app.go_action("更新数据")
        self.app.action_steps.select(2)
        self.app.go_action("数据核验")
        self.assertEqual(self.app.start.get(), "2026-11-01")
        self.assertEqual(self.app.end.get(), "2026-11-19")
        self.assertEqual(self.app.scope.get(), "指定股票")
        self.assertEqual(self.app.stock_box.get("1.0", "end-1c"),
                         "000001.SZ, 600519.SH")
        self.assertEqual(self.app.action_steps.index(
            self.app.action_steps.select()), 0)

    def test_audit_main_table_and_right_evidence_both_visible(self):
        self.assertTrue(self.app.audit_details_visible)
        self.assertEqual(len(self.app.audit_split.panes()), 2)
        self.assertIsNotNone(self.app.audit_table)
        self.assertIsNotNone(self.app.audit_result_text)

    def test_evidence_toggle_does_not_destroy_proof(self):
        self.app._toggle_audit_details()
        self.assertFalse(self.app.audit_details_visible)
        self.assertEqual(len(self.app.audit_split.panes()), 1)
        self.app._toggle_audit_details()
        self.assertTrue(self.app.audit_details_visible)
        self.assertEqual(len(self.app.audit_split.panes()), 2)

    def test_fault_panel_has_split_view_and_retry_disabled(self):
        self.assertEqual(len(self.app.fault_split.panes()), 2)
        self.assertEqual(str(self.app.fault_repair_disabled["state"]),
                         "disabled")

    def test_log_scroll_both_directions_and_local_search(self):
        self.assertEqual(str(self.app.log_text["wrap"]), "none")
        self.assertIsNotNone(self.app.log_text["yscrollcommand"])
        self.assertIsNotNone(self.app.log_text["xscrollcommand"])
        self.app.log_query.set("QMT")
        self.app._highlight_log()

    def test_data_management_keeps_all_eight_unknown(self):
        self.assertEqual(len(self.app.period_vars), 8)
        self.assertTrue(all(v.get() == "未逐周期核验"
                            for v in self.app.period_vars.values()))

    def test_settings_never_allow_market_writes(self):
        flags = {row[0]: row[1] for row in self.app.feature_flags}
        self.assertFalse(flags["自动更新执行"])
        self.assertFalse(flags["历史缺口自动修复"])
        self.assertFalse(flags["财务断线一键续跑"])
        self.assertFalse(flags["有限历史行情只读核验"])

    def test_only_bounded_readonly_audit_disabled_without_root(self):
        self.assertEqual(str(self.app.audit_button["state"]), "disabled")
        self.assertIsNone(self.app.market_root)

    def test_readonly_refresh_does_not_create_state_files(self):
        before = set(self.app.state_module.iterdir())
        self.app.refresh_overview()
        self.assertEqual(before, set(self.app.state_module.iterdir()))

    def test_home_uses_independent_execution_data_cross_status(self):
        self.assertEqual(set(self.app.validation_vars),
                         {"execution", "data", "cross"})

    def test_summary_contains_no_fabricated_coverage(self):
        self.assertIn("逐周期历史覆盖", self.app.management_summary.get())
        self.assertIn("尚无独立扫描证据", self.app.management_summary.get())

    def test_log_highlight_never_triggers_network_or_qmt(self):
        self.app.log_query.set("financial")
        with mock.patch("socket.create_connection",
                        side_effect=AssertionError("network")):
            self.app._highlight_log()
