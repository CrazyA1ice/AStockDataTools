#!/usr/bin/env python3
"""Conservative independent-month real daily Parquet/raw Hikyuu H5 hypotheses.

Only SH600000/SZ000001 on 2025-09-30 and 2026-08-24: 4 stock-days.
Reuses bounded per-month/day real Parquet reader, original raw H5 day reader,
and the same fixed candidate factor grid. NO production writes or native
C++ recheck on the two new dates. Missing data fail closed, never substituted.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

HELD=load("prior_real_daily_holdout_gate",
          "probe-real-h5-parquet-heldout-day-factors-readonly.py")
PAIR=HELD.PAIR
DAY=HELD.DAY
AUDIT=HELD.AUDIT

FORMAT="AStockDataTools real H5 Parquet two-month cross-year daily candidate factors v1"
SAMPLES=(("2025-09-30","day/2025-09.parquet"),
         ("2026-08-24","day/2026-08.parquet"))
MAX_SCANNED_TOTAL=300000
MAX_GROUPS_TOTAL=64
MIN_DISCOVERY_REFERENCE=6


def verified_sources(raw_safe,native_safe,heldout_safe):
    chain=HELD.verify_chain(raw_safe,native_safe)
    path=AUDIT._path(heldout_safe,True)
    data=path.read_bytes()
    if not 0<len(data)<=200000:
        raise ValueError("Cross-month prerequisite heldout SAFE too large or empty")
    try:
        previous=json.loads(data)
    except (ValueError,UnicodeError):
        raise ValueError("Cross-month prerequisite heldout SAFE invalid JSON") from None
    agg=previous.get("aggregate") if type(previous) is dict else None
    days=previous.get("per_holdout_date_diagnostic") if type(previous) is dict else None
    if (type(previous) is not dict or previous.get("format")!=HELD.FORMAT
            or previous.get("holdout_days")!=list(HELD.DAYS)
            or previous.get("prior_discovery_date_excluded")!="2026-09-30"
            or previous.get("observations_independent_of_discovery_date") is not True
            or previous.get("previous_SAFE_sha256")!=chain
            or previous.get("h5_raw_day_records_read")!=4
            or previous.get("original_parquet_or_h5_modified") is not False
            or previous.get("raw_ohlcva_or_h5_integer_values_exported") is not False
            or previous.get("native_decoder_consistency_not_retested_on_heldout_dates") is not True
            or previous.get("holdout_native_cpp_kdata_executed") is not False
            or previous.get("vendor_volume_physical_unit_certified") is not False
            or previous.get("vendor_amount_physical_unit_certified") is not False
            or previous.get("sample_factor_generalization_certified") is not False
            or previous.get("licensed_parquet_to_h5_mapping_certified") is not False
            or previous.get("ready_for_full_market_mirror") is not False
            or type(agg) is not dict
            or agg.get("heldout_stock_days_compared")!=4
            or agg.get("volume_candidate_factor100_matched")!=4
            or agg.get("amount_candidate_factor1000_matched")!=4
            or agg.get("nonzero_positive_pairs")!={"volume":4,"amount":4}
            or agg.get("zero_pairs")!={"volume":0,"amount":0}
            or agg.get("price_fields_within_tolerance")!={
                "open":4,"high":4,"low":4,"close":4}
            or type(days) is not dict
            or set(days)!=set(HELD.DAYS)
            or any(days[d].get("stock_days_compared")!=2
                   or days[d].get("candidate_volume_raw_h5_times100_matched")!=2
                   or days[d].get("candidate_amount_raw_h5_times1000_matched")!=2
                   or days[d].get("quantity_positive_nonzero_pairs")!={
                       "volume":2,"amount":2}
                   for d in HELD.DAYS)):
        raise ValueError("Cross-month prerequisite heldout SAFE not qualified")
    return {**chain,"same_month_heldout":hashlib.sha256(data).hexdigest()}


def check_calendar():
    if (len(SAMPLES)!=2
            or SAMPLES!=(("2025-09-30","day/2025-09.parquet"),
                          ("2026-08-24","day/2026-08.parquet"))
            or any(day in HELD.DAYS or day==PAIR.DAY_DATE
                   for day,_ in SAMPLES)):
        raise ValueError("Cross-year selected sample dates or months changed")


def compare(days):
    if type(days) is not dict or set(days)!={d for d,_ in SAMPLES}:
        raise ValueError("Cross-year sample identities cannot change")
    results={}
    for name,_ in SAMPLES:
        entry=days[name]
        if type(entry) is not dict or set(entry)!={"parquet","h5"}:
            raise ValueError("Cross-year paired source fields invalid")
        results[name]=HELD.aggregated_day(entry["parquet"],entry["h5"])
    factor_names=("volume","amount")
    total={
        "stock_days_compared":4,
        "per_field_price_tolerance_matches":{
            field:sum(results[day]["price_h5_raw_div1000_within_0p005"][field]
                      for day,_ in SAMPLES)
            for field in ("open","high","low","close")},
        "volume_candidate_raw_h5_times100_matched":sum(
            results[day]["candidate_volume_raw_h5_times100_matched"]
            for day,_ in SAMPLES),
        "amount_candidate_raw_h5_times1000_matched":sum(
            results[day]["candidate_amount_raw_h5_times1000_matched"]
            for day,_ in SAMPLES),
        "nonzero_positive_pairs":{
            field:sum(results[day]["quantity_positive_nonzero_pairs"][field]
                      for day,_ in SAMPLES)
            for field in factor_names},
        "both_zero_pairs":{
            field:sum(results[day]["quantity_both_zero_pairs"][field]
                      for day,_ in SAMPLES)
            for field in factor_names},
        "one_zero_pairs":{
            field:sum(results[day]["quantity_one_zero_pairs"][field]
                      for day,_ in SAMPLES)
            for field in factor_names},
    }
    if any(sum(total[k][field] for k in (
            "nonzero_positive_pairs","both_zero_pairs","one_zero_pairs"))!=4
            for field in factor_names):
        raise ValueError("Cross-year quantity counts fail conservation")
    return results,total


def run(parquet_root,h5_root,raw_safe,native_safe,heldout_safe,out):
    target=AUDIT._path(out,False)
    check_calendar()
    prior=verified_sources(raw_safe,native_safe,heldout_safe)
    month_files={day:DAY.FOOTER.selected_file(
        parquet_root,path,"day") for day,path in SAMPLES}
    if len({p.resolve() for p in month_files.values()})!=len(SAMPLES):
        raise ValueError("Cross-year samples must be different Parquet monthly sources")
    file_stamps={day:DAY.FOOTER.footer_guard(p)
                 for day,p in month_files.items()}
    h5paths={symbol:PAIR._plain_h5_path(h5_root,symbol)
             for symbol in PAIR.SYMBOLS}
    h5stamps={symbol:(p.stat().st_size,p.stat().st_mtime_ns)
              for symbol,p in h5paths.items()}
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    import h5py
    import numpy as np
    scanned=0
    groups=0
    paired={}
    try:
        for day,path in month_files.items():
            vals,n,g=DAY._read_bounded_daily(path,day,pa,pq,pc)
            scanned+=n
            groups+=g
            if scanned>MAX_SCANNED_TOTAL or groups>MAX_GROUPS_TOTAL:
                raise ValueError("Cross-year fixed source scan budget exceeded")
            h5={s:PAIR._read_single_h5(h5_root,s,day,h5py,np)
                for s in PAIR.SYMBOLS}
            paired[day]={"parquet":vals,"h5":h5}
        breakdown,aggregate=compare(paired)
    finally:
        if any(DAY.FOOTER.footer_guard(p)!=file_stamps[day]
               for day,p in month_files.items()):
            raise ValueError("Real Parquet file changed during cross-year analysis")
        if any((p.stat().st_size,p.stat().st_mtime_ns)!=h5stamps[s]
               for s,p in h5paths.items()):
            raise ValueError("Real H5 file changed during cross-year analysis")
    safe={
        "format":FORMAT,
        "fixed_crossyear_samples":[day for day,_ in SAMPLES],
        "independent_of_prior_2026_09_discovery_and_heldout_days":True,
        "symbols_sampled_count":2,
        "source_period":"day",
        "source_parquet_month_files_read":2,
        "source_parquet_total_rows_scanned":scanned,
        "source_parquet_row_groups_scanned":groups,
        "raw_h5_day_records_read":4,
        "native_cpp_h5_decoding_on_crossyear_samples_executed":False,
        "previous_native_real_decode_was_only_2026_09_30":True,
        "tolerance_amount_volume_ratio_relative":"0.00001",
        "tolerance_price_absolute":"0.005",
        "parquet_float_approximately_equals_raw_h5_integer_times_factor":True,
        "per_sample_day":breakdown,
        "crossyear_aggregate":aggregate,
        "previous_safe_sha256":prior,
        "source_files_stat_or_footer_before_after_unchanged":True,
        "entire_market_source_files_sha256_checked":False,
        "source_files_modified":False,
        "market_sqlite_or_h5_writes_performed":False,
        "raw_ohlcva_or_native_integer_values_in_report":False,
        "raw_market_paths_or_individual_source_timestamps_in_report":False,
        "vendor_amount_physical_units_certified":False,
        "vendor_volume_physical_units_certified":False,
        "source_timestamp_semantics_certified":False,
        "universal_factor_across_time_or_periods_certified":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
    }
    with target.open("x",encoding="utf-8") as stream:
        json.dump(safe,stream,indent=2,sort_keys=True,ensure_ascii=False)
        stream.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parquet-root",type=Path,required=True)
    p.add_argument("--h5-root",type=Path,required=True)
    p.add_argument("--prior-raw-safe",type=Path,required=True)
    p.add_argument("--prior-native-safe",type=Path,required=True)
    p.add_argument("--prior-heldout-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-crossyear-days",required=True,action="store_true")
    args=p.parse_args(argv)
    try:
        result=run(args.parquet_root,args.h5_root,args.prior_raw_safe,
                   args.prior_native_safe,args.prior_heldout_safe,args.out)
    except (ValueError,TypeError,KeyError,OSError,ImportError,
            OverflowError,json.JSONDecodeError):
        p.error("Cross-year sampled real H5/Parquet verification refused; sources or SAFE incomplete")
    stats=result["crossyear_aggregate"]
    print("SAFE cross-year daily evidence:",args.out)
    print("Cross-year stock-days:",stats["stock_days_compared"])
    print("Volume raw H5 x100 matches:",stats["volume_candidate_raw_h5_times100_matched"])
    print("Amount raw H5 x1000 matches:",stats["amount_candidate_raw_h5_times1000_matched"])
    print("Original sources modified: NO")
    print("Vendor units or production conversion certified: NO")


if __name__=="__main__":
    main()
