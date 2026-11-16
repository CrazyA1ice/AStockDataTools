#!/usr/bin/env python3
"""Bounded sequential QMT financial market scan, resumable from progress.json.

Each one-stock batch uses the existing QMT worker watchdog, failure queue,
exclusive writer lock and durable per-stock cursor. No parallel QMT downloads.
Explicit --apply required. Purchased eight-cycle/H5 and the 21:30 task untouched.
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, time, timedelta
from pathlib import Path

import qmt_extra_data as E

BLACKOUT_START = time(21, 0)
BLACKOUT_END = time(23, 0)
MAX_TABLES_PER_STOCK = len(E.FIN_TABLES)


def _local_now(clock):
    now = clock()
    if now.tzinfo is None:
        raise ValueError("QMT bounded-run clock must be timezone-aware")
    return now.astimezone(E.L.UTC8)


def _blackout_reason(now, timeout_seconds):
    """Never start a symbol that might overlap 21:00 in worst worker case."""
    local = now.timetz().replace(tzinfo=None)
    if BLACKOUT_START <= local < BLACKOUT_END:
        return "PROTECTED_2130_WINDOW"
    if local < BLACKOUT_START:
        start = datetime.combine(now.date(), BLACKOUT_START,
                                 tzinfo=E.L.UTC8)
        # Guard beyond nine worker timeouts for startup, QMT discovery,
        # JSON serialization and Parquet commits; no global hard bound.
        safety_seconds = MAX_TABLES_PER_STOCK * timeout_seconds + 120
        if (start - now).total_seconds() <= safety_seconds:
            return "INSUFFICIENT_PRE_2130_WORST_CASE_WINDOW"
    return None


def scan(root, *, xt, apply=False, max_symbols=30, max_minutes=360,
         timeout_seconds=180, workspace=E.WORK, clock=None,
         progress=print):
    """Do not wrap after the end of the stock universe; pending is distinct."""
    if not isinstance(max_symbols, int) or not 1 <= max_symbols <= 10000:
        raise ValueError("max_symbols must be 1..10000")
    if not isinstance(max_minutes, int) or not 1 <= max_minutes <= 1440:
        raise ValueError("max_minutes must be 1..1440")
    if not isinstance(timeout_seconds, int) or not 30 <= timeout_seconds <= 3600:
        raise ValueError("timeout_seconds must be 30..3600")
    if clock is None:
        clock = lambda: datetime.now(E.L.UTC8)
    started = _local_now(clock)
    extra = E._storage(Path(root))
    initial = E._state(extra, workspace)
    first_cursor = initial.get("cursor", {}).get("financial", "")
    if not isinstance(first_cursor, str):
        raise ValueError("Invalid financial cursor")
    result = {
        "mode": "APPLY" if apply else "PREVIEW",
        "first_cursor": first_cursor, "last_cursor": first_cursor,
        "symbols_processed": 0, "symbols_deferred": 0,
        "pending_retry_count": len(E._pending_financial(initial)),
        "max_symbols": max_symbols, "max_minutes": max_minutes,
        "source_completeness_verified": False,
        "purchased_8_cycle_modified": False,
        "h5_modified": False, "windows_schedule_modified": False}
    if not apply:
        catalog = E._tickers(xt, ("沪深A股",), required=True)
        result["universe_symbols"] = len(catalog)
        result["universe_sha256"] = hashlib.sha256(
            E.canonical_json(catalog).encode("utf-8")).hexdigest()
        preview = E.run(
            root, xt=xt, apply=False, section="financial",
            stock_limit=max_symbols, workspace=workspace,
            financial_timeout_seconds=timeout_seconds,
            financial_continue_on_error=True,
            financial_universe=catalog, progress=lambda _: None)
        result["next"] = preview["next"]["financial"]
        result["status"] = "BOUNDED_FINANCIAL_READONLY_PREVIEW"
        progress("QMT_FINANCIAL_BULK_SUMMARY=" + E.canonical_json(result))
        return result

    deadline = started + timedelta(minutes=max_minutes)
    catalog = None
    for _ in range(max_symbols):
        now = _local_now(clock)
        if now >= deadline:
            result["status"] = "PAUSED_TIME_BUDGET"
            break
        guard = _blackout_reason(now, timeout_seconds)
        if guard:
            result["status"] = "PAUSED_" + guard
            break
        if catalog is None:
            # A single source-defined A-share universe snapshot is used for
            # the entire bounded session; rediscover on the next invocation.
            catalog = E._tickers(xt, ("沪深A股",), required=True)
            result["universe_symbols"] = len(catalog)
            result["universe_sha256"] = hashlib.sha256(
                E.canonical_json(catalog).encode("utf-8")).hexdigest()
            progress("QMT_FINANCIAL_BULK_UNIVERSE=" + E.canonical_json({
                "symbols": len(catalog), "sha256": result["universe_sha256"]}))
            now = _local_now(clock)
            if now >= deadline:
                result["status"] = "PAUSED_TIME_BUDGET"
                break
            guard = _blackout_reason(now, timeout_seconds)
            if guard:
                result["status"] = "PAUSED_" + guard
                break
        before = E._state(extra, workspace).get("cursor", {}).get("financial", "")
        # One stock per call gives the tightest safe checkpoint and avoids
        # an unbounded 5,224-stock call crossing the existing 21:30 task.
        report = E.run(
            root, xt=xt, apply=True, section="financial",
            stock_limit=1, since=E.SINCE,
            today=now.date(), workspace=workspace,
            financial_timeout_seconds=timeout_seconds,
            financial_continue_on_error=True,
            financial_universe=catalog, progress=progress)
        section = report["sections"]["financial"]
        cursor = section["cursor"]
        completed = section["symbols_processed"]
        deferred = section["symbols_deferred"]
        if completed + deferred not in (0, 1):
            raise ValueError("A bounded single-symbol batch processed unexpected count")
        if completed + deferred == 1 and not cursor > before:
            raise ValueError("Financial high-water cursor did not advance")
        if completed + deferred == 0 and section["next_batch_required"]:
            raise ValueError("QMT scan produced no securities while more remain")
        result["symbols_processed"] += completed
        result["symbols_deferred"] += deferred
        result["last_cursor"] = cursor
        result["pending_retry_count"] = section["pending_retry_count"]
        progress("QMT_FINANCIAL_BULK_CHECKPOINT=" + E.canonical_json({
            "cursor": cursor,
            "processed_total": result["symbols_processed"],
            "deferred_total": result["symbols_deferred"],
            "pending": result["pending_retry_count"],
            "scan_has_more": section["next_batch_required"]}))
        if not section["next_batch_required"]:
            result["status"] = ("SCAN_EXHAUSTED_PENDING_RETRIES"
                                if result["pending_retry_count"] else
                                "SCAN_EXHAUSTED_COVERAGE_UNVERIFIED")
            break
    else:
        result["status"] = "PAUSED_SYMBOL_LIMIT"
    progress("QMT_FINANCIAL_BULK_SUMMARY=" + E.canonical_json(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--max-symbols", type=int, default=30)
    parser.add_argument("--max-minutes", type=int, default=360)
    parser.add_argument("--financial-timeout-seconds", type=int, default=180)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    from xtquant import xtdata
    scan(args.root, xt=xtdata, apply=args.apply,
         max_symbols=args.max_symbols, max_minutes=args.max_minutes,
         timeout_seconds=args.financial_timeout_seconds)


if __name__ == "__main__":
    main()
