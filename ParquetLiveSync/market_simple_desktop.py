"""Three-tab A-share data manager; reuses the established manual runner.

Execution selected by stock/date/type is PREVIEW ONLY until a bounded
executor is independently certified. Existing resume remains a separate,
explicitly labeled legacy operation behind the original mutex and gates.
"""
from __future__ import annotations

from datetime import date, datetime
import json
import os
import subprocess
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from market_update_dashboard import (
    MODULE, REPO, WORK, SHANGHAI, REVIEW_MODE, REVIEW_MAIN_REPO,
    UpdaterDashboard, safe_json, safe_refresh_limit,
)
from market_simple_ui_model import (
    MODULES, PERIODS, EXTRAS, InvalidSimplePlan, coverage_rows,
    initial_date, preview_request, finance_cache_refresh_scope,
    finance_pending_brief, finance_root_from_progress, finance_issue_report_view,
    finance_decode_retry_target, finance_decode_retry_window,
    finance_qmt_probe_view, extract_qmt_probe_receipt,
    finance_secondary_pilot_view, extract_finance_secondary_receipt,
    finance_secondary_timeout_stage, finance_capital_first_blocker_view,
)
from market_daily_calendar_read import CalendarUnavailable, query_calendar
import market_center_finance_pending_triage as P2
import market_center_finance_pending_snapshot_review as P3


def secondary_finance_python(canonical_repo: Path) -> Path:
    """Only the external financial pilot may use the optional isolated Python.

    The production QMT runner, the nine-table QMT probe and the GUI itself
    continue to use the canonical existing .venv. Never resolve an arbitrary
    interpreter path from external receipts, user text or source listings.
    """
    if not canonical_repo.is_absolute() or canonical_repo.is_symlink():
        raise InvalidSimplePlan("正式仓库目录无效")
    isolated = canonical_repo / ".venv-akshare"
    if isolated.exists() or isolated.is_symlink():
        if not isolated.is_dir() or isolated.is_symlink():
            raise InvalidSimplePlan("独立AKShare环境无效，不会回退到正式QMT Python")
        python = isolated / "Scripts" / "python.exe"
        if (not python.is_file() or python.is_symlink()
                or python.parent.is_symlink()):
            raise InvalidSimplePlan("独立AKShare环境不完整，请先完成安装")
        return python
    python = canonical_repo / ".venv" / "Scripts" / "python.exe"
    if (not python.is_file() or python.is_symlink()
            or python.parent.is_symlink()):
        raise InvalidSimplePlan("正式QMT Python不可用")
    return python


class SimpleMarketDashboard(UpdaterDashboard):
    """One entry, three tabs, no duplicated diagnostic wizard."""

    def __init__(self):
        self._default_date = ""
        self._coverage_snapshot = None
        self._calendar_receipts = queue.Queue()
        self._finance_diag_queue = queue.Queue()
        self._finance_diag_running = False
        self._finance_diag_text = ""
        self._finance_decode_retry_stock = None
        self._qmt_probe_running = False
        self._qmt_probe_queue = queue.Queue()
        self._secondary_finance_running = False
        self._secondary_finance_queue = queue.Queue()
        self._capital_review_running = False
        self._capital_review_queue = queue.Queue()
        super().__init__()
        self._resolve_default_session()

    def setup(self):
        self.title("A股数据管理中心")
        self.geometry("1160x770")
        self.minsize(880, 570)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        header = ttk.Frame(body)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(
            header, text=("A股数据管理中心 · 只读试运行"
                          if REVIEW_MODE else "A股数据管理中心"),
            font=("Microsoft YaHei UI", 17, "bold"),
        ).pack(side="left")
        ttk.Button(header, text="刷新", command=self.refresh).pack(side="right")

        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill="both", expand=True)
        overview = ttk.Frame(self.tabs, padding=10)
        update = ttk.Frame(self.tabs, padding=10)
        logs = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(overview, text="数据总览")
        self.tabs.add(update, text="下载 / 更新")
        self.tabs.add(logs, text="异常与日志")
        self._build_overview(overview)
        self._build_update(update)
        self._build_logs(logs)

    def _build_overview(self, page):
        for variable in (
            self.autopilot_status, self.last_run, self.finance,
            self.autopilot_quality,
        ):
            ttk.Label(page, textvariable=variable, justify="left",
                      wraplength=1020).pack(anchor="w", pady=2)
        self.finance_attention = tk.StringVar(value="财务待审：读取账本中")
        ttk.Label(page, textvariable=self.finance_attention, justify="left",
                  wraplength=1020).pack(anchor="w", pady=3)
        ttk.Label(
            page,
            text="数据范围来自已提交日期索引；未验证的缺口和多源结果均明确标注。",
        ).pack(anchor="w", pady=(4, 9))
        area = ttk.Frame(page)
        area.pack(fill="both", expand=True)
        columns = ("name", "first", "last", "updated", "multi")
        self.coverage_table = ttk.Treeview(
            area, columns=columns, show="headings", height=13)
        for col, title, width in (
            ("name", "数据", 155), ("first", "起始日期", 155),
            ("last", "最新数据日期", 160), ("updated", "最近更新", 160),
            ("multi", "多源核验", 125),
        ):
            self.coverage_table.heading(col, text=title)
            self.coverage_table.column(
                col, width=width, minwidth=90,
                stretch=(col != "name"))
        self.coverage_table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(
            area, orient="vertical", command=self.coverage_table.yview)
        self.coverage_table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.coverage_table.bind("<<TreeviewSelect>>", self._coverage_selected)
        self.coverage_detail = tk.StringVar(value="选择一项数据查看覆盖证据与待审情况")
        ttk.Label(page, textvariable=self.coverage_detail,
                  wraplength=1030, justify="left").pack(
                      anchor="w", pady=(8, 4))
        ttk.Button(page, text="检查财务问题（只读）",
                   command=self.show_finance_issues).pack(anchor="e", pady=(2, 0))
        ttk.Button(page, text="查看对应错误与日志",
                   command=lambda: self.tabs.select(2)).pack(
                       anchor="e")

    def _build_update(self, page):
        self.update_mode = tk.StringVar(value="增量更新")
        self.update_scope = tk.StringVar(value="全市场")
        self.date_start = tk.StringVar(value="")
        self.date_end = tk.StringVar(value="")
        self.date_source = tk.StringVar(value="正在确认最近交易日")
        self.module_vars = {name: tk.BooleanVar(value=True)
                            for name in MODULES}

        row = ttk.Frame(page)
        row.pack(fill="x", pady=(3, 8))
        ttk.Label(row, text="方式：").pack(side="left")
        for mode in ("增量更新", "重新下载并比对"):
            ttk.Radiobutton(row, text=mode, variable=self.update_mode,
                            value=mode).pack(side="left", padx=(5, 20))
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="范围：").pack(side="left")
        for scope in ("全市场", "自选股票"):
            ttk.Radiobutton(row, text=scope, variable=self.update_scope,
                            value=scope, command=self._toggle_stock_entry
                            ).pack(side="left", padx=(5, 20))
        self.stock_frame = ttk.Frame(page)
        ttk.Label(self.stock_frame,
                  text="股票代码（用逗号分隔，带.SH/.SZ/.BJ后缀）：").pack(anchor="w")
        self.stock_input = tk.Text(
            self.stock_frame, height=3, wrap="word",
            font=("Consolas", 10))
        self.stock_input.pack(fill="x")
        self.stock_input.insert("1.0", "000001.SZ, 600519.SH")

        row = ttk.Frame(page)
        row.pack(fill="x", pady=(3, 9))
        self.date_row = row
        ttk.Label(row, text="开始日期").pack(side="left")
        ttk.Entry(row, textvariable=self.date_start,
                  width=15).pack(side="left", padx=(8, 18))
        ttk.Label(row, text="结束日期").pack(side="left")
        ttk.Entry(row, textvariable=self.date_end,
                  width=15).pack(side="left", padx=(8, 18))
        ttk.Label(row, textvariable=self.date_source).pack(side="left")

        types = ttk.Frame(page)
        types.pack(fill="x", pady=(0, 10))
        ttk.Label(types, text="数据：").pack(side="left")
        for name in MODULES:
            ttk.Checkbutton(types, text=name, variable=self.module_vars[name]
                            ).pack(side="left", padx=(4, 18))
        buttons = ttk.Frame(page)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="检查选定范围",
                   command=self.preview_selection).pack(side="left")
        self.selected_run_button = ttk.Button(
            buttons, text="刷新财务缓存并检查历史（不入库）",
            command=self.run_scoped_finance_cache, state="disabled")
        self.selected_run_button.pack(side="left", padx=10)
        self.preview_line = tk.StringVar(
            value="可刷新自选股票的QMT财务缓存并进行九表历史核对，不自动入库。")
        self.update_mode.trace_add("write", self._scoped_button_state)
        self.update_scope.trace_add("write", self._scoped_button_state)
        for selected in self.module_vars.values():
            selected.trace_add("write", self._scoped_button_state)
        self._scoped_button_state()
        ttk.Label(page, textvariable=self.preview_line,
                  wraplength=1000, justify="left").pack(
                      anchor="w", pady=(10, 9))
        legacy = ttk.LabelFrame(
            page, text="当前已支持：原有全市场安全续更", padding=10)
        legacy.pack(fill="x", pady=8)
        self.run_button = ttk.Button(
            legacy, text="按既有游标继续更新",
            command=self.manual_update)
        self.run_button.pack(side="left")
        ttk.Label(
            legacy, text="独立于上方股票及日期选择；遵循原任务时间窗口、写锁和备份校验。",
            wraplength=650,
        ).pack(side="left", padx=(12, 0))
        # Original conservative runner uses these known-good bounds.
        self.finance_cap.set("200")
        self.adjust_cap.set("80")

    def _build_logs(self, page):
        ttk.Label(page, textvariable=self.info,
                  wraplength=1000).pack(anchor="w", pady=(0, 6))
        diagnosis = ttk.LabelFrame(
            page, text="财务待审 · 内置只读检查", padding=7)
        diagnosis.pack(fill="x", pady=(0, 6))
        actions = ttk.Frame(diagnosis)
        actions.pack(fill="x")
        self.finance_diag_button = ttk.Button(
            actions, text="检查财务问题（只读）",
            command=self.start_finance_diagnostic)
        self.finance_diag_button.pack(side="left")
        self.finance_decode_retry_button = ttk.Button(
            actions, text="定位解码异常股票（需确认刷新）",
            command=self.prepare_finance_decode_retry, state="disabled")
        self.finance_decode_retry_button.pack(side="left", padx=8)
        self.qmt_table_probe_button = ttk.Button(
            actions, text="检查QMT九表（只读）",
            command=self.start_qmt_finance_table_probe, state="disabled")
        self.qmt_table_probe_button.pack(side="left", padx=8)
        ttk.Button(actions, text="复制诊断摘要",
                   command=self.copy_finance_diagnostic).pack(
                       side="left", padx=8)
        self.finance_diag_status = tk.StringVar(
            value="点击检查后，后台清点全部待审股票的九表本地元数据；不会下载或改写数据。")
        ttk.Label(diagnosis, textvariable=self.finance_diag_status,
                  justify="left", wraplength=980).pack(
                      anchor="w", pady=(5, 2))
        self.finance_diag_detail = tk.StringVar(value="")
        ttk.Label(diagnosis, textvariable=self.finance_diag_detail,
                  justify="left", wraplength=980).pack(anchor="w")
        self.qmt_probe_detail = tk.StringVar(value="")
        self.qmt_probe_output = tk.Text(
            diagnosis, height=5, wrap="word", state="disabled",
            font=("Consolas", 9))
        self.qmt_probe_output.pack(fill="x", pady=(5, 0))
        external_actions = ttk.Frame(diagnosis)
        external_actions.pack(fill="x", pady=(6, 1))
        self.secondary_finance_button = ttk.Button(
            external_actions, text="QMT异常首张报表核验（只读）",
            command=self.start_secondary_finance_pilot)
        self.secondary_finance_button.pack(side="left")
        self.capital_review_button = ttk.Button(
            external_actions, text="Capital首阻断分类（只读）",
            command=self.start_capital_first_blocker_review)
        self.capital_review_button.pack(side="left", padx=8)
        self.capital_review_detail = tk.StringVar(value=(
            "只读取正式QMT待审账本及Capital历史快照文件元数据；"
            "不连接QMT，不查东方财富，不定位实际冲突报告期。"))
        ttk.Label(diagnosis, textvariable=self.capital_review_detail,
                  wraplength=980, justify="left").pack(anchor="w")
        self.secondary_finance_detail = tk.StringVar(value=(
            "只核验QMT账本已标记的第一张异常报表（Balance/Income/CashFlow）；"
            "不抓全市场公告，不修改历史冲突或正式数据。"))
        ttk.Label(diagnosis, textvariable=self.secondary_finance_detail,
                  wraplength=980, justify="left").pack(anchor="w")
        stage = ttk.LabelFrame(page, text="最近任务 · 分阶段状态", padding=7)
        stage.pack(fill="x")
        cols = ("execution", "quality", "cross", "log")
        self.tree = ttk.Treeview(
            stage, columns=cols, show="headings", height=4)
        for col, title, width in (
            ("execution", "阶段", 170), ("quality", "数据核验", 180),
            ("cross", "跨源核验", 170), ("log", "日志", 310),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=True)
        self.tree.pack(fill="x")
        line = ttk.Frame(page)
        line.pack(fill="x", pady=8)
        ttk.Label(line, text="日志").pack(side="left")
        self.log_combo = ttk.Combobox(line, state="readonly", width=58)
        self.log_combo.pack(side="left", fill="x", expand=True, padx=6)
        self.log_combo.bind("<<ComboboxSelected>>", self.select_log)
        ttk.Checkbutton(line, text="跟随最新",
                        variable=self.auto_follow).pack(side="left")
        ttk.Button(line, text="打开文件", command=self.open_log).pack(
            side="left", padx=5)
        ttk.Button(line, text="打开日志目录", command=self.open_folder).pack(
            side="left", padx=5)
        display = ttk.Frame(page)
        display.pack(fill="both", expand=True)
        self.output = tk.Text(
            display, wrap="none", font=("Consolas", 9),
            bg="#101827", fg="#E5E7EB")
        y = ttk.Scrollbar(
            display, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=y.set)
        self.output.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")

    def show_finance_issues(self):
        self.tabs.select(2)
        self.start_finance_diagnostic()

    def start_finance_diagnostic(self):
        """One-click local metadata check, isolated from the daily QMT writer."""
        if self._finance_diag_running:
            return
        if self._qmt_probe_running:
            self.finance_diag_status.set(
                "QMT逐表检查仍在运行；完成后再重新读取财务待审账本。")
            return
        self._finance_diag_running = True
        self._finance_decode_retry_stock = None
        self.finance_decode_retry_button.configure(state="disabled")
        self.qmt_table_probe_button.configure(state="disabled")
        self.qmt_probe_detail.set("")
        self.qmt_probe_output.configure(state="normal")
        self.qmt_probe_output.delete("1.0", "end")
        self.qmt_probe_output.configure(state="disabled")
        self.finance_diag_status.set(
            "后台检查中：不连接QMT、不下载、不写入正式财务数据。")
        self.finance_diag_button.configure(state="disabled")

        def worker():
            try:
                progress = safe_json(
                    WORK / "qmt_extra" / "financial-cache-progress.json")
                root = finance_root_from_progress(progress)
                from market_scoped_finance_pending_full_census import census
                report = census(root, WORK / "qmt_extra",
                                page=1, page_size=3)
                detail = finance_issue_report_view(report)
                target = finance_decode_retry_target(report)
                self._finance_diag_queue.put(("ok", detail, target))
            except Exception as exc:
                # Show a bounded diagnostic, never auto-retry or auto-repair.
                message = str(exc)[:120]
                if "RESERVED_2005" in message:
                    message = "北京时间19:50—20:25为正式更新保护时段，请之后再检查"
                self._finance_diag_queue.put((
                    "error", "检查未完成：" + message +
                    "。原有财务数据和待审记录未由本功能修改。", None))

        threading.Thread(target=worker, daemon=True,
                         name="readonly-finance-issue-check").start()
        self.after(250, self._poll_finance_diagnostic)

    def _poll_finance_diagnostic(self):
        try:
            state, detail, target = self._finance_diag_queue.get_nowait()
        except queue.Empty:
            if self._finance_diag_running:
                self.after(250, self._poll_finance_diagnostic)
            return
        self._finance_diag_running = False
        self.finance_diag_button.configure(state="normal")
        self._finance_diag_text = detail
        self._finance_decode_retry_stock = target if state == "ok" else None
        self.finance_decode_retry_button.configure(
            state="normal" if self._finance_decode_retry_stock
            and self.process is None and not REVIEW_MODE else "disabled")
        self.qmt_table_probe_button.configure(
            state="normal" if self._finance_decode_retry_stock
            and self.process is None and not self._qmt_probe_running
            else "disabled")
        if state == "ok":
            self.finance_diag_status.set(
                "已检查：全体待审股票的本地九表元数据。来源冲突仍待复核，未获入库授权。")
        else:
            self.finance_diag_status.set("只读检查被阻断：没有执行任何修复")
        self.finance_diag_detail.set(detail)

    def start_qmt_finance_table_probe(self):
        """Explicit one-stock QMT cache reads; no download and no file output."""
        code = self._finance_decode_retry_stock
        if not code or self._qmt_probe_running or self.process is not None:
            return
        try:
            now = datetime.now(SHANGHAI)
            minute = now.hour * 60 + now.minute
            if 19 * 60 + 50 <= minute < 20 * 60 + 25:
                raise InvalidSimplePlan("北京时间19:50—20:25正在保护正式更新任务")
            progress = safe_json(
                WORK / "qmt_extra" / "financial-cache-progress.json")
            pending = progress.get("pending", {})
            if (not isinstance(pending, dict)
                    or not isinstance(pending.get(code), dict)
                    or pending[code].get("reason") != "CACHE_DECODE_ERROR"):
                raise InvalidSimplePlan("待审状态已变化，请重新运行本地只读检查")
            qmt_repo = Path(REVIEW_MAIN_REPO) if REVIEW_MODE else REPO
            python = qmt_repo / ".venv" / "Scripts" / "python.exe"
            worker_file = MODULE / "qmt_extra_financial_cache_worker.py"
            if (os.name != "nt" or not (qmt_repo / ".git").is_dir()
                    or (qmt_repo / ".git").is_symlink()
                    or not python.is_file() or python.is_symlink()
                    or not worker_file.is_file() or worker_file.is_symlink()):
                raise InvalidSimplePlan("正式Windows环境或QMT只读检查组件不可用")
        except (InvalidSimplePlan, OSError, ValueError, TypeError) as exc:
            self.qmt_probe_detail.set("QMT逐表检查已阻断：" + str(exc)[:120])
            return
        self._qmt_probe_running = True
        self.qmt_table_probe_button.configure(state="disabled")
        self.qmt_probe_detail.set("正在读取 " + code +
                                  " 的九张本地缓存表；不下载、不写入。")
        def worker():
            try:
                result = subprocess.run(
                    [str(python), "-u", "-B", str(worker_file),
                     "--symbols", code, "--probe-readonly"],
                    cwd=str(qmt_repo), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    check=False, timeout=45,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if (result.returncode != 0 or not isinstance(result.stdout, bytes)
                        or len(result.stdout) > 16384):
                    raise ValueError("QMT未连接、检查超时之外的异常或输出过大")
                # QMT may print GBK console logs; only the tagged JSON is UTF-8.
                receipt = extract_qmt_probe_receipt(result.stdout)
                view = finance_qmt_probe_view(receipt, code)
                self._qmt_probe_queue.put(("ok", view))
            except (OSError, ValueError, UnicodeError, TypeError,
                    subprocess.TimeoutExpired) as exc:
                self._qmt_probe_queue.put((
                    "error", "QMT逐表检查未完成：" + type(exc).__name__ +
                    "。没有下载或写入财务数据；请检查QMT客户端。"))
        threading.Thread(target=worker, daemon=True,
                         name="readonly-qmt-table-probe").start()
        self.after(250, self._poll_qmt_finance_table_probe)

    def _poll_qmt_finance_table_probe(self):
        try:
            state, summary = self._qmt_probe_queue.get_nowait()
        except queue.Empty:
            if self._qmt_probe_running:
                self.after(250, self._poll_qmt_finance_table_probe)
            return
        self._qmt_probe_running = False
        self.qmt_table_probe_button.configure(
            state="normal" if self._finance_decode_retry_stock
            and self.process is None else "disabled")
        self.qmt_probe_detail.set(summary)
        self.qmt_probe_output.configure(state="normal")
        self.qmt_probe_output.delete("1.0", "end")
        self.qmt_probe_output.insert("1.0", summary)
        self.qmt_probe_output.configure(state="disabled")

    def start_capital_first_blocker_review(self):
        """Only P2/P3 ledger and filename metadata, never cache or source API."""
        if self._capital_review_running:
            return
        if (self._finance_diag_running or self._secondary_finance_running
                or self._qmt_probe_running or self.process is not None):
            self.capital_review_detail.set(
                "其他财务任务仍在运行；Capital只读分类未启动。")
            return
        try:
            now = datetime.now(SHANGHAI)
            minute = now.hour * 60 + now.minute
            if 19 * 60 + 50 <= minute < 20 * 60 + 25:
                raise InvalidSimplePlan("北京时间19:50—20:25保护正式20:05任务")
            progress = safe_json(
                WORK / "qmt_extra" / "financial-cache-progress.json")
            root = finance_root_from_progress(progress)
            repo = Path(REVIEW_MAIN_REPO) if REVIEW_MODE else REPO
            state_module = repo / "ParquetLiveSync"
            market_root = root / "AllCycleAStockData"
            if (not repo.is_absolute() or repo.is_symlink()
                    or not state_module.is_dir()
                    or state_module.is_symlink()
                    or not market_root.is_dir()
                    or market_root.is_symlink()):
                raise InvalidSimplePlan("正式只读账本或Capital快照目录不可用")
        except (OSError, ValueError, TypeError, InvalidSimplePlan) as exc:
            self.capital_review_detail.set(
                "Capital分类未启动：" + str(exc)[:120])
            return
        self._capital_review_running = True
        self.capital_review_button.configure(state="disabled")
        self.capital_review_detail.set(
            "正在核对正式待审账本与Capital历史快照元数据；"
            "不读取任何财务数值，不发外部请求。")

        def worker():
            try:
                first = P2.summarize_pending(state_module)
                metadata = P3.review(state_module, market_root)
                # Both summaries must refer to the same immutable ledger.
                summary = finance_capital_first_blocker_view(first, metadata)
                self._capital_review_queue.put(("ok", summary))
            except Exception as exc:
                # Do not disclose raw ledger, filenames or financial values.
                self._capital_review_queue.put((
                    "error", "Capital分类未完成：" + type(exc).__name__ +
                    "；只读审计已停止，正式数据与待审账本未修改。"))
        threading.Thread(target=worker, daemon=True,
                         name="readonly-capital-first-blocker").start()
        self.after(250, self._poll_capital_first_blocker_review)

    def _poll_capital_first_blocker_review(self):
        try:
            state, detail = self._capital_review_queue.get_nowait()
        except queue.Empty:
            if self._capital_review_running:
                self.after(250, self._poll_capital_first_blocker_review)
            return
        self._capital_review_running = False
        self.capital_review_button.configure(state="normal")
        self.capital_review_detail.set(detail)

    def start_secondary_finance_pilot(self):
        """External leads + verified QMT snapshots, never run a writer."""
        if (self._secondary_finance_running or self._qmt_probe_running
                or self._finance_diag_running or self.process is not None):
            self.secondary_finance_detail.set(
                "其他任务运行中；外部财务只读检查未启动。")
            return
        try:
            now = datetime.now(SHANGHAI)
            minute = now.hour * 60 + now.minute
            if 19 * 60 + 50 <= minute < 20 * 60 + 25:
                raise InvalidSimplePlan(
                    "北京时间19:50—20:25为正式更新保护时段")
            progress = safe_json(
                WORK / "qmt_extra" / "financial-cache-progress.json")
            root = finance_root_from_progress(progress)
            pending = progress.get("pending")
            if not isinstance(pending, dict):
                raise InvalidSimplePlan("正式财务待审账本不可用")
            conflicts = sorted(
                (code, P2._parse_first_conflict(
                    code, entry.get("detail"))[0])
                for code, entry in pending.items()
                if isinstance(entry, dict)
                and entry.get("reason") == "SOURCE_HISTORY_CONFLICT")
            if not conflicts:
                raise InvalidSimplePlan("没有待核验的历史来源冲突股票")
            # Ledger only names the FIRST blocker. Capital and other nine-table
            # blockers do not justify requesting any of the three EM statements.
            eligible = [(code, table) for code, table in conflicts
                        if table in ("Balance", "Income", "CashFlow")]
            if not eligible:
                raise InvalidSimplePlan(
                    "待审账本未发现可由东财三表对应的首张冲突表；"
                    "Capital等异常保留QMT专项处理，不做无关外部查询")
            selected, first_table = [eligible[0][0]], eligible[0][1]
            known = sorted(pending)[:500]
            canonical_repo = Path(REVIEW_MAIN_REPO) if REVIEW_MODE else REPO
            python = secondary_finance_python(canonical_repo)
            script = MODULE / "market_finance_secondary.py"
            if (os.name != "nt" or not (canonical_repo / ".git").is_dir()
                    or (canonical_repo / ".git").is_symlink()
                    or not script.is_file() or script.is_symlink()):
                raise InvalidSimplePlan(
                    "正式Windows Python或独立财务源组件不可用")
        except (OSError, ValueError, InvalidSimplePlan, TypeError) as exc:
            self.secondary_finance_detail.set(
                "跨源核验未启动：" + str(exc)[:130])
            return
        self._secondary_finance_running = True
        self.secondary_finance_button.configure(state="disabled")
        self.secondary_finance_detail.set(
            "只读核验QMT待审 " + selected[0] +
            " 首张冲突表 " + first_table +
            "；跳过公告与无关报表。报告期尚未精确定位，不会修改数据。")

        def worker():
            try:
                result = subprocess.run(
                    [str(python), "-u", "-B", str(script),
                     "--root", str(root),
                     "--symbols", ",".join(selected),
                     "--known-symbols", ",".join(known),
                     "--pending-first-blocker-only",
                     "--explicit-readonly"],
                    cwd=str(canonical_repo),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, check=False, timeout=120,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                receipt = extract_finance_secondary_receipt(
                    result.stdout, result.returncode)
                summary = finance_secondary_pilot_view(receipt)
                self._secondary_finance_queue.put(("ok", summary))
            except subprocess.TimeoutExpired as exc:
                self._secondary_finance_queue.put((
                    "error", "外部核验超过120秒，已停止本轮子进程；超时位置：" +
                    finance_secondary_timeout_stage(exc.stdout) +
                    "。没有修改正式数据。"))
            except InvalidSimplePlan as exc:
                self._secondary_finance_queue.put((
                    "error", "外部核验未完成：" + str(exc)[:150] +
                    "；没有修改正式数据。"))
            except (OSError, ValueError, UnicodeError, TypeError) as exc:
                self._secondary_finance_queue.put((
                    "error", "外部核验未完成：" + type(exc).__name__ +
                    "（未取得可信结果）；没有修改正式数据。"))
        threading.Thread(target=worker, daemon=True,
                         name="external-finance-readonly-pilot").start()
        self.after(250, self._poll_secondary_finance_pilot)

    def _poll_secondary_finance_pilot(self):
        try:
            state, summary = self._secondary_finance_queue.get_nowait()
        except queue.Empty:
            if self._secondary_finance_running:
                self.after(250, self._poll_secondary_finance_pilot)
            return
        self._secondary_finance_running = False
        self.secondary_finance_button.configure(state="normal")
        self.secondary_finance_detail.set(summary)

    def prepare_finance_decode_retry(self):
        """Prepare bounded vendor-cache refresh; NEVER launch it automatically."""
        if REVIEW_MODE:
            self.finance_diag_status.set("只读试运行禁止QMT缓存刷新；正式数据未修改。")
            return
        code = self._finance_decode_retry_stock
        if not code:
            self.finance_diag_status.set(
                "没有已确认的单只缓存解码异常；请先运行只读检查。")
            return
        if self.process is not None:
            self.finance_diag_status.set("已有任务运行，暂不能准备新的QMT缓存刷新。")
            return
        try:
            progress = safe_json(
                WORK / "qmt_extra" / "financial-cache-progress.json")
            pending = progress.get("pending", {})
            item = pending.get(code) if isinstance(pending, dict) else None
            if not isinstance(item, dict) or item.get("reason") != "CACHE_DECODE_ERROR":
                self._finance_decode_retry_stock = None
                self.finance_decode_retry_button.configure(state="disabled")
                self.finance_diag_status.set(
                    "解码异常的待审状态已变化；请重新点击只读检查。")
                return
        except (OSError, ValueError, TypeError):
            self.finance_diag_status.set(
                "无法核对最新待审账本；未准备QMT缓存刷新。")
            return
        start, end = finance_decode_retry_window()
        self.update_mode.set("增量更新")
        self.update_scope.set("自选股票")
        self._toggle_stock_entry()
        for name, selected in self.module_vars.items():
            selected.set(name == "财务")
        self.stock_input.delete("1.0", "end")
        self.stock_input.insert("1.0", code)
        self.date_start.set(start)
        self.date_end.set(end)
        self.date_source.set("仅预填最近31日公告窗口；不是全历史验证")
        self.preview_selection()
        self.tabs.select(1)
        self.finance_diag_status.set(
            "已定位 " + code + "；请先检查日期，再按“刷新财务缓存并检查历史"
            "（不入库）”并确认。此操作不会清除历史待审。")

    def copy_finance_diagnostic(self):
        """Copy a short, actionable receipt; no files are written."""
        if not self._finance_diag_text:
            self.finance_diag_status.set("尚无诊断摘要，请先点击“检查财务问题（只读）”。")
            return
        text = self._finance_diag_text
        if self.qmt_probe_detail.get():
            text += "\n\n" + self.qmt_probe_detail.get()
        if self.secondary_finance_detail.get():
            text += "\n\n" + self.secondary_finance_detail.get()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.finance_diag_status.set(
            "诊断摘要已复制；无需再提供数百项测试的完整输出。")

    def _scoped_button_state(self, *_):
        if hasattr(self, "finance_decode_retry_button"):
            self.finance_decode_retry_button.configure(
                state="normal" if self._finance_decode_retry_stock
                and self.process is None and not REVIEW_MODE else "disabled")
        if hasattr(self, "qmt_table_probe_button"):
            self.qmt_table_probe_button.configure(
                state="normal" if self._finance_decode_retry_stock
                and self.process is None and not self._qmt_probe_running
                else "disabled")
        enabled = (self.update_mode.get() == "增量更新"
                   and self.update_scope.get() == "自选股票"
                   and [name for name in MODULES if
                        self.module_vars[name].get()] == ["财务"]
                   and self.process is None and not REVIEW_MODE)
        self.selected_run_button.configure(
            state="normal" if enabled else "disabled")

    def run_scoped_finance_cache(self):
        """Explicit QMT local-cache update; no canonical Parquet import."""
        if REVIEW_MODE:
            messagebox.showwarning("只读试运行", "试运行不允许刷新QMT缓存或写入任何财务数据。")
            return
        if self.process is not None:
            messagebox.showwarning("已有任务运行", "请先等待当前任务结束")
            return
        try:
            plan = preview_request(
                mode=self.update_mode.get(), scope=self.update_scope.get(),
                stocks=self.stock_input.get("1.0", "end-1c"),
                start=self.date_start.get(), end=self.date_end.get(),
                modules=[name for name in MODULES if
                         self.module_vars[name].get()])
            scope = finance_cache_refresh_scope(plan)
            codes = scope["symbols"]
            script = MODULE / "run-scoped-qmt-finance-cache.ps1"
            python = REPO / ".venv" / "Scripts" / "python.exe"
            if (os.name != "nt" or not (REPO / ".git").is_dir()
                    or not script.is_file() or not python.is_file()):
                raise InvalidSimplePlan("仅允许正式Windows仓库执行，开发工作树禁止刷新QMT缓存")
        except (InvalidSimplePlan, ValueError, OSError) as exc:
            messagebox.showerror("范围检查未通过", str(exc))
            return
        if not messagebox.askyesno(
            "确认刷新QMT财务缓存",
            "股票：" + "、".join(codes) + "\n公告日期：" +
            plan["start"] + " 至 " + plan["end"] +
            "\n此操作会更新QMT客户端的财务缓存，但不会修改正式Parquet、"
            "H5、财务历史快照或待审游标。\n"
            "刷新后将自动核对九张财务表的旧版本；历史冲突会在日志中报告。\n本操作不代表多源认证或正式入库。继续吗？"
        ):
            return
        engine = (Path(os.environ.get("SystemRoot", r"C:\Windows")) /
                  "System32" / "WindowsPowerShell" / "v1.0" /
                  "powershell.exe")
        args = [
            str(engine), "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script), "-Symbols", ",".join(codes),
            "-StartDate", plan["start"], "-EndDate", plan["end"],
            "-ExplicitCacheRefresh",
        ]
        try:
            self.process = subprocess.Popen(
                args, cwd=str(REPO),
                creationflags=subprocess.CREATE_NEW_CONSOLE)
            self.last_process_rc = None
            self.info.set(
                "已启动QMT财务缓存刷新和九表只读历史预检；"
                "正式财务Parquet未入库，请到异常与日志页查看结果。")
            self.run_button.configure(state="disabled")
            self._scoped_button_state()
        except OSError as exc:
            self.process = None
            messagebox.showerror("启动失败", str(exc))

    def _toggle_stock_entry(self):
        if self.update_scope.get() == "自选股票":
            self.stock_frame.pack(fill="x", pady=(0, 7),
                                  before=self.date_row)
        else:
            self.stock_frame.pack_forget()

    def _apply_default_day(self, day, source):
        if not day:
            self.date_source.set(source)
            return
        # Once user changes either date, never silently reset their choices.
        current = (self.date_start.get(), self.date_end.get())
        if current not in (("", ""), (self._default_date, self._default_date)):
            return
        if not self._default_date or day >= self._default_date:
            self._default_date = day
            self.date_start.set(day)
            self.date_end.set(day)
            self.date_source.set(source)

    def _resolve_default_session(self):
        try:
            ledger = safe_json(WORK / "market_update" / "commits.json")
            fallback, source = initial_date(ledger)
        except (OSError, ValueError):
            fallback, source = "", "已提交交易日不可用"
        self._apply_default_day(fallback, source)
        limit = safe_refresh_limit()
        if REVIEW_MODE:
            self.date_source.set(
                self.date_source.get() + "；只读试运行未自动连接QMT日历")
            return
        def worker():
            try:
                result = query_calendar(limit)
                self._calendar_receipts.put((result["last"], result["source"]))
            except (CalendarUnavailable, OSError, ValueError):
                self._calendar_receipts.put((None, "QMT日历暂不可用"))
        threading.Thread(target=worker, daemon=True,
                         name="readonly-qmt-calendar").start()
        self.after(150, self._poll_calendar)

    def _poll_calendar(self):
        try:
            latest, source = self._calendar_receipts.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_calendar)
            return
        if latest is None:
            self.date_source.set(self.date_source.get() + "；" + source)
        else:
            self._apply_default_day(latest, source)

    def preview_selection(self):
        try:
            result = preview_request(
                mode=self.update_mode.get(),
                scope=self.update_scope.get(),
                stocks=self.stock_input.get("1.0", "end-1c"),
                start=self.date_start.get(), end=self.date_end.get(),
                modules=[name for name in MODULES if
                         self.module_vars[name].get()])
        except (InvalidSimplePlan, ValueError) as exc:
            self.preview_line.set("选定范围有误：" + str(exc))
            return
        quantity = (str(len(result["symbols"])) + "只"
                    if result["scope"] == "自选股票" else "全市场")
        text = ("预览：%s / %s / %s 至 %s / %s。" %
                (result["mode"], quantity, result["start"], result["end"],
                 "、".join(result["modules"])))
        try:
            finance_cache_refresh_scope(result)
        except InvalidSimplePlan:
            text += " 定向执行尚未开放；不会将此范围偷换成全市场更新。"
        else:
            text += " 可刷新QMT财务缓存并核对九表；不代表正式入库或多源核验。"
        self.preview_line.set(text)

    def _coverage_selected(self, _event=None):
        selected = self.coverage_table.selection()
        if selected:
            meta = self.coverage_table.item(selected[0], "values")
            if meta and hasattr(self, "_coverage_detail_by_key"):
                self.coverage_detail.set(
                    self._coverage_detail_by_key.get(meta[0],
                                                     "本轮证据暂不可用"))

    def _refresh_coverage(self):
        try:
            ledger = safe_json(WORK / "market_update" / "commits.json")
            receipt = safe_json(WORK / "last-afternoon-unified.json")
            progress = safe_json(WORK / "qmt_extra" /
                                 "financial-cache-progress.json")
            self.finance_attention.set(finance_pending_brief(progress))
            rows = coverage_rows(ledger, receipt, progress)
            frozen = tuple(tuple(r[k] for k in
                                 ("name", "begin", "end", "updated",
                                  "multi_source", "detail")) for r in rows)
            if frozen == self._coverage_snapshot:
                return
            self._coverage_snapshot = frozen
            self._coverage_detail_by_key = {
                r["name"]: r["detail"] for r in rows}
            selected = self.coverage_table.selection()
            name = (self.coverage_table.item(selected[0], "values")[0]
                    if selected else None)
            self.coverage_table.delete(*self.coverage_table.get_children())
            for r in rows:
                ident = self.coverage_table.insert(
                    "", "end", values=(
                        r["name"], r["begin"], r["end"],
                        r["updated"], r["multi_source"]))
                if r["name"] == name:
                    self.coverage_table.selection_set(ident)
        except (ValueError, OSError, TypeError) as exc:
            self.coverage_detail.set("覆盖索引读取失败：" +
                                     type(exc).__name__)
            self.finance_attention.set("财务待审：账本读取未核实，不能认定无异常")
            self._coverage_snapshot = None

    def refresh(self):
        # Inherit all legacy safety checks, stage receipts and bounded log tail.
        super().refresh()
        if REVIEW_MODE:
            self.run_button.configure(state="disabled")
        self._scoped_button_state()
        self._refresh_coverage()

    def manual_update(self):
        if REVIEW_MODE:
            messagebox.showwarning("只读试运行", "试运行不允许启动正式行情更新。")
            return
        return super().manual_update()


def main():
    if os.name != "nt":
        raise SystemExit("Windows desktop required")
    SimpleMarketDashboard().mainloop()


if __name__ == "__main__":
    main()
