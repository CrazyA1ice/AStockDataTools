#!/usr/bin/env python3
"""Exact 5min single-stock/day RowGroup membership PREVIEW using only ts/symbol.

Unlike a sample or footer min/max estimate, examines EVERY time/symbol footer
candidate RowGroup's two key columns, and records groups that contain actual
matching keys. Does NOT read OHLCVA, prune a production query, modify source
data, or create a writable query/index cache. A source STAT manifest, not the
Parquet byte contents, is verified before and after the scan.

Reports contain only counts and RowGroup locators, NEVER source key rows or
licensed OHLCVA. Real savings in CPU, physical IO or wall time remain unproven
until a separate parity-preserving query implementation is benchmarked.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
SPEC = importlib.util.spec_from_file_location(
    "purchased_parquet_exact_rowgroup_query",
    HERE / "query-parquet-primary-readonly.py")
query = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(query)


def plan(root, symbol, day, max_candidate_rows=30000000,
         max_candidate_groups=1000, max_result_keys=25000):
    """Full key-only scan; zero OHLCVA access. Fail closed on any partial work."""
    if (type(max_candidate_groups) is not int
            or not 1 <= max_candidate_groups <= 10000):
        raise ValueError("max_candidate_groups must be in 1..10000")
    if (type(max_result_keys) is not int or
            not 1 <= max_result_keys <= 100000):
        raise ValueError("max_result_keys must be in 1..100000")
    symbol, first, last = query.request_dates(
        symbol, "5min", day, day, max_candidate_rows, max_result_keys)
    if first != last:
        raise ValueError("Exact locator only supports one source day")
    started = time.perf_counter()
    before = query.private_cache.source_signature(
        root, "5min", first, last, query.core)
    ctx = query.prepare_query(
        root, symbol, "5min", first, last,
        max_candidate_rows, max_result_keys)
    if len(ctx["pending"]) > max_candidate_groups:
        raise ValueError("Candidate RowGroups exceed --max-candidate-groups")
    import pyarrow as pa
    import pyarrow.compute as pc
    aliases = pa.array(sorted(ctx["aliases"]), type=pa.string())
    selected = []
    missing_groups = 0
    examined = 0
    seen_stamps = set()
    for path, pf, group in ctx["pending"]:
        rg = pf.metadata.row_group(group)
        group_rows = 0
        matches = 0
        batches = pf.iter_batches(
            row_groups=[group], columns=["ts", "symbol"],
            batch_size=65536, use_threads=True)
        for batch in batches:
            if (batch.num_columns != 2
                    or batch.schema.names != ["ts", "symbol"]):
                raise ValueError("Key-only scanner received wrong columns")
            group_rows += batch.num_rows
            mask = pc.and_(
                pc.is_in(batch.column(1), value_set=aliases),
                pc.and_(
                    pc.greater_equal(batch.column(0), ctx["low_ms"]),
                    pc.less(batch.column(0), ctx["high_ms"])))
            for row in batch.filter(mask).to_pylist():
                if query.core.symbol_id(row["symbol"]) != symbol:
                    # Never prune on an alias that is not actually canonical.
                    continue
                stamp = row["ts"]
                if type(stamp) is not int or stamp % 60000:
                    raise ValueError("Non-minute source timestamp for selected symbol")
                raw = datetime.fromtimestamp(stamp / 1000, tz=query.core.UTC8)
                if raw.date() != first:
                    raise ValueError("Selected source timestamp outside trading date")
                if stamp in seen_stamps:
                    raise ValueError("Duplicate timestamp across source RowGroups")
                seen_stamps.add(stamp)
                matches += 1
                if len(seen_stamps) > max_result_keys:
                    raise ValueError("Result key count exceeds --max-result-keys")
        if group_rows != rg.num_rows:
            raise ValueError("Incomplete key-column scan of candidate RowGroup")
        examined += group_rows
        if matches:
            selected.append({
                "source_file_relative_path": path.relative_to(
                    ctx["root"]).as_posix(),
                "row_group": group,
                "matching_key_count": matches,
            })
        else:
            missing_groups += 1
    after = query.private_cache.source_signature(
        root, "5min", first, last, query.core)
    if before != after:
        raise ValueError("Parquet source stat manifest changed during full key scan")
    if examined != ctx["metadata"]["candidate_source_rows_upper_bound"]:
        raise ValueError("Full key-column scan failed source row conservation")
    if sum(e["matching_key_count"] for e in selected) != len(seen_stamps):
        raise ValueError("Selected membership counts failed conservation")
    return {
        "format": "AStockDataTools exact single 5min symbol-day RowGroup key membership v1",
        "symbol": symbol,
        "date": first.isoformat(), "period": "5min",
        "candidate_row_groups": len(ctx["pending"]),
        "candidate_source_rows_upper_bound": ctx["metadata"][
            "candidate_source_rows_upper_bound"],
        "two_key_columns_source_rows_examined": examined,
        "exact_groups_containing_target_keys": len(selected),
        "exact_groups_without_target_keys": missing_groups,
        "matching_source_keys": len(seen_stamps),
        "nonempty_source_row_group_locators": selected,
        "source_stat_manifest_sha256": before["manifest_sha256_stat_only"],
        "source_stat_manifest_file_count": before["manifest_file_count"],
        "source_manifest_stat_only_not_content_sha256": True,
        "source_manifest_stable_during_key_scan": True,
        "ALL_footer_candidate_groups_key_columns_scanned": True,
        "only_ts_and_symbol_columns_read": True,
        "rowgroup_pruning_is_a_possible_future_optimization_not_applied": True,
        "possible_row_groups_to_omit_if_sources_unchanged": missing_groups,
        "physical_parquet_io_saved_unknown": True,
        "net_query_speedup_not_measured": True,
        "current_production_query_modified": False,
        "automatic_source_union_or_import_performed": False,
        "raw_ohlcva_exported": False,
        "h5_source_accessed": False,
        "source_market_files_modified": False,
        "elapsed_seconds_of_key_only_scan_including_footer_preflight": round(
            time.perf_counter() - started, 6),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--max-candidate-rows", type=int, default=30000000)
    parser.add_argument("--max-candidate-groups", type=int, default=1000)
    parser.add_argument("--max-result-keys", type=int, default=25000)
    parser.add_argument("--read-only", action="store_true", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        out, scratch = query.core.resolve_module_artifact_paths(args.out)
        root, _, _ = query.core.resolve_safe_paths(args.root, out, scratch)
        if (out.suffix.lower() != ".json" or out.exists()
                or not out.is_relative_to((MODULE / "reports").resolve())):
            raise ValueError("Use NEW JSON inside H5ParquetReconciler/reports/")
        summary = plan(root, args.symbol, args.date, args.max_candidate_rows,
                       args.max_candidate_groups, args.max_result_keys)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as fd:
            json.dump(summary, fd, ensure_ascii=False, indent=2, allow_nan=False)
            fd.write("\n")
        print("Saved exact two-key-column RowGroup plan:", out)
        print("Candidate groups:", summary["candidate_row_groups"],
              "with keys:", summary["exact_groups_containing_target_keys"],
              "without keys:", summary["exact_groups_without_target_keys"])
        print("No source edits, no production pruning, no OHLCVA export.")
    except (ValueError, TypeError, OSError, OverflowError,
            ModuleNotFoundError) as e:
        parser.error(str(e))


if __name__ == "__main__":
    main()
