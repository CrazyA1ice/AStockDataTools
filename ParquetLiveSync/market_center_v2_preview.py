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
TITLE_FONT = ("Microsoft YaHei UI", 17, "bold")


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
        self.geometry("1070x760")
        self.minsize(850, 600)
        self.option_add("*Font", LABEL_FONT)
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
        ttk.Label(head, text="A股数据更新与核验中心", font=TITLE_FONT).pack(side="left")
        ttk.Label(head, text="V2-A · 预览版 | 20:05 自动任务保持不变",
                  foreground="#4b647f").pack(side="right")
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
        ttk.Label(self, textvariable=self.status_line, foreground="#546579",
                  padding=(18, 4)).pack(fill="x")

    def build_home(self):
        top = ttk.Frame(self.home)
        top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, text="最近运行状态", font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        ttk.Button(top, text="刷新状态", command=self.refresh_overview).pack(side="right")
        tiles = ttk.Frame(self.home)
        tiles.pack(fill="x")
        self.cards = {}
        for label in ("已提交最新交易日", "最近任务状态", "当前安全截止", "QMT 最近预检"):
            card = ttk.LabelFrame(tiles, text=label, padding=12)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            variable = tk.StringVar(value="—")
            ttk.Label(card, textvariable=variable, font=("Microsoft YaHei UI", 13, "bold"),
                      wraplength=190).pack(anchor="w")
            self.cards[label] = variable
        changed = ttk.LabelFrame(self.home, text="本次相比上次，有什么变化？", padding=14)
        changed.pack(fill="x", pady=(18, 12))
        ttk.Label(changed, textvariable=self.overview_info, wraplength=900,
                  foreground="#334b69").pack(anchor="w")
        ttk.Label(changed, text="如未有可信的前后快照，不能编造新增数量。",
                  foreground="#697b90").pack(anchor="w", pady=(6, 0))
        phases = ttk.LabelFrame(self.home, text="上一次运行的四个阶段", padding=10)
        phases.pack(fill="x")
        self.stage_labels = {}
        for key, title in STAGES:
            var = tk.StringVar(value="暂无")
            self.stage_labels[key] = var
            line = ttk.Frame(phases)
            line.pack(fill="x", pady=4)
            ttk.Label(line, text=title, width=15).pack(side="left")
            ttk.Label(line, textvariable=var).pack(side="left", fill="x")
        actions = ttk.Frame(self.home)
        actions.pack(anchor="w", pady=(18, 0))
        ttk.Button(actions, text="配置更新范围", command=lambda: self.go_action("更新数据")).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="配置数据核验", command=lambda: self.go_action("数据核验")).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="查看运行日志", command=lambda: self.book.select(self.logs)).pack(side="left")
        ttk.Label(self.home, text="正在运行的老版本更新器不受此预览界面影响；未完成日期和股票定向接口验收之前不能执行。",
                  foreground="#6a798c", wraplength=900).pack(anchor="w", pady=(18, 0))

    def build_action(self):
        top = ttk.Frame(self.action)
        top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, text="操作配置", font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        ttk.Label(top, text="仅生成计划 · 暂不执行生产更新或核验",
                  foreground="#936d27").pack(side="right")
        mode_row = ttk.LabelFrame(self.action, text="任务类型（共用下方同一组范围）", padding=8)
        mode_row.pack(fill="x", pady=(0, 10))
        for item in ("更新数据", "数据核验"):
            ttk.Radiobutton(mode_row, text=item, value=item, variable=self.mode).pack(side="left", padx=12)
        dates = ttk.LabelFrame(self.action, text="处理时间段 · 同时适用于更新和核验", padding=10)
        dates.pack(fill="x", pady=(0, 10))
        ttk.Label(dates, text="开始日期").pack(side="left")
        ttk.Entry(dates, textvariable=self.start, width=13).pack(side="left", padx=(8, 20))
        ttk.Label(dates, text="结束日期").pack(side="left")
        ttk.Entry(dates, textvariable=self.end, width=13).pack(side="left", padx=8)
        ttk.Label(dates, text="YYYY-MM-DD，北京时间 20:05 安全界限",
                  foreground="#687b92").pack(side="left", padx=12)
        stocks = ttk.LabelFrame(self.action, text="股票范围", padding=10)
        stocks.pack(fill="x", pady=(0, 10))
        bar = ttk.Frame(stocks)
        bar.pack(fill="x")
        for option in ("全部股票", "指定股票"):
            ttk.Radiobutton(bar, text=option, value=option,
                            variable=self.scope).pack(side="left", padx=(0, 14))
        ttk.Label(bar, textvariable=self.stock_count, foreground="#41678d").pack(side="right")
        ttk.Label(stocks, text="指定多只：输入 000001.SZ, 600519.SH，或换行粘贴；自动去重，最多 500 只。",
                  foreground="#637a91").pack(anchor="w", pady=(8, 2))
        self.stock_box = tk.Text(stocks, height=3, font=("Consolas", 10), wrap="word")
        self.stock_box.pack(fill="x")
        self.stock_box.insert("1.0", "000001.SZ, 600519.SH")
        ttk.Button(stocks, text="检查股票列表", command=self.check_stocks).pack(anchor="e", pady=(4, 0))
        types = ttk.LabelFrame(self.action, text="数据类型（可多选）", padding=10)
        types.pack(fill="x", pady=(0, 10))
        for name in MODULES:
            ttk.Checkbutton(types, text=name, variable=self.modules[name]).pack(side="left", padx=(6, 25))
        sources = ttk.LabelFrame(self.action, text="数据来源 · 自动按现有配置选择，不允许手选", padding=10)
        sources.pack(fill="x", pady=(0, 10))
        ttk.Label(sources, textvariable=self.source_line, wraplength=940,
                  justify="left").pack(anchor="w")
        preview = ttk.LabelFrame(self.action, text="任务预览 / 执行门禁", padding=10)
        preview.pack(fill="both", expand=True)
        self.preview_text = tk.Text(preview, height=5, font=("Microsoft YaHei UI", 10), wrap="word",
                                    background="#f6f8fb", foreground="#304761")
        self.preview_text.pack(fill="both", expand=True)
        self.preview_text.insert("1.0", "请检查日期、股票及数据类型后点击「预览任务」。\n"
                                           "目前不提供真实执行入口，防止把定向任务错误地变为全市场写入。")
        self.preview_text.configure(state="disabled")
        row = ttk.Frame(preview)
        row.pack(fill="x", pady=(9, 0))
        ttk.Button(row, text="预览任务", command=self.show_preview).pack(side="left")
        ttk.Button(row, text="复制计划", command=self.copy_preview).pack(side="left", padx=10)
        ttk.Label(row, text="执行功能待后端能力验收后开放",
                  foreground="#a06f22").pack(side="right")

    def build_logs(self):
        head = ttk.Frame(self.logs)
        head.pack(fill="x", pady=(0, 12))
        ttk.Label(head, text="最近任务原始日志", font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        ttk.Button(head, text="刷新日志", command=self.refresh_logs).pack(side="right")
        ttk.Label(self.logs, text="这里仅显示最新任务末尾内容；完整日志始终保存在原目录。",
                  foreground="#667b90").pack(anchor="w", pady=(0, 10))
        self.log_text = tk.Text(self.logs, font=("Consolas", 10), wrap="none",
                                background="#152235", foreground="#e3ebf7")
        self.log_text.pack(fill="both", expand=True)
        ttk.Button(self.logs, text="打开原日志文件夹", command=self.open_log_folder).pack(anchor="e", pady=8)

    def go_action(self, mode):
        self.mode.set(mode)
        self.book.select(self.action)

    def check_stocks(self):
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
        description = (p["mode"] + " | " + p["start_date"] + " 至 " + p["end_date"] + "\n"
                       + "股票：" + (p["scope"] if p["scope"] == "全部股票"
                                    else ", ".join(p["symbols"])) + "\n"
                       + "数据：" + "、".join(p["data_types"]) + "\n"
                       + "执行状态：禁止（V2-A 只读预览）；需先实现对应日期/股票范围的后端支持。")
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", description)
        self.preview_text.configure(state="disabled")
        self.status_line.set("预览校验通过 · 不会自动更新或下载")

    def copy_preview(self):
        if self.plan_ready is None:
            messagebox.showinfo("尚无计划", "请先点击「预览任务」。")
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
            self.overview_info.set(obj["comparison"])
            for key, name in STAGES:
                entry = obj["stage_records"][key]
                self.stage_labels[key].set(
                    ("退出码 " + str(entry["exit_code"])) if entry["exit_code"] is not None
                    else "未记录本阶段执行")
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
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", text)

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
