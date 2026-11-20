"""A股数据更新与核验中心 V2-A: minimal read-only Tkinter UI preview.

This is NOT a replacement for the working 20:05 scheduled task, updater,
audit engine, or original market_update_dashboard.py. There is intentionally
no subprocess.Popen, QMT import, data download, task install or Apply button.
"""
from __future__ import annotations

from datetime import date
import argparse
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from market_center_v2_model import (
    MODULES, InvalidPlan, latest_status, parse_symbols, plan_preview,
    safe_cutoff, source_info,
)

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
    def __init__(self, *, state_module: Path = HERE):
        super().__init__()
        self.state_module = Path(state_module)
        self.state_work = self.state_module / "work"
        self.title("A股数据更新与核验中心 V2 · 设计预览")
        self.geometry("1080x710")
        self.minsize(900, 610)
        self.option_add("*Font", LABEL_FONT)
        self.app_style = apply_theme(self)
        self.mode = tk.StringVar(value="更新数据")
        self.scope = tk.StringVar(value="全部股票")
        cutoff = safe_cutoff()
        self.start = tk.StringVar(value=cutoff.replace(day=1).isoformat())
        self.end = tk.StringVar(value=cutoff.isoformat())
        self.modules = {name: tk.BooleanVar(value=True) for name in MODULES}
        self.stock_count = tk.StringVar(value="指定股票尚未填写")
        self.overview_info = tk.StringVar(value="尚未读取")
        self.status_line = tk.StringVar(value="V2-A：只读预览，不会启动数据处理")
        self.source_line = tk.StringVar(value="数据源：读取当前项目配置")
        self.plan_ready = None
        self.make_widgets()
        self.refresh_overview()

    def make_widgets(self):
        head = ttk.Frame(self, padding=(18, 14))
        head.pack(fill="x")
        ttk.Label(head, text="A股数据更新与核验中心", style="AppTitle.TLabel").pack(side="left")
        ttk.Label(head, text="● 只读预览  |  每晚 20:05 自动任务不变",
                  style="Muted.TLabel").pack(side="right")
        self.book = ttk.Notebook(self)
        self.book.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        self.home = ttk.Frame(self.book, padding=14)
        self.action = ttk.Frame(self.book, padding=14)
        self.logs = ttk.Frame(self.book, padding=14)
        self.book.add(self.home, text="  运行总览  ")
        self.book.add(self.action, text="  更新 / 核验  ")
        self.book.add(self.logs, text="  运行日志  ")
        self.build_home()
        self.build_action()
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
        for label in ("已提交最新交易日", "最近任务状态", "当前安全截止", "QMT 最近预检"):
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
        ttk.Label(self.home, text="已有日期：跳过或拒绝冲突覆盖  |  自动任务占用时：手动更新必须等待执行锁  |  当前为只读预览",
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
        ttk.Label(top, text="● 预览模式：真实执行暂未开放",
                  style="Muted.TLabel").pack(side="right")
        mode_row = ttk.LabelFrame(content, text="任务类型（共用下方同一组范围）", padding=8)
        mode_row.pack(fill="x", pady=(0, 10))
        for item in ("更新数据", "数据核验"):
            ttk.Radiobutton(mode_row, text=item, value=item, variable=self.mode).pack(side="left", padx=12)
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
        ttk.Label(row, text="已提交数据不可盲目覆盖；运行中禁止重复写入",
                  style="Section.TLabel").pack(side="right")

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
        overlap = ("⚠ 日期范围可能与已提交行情重叠（最新已提交：" + latest
                   + "）；禁止盲目覆盖。\n"
                   if latest != "未证明" and p["start_date"] <= latest else
                   "尚未证明所选范围与已提交行情是否重叠；执行前必须核验。\n")
        description = (p["mode"] + " | " + p["start_date"] + " 至 " + p["end_date"] + "\n"
                       + "股票：" + (p["scope"] if p["scope"] == "全部股票"
                                    else ", ".join(p["symbols"])) + "\n"
                       + "数据：" + "、".join(p["data_types"]) + "\n"
                       + overlap
                       + "并发规则：20:05计划任务运行中不允许第二个写入任务。\n"
                       + "执行状态：禁止（V2-A 只读预览）；需先实现对应日期/股票范围的后端支持。")
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
            self.cards["最近任务状态"].set(str(obj["last_run_status"]))
            self.cards["当前安全截止"].set(obj["safe_candidate_cutoff"])
            self.cards["QMT 最近预检"].set(obj["qmt_last_preflight"])
            run_status = str(obj["last_run_status"]).upper()
            self.card_widgets["最近任务状态"].configure(
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
                self.stage_labels[key].set(
                    ("✓ 已执行（退出码 0）" if code == 0 else "✕ 失败（退出码 " + str(code) + "）")
                    if code is not None else "— 本轮未记录")
                self.stage_widgets[key].configure(
                    style=("Success.Section.TLabel" if code == 0
                           else "Failure.Section.TLabel" if code is not None
                           else "Neutral.Section.TLabel"))
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
    parser = argparse.ArgumentParser(description="V2-A 只读界面原型")
    parser.add_argument("--state-module", type=Path, default=HERE,
                        help="显式指定只读状态来源的 ParquetLiveSync 目录")
    args = parser.parse_args(argv)
    path = args.state_module
    if not path.is_absolute() or path.name.lower() != "parquetlivesync" or not path.is_dir():
        parser.error("state-module 必须是已存在的绝对 ParquetLiveSync 目录")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        parser.error("拒绝符号链接的状态目录")
    MarketCenterV2(state_module=path).mainloop()


if __name__ == "__main__":
    main()
