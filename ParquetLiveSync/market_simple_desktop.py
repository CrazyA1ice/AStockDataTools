"""Three-tab A-share data manager; reuses the established manual runner.

Execution selected by stock/date/type is PREVIEW ONLY until a bounded
executor is independently certified. Existing resume remains a separate,
explicitly labeled legacy operation behind the original mutex and gates.
"""
from __future__ import annotations

from datetime import date
import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from market_update_dashboard import (
    MODULE, WORK, UpdaterDashboard, safe_json, safe_refresh_limit,
)
from market_simple_ui_model import (
    MODULES, PERIODS, EXTRAS, InvalidSimplePlan, coverage_rows,
    initial_date, preview_request,
)
from market_daily_calendar_read import CalendarUnavailable, query_calendar


class SimpleMarketDashboard(UpdaterDashboard):
    """One entry, three tabs, no duplicated diagnostic wizard."""

    def __init__(self):
        self._default_date = ""
        self._coverage_snapshot = None
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
            header, text="A股数据管理中心",
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
            self.autopilot_status, self.last_run, self.autopilot_quality,
        ):
            ttk.Label(page, textvariable=variable, justify="left",
                      wraplength=1020).pack(anchor="w", pady=2)
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
            buttons, text="执行指定范围（待接入）", state="disabled")
        self.selected_run_button.pack(side="left", padx=10)
        self.preview_line = tk.StringVar(
            value="指定股票及日期重下载尚未接入安全执行器，仅可预览。")
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

    def _toggle_stock_entry(self):
        if self.update_scope.get() == "自选股票":
            self.stock_frame.pack(fill="x", pady=(0, 7),
                                  before=self.date_source.master if False else None)
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
        def worker():
            try:
                result = query_calendar(limit)
                self.after(0, lambda: self._apply_default_day(
                    result["last"], result["source"]))
            except (CalendarUnavailable, OSError, ValueError):
                self.after(0, lambda: self.date_source.set(
                    self.date_source.get() + "；QMT日历暂不可用"))
        threading.Thread(target=worker, daemon=True,
                         name="readonly-qmt-calendar").start()

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
        self.preview_line.set(
            "预览：%s / %s / %s 至 %s / %s。"
            " 定向执行尚未开放；不得将此选择交给原全市场任务。" %
            (result["mode"], quantity, result["start"], result["end"],
             "、".join(result["modules"])))

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
            self._coverage_snapshot = None

    def refresh(self):
        # Inherit all legacy safety checks, stage receipts and bounded log tail.
        super().refresh()
        self._refresh_coverage()


def main():
    if os.name != "nt":
        raise SystemExit("Windows desktop required")
    SimpleMarketDashboard().mainloop()


if __name__ == "__main__":
    main()
