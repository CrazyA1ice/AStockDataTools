#!/usr/bin/env python3
"""Combine three ALREADY EXISTING SAFE reports; never open market data.

Evidence: real two-stock Parquet float64 precision (one day);
TDX vs purchased Parquet for ONE stock on that same date (different source);
H5 vs purchased Parquet 5min residuals on another date (different source).
A scalar ratio or a two-bar tick fit CANNOT certify source units or a
full-market, cross-source-to-Hikyuu conversion. Output only fixed safe counts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools offline real float64 and crosssource evidence bridge v1"
PRECISION_FORMAT="AStockDataTools bounded real Parquet day float64 H5 tick hypotheses v1"
TDX_FORMAT="AStockDataTools bounded TDX vs Parquet daily and 5min parity audit v1"
H5_FORMAT="AStockDataTools x100 focused 5min residual session forensic v1"
SYMBOLS=frozenset(("SH600000","SZ000001"))
FIELDS=("open","high","low","close","amount","volume")
MASKS=frozenset(("none","volume","amount","price","volume_amount",
                 "volume_price","amount_price","volume_amount_price"))
MAX_REPORT=200_000


def safe_path(p,existing):
    p=Path(p)
    if (REPORTS.is_symlink() or p.is_symlink() or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Only direct report JSON under module reports/ allowed")
    if existing:
        if not p.is_file() or not 0<p.stat().st_size<=MAX_REPORT:
            raise ValueError("Existing bounded SAFE report required")
    elif p.exists():
        raise ValueError("Use a NEW SAFE output filename; no overwrites")
    return p


def checked_safe(path):
    p=safe_path(path,True)
    blob=p.read_bytes()
    # No raw user paths, raw file contents or arbitrary vendor metadata are
    # echoed back to the caller/output. Hash provides report identity only.
    try:
        return json.loads(blob),hashlib.sha256(blob).hexdigest()
    except (UnicodeDecodeError,json.JSONDecodeError):
        raise ValueError("Malformed SAFE input report") from None


def _exact_int(x,lo,hi):
    if type(x) is not int or not lo<=x<=hi:
        raise ValueError("Invalid bounded aggregate count")
    return x


def _finite_ratio(x,lo,hi):
    if type(x) not in (int,float) or not math.isfinite(x) or not lo<=x<=hi:
        raise ValueError("Invalid aggregate relative ratio")
    return x


def precision_part(d):
    if (type(d) is not dict or d.get("format")!=PRECISION_FORMAT
            or d.get("sample_trading_day")!="2026-09-30"
            or d.get("sample_security_count")!=2
            or d.get("no_native_h5_integer_records_encoded_or_written") is not True
            or d.get("source_parquet_read_only") is not True
            or d.get("raw_ohlcva_or_timestamp_values_in_safe") is not False
            or d.get("licensed_parquet_physical_units_certified") is not False
            or d.get("real_float64_to_h5_precision_mapping_certified") is not False
            or d.get("ready_for_full_market_mirror") is not False
            or type(d.get("field_hypotheses")) is not dict
            or set(d["field_hypotheses"])!=set(FIELDS)):
        raise ValueError("Precision SAFE incompatible or has an unsafe claim")
    stats={}
    for field in FIELDS:
        x=d["field_hypotheses"][field]
        if type(x) is not dict or set(x)!={
                "sampled_values","shortest_decimal_tick_exact_count",
                "binary_float_tick_exact_count",
                "would_require_rounding_count",
                "half_tick_boundary_count","range_overflow_count"}:
            raise ValueError("Unexpected precision fields (could expose prices)")
        _exact_int(x["sampled_values"],2,2)
        vals={key:_exact_int(value,0,2) for key,value in x.items()}
        if (vals["shortest_decimal_tick_exact_count"]+
                vals["would_require_rounding_count"]+
                vals["range_overflow_count"]!=2
                or vals["half_tick_boundary_count"]>
                vals["would_require_rounding_count"]
                or vals["binary_float_tick_exact_count"]>
                vals["shortest_decimal_tick_exact_count"]):
            raise ValueError("Inconsistent precision aggregate")
        stats[field]=vals
    return {
        "trading_day":"2026-09-30",
        "two_real_stock_days_sampled":2,
        "price_shortest_decimal_tick_fit":{
            field:stats[field]["shortest_decimal_tick_exact_count"]
            for field in ("open","high","low","close")},
        "price_binary_float_tick_exact":{
            field:stats[field]["binary_float_tick_exact_count"]
            for field in ("open","high","low","close")},
        "quantity_shortest_decimal_tick_fit":{
            field:stats[field]["shortest_decimal_tick_exact_count"]
            for field in ("volume","amount")},
        "total_possible_tick_rounding_values":sum(
            stats[f]["would_require_rounding_count"] for f in FIELDS),
        "total_native_integer_range_overflows":sum(
            stats[f]["range_overflow_count"] for f in FIELDS),
        "original_vendor_decimal_recovered":False,
        "raw_float64_to_native_h5_mapping_certified":False,
    }


def _tdx_comparison(d,group,keys,n):
    compare=d.get("comparisons")
    if type(compare) is not dict or type(compare.get(group)) is not dict:
        raise ValueError("TDX parity group missing")
    rec=compare[group]
    for field in keys:
        row=rec.get(field)
        if type(row) is not dict:
            raise ValueError("TDX parity field missing")
        if (_exact_int(row.get("n"),n,n)!=n or
                _exact_int(row.get("within_diagnostic_tolerance"),
                           0,n)!=n):
            raise ValueError("TDX field not matched within prior tolerances")
        _finite_ratio(row.get("max_relative_error"),0,0.01)
        if field in ("amount","volume"):
            _finite_ratio(row.get("ratio_actual_over_reference_median"),
                          0.9,1.1)
    return True


def tdx_part(d):
    if (type(d) is not dict or d.get("format")!=TDX_FORMAT
            or d.get("date")!="2026-09-30"
            or d.get("symbol")!="SH600000"
            or d.get("tdx_internal_three_period_all_fields_within_tolerance") is not True
            or d.get("only_tdx_and_purchased_parquet_read") is not True
            or d.get("h5_accessed") is not False
            or d.get("cross_vendor_volume_and_amount_unit_convention_unverified") is not True
            or d.get("source_market_files_modified") is not False
            or d.get("eligible_for_automatic_production_union") is not False
            or d.get("five_minute_alignment")!=
               "TDX ending label == Parquet starting label + 5 minutes"
            or type(d.get("tdx_source_counts")) is not dict
            or type(d.get("parquet_source_counts")) is not dict):
        raise ValueError("TDX cross-source SAFE incompatible or unsafe")
    if (d["tdx_source_counts"].get("day")!=1
            or d["tdx_source_counts"].get("5min")!=48
            or d["parquet_source_counts"].get("day")!=1
            or d["parquet_source_counts"].get("5min")!=48):
        raise ValueError("TDX cross-source stock-day coverage incomplete")
    _tdx_comparison(d,"tdx_5min_vs_parquet_5min_by_interval",FIELDS,48)
    _tdx_comparison(d,"tdx_daily_vs_parquet_daily",FIELDS,1)
    return {
        "trading_day":"2026-09-30",
        "selected_security":"SH600000",
        "same_stock_day_as_precision_pilot":True,
        "five_minute_bars_compared":48,
        "five_minute_all_six_fields_within_report_tolerance":48,
        "daily_bars_compared":1,
        "daily_all_six_fields_within_report_tolerance":1,
        "tdx_is_hikyuu_h5":False,
        "independent_supplier_units_certified":False,
        "five_minute_start_end_label_semantics_officially_certified":False,
    }


def h5_part(d):
    if (type(d) is not dict or d.get("format")!=H5_FORMAT
            or d.get("date")!="2026-09-28"
            or d.get("h5_five_minute_volume_factor_candidate")!=100
            or d.get("unit_mapping_certified") is not False
            or d.get("safe_to_automatically_union") is not False
            or d.get("no_raw_ohlcv_exported") is not True
            or d.get("source_files_modified") is not False
            or type(d.get("symbol_results")) is not dict
            or set(d["symbol_results"])!=set((
                "SH688629","SH688017","SH688172"))):
        raise ValueError("H5 residual SAFE incompatible or unsafe")
    matched=0
    conflicts=0
    each=[]
    for symbol in sorted(d["symbol_results"]):
        entry=d["symbol_results"][symbol]
        if (type(entry) is not dict
                or _exact_int(entry.get("h5_5min_bars"),48,48)!=48
                or _exact_int(entry.get("parquet_5min_bars"),48,48)!=48
                or _exact_int(entry.get("h5_only_bars"),0,0)!=0
                or _exact_int(entry.get("parquet_only_bars"),0,0)!=0
                or type(entry.get("exact_residual_masks")) is not dict
                or set(entry["exact_residual_masks"])!=MASKS):
            raise ValueError("H5 matched residual mask coverage missing")
        m={name:_exact_int(val,0,48)
           for name,val in entry["exact_residual_masks"].items()}
        if sum(m.values())!=48:
            raise ValueError("H5 residual masks do not sum to matched bars")
        matched+=48
        conflicts+=48-m["none"]
        each.append(48-m["none"])
    if matched!=144 or conflicts<=0:
        raise ValueError("H5 residual dataset unrecognized")
    return {
        "trading_day":"2026-09-28",
        "selected_stock_days":3,
        "five_minute_bars_compared":matched,
        "any_field_candidate_conflict_bars":conflicts,
        "stock_day_candidate_conflict_counts":each,
        "h5_volume_factor_100_is_only_a_hypothesis":True,
        "single_daily_exact_tick_fit_does_not_remove_h5_residuals":True,
        "source_time_label_semantics_certified":False,
        "global_h5_vs_parquet_unit_mapping_certified":False,
    }


def build(precision,tdx,h5):
    p=precision_part(precision)
    t=tdx_part(tdx)
    h=h5_part(h5)
    return {
        "format":FORMAT,
        "input_evidence_was_preexisting_safe_json_only":True,
        "source_stock_files_or_market_db_opened":False,
        "real_ohlcva_or_individual_timestamps_emitted":False,
        "precision":p,
        "tdx_vs_purchased_parquet":t,
        "hikyuu_h5_vs_purchased_parquet":h,
        "crosssource_daily_precision_and_h5_residual_are_different_stock_dates":True,
        "reason_not_to_expand_same_precision_pilot":
            "two_price_tick_fit_not_a_physical_unit_proof",
        "required_before_real_h5_encoding":[
            "licensed_parquet_amount_volume_physical_unit_reference",
            "independent_hikyuu_h5_decoded_unit_baseline",
            "timestamp_alignment_and_adjustment_basis",
            "rounding_precision_and_integer_overflow_policy_on_real_samples",
            "source_provenance_and_source_level_conflict_handling",
        ],
        "physical_amount_unit_certified":False,
        "physical_volume_unit_certified":False,
        "real_float64_to_native_h5_precision_mapping_certified":False,
        "h5_parquet_universal_volume_factor_100_certified":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
        "original_market_files_modified":False,
    }


def run(precision_path,tdx_path,h5_path,out):
    destination=safe_path(out,False)
    sources=[safe_path(x,True) for x in (precision_path,tdx_path,h5_path)]
    if len({x.resolve() for x in (*sources,destination)})!=4:
        raise ValueError("Four distinct new/report paths required")
    docs=[]
    hashes=[]
    for source in sources:
        doc,sha=checked_safe(source)
        docs.append(doc)
        hashes.append(sha)
    safe=build(*docs)
    safe["input_report_sha256"]={
        "real_day_precision":hashes[0],
        "tdx_parquet_crosssource":hashes[1],
        "h5_parquet_crosssource":hashes[2],
    }
    with destination.open("x",encoding="utf-8") as f:
        json.dump(safe,f,ensure_ascii=False,indent=2)
        f.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--real-day-precision-safe",type=Path,required=True)
    p.add_argument("--tdx-parquet-safe",type=Path,required=True)
    p.add_argument("--h5-parquet-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--offline-reports-only",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        result=run(args.real_day_precision_safe,
                   args.tdx_parquet_safe,args.h5_parquet_safe,args.out)
        print("SAFE crosssource evidence bridge:",args.out)
        print("Real precision sample:",result["precision"]["two_real_stock_days_sampled"])
        print("Existing H5 vs Parquet residuals:",
              result["hikyuu_h5_vs_purchased_parquet"][
                  "any_field_candidate_conflict_bars"])
        print("Global physical units or production conversion certified: NO")
        print("Market source files read: NO")
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError):
        p.error("Invalid, missing, or unsafe existing SAFE report")


if __name__=="__main__":
    main()
