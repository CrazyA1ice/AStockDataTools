#!/usr/bin/env python3
"""Finish accepted purchased minute 2026 September H5 dates in four safe waves.

First real persistent minute H5 2026-09-23 was already verified. 2026-09-24
is inside the SHA-approved H5 base; 9/28..30 are in the reused earlier
6,427,013-row native H5 mirror. This script advances ONLY confirmed source
windows 2026-09-01..22, using a single six-file private H5 working library.
No original H5/Parquet writes, no 2026-09-25 holiday or 10/14+ guessing.

Each window uses a bounded 12m-row purchased-only SQLite staging database and
a durable per-stock H5 undo/redo journal; interrupted runs resume only the
currently incomplete wave. Previously completed waves are skipped WITHOUT
rechecking mutable in-progress six-file SHA (which would incorrectly block
a legitimate recovery from a subsequent interrupted wave).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent

def load():
    spec=importlib.util.spec_from_file_location(
        "resumable_verified_sep_purchased_minute_wave",
        HERE/"resume-purchased-minute-parquet-into-private-native-h5.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

R=load()

# Observed already-purchased minute windows from prior actual Windows
# 2026 September physical purchased+H5 unified-Parquet receipts. They avoid
# weekends and source-empty candidate dates; not an official trade calendar.
WAVES=(
    ("2026-09-21","2026-09-22"),
    ("2026-09-14","2026-09-18"),
    ("2026-09-07","2026-09-11"),
    ("2026-09-01","2026-09-04"),
)
MARK="PASS_2026_SEPTEMBER_PURCHASED_1MIN_5MIN_NATIVE_H5_RESUMABLE_WAVES"

def validate_windows():
    """No accidental overlap with September 23, 24 or four prior native days."""
    from datetime import timedelta
    days=set()
    for first,last in WAVES:
        start,end=R.batch_dates(first,last)
        if (end-start).days>6:
            raise ValueError("September H5 wave exceeds bounded source dates")
        date_value=start
        while date_value<=end:
            if date_value.weekday()>=5 or str(date_value) in days:
                raise ValueError("Weekends/overlaps not allowed in explicit prior purchased waves")
            days.add(str(date_value))
            date_value+=timedelta(days=1)
    if (len(days)!=16 or min(days)!="2026-09-01"
            or max(days)!="2026-09-22"
            or any(d in days for d in
                   ("2026-09-23","2026-09-24","2026-09-25",
                    "2026-09-28","2026-09-29","2026-09-30"))):
        raise ValueError("Unexpected 2026 September purchased source wave selection")
    return len(days)

def validate_done(first,last):
    path=R.LIVE/"batches"/("batch_"+first+"_"+last)/"done.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing committed physical H5 actual window SAFE")
    doc=json.loads(path.read_bytes())
    source=doc.get("purchased_parquet_rows_processed_by_period")
    if (doc.get("status")!=R.STATUS
            or doc.get("dataset_sha256")!=R.SOURCE_SHA
            or doc.get("window")!=[first,last]
            or doc.get("all_stock_swaps_completed_and_journal_committed") is not True
            or doc.get("original_purchased_parquet_or_hikyuu_H5_modified") is not False
            or doc.get("original_markets_never_opened_in_write_mode") is not True
            or doc.get("production_H5_activated") is not False
            or doc.get("numeric_unit_mapping_vendor_certified") is not False
            or doc.get("complete_2011_2026_minute_history") is not False
            or type(source) is not dict
            or any(type(source.get(p)) is not int or source[p]<1
                   or source[p]>12000000 for p in R.PERIODS)
            or set(doc.get("full_private_six_file_H5_sha256",{}))!=set(R.H5_NAMES)):
        raise ValueError("Unverified purchased-minute native H5 transaction receipt")
    return source

def is_committed(first,last):
    state=R.LIVE/"initialized.json"
    if not state.is_file() or state.is_symlink():
        return False
    doc=json.loads(state.read_bytes())
    return [first,last] in doc.get("completed_windows",[])

def run_all(root,manifest,*,max_waves=4):
    if max_waves not in (1,2,3,4):
        raise ValueError("Only one to four fixed real September windows allowed")
    validated_days=validate_windows()
    totals={p:0 for p in R.PERIODS}
    completed=[]
    with R.exclusive_working_h5_lock():
        for first,last in WAVES[:max_waves]:
            if is_committed(first,last):
                # Intentionally skip calling R.run for earlier completed waves.
                # A later incomplete wave may have partially changed H5 bytes;
                # the journal for that later wave is responsible for recovery.
                source=validate_done(first,last)
                print("ALREADY_COMMITTED_PRIVATE_MINUTE_H5_WINDOW="+
                      first+".."+last,flush=True)
            else:
                print("REAL_PARQUET_TO_PRIVATE_H5_WINDOW_START="+
                      first+".."+last,flush=True)
                R.run(root,manifest,first,last)
                if not is_committed(first,last):
                    raise ValueError("Window commit did not publish persistent private state")
                source=validate_done(first,last)
                print("REAL_PARQUET_TO_PRIVATE_H5_WINDOW_PASS="+
                      first+".."+last,flush=True)
            for period in R.PERIODS:
                totals[period]+=source[period]
            completed.append([first,last])
        # The final live six-file H5 bytes must still equal the most
        # recently committed SHA set. This is especially important when all
        # windows were skipped on a subsequent idempotent invocation.
        if len(completed)==len(WAVES):
            state=R.LIVE/"initialized.json"
            if state.is_symlink() or not state.is_file():
                raise ValueError("Missing permanent six-H5 completed state")
            doc=json.loads(state.read_bytes())
            expected=doc.get("latest_h5_files_sha256")
            if type(expected) is not dict or set(expected)!=set(R.H5_NAMES):
                raise ValueError("Incomplete latest six-file H5 provenance")
            for filename,digest in expected.items():
                if (type(digest) is not str
                        or len(digest)!=64
                        or R.sha(R.LIVE/filename)!=digest):
                    raise ValueError("Final copied private H5 bytes differ from committed SHA")
            print("ALL_SIX_CONTINUOUS_H5_FILES_MATCH_LATEST_COMMIT_SHA=TRUE",
                  flush=True)
        # No claim of all-September completion unless four waves and
        # the already accepted 9/23, 9/24, 9/28..30 are also accounted for.
        result={
            "status":"accepted_purchased_2026_september_minute_H5_rolling_windows",
            "window_count":len(completed),
            "purchased_source_days_in_full_explicit_plan":validated_days,
            "completed_or_reused_windows":completed,
            "purchased_source_rows_processed_in_these_windows":totals,
            "private_h5_workspace":str(R.LIVE),
            "previous_sep23_24_and_sep28_30_not_rebuilt":True,
            "historical_minute_2011_2026_whole_coverage_certified":False,
            "original_purchased_or_hikyuu_market_files_modified":False,
            "native_minute_units_vendor_certified":False,
            "production_h5_activated":False,
        }
        print(MARK+"="+json.dumps(result,sort_keys=True,
                                  separators=(",",":")),flush=True)
        return result

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--max-waves",type=int,default=4)
    parser.add_argument("--write-verified-september-purchased-private-h5",action="store_true",
                        required=True)
    args=parser.parse_args(argv)
    try:
        run_all(args.root,args.manifest,max_waves=args.max_waves)
    except (OSError,ValueError,TypeError,KeyError,ImportError) as exc:
        parser.error("Continuous September minute native H5 real purchased source "
                     "not accepted: "+type(exc).__name__+": "+str(exc))

if __name__=="__main__":
    main()
