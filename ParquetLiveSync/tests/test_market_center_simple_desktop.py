"""Synthetic latest trading day, date-range and three-tab GUI tests."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import tkinter as tk
import unittest

import market_simple_ui_model as M
import market_daily_calendar_read as C
import market_simple_desktop as UI
import market_update_dashboard as OLD


class SimpleModelTests(unittest.TestCase):
    def test_committed_date_is_selected_as_fallback(self):
        ledger = {"periods": {"1min": {"2026-11": {
            "days": ["2026-11-19", "2026-11-20"]}}}}
        day, reason = M.initial_date(ledger, cutoff=date(2026, 11, 21))
        self.assertEqual(day, "2026-11-20")
        self.assertIn("本地已提交", reason)

    def test_missing_ledger_never_guesses_holiday(self):
        self.assertEqual(M.initial_date({}, cutoff=date(2026, 11, 21))[0], "")

    def test_future_ledger_day_rejected(self):
        ledger = {"periods": {"1min": {"2026-11": {
            "days": ["2026-11-23"]}}}}
        self.assertEqual(M.initial_date(
            ledger, cutoff=date(2026, 11, 21))[0], "")

    def test_eight_cycles_have_independent_date_ranges(self):
        ledger = {"periods": {
            "1min": {"2026-11": {"days": ["2026-11-19", "2026-11-20"]}},
            "day": {"2026-11": {"days": ["2026-11-18", "2026-11-19"]}},
        }}
        result = {r["key"]: r for r in M.coverage_rows(ledger, {}, {})}
        self.assertEqual(len(result), 11)
        self.assertEqual(result["1min"]["end"], "2026-11-20")
        self.assertEqual(result["day"]["end"], "2026-11-19")
        self.assertEqual(result["week"]["end"], "未核实")
        self.assertEqual(result["1min"]["multi_source"], "未核验")

    def test_single_stage_pass_not_multisource_verified(self):
        receipt = {"validation": {"sections": {"SECTORS": {
            "data_validation": "PASS",
            "cross_validation": "UNVERIFIED"}}}}
        result = {r["key"]: r for r in M.coverage_rows({}, receipt, {})}
        self.assertEqual(result["SECTORS"]["multi_source"], "未核验")

    def test_cross_source_fail_is_visible(self):
        receipt = {"validation": {"sections": {"SECTORS": {
            "data_validation": "PASS",
            "cross_validation": "FAIL"}}}}
        result = {r["key"]: r for r in M.coverage_rows({}, receipt, {})}
        self.assertEqual(result["SECTORS"]["multi_source"], "失败")

    def test_single_day_selected_stocks_are_preview_only(self):
        selected = M.preview_request(
            mode="重新下载并比对", scope="自选股票",
            stocks="000001.SZ, 600519.SH",
            start="2026-11-20", end="2026-11-20",
            modules=["八周期行情", "财务"],
            cutoff=date(2026, 11, 21))
        self.assertEqual(selected["start"], selected["end"])
        self.assertEqual(len(selected["symbols"]), 2)
        self.assertFalse(selected["allowed_to_execute_selected_range"])

    def test_invalid_selected_dates_block(self):
        for a, b in (("2026-11-20", "2026-11-22"),
                     ("2026-11-21", "2026-11-20")):
            with self.subTest(a=a, b=b), self.assertRaises(ValueError):
                M.preview_request(
                    mode="增量更新", scope="全市场", stocks="",
                    start=a, end=b, modules=["财务"],
                    cutoff=date(2026, 11, 21))

    def test_incomplete_stock_code_blocked(self):
        with self.assertRaises(ValueError):
            M.preview_request(
                mode="增量更新", scope="自选股票", stocks="600519",
                start="2026-11-20", end="2026-11-20",
                modules=["财务"], cutoff=date(2026, 11, 21))


class CalendarTests(unittest.TestCase):
    def test_exchange_calendar_skips_holiday_and_weekend(self):
        self.assertEqual(C.last_session(
            ["20261117", "20261118", "20261120"],
            date(2026, 11, 22)), "2026-11-20")

    def test_calendar_excludes_future_dates(self):
        self.assertEqual(C.last_session(
            [20261120, 20261123], date(2026, 11, 22)),
            "2026-11-20")

    def test_empty_and_invalid_calendar_block(self):
        with self.assertRaises(C.CalendarUnavailable):
            C.last_session([], date(2026, 11, 22))
        with self.assertRaises(C.CalendarUnavailable):
            C.last_session(["invalid"], date(2026, 11, 22))

    def test_only_bounded_calendar_child_is_run(self):
        payload = {"market": "SH", "cutoff": "2026-11-22",
                   "last": "2026-11-20", "source": "QMT交易日历"}
        def runner(args, **kw):
            self.assertIn("--read-calendar", args)
            self.assertEqual(kw["timeout"], 9)
            self.assertNotIn("download", " ".join(args))
            return SimpleNamespace(
                returncode=0,
                stdout=(C.SENTINEL + json.dumps(payload) + "\n").encode())
        self.assertEqual(
            C.query_calendar(date(2026, 11, 22), runner=runner)["last"],
            "2026-11-20")

    def test_malformed_child_receipt_rejected(self):
        with self.assertRaises(C.CalendarUnavailable):
            C.query_calendar(
                date(2026, 11, 22),
                runner=lambda *a, **k: SimpleNamespace(
                    returncode=0, stdout=b"invalid"))


class GuiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="market-simple-")
        self.addCleanup(self.temp.cleanup)
        self.module = Path(self.temp.name) / "ParquetLiveSync"
        self.work = self.module / "work"
        (self.work / "market_update").mkdir(parents=True)
        (self.work / "market_update" / "commits.json").write_text(
            json.dumps({"periods": {"1min": {
                "2026-11": {"days": ["2026-11-20"]}}}}),
            encoding="utf-8")
        try:
            with patch.object(UI, "WORK", self.work), \
                 patch.object(OLD, "WORK", self.work), \
                 patch.object(OLD, "MODULE", self.module), \
                 patch.object(UI.SimpleMarketDashboard,
                              "_resolve_default_session", return_value=None):
                self.app = UI.SimpleMarketDashboard()
        except tk.TclError as exc:
            if "display" in str(exc).lower() or "couldn't connect" in str(exc).lower():
                self.skipTest("No Tk display")
            raise
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def test_only_three_tabs_and_legacy_runner_is_separate(self):
        self.assertEqual(len(self.app.tabs.tabs()), 3)
        self.assertEqual(self.app.tabs.tab(0, "text"), "数据总览")
        self.assertEqual(self.app.tabs.tab(1, "text"), "下载 / 更新")
        self.assertEqual(self.app.tabs.tab(2, "text"), "异常与日志")
        self.assertEqual(str(self.app.selected_run_button["state"]), "disabled")
        self.assertIn("既有游标", self.app.run_button["text"])

    def test_date_start_and_end_auto_fill_identically(self):
        self.app._apply_default_day("2026-11-20", "QMT交易日历")
        self.assertEqual(self.app.date_start.get(), "2026-11-20")
        self.assertEqual(self.app.date_end.get(), "2026-11-20")
        self.app.date_start.set("2026-11-10")
        self.app._apply_default_day("2026-11-21", "QMT交易日历")
        self.assertEqual(self.app.date_start.get(), "2026-11-10")

    def test_stock_input_only_when_scoped(self):
        self.assertEqual(self.app.stock_frame.winfo_manager(), "")
        self.app.update_scope.set("自选股票")
        self.app._toggle_stock_entry()
        self.assertEqual(self.app.stock_frame.winfo_manager(), "pack")
        self.app.update_scope.set("全市场")
        self.app._toggle_stock_entry()
        self.assertEqual(self.app.stock_frame.winfo_manager(), "")

    def test_coverage_table_uses_ledger_not_guessed_dates(self):
        with patch.object(UI, "WORK", self.work):
            self.app._refresh_coverage()
        items = [self.app.coverage_table.item(k, "values")
                 for k in self.app.coverage_table.get_children()]
        minute = next(row for row in items if row[0] == "1分钟")
        week = next(row for row in items if row[0] == "周线")
        self.assertEqual(minute[2], "2026-11-20")
        self.assertEqual(minute[4], "未核验")
        self.assertEqual(week[2], "未核实")

    def test_preview_never_launches_market_writer(self):
        self.app._apply_default_day("2026-11-20", "本地")
        with patch.object(self.app, "manual_update",
                          side_effect=AssertionError("writer_launched")):
            self.app.preview_selection()
        self.assertIn("定向执行尚未开放", self.app.preview_line.get())


if __name__ == "__main__":
    unittest.main()
