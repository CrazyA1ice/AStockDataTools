"""Offline V2-A UI model acceptance: synthetic files only, no QMT/data writes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import market_center_v2_model as M
import market_center_v2_preview as UI

CN = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 20, 18, 34, tzinfo=CN)


class V2AContractTests(unittest.TestCase):
    def base(self, **kwargs):
        args = dict(mode="更新数据", start="2026-11-01", end="2026-11-19",
                    scope="指定股票", stock_text="000001.SZ, 600519.SH",
                    modules=["八周期行情", "财务"], now=NOW)
        args.update(kwargs)
        return M.plan_preview(**args)

    def test_preview_is_never_executable(self):
        result = self.base()
        self.assertFalse(result["allowed_to_execute"])
        self.assertEqual(result["format"], "market_center_v2_plan_preview_only_v1")
        self.assertFalse(result["physical_data_certified"])

    def test_two_modes_share_identical_scope(self):
        update = self.base()
        audit = self.base(mode="数据核验")
        for field in ("start_date", "end_date", "scope", "symbols", "data_types"):
            self.assertEqual(update[field], audit[field])
        self.assertFalse(audit["allowed_to_execute"])

    def test_stock_list_deduplicates_preserving_order(self):
        self.assertEqual(
            M.parse_symbols("000001.sz, 600519.SH\n000001.SZ；830001.BJ"),
            ("000001.SZ", "600519.SH", "830001.BJ"),
        )

    def test_stock_market_cannot_be_guessed(self):
        for text in ("000001", "600519", "abcd", "000001.SS", "000001.XX",
                     "000001.SZ; DELETE", "12345.SZ"):
            with self.subTest(text=text):
                with self.assertRaises(M.InvalidPlan):
                    M.parse_symbols(text)

    def test_stock_count_cap(self):
        input_text = ",".join(f"{i:06d}.SZ" for i in range(501))
        with self.assertRaisesRegex(M.InvalidPlan, "500"):
            M.parse_symbols(input_text)

    def test_multiple_stocks_allowed(self):
        result = self.base(stock_text="000001.SZ 600519.SH 000858.SZ")
        self.assertEqual(result["symbol_count"], 3)

    def test_all_stocks_ignores_input_without_inference(self):
        result = self.base(scope="全部股票", stock_text="even malformed")
        self.assertEqual(result["symbols"], [])
        self.assertIsNone(result["symbol_count"])
        self.assertFalse(result["stock_universe_membership_certified"])

    def test_selected_empty_stocks_rejected(self):
        with self.assertRaisesRegex(M.InvalidPlan, "至少选择一只"):
            self.base(stock_text="")

    def test_date_invalid_or_reversed_fails_closed(self):
        for args in (
            {"start": "2026-11-20"},
            {"end": "2026-11-31"},
            {"end": "2026/11/19"},
            {"start": "2026-11-19", "end": "2026-11-01"},
        ):
            with self.subTest(args=args):
                with self.assertRaises(M.InvalidPlan):
                    self.base(**args)

    def test_future_today_denied_before_china_2005(self):
        with self.assertRaisesRegex(M.InvalidPlan, "安全候选上限"):
            self.base(end="2026-11-20")

    def test_same_day_after_2005_date_only_candidate(self):
        later = datetime(2026, 11, 20, 20, 5, tzinfo=CN)
        p = self.base(end="2026-11-20", now=later)
        self.assertFalse(p["trading_calendar_confirmed"])
        self.assertFalse(p["allowed_to_execute"])

    def test_weekend_safe_candidate_falls_back_friday(self):
        sunday = datetime(2026, 11, 22, 20, 10, tzinfo=CN)
        self.assertEqual(M.safe_cutoff(sunday).isoformat(), "2026-11-20")

    def test_unknown_module_or_empty_set_rejected(self):
        for mods in ([], ["未实现数据"]):
            with self.assertRaises(M.InvalidPlan):
                self.base(modules=mods)

    def test_source_configuration_is_display_only(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "market_sources.json").write_text(json.dumps({
                "primary": "qmt",
                "minute_cross_checks": {
                    "eltdx": {"enabled": True},
                    "tencent": {"enabled": True},
                    "akshare": {"enabled": False},
                },
            }), encoding="utf-8")
            src = M.source_info(root)
            self.assertTrue(src["source_config_loaded"])
            self.assertFalse(src["crosscheck_execution_evidenced"])
            self.assertFalse(src["source_selection_user_editable"])
            self.assertEqual(len(src["minute_crosschecks_configured"]), 2)

    def test_local_source_override_takes_precedence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "market_sources.json").write_text(
                '{"minute_cross_checks":{"tencent":{"enabled":true}}}',
                encoding="utf-8")
            d = root / "work" / "market_update"
            d.mkdir(parents=True)
            (d / "sources.local.json").write_text(
                '{"minute_cross_checks":{"eltdx":{"enabled":true}}}',
                encoding="utf-8")
            src = M.source_info(root)
            self.assertEqual(src["config_file"], "本地覆盖配置")
            self.assertIn("eltdx", src["minute_crosschecks_configured"][0])

    def test_unavailable_delta_is_not_fabricated(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "work" / "market_update").mkdir(parents=True)
            (root / "work" / "market_update" / "commits.json").write_text(
                json.dumps({"periods": {"1min": {"2026-11": {
                    "days": ["2026-11-18", "2026-11-19"]}}}}),
                encoding="utf-8")
            (root / "work" / "last-afternoon-unified.json").write_text(
                json.dumps({"status": "FAILED",
                            "qmt_preflight_status": "QMT_SERVICE_UNAVAILABLE",
                            "validation": {"data_validation": "FAIL"}}),
                encoding="utf-8")
            summary = M.latest_status(root, now=NOW)
            self.assertEqual(summary["last_accepted_trading_day"], "2026-11-19")
            self.assertEqual(summary["qmt_last_preflight"], "QMT_SERVICE_UNAVAILABLE")
            self.assertFalse(summary["comparison_evidenced"])
            self.assertIn("无法计算", summary["comparison"])
            self.assertFalse(summary["qmt_is_live_now_verified"])

    def test_oversized_source_config_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "market_sources.json").write_text(" " * (M.MAX_SOURCE_BYTES + 1))
            with self.assertRaisesRegex(M.InvalidPlan, "过大"):
                M.source_info(root)

    def test_log_reader_only_allows_private_work_log(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "work").mkdir()
            legitimate = root / "work" / "afternoon-test.log"
            legitimate.write_text("SYNTHETIC_LOG_OK", encoding="utf-8")
            outside = root / "outside.log"
            outside.write_text("SYNTHETIC_OUTSIDE", encoding="utf-8")
            with patch.object(UI, "WORK", root / "work"):
                self.assertIn("SYNTHETIC_LOG_OK", UI._read_log_tail(str(legitimate)))
                self.assertIn("不属于", UI._read_log_tail(str(outside)))

    def test_explicit_canonical_status_source_is_read_only(self):
        with TemporaryDirectory() as tmp:
            module = Path(tmp) / "ParquetLiveSync"
            module.mkdir()
            with patch.object(UI, "MarketCenterV2") as fake_app:
                UI.main(["--state-module", str(module)])
                fake_app.assert_called_once_with(state_module=module)
                fake_app.return_value.mainloop.assert_called_once()

    def test_ui_refuses_non_module_status_directory(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                UI.main(["--state-module", tmp])

    def test_blue_white_theme_and_tristate_colors(self):
        self.assertEqual(UI.COLORS["surface"], "#FFFFFF")
        self.assertEqual(UI.COLORS["blue"], "#1769D1")
        self.assertNotEqual(UI.COLORS["green"], UI.COLORS["red"])
        self.assertNotEqual(UI.COLORS["amber"], UI.COLORS["green"])
        theme = inspect.getsource(UI.apply_theme)
        self.assertIn('theme_use("clam")', theme)
        self.assertIn('"Primary.TButton"', theme)
        self.assertIn('"Success.CardValue.TLabel"', inspect.getsource(
            UI.MarketCenterV2.refresh_overview))

    def test_log_vertical_and_horizontal_scrollbars_are_connected(self):
        ui = inspect.getsource(UI.MarketCenterV2.build_logs)
        self.assertIn('orient="vertical", command=self.log_text.yview', ui)
        self.assertIn('orient="horizontal", command=self.log_text.xview', ui)
        self.assertIn('yscrollcommand=self.log_vertical_scroll.set', ui)
        self.assertIn('xscrollcommand=self.log_horizontal_scroll.set', ui)
        self.assertIn('self.log_vertical_scroll.grid', ui)
        self.assertIn('self.log_horizontal_scroll.grid', ui)
        self.assertIn('state="disabled"', ui)

    def test_short_windows_have_scrollable_configuration_page(self):
        ui = inspect.getsource(UI.MarketCenterV2.build_action)
        self.assertIn('tk.Canvas(self.action', ui)
        self.assertIn('orient="vertical", command=area.yview', ui)
        self.assertIn('scrollregion=area.bbox("all")', ui)

    def test_preview_discloses_already_committed_and_schedule_collisions(self):
        plan = self.base()
        self.assertFalse(plan["allowed_to_execute"])
        self.assertFalse(plan["existing_stock_day_coverage_scanned"])
        self.assertFalse(plan["scheduled_task_live_state_checked"])
        self.assertIn("拒绝盲目覆盖", plan["existing_history_policy"])
        self.assertIn("执行锁", plan["concurrent_task_policy"])
        self.assertIn("未证明", inspect.getsource(
            UI.MarketCenterV2.show_preview))

    def test_no_prod_update_process_is_reachable_from_preview(self):
        # UI imports but does not start its desktop in this test.
        self.assertTrue(hasattr(UI, "MarketCenterV2"))
        self.assertFalse(hasattr(UI.MarketCenterV2, "manual_update"))
        self.assertFalse(hasattr(UI.MarketCenterV2, "install_schedule"))


if __name__ == "__main__":
    unittest.main()
