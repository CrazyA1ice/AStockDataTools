#!/usr/bin/env python3
"""Read explicitly registered private day union, with purchased Parquet priority.

Research-only local memory result. Requires a named immutable 22,274 candidate
version, then reruns the full original-source H5/Parquet evidence gate before
returning requested rows. No active pointer, data writes, or H5 mirror.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import time
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIELDS = ("open", "high", "low", "close", "volume", "amount")
FORMAT = "AStockDataTools explicit private combined 22274 daily research query SAFE v1"


def load(label, filename):
    spec = importlib.util.spec_from_file_location(label, HERE / filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


REG = load("private_22274_query_version_registry",
           "register-private-combined-day-22274-version.py")
PRE = REG.PRE
WHOLE = PRE.WHOLE
MIXED = PRE.MIXED
PURCHASED = WHOLE.purchased


def validated_source_row(row, symbol, first, last, source):
    if (type(row) is not dict or row.get("symbol") != symbol
            or row.get("period") != "day"
            or type(row.get("trading_date")) is not str):
        raise ValueError("Noncanonical source day record")
    d = date.fromisoformat(row["trading_date"])
    if d.isoformat() != row["trading_date"] or not first <= d <= last:
        raise ValueError("Source trading date escaped selected query window")
    if type(row.get("source_timestamp_ms")) is not int:
        raise ValueError("Day row timestamp must be integer milliseconds")
    # Time of day may differ in purchased Parquet; source contract is by date.
    actual_day = datetime.fromtimestamp(
        row["source_timestamp_ms"] / 1000, tz=MIXED.CORE.UTC8).date()
    if d != actual_day:
        raise ValueError("Day row timestamp/date mismatch")
    values = [row.get(k) for k in FIELDS]
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
            or min(values[:4]) <= 0 or values[1] + 1e-8 <
                max(values[0], values[2], values[3])
            or values[2] - 1e-8 > min(values[0], values[1], values[3])
            or values[4] < 0 or values[5] < 0):
        raise ValueError("Untrusted source OHLCVA geometry")
    return {**row, "value_source": source}


def merge_stock_day_rows(symbol, first, last, purchased, whole, mixed, limit):
    """Never silently shadow a source key; all sources were separately audited."""
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError("Invalid combined daily result-row budget")
    if type(symbol) is not str or symbol != symbol.upper():
        raise ValueError("Query symbol must be canonical")
    if type(first) is not date or type(last) is not date or first > last:
        raise ValueError("Invalid daily query window")
    if any(type(group) is not list for group in (purchased, whole, mixed)):
        raise ValueError("Day result sources must be explicit lists")
    by_day = {}
    counts = {"purchased_parquet": 0, "private_h5_whole_date_candidate": 0,
              "private_h5_mixed_stockday_candidate": 0}
    for source, group in (
        ("purchased_parquet", purchased),
        ("private_h5_whole_date_candidate", whole),
        ("private_h5_mixed_stockday_candidate", mixed),
    ):
        for bar in group:
            clean = validated_source_row(bar, symbol, first, last, source)
            day = clean["trading_date"]
            if day in by_day:
                raise ValueError("Purchased/private or private/private stockday overlap: fail closed")
            by_day[day] = clean
            counts[source] += 1
            if len(by_day) > limit:
                raise ValueError("Combined result exceeds --max-result-bars")
    ordered = [by_day[d] for d in sorted(by_day)]
    return ordered, counts


def selected_mixed_rows(rows, symbol, first, last):
    """Stage is already SHA/H5-verified by live PRE.verify; decode schema again."""
    result = []
    all_keys = set()
    for item in rows:
        if type(item) is not dict or set(item) != set(MIXED.STAGE.SCHEMA_FIELDS):
            raise ValueError("Mixed private daily stage schema changed")
        canonical = MIXED.CORE.symbol_id(item["symbol"])
        if canonical is None:
            raise ValueError("Unknown mixed stage stock symbol")
        try:
            stamp = int(item["ts"])
            dt = datetime.fromtimestamp(stamp / 1000, tz=MIXED.CORE.UTC8)
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Invalid mixed source timestamp") from None
        d = dt.date()
        if dt.time().hour != 0 or dt.time().minute != 0:
            raise ValueError("Mixed stage not a local midnight daily candidate")
        if (item["source"] != "hikyuu_h5_mixed_day_candidate"
                or not MIXED.CORE.is_a_share_candidate(canonical, d.year)
                or (canonical, d.isoformat()) in all_keys):
            raise ValueError("Bad/duplicate mixed source stockday")
        all_keys.add((canonical, d.isoformat()))
        if canonical != symbol or not first <= d <= last:
            continue
        result.append({
            "symbol": canonical, "period": "day",
            "trading_date": d.isoformat(),
            "source_timestamp_ms": stamp,
            "source_beijing_time": dt.strftime("%Y-%m-%d %H:%M"),
            "normalized_query_label": d.isoformat(),
            **{field: float(item[field]) for field in FIELDS},
        })
    if len(all_keys) != PRE.MIXED_ROWS:
        raise ValueError("Mixed stage does not contain exactly 83 stockday keys")
    return result


def query(root, symbol, first, last, version_sha, live_safe, private_keys,
          ledger, source2016, source2026, mixed_plan, fresh_recheck_out,
          out, max_candidate_rows=30000000, max_result_bars=100,
          max_overlay_source_rows=30000):
    started = time.perf_counter()
    canonical, first_d, last_d = PURCHASED.request_dates(
        symbol, "day", first, last, max_candidate_rows, max_result_bars)
    if first_d.year != last_d.year:
        raise ValueError("Private combined pilot supports one year per query")
    root = Path(root).resolve()
    fresh_path = PRE.new_report(fresh_recheck_out)
    report_path = PRE.new_report(out)
    if fresh_path == report_path:
        raise ValueError("Live recheck SAFE and query SAFE must differ")
    if REG.LOCK.is_symlink() or REG.LOCK.exists():
        raise ValueError("Private immutable version registration in progress")
    entry = REG.load_version(version_sha)
    if (entry["whole_day_candidate_rows"] != PRE.WHOLE_ROWS
            or entry["mixed_stockday_candidate_rows"] != PRE.MIXED_ROWS
            or entry["candidate_total_new_stockday_rows"] != PRE.TOTAL_ROWS
            or entry["ready_for_production_query"] is not False):
        raise ValueError("Untrusted private version counts or activation claim")
    whole_sha = entry["whole_day_overlay_version_sha256"]
    mixed_safe = PRE.REPORTS / entry["mixed_stage_safe_basename"]
    # Do not rely on historical stale certificates: fresh H5/PQ exact-key
    # checks are mandatory for every research query, even baseline-only.
    fresh = PRE.verify(root, whole_sha, mixed_safe, live_safe, private_keys,
                       ledger, source2016, source2026, mixed_plan, fresh_path)
    original_path, _, original = REG.read_audit(
        PRE.REPORTS / entry["original_preflight_safe_basename"])
    if (fresh != original or fresh["whole_day_overlay_version_sha256"] != whole_sha
            or fresh["mixed_stage_parquet_sha256"] != entry["mixed_stage_parquet_sha256"]
            or fresh["mixed_stage_manifest_sha256"] != entry["mixed_stage_manifest_sha256"]
            or fresh["mixed_stage_safe_sha256"] != entry["mixed_stage_safe_sha256"]
            or fresh["original_source_stat_sha256"] != entry["original_source_stat_sha256"]):
        raise ValueError("Private registered source changed after original H5/PQ audit")
    start_state = PRE.KEYS.state_digest(root, (2016, 2026))
    if start_state != entry["original_source_stat_sha256"]:
        raise ValueError("Original H5/Parquet state drift after live source recheck")
    version, evidence, whole_stages = WHOLE.verified_version(
        whole_sha, max_overlay_source_rows)
    if (version.get("rows_in_overlay") != PRE.WHOLE_ROWS
            or {item["day"] for item in whole_stages} != PRE.WHOLE_DATES):
        raise ValueError("Whole-date stage changed after combined live preflight")
    originals, years = PRE.KEYS.verified_existing_plan(
        ledger, source2016, source2026, mixed_plan)
    doc, selected, stage_data, stage_meta, fingerprint, mixed_rows, stage_safe = (
        PRE.verify_mixed_stage(mixed_safe, live_safe, private_keys, originals, years))
    if (fingerprint != entry["mixed_stage_parquet_sha256"]
            or PRE.sha(stage_meta) != entry["mixed_stage_manifest_sha256"]
            or PRE.sha(stage_safe) != entry["mixed_stage_safe_sha256"]):
        raise ValueError("Mixed private stage content changed since registration")
    purchased_result = PURCHASED.query_bars(
        root, canonical, "day", first_d.isoformat(), last_d.isoformat(),
        max_candidate_rows=max_candidate_rows, max_result_bars=max_result_bars,
        local_cache=False)
    purchased_rows = purchased_result["bars"]
    whole_rows = []
    for item in whole_stages:
        d = date.fromisoformat(item["day"])
        if first_d <= d <= last_d:
            whole_rows.extend(WHOLE._decode_selected_stage(item, canonical))
    mixed_selected = selected_mixed_rows(mixed_rows, canonical, first_d, last_d)
    combined, counts = merge_stock_day_rows(
        canonical, first_d, last_d, purchased_rows, whole_rows,
        mixed_selected, max_result_bars)
    # Check the complete private versions and exact origin state at the end
    # to prevent a stale candidate from being returned after a mid-query edit.
    if (PRE.KEYS.state_digest(root, (2016, 2026)) != start_state
            or PRE.sha(stage_data) != fingerprint
            or PRE.sha(stage_meta) != entry["mixed_stage_manifest_sha256"]
            or PRE.sha(stage_safe) != entry["mixed_stage_safe_sha256"]
            or REG.load_version(version_sha) != entry
            or original_path.read_bytes() == b""  # keep explicit trusted provenance in read
            or REG.LOCK.exists() or REG.LOCK.is_symlink()):
        raise ValueError("Private combined query evidence or source changed during read")
    again, _, stages_again = WHOLE.verified_version(
        whole_sha, max_overlay_source_rows)
    if again != version or stages_again != whole_stages:
        raise ValueError("Whole-day stage SHA/key changed during read")
    summary = {
        "format": FORMAT,
        "period": "day",
        "state": "explicit_private_combined_day_read_only_research_query",
        "private_combined_version_sha256": version_sha,
        "whole_day_overlay_version_sha256": whole_sha,
        "mixed_stage_parquet_sha256": fingerprint,
        "live_recheck_safe_sha256": PRE.sha(fresh_path),
        "whole_day_candidate_rows_in_registered_version": PRE.WHOLE_ROWS,
        "mixed_stockday_candidate_rows_in_registered_version": PRE.MIXED_ROWS,
        "total_candidate_rows_in_registered_version": PRE.TOTAL_ROWS,
        "matched_purchased_stockday_bars": counts["purchased_parquet"],
        "matched_private_whole_day_stockday_bars":
            counts["private_h5_whole_date_candidate"],
        "matched_private_mixed_day_stockday_bars":
            counts["private_h5_mixed_stockday_candidate"],
        "matching_stockday_bars": len(combined),
        "source_priority": "purchased_parquet_first_exact_symbol_day_fail_closed_on_stale_overlap",
        "one_symbol_selected_no_symbol_in_safe": True,
        "no_raw_ohlcva_in_safe": True,
        "candidate_source_units_certified": False,
        "source_market_files_written": False,
        "purchased_parquet_replaced": False,
        "private_or_production_active_pointer_modified": False,
        "h5_mirror_created": False,
        "ready_for_production_query": False,
        "ready_for_automatic_market_merge": False,
        "elapsed_seconds_this_invocation": round(time.perf_counter() - started, 6),
    }
    with report_path.open("x", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    return {"bars": combined, "safe_summary": summary}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--symbol", required=True)
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
    p.add_argument("--max-candidate-rows", type=int, default=30000000)
    p.add_argument("--max-result-bars", type=int, default=100)
    p.add_argument("--max-overlay-source-rows", type=int, default=30000)
    p.add_argument("--read-only", action="store_true", required=True)
    a = p.parse_args(argv)
    try:
        result = query(
            a.source_root, a.symbol, a.from_date, a.to_date,
            a.version_sha256, a.live_safe, a.private_keys,
            a.history_ledger, a.source_2016, a.source_2026, a.mixed_plan,
            a.fresh_recheck_out, a.out, a.max_candidate_rows,
            a.max_result_bars, a.max_overlay_source_rows)
        print("Research-only day bars:", result["safe_summary"]["matching_stockday_bars"])
        print("Purchased:", result["safe_summary"]["matched_purchased_stockday_bars"])
        print("Whole-day private:", result["safe_summary"]["matched_private_whole_day_stockday_bars"])
        print("Mixed-day private:", result["safe_summary"]["matched_private_mixed_day_stockday_bars"])
        print("Aggregate SAFE:", a.out)
        print("No raw licensed values, stock symbols or production writes printed")
    except (OSError, ValueError, TypeError, KeyError, ImportError, OverflowError):
        p.error("Explicit private combined day read-only query failed closed")


if __name__ == "__main__":
    main()
