#!/usr/bin/env python3
"""Two previously unused stock-days x two symbols: real Parquet vs raw H5.

Only 2026-09-28 and 2026-09-29; the original 2026-09-30 day is never
reused as new evidence. Previous real 2/2 native Hikyuu proof is required,
but this does NOT rerun native C++ on the held-out dates. This outputs
fixed aggregate counts only; no raw OHLCVA or new production H5.
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
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


PAIR=load("readonly_raw_day_pair","probe-real-parquet-h5-day-unit-factors-readonly.py")
NATIVE=load("readonly_real_native_day_proof","verify-real-hikyuu-h5-native-day-isolated.py")
DAY=PAIR.DAY
AUDIT=PAIR.AUDIT

FORMAT="AStockDataTools real H5 Parquet heldout Sep28-29 two-stock-day unit-factor evidence v1"
DAYS=("2026-09-28","2026-09-29")
SOURCE_MONTH="day/2026-09.parquet"
MAX_TOTAL_SCANNED_ROWS=300000
MAX_SOURCE_GROUPS_PER_DAY=32


def previous(path,format_name):
    p=AUDIT._path(path,True)
    blob=p.read_bytes()
    if not 0<len(blob)<=200000:
        raise ValueError("Missing or excessive previous SAFE")
    try:
        d=json.loads(blob)
    except (ValueError,UnicodeError):
        raise ValueError("Malformed previous SAFE") from None
    if type(d) is not dict or d.get("format")!=format_name:
        raise ValueError("Wrong previous SAFE format")
    return d,hashlib.sha256(blob).hexdigest()


def verify_chain(raw_safe,native_safe):
    raw,raw_hash=previous(raw_safe,PAIR.FORMAT)
    nat,nat_hash=previous(native_safe,NATIVE.FORMAT)
    mask=raw.get("comparison",{}).get(
        "candidate_factor_multiply_raw_h5_record_to_parquet_value",{})
    prices=raw.get("comparison",{}).get(
        "raw_h5_price_divided_1000_within_0p005_count",{})
    if (raw.get("sample_day")!="2026-09-30"
            or raw.get("two_selected_stock_days_compared")!=2
            or raw.get("h5_raw_day_records_read")!=2
            or raw.get("sources_read_only_no_h5_or_parquet_writes") is not True
            or raw.get("original_market_files_modified") is not False
            or raw.get("ready_for_full_market_mirror") is not False
            or raw.get("parquet_vendor_physical_amount_unit_certified") is not False
            or raw.get("parquet_vendor_physical_volume_unit_certified") is not False
            or raw.get("licensed_parquet_to_h5_mapping_certified") is not False
            or type(mask) is not dict
            or type(mask.get("volume")) is not dict
            or type(mask.get("amount")) is not dict
            or mask["volume"].get("100")!=2
            or mask["amount"].get("1000")!=2
            or type(prices) is not dict
            or any(prices.get(k)!=2 for k in
                   ("open","high","low","close"))):
        raise ValueError("Previous real two-source raw H5 SAFE not qualified")
    if (nat.get("target_day")!="2026-09-30"
            or nat.get("native_status")!="native_complete"
            or nat.get("native_final_phase")!="finished"
            or nat.get("native_last_work_phase")!="native_complete"
            or nat.get("native_matching_stock_day_count")!=2
            or nat.get("all_two_native_h5_real_daily_records_match") is not True
            or nat.get("native_h5_raw_record_decode_evidence_for_two_stock_days")
               is not True
            or nat.get("native_get_kdata_called") is not True
            or nat.get("original_h5_stat_before_after_unchanged") is not True
            or nat.get("source_h5_or_parquet_modified") is not False
            or nat.get("original_parquet_or_market_sqlite_accessed") is not False
            or nat.get("raw_market_ohlcva_or_timestamp_recorded_in_safe") is not False
            or nat.get("hmac_key_or_digest_recorded_in_safe") is not False
            or nat.get("parquet_vendor_amount_physical_unit_certified") is not False
            or nat.get("parquet_vendor_volume_physical_unit_certified") is not False
            or nat.get("parquet_to_hikyuu_native_units_certified") is not False
            or nat.get("licensed_parquet_to_h5_mapping_certified") is not False
            or nat.get("ready_for_full_market_mirror") is not False):
        raise ValueError("Previous real native H5 two-stock-day SAFE not qualified")
    return {"real_raw_stock_day":raw_hash,"real_native_stock_day":nat_hash}


def aggregated_day(parquet_rows,h5_rows):
    # Pair's checked evaluate() accepts only 2 exact selected symbols and
    # does not persist any real float or raw H5 integer after the call.
    diagnostic=PAIR.evaluate(parquet_rows,h5_rows)
    p=diagnostic["raw_h5_price_divided_1000_within_0p005_count"]
    cand=diagnostic["candidate_factor_multiply_raw_h5_record_to_parquet_value"]
    count=diagnostic["nonzero_positive_pair_count"]
    zero=diagnostic["both_zero_pair_count"]
    one_zero=diagnostic["one_zero_or_nonpositive_pair_count"]
    if any(count[f]+zero[f]+one_zero[f]!=2 for f in ("amount","volume")):
        raise ValueError("Invalid positive/zero H5 comparison partition")
    # The fixed-factor panel remains a DIAGNOSTIC of the underlying raw H5
    # integers, not a claim about vendor-provided yuan/lot/adjustment units.
    return {
        "stock_days_compared":2,
        "price_h5_raw_div1000_within_0p005":{
            field:p[field] for field in ("open","high","low","close")},
        "quantity_positive_nonzero_pairs":{
            field:count[field] for field in ("volume","amount")},
        "quantity_both_zero_pairs":{
            field:zero[field] for field in ("volume","amount")},
        "quantity_one_zero_pairs":{
            field:one_zero[field] for field in ("volume","amount")},
        "candidate_volume_raw_h5_times100_matched":cand["volume"]["100"],
        "candidate_amount_raw_h5_times1000_matched":cand["amount"]["1000"],
        "factor_grid_counts":{
            "volume":dict(cand["volume"]),
            "amount":dict(cand["amount"]),
        },
    }


def evaluate_holdout(day_rows):
    if type(day_rows) is not dict or set(day_rows)!=set(DAYS):
        raise ValueError("Must compare exactly two fixed held-out dates")
    breakdown={}
    for day in DAYS:
        item=day_rows[day]
        if type(item) is not dict or set(item)!={"parquet","h5"}:
            raise ValueError("Invalid held-out pairing")
        breakdown[day]=aggregated_day(item["parquet"],item["h5"])
    count=lambda field:sum(breakdown[day][field] for day in DAYS)
    total={
        "heldout_stock_days_compared":4,
        "price_fields_within_tolerance":{
            field:sum(breakdown[day]["price_h5_raw_div1000_within_0p005"][field]
                      for day in DAYS)
            for field in ("open","high","low","close")},
        "volume_candidate_factor100_matched":count(
            "candidate_volume_raw_h5_times100_matched"),
        "amount_candidate_factor1000_matched":count(
            "candidate_amount_raw_h5_times1000_matched"),
        "nonzero_positive_pairs":{
            field:sum(breakdown[day]["quantity_positive_nonzero_pairs"][field]
                      for day in DAYS)
            for field in ("volume","amount")},
        "zero_pairs":{
            field:sum(breakdown[day]["quantity_both_zero_pairs"][field]
                      for day in DAYS)
            for field in ("volume","amount")},
    }
    return breakdown,total


def run(parquet_root,h5_root,prior_raw,prior_native,out):
    target=AUDIT._path(out,False)
    hashes=verify_chain(prior_raw,prior_native)
    # The source is one exact purchased MONTHLY DAY file only, no 5min/1min.
    path=DAY.FOOTER.selected_file(parquet_root,SOURCE_MONTH,"day")
    source_before=DAY.FOOTER.footer_guard(path)
    h5_paths={symbol:PAIR._plain_h5_path(h5_root,symbol)
              for symbol in PAIR.SYMBOLS}
    h5_before={
        symbol:(p.stat().st_size,p.stat().st_mtime_ns)
        for symbol,p in h5_paths.items()}
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    import h5py
    import numpy as np
    daily={}
    scan=0
    groups=0
    try:
        for day in DAYS:
            if day==PAIR.DAY_DATE:
                raise ValueError("Heldout day overlaps discovery sample")
            pq_rows,n,g=DAY._read_bounded_daily(path,day,pa,pq,pc)
            scan+=n
            groups+=g
            if (scan>MAX_TOTAL_SCANNED_ROWS or g>MAX_SOURCE_GROUPS_PER_DAY):
                raise ValueError("Exceeded small held-out day source scan budget")
            h5_rows={symbol:PAIR._read_single_h5(h5_root,symbol,day,h5py,np)
                     for symbol in PAIR.SYMBOLS}
            daily[day]={"parquet":pq_rows,"h5":h5_rows}
        breakdown,aggregate=evaluate_holdout(daily)
    finally:
        if DAY.FOOTER.footer_guard(path)!=source_before:
            raise ValueError("Original Parquet source changed during held-out check")
        if any((p.stat().st_size,p.stat().st_mtime_ns)!=h5_before[symbol]
               for symbol,p in h5_paths.items()):
            raise ValueError("Original H5 source changed during held-out check")
    safe={
        "format":FORMAT,
        "holdout_days":list(DAYS),
        "prior_discovery_date_excluded":"2026-09-30",
        "source_period":"day",
        "stock_days_per_date":2,
        "source_parquet_month_files_read":1,
        "scanned_monthly_source_rows_total":scan,
        "scanned_row_groups_total_across_date_passes":groups,
        "h5_raw_day_records_read":4,
        "observations_independent_of_discovery_date":True,
        "previous_real_native_proof_only_covers_discovery_date":True,
        "holdout_native_cpp_kdata_executed":False,
        "candidate_definition":
            "Parquet original float approximately equals raw H5 integer multiplied by factor",
        "quantity_candidate_relative_tolerance":"0.00001",
        "price_tolerance":"0.005",
        "per_holdout_date_diagnostic":breakdown,
        "aggregate":aggregate,
        "previous_SAFE_sha256":hashes,
        "raw_ohlcva_or_h5_integer_values_exported":False,
        "source_paths_or_market_timestamps_exported":False,
        "original_parquet_or_h5_modified":False,
        "no_market_sqlite_or_h5_write_performed":True,
        "native_decoder_consistency_not_retested_on_heldout_dates":True,
        "vendor_volume_physical_unit_certified":False,
        "vendor_amount_physical_unit_certified":False,
        "source_timestamp_semantics_certified":False,
        "sample_factor_generalization_certified":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
    }
    with target.open("x",encoding="utf-8") as f:
        json.dump(safe,f,ensure_ascii=False,indent=2,sort_keys=True)
        f.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parquet-root",required=True,type=Path)
    p.add_argument("--h5-root",required=True,type=Path)
    p.add_argument("--prior-raw-safe",required=True,type=Path)
    p.add_argument("--prior-native-safe",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--read-only-heldout-days",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        result=run(args.parquet_root,args.h5_root,args.prior_raw_safe,
                   args.prior_native_safe,args.out)
    except (ValueError,TypeError,KeyError,OSError,ImportError,
            OverflowError,json.JSONDecodeError):
        p.error("Heldout real daily source verification refused; check prior SAFE and source bounds")
    aggregate=result["aggregate"]
    print("SAFE heldout daily evidence:",args.out)
    print("Heldout stock-day pairs:",aggregate["heldout_stock_days_compared"])
    print("Volume raw H5 x100 matched:",
          aggregate["volume_candidate_factor100_matched"])
    print("Amount raw H5 x1000 matched:",
          aggregate["amount_candidate_factor1000_matched"])
    print("Original market files modified: NO")
    print("Vendor physical units / production H5 mapping certified: NO")


if __name__=="__main__":
    main()
