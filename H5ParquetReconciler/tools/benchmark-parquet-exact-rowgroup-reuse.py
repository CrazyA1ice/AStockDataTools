#!/usr/bin/env python3
"""Read-only REAL A/B: full Arrow vs exact-key RowGroup-restricted Arrow.

Consumes an existing, COMPLETE, stat-bound key-only locator report. NEVER
trusts its claims alone: validate query identity, the entire footer candidate
set, source manifest, row-group membership counts, then compare EVERY returned
OHLCVA value/timestamp/file/row-group with a fresh full-Arrow query. Optional
--verify-rowgroup also compares to the default ParquetFile engine.

The result is an experimental TIMING comparison, not production pruning.
No private OHLCVA cache, SQLite, H5, source modification, or automatic import.
Only aggregate safe JSON is written to module reports/. The original full
5min preflight budget is enforced even when only 18/47 groups are read.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=(MODULE/"reports").resolve()
BENCH_SPEC=importlib.util.spec_from_file_location(
    "exact_rg_reuse_arrow_engine",HERE/"benchmark-parquet-arrow-filter-cold.py")
benchmark=importlib.util.module_from_spec(BENCH_SPEC)
BENCH_SPEC.loader.exec_module(benchmark)
query=benchmark.query
LOCATOR_FORMAT="AStockDataTools exact single 5min symbol-day RowGroup key membership v1"
ORDERS=("full-first","restricted-first")


def report_path(path, *, new_output=False):
    supplied=Path(path)
    target=supplied if supplied.is_absolute() else MODULE/supplied
    if (target.is_symlink() or not target.resolve().is_relative_to(REPORTS)
            or target.suffix.lower()!=".json"):
        raise ValueError("Only JSON under H5ParquetReconciler/reports/ allowed")
    if new_output:
        if target.exists():
            raise ValueError("Output JSON exists: no overwrite allowed")
    elif not target.is_file():
        raise ValueError("Existing key locator JSON required")
    return target.resolve()


def positive_int(value,label,allow_zero=False):
    if type(value) is not int or value<(0 if allow_zero else 1):
        raise ValueError(label+" must be a nonnegative integer" if allow_zero
                         else label+" must be a positive integer")
    return value


def read_locator(path):
    location=report_path(path)
    if location.stat().st_size>131072:
        raise ValueError("Locator report exceeds 128 KiB")
    with location.open("r",encoding="utf-8") as reader:
        report=json.load(reader)
    if type(report) is not dict:
        raise ValueError("Locator must be a JSON object")
    return report


def validate_locator(locator,ctx,signature):
    """Never use a report until its full candidate census is independently checked."""
    if locator.get("format")!=LOCATOR_FORMAT:
        raise ValueError("Unsupported exact RowGroup locator format")
    if (locator.get("symbol")!=ctx["symbol"]
            or locator.get("date")!=ctx["start"].isoformat()
            or ctx["start"]!=ctx["end"]
            or locator.get("period")!="5min"):
        raise ValueError("Locator query identity mismatches source request")
    required_true=(
        "source_manifest_stat_only_not_content_sha256",
        "source_manifest_stable_during_key_scan",
        "ALL_footer_candidate_groups_key_columns_scanned",
        "only_ts_and_symbol_columns_read",
        "rowgroup_pruning_is_a_possible_future_optimization_not_applied",
        "physical_parquet_io_saved_unknown",
        "net_query_speedup_not_measured",
    )
    required_false=(
        "current_production_query_modified",
        "automatic_source_union_or_import_performed",
        "raw_ohlcva_exported",
        "h5_source_accessed",
        "source_market_files_modified",
    )
    for key in required_true:
        if locator.get(key) is not True:
            raise ValueError("Locator full-scan safety flag absent: "+key)
    for key in required_false:
        if locator.get(key) is not False:
            raise ValueError("Locator unsafe state: "+key)
    if (locator.get("source_stat_manifest_sha256")!=signature[
            "manifest_sha256_stat_only"]
            or locator.get("source_stat_manifest_file_count")!=signature[
                "manifest_file_count"]):
        raise ValueError("Locator source stat manifest stale or mismatched")
    all_groups={
        (p.relative_to(ctx["root"]).as_posix(),gid)
        for p,_,gid in ctx["pending"]
    }
    group_count=len(all_groups)
    upper_bound=ctx["metadata"]["candidate_source_rows_upper_bound"]
    if len(ctx["pending"])!=group_count:
        raise ValueError("Repeated source RowGroup candidate in preflight")
    if (positive_int(locator.get("candidate_row_groups"),
                     "candidate_row_groups",allow_zero=True)!=group_count
            or positive_int(locator.get("candidate_source_rows_upper_bound"),
                            "candidate_source_rows_upper_bound",allow_zero=True)
               !=upper_bound
            or positive_int(locator.get("two_key_columns_source_rows_examined"),
                            "two_key_columns_source_rows_examined",allow_zero=True)
               !=upper_bound):
        raise ValueError("Locator lacks complete original footer candidate census")
    entries=locator.get("nonempty_source_row_group_locators")
    if type(entries) is not list or len(entries)>group_count:
        raise ValueError("Invalid RowGroup locator list")
    membership={}
    for item in entries:
        if type(item) is not dict:
            raise ValueError("Malformed RowGroup membership item")
        source=item.get("source_file_relative_path")
        gid=item.get("row_group")
        count=item.get("matching_key_count")
        if (type(source) is not str or type(gid) is not int or gid<0):
            raise ValueError("Invalid RowGroup path/id")
        key=(source,gid)
        if key not in all_groups or key in membership:
            raise ValueError("Locator contains foreign or duplicate RowGroup")
        membership[key]=positive_int(count,"matching_key_count")
    exact_count=positive_int(locator.get("exact_groups_containing_target_keys"),
                             "exact_groups_containing_target_keys",allow_zero=True)
    empty_count=positive_int(locator.get("exact_groups_without_target_keys"),
                             "exact_groups_without_target_keys",allow_zero=True)
    omitted=positive_int(locator.get("possible_row_groups_to_omit_if_sources_unchanged"),
                         "possible_row_groups_to_omit_if_sources_unchanged",allow_zero=True)
    key_count=positive_int(locator.get("matching_source_keys"),
                           "matching_source_keys",allow_zero=True)
    if (exact_count!=len(membership) or exact_count+empty_count!=group_count
            or omitted!=empty_count or sum(membership.values())!=key_count):
        raise ValueError("Locator membership counts do not conserve source census")
    return membership


def run(root,symbol,day,locator,order="full-first",
        max_candidate_rows=30000000,max_result_bars=25000,
        verify_rowgroup=False):
    """Measure identical requests in either order and FAIL on ANY mismatch."""
    if order not in ORDERS:
        raise ValueError("Invalid execution order")
    if type(verify_rowgroup) is not bool:
        raise ValueError("verify_rowgroup must be a boolean")
    symbol,first,last=query.request_dates(
        symbol,"5min",day,day,max_candidate_rows,max_result_bars)
    started=time.perf_counter()
    before=query.private_cache.source_signature(
        root,"5min",first,last,query.core)
    ctx=query.prepare_query(
        root,symbol,"5min",first,last,max_candidate_rows,max_result_bars)
    membership=validate_locator(locator,ctx,before)
    allowed=frozenset(membership)
    args=(root,symbol,"5min",first,last,max_candidate_rows,max_result_bars)
    if order=="full-first":
        full=benchmark.arrow_filtered_query(*args)
        restricted=benchmark.arrow_filtered_query(
            *args,allowed_rowgroups=allowed)
    else:
        restricted=benchmark.arrow_filtered_query(
            *args,allowed_rowgroups=allowed)
        full=benchmark.arrow_filtered_query(*args)
    after=query.private_cache.source_signature(
        root,"5min",first,last,query.core)
    if before!=after:
        raise ValueError("Source stat manifest changed between full and restricted reads")
    if full["bars"]!=restricted["bars"]:
        raise ValueError("EXACT RowGroup pruning differs in OHLCVA/time/source provenance")
    bars=full["bars"]
    if len(bars)!=locator["matching_source_keys"]:
        raise ValueError("Locator matching key count mismatches full Arrow source")
    from collections import Counter
    delivered=Counter(
        (b["source_file_relative_path"],b["source_row_group"])
        for b in bars)
    if dict(delivered)!=membership:
        raise ValueError("Locator per-RowGroup key counts mismatch real source results")
    baseline=None
    if verify_rowgroup:
        baseline=query.query_bars(
            root,symbol,"5min",first,last,max_candidate_rows,
            max_result_bars,local_cache=False)
        if baseline["bars"]!=bars:
            raise ValueError("Default RowGroup output differs from full/pruned Arrow")
        after_verify=query.private_cache.source_signature(
            root,"5min",first,last,query.core)
        if before!=after_verify:
            raise ValueError("Source stat manifest changed during RowGroup verification")
    reference=full["safe_measurement"]
    reduced=restricted["safe_measurement"]
    if (reference["candidate_row_groups"]!=len(ctx["pending"])
            or reduced["candidate_row_groups"]!=len(ctx["pending"])
            or reference["row_groups_actually_scanned"]!=len(ctx["pending"])
            or reduced["row_groups_actually_scanned"]!=len(membership)):
        raise ValueError("Engine scanned unexpected RowGroup count")
    old_t=reference["query_elapsed_seconds_this_invocation"]
    new_t=reduced["query_elapsed_seconds_this_invocation"]
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0
           for v in (old_t,new_t)):
        raise ValueError("Nonfinite engine timing")
    selected_upper=reduced[
        "row_group_source_rows_upper_bound_actually_scanned"]
    if not 0<=selected_upper<=ctx["metadata"]["candidate_source_rows_upper_bound"]:
        raise ValueError("Invalid restricted source RowGroup upper bound")
    return {
        "format":"AStockDataTools exact 5min RowGroup reuse A/B v1",
        "symbol":symbol,"date":first.isoformat(),"period":"5min",
        "requested_execution_order":order,
        "matching_bar_count":len(bars),
        "full_arrow_seconds":old_t,
        "restricted_arrow_seconds":new_t,
        "full_over_restricted_ratio":round(old_t/new_t,6) if new_t else None,
        "full_footer_candidate_row_groups":len(ctx["pending"]),
        "restricted_row_groups_actually_scanned":len(membership),
        "row_groups_not_read_in_restricted_scan":len(ctx["pending"])-len(membership),
        "original_preflight_rows_upper_bound":ctx["metadata"][
            "candidate_source_rows_upper_bound"],
        "restricted_rowgroup_source_rows_upper_bound":selected_upper,
        "key_only_locator_build_seconds_from_prior_report":locator.get(
            "elapsed_seconds_of_key_only_scan_including_footer_preflight"),
        "locator_build_cost_not_included_in_engine_comparison":True,
        "source_stat_manifest_sha256":before["manifest_sha256_stat_only"],
        "source_stat_manifest_file_count":before["manifest_file_count"],
        "source_stat_only_not_content_hash":True,
        "source_stat_stable_during_comparison":True,
        "all_output_ohlcva_time_and_provenance_identical":True,
        "locator_key_count_and_group_membership_crosschecked_with_full_source":True,
        "legacy_rowgroup_exact_equality_verified_this_run":bool(verify_rowgroup),
        "legacy_rowgroup_seconds_if_verified":(
            baseline["safe_summary"]["query_elapsed_seconds_this_invocation"]
            if baseline else None),
        "total_wall_seconds_including_all_parity_scans":round(
            time.perf_counter()-started,6),
        "net_end_to_end_speedup_including_locator_creation_not_proven":True,
        "physical_parquet_io_saved_unknown":True,
        "not_production_pruning":True,
        "local_private_cache_not_used":True,
        "paid_ohlcva_exported":False,
        "h5_source_accessed":False,
        "source_market_files_modified":False,
        "automatic_source_union_or_import_performed":False,
    }


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root",type=Path)
    ap.add_argument("--symbol",required=True)
    ap.add_argument("--date",required=True)
    ap.add_argument("--locator-report",type=Path,required=True)
    ap.add_argument("--order",choices=ORDERS,default="full-first")
    ap.add_argument("--max-candidate-rows",type=int,default=30000000)
    ap.add_argument("--max-result-bars",type=int,default=25000)
    ap.add_argument("--verify-rowgroup",action="store_true")
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--read-only",action="store_true",required=True)
    args=ap.parse_args(argv)
    try:
        loc_path=report_path(args.locator_report)
        out=report_path(args.out,new_output=True)
        if loc_path==out:
            raise ValueError("Input and output path must be different")
        _,scratch=query.core.resolve_module_artifact_paths(out)
        root,_,_=query.core.resolve_safe_paths(args.root,out,scratch)
        result=run(root,args.symbol,args.date,read_locator(loc_path),
                   args.order,args.max_candidate_rows,args.max_result_bars,
                   args.verify_rowgroup)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as fh:
            json.dump(result,fh,indent=2,ensure_ascii=False,allow_nan=False)
            fh.write("\n")
        print("Saved exact RowGroup reuse aggregate-only A/B:",out)
        print("Full vs restricted seconds:",
              result["full_arrow_seconds"],result["restricted_arrow_seconds"])
        print("Parity:",result["all_output_ohlcva_time_and_provenance_identical"])
        print("Not production pruning. Original query unchanged.")
    except (ValueError,TypeError,OSError,OverflowError,
            ModuleNotFoundError,json.JSONDecodeError) as e:
        ap.error(str(e))


if __name__=="__main__":
    main()
