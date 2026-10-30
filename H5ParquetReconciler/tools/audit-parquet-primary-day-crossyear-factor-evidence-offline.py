#!/usr/bin/env python3
"""Offline five-SAFE daily factor evidence gate for the Parquet-primary roadmap.

ZERO raw H5, Parquet, C++ or production database reads. The successful
2025/2026 sample supports numeric candidate ratios, not vendor physical
units or permission to create native market H5 mirrors.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "source_crossyear_daily_safe_gate",
    HERE/"probe-real-h5-parquet-crossyear-day-readonly.py")
T=importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

FORMAT="AStockDataTools Parquet-primary independent-year daily sample evidence gate v1"
DAYS=("2025-09-30","2026-08-24")
FIELDS=("open","high","low","close")
FACTORS=("0.01","0.1","1","10","100","1000")
MAX_SAFE_BYTES=200000


def verified_json(path):
    source=T.AUDIT._path(path,True)
    raw=source.read_bytes()
    if not 0<len(raw)<=MAX_SAFE_BYTES:
        raise ValueError("Missing or excessive SAFE evidence")
    try:
        content=json.loads(raw)
    except (UnicodeError,ValueError):
        raise ValueError("Malformed SAFE evidence") from None
    if type(content) is not dict:
        raise ValueError("SAFE evidence must be a JSON object")
    return content,hashlib.sha256(raw).hexdigest()


def check_per_day(item):
    if type(item) is not dict or item.get("stock_days_compared")!=2:
        raise ValueError("Invalid independently tested stock-day count")
    if item.get("candidate_volume_raw_h5_times100_matched")!=2:
        raise ValueError("Volume candidate not confirmed on both daily samples")
    if item.get("candidate_amount_raw_h5_times1000_matched")!=2:
        raise ValueError("Amount candidate not confirmed on both daily samples")
    if item.get("price_h5_raw_div1000_within_0p005")!=dict.fromkeys(FIELDS,2):
        raise ValueError("Not all four daily price fields qualify")
    if item.get("quantity_positive_nonzero_pairs")!={"volume":2,"amount":2}:
        raise ValueError("Zero or invalid quantity cannot prove a factor")
    if item.get("quantity_both_zero_pairs")!={"volume":0,"amount":0}:
        raise ValueError("Both-zero factors are non-evidence")
    if item.get("quantity_one_zero_pairs")!={"volume":0,"amount":0}:
        raise ValueError("One-zero candidate is invalid")
    grid=item.get("factor_grid_counts")
    if type(grid) is not dict or set(grid)!={"volume","amount"}:
        raise ValueError("Missing complete candidate factor grid")
    for field,winner in (("volume","100"),("amount","1000")):
        counts=grid[field]
        if (type(counts) is not dict or set(counts)!=set(FACTORS)
                or any(type(v) is not int or v<0 or v>2
                       for v in counts.values())
                or counts[winner]!=2
                or any(v!=0 for k,v in counts.items() if k!=winner)):
            raise ValueError("Ambiguous or inconsistent candidate factor grid")


def audit(raw_safe,native_safe,heldout_safe,key_safe,crossyear_safe,out):
    target=T.AUDIT._path(out,False)
    # Run EXACT prior discovery, native and 2026-09 same-month chain checks.
    prior=T.verified_sources(raw_safe,native_safe,heldout_safe)
    # The 2025 annual key-only proof was 2-column-only: do not pretend it
    # measured prices, or accept false production certification.
    key,sha_key=T.qualified_annual_key_only_safe(key_safe)
    result,sha_cross=verified_json(crossyear_safe)
    declared={**prior,"annual_2025_key_only":sha_key}
    if (result.get("format")!=T.FORMAT
            or result.get("fixed_crossyear_samples")!=list(DAYS)
            or result.get("independent_of_prior_2026_09_discovery_and_heldout_days") is not True
            or result.get("source_period")!="day"
            or result.get("symbols_sampled_count")!=2
            or result.get("source_parquet_files_read")!=2
            or result.get("source_parquet_layouts")!={"2025":"annual_two_column_key_revalidated",
                                                        "2026":"monthly"}
            or result.get("previous_safe_sha256")!=declared
            or result.get("annual_2025_prior_key_only_safe_revalidated") is not True
            or result.get("annual_2025_key_only_rows_rechecked")!=key["key_only_rows_scanned"]
            or result.get("annual_2025_key_only_batches_rechecked")!=key["key_only_batches_scanned"]
            or result.get("annual_2025_source_total_rows_from_footer")!=key["source_year_footer_rows"]
            or result.get("annual_2025_source_rowgroups_from_footer")!=key["source_year_footer_rowgroups"]
            or result.get("annual_2025_selected_rowgroups_scanned")!=key["selected_target_rowgroups"]
            or result.get("annual_2025_ohlcva_rows_scanned")!=key["selected_target_rowgroup_total_rows"]
            or type(result.get("source_parquet_total_rows_scanned")) is not int
            or not key["selected_target_rowgroup_total_rows"]<=result["source_parquet_total_rows_scanned"]<=300000
            or type(result.get("source_parquet_row_groups_scanned")) is not int
            or not key["selected_target_rowgroups"]<=result["source_parquet_row_groups_scanned"]<=64
            or result.get("raw_h5_day_records_read")!=4
            or result.get("native_cpp_h5_decoding_on_crossyear_samples_executed") is not False
            or result.get("previous_native_real_decode_was_only_2026_09_30") is not True
            or result.get("source_files_stat_or_footer_before_after_unchanged") is not True
            or result.get("entire_market_source_files_sha256_checked") is not False
            or result.get("source_files_modified") is not False
            or result.get("market_sqlite_or_h5_writes_performed") is not False
            or result.get("raw_ohlcva_or_native_integer_values_in_report") is not False
            or result.get("raw_market_paths_or_individual_source_timestamps_in_report") is not False
            or result.get("vendor_amount_physical_units_certified") is not False
            or result.get("vendor_volume_physical_units_certified") is not False
            or result.get("source_timestamp_semantics_certified") is not False
            or result.get("universal_factor_across_time_or_periods_certified") is not False
            or result.get("licensed_parquet_to_h5_mapping_certified") is not False
            or result.get("ready_for_full_market_mirror") is not False):
        raise ValueError("Crossyear real numeric sample SAFE not qualified")
    days=result.get("per_sample_day")
    if type(days) is not dict or set(days)!=set(DAYS):
        raise ValueError("Independently tested dates do not match")
    for day in DAYS:
        check_per_day(days[day])
    aggregate=result.get("crossyear_aggregate")
    if (type(aggregate) is not dict
            or aggregate.get("stock_days_compared")!=4
            or aggregate.get("volume_candidate_raw_h5_times100_matched")!=4
            or aggregate.get("amount_candidate_raw_h5_times1000_matched")!=4
            or aggregate.get("per_field_price_tolerance_matches")!=dict.fromkeys(FIELDS,4)
            or aggregate.get("nonzero_positive_pairs")!={"volume":4,"amount":4}
            or aggregate.get("both_zero_pairs")!={"volume":0,"amount":0}
            or aggregate.get("one_zero_pairs")!={"volume":0,"amount":0}):
        raise ValueError("Crossyear aggregate contradicts per-day positives")
    report={
        "format":FORMAT,
        "scope":"two fixed symbols; three months across 2025 and 2026; daily only",
        "source_discovery_stock_days":2,
        "same_month_holdout_stock_days":4,
        "crossyear_holdout_stock_days":4,
        "total_distinct_daily_stock_days_with_candidate_factor_matches":10,
        "positive_volume_factor100_sample_count":10,
        "positive_amount_factor1000_sample_count":10,
        "all_four_ohlc_raw_div1000_sample_count_per_field":10,
        "native_hikyuu_281_cpp_verified_real_stock_days":2,
        "native_cpp_tested_on_crossyear_holdouts":False,
        "annual_2025_key_only_rows_verified":key["key_only_rows_scanned"],
        "annual_2025_ohlcva_rows_verified":result["annual_2025_ohlcva_rows_scanned"],
        "crossyear_total_ohlcva_rows_verified":result["source_parquet_total_rows_scanned"],
        "five_safe_sha256":{**declared,"crossyear_holdout":sha_cross},
        "sample_numeric_factor_candidate_supported":True,
        "candidate_raw_h5_volume_multiply":100,
        "candidate_raw_h5_amount_multiply":1000,
        "candidate_raw_h5_price_divide":1000,
        "raw_ohlcva_h5_integer_or_source_paths_exported":False,
        "market_source_opened_or_modified_by_this_audit":False,
        "vendor_amount_physical_units_certified":False,
        "vendor_volume_physical_units_certified":False,
        "adjustment_and_timestamps_certified":False,
        "universal_period_factor_certified":False,
        "licensed_parquet_to_native_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
        "ready_to_modify_parquet_primary_source":False,
    }
    with target.open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,sort_keys=True)
        f.write("\n")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("raw","native","heldout","key","crossyear"):
        p.add_argument("--"+arg+"-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--offline-day-factor-evidence-only",required=True,
                   action="store_true")
    a=p.parse_args(argv)
    try:
        report=audit(a.raw_safe,a.native_safe,a.heldout_safe,
                     a.key_safe,a.crossyear_safe,a.out)
    except (ValueError,TypeError,KeyError,OSError,OverflowError,ImportError):
        p.error("SAFE daily factor chain not qualified, no production mapping approved")
    print("SAFE daily evidence:",a.out)
    print("Matching independent-year stock-days:",
          report["total_distinct_daily_stock_days_with_candidate_factor_matches"])
    print("Physical unit and native H5 production conversion approved: NO")


if __name__=="__main__":
    main()
