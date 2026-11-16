#!/usr/bin/env python3
"""Foreground unattended first-pass QMT financial scan, with safe nightly pauses.

Continue across one-day scanner limits, automatically resume after the 21:30
protected window, and finish only when the A-share high-water scan is exhausted
(or a finite operator-defined days budget is reached). Never retry local
corruption, hide source failures, auto-wrap, or modify existing scheduled tasks.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from pathlib import Path
import sys
import time as clock_time

import qmt_extra_data as E
import qmt_extra_financial_bulk as B

DONE = frozenset(("SCAN_EXHAUSTED_PENDING_RETRIES",
                  "SCAN_EXHAUSTED_COVERAGE_UNVERIFIED"))
BLOCKED = frozenset(("PAUSED_PROTECTED_2130_WINDOW",
                     "PAUSED_INSUFFICIENT_PRE_2130_WORST_CASE_WINDOW"))
BUDGETED = frozenset(("PAUSED_TIME_BUDGET", "PAUSED_SYMBOL_LIMIT"))
WAKE_AT = time(23, 5)


@contextmanager
def keep_awake(enabled):
    """Opt-in Windows process lifetime system sleep prevention, reversible."""
    if not enabled:
        yield
        return
    if sys.platform != "win32":
        raise RuntimeError("--keep-awake requires Windows")
    from ctypes import windll
    # Windows SetThreadExecutionState; keep display free to turn off.
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    if not windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
        raise OSError("SetThreadExecutionState could not inhibit system sleep")
    try:
        yield
    finally:
        windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def _resume_after_blackout(now):
    local = B._local_now(lambda: now)
    target = datetime.combine(local.date(), WAKE_AT, tzinfo=E.L.UTC8)
    if target <= local:
        raise ValueError("Unexpected blackout pause after resumption time")
    return (target - local).total_seconds()


def run_foreground(root, *, xt, max_days=45, max_symbols_per_session=6000,
                   max_minutes_per_session=1440, timeout_seconds=180,
                   keep_awake_enabled=False, clock=None,
                   sleep=None, progress=print, scan_fn=None):
    """Loop only on known, safe pause statuses; no busy restart or fake success."""
    if not isinstance(max_days, int) or not 1 <= max_days <= 90:
        raise ValueError("max_days must be 1..90")
    if not 1 <= max_symbols_per_session <= 10000:
        raise ValueError("max_symbols_per_session must be 1..10000")
    if not 1 <= max_minutes_per_session <= 1440:
        raise ValueError("max_minutes_per_session must be 1..1440")
    if not 30 <= timeout_seconds <= 3600:
        raise ValueError("timeout_seconds must be 30..3600")
    if clock is None:
        clock = lambda: datetime.now(E.L.UTC8)
    if sleep is None:
        sleep = clock_time.sleep
    if scan_fn is None:
        scan_fn = B.scan
    started = B._local_now(clock)
    deadline = started + timedelta(days=max_days)
    sessions = 0
    processed = 0
    deferred = 0
    last_cursor = None
    pending = None
    status = "NOT_STARTED"
    with keep_awake(keep_awake_enabled):
        while B._local_now(clock) < deadline:
            session = scan_fn(
                root, xt=xt, apply=True,
                max_symbols=max_symbols_per_session,
                max_minutes=max_minutes_per_session,
                timeout_seconds=timeout_seconds,
                clock=clock, progress=progress)
            sessions += 1
            status = session.get("status")
            completed = session.get("symbols_processed", 0)
            skipped = session.get("symbols_deferred", 0)
            if (not isinstance(completed, int) or completed < 0 or
                    not isinstance(skipped, int) or skipped < 0):
                raise ValueError("Financial session has malformed progress")
            processed += completed
            deferred += skipped
            last_cursor = session.get("last_cursor")
            pending = session.get("pending_retry_count")
            progress("QMT_FINANCIAL_UNATTENDED_SESSION=" + E.canonical_json({
                "sessions": sessions, "session_status": status,
                "session_processed": completed, "session_deferred": skipped,
                "processed_total": processed, "deferred_total": deferred,
                "cursor": last_cursor, "pending_retry_count": pending}))
            if status in DONE:
                break
            if status in BLOCKED:
                remaining = (deadline - B._local_now(clock)).total_seconds()
                if remaining <= 0:
                    status = "STOPPED_MAX_DAYS"
                    break
                wait = min(_resume_after_blackout(B._local_now(clock)), remaining)
                progress("QMT_FINANCIAL_UNATTENDED_WAIT=" + E.canonical_json({
                    "seconds": round(wait), "reason": status,
                    "resume_at_market_local": WAKE_AT.isoformat()}))
                sleep(wait)
                continue
            if status in BUDGETED:
                if completed + skipped <= 0:
                    # No progress after 24h time budget or 6000 symbols cap:
                    # refuse to hammer the QMT connection indefinitely.
                    raise RuntimeError("Bounded financial session made no progress: "
                                       + status)
                continue
            raise RuntimeError("Unrecognized financial session status " +
                               repr(status))
        else:
            status = "STOPPED_MAX_DAYS"
    summary = {
        "status": status, "sessions": sessions,
        "processed_total": processed, "deferred_total": deferred,
        "last_cursor": last_cursor, "pending_retry_count": pending,
        "scan_exhausted": status in DONE,
        "historical_completeness_verified": False,
        "background_task_installed": False,
        "purchased_8_cycle_modified": False,
        "h5_modified": False}
    progress("QMT_FINANCIAL_UNATTENDED_FINAL=" + E.canonical_json(summary))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--max-days", type=int, default=45)
    parser.add_argument("--max-symbols-per-session", type=int, default=6000)
    parser.add_argument("--max-minutes-per-session", type=int, default=1440)
    parser.add_argument("--financial-timeout-seconds", type=int, default=180)
    parser.add_argument("--keep-awake", action="store_true",
                        help="Opt-in Windows system sleep inhibition for this process")
    parser.add_argument("--apply", action="store_true",
                        help="Required for all-night real financial collection")
    args = parser.parse_args(argv)
    if not args.apply:
        parser.error("Explicit --apply required; use bulk.py without --apply for preview")
    from xtquant import xtdata
    run_foreground(
        args.root, xt=xtdata, max_days=args.max_days,
        max_symbols_per_session=args.max_symbols_per_session,
        max_minutes_per_session=args.max_minutes_per_session,
        timeout_seconds=args.financial_timeout_seconds,
        keep_awake_enabled=args.keep_awake)


if __name__ == "__main__":
    main()
