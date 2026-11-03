#!/usr/bin/env python3
"""Purchased-primary REAL minute gap overlay: never rematerialize vendor bars.

Preview is read-only. Explicit --write-gap-only may write *only* fully absent,
complete H5 stockdays to isolated private Parquet; zero eligible gaps produce
zero market Parquet files. Partial purchased stockdays remain unexamined and
are NEVER declared complete by this stockday-level gate.

This is NOT a production query activation or an exact partial-minute diff.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import secrets
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
PERIODS=("1min","5min")
RUN_ID=re.compile(r"[a-f0-9]{12}\Z")


def load(tag,name):
    spec=importlib.util.spec_from_file_location(tag,HERE/name)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


ST=load("minute_real_h5_only_stage","write-h5-only-complete-minute-stockdays-to-private-parquet.py")
W=load("minute_gap_overlay_existing_writer_lock","minute-private-parquet-worker.py")


def validate(root,day,run_id):
    root=Path(root)
    if (root.is_symlink() or not root.is_dir()
            or not (root/"HikyuuData").is_dir()
            or not (root/"AllCycleAStockData").is_dir()):
        raise ValueError("Original purchased and Hikyuu source directories required")
    d=date.fromisoformat(day) if isinstance(day,str) else day
    if not isinstance(d,date) or not date(2025,1,1)<=d<=date(2026,10,13):
        raise ValueError("Bound source date to 2025-01-01..2026-10-13")
    if not isinstance(run_id,str) or RUN_ID.fullmatch(run_id) is None:
        raise ValueError("Require 12-character lowercase hexadecimal run ID")
    if ST.WORK.is_symlink() or REPORTS.is_symlink():
        raise ValueError("Unsafe private output location")
    return root.resolve(),d


def source_snapshot(root,year):
    """Cheap change detector, NOT full-content SHA or proof of source version."""
    observed={}
    for period in PERIODS:
        files=ST.CORE.year_files(root,period,year)
        if not files:
            raise ValueError("Purchased year has no parquet source: "+period)
        h5files=[root/"HikyuuData"/(market+"_"+period+".h5")
                 for market in ("sh","sz","bj")]
        if not any(p.is_file() for p in h5files):
            raise ValueError("H5 minute market source missing: "+period)
        for p in [*files,*h5files]:
            if p.exists():
                if p.is_symlink() or not p.is_file():
                    raise ValueError("Original market input file is unsafe")
                stat=p.stat()
                rel=p.relative_to(root).as_posix()
                observed[rel]=(stat.st_size,stat.st_mtime_ns,stat.st_ino)
    serial=json.dumps(observed,sort_keys=True,separators=(",",":"))
    return {
        "change_detector":"path_size_mtime_ns_inode_NOT_CONTENT_SHA",
        "source_files":len(observed),
        "source_metadata_fingerprint_sha256":hashlib.sha256(
            serial.encode("utf-8")).hexdigest(),
    }


def inspect_period(root,day,period,*,max_purchased_rows=6000000,
                   max_h5_rows=2500000):
    """Validate candidate H5-only full stockdays before creating any output."""
    import h5py

    purchased,scan=ST.purchased_stockdays(
        root,period,day,max_rows=max_purchased_rows)
    lo=int(day.strftime("%Y%m%d"))*10000
    hi=int((day+ST.timedelta(days=1)).strftime("%Y%m%d"))*10000
    eligible_rows=0
    eligible_stockdays=0
    h5_seen_stockdays=0
    purchased_stockdays_not_probed=0
    h5_examined=0
    quarantined=Counter()
    missing_market_files=[]
    found_markets=0
    for market in ("sh","sz","bj"):
        h5file=root/"HikyuuData"/(market+"_"+period+".h5")
        if not h5file.exists():
            missing_market_files.append(market)
            continue
        found_markets+=1
        with h5py.File(h5file,"r") as h5:
            group=h5.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("Missing H5 native data group: "+market)
            for symbol in group:
                if (not re.fullmatch(market.upper()+r"\d{6}",symbol)
                        or not ST.CORE.is_a_share_candidate(symbol,day.year)):
                    continue
                # A purchased stockday is authoritative. Deliberately do
                # not infer whether it has partial missing minute keys.
                if symbol in purchased:
                    purchased_stockdays_not_probed+=1
                    continue
                ds=group[symbol]
                if (not isinstance(ds,h5py.Dataset)
                        or not set(ST.RAW_FIELDS).issubset(ds.dtype.names or ())):
                    quarantined["invalid_native_h5_schema"]+=1
                    continue
                a,b=ST.CORE.h5_key_slice(ds,lo,hi)
                if a==b:
                    continue
                h5_seen_stockdays+=1
                h5_examined+=b-a
                if h5_examined>max_h5_rows or b-a>240:
                    raise ValueError("Bounded H5 candidate day row budget exceeded")
                native=ds[a:b]
                classification=ST.completeness(
                    [int(r["datetime"]) for r in native],day,period)
                if classification!="complete":
                    quarantined[classification]+=1
                    continue
                try:
                    rows=[ST.converted_row(r,symbol,period,day)
                          for r in native]
                except (TypeError,ValueError,OverflowError):
                    quarantined["invalid_native_minute_values"]+=1
                    continue
                keys=[r["ts"] for r in rows]
                if len(keys)!=len(set(keys)):
                    quarantined["duplicate_normalized_minute_timestamp"]+=1
                    continue
                eligible_rows+=len(rows)
                eligible_stockdays+=1
    if not found_markets:
        raise ValueError("H5 minute files absent")
    return {
        "period":period,"purchased_source_stockdays":len(purchased),
        "purchased_key_scan":scan,
        "purchased_h5_stockday_datasets_not_probed":purchased_stockdays_not_probed,
        "h5_only_stockdays_seen":h5_seen_stockdays,
        "eligible_complete_h5_only_stockdays":eligible_stockdays,
        "eligible_h5_only_rows":eligible_rows,
        "h5_candidate_native_rows_examined":h5_examined,
        "quarantined_h5_only_stockdays_by_reason":dict(sorted(quarantined.items())),
        "missing_h5_market_files":missing_market_files,
        "partial_purchased_stockday_minute_keys_checked":False,
        "ready_for_production_query":False,
    }


def execute(root,day,run_id,*,write=False,
            max_purchased_rows=6000000,max_h5_rows=2500000):
    root,day=validate(root,day,run_id)
    label=day.strftime("%Y%m%d")
    report=REPORTS/f"minute-h5-gap-only-{label}-{run_id}.json"
    if write and (not REPORTS.is_dir() or report.exists() or
                  report.is_symlink() or report.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Require a new isolated report path under reports")
    def perform():
        before=source_snapshot(root,day.year)
        periods={period:inspect_period(
            root,day,period,max_purchased_rows=max_purchased_rows,
            max_h5_rows=max_h5_rows) for period in PERIODS}
        if source_snapshot(root,day.year)!=before:
            raise RuntimeError("Input market file metadata changed while inspecting")
        results={}
        accepted=0
        for period,entry in periods.items():
            n=entry["eligible_h5_only_rows"]
            if not write or n==0:
                results[period]={
                    "written_h5_gap_rows":0,
                    "private_parquet_relative_file":None,
                    "private_parquet_sha256":None,
                    "status":"preview_only" if not write else
                             "zero_gap_no_market_parquet_written",
                }
                continue
            # Reuse existing thoroughly tested H5-only native lossless writer,
            # NOT the legacy purchased+H5 union writer. No vendor bar copied.
            actual=ST.write_private_day(
                root,day,period,run_id,max_purchased_rows=max_purchased_rows,
                max_h5_rows=max_h5_rows)
            if (actual["private_parquet_rows"]!=n
                    or actual["private_parquet_stockdays"]!=
                    entry["eligible_complete_h5_only_stockdays"]
                    or not actual["h5_raw_integer_fields_preserved"]
                    or actual["original_purchased_parquet_or_h5_modified"] is not False):
                raise ValueError("H5-only staged file differs from exact preview; isolated")
            results[period]={
                "written_h5_gap_rows":n,
                "private_parquet_relative_file":actual["private_parquet_relative_file"],
                "private_parquet_sha256":actual["private_parquet_sha256"],
                "status":"isolated_complete_h5_stockday_gap_written_and_readback",
            }
            accepted+=n
        if source_snapshot(root,day.year)!=before:
            raise RuntimeError("Input market source changed during output, not accepted")
        outcome={
            "format":"AStockDataTools purchased-primary minute H5-only gap overlay v1",
            "day":day.isoformat(),"run_id":run_id,
            "status":("preview_no_market_files_written" if not write else
                     "h5_only_isolated_gap_parquet_written" if accepted else
                     "zero_eligible_full_stockday_gap_no_market_files_written"),
            "periods":periods,"outputs":results,
            "accepted_new_h5_full_stockday_gap_rows":accepted,
            "purchased_bars_rematerialized":0,
            "source_fingerprint":before,
            "source_fingerprint_is_full_content_sha":False,
            "source_fingerprint_checked_unchanged_during_run":True,
            "original_purchased_parquet_or_h5_modified":False,
            "partial_purchased_stockdays_automatically_filled":False,
            "private_or_production_active_pointer_modified":False,
            "ready_for_production_query":False,
            "net_gap_scope":"only_complete_H5_stockdays_with_no_purchased_stockday",
        }
        if write:
            with report.open("x",encoding="utf-8",newline="\n") as f:
                json.dump(outcome,f,ensure_ascii=False,sort_keys=True,indent=2)
                f.write("\n")
            outcome["report_path"]=str(report)
        return outcome
    if not write:
        return perform()
    # Coordinate with legacy GUI worker; fail closed if a writer is active.
    with W.exclusive_lock(W.LOCK):
        return perform()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--day",required=True)
    p.add_argument("--run-id",default=None)
    p.add_argument("--write-gap-only",action="store_true")
    args=p.parse_args(argv)
    rid=args.run_id or secrets.token_hex(6)
    result=execute(args.root,args.day,rid,write=args.write_gap_only)
    print(json.dumps(result,sort_keys=True,ensure_ascii=False,indent=2))
    if not args.write_gap_only:
        print("READ-ONLY PREVIEW. Add --write-gap-only for NEW H5-only gaps, no purchased copies.")


if __name__=="__main__":
    main()
