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
        or data.get("requested_periods") != ["5min"]
        or data.get("requested_years") != [day.year]
        or data.get("universe_mode") != "a-share-candidate"
        or data.get("eligible_for_automatic_union") is not False):
        raise ValueError("Require a matching completed single-day 5min candidate report")
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path, help="Local read-only H5 and purchased PQ root")
    ap.add_argument("--date", required=True, help="Single trading date YYYY-MM-DD")
    ap.add_argument("--baseline-report", type=Path, required=True,
                    help="Existing one-day exact mask JSON")
    ap.add_argument("--top-symbols", type=int, default=3)
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
        h5, hmeta = diagnose.load_h5(root, tuple(selected), day)
        pq, pmeta = diagnose.load_parquet(root, tuple(selected), day, True)
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
