#!/usr/bin/env python3
"""Focused read-only H5×100 five-minute residual-session forensics.

Use the top residual stock-days in an existing complete, one-day H5/PQ
reconciliation JSON. Read only those H5 symbols and filter Parquet by symbol
and day using row-group metadata where possible. No raw OHLCV in outputs.
This is a hypothesis diagnostic; it never certifies units or merges data.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "session_for_focused_x100", HERE / "analyze-5min-session-conservation.py")
session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(session)
diagnose = session.diagnostic
core = diagnose.core
MASKS = core.CANDIDATE_RESIDUAL_MASKS


def load_baseline(data: dict, day: date, count: int):
    """Select high-conflict securities from a completed exact-mask report."""
    if not 1 <= count <= 8:
        raise ValueError("--top-symbols must be in 1..8")
    if (not isinstance(data, dict)
        or data.get("format") !=
           "AStockDataTools H5-Parquet local coverage/difference report v1"
        or data.get("status") != "complete"
        or data.get("requested_from_date") != day.isoformat()
        or data.get("requested_to_date") != day.isoformat()
        or data.get("requested_periods") not in (["5min"], ["day", "5min"])
        or data.get("requested_years") != [day.year]
        or data.get("universe_mode") != "a-share-candidate"
        or data.get("eligible_for_automatic_union") is not False):
        raise ValueError("Require a matching completed single-day 5min candidate report")
    results = data.get("results")
    if not isinstance(results, dict):
        raise ValueError("Missing bounded source result sections")
    expected = (
        {f"day/{day.year}", f"5min/{day.year}"}
        if data["requested_periods"] == ["day", "5min"]
        else {f"5min/{day.year}"}
    )
    if set(results) != expected:
        raise ValueError("Source section set differs from requested periods")
    if "day" in data["requested_periods"]:
        daily = results[f"day/{day.year}"]
        if (not isinstance(daily, dict)
                or daily.get("period") != "day"
                or daily.get("year") != day.year
                or daily.get("from_date") != day.isoformat()
                or daily.get("to_date") != day.isoformat()
                or daily.get("universe_mode") != "a-share-candidate"
                or daily.get("scan_complete") is not True
                or daily.get("issues") != []
                or daily.get("safe_to_automatically_union") is not False):
            raise ValueError("Incomplete or mismatched day companion for focused 5min source")
    section = data.get("results", {}).get(f"5min/{day.year}")
    if (not isinstance(section, dict)
        or section.get("scan_complete") is not True
        or section.get("issues") != []
        or section.get("safe_to_automatically_union") is not False):
        raise ValueError("Incomplete or unsafe baseline source section")
    candidate = section.get("quantity_scale_diagnostics", {}).get(
        "h5_volume_times_100_candidate", {})
    top = candidate.get("exact_residual_top_stock_days")
    counts = candidate.get("exact_residual_field_mask_counts")
    if (not isinstance(top, list) or not top
        or not candidate.get("exact_masks_are_mutually_exclusive")
        or not isinstance(counts, dict)
        or set(counts) != set(MASKS)):
        raise ValueError("Baseline is missing certified-internal exact mask counts")
    if len(top) < count:
        raise ValueError("Baseline does not contain enough selected stock-days")
    selection = {}
    for item in top[:count]:
        symbol = item.get("symbol")
        masks = item.get("field_mask_counts")
        if (not isinstance(symbol, str)
            or core.symbol_id(symbol) != symbol
            or not core.is_a_share_candidate(symbol, day.year)
            or item.get("day") != day.strftime("%Y%m%d")
            or symbol in selection
            or not isinstance(masks, dict)
            or not masks
            or any(k not in MASKS or k == "none" or
                   type(v) is not int or v <= 0 for k, v in masks.items())
            or sum(masks.values()) != item.get("candidate_conflicting_bars")):
            raise ValueError("Invalid top stock-day mask provenance")
        selection[symbol] = masks
    return selection


def mask_for_pair(h, p):
    """Use exactly the existing volume/amount/price thresholds after ×100."""
    price_diff = any(
        not diagnose.close_enough(p[i], h[i], "price")
        for i in range(4))
    volume_diff = not diagnose.close_enough(p[4], h[4], "volume")
    amount_diff = not diagnose.close_enough(p[5], h[5], "amount")
    return core.candidate_residual_mask(volume_diff, amount_diff, price_diff)


def summarized_pair_masks(h5_rows, parquet_starts, selected):
    """Conserve exact masks for top symbols and each exchange session."""
    normalized_h5 = {
        key: (*row[:4], row[4] * 100.0, row[5])
        for key, row in h5_rows.items() if key[0] in selected
    }
    parquet_end = {}
    for (symbol, stamp), row in parquet_starts.items():
        if symbol not in selected:
            continue
        key = (symbol, diagnose.shift_bar_stamp(stamp, 5))
        if key in parquet_end:
            raise ValueError("Parquet end-time collision for selected symbols")
        parquet_end[key] = row
    # Reuse the tested session conservation and price-boundary algorithms.
    analyzed = session.analyze(
        normalized_h5,
        {key: row for key, row in parquet_starts.items()
         if key[0] in selected},
        tuple(selected)
    )
    for symbol, expected in selected.items():
        h = {t: row for (sym, t), row in normalized_h5.items()
             if sym == symbol}
        p = {t: row for (sym, t), row in parquet_end.items()
             if sym == symbol}
        actual = Counter()
        grouped = defaultdict(Counter)
        for t in sorted(h.keys() & p.keys()):
            mask = mask_for_pair(h[t], p[t])
            actual[mask] += 1
            grouped[session.session_name(t)][mask] += 1
        residual = {key: actual[key] for key in MASKS
                    if key != "none" and actual[key]}
        if residual != expected:
            raise ValueError(
                "Focused live bars do not reproduce the baseline exact masks: " +
                symbol)
        detail = analyzed[symbol]
        if sum(actual.values()) != detail[
                "conservation_on_matched_keys_only"]["matched_bars"]:
            raise ValueError("Focused mask and session matched-key discrepancy")
        by_session = {}
        for name, summary in detail["sessions"].items():
            mask_counts = {k: grouped[name][k] for k in MASKS}
            if sum(mask_counts.values()) != summary["matched_bars"]:
                raise ValueError("Focused session mask conservation mismatch")
            by_session[name] = {
                **summary,
                "exact_residual_masks": mask_counts,
            }
        detail["sessions"] = by_session
        detail["exact_residual_masks"] = {k: actual[k] for k in MASKS}
        detail["candidate_volume_factor_h5"] = 100
        detail["matched_only"] = True
        detail["not_proof_of_boundary_reallocation"] = True
        # Field conservation uses the same matched bars only and excludes
        # any missing symbols/time keys without inventing price differences.
    return analyzed



def row_group_read_cost(metadata_files, symbols, day, allowed_groups=None):
    """Conservative metadata-only read plan matching load_parquet's skip order.

    Candidate source-row counts are an *upper bound* for decompression, not the
    number of selected K-lines or the estimated Arrow predicate result size.
    An ambiguous/missing symbol min-max never licenses skipping a row group.
    """
    _, _, lower_ms, upper_ms = core.parse_day_range(
        day.year, day.isoformat(), day.isoformat())
    aliases = set().union(*(diagnose.source_spellings(s) for s in symbols))
    totals = {
        "parquet_files": 0,
        "row_groups_total": 0,
        "row_groups_skipped_by_completed_index": 0,
        "row_groups_skipped_by_time_metadata": 0,
        "row_groups_skipped_by_symbol_min_max": 0,
        "row_groups_candidate_to_decode": 0,
        "candidate_source_rows_upper_bound": 0,
        "candidate_uncompressed_bytes_upper_bound": 0,
        "candidate_group_rows_max": 0,
        "file_metadata": [],
        "plan_only_metadata_opened": True,
        "ohlcv_column_values_read": False,
        "candidate_rows_are_selected_symbol_rows": False,
        "missing_or_unreliable_min_max_never_prunes_row_groups": True,
    }
    for path, metadata in metadata_files:
        path = Path(path)
        allowed = None
        if allowed_groups is not None:
            allowed = allowed_groups.get(str(path.resolve()))
            if allowed is None:
                raise ValueError("Completed locator has no entry for source file")
        group_total = int(metadata.num_row_groups)
        one = {"file": path.name, "row_groups_total": group_total,
               "candidate_groups": 0, "candidate_source_rows_upper_bound": 0,
               "skipped_by_index": 0, "skipped_by_time": 0,
               "skipped_by_symbol": 0}
        totals["parquet_files"] += 1
        totals["row_groups_total"] += group_total
        for idx in range(group_total):
            if allowed is not None and idx not in allowed:
                one["skipped_by_index"] += 1
                totals["row_groups_skipped_by_completed_index"] += 1
                continue
            rg = metadata.row_group(idx)
            if not core.row_group_overlaps_timestamp(rg, lower_ms, upper_ms):
                one["skipped_by_time"] += 1
                totals["row_groups_skipped_by_time_metadata"] += 1
                continue
            if not diagnose.might_contain_symbols(rg, aliases):
                one["skipped_by_symbol"] += 1
                totals["row_groups_skipped_by_symbol_min_max"] += 1
                continue
            rows = int(rg.num_rows)
            if rows < 0:
                raise ValueError("Invalid negative Parquet row-group rows")
            one["candidate_groups"] += 1
            one["candidate_source_rows_upper_bound"] += rows
            totals["row_groups_candidate_to_decode"] += 1
            totals["candidate_source_rows_upper_bound"] += rows
            totals["candidate_group_rows_max"] = max(
                totals["candidate_group_rows_max"], rows)
            totals["candidate_uncompressed_bytes_upper_bound"] += int(
                rg.total_byte_size)
        totals["file_metadata"].append(one)
    counted = sum(totals[key] for key in (
        "row_groups_skipped_by_completed_index",
        "row_groups_skipped_by_time_metadata",
        "row_groups_skipped_by_symbol_min_max",
        "row_groups_candidate_to_decode"))
    if counted != totals["row_groups_total"]:
        raise ValueError("Parquet row-group plan is not conserved")
    return totals


def plan_with_footers(root, symbols, day, allowed_groups=None):
    """Open only annual Parquet footers; never read ts/symbol or OHLCV values."""
    import pyarrow.parquet as pq
    paths = core.year_files(root, "5min", day.year)
    if not paths:
        raise ValueError("No Parquet 5min files for requested year")
    metadata_files = []
    for path in paths:
        pf = pq.ParquetFile(str(path))
        if not set(core.NEEDED).issubset(pf.schema_arrow.names):
            raise ValueError("Parquet missing expected columns: " + path.name)
        metadata_files.append((path, pf.metadata))
    return row_group_read_cost(metadata_files, symbols, day, allowed_groups)


def resolve_completed_locator(root, symbols, day, index_path):
    """Use the existing full source-fingerprint and completion gate; no bypass."""
    index, _ = core.resolve_module_artifact_paths(index_path, None)
    spec = importlib.util.spec_from_file_location(
        "union_planner_for_focused_completed_index",
        HERE / "plan-5min-readonly-union.py")
    planner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(planner)
    return planner.validated_parquet_locator(
        index, root, symbols, day, "a-share-candidate")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path, help="Local read-only H5 and purchased PQ root")
    ap.add_argument("--date", required=True, help="Single trading date YYYY-MM-DD")
    ap.add_argument("--baseline-report", type=Path, required=True,
                    help="Existing one-day exact mask JSON")
    ap.add_argument("--top-symbols", type=int, default=3)
    ap.add_argument("--plan-only", action="store_true",
                    help="Report Parquet footer-only candidate I/O; no H5/PQ bar values")
    ap.add_argument("--coverage-index", type=Path, default=None,
                    help="Optional COMPLETED, source-verified 2026 V3 coverage locator; "
                         "partial indexes fail closed")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
        out, scratch = core.resolve_module_artifact_paths(args.out, None)
        root, _, _ = core.resolve_safe_paths(args.root, out, scratch)
        if not out.is_relative_to((HERE.parent / "reports").resolve()) or out.suffix != ".json":
            raise ValueError("Output must be new JSON inside module reports/")
        if out.exists():
            raise ValueError("Refusing to overwrite prior report")
        baseline_path = args.baseline_report.resolve()
        if baseline_path.suffix.lower() != ".json" or baseline_path == out:
            raise ValueError("Baseline must be another existing JSON file")
        selected = load_baseline(
            json.loads(baseline_path.read_text(encoding="utf-8")),
            day, args.top_symbols)
        print("Focused candidate symbols:", ", ".join(selected), flush=True)
        allowed_groups = None
        index_info = {"used": False, "complete_source_matched_index": False}
        if args.coverage_index is not None:
            allowed_groups, index_info = resolve_completed_locator(
                root, tuple(selected), day, args.coverage_index)
            index_info["complete_source_matched_index"] = True
        if args.plan_only:
            metadata_plan = plan_with_footers(
                root, tuple(selected), day, allowed_groups)
            report = {
                "format": "AStockDataTools focused parquet metadata read plan v1",
                "date": day.isoformat(),
                "selected_symbols": list(selected),
                "selection": "from completed exact-mask baseline top stock-days",
                "baseline_report_name": baseline_path.name,
                "parquet_row_group_plan": metadata_plan,
                "coverage_index": index_info,
                "h5_market_files_read": False,
                "parquet_bar_values_read": False,
                "source_market_files_modified": False,
                "not_a_measured_runtime_speedup": True,
                "unit_mapping_certified": False,
                "safe_to_automatically_union": False,
            }
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("x", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
                f.write("\n")
            print("Saved footer-only 5min read cost plan:", out, flush=True)
            return
        h5, hmeta = diagnose.load_h5(root, tuple(selected), day)
        pq, pmeta = diagnose.load_parquet(
            root, tuple(selected), day, True, allowed_groups=allowed_groups)
        if any(hmeta[s].get("h5_duplicate_keys", 0) for s in selected):
            raise ValueError("H5 duplicate focused keys")
        if pmeta.get("duplicate_keys", 0) or pmeta.get("nonfinite_rows", 0):
            raise ValueError("Parquet duplicate or nonfinite focused keys")
        by_symbol = summarized_pair_masks(h5, pq, selected)
        report = {
            "format": "AStockDataTools x100 focused 5min residual session forensic v1",
            "date": day.isoformat(),
            "selected_symbols": list(selected),
            "selection": "highest residual stock-days in the completed exact-mask baseline",
            "baseline_report_name": baseline_path.name,
            "parquet_start_plus_five_minutes_candidate": True,
            "h5_five_minute_volume_factor_candidate": 100,
            "price_absolute_tolerance": 0.005,
            "volume_relative_tolerance": 0.00001,
            "amount_relative_tolerance": 0.001,
            "source_files_modified": False,
            "no_raw_ohlcv_exported": True,
            "unit_mapping_certified": False,
            "safe_to_automatically_union": False,
            "h5_selected_source": hmeta,
            "parquet_scan": pmeta,
            "coverage_index": index_info,
            "symbol_results": by_symbol,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print("Saved focused ×100 session residual evidence:", out, flush=True)
    except (ValueError, OSError, OverflowError, json.JSONDecodeError) as err:
        ap.error(str(err))


if __name__ == "__main__":
    main()
