#!/usr/bin/env python3
"""Lightweight Windows GUI for REAL (not simulated) purchased-first minute
Parquet writing. Standard-library Tkinter only, worker continues after UI
closes, per-trading-day status is journaled under the project work directory.
"""
from __future__ import annotations
import json
import os
import re
import secrets
import subprocess
import sys
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog,messagebox,scrolledtext,ttk

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
JOBS=MODULE/"work"/"minute_gui"/"jobs"
WORKER=HERE/"minute-private-parquet-worker.py"
ID=re.compile(r"^[a-f0-9]{12}$")

def labels(status):
    return {
        "created":"尚未启动","running":"运行中 / 可能等待进程",
        "completed":"已完成","paused":"已暂停","failed":"失败，可恢复",
        "finished_verified":"新文件已验收","sha_reused_existing_verified_day":
            "已有数据 / SHA复用",
        "no_market_source_rows":"无行情源（非完成覆盖）",
        "interrupted_or_failed":"中断保留，待隔离重试",
    }.get(status,str(status))

def worker_launch_executable_and_flags(python_executable,is_windows):
    """Return a quiet background executable even if Python runs in a console.

    Prefer the venv's pythonw.exe on Windows, which is a GUI subsystem binary.
    A python.exe fallback uses CREATE_NO_WINDOW, not DETACHED_PROCESS (which
    can suppress the no-window flag). The worker still logs to a file.
    """
    if not is_windows:
        return str(python_executable),0
    candidate=Path(python_executable).with_name("pythonw.exe")
    executable=str(candidate) if candidate.is_file() else str(python_executable)
    flags=(getattr(subprocess,"CREATE_NO_WINDOW",0x08000000) |
           getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0x00000200))
    return executable,flags

def launch(jobid,*,resume=False,root=None,start=None,end=None):
    executable,flags=worker_launch_executable_and_flags(
        sys.executable,os.name=="nt")
    argv=[executable,str(WORKER),"--job-id",jobid,
          "--run-real-private-minute-parquet"]
    if resume:
        argv.append("--resume")
    else:
        argv+=["--root",str(root),"--start",start,"--end",end]
    JOBS.mkdir(parents=True,exist_ok=True)
    job=JOBS/jobid
    job.mkdir(parents=True,exist_ok=True)
    # Windows worker uses pythonw.exe (or CREATE_NO_WINDOW fallback);
    # do not spawn a blank Python command window. Parent GUI exit does
    # not terminate the separately launched worker process.
    env=os.environ.copy()
    env["PYTHONIOENCODING"]="utf-8"
    with (job/"worker-stdout.log").open("ab") as stdout:
        return subprocess.Popen(argv,cwd=MODULE,stdin=subprocess.DEVNULL,
             stdout=stdout,stderr=subprocess.STDOUT,close_fds=True,
             creationflags=flags,env=env)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AStockDataTools · 分钟数据真实转换")
        self.geometry("1020x710")
        self.minsize(820,550)
        self.jobid=None
        self.last_log=""
        self.root_value=tk.StringVar(value=r"D:\stock")
        self.start_value=tk.StringVar(value="2026-01-01")
        self.end_value=tk.StringVar(value="2026-10-13")
        self.id_value=tk.StringVar()
        self.status_value=tk.StringVar(value="就绪 · 仅写私有统一Parquet，原数据只读")
        self.count_value=tk.StringVar(value="0 / 0")
        self._build()
        self._recent_jobs()
        self.after(1100,self._refresh)

    def _build(self):
        f=ttk.Frame(self,padding=12)
        f.pack(fill="both",expand=True)
        ttk.Label(f,text="分钟数据转换控制台",font=("Microsoft YaHei UI",17,"bold")).pack(anchor="w")
        ttk.Label(f,text="真实流程：购买Parquet优先 → H5完整股票日补缺 → 私有1min/5min Parquet → SHA/全字段回读",
                  foreground="#41637e").pack(anchor="w",pady=(2,7))
        ttk.Label(f,text="旧版全年重写购买Parquet已停用；此界面仅供旧任务状态查看与日终暂停。",
                  foreground="#b42318").pack(anchor="w",pady=(0,12))
        group=ttk.LabelFrame(f,text="任务配置",padding=10)
        group.pack(fill="x")
        ttk.Label(group,text="原始数据根目录（只读）").grid(row=0,column=0,sticky="w")
        ttk.Entry(group,textvariable=self.root_value).grid(row=0,column=1,columnspan=3,sticky="ew",padx=8)
        ttk.Button(group,text="选择…",command=self._choose_root).grid(row=0,column=4,sticky="ew")
        ttk.Label(group,text="开始日期").grid(row=1,column=0,sticky="w",pady=(9,0))
        ttk.Entry(group,textvariable=self.start_value,width=15).grid(row=1,column=1,sticky="w",pady=(9,0),padx=8)
        ttk.Label(group,text="结束日期").grid(row=1,column=2,sticky="w",pady=(9,0))
        ttk.Entry(group,textvariable=self.end_value,width=15).grid(row=1,column=3,sticky="w",pady=(9,0),padx=8)
        ttk.Label(group,text="格式 YYYY-MM-DD，自动跳过已验收日期；周末不扫描。",foreground="#5f717d").grid(row=2,column=0,columnspan=5,sticky="w",pady=(9,0))
        group.columnconfigure(1,weight=1)
        group.columnconfigure(3,weight=1)
        actions=ttk.Frame(f)
        actions.pack(fill="x",pady=10)
        ttk.Button(actions,text="▶ 旧重写模式已停用",command=self._new_job,
                   state="disabled").pack(side="left",padx=(0,7))
        ttk.Button(actions,text="⏸ 当前日期结束后暂停",command=self._pause).pack(side="left",padx=(0,7))
        ttk.Button(actions,text="↻ 旧任务恢复已停用",command=self._resume,
                   state="disabled").pack(side="left",padx=(0,7))
        ttk.Button(actions,text="📁 打开任务目录",command=self._open_dir).pack(side="left")
        ttk.Label(actions,text="任务ID").pack(side="left",padx=(12,5))
        ttk.Entry(actions,textvariable=self.id_value,width=15).pack(side="left")
        row=ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row,textvariable=self.status_value,font=("Microsoft YaHei UI",10)).pack(side="left")
        ttk.Label(row,textvariable=self.count_value).pack(side="right")
        self.progress=ttk.Progressbar(f,mode="determinate")
        self.progress.pack(fill="x",pady=(5,11))
        dates=ttk.LabelFrame(f,text="每日写入进度（真实文件 / SHA）",padding=7)
        dates.pack(fill="both",expand=True)
        self.tree=ttk.Treeview(dates,columns=("day","state","one","five","source"),
                               show="headings",height=9)
        for key,title,width in (("day","交易日",110),("state","状态",210),
                                ("one","1分钟条数",125),("five","5分钟条数",125),
                                ("source","来源",145)):
            self.tree.heading(key,text=title)
            self.tree.column(key,width=width,anchor="center")
        bar=ttk.Scrollbar(dates,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left",fill="both",expand=True)
        bar.pack(side="right",fill="y")
        logs=ttk.LabelFrame(f,text="任务日志（自动刷新，仅显示最后120行）",padding=7)
        logs.pack(fill="both",expand=True,pady=(10,0))
        self.logbox=scrolledtext.ScrolledText(logs,height=8,wrap="word",
                   font=("Consolas",9),state="disabled")
        self.logbox.pack(fill="both",expand=True)
        ttk.Label(f,text="关闭窗口不停止后台任务；暂停只在当前日期完成后生效。中断文件不覆盖，恢复时新版本隔离重试。",
                  foreground="#5f717d").pack(anchor="w",pady=(8,0))

    def _choose_root(self):
        path=filedialog.askdirectory(initialdir=self.root_value.get())
        if path:
            self.root_value.set(path)

    def _recent_jobs(self):
        if not JOBS.is_dir():
            return
        existing=sorted(
            (x for x in JOBS.iterdir() if x.is_dir() and ID.fullmatch(x.name)
             and (x/"config.json").exists()),key=lambda p:p.stat().st_mtime,
             reverse=True)
        if existing:
            self._attach(existing[0].name)

    def _attach(self,jobid):
        self.jobid=jobid
        self.id_value.set(jobid)
        cfg=JOBS/jobid/"config.json"
        if cfg.is_file():
            try:
                d=json.loads(cfg.read_text(encoding="utf-8"))
                self.root_value.set(d["root"])
                self.start_value.set(d["start"])
                self.end_value.set(d["end"])
            except (OSError,ValueError,KeyError):
                pass
        self._paint()

    def _new_job(self):
        messagebox.showwarning("旧版整日重写已停用",
            "此功能会重复物化购买Parquet。后续新任务只允许写入已认证H5真实缺口。")
        return
        try:
            a=date.fromisoformat(self.start_value.get().strip())
            b=date.fromisoformat(self.end_value.get().strip())
            if a>b or a<date(2025,1,1) or b>date(2026,12,31):
                raise ValueError("日期必须在2025—2026年，且开始不晚于结束")
            root=Path(self.root_value.get().strip())
            if not root.is_dir() or not (root/"HikyuuData").is_dir():
                raise ValueError("请选择包含HikyuuData的行情数据根目录")
            jobid=secrets.token_hex(6)
            launch(jobid,root=root,start=a.isoformat(),end=b.isoformat())
            self.jobid=jobid
            self.id_value.set(jobid)
            self.status_value.set("新任务已交给独立后台进程："+jobid)
        except (ValueError,OSError,subprocess.SubprocessError) as exc:
            messagebox.showerror("无法启动",str(exc))

    def _pause(self):
        job=self._chosen_job()
        if job is None:
            return
        (job/"stop_after_day.flag").write_text("after_current_day\n",
                                              encoding="ascii")
        messagebox.showinfo("暂停请求已提交",
            "当前日期转换完成后暂停。不要强制结束写盘进程；关闭本界面不会停止任务。")

    def _chosen_job(self):
        jobid=self.id_value.get().strip()
        if not ID.fullmatch(jobid) or not (JOBS/jobid/"config.json").is_file():
            messagebox.showerror("任务ID无效","请从已有任务目录或日志中找回12位任务ID")
            return None
        return JOBS/jobid

    def _resume(self):
        messagebox.showwarning("旧版恢复已停用",
            "已发现旧任务重复物化购买行情；请保留现有状态，不再恢复此模式。")
        return
        job=self._chosen_job()
        if job is None:
            return
        try:
            if (job/"stop_after_day.flag").exists():
                (job/"stop_after_day.flag").unlink()
            launch(job.name,resume=True)
            self._attach(job.name)
            self.status_value.set("已请求后台恢复；如已有任务正在运行，全局写入锁会拒绝第二个进程。")
        except (OSError,subprocess.SubprocessError) as exc:
            messagebox.showerror("无法恢复",str(exc))

    def _open_dir(self):
        job=self._chosen_job()
        if job is not None:
            try:
                os.startfile(str(job))
            except (OSError,AttributeError):
                messagebox.showinfo("任务目录",str(job))

    def _paint(self):
        if not self.jobid:
            return
        folder=JOBS/self.jobid
        path=folder/"state.json"
        try:
            d=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            return
        self.status_value.set(labels(d.get("status"))+
            (" · 当前 "+str(d["current"]) if d.get("current") else "")+
            (" · "+str(d["last_error"])[:160] if d.get("last_error") else ""))
        self.count_value.set(str(d.get("done",0))+" / "+str(d.get("total",0)))
        self.progress.configure(maximum=max(1,int(d.get("total",0))),
                                value=int(d.get("done",0)))
        cfg=folder/"config.json"
        try:
            dates=json.loads(cfg.read_text(encoding="utf-8"))["weekdays"]
        except (OSError,ValueError,KeyError):
            dates=[]
        entries=d.get("days",{})
        wanted={}
        for day in dates:
            x=entries.get(day,{})
            status=("正在处理" if day==d.get("current") else
                    labels(x.get("status","待处理")))
            wanted[day]=(day,status,
                f'{x["1min"]:,}' if "1min" in x else "—",
                f'{x["5min"]:,}' if "5min" in x else "—",
                x.get("source","—"))
        old=set(self.tree.get_children())
        for day,values in wanted.items():
            if self.tree.exists(day):
                if tuple(self.tree.item(day,"values"))!=values:
                    self.tree.item(day,values=values)
            else:
                self.tree.insert("", "end",iid=day,values=values)
        for item in old-set(wanted):
            self.tree.delete(item)
        try:
            live=folder/"worker-stdout.log"
            if not live.is_file():
                live=folder/"activity.log"
            tail=live.read_text(encoding="utf-8",
                    errors="replace").splitlines()[-120:]
            rendered="\n".join(tail)
        except OSError:
            rendered=""
        if rendered!=self.last_log:
            self.last_log=rendered
            self.logbox.configure(state="normal")
            self.logbox.delete("1.0","end")
            self.logbox.insert("end",rendered)
            self.logbox.see("end")
            self.logbox.configure(state="disabled")

    def _refresh(self):
        try:
            self._paint()
        finally:
            self.after(1200,self._refresh)

if __name__=="__main__":
    App().mainloop()
