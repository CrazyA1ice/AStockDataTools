#!/usr/bin/env python3
"""Read-only two-stock-day amount residual diagnostic, NOT a rounding policy.

Never creates real H5 or writes to purchased Parquet/H5/market SQLite.
Checks existing same-day SAFE as well as the 10-stockday candidate report.
No amount, integer raw record, per-symbol values or source paths are exported.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "bounded_native_integer_pilot",HERE/"audit-real-pq-to-native-h5-raw-exactness-readonly.py")
EXACT=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXACT)
PAIR=EXACT.PAIR
FORMAT="AStockDataTools bounded real daily amount residual candidate triage v1"
DAY="2026-09-30"
MAX_SAFE_BYTES=200000
ABS_BUCKETS=("zero","le_0p01","le_0p1","le_0p5","le_1","gt_1")


def check_previous_exactness(path,ten_sha):
    source=PAIR.AUDIT._path(path,True)
    payload=source.read_bytes()
    if not 0<len(payload)<=MAX_SAFE_BYTES:
        raise ValueError("Bounded previous real exactness SAFE required")
    try:
        info=json.loads(payload)
    except (ValueError,UnicodeError):
        raise ValueError("Malformed previous exactness SAFE") from None
    if (type(info) is not dict or info.get("format")!=EXACT.FORMAT
            or info.get("sample_period")!="day" or info.get("sample_day")!=DAY
            or info.get("sample_stock_days")!=2
            or info.get("original_hikyuu_h5_records_read")!=2
            or info.get("prior_ten_stockday_evidence_sha256")!=ten_sha
            or info.get("source_stat_before_after_unchanged") is not True
            or info.get("raw_real_prices_quantities_timestamps_or_paths_exported") is not False
            or info.get("raw_native_h5_integer_values_exported") is not False
            or info.get("no_h5_parquet_or_market_sqlite_writes") is not True
            or info.get("ready_for_full_market_mirror") is not False
            or info.get("ready_to_modify_purchased_parquet_or_original_h5") is not False
            or info.get("real_float64_to_native_h5_mapping_certified") is not False
            or info.get("licensed_parquet_physical_units_certified") is not False):
        raise ValueError("Previous fixed-date exactness SAFE is not admissible")
    counts=info.get("candidate_raw_integer_field_counts")
    if type(counts) is not dict or set(counts)!=set(EXACT.FIELDS):
        raise ValueError("Previous amount and OHLCVA counts missing")
    for field,stats in counts.items():
        if (type(stats) is not dict or stats.get("sample_pairs")!=2
                or stats.get("positive_nonzero_pairs")!=2
                or stats.get("both_zero_pairs")!=0 or stats.get("one_zero_pairs")!=0
                or stats.get("native_integer_range_overflow_count")!=0
                or stats.get("positive_exact_raw_integer_matches_count")!=
                    (0 if field=="amount" else 2)
                or stats.get("shortest_decimal_requires_rounding_count")!=
                    (2 if field=="amount" else 0)):
            raise ValueError("Earlier amount rounding anomaly not reproduced in SAFE")
    return hashlib.sha256(payload).hexdigest()


def one_amount(value,raw_h5):
    checked=EXACT.classify_pair(value,raw_h5,"amount")
    if not checked["positive_nonzero"] or checked["range_overflow"]:
        raise ValueError("Require positive bounded source amount pairs")
    # IMPORTANT: candidate is the raw-H5 integer numerical hypothesis.
    # Do not interpret 1000 as a currency unit; no candidate rounded value
    # ever leaves this function.
    candidate=Decimal(str(value))/Decimal(1000)
    target=Decimal(raw_h5)
    diff=candidate-target
    magnitude=abs(diff)
    boundaries=(("zero",Decimal(0)),
                ("le_0p01",Decimal("0.01")),
                ("le_0p1",Decimal("0.1")),
                ("le_0p5",Decimal("0.5")),
                ("le_1",Decimal(1)))
    bucket=next((key for key,limit in boundaries if magnitude<=limit),"gt_1")
    relative=magnitude/max(candidate,target)
    nearest=int(candidate.to_integral_value(rounding=ROUND_HALF_EVEN))
    floor=int(candidate.to_integral_value(rounding=ROUND_FLOOR))
    ceil=int(candidate.to_integral_value(rounding=ROUND_CEILING))
    return {
        "abs_residual_bucket":bucket,
        "candidate_above_native_raw":diff>0,
        "candidate_below_native_raw":diff<0,
        "nearest_half_even_matches_raw":nearest==raw_h5,
        "floor_matches_raw":floor==raw_h5,
        "ceiling_matches_raw":ceil==raw_h5,
        "existing_relative_tolerance_1e_minus_5":relative<=Decimal("0.00001"),
        "candidate_requires_rounding":checked["decimal_requires_rounding"],
        "candidate_exactly_equals_raw":checked["exact_raw_match"],
    }


def aggregate(parquet,h5):
    if (type(parquet) is not dict or type(h5) is not dict
            or set(parquet)!=set(PAIR.SYMBOLS) or set(h5)!=set(PAIR.SYMBOLS)):
        raise ValueError("Must have exactly two matching source stock-days")
    counts={
        "sample_positive_pairs":0,
        "would_require_decimal_rounding":0,
        "candidate_exact_original_h5_integer_count":0,
        "nearest_half_even_matches_original_count":0,
        "floor_matches_original_count":0,
        "ceiling_matches_original_count":0,
        "within_previous_relative_tolerance_count":0,
        "candidate_above_original_count":0,
        "candidate_below_original_count":0,
        "absolute_integer_candidate_residual_buckets":{b:0 for b in ABS_BUCKETS},
    }
    for symbol in PAIR.SYMBOLS:
        record=h5[symbol]
        row=parquet[symbol]
        if (type(row) is not dict or set(row)!=set(PAIR.FIELDS)
                or type(record) is not dict or set(record)!=set(PAIR.RAW)
                or type(record.get("datetime")) is not int
                or record["datetime"]!=202609300000):
            raise ValueError("Invalid paired daily amount record")
        result=one_amount(row["amount"],record["transAmount"])
        counts["sample_positive_pairs"]+=1
        for source,dest in (
            ("candidate_requires_rounding","would_require_decimal_rounding"),
            ("candidate_exactly_equals_raw","candidate_exact_original_h5_integer_count"),
            ("nearest_half_even_matches_raw","nearest_half_even_matches_original_count"),
            ("floor_matches_raw","floor_matches_original_count"),
            ("ceiling_matches_raw","ceiling_matches_original_count"),
            ("existing_relative_tolerance_1e_minus_5","within_previous_relative_tolerance_count"),
            ("candidate_above_native_raw","candidate_above_original_count"),
            ("candidate_below_native_raw","candidate_below_original_count")):
            counts[dest]+=int(result[source])
        counts["absolute_integer_candidate_residual_buckets"][
            result["abs_residual_bucket"]]+=1
    if counts["would_require_decimal_rounding"]!=2:
        raise ValueError("Real amount result contradicts existing SAFE evidence")
    return counts


def run(purchased_root,h5_root,day,ten_safe,exactness_safe,out):
    destination=PAIR.AUDIT._path(out,False)
    if day!=DAY:
        raise ValueError("Only known same-day two-stock read-only scope allowed")
    ten_sha=EXACT.qualified_prior(ten_safe)
    exact_sha=check_previous_exactness(exactness_safe,ten_sha)
    pq_path=PAIR.DAY.FOOTER.selected_file(
        purchased_root,"day/2026-09.parquet","day")
    h5_paths=[PAIR._plain_h5_path(h5_root,s) for s in PAIR.SYMBOLS]
    def stat_key(p):
        stat=p.stat()
        return (stat.st_size,stat.st_mtime_ns)
    source_before={path:stat_key(path) for path in (pq_path,*h5_paths)}
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    import h5py
    import numpy as np
    bars,scanned,groups=PAIR.DAY._read_bounded_daily(
        pq_path,DAY,pa,pq,pc)
    records={symbol:PAIR._read_single_h5(h5_root,symbol,DAY,h5py,np)
             for symbol in PAIR.SYMBOLS}
    # Re-run all fields' previous exactness result, not just amount.
    # This guards against mismatched H5/Parquet source versions.
    now=EXACT.summarize(bars,records)
    old=json.loads(PAIR.AUDIT._path(exactness_safe,True).read_text(encoding="utf-8"))
    if now!=old["candidate_raw_integer_field_counts"]:
        raise ValueError("Paired market data no longer match previous exactness SAFE")
    amount=aggregate(bars,records)
    if any(stat_key(path)!=before for path,before in source_before.items()):
        raise ValueError("Market source changed during bounded read")
    if (EXACT.qualified_prior(ten_safe)!=ten_sha
            or check_previous_exactness(exactness_safe,ten_sha)!=exact_sha):
        raise ValueError("Previous SAFE proof changed during read")
    safe={
        "format":FORMAT,
        "scope":"two previously verified daily stock-days only",
        "trading_day":DAY,
        "amount_native_integer_candidate_is_purchased_amount_divided_by":"1000",
        "amount_residual_counts":amount,
        "parquet_scanned_source_rows_bounded":scanned,
        "parquet_row_groups_scanned":groups,
        "h5_target_day_records_read":2,
        "previous_ten_stockday_safe_sha256":ten_sha,
        "previous_exactness_safe_sha256":exact_sha,
        "source_file_stat_unchanged":True,
        "prior_exactness_counts_reverified":True,
        "no_source_values_raw_integers_symbols_or_absolute_paths_exported":True,
        "hypothetical_rounding_is_not_an_approved_policy":True,
        "original_source_parquet_h5_or_sqlite_written":False,
        "real_h5_written":False,
        "vendor_amount_physical_units_certified":False,
        "lossless_native_h5_amount_conversion_certified":False,
        "ready_for_full_market_mirror":False,
        "ready_to_modify_purchased_parquet_or_original_h5":False,
    }
    with destination.open("x",encoding="utf-8") as stream:
        json.dump(safe,stream,ensure_ascii=False,indent=2,sort_keys=True)
        stream.write("\n")
    return safe


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purchased-root",type=Path,required=True)
    parser.add_argument("--h5-root",type=Path,required=True)
    parser.add_argument("--day",required=True)
    parser.add_argument("--ten-safe",type=Path,required=True)
    parser.add_argument("--exactness-safe",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--read-only-amount-residual",action="store_true",required=True)
    a=parser.parse_args(argv)
    try:
        result=run(a.purchased_root,a.h5_root,a.day,
                   a.ten_safe,a.exactness_safe,a.out)
        print("SAFE daily amount residual candidate diagnostics:",a.out)
        print("Positive paired stock-days:",result["amount_residual_counts"]["sample_positive_pairs"])
        print("Real H5 or original Parquet written: NO")
        print("Rounding policy or physical amount units certified: NO")
    except (ValueError,KeyError,TypeError,OSError,ImportError,
            OverflowError,json.JSONDecodeError):
        parser.error("Fixed two-stock amount residual read-only check failed; no market writes")


if __name__=="__main__":
    main()
