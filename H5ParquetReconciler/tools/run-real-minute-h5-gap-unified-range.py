#!/usr/bin/env python3
"""Execute actual daily 1min/5min H5 gap fill AND purchased-first physical
Parquet union over an explicit, bounded range of A-share calendar weekdays.

This is a WRITE pipeline, not a candidate planner, index, or pointer. Every
successfully completed day has its own SHA-checked staged and physically
unified Parquet files plus aggregate-only SAFE receipts. Re-running the SAME
--run-id resumes *only* fully verified completed days, not incomplete ones.
An incomplete day fails closed and must be inspected before retrying.

Original purchased Parquet, native Hikyuu H5 and all previously materialized
DAY data remain read-only. Does not claim source timestamp convention has
been vendor-certified or entire minute history has been unified.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
import traceback
from datetime import date,timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
FMT="AStockDataTools real purchased-first two-period private minute batch v1"
RUN=re.compile(r"[0-9a-f]{12}\Z")


def load(name,script):
    spec=importlib.util.spec_from_file_location(name,HERE/script)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


ST=load("minute_range_real_h5_gap_writer",
        "write-h5-only-complete-minute-stockdays-to-private-parquet.py")
UN=load("minute_range_real_purchased_first_writer",
        "write-purchased-first-unified-minute-day-parquet.py")


def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda:stream.read(1<<20),b""):
            h.update(part)
    return h.hexdigest()


def days_between(start,finish,max_days,exclude_dates=()):
    if (type(max_days) is not int or not 1<=max_days<=15
            or start>finish
            or start<date(2025,1,1) or finish>date(2026,12,31)):
        raise ValueError("Require a bounded 1..15 weekdays range in 2025/2026")
    excluded=set(exclude_dates)
    if (len(excluded)!=len(tuple(exclude_dates))
            or any(type(day) is not date or not start<=day<=finish
                   or day.weekday()>=5 for day in excluded)):
        raise ValueError("Excluded days must be unique weekdays in selected range")
    dates=[]
    day=start
    while day<=finish:
        if day.weekday()<5 and day not in excluded:
            dates.append(day)
            if len(dates)>max_days:
                raise ValueError("Too many market candidate weekdays in date range")
        day+=timedelta(days=1)
    if not dates:
        raise ValueError("No unprocessed candidate weekdays in date range")
    return dates


def write_json_new(path,report):
    payload=json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+"\n"
    with path.open("x",encoding="utf-8",newline="\n") as f:
        f.write(payload)


def receipt_paths(day,child):
    label=day.isoformat().replace("-","")
    return (REPORTS/f"minute-batch-stage-{label}-{child}.json",
            REPORTS/f"minute-batch-unified-{label}-{child}.json")


def verified_completed(day,stage_safe,unified_safe,child):
    """Only reuse signed completed outputs; don't replay source market reads."""
    if not stage_safe.is_file() or not unified_safe.is_file():
        raise ValueError("Prior same-run day is partially completed; manual review required")
    if (stage_safe.is_symlink() or unified_safe.is_symlink()
            or stage_safe.resolve().parent!=REPORTS.resolve()
            or unified_safe.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Prior report path unsafe")
    staged,source_day,sources=UN.G.selected_source(stage_safe)
    if source_day!=day or staged.get("source_day")!=day.isoformat():
        raise ValueError("Resumed H5 staged day differs")
    u=json.loads(unified_safe.read_bytes())
    if (u.get("format")!=UN.FMT
            or u.get("status")!=
               "purchased_first_1min_5min_physical_parquet_unified_readback_only"
            or u.get("source_day")!=day.isoformat()
            or u.get("source_minute_gap_safe_sha256")!=digest(stage_safe)
            or u.get("original_purchased_parquet_or_hikyuu_h5_modified") is not False
            or u.get("full_minute_history_unified") is not False
            or set(u.get("periods",{}))!=set(ST.PERIODS)):
        raise ValueError("Prior same-run purchased-first unified SAFE invalid")
    for period in ST.PERIODS:
        record=u["periods"][period]
        source_record=staged["period_results"][period]
        relative=record.get("unified_parquet_relative_file","")
        if (not isinstance(relative,str)
                or not re.fullmatch(
                    r"work/unified_parquet/minute_complete_day/minute_"+
                    re.escape(child)+r"/"+period+r"-"+
                    re.escape(day.isoformat())+r"\.parquet",relative)
                or record.get("source_h5_gap_parquet_sha256")!=
                   source_record["private_parquet_sha256"]
                or record.get("full_merged_source_rows_and_vendor_extra_columns_readback_verified") is not True
                or record.get("ready_for_production_query") is not False):
            raise ValueError("Resumed physical minute partition provenance invalid")
        path=MODULE/relative
        if (not path.is_file() or path.is_symlink()
                or digest(path)!=record.get("unified_parquet_sha256")):
            raise ValueError("Prior unified minute partition SHA changed")
        n=record.get("unified_rows")
        cnt=record.get("source_rows")
        if (type(n) is not int or type(cnt) is not dict
                or n!=sum(cnt.values())
                or cnt.get("h5_only_complete_stockday",0)!=
                   source_record["private_parquet_rows"]):
            raise ValueError("Resumed unified minute provenance counts differ")
    return staged,u


def process(root,start,end,run_id,out,*,max_days=5,
            max_purchased_rows=30000000,max_h5_rows=2500000,
            max_unified_rows=4500000,exclude_dates=()):
    if type(run_id) is not str or RUN.fullmatch(run_id) is None:
        raise ValueError("Invalid new 12-hex minute batch id")
    dates=days_between(start,end,max_days,exclude_dates)
    if (not root.is_dir() or REPORTS.is_symlink()
            or Path(out).is_symlink()
            or Path(out).exists()
            or Path(out).resolve().parent!=REPORTS.resolve()
            or Path(out).suffix!=".json"):
        raise ValueError("Only original readonly market root and new SAFE output")
    completed=[]
    for day in dates:
        child=hashlib.sha256(
            (run_id+":"+day.isoformat()).encode("ascii")).hexdigest()[:12]
        stage_safe,unified_safe=receipt_paths(day,child)
        if stage_safe.exists() or unified_safe.exists():
            staged,unified=verified_completed(
                day,stage_safe,unified_safe,child)
            status="reused_sha_verified_completed_day"
        else:
            # The two in-memory returns are strictly aggregate metadata.
            results={}
            for period in ST.PERIODS:
                results[period]=ST.write_private_day(
                    root,day,period,child,
                    max_purchased_rows=max_purchased_rows,
                    max_h5_rows=max_h5_rows)
                print("Wrote new private H5 gap:",day.isoformat(),period,
                      "bars:",results[period]["private_parquet_rows"],
                      flush=True)
            staged={
                "format":ST.FORMAT,
                "source_day":day.isoformat(),
                "period_results":results,
                "original_market_files_modified":False,
                "production_or_private_pointer_modified":False,
                "all_private_outputs_written_not_merged":True,
            }
            write_json_new(stage_safe,staged)
            unified=UN.stage_unified(
                root,stage_safe,child,unified_safe,
                max_rows=max_unified_rows)
            status="new_physical_day_written_and_verified"
        for period in ST.PERIODS:
            record=unified["periods"][period]
            if record["unified_rows"]<record["source_rows"].get(
                    "purchased_parquet",0):
                raise ValueError("Purchased primary physical day not conserved")
        entry={
            "day":day.isoformat(),
            "status":status,
            "stage_safe_sha256":digest(stage_safe),
            "unified_safe_sha256":digest(unified_safe),
            "by_period":{
                period:{
                    "physical_unified_rows":int(
                        unified["periods"][period]["unified_rows"]),
                    "purchased_rows":int(unified["periods"][period][
                        "source_rows"].get("purchased_parquet",0)),
                    "h5_gap_rows":int(unified["periods"][period][
                        "source_rows"].get("h5_only_complete_stockday",0)),
                    "h5_quarantined_stockdays":int(sum(
                        staged["period_results"][period].get(
                            "quarantined_stockdays",{}).values())),
                    "unified_parquet_sha256":unified["periods"][period][
                        "unified_parquet_sha256"],
                } for period in ST.PERIODS},
        }
        # A weekday is NOT evidence of a trading session. A zero-bar
        # weekday must remain visibly unverified, not be misreported as
        # fully covered exchange trading history.
        entry["periods_without_source_rows"]=[
            period for period in ST.PERIODS
            if entry["by_period"][period]["physical_unified_rows"]==0
        ]
        if len(entry["periods_without_source_rows"])==len(ST.PERIODS):
            entry["status"]="zero_market_rows_not_certified_as_trading_day"
        completed.append(entry)
        print("Completed purchased-first real minute physical day:",
              day.isoformat(),"1min:",entry["by_period"]["1min"],
              "5min:",entry["by_period"]["5min"],flush=True)
    aggregate={
        "format":FMT,
        "status":"bounded_two_period_actual_minute_days_physical_parquet_completed",
        "range_start":start.isoformat(),
        "range_end":end.isoformat(),
        "batch_days":len(completed),
        "excluded_previous_completed_days":sorted(d.isoformat() for d in exclude_dates),
        "candidate_weekdays_no_market_source_rows":[
            x["day"] for x in completed
            if x["status"]=="zero_market_rows_not_certified_as_trading_day"],
        "candidate_weekdays_partial_periods":{
            x["day"]:x["periods_without_source_rows"]
            for x in completed if x["periods_without_source_rows"]
        },
        "days":completed,
        "aggregated_source_rows":{
            p:{
                k:sum(e["by_period"][p][k] for e in completed)
                for k in ("physical_unified_rows","purchased_rows",
                          "h5_gap_rows","h5_quarantined_stockdays")
            } for p in ST.PERIODS},
        "original_purchased_parquet_or_hikyuu_h5_modified":False,
        "private_or_production_active_pointer_modified":False,
        "h5_minute_timestamp_alignment_vendor_certified":False,
        "all_historical_minute_days_completed":False,
        "full_native_hikyuu_minutes_generated":False,
    }
    write_json_new(Path(out),aggregate)
    return aggregate


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--from-date",required=True)
    p.add_argument("--to-date",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--max-days",type=int,default=5)
    p.add_argument("--exclude-day",action="append",default=[],
                   help="Explicit previously verified YYYY-MM-DD date to skip; "
                        "never silently regenerate existing completed days")
    p.add_argument("--max-purchased-key-rows",type=int,default=30000000)
    p.add_argument("--max-h5-rows",type=int,default=2500000)
    p.add_argument("--max-unified-rows",type=int,default=4500000)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--write-private-minute-range",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        result=process(
            args.root,date.fromisoformat(args.from_date),
            date.fromisoformat(args.to_date),args.run_id,args.out,
            max_days=args.max_days,
            max_purchased_rows=args.max_purchased_key_rows,
            max_h5_rows=args.max_h5_rows,
            max_unified_rows=args.max_unified_rows,
            exclude_dates=tuple(date.fromisoformat(x) for x in args.exclude_day))
        print("PASS: physical purchased-first 1min+5min Parquet range",
              result["batch_days"],"days")
        print("SAFE:",args.out)
        print("Original vendors unchanged; H5 1/5min vendor timestamp alignment remains candidate")
    except Exception as ex:
        last=traceback.extract_tb(ex.__traceback__)[-1]
        p.error("Private purchased-first minute range failed ["+
                type(ex).__name__+"/"+last.name+":"+str(last.lineno)+
                "]; original sources unchanged; earlier completed daily receipts reusable")


if __name__=="__main__":
    main()
