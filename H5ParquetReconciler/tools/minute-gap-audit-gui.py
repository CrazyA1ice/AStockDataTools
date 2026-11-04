#!/usr/bin/env python3
"""Minute data SOURCE-KEY gap-audit dashboard (Tkinter, read-only markets).

Independent of the retired physical purchased-Parquet rematerialization GUI.
User can select a month/range and reuse indexed source keys, optionally
create missing *key-only* private indexes. NEVER write original market bars.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog,messagebox,scrolledtext,ttk

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
WORKER=HERE/"minute-gap-audit-gui-worker.py"

def load_worker():
    import importlib.util
    spec=importlib.util.spec_from_file_location(
        "safe_minute_gap_audit_gui_backend",WORKER)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


W=load_worker()
JOBS=W.JOBS


def launch(jobid):
    """Always a separate process, never the retired purchased-copy worker."""
    job=JOBS/jobid
    if not job.is_dir() or job.is_symlink():
        raise ValueError("New read-only audit job directory missing")
    env=os.environ.copy()
    env["PYTHONIOENCODING"]="utf-8"
    flags=(getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0)
    with (job/"activity.log").open("ab") as log:
        return subprocess.Popen(
            [sys.executable,"-B",str(WORKER),"--job-id",jobid],
            cwd=str(MODULE),env=env,stdin=subprocess.DEVNULL,
            stdout=log,stderr=subprocess.STDOUT,close_fds=True,
            creationflags=flags)


def load_json(path):
    if path.is_symlink() or path.stat().st_size>2000000:
        raise ValueError("Unsafe/oversize audit state file")
    return json.loads(path.read_text(encoding="utf-8"))


def available_jobs():
    if not JOBS.is_dir() or JOBS.is_symlink():
        return []
    items=[]
    for directory in JOBS.iterdir():
        if directory.is_symlink() or not directory.is_dir():
            continue
        state=directory/"state.json"
        cfg=directory/"config.json"
        if not W.JOB_ID.fullmatch(directory.name) or not state.is_file() or not cfg.is_file():
            continue
        try:
            doc=load_json(state)
            meta=load_json(cfg)
            if doc.get("job_id")!=directory.name or meta.get("job_id")!=directory.name:
                continue
            items.append((directory,doc,meta))
        except (OSError,ValueError,KeyError,json.JSONDecodeError):
            continue
    return sorted(items,key=lambda x:x[0].stat().st_mtime,reverse=True)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AStockDataTools · 分钟数据核对控制台（源数据只读）")
        self.geometry("1120x760")
        self.minsize(900,620)
        self.source=tk.StringVar(value=r"D:\stock")
        self.start=tk.StringVar(value="2026-02-01")
        self.end=tk.StringVar(value="2026-02-28")
        self.allow_index=tk.BooleanVar(value=True)
        self.selected=tk.StringVar(value="")
        self.status=tk.StringVar(value="就绪 · 仅核对分钟时间键，不修改市场Parquet/H5")
        self.indicators=tk.StringVar(value="无已选任务")
        self.recent_summary=tk.StringVar(value="H5净新增候选：—   购买数据复制：0")
        self.last_seen=""
        self._layout()
        self._refresh()
        self.after(1100,self._tick)

    def _layout(self):
        pad=ttk.Frame(self,padding=14)
        pad.pack(fill="both",expand=True)
        ttk.Label(pad,text="分钟数据缺口核对",font=("Microsoft YaHei UI",18,"bold")).pack(anchor="w")
        ttk.Label(pad,text="购买Parquet为主 · 复用分钟键索引 · H5精确差集 · 只读市场数据",
                  foreground="#285478").pack(anchor="w",pady=(2,3))
        ttk.Label(pad,text="安全边界：允许写入私有SQLite索引与核对报告；禁止复制购买OHLCVA、覆盖源H5、自动补缺或启用生产指针。",
                  foreground="#a13e17",wraplength=1040).pack(anchor="w",pady=(0,10))
        options=ttk.LabelFrame(pad,text="范围与源目录",padding=10)
        options.pack(fill="x")
        ttk.Label(options,text="原始行情目录").grid(row=0,column=0,sticky="w")
        ttk.Entry(options,textvariable=self.source).grid(row=0,column=1,columnspan=3,sticky="ew",padx=8)
        ttk.Button(options,text="浏览…",command=self._browse).grid(row=0,column=4,sticky="e")
        ttk.Label(options,text="开始").grid(row=1,column=0,sticky="w",pady=(8,0))
        ttk.Entry(options,textvariable=self.start,width=16).grid(row=1,column=1,sticky="ew",padx=8,pady=(8,0))
        ttk.Label(options,text="结束").grid(row=1,column=2,sticky="w",pady=(8,0))
        ttk.Entry(options,textvariable=self.end,width=16).grid(row=1,column=3,sticky="ew",padx=8,pady=(8,0))
        ttk.Checkbutton(options,text="允许创建缺少的私有键索引（仅ts/symbol，不存OHLCVA）",
                        variable=self.allow_index).grid(row=2,column=0,columnspan=5,sticky="w",pady=(10,0))
        options.columnconfigure(1,weight=2)
        options.columnconfigure(3,weight=1)
        actions=ttk.Frame(pad)
        actions.pack(fill="x",pady=10)
        ttk.Button(actions,text="查看将要复用/新建的索引分段",command=self._preview).pack(side="left",padx=(0,7))
        ttk.Button(actions,text="开始批量只读核对",command=self._start).pack(side="left",padx=7)
        ttk.Button(actions,text="当前分段完成后暂停",command=self._pause).pack(side="left",padx=7)
        ttk.Button(actions,text="填入剩余未完成范围",command=self._remaining).pack(side="left",padx=7)
        ttk.Button(actions,text="查看隔离异常",command=self._exceptions).pack(side="left",padx=7)
        ttk.Button(actions,text="刷新",command=self._refresh).pack(side="right")
        ttk.Label(pad,textvariable=self.status,foreground="#264a6b").pack(anchor="w",pady=(0,3))
        ttk.Label(pad,textvariable=self.indicators).pack(anchor="w")
        self.progress=ttk.Progressbar(pad,mode="determinate",maximum=100)
        self.progress.pack(fill="x",pady=(5,9))
        ttk.Label(pad,textvariable=self.recent_summary,foreground="#355d44").pack(anchor="w",pady=(0,10))
        split=ttk.Panedwindow(pad,orient="vertical")
        split.pack(fill="both",expand=True)
        upper=ttk.Frame(split)
        lower=ttk.Frame(split)
        split.add(upper,weight=2)
        split.add(lower,weight=3)
        cols=("range","status","dates","gaps","exceptions")
        self.table=ttk.Treeview(upper,columns=cols,show="headings",height=8,selectmode="browse")
        for key,text,width in (
                ("range","已登记任务范围",250),
                ("status","任务状态",100),
                ("dates","完成日期",110),
                ("gaps","H5候选缺口",140),
                ("exceptions","隔离股票日",100)):
            self.table.heading(key,text=text)
            self.table.column(key,width=width,anchor="w" if key=="range" else "center")
        self.table.pack(side="left",fill="both",expand=True)
        scroll=ttk.Scrollbar(upper,orient="vertical",command=self.table.yview)
        scroll.pack(side="right",fill="y")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind("<<TreeviewSelect>>",self._select)
        ttk.Label(lower,text="任务日志（选中历史任务即可查看）").pack(anchor="w",pady=(7,3))
        self.log=scrolledtext.ScrolledText(lower,wrap="word",height=12,font=("Consolas",10))
        self.log.pack(fill="both",expand=True)
        self.log.configure(state="disabled")
        ttk.Label(pad,text="注意：本工具仅核对已知2025—2026分钟源；异常H5记录保持隔离，不能将0候选等同于行情质量全部认证。",
                  foreground="#697580",wraplength=1050).pack(anchor="w",pady=(8,0))

    def _browse(self):
        path=filedialog.askdirectory(initialdir=self.source.get())
        if path:self.source.set(path)

    def _request(self):
        return (Path(self.source.get()),self.start.get().strip(),
                self.end.get().strip(),self.allow_index.get())

    def _preview(self):
        try:
            root,a,b,allow=self._request()
            W.I.N.validate(root,a,"000000000000")
            windows=W.plan(root,a,b,allow_build=allow)
            reused=sum(x["mode"]=="reuse_existing_index" for x in windows)
            created=len(windows)-reused
            weekdays=sum(x["eligible_weekdays"] for x in windows)
            lines=[f'{x["first"]} 至 {x["last"]} · '+
                   ("复用已建索引" if x["existing_index"] else "只建缺失私有键索引")
                   for x in windows]
            messagebox.showinfo("只读核对计划",
                f"合计 {len(windows)} 个分段；复用 {reused}，新建 {created}；"+
                f"候选工作日 {weekdays} 个。\n\n"+
                "\n".join(lines[:30])+
                ("\n…其余分段略" if len(lines)>30 else "")+
                "\n\n不会修改原始Parquet/H5，也不会写入任何行情文件。")
        except Exception as e:
            messagebox.showerror("计划不可执行",str(e))

    def _start(self):
        try:
            root,a,b,allow=self._request()
            windows=W.plan(root,a,b,allow_build=allow)
            if any(x[1].get("status") in ("created","running")
                   for x in available_jobs()):
                raise ValueError("已有准备中/运行中的核对任务。请先等待它完成，或安全暂停当前分段。")
            if not any(w["eligible_weekdays"] for w in windows):
                raise ValueError("所选范围没有候选工作日。")
            msg=(f"核对 {a} 至 {b}；共{len(windows)}个分段。\n"+
                 f"索引不足时{'允许新建私有键索引' if allow else '拒绝新建任何索引'}。\n"+
                 "所有原始行情严格只读；生成的结果仅用于缺口审计。\n确认开始？")
            if not messagebox.askyesno("确认只读核对",msg):
                return
            identifier=secrets.token_hex(6)
            W.start_job(root,a,b,allow,identifier)
            try:
                launch(identifier)
            except Exception as e:
                job=JOBS/identifier
                state=load_json(job/"state.json")
                state["status"]="failed"
                state["last_error"]="Process launch failed: "+str(e)
                W.dump(job/"state.json",state)
                raise
            self.selected.set(identifier)
            self.status.set("任务 "+identifier+" 已启动，正在后台核对；原始行情只读。")
            self._refresh()
        except Exception as e:
            messagebox.showerror("无法启动核对任务",str(e))

    def _selected_job(self):
        ident=self.selected.get()
        if not ident or not W.JOB_ID.fullmatch(ident):
            raise ValueError("请先从任务列表中选择一项。")
        return W._job(ident)

    def _pause(self):
        try:
            job=self._selected_job()
            state=load_json(job/"state.json")
            if state["status"]!="running":
                raise ValueError("仅运行中的任务可请求安全暂停。")
            (job/"pause_after_window.flag").touch(exist_ok=True)
            self.status.set("已请求当前分段结束后暂停；不会强杀正在核对的进程。")
        except Exception as e:
            messagebox.showerror("无法暂停",str(e))

    def _remaining(self):
        try:
            job=self._selected_job()
            cfg=load_json(job/"config.json")
            state=load_json(job/"state.json")
            if state["status"] not in ("paused","failed"):
                raise ValueError("只有已暂停/失败的任务才能选择剩余范围。")
            done=int(state.get("windows_done",0))
            windows=cfg["windows"]
            if done>=len(windows):
                raise ValueError("没有剩余分段。")
            self.start.set(windows[done]["first"])
            self.end.set(cfg["through_day"])
            self.source.set(cfg["root"])
            self.allow_index.set(cfg["allow_create_private_key_indexes"])
            self.status.set("已填入未完成的日期范围。请先查看计划，再启动新任务；旧任务报告保留。")
        except Exception as e:
            messagebox.showerror("无法选择剩余范围",str(e))

    def _exceptions(self):
        """Read completed private receipts: date/period/reason/count only."""
        try:
            job=self._selected_job()
            entries=[]
            for p in sorted(job.glob("audit-*.json")):
                if p.is_symlink() or not p.is_file():
                    raise ValueError("Unsafe private aggregate audit receipt")
                result=load_json(p)
                if result.get("status")!="read_only_existing_index_multi_day_candidate_diff_not_activated":
                    raise ValueError("Unknown audit receipt provenance")
                for row in result.get("days",[]):
                    for period in ("1min","5min"):
                        for reason,count in row["periods"][period].get(
                                "quarantined_h5_stockdays_by_reason",{}).items():
                            if int(count):
                                entries.append((row["day"],period,str(reason),int(count)))
            win=tk.Toplevel(self)
            win.title("H5时间格异常（只读统计，不包含行情数值）")
            win.geometry("690x430")
            note="隔离记录仅说明原生H5时间格异常。不能直接视为购买Parquet缺口或自动补入。"
            ttk.Label(win,text=note,wraplength=660).pack(anchor="w",padx=12,pady=10)
            tree=ttk.Treeview(win,columns=("day","period","reason","count"),
                              show="headings")
            for k,name,width in (
                ("day","日期",125),("period","周期",75),
                ("reason","隔离原因",380),("count","股票日数",80)):
                tree.heading(k,text=name)
                tree.column(k,width=width,anchor="center" if k=="count" else "w")
            tree.pack(fill="both",expand=True,padx=12,pady=(0,12))
            for item in entries:
                tree.insert("","end",values=item)
            if not entries:
                ttk.Label(win,text="当前任务已完成的分段没有记录到H5隔离异常。").pack(
                    anchor="w",padx=12,pady=(0,10))
        except Exception as e:
            messagebox.showerror("无法读取隔离明细",str(e))

    def _select(self,event=None):
        items=self.table.selection()
        if items:self.selected.set(items[0])
        self._paint()

    def _paint(self):
        try:
            job=self._selected_job()
            state=load_json(job/"state.json")
            config=load_json(job/"config.json")
            pct=(100*state["days_done"]/state["days_total"] if state["days_total"] else 0)
            self.progress["value"]=min(100,pct)
            status=state["status"]
            self.indicators.set(
                f"状态：{status}    日期：{state['days_done']}/{state['days_total']}  "+
                f"分段：{state['windows_done']}/{state['windows_total']}    "+
                f"当前：{state.get('current_day') or state.get('current_window') or '—'}")
            summary=state.get("summary_by_period",{})
            pieces=[]
            for period in ("1min","5min"):
                d=summary.get(period,{})
                gaps=int(d.get("h5_only_keys_on_full_purchased_absence_days",0)) + int(
                    d.get("h5_only_candidate_keys_on_partial_purchased_stockdays",0))
                exceptions=sum(int(v) for k,v in d.items() if k.startswith("quarantined_"))
                pieces.append(f"{period}：候选缺口{gaps}，隔离股日{exceptions}")
            self.recent_summary.set("   |   ".join(pieces)+"   |   购买数据复制0条")
            path=job/"activity.log"
            if path.is_file() and not path.is_symlink():
                # Only read the newest 200 kB of log for a responsive GUI.
                with path.open("rb") as f:
                    f.seek(0,2)
                    f.seek(max(0,f.tell()-200000))
                    body=f.read().decode("utf-8",errors="replace")
                if body!=self.last_seen:
                    self.log.configure(state="normal")
                    self.log.delete("1.0","end")
                    self.log.insert("end",body)
                    self.log.see("end")
                    self.log.configure(state="disabled")
                    self.last_seen=body
            if status in ("failed","paused","completed"):
                self.status.set(
                    f"任务 {job.name} {status}。"+
                    (str(state.get("last_error")) if state.get("last_error") else
                     " 原始Parquet与H5未被写入。"))
        except Exception as e:
            self.status.set("任务显示受限："+str(e))

    def _refresh(self):
        data=available_jobs()
        seen={item[0].name for item in data}
        for old in self.table.get_children():
            if old not in seen:self.table.delete(old)
        for directory,state,config in data:
            summary=state.get("summary_by_period",{})
            gaps=sum(int(summary.get(p,{}).get(k,0))
                     for p in ("1min","5min")
                     for k in ("h5_only_keys_on_full_purchased_absence_days",
                               "h5_only_candidate_keys_on_partial_purchased_stockdays"))
            exceptions=sum(int(v)
                           for p in ("1min","5min")
                           for k,v in summary.get(p,{}).items()
                           if k.startswith("quarantined_"))
            cells=(config.get("from_day","")+" → "+config.get("through_day",""),
                   state.get("status","?"),
                   f'{state.get("days_done",0)}/{state.get("days_total",0)}',
                   str(gaps),str(exceptions))
            if self.table.exists(directory.name):
                self.table.item(directory.name,values=cells)
            else:
                self.table.insert("","end",iid=directory.name,values=cells)
        if self.selected.get() not in seen and data:
            self.selected.set(data[0][0].name)
        if self.selected.get() in seen:
            self.table.selection_set(self.selected.get())
            self._paint()

    def _tick(self):
        self._refresh()
        self.after(1100,self._tick)


if __name__=="__main__":
    App().mainloop()
