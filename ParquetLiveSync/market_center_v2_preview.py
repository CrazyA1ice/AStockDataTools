"""A股数据更新与核验中心 V2-B: read-only Tkinter UI and bounded history audit.

This is NOT a replacement for the working 20:05 scheduled task, updater,
audit engine, or original market_update_dashboard.py. There is intentionally
no subprocess.Popen, QMT import, data download, task install or Apply button.
"""
from __future__ import annotations

from datetime import date
import argparse
import json
import os
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from market_center_v2_model import (
    MODULES, HISTORY_POLICIES, InvalidPlan, latest_status, parse_symbols, plan_preview,
    safe_cutoff, source_info,
)

from market_center_v2_audit_cli import audited_query
from market_center_v2_readonly_audit import AuditBlocked, FROZEN_ASOF, PERIODS

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"

STAGES = (
    ("EIGHT_PERIODS", "八周期行情"),
    ("SECTORS", "板块"),
    ("ADJUSTMENTS_ROTATING", "除权"),
    ("FINANCIAL_DAILY", "财务"),
)
LABEL_FONT = ("Microsoft YaHei UI", 10)
TITLE_FONT = ("Microsoft YaHei UI", 18, "bold")
COLORS = {
    "bg": "#F3F7FD",
    "surface": "#FFFFFF",
    "navy": "#172B4D",
    "text": "#263E5E",
    "muted": "#687C96",
    "blue": "#1769D1",
    "blue_hover": "#0D55B6",
    "blue_tint": "#E8F2FF",
    "border": "#D8E3F1",
    "green": "#17824C",
    "red": "#C53B42",
    "amber": "#A66A0A",
    "log_bg": "#101E31",
    "log_fg": "#E9F2FF",
}


def apply_theme(root: tk.Tk):
    """No third-party theme; uses Tkinter's built-in clam for Windows ttk colors."""
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=COLORS["bg"])
    style.configure(".", font=LABEL_FONT, foreground=COLORS["text"],
                    background=COLORS["bg"])
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("TLabelframe", background=COLORS["surface"],
                    bordercolor=COLORS["border"], relief="solid")
    style.configure("TLabelframe.Label", background=COLORS["surface"],
                    foreground=COLORS["navy"], font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("Card.TLabelframe", background=COLORS["surface"],
                    bordercolor=COLORS["border"])
    style.configure("Card.TLabelframe.Label", background=COLORS["surface"],
                    foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
    style.configure("CardValue.TLabel", background=COLORS["surface"],
                    foreground=COLORS["navy"], font=("Microsoft YaHei UI", 13, "bold"))
    for name, color in (("Success", COLORS["green"]), ("Failure", COLORS["red"]),
                        ("Warning", COLORS["amber"]), ("Neutral", COLORS["navy"])):
        style.configure(name + ".CardValue.TLabel",
                        background=COLORS["surface"], foreground=color,
                        font=("Microsoft YaHei UI", 13, "bold"))
        style.configure(name + ".Section.TLabel",
                        background=COLORS["surface"], foreground=color)
    style.configure("Section.TLabel", background=COLORS["surface"],
                    foreground=COLORS["text"])
    style.configure("Muted.TLabel", foreground=COLORS["muted"])
    style.configure("AppTitle.TLabel", foreground=COLORS["navy"],
                    font=TITLE_FONT)
    style.configure("Primary.TButton", background=COLORS["blue"],
                    foreground=COLORS["surface"], bordercolor=COLORS["blue"],
                    padding=(14, 8), font=("Microsoft YaHei UI", 10, "bold"))
    style.map("Primary.TButton",
              background=[("active", COLORS["blue_hover"])],
              foreground=[("active", COLORS["surface"])])
    style.configure("TButton", padding=(11, 6), background=COLORS["blue_tint"],
                    foreground=COLORS["blue"], bordercolor=COLORS["border"])
    style.map("TButton", background=[("active", "#D3E7FF")])
    style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background="#E3EBF7",
                    foreground=COLORS["muted"], padding=(19, 8))
    style.map("TNotebook.Tab",
              background=[("selected", COLORS["surface"])],
              foreground=[("selected", COLORS["blue"])])
    style.configure("TRadiobutton", background=COLORS["surface"])
    style.configure("TCheckbutton", background=COLORS["surface"])
    style.configure("TEntry", fieldbackground=COLORS["surface"],
                    bordercolor=COLORS["border"], padding=5)
    return style


def _read_log_tail(path_text: str, *, limit: int = 40 * 1024,
                   work_dir: Path | None = None) -> str:
    """Only the bounded last part of an existing private work/afternoon log."""
    if not isinstance(path_text, str) or not path_text:
        return "暂无日志文件"
    path = Path(path_text)
    try:
        root = (work_dir or WORK).resolve(strict=True)
        real = path.resolve(strict=True)
        if (not real.is_relative_to(root) or real.suffix.lower() != ".log"
                or path.is_symlink() or not real.is_file()):
            return "日志路径不属于本地私有工作目录"
        with real.open("rb") as stream:
            size = real.stat().st_size
            if size > limit:
                stream.seek(size - limit)
                stream.readline()
            return stream.read(limit).decode("utf-8-sig", errors="replace")
    except OSError:
        return "日志文件尚不存在或暂不可读取"


class MarketCenterV2(tk.Tk):
    def __init__(self, *, state_module: Path = HERE,
                 market_root: Path | None = None,
                 evidence_file: Path | None = None,
                 evidence_sha256: str | None = None):
        super().__init__()
        self.state_module = Path(state_module)
        self.market_root = Path(market_root) if market_root is not None else None
        self.evidence_file = Path(evidence_file) if evidence_file is not None else None
        self.evidence_sha256 = evidence_sha256
        self.audit_queue = queue.Queue()
        self.audit_running = False
        self.state_work = self.state_module / "work"
        self.title("A股数据更新与核验中心 V2 · 设计预览")
        self.geometry("1080x710")
        self.minsize(900, 610)
        self.option_add("*Font", LABEL_FONT)
        self.app_style = apply_theme(self)
        self.mode = tk.StringVar(value="更新数据")
        self.scope = tk.StringVar(value="全部股票")
        self.history_policy = tk.StringVar(value=HISTORY_POLICIES[0])
        self.audit_period = tk.StringVar(value="day")
        cutoff = safe_cutoff()
        self.start = tk.StringVar(value=cutoff.replace(day=1).isoformat())
        self.end = tk.StringVar(value=cutoff.isoformat())
        self.modules = {name: tk.BooleanVar(value=True) for name in MODULES}
        self.stock_count = tk.StringVar(value="指定股票尚未填写")
        self.overview_info = tk.StringVar(value="尚未读取")
        self.last_run_details = tk.StringVar(value="最近任务历史记录尚未读取")
        self.status_line = tk.StringVar(value="V2-B：仅历史物理行情只读核验；更新和修复仍不开放")
        self.source_line = tk.StringVar(value="数据源：读取当前项目配置")
        self.plan_ready = None
        self.make_widgets()
        self.refresh_overview()

    def make_widgets(self):
        head = ttk.Frame(self, padding=(18, 14))
        head.pack(fill="x")
        ttk.Label(head, text="A股数据更新与核验中心", style="AppTitle.TLabel").pack(side="left")
        ttk.Label(head, text="● 只读核验  |  每晚 20:05 自动任务不变",
                  style="Muted.TLabel").pack(side="right")
        self.book = ttk.Notebook(self)
        self.book.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        self.home = ttk.Frame(self.book, padding=14)
        self.action = ttk.Frame(self.book, padding=14)
        self.logs = ttk.Frame(self.book, padding=14)
        self.audit_page = ttk.Frame(self.book, padding=14)
        self.book.add(self.home, text="  运行总览  ")
        self.book.add(self.action, text="  更新 / 核验  ")
        self.book.add(self.audit_page, text="  核验结果  ")
        self.book.add(self.logs, text="  运行日志  ")
        self.build_home()
        self.build_action()
        self.build_audit_results()
        self.build_logs()
        ttk.Label(self, textvariable=self.status_line, style="Muted.TLabel",
                  padding=(18, 5)).pack(fill="x")

    def build_home(self):
        top = ttk.Frame(self.home)
        top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, text="最近运行状态", font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        ttk.Button(top, text="刷新状态", command=self.refresh_overview).pack(side="right")
        tiles = ttk.Frame(self.home)
        tiles.pack(fill="x")
        self.cards = {}
        for label in ("已提交最新交易日", "上次任务结果", "当前安全截止", "QMT 最近预检", "财务待审"):
            card = ttk.LabelFrame(tiles, text=label, padding=12,
                                  style="Card.TLabelframe")
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            variable = tk.StringVar(value="—")
            display = ttk.Label(card, textvariable=variable, style="CardValue.TLabel",
                                wraplength=195)
            display.pack(anchor="w")
            self.cards[label] = variable
            self.card_widgets = getattr(self, "card_widgets", {})
            self.card_widgets[label] = display
        ttk.Label(self.home, textvariable=self.last_run_details,
                  style="Muted.TLabel").pack(anchor="w", pady=(9, 0))
        changed = ttk.LabelFrame(self.home, text="本次相比上次，有什么变化？", padding=14)
        changed.pack(fill="x", pady=(18, 12))
        ttk.Label(changed, textvariable=self.overview_info, wraplength=900,
                  style="Section.TLabel").pack(anchor="w")
        ttk.Label(changed, text="暂无可信前后快照时，仅显示证据不足，不推测新增量。",
                  style="Section.TLabel").pack(anchor="w", pady=(6, 0))
        phases = ttk.LabelFrame(self.home, text="上一次运行的四个阶段", padding=10)
        phases.pack(fill="x")
        self.stage_labels = {}
        for key, title in STAGES:
            var = tk.StringVar(value="暂无")
            self.stage_labels[key] = var
            line = ttk.Frame(phases)
            line.pack(fill="x", pady=4)
            ttk.Label(line, text=title, width=15, style="Section.TLabel").pack(side="left")
            stage_view = ttk.Label(line, textvariable=var, style="Neutral.Section.TLabel")
            stage_view.pack(side="left", fill="x")
            self.stage_widgets = getattr(self, "stage_widgets", {})
            self.stage_widgets[key] = stage_view
        actions = ttk.Frame(self.home)
        actions.pack(anchor="w", pady=(18, 0))
        ttk.Button(actions, text="配置更新范围", style="Primary.TButton",
                   command=lambda: self.go_action("更新数据")).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="配置数据核验", command=lambda: self.go_action("数据核验")).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="查看运行日志", command=lambda: self.book.select(self.logs)).pack(side="left")
        ttk.Label(self.home, text="已有日期可选择补缺失、对比或审核修复（写入功能待开放）  |  20:05任务运行期间只读核验需取得共享锁",
                  style="Muted.TLabel", wraplength=930).pack(anchor="w", pady=(18, 0))

    def build_action(self):
        # The configuration form can exceed a laptop-height window. Keep
        # every control reachable without enlarging the application.
        area = tk.Canvas(self.action, background=COLORS["bg"],
                         highlightthickness=0, borderwidth=0)
        vertical = ttk.Scrollbar(self.action, orient="vertical", command=area.yview)
        area.configure(yscrollcommand=vertical.set)
        vertical.pack(side="right", fill="y")
        area.pack(side="left", fill="both", expand=True)
        content = ttk.Frame(area, padding=(5, 5, 16, 18))
        window = area.create_window((0, 0), anchor="nw", window=content)
        content.bind("<Configure>",
                     lambda _event: area.configure(scrollregion=area.bbox("all")))
        area.bind("<Configure>",
                  lambda event: area.itemconfigure(window, width=event.width))
        top = ttk.Frame(content)
        top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, text="操作配置", font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        ttk.Label(top, text="● 历史行情只读核验已接入 · 写入仍关闭",
                  style="Muted.TLabel").pack(side="right")
        mode_row = ttk.LabelFrame(content, text="任务类型（共用下方同一组范围）", padding=8)
        mode_row.pack(fill="x", pady=(0, 10))
        for item in ("更新数据", "数据核验"):
            ttk.Radiobutton(mode_row, text=item, value=item, variable=self.mode).pack(side="left", padx=12)
        policy = ttk.LabelFrame(content, text="已有历史数据的处理方式（仅更新模式）", padding=10)
        policy.pack(fill="x", pady=(0, 10))
        for item in HISTORY_POLICIES:
            ttk.Radiobutton(policy, text=item, value=item, variable=self.history_policy).pack(
                side="left", padx=(3, 24))
        ttk.Label(policy, text="补缺失先核验；重新获取只比较；修复必须审核。三种写入功能均待开放。",
                  style="Section.TLabel").pack(anchor="w", pady=(8, 0))
        dates = ttk.LabelFrame(content, text="处理时间段 · 同时适用于更新和核验", padding=10)
        dates.pack(fill="x", pady=(0, 10))
        ttk.Label(dates, text="开始日期").pack(side="left")
        ttk.Entry(dates, textvariable=self.start, width=13).pack(side="left", padx=(8, 20))
        ttk.Label(dates, text="结束日期").pack(side="left")
        ttk.Entry(dates, textvariable=self.end, width=13).pack(side="left", padx=8)
        ttk.Label(dates, text="YYYY-MM-DD，北京时间 20:05 安全界限",
                  foreground="#687b92").pack(side="left", padx=12)
        stocks = ttk.LabelFrame(content, text="股票范围", padding=10)
        stocks.pack(fill="x", pady=(0, 10))
        bar = ttk.Frame(stocks)
        bar.pack(fill="x")
        for option in ("全部股票", "指定股票"):
            ttk.Radiobutton(bar, text=option, value=option,
                            variable=self.scope).pack(side="left", padx=(0, 14))
        ttk.Label(bar, textvariable=self.stock_count, foreground="#41678d").pack(side="right")
        ttk.Label(stocks, text="指定多只：输入 000001.SZ, 600519.SH，或换行粘贴；自动去重，最多 500 只。",
                  foreground="#637a91").pack(anchor="w", pady=(8, 2))
        stock_holder = ttk.Frame(stocks)
        stock_holder.pack(fill="x")
        self.stock_box = tk.Text(stock_holder, height=3, font=("Consolas", 10), wrap="word",
                                 background=COLORS["surface"], foreground=COLORS["navy"],
                                 selectbackground=COLORS["blue"])
        stock_scroll = ttk.Scrollbar(stock_holder, orient="vertical",
                                      command=self.stock_box.yview)
        self.stock_box.configure(yscrollcommand=stock_scroll.set)
        self.stock_box.pack(side="left", fill="x", expand=True)
        stock_scroll.pack(side="right", fill="y")
        self.stock_box.insert("1.0", "000001.SZ, 600519.SH")
        ttk.Button(stocks, text="检查股票列表", command=self.check_stocks).pack(anchor="e", pady=(4, 0))
        self.scope.trace_add("write", lambda *_: self.sync_stock_scope())
        self.sync_stock_scope()
        types = ttk.LabelFrame(content, text="数据类型（可多选）", padding=10)
        types.pack(fill="x", pady=(0, 10))
        for name in MODULES:
            ttk.Checkbutton(types, text=name, variable=self.modules[name]).pack(side="left", padx=(6, 25))
        sources = ttk.LabelFrame(content, text="数据来源 · 自动按现有配置选择，不允许手选", padding=10)
        sources.pack(fill="x", pady=(0, 10))
        ttk.Label(sources, textvariable=self.source_line, wraplength=940,
                  justify="left", style="Section.TLabel").pack(anchor="w")
        preview = ttk.LabelFrame(content, text="任务预览 / 执行门禁", padding=10)
        preview.pack(fill="both", expand=True)
        self.preview_text = tk.Text(preview, height=5, font=("Microsoft YaHei UI", 10),
                                    wrap="word", borderwidth=0, padx=12, pady=10,
                                    background="#EDF5FF", foreground=COLORS["navy"])
        self.preview_text.pack(fill="x")
        self.preview_text.insert("1.0", "请检查日期、股票及数据类型后点击「预览任务」。\n"
                                           "目前不提供真实执行入口，防止把定向任务错误地变为全市场写入。")
        self.preview_text.configure(state="disabled")
        row = ttk.Frame(preview)
        row.pack(fill="x", pady=(9, 0))
        ttk.Button(row, text="预览任务", style="Primary.TButton",
                   command=self.show_preview).pack(side="left")
        ttk.Button(row, text="复制计划", command=self.copy_preview).pack(side="left", padx=10)
        ttk.Label(row, text="历史数据可重查，但不能盲目覆盖；运行中的任务拥有互斥锁",
                  style="Section.TLabel").pack(side="right")
        audit_bar = ttk.Frame(content)
        audit_bar.pack(fill="x", pady=(12, 0))
        ttk.Label(audit_bar, text="只读核验周期（首版每次一个）").pack(side="left")
        ttk.Combobox(audit_bar, state="readonly", width=12,
                     textvariable=self.audit_period,
                     values=PERIODS).pack(side="left", padx=8)
        self.audit_button = ttk.Button(audit_bar, text="开始历史行情只读核验",
                                       style="Primary.TButton", command=self.run_readonly_audit)
        self.audit_button.pack(side="left", padx=8)
        if self.market_root is None:
            self.audit_button.configure(state="disabled")
        ttk.Label(audit_bar, text="需指定行情根目录；仅限20只股票、31日、截至2026-11-19",
                  style="Muted.TLabel").pack(side="left", padx=8)

    def build_audit_results(self):
        ttk.Label(self.audit_page, text="历史行情核验 · 结果总览",
                  font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(self.audit_page,
                  text="已出现记录 ≠ 官方完整；未出现记录 ≠ 确认缺失。条件证据只有文件完整性校验，不能当作独立来源认证。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 9))
        top = ttk.Frame(self.audit_page)
        top.pack(fill="x", pady=(0, 10))
        self.audit_cards = {}
        for label in ("已观察记录", "异常待复核", "未观察/待确认", "缺失候选"):
            tile = ttk.LabelFrame(top, text=label, style="Card.TLabelframe", padding=10)
            tile.pack(side="left", fill="x", expand=True, padx=(0, 9))
            value = tk.StringVar(value="—")
            display = ttk.Label(tile, textvariable=value, style="CardValue.TLabel")
            display.pack(anchor="w")
            self.audit_cards[label] = value
        self.audit_evidence_note = tk.StringVar(value="尚无核验记录")
        ttk.Label(self.audit_page, textvariable=self.audit_evidence_note,
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 7))
        frame = ttk.LabelFrame(self.audit_page, text="逐股票 · 周期 · 日期观察明细", padding=8)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = ("period", "symbol", "date", "count", "physical", "interpretation")
        self.audit_table = ttk.Treeview(frame, columns=columns, show="headings",
                                        selectmode="browse", height=12)
        headings = (
            ("period", "周期", 90),
            ("symbol", "股票", 110),
            ("date", "时间戳标签日", 130),
            ("count", "行数", 70),
            ("physical", "物理观察", 180),
            ("interpretation", "证据判定（非认证）", 280),
        )
        for key, title, width in headings:
            self.audit_table.heading(key, text=title)
            self.audit_table.column(key, width=width, stretch=(key == "interpretation"))
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.audit_table.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.audit_table.xview)
        self.audit_table.configure(yscrollcommand=vertical.set,
                                   xscrollcommand=horizontal.set)
        self.audit_table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.audit_table.tag_configure("alert", foreground=COLORS["red"])
        self.audit_table.tag_configure("candidate", foreground=COLORS["amber"])
        self.audit_table.tag_configure("neutral", foreground=COLORS["navy"])
        self.audit_table.bind("<<TreeviewSelect>>", self._select_audit_row)
        self.audit_table_rows = {}
        control = ttk.Frame(self.audit_page)
        control.pack(fill="x", pady=(9, 0))
        self.audit_details_button = ttk.Button(
            control, text="展开原始核验证据", command=self._toggle_audit_details)
        self.audit_details_button.pack(side="left")
        ttk.Label(control,
                  text="这不是数据修复按钮；没有官方交易日历和有效股票池时不可自动补缺失",
                  style="Muted.TLabel").pack(side="left", padx=12)
        self.audit_detail_frame = ttk.LabelFrame(
            self.audit_page, text="原始只读证据 / 当前选中条目", padding=8)
        self.audit_detail_frame.columnconfigure(0, weight=1)
        self.audit_detail_frame.rowconfigure(0, weight=1)
        self.audit_result_text = tk.Text(
            self.audit_detail_frame, wrap="none", height=8, font=("Consolas", 9),
            borderwidth=0, background=COLORS["log_bg"],
            foreground=COLORS["log_fg"], padx=10, pady=8)
        details_scroll = ttk.Scrollbar(
            self.audit_detail_frame, orient="vertical",
            command=self.audit_result_text.yview)
        self.audit_result_text.configure(yscrollcommand=details_scroll.set)
        self.audit_result_text.grid(row=0, column=0, sticky="nsew")
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.audit_details_visible = False
        self.audit_raw_report = (
            "请选择「数据核验」、指定股票、只勾选八周期行情，再选择核验周期。"
            "\n更新与修复仍不开放，核验过程不下载或写入行情。")
        self._set_audit_text(self.audit_raw_report)

    def _toggle_audit_details(self):
        if self.audit_details_visible:
            self.audit_detail_frame.pack_forget()
            self.audit_details_button.configure(text="展开原始核验证据")
            self.audit_details_visible = False
        else:
            self.audit_detail_frame.pack(fill="x", pady=(8, 0))
            self.audit_details_button.configure(text="收起原始核验证据")
            self.audit_details_visible = True

    def _select_audit_row(self, _event=None):
        selected = self.audit_table.selection()
        if selected and selected[0] in self.audit_table_rows:
            self._set_audit_text(json.dumps(
                self.audit_table_rows[selected[0]],
                ensure_ascii=False, indent=2))

    def run_readonly_audit(self):
        """Use only the explicitly chosen local root and narrow UI scope."""
        if self.audit_running:
            return
        if self.market_root is None:
            messagebox.showerror("行情目录未授权", "启动时需指定 --market-root 本机行情目录。")
            return
        if self.mode.get() != "数据核验" or self.scope.get() != "指定股票":
            messagebox.showinfo("请先选择范围", "请切换为「数据核验」和「指定股票」。")
            return
        chosen = [key for key in MODULES if self.modules[key].get()]
        if chosen != ["八周期行情"]:
            messagebox.showinfo("当前仅支持行情",
                                "V2-B 暂只提供八周期行情物理核验；请取消板块、除权、财务。")
            return
        try:
            selection = plan_preview(
                mode="数据核验", start=self.start.get().strip(),
                end=self.end.get().strip(), scope="指定股票",
                stock_text=self.stock_box.get("1.0", "end-1c"),
                modules=chosen, history_policy=self.history_policy.get())
            codes = selection["symbols"]
            if len(codes) > 20:
                raise InvalidPlan("本轮物理核验最多选择20只股票，请缩小范围")
            if selection["end_date"] > FROZEN_ASOF.isoformat():
                raise InvalidPlan("V2-B 冻结只读核验暂截至 2026-11-19")
        except InvalidPlan as exc:
            messagebox.showerror("核验范围不符合限制", str(exc))
            return
        period = self.audit_period.get()
        if period not in PERIODS:
            messagebox.showerror("周期无效", "请选择已支持的八周期之一")
            return
        if not messagebox.askyesno(
            "确认只读核验",
            "只读取本机选定 Parquet 的指定行组，不连接 QMT、不下载、不覆盖。\n"
            + "时间：" + selection["start_date"] + " 至 " + selection["end_date"]
            + "；周期：" + period + "；股票：" + str(len(codes)) + "只。\n"
            + "最多解压250万候选行，超限将拒绝并要求缩小范围。\n"
            + "没有读到记录不代表该交易日确实缺失。继续吗？"
        ):
            return
        self.audit_running = True
        self.audit_button.configure(state="disabled")
        old_rows = self.audit_table.get_children()
        if old_rows:
            self.audit_table.delete(*old_rows)
        self.audit_table_rows.clear()
        for field in self.audit_cards.values():
            field.set("—")
        self.audit_evidence_note.set("核验进行中，等待有界物理数据扫描与资格证据判断")
        self.book.select(self.audit_page)
        self._set_audit_text("只读历史行情核验正在执行。若任务同时启动，执行锁将阻止本次读取。")
        self.status_line.set("V2-B 有界只读核验运行中，不访问 QMT，不写入行情")
        def worker():
            try:
                result = audited_query(
                    root=self.market_root, start=selection["start_date"],
                    end=selection["end_date"], symbols=codes,
                    periods=[period], explicit_readonly=True,
                    evidence_file=self.evidence_file,
                    evidence_sha256=self.evidence_sha256)
                self.audit_queue.put(("result", result))
            except (AuditBlocked, OSError, ValueError) as exc:
                self.audit_queue.put(("error", str(exc)))
            except Exception as exc:
                self.audit_queue.put(("error", "只读核验未完成：" + type(exc).__name__))
        threading.Thread(target=worker, name="market-v2-readonly-audit", daemon=True).start()
        self.after(150, self._poll_audit)

    def _set_audit_text(self, value: str):
        self.audit_result_text.configure(state="normal")
        self.audit_result_text.delete("1.0", "end")
        self.audit_result_text.insert("1.0", value)
        self.audit_result_text.configure(state="disabled")
        self.audit_result_text.see("1.0")

    def _poll_audit(self):
        try:
            kind, data = self.audit_queue.get_nowait()
        except queue.Empty:
            if self.audit_running:
                self.after(150, self._poll_audit)
            return
        self.audit_running = False
        self.audit_button.configure(state="normal" if self.market_root else "disabled")
        if kind == "error":
            self.audit_evidence_note.set("核验已阻断：" + str(data)[:240])
            self.audit_raw_report = (
                "核验阻断（没有修改任何行情文件）\n" + str(data) +
                "\n请先排除任务占用、来源证据不一致或行组读取预算超限。")
            self._set_audit_text(self.audit_raw_report)
            if not self.audit_details_visible:
                self._toggle_audit_details()
            self.status_line.set("只读核验阻断；原始行情保持不变")
            return
        result = data.get("evidence_interpretation", {})
        rows = result.get("observations", [])
        old_rows = self.audit_table.get_children()
        if old_rows:
            self.audit_table.delete(*old_rows)
        self.audit_table_rows.clear()
        count_present = sum(row["interpretation"] == "RECORDS_PRESENT_NOT_CERTIFIED"
                            for row in rows)
        count_alert = sum(row["interpretation"] in (
            "PHYSICAL_ANOMALY_NEEDS_REVIEW",
            "PHYSICAL_SOURCE_DECLARATION_CONFLICT_UNVERIFIED")
                          for row in rows)
        count_candidate = sum(
            row["interpretation"] == "MISSING_CANDIDATE_SOURCE_AUTHENTICITY_UNVERIFIED"
            for row in rows)
        count_unobserved = sum(row["rows"] == 0 for row in rows)
        self.audit_cards["已观察记录"].set(str(count_present))
        self.audit_cards["异常待复核"].set(str(count_alert))
        self.audit_cards["未观察/待确认"].set(str(count_unobserved))
        self.audit_cards["缺失候选"].set(str(count_candidate))
        self.audit_evidence_note.set(
            "状态：只读物理观察完成 | 已解压候选行：" +
            str(data["row_group_budget"]["rows_inspected"]) +
            " | 资格证据：" +
            ("仅 SHA 完整性检查，来源未认证"
             if result.get("source_integrity_checked") else "未提供交易日历/股票状态证据")
            + " | 确认缺失：0（无自动补更）")
        status_names = {
            "RECORDS_PRESENT_NOT_CERTIFIED": "存在记录，未认证",
            "PHYSICAL_ANOMALY_NEEDS_REVIEW": "物理异常待复核",
            "PHYSICAL_SOURCE_DECLARATION_CONFLICT_UNVERIFIED": "物理记录与来源声明矛盾",
            "NO_ROWS_CALENDAR_AND_ELIGIBILITY_UNKNOWN": "无记录，证据不足",
            "NO_ROWS_NONTRADING_DECLARED_UNCERTIFIED": "声明非交易日，未认证",
            "NO_ROWS_PRELISTING_DECLARED_UNCERTIFIED": "声明上市前，未认证",
            "NO_ROWS_POSTLISTING_DECLARED_UNCERTIFIED": "声明退市后，未认证",
            "NO_ROWS_SUSPENDED_DECLARED_UNCERTIFIED": "声明停牌，未认证",
            "NO_ROWS_ELIGIBILITY_INDETERMINATE": "缺失判断仍不确定",
            "PHYSICAL_PARTITION_MISSING_STOCK_GAP_UNDETERMINED": "物理分区缺失，逐股待核实",
            "MISSING_CANDIDATE_SOURCE_AUTHENTICITY_UNVERIFIED": "疑似缺失，源未认证",
            "LONG_CYCLE_LABEL_NEEDS_CLOSURE_PROOF": "周/月需要闭合证明",
        }
        for row in rows[:600]:
            interpretation = row["interpretation"]
            tag = ("alert" if interpretation in (
                        "PHYSICAL_ANOMALY_NEEDS_REVIEW",
                        "PHYSICAL_SOURCE_DECLARATION_CONFLICT_UNVERIFIED")
                   else "candidate" if (
                       interpretation == "MISSING_CANDIDATE_SOURCE_AUTHENTICITY_UNVERIFIED"
                       or interpretation.startswith("NO_ROWS")) else "neutral")
            ident = self.audit_table.insert("", "end",
                values=(row["period"], row["symbol"], row["label_day"],
                        row["rows"], row["physical_status"],
                        status_names.get(interpretation, interpretation)),
                tags=(tag,))
            self.audit_table_rows[ident] = row
        self.audit_raw_report = json.dumps(
            {"scope": data["scope"], "source_partitions": data["source_partitions"],
             "missing_partitions": data["missing_partitions"],
             "row_group_budget": data["row_group_budget"],
             "evidence_interpretation": result,
             "market_file_writes": False, "qmt_calls": 0},
            ensure_ascii=False, indent=2)
        self._set_audit_text(self.audit_raw_report)
        self.status_line.set(
            "只读历史核验完成 · " + str(len(rows)) +
            " 条标签日观察；确认缺失为0，任何历史写入仍禁止")

    def build_logs(self):
        head = ttk.Frame(self.logs)
        head.pack(fill="x", pady=(0, 12))
        ttk.Label(head, text="最近任务原始日志", font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        ttk.Button(head, text="刷新日志", command=self.refresh_logs).pack(side="right")
        ttk.Label(self.logs, text="日志保留最近的末尾内容；右侧上下滚动、底部左右滚动，完整原始文件仍保存在本地。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        log_area = ttk.Frame(self.logs)
        log_area.pack(fill="both", expand=True)
        log_area.columnconfigure(0, weight=1)
        log_area.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_area, font=("Consolas", 10), wrap="none",
                                borderwidth=0, padx=12, pady=10,
                                background=COLORS["log_bg"], foreground=COLORS["log_fg"],
                                selectbackground=COLORS["blue"], insertbackground=COLORS["log_fg"])
        self.log_vertical_scroll = ttk.Scrollbar(
            log_area, orient="vertical", command=self.log_text.yview)
        self.log_horizontal_scroll = ttk.Scrollbar(
            log_area, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=self.log_vertical_scroll.set,
                                xscrollcommand=self.log_horizontal_scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_vertical_scroll.grid(row=0, column=1, sticky="ns")
        self.log_horizontal_scroll.grid(row=1, column=0, sticky="ew")
        self.log_text.configure(state="disabled")
        ttk.Button(self.logs, text="打开原日志文件夹", command=self.open_log_folder).pack(anchor="e", pady=8)

    def go_action(self, mode):
        self.mode.set(mode)
        self.book.select(self.action)

    def sync_stock_scope(self):
        if self.scope.get() == "指定股票":
            self.stock_box.configure(state="normal", background=COLORS["surface"])
            self.stock_count.set("可填写多只股票")
        else:
            self.stock_box.configure(state="disabled", background="#EAF0F8")
            self.stock_count.set("全部股票 · 无需输入")

    def check_stocks(self):
        if self.scope.get() == "全部股票":
            self.stock_count.set("全部股票 · 输入列表不参与当前计划")
            return
        try:
            parsed = parse_symbols(self.stock_box.get("1.0", "end-1c"))
        except InvalidPlan as exc:
            messagebox.showerror("股票代码有误", str(exc))
            return
        self.stock_count.set("有效、去重后：" + str(len(parsed)) + " 只")

    def show_preview(self):
        try:
            self.plan_ready = plan_preview(
                mode=self.mode.get(), start=self.start.get().strip(),
                end=self.end.get().strip(), scope=self.scope.get(),
                stock_text=self.stock_box.get("1.0", "end-1c"),
                modules=[n for n in MODULES if self.modules[n].get()],
                history_policy=self.history_policy.get(),
            )
        except InvalidPlan as exc:
            self.plan_ready = None
            messagebox.showerror("计划未通过输入校验", str(exc))
            return
        p = self.plan_ready
        # A committed-date frontier is not complete per-stock coverage. Only
        # warn of a possible intersection, never infer exact missing keys.
        try:
            latest = latest_status(self.state_module)["last_accepted_trading_day"]
        except (InvalidPlan, OSError):
            # Failure to read optional history must never turn into permission
            # to overwrite existing data or prevent safe previewing.
            latest = "未证明"
        overlap = ("所选日期与已提交行情可能重叠（最新已提交：" + latest
                   + "）；允许重新核验，更新时按所选策略处理。\n"
                   if latest != "未证明" and p["start_date"] <= latest else
                   "所选日期的股日完整覆盖尚未核对；不能推测存在或缺失。\n")
        description = (p["mode"] + " | " + p["start_date"] + " 至 " + p["end_date"] + "\n"
                       + "股票：" + (p["scope"] if p["scope"] == "全部股票"
                                    else ", ".join(p["symbols"])) + "\n"
                       + "数据：" + "、".join(p["data_types"]) + "\n"
                       + ("历史数据处理：" + p["history_policy"] + "（尚未开放写入）\n"
                          if p["mode"] == "更新数据" else "核验：限定范围内只读检查已有行情文件。\n")
                       + overlap
                       + "并发规则：20:05计划任务运行中不允许第二个写入任务。\n"
                       + "执行状态：真实更新/修复暂不开放。指定股票+八周期行情可单独执行有限只读核验。")
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", description)
        self.preview_text.configure(state="disabled")
        self.status_line.set("预览校验通过 · 不会自动更新或下载")

    def copy_preview(self):
        # Recalculate so changing dates, stock selection or mode cannot copy
        # an old, potentially misleading plan preview.
        self.show_preview()
        if self.plan_ready is None:
            return
        self.clipboard_clear()
        self.clipboard_append(json.dumps(self.plan_ready, ensure_ascii=False, indent=2))
        self.status_line.set("已复制只读任务预览（allowed_to_execute=false）")

    def refresh_overview(self):
        try:
            obj = latest_status(self.state_module)
            src = source_info(self.state_module)
            self.cards["已提交最新交易日"].set(obj["last_accepted_trading_day"])
            self.cards["上次任务结果"].set(str(obj["last_run_status"]))
            self.cards["当前安全截止"].set(obj["safe_candidate_cutoff"])
            self.cards["QMT 最近预检"].set(obj["qmt_last_preflight"])
            pending = obj["finance_pending_count"]
            self.cards["财务待审"].set(str(pending) + " 项" if pending is not None else "未记录")
            self.card_widgets["财务待审"].configure(
                style=("Warning.CardValue.TLabel" if pending is not None and pending > 0
                       else "Success.CardValue.TLabel" if pending == 0
                       else "Neutral.CardValue.TLabel"))
            self.last_run_details.set(
                "上次任务开始：" + str(obj["last_run_started"]) +
                "　｜　以上 QMT 预检是历史回执，不代表当前实时连接状态")
            run_status = str(obj["last_run_status"]).upper()
            self.card_widgets["上次任务结果"].configure(
                style=("Failure.CardValue.TLabel" if run_status in ("FAILED", "FAIL")
                       else "Success.CardValue.TLabel" if run_status == "SUCCESS"
                       else "Warning.CardValue.TLabel"))
            self.card_widgets["QMT 最近预检"].configure(
                style=("Success.CardValue.TLabel"
                       if obj["qmt_last_preflight"] == "CONNECTED"
                       else "Failure.CardValue.TLabel"
                       if obj["qmt_last_preflight"] == "QMT_SERVICE_UNAVAILABLE"
                       else "Warning.CardValue.TLabel"))
            self.overview_info.set(obj["comparison"])
            for key, name in STAGES:
                entry = obj["stage_records"][key]
                code = entry["exit_code"]
                quality = entry["data_validation"]
                if code is None:
                    summary, shade = "— 未记录本阶段执行", "Neutral"
                elif code != 0:
                    summary, shade = "✕ 运行失败（退出码 " + str(code) + "）", "Failure"
                elif quality == "PASS":
                    summary, shade = "✓ 已执行，数据核验通过", "Success"
                elif quality == "PARTIAL":
                    summary, shade = "△ 已执行，数据核验部分通过", "Warning"
                elif quality == "FAIL":
                    summary, shade = "! 已执行，但数据核验失败", "Failure"
                else:
                    summary, shade = "△ 已执行，数据尚未认证", "Warning"
                self.stage_labels[key].set(summary)
                self.stage_widgets[key].configure(
                    style=shade + ".Section.TLabel")
            cross = "、".join(src["minute_crosschecks_configured"]) or "当前未启用抽样核验"
            self.source_line.set(
                "更新：分钟 " + src["market_minute_update"] +
                "；日线 " + src["market_day_update"] +
                "\n周/月 " + src["market_week_month_update"] +
                "；其余 " + src["other_update"] +
                "\n核验：已配置 " + cross +
                "（仅抽样，不能视为本轮成功）；" + src["other_crosschecks"]
            )
            self.status_line.set("仅查看本地状态 | 当前 QMT 是否在线未进行实时连接测试")
            self.refresh_logs()
        except (InvalidPlan, OSError) as exc:
            self.status_line.set("状态读取异常：" + str(exc))

    def refresh_logs(self):
        try:
            receipt_path = self.state_work / "last-afternoon-unified.json"
            last = {}
            if receipt_path.is_file() and not receipt_path.is_symlink():
                if receipt_path.stat().st_size <= 2 * 1024 * 1024:
                    last = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            path = last.get("log_path", "") if isinstance(last, dict) else ""
            text = _read_log_tail(path, work_dir=self.state_work)
        except (OSError, ValueError, InvalidPlan):
            text = "日志暂不可读"
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", text)
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def open_log_folder(self):
        if os.name == "nt" and self.state_work.is_dir():
            os.startfile(str(self.state_work))
        else:
            messagebox.showinfo("日志目录", "本地日志目录暂不存在")


def main(argv=None):
    parser = argparse.ArgumentParser(description="V2-B 只读历史行情核验界面")
    parser.add_argument("--state-module", type=Path, default=HERE,
                        help="显式指定只读状态来源的 ParquetLiveSync 目录")
    parser.add_argument("--market-root", type=Path,
                        help="显式指定本机 AllCycleAStockData 物理目录，仅用于只读核验")
    parser.add_argument("--evidence-file", type=Path,
                        help="可选显式完整资格证据快照，须带 --evidence-sha256")
    parser.add_argument("--evidence-sha256",
                        help="可选证据快照字节SHA256，仅验证完整性非来源真实性")
    args = parser.parse_args(argv)
    path = args.state_module
    if not path.is_absolute() or path.name.lower() != "parquetlivesync" or not path.is_dir():
        parser.error("state-module 必须是已存在的绝对 ParquetLiveSync 目录")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        parser.error("拒绝符号链接的状态目录")
    if (args.evidence_file is None) != (args.evidence_sha256 is None):
        parser.error("--evidence-file 和 --evidence-sha256 必须同时提供")
    if args.evidence_file is not None and args.market_root is None:
        parser.error("使用证据文件时必须显式提供 --market-root")
    if args.market_root is not None:
        market = args.market_root
        if (not market.is_absolute()
                or market.name.lower() != "allcycleastockdata"
                or not market.is_dir()
                or any(parent.is_symlink() for parent in (market, *market.parents))):
            parser.error("market-root 必须是安全的绝对 AllCycleAStockData 目录")
        options = {"state_module": path, "market_root": market}
        if args.evidence_file is not None:
            options["evidence_file"] = args.evidence_file
            options["evidence_sha256"] = args.evidence_sha256
        MarketCenterV2(**options).mainloop()
    else:
        MarketCenterV2(state_module=path).mainloop()


if __name__ == "__main__":
    main()
