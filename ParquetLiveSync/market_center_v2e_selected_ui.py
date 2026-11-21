"""Market Center V2E - integrated seven-page shell on the V2-D2C backend.

User-selected A/B layout is kept; V2-D2A opt-in QMT get_client probe and
V2-D2B read-only canonical hashes/finance inventory are retained. Optional
V2-D2C historical version closure is read-only. No update, financial commit,
download, writer mutex acquisition or changes to the 20:05 scheduled task.
"""
from __future__ import annotations

import argparse
import json
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from market_center_v2_faults import FaultEvidenceBlocked
from market_center_v2_recovery_inventory import PreflightBlocked
from market_center_v2_finance_history_scope import inventory_historical_versions
from market_center_v2g_workflow import (
    TASKS, task_by_id, recommended_task, workflow_guide,
)
from market_center_v2g2_audit_review import (
    AuditFlowBlocked, explain_observation, format_review_text,
    summarize_readonly_report,
)

from market_center_v2_model import (
    HISTORY_POLICIES, MODULES, InvalidPlan, latest_status, source_info,
)
from market_center_v2_readonly_audit import (
    PERIODS, AuditBlocked, FROZEN_ASOF, read_only_ceiling,
)
from market_center_v2_preview import (
    COLORS, HERE, STAGES, MarketCenterV2,
)

PAGES = (
    ("运行总览", "本轮状态 · 可信变化 · 关键操作", "A"),
    ("更新 / 核验", "三步配置 · 共享日期与股票 · 安全预检", "B"),
    ("核验结果", "主表观察 · 原始证据分栏", "B"),
    ("故障诊断", "同次错误 · 影响范围 · 只读恢复路线", "B"),
    ("运行日志", "完整阶段日志 · 检索定位", "B"),
    ("数据管理", "八周期资料 · 数据源与覆盖证据", "A"),
    ("高级设置", "原计划任务 · 来源配置 · 权限边界", "A"),
)
PERIOD_LABELS = (
    ("1min", "1 分钟"), ("5min", "5 分钟"),
    ("15min", "15 分钟"), ("30min", "30 分钟"),
    ("60min", "60 分钟"), ("day", "日线"),
    ("week", "周线"), ("month", "月线"),
)
PAGE_MAP = {name: index for index, (name, _, _) in enumerate(PAGES)}


def format_evidence_state(value: object) -> str:
    """Render unknown evidence without pretending a result is certified."""
    if value is None or value == "":
        return "暂无可信记录"
    if isinstance(value, bool):
        return "已确认" if value else "未证实"
    return str(value)[:100]


def view_coverage_rows(status: dict) -> tuple[dict, ...]:
    """A displayed eight-period inventory is NOT a per-period scan."""
    phases = status.get("stage_records", {})
    phase = phases.get("EIGHT_PERIODS", {}) if isinstance(phases, dict) else {}
    phase = phase if isinstance(phase, dict) else {}
    summary = format_evidence_state(phase.get("data_validation"))
    return tuple({
        "period": period,
        "name": name,
        "coverage": "未逐周期核验",
        "source_statement": "最近一次八周期阶段：" + summary,
        "certified": False,
        "count": None,
    } for period, name in PERIOD_LABELS)


def separated_run_evidence(status: dict) -> dict:
    """Execution, data quality and cross-source validation stay separate."""
    return {
        "execution": format_evidence_state(status.get("execution_validation")),
        "data": format_evidence_state(status.get("data_validation")),
        "cross": format_evidence_state(status.get("cross_validation")),
        "qmt_live": False,
        "comparison_evidenced": bool(status.get("comparison_evidenced") is True),
    }


# Neutral enterprise dashboard palette. This is purely presentation data:
# no business logic or execution permissions are tied to these colors.
V2F = {
    "canvas": "#F5F7FB",
    "sidebar": "#12233D",
    "sidebar_selected": "#244C7A",
    "surface": "#FFFFFF",
    "border": "#E3EAF2",
    "subtle": "#F7F9FC",
    "heading": "#182B46",
    "text": "#31445E",
    "secondary": "#78879B",
    "accent": "#2469B6",
    "danger": "#B5474B",
    "danger_bg": "#FFF5F4",
    "success": "#1F805B",
    "warning": "#A97124",
}


class MarketCenterV2SelectedUI(MarketCenterV2):
    """V2E visual shell: all current backend safeguards stay in the controller."""

    def _modernize_theme(self):
        """Lightweight ttk styling, using only built-in Tk; no new dependency."""
        self.configure(background=V2F["canvas"])
        style = self.app_style
        style.configure(".", background=V2F["canvas"],
                        foreground=V2F["text"],
                        font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=V2F["canvas"])
        style.configure("TLabel", background=V2F["canvas"],
                        foreground=V2F["text"])
        style.configure("TLabelframe",
                        background=V2F["surface"],
                        bordercolor=V2F["border"],
                        borderwidth=0, relief="flat")
        style.configure("TLabelframe.Label",
                        background=V2F["surface"],
                        foreground=V2F["heading"],
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Card.TLabelframe",
                        background=V2F["surface"], borderwidth=0)
        style.configure("Card.TLabelframe.Label",
                        background=V2F["surface"],
                        foreground=V2F["secondary"])
        style.configure("CardValue.TLabel",
                        background=V2F["surface"],
                        foreground=V2F["heading"],
                        font=("Segoe UI", 16, "bold"))
        for name, color in (
            ("Success", V2F["success"]), ("Failure", V2F["danger"]),
            ("Warning", V2F["warning"]), ("Neutral", V2F["heading"])):
            style.configure(name + ".CardValue.TLabel",
                            background=V2F["surface"], foreground=color,
                            font=("Segoe UI", 16, "bold"))
            style.configure(name + ".Section.TLabel",
                            background=V2F["surface"], foreground=color)
        style.configure("Section.TLabel",
                        background=V2F["surface"], foreground=V2F["text"])
        style.configure("Muted.TLabel",
                        background=V2F["canvas"],
                        foreground=V2F["secondary"])
        style.configure("V2F.Card.TFrame",
                        background=V2F["surface"])
        style.configure("V2F.CardHeading.TLabel",
                        background=V2F["surface"],
                        foreground=V2F["heading"],
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("V2F.CardNote.TLabel",
                        background=V2F["surface"],
                        foreground=V2F["secondary"],
                        font=("Microsoft YaHei UI", 9))
        style.configure("V2F.MetricHeading.TLabel",
                        background=V2F["surface"],
                        foreground=V2F["secondary"],
                        font=("Microsoft YaHei UI", 9))
        style.configure("V2F.Badge.TLabel",
                        background=V2F["subtle"],
                        foreground=V2F["secondary"],
                        padding=(9, 4))
        style.configure("V2F.Danger.TLabel",
                        background=V2F["danger_bg"],
                        foreground=V2F["danger"],
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("V2F.SectionHeading.TLabel",
                        background=V2F["canvas"],
                        foreground=V2F["heading"],
                        font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("V2F.SideTitle.TLabel",
                        background=V2F["surface"],
                        foreground=V2F["text"],
                        font=("Microsoft YaHei UI", 9))
        style.configure("V2F.Primary.TButton",
                        background=V2F["accent"],
                        bordercolor=V2F["accent"],
                        foreground=V2F["surface"],
                        padding=(12, 10),
                        relief="flat",
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.map("V2F.Primary.TButton",
                  background=[("active", "#1B578F"),
                              ("disabled", V2F["subtle"])],
                  foreground=[("active", "#FFFFFF")])
        style.configure("Primary.TButton",
                        background=V2F["accent"], foreground="#FFFFFF",
                        bordercolor=V2F["accent"], borderwidth=0,
                        padding=(12, 10), relief="flat")
        style.map("Primary.TButton",
                  background=[("active", "#1B578F")])
        style.configure("TButton",
                        background=V2F["surface"],
                        foreground=V2F["accent"],
                        bordercolor=V2F["border"],
                        padding=(11, 9), relief="flat")
        style.map("TButton", background=[("active", "#EDF3FB")])
        style.configure("TNotebook.Tab", padding=(16, 9))
        style.configure("Treeview", rowheight=29, background="#FFFFFF",
                        fieldbackground="#FFFFFF",
                        foreground=V2F["text"],
                        borderwidth=0)
        style.configure("Treeview.Heading",
                        background=V2F["subtle"],
                        foreground=V2F["secondary"],
                        font=("Microsoft YaHei UI", 9, "bold"),
                        relief="flat", padding=(8, 7))
        style.map("Treeview",
                  background=[("selected", "#E7F0FA")],
                  foreground=[("selected", V2F["heading"])])

    def make_widgets(self):
        self.historical_inventory_queue = queue.Queue()
        self.historical_inventory_running = False
        self.historical_inventory_result = None
        self.historical_inventory_buttons = []
        self.historical_inventory_summary = tk.StringVar(
            value="历史财务版本范围尚未进行只读盘点")
        self.workflow_hint = tk.StringVar(
            value="建议下一步：先查看最近任务状态，再选择一项工作。")
        self.workflow_tip = tk.StringVar(
            value=workflow_guide("update"))
        self.workflow_current_task = None
        self.quick_tools_shown = False
        self.recommended_task_id = "audit"
        self.title("A股数据更新与核验中心 · Market Center V2G3")
        self.geometry("1350x860")
        self.minsize(1020, 670)
        self._modernize_theme()
        self.app_style.layout("V2E.Hidden.TNotebook.Tab", [])
        self.app_style.configure("V2E.Hidden.TNotebook", tabmargins=0)
        self.app_style.configure("V2E.TNotebook.Tab", padding=(20, 12))
        self.app_style.configure("V2E.Heading.TLabel",
                                 foreground=V2F["heading"],
                                 font=("Microsoft YaHei UI", 17, "bold"))
        self.app_style.configure("V2E.Subheading.TLabel",
                                 foreground=V2F["secondary"],
                                 font=("Microsoft YaHei UI", 10))
        self.shell = ttk.Frame(self)
        self.shell.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(self.shell, bg=V2F["sidebar"], width=208)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Label(self.sidebar, text="MARKET CENTER", bg=V2F["sidebar"],
                 fg="#FFFFFF", font=("Segoe UI", 15, "bold"),
                 padx=20, pady=26, anchor="w").pack(fill="x")
        tk.Label(self.sidebar, text="A-STOCK DATA  /  READ ONLY",
                 bg=V2F["sidebar"],
                 fg="#91A7C2", font=("Segoe UI", 8, "bold"),
                 padx=20, anchor="w").pack(fill="x", pady=(0, 26))
        self.nav_controls = {}
        for index, (name, _, _) in enumerate(PAGES):
            button = tk.Button(
                self.sidebar, text="   " + name, anchor="w",
                font=("Microsoft YaHei UI", 10),
                relief="flat", borderwidth=0, highlightthickness=0,
                padx=16, pady=12,
                bg=V2F["sidebar"], fg="#B9C9DE",
                activebackground=V2F["sidebar_selected"],
                activeforeground="white",
                cursor="hand2",
                command=lambda n=index: self.navigate(n),
            )
            button.pack(fill="x", padx=12, pady=3)
            self.nav_controls[name] = button
        tk.Label(
            self.sidebar, text="仅限本地状态读取\n写入、下载、自动修复：未开放",
            bg=V2F["sidebar"], fg="#8FA3BD", justify="left",
            font=("Microsoft YaHei UI", 9), padx=18, pady=18,
        ).pack(side="bottom", fill="x")

        self.workspace = ttk.Frame(self.shell)
        self.workspace.pack(side="left", fill="both", expand=True)
        header = ttk.Frame(self.workspace, padding=(25, 19, 25, 13))
        header.pack(fill="x")
        left = ttk.Frame(header)
        left.pack(side="left", fill="x", expand=True)
        self.page_heading = tk.StringVar(value=PAGES[0][0])
        self.page_subtitle = tk.StringVar(value=PAGES[0][1])
        ttk.Label(left, textvariable=self.page_heading,
                  style="V2E.Heading.TLabel").pack(anchor="w")
        ttk.Label(left, textvariable=self.page_subtitle,
                  style="V2E.Subheading.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Label(
            header, text="● 故障诊断与只读核验  |  20:05 自动任务不变",
            style="Muted.TLabel",
        ).pack(side="right")
        self.book = ttk.Notebook(self.workspace, style="V2E.Hidden.TNotebook")
        self.book.pack(fill="both", expand=True, padx=(18, 22), pady=(0, 9))
        self.home = ttk.Frame(self.book, padding=9)
        self.action = ttk.Frame(self.book, padding=13)
        self.audit_page = ttk.Frame(self.book, padding=13)
        self.fault_page = ttk.Frame(self.book, padding=13)
        self.logs = ttk.Frame(self.book, padding=13)
        self.data_page = ttk.Frame(self.book, padding=13)
        self.settings_page = ttk.Frame(self.book, padding=13)
        for page, (name, _, _) in zip((
            self.home, self.action, self.audit_page, self.fault_page,
            self.logs, self.data_page, self.settings_page,
        ), PAGES):
            self.book.add(page, text=name)
        self.build_home()
        self.build_action()
        self.build_audit_results()
        self.build_fault_page()
        self.build_logs()
        self.build_data_management()
        self.build_settings()
        self.book.bind("<<NotebookTabChanged>>", self._navigation_changed)
        self.navigate(0)
        footer = ttk.Frame(self.workspace, padding=(23, 5, 23, 9))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status_line,
                  style="Muted.TLabel").pack(anchor="w")

    def navigate(self, index: int):
        if not 0 <= index < len(PAGES):
            return
        self.book.select(index)
        self._navigation_changed()

    def _navigation_changed(self, _event=None):
        current = self.book.index(self.book.select())
        name, subtitle, _design = PAGES[current]
        self.page_heading.set(name)
        self.page_subtitle.set(subtitle)
        for key, btn in self.nav_controls.items():
            if key == name:
                btn.configure(bg=V2F["sidebar_selected"], fg="white")
            else:
                btn.configure(bg=V2F["sidebar"], fg="#B9C9DE")
        # A sidebar click may bypass the four task cards. Keep the footer
        # tied to the *actual* page, never to a stale prior goal.
        self.status_line.set(
            "当前页面：" + name +
            "  |  只读管理与核验；手动下载和自动修复未开放")

    def _scroll_content(self, parent):
        """Only display a page scrollbar when contents really overflow.

        Data management and settings fit on one page at normal desktop
        sizes. On smaller windows/high-DPI screens, keep a safety fallback
        rather than clipping important read-only settings or coverage notes.
        """
        canvas = tk.Canvas(
            parent, background=COLORS["bg"],
            highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(
            parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        inside = ttk.Frame(canvas, padding=(5, 5, 12, 10))
        window_id = canvas.create_window(
            (0, 0), window=inside, anchor="nw")

        def sync_scrollbar():
            if not canvas.winfo_exists():
                return
            canvas.configure(scrollregion=canvas.bbox("all"))
            viewport = canvas.winfo_height()
            if viewport <= 2:
                return
            overflow = inside.winfo_reqheight() > viewport + 2
            visible = scroll.winfo_manager() == "pack"
            if overflow and not visible:
                scroll.pack(side="right", fill="y", before=canvas)
            elif not overflow and visible:
                scroll.pack_forget()
                canvas.yview_moveto(0)

        def resize_canvas(event):
            canvas.itemconfigure(window_id, width=event.width)
            self.after_idle(sync_scrollbar)

        inside.bind(
            "<Configure>", lambda _event: self.after_idle(sync_scrollbar))
        canvas.bind("<Configure>", resize_canvas)
        return inside

    def _section(self, parent, title, *, fill="x"):
        frame = ttk.LabelFrame(parent, text=title, padding=13)
        frame.pack(fill=fill, pady=(0, 12))
        return frame

    def build_home(self):
        """One-screen desktop dashboard: cards / two columns / fault summary.

        Unlike the long V2E prototype, the homepage has NO outer Canvas and
        NO page scrollbar. Long logs, case JSON and full audit evidence remain
        in their dedicated pages, where local scrollbars are appropriate.
        """
        content = ttk.Frame(self.home)
        content.pack(fill="both", expand=True)
        self.home_dashboard = content
        header = ttk.Frame(content)
        header.pack(fill="x", pady=(0, 7))
        ttk.Label(
            header, text="运行概览",
            style="V2F.SectionHeading.TLabel",
        ).pack(side="left")
        ttk.Label(
            header, text="最近一次任务 · 仅展示有证据的结果",
            style="Muted.TLabel",
        ).pack(side="right")

        # Four key metrics across the top, without separate stacked sections.
        metrics = ttk.Frame(content)
        metrics.pack(fill="x", pady=(0, 9))
        self.cards = {}
        self.card_widgets = {}
        for label in (
            "已提交最新交易日", "上次任务结果", "当前安全截止", "QMT 最近预检",
        ):
            box = ttk.Frame(
                metrics, style="V2F.Card.TFrame", padding=(15, 11))
            box.pack(side="left", fill="both", expand=True, padx=(0, 8))
            ttk.Label(
                box, text=label, style="V2F.MetricHeading.TLabel"
            ).pack(anchor="w", pady=(0, 7))
            value = tk.StringVar(value="—")
            self.cards[label] = value
            widget = ttk.Label(
                box, textvariable=value, style="CardValue.TLabel",
                wraplength=165)
            widget.pack(anchor="w")
            self.card_widgets[label] = widget

        self.last_run_details = tk.StringVar(value="等待读取运行回执")
        self.home_last_run_view = ttk.Label(
            content, textvariable=self.last_run_details,
            style="Muted.TLabel", wraplength=850,
        )
        self.home_last_run_view.pack(anchor="w", pady=(0, 12))

        # Combine validation, four phases, change summary and controls into
        # two balanced columns; this replaces four tall full-width sections.
        # Let the fault summary follow the stage/actions area directly;
        # expanding this frame created a large blank stripe on 1332x882.
        center = ttk.Frame(content)
        center.pack(fill="x", pady=(0, 7))
        left = ttk.Frame(center)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        right = ttk.Frame(center)
        right.pack(side="left", fill="both", expand=True, padx=(5, 0))

        validation = ttk.Frame(
            left, style="V2F.Card.TFrame", padding=(15, 11))
        validation.pack(fill="x", pady=(0, 9))
        ttk.Label(
            validation, text="三类结果独立判定",
            style="V2F.CardHeading.TLabel",
        ).pack(anchor="w", pady=(0, 11))
        badges = ttk.Frame(validation, style="V2F.Card.TFrame")
        badges.pack(fill="x")
        self.validation_vars = {}
        self.validation_value_widgets = {}
        for column, (key, title) in enumerate((
            ("execution", "任务执行"), ("data", "数据核验"),
            ("cross", "跨源状态"),
        )):
            cell = ttk.Frame(badges, style="V2F.Card.TFrame")
            cell.grid(row=0, column=column, sticky="ew", padx=(0, 9))
            badges.columnconfigure(column, weight=1)
            ttk.Label(
                cell, text=title, style="V2F.MetricHeading.TLabel",
            ).pack(anchor="w", pady=(0, 4))
            value = tk.StringVar(value="UNVERIFIED")
            self.validation_vars[key] = value
            widget = ttk.Label(
                cell, textvariable=value, style="CardValue.TLabel")
            widget.pack(anchor="w")
            self.validation_value_widgets[key] = widget

        # Size stage cards to their status text instead of stretching them
        # vertically across the free dashboard space.
        phases = ttk.Frame(
            left, style="V2F.Card.TFrame", padding=(13, 9))
        phases.pack(fill="x")
        ttk.Label(
            phases, text="本轮四个阶段",
            style="V2F.CardHeading.TLabel",
        ).pack(anchor="w", padx=2, pady=(0, 8))
        self.stage_labels = {}
        self.stage_widgets = {}
        matrix = ttk.Frame(phases, style="V2F.Card.TFrame")
        matrix.pack(fill="x")
        for column in (0, 1):
            matrix.columnconfigure(column, weight=1)
        for index, (key, name) in enumerate(STAGES):
            cell = tk.Frame(
                matrix, background=V2F["surface"],
                highlightbackground=V2F["border"],
                highlightthickness=1, bd=0, padx=11, pady=8)
            cell.grid(
                row=index // 2, column=index % 2,
                sticky="ew", padx=3, pady=3)
            tk.Label(
                cell, text=name, background=V2F["surface"],
                foreground=V2F["secondary"],
                font=("Microsoft YaHei UI", 9),
                anchor="w",
            ).pack(anchor="w", pady=(0, 5))
            value = tk.StringVar(value="未记录")
            self.stage_labels[key] = value
            widget = ttk.Label(
                cell, textvariable=value,
                style="Neutral.Section.TLabel", wraplength=230,
                justify="left")
            widget.pack(anchor="w")
            self.stage_widgets[key] = widget

        progress = ttk.Frame(
            right, style="V2F.Card.TFrame", padding=(15, 12))
        progress.pack(fill="x", pady=(0, 9))
        ttk.Label(
            progress, text="本次可信变化",
            style="V2F.CardHeading.TLabel",
        ).pack(anchor="w", pady=(0, 9))
        self.overview_info = tk.StringVar(value="暂无可比证据")
        self.home_progress_view = ttk.Label(
            progress, textvariable=self.overview_info,
            style="Section.TLabel", wraplength=300,
            justify="left")
        self.home_progress_view.pack(anchor="w")
        self.home_progress_note = ttk.Label(
            progress, text="没有完整前后快照，不展示猜测的增量或覆盖率。",
            style="V2F.CardNote.TLabel", wraplength=300)
        self.home_progress_note.pack(anchor="w", pady=(4, 0))

        actions = ttk.Frame(
            right, style="V2F.Card.TFrame", padding=(15, 12))
        actions.pack(fill="x")
        ttk.Label(
            actions, text="我要做什么？",
            style="V2F.CardHeading.TLabel",
        ).grid(row=0, column=0, columnspan=2,
               sticky="w", padx=3, pady=(0, 8))
        for column in (0, 1):
            actions.columnconfigure(column, weight=1)
        self.task_buttons = {}
        for index, task in enumerate(TASKS):
            task_cell = ttk.Frame(
                actions, style="V2F.Card.TFrame", padding=(7, 4))
            task_cell.grid(
                row=index // 2 + 1, column=index % 2,
                sticky="nsew", padx=2, pady=2)
            task_button = ttk.Button(
                task_cell, text=task["title"],
                style=("Primary.TButton" if task["id"] == "audit"
                       else "TButton"),
                command=lambda task_id=task["id"]:
                    self.open_workflow(task_id))
            task_button.pack(fill="x")
            ttk.Label(
                task_cell, text=task["subtitle"] + " · " +
                task["availability"],
                style="V2F.CardNote.TLabel",
                wraplength=190, justify="center",
            ).pack(anchor="center", pady=(3, 0))
            self.task_buttons[task["id"]] = task_button
        guidance = ttk.Frame(
            actions, style="V2F.Card.TFrame")
        guidance.grid(row=3, column=0, columnspan=2,
                      sticky="ew", padx=5, pady=(8, 1))
        self.workflow_recommendation = ttk.Label(
            guidance, textvariable=self.workflow_hint,
            style="V2F.CardNote.TLabel", wraplength=260,
            justify="left")
        self.workflow_recommendation.pack(side="left", fill="x", expand=True)
        self.follow_recommendation_button = ttk.Button(
            guidance, text="按建议继续",
            command=self.follow_recommendation)
        self.follow_recommendation_button.pack(
            side="right", padx=(7, 0))
        self.quick_tools_toggle = ttk.Button(
            actions, text="展开高级只读检查",
            command=self.toggle_home_tools)
        self.quick_tools_toggle.grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=5,
            pady=(6, 0))
        self.quick_tools_frame = ttk.Frame(
            actions, style="V2F.Card.TFrame")
        self.quick_tools_frame.grid(
            row=5, column=0, columnspan=2, sticky="ew",
            padx=5, pady=(5, 0))
        self.quick_tools_frame.grid_remove()
        qmt = ttk.Button(
            self.quick_tools_frame, text="检查QMT连接（不下载）",
            command=self.start_qmt_live_probe)
        qmt.pack(fill="x", pady=(0, 4))
        self.qmt_probe_buttons.append(qmt)
        inventory = ttk.Button(
            self.quick_tools_frame, text="核对正式版本与备份范围（只读）",
            command=self.start_finance_inventory)
        inventory.pack(fill="x")
        self.inventory_buttons.append(inventory)

        # A short full-width diagnosis strip replaces the old tall incident
        # panel. Detailed case rows and original JSON belong in Faults.
        alert_rail = tk.Frame(
            content, bg=V2F["border"], borderwidth=0, padx=3)
        alert_rail.pack(fill="x", pady=(3, 0))
        self.home_alert_rail = alert_rail
        issues = ttk.Frame(
            alert_rail, style="V2F.Card.TFrame", padding=(15, 10))
        issues.pack(fill="x")
        ttk.Label(
            issues, text="待处理事项与下一步",
            style="V2F.CardHeading.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        headline = ttk.Frame(issues, style="V2F.Card.TFrame")
        headline.pack(fill="x", pady=(0, 4))
        self.fault_headline = tk.StringVar(value="等待诊断")
        self.fault_explanation = tk.StringVar(value="尚无可用证据")
        self.fault_resume_gate = tk.StringVar(value="安全续跑：尚未核对")
        self.fault_title_view = ttk.Label(
            headline, textvariable=self.fault_headline,
            style="Neutral.Section.TLabel",
            font=("Microsoft YaHei UI", 10, "bold"),
            wraplength=790, justify="left")
        self.fault_title_view.pack(side="left", fill="x", expand=True)
        self.home_issue_views = [self.fault_title_view]
        self.cards["财务待审"] = tk.StringVar(value="未记录")
        pending = ttk.Frame(headline, style="V2F.Card.TFrame")
        pending.pack(side="right", padx=(12, 0))
        ttk.Label(
            pending, text="财务待审", style="V2F.CardNote.TLabel").pack(side="left")
        widget = ttk.Label(
            pending, textvariable=self.cards["财务待审"],
            style="Neutral.CardValue.TLabel")
        widget.pack(side="left", padx=(8, 0))
        self.card_widgets["财务待审"] = widget
        for var, style, gap in (
            (self.fault_explanation, "Section.TLabel", 3),
            (self.fault_resume_gate, "Warning.Section.TLabel", 3),
            (self.qmt_gate_summary, "V2F.CardNote.TLabel", 3),
            (self.finance_inventory_status, "V2F.CardNote.TLabel", 0),
        ):
            view = ttk.Label(
                issues, textvariable=var, style=style,
                wraplength=640, justify="left")
            view.pack(anchor="w", pady=(0, gap))
            self.home_issue_views.append(view)
        self.home.bind("<Configure>", self._resize_home_wrapping)

    def sync_workflow_mode(self):
        """Keep the guided banner consistent when radio buttons are changed."""
        if self.mode.get() == "数据核验":
            self.workflow_tip.set(workflow_guide("audit"))
        elif self.mode.get() == "更新数据":
            self.workflow_tip.set(workflow_guide("update"))

    def open_workflow(self, task_id):
        """Navigate to the right *read-only* capability, never execute."""
        task_by_id(task_id)  # invalid/forged UI task names fail closed
        self.workflow_current_task = task_id
        self.workflow_tip.set(workflow_guide(task_id))
        if task_id == "update":
            self.go_action("更新数据")
        elif task_id == "audit":
            self.go_action("数据核验")
        elif task_id == "diagnose":
            self.open_fault_page()
        elif task_id == "manage":
            self.navigate(PAGE_MAP["数据管理"])
        self.status_line.set(
            "当前目标：" + task_by_id(task_id)["title"] +
            "；V2G仅提供预览、只读核验与故障诊断，下载和自动修复未开放")

    def follow_recommendation(self):
        """The recommendation only opens a page, never starts an operation."""
        self.open_workflow(self.recommended_task_id)

    def toggle_home_tools(self):
        """Show advanced diagnostics on demand; never run them on expand."""
        self.quick_tools_shown = not self.quick_tools_shown
        if self.quick_tools_shown:
            self.quick_tools_frame.grid()
            self.quick_tools_toggle.configure(text="收起高级只读检查")
        else:
            self.quick_tools_frame.grid_remove()
            self.quick_tools_toggle.configure(text="展开高级只读检查")

    def _resize_home_wrapping(self, event):
        """Wrap only dashboard prose on narrow windows, never hide an action."""
        available = max(300, event.width - 45)
        if abs(available - getattr(self, "_home_wrap_width", 0)) < 9:
            return
        self._home_wrap_width = available
        self.home_last_run_view.configure(wraplength=available)
        self.fault_title_view.configure(wraplength=max(220, available - 160))
        for view in self.home_issue_views[1:]:
            view.configure(wraplength=available)
        phase_width = max(145, int(available * 0.25) - 25)
        for view in self.stage_widgets.values():
            view.configure(wraplength=phase_width)
        progress_width = max(210, int(available * 0.42) - 25)
        self.home_progress_view.configure(wraplength=progress_width)
        self.home_progress_note.configure(wraplength=progress_width)

    def build_action(self):
        ttk.Label(
            self.action, textvariable=self.workflow_tip,
            style="V2F.SectionHeading.TLabel",
            wraplength=1050, justify="left",
        ).pack(anchor="w", pady=(0, 7))
        ttk.Label(
            self.action, text="同一组日期、股票和数据类型用于更新与核验；切换模式不重置输入。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 12))
        steps = ttk.Notebook(self.action)
        steps.pack(fill="both", expand=True)
        self.action_steps = steps
        scope_step = ttk.Frame(steps, padding=16)
        stocks_step = ttk.Frame(steps, padding=16)
        review_step = ttk.Frame(steps, padding=16)
        steps.add(scope_step, text="  ① 方式与日期  ")
        steps.add(stocks_step, text="  ② 股票与数据  ")
        steps.add(review_step, text="  ③ 安全预检 / 核验  ")
        choose = self._section(scope_step, "操作方式")
        for mode in ("更新数据", "数据核验"):
            ttk.Radiobutton(choose, text=mode, value=mode,
                            variable=self.mode).pack(side="left", padx=(0, 25))
        self.mode.trace_add("write", lambda *_: self.sync_workflow_mode())
        history = self._section(scope_step, "已有历史数据如何处理（仅更新模式）")
        for mode in HISTORY_POLICIES:
            ttk.Radiobutton(history, text=mode, value=mode,
                            variable=self.history_policy).pack(anchor="w", pady=5)
        ttk.Label(history, text="补缺失先核验；重新获取仅比对；修复必须审核。写入均未开放。",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        calendar = self._section(scope_step, "日期范围 · 包含起止日")
        fields = ttk.Frame(calendar)
        fields.pack(anchor="w")
        ttk.Label(fields, text="开始日期").pack(side="left")
        ttk.Entry(fields, textvariable=self.start, width=14).pack(
            side="left", padx=(8, 22))
        ttk.Label(fields, text="结束日期").pack(side="left")
        ttk.Entry(fields, textvariable=self.end, width=14).pack(
            side="left", padx=8)
        ttk.Label(calendar, text="北京时间 20:05 候选安全截止；交易日历尚未认证。",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Button(scope_step, text="下一步：股票与数据 →", style="Primary.TButton",
                   command=lambda: steps.select(1)).pack(anchor="e", pady=12)

        stocks = self._section(stocks_step, "股票范围")
        scopes = ttk.Frame(stocks)
        scopes.pack(fill="x")
        for scope in ("全部股票", "指定股票"):
            ttk.Radiobutton(scopes, text=scope, variable=self.scope,
                            value=scope).pack(side="left", padx=(0, 18))
        self.stock_count = tk.StringVar(value="股票列表未验证")
        ttk.Label(scopes, textvariable=self.stock_count,
                  style="Muted.TLabel").pack(side="right")
        holder = ttk.Frame(stocks)
        holder.pack(fill="x", pady=8)
        self.stock_box = tk.Text(
            holder, height=4, wrap="word", font=("Consolas", 10),
            background=COLORS["surface"], foreground=COLORS["navy"],
            selectbackground=COLORS["blue"],
        )
        vs = ttk.Scrollbar(holder, orient="vertical",
                           command=self.stock_box.yview)
        self.stock_box.configure(yscrollcommand=vs.set)
        self.stock_box.pack(side="left", fill="x", expand=True)
        vs.pack(side="right", fill="y")
        self.stock_box.insert("1.0", "000001.SZ, 600519.SH")
        ttk.Label(stocks, text="指定股票最多 500 只；必须保留 .SH/.SZ/.BJ 后缀。",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Button(stocks, text="检查股票代码与去重",
                   command=self.check_stocks).pack(anchor="e", pady=5)
        self.scope.trace_add("write", lambda *_: self.sync_stock_scope())
        self.sync_stock_scope()
        types = self._section(stocks_step, "数据类型（可多选）")
        for name in MODULES:
            ttk.Checkbutton(types, text=name, variable=self.modules[name]).pack(
                side="left", padx=(0, 30))
        sources = self._section(stocks_step, "自动来源说明 · 不支持手选供应商")
        ttk.Label(sources, textvariable=self.source_line,
                  style="Section.TLabel", wraplength=910, justify="left").pack(
                      anchor="w")
        ttk.Button(stocks_step, text="下一步：安全预检 →",
                   style="Primary.TButton",
                   command=lambda: steps.select(2)).pack(anchor="e", pady=12)

        intro = self._section(review_step, "计划预检 · 写入功能未开放")
        self.preview_text = tk.Text(
            intro, height=9, wrap="word", borderwidth=0,
            font=("Microsoft YaHei UI", 10),
            background="#EDF5FF", foreground=COLORS["navy"],
            padx=12, pady=10,
        )
        self.preview_text.pack(fill="x")
        self.preview_text.insert(
            "1.0", "选择共享的日期、股票和模块，再点击「预览计划」。\n"
            "仅可执行已有受限历史行情只读核验，绝不隐式触发生产更新。")
        self.preview_text.configure(state="disabled")
        row = ttk.Frame(review_step)
        row.pack(fill="x", pady=(4, 12))
        ttk.Button(row, text="预览计划", style="Primary.TButton",
                   command=self.show_preview).pack(side="left")
        ttk.Button(row, text="复制只读计划",
                   command=self.copy_preview).pack(side="left", padx=8)
        audit = self._section(review_step, "受限历史行情只读核验")
        ttk.Label(audit, text="仅支持指定股票、八周期行情中的一个周期；不下载、不修复。",
                  style="Section.TLabel").pack(anchor="w")
        audit_row = ttk.Frame(audit)
        audit_row.pack(fill="x", pady=9)
        self.audit_period = getattr(self, "audit_period", tk.StringVar(value="day"))
        ttk.Label(audit_row, text="周期").pack(side="left")
        ttk.Combobox(audit_row, textvariable=self.audit_period, values=PERIODS,
                     state="readonly", width=13).pack(side="left", padx=9)
        self.audit_button = ttk.Button(
            audit_row, text="启动受限只读核验",
            style="Primary.TButton", command=self.run_readonly_audit,
        )
        self.audit_button.pack(side="left", padx=6)
        if self.market_root is None:
            self.audit_button.configure(state="disabled")
        self.audit_ceiling_note = tk.StringVar(
            value="最多20股、31日；旧版默认截止2026-11-19；"
                  "如提交账本证据允许，可只读核验已提交的更近日期。")
        ttk.Label(audit, textvariable=self.audit_ceiling_note,
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Button(review_step, text="← 修改配置",
                   command=lambda: steps.select(0)).pack(anchor="w", pady=8)

    def build_audit_results(self):
        ttk.Label(self.audit_page,
                  text="结果仅代表实际扫描到的物理记录；不是官方交易日或上市资格认证。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 9))
        guide = ttk.Frame(
            self.audit_page, style="V2F.Card.TFrame", padding=(13, 9))
        guide.pack(fill="x", pady=(0, 8))
        self.audit_flow_title = tk.StringVar(
            value="步骤 1/3：选择股票、日期和周期，启动受限只读核验")
        self.audit_flow_next = tk.StringVar(
            value="核验后先查看物理观察，再按选中记录逐项复核；修复未开放。")
        ttk.Label(guide, textvariable=self.audit_flow_title,
                  style="V2F.CardHeading.TLabel",
                  wraplength=960, justify="left").pack(anchor="w")
        ttk.Label(guide, textvariable=self.audit_flow_next,
                  style="V2F.CardNote.TLabel",
                  wraplength=1000, justify="left").pack(
                      anchor="w", pady=(4, 0))
        cards = ttk.Frame(self.audit_page)
        cards.pack(fill="x", pady=(0, 8))
        self.audit_cards = {}
        for label in ("已观察记录", "异常待复核", "未观察/待确认", "缺失候选"):
            box = ttk.LabelFrame(cards, text=label,
                                 style="Card.TLabelframe", padding=10)
            box.pack(side="left", fill="x", expand=True, padx=(0, 8))
            item = tk.StringVar(value="—")
            self.audit_cards[label] = item
            ttk.Label(box, textvariable=item,
                      style="CardValue.TLabel").pack(anchor="w")
        self.audit_evidence_note = tk.StringVar(value="本次尚未执行核验")
        ttk.Label(self.audit_page, textvariable=self.audit_evidence_note,
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.audit_split = ttk.PanedWindow(self.audit_page, orient="horizontal")
        self.audit_split.pack(fill="both", expand=True)
        table_frame = ttk.LabelFrame(self.audit_split,
                                     text="股票 · 周期 · 日期观察明细", padding=8)
        self.audit_detail_frame = ttk.LabelFrame(
            self.audit_split, text="所选记录 · 只读原始证据", padding=8)
        self.audit_split.add(table_frame, weight=3)
        self.audit_split.add(self.audit_detail_frame, weight=2)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = ("period", "symbol", "date", "count", "physical", "interpretation")
        self.audit_table = ttk.Treeview(table_frame, columns=columns,
                                        show="headings", selectmode="browse")
        self.audit_sort_reverse = {}
        for key, title, width in (
            ("period", "周期", 52), ("symbol", "股票", 103),
            ("date", "时间戳日期", 101), ("count", "行数", 43),
            ("physical", "物理观察", 87),
            ("interpretation", "证据判定", 155),
        ):
            self.audit_table.heading(
                key, text=title,
                command=lambda col=key: self._sort_audit_column(col),
            )
            self.audit_table.column(key, width=width,
                                    stretch=(key == "interpretation"))
        y = ttk.Scrollbar(table_frame, orient="vertical",
                          command=self.audit_table.yview)
        x = ttk.Scrollbar(table_frame, orient="horizontal",
                          command=self.audit_table.xview)
        self.audit_table.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.audit_table.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        for key, shade in (
            ("alert", COLORS["red"]), ("candidate", COLORS["amber"]),
            ("neutral", COLORS["navy"]),
        ):
            self.audit_table.tag_configure(key, foreground=shade)
        self.audit_table_rows = {}
        self.audit_table.bind("<<TreeviewSelect>>", self._select_audit_row)
        self.audit_detail_frame.columnconfigure(0, weight=1)
        self.audit_detail_frame.rowconfigure(2, weight=1)
        self.audit_result_text = tk.Text(
            self.audit_detail_frame, wrap="word", borderwidth=0, state="disabled",
            font=("Consolas", 9), background=COLORS["log_bg"],
            foreground=COLORS["log_fg"], padx=9, pady=9,
        )
        ys = ttk.Scrollbar(self.audit_detail_frame, orient="vertical",
                           command=self.audit_result_text.yview)
        self.audit_result_text.configure(yscrollcommand=ys.set)
        self.audit_result_text.grid(row=2, column=0, sticky="nsew")
        ys.grid(row=2, column=1, sticky="ns")
        self.audit_raw_scroll = ys
        self.audit_selection_guide = ttk.Frame(
            self.audit_detail_frame, style="V2F.Card.TFrame", padding=(9, 7))
        self.audit_selection_guide.grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        self.audit_selected_title = tk.StringVar(
            value="步骤 2/3：选择左侧记录，查看对应的异常原因与复核条件")
        self.audit_selected_next = tk.StringVar(
            value="所有结论仍是只读观察，不代表缺失已经认证。")
        ttk.Label(
            self.audit_selection_guide, textvariable=self.audit_selected_title,
            style="V2F.CardHeading.TLabel", wraplength=350,
            justify="left").pack(anchor="w")
        ttk.Label(
            self.audit_selection_guide, textvariable=self.audit_selected_next,
            style="V2F.CardNote.TLabel", wraplength=350,
            justify="left").pack(anchor="w", pady=(4, 0))
        self.audit_selected_review = None
        self.audit_raw_toggle = ttk.Button(
            self.audit_detail_frame,
            text="展开原始 JSON（技术证据）",
            command=self.toggle_audit_raw_json,
        )
        self.audit_raw_toggle.grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 5))
        self.audit_raw_visible = False
        self.audit_result_text.grid_remove()
        self.audit_raw_scroll.grid_remove()
        bottom = ttk.Frame(self.audit_page)
        bottom.pack(fill="x", pady=(8, 0))
        self.audit_details_visible = True
        self.audit_details_button = ttk.Button(
            bottom, text="隐藏右侧证据", command=self._toggle_audit_details)
        self.audit_details_button.pack(side="left")
        self.audit_retry_scope = ttk.Button(
            bottom, text="返回调整核验范围",
            command=lambda: self.open_workflow("audit"))
        self.audit_retry_scope.pack(side="left", padx=(8, 0))
        self.audit_copy_review = ttk.Button(
            bottom, text="复制本条复核清单（不修复）",
            command=self.copy_selected_audit_review, state="disabled")
        self.audit_copy_review.pack(side="left", padx=(8, 0))
        self.audit_repair_disabled = ttk.Button(
            bottom, text="自动修复（未开放）", state="disabled")
        self.audit_repair_disabled.pack(side="right")
        self.audit_raw_report = "暂无核验结果。前往「更新 / 核验」选择范围并启动只读核验。"
        self._set_audit_text(self.audit_raw_report)
        # Keep the actions visible above the large table even on a 1350x890
        # Windows laptop, while the table takes the remaining height.
        bottom.pack_configure(before=self.audit_split, pady=(0, 8))

    def toggle_audit_raw_json(self):
        """Reveal full existing evidence on demand; never reread the market."""
        self.audit_raw_visible = not self.audit_raw_visible
        if self.audit_raw_visible:
            self.audit_result_text.grid()
            self.audit_raw_scroll.grid()
            self.audit_raw_toggle.configure(text="收起原始 JSON（技术证据）")
        else:
            self.audit_result_text.grid_remove()
            self.audit_raw_scroll.grid_remove()
            self.audit_raw_toggle.configure(text="展开原始 JSON（技术证据）")

    def _select_audit_row(self, _event=None):
        """Keep original raw evidence and show a separate market-data review."""
        super()._select_audit_row(_event)
        selected = self.audit_table.selection()
        row = (self.audit_table_rows.get(selected[0])
               if selected else None)
        try:
            if row is None:
                raise AuditFlowBlocked("no_selected_market_observation")
            review = explain_observation(row)
        except AuditFlowBlocked:
            self.audit_selected_review = None
            self.audit_selected_title.set(
                "步骤 2/3：请选择要复核的行情观察行")
            self.audit_selected_next.set(
                "没有可信观察时，不能推断缺失、生成恢复许可或修改行情。")
            self.audit_copy_review.configure(state="disabled")
            return
        self.audit_selected_review = review
        self.audit_selected_title.set(
            "步骤 2/3：" + review["focus"] + " · " + review["title"])
        self.audit_selected_next.set(
            "下一步：" + review["next_step"] +
            "\n复核前提：" + review["required_evidence"] +
            "\n步骤 3/3：仅能生成复核清单，自动修复未开放。")
        self.audit_copy_review.configure(state="normal")

    def _poll_audit(self):
        """Use the existing guarded scanner, then interpret its read-only JSON.

        No extra market I/O, no retry of the scanner, no QMT connection.
        """
        super()._poll_audit()
        if self.audit_running:
            self.audit_selected_review = None
            self.audit_copy_review.configure(state="disabled")
            self.audit_flow_title.set(
                "步骤 1/3：只读核验正在进行，尚无本轮结果")
            self.audit_flow_next.set(
                "等待有界物理扫描结束；期间不能复制旧结果或触发自动修复。")
            return
        self.audit_selected_review = None
        self.audit_copy_review.configure(state="disabled")
        self.audit_selected_title.set(
            "步骤 2/3：选择左侧观察行，查看对应的复核条件")
        self.audit_selected_next.set(
            "本工具不提供自动补缺、历史覆盖或写入能力。")
        try:
            report = json.loads(self.audit_raw_report)
            summary = summarize_readonly_report(report)
        except (ValueError, TypeError, AuditFlowBlocked):
            if self.audit_raw_report.startswith("核验阻断"):
                self.audit_flow_title.set(
                    "核验已阻断：当前没有可用于修复的结果")
                self.audit_flow_next.set(
                    "检查任务占用、只读范围或读取预算；不得自动重试写入。")
            else:
                self.audit_flow_title.set(
                    "步骤 1/3：先从「更新 / 核验」启动一次有界只读核验")
                self.audit_flow_next.set(
                    "历史行情尚无有效观察，不能给出缺失或修复结论。")
            return
        self.audit_flow_title.set(
            "步骤 1/3 已完成：" + summary["title"])
        self.audit_flow_next.set(summary["next_step"] +
                                 " 已确认缺失：0；下载和修复不可用。")
        # The original controller retains raw status codes in memory/JSON.
        # Translate only the visible physical-observation column so the
        # entire row (including symbol) fits a normal-width split pane.
        labels = {
            "ROWS_OBSERVED_UNCERTIFIED": "有记录",
            "ANOMALY_OBSERVED": "物理异常",
            "NO_ROWS_OBSERVED": "无记录",
        }
        for ident, observed in self.audit_table_rows.items():
            values = list(self.audit_table.item(ident, "values"))
            if len(values) == 6:
                values[4] = labels.get(
                    observed.get("physical_status"), "待核实")
                self.audit_table.item(ident, values=values)
        self.audit_table.xview_moveto(0)
        # No action is taken by selection: show the first row's human
        # explanation immediately, rather than an empty panel plus raw JSON.
        children = self.audit_table.get_children()
        if children and not self.audit_table.selection():
            self.audit_table.selection_set(children[0])
            self._select_audit_row()

    def copy_selected_audit_review(self):
        """Copy only selected non-executable market review guidance."""
        selected = self.audit_table.selection()
        if not selected:
            return
        row = self.audit_table_rows.get(selected[0])
        try:
            if row is None:
                return
            review = explain_observation(row)
            content = format_review_text(review)
        except (AuditFlowBlocked, KeyError, TypeError):
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        self.status_line.set(
            "已复制行情只读复核清单；未调用QMT、未下载或修改数据")

    def _toggle_audit_details(self):
        if self.audit_details_visible:
            self.audit_split.forget(self.audit_detail_frame)
            self.audit_details_visible = False
            self.audit_details_button.configure(text="显示右侧证据")
        else:
            self.audit_split.add(self.audit_detail_frame, weight=2)
            self.audit_details_visible = True
            self.audit_details_button.configure(text="隐藏右侧证据")

    def build_fault_page(self):
        header = ttk.Frame(self.fault_page)
        header.pack(fill="x", pady=(0, 9))
        ttk.Label(header, text="故障 → 证据 → 安全处置（不自动修复）",
                  style="V2E.Heading.TLabel").pack(side="left")
        ttk.Button(header, text="刷新本轮诊断",
                   command=self.refresh_overview).pack(side="right")
        triage_summary = ttk.LabelFrame(self.fault_page, text="本轮诊断摘要与安全门禁", padding=9)
        triage_summary.pack(fill="x", pady=(0, 9))
        self.fault_page_headline_view = ttk.Label(
            triage_summary, textvariable=self.fault_headline,
            style="Neutral.Section.TLabel", wraplength=960,
        )
        self.fault_page_headline_view.pack(anchor="w")
        ttk.Label(triage_summary, textvariable=self.fault_explanation,
                  style="Section.TLabel", wraplength=960).pack(anchor="w", pady=4)
        ttk.Label(triage_summary, textvariable=self.fault_resume_gate,
                  style="Warning.Section.TLabel", wraplength=960).pack(anchor="w")
        self.fault_split = ttk.PanedWindow(self.fault_page, orient="horizontal")
        self.fault_split.pack(fill="both", expand=True)
        left = ttk.LabelFrame(self.fault_split, text="同一轮任务 · 错误及待续批次", padding=8)
        right = ttk.LabelFrame(self.fault_split, text="证据、检查点与下一步", padding=9)
        self.fault_split.add(left, weight=3)
        self.fault_split.add(right, weight=2)
        self.selected_fault_code = tk.StringVar(
            value="在左侧选择错误，可查看完整错误代码。")
        ttk.Label(
            right, textvariable=self.selected_fault_code,
            style="V2F.CardNote.TLabel",
            wraplength=380, justify="left",
        ).pack(anchor="w", pady=(0, 7))
        gates = ttk.Frame(right, style="V2F.Card.TFrame", padding=(11, 9))
        gates.pack(fill="x", pady=(0, 9))
        ttk.Label(
            gates, text="恢复前应该做什么？",
            style="V2F.CardHeading.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        self.fault_step_labels = []
        for number, title, explanation in (
            ("1", "查看错误与同轮日志", "确认失败阶段和最后检查点"),
            ("2", "按需检查 QMT 当前连接", "仅探测连接，不下载数据"),
            ("3", "核对代码与财务版本", "核对范围，不代表已备份或批准"),
            ("4", "等待受控恢复入口", "不重放旧日任务、不清空游标"),
        ):
            step = ttk.Frame(gates, style="V2F.Card.TFrame")
            step.pack(fill="x", pady=(0, 7))
            ttk.Label(
                step, text=number + ".",
                style="V2F.CardHeading.TLabel",
                width=3,
            ).pack(side="left", anchor="n")
            description = ttk.Frame(step, style="V2F.Card.TFrame")
            description.pack(side="left", fill="x", expand=True)
            title_view = ttk.Label(
                description, text=title,
                style="V2F.CardHeading.TLabel")
            title_view.pack(anchor="w")
            ttk.Label(
                description, text=explanation,
                style="V2F.CardNote.TLabel", wraplength=350,
                justify="left",
            ).pack(anchor="w", pady=(2, 0))
            self.fault_step_labels.append(title_view)

        self.fault_gate_toggle = ttk.Button(
            right, text="展开恢复门禁详情（只读）",
            command=self.toggle_fault_gate_details)
        self.fault_gate_toggle.pack(anchor="w", pady=(0, 6))
        self.fault_gate_frame = ttk.Frame(
            right, style="V2F.Card.TFrame", padding=(9, 7))
        self.fault_gate_frame.pack(fill="x", pady=(0, 7))
        self.fault_gate_visible = False
        ttk.Label(
            self.fault_gate_frame, textvariable=self.qmt_gate_details,
            style="Section.TLabel", wraplength=360,
            justify="left",
        ).pack(anchor="w")
        ttk.Label(
            self.fault_gate_frame, textvariable=self.finance_inventory_status,
            style="V2F.CardNote.TLabel", wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(5, 0))
        ttk.Label(
            self.fault_gate_frame,
            textvariable=self.historical_inventory_summary,
            style="V2F.CardNote.TLabel", wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))
        self.fault_gate_frame.pack_forget()
        cols = ("severity", "stage", "type", "description")
        self.fault_tree = ttk.Treeview(
            left, columns=cols, show="headings", selectmode="browse")
        for key, title, width in (
            ("severity", "等级", 65), ("stage", "阶段", 80),
            ("type", "类别", 210), ("description", "问题及范围", 250),
        ):
            self.fault_tree.heading(key, text=title)
            self.fault_tree.column(key, width=width,
                                   stretch=(key == "description"))
        ys = ttk.Scrollbar(left, orient="vertical", command=self.fault_tree.yview)
        self.fault_tree.configure(yscrollcommand=ys.set)
        self.fault_tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.fault_tree.bind("<<TreeviewSelect>>", self._select_fault)
        self.fault_case_by_row = {}
        self.fault_technical_toggle = ttk.Button(
            right, text="展开原始证据（技术详情）",
            command=self.toggle_fault_technical)
        self.fault_technical_toggle.pack(anchor="w", pady=(7, 4))
        evidence = ttk.Frame(right)
        evidence.pack(fill="both", expand=True)
        self.fault_technical_frame = evidence
        self.fault_technical_visible = False
        self.fault_detail_text = tk.Text(
            evidence, wrap="word", height=15, font=("Consolas", 9),
            background=COLORS["log_bg"], foreground=COLORS["log_fg"],
            borderwidth=0, padx=9, pady=9, state="disabled",
        )
        y = ttk.Scrollbar(evidence, orient="vertical",
                          command=self.fault_detail_text.yview)
        self.fault_detail_text.configure(yscrollcommand=y.set)
        self.fault_detail_text.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")
        evidence.pack_forget()
        buttons = ttk.Frame(self.fault_page)
        buttons.pack(fill="x", pady=(10, 0))
        actions_top = ttk.Frame(buttons)
        actions_top.pack(fill="x")
        actions_bottom = ttk.Frame(buttons)
        actions_bottom.pack(fill="x", pady=(7, 0))
        ttk.Button(actions_top, text="查看选中阶段日志",
                   command=self.show_selected_fault_log).pack(side="left")
        ttk.Button(actions_top, text="复制安全续跑预览",
                   command=self.copy_finance_resume_preview).pack(
                       side="left", padx=8)
        live = ttk.Button(actions_top, text="检查 QMT 连接（不下载）",
                          command=self.start_qmt_live_probe)
        live.pack(side="left", padx=8)
        self.qmt_probe_buttons.append(live)
        short_scope = ttk.Button(actions_bottom, text="版本指纹与当天范围",
                                 command=self.start_finance_inventory)
        short_scope.pack(side="left")
        self.inventory_buttons.append(short_scope)
        all_scope = ttk.Button(actions_bottom, text="历史财务版本范围（只读）",
                               command=self.start_historical_inventory)
        all_scope.pack(side="left", padx=8)
        self.historical_inventory_buttons.append(all_scope)
        self.fault_repair_disabled = ttk.Button(
            actions_bottom, text="一键重试（未开放）", state="disabled")
        self.fault_repair_disabled.pack(side="left", padx=8)
        ttk.Label(self.fault_page,
                  text="故障以本轮回执和检查点为准。连接测试、文件清单均不能解锁写入；20:05 任务不变。",
                  style="Muted.TLabel").pack(anchor="w", pady=(7, 0))

    def _select_fault(self, _event=None):
        """Keep original evidence selection; reveal full error type in prose."""
        super()._select_fault(_event)
        selected = self.fault_tree.selection()
        case = (self.fault_case_by_row.get(selected[0])
                if selected else None)
        if isinstance(case, dict):
            self.selected_fault_code.set(
                "当前错误代码：" + str(case.get("category", "未提供")))
        else:
            self.selected_fault_code.set(
                "在左侧选择错误，可查看完整错误代码。")

    def toggle_fault_gate_details(self):
        """Disclose complete gate notes without running a probe."""
        self.fault_gate_visible = not self.fault_gate_visible
        if self.fault_gate_visible:
            self.fault_gate_frame.pack(
                fill="x", pady=(0, 7), before=self.fault_technical_toggle)
            self.fault_gate_toggle.configure(
                text="收起恢复门禁详情（只读）")
        else:
            self.fault_gate_frame.pack_forget()
            self.fault_gate_toggle.configure(
                text="展开恢复门禁详情（只读）")

    def toggle_fault_technical(self):
        """Evidence stays readable; its raw JSON is collapsed by default."""
        self.fault_technical_visible = not self.fault_technical_visible
        if self.fault_technical_visible:
            self.fault_technical_frame.pack(fill="both", expand=True)
            self.fault_technical_toggle.configure(
                text="收起原始证据（技术详情）")
        else:
            self.fault_technical_frame.pack_forget()
            self.fault_technical_toggle.configure(
                text="展开原始证据（技术详情）")

    def start_historical_inventory(self):
        """Only the explicit button triggers bounded metadata-only inspection."""
        if self.historical_inventory_running:
            return
        if self.market_root is None:
            messagebox.showinfo(
                "尚未指定市场目录",
                "启动时必须显式指定 --market-root，才能只读盘点历史财务版本。")
            return
        self.historical_inventory_running = True
        self.historical_inventory_result = None
        generation = self.fault_diagnosis_generation
        receipt_sha = (self.fault_diagnosis or {}).get("receipt_sha256")
        progress_sha = (self.fault_diagnosis or {}).get("finance_progress_sha256")
        for button in self.historical_inventory_buttons:
            button.state(["disabled"])
        self.historical_inventory_summary.set(
            "正在只读统计失败批次的历史财务快照和活动指针；不创建备份。")

        def worker():
            try:
                report = inventory_historical_versions(
                    state_module=self.state_module,
                    market_root=self.market_root)
            except (PreflightBlocked, FaultEvidenceBlocked, OSError, ValueError) as exc:
                report = {
                    "status": "V2E_HISTORY_INVENTORY_BLOCKED",
                    "detail": str(exc)[:160], "can_execute": False,
                }
            except Exception as exc:
                report = {
                    "status": "V2E_HISTORY_INVENTORY_FAILED",
                    "detail": "unexpected_" + type(exc).__name__,
                    "can_execute": False,
                }
            self.historical_inventory_queue.put(
                (generation, receipt_sha, progress_sha, report))

        threading.Thread(
            target=worker, name="v2e-finance-history-readonly",
            daemon=True).start()
        self.after(160, self._poll_historical_inventory)

    def _poll_historical_inventory(self):
        try:
            generation, receipt_sha, progress_sha, report = (
                self.historical_inventory_queue.get_nowait())
        except queue.Empty:
            if self.historical_inventory_running:
                self.after(160, self._poll_historical_inventory)
            return
        self.historical_inventory_running = False
        for button in self.historical_inventory_buttons:
            button.state(["!disabled"])
        current = self.fault_diagnosis
        stale = (
            current is None
            or generation != self.fault_diagnosis_generation
            or receipt_sha != current.get("receipt_sha256")
            or progress_sha != current.get("finance_progress_sha256")
            or report.get("receipt_sha256", receipt_sha) != receipt_sha
            or report.get("finance_progress_sha256", progress_sha) != progress_sha
        )
        if stale:
            self.historical_inventory_result = None
            self.historical_inventory_summary.set(
                "本轮回执或游标已变化，历史版本清单失效，请重新核对。")
        elif report.get("status") == "V2D2C_HISTORICAL_FINANCE_METADATA_NOT_RESTORABLE":
            self.historical_inventory_result = report
            self.historical_inventory_summary.set(
                "历史盘点：" + str(report.get("historical_snapshot_count", 0)) +
                " 个快照、" +
                str(report.get("historical_active_pin_count", 0)) +
                " 个活动指针；只统计元数据，未备份、未验证回滚。")
            self._set_fault_detail(json.dumps(
                report, ensure_ascii=False, indent=2))
        else:
            self.historical_inventory_result = None
            self.historical_inventory_summary.set(
                "历史只读盘点未通过：" + str(report.get("detail", "未知原因")))
        self.status_line.set(
            "历史财务版本仅盘点元数据；无论结果如何，一键恢复均未开放")

    def refresh_fault_diagnosis(self):
        self.historical_inventory_result = None
        self.historical_inventory_summary.set("回执刷新后需重新盘点历史财务版本范围")
        self.selected_fault_code.set(
            "在左侧选择错误，可查看完整错误代码。")
        super().refresh_fault_diagnosis()
        # A neutral rail by default; red only for an evidenced execution
        # error, amber for warnings, blue for progress notices. A missing
        # receipt must never be painted as a certified green success.
        cases = (self.fault_diagnosis or {}).get("cases", [])
        severity = {item.get("severity") for item in cases
                    if isinstance(item, dict)}
        if "ERROR" in severity:
            rail_color = V2F["danger"]
        elif "WARN" in severity:
            rail_color = V2F["warning"]
        elif "INFO" in severity:
            rail_color = V2F["accent"]
        else:
            rail_color = V2F["border"]
        if hasattr(self, "home_alert_rail"):
            self.home_alert_rail.configure(bg=rail_color)
        if hasattr(self, "fault_page_headline_view"):
            self.fault_page_headline_view.configure(
                style=self.fault_title_view.cget("style"))

    def build_logs(self):
        top = ttk.Frame(self.logs)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="按当前回执查看的日志尾段 · 只读",
                  style="V2E.Heading.TLabel").pack(side="left")
        ttk.Button(top, text="刷新日志", command=self.refresh_logs).pack(
            side="right")
        filter_row = ttk.Frame(self.logs)
        filter_row.pack(fill="x", pady=(0, 9))
        ttk.Label(filter_row, text="页内查找").pack(side="left")
        self.log_query = tk.StringVar()
        ttk.Entry(filter_row, textvariable=self.log_query,
                  width=35).pack(side="left", padx=8)
        ttk.Button(filter_row, text="高亮匹配",
                   command=self._highlight_log).pack(side="left")
        ttk.Button(filter_row, text="显示本轮财务日志",
                   command=self.show_finance_log).pack(side="left", padx=8)
        holder = ttk.Frame(self.logs)
        holder.pack(fill="both", expand=True)
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            holder, font=("Consolas", 10), wrap="none", borderwidth=0,
            padx=12, pady=11, background=COLORS["log_bg"],
            foreground=COLORS["log_fg"], selectbackground=COLORS["blue"],
            insertbackground=COLORS["log_fg"], state="disabled",
        )
        vs = ttk.Scrollbar(holder, orient="vertical", command=self.log_text.yview)
        hs = ttk.Scrollbar(holder, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        self.log_text.tag_configure("match", background="#E6B75C",
                                    foreground="#142235")
        bottom = ttk.Frame(self.logs)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Label(bottom, text="只加载末尾有限字节；原始长日志不会全文写到界面内。",
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(bottom, text="打开本地日志文件夹",
                   command=self.open_log_folder).pack(side="right")

    def _highlight_log(self):
        query = self.log_query.get().strip()
        self.log_text.tag_remove("match", "1.0", "end")
        if not query:
            return
        cursor = "1.0"
        for _ in range(250):
            at = self.log_text.search(query, cursor, "end", nocase=True)
            if not at:
                break
            end = self.log_text.index(at + "+" + str(len(query)) + "c")
            self.log_text.tag_add("match", at, end)
            cursor = end
        self.log_text.see("1.0")

    def build_data_management(self):
        content = self._scroll_content(self.data_page)
        overview = self._section(content, "八周期概览 · 需要逐周期物理核验")
        ttk.Label(overview,
                  text="以下周期卡仅说明计划覆盖范围，不等于数据库真实完整率或缺口数量。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 9))
        grid = ttk.Frame(overview)
        grid.pack(fill="x")
        for col in range(4):
            grid.columnconfigure(col, weight=1)
        self.period_vars = {}
        for i, (period, name) in enumerate(PERIOD_LABELS):
            cell = ttk.LabelFrame(grid, text=name, padding=10)
            cell.grid(row=i // 4, column=i % 4, padx=5, pady=5, sticky="ew")
            var = tk.StringVar(value="未逐周期核验")
            ttk.Label(cell, textvariable=var,
                      style="Muted.TLabel").pack(anchor="w")
            self.period_vars[period] = var
        source_box = self._section(content, "本机数据目录与来源证据")
        self.management_summary = tk.StringVar(value="尚未读取可信回执")
        ttk.Label(source_box, textvariable=self.management_summary,
                  style="Section.TLabel", wraplength=940).pack(anchor="w")
        ttk.Label(source_box,
                  text="跨源抽样配置 ≠ 本次比对成功；未查询历史分区，不展示虚构覆盖率。",
                  style="Muted.TLabel").pack(anchor="w", pady=(7, 0))
        data_actions = ttk.Frame(content)
        data_actions.pack(fill="x")
        ttk.Button(data_actions, text="重新读取状态摘要",
                   command=self.refresh_overview).pack(side="left")
        ttk.Button(data_actions, text="前往范围核验",
                   command=lambda: self.go_action("数据核验")).pack(
                       side="left", padx=9)
        ttk.Button(data_actions, text="查看最近核验结果",
                   command=lambda: self.navigate(PAGE_MAP["核验结果"])).pack(
                       side="left", padx=9)

    def build_settings(self):
        content = self._scroll_content(self.settings_page)
        schedule = self._section(content, "现有自动任务 · 仅展示设计约束")
        for label in (
            "调度：唯一 Windows 20:05 自动更新；本界面不安装、不编辑、不触发计划任务。",
            "并发：正式 runner 使用具名 mutex 和任务单实例策略；此 UI 不推测当前是否占用。",
            "历史重下与修复：仍需独立来源版本、隔离比对、备份和人工批准。",
        ):
            ttk.Label(schedule, text="• " + label, style="Section.TLabel",
                      wraplength=970).pack(anchor="w", pady=5)
        source = self._section(content, "数据来源与只读运行目录")
        self.settings_source = tk.StringVar(value="等待读取来源配置")
        ttk.Label(source, textvariable=self.settings_source,
                  style="Section.TLabel", wraplength=970,
                  justify="left").pack(anchor="w")
        ttk.Label(source, text="当前 GUI 不允许手动切换主行情源；真实来源以运行回执为准。",
                  style="Muted.TLabel").pack(anchor="w", pady=8)
        safe = self._section(content, "功能权限 · 当前全为保守模式")
        self.feature_flags = (
            ("自动更新执行", False, "未接入受控写入执行器"),
            ("历史缺口自动修复", False, "需要交易日历、独立来源及差异审批"),
            ("财务断线一键续跑", False, "QMT检查不能代替正式写锁、版本批准和备份"),
            ("有限历史行情只读核验", self.market_root is not None,
             "仅在显式 --market-root 与范围限制下可用"),
            ("QMT即时连接检查", True, "用户点击后仅观察 get_client，不下载"),
            ("财务版本及备份范围盘点", self.market_root is not None,
             "只读文件清单，未验证快照内容与回滚能力"),
        )
        for name, ready, note in self.feature_flags:
            row = ttk.Frame(safe)
            row.pack(fill="x", pady=7)
            ttk.Label(row, text=name, width=25,
                      style="Section.TLabel").pack(side="left")
            ttk.Label(row, text=("有条件开放" if ready else "未开放"),
                      style=("Warning.Section.TLabel" if ready
                             else "Muted.TLabel")).pack(side="left", padx=5)
            ttk.Label(row, text=note,
                      style="Muted.TLabel").pack(side="left", padx=10)
        ttk.Button(content, text="重新读取只读来源信息",
                   command=self.refresh_overview).pack(anchor="w", pady=7)

    def _refresh_auxiliary(self, current: dict, config: dict):
        states = separated_run_evidence(current)
        for key, name in (
            ("execution", "execution"), ("data", "data"), ("cross", "cross"),
        ):
            status = states[name]
            self.validation_vars[key].set(status)
            shade = ("Success" if status in ("PASS", "SUCCESS") else
                     "Failure" if status in ("FAIL", "FAILED") else
                     "Warning" if status == "PARTIAL" else "Neutral")
            self.validation_value_widgets[key].configure(
                style=shade + ".CardValue.TLabel")
        accepted = current.get("last_accepted_trading_day", "未证明")
        detail = current.get("stage_records", {}).get("EIGHT_PERIODS", {})
        phase = format_evidence_state(detail.get("data_validation"))
        summary = ("最新已提交交易日：" + str(accepted) +
                   "  |  八周期本轮核验：" + phase +
                   "  |  逐周期历史覆盖：尚无独立扫描证据。")
        self.management_summary.set(summary)
        for row in view_coverage_rows(current):
            self.period_vars[row["period"]].set(row["coverage"])
        crosses = "、".join(config.get("minute_crosschecks_configured", []))
        self.settings_source.set(
            "配置来源：" + str(config.get("config_file", "未记录")) +
            "\n分钟主源：" + str(config.get("market_minute_update", "未核验")) +
            "\n日线主源：" + str(config.get("market_day_update", "未核验")) +
            "\n抽样参照（仅已配置）：" + (crosses or "未配置") +
            "\n状态目录（只读）：" + str(self.state_module))

    def refresh_overview(self):
        # V2D1 owns bounded reads, diagnoses and log refresh.
        super().refresh_overview()
        try:
            snapshot = latest_status(self.state_module)
            self._sync_committed_readonly_ceiling(snapshot)
            recommendation = recommended_task(snapshot)
            self.recommended_task_id = recommendation["task_id"]
            for task_id, button in self.task_buttons.items():
                button.configure(
                    style=("Primary.TButton"
                           if task_id == self.recommended_task_id
                           else "TButton"))
            self.workflow_hint.set(
                "建议下一步：" + recommendation["reason"])
            self._refresh_auxiliary(
                snapshot, source_info(self.state_module),
            )
        except (InvalidPlan, OSError, ValueError) as exc:
            self._sync_committed_readonly_ceiling({})
            self.recommended_task_id = "audit"
            self.workflow_hint.set(
                "建议下一步：状态证据不足，可先检查数据或查看本轮日志。")
            self.management_summary.set("状态读取不足：" + str(exc)[:120])
            self.settings_source.set("来源配置不可用；未进行额外读写")

    def _sync_committed_readonly_ceiling(self, status):
        """Only a local committed-day candidate can extend the old frozen day.

        This candidate limits reading, not historical coverage certification.
        The existing market mutex, date range and rowgroup guard are unchanged.
        """
        self.audit_accepted_asof = None
        value = status.get("last_accepted_trading_day") if isinstance(status, dict) else None
        try:
            ceiling = read_only_ceiling(value if isinstance(value, str) else None)
            if ceiling > FROZEN_ASOF:
                self.audit_accepted_asof = value
        except AuditBlocked:
            ceiling = FROZEN_ASOF
        self.audit_ceiling_note.set(
            "最多20股、31日；当前可核验截止：" + ceiling.isoformat() +
            "（仅限本地已提交且早于北京时间今天的历史日；不证明行情完整）。")
        return ceiling

    def run_readonly_audit(self):
        """Refresh the committed-day bound for each user-initiated audit."""
        try:
            snapshot = latest_status(self.state_module)
        except (OSError, ValueError, InvalidPlan):
            snapshot = {}
        self._sync_committed_readonly_ceiling(snapshot)
        return super().run_readonly_audit()

    def go_action(self, mode):
        super().go_action(mode)
        self.action_steps.select(0)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Market Center V2E seven-page visual review (no writes)"
    )
    parser.add_argument("--state-module", type=Path, default=HERE)
    parser.add_argument("--market-root", type=Path)
    parser.add_argument("--evidence-file", type=Path)
    parser.add_argument("--evidence-sha256")
    args = parser.parse_args(argv)
    path = args.state_module
    if (not path.is_absolute() or path.name.lower() != "parquetlivesync"
            or not path.is_dir()
            or any(p.is_symlink() for p in (path, *path.parents))):
        parser.error("state-module 必须是无符号链接的现有绝对 ParquetLiveSync 目录")
    if (args.evidence_file is None) != (args.evidence_sha256 is None):
        parser.error("evidence-file 和 evidence-sha256 必须同时提供")
    if args.evidence_file is not None and args.market_root is None:
        parser.error("证据快照只能与显式 market-root 一同提供")
    opts = {"state_module": path}
    if args.market_root is not None:
        root = args.market_root
        if (not root.is_absolute()
                or root.name.lower() != "allcycleastockdata"
                or not root.is_dir()
                or any(p.is_symlink() for p in (root, *root.parents))):
            parser.error("market-root 必须是现有绝对 AllCycleAStockData 目录且非符号链接")
        opts["market_root"] = root
    if args.evidence_file is not None:
        opts["evidence_file"] = args.evidence_file
        opts["evidence_sha256"] = args.evidence_sha256
    MarketCenterV2SelectedUI(**opts).mainloop()


if __name__ == "__main__":
    main()
