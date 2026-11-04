#!/usr/bin/env python3
"""Read-only indexed minute gap GUI worker; NEVER writes market Parquet/H5.

Only artifacts written: source-key-only SQLite when explicitly enabled, and
audit job logs/state/aggregate receipts inside H5ParquetReconciler/work.
Unlike the retired minute physical-conversion GUI, this worker never calls
the purchased-source rematerialization writer or activates market pointers.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import traceback
from collections import Counter
from datetime import date,timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
BASE=MODULE/"work"/"minute_audit_gui"
JOBS=BASE/"jobs"
LOCK=BASE/"audit.lock"
JOB_ID=re.compile(r"[a-f0-9]{12}\Z")
INDEX_NAME=re.compile(
    r"purchased-minute-keys-(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})-([a-f0-9]{12})\.sqlite\Z")


def load(tag,name):
    spec=importlib.util.spec_from_file_location(tag,HERE/name)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E=load("gui_minute_index_ensure","ensure-minute-key-index-window.py")
B=load("gui_minute_index_exact_batch","audit-minute-index-window-readonly.py")
D=load("gui_historical_daily_h5_coverage","inspect-daily-h5-coverage-readonly.py")
I=E.I


def date_range(first,last):
    """Validate user input without imposing a global artificial history cap."""
    first=date.fromisoformat(first) if isinstance(first,str) else first
    last=date.fromisoformat(last) if isinstance(last,str) else last
    if not isinstance(first,date) or not isinstance(last,date) or first>last:
        raise ValueError("Dates must use YYYY-MM-DD with start <= end")
    return first,last


def inventory(root):
    """Discover date-bound completed indexes; validate source on use."""
    found=[]
    if I.STORE.is_symlink():
        raise ValueError("Unsafe index store symlink")
    if not I.STORE.exists():
        return found
    for p in sorted(I.STORE.iterdir()):
        if p.suffix!=".sqlite":
            continue
        if p.is_symlink() or not p.is_file():
            raise ValueError("Unsafe completed index item")
        m=INDEX_NAME.fullmatch(p.name)
        if not m:
            continue
        a=date.fromisoformat(m.group(1))
        b=date.fromisoformat(m.group(2))
        if a>b:
            raise ValueError("Malformed source-index date range")
        found.append((a,b,p))
    return found


def plan(root,first,last,*,allow_build=False,mode="minute"):
    """Partition requested range into reused existing indexes and new gaps.

    Prefer existing index windows even if they cover only part of a month.
    Never rebuild a covered window. Any two covering indexes for a requested
    day cause a fail-closed conflict, not silent selection.
    """
    first,last=date_range(first,last)
    if mode=="day":
        return D.plan(root,first,last)
    if mode!="minute":
        raise ValueError("Unknown audit mode")
    # The verified exact MINUTE key engine is currently bounded to source
    # 2025..2026-10-13. This is NOT a global H5 daily-history cutoff.
    # A future source-aware minute engine can extend coverage safely.
    if first<date(2025,1,1) or last>date(2026,10,13):
        raise ValueError(
            "Verified 1/5min exact-key engine currently supports "
            "2025-01-01..2026-10-13; choose historical DAY coverage mode "
            "for older H5 daily data")
    items=inventory(root)
    days=[]
    day=first
    while day<=last:
        matches=[p for a,b,p in items if a<=day<=b]
        if len(matches)>1:
            raise ValueError("Overlapping existing minute key indexes: manual review required")
        days.append((day,matches[0] if matches else None))
        day+=timedelta(days=1)
    windows=[]
    n=0
    while n<len(days):
        a,path=days[n]
        k=n+1
        while k<len(days):
            d,p=days[k]
            # Never build cross-month/cross-year new index fragments;
            # existing valid index windows may span months within bounds.
            if p!=path or (path is None and (d.year,d.month)!=(a.year,a.month)):
                break
            if (d-a).days>=31:
                break
            k+=1
        b=days[k-1][0]
        if path is None and not allow_build:
            raise ValueError(
                "Unindexed date range "+a.isoformat()+".."+b.isoformat()+
                "; enable private key-only index building to continue")
        windows.append({
            "first":a.isoformat(),"last":b.isoformat(),
            "existing_index":str(path) if path else None,
            "mode":"reuse_existing_index" if path else "build_missing_private_index",
            "eligible_weekdays":sum(days[i][0].weekday()<5 for i in range(n,k)),
        })
        n=k
    return windows


def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".tmp."+str(os.getpid()))
    with tmp.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(obj,f,ensure_ascii=False,sort_keys=True,indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp,path)


def start_job(root,first,last,allow_build,jobid,*,mode="minute"):
    if not isinstance(jobid,str) or not JOB_ID.fullmatch(jobid):
        raise ValueError("Job identifier must be 12 hex characters")
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Original market root missing or unsafe")
    if mode=="minute":
        I.N.validate(root,first,"000000000000")
    elif mode!="day":
        raise ValueError("Unknown audit mode")
    windows=plan(root,first,last,allow_build=allow_build,mode=mode)
    job=JOBS/jobid
    if job.is_symlink() or job.exists() or JOBS.is_symlink():
        raise ValueError("Audit job ID already exists / unsafe job path")
    job.mkdir(parents=True,exist_ok=False)
    dump(job/"config.json",{
        "job_id":jobid,"root":str(root.resolve()),
        "from_day":str(first),"through_day":str(last),
        "audit_mode":mode,
        "allow_create_private_key_indexes":bool(allow_build),
        "audit_only_no_market_data_writes":True,
        "windows":windows,
    })
    dump(job/"state.json",{
        "job_id":jobid,"status":"created",
        "windows_total":len(windows),"windows_done":0,
        "days_total":sum(w["eligible_weekdays"] for w in windows),
        "days_done":0,"current_day":None,
        "current_window":None,"last_error":None,
        "new_market_gap_keys_accepted":0,
        "purchased_ohlcva_rows_rematerialized":0,
        "summary_by_period":{},
    })
    return job


def _job(jobid):
    if not JOB_ID.fullmatch(jobid):
        raise ValueError("Invalid audit job ID")
    job=JOBS/jobid
    if (job.is_symlink() or not job.is_dir()
            or (job/"state.json").is_symlink()
            or (job/"config.json").is_symlink()):
        raise ValueError("Unsafe job path")
    return job


def run(jobid):
    job=_job(jobid)
    config=json.loads((job/"config.json").read_text(encoding="utf-8"))
    state=json.loads((job/"state.json").read_text(encoding="utf-8"))
    if (state.get("status")!="created" or config.get("job_id")!=jobid
            or state.get("job_id")!=jobid
            or config.get("audit_only_no_market_data_writes") is not True):
        raise ValueError("Only new safe read-only audit jobs may start")
    # Exclusive advisory lock also protects against two simultaneous GUI
    # index builders running in the same repo. Old legacy writer is retired.
    with I.N.W.exclusive_lock(LOCK):
        root=Path(config["root"])
        mode=config.get("audit_mode","minute")
        windows=plan(root,config["from_day"],config["through_day"],
                     allow_build=config["allow_create_private_key_indexes"],
                     mode=mode)
        if windows!=config["windows"]:
            raise ValueError("Index inventory changed between GUI plan and execution")
        state["status"]="running"
        dump(job/"state.json",state)
        total={period:Counter() for period in
               (("1min","5min") if mode=="minute" else ("day",))}
        for w in windows:
            first,last=w["first"],w["last"]
            state["current_window"]=first+".."+last
            dump(job/"state.json",state)
            print("AUDIT WINDOW "+state["current_window"]+" "+w["mode"],flush=True)
            if mode=="day":
                summary=D.inspect_year(root,first,last)
                receipt=job/("audit-day-"+first+"-"+last+".json")
                if receipt.exists() or receipt.is_symlink():
                    raise ValueError("Historical day inventory receipt would be overwritten")
                dump(receipt,summary)
                total["day"]["h5_a_share_candidate_daily_rows"]+=summary[
                    "h5_a_share_candidate_daily_rows"]
                total["day"]["h5_candidate_symbols_present"]+=summary[
                    "h5_candidate_symbols_present"]
                total["day"]["purchased_annual_files_checked"]+=summary[
                    "purchased_day_parquet_year_file_count"]
                state["latest_day"]={
                    "year":summary["year"],"h5_daily_candidate_rows":summary[
                        "h5_a_share_candidate_daily_rows"],
                    "net_day_gap_certified":False,
                }
                state["days_done"]+=1
                state["windows_done"]+=1
                state["summary_by_period"]={"day":dict(sorted(total["day"].items()))}
                state["current_day"]=str(summary["year"])
                dump(job/"state.json",state)
                print("H5 DAILY HISTORY "+str(summary["year"])+
                      " native_candidate_rows="+str(summary[
                          "h5_a_share_candidate_daily_rows"])+
                      " actual_gap_not_certified",flush=True)
                if (job/"pause_after_window.flag").exists():
                    state["status"]="paused"
                    print("SAFE PAUSE after completed daily year window",flush=True)
                    break
                continue
            if w["existing_index"] is not None:
                idx=Path(w["existing_index"])
                # Query both bounds/periods to recheck index source metadata
                # before H5 inspection. Never silently switch to a new index.
                for period in ("1min","5min"):
                    for d in (first,last):
                        I.query_index(idx,root,period,d)
            else:
                got=E.ensure(root,first,last)
                if not got["new_private_index_created"]:
                    raise RuntimeError("New source-index window unexpectedly reused")
                idx=Path(got["index_path"])
                print("INDEX BUILT "+str(idx.name),flush=True)

            def progress(d,row,count):
                state["current_day"]=d.isoformat()
                state["days_done"]+=1
                state["latest_day"]={
                    "day":d.isoformat(),
                    "1min_full_gap":row["periods"]["1min"][
                        "h5_only_keys_on_full_purchased_absence_days"],
                    "1min_partial_candidate":row["periods"]["1min"][
                        "h5_only_candidate_keys_on_partial_purchased_stockdays"],
                    "5min_full_gap":row["periods"]["5min"][
                        "h5_only_keys_on_full_purchased_absence_days"],
                    "5min_partial_candidate":row["periods"]["5min"][
                        "h5_only_candidate_keys_on_partial_purchased_stockdays"],
                    "1min_h5_quarantine":row["periods"]["1min"][
                        "quarantined_h5_stockdays_by_reason"],
                }
                dump(job/"state.json",state)

            result=B.audit(root,idx,first,last,progress=progress)
            receipt=job/("audit-"+first+"-"+last+".json")
            if receipt.exists() or receipt.is_symlink():
                raise ValueError("Historical audit receipt would be overwritten")
            dump(receipt,result)
            for period in total:
                for k,value in result["summaries"][period].items():
                    if isinstance(value,int):
                        total[period][k]+=value
                    elif k=="quarantined_h5_stockdays_by_reason":
                        for reason,count in value.items():
                            total[period]["quarantined_"+reason]+=count
            state["summary_by_period"]={
                period:dict(sorted(total[period].items()))
                for period in total
            }
            state["windows_done"]+=1
            state["current_day"]=None
            dump(job/"state.json",state)
            if (job/"pause_after_window.flag").exists():
                state["status"]="paused"
                print("SAFE PAUSE after completed index window",flush=True)
                break
        else:
            state["status"]="completed"
        state["current_window"]=None
        state["current_day"]=None
        dump(job/"state.json",state)
        print("AUDIT FINISHED status="+state["status"]+
              " windows="+str(state["windows_done"])+"/"+
              str(state["windows_total"])+" purchased_bars_copied=0",flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job-id",required=True)
    args=p.parse_args(argv)
    try:
        run(args.job_id)
    except Exception as exc:
        try:
            job=_job(args.job_id)
            state=json.loads((job/"state.json").read_text(encoding="utf-8"))
            state["status"]="failed"
            state["last_error"]=type(exc).__name__+": "+str(exc)
            dump(job/"state.json",state)
        except Exception:
            pass
        traceback.print_exc()
        raise SystemExit(2)


if __name__=="__main__":
    main()
