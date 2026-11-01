#!/usr/bin/env python3
"""Repeated, SHA-pinned local DAY OHLCVA performance verification.

All real licensed bar values exist only as transient local Python objects.
Compares full row bytes in memory across bounded runs, without persisting
symbols, date windows, OHLCVA, bar fingerprints or individual keys.
Only new aggregate-only reports/ SAFE JSON is written.

FIRST invocation is not a scientifically guaranteed cold-cache sample:
OS and filesystem caches are not cleared or manipulated.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import statistics
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load():
    spec=importlib.util.spec_from_file_location(
        "private_all16_repeated_ohlcva_bench_api",
        HERE/"query-private-2011-2026-all16-ohlcva-local-readonly.py")
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


API=load()
FORMAT="AStockDataTools all16 pinned private local OHLCVA repeated read-only performance v1"
PHASES=(
    "sha_footer_and_rowgroup_preflight_seconds",
    "arrow_key_filter_seconds",
    "sqlite_count_crosscheck_seconds",
)


def _stats(values):
    if not values:
        raise ValueError("Empty private performance samples")
    return {
        "min":round(min(values),6),
        "median":round(statistics.median(values),6),
        "max":round(max(values),6),
    }


def benchmark(version_safe,version_sha256,symbol,first,last,
              *,repeats=3,expected_bars=None,max_candidate_rows=3000000,
              max_result_bars=31):
    if type(repeats) is not int or not 3<=repeats<=7:
        raise ValueError("Only 3..7 bounded SHA re-verified read-only repeats")
    if (expected_bars is not None and
            (type(expected_bars) is not int or
             not 0<=expected_bars<=max_result_bars)):
        raise ValueError("Invalid expected local match count")
    records=[]
    first_signature=None
    first_summary=None
    for run in range(repeats):
        result=API.read_local_bars(
            version_safe,version_sha256,symbol,first,last,
            allow_private_values=True,
            max_candidate_rows=max_candidate_rows,
            max_result_bars=max_result_bars)
        bars=result["bars"]
        safe=result["safe_summary"]
        if (safe.get("source_all16_private_version_sha256")!=version_sha256
                or safe.get("matched_stockday_rows")!=len(bars)
                or safe.get("sqlite_rows_matched")!=len(bars)
                or safe.get("matched_key_rows_vectorized_by_arrow")!=len(bars)
                or safe.get("local_bars_count")!=len(bars)
                or safe.get("all_original_licensed_OHLCVA_values_read") is not True
                or safe.get("local_licensed_OHLCVA_values_exported_to_safe") is not False
                or safe.get("ready_for_production_query") is not False
                or safe.get("ready_for_automatic_market_merge") is not False
                or safe.get("ready_for_h5_mirror") is not False
                or (expected_bars is not None and len(bars)!=expected_bars)):
            raise ValueError("Repeated private OHLCVA result breached SHA/SQLite or count gate")
        digest=hashlib.sha256()
        for bar in bars:
            digest.update(API.Q.PHYS.row_bytes(bar))
        # This fingerprint is NEVER written to the resulting aggregate SAFE.
        signature=(digest.digest(),len(bars),
                   tuple(sorted(safe["by_source_counts"].items())),
                   safe["sha_checked_private_partitions"],
                   safe["candidate_rows_upper_bound"],
                   safe["rowgroups_loaded"])
        if first_signature is None:
            first_signature=signature
            first_summary=safe
        elif signature!=first_signature:
            raise ValueError("Repeated local OHLCVA Float64/source/partition SHA results differ")
        phases=safe.get("phase_timings_seconds")
        if (type(phases) is not dict or set(phases)!=set(PHASES)
                or any(type(phases[p]) not in (int,float) or phases[p]<0
                       for p in PHASES)
                or type(safe.get("elapsed_seconds")) not in (int,float)
                or safe["elapsed_seconds"]<0):
            raise ValueError("Repeated query performance evidence incomplete")
        records.append({
            "ordinal":run+1,
            "elapsed_seconds":safe["elapsed_seconds"],
            "sha_footer_seconds":phases[PHASES[0]],
            "arrow_read_filter_seconds":phases[PHASES[1]],
            "sqlite_crosscheck_seconds":phases[PHASES[2]],
        })
        # Raw rows and transient digest become unreachable after iteration.
    rest=[x["elapsed_seconds"] for x in records[1:]]
    result={
        "format":FORMAT,
        "status":"private_all16_local_ohlcva_repeated_float64_sha_and_sqlite_parity_verified",
        "source_all16_private_version_sha256":version_sha256,
        "sample_count":repeats,
        "matched_rows_per_run":first_summary["matched_stockday_rows"],
        "by_source_counts_per_run":first_summary["by_source_counts"],
        "sha_checked_private_partitions_per_run":
            first_summary["sha_checked_private_partitions"],
        "rowgroups_loaded_per_run":first_summary["rowgroups_loaded"],
        "candidate_rows_upper_bound_per_run":
            first_summary["candidate_rows_upper_bound"],
        "full_float64_row_bytes_equal_across_runs_in_memory":True,
        "all_runs_reverified_full_selected_partition_sha_and_sqlite":True,
        "query_symbol_and_exact_dates_exported":False,
        "market_values_or_float64_fingerprint_exported":False,
        "first_run_os_cache_cold_verified":False,
        "first_observed_run_seconds":records[0]["elapsed_seconds"],
        "subsequent_observed_runs_seconds":rest,
        "subsequent_observed_run_stats_seconds":_stats(rest),
        "all_observed_run_stats_seconds":_stats(
            [x["elapsed_seconds"] for x in records]),
        "sha_footer_phase_seconds":_stats(
            [x["sha_footer_seconds"] for x in records]),
        "arrow_filter_phase_seconds":_stats(
            [x["arrow_read_filter_seconds"] for x in records]),
        "sqlite_crosscheck_phase_seconds":_stats(
            [x["sqlite_crosscheck_seconds"] for x in records]),
        "private_or_production_active_pointer_modified":False,
        "original_source_or_private_market_files_written":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "h5_only_candidate_source_units_certified":False,
    }
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version-safe",type=Path,required=True)
    parser.add_argument("--version-sha256",required=True)
    parser.add_argument("--symbol",required=True)
    parser.add_argument("--start",required=True)
    parser.add_argument("--end",required=True)
    parser.add_argument("--repeats",type=int,default=3)
    parser.add_argument("--expected-bars",type=int,required=True)
    parser.add_argument("--max-candidate-rows",type=int,default=3000000)
    parser.add_argument("--max-result-bars",type=int,default=31)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--benchmark-local-only",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        dest=Path(args.out)
        if (API.Q.M.REPORTS.is_symlink() or dest.is_symlink()
                or dest.exists() or dest.suffix!=".json"
                or dest.resolve().parent!=API.Q.M.REPORTS.resolve()):
            raise ValueError("Only a NEW module reports/ aggregate-only benchmark SAFE")
        doc=benchmark(
            args.version_safe,args.version_sha256,
            args.symbol,args.start,args.end,
            repeats=args.repeats,expected_bars=args.expected_bars,
            max_candidate_rows=args.max_candidate_rows,
            max_result_bars=args.max_result_bars)
        if not doc["full_float64_row_bytes_equal_across_runs_in_memory"]:
            raise ValueError("Repeated real OHLCVA results differ")
        with dest.open("x",encoding="utf-8",newline="\n") as stream:
            json.dump(doc,stream,indent=2,sort_keys=True)
            stream.write("\n")
        print("PASS: pinned private OHLCVA repeats all match exact Float64/SQLite")
        print("Runs:",doc["sample_count"],"Rows per run:",
              doc["matched_rows_per_run"])
        print("First observed seconds:",doc["first_observed_run_seconds"])
        print("Later observed median seconds:",
              doc["subsequent_observed_run_stats_seconds"]["median"])
        print("SAFE:",args.out)
        print("No real values, bar fingerprints, symbols or exact dates exported")
    except Exception:
        parser.error("Private repeat benchmark refused: SHA, original Float64, SQLite, limits or privacy")


if __name__=="__main__":
    main()
