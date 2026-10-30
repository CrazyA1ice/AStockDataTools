#!/usr/bin/env python3
"""Drill into 1990-1993 private H5 RAW zero-quantity/amount records, READ ONLY.

Requires the already qualified 21-year all-values RAW SAFE and derived numeric
aggregate SAFE. Checks private 21-year manifests and hashes; streams ONLY four
early-year PRIVATE RAW Parquets. No original H5 or purchased Parquet is opened.
Report only year/market/zero-state/flat-OHLC aggregate counts, never stocks or
dates or raw prices/quantities/amounts. No conversion rule is authorized.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
YEARS=(1990,1991,1992,1993)
STATES=("both_positive","volume_positive_amount_zero",
        "volume_zero_amount_positive","both_zero")
FORMAT="AStockDataTools pre2011 early amount-volume zero aggregate stratum audit v1"
EXPECTED_ROWS=28325


def load():
    spec=importlib.util.spec_from_file_location(
        "pre2011_raw_early_numerical_aggregate_prerequisite",
        HERE/"audit-pre2011-raw-numeric-profile-readonly.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P=load()
SINGLE=P.SINGLE


def require_early_profile(path,full_sha,full):
    p=Path(path)
    if (P.REPORTS.is_symlink() or p.is_symlink() or not p.is_file()
            or p.resolve().parent!=P.REPORTS.resolve()
            or not 0<p.stat().st_size<=200000):
        raise ValueError("Previously completed private RAW profile SAFE required")
    raw=p.read_bytes()
    doc=json.loads(raw)
    if (type(doc) is not dict or doc.get("format")!=P.FORMAT
            or doc.get("status")!="historical_raw_numeric_diagnostics_only_not_units_certification"
            or doc.get("verified_full21_source_safe_sha256")!=full_sha
            or doc.get("verified_full21_snapshot_rows")!=P.TOTAL_ROWS
            or doc.get("years_scanned")!=21
            or doc.get("private_raw_rows_profiled")!=P.TOTAL_ROWS
            or doc.get("original_h5_or_purchased_parquet_opened") is not False
            or doc.get("original_sources_rechecked_live_during_this_profile") is not False
            or doc.get("private_raw_stage_modified") is not False
            or doc.get("production_or_active_pointer_modified") is not False
            or doc.get("normalized_purchased_day_parquet_created") is not False
            or doc.get("historical_units_certified") is not False
            or doc.get("historical_security_master_or_adjustment_basis_certified") is not False
            or doc.get("ready_for_production_query_or_h5_mirror") is not False
            or doc.get("raw_stock_codes_dates_and_ohlcva_excluded_from_safe") is not True
            or type(doc.get("yearly_aggregate_counts")) is not list
            or len(doc["yearly_aggregate_counts"])!=21):
        raise ValueError("Previous 21-year RAW numeric profile SAFE is not qualified")
    base={}
    for item,source in zip(doc["yearly_aggregate_counts"],full["yearly"]):
        if (type(item) is not dict or item.get("year")!=source["year"]
                or item.get("rows")!=source["rows"]
                or any(type(item.get(k)) is not int or not 0<=item[k]<=item["rows"]
                       for k in (
                       "open_high_low_close_all_equal","volume_and_amount_both_zero",
                       "volume_nonzero_amount_zero","volume_zero_amount_nonzero"))):
            raise ValueError("Numerical profile year/counts disagree with full21")
        base[source["year"]]=item
    return base,hashlib.sha256(raw).hexdigest()


def classify(vol,amount):
    if vol>0 and amount>0:
        return "both_positive"
    if vol>0 and amount==0:
        return "volume_positive_amount_zero"
    if vol==0 and amount>0:
        return "volume_zero_amount_positive"
    if vol==0 and amount==0:
        return "both_zero"
    raise ValueError("Invalid H5 native zero-state values")


def inspect_year(file,year,expected):
    """Only aggregate info leaves the tight inner loop; no raw values returned."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    names=("symbol","openPrice","highPrice","lowPrice",
           "closePrice","transCount","transAmount")
    groups={market:Counter() for market in ("SH","SZ","BJ")}
    flat=Counter()
    states=Counter()
    count=0
    parquet=pq.ParquetFile(file,memory_map=False,pre_buffer=False)
    try:
        if (tuple(parquet.schema_arrow.names)!=SINGLE.FIELDS
                or parquet.schema_arrow.field("symbol").type!=pa.string()
                or any(parquet.schema_arrow.field(k).type!=pa.uint64()
                       for k in SINGLE.REQUIRED_NUMERIC)
                or parquet.metadata.num_rows!=expected):
            raise ValueError("Unexpected private RAW early-year schema/rows")
        for batch in parquet.iter_batches(batch_size=SINGLE.CHUNK,columns=list(names)):
            if any(batch.column(i).null_count for i in range(len(names))):
                raise ValueError("Null historical private RAW numeric/symbol")
            values=[batch.column(i).to_pylist() for i in range(len(names))]
            for symbol,op,high,low,close,volume,amount in zip(*values):
                if (type(symbol) is not str
                        or not re.fullmatch(r"(SH|SZ|BJ)[0-9]{6}",symbol)
                        or not SINGLE.AUDIT.CORE.is_a_share_candidate(symbol,2010)
                        or any(type(x) is not int or x<0
                               for x in (op,high,low,close,volume,amount))
                        or not 0<low<=op<=high
                        or not low<=close<=high):
                    raise ValueError("Invalid early H5 RAW integer record structure")
                market=symbol[:2]
                kind=classify(volume,amount)
                same=(op==high==low==close)
                states[kind]+=1
                groups[market][kind]+=1
                if same:
                    flat[kind]+=1
                count+=1
                if count>expected:
                    raise ValueError("Historical private early-year row budget exceeded")
        if count!=expected:
            raise ValueError("Historical private early-year row count mismatch")
    finally:
        parquet.close()
    return {
        "year":year,"rows":count,
        "zero_state_count":{k:states[k] for k in STATES},
        "zero_state_flat_ohlc_count":{k:flat[k] for k in STATES},
        "market_zero_state_count":{
            m:{k:groups[m][k] for k in STATES}
            for m in ("SH","SZ","BJ")},
    }


def run(full21,profile,out):
    full,full_sha=P.source_safe(full21)
    prior,profile_sha=require_early_profile(profile,full_sha,full)
    path=P.target_safe(out)
    entries=P.verified_private_files(full)
    got={year:(file,count,file_sha) for year,file,count,file_sha in entries}
    if set(got)!=set(P.YEARS):
        raise ValueError("Full historical private RAW stage set incomplete")
    yearly=[]
    for year in YEARS:
        file,count,sha=got[year]
        state=(file.stat().st_size,file.stat().st_mtime_ns)
        row=inspect_year(file,year,count)
        if (file.stat().st_size,file.stat().st_mtime_ns)!=state
                or SINGLE.hash_file(file)!=sha):
            raise ValueError("Original private early-year RAW changed during read")
        summary=prior[year]
        for key,prev in (
            ("volume_positive_amount_zero","volume_nonzero_amount_zero"),
            ("volume_zero_amount_positive","volume_zero_amount_nonzero"),
            ("both_zero","volume_and_amount_both_zero")):
            if row["zero_state_count"][key]!=summary[prev]:
                raise ValueError("Early private RAW differs from prior numeric profile")
        if sum(row["zero_state_flat_ohlc_count"].values())!=summary[
                "open_high_low_close_all_equal"]:
            raise ValueError("Historical flat-price count differs from prior profile")
        yearly.append(row)
    total=sum(item["rows"] for item in yearly)
    if total!=EXPECTED_ROWS:
        raise ValueError("1990-1993 private RAW count disagrees with source record")
    result={
        "format":FORMAT,
        "status":"pre2011_early_zero_amount_volume_aggregate_triage_not_correction",
        "full21_source_safe_sha256":full_sha,
        "prior_raw_numeric_profile_sha256":profile_sha,
        "years_profiled":list(YEARS),
        "rows_profiled":total,
        "yearly_market_zero_state_aggregate":yearly,
        "total_state_count":{
            kind:sum(x["zero_state_count"][kind] for x in yearly) for kind in STATES},
        "full21_private_raw_files_sha_verified":True,
        "historical_original_h5_or_purchased_parquet_opened":False,
        "historical_units_or_adjustment_certified":False,
        "invalid_zero_amount_rows_auto_repaired_or_dropped":False,
        "private_stage_or_production_changed":False,
        "historical_standard_parquet_or_new_h5_written":False,
        "individual_market_data_or_symbols_in_safe":False,
    }
    with path.open("x",encoding="utf-8") as outfp:
        json.dump(result,outfp,ensure_ascii=False,sort_keys=True,indent=2)
        outfp.write("\n")
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full21-safe",type=Path,required=True)
    parser.add_argument("--numeric-profile-safe",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--read-only-private-raw",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        result=run(args.full21_safe,args.numeric_profile_safe,args.out)
        print("1990-1993 only RAW zero amount/volume aggregate:",result["rows_profiled"])
        print("No original sources read; no records changed; no units certified.")
        print("SAFE:",args.out)
    except (ValueError,KeyError,TypeError,OSError,OverflowError,ImportError,
            ModuleNotFoundError,json.JSONDecodeError):
        parser.error("Historical early zero-state research refused; no changes made")


if __name__=="__main__":
    main()
