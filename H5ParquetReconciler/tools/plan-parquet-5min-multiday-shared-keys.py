#!/usr/bin/env python3
"""BOUNDED opt-in 5min key-only pilot: multiple stocks x dates in ONE month.

Plan every stock/day RowGroup locator from ONE pass of union footer-candidate
RowGroups, projecting ONLY ts and symbol. Do not read OHLCVA, create a licensed
cache or install any reusable production index. User-editable JSON locators
are NOT trusted for automatic production pruning.

Full source-row/RowGroup budgets are checked BEFORE key scanning. Results
contain only dates, symbol IDs, source RowGroup coordinates and counts, never
raw source timestamps or purchased OHLCVA. Source stats are checked before
and after. All opened ParquetFile handles close even if validation fails.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from collections import Counter
from contextlib import ExitStack
from datetime import timedelta, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
SPEC = importlib.util.spec_from_file_location(
    "multiday_5min_shared_query", HERE / "query-parquet-primary-readonly.py")
query = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(query)


def validated_request(symbols, first, last, max_candidate_rows,
                      max_keys_per_stock_day, max_total_keys):
    if type(symbols) not in (list, tuple) or not 2 <= len(symbols) <= 8:
        raise ValueError("Supply 2..8 distinct canonical A-share symbols")
    if type(max_keys_per_stock_day) is not int or not (
            1 <= max_keys_per_stock_day <= 100000):
        raise ValueError("--max-keys-per-stock-day must be 1..100000")
    if type(max_total_keys) is not int or not 1 <= max_total_keys <= 100000:
        raise ValueError("--max-total-keys must be 1..100000")
    canonical = []
    start = end = None
    for sym in symbols:
        if type(sym) is not str:
            raise ValueError("A-share symbols must be strings")
        name, a, b = query.request_dates(
            sym, "5min", first, last, max_candidate_rows,
            max_keys_per_stock_day)
        canonical.append(name)
        if start is None:
            start, end = a, b
        elif start != a or end != b:
            raise ValueError("Stock window disagrees between symbols")
    if len(set(canonical)) != len(canonical):
        raise ValueError("Duplicate requested symbol")
    if start.year != end.year or start.month != end.month:
        raise ValueError("Shared multi-day pilot requires a single calendar month")
    days = []
    date_cursor = start
    while date_cursor <= end:
        days.append(date_cursor.isoformat())
        date_cursor += timedelta(days=1)
    if len(days) * len(canonical) > 248:
        raise ValueError("Exceeded 248 bounded stock-day records")
    return sorted(canonical), start, end, days


def plan(root, symbols, first, last, max_candidate_rows=30000000,
         max_candidate_groups=1000, max_keys_per_stock_day=25000,
         max_total_keys=25000):
    """No partial files on failure. Every union RowGroup is scanned once."""
    if type(max_candidate_groups) is not int or not (
            1 <= max_candidate_groups <= 10000):
        raise ValueError("--max-candidate-groups must be 1..10000")
    symbols, start, end, days = validated_request(
        symbols, first, last, max_candidate_rows,
        max_keys_per_stock_day, max_total_keys)
    root = Path(root).resolve()
    purchased = (root / "AllCycleAStockData").resolve()
    if not root.is_dir() or not purchased.is_dir():
        raise ValueError("Purchased Parquet root not found")
    started = time.perf_counter()
    signature_before = query.private_cache.source_signature(
        root, "5min", start, end, query.core)
    low_ms, high_ms = query.day_bounds(start, end)

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    aliases_by_stock = {
        sym: set(query.diagnose.source_spellings(sym)) for sym in symbols}
    all_aliases = pa.array(
        sorted(set().union(*aliases_by_stock.values())), type=pa.string())

    preflight = Counter()
    independent = {sym: [0, 0] for sym in symbols}
    found = {(sym, day): set() for sym in symbols for day in days}
    matched_groups = Counter()
    pending = []
    with ExitStack() as closer:
        # No ts/symbol batches until ALL union candidate costs are accounted.
        for path in query.core.year_files(root, "5min", start.year):
            if (path.is_symlink() or not path.is_file()
                    or not path.resolve().is_relative_to(purchased)):
                raise ValueError("Unsafe purchased Parquet source path")
            pf = pq.ParquetFile(str(path))
            closer.callback(pf.close)
            preflight["source_file_footers_opened"] += 1
            if not set(query.NEEDED).issubset(pf.schema_arrow.names):
                raise ValueError("Missing required Parquet source columns")
            if not query.monthly_filename_overlaps_query(
                    path, purchased / "5min", start, end):
                if all(not query.core.row_group_overlaps_timestamp(
                        pf.metadata.row_group(i), low_ms, high_ms)
                       for i in range(pf.metadata.num_row_groups)):
                    preflight["nonmatching_month_files_skipped_after_footer"] += 1
                    continue
            for gid in range(pf.metadata.num_row_groups):
                rg = pf.metadata.row_group(gid)
                if not query.core.row_group_overlaps_timestamp(
                        rg, low_ms, high_ms):
                    continue
                eligible = frozenset(
                    sym for sym in symbols if query.diagnose.might_contain_symbols(
                        rg, aliases_by_stock[sym]))
                for sym in eligible:
                    independent[sym][0] += 1
                    independent[sym][1] += rg.num_rows
                if not eligible:
                    continue
                pending.append((path, pf, gid, eligible))
                preflight["union_source_rows_upper_bound"] += rg.num_rows
                if len(pending) > max_candidate_groups:
                    raise ValueError("Union exceeds --max-candidate-groups")
                if preflight["union_source_rows_upper_bound"] > max_candidate_rows:
                    raise ValueError("Union exceeds --max-candidate-rows")
        scan_started = time.perf_counter()
        scanned = 0
        key_count = 0
        for path, pf, gid, eligible in pending:
            rg = pf.metadata.row_group(gid)
            rows_this_group = 0
            relative = path.relative_to(root).as_posix()
            for batch in pf.iter_batches(
                    row_groups=[gid], columns=["ts", "symbol"],
                    batch_size=65536, use_threads=True):
                if (batch.num_columns != 2 or
                        batch.schema.names != ["ts", "symbol"]):
                    raise ValueError("Key-only scanner projected wrong columns")
                rows_this_group += batch.num_rows
                mask = pc.and_(
                    pc.is_in(batch.column(1), value_set=all_aliases),
                    pc.and_(pc.greater_equal(batch.column(0), low_ms),
                            pc.less(batch.column(0), high_ms)))
                for item in batch.filter(mask).to_pylist():
                    sym = query.core.symbol_id(item["symbol"])
                    if sym not in independent:
                        continue
                    if sym not in eligible:
                        raise ValueError("Footer symbol pruning contradicted source")
                    ts = item["ts"]
                    if type(ts) is not int or ts % 60000:
                        raise ValueError("Non-minute timestamp for selected stock")
                    day = datetime.fromtimestamp(
                        ts / 1000, tz=query.core.UTC8).date().isoformat()
                    pair = (sym, day)
                    if pair not in found:
                        raise ValueError("Selected timestamp outside requested dates")
                    if ts in found[pair]:
                        raise ValueError("Duplicate selected stock/date timestamp")
                    found[pair].add(ts)
                    if len(found[pair]) > max_keys_per_stock_day:
                        raise ValueError("--max-keys-per-stock-day exceeded")
                    key_count += 1
                    if key_count > max_total_keys:
                        raise ValueError("--max-total-keys exceeded")
                    matched_groups[(sym, day, relative, gid)] += 1
            if rows_this_group != rg.num_rows:
                raise ValueError("Incomplete key-column RowGroup scan")
            scanned += rows_this_group
        if scanned != preflight["union_source_rows_upper_bound"]:
            raise ValueError("Union RowGroup source-row count not conserved")
        scan_seconds = round(time.perf_counter() - scan_started, 6)
        signature_after = query.private_cache.source_signature(
            root, "5min", start, end, query.core)
        if signature_before != signature_after:
            raise ValueError("Source stat manifest changed during multi-day scan")

    source_row_sum = sum(v[1] for v in independent.values())
    daily = []
    per_stock = []
    for sym in symbols:
        sumkeys = 0
        for day in days:
            locators = [
                {"source_file_relative_path": path,
                 "row_group": gid, "matching_key_count": count}
                for (stock, locday, path, gid), count in
                sorted(matched_groups.items())
                if stock == sym and locday == day
            ]
            n = len(found[(sym, day)])
            if sum(e["matching_key_count"] for e in locators) != n:
                raise ValueError("Per-stock-day membership count not conserved")
            sumkeys += n
            daily.append({
                "symbol": sym, "date": day,
                "matching_source_keys": n,
                "exact_row_groups_containing_keys": len(locators),
                "nonempty_row_group_locators": locators,
            })
        per_stock.append({
            "symbol": sym,
            "independent_footer_candidate_row_groups": independent[sym][0],
            "independent_footer_candidate_source_rows_upper_bound":
                independent[sym][1],
            "matching_source_keys_all_days": sumkeys,
        })
    if sum(x["matching_source_keys"] for x in daily) != key_count:
        raise ValueError("Total selected stock-day keys not conserved")
    return {
        "format": "AStockDataTools bounded monthly multisymbol 5min key-only locator pilot v1",
        "period": "5min", "from_date": start.isoformat(),
        "to_date": end.isoformat(), "requested_calendar_days": len(days),
        "requested_distinct_symbol_count": len(symbols),
        "requested_symbol_day_count": len(daily),
        "per_symbol": per_stock,
        "per_symbol_day": daily,
        "matching_keys_all_stock_days": key_count,
        "union_footer_candidate_row_groups": len(pending),
        "union_footer_candidate_source_rows_upper_bound":
            preflight["union_source_rows_upper_bound"],
        "union_source_key_rows_examined_once": scanned,
        "sum_of_independent_symbol_footer_row_upper_bounds": source_row_sum,
        "theoretical_rows_avoided_vs_independent_symbol_scans":
            source_row_sum - scanned,
        "source_file_footers_opened_once": preflight[
            "source_file_footers_opened"],
        "source_stat_manifest_sha256": signature_before[
            "manifest_sha256_stat_only"],
        "source_stat_manifest_file_count": signature_before[
            "manifest_file_count"],
        "source_stat_manifest_stable_during_scan": True,
        "source_manifest_stat_only_not_content_sha256": True,
        "all_union_footer_candidate_groups_key_columns_scanned": True,
        "only_ts_and_symbol_columns_read": True,
        "all_parquet_readers_explicitly_closed": True,
        "one_pass_key_scan_seconds": scan_seconds,
        "whole_planning_seconds": round(
            time.perf_counter() - started, 6),
        "physical_disk_bytes_read_or_saved_unknown": True,
        "net_end_to_end_query_speedup_not_measured": True,
        "locator_unsigned_not_trusted_for_production": True,
        "production_default_engine_unchanged": True,
        "no_raw_ohlcva_or_individual_intraday_time_keys_exported": True,
        "no_h5_read": True,
        "source_market_files_modified": False,
        "automatic_source_union_or_import_performed": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--max-candidate-rows", type=int, default=30000000)
    ap.add_argument("--max-candidate-groups", type=int, default=1000)
    ap.add_argument("--max-keys-per-stock-day", type=int, default=25000)
    ap.add_argument("--max-total-keys", type=int, default=25000)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        symbols = args.symbols.split(",")
        if any(not s or s != s.strip() for s in symbols):
            raise ValueError("Provide canonical comma-separated symbols")
        out, scratch = query.core.resolve_module_artifact_paths(args.out)
        root, _, _ = query.core.resolve_safe_paths(args.root, out, scratch)
        if (out.suffix.lower() != ".json" or out.exists()
                or not out.is_relative_to((MODULE / "reports").resolve())):
            raise ValueError("Use NEW JSON under H5ParquetReconciler/reports/")
        result = plan(
            root, symbols, args.from_date, args.to_date,
            args.max_candidate_rows, args.max_candidate_groups,
            args.max_keys_per_stock_day, args.max_total_keys)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as fd:
            json.dump(result, fd, ensure_ascii=False, indent=2,
                      allow_nan=False)
            fd.write("\n")
        print("Saved bounded multi-day multisymbol key-only report:", out)
        print("Source rows scanned once:",
              result["union_source_key_rows_examined_once"],
              "symbols:", result["requested_distinct_symbol_count"],
              "days:", result["requested_calendar_days"])
        print("No OHLCVA, H5, production index or source edits.")
    except (ValueError, TypeError, OSError, OverflowError,
            ModuleNotFoundError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
