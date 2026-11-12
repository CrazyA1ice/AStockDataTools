#!/usr/bin/env python3
"""Compact native Windows A-share Parquet dashboard. Details are optional."""
from __future__ import annotations
from datetime import date,timedelta
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk,messagebox

from live_sync import WORK,BASE_DAY,latest_yesterday,summarize
from local_layout import PERIODS,inventory,storage_root
from update_pipeline import run as update_all
from minute_probe import PERIODS as MINUTES,run as trial_minutes
from minute_batch import run as collect_market_batch

class ParquetDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("A股行情 · Parquet 更新器")
        self.geometry("820x550")
        self.minsize(710,470)
        self.root_path=Path("D:/stock")
        self.events=queue.Queue()
        self.stop_event=threading.Event()
        self.running=False
        self.close_requested=False
        self.log_visible=False
        last=latest_yesterday()
        first=max(BASE_DAY+timedelta(days=1),last-timedelta(days=89))
        self.start_day=tk.StringVar(value=first.isoformat())
        self.end_day=tk.StringVar(value=last.isoformat())
        self.symbols=tk.StringVar(value="SH600000,SZ000001,BJ920021")
        self.minute_mode=tk.StringVar(value="三只样本")
        self.status=tk.StringVar(value="准备就绪")
        self.overview=tk.StringVar(value="检查本地数据库…")
        self.schedule=tk.StringVar(value="自动更新：读取状态…")
        self.minute=tk.StringVar(value="分钟线：尚未核验来源")
        self.summary=tk.StringVar(value="")
        self._build()
        self.after(100,self._poll)
        self.refresh()
        self.protocol("WM_DELETE_WINDOW",self._close)

    def _build(self):
        outer=ttk.Frame(self,padding=19)
        outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="A股 Parquet 更新",font=("Microsoft YaHei UI",20,"bold")).pack(anchor="w")
        ttk.Label(outer,text="存储目录：D:\\stock\\AllCycleAStockData",foreground="#5c6673").pack(
            anchor="w",pady=(1,11))
        status=ttk.LabelFrame(outer,text="数据库与任务状态",padding=(13,10))
        status.pack(fill="x")
        ttk.Label(status,textvariable=self.overview,
                  font=("Microsoft YaHei UI",11)).pack(anchor="w")
        ttk.Label(status,textvariable=self.minute).pack(anchor="w",pady=(5,0))
        ttk.Label(status,textvariable=self.schedule,
                  foreground="#445d73").pack(anchor="w",pady=(5,0))
        line=ttk.LabelFrame(outer,text="日线、周线、月线自动更新",padding=12)
        line.pack(fill="x",pady=(12,0))
        dates=ttk.Frame(line)
        dates.pack(fill="x")
        ttk.Label(dates,text="从").pack(side="left")
        ttk.Entry(dates,textvariable=self.start_day,width=14).pack(side="left",padx=(6,14))
        ttk.Label(dates,text="至").pack(side="left")
        ttk.Entry(dates,textvariable=self.end_day,width=14).pack(side="left",padx=(6,13))
        ttk.Label(dates,text="已更新日期会自动跳过",foreground="#667085").pack(side="left")
        actions=ttk.Frame(line)
        actions.pack(fill="x",pady=(11,0))
        self.update_button=ttk.Button(
            actions,text="更新日/周/月",command=self._start_update)
        self.update_button.pack(side="left")
        self.stop_button=ttk.Button(
            actions,text="停止",command=self._stop,state="disabled")
        self.stop_button.pack(side="left",padx=8)
        ttk.Button(actions,text="刷新状态",command=self.refresh).pack(side="right")
        minutes=ttk.LabelFrame(outer,text="分钟线：先验证数据源",padding=12)
        minutes.pack(fill="x",pady=(10,0))
        selection=ttk.Frame(minutes)
        selection.pack(fill="x")
        ttk.Label(selection,text="测试股票").pack(side="left")
        ttk.Entry(selection,textvariable=self.symbols,width=29).pack(
            side="left",fill="x",expand=True,padx=(8,5))
        ttk.Combobox(selection,textvariable=self.minute_mode,
                     values=("三只样本","全市场下一批10只"),
                     width=17,state="readonly").pack(side="left",padx=(0,8))
        self.probe_button=ttk.Button(
            selection,text="开始分钟下载",command=self._start_probe)
        self.probe_button.pack(side="left")
        ttk.Label(minutes,
                  text="1/5/15/30/60分钟 · 暂存独立样本，不会改写原始 Parquet 或 H5",
                  foreground="#667085").pack(anchor="w",pady=(7,0))
        current=ttk.Frame(outer)
        current.pack(fill="x",pady=(13,4))
        ttk.Label(current,textvariable=self.status).pack(side="left")
        ttk.Button(current,text="查看 / 隐藏日志",command=self._toggle_log).pack(side="right")
        self.progress=ttk.Progressbar(outer,mode="indeterminate")
        self.progress.pack(fill="x",pady=(4,7))
        self.details=ttk.Frame(outer)
        self.details.pack(fill="both",expand=True)
        self.results=ttk.Label(self.details,textvariable=self.summary,justify="left",
                               anchor="nw",foreground="#556575")
        self.results.pack(fill="x")
        self.log_frame=ttk.Frame(self.details)
        self.log=tk.Text(self.log_frame,wrap="word",font=("Consolas",9),
                         bg="#151c2b",fg="#d8e3ee",height=11,
                         insertbackground="white")
        self.log.pack(fill="both",expand=True)

    def _toggle_log(self):
        self.log_visible=not self.log_visible
        if self.log_visible:
            self.log_frame.pack(fill="both",expand=True,pady=(3,0))
            self.geometry("900x670")
        else:
            self.log_frame.pack_forget()
            self.geometry("820x550")

    def _write(self,message):
        self.log.insert("end",str(message)+"\n")
        self.log.see("end")

    def refresh(self):
        try:
            location=storage_root(self.root_path)
            report=inventory(location)
            source=summarize()
            latest=source["latest_overlaid_day"] or "待更新"
            self.overview.set("日线："+latest+"    周/月线：已接入按月更新")
            periods=report["periods"]
            fragments="  ".join(
                f"{period}：本年{len(periods[period]['current_year_monthly_files'])}个月"
                for period in PERIODS)
            self.summary.set(fragments)
        except Exception as exc:
            self.overview.set("数据库读取失败，请检查 D:\\stock")
            self.summary.set("诊断："+str(exc)[:200])
        proof=WORK/"last-scheduled-run.json"
        if proof.is_file():
            try:
                record=json.loads(proof.read_text(encoding="utf-8-sig"))
                result="成功" if record["status"]=="SUCCESS" else "失败"
                time=record.get("finished_time_local","未知")[:19].replace("T"," ")
                self.schedule.set(f"自动任务：上次{result} · {time}（本机时间；每天21:30计划）")
                if record["status"]!="SUCCESS":
                    self._write("最近自动任务失败："+record.get("message","未知原因"))
            except (ValueError,KeyError,UnicodeError):
                self.schedule.set("自动任务：上次结果文件无法解析；请查看详细日志")
        else:
            self.schedule.set("自动任务：尚无本工具记录的运行回执 · 计划时间21:30")
        report_root=WORK/"minute_source_trials"
        batch=report_root/"batch-progress.json"
        if batch.is_file():
            try:
                record=json.loads(batch.read_text(encoding="utf-8"))
                done=int(record.get("current_completed_stocks",
                         len(record.get("accepted_stock_symbols",[]))))
                all_stocks=int(record.get("symbols_in_universe",0))
                self.minute.set(
                    f"分钟线候选采集：{done}/{all_stocks} 只股票 · "
                    "1/5/15/30/60分钟（待量纲与完整性验收）")
                return
            except (ValueError,KeyError,UnicodeError):
                self.minute.set("分钟线候选索引需检查")
        trials=sorted(report_root.glob("*/latest-trial.json")) if report_root.is_dir() else []
        if trials:
            try:
                doc=json.loads(trials[-1].read_text(encoding="utf-8"))
                periods=doc.get("periods",{})
                checked=sum(x.get("status")=="CANDIDATE_ONLY_NOT_MERGED"
                            for payload in periods.values() for x in payload.values())
                self.minute.set(f"分钟试验：已取得 {checked} 组样本 · "
                                f"{len(doc.get('failed',[]))} 组失败 · 尚未并入")
            except (ValueError,UnicodeError):
                self.minute.set("分钟试验：历史回执需检查")
        else:
            self.minute.set("分钟试验：尚未下载 · 1/5/15/30/60分钟")

    def _begin(self,worker,task_label):
        self.running=True
        self.stop_event.clear()
        self.update_button.configure(state="disabled")
        self.probe_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.start(12)
        self.status.set(task_label)
        def job():
            try:
                result=worker()
                self.events.put(("done",result))
            except Exception as exc:
                self.events.put(("error",str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def _start_update(self):
        if self.running:
            return
        try:
            start=date.fromisoformat(self.start_day.get().strip())
            end=date.fromisoformat(self.end_day.get().strip())
            from live_sync import safe_window
            safe_window(start,end,max_days=180)
            storage_root(self.root_path)
        except Exception as exc:
            messagebox.showerror("日期或路径不正确",str(exc))
            return
        if not messagebox.askyesno("确认更新",
            f"更新 {start} 至 {end} 的日线，并补齐已结束的周线/月线？\n"
            "已保存的相同数据会校验并跳过；原分钟线和H5不变。"):
            return
        self._begin(
            lambda:update_all(
                self.root_path,start=start,end=end,retry_days=90,
                apply=True,logger=lambda line:self.events.put(("log",line)),
                stop=self.stop_event.is_set),
            "正在更新日线，之后核验周/月线…")

    def _start_probe(self):
        if self.running:
            return
        mode=self.minute_mode.get()
        from minute_probe import parse_symbols
        try:
            if mode=="三只样本":
                symbols=parse_symbols(self.symbols.get())
            else:
                storage_root(self.root_path)
        except ValueError as exc:
            messagebox.showerror("分钟线下载参数不正确",str(exc))
            return
        if mode=="三只样本":
            prompt=(f"下载 {len(symbols)} 只股票的1/5/15/30/60分钟候选源数据？"
                    "\n仅保存独立SHA原始样本，不修改正式数据库。")
            job=lambda:trial_minutes(
                symbols,logger=lambda line:self.events.put(("log",line)),
                stop=self.stop_event.is_set)
        else:
            prompt=("从已验收本地日线提取全市场股票，每次继续10只股票的"
                    "五个分钟周期候选下载，并保存断点。\n"
                    "源数据保留期有限；本功能暂不覆盖正式分钟Parquet或H5。")
            job=lambda:collect_market_batch(
                self.root_path,limit=10,
                logger=lambda line:self.events.put(("log",line)),
                stop=self.stop_event.is_set)
        if not messagebox.askyesno("分钟行情下载",prompt):
            return
        self._begin(job,"正在下载分钟行情候选；原数据库不改动…")

    def _stop(self):
        self.stop_event.set()
        self.status.set("已请求安全停止；当前处理结束后退出")

    def _poll(self):
        try:
            while True:
                kind,payload=self.events.get_nowait()
                if kind=="log":
                    self._write(payload)
                    continue
                self.running=False
                self.progress.stop()
                self.update_button.configure(state="normal")
                self.probe_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                if kind=="error":
                    self.status.set("本次未全部完成，已保存通过校验的历史数据")
                    self._write("失败："+payload)
                    messagebox.showerror("本次任务未全部完成",payload[:1000])
                else:
                    success=payload.get("status","")
                    if success=="DAY_WEEK_MONTH_COMPLETED_AND_SHA_BACKED":
                        self.status.set("日/周/月更新成功")
                    elif success.startswith("PROBE") or "CANDIDATE" in success:
                        self.status.set("分钟候选下载已完成；尚未写入正式分钟数据库")
                    else:
                        self.status.set("任务结束："+success)
                    self._write("结果："+json.dumps(payload,ensure_ascii=False)[:3000])
                    self.refresh()
                if self.close_requested:
                    self.destroy()
                    return
        except queue.Empty:
            pass
        self.after(150,self._poll)

    def _close(self):
        if not self.running:
            self.destroy()
        elif messagebox.askyesno("正在更新",
                  "需要安全停止当前任务并在完成后关闭吗？"):
            self.stop_event.set()
            self.close_requested=True
            self.status.set("正在安全停止…")

if __name__=="__main__":
    ParquetDashboard().mainloop()
