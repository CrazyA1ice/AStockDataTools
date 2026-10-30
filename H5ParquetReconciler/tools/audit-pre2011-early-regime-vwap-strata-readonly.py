#!/usr/bin/env python3
"""Read-only historical RAW 1990-96 VWAP factor regime by market and quarter.

Requires full21 original-H5 verified SNAPSHOT, all-year numeric profile, and
all-year prior VWAP factor SAFE. Only PRIVATE pre2011 native H5 RAW Parquets
are opened. Every source private file SHA/manifest is checked against full21.
No original H5, licensed Parquet, production files, dates, symbols or OHLCVA
values are output or modified. Grouping is for exploration, NOT unit approval.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
YEARS=tuple(range(1990,1997))
EXPECTED_ROWS=215238
FORMAT="AStockDataTools pre2011 early H5 RAW market-quarter factor strata v1"
ZERO_NAMES=("volume_nonzero_amount_zero",
            "volume_zero_amount_nonzero",
            "volume_and_amount_both_zero")


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,HERE/path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V=load("pre2011_prior_vwap_evidence",
       "audit-pre2011-private-raw-vwap-factors-readonly.py")
P=V.P
SINGLE=P.SINGLE


def prior_factor_safe(path,full_sha,profile_sha,full):
    """Reject partial/unsafe result or unbound prior-year factor counts."""
    p=Path(path)
    if (P.REPORTS.is_symlink() or p.is_symlink() or not p.is_file()
            or p.resolve().parent!=P.REPORTS.resolve()
            or not 0<p.stat().st_size<=200000):
        raise ValueError("Existing full21 historic candidate factor SAFE required")
    raw=p.read_bytes()
    doc=json.loads(raw)
    if (type(doc) is not dict or doc.get("format")!=V.FORMAT
            or doc.get("status")!="full21_private_raw_vwap_candidate_arithmetic_only_not_normalization"
            or doc.get("full21_source_safe_sha256")!=full_sha
            or doc.get("previous_numeric_profile_sha256")!=profile_sha
            or doc.get("years_audited")!=21
            or doc.get("rows_audited")!=P.TOTAL_ROWS
            or doc.get("candidate_scale_factors_raw_amount_times")!=list(V.FACTOR_GRID)
            or doc.get("candidate_factor_is_not_universal_or_production_approved") is not True
            or doc.get("original_h5_or_purchased_parquet_opened") is not False
            or doc.get("current_original_sources_requalified") is not False
            or doc.get("private_native_raw_modified") is not False
            or doc.get("production_or_private_active_modified") is not False
            or doc.get("historical_physical_units_or_corporate_actions_certified") is not False
            or doc.get("standardized_historical_parquet_created") is not False
            or doc.get("new_native_h5_mirror_created") is not False
            or doc.get("safe_contains_real_codes_dates_or_values") is not False
            or type(doc.get("per_year_aggregate")) is not list
            or len(doc["per_year_aggregate"])!=21
            or type(doc.get("total_factor_matches")) is not dict):
        raise ValueError("Full21 prior factor SAFE failed security or source SHA chain")
    factor_names=tuple(str(f) for f in V.FACTOR_GRID)
    previous={}
    for item,original in zip(doc["per_year_aggregate"],full["yearly"]):
        if (type(item) is not dict or item.get("year")!=original["year"]
                or item.get("rows")!=original["rows"]
                or type(item.get("eligible_positive_volume_amount_rows")) is not int
                or type(item.get("candidate_raw_amount_multiplier_hits")) is not dict
                or set(item["candidate_raw_amount_multiplier_hits"])!=set(factor_names)
                or type(item.get("zero_states_excluded_from_factor_counts")) is not dict
                or set(item["zero_states_excluded_from_factor_counts"])!=set(ZERO_NAMES)):
            raise ValueError("Prior all-year factor SAFE year/schema inconsistent")
        hits=item["candidate_raw_amount_multiplier_hits"]
        zeros=item["zero_states_excluded_from_factor_counts"]
        if (any(type(hits[k]) is not int or not 0<=hits[k]<=item[
                "eligible_positive_volume_amount_rows"] for k in factor_names)
                or any(type(zeros[k]) is not int or not 0<=zeros[k]<=original["rows"]
                       for k in ZERO_NAMES)
                or item["eligible_positive_volume_amount_rows"]+sum(
                    zeros.values())!=original["rows"]):
            raise ValueError("Prior full21 factor year counts inconsistent")
        previous[item["year"]]=item
    if (set(doc["total_factor_matches"])!=set(factor_names)
            or any(type(doc["total_factor_matches"][k]) is not int
                   or doc["total_factor_matches"][k]!=sum(previous[y][
                       "candidate_raw_amount_multiplier_hits"][k] for y in P.YEARS)
                   for k in factor_names)):
        raise ValueError("Prior factor totals do not match all years")
    return previous,hashlib.sha256(raw).hexdigest()


def inspect_year(file,year,expected):
    import pyarrow as pa
    import pyarrow.parquet as pq
    fields=SINGLE.FIELDS
    pf=pq.ParquetFile(file,memory_map=False,pre_buffer=False)
    buckets={}
    counts=Counter()
    count=0
    try:
        if (tuple(pf.schema_arrow.names)!=fields
                or pf.schema_arrow.field("symbol").type!=pa.string()
                or any(pf.schema_arrow.field(k).type!=pa.uint64()
                       for k in SINGLE.REQUIRED_NUMERIC)
                or pf.metadata.num_rows!=expected):
            raise ValueError("Historical early RAW schema or source row count changed")
        for batch in pf.iter_batches(batch_size=SINGLE.CHUNK,columns=list(fields)):
            if any(batch.column(i).null_count for i in range(len(fields))):
                raise ValueError("Historical private H5 RAW contains null column")
            for row in batch.to_pylist():
                symbol=row["symbol"]
                timestamp=row["datetime"]
                if (type(symbol) is not str or len(symbol)!=8
                        or symbol[:2] not in ("SH","SZ","BJ")
                        or not SINGLE.AUDIT.CORE.is_a_share_candidate(symbol,2010)
                        or any(type(row[name]) is not int or row[name]<0
                               for name in SINGLE.REQUIRED_NUMERIC)):
                    raise ValueError("Invalid native historical RAW record")
                date=SINGLE.AUDIT.date_key(timestamp)
                if date.year!=year:
                    raise ValueError("Early RAW row outside selected historical year")
                low,high=row["lowPrice"],row["highPrice"]
                op,cl=row["openPrice"],row["closePrice"]
                if not 0<low<=op<=high or not low<=cl<=high:
                    raise ValueError("Early RAW OHLC bounds or zero value invalid")
                quarter=(date.month-1)//3+1
                key=(symbol[:2],quarter)
                if key not in buckets:
                    buckets[key]=Counter()
                item=buckets[key]
                item["rows"]+=1
                counts["rows"]+=1
                if op==high==low==cl:
                    item["all_ohlc_equal"]+=1
                volume,amount=row["transCount"],row["transAmount"]
                if volume>0 and amount>0:
                    item["eligible_positive"]+=1
                    counts["eligible_positive"]+=1
                    hits=0
                    for factor in V.FACTOR_GRID:
                        if V.vwap_candidate_matches(
                                amount,volume,low,high,factor):
                            item["factor_"+str(factor)]+=1
                            counts["factor_"+str(factor)]+=1
                            hits+=1
                    if hits==0:
                        item["not_matched_any_factor"]+=1
                    if hits>1:
                        item["multiple_candidate_factors"]+=1
                else:
                    if volume>0:
                        flag="volume_nonzero_amount_zero"
                    elif amount>0:
                        flag="volume_zero_amount_nonzero"
                    else:
                        flag="volume_and_amount_both_zero"
                    item[flag]+=1
                    counts[flag]+=1
                count+=1
                if count>expected:
                    raise ValueError("Early historical private row budget exceeded")
        if count!=expected:
            raise ValueError("Incomplete early historical native RAW year")
    finally:
        pf.close()
    all_names=["rows","all_ohlc_equal","eligible_positive",
               *ZERO_NAMES,"not_matched_any_factor","multiple_candidate_factors",
               *("factor_"+str(f) for f in V.FACTOR_GRID)]
    strata=[
        {"market":market,"quarter":quarter,
         **{name:int(buckets[(market,quarter)][name]) for name in all_names}}
        for market,quarter in sorted(buckets)
    ]
    return {
        "year":year,"rows":count,
        "eligible_positive_volume_amount_rows":int(counts["eligible_positive"]),
        "excluded_zero_state_counts":{name:int(counts[name]) for name in ZERO_NAMES},
        "candidate_factor_match_counts":{
            str(f):int(counts["factor_"+str(f)]) for f in V.FACTOR_GRID},
        "market_quarter_strata":strata,
    }


def run(full21_safe,profile_safe,factor_safe,out):
    full,full_sha=P.source_safe(full21_safe)
    numeric,profile_sha=V.EARLY.require_early_profile(profile_safe,full_sha,full)
    factor,factor_sha=prior_factor_safe(factor_safe,full_sha,profile_sha,full)
    target=P.target_safe(out)
    entries=P.verified_private_files(full)
    results=[]
    for year,file,expected,sha in entries:
        if year not in YEARS:
            continue
        before=(file.stat().st_size,file.stat().st_mtime_ns)
        result=inspect_year(file,year,expected)
        if ((file.stat().st_size,file.stat().st_mtime_ns)!=before
                or SINGLE.hash_file(file)!=sha):
            raise ValueError("Early RAW SHA changed during read-only audit")
        if (result["eligible_positive_volume_amount_rows"]!=factor[year][
                "eligible_positive_volume_amount_rows"]
                or result["candidate_factor_match_counts"]!=factor[year][
                    "candidate_raw_amount_multiplier_hits"]
                or result["excluded_zero_state_counts"]!=factor[year][
                    "zero_states_excluded_from_factor_counts"]
                or result["excluded_zero_state_counts"]!={name:numeric[year][name]
                    for name in ZERO_NAMES}
                or sum(x["all_ohlc_equal"] for x in result[
                    "market_quarter_strata"])!=numeric[year][
                    "open_high_low_close_all_equal"]):
            raise ValueError("Market-quarter strata contradict verified annual SAFE")
        results.append(result)
    total=sum(x["rows"] for x in results)
    if len(results)!=len(YEARS) or total!=EXPECTED_ROWS:
        raise ValueError("Historical seven-year 1990-1996 bounded row count mismatch")
    result={
        "format":FORMAT,
        "status":"early_historical_private_raw_market_quarter_factor_candidates_only",
        "selected_years":list(YEARS),
        "rows_stratified":total,
        "full21_source_safe_sha256":full_sha,
        "prior_numeric_profile_safe_sha256":profile_sha,
        "prior_all_year_factor_safe_sha256":factor_sha,
        "years":results,
        "total_candidate_factor_hits":{
            str(f):sum(x["candidate_factor_match_counts"][str(f)]
                       for x in results) for f in V.FACTOR_GRID},
        "private_source_sha_chain_verified_for_21_years":True,
        "original_h5_or_purchased_parquet_opened":False,
        "private_raw_or_original_market_sources_modified":False,
        "production_or_active_pointer_modified":False,
        "physical_units_corporate_actions_or_securities_certified":False,
        "standardized_purchased_parquet_or_h5_created":False,
        "output_excludes_individual_stock_date_ohlcva":True,
    }
    with target.open("x",encoding="utf-8") as handle:
        json.dump(result,handle,sort_keys=True,ensure_ascii=False,indent=2)
        handle.write("\n")
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full21-safe",type=Path,required=True)
    parser.add_argument("--numeric-profile-safe",type=Path,required=True)
    parser.add_argument("--factor-safe",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--read-only-private-raw",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        result=run(args.full21_safe,args.numeric_profile_safe,args.factor_safe,args.out)
        print("1990-1996 RAW only market-quarter factor strata:",
              result["rows_stratified"],"rows")
        print("No physical units certified, no original sources opened.")
        print("SAFE:",args.out)
    except (ValueError,KeyError,TypeError,OSError,OverflowError,ImportError,
            ModuleNotFoundError,json.JSONDecodeError):
        parser.error("Early historical RAW factor strata refused; no market write")


if __name__=="__main__":
    main()
