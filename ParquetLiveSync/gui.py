#!/usr/bin/env python3
"""Standard-library Windows GUI for licensed, conservative DAY-only updates."""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox,ttk
from live_sync import WORK,BASE_DAY,latest_yesterday,safe_window,sync,summarize,exclusive_writer,CN
from local_layout import inventory,storage_root,rollover_all_periods,PERIODS
from rollup_week_month import run as verify_and_derive_week_month
from update_pipeline import run as run_complete_parquet_pipeline
from datetime import datetime

class LiveParquetGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AStockDataTools | Parquet 增量更新")
        self.geometry("970x785")
        self.minsize(840,690)
        self.messages=queue.Queue()
        self.stop_event=threading.Event()
        self.running=False
        self.root_value=tk.StringVar(value="D:\\stock" if os.name=="nt" else "D:/stock")
        self.start_day=tk.StringVar(value="2026-10-14")
        self.end_day=tk.StringVar(value=latest_yesterday().isoformat())
        self.headline=tk.StringVar(value="加载本地数据库状态…")
        self.current=tk.StringVar(value="待命")
        self.pct=tk.IntVar(value=0)
        self.direct_local=tk.BooleanVar(value=True)
        self.localpath=tk.StringVar(value=r"D:\stock\AllCycleAStockData")
        self.close_requested=False
        self.derivation_preview_root=None
        self._layout()
        self.after(120,self._poll)
        self._refresh()
        self.protocol("WM_DELETE_WINDOW",self._close)

    def _layout(self):
        frame=ttk.Frame(self,padding=20)
        frame.pack(fill="both",expand=True)
        ttk.Label(frame,text="A股 Parquet 增量更新",
                  font=("Microsoft YaHei UI",19,"bold")).pack(anchor="w")
        ttk.Label(frame,text="a-stock-data v3.10.4 · 通达信官网全市场盘后日线 · 原始购买 Parquet/H5 不会被覆盖",
                  foreground="#586575").pack(anchor="w",pady=(5,16))
        top=ttk.LabelFrame(frame,text="数据库状态",padding=12)
        top.pack(fill="x")
        ttk.Label(top,textvariable=self.headline,
                  font=("Microsoft YaHei UI",11)).pack(anchor="w")
        ttk.Label(top,text="存储位置自动识别：",foreground="#666666").pack(anchor="w",pady=(7,0))
        ttk.Label(top,textvariable=self.localpath).pack(anchor="w")
        ttk.Label(top,text="目录规则：往年 YYYY.parquet / 当年 YYYY-MM.parquet；日线优先更新，其余周期保留。",
                  foreground="#666666").pack(anchor="w",pady=(7,0))
        ctrl=ttk.LabelFrame(frame,text="更新参数",padding=12)
        ctrl.pack(fill="x",pady=(12,0))
        ttk.Label(ctrl,text="市场数据根目录").grid(row=0,column=0,sticky="w",pady=6)
        ttk.Entry(ctrl,textvariable=self.root_value,width=69).grid(
            row=0,column=1,columnspan=3,sticky="ew",padx=(12,0))
        ttk.Label(ctrl,text="开始日期").grid(row=1,column=0,sticky="w",pady=6)
        ttk.Entry(ctrl,textvariable=self.start_day,width=16).grid(
            row=1,column=1,sticky="w",padx=(12,4))
        ttk.Label(ctrl,text="结束日期").grid(row=1,column=2,sticky="e",padx=(12,4))
        ttk.Entry(ctrl,textvariable=self.end_day,width=16).grid(
            row=1,column=3,sticky="w")
        ctrl.columnconfigure(1,weight=1)
        ttk.Checkbutton(
            frame,text=("把已校验的新日线合并进 AllCycleAStockData/day/"+
                  str(datetime.now(CN).year)+"-MM.parquet（备份、校验与原子替换）"),
            variable=self.direct_local).pack(anchor="w",pady=(9,0))
        btn=ttk.Frame(frame)
        btn.pack(fill="x",pady=14)
        self.preview=ttk.Button(btn,text="预览更新范围",command=self._preview)
        self.preview.pack(side="left")
        self.start=ttk.Button(btn,text="开始下载并补齐日线",command=self._begin)
        self.start.pack(side="left",padx=9)
        self.cancel=ttk.Button(btn,text="安全停止",command=self._stop,state="disabled")
        self.cancel.pack(side="left")
        self.autopilot=ttk.Button(
            btn,text="一键更新日/周/月",command=self._run_autopilot)
        self.autopilot.pack(side="left",padx=(9,0))
        ttk.Button(btn,text="刷新状态",command=self._refresh).pack(side="right")
        ttk.Button(btn,text="跨年归档检查",command=self._rollover).pack(side="right",padx=7)
        derived=ttk.Frame(frame)
        derived.pack(fill="x",pady=(0,5))
        ttk.Label(derived,text="周线/月线：仅由完整日线推导；必须先对照旧购买数据校准时间戳",
                  foreground="#667085").pack(side="left",padx=(0,12))
        self.preview_derived=ttk.Button(
            derived,text="核验周线/月线",command=lambda:self._run_derived(False))
        self.preview_derived.pack(side="left")
        self.apply_derived=ttk.Button(
            derived,text="写入已完成周/月",command=lambda:self._run_derived(True),
            state="disabled")
        self.apply_derived.pack(side="left",padx=7)
        state=ttk.Frame(frame)
        state.pack(fill="x")
        ttk.Label(state,textvariable=self.current).pack(anchor="w")
        self.progress=ttk.Progressbar(state,mode="indeterminate",maximum=100)
        self.progress.pack(fill="x",pady=(7,0))
        status=ttk.LabelFrame(frame,text="各周期接入状态",padding=10)
        status.pack(fill="x",pady=(13,0))
        self.table=ttk.Treeview(status,columns=("status","source"),
                                show="headings",height=8)
        self.table.heading("status",text="周期 / 更新时间")
        self.table.heading("source",text="当前来源")
        self.table.column("status",width=360)
        self.table.column("source",width=440)
        self.table.pack(fill="x")
        log_frame=ttk.LabelFrame(frame,text="下载与 Parquet 验证日志",padding=10)
        log_frame.pack(fill="both",expand=True,pady=(12,0))
        self.log=tk.Text(log_frame,height=10,wrap="word",
                         bg="#111827",fg="#e2e8f0",
                         insertbackground="white",font=("Consolas",10))
        self.log.pack(fill="both",expand=True)
        ttk.Label(frame,text="日线新数据同时留私有SHA增量副本；本地标准月文件变更前自动备份。跨年归档需12个月完整且明确确认。",
                  foreground="#667085").pack(anchor="w",pady=(7,0))

    def _write(self,message):
        self.log.insert("end",str(message)+"\n")
        self.log.see("end")

    def _window(self):
        left=date.fromisoformat(self.start_day.get().strip())
        right=date.fromisoformat(self.end_day.get().strip())
        safe_window(left,right,max_days=180)
        return left,right

    def _preview(self):
        try:
            start,end=self._window()
            identified=storage_root(self.root_value.get().strip())
            self._write("自动发现八周期目录："+str(identified))
            self._write("本地日线合并："+("开启" if self.direct_local.get() else "仅私有SHA增量"))
            self._write("预览：" + str(start)+" → "+str(end)+
                        "，最多 "+str((end-start).days+1)+" 个日历日")
            self._write("只对2026-10-13之后下载通达信官方完整盘后包；404将留待下次重试。")
            self._write("第一次会先从原购买Parquet历史日线和通达信同日数据自动验证量价额量纲；不通过会拒绝落库。")
        except Exception as exc:
            messagebox.showerror("日期范围无效",str(exc))

    def _begin(self):
        if self.running:
            return
        try:
            left,right=self._window()
            root=Path(self.root_value.get().strip())
            resolved=storage_root(root)
            self.localpath.set(str(resolved))
        except Exception as exc:
            messagebox.showerror("无法启动",str(exc))
            return
        if not messagebox.askyesno(
                "确认增量更新",
                "将访问通达信官网并保存可核验的日线 Parquet 增量。\n"
                + ("同时备份并合并到实际 AllCycleAStockData/day/YYYY-MM.parquet。\n" if self.direct_local.get()
                   else "仅私有增量目录，不改动原月文件。\n")
                + "不会修改任何 H5 或其余七周期的原数据。\n\n"
                f"范围：{left} 至 {right}\n继续吗？"):
            return
        use_local_months=bool(self.direct_local.get())
        self.running=True
        self.stop_event.clear()
        self.progress.start(12)
        self.start.configure(state="disabled")
        self.cancel.configure(state="normal")
        self.current.set("正在运行；进度会逐日显示")
        def job():
            try:
                result=sync(root,left,right,max_days=180,
                            logger=lambda msg:self.messages.put(("log",msg)),
                            stop=self.stop_event.is_set,
                            materialize_local=use_local_months)
                self.messages.put(("ok",result))
            except Exception as exc:
                self.messages.put(("error",str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def _run_autopilot(self):
        if self.running:
            messagebox.showinfo("当前已有更新任务","请先完成现有写入任务。")
            return
        try:
            left,right=self._window()
            root=Path(self.root_value.get().strip())
            self.localpath.set(str(storage_root(root)))
            if not self.direct_local.get():
                raise ValueError("一键更新需要勾选把新日线合并进本地标准月文件")
        except Exception as exc:
            messagebox.showerror("一键更新前检查未通过",str(exc))
            return
        if not messagebox.askyesno(
            "确认一次性更新三个周期",
            "会依次执行：\n"
            "1. 官方TDX日线下载、校准、SHA核验、写入day当年月文件；\n"
            "2. 重新核验2026年5—9月购买周/月线历史口径；\n"
            "3. 仅合并已结束且日期完整的week/month，当年月份文件。\n\n"
            "已存在同一证券/时间戳的周/月K线会逐字段核对，不会静默覆盖。"
            "任一步失败都会停止后续操作，已验收的前一步文件保留。"
            "\n不会修改任何H5或分钟线。\n\n"
            f"日线下载日期：{left} 至 {right}\n确定开始吗？"):
            return
        self.derivation_preview_root=None
        self.apply_derived.configure(state="disabled")
        self.running=True
        self.stop_event.clear()
        self.progress.start(12)
        self.start.configure(state="disabled")
        self.autopilot.configure(state="disabled")
        self.cancel.configure(state="normal")
        self.preview_derived.configure(state="disabled")
        self.current.set("一键更新中：先处理日线，再校验并补齐已结束的周/月线")
        def job():
            try:
                result=run_complete_parquet_pipeline(
                    root,start=left,end=right,apply=True,retry_days=90,
                    logger=lambda msg:self.messages.put(("log",msg)),
                    stop=self.stop_event.is_set)
                self.messages.put(("auto_ok",result))
            except Exception as exc:
                self.messages.put(("error","一键日/周/月增量未全部通过："+str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def _stop(self):
        self.stop_event.set()
        self.current.set("已请求安全停止，当前单日写入结束后退出")
        self._write("STOP_REQUESTED：保留已经提交的日期，下次运行自动跳过。")

    def _refresh(self):
        self.table.delete(*self.table.get_children())
        try:
            root=storage_root(self.root_value.get().strip())
            self.localpath.set(str(root))
            report=summarize()
            layout=inventory(root)
            last=report["latest_overlaid_day"] or "尚无新增日线"
            self.headline.set(
                f"历史日线截止 {BASE_DAY} | 最新增量 {last} | "
                f"已获取 {report['new_day_dates']} 日、{report['new_day_rows']:,} 行")
            for period in PERIODS:
                folder=layout["periods"][period]
                current=len(folder["current_year_monthly_files"])
                old=folder["annual_files"]
                anomalies=len(folder["prior_year_monthly_files"])
                note=(f"{old}个年度文件 / 本年{current}个月文件"
                      + (f" / {anomalies}个往年月文件待归档" if anomalies else ""))
                if period=="day":
                    note+=" / 已接入官方TDX真实日线增量"
                elif period in ("week","month"):
                    recent=any(name.startswith(str(datetime.now(CN).year)+"-10")
                               or name.startswith(str(datetime.now(CN).year)+"-11")
                               for name in folder["current_year_monthly_files"])
                    note+=(" / 存在新周期月文件（按核验收据判断完整性）" if recent
                           else " / 可由已验日线推导；需先核验旧购买周期")
                else:
                    note+=" / 尚无可靠完整分钟OHLCVA增量源"
                self.table.insert("","end",
                                  values=(period+"： "+note,str(root/period)))
        except Exception as exc:
            self.headline.set("未能验证本地八周期 Parquet 文件布局")
            self._write("路径/布局校验失败："+str(exc))
            for period in PERIODS:
                self.table.insert("","end",values=(period,"等待D:\\stock目录验证"))

    def _rollover(self):
        if self.running:
            messagebox.showinfo("任务仍在运行","请先完成或安全停止当前下载。")
            return
        try:
            root=storage_root(self.root_value.get().strip())
            year=datetime.now(CN).year-1
            preview=rollover_all_periods(
                root,year,WORK,current_year=year+1,apply=False)
            self._write("跨年预检："+str(year)+"，八个周期已存在完整年度文件或12个月文件。")
            for period,info in preview["periods"].items():
                self._write(period+": "+info["action"])
        except Exception as exc:
            self._write("跨年尚不能归档："+str(exc))
            messagebox.showinfo(
                "未满足年度归档条件",
                "八个周期必须全部具有完整的上一年度数据。当前只读预检结果：\n"+
                str(exc))
            return
        if not messagebox.askyesno(
            "年度归档确认",
            f"将 {year} 年八周期的每月文件合并为每周期一个 {year}.parquet，"+
            "先做SHA私有备份与整数字段/唯一键校验，归档后移除原位置月文件。\n"+
            "旧的固定物理快照若硬编码了这些月文件路径，将需要重新生成索引版本。\n"+
            "确定要进行跨年归档吗？"):
            return
        self.running=True
        self.stop_event.clear()
        self.progress.start(12)
        self.start.configure(state="disabled")
        self.cancel.configure(state="disabled")
        self.current.set("正在核对并归档八周期上一年度Parquet；不得强制关窗")
        def job():
            try:
                with exclusive_writer():
                    result=rollover_all_periods(
                        root,year,WORK,current_year=year+1,apply=True)
                self.messages.put(("archive_ok",result))
            except Exception as exc:
                self.messages.put(("error",str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def _run_derived(self,apply):
        if self.running:
            messagebox.showinfo("当前有任务","先结束当前同步或归档，再执行周/月核验。")
            return
        try:
            root=storage_root(self.root_value.get().strip())
        except Exception as exc:
            messagebox.showerror("本地Parquet路径不合法",str(exc))
            return
        if apply and (self.derivation_preview_root is None or
                      self.derivation_preview_root!=str(root)):
            messagebox.showerror("必须先核验",
                                 "路径或历史核验状态发生变化，请先重新执行周/月只读核验。")
            return
        if apply and not messagebox.askyesno(
            "仅写入已完整结束的周线/月线",
            "将从已SHA验证的真实日线生成完成周期，并先校验现有2026年5—9月购买"+
            "周/月线时标、开高低收、成交量、成交额。只有全部通过才会写入"+
            "AllCycleAStockData/week与month的当前年月文件，旧文件先备份。\n"+
            "本周/本月未结束的周期不会写；原日线、分钟线、H5不修改。\n继续吗？"):
            return
        if not apply:
            self.derivation_preview_root=None
            self.apply_derived.configure(state="disabled")
        self.running=True
        self.progress.start(12)
        self.start.configure(state="disabled")
        self.preview_derived.configure(state="disabled")
        self.apply_derived.configure(state="disabled")
        self.cancel.configure(state="disabled")
        self.current.set("正在核验购买源周/月口径..." if not apply
                         else "已授权：仅合并通过核验的已结束周/月K线")
        def job():
            try:
                result=verify_and_derive_week_month(
                    root,apply=apply,
                    log=lambda msg:self.messages.put(("log",msg)))
                self.messages.put(("derived_applied" if apply else "derived_preview",result))
            except Exception as exc:
                self.messages.put(("error","周/月派生已拒绝："+str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def _close(self):
        if not self.running:
            self.destroy()
            return
        if messagebox.askyesno(
                "当前仍有写入任务",
                "任务运行中。现在请求安全停止并保持窗口，直至当前操作结束吗？"):
            self.stop_event.set()
            self.close_requested=True
            self.current.set("正在安全结束当前日期，窗口将随后自动关闭")

    def _poll(self):
        try:
            while True:
                kind,item=self.messages.get_nowait()
                if kind=="log":
                    self._write(item)
                else:
                    self.running=False
                    self.progress.stop()
                    self.start.configure(state="normal")
                    self.cancel.configure(state="disabled")
                    self.preview_derived.configure(state="normal")
                    self.autopilot.configure(state="normal")
                    if self.derivation_preview_root is not None:
                        self.apply_derived.configure(state="normal")
                    if kind=="auto_ok":
                        self.current.set("日线、完整周/月线联合增量已完成")
                        self._write("一键流水线验收："+json.dumps(item,ensure_ascii=False))
                        self._refresh()
                    elif kind=="derived_preview":
                        self.derivation_preview_root=str(
                            storage_root(self.root_value.get().strip()))
                        self.apply_derived.configure(state="normal")
                        self.current.set("购买源周/月口径预检通过，可显式提交完成的周期")
                        self._write("周/月只读核验通过："+json.dumps(item,ensure_ascii=False))
                    elif kind=="derived_applied":
                        self.current.set("周线/月线已验收且已完成的周期写入月文件")
                        self._write("周/月物理月文件回写："+json.dumps(item,ensure_ascii=False))
                        self._refresh()
                    elif kind=="archive_ok":
                        self.current.set("年度归档完成")
                        self._write("归档验收："+json.dumps(item,ensure_ascii=False))
                        self._refresh()
                    elif kind=="ok":
                        self.current.set("当前请求已完成，请看增量状态")
                        self._write("完成："+json.dumps(item,ensure_ascii=False))
                        self._refresh()
                    else:
                        self.current.set("运行中断：保留已验收的日线数据")
                        self._write("已停止/失败："+item)
                        messagebox.showerror("增量更新未全部成功",item)
                    if self.close_requested:
                        self.destroy()
                        return
        except queue.Empty:
            pass
        self.after(120,self._poll)

if __name__=="__main__":
    LiveParquetGui().mainloop()
