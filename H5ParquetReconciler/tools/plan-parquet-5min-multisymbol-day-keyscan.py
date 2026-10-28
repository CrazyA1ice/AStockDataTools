#!/usr/bin/env python3
"""Read-only, bounded pilot: ONE full (ts,symbol) RowGroup scan for 2..8 stocks/day.

This is a planning EXPERIMENT, not a production reusable index. It inspects
ALL footer candidates for ANY requested symbol, then reads the union of those
RowGroups exactly once, using ONLY ts and symbol. It reports rowgroup locators
and counts (no raw time keys or OHLCVA) under this module's reports/. Neither
the original purchased source nor the production query/cache is changed.

Do not confuse a smaller combined RowGroup upper bound with measured physical
IO savings or a proven speedup. The local JSON is unsigned and not sufficient
for unattended production pruning.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from collections import Counter
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
SPEC = importlib.util.spec_from_file_location(
    "parquet_shared_key_pilot_query", HERE / "query-parquet-primary-readonly.py")
query = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(query)


def requested_symbols(symbols, day, max_candidate_rows, max_keys_per_symbol):
    if not isinstance(symbols, (list, tuple)) or not 2 <= len(symbols) <= 8:
        raise ValueError("Supply 2..8 distinct canonical A-share symbols")
    if (type(max_keys_per_symbol) is not int
            or not 1 <= max_keys_per_symbol <= 100000):
        raise ValueError("--max-keys-per-symbol must be 1..100000")
    canonical = []
    first = None
    for raw in symbols:
        if type(raw) is not str:
            raise ValueError("Symbols must be canonical strings")
        sym, date_first, date_last = query.request_dates(
            raw, "5min", day, day, max_candidate_rows, max_keys_per_symbol)
        if first is not None and (date_first != first or date_last != first):
            raise ValueError("Shared scan must have one date")
        first = date_first
        canonical.append(sym)
    if len(set(canonical)) != len(canonical):
        raise ValueError("Repeated stock symbols are not allowed")
    return sorted(canonical), first


def plan(root, symbols, day, max_candidate_rows=30000000,
         max_candidate_groups=1000, max_keys_per_symbol=25000):
    """One source/RowGroup key-only pass; close all readers on every exit."""
    if type(max_candidate_groups) is not int or not 1 <= max_candidate_groups <= 10000:
        raise ValueError("--max-candidate-groups must be in 1..10000")
    symbols, first = requested_symbols(
        symbols, day, max_candidate_rows, max_keys_per_symbol)
    root = Path(root).resolve()
    purchased = root / "AllCycleAStockData"
    if not root.is_dir() or not purchased.is_dir():
        raise ValueError("Purchased Parquet source root missing")
    started = time.perf_counter()
    before = query.private_cache.source_signature(
        root, "5min", first, first, query.core)
    low_ms, high_ms = query.day_bounds(first, first)
    aliases_by_symbol = {
        sym: set(query.diagnose.source_spellings(sym)) for sym in symbols
    }
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    alias_array = pa.array(
        sorted(set().union(*aliases_by_symbol.values())), type=pa.string())
    pending = []
    stats = Counter()
    individual = {sym: [0, 0] for sym in symbols}
    membership = {sym: [] for sym in symbols}
    seen = {sym: set() for sym in symbols}
    data_start = None
    with ExitStack() as cleanup:
        # Every source Footer is examined before reading any source key column.
        for path in query.core.year_files(root, "5min", first.year):
            stats["source_file_footers_opened"] += 1
            if (path.is_symlink() or not path.is_file()
                    or not path.resolve().is_relative_to(purchased.resolve())):
                raise ValueError("Unsafe purchased Parquet source path")
            pf = pq.ParquetFile(str(path))
            cleanup.callback(pf.close)
            if not set(query.NEEDED).issubset(pf.schema_arrow.names):
                raise ValueError("Missing source ts/symbol/OHLCVA columns")
            if not query.monthly_filename_overlaps_query(
                    path, purchased / "5min", first, first):
                if all(not query.core.row_group_overlaps_timestamp(
                        pf.metadata.row_group(gid), low_ms, high_ms)
                        for gid in range(pf.metadata.num_row_groups)):
                    stats["month_files_skipped_with_footer_confirmation"] += 1
                    continue
            for gid in range(pf.metadata.num_row_groups):
                rg = pf.metadata.row_group(gid)
                if not query.core.row_group_overlaps_timestamp(
                        rg, low_ms, high_ms):
                    continue
                eligible = [
                    sym for sym in symbols
                    if query.diagnose.might_contain_symbols(
                        rg, aliases_by_symbol[sym])
                ]
                for sym in eligible:
                    individual[sym][0] += 1
                    individual[sym][1] += rg.num_rows
                if not eligible:
                    continue
                stats["union_candidate_source_rows_upper_bound"] += rg.num_rows
                pending.append((path, pf, gid, frozenset(eligible)))
                if len(pending) > max_candidate_groups:
                    raise ValueError("Union exceeds --max-candidate-groups")
                if stats["union_candidate_source_rows_upper_bound"] > max_candidate_rows:
                    raise ValueError("Union exceeds --max-candidate-rows")
        stats["union_candidate_row_groups"] = len(pending)
        data_start = time.perf_counter()
        examined = 0
        # No parquet data columns beyond ts/symbol are accessed.
        for path, pf, gid, eligible in pending:
            rg = pf.metadata.row_group(gid)
            group_count = Counter()
            source_rows = 0
            for batch in pf.iter_batches(
                    row_groups=[gid], columns=["ts", "symbol"],
                    batch_size=65536, use_threads=True):
                if (batch.num_columns != 2
                        or batch.schema.names != ["ts", "symbol"]):
                    raise ValueError("Key-only scanner received unexpected columns")
                source_rows += batch.num_rows
                mask = pc.and_(
                    pc.is_in(batch.column(1), value_set=alias_array),
                    pc.and_(pc.greater_equal(batch.column(0), low_ms),
                            pc.less(batch.column(0), high_ms)))
                for row in batch.filter(mask).to_pylist():
                    sym = query.core.symbol_id(row["symbol"])
                    if sym not in seen:
                        continue
                    if sym not in eligible:
                        # The original conservative Footer index must not
                        # discard an actual matching source stock.
                        raise ValueError("Footer symbol pruning contradicted source keys")
                    stamp = row["ts"]
                    if type(stamp) is not int or stamp % 60000:
                        raise ValueError("Non-minute source timestamp")
                    dt = datetime.fromtimestamp(stamp / 1000, tz=query.core.UTC8)
                    if dt.date() != first:
                        raise ValueError("Selected key outside requested trading day")
                    if stamp in seen[sym]:
                        raise ValueError("Duplicate source timestamp for " + sym)
                    seen[sym].add(stamp)
                    if len(seen[sym]) > max_keys_per_symbol:
                        raise ValueError("Selected keys exceed --max-keys-per-symbol")
                    group_count[sym] += 1
            if source_rows != rg.num_rows:
                raise ValueError("Incomplete RowGroup key-only read")
            examined += source_rows
            for sym, count in group_count.items():
                membership[sym].append({
                    "source_file_relative_path": path.relative_to(root).as_posix(),
                    "row_group": gid,
                    "matching_key_count": count,
                })
        if examined != stats["union_candidate_source_rows_upper_bound"]:
            raise ValueError("Union key-column source rows failed conservation")
        after = query.private_cache.source_signature(
            root, "5min", first, first, query.core)
        if before != after:
            raise ValueError("Source stat manifest changed during shared key scan")
        for sym in symbols:
            if sum(x["matching_key_count"] for x in membership[sym]) != len(seen[sym]):
                raise ValueError("Per-stock RowGroup membership count mismatch")

    individual_sum = sum(v[1] for v in individual.values())
    return {
        "format": "AStockDataTools shared 5min single-day multiple-symbol key-only RowGroup plan v1",
        "date": first.isoformat(), "period": "5min",
        "requested_distinct_symbol_count": len(symbols),
        "per_symbol": [{
            "symbol": sym,
            "individual_footer_candidate_row_groups": individual[sym][0],
            "individual_footer_candidate_source_rows_upper_bound": individual[sym][1],
            "matching_source_keys": len(seen[sym]),
            "exact_row_groups_containing_keys": len(membership[sym]),
            "nonempty_row_group_locators": membership[sym],
        } for sym in symbols],
        "union_candidate_row_groups": stats["union_candidate_row_groups"],
        "union_candidate_source_rows_upper_bound": stats[
            "union_candidate_source_rows_upper_bound"],
        "union_source_key_rows_examined_once": examined,
        "sum_of_independent_symbol_footer_row_upper_bounds": individual_sum,
        "theoretical_rowgroup_row_upper_bound_saved_vs_independent_scans":
            individual_sum - examined,
        "source_file_footers_opened_once_for_all_symbols":
            stats["source_file_footers_opened"],
        "source_stat_manifest_sha256": before["manifest_sha256_stat_only"],
        "source_stat_manifest_file_count": before["manifest_file_count"],
        "source_stat_manifest_stable_during_scan": True,
        "manifest_stat_only_not_content_hash": True,
        "every_union_footer_candidate_group_scanned": True,
        "only_ts_and_symbol_columns_read": True,
        "all_parquet_readers_explicitly_closed": True,
        "source_key_scan_seconds": round(time.perf_counter() - data_start, 6),
        "whole_planning_seconds": round(time.perf_counter() - started, 6),
        "physical_disk_bytes_saved_unknown": True,
        "net_query_speedup_not_proven": True,
        "no_production_pruning_or_index_installation": True,
        "this_report_is_not_a_trusted_production_locator": True,
        "no_original_ohlcva_in_report": True,
        "h5_source_accessed": False,
        "source_market_files_modified": False,
        "automatic_source_union_or_import_performed": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--symbols", required=True,
                    help="Comma-separated 2..8 canonical A-share symbols")
    ap.add_argument("--date", required=True)
    ap.add_argument("--max-candidate-rows", type=int, default=30000000)
    ap.add_argument("--max-candidate-groups", type=int, default=1000)
    ap.add_argument("--max-keys-per-symbol", type=int, default=25000)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        symbols = args.symbols.split(",")
        if any(not s or s != s.strip() for s in symbols):
            raise ValueError("Provide comma-separated symbols without extra spaces")
        out, scratch = query.core.resolve_module_artifact_paths(args.out)
        root, _, _ = query.core.resolve_safe_paths(args.root, out, scratch)
        if (out.suffix.lower() != ".json" or out.exists()
                or not out.is_relative_to((MODULE / "reports").resolve())):
            raise ValueError("Use a NEW JSON file inside H5ParquetReconciler/reports/")
        report = plan(root, symbols, args.date, args.max_candidate_rows,
                      args.max_candidate_groups, args.max_keys_per_symbol)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as target:
            json.dump(report, target, ensure_ascii=False, indent=2, allow_nan=False)
            target.write("\n")
        print("Saved metadata-only multisymbol key scan:", out)
        print("Symbols:", report["requested_distinct_symbol_count"],
              "shared source rows:", report["union_source_key_rows_examined_once"])
        print("No OHLCVA, no production index, no source edits.")
    except (ValueError, TypeError, OSError, OverflowError, ModuleNotFoundError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
