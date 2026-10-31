#!/usr/bin/env python3
"""Audit *all 83* mixed-date private stockday reads in ONE live-source pass.

Uses the already-verified purchased-key absence gate, not a repeated full
purchased rowgroup scan for every candidate. Every OHLCVA value stays in memory.
No automatic activation, market writes or licensed-content SAFE output.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORMAT = "AStockDataTools all83 private mixed stockday read-once audit SAFE v1"


def load(label, file):
    spec = importlib.util.spec_from_file_location(label, HERE / file)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


Q = load("mixed83_onepass_explicit_day_query",
         "query-private-combined-day-22274-readonly.py")
REG = Q.REG
PRE = Q.PRE


def key_date(stamp):
    if type(stamp) is not int or stamp < 201601010000:
        raise ValueError("Invalid private native H5 day-key timestamp")
    raw = str(stamp)
    if len(raw) != 12 or not raw.endswith("0000"):
        raise ValueError("Noncanonical H5 stock-day date key")
    d = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    if int(d.strftime("%Y%m%d")) * 10000 != stamp:
        raise ValueError("Invalid encoded native daily date")
    return d


def audit_mixed_rows(selected, stage_rows):
    """Read 83 real staged OHLCVA locally; return only aggregate counts."""
    if (type(selected) is not set or len(selected) != PRE.MIXED_ROWS
            or type(stage_rows) is not list or len(stage_rows) != PRE.MIXED_ROWS):
        raise ValueError("Require exact SHA-bound 83-key source and 83-row stage")
    counts = Counter()
    seen = set()
    for symbol, stamp in sorted(selected):
        d = key_date(stamp)
        if (d.isoformat() in PRE.WHOLE_DATES or d.isoformat() == "2026-07-16"
                or d.year not in (2016, 2026)):
            raise ValueError("Full-day overlap, forbidden year, or quarantined stock-day")
        if (type(symbol) is not str
                or not PRE.MIXED.CORE.is_a_share_candidate(symbol, d.year)
                or (symbol, d.isoformat()) in seen):
            raise ValueError("Invalid or duplicate mixed candidate key")
        seen.add((symbol, d.isoformat()))
        picked = Q.selected_mixed_rows(stage_rows, symbol, d, d)
        # All purchased stockday absences have just been verified live by
        # PRE.verify; do NOT claim purchased.source OHLCVA rows were queried.
        if len(picked) != 1:
            raise ValueError("Mixed private query failed to return exact selected key")
        result, sources = Q.merge_stock_day_rows(
            symbol, d, d, [], [], picked, 1)
        if (len(result) != 1 or sources["purchased_parquet"] != 0
                or sources["private_h5_whole_date_candidate"] != 0
                or sources["private_h5_mixed_stockday_candidate"] != 1
                or result[0]["value_source"] !=
                   "private_h5_mixed_stockday_candidate"):
            raise ValueError("Mixed stockday source selection was not isolated")
        counts[d.year] += 1
    if (sum(counts.values()) != PRE.MIXED_ROWS or counts != {2016: 1, 2026: 82}):
        raise ValueError("Mixed stockday year distribution unexpectedly changed")
    return {"2016": counts[2016], "2026": counts[2026]}


def verify(root, version_sha, live_safe, private_keys, ledger, source2016,
           source2026, mixed_plan, fresh_out, out):
    root = Path(root).resolve()
    fresh_path = PRE.new_report(fresh_out)
    output = PRE.new_report(out)
    if fresh_path == output:
        raise ValueError("Live audit and aggregate output paths must differ")
    if REG.LOCK.is_symlink() or REG.LOCK.exists():
        raise ValueError("Concurrent private logical version registration")
    entry = REG.load_version(version_sha)
    if entry.get("ready_for_production_query") is not False:
        raise ValueError("Research read refuses any production route claims")
    source_before = PRE.KEYS.state_digest(root, (2016, 2026))
    if source_before != entry["original_source_stat_sha256"]:
        raise ValueError("Market source files changed since registered version")
    whole_sha = entry["whole_day_overlay_version_sha256"]
    mixed_safe = PRE.REPORTS / entry["mixed_stage_safe_basename"]
    # SINGLE expensive full-market exact-key audit: covers both years, 4
    # complete days, all 83 mixed keys, and private OHLCVA candidate fidelity.
    fresh = PRE.verify(root, whole_sha, mixed_safe, live_safe, private_keys,
                       ledger, source2016, source2026, mixed_plan, fresh_path)
    original_path, _, original = REG.read_audit(
        PRE.REPORTS / entry["original_preflight_safe_basename"])
    if (fresh != original
            or PRE.sha(fresh_path) != entry["fresh_recheck_safe_sha256"]
            or fresh["mixed_stage_parquet_sha256"] != entry["mixed_stage_parquet_sha256"]
            or fresh["mixed_stage_manifest_sha256"] != entry["mixed_stage_manifest_sha256"]
            or fresh["mixed_stage_safe_sha256"] != entry["mixed_stage_safe_sha256"]):
        raise ValueError("Registered full-market source proof is stale")
    originals, dates = PRE.KEYS.verified_existing_plan(
        ledger, source2016, source2026, mixed_plan)
    _, selected, data, manifest, stage_sha, rows, stage_safe = PRE.verify_mixed_stage(
        mixed_safe, live_safe, private_keys, originals, dates)
    if (stage_sha != entry["mixed_stage_parquet_sha256"]
            or PRE.sha(manifest) != entry["mixed_stage_manifest_sha256"]
            or PRE.sha(stage_safe) != entry["mixed_stage_safe_sha256"]):
        raise ValueError("Private mixed stage does not match registered SHA")
    counts = audit_mixed_rows(selected, rows)
    if (PRE.KEYS.state_digest(root, (2016, 2026)) != source_before
            or PRE.sha(data) != stage_sha
            or PRE.sha(manifest) != entry["mixed_stage_manifest_sha256"]
            or PRE.sha(stage_safe) != entry["mixed_stage_safe_sha256"]
            or PRE.sha(original_path) != entry["original_preflight_safe_sha256"]
            or PRE.sha(fresh_path) != entry["fresh_recheck_safe_sha256"]
            or REG.load_version(version_sha) != entry
            or REG.LOCK.is_symlink() or REG.LOCK.exists()):
        raise ValueError("Private mixed stockday source changed during full-key audit")
    result = {
        "format": FORMAT,
        "state": "all83_mixed_stockday_queries_verified_one_live_source_pass",
        "private_combined_version_sha256": version_sha,
        "whole_day_overlay_version_sha256": whole_sha,
        "mixed_stage_parquet_sha256": stage_sha,
        "mixed_stage_manifest_sha256": entry["mixed_stage_manifest_sha256"],
        "live_recheck_safe_sha256": PRE.sha(fresh_path),
        "live_full_source_audit_invocations": 1,
        "mixed_candidate_keys_verified": PRE.MIXED_ROWS,
        "mixed_candidate_rows_returned_in_memory": sum(counts.values()),
        "mixed_candidate_year_counts": counts,
        "purchased_exact_stockday_absence_checked_live": True,
        "purchased_ohlcva_requeried_for_each_candidate": False,
        "whole_day_candidate_rows_in_version": PRE.WHOLE_ROWS,
        "candidate_total_new_stockday_rows_in_version": PRE.TOTAL_ROWS,
        "quarantined_2026_07_16_stockday_bars_not_included": 5,
        "private_or_production_active_pointer_modified": False,
        "source_market_files_written": False,
        "purchased_parquet_replaced": False,
        "h5_mirror_created": False,
        "candidate_source_units_certified": False,
        "ready_for_production_query": False,
        "ready_for_automatic_market_merge": False,
        "no_stock_symbols_or_ohlcva_in_safe": True,
    }
    with output.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--version-sha256", required=True)
    p.add_argument("--live-safe", type=Path, required=True)
    p.add_argument("--private-keys", type=Path, required=True)
    p.add_argument("--history-ledger", type=Path, required=True)
    p.add_argument("--source-2016", type=Path, required=True)
    p.add_argument("--source-2026", type=Path, required=True)
    p.add_argument("--mixed-plan", type=Path, required=True)
    p.add_argument("--fresh-recheck-out", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--read-only", action="store_true", required=True)
    a = p.parse_args(argv)
    try:
        report = verify(a.source_root, a.version_sha256, a.live_safe,
                        a.private_keys, a.history_ledger, a.source_2016,
                        a.source_2026, a.mixed_plan, a.fresh_recheck_out, a.out)
        print("Mixed exact stock-day candidate reads:",
              report["mixed_candidate_rows_returned_in_memory"])
        print("Live full-market keyset audits:",
              report["live_full_source_audit_invocations"])
        print("Aggregate SAFE:", a.out)
        print("No licensed OHLCVA or private keys exported")
    except (ValueError, OSError, TypeError, KeyError, ImportError, OverflowError):
        p.error("Mixed 83 real stockday candidate query audit failed closed")


if __name__ == "__main__":
    main()
