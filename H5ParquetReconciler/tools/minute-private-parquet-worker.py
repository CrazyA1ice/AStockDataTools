#!/usr/bin/env python3
"""Background worker for the real purchased-first 1min/5min PRIVATE Parquet UI.

One date at a time through the already proven batch writer. The worker is a
separate process: closing the Tkinter window or PowerShell does not stop it.
Every output is new and isolated; no purchased/Hikyuu originals are changed.
No full native H5 mirror is claimed or created here.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
JOBS=MODULE/"work"/"minute_gui"/"jobs"
LOCK=MODULE/"work"/"minute_gui"/"active.lock"
REPORTS=MODULE/"reports"
ID=re.compile(r"[a-f0-9]{12}\Z")
CONTRACT={"1min":"native_1min_end_equals_purchased_1min_end",
          "5min":"native_5min_end_minus_5_equals_purchased_5min_start"}

def module(tag, filename):
    spec=importlib.util.spec_from_file_location(tag,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

B=module("minute_gui_real_day_runner","run-real-minute-h5-gap-unified-range.py")

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".tmp."+str(os.getpid()))
    with tmp.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(obj,f,ensure_ascii=False,sort_keys=True,indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp,path)

def log(job,line):
    line=time.strftime("%Y-%m-%d %H:%M:%S")+" "+str(line)
    with (job/"activity.log").open("a",encoding="utf-8") as f:
        f.write(line+"\n")
    print(line,flush=True)

def weekdays(first,last):
    a=date.fromisoformat(first)
    b=date.fromisoformat(last)
    if a>b or a<date(2025,1,1) or b>date(2026,12,31):
        raise ValueError("Choose a date range within 2025–2026")
    result=[]
    while a<=b:
        if a.weekday()<5:
            result.append(a.isoformat())
        a+=timedelta(days=1)
    if not result:
        raise ValueError("No candidate weekdays")
    return result

@contextlib.contextmanager
def exclusive_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a+b") as fp:
        fp.seek(0)
        fp.write(b"\0")
        fp.flush()
        fp.seek(0)
        if os.name=="nt":
            import msvcrt
            try:
                msvcrt.locking(fp.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as e:
                raise RuntimeError("Another minute writer is running") from e
            try:
                yield
            finally:
                fp.seek(0)
                msvcrt.locking(fp.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            try:
                fcntl.flock(fp,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as e:
                raise RuntimeError("Another minute writer is running") from e
            try:
                yield
            finally:
                fcntl.flock(fp,fcntl.LOCK_UN)

def sha(path):
    return B.digest(path)

def check_contract(staged,unified):
    for period in ("1min","5min"):
        origin=staged["period_results"][period]
        item=unified["periods"][period]
        if (origin.get("private_parquet_rows",0)>0
            and (origin.get("standardized_minute_key_contract")!=CONTRACT[period]
                 or item.get("standardized_minute_key_contract")!=CONTRACT[period])):
            raise ValueError("Uncertified or legacy -1min H5 time key")
    return unified

def verified_existing_batch(day):
    """Reuse completed daily receipts FROM ANY PREVIOUS RUN (not only ours).

    If a receipt is present but invalid, fail closed. Zero-source weekdays
    are explicitly NOT considered historical source coverage.
    """
    label=day.replace("-","")
    valid=[]
    for unified_file in sorted(REPORTS.glob(f"minute-batch-unified-{label}-*.json")):
        match=re.fullmatch(r"minute-batch-unified-"+label+r"-([a-f0-9]{12})\.json",
                           unified_file.name)
        if not match:
            raise ValueError("Unexpected daily verified filename")
        child=match.group(1)
        stage=REPORTS/f"minute-batch-stage-{label}-{child}.json"
        staged,u=B.verified_completed(date.fromisoformat(day),stage,unified_file,child)
        check_contract(staged,u)
        rows={p:int(u["periods"][p]["unified_rows"]) for p in ("1min","5min")}
        if sum(rows.values())>0:
            valid.append((rows,{p:u["periods"][p]["unified_parquet_sha256"]
                                for p in ("1min","5min")},str(unified_file)))
    if day=="2026-10-13":
        # Only the version corrected to the 1min native END time label
        # can be used. The earlier v1 -1min snapshot is deliberately ignored.
        u_file=REPORTS/"real-unified-minute-parquet-20261013-end-key-11127c8d60ba.json"
        if u_file.exists():
            stage=REPORTS/"minute-h5-1min-end-rekey-20261013-11127c8d60ba.json"
            if not stage.is_file():
                raise ValueError("Corrected Oct13 stage SAFE absent")
            staged,source_day,_=B.UN.G.selected_source(stage)
            u=json.loads(u_file.read_text(encoding="utf-8"))
            if (source_day.isoformat()!=day or u.get("source_day")!=day or
                u.get("source_minute_gap_safe_sha256")!=sha(stage) or
                u.get("status")!="purchased_first_1min_5min_physical_parquet_unified_readback_only" or
                u.get("original_purchased_parquet_or_hikyuu_h5_modified") is not False):
                raise ValueError("Oct13 corrected SAFE origin mismatch")
            check_contract(staged,u)
            rows={}
            hashes={}
            for period in ("1min","5min"):
                e=u["periods"][period]
                rel=e["unified_parquet_relative_file"]
                path=(MODULE/rel).resolve()
                if (not path.is_file() or not path.is_relative_to(
                        (MODULE/"work"/"unified_parquet").resolve()) or
                    sha(path)!=e["unified_parquet_sha256"] or
                    e.get("full_merged_source_rows_and_vendor_extra_columns_readback_verified") is not True):
                    raise ValueError("Corrected Oct13 physical file SHA changed")
                rows[period]=e["unified_rows"]
                hashes[period]=e["unified_parquet_sha256"]
            valid.append((rows,hashes,str(u_file)))
    if not valid:
        return None
    if any(item[1]!=valid[0][1] or item[0]!=valid[0][0] for item in valid):
        raise ValueError("Conflicting accepted snapshots for "+day+"; manual choice required")
    return {"status":"sha_reused_existing_verified_day",
            "source":"existing_safe","1min":valid[0][0]["1min"],
            "5min":valid[0][0]["5min"],"safe":valid[0][2]}

def report_out(day,run_id):
    return REPORTS/f"minute-gui-day-{day.replace('-','')}-{run_id}.json"

def run_id(jobid,day,attempt):
    return hashlib.sha256(
        (jobid+":"+day+":"+str(attempt)).encode("ascii")).hexdigest()[:12]

def candidate_paths(day,child):
    stage,unified=B.receipt_paths(date.fromisoformat(day),child)
    return (stage,unified,
            MODULE/"work"/"unified_parquet"/"minute_gap_staging"/child,
            MODULE/"work"/"unified_parquet"/"minute_complete_day"/("minute_"+child))

def process_one(day,job_id,attempt,root,job):
    """Recover a fully finished child if interrupted before state flush.

    A partially written child gets a new attempt ID, retaining its broken
    evidence in a separate isolated directory; never delete/overwrite it.
    """
    for tries in range(100):
        child=run_id(job_id,day,attempt)
        safe=report_out(day,child)
        stage,unified,staging_dir,union_dir=candidate_paths(day,hashlib.sha256(
            (child+":"+day).encode("ascii")).hexdigest()[:12])
        # B.process derives its own per-day child from the supplied run_id.
        if safe.is_file():
            doc=json.loads(safe.read_text(encoding="utf-8"))
            if (doc.get("batch_days")!=1 or
                doc.get("status")!="bounded_two_period_actual_minute_days_physical_parquet_completed" or
                doc.get("days",[{}])[0].get("day")!=day):
                raise ValueError("Existing GUI daily SAFE conflicts")
            B.verified_completed(date.fromisoformat(day),stage,unified,
                                 staging_dir.name)
            result=check_contract(json.loads(stage.read_text(encoding="utf-8")),
                                  json.loads(unified.read_text(encoding="utf-8")))
        elif ((stage.exists() or unified.exists() or staging_dir.exists() or
               union_dir.exists()) and not (stage.is_file() and unified.is_file())):
            log(job,day+" previous interrupted attempt "+str(attempt)+
                    " remains isolated; starting a new attempt")
            attempt+=1
            continue
        else:
            log(job,day+" start actual purchased-first H5-gap 1min/5min physical Parquet")
            doc=B.process(root,date.fromisoformat(day),date.fromisoformat(day),
                          child,safe,max_days=1)
            result=check_contract(json.loads(stage.read_text(encoding="utf-8")),
                                  json.loads(unified.read_text(encoding="utf-8")))
        if result.get("source_day")!=day:
            raise ValueError("Unexpected completed physical day")
        counts={p:int(result["periods"][p]["unified_rows"]) for p in ("1min","5min")}
        entry={"status":("finished_verified" if sum(counts.values()) else
                          "no_market_source_rows"),
               "source":"new_private_parquet",
               "1min":counts["1min"],"5min":counts["5min"],
               "safe":str(unified),"attempt":attempt}
        return entry
    raise RuntimeError("More than 100 interrupted isolated attempts for one date")

def new_job(jobid,root,start,end):
    if not ID.fullmatch(jobid):
        raise ValueError("Invalid job identifier")
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Source market directory missing/unsafe")
    days=weekdays(start,end)
    job=JOBS/jobid
    job.mkdir(parents=True,exist_ok=False)
    dump(job/"config.json",{"job_id":jobid,"root":str(root.resolve()),
        "start":start,"end":end,"weekdays":days,
        "mode":"REAL_PRIVATE_PURCHASED_FIRST_1MIN_5MIN_PARQUET_ONLY"})
    dump(job/"state.json",{"status":"created","job_id":jobid,
        "total":len(days),"done":0,"current":None,"days":{},
        "last_error":None,"pid":None})
    return job

def worker(jobid,resume=False,root=None,start=None,end=None):
    if not ID.fullmatch(jobid):
        raise ValueError("Invalid job ID")
    job=JOBS/jobid
    with exclusive_lock(LOCK):
        if resume:
            cfg=json.loads((job/"config.json").read_text(encoding="utf-8"))
        else:
            cfg=json.loads((new_job(jobid,root,start,end)/"config.json").read_text(
                encoding="utf-8"))
        source=Path(cfg["root"])
        all_days=cfg["weekdays"]
        state=json.loads((job/"state.json").read_text(encoding="utf-8"))
        state["pid"]=os.getpid()
        state["status"]="running"
        state["last_error"]=None
        dump(job/"state.json",state)
        log(job,"Real PRIVATE minute Parquet worker started (PID "+str(os.getpid())+")")
        try:
            for day in all_days:
                if state["days"].get(day,{}).get("status") in (
                        "finished_verified","sha_reused_existing_verified_day",
                        "no_market_source_rows"):
                    continue
                if (job/"stop_after_day.flag").exists():
                    state["status"]="paused"
                    log(job,"Pause requested: no new day started")
                    break
                state["current"]=day
                state["status"]="running"
                dump(job/"state.json",state)
                reused=verified_existing_batch(day)
                if reused:
                    entry=reused
                    log(job,day+" SKIP: existing source-SHA-verified private Parquet "+
                        str(reused["1min"])+" / "+str(reused["5min"]))
                else:
                    previous=state["days"].get(day,{})
                    attempt=int(previous.get("attempt",0))
                    entry=process_one(day,jobid,attempt,source,job)
                    log(job,day+" "+entry["status"]+
                        " 1min="+str(entry["1min"])+
                        " 5min="+str(entry["5min"]))
                state["days"][day]=entry
                state["done"]=len(state["days"])
                state["current"]=None
                dump(job/"state.json",state)
            else:
                state["status"]="completed"
            if state["status"]=="paused" and (job/"stop_after_day.flag").exists():
                (job/"stop_after_day.flag").unlink()
        except Exception as exc:
            state["status"]="failed"
            state["last_error"]=str(exc)
            if state["current"] is not None:
                prev=state["days"].get(state["current"],{})
                state["days"][state["current"]]={
                    "status":"interrupted_or_failed","attempt":prev.get("attempt",0),
                    "error":str(exc)}
            log(job,"STOP: "+type(exc).__name__+": "+str(exc))
            log(job,traceback.format_exc()[-4500:])
        finally:
            state["current"]=None
            state["done"]=sum(
                x.get("status") in ("finished_verified",
                                   "sha_reused_existing_verified_day",
                                   "no_market_source_rows")
                for x in state["days"].values())
            dump(job/"state.json",state)
            log(job,"Worker ended: "+state["status"]+
                ", processed "+str(state["done"])+"/"+str(state["total"]))
        if state["status"]=="failed":
            raise RuntimeError("Minute worker failed; inspect activity.log and resume safely")
        return state

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job-id",required=True)
    p.add_argument("--resume",action="store_true")
    p.add_argument("--root",type=Path)
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--run-real-private-minute-parquet",action="store_true",required=True)
    a=p.parse_args(argv)
    if not a.resume and (a.root is None or not a.start or not a.end):
        p.error("New job requires source root and bounded date range")
    worker(a.job_id,resume=a.resume,root=a.root,start=a.start,end=a.end)

if __name__=="__main__":
    main()
