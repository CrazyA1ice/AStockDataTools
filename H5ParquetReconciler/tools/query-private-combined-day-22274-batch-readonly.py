#!/usr/bin/env python3
"""Read bounded MULTI-STOCK private daily candidates after ONE full live gate.

Purchased Parquet wins existing stock/day keys. H5-only candidates are fetched
from immutable private stages ONLY after the exact real H5/PQ absence audit.
No source writes, no raw licensed bars in SAFE, no pointer reads/activation.
Experimental bounded H5 scanner must be explicitly requested.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORMAT = "AStockDataTools explicit SHA 22274 private day batch single-live-gate SAFE v1"
MAX_SYMBOLS = 10


def load(label, filename):
    spec = importlib.util.spec_from_file_location(label, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


Q = load("private_22274_batch_single_query",
         "query-private-combined-day-22274-readonly.py")
REG = Q.REG
PRE = Q.PRE
WHOLE = Q.WHOLE
PURCHASED = Q.PURCHASED


def checked_requests(symbols, first, last, per_source_budget,
                     per_result_budget, total_source_budget, total_result_budget):
    if (type(symbols) not in (list, tuple) or
            not 1 <= len(symbols) <= MAX_SYMBOLS):
        raise ValueError("Require 1..10 explicit daily symbols")
    if (type(per_source_budget) is not int or
            not 1 <= per_source_budget <= 100000000 or
            type(total_source_budget) is not int or
            not 1 <= total_source_budget <= 100000000 or
            type(per_result_budget) is not int or
            not 1 <= per_result_budget <= 100000 or
            type(total_result_budget) is not int or
            not 1 <= total_result_budget <= 100000):
        raise ValueError("Invalid bounded private batch source/result budgets")
    if any(type(s) is not str or s != s.upper() or s != s.strip()
           for s in symbols):
        raise ValueError("Require canonical uppercase stock symbols")
    prepared = [
        PURCHASED.request_dates(s, "day", first, last,
                                per_source_budget, per_result_budget)
        for s in symbols
    ]
    canonical = [r[0] for r in prepared]
    if len(set(canonical)) != len(canonical):
        raise ValueError("Duplicate exact stock symbol in batch")
    start, end = prepared[0][1:]
    if start.year != end.year or any(r[1:] != (start, end) for r in prepared):
        raise ValueError("Private batch must be a common single-year date window")
    return canonical, start, end


def query_batch(root, symbols, first, last, version_sha, live_safe, private_keys,
                ledger, source2016, source2026, mixed_plan, fresh_out, out,
                max_candidate_rows_per_symbol=30000000,
                max_total_candidate_rows=30000000,
                max_result_bars_per_symbol=100,
                max_total_result_bars=1000,
                max_overlay_source_rows=30000,
                fast_bounded_h5_scan=False):
    if type(fast_bounded_h5_scan) is not bool:
        raise ValueError("Bounded H5 optimization must be a boolean opt-in")
    canon, start, end = checked_requests(
        symbols, first, last, max_candidate_rows_per_symbol,
        max_result_bars_per_symbol, max_total_candidate_rows,
        max_total_result_bars)
    start_clock = time.perf_counter()
    root = Path(root).resolve()
    fresh_path = PRE.new_report(fresh_out)
    output_path = PRE.new_report(out)
    if fresh_path == output_path:
        raise ValueError("Require distinct NEW live-gate and query SAFE outputs")
    if REG.LOCK.is_symlink() or REG.LOCK.exists():
        raise ValueError("Private combined version registration in progress")
    version = REG.load_version(version_sha)
    if (version["ready_for_production_query"] is not False or
            version["whole_day_candidate_rows"] != PRE.WHOLE_ROWS or
            version["mixed_stockday_candidate_rows"] != PRE.MIXED_ROWS or
            version["candidate_total_new_stockday_rows"] != PRE.TOTAL_ROWS):
        raise ValueError("Version does not declare exact immutable private 22274 stockdays")
    whole_sha = version["whole_day_overlay_version_sha256"]
    mixed_safe = PRE.REPORTS / version["mixed_stage_safe_basename"]

    # Exactly ONE full live audit across all requested stocks, both mixed
    # years and four full-market gaps. It verifies all 22,274 source-key
    # claims, the H5 OHLCVA candidate stage, and purchased-stock precedence.
    source_timings = {}
    fresh = PRE.verify(
        root, whole_sha, mixed_safe, live_safe, private_keys,
        ledger, source2016, source2026, mixed_plan, fresh_path,
        timing_sink=source_timings, bounded_h5_scan=fast_bounded_h5_scan)
    original_path, _, original = REG.read_audit(
        PRE.REPORTS / version["original_preflight_safe_basename"])
    fresh_sha = PRE.sha(fresh_path)
    if (fresh != original
            or fresh_sha != version["fresh_recheck_safe_sha256"]
            or fresh["whole_day_overlay_version_sha256"] != whole_sha
            or fresh["mixed_stage_parquet_sha256"] != version["mixed_stage_parquet_sha256"]
            or fresh["mixed_stage_manifest_sha256"] != version["mixed_stage_manifest_sha256"]
            or fresh["mixed_stage_safe_sha256"] != version["mixed_stage_safe_sha256"]
            or fresh["original_source_stat_sha256"] != version["original_source_stat_sha256"]):
        raise ValueError("Registered private full live source proof has changed")
    gate_seconds = round(time.perf_counter() - start_clock, 6)
    source_before = PRE.KEYS.state_digest(root, (2016, 2026))
    if source_before != version["original_source_stat_sha256"]:
        raise ValueError("Live H5/Parquet source stat drift")

    whole, evidence, stages = WHOLE.verified_version(
        whole_sha, max_overlay_source_rows)
    if (whole.get("rows_in_overlay") != PRE.WHOLE_ROWS or
            {s["day"] for s in stages} != PRE.WHOLE_DATES):
        raise ValueError("Missing verified full-day private stages")
    originals, year_dates = PRE.KEYS.verified_existing_plan(
        ledger, source2016, source2026, mixed_plan)
    _, mixed_keys, stage_data, stage_manifest, mixed_sha, stage_rows, stage_safe = (
        PRE.verify_mixed_stage(mixed_safe, live_safe, private_keys, originals, year_dates))
    if (mixed_sha != version["mixed_stage_parquet_sha256"]
            or PRE.sha(stage_manifest) != version["mixed_stage_manifest_sha256"]
            or PRE.sha(stage_safe) != version["mixed_stage_safe_sha256"]
            or len(mixed_keys) != PRE.MIXED_ROWS):
        raise ValueError("Private mixed stage SHA/key identity differs")
    preparation_seconds = round(time.perf_counter() - start_clock - gate_seconds, 6)

    grouped = {}
    scanned = 0
    total = 0
    counters = {
        "purchased_parquet": 0,
        "private_h5_whole_date_candidate": 0,
        "private_h5_mixed_stockday_candidate": 0,
    }
    for symbol in canon:
        remaining = max_total_candidate_rows - scanned
        if remaining < 1:
            raise ValueError("Aggregate purchased Parquet rowgroup scan budget exhausted")
        baseline = PURCHASED.query_bars(
            root, symbol, "day", start.isoformat(), end.isoformat(),
            max_candidate_rows=min(remaining, max_candidate_rows_per_symbol),
            max_result_bars=max_result_bars_per_symbol,
            local_cache=False)
        meta = baseline["safe_summary"]
        scanned_rows = meta.get("source_rows_scanned")
        if (type(scanned_rows) is not int or scanned_rows < 0 or
                scanned_rows > remaining):
            raise ValueError("Unexpected purchased Parquet rowgroup scan budget result")
        scanned += scanned_rows
        whole_bars = []
        for stage in stages:
            if start <= date.fromisoformat(stage["day"]) <= end:
                whole_bars.extend(WHOLE._decode_selected_stage(stage, symbol))
        mixed_bars = Q.selected_mixed_rows(stage_rows, symbol, start, end)
        rows, counts = Q.merge_stock_day_rows(
            symbol, start, end, baseline["bars"], whole_bars, mixed_bars,
            max_result_bars_per_symbol)
        total += len(rows)
        if total > max_total_result_bars:
            raise ValueError("Aggregate returned daily stockday bar limit exceeded")
        grouped[symbol] = rows
        for key, count in counts.items():
            counters[key] += count
    query_seconds = round(time.perf_counter() - start_clock -
                          gate_seconds - preparation_seconds, 6)

    # Final live snapshot checks before any caller gets an in-memory result;
    # do not trust merely matching total counts, mtimes or file names.
    if (PRE.KEYS.state_digest(root, (2016, 2026)) != source_before or
            PRE.sha(stage_data) != mixed_sha or
            PRE.sha(stage_manifest) != version["mixed_stage_manifest_sha256"] or
            PRE.sha(stage_safe) != version["mixed_stage_safe_sha256"] or
            PRE.sha(original_path) != version["original_preflight_safe_sha256"] or
            PRE.sha(fresh_path) != fresh_sha or
            REG.load_version(version_sha) != version or
            REG.LOCK.is_symlink() or REG.LOCK.exists()):
        raise ValueError("Live private source or signed proof changed during batch")
    second, second_evidence, stages2 = WHOLE.verified_version(
        whole_sha, max_overlay_source_rows)
    if (second != whole or second_evidence != evidence or stages2 != stages):
        raise ValueError("Whole-day source version changed during batch query")

    safe = {
        "format": FORMAT,
        "state": "explicit_private_combined_day_batch_one_live_gate_passed",
        "private_combined_version_sha256": version_sha,
        "whole_day_overlay_version_sha256": whole_sha,
        "mixed_stage_parquet_sha256": mixed_sha,
        "full_live_recheck_safe_sha256": fresh_sha,
        "full_live_market_keyset_audit_count": 1,
        "bounded_h5_scan_explicit_opt_in": fast_bounded_h5_scan,
        "same_year_bounded_query": True,
        "requested_stock_count": len(canon),
        "query_result_stockday_bars": total,
        "purchased_parquet_bars": counters["purchased_parquet"],
        "whole_h5_only_candidate_bars": counters["private_h5_whole_date_candidate"],
        "mixed_h5_only_candidate_bars": counters["private_h5_mixed_stockday_candidate"],
        "purchased_parquet_rowgroup_rows_scanned_across_stocks": scanned,
        "candidate_total_new_stockday_rows_in_immutable_version": PRE.TOTAL_ROWS,
        "quarantined_2026_07_16_stockday_bars_not_included": 5,
        "source_priority": "purchased_parquet_first_exact_stockday_fail_closed_on_overlap",
        "no_raw_ohlcva_or_symbols_in_safe": True,
        "source_market_files_written": False,
        "purchased_parquet_replaced": False,
        "private_or_production_active_pointer_modified": False,
        "h5_mirror_created": False,
        "candidate_source_units_certified": False,
        "ready_for_production_query": False,
        "ready_for_automatic_market_merge": False,
        "full_live_market_gate_elapsed_seconds": gate_seconds,
        "immutable_stage_reverification_elapsed_seconds": preparation_seconds,
        "stock_queries_and_merges_elapsed_seconds": query_seconds,
        "full_live_gate_phase_elapsed_seconds": source_timings,
        "total_elapsed_seconds_this_invocation": round(time.perf_counter() - start_clock, 6),
    }
    with output_path.open("x", encoding="utf-8") as f:
        json.dump(safe, f, sort_keys=True, ensure_ascii=False, indent=2)
        f.write("\n")
    return {"bars_by_symbol": grouped, "safe_summary": safe}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--symbols", nargs="+", required=True)
    p.add_argument("--from-date", required=True)
    p.add_argument("--to-date", required=True)
    p.add_argument("--version-sha256", required=True)
    p.add_argument("--live-safe", type=Path, required=True)
    p.add_argument("--private-keys", type=Path, required=True)
    p.add_argument("--history-ledger", type=Path, required=True)
    p.add_argument("--source-2016", type=Path, required=True)
    p.add_argument("--source-2026", type=Path, required=True)
    p.add_argument("--mixed-plan", type=Path, required=True)
    p.add_argument("--fresh-recheck-out", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-candidate-rows-per-symbol", type=int, default=30000000)
    p.add_argument("--max-total-candidate-rows", type=int, default=30000000)
    p.add_argument("--max-result-bars-per-symbol", type=int, default=100)
    p.add_argument("--max-total-result-bars", type=int, default=1000)
    p.add_argument("--max-overlay-source-rows", type=int, default=30000)
    p.add_argument("--fast-bounded-h5-scan", action="store_true")
    p.add_argument("--read-only", action="store_true", required=True)
    a = p.parse_args(argv)
    try:
        result = query_batch(
            a.source_root, a.symbols, a.from_date, a.to_date,
            a.version_sha256, a.live_safe, a.private_keys, a.history_ledger,
            a.source_2016, a.source_2026, a.mixed_plan, a.fresh_recheck_out,
            a.out, a.max_candidate_rows_per_symbol,
            a.max_total_candidate_rows, a.max_result_bars_per_symbol,
            a.max_total_result_bars, a.max_overlay_source_rows,
            a.fast_bounded_h5_scan)
        summary = result["safe_summary"]
        print("One full market live gate; requested stocks:", summary["requested_stock_count"])
        print("Daily bars:", summary["query_result_stockday_bars"])
        print("Purchased:", summary["purchased_parquet_bars"],
              "whole-date:", summary["whole_h5_only_candidate_bars"],
              "mixed-date:", summary["mixed_h5_only_candidate_bars"])
        print("Aggregate-only SAFE:", a.out)
        print("No raw OHLCVA, security identifiers, production writes or pointer switches")
    except (OSError, ValueError, TypeError, KeyError, ImportError, OverflowError):
        p.error("Private combined multi-stock read-only query failed closed")


if __name__ == "__main__":
    main()
