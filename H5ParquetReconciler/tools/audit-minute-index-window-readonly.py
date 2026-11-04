#!/usr/bin/env python3
"""Batch EXACT 1min/5min key audits from ONE already-built purchased key index.

The purchased Parquet is NEVER scanned or decoded again: its source-file
metadata is rechecked, the purchased time keys are reconstructed from the
read-only private SQLite bitmaps, and only H5 minute candidates are compared.

Only intended for 1..31 calendar days per run and not for production
activation. No market files, indexes, ledgers, or reports are written.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load(tag,name):
    spec=importlib.util.spec_from_file_location(tag,HERE/name)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


Q=load("batch_exact_minute_key_preview",
       "preview-minute-exact-key-diff-readonly.py")
I=Q.I
N=Q.N
FIELDS=(
    "purchased_a_share_date_key_count",
    "h5_date_native_rows_examined",
    "overlapping_exact_keys",
    "h5_only_keys_on_full_purchased_absence_days",
    "h5_only_candidate_keys_on_partial_purchased_stockdays",
    "purchased_only_keys_on_native_complete_H5_stockdays",
    "purchased_only_0930_keys_on_complete_H5_stockdays",
    "purchased_only_other_time_keys_on_complete_H5_stockdays",
    "h5_only_complete_stockdays_without_purchased",
    "partial_purchased_stockdays_with_h5_only_candidate_keys",
)


def audit(root,index,first,last,*,include_weekends=False,max_days=31,
          progress=None):
    root=Path(root)
    index=Path(index)
    days=I.make_days(first,last)
    if len(days)>max_days:
        raise ValueError("Bound index audit day count exceeded")
    root,start=N.validate(root,days[0],"000000000000")
    if not days or days[-1]>date(2026,10,13):
        raise ValueError("Audit exceeds verified market source endpoint")
    before=N.source_snapshot(root,days[0].year)
    days_report=[]
    totals={period:Counter() for period in N.PERIODS}
    quarantine={period:Counter() for period in N.PERIODS}
    audited=0
    for day in days:
        if not include_weekends and day.weekday()>=5:
            continue
        audit_row={"day":day.isoformat(),"periods":{}}
        for period in N.PERIODS:
            entry=Q.inspect_exact_period(root,day,period,key_index=index)
            # Every bought source-key query must explicitly use the
            # private index; otherwise this tool would silently regress
            # into the expensive old per-date Parquet scan.
            used=entry["purchased_date_key_scan"]
            if (used.get("index_used") is not True or
                    used.get("no_purchased_parquet_scanned_during_lookup") is not True):
                raise RuntimeError("Purchased source index unexpectedly bypassed")
            audit_row["periods"][period]={
                k:int(entry[k]) for k in FIELDS
            }
            audit_row["periods"][period]["source_purchased_stockdays"]=int(
                entry["source_purchased_stockdays"])
            audit_row["periods"][period]["missing_h5_market_files"]=list(
                entry["missing_h5_market_files"])
            audit_row["periods"][period]["quarantined_h5_stockdays_by_reason"]=dict(
                entry["quarantined_h5_stockdays_by_reason"])
            totals[period].update({k:int(entry[k]) for k in FIELDS})
            quarantine[period].update(
                entry["quarantined_h5_stockdays_by_reason"])
        audit_row["no_purchased_or_verified_complete_h5_stockday_rows"]=(
            all(not audit_row["periods"][period][
                "purchased_a_share_date_key_count"] and
                not audit_row["periods"][period][
                    "h5_date_native_rows_examined"] for period in N.PERIODS))
        if audit_row["no_purchased_or_verified_complete_h5_stockday_rows"]:
            audit_row["source_coverage_status"]="NO_SOURCE_EVIDENCE_NOT_EXCHANGE_CLOSED"
        else:
            audit_row["source_coverage_status"]="SOME_SOURCE_EVIDENCE_NOT_FULLY_CERTIFIED"
        days_report.append(audit_row)
        audited+=1
        if progress is not None:
            progress(day,audit_row,audited)
        print("READONLY "+day.isoformat()+
              " 1min H5_full_gap="+str(audit_row["periods"]["1min"][
                  "h5_only_keys_on_full_purchased_absence_days"])+
              " partial="+str(audit_row["periods"]["1min"][
                  "h5_only_candidate_keys_on_partial_purchased_stockdays"])+
              " | 5min full="+str(audit_row["periods"]["5min"][
                  "h5_only_keys_on_full_purchased_absence_days"])+
              " partial="+str(audit_row["periods"]["5min"][
                  "h5_only_candidate_keys_on_partial_purchased_stockdays"])+
              " | market_files_written=0",flush=True)
    if not audited:
        raise ValueError("Requested index window contains no eligible audit dates")
    after=N.source_snapshot(root,days[0].year)
    if before!=after:
        raise RuntimeError("Original purchased/H5 source changed during indexed audit")
    summary={
        period:{
            **{k:int(totals[period][k]) for k in FIELDS},
            "quarantined_h5_stockdays_by_reason":dict(
                sorted(quarantine[period].items())),
        }
        for period in N.PERIODS
    }
    return {
        "format":"AStockDataTools bought-primary reusable index H5 exact-minute batch audit v1",
        "status":"read_only_existing_index_multi_day_candidate_diff_not_activated",
        "from_day":days[0].isoformat(),
        "through_day":days[-1].isoformat(),
        "candidate_weekdays_only":not include_weekends,
        "audited_calendar_dates":audited,
        "days":days_report,
        "summaries":summary,
        "source_metadata_fingerprint":before,
        "original_source_metadata_unchanged_during_audit":True,
        "source_fingerprint_is_content_sha":False,
        "existing_purchased_key_index_reused":True,
        "original_purchased_parquet_opened_for_bars":False,
        "purchased_ohlcva_rows_rematerialized":0,
        "new_parquet_or_h5_market_files_written":False,
        "new_market_gap_keys_accepted":0,
        "ready_for_production_query":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--index",type=Path,required=True)
    p.add_argument("--from-day",required=True)
    p.add_argument("--through-day",required=True)
    p.add_argument("--include-weekends",action="store_true")
    args=p.parse_args(argv)
    result=audit(args.root,args.index,args.from_day,args.through_day,
                 include_weekends=args.include_weekends)
    print("===== Aggregate exact-minute key differences (read only) =====")
    print(json.dumps({
        "status":result["status"],
        "from_day":result["from_day"],
        "through_day":result["through_day"],
        "audited_calendar_dates":result["audited_calendar_dates"],
        "summaries":result["summaries"],
        "purchased_ohlcva_rows_rematerialized":0,
        "new_parquet_or_h5_market_files_written":False,
        "new_market_gap_keys_accepted":0,
        "source_fingerprint_is_content_sha":False,
    },sort_keys=True,indent=2,ensure_ascii=False))


if __name__=="__main__":
    main()
