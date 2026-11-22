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


def sample_finance_census():
    return {
        "status": "S9_FULL_PENDING_METADATA_CENSUS_READONLY_NOT_SOURCE_CERTIFIED",
        "can_apply": False, "can_commit": False,
        "all_historical_versions_verified": False, "qmt_calls": 0,
        "ledger_pending_total": 2,
        "pending_by_reason": {
            "SOURCE_HISTORY_CONFLICT": 1, "CACHE_DECODE_ERROR": 1},
        "first_recorded_conflict_table_counts": {"Capital": 1},
        "per_share_without_local_snapshots": 2,
        "nine_table_local_state_counts": [
            {"table": "PerShare", "state": "M", "count": 2},
            {"table": "Capital", "state": "M", "count": 1},
            {"table": "Capital", "state": "U", "count": 1},
            {"table": "Balance", "state": "M", "count": 1},
            {"table": "Balance", "state": "P", "count": 1},
            {"table": "Income", "state": "M", "count": 1},
            {"table": "Income", "state": "P", "count": 1},
            {"table": "CashFlow", "state": "M", "count": 1},
            {"table": "CashFlow", "state": "P", "count": 1},
            {"table": "Top10FlowHolder", "state": "M", "count": 1},
            {"table": "Top10FlowHolder", "state": "P", "count": 1},
            {"table": "Top10Holder", "state": "M", "count": 1},
            {"table": "Top10Holder", "state": "P", "count": 1},
            {"table": "HolderNum", "state": "M", "count": 1},
            {"table": "HolderNum", "state": "P", "count": 1},
            {"table": "PershareIndex", "state": "M", "count": 1},
            {"table": "PershareIndex", "state": "P", "count": 1},
        ],
        "cache_decode_error_stocks": ["688259.SH"],
        "journal_counts": {"capital-recovery-journal": 0,
                           "scoped-finance-transaction-journals": 0},
        "rows_on_page": [
            {"symbol": "688259.SH", "reason": "CACHE_DECODE_ERROR",
             "nine_table_states": {"PerShare": "M"},
             "first_recorded_conflict_table": None},
            {"symbol": "000010.SZ", "reason": "SOURCE_HISTORY_CONFLICT",
             "nine_table_states": {"PerShare": "M", "Capital": "U"},
             "first_recorded_conflict_table": "Capital"},
        ],
    }


def sample_qmt_table_probe():
    names = ("Balance", "Income", "CashFlow", "Capital",
             "Top10FlowHolder", "Top10Holder", "HolderNum",
             "PershareIndex", "PerShare")
    values = []
    for name in names:
        bad = name == "PerShare"
        values.append({
            "table": name,
            "role": "OPTIONAL_UNCONFIRMED" if bad else "DOCUMENTED_CORE",
            "status": "UTF8_DECODE_ERROR" if bad else "ROWS_IN_LOCAL_CACHE",
            "cached_rows": None if bad else 3,
        })
    return {
        "status": "QMT_FINANCE_TABLE_READONLY_PROBE_REQUIRES_REVIEW",
        "symbol": "688259.SH", "tables_checked": 9, "tables": values,
        "qmt_get_financial_data_calls": 9, "qmt_download_calls": 0,
        "can_apply": False, "can_commit": False,
        "can_download": False, "official_finance_writes": 0,
        "per_share_optional_support_proven": False,
        "historical_consistency_verified": False,
        "empty_cache_proves_provider_empty": False,
    }


class SimpleModelTests(unittest.TestCase):
    def test_finance_pending_exposes_reasons_not_just_count(self):
        brief = M.finance_pending_brief({
            "pending": {
                "000010.SZ": {"reason": "SOURCE_HISTORY_CONFLICT"},
                "688259.SH": {"reason": "CACHE_DECODE_ERROR"},
            }})
        self.assertIn("待审 2 只", brief)
        self.assertIn("历史差异 1", brief)
        self.assertIn("缓存解码 1", brief)
        self.assertIn("不会覆盖旧历史", brief)

    def test_missing_or_malformed_finance_ledger_not_green(self):
        self.assertIn("账本不可用", M.finance_pending_brief({}))
        self.assertIn("格式待核实", M.finance_pending_brief(
            {"pending": {"000010.SZ": "bad"}}))
        self.assertIn("不代表财务历史已跨源核验",
                      M.finance_pending_brief({"pending": {}}))

    def test_finance_diagnostic_binds_root_from_existing_ledger(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            extra = root / "AllCycleAStockData" / "qmt_extra"
            self.assertEqual(M.finance_root_from_progress(
                {"root": str(extra)}), root)
            for invalid in ({}, {"root": str(root)},
                            {"root": "relative/qmt_extra"}):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(M.InvalidSimplePlan):
                        M.finance_root_from_progress(invalid)

    def test_finance_diagnostic_chinese_view_is_not_repair_approval(self):
        text = M.finance_issue_report_view(sample_finance_census())
        self.assertIn("待审 2 只", text)
        self.assertIn("688259.SH", text)
        self.assertIn("PerShare 无本地快照 2/2", text)
        self.assertIn("无快照10、未pin1", text)
        self.assertIn("不能据此判断QMT来源为空", text)
        self.assertIn("不会补pin", text)

    def test_finance_diagnostic_rejects_forged_green_or_bad_counts(self):
        for fake in (
            {**sample_finance_census(), "can_commit": True},
            {**sample_finance_census(), "qmt_calls": 1},
            {**sample_finance_census(), "ledger_pending_total": 4},
            {**sample_finance_census(), "status": "UNKNOWN"},
        ):
            with self.subTest(fake=fake.get("status")):
                with self.assertRaises(M.InvalidSimplePlan):
                    M.finance_issue_report_view(fake)

    def test_qmt_readonly_probe_shows_separate_pershare_decode_failure(self):
        result = M.finance_qmt_probe_view(
            sample_qmt_table_probe(), "688259.SH")
        self.assertIn("688259.SH", result)
        self.assertIn("Balance：缓存有记录（3行）", result)
        self.assertIn("PerShare：UTF-8解码失败", result)
        self.assertIn("支持情况未确认", result)
        self.assertIn("不自动修复", result)

    def test_qmt_probe_refuses_forged_download_or_wrong_count(self):
        for change in (
            {"qmt_download_calls": 1},
            {"can_commit": True},
            {"tables_checked": 8},
            {"symbol": "600000.SH"},
        ):
            with self.subTest(change=change):
                r = {**sample_qmt_table_probe(), **change}
                with self.assertRaises(M.InvalidSimplePlan):
                    M.finance_qmt_probe_view(r, "688259.SH")

    def test_qmt_probe_rejects_duplicate_tables_or_claimed_source_emptiness(self):
        r = sample_qmt_table_probe()
        r["tables"][8]["table"] = "Balance"
        with self.assertRaises(M.InvalidSimplePlan):
            M.finance_qmt_probe_view(r, "688259.SH")
        r = sample_qmt_table_probe()
        r["empty_cache_proves_provider_empty"] = True
        with self.assertRaises(M.InvalidSimplePlan):
            M.finance_qmt_probe_view(r, "688259.SH")

    def test_qmt_probe_distinguishes_optional_pershare_from_core(self):
        r = sample_qmt_table_probe()
        r["installed_xtquant_version"] = "250807.1.2"
        view = M.finance_qmt_probe_view(r, "688259.SH")
        self.assertIn("250807.1.2", view)
        self.assertIn("仅PerShare单表存在异常", view)
        self.assertIn("仍不能证明九表组合请求的根因", view)

    def test_qmt_probe_reports_core_failure_without_blame_on_pershare(self):
        r = sample_qmt_table_probe()
        r["tables"][0]["status"] = "UTF8_DECODE_ERROR"
        r["tables"][0]["cached_rows"] = None
        view = M.finance_qmt_probe_view(r, "688259.SH")
        self.assertIn("核心八表中需要排查 Balance", view)
        self.assertIn("不能仅归因于PerShare", view)

    def test_qmt_probe_all_empty_is_not_claimed_source_empty(self):
        r = sample_qmt_table_probe()
        for item in r["tables"]:
            item["status"] = "EMPTY_OR_NOT_CACHED"
            item["cached_rows"] = 0
        view = M.finance_qmt_probe_view(r, "688259.SH")
        self.assertIn("核心八表的本地缓存均为空或尚未采集", view)
        self.assertIn("不能判定供应商源数据不存在", view)

    def test_qmt_probe_rejects_false_history_or_optional_certification(self):
        for claimed in ("historical_consistency_verified",
                        "per_share_optional_support_proven"):
            r = sample_qmt_table_probe()
            r[claimed] = True
            with self.subTest(claimed=claimed), \
                 self.assertRaises(M.InvalidSimplePlan):
                M.finance_qmt_probe_view(r, "688259.SH")

    def test_qmt_probe_version_must_not_contain_control_characters(self):
        r = sample_qmt_table_probe()
        r["installed_xtquant_version"] = "1.2\nINJECTED_APPROVAL"
        with self.assertRaises(M.InvalidSimplePlan):
            M.finance_qmt_probe_view(r, "688259.SH")

    def test_verified_single_decode_error_can_prepare_only_one_stock(self):
        self.assertEqual(
            M.finance_decode_retry_target(sample_finance_census()),
            "688259.SH")
        empty = sample_finance_census()
        empty["pending_by_reason"]["CACHE_DECODE_ERROR"] = 0
        empty["pending_by_reason"]["SOURCE_HISTORY_CONFLICT"] = 2
        empty["cache_decode_error_stocks"] = []
        self.assertIsNone(M.finance_decode_retry_target(empty))

    def test_decode_target_list_must_match_pending_and_stock_format(self):
        for codes in ([], ["not-a-stock"], ["688259.SH", "688259.SH"]):
            report = sample_finance_census()
            report["cache_decode_error_stocks"] = codes
            with self.subTest(codes=codes), \
                 self.assertRaises(M.InvalidSimplePlan):
                M.finance_decode_retry_target(report)

    def test_cache_refresh_window_is_only_recent_31_days(self):
        start, end = M.finance_decode_retry_window(cutoff=date(2026, 11, 20))
        self.assertEqual((start, end), ("2026-10-21", "2026-11-20"))
        with self.assertRaises(M.InvalidSimplePlan):
            M.finance_decode_retry_window(cutoff="2026-11-20")

    def test_one_decode_target_disabled_when_multiple_stocks_fail(self):
        report = sample_finance_census()
        report["pending_by_reason"]["CACHE_DECODE_ERROR"] = 2
        report["pending_by_reason"]["SOURCE_HISTORY_CONFLICT"] = 0
        report["cache_decode_error_stocks"] = ["688259.SH", "688622.SH"]
        self.assertIsNone(M.finance_decode_retry_target(report))

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

    def test_finance_readonly_button_is_on_existing_logs_tab(self):
        self.assertEqual(self.app.finance_diag_button["text"],
                         "检查财务问题（只读）")
        self.assertEqual(len(self.app.tabs.tabs()), 3)

    def test_finance_pending_is_visible_automatically_on_overview(self):
        progress = self.work / "qmt_extra" / "financial-cache-progress.json"
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.write_text(json.dumps({
            "pending": {
                "000010.SZ": {"reason": "SOURCE_HISTORY_CONFLICT"},
                "688259.SH": {"reason": "CACHE_DECODE_ERROR"}}}),
            encoding="utf-8")
        with patch.object(UI, "WORK", self.work):
            self.app._refresh_coverage()
        self.assertIn("待审 2 只", self.app.finance_attention.get())
        self.assertIn("缓存解码 1", self.app.finance_attention.get())

    def test_finance_diagnostic_worker_uses_census_not_qmt_or_writer(self):
        import market_scoped_finance_pending_full_census as S9
        root = Path(self.temp.name) / "stock"
        progress = {"root": str(root / "AllCycleAStockData" / "qmt_extra")}
        with patch.object(UI, "WORK", self.work), \
             patch.object(UI, "safe_json", return_value=progress), \
             patch.object(S9, "census",
                          return_value=sample_finance_census()) as scan, \
             patch.object(UI.threading, "Thread") as launch:
            self.app.start_finance_diagnostic()
            self.assertEqual(str(self.app.finance_diag_button["state"]),
                             "disabled")
            launch.assert_called_once()
            launch.call_args.kwargs["target"]()
            self.app._poll_finance_diagnostic()
            scan.assert_called_once_with(root, self.work / "qmt_extra",
                                         page=1, page_size=3)
        self.assertIn("688259.SH", self.app.finance_diag_detail.get())
        self.assertEqual(str(self.app.finance_diag_button["state"]), "normal")
        self.assertFalse(self.app._finance_diag_running)

    def test_missing_real_ledger_blocks_without_running_census(self):
        import market_scoped_finance_pending_full_census as S9
        with patch.object(UI, "WORK", self.work), \
             patch.object(UI, "safe_json", return_value={}), \
             patch.object(S9, "census") as scan, \
             patch.object(UI.threading, "Thread") as launch:
            self.app.start_finance_diagnostic()
            launch.call_args.kwargs["target"]()
            self.app._poll_finance_diagnostic()
        scan.assert_not_called()
        self.assertIn("只读检查被阻断", self.app.finance_diag_status.get())
        self.assertFalse(self.app._finance_diag_running)

    def test_repeated_click_while_running_does_not_spawn_new_worker(self):
        with patch.object(UI.threading, "Thread") as launch:
            self.app.start_finance_diagnostic()
            self.app.start_finance_diagnostic()
            launch.assert_called_once()
        self.app._finance_diag_queue.put(("error", "Synthetic only", None))
        self.app._poll_finance_diagnostic()

    def test_diagnostic_failure_does_not_start_retry_or_approval(self):
        self.app._finance_diag_running = True
        self.app._finance_diag_queue.put(
            ("error", "检查未完成：RESERVED_2005_NO_FINANCE_INVENTORY", None))
        self.app._poll_finance_diagnostic()
        self.assertIn("只读检查被阻断", self.app.finance_diag_status.get())
        self.assertFalse(self.app._finance_diag_running)

    def test_qmt_probe_button_requires_verified_pending_decode(self):
        self.assertEqual(str(self.app.qmt_table_probe_button["state"]),
                         "disabled")
        self.app._finance_diag_queue.put((
            "ok", M.finance_issue_report_view(sample_finance_census()),
            "688259.SH"))
        self.app._poll_finance_diagnostic()
        self.assertEqual(str(self.app.qmt_table_probe_button["state"]),
                         "normal")
        self.app._finance_diag_queue.put(("error", "blocked", None))
        self.app._poll_finance_diagnostic()
        self.assertEqual(str(self.app.qmt_table_probe_button["state"]),
                         "disabled")

    def test_qmt_probe_worker_is_read_only_and_shows_utf8_table(self):
        from datetime import datetime, timezone, timedelta
        repo = Path(self.temp.name)
        (repo / ".git").mkdir(exist_ok=True)
        python = repo / ".venv" / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_text("synthetic-fixture", encoding="utf-8")
        script = self.module / "qmt_extra_financial_cache_worker.py"
        script.write_text("synthetic-fixture", encoding="utf-8")
        receipt = (
            "QMT_FINANCE_TABLE_READONLY_PROBE=" +
            json.dumps(sample_qmt_table_probe()) + "\n").encode("utf-8")
        self.app._finance_decode_retry_stock = "688259.SH"
        with patch.object(UI, "REPO", repo), \
             patch.object(UI, "MODULE", self.module), \
             patch.object(UI, "WORK", self.work), \
             patch.object(UI, "safe_json", return_value={
                 "pending": {"688259.SH": {"reason": "CACHE_DECODE_ERROR"}}}), \
             patch.object(UI, "datetime") as fake_clock, \
             patch.object(UI.os, "name", "nt"), \
             patch.object(UI.subprocess, "run",
                          return_value=SimpleNamespace(
                              returncode=0, stdout=receipt)) as exec_read, \
             patch.object(UI.threading, "Thread") as launch:
            fake_clock.now.return_value = datetime(
                2026, 11, 22, 11, 0,
                tzinfo=timezone(timedelta(hours=8)))
            self.app.start_qmt_finance_table_probe()
            launch.assert_called_once()
            launch.call_args.kwargs["target"]()
            self.app._poll_qmt_finance_table_probe()
            args = exec_read.call_args.args[0]
            self.assertIn("--probe-readonly", args)
            self.assertNotIn("--mode", args)
            self.assertNotIn("--output", args)
            self.assertNotIn("download", " ".join(args))
            self.assertEqual(exec_read.call_args.kwargs["timeout"], 45)
            self.assertEqual(exec_read.call_args.kwargs["stdin"],
                             UI.subprocess.DEVNULL)
        self.assertIn("PerShare：UTF-8解码失败",
                      self.app.qmt_probe_detail.get())
        self.assertFalse(self.app._qmt_probe_running)

    def test_copy_diagnostic_includes_optional_per_share_probe(self):
        self.app._finance_diag_text = "本地待审：85只"
        self.app.qmt_probe_detail.set(
            "688259.SH：PerShare UTF-8解码失败；未做下载")
        self.app.copy_finance_diagnostic()
        clip = self.app.clipboard_get()
        self.assertIn("本地待审：85只", clip)
        self.assertIn("PerShare UTF-8解码失败", clip)

    def test_qmt_probe_blocks_stale_pending_without_subprocess(self):
        self.app._finance_decode_retry_stock = "688259.SH"
        with patch.object(UI, "safe_json", return_value={"pending": {}}), \
             patch.object(UI.subprocess, "run",
                          side_effect=AssertionError("QMT_CALLED")):
            self.app.start_qmt_finance_table_probe()
        self.assertIn("已阻断", self.app.qmt_probe_detail.get())

    def test_decode_retry_button_opens_scoped_form_without_running_qmt(self):
        self.app._finance_diag_queue.put((
            "ok", M.finance_issue_report_view(sample_finance_census()),
            "688259.SH"))
        self.app._poll_finance_diagnostic()
        self.assertEqual(
            str(self.app.finance_decode_retry_button["state"]), "normal")
        with patch.object(UI.subprocess, "Popen",
                          side_effect=AssertionError("QMT_STARTED")), \
             patch.object(UI, "safe_json", return_value={
                 "pending": {"688259.SH": {"reason": "CACHE_DECODE_ERROR"}}}), \
             patch.object(self.app, "run_scoped_finance_cache",
                          side_effect=AssertionError("REFRESH_STARTED")):
            self.app.prepare_finance_decode_retry()
        self.assertEqual(self.app.tabs.index(self.app.tabs.select()), 1)
        self.assertEqual(self.app.stock_input.get("1.0", "end-1c"),
                         "688259.SH")
        self.assertEqual(self.app.update_scope.get(), "自选股票")
        self.assertEqual(self.app.update_mode.get(), "增量更新")
        self.assertEqual([name for name in M.MODULES
                          if self.app.module_vars[name].get()], ["财务"])
        self.assertEqual(str(self.app.selected_run_button["state"]),
                         "normal")
        self.assertIn("请先检查日期", self.app.finance_diag_status.get())
        self.assertIn("不是全历史验证", self.app.date_source.get())

    def test_preparation_without_verified_target_does_not_change_scope(self):
        original = self.app.update_scope.get()
        self.app.prepare_finance_decode_retry()
        self.assertEqual(self.app.update_scope.get(), original)
        self.assertIn("请先运行只读检查", self.app.finance_diag_status.get())

    def test_resolved_pending_cannot_be_retried_from_stale_diagnostic(self):
        self.app._finance_decode_retry_stock = "688259.SH"
        before = self.app.update_scope.get()
        with patch.object(UI, "safe_json", return_value={"pending": {}}), \
             patch.object(UI.subprocess, "Popen",
                          side_effect=AssertionError("QMT_STARTED")):
            self.app.prepare_finance_decode_retry()
        self.assertIsNone(self.app._finance_decode_retry_stock)
        self.assertEqual(before, self.app.update_scope.get())
        self.assertIn("待审状态已变化", self.app.finance_diag_status.get())

    def test_stale_invalid_ledger_cannot_prepare_decode_retry(self):
        self.app._finance_decode_retry_stock = "688259.SH"
        with patch.object(UI, "safe_json", side_effect=ValueError("bad")):
            self.app.prepare_finance_decode_retry()
        self.assertIn("无法核对最新待审账本", self.app.finance_diag_status.get())
        self.assertEqual(self.app.update_scope.get(), "全市场")

    def test_preparation_is_blocked_if_existing_update_process_running(self):
        self.app._finance_decode_retry_stock = "688259.SH"
        self.app.process = SimpleNamespace(poll=lambda: None)
        previous = self.app.update_scope.get()
        self.app.prepare_finance_decode_retry()
        self.assertEqual(self.app.update_scope.get(), previous)
        self.assertIn("已有任务运行", self.app.finance_diag_status.get())
        self.app.process = None

    def test_failed_diagnostic_cannot_leave_decode_retry_enabled(self):
        self.app._finance_decode_retry_stock = "688259.SH"
        self.app._finance_diag_running = True
        self.app._finance_diag_queue.put(("error", "blocked", None))
        self.app._poll_finance_diagnostic()
        self.assertIsNone(self.app._finance_decode_retry_stock)
        self.assertEqual(
            str(self.app.finance_decode_retry_button["state"]), "disabled")

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
