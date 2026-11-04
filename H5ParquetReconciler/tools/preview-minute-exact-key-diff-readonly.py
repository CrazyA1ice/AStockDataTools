#!/usr/bin/env python3
"""Read-only exact-minute key coverage, no purchased/OHLCVA rematerialization.

Compare both 1min/5min source keys on ONE explicitly selected source day.
The output contains only aggregate counts, never individual stock IDs,
price, raw H5 rows, market keys or source path names.

This is a DIAGNOSTIC, not proof that a missing H5 bar is a genuine
exchange trade or is safe for automatic production backfill. It does
not write, stage, or activate any Parquet/H5 and never resumes the
retired full-purchased-minute GUI worker. A future year-key index is
needed before scanning many dates.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections import Counter
from datetime import datetime,timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load(tag,filename):
    spec=importlib.util.spec_from_file_location(tag,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


N=load("minute_exact_key_existing_gap_preview",
       "run-minute-h5-gap-only-overlay.py")
ST=N.ST
I=load("minute_exact_key_optional_purchased_sqlite_index",
       "build-minute-purchased-key-index.py")


def normalized_native_keys(day,period):
    """Map native H5 end labels to normalized purchased epoch-ms keys."""
    offset=0 if period=="1min" else 5
    return {
        stamp:int((datetime.strptime(str(stamp),"%Y%m%d%H%M")
                   .replace(tzinfo=ST.CORE.UTC8)
                   -timedelta(minutes=offset)).timestamp()*1000)
        for stamp in ST.session_stamps(day,period)
    }


def inspect_exact_period(root,day,period,*,max_purchased_rows=6000000,
                         max_native_rows=2500000,key_index=None):
    """Single date-only purchased scan + bounded H5 native datetime probes."""
    import h5py

    if key_index is None:
        bought,scan,bought_keys=ST.purchased_stockdays(
            root,period,day,max_rows=max_purchased_rows,include_time_keys=True)
        scan=dict(scan, index_used=False)
    else:
        bought_keys,scan=I.query_index(key_index,root,period,day)
        bought=set(bought_keys)
    normalized=normalized_native_keys(day,period)
    lower=int(day.strftime("%Y%m%d"))*10000
    upper=int((day+timedelta(days=1)).strftime("%Y%m%d"))*10000
    purchase_0930_key=I.day_epoch_ms(day)+(9*60+30)*60000
    found_markets=0
    missing_markets=[]
    h5_native_rows=0
    totals=Counter()
    excluded=Counter()
    for market in ("sh","sz","bj"):
        file=root/"HikyuuData"/f"{market}_{period}.h5"
        if not file.exists():
            missing_markets.append(market)
            continue
        if file.is_symlink() or not file.is_file():
            raise ValueError("Unsafe original H5 path")
        found_markets+=1
        with h5py.File(file,"r") as h5:
            group=h5.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("Original H5 market data group missing")
            for symbol in group:
                if (not re.fullmatch(market.upper()+r"\d{6}",symbol)
                        or not ST.CORE.is_a_share_candidate(symbol,day.year)):
                    continue
                ds=group[symbol]
                if (not isinstance(ds,h5py.Dataset)
                        or not set(ST.RAW_FIELDS).issubset(ds.dtype.names or ())):
                    excluded["invalid_native_h5_schema"]+=1
                    continue
                lo,hi=ST.CORE.h5_key_slice(ds,lower,upper)
                if lo==hi:
                    continue
                h5_native_rows+=hi-lo
                if h5_native_rows>max_native_rows:
                    raise ValueError("Exact H5 native date-row budget exceeded")
                native=ds[lo:hi]
                stamps=[int(r["datetime"]) for r in native]
                status=ST.completeness(stamps,day,period)
                if status!="complete":
                    excluded[status]+=1
                    continue
                # Only code/time keys are compared here. No assertion about
                # H5 OHLCVA, vendor units, suspension or listing validity.
                h5_times={normalized[x] for x in stamps}
                if len(h5_times)!=len(stamps):
                    excluded["duplicate_normalized_h5_keys"]+=1
                    continue
                purchased=bought_keys.get(symbol)
                if purchased is None:
                    totals["h5_only_complete_stockdays_without_purchased"]+=1
                    totals["h5_only_keys_on_full_purchased_absence_days"]+=len(h5_times)
                    continue
                totals["overlapping_stockdays_with_native_complete_H5"]+=1
                both=purchased & h5_times
                missing=h5_times-purchased
                bought_only=purchased-h5_times
                totals["overlapping_exact_keys"]+=len(both)
                totals["h5_only_candidate_keys_on_partial_purchased_stockdays"]+=len(missing)
                totals["purchased_only_keys_on_native_complete_H5_stockdays"]+=len(bought_only)
                # A purchased-only minute often reflects a distinct vendor
                # timestamp label (e.g. 09:30 vs native 1min 09:31 END).
                # Check the actual normalized timestamp, never assume it.
                at_0930=int(purchase_0930_key in bought_only)
                totals["purchased_only_0930_keys_on_complete_H5_stockdays"]+=at_0930
                totals["purchased_only_other_time_keys_on_complete_H5_stockdays"]+=(
                    len(bought_only)-at_0930)
                if missing:
                    totals["partial_purchased_stockdays_with_h5_only_candidate_keys"]+=1
                if bought_only:
                    totals["purchased_stockdays_with_keys_not_in_H5"]+=1
    if not found_markets:
        raise ValueError("No original H5 minute source files found")
    if (totals["purchased_only_0930_keys_on_complete_H5_stockdays"]+
        totals["purchased_only_other_time_keys_on_complete_H5_stockdays"]!=
            totals["purchased_only_keys_on_native_complete_H5_stockdays"]):
        raise ValueError("Purchased-only exact minute time bucket conservation failed")
    return {
        "period":period,
        "source_purchased_stockdays":len(bought),
        "purchased_date_key_scan":scan,
        "purchased_a_share_date_key_count":sum(map(len,bought_keys.values())),
        "h5_date_native_rows_examined":h5_native_rows,
        "source_h5_stocks_with_complete_native_time_grid":
            (totals["overlapping_stockdays_with_native_complete_H5"]+
             totals["h5_only_complete_stockdays_without_purchased"]),
        "overlapping_stockdays_with_native_complete_H5":
            totals["overlapping_stockdays_with_native_complete_H5"],
        "overlapping_exact_keys":totals["overlapping_exact_keys"],
        "h5_only_complete_stockdays_without_purchased":
            totals["h5_only_complete_stockdays_without_purchased"],
        "h5_only_keys_on_full_purchased_absence_days":
            totals["h5_only_keys_on_full_purchased_absence_days"],
        "partial_purchased_stockdays_with_h5_only_candidate_keys":
            totals["partial_purchased_stockdays_with_h5_only_candidate_keys"],
        "h5_only_candidate_keys_on_partial_purchased_stockdays":
            totals["h5_only_candidate_keys_on_partial_purchased_stockdays"],
        "purchased_stockdays_with_keys_not_in_H5":
            totals["purchased_stockdays_with_keys_not_in_H5"],
        "purchased_only_keys_on_native_complete_H5_stockdays":
            totals["purchased_only_keys_on_native_complete_H5_stockdays"],
        "purchased_only_0930_keys_on_complete_H5_stockdays":
            totals["purchased_only_0930_keys_on_complete_H5_stockdays"],
        "purchased_only_other_time_keys_on_complete_H5_stockdays":
            totals["purchased_only_other_time_keys_on_complete_H5_stockdays"],
        "quarantined_h5_stockdays_by_reason":dict(sorted(excluded.items())),
        "missing_h5_market_files":missing_markets,
        "purchased_bars_rematerialized":0,
        "candidate_keys_automatically_accepted":0,
        "h5_value_units_and_trading_truth_verified":False,
        "ready_for_production_query":False,
    }


def preview(root,day,*,key_index=None):
    root,day=N.validate(root,day,"000000000000")
    before=N.source_snapshot(root,day.year)
    outputs={}
    for period in N.PERIODS:
        outputs[period]=inspect_exact_period(
            root,day,period,key_index=key_index)
        print("READONLY "+period+" exact-key probe: H5-only full-stockday="+
              str(outputs[period]["h5_only_keys_on_full_purchased_absence_days"])+
              " partial-stockday candidate keys="+
              str(outputs[period]["h5_only_candidate_keys_on_partial_purchased_stockdays"])+
              " accepted keys=0, market files written=0",flush=True)
    after=N.source_snapshot(root,day.year)
    if before!=after:
        raise RuntimeError("Original market source metadata changed during exact-key preview")
    return {
        "format":"AStockDataTools exact 1min/5min purchased-vs-H5 read-only minute-key candidate audit v1",
        "status":"single_day_exact_keys_readonly_candidate_only_not_authorized_gap_write",
        "day":day.isoformat(),
        "periods":outputs,
        "source_fingerprint":before,
        "source_fingerprint_is_content_sha":False,
        "source_metadata_unchanged_during_read":True,
        "purchased_bars_rematerialized":0,
        "new_market_parquet_or_h5_files_written":False,
        "h5_only_candidate_keys_not_automatically_accepted":True,
        "original_purchased_parquet_or_h5_modified":False,
        "ready_for_production_query":False,
        "reusable_key_index_used":key_index is not None,
        "reusable_key_index_path":str(key_index) if key_index else None,
        "reusable_key_index_built_during_preview":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",required=True,type=Path)
    parser.add_argument("--day",required=True)
    parser.add_argument("--key-index",type=Path,default=None,
                        help="Previously completed private purchased key SQLite index")
    args=parser.parse_args(argv)
    result=preview(args.root,args.day,key_index=args.key_index)
    print(json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False))


if __name__=="__main__":
    main()
