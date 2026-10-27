#!/usr/bin/env python3
"""EXPERIMENTAL opt-in Parquet Arrow filtered query. Never changes default engine.

Reuse the proven RowGroup-fragment predicate from the cold A/B benchmark.
The public Python API returns OHLCVA only in process memory; CLI writes ONLY
aggregate metadata under H5ParquetReconciler/reports/. No licensed cache, H5,
SQLite, source modification, unit conversion, or automatic source union.

This is a *preview*, NOT a production default. Enable --verify-rowgroup to
compare the exact output (OHLCVA, timestamp, file, RowGroup) against the
current default engine on the same local request; that option is deliberately
slower. Source stat signature is checked before and after, but not SHA of bytes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
SPEC = importlib.util.spec_from_file_location(
    "parquet_arrow_preview_benchmark",
    HERE / "benchmark-parquet-arrow-filter-cold.py")
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)
query = benchmark.query


def query_bars(root, symbol, period, start, end,
               max_candidate_rows=30000000, max_result_bars=25000,
               verify_rowgroup=False):
    """Return real Arrow-filtered OHLCVA bars in memory plus a SAFE summary."""
    canonical, first, last = query.request_dates(
        symbol, period, start, end, max_candidate_rows, max_result_bars)
    if type(verify_rowgroup) is not bool:
        raise ValueError("verify_rowgroup must be a boolean")
    before = query.private_cache.source_signature(
        root, period, first, last, query.core)
    result = benchmark.arrow_filtered_query(
        root, canonical, period, first, last, max_candidate_rows,
        max_result_bars)
    measurement = result["safe_measurement"]
    after = query.private_cache.source_signature(
        root, period, first, last, query.core)
    if before != after:
        raise ValueError("Source stat manifest changed during Arrow preview")
    bars = result["bars"]
    if len(bars) != measurement["selected_matching_bars"]:
        raise ValueError("Arrow selected bar count differs from its measurement")
    if (measurement["arrow_rows_emitted_after_predicate"]
            < len(bars)):
        raise ValueError("Arrow emitted fewer rows than selected")
    baseline = None
    if verify_rowgroup:
        baseline = query.query_bars(
            root, canonical, period, first, last, max_candidate_rows,
            max_result_bars, local_cache=False)
        after_verify = query.private_cache.source_signature(
            root, period, first, last, query.core)
        if before != after_verify:
            raise ValueError("Source stat manifest changed during verification")
        if baseline["bars"] != bars:
            raise ValueError("Arrow output differs from RowGroup OHLCVA/time/provenance")
    if (type(measurement["query_elapsed_seconds_this_invocation"])
            not in (int, float)
            or not math.isfinite(
                measurement["query_elapsed_seconds_this_invocation"])
            or measurement["query_elapsed_seconds_this_invocation"] < 0):
        raise ValueError("Invalid Arrow preview elapsed time")
    safe_summary = {
        "format": "AStockDataTools Parquet Arrow opt-in preview summary v1",
        "engine": "experimental_arrow_dataset_rowgroup_fragment_filter",
        "production_default_engine_unchanged": True,
        "symbol": canonical, "period": period,
        "from_date": first.isoformat(), "to_date": last.isoformat(),
        "matching_bar_count": len(bars),
        "candidate_row_groups": measurement["candidate_row_groups"],
        "candidate_source_rows_upper_bound": measurement[
            "candidate_source_rows_upper_bound"],
        "row_groups_that_emitted_filtered_rows": measurement[
            "row_groups_that_emitted_filtered_rows"],
        "arrow_rows_emitted_after_predicate": measurement[
            "arrow_rows_emitted_after_predicate"],
        "source_file_footers_opened": measurement[
            "source_file_footers_opened"],
        "arrow_engine_elapsed_seconds": measurement[
            "query_elapsed_seconds_this_invocation"],
        "source_stat_manifest_sha256": before["manifest_sha256_stat_only"],
        "source_stat_manifest_file_count": before["manifest_file_count"],
        "source_manifest_stat_only_not_content_sha256": True,
        "source_stat_manifest_stable_during_query": True,
        "rowgroup_exact_equality_verified_this_invocation": bool(
            verify_rowgroup),
        "baseline_elapsed_seconds_if_verified": (
            baseline["safe_summary"]["query_elapsed_seconds_this_invocation"]
            if baseline else None),
        "actual_parquet_rows_decoded_unknown": True,
        "actual_disk_bytes_read_unknown": True,
        "arrow_output_rows_are_not_physical_rows_read": True,
        "local_private_ohlcva_cache_used": False,
        "no_raw_ohlcva_in_safe_summary": True,
        "no_h5_read": True,
        "source_market_files_modified": False,
        "automatic_source_union_or_import_performed": False,
    }
    return {"bars": bars, "safe_summary": safe_summary}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--period", choices=query.PERIODS, required=True)
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--max-candidate-rows", type=int, default=30000000)
    ap.add_argument("--max-result-bars", type=int, default=25000)
    ap.add_argument("--verify-rowgroup", action="store_true",
                    help="Optional slower exact equality verification against "
                         "the default engine (no private cache)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        out, scratch = query.core.resolve_module_artifact_paths(args.out)
        root, _, _ = query.core.resolve_safe_paths(args.root, out, scratch)
        if (out.suffix.lower() != ".json" or out.exists()
                or not out.is_relative_to((MODULE / "reports").resolve())):
            raise ValueError("Use NEW JSON inside H5ParquetReconciler/reports/")
        result = query_bars(
            root, args.symbol, args.period, args.from_date, args.to_date,
            args.max_candidate_rows, args.max_result_bars,
            verify_rowgroup=args.verify_rowgroup)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as fh:
            json.dump(result["safe_summary"], fh, indent=2,
                      ensure_ascii=False, allow_nan=False)
            fh.write("\n")
        print("Saved aggregate-only experimental Arrow query summary:", out)
        print("Matched bars:", result["safe_summary"]["matching_bar_count"])
        print("Default production RowGroup engine remains unchanged.")
    except (ValueError, TypeError, OSError, OverflowError,
            ModuleNotFoundError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
