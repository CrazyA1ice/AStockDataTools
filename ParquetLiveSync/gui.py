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
from live_sync import WORK,BASE_DAY,latest_yesterday,safe_window,sync,summarize

class LiveParquetGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AStockDataTools | Parquet 增量更新")
        self.geometry("940x690")
        self.minsize(800,590)
        self.messages=queue.Queue()
        self.stop_event=threading.Event()
        self.running=False
        self.root_value=tk.StringVar(value="D:\\stock" if os.name=="nt" else "D:/stock")
        self.start_day=tk.StringVar(value="2026-10-14")
        self.end_day=tk.StringVar(value=latest_yesterday().isoformat())
        self.headline=tk.StringVar(value="加载本地数据库状态…")
        self.current=tk.StringVar(value="待命")
        self.pct=tk.IntVar(value=0)
        self._layout()
        self.after(120,self._poll)
        self._refresh()

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
        ttk.Label(top,text="原八周期快照：截至 2026-10-13。仅日线可用通达信官方包完整补齐；其他七周期仍为原快照。",
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
        btn=ttk.Frame(frame)
        btn.pack(fill="x",pady=14)
        self.preview=ttk.Button(btn,text="预览更新范围",command=self._preview)
        self.preview.pack(side="left")
        self.start=ttk.Button(btn,text="开始下载并补齐日线",command=self._begin)
        self.start.pack(side="left",padx=9)
        self.cancel=ttk.Button(btn,text="安全停止",command=self._stop,state="disabled")
        self.cancel.pack(side="left")
        ttk.Button(btn,text="刷新状态",command=self._refresh).pack(side="right")
        state=ttk.Frame(frame)
        state.pack(fill="x")
        ttk.Label(state,textvariable=self.current).pack(anchor="w")
        ttk.Progressbar(state,mode="indeterminate",maximum=100,
                        variable=self.pct).pack(fill="x",pady=(7,0))
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
        ttk.Label(frame,text="原始 ZIP、增量 Parquet、SHA 收据及日志均存于 ParquetLiveSync/work（Git 忽略）；404 不等于休市。",
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
            if not root.is_dir():
                raise ValueError("找不到 D:\\stock 市场数据库目录")
        except Exception as exc:
            messagebox.showerror("无法启动",str(exc))
            return
        if not messagebox.askyesno(
                "确认增量更新",
                "将访问通达信官网并在私有 work 目录保存新的日线 Parquet。\n"
                "不会覆盖历史八周期 Parquet 或 H5。\n\n"
                f"范围：{left} 至 {right}\n继续吗？"):
            return
        self.running=True
        self.stop_event.clear()
        self.start.configure(state="disabled")
        self.cancel.configure(state="normal")
        self.current.set("正在运行；进度会逐日显示")
        def job():
            try:
                result=sync(root,left,right,max_days=180,
                            logger=lambda msg:self.messages.put(("log",msg)),
                            stop=self.stop_event.is_set)
                self.messages.put(("ok",result))
            except Exception as exc:
                self.messages.put(("error",str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def _stop(self):
        self.stop_event.set()
        self.current.set("已请求安全停止，当前单日写入结束后退出")
        self._write("STOP_REQUESTED：保留已经提交的日期，下次运行自动跳过。")

    def _refresh(self):
        self.table.delete(*self.table.get_children())
        try:
            report=summarize()
            last=report["latest_overlaid_day"] or "尚无新增日线"
            self.headline.set(
                f"原版日线截至 {BASE_DAY}  |  新增日线最新 {last}  |  "
                f"新增 {report['new_day_dates']} 日 / {report['new_day_rows']:,} 行")
            for period in ("day","1min","5min","15min",
                           "30min","60min","week","month"):
                if period=="day":
                    detail=f"原始完整日线 + {report['new_day_dates']} 日新Parquet（SHA 验证）"
                else:
                    detail="原始物理来源截至 2026-10-13；尚未增量"
                self.table.insert("","end",values=(period+"： "+detail,
                                                    report["periods"][period]))
        except Exception as exc:
            self.headline.set("尚未找到可用的本地原八周期 Parquet 快照")
            self._write("状态读取失败："+str(exc))
            for period in ("day","1min","5min","15min",
                           "30min","60min","week","month"):
                self.table.insert("","end",values=(period,"等待本地 Parquet 源验证"))

    def _poll(self):
        try:
            while True:
                kind,item=self.messages.get_nowait()
                if kind=="log":
                    self._write(item)
                else:
                    self.running=False
                    self.start.configure(state="normal")
                    self.cancel.configure(state="disabled")
                    if kind=="ok":
                        self.current.set("当前请求已完成，请看增量状态")
                        self._write("完成："+json.dumps(item,ensure_ascii=False))
                        self._refresh()
                    else:
                        self.current.set("运行中断：保留已验收的日线数据")
                        self._write("已停止/失败："+item)
                        messagebox.showerror("增量更新未全部成功",item)
        except queue.Empty:
            pass
        self.after(120,self._poll)

if __name__=="__main__":
    LiveParquetGui().mainloop()
