#!/usr/bin/env python3
"""EXPERIMENTAL single-symbol/day 5min query using a previously built key locator.

Default parity-safe mode reads the full Arrow source as well and compares
every source OHLCVA value, timestamp, file and RowGroup. Explicit
--fast-stat-only avoids the second full data read, but is NOT production-safe:
the user-editable locator is not signed and matching source file size/mtime
does not cryptographically prove unmodified content. Always report this risk.

Only reads licensed data in memory; CLI writes SAFE aggregate-only JSON.
Does not change default query, use the OHLCVA private cache, H5 or SQLite.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "exact_rg_located_query_validation",
    HERE/"benchmark-parquet-exact-rowgroup-reuse.py")
gate=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
benchmark=gate.benchmark
query=gate.query


def query_bars(root,symbol,day,locator,*,max_candidate_rows=30000000,
               max_result_bars=25000,fast_stat_only=False):
    """Return local real OHLCVA bars with explicit evidence/warnings.

    When fast_stat_only=False, run the full Arrow query and assert parity.
    Even fast mode validates the FULL footer census, budgets, source stat,
    and actual emitted per-RowGroup key counts; a tampered, count-preserving
    editable locator can still omit records in fast mode. Use only locally.
    """
    if type(fast_stat_only) is not bool:
        raise ValueError("fast_stat_only must be a bool")
    canonical,first,last=query.request_dates(
        symbol,"5min",day,day,max_candidate_rows,max_result_bars)
    started=time.perf_counter()
    stamp=time.perf_counter()
    sig_before=query.private_cache.source_signature(
        root,"5min",first,last,query.core)
    source_manifest_before_seconds=round(time.perf_counter()-stamp,6)
    stamp=time.perf_counter()
    ctx=query.prepare_query(
        root,canonical,"5min",first,last,max_candidate_rows,max_result_bars)
    full_footer_preflight_seconds=round(time.perf_counter()-stamp,6)
    # prepare_query() returns open ParquetFile readers shared by every
    # candidate RowGroup. Explicitly close each DISTINCT reader even when
    # validation or Arrow parity raises. On Windows, keeping a ParquetFile
    # alive through mock call history can otherwise block TemporaryDirectory
    # deletion with WinError 32. Do not rely on garbage collection.
    readers={id(pf):pf for _,pf,_ in ctx["pending"]}
    try:
        stamp=time.perf_counter()
        membership=gate.validate_locator(locator,ctx,sig_before)
        locator_validation_seconds=round(time.perf_counter()-stamp,6)
        allowed=frozenset(membership)
        restricted=benchmark.arrow_filtered_query(
            root,canonical,"5min",first,last,max_candidate_rows,
            max_result_bars,allowed_rowgroups=allowed,prepared_context=ctx)
        restricted_measurement=restricted["safe_measurement"]
        if restricted_measurement["row_groups_actually_scanned"]!=len(membership):
            raise ValueError("Restricted Arrow scanned a different RowGroup count")
        selected=restricted["bars"]
        if len(selected)!=locator["matching_source_keys"]:
            raise ValueError("Locator selected key count mismatches restricted source")
        delivered=dict(Counter(
            (bar["source_file_relative_path"],bar["source_row_group"])
            for bar in selected))
        if delivered!=membership:
            raise ValueError("Locator per-RowGroup counts differ from restricted source")
        full=None
        if not fast_stat_only:
            full=benchmark.arrow_filtered_query(
                root,canonical,"5min",first,last,max_candidate_rows,
                max_result_bars,prepared_context=ctx)
            if full["bars"]!=selected:
                raise ValueError("Full Arrow parity disagrees with locator-restricted result")
            if (full["safe_measurement"]["candidate_row_groups"]!=
                    restricted_measurement["candidate_row_groups"]):
                raise ValueError("Query preflights diverged")
        stamp=time.perf_counter()
        sig_after=query.private_cache.source_signature(
            root,"5min",first,last,query.core)
        source_manifest_after_seconds=round(time.perf_counter()-stamp,6)
        if sig_before!=sig_after:
            raise ValueError("Source stat manifest changed during locator query")
        measurement=restricted["safe_measurement"]
        safe={
            "format":"AStockDataTools experimental exact locator 5min query v1",
            "symbol":canonical,"date":first.isoformat(),"period":"5min",
            "query_engine":"experimental_arrow_restricted_by_local_complete_key_locator",
            "matching_bar_count":len(selected),
            "full_preflight_candidate_row_groups":len(ctx["pending"]),
            "restricted_row_groups_actually_scanned":len(membership),
            "footer_candidate_source_rows_upper_bound":ctx["metadata"][
                "candidate_source_rows_upper_bound"],
            "restricted_row_group_source_rows_upper_bound":measurement[
                "row_group_source_rows_upper_bound_actually_scanned"],
            "restricted_engine_elapsed_seconds":measurement[
                "query_elapsed_seconds_this_invocation"],
            "total_invocation_wall_seconds_including_validations":round(
                time.perf_counter()-started,6),
            "source_manifest_before_seconds":source_manifest_before_seconds,
            "full_footer_preflight_seconds":full_footer_preflight_seconds,
            "locator_validation_seconds":locator_validation_seconds,
            "source_manifest_after_seconds":source_manifest_after_seconds,
            "full_footer_preflight_executions_this_invocation":1,
            "prepared_preflight_context_reused_for_arrow_scans":True,
            "arrow_engine_seconds_are_scan_only_in_prepared_mode":True,
            "full_arrow_equality_checked_this_invocation":not fast_stat_only,
            "full_arrow_seconds_if_verified":(
                full["safe_measurement"]["query_elapsed_seconds_this_invocation"]
                if full else None),
            "source_stat_manifest_sha256":sig_before["manifest_sha256_stat_only"],
            "source_stat_manifest_file_count":sig_before["manifest_file_count"],
            "source_stat_manifest_stable_during_query":True,
            "locator_group_membership_counts_match_restricted_rows":True,
            "full_original_candidate_budget_enforced":True,
            "locator_report_is_editable_and_not_signed":True,
            "source_stat_fingerprint_is_not_content_hash":True,
            "fast_path_can_silently_omit_bars_if_locator_is_tampered":fast_stat_only,
            "production_default_engine_unchanged":True,
            "not_certified_for_unattended_production_pruning":True,
            "physical_parquet_rows_and_disk_bytes_read_unknown":True,
            "licensed_ohlcva_in_process_memory_only":True,
            "raw_ohlcva_in_safe_summary":False,
            "local_private_ohlcva_cache_used":False,
            "h5_source_accessed":False,
            "source_market_files_modified":False,
            "automatic_source_union_or_import_performed":False,
        }
        return {"bars":selected,"safe_summary":safe}
    finally:
        for pf in readers.values():
            pf.close()


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root",type=Path)
    ap.add_argument("--symbol",required=True)
    ap.add_argument("--date",required=True)
    ap.add_argument("--locator-report",type=Path,required=True)
    ap.add_argument("--max-candidate-rows",type=int,default=30000000)
    ap.add_argument("--max-result-bars",type=int,default=25000)
    ap.add_argument("--fast-stat-only",action="store_true",
                    help="EXPERIMENT ONLY: bypass full Arrow parity; uses an "
                         "editable unsigned locator + non-cryptographic stat "
                         "fingerprint. May silently miss source bars if altered.")
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--read-only",action="store_true",required=True)
    args=ap.parse_args(argv)
    try:
        loc=gate.report_path(args.locator_report)
        out=gate.report_path(args.out,new_output=True)
        if loc==out:
            raise ValueError("Locator and output must differ")
        _,scratch=query.core.resolve_module_artifact_paths(out)
        root,_,_=query.core.resolve_safe_paths(args.root,out,scratch)
        result=query_bars(
            root,args.symbol,args.date,gate.read_locator(loc),
            max_candidate_rows=args.max_candidate_rows,
            max_result_bars=args.max_result_bars,
            fast_stat_only=args.fast_stat_only)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as target:
            json.dump(result["safe_summary"],target,indent=2,
                      ensure_ascii=False,allow_nan=False)
            target.write("\n")
        print("Saved aggregate-only experimental locator query:",out)
        print("Selected bars:",len(result["bars"]))
        print("Full source parity performed:",
              result["safe_summary"]["full_arrow_equality_checked_this_invocation"])
        if args.fast_stat_only:
            print("WARNING: unsigned editable locator, no full parity in fast mode; "
                  "NOT safe for unattended production.")
    except (ValueError,TypeError,OSError,OverflowError,
            ModuleNotFoundError,json.JSONDecodeError) as exc:
        ap.error(str(exc))


if __name__=="__main__":
    main()
