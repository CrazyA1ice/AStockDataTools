"""A-share incremental updater: local Windows status, logs and manual catch-up.

Tkinter is only an operator dashboard. It never reads or writes market bars.
Manual updating invokes the SAME scheduled-afternoon-update.ps1 pipeline in
an interactive console, protected by that script's cross-process mutex.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from market_daily_autopilot_view import read_view

MODULE = Path(__file__).resolve().parent
REPO = MODULE.parent


def _review_state_module(raw: str) -> Path:
    """Validated external ledger root ONLY for detached, non-writing GUI review."""
    if not raw:
        return MODULE
    root = Path(raw)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("GUI_REVIEW_MAIN_REPO_INVALID")
    # The review program MUST live in a detached worktree whose .git is a
    # file. Never enable the override for a production git checkout.
    if not (REPO / ".git").is_file() or (REPO / ".git").is_symlink():
        raise ValueError("GUI_REVIEW_REQUIRES_DETACHED_WORKTREE")
    if not (root / ".git").is_dir() or (root / ".git").is_symlink():
        raise ValueError("GUI_REVIEW_CANONICAL_CHECKOUT_REQUIRED")
    module = root / "ParquetLiveSync"
    work = module / "work"
    if (not module.is_dir() or module.is_symlink()
            or not work.is_dir() or work.is_symlink()):
        raise ValueError("GUI_REVIEW_CANONICAL_WORKSPACE_REQUIRED")
    if module.resolve() == MODULE.resolve():
        raise ValueError("GUI_REVIEW_REJECTS_SELF_REFERENCE")
    return module


REVIEW_MAIN_REPO = os.environ.get("ASTOCK_GUI_REVIEW_REPO", "")
REVIEW_MODE = bool(REVIEW_MAIN_REPO)
STATE_MODULE = _review_state_module(REVIEW_MAIN_REPO)
WORK = STATE_MODULE / "work"
STAGES = (
    ("EIGHT_PERIODS", "八周期行情"),
    ("SECTORS", "板块"),
    ("ADJUSTMENTS_ROTATING", "除权轮转"),
    ("FINANCIAL_DAILY", "财务增量"),
)
RUNNER = MODULE / "scheduled-afternoon-update.ps1"
MAX_STATUS_BYTES = 4 * 1024 * 1024
TAIL_BYTES = 100 * 1024
SHANGHAI = timezone(timedelta(hours=8))


def safe_json(path: Path, *, budget: int = MAX_STATUS_BYTES) -> dict:
    """Only the explicitly known private progress documents, never source data."""
    if path.is_symlink() or not path.is_file():
        return {}
    if path.stat().st_size > budget:
        raise ValueError("Progress receipt exceeds display budget: " + path.name)
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError("Progress receipt root must be an object")
    return obj


def accepted_minute_day(state: dict) -> str:
    """Get last physically committed ledger day (not a calendar prediction)."""
    if not isinstance(state, dict):
        return ""
    months = state.get("periods", {}).get("1min", {})
    if not isinstance(months, dict):
        return ""
    days = []
    for entry in months.values():
        if not isinstance(entry, dict):
            continue
        for item in entry.get("days", []):
            if isinstance(item, str):
                try:
                    if date.fromisoformat(item).isoformat() == item:
                        days.append(item)
                except ValueError:
                    continue
    return max(days, default="")


def safe_refresh_limit(now: datetime | None = None) -> date:
    """No current-day market updates before 20:05 China time, even manually."""
    now = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    target = now.date()
    if (now.hour, now.minute) < (20, 5):
        target -= timedelta(days=1)
    while target.weekday() >= 5:
        target -= timedelta(days=1)
    return target


def log_tail(path: Path, *, budget: int = TAIL_BYTES) -> str:
    """A bounded view of a local log. Never expand paths outside WORK."""
    real = path.resolve(strict=True)
    base = WORK.resolve(strict=True)
    if not real.is_relative_to(base) or real.suffix.lower() != ".log":
        raise ValueError("Log outside private update workspace")
    with real.open("rb") as stream:
        size = real.stat().st_size
        if size > budget:
            stream.seek(size - budget)
            stream.readline()  # skip a potentially partial UTF-8 line
        raw = stream.read(budget)
    return raw.decode("utf-8-sig", errors="replace")


def private_logs(limit: int = 60) -> list[Path]:
    if not WORK.is_dir() or WORK.is_symlink():
        return []
    found = []
    for path in WORK.glob("afternoon-*.log"):
        if path.is_symlink() or not path.is_file():
            continue
        found.append(path)
    return sorted(found, key=lambda p: p.stat().st_mtime_ns, reverse=True)[:limit]


class UpdaterDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("A股八周期增量更新中心 · 20:05")
        self.geometry("1120x780")
        self.minsize(850, 570)
        self.process: subprocess.Popen | None = None
        self.last_process_rc: int | None = None
        self.active_log: Path | None = None
        self.log_options: list[Path] = []
        self.auto_follow = tk.BooleanVar(value=True)
        self.finance_cap = tk.StringVar(value="200")
        self.adjust_cap = tk.StringVar(value="80")
        self.info = tk.StringVar(value="读取本地更新状态中")
        self.scheduled = tk.StringVar(value="")
        self.market = tk.StringVar(value="")
        self.finance = tk.StringVar(value="")
        self.last_run = tk.StringVar(value="")
        self.qmt_status = tk.StringVar(value="QMT服务预检：尚无运行记录")
        self.autopilot_status = tk.StringVar(value="自动健康：等待读取")
        self.autopilot_coverage = tk.StringVar(value="财务覆盖：未确认")
        self.autopilot_quality = tk.StringVar(value="质量校验：未认证")
        self.autopilot_valuation = tk.StringVar(
            value="估值派生（总市值 / PE / PB）：尚未启用")
        self.setup()
        self.refresh()

    def setup(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="A股增量更新中心", font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="20:05 北京时间自动更新 · 四阶段共用原定时任务 · 关机漏跑从已提交游标补更 · 数据源错误不强行覆盖",
        ).pack(anchor="w", pady=(2, 10))
        for variable in (self.info, self.scheduled, self.market, self.finance, self.last_run, self.qmt_status):
            ttk.Label(outer, textvariable=variable, justify="left").pack(anchor="w", pady=2)
        automatic = ttk.LabelFrame(
            outer, text="无人值守健康度 · 最近一次正式回执（只读预览）",
            padding=8)
        automatic.pack(fill="x", pady=(7, 3))
        for variable in (self.autopilot_status, self.autopilot_coverage,
                         self.autopilot_quality, self.autopilot_valuation):
            ttk.Label(automatic, textvariable=variable,
                      justify="left").pack(anchor="w", pady=1)
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=10)
        self.run_button = ttk.Button(buttons, text="补更至最近允许日期（四阶段）", command=self.manual_update)
        self.run_button.pack(side="left")
        ttk.Button(buttons, text="刷新状态", command=self.refresh).pack(side="left", padx=8)
        ttk.Button(buttons, text="打开日志文件夹", command=self.open_folder).pack(side="left")
        caps = ttk.Frame(outer)
        caps.pack(fill="x", pady=(0, 6))
        ttk.Label(caps, text="20:05后手动补更财务每轮上限").pack(side="left")
        ttk.Combobox(caps, textvariable=self.finance_cap, state="readonly", width=9,
                     values=("200", "500", "1000", "5000", "10000")).pack(side="left", padx=7)
        ttk.Label(caps, text="除权每轮上限").pack(side="left", padx=(18, 0))
        ttk.Combobox(caps, textvariable=self.adjust_cap, state="readonly", width=9,
                     values=("80", "200", "500", "1000")).pack(side="left", padx=7)
        ttk.Label(caps, text="异常冲突仍需人工审核；上限≠保证全部完成").pack(side="left", padx=10)
        ttk.Label(
            outer,
            text="手动启动会弹出独立 PowerShell 实时控制台；窗口关闭后仍可在下方阅读日志。正在写入时请勿强制结束进程。",
        ).pack(anchor="w")
        area = ttk.LabelFrame(outer, text="分阶段状态（来自最新运行回执）", padding=8)
        area.pack(fill="x", pady=(12, 8))
        self.tree = ttk.Treeview(area, columns=("execution", "quality", "cross", "log"),
                                  show="headings", height=4)
        for key, title, width in (
            ("execution", "阶段执行", 230),
            ("quality", "数据校验", 190),
            ("cross", "跨源状态", 190),
            ("log", "阶段日志", 350),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, stretch=True)
        self.tree.pack(fill="x")
        display = ttk.LabelFrame(outer, text="历史及实时日志（保留完整原始日志文件）", padding=8)
        display.pack(fill="both", expand=True, pady=(7, 0))
        bar = ttk.Frame(display)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="选择日志：").pack(side="left")
        self.log_combo = ttk.Combobox(bar, state="readonly", width=78)
        self.log_combo.pack(side="left", fill="x", expand=True)
        self.log_combo.bind("<<ComboboxSelected>>", self.select_log)
        ttk.Checkbutton(bar, text="跟随最新", variable=self.auto_follow).pack(side="left", padx=6)
        ttk.Button(bar, text="打开日志文件", command=self.open_log).pack(side="left", padx=(8, 0))
        holder = ttk.Frame(display)
        holder.pack(fill="both", expand=True)
        self.output = tk.Text(holder, font=("Consolas", 9), wrap="none",
                              bg="#101827", fg="#E5E7EB")
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def refresh(self):
        try:
            ledger = safe_json(WORK / "market_update" / "commits.json")
            finance = safe_json(WORK / "qmt_extra" / "financial-cache-progress.json")
            last = safe_json(WORK / "last-afternoon-unified.json")
            historical = safe_json(WORK / "last-precutoff-market-only.json")
            accepted = accepted_minute_day(ledger)
            limit = safe_refresh_limit()
            self.market.set(
                "已提交 1min 最新交易日：" + (accepted or "尚无可验证游标") +
                "    本轮安全上限（北京时间）：" + limit.isoformat() +
                "    ※ 非交易日以 QMT 交易日历为准"
            )
            pending = finance.get("pending", {})
            self.finance.set(
                "财务增量：截止日 " + str(finance.get("daily_date", "未知")) +
                "    待审 " + str(len(pending) if isinstance(pending, dict) else "未知") +
                "    当前轮转游标 " + str(finance.get("daily_cursor", "未知"))
            )
            status = str(last.get("status", "暂无历史任务结果"))
            self.last_run.set(
                "最近任务：" + status +
                "    触发：" + str(last.get("invocation", "原有计划任务/未知")) +
                "    开始：" + str(last.get("china_start", "未知")) +
                "    结束：" + str(last.get("finished_local", "未知")) +
                "    20:05前历史补更：" + str(historical.get("status", "尚未执行"))
            )
            self.qmt_status.set(
                "QMT服务预检：正式任务=" + str(last.get("qmt_preflight_status", "旧版本未记录")) +
                "（尝试 " + str(last.get("qmt_preflight_attempts", 0)) + " 次）" +
                "；20:05前补更=" + str(historical.get("qmt_preflight_status", "尚无记录"))
            )
            model = read_view(STATE_MODULE)
            self.autopilot_status.set(model["headline"])
            self.autopilot_coverage.set(model["coverage"])
            self.autopilot_quality.set(model["quality"] +
                                       "  |  " + model["action"])
            self.autopilot_valuation.set(model["valuation"])
            self.show_stages(last)
            self.update_logs()
            self.info.set(
                "实时运行：" +
                ("手动补更进程正在执行" if self.process is not None
                 else "未检测到本界面启动的补更进程（计划任务可能独立运行）") +
                "    最后人工运行退出码：" +
                (str(self.last_process_rc) if self.last_process_rc is not None else "暂无")
            )
            if self.process is not None:
                code = self.process.poll()
                if code is not None:
                    self.last_process_rc = code
                    self.process = None
                    if code != 0:
                        messagebox.showwarning(
                            "增量更新未完全成功",
                            f"进程返回 {code}。请查看阶段日志、QMT服务预检结果以及当次状态回执；"
                            "已成功提交的日期保持不变。"
                        )
            self.run_button.configure(state="disabled" if self.process else "normal")
        except Exception as exc:
            self.info.set("状态读取异常：" + str(exc))
        self.after(2500, self.refresh)

    def show_stages(self, last: dict):
        for item in self.tree.get_children():
            self.tree.delete(item)
        validation = last.get("validation") or {}
        sections = validation.get("sections", {}) if isinstance(validation, dict) else {}
        raw = last.get("stage_records", {})
        if not isinstance(raw, dict):
            raw = {}
        for key, label in STAGES:
            v = sections.get(key, {}) if isinstance(sections, dict) else {}
            rec = raw.get(key, {})
            if not isinstance(rec, dict):
                rec = {}
            result = (str(v.get("execution", "未知")) + " / " + label)
            self.tree.insert("", "end", values=(
                result, v.get("data_validation", "未验证"),
                v.get("cross_validation", "未验证"),
                Path(str(rec.get("log_path", ""))).name if rec.get("log_path") else "无"
            ))

    def update_logs(self):
        latest = private_logs()
        if latest != self.log_options:
            self.log_options = latest
            self.log_combo.configure(values=[p.name for p in latest])
        if latest and (self.active_log is None or self.auto_follow.get()):
            self.active_log = latest[0]
            self.log_combo.set(latest[0].name)
        if self.active_log and self.active_log in latest:
            text = log_tail(self.active_log)
            if self.output.get("1.0", "end-1c") != text:
                self.output.delete("1.0", "end")
                self.output.insert("1.0", text)
                self.output.see("end")

    def select_log(self, _event=None):
        self.auto_follow.set(False)
        choice = self.log_combo.get()
        for path in self.log_options:
            if path.name == choice:
                self.active_log = path
                self.update_logs()
                return

    def manual_update(self):
        if self.process is not None:
            return
        if os.name != "nt" or not (REPO / ".git").is_dir():
            messagebox.showerror(
                "未能启动", "只能在 Windows 正式仓库执行补更，不允许从 detached worktree 写入生产数据。"
            )
            return
        if not RUNNER.is_file() or not (REPO / ".venv" / "Scripts" / "python.exe").is_file():
            messagebox.showerror("组件缺失", "找不到正式增量脚本或项目 Python 环境")
            return
        if not (WORK / "market_update" / "commits.json").is_file():
            messagebox.showerror("游标缺失", "没有已提交行情账本，不能自动推断补更起点")
            return
        latest = accepted_minute_day(safe_json(WORK / "market_update" / "commits.json"))
        limit = safe_refresh_limit()
        now_cn = datetime.now(SHANGHAI)
        historical_only = (now_cn.hour, now_cn.minute) < (20, 5)
        if not latest:
            messagebox.showerror("无法补更", "最新成功行情日期不可验证，拒绝盲目下载")
            return
        finance_cap = int(self.finance_cap.get())
        adjust_cap = int(self.adjust_cap.get())
        if finance_cap not in (200, 500, 1000, 5000, 10000) or adjust_cap not in (80, 200, 500, 1000):
            messagebox.showerror("参数无效", "补更数量必须使用受控选项")
            return
        if not messagebox.askyesno(
            "确认执行增量补更",
            "即将打开新的命令行窗口，使用与计划任务相同的增量更新程序。\n"
            f"最后 1min 已提交：{latest}\n北京时间本轮截止：{limit.isoformat()}\n"
            "市场历史按最多30日一批断点续跑；" +
            ("当前未到北京时间20:05，只补已收盘历史行情，板块/除权/财务不运行。\n"
             if historical_only else
             "已过北京时间20:05，本轮会继续板块、除权和财务。\n") +
            f"20:05后财务上限 {finance_cap} 只/轮；除权上限 {adjust_cap} 只/轮。\n" +
            "程序可能下载并写入经过校验的月度 Parquet；"
            "请先确保已登录 QMT、网络正常，且磁盘空间充足。\n"
            "同一时刻仅允许一个自动/手动任务。继续吗？"
        ):
            return
        engine = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        try:
            args = [str(engine), "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(RUNNER), "-Invocation", "Manual"]
            if historical_only:
                args.append("-HistoryOnly")
            else:
                args.extend(["-FinanceDailyStockLimit", str(finance_cap),
                             "-AdjustmentStockLimit", str(adjust_cap)])
            args.append("-Apply")
            self.process = subprocess.Popen(
                args,
                cwd=str(REPO), creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            self.last_process_rc = None
            self.active_log = None
            self.auto_follow.set(True)
            self.info.set("手动补更已启动，实时输出位于弹出的 PowerShell 控制台")
        except OSError as exc:
            self.process = None
            messagebox.showerror("无法启动", str(exc))

    def open_folder(self):
        if WORK.is_dir():
            os.startfile(str(WORK))
        else:
            messagebox.showinfo("日志目录", "尚未存在私有日志目录")

    def open_log(self):
        if self.active_log and self.active_log.is_file():
            try:
                log_tail(self.active_log, budget=4096)
                os.startfile(str(self.active_log))
            except (OSError, ValueError) as exc:
                messagebox.showerror("无法打开日志", str(exc))


def main():
    if os.name != "nt":
        raise SystemExit("Windows interactive desktop required")
    UpdaterDashboard().mainloop()


if __name__ == "__main__":
    main()
