#!/usr/bin/env python3
"""Count actually written 1min/5min purchased-first Parquet stock bars by date.

Uses the SAME previously audited per-day private Parquet SHA verification path
as the real Windows minute GUI. It does not read original H5/vendor Parquet,
write market records, or count repeated receipts twice. This is NOT a
source-wide minute completeness or Hikyuu mirror certification.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
from datetime import date
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
REPORTS=MODULE/"reports"
_PATTERN=re.compile(r"minute-batch-unified-(\d{8})-([0-9a-f]{12})\.json")

def load_worker():
    file=MODULE/"tools"/"minute-private-parquet-worker.py"
    spec=importlib.util.spec_from_file_location("minute_progress_existing_safe_gate",file)
    worker=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker

def valid_days():
    days=set()
    for path in REPORTS.glob("minute-batch-unified-*.json"):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Unsafe daily SAFE path")
        m=_PATTERN.fullmatch(path.name)
        if m is None:
            raise ValueError("Unrecognized minute daily SAFE name")
        day=date.fromisoformat(f"{m[1][0:4]}-{m[1][4:6]}-{m[1][6:8]}")
        if not 1990<=day.year<=2100:
            raise ValueError("Invalid dated minute receipt")
        days.add(day.isoformat())
    corrected=REPORTS/"real-unified-minute-parquet-20261013-end-key-11127c8d60ba.json"
    if corrected.is_file() and not corrected.is_symlink():
        days.add("2026-10-13")
    return sorted(days)

def build(worker):
    if REPORTS.is_symlink() or not REPORTS.is_dir():
        raise ValueError("Missing or unsafe module reports folder")
    dates=valid_days()
    if not dates:
        raise ValueError("No daily unified minute receipts found: cannot certify progress")
    totals={"1min":0,"5min":0}
    by_date={}
    ignored=[]
    for day in dates:
        # Reads immutable per-day receipts and rehashes real local physical
        # Parquet files. Conflicting same-date receipts fail CLOSED.
        obj=worker.verified_existing_batch(day)
        if obj is None:
            ignored.append(day)
            continue
        counts={}
        for period in ("1min","5min"):
            n=obj[period]
            if type(n) is not int or n<0:
                raise ValueError("Invalid certified period row count")
            totals[period]+=n
            counts[period]=n
        if sum(counts.values())==0:
            ignored.append(day)
            continue
        by_date[day]=counts
    if not by_date:
        raise ValueError("No verified nonempty market day")
    return {
        "format":"AStockDataTools SHA-verified unique daily 1min/5min private physical Parquet progress v1",
        "status":"unique_minute_dates_existing_private_physical_parquet_sha_rechecked_not_full_history",
        "unique_nonempty_date_count":len(by_date),
        "first_verified_day":min(by_date),
        "last_verified_day":max(by_date),
        "verified_physical_rows_by_period":totals,
        "verified_physical_rows_total":sum(totals.values()),
        "verified_unique_date_rows":by_date,
        "zero_market_source_days_not_certified":ignored,
        "dates_with_conflicting_reports_silently_accepted":False,
        "original_market_files_opened":False,
        "new_market_parquet_or_h5_written":False,
        "all_historical_minute_days_completed":False,
        "ready_for_production_query":False,
        "hikyuu_mirror_complete":False,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--verify-existing-sha-only",action="store_true",required=True)
    args=p.parse_args(argv)
    out=args.out
    if (out.suffix!=".json" or out.is_symlink() or out.exists()
            or out.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Output must be a fresh private module reports/*.json file")
    result=build(load_worker())
    # Do not include licensed OHLCVA / code, only safe per-day counts.
    with out.open("x",encoding="utf-8") as f:
        json.dump(result,f,ensure_ascii=False,indent=2,sort_keys=True)
        f.write("\n")
    print("Verified unique nonempty days:",result["unique_nonempty_date_count"])
    print("1min physical rows:",result["verified_physical_rows_by_period"]["1min"])
    print("5min physical rows:",result["verified_physical_rows_by_period"]["5min"])
    print("Total verified unique physical rows:",result["verified_physical_rows_total"])
    print("No source market writes and NOT a complete-history certification. SAFE:",out)

if __name__=="__main__":
    main()
