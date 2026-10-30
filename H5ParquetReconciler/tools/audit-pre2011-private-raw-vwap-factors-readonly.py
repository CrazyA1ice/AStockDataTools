#!/usr/bin/env python3
"""Historical RAW turnover/quantity/price numeric coherence hypotheses, read-only.

Existing independently observed modern paired H5/PQ SAMPLE candidates yield
PQ amount ~= native H5 transAmount*1000, volume ~= transCount*100,
price ~= native H5 integer price/1000; hence hypothetical RAW implied
VWAP-scale factor: amount*10000/volume vs original RAW lowPrice..highPrice.

Compare this factor with alternatives, never certify physical units, recover
status, vendor schema, correctness of prices or a normalized output.
Reads only previously SHA-qualified PRIVATE RAW Parquets (1990..2010) and
prior sanitized SAFE; never touches real purchased/H5 market sources.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
YEARS=tuple(range(1990,2011))
FACTOR_GRID=(1,10,100,1000,10000,100000)
# Candidate VWAP within RAW daily OHLC band expanded 0.5% each edge
TOL_NUM=5
TOL_DEN=1000
FORMAT="AStockDataTools historical private H5 RAW VWAP arithmetic candidate matrix v1"


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


EARLY=load("raw_historical_prior_aggregate_gate",
           "audit-pre2011-early-zero-amount-strata-readonly.py")
P=EARLY.P
SINGLE=P.SINGLE


def vwap_candidate_matches(raw_amount,raw_volume,raw_low,raw_high,factor):
    """Exact nonnegative Python integer arithmetic; no uint64 multiplication overflow.

    This is only a NUMERIC factor hypothesis, not a unit conversion approval.
    """
    if (any(type(v) is not int or v<0 for v in (
            raw_amount,raw_volume,raw_low,raw_high,factor))
            or not 0<raw_low<=raw_high or raw_amount<=0
            or raw_volume<=0 or factor not in FACTOR_GRID):
        return False
    x=raw_amount*factor*TOL_DEN
    minimum=raw_volume*raw_low*(TOL_DEN-TOL_NUM)
    maximum=raw_volume*raw_high*(TOL_DEN+TOL_NUM)
    return minimum<=x<=maximum


def scan_year(file,year,expected):
    import pyarrow as pa
    import pyarrow.parquet as pq
    fields=("lowPrice","highPrice","transCount","transAmount")
    f=pq.ParquetFile(file,memory_map=False,pre_buffer=False)
    count=0
    positive=0
    zero_states=Counter()
    hits=Counter()
    overlaps=0
    try:
        if (tuple(f.schema_arrow.names)!=SINGLE.FIELDS
                or f.schema_arrow.field("symbol").type!=pa.string()
                or any(f.schema_arrow.field(k).type!=pa.uint64()
                       for k in SINGLE.REQUIRED_NUMERIC)
                or f.metadata.num_rows!=expected):
            raise ValueError("Private RAW year schema/row count differs from source SAFE")
        for batch in f.iter_batches(batch_size=SINGLE.CHUNK,columns=list(fields)):
            if any(batch.column(i).null_count for i in range(4)):
                raise ValueError("Unexpected null in historical RAW H5 integer column")
            for low,high,volume,amount in zip(*[
                    batch.column(i).to_pylist() for i in range(4)]):
                if (type(low) is not int or type(high) is not int
                        or not 0<low<=high
                        or type(volume) is not int or volume<0
                        or type(amount) is not int or amount<0):
                    raise ValueError("Bad native H5 RAW numeric structure")
                if volume and amount:
                    positive+=1
                    count_hit=0
                    for factor in FACTOR_GRID:
                        if vwap_candidate_matches(amount,volume,low,high,factor):
                            hits[str(factor)]+=1
                            count_hit+=1
                    overlaps+=int(count_hit>1)
                elif volume:
                    zero_states["volume_nonzero_amount_zero"]+=1
                elif amount:
                    zero_states["volume_zero_amount_nonzero"]+=1
                else:
                    zero_states["volume_and_amount_both_zero"]+=1
                count+=1
                if count>expected:
                    raise ValueError("Private RAW yearly scan exceeded recorded row budget")
        if count!=expected:
            raise ValueError("Private RAW yearly scan incomplete")
    finally:
        f.close()
    return {
        "year":year,
        "rows":count,
        "eligible_positive_volume_amount_rows":positive,
        "zero_states_excluded_from_factor_counts":{
            k:int(zero_states[k]) for k in (
                "volume_nonzero_amount_zero",
                "volume_zero_amount_nonzero",
                "volume_and_amount_both_zero")},
        "candidate_raw_amount_multiplier_hits":{
            str(factor):int(hits[str(factor)]) for factor in FACTOR_GRID},
        "multiple_candidate_factors_match_same_row":overlaps,
    }


def run(full21_safe,numeric_profile_safe,out):
    full,full_sha=P.source_safe(full21_safe)
    prior,profile_sha=EARLY.require_early_profile(
        numeric_profile_safe,full_sha,full)
    target=P.target_safe(out)
    entries=P.verified_private_files(full)
    if [entry[0] for entry in entries]!=list(YEARS):
        raise ValueError("Full 21-year private H5 RAW stages not qualified")
    rows=[]
    for year,file,expected,file_sha in entries:
        before=(file.stat().st_size,file.stat().st_mtime_ns)
        result=scan_year(file,year,expected)
        if ((file.stat().st_size,file.stat().st_mtime_ns)!=before
                or SINGLE.hash_file(file)!=file_sha):
            raise ValueError("Verified private source RAW changed during factor scan")
        original=prior[year]
        if any(result["zero_states_excluded_from_factor_counts"][key]!=
               original[key] for key in result["zero_states_excluded_from_factor_counts"]):
            raise ValueError("Prior full21 numeric zero-state profile contradicted")
        n=result["eligible_positive_volume_amount_rows"]
        if n+sum(result["zero_states_excluded_from_factor_counts"].values())!=expected:
            raise ValueError("Incorrect historical RAW numeric partition")
        rows.append(result)
    totals={str(factor):sum(x["candidate_raw_amount_multiplier_hits"][
        str(factor)] for x in rows) for factor in FACTOR_GRID}
    result={
        "format":FORMAT,
        "status":"full21_private_raw_vwap_candidate_arithmetic_only_not_normalization",
        "full21_source_safe_sha256":full_sha,
        "previous_numeric_profile_sha256":profile_sha,
        "years_audited":21,
        "rows_audited":sum(x["rows"] for x in rows),
        "positive_volume_amount_rows_eligible":sum(x[
            "eligible_positive_volume_amount_rows"] for x in rows),
        "candidate_scale_factors_raw_amount_times":list(FACTOR_GRID),
        "tolerance_parts_per_thousand":TOL_NUM,
        "per_year_aggregate":rows,
        "total_factor_matches":totals,
        "rows_matching_multiple_factors":sum(x[
            "multiple_candidate_factors_match_same_row"] for x in rows),
        "original_h5_or_purchased_parquet_opened":False,
        "current_original_sources_requalified":False,
        "private_native_raw_modified":False,
        "production_or_private_active_modified":False,
        "historical_physical_units_or_corporate_actions_certified":False,
        "standardized_historical_parquet_created":False,
        "new_native_h5_mirror_created":False,
        "safe_contains_real_codes_dates_or_values":False,
        "candidate_factor_is_not_universal_or_production_approved":True,
    }
    if result["rows_audited"]!=P.TOTAL_ROWS:
        raise ValueError("21-year RAW aggregate count disagrees with source snapshot")
    with target.open("x",encoding="utf-8") as handle:
        json.dump(result,handle,sort_keys=True,ensure_ascii=False,indent=2)
        handle.write("\n")
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full21-safe",type=Path,required=True)
    parser.add_argument("--numeric-profile-safe",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--read-only-private-raw",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        r=run(args.full21_safe,args.numeric_profile_safe,args.out)
        print("PRIVATE 21-YEAR RAW numeric candidate matrix:",
              r["rows_audited"],"rows.")
        print("No source H5/Parquet opened; NO physical units certified.")
        print("SAFE:",args.out)
    except (ValueError,TypeError,KeyError,OSError,OverflowError,ImportError,
            ModuleNotFoundError,json.JSONDecodeError):
        parser.error("Historical RAW ratio evidence refused; no writes to market data")


if __name__=="__main__":
    main()
