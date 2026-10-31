#!/usr/bin/env python3
"""Purchased Parquet first + full private 22,274 H5 gap candidate query, read only.

Unlike a production merge this reads ORIGINAL purchased DAY and an immutable,
previously live-audited, candidate-only local private Parquet snapshot. One
OFFLINE all-rows SHA/schema/key audit of the private partitions is mandatory
for each invocation. Live purchased/H5 key absence audit is NOT repeated;
the original-market source stat must match the candidate's original evidence
before and after each query. Any purchased/private stockday collision fails
closed. No writes outside module reports (SAFE) and no source/pointer writes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import time
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
FORMAT="AStockDataTools purchased first plus full private 22274 day candidate bounded query SAFE v1"
MAX_SYMBOLS=10
MAX_TOTAL_RESULTS=1000
MAX_SOURCE_ROWS=100000000


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


V=load("joined_22274_candidate_offline_verify",
       "verify-private-full-22274-gap-candidates.py")
B=load("joined_22274_source_query",
       "query-private-combined-day-22274-batch-readonly.py")
P=B.PURCHASED
Q=B.Q
STAGER=V.STAGER
FIELDS=STAGER.FIELDS


def requests(symbols,first,last,max_candidate_rows_per_symbol,max_total_candidate_rows,
             max_result_bars_per_symbol,max_total_result_bars):
    if (type(symbols) not in (tuple,list) or not 1<=len(symbols)<=MAX_SYMBOLS
            or any(type(x) is not str or x!=x.upper() or x!=x.strip()
                   for x in symbols)):
        raise ValueError("Require 1..10 explicit canonical stock symbols")
    if (type(max_candidate_rows_per_symbol) is not int
            or not 1<=max_candidate_rows_per_symbol<=MAX_SOURCE_ROWS
            or type(max_total_candidate_rows) is not int
            or not 1<=max_total_candidate_rows<=MAX_SOURCE_ROWS
            or type(max_result_bars_per_symbol) is not int
            or not 1<=max_result_bars_per_symbol<=MAX_TOTAL_RESULTS
            or type(max_total_result_bars) is not int
            or not 1<=max_total_result_bars<=MAX_TOTAL_RESULTS):
        raise ValueError("Invalid bounded source or daily output limits")
    dates=[P.request_dates(s,"day",first,last,max_candidate_rows_per_symbol,
                           max_result_bars_per_symbol) for s in symbols]
    if len({x[0] for x in dates})!=len(dates):
        raise ValueError("Duplicate stock symbols in private unified query")
    start,end=dates[0][1:]
    if start.year!=end.year or any(x[1:]!=(start,end) for x in dates):
        raise ValueError("Require 1..31 days within a single calendar year")
    return [x[0] for x in dates],start,end


def verified_candidate_selection(snapshot_safe,verified_full,requested_year,symbols,start,end):
    """Extract only selected rows from the FULLY rehashed private year source."""
    if (type(verified_full) is not dict
            or verified_full.get("state")!="all_22274_candidate_rows_partition_sha_schema_and_keys_verified_not_merged"
            or verified_full.get("total_h5_only_day_candidates_verified")!=22274
            or verified_full.get("whole_date_candidate_rows_verified")!=22191
            or verified_full.get("mixed_date_candidate_rows_verified")!=83
            or verified_full.get("candidate_source_units_certified") is not False
            or verified_full.get("full_purchased_parquet_historical_market_included") is not False
            or verified_full.get("original_market_source_freshness_rechecked") is not False):
        raise ValueError("Unqualified private all-stockday offline audit")
    doc,proof_sha,folder,mf=V.source(snapshot_safe)
    if (doc.get("source_version_sha256")!=verified_full.get("source_private_version_sha256")
            or doc.get("manifest_sha256")!=verified_full.get("source_private_manifest_sha256")
            or proof_sha!=verified_full.get("source_materialization_safe_sha256")):
        raise ValueError("Private all-stockday source proof changed since complete audit")
    results={s:{"private_h5_whole_date_candidate":[],
                "private_h5_mixed_stockday_candidate":[]} for s in symbols}
    year=str(requested_year)
    if year not in doc["candidate_year_rows"]:
        return results,doc,proof_sha
    # V.verify() has already rehashed every candidate partition, but the
    # file could change after that audit and before this second read.
    # Check the on-disk bytes BEFORE passing them to Arrow. This also turns
    # deliberate corruption into a stable fail-closed integrity error rather
    # than relying on whichever Arrow decoder error happens first.
    manifest=json.loads(mf.read_bytes())
    part=manifest["partitions"][year]
    rel=folder/("year="+year)/"day.parquet"
    if (rel.parent.is_symlink() or rel.is_symlink()
            or STAGER.sha(mf)!=doc["manifest_sha256"]
            or STAGER.sha(rel)!=part["sha256"]
            or V.source(snapshot_safe)[1]!=proof_sha):
        raise ValueError("Private candidate year partition or SAFE changed before selection")
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(rel,memory_map=False,pre_buffer=False)
    try:
        schema=STAGER.candidate_schema(__import__("pyarrow"))
        if (pf.schema_arrow!=schema or pf.metadata.num_rows!=doc["candidate_year_rows"][year]):
            raise ValueError("Candidate source partition schema/rows changed after full audit")
        table=pf.read(columns=schema.names,use_threads=False)
    finally:
        pf.close()
    if table.schema!=schema or table.num_rows!=doc["candidate_year_rows"][year]:
        raise ValueError("Private candidate year decode mismatch")
    selected_set=set(symbols)
    for row in table.to_pylist():
        symbol=row["symbol"]
        d=row["trading_date"]
        if symbol not in selected_set or not start.isoformat()<=d<=end.isoformat():
            continue
        kind=row["value_source"]
        if kind not in results[symbol]:
            raise ValueError("Private candidate source category changed")
        original={
            "symbol":symbol,"period":"day","trading_date":d,
            "source_timestamp_ms":row["ts"],
            **{f:row[f] for f in FIELDS},
        }
        clean=Q.validated_source_row(original,symbol,start,end,kind)
        results[symbol][kind].append(clean)
    manifest=json.loads(mf.read_bytes())
    part=manifest["partitions"][year]
    if (STAGER.sha(rel)!=part["sha256"]
            or STAGER.sha(mf)!=doc["manifest_sha256"]
            or V.source(snapshot_safe)[1]!=proof_sha):
        raise ValueError("Private candidate year partition or SAFE changed after selection")
    return results,doc,proof_sha


def query(root,snapshot_safe,symbols,first,last,candidate_recheck_out,out,
          max_candidate_rows_per_symbol=30000000,
          max_total_candidate_rows=30000000,
          max_result_bars_per_symbol=100,
          max_total_result_bars=1000):
    start_time=time.perf_counter()
    canon,start,end=requests(
        symbols,first,last,max_candidate_rows_per_symbol,
        max_total_candidate_rows,max_result_bars_per_symbol,max_total_result_bars)
    verify_path=V.REPORTS/Path(candidate_recheck_out).name
    output=V.REPORTS/Path(out).name
    if (Path(candidate_recheck_out).resolve()!=verify_path.resolve()
            or Path(out).resolve()!=output.resolve()
            or verify_path==output or output.exists() or verify_path.exists()
            or output.is_symlink() or verify_path.is_symlink()
            or V.REPORTS.is_symlink()):
        raise ValueError("Require two NEW separate direct module reports SAFE outputs")
    original_root=Path(root)
    if (not original_root.is_absolute() or original_root.is_symlink()
            or not original_root.is_dir()):
        raise ValueError("Purchased Parquet root must be explicit absolute directory")
    prior,_,_,_=V.source(snapshot_safe)
    purchased_selected_year_before=P.private_cache.source_signature(
        original_root,"day",start,end,P.core)
    before=STAGER.PRE.KEYS.state_digest(original_root.resolve(),(2016,2026))
    if before!=prior["original_source_stat_sha256"]:
        raise ValueError("Original market stat differs from immutable candidate source")
    # One complete private candidate verification, not a 180s live key scan.
    full=V.verify(snapshot_safe,verify_path)
    selected,doc,proof_sha=verified_candidate_selection(
        snapshot_safe,full,start.year,canon,start,end)
    if doc["original_source_stat_sha256"]!=before:
        raise ValueError("Private source stat no longer matches candidate proof")
    purchased=whole=mixed=source_rows_scanned=0
    total=0
    combined={}
    for symbol in canon:
        remaining=max_total_candidate_rows-source_rows_scanned
        if remaining<1:
            raise ValueError("Purchased cumulative source-row budget exhausted")
        result=P.query_bars(
            original_root,symbol,"day",start.isoformat(),end.isoformat(),
            max_candidate_rows=min(max_candidate_rows_per_symbol,remaining),
            max_result_bars=max_result_bars_per_symbol,local_cache=False)
        item=result["safe_summary"]
        scanned=item.get("source_rows_scanned")
        if (type(scanned) is not int or scanned<0 or scanned>remaining
                or item.get("source_market_files_modified") is not False
                or item.get("no_h5_read") is not True
                or item.get("no_automatic_gaps_fill") is not True):
            raise ValueError("Purchased Parquet bounded query source proof not trusted")
        source_rows_scanned+=scanned
        bundle=selected[symbol]
        rows,counts=Q.merge_stock_day_rows(
            symbol,start,end,result["bars"],
            bundle["private_h5_whole_date_candidate"],
            bundle["private_h5_mixed_stockday_candidate"],
            max_result_bars_per_symbol)
        total+=len(rows)
        if total>max_total_result_bars:
            raise ValueError("Full private + purchased day result budget exhausted")
        purchased+=counts["purchased_parquet"]
        whole+=counts["private_h5_whole_date_candidate"]
        mixed+=counts["private_h5_mixed_stockday_candidate"]
        combined[symbol]=rows
    if (STAGER.PRE.KEYS.state_digest(original_root.resolve(),(2016,2026))!=before
            or P.private_cache.source_signature(
                original_root,"day",start,end,P.core)!=purchased_selected_year_before
            or V.source(snapshot_safe)[1]!=proof_sha
            or STAGER.REG.load_version(doc["source_version_sha256"]).get(
                "original_source_stat_sha256")!=before
            or STAGER.REG.LOCK.exists() or STAGER.REG.LOCK.is_symlink()):
        raise ValueError("Purchased/ H5 market source or private version changed during query")
    # Candidate data recheck is STATIC (all rows), source freshness is
    # stat-only; do not claim that licensed vendor units are certified.
    safe={
        "format":FORMAT,
        "state":"purchased_first_private_22274_h5_gap_bounded_view_verified_not_activated",
        "private_source_version_sha256":doc["source_version_sha256"],
        "private_candidate_snapshot_safe_sha256":proof_sha,
        "private_candidate_manifest_sha256":doc["manifest_sha256"],
        "private_candidate_full_recheck_safe_sha256":STAGER.sha(verify_path),
        "requested_stock_count":len(canon),
        "queried_calendar_year":start.year,
        "returned_stockday_rows":total,
        "purchased_parquet_rows":purchased,
        "whole_h5_candidate_rows":whole,
        "mixed_h5_candidate_rows":mixed,
        "purchased_source_rows_scanned":source_rows_scanned,
        "purchased_parquet_first_no_duplicate_stockday":True,
        "private_candidate_all_22274_rows_sha_schema_keys_verified":True,
        "source_file_stat_before_and_after_unchanged":True,
        "queried_purchased_year_file_count_and_stat_before_after_unchanged":True,
        "source_stat_drift_detection_not_full_live_market_key_absence_audit":True,
        "original_live_h5_keyset_not_rescanned":True,
        "candidate_source_units_certified":False,
        "full_unified_historical_market_database_materialized":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "h5_mirror_created":False,
        "original_market_files_written":False,
        "purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "no_licensed_ohlcva_or_symbols_exported_in_safe":True,
        "elapsed_seconds":round(time.perf_counter()-start_time,6),
    }
    with output.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(safe,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")
    return {"bars_by_symbol":combined,"safe_summary":safe}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--candidate-safe",type=Path,required=True)
    p.add_argument("--symbols",nargs="+",required=True)
    p.add_argument("--from-date",required=True)
    p.add_argument("--to-date",required=True)
    p.add_argument("--candidate-recheck-out",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--max-candidate-rows-per-symbol",type=int,default=30000000)
    p.add_argument("--max-total-candidate-rows",type=int,default=30000000)
    p.add_argument("--max-result-bars-per-symbol",type=int,default=100)
    p.add_argument("--max-total-result-bars",type=int,default=1000)
    p.add_argument("--read-only-view",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        r=query(a.source_root,a.candidate_safe,a.symbols,a.from_date,
                a.to_date,a.candidate_recheck_out,a.out,
                a.max_candidate_rows_per_symbol,a.max_total_candidate_rows,
                a.max_result_bars_per_symbol,a.max_total_result_bars)
        s=r["safe_summary"]
        print("Purchased + private candidate stockdays:",s["returned_stockday_rows"])
        print("Purchased:",s["purchased_parquet_rows"],
              "whole:",s["whole_h5_candidate_rows"],
              "mixed:",s["mixed_h5_candidate_rows"])
        print("One offline full-candidate SHA/schema/key audit, NO full live source key scan")
        print("Aggregate-only SAFE:",a.out)
    except (ValueError,OSError,TypeError,KeyError,ImportError,OverflowError):
        p.error("Purchased + 22,274 private H5-gap candidate query failed closed")


if __name__=="__main__":
    main()
