#!/usr/bin/env python3
"""Bounded, read-only real daily Parquet -> native H5 raw INTEGER feasibility.

This is NOT a real-market H5 writer and never approves physical vendor units.
It only tests whether the prior candidate factors, applied to two fixed real
Parquet stock-days, reproduce the matching raw integers in existing Hikyuu H5.
The same pair has already passed the independent real native C++ canary.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

HERE=Path(__file__).resolve().parent
S=importlib.util.spec_from_file_location(
    "real_pq_h5_raw_pair_reader",
    HERE/"probe-real-parquet-h5-day-unit-factors-readonly.py")
PAIR=importlib.util.module_from_spec(S)
S.loader.exec_module(PAIR)

FORMAT="AStockDataTools real daily Parquet to Hikyuu raw integer candidate exactness v1"
PRIOR_FORMAT="AStockDataTools Parquet-primary independent-year daily sample evidence gate v1"
DATE="2026-09-30"
FIELDS=("open","high","low","close","amount","volume")
RAW={
    "open":"openPrice","high":"highPrice","low":"lowPrice",
    "close":"closePrice","amount":"transAmount","volume":"transCount",
}
# Exactly the REAL-SAMPLE candidate relationship, not the Hikyuu-decoded
# synthetic units: Parquet approx H5 integer*1000 (amount) / *100 (volume).
# Therefore the hypothetical raw native fields would be Parquet/1000, /100.
SCALES={
    "open":("1000",Fraction(1000,1)),
    "high":("1000",Fraction(1000,1)),
    "low":("1000",Fraction(1000,1)),
    "close":("1000",Fraction(1000,1)),
    "amount":("0.001",Fraction(1,1000)),
    "volume":("0.01",Fraction(1,100)),
}
MAXIMUM={f:((1<<32)-1 if f in ("open","high","low","close")
             else (1<<64)-1) for f in FIELDS}
MAX_SAFE_BYTES=200000


def qualified_prior(path):
    source=PAIR.AUDIT._path(path,True)
    raw=source.read_bytes()
    if not 0<len(raw)<=MAX_SAFE_BYTES:
        raise ValueError("Bounded ten-stockday SAFE evidence missing")
    try:
        prior=json.loads(raw)
    except (ValueError,UnicodeError):
        raise ValueError("Malformed prior daily SAFE proof") from None
    true_fields={
        "sample_numeric_factor_candidate_supported":True,
        "raw_ohlcva_h5_integer_or_source_paths_exported":False,
        "market_source_opened_or_modified_by_this_audit":False,
        "native_cpp_tested_on_crossyear_holdouts":False,
        "vendor_amount_physical_units_certified":False,
        "vendor_volume_physical_units_certified":False,
        "adjustment_and_timestamps_certified":False,
        "universal_period_factor_certified":False,
        "licensed_parquet_to_native_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
        "ready_to_modify_parquet_primary_source":False,
    }
    if (type(prior) is not dict or prior.get("format")!=PRIOR_FORMAT
            or any(prior.get(field) is not value
                   for field,value in true_fields.items())
            or prior.get("source_discovery_stock_days")!=2
            or prior.get("same_month_holdout_stock_days")!=4
            or prior.get("crossyear_holdout_stock_days")!=4
            or prior.get("total_distinct_daily_stock_days_with_candidate_factor_matches")!=10
            or prior.get("native_hikyuu_281_cpp_verified_real_stock_days")!=2
            or prior.get("positive_volume_factor100_sample_count")!=10
            or prior.get("positive_amount_factor1000_sample_count")!=10
            or prior.get("all_four_ohlc_raw_div1000_sample_count_per_field")!=10
            or prior.get("candidate_raw_h5_price_divide")!=1000
            or prior.get("candidate_raw_h5_amount_multiply")!=1000
            or prior.get("candidate_raw_h5_volume_multiply")!=100
            or type(prior.get("five_safe_sha256")) is not dict
            or set(prior["five_safe_sha256"])!={
                "real_raw_stock_day","real_native_stock_day","same_month_heldout",
                "annual_2025_key_only","crossyear_holdout"}
            or any(type(s) is not str or not re.fullmatch("[0-9a-f]{64}",s)
                   for s in prior["five_safe_sha256"].values())):
        raise ValueError("Ten-stockday candidate-only SAFE evidence not qualified")
    return hashlib.sha256(raw).hexdigest()


def classify_pair(value,raw_integer,field):
    """Only counts/statistics escape. No raw candidate integers are exported."""
    if (type(value) is not float or not math.isfinite(value) or value<0
            or type(raw_integer) is not int or raw_integer<0
            or raw_integer>MAXIMUM[field]):
        raise ValueError("Invalid real candidate pair")
    decimal_scale,rational_scale=SCALES[field]
    shortest=Decimal(str(value))*Decimal(decimal_scale)
    binary=Fraction.from_float(value)*rational_scale
    maximum=MAXIMUM[field]
    bounded=shortest<=maximum
    decimal_exact=bounded and shortest==shortest.to_integral_value()
    binary_exact=binary.denominator==1 and 0<=binary.numerator<=maximum
    positive=value>0 and raw_integer>0
    return {
        "positive_nonzero":positive,
        "both_zero":value==0 and raw_integer==0,
        "one_zero":(value==0)!=(raw_integer==0),
        "decimal_tick_exact":decimal_exact,
        "binary64_tick_exact":binary_exact,
        "decimal_requires_rounding":bounded and not decimal_exact,
        "range_overflow":not bounded,
        "exact_raw_match":positive and decimal_exact and int(shortest)==raw_integer,
    }


def summarize(parquet,h5):
    if (type(parquet) is not dict or type(h5) is not dict
            or set(parquet)!=set(PAIR.SYMBOLS) or set(h5)!=set(PAIR.SYMBOLS)):
        raise ValueError("Require exact selected real paired stock-days")
    counts={f:{key:0 for key in (
        "sample_pairs","positive_nonzero_pairs","both_zero_pairs",
        "one_zero_pairs","shortest_decimal_tick_exact_count",
        "binary64_tick_exact_count","shortest_decimal_requires_rounding_count",
        "native_integer_range_overflow_count",
        "positive_exact_raw_integer_matches_count")} for f in FIELDS}
    for sym in PAIR.SYMBOLS:
        row,record=parquet[sym],h5[sym]
        if (type(row) is not dict or set(row)!=set(PAIR.FIELDS)
                or type(record) is not dict or set(record)!=set(PAIR.RAW)
                or type(record["datetime"]) is not int
                or record["datetime"]!=202609300000):
            raise ValueError("Unexpected source row or native date key")
        for field in FIELDS:
            c=classify_pair(row[field],record[RAW[field]],field)
            stats=counts[field]
            stats["sample_pairs"]+=1
            for label,source in (
                ("positive_nonzero_pairs","positive_nonzero"),
                ("both_zero_pairs","both_zero"),
                ("one_zero_pairs","one_zero"),
                ("shortest_decimal_tick_exact_count","decimal_tick_exact"),
                ("binary64_tick_exact_count","binary64_tick_exact"),
                ("shortest_decimal_requires_rounding_count","decimal_requires_rounding"),
                ("native_integer_range_overflow_count","range_overflow"),
                ("positive_exact_raw_integer_matches_count","exact_raw_match")):
                stats[label]+=int(c[source])
    return counts


def run(purchased_root,h5_root,day,prior_safe,out):
    destination=PAIR.AUDIT._path(out,False)
    if day!=DATE:
        raise ValueError("Only the previously native-validated fixed day is allowed")
    proof_sha=qualified_prior(prior_safe)
    pq_path=PAIR.DAY.FOOTER.selected_file(
        purchased_root,"day/2026-09.parquet","day")
    h5_paths=[PAIR._plain_h5_path(h5_root,sym) for sym in PAIR.SYMBOLS]
    def source_state(p):
        stat=p.stat()
        return stat.st_size,stat.st_mtime_ns
    before={p:source_state(p) for p in (pq_path,*h5_paths)}
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    import numpy as np
    import h5py

    bars,scanned,groups=PAIR.DAY._read_bounded_daily(
        pq_path,DATE,pa,pq,pc)
    records={sym:PAIR._read_single_h5(h5_root,sym,DATE,h5py,np)
             for sym in PAIR.SYMBOLS}
    counts=summarize(bars,records)
    if any(source_state(p)!=old for p,old in before.items()):
        raise ValueError("Real market file stat changed during read-only sample")
    if qualified_prior(prior_safe)!=proof_sha:
        raise ValueError("Prior ten-stockday SAFE changed during sample")
    safe={
        "format":FORMAT,
        "sample_period":"day",
        "sample_day":DATE,
        "sample_stock_days":2,
        "parquet_source_rows_scanned":scanned,
        "parquet_source_rowgroups_scanned":groups,
        "original_hikyuu_h5_records_read":2,
        "candidate_h5_raw_integer_scale_from_purchased_float":{
            field:SCALES[field][0] for field in FIELDS},
        "candidate_raw_integer_field_counts":counts,
        "prior_ten_stockday_evidence_sha256":proof_sha,
        "source_stat_before_after_unchanged":True,
        "raw_real_prices_quantities_timestamps_or_paths_exported":False,
        "raw_native_h5_integer_values_exported":False,
        "sample_shortest_decimal_is_not_original_vendor_decimal":True,
        "binary64_and_shortest_decimal_separately_tested":True,
        "no_h5_parquet_or_market_sqlite_writes":True,
        "licensed_parquet_physical_units_certified":False,
        "real_float64_to_native_h5_mapping_certified":False,
        "source_adjustment_or_time_semantics_certified":False,
        "all_market_periods_certified":False,
        "ready_for_full_market_mirror":False,
        "ready_to_modify_purchased_parquet_or_original_h5":False,
    }
    with destination.open("x",encoding="utf-8") as stream:
        json.dump(safe,stream,indent=2,ensure_ascii=False,sort_keys=True)
        stream.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--purchased-root",type=Path,required=True)
    p.add_argument("--h5-root",type=Path,required=True)
    p.add_argument("--day",required=True)
    p.add_argument("--prior-ten-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-native-int-preview",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        result=run(args.purchased_root,args.h5_root,args.day,
                   args.prior_ten_safe,args.out)
        print("SAFE native raw daily integer feasibility:",args.out)
        print("Paired real daily samples:",result["sample_stock_days"])
        print("Source writes or real H5 encoding: NO")
        print("Production scale mapping certified: NO")
    except (ValueError,TypeError,OSError,KeyError,ImportError,
            OverflowError,json.JSONDecodeError):
        p.error("Bounded candidate native integer sample refused; no H5 written")


if __name__=="__main__":
    main()
