#!/usr/bin/env python3
"""Start/resume real 2025/2026 1min+5min private Parquet backfill, detached.

The existing GUI background worker does every real DAY write and full readback.
This launcher does not touch purchased source Parquet or original Hikyuu H5.
Its sole purpose is to start a durable worker without manual GUI clicks, reuse
a matching interrupted task, and avoid starting a duplicate live writer.
No false claim that a weekday without market bars is covered.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import re
import secrets
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
JOBS=MODULE/"work"/"minute_gui"/"jobs"
JOB_ID=re.compile("[a-f0-9]{12}\\Z")

def load(tag,name):
    spec=importlib.util.spec_from_file_location(tag,HERE/name)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

W=load("minute_backfill_existing_worker","minute-private-parquet-worker.py")
GUI=load("minute_backfill_existing_gui","minute-private-parquet-gui.py")

def validate(root,start,end):
    path=Path(root)
    if (path.is_symlink() or not path.is_dir()
            or not (path/"HikyuuData").is_dir()):
        raise ValueError("The original read-only source needs a HikyuuData folder")
    try:
        a=date.fromisoformat(start)
        b=date.fromisoformat(end)
    except (TypeError,ValueError):
        raise ValueError("Require ISO start/end dates") from None
    if (a>b or a<date(2025,1,1) or b>date(2026,10,13)):
        raise ValueError("Do not invent dates beyond last verified H5 source 2026-10-13")
    if a.year!=b.year:
        raise ValueError("One calendar-year job at a time, 2026 then 2025")
    if JOBS.is_symlink() or GUI.JOBS!=JOBS or W.JOBS!=JOBS:
        raise ValueError("Unsafe GUI jobs storage mismatch")
    if W.LOCK.parent.is_symlink() or W.LOCK.is_symlink():
        raise ValueError("Unsafe or changed writer lock")
    return path.resolve(),a.isoformat(),b.isoformat()

def matching_jobs(root,start,end):
    if not JOBS.is_dir():
        return []
    found=[]
    for folder in JOBS.iterdir():
        if not folder.is_dir() or folder.is_symlink() or not JOB_ID.fullmatch(folder.name):
            continue
        cfg=folder/"config.json"
        state=folder/"state.json"
        if not cfg.is_file() or not state.is_file() or cfg.is_symlink() or state.is_symlink():
            continue
        if cfg.stat().st_size>200000 or state.stat().st_size>2000000:
            raise ValueError("Suspicious existing minute worker job state")
        obj=json.loads(cfg.read_text(encoding="utf-8"))
        if (obj.get("mode")!="REAL_PRIVATE_PURCHASED_FIRST_1MIN_5MIN_PARQUET_ONLY"
                or obj.get("start")!=start or obj.get("end")!=end
                or obj.get("root")!=str(root)):
            continue
        s=json.loads(state.read_text(encoding="utf-8"))
        if (s.get("job_id")!=folder.name
                or s.get("status") not in ("created","running","paused",
                                           "failed","completed")):
            raise ValueError("Unsafe or unknown prior task state")
        found.append((folder,s))
    return sorted(found,key=lambda item:item[0].stat().st_mtime,reverse=True)

def launch(root,start,end,*,dry_run=False):
    root,start,end=validate(root,start,end)
    prior=matching_jobs(root,start,end)
    if prior and prior[0][1]["status"]=="completed":
        return {"status":"already_completed_no_new_market_writes",
                "job_id":prior[0][0].name,"root":str(root),
                "start":start,"end":end,"launched":False}
    # Inspect the shared writer lock first: 0 concurrent physical writers.
    try:
        with W.exclusive_lock(W.LOCK):
            pass
    except RuntimeError as exc:
        return {"status":"another_minute_writer_active_no_new_job",
                "job_id":prior[0][0].name if prior else None,
                "root":str(root),"start":start,"end":end,
                "launched":False,"reason":str(exc)}
    if prior:
        job=prior[0][0]
        resume=True
        identifier=job.name
    else:
        identifier=secrets.token_hex(6)
        resume=False
    if dry_run:
        return {"status":"dry_run_no_child_process",
                "job_id":identifier if resume else None,
                "root":str(root),"start":start,"end":end,
                "would_resume_existing":resume,"launched":False}
    # RETIRED: full-day purchased Parquet rematerialization is not H5
    # gap filling. The user requested a source-first delta overlay.
    # Do not spawn a new worker or resume any paused legacy job.
    # Existing running workers are unaffected by this source change.
    raise RuntimeError(
        "RETIRED_FULL_PURCHASED_REWRITE: old 2025/2026 minute job "
        "copies purchased Parquet instead of only writing H5 gaps. "
        "Do not resume. Inspect paused jobs read-only; implement and "
        "verify purchased-primary missing-key overlay first.")

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--start",required=True)
    p.add_argument("--end",required=True)
    p.add_argument("--launch-real-minute-backfill",action="store_true",required=True)
    p.add_argument("--dry-run",action="store_true")
    args=p.parse_args(argv)
    result=launch(args.root,args.start,args.end,dry_run=args.dry_run)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    if result["status"]=="another_minute_writer_active_no_new_job":
        raise SystemExit(3)

if __name__=="__main__":
    main()
