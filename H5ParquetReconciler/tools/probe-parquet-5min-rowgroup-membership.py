#!/usr/bin/env python3
"""Bounded Parquet two-column row-group membership pilot for one 5min stock-day.

Before building a month-long key locator, read only ts/symbol from at most 8
deterministically spread candidate row groups. Report count/slot coverage, not
raw timestamps or licensed OHLCV. This PROBE CANNOT be used for pruning:
unexamined row groups remain unknown. No H5 data is opened.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent


def import_local(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


focused = import_local("focused_5min_membership_source", "analyze-5min-x100-focused-sessions.py")
indexer = import_local("v3_membership_slot_converter", "index-parquet-5min-coverage.py")
core, diagnose = focused.core, focused.diagnose


def chosen_positions(total, limit):
    """Evenly spread, deterministic, unique samples among candidate groups."""
    if (type(total) is not int or total < 0 or type(limit) is not int
            or not 1 <= limit <= 8):
        raise ValueError("Pilot requires a valid nonnegative count and --max-groups 1..8")
    size = min(total, limit)
    if size == 0:
        return []
    if size == 1:
        return [0]
    return [((total - 1) * i) // (size - 1) for i in range(size)]


def candidate_groups(metadata_files, symbols, day):
    """Exactly the existing time & symbol min/max fail-open inclusion rules."""
    _, _, start, end = core.parse_day_range(
        day.year, day.isoformat(), day.isoformat())
    aliases = set().union(*(diagnose.source_spellings(s) for s in symbols))
    rows = []
    total_groups = 0
    for path, pf in metadata_files:
        if not {"ts", "symbol"}.issubset(pf.schema_arrow.names):
            raise ValueError("Missing Parquet key columns in " + Path(path).name)
        for idx in range(pf.metadata.num_row_groups):
            total_groups += 1
            rg = pf.metadata.row_group(idx)
            if not core.row_group_overlaps_timestamp(rg, start, end):
                continue
            if not diagnose.might_contain_symbols(rg, aliases):
                continue
            rows.append((Path(path), pf, idx))
    return rows, total_groups


def summarize_two_column_batches(batches, year, day_integer, symbols):
    """Summarize only selected symbol/day slots; never return raw key rows."""
    selected = set(symbols)
    scanned = valid_day = invalid = 0
    reasons = Counter()
    observed = defaultdict(lambda: {"rows": 0, "slots": set()})
    cache = {}
    for batch in batches:
        if batch.num_columns != 2:
            raise ValueError("Probe can read only ts and symbol key columns")
        times = batch.column(0).to_pylist()
        tickers = batch.column(1).to_pylist()
        if len(times) != len(tickers) or len(times) != batch.num_rows:
            raise ValueError("Parquet two-column batch length mismatch")
        for timestamp, raw_symbol in zip(times, tickers):
            scanned += 1
            normalized = core.symbol_id(raw_symbol)
            if normalized is None:
                reasons["unrecognized_symbol"] += 1
                continue
            pair, error = indexer.minute_slot(timestamp, year, cache)
            if error:
                reasons[error] += 1
                continue
            trade_day, slot = pair
            if trade_day != day_integer:
                continue
            valid_day += 1
            if normalized not in selected:
                continue
            observed[normalized]["rows"] += 1
            observed[normalized]["slots"].add(slot)
    grouped = {}
    for symbol in symbols:
        item = observed[symbol]
        grouped[symbol] = {
            "source_rows_same_symbol_day": item["rows"],
            "unique_regular_five_minute_slots": len(item["slots"]),
            "duplicate_slot_rows": item["rows"] - len(item["slots"]),
            "symbol_day_present_in_this_group": item["rows"] > 0,
        }
    return {
        "source_rows_examined_in_group": scanned,
        "all_symbol_valid_5min_rows_on_target_day": valid_day,
        "key_parse_anomaly_counts_in_sampled_group": dict(sorted(reasons.items())),
        "selected_symbols": grouped,
        "sampled_group_contains_any_selected_symbol_day": any(
            entry["symbol_day_present_in_this_group"]
            for entry in grouped.values()),
    }


def run_probe(metadata_files, symbols, day, max_groups):
    candidates, all_groups = candidate_groups(metadata_files, symbols, day)
    positions = chosen_positions(len(candidates), max_groups)
    out = []
    for pos in positions:
        path, pf, idx = candidates[pos]
        metadata = pf.metadata.row_group(idx)
        batch_iter = pf.iter_batches(
            row_groups=[idx], columns=["ts", "symbol"],
            batch_size=65536, use_threads=True)
        summary = summarize_two_column_batches(
            batch_iter, day.year, int(day.strftime("%Y%m%d")), symbols)
        if summary["source_rows_examined_in_group"] != metadata.num_rows:
            raise ValueError("Sampled Parquet source row count differs from footer")
        out.append({
            "file": path.name,
            "row_group": idx,
            "row_group_source_rows": int(metadata.num_rows),
            **summary,
        })
    return {
        "parquet_files": len(metadata_files),
        "row_groups_all_year": all_groups,
        "row_groups_matching_existing_metadata_filter": len(candidates),
        "sampled_group_count": len(out),
        "sampled_source_rows_total": sum(
            x["source_rows_examined_in_group"] for x in out),
        "sampled_groups_with_selected_keys": sum(
            bool(x["sampled_group_contains_any_selected_symbol_day"])
            for x in out),
        "sampled_groups_without_selected_keys": sum(
            not x["sampled_group_contains_any_selected_symbol_day"] for x in out),
        "per_sample_group": out,
        "columns_read": ["ts", "symbol"],
        "sampled_groups_are_the_only_groups_verified_by_keys": True,
        "unsampled_groups_proven_empty": False,
        "result_is_eligible_for_query_pruning": False,
        "extrapolated_full_month_speedup": None,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--baseline-report", type=Path, required=True)
    ap.add_argument("--top-symbols", type=int, default=3)
    ap.add_argument("--max-groups", type=int, default=3)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
        positions_guard = chosen_positions(0, args.max_groups)
        del positions_guard
        output, scratch = core.resolve_module_artifact_paths(args.out)
        root, _, _ = core.resolve_safe_paths(args.root, output, scratch)
        if (output.suffix.lower() != ".json"
            or not output.is_relative_to((HERE.parent / "reports").resolve())
            or output.exists()):
            raise ValueError("Report must be new JSON inside module reports/")
        baseline_path = args.baseline_report.resolve()
        if baseline_path == output or baseline_path.suffix.lower() != ".json":
            raise ValueError("Baseline must be a separate JSON")
        symbols = tuple(focused.load_baseline(
            json.loads(baseline_path.read_text(encoding="utf-8")),
            day, args.top_symbols))
        import pyarrow.parquet as pq
        paths = core.year_files(root, "5min", day.year)
        if not paths:
            raise ValueError("No Parquet source files for requested year")
        metadata_files = [
            (path, pq.ParquetFile(str(path))) for path in paths
        ]
        result = {
            "format": "AStockDataTools bounded 5min Parquet rowgroup two-column membership pilot v1",
            "date": day.isoformat(),
            "selected_symbols": list(symbols),
            "baseline_report_name": baseline_path.name,
            "max_sampled_groups": args.max_groups,
            "membership_pilot": run_probe(
                metadata_files, symbols, day, args.max_groups),
            "source_market_files_modified": False,
            "h5_source_read": False,
            "parquet_ohlcv_columns_read": False,
            "not_a_completed_index": True,
            "safe_to_automatically_union": False,
            "data_unit_and_bar_label_certified": False,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("Saved bounded two-column membership pilot:", output)
    except (ValueError, OSError, TypeError, OverflowError, json.JSONDecodeError) as error:
        ap.error(str(error))


if __name__ == "__main__":
    main()
