#!/usr/bin/env python3
"""Read-only held-out 2026-09-28/29 QDC Parquet vs raw H5 amount residuals.

Rechecks an already verified 4-stock-day heldout factor SAFE against newly
read, tightly bounded original data; links independently verified Sep30
residual SAFE without re-reading Sep30. Compares candidate *rounding rules*
as diagnostics only. Never writes original Parquet/H5 or chooses a policy.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def import_file(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOLDOUT=import_file("heldout_amount_previous_factor_probe",
                    "probe-real-h5-parquet-heldout-day-factors-readonly.py")
AMOUNT=import_file("heldout_amount_previous_discovery_residual",
                   "audit-real-pq-h5-amount-residual-readonly.py")
PAIR=HOLDOUT.PAIR
DAY=HOLDOUT.DAY
AUDIT=HOLDOUT.AUDIT
DAYS=("2026-09-28","2026-09-29")
FORMAT="AStockDataTools bounded real heldout daily amount integer residual diagnostics v1"
MAX_REPORT_BYTES=200000


def previous_heldout(file):
    obj,sha=HOLDOUT.previous(file,HOLDOUT.FORMAT)
    agg=obj.get("aggregate")
    per=obj.get("per_holdout_date_diagnostic")
    if (obj.get("holdout_days")!=list(DAYS)
            or obj.get("prior_discovery_date_excluded")!="2026-09-30"
            or obj.get("source_period")!="day"
            or obj.get("stock_days_per_date")!=2
            or obj.get("source_parquet_month_files_read")!=1
            or obj.get("h5_raw_day_records_read")!=4
            or obj.get("observations_independent_of_discovery_date") is not True
            or obj.get("holdout_native_cpp_kdata_executed") is not False
            or obj.get("original_parquet_or_h5_modified") is not False
            or obj.get("no_market_sqlite_or_h5_write_performed") is not True
            or obj.get("raw_ohlcva_or_h5_integer_values_exported") is not False
            or obj.get("source_paths_or_market_timestamps_exported") is not False
            or any(obj.get(flag) is not False for flag in (
                "vendor_volume_physical_unit_certified",
                "vendor_amount_physical_unit_certified",
                "source_timestamp_semantics_certified",
                "sample_factor_generalization_certified",
                "licensed_parquet_to_h5_mapping_certified",
                "ready_for_full_market_mirror"))
            or type(agg) is not dict
            or agg.get("heldout_stock_days_compared")!=4
            or agg.get("price_fields_within_tolerance")!={
                field:4 for field in ("open","high","low","close")}
            or agg.get("volume_candidate_factor100_matched")!=4
            or agg.get("amount_candidate_factor1000_matched")!=4
            or agg.get("nonzero_positive_pairs")!={"volume":4,"amount":4}
            or agg.get("zero_pairs")!={"volume":0,"amount":0}
            or type(per) is not dict or set(per)!=set(DAYS)):
        raise ValueError("Existing heldout factor SAFE cannot be used as exact residual baseline")
    for day in DAYS:
        item=per[day]
        if (type(item) is not dict
                or item.get("stock_days_compared")!=2
                or item.get("candidate_volume_raw_h5_times100_matched")!=2
                or item.get("candidate_amount_raw_h5_times1000_matched")!=2
                or item.get("price_h5_raw_div1000_within_0p005")!={
                    k:2 for k in ("open","high","low","close")}
                or item.get("quantity_positive_nonzero_pairs")!={"volume":2,"amount":2}
                or item.get("quantity_both_zero_pairs")!={"volume":0,"amount":0}
                or item.get("quantity_one_zero_pairs")!={"volume":0,"amount":0}):
            raise ValueError("Existing heldout per-day factor SAFE is not qualified")
    return obj,sha


def previous_discovery_amount(file):
    p=AUDIT._path(file,True)
    blob=p.read_bytes()
    if not 0<len(blob)<=MAX_REPORT_BYTES:
        raise ValueError("Prior discovery amount residual SAFE missing or oversized")
    obj=json.loads(blob)
    counts=obj.get("amount_residual_counts")
    required={
        "sample_positive_pairs":2,
        "would_require_decimal_rounding":2,
        "candidate_exact_original_h5_integer_count":0,
        "nearest_half_even_matches_original_count":2,
        "floor_matches_original_count":0,
        "ceiling_matches_original_count":2,
        "within_previous_relative_tolerance_count":2,
        "candidate_above_original_count":0,
        "candidate_below_original_count":2,
    }
    if (type(obj) is not dict or obj.get("format")!=AMOUNT.FORMAT
            or obj.get("trading_day")!="2026-09-30"
            or obj.get("h5_target_day_records_read")!=2
            or obj.get("amount_native_integer_candidate_is_purchased_amount_divided_by")!="1000"
            or type(counts) is not dict
            or any(counts.get(k)!=v for k,v in required.items())
            or counts.get("absolute_integer_candidate_residual_buckets")!={
                name:(2 if name=="le_0p1" else 0)
                for name in AMOUNT.ABS_BUCKETS}
            or obj.get("source_file_stat_unchanged") is not True
            or obj.get("prior_exactness_counts_reverified") is not True
            or obj.get("no_source_values_raw_integers_symbols_or_absolute_paths_exported") is not True
            or obj.get("hypothetical_rounding_is_not_an_approved_policy") is not True
            or any(obj.get(flag) is not False for flag in (
                "original_source_parquet_h5_or_sqlite_written",
                "real_h5_written",
                "vendor_amount_physical_units_certified",
                "lossless_native_h5_amount_conversion_certified",
                "ready_for_full_market_mirror",
                "ready_to_modify_purchased_parquet_or_original_h5"))):
        raise ValueError("Prior real Sep30 amount residual SAFE is not qualified")
    return hashlib.sha256(blob).hexdigest()


def sample_day(parquet,h5,day):
    if (type(parquet) is not dict or type(h5) is not dict
            or set(parquet)!=set(PAIR.SYMBOLS) or set(h5)!=set(PAIR.SYMBOLS)
            or day not in DAYS):
        raise ValueError("Exactly the two known heldout stocks and dates required")
    result={
        "sample_positive_pairs":0,
        "would_require_decimal_rounding":0,
        "candidate_exact_original_h5_integer_count":0,
        "nearest_half_even_matches_original_count":0,
        "floor_matches_original_count":0,
        "ceiling_matches_original_count":0,
        "within_previous_relative_tolerance_count":0,
        "candidate_above_original_count":0,
        "candidate_below_original_count":0,
        "rounding_hypotheses_half_even_vs_ceil_differ_count":0,
        "rounding_hypotheses_half_even_vs_floor_differ_count":0,
        "absolute_integer_candidate_residual_buckets":{
            name:0 for name in AMOUNT.ABS_BUCKETS},
    }
    for symbol in PAIR.SYMBOLS:
        row=parquet[symbol]
        native=h5[symbol]
        expected_date=int(day.replace("-","")+"0000")
        if (type(row) is not dict or set(row)!=set(PAIR.FIELDS)
                or type(native) is not dict or set(native)!=set(PAIR.RAW)
                or type(native.get("datetime")) is not int
                or native["datetime"]!=expected_date):
            raise ValueError("Heldout amount pair has invalid fields or day")
        d=AMOUNT.one_amount(row["amount"],native["transAmount"])
        result["sample_positive_pairs"]+=1
        for old,new in (
            ("candidate_requires_rounding","would_require_decimal_rounding"),
            ("candidate_exactly_equals_raw","candidate_exact_original_h5_integer_count"),
            ("nearest_half_even_matches_raw","nearest_half_even_matches_original_count"),
            ("floor_matches_raw","floor_matches_original_count"),
            ("ceiling_matches_raw","ceiling_matches_original_count"),
            ("existing_relative_tolerance_1e_minus_5","within_previous_relative_tolerance_count"),
            ("candidate_above_native_raw","candidate_above_original_count"),
            ("candidate_below_native_raw","candidate_below_original_count")):
            result[new]+=int(d[old])
        # A distinct rounding decision is informative only when the candidate
        # would have produced a different native integer under the hypotheses.
        from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN
        c=Decimal(str(row["amount"]))/Decimal(1000)
        half=c.to_integral_value(rounding=ROUND_HALF_EVEN)
        ceil=c.to_integral_value(rounding=ROUND_CEILING)
        floor=c.to_integral_value(rounding=ROUND_FLOOR)
        result["rounding_hypotheses_half_even_vs_ceil_differ_count"]+=int(half!=ceil)
        result["rounding_hypotheses_half_even_vs_floor_differ_count"]+=int(half!=floor)
        result["absolute_integer_candidate_residual_buckets"][d["abs_residual_bucket"]]+=1
    return result


def evaluate(daily):
    if type(daily) is not dict or set(daily)!=set(DAYS):
        raise ValueError("Only two fixed heldout dates admitted")
    by_day={}
    for day in DAYS:
        if type(daily[day]) is not dict or set(daily[day])!={"parquet","h5"}:
            raise ValueError("Missing original paired heldout source")
        by_day[day]=sample_day(daily[day]["parquet"],daily[day]["h5"],day)
    keys=[name for name in by_day[DAYS[0]]
          if name!="absolute_integer_candidate_residual_buckets"]
    totals={key:sum(by_day[day][key] for day in DAYS) for key in keys}
    totals["absolute_integer_candidate_residual_buckets"]={
        key:sum(by_day[day]["absolute_integer_candidate_residual_buckets"][key]
                for day in DAYS) for key in AMOUNT.ABS_BUCKETS}
    if (totals["sample_positive_pairs"]!=4
            or sum(totals["absolute_integer_candidate_residual_buckets"].values())!=4
            or totals["candidate_above_original_count"]+
               totals["candidate_below_original_count"]+
               totals["candidate_exact_original_h5_integer_count"]!=4):
        raise ValueError("Heldout residual coverage incomplete")
    return by_day,totals


def run(purchased_root,h5_root,heldout_safe,discovery_safe,out):
    target=AUDIT._path(out,False)
    prior,heldout_sha=previous_heldout(heldout_safe)
    discovery_sha=previous_discovery_amount(discovery_safe)
    path=DAY.FOOTER.selected_file(purchased_root,HOLDOUT.SOURCE_MONTH,"day")
    market_before=DAY.FOOTER.footer_guard(path)
    h5_paths={symbol:PAIR._plain_h5_path(h5_root,symbol) for symbol in PAIR.SYMBOLS}
    h5_before={symbol:(p.stat().st_size,p.stat().st_mtime_ns)
               for symbol,p in h5_paths.items()}
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    import h5py
    import numpy as np
    scan=0
    groups=0
    daily={}
    try:
        for day in DAYS:
            rows,n,g=DAY._read_bounded_daily(path,day,pa,pq,pc)
            scan+=n
            groups+=g
            if scan>HOLDOUT.MAX_TOTAL_SCANNED_ROWS or g>HOLDOUT.MAX_SOURCE_GROUPS_PER_DAY:
                raise ValueError("Heldout monthly Parquet read exceeds agreed budget")
            records={symbol:PAIR._read_single_h5(h5_root,symbol,day,h5py,np)
                     for symbol in PAIR.SYMBOLS}
            daily[day]={"parquet":rows,"h5":records}
        # Verify exact previous factor counts, not merely current plausibility.
        now_by_day,now_aggregate=HOLDOUT.evaluate_holdout(daily)
        if (now_by_day!=prior["per_holdout_date_diagnostic"]
                or now_aggregate!=prior["aggregate"]
                or scan!=prior.get("scanned_monthly_source_rows_total")
                or groups!=prior.get("scanned_row_groups_total_across_date_passes")):
            raise ValueError("Previous heldout source evidence no longer reproduces")
        by_date,total=evaluate(daily)
    finally:
        if DAY.FOOTER.footer_guard(path)!=market_before:
            raise ValueError("Purchased original Parquet changed during heldout read")
        if any((p.stat().st_size,p.stat().st_mtime_ns)!=h5_before[symbol]
               for symbol,p in h5_paths.items()):
            raise ValueError("Original H5 source changed during heldout read")
    if (HOLDOUT.previous(heldout_safe,HOLDOUT.FORMAT)[1]!=heldout_sha
            or previous_discovery_amount(discovery_safe)!=discovery_sha):
        raise ValueError("Previous SAFE changed during heldout residual audit")
    result={
        "format":FORMAT,
        "status":"four_heldout_daily_pairs_descriptive_amount_rounding_not_certified",
        "dates":list(DAYS),
        "discovery_day_not_reread":"2026-09-30",
        "heldout_stock_days_compared":4,
        "original_h5_raw_day_records_read":4,
        "purchased_parquet_monthly_source_rows_bounded":scan,
        "purchased_parquet_row_groups_scanned_across_dates":groups,
        "raw_h5_integer_candidate_definition":"purchased amount / 1000",
        "per_holdout_date_residual_counts":by_date,
        "heldout_aggregate_residual_counts":total,
        "previous_heldout_factor_safe_sha256":heldout_sha,
        "previous_discovery_amount_residual_safe_sha256":discovery_sha,
        "prior_heldout_factor_counts_reproduced":True,
        "previous_discovery_amount_prior_only_not_reread":True,
        "source_file_stat_unchanged":True,
        "real_market_ohlcva_h5_integers_stock_codes_or_absolute_paths_exported":False,
        "output_is_descriptive_not_rounding_policy":True,
        "vendor_amount_physical_units_certified":False,
        "lossless_native_h5_amount_conversion_certified":False,
        "heldout_native_cpp_kdata_executed":False,
        "ready_for_full_market_mirror":False,
        "ready_to_modify_purchased_parquet_or_original_h5":False,
        "source_parquet_h5_or_market_sqlite_written":False,
        "production_or_private_active_pointer_modified":False,
    }
    with target.open("x",encoding="utf-8") as handle:
        json.dump(result,handle,sort_keys=True,ensure_ascii=False,indent=2)
        handle.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--purchased-root",type=Path,required=True)
    p.add_argument("--h5-root",type=Path,required=True)
    p.add_argument("--heldout-safe",type=Path,required=True)
    p.add_argument("--discovery-amount-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-heldout-amount-residual",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        report=run(args.purchased_root,args.h5_root,args.heldout_safe,
                   args.discovery_amount_safe,args.out)
        print("SAFE heldout daily amount residual:",args.out)
        print("Previously heldout nonzero source stock-days:",
              report["heldout_stock_days_compared"])
        print("Actual Parquet/H5 market writes: NO")
        print("H5 mirror rounding rule or historical units certified: NO")
    except (OSError,ValueError,TypeError,KeyError,ImportError,
            OverflowError,json.JSONDecodeError,ArithmeticError):
        p.error("Heldout daily amount precision audit refused; no original writes")


if __name__=="__main__":
    main()
