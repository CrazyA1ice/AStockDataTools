#!/usr/bin/env python3
"""Conservative, explicitly opt-in QMT cached-financial repair for 000008.SZ.

The original 2026-11-16 Income snapshot had 12 rows and the Top10FlowHolder
read produced zero. Later cache-only reads observed 149 and 924 rows.
Preview never writes Parquet, progress.json, original eight-cycle or H5;
--apply creates only separate immutable qmt_extra/financial snapshots.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import os
from pathlib import Path

import qmt_extra_data as E

TARGET = "000008.SZ"
TABLES = ("Income", "Top10FlowHolder")
BASELINE_ASOF = "2026-11-16"
MINIMUM_ROWS = {"Income": 149, "Top10FlowHolder": 924}


def _row_multiset(records):
    """Preserve every raw provider field; row-index order is not a report key."""
    if any(not isinstance(row, dict) for row in records):
        raise ValueError("Invalid financial record shape")
    return Counter(E.canonical_json({k: v for k, v in row.items()
                                     if k != "_index"}) for row in records)


def _compare(baseline, fresh, table, minimum_rows):
    if len(fresh) < minimum_rows:
        raise ValueError("QMT cache fell below observed minimum for " +
                         table + ": " + str(len(fresh)) + " < " +
                         str(minimum_rows))
    old = _row_multiset(baseline or [])
    new = _row_multiset(fresh)
    missing = old - new
    if missing:
        raise ValueError(
            "Refusing QMT financial repair: previously saved source records "
            "were removed or revised in " + table + "; lost=" +
            str(sum(missing.values())))
    return {"previous_rows": len(baseline or []),
            "cached_rows": len(fresh),
            "extra_exact_records": sum((new - old).values()),
            "lost_or_changed_records": 0,
            "source": "QMT_LOCAL_CACHE_READ_ONLY",
            "historical_completeness_proven": False}


def reconcile(root, *, asof=None, baseline_asof=BASELINE_ASOF,
              apply=False, timeout_seconds=180, workspace=E.WORK,
              progress=print, expected_minimums=None):
    if asof is None:
        asof = datetime.now(E.L.UTC8).date().isoformat()
    E.date.fromisoformat(asof)
    E.date.fromisoformat(baseline_asof)
    # An observation may be fresher than the historical baseline, never
    # stamped as an earlier observation date.
    if asof < baseline_asof:
        raise ValueError("Repair observation date precedes source baseline")
    if apply and asof != datetime.now(E.L.UTC8).date().isoformat():
        raise ValueError("Repair --apply must use actual current market-local day")
    minimums = MINIMUM_ROWS if expected_minimums is None else expected_minimums
    extra = E._storage(Path(root))
    state = E._state(extra, workspace)
    if state.get("cursor", {}).get("financial", "") < TARGET:
        raise ValueError("Financial scan has not reached target security")
    report = {"symbol": TARGET, "asof": asof,
              "baseline_asof": baseline_asof,
              "mode": "APPLY" if apply else "PREVIEW",
              "tables": {}, "progress_modified": False,
              "purchased_8_cycle_modified": False, "h5_modified": False,
              "cache_download_called": False}

    # Hold the existing exclusive writer lock across BOTH source verification
    # and the optional commit. Live 21:30 updates cannot overlap this repair.
    with E.LIVE.exclusive_writer():
        staged = {}
        for name in TABLES:
            baseline = E._financial_snapshot_rows(
                extra, TARGET, name, baseline_asof)
            current = E._financial_snapshot_rows(extra, TARGET, name, asof)
            # On a later day, both baseline and any existing target-day
            # version must be preserved. Never allow regression of either.
            fresh = E._read_financial_isolated(
                TARGET, name, workspace, timeout_seconds=timeout_seconds,
                asof=asof, progress=progress, cached_only=True,
                record_failure=False)
            result = _compare(baseline, fresh, name, minimums[name])
            if current is not None:
                _compare(current, fresh, name, len(current))
            result["same_day_current_rows"] = (
                len(current) if current is not None else None)
            result["action"] = (
                "NO_CHANGE" if current is not None and
                _row_multiset(current) == _row_multiset(fresh) else
                "NEW_VERSION_REQUIRED")
            staged[name] = (fresh, result)
            report["tables"][name] = result

        if not apply:
            report["status"] = "QMT_FINANCIAL_REPAIR_READONLY_PREVIEW"
            progress("QMT_FINANCIAL_REPAIR_SUMMARY=" + E.canonical_json(report))
            return report

        # Both tables have already passed the same-source superset audit.
        # Snapshot commits are one table at a time; each table independently
        # keeps an immutable previous version and an atomic active pointer.
        for name, (fresh, result) in staged.items():
            if result["action"] == "NO_CHANGE":
                continue
            previous = E._financial_snapshot_file(extra, TARGET, name, asof)
            pin = E._financial_active_path(extra, TARGET, name, asof)
            if previous is not None and not pin.exists():
                # Pin the old version FIRST. A crash while writing the new
                # candidate will still leave the previous version selected.
                E._pin_financial_snapshot(extra, TARGET, name, asof, previous)
            table = E.snapshot_table(asof, TARGET, name, fresh)
            path = E._snapshot_path(
                extra, "financial/" + name + "/" + TARGET, asof, table)
            saved = E._snapshot_write(
                extra, "financial/" + name + "/" + TARGET,
                asof, table, workspace=workspace)
            E._verify_financial_snapshot_file(
                extra, TARGET, name, asof, path)
            E._pin_financial_snapshot(extra, TARGET, name, asof, path)
            result["committed_rows"] = len(fresh)
            result["commit_status"] = saved["status"]
            result["active_snapshot"] = path.name
            progress("QMT_FINANCIAL_REPAIR_TABLE_COMMITTED=" +
                     E.canonical_json({"symbol": TARGET, "table": name,
                                       **result}))
        report["status"] = "QMT_FINANCIAL_REPAIR_VERSIONED_COMMITTED"
        # Diagnostic audit ledger only, not a replacement for progress.json
        # or a claim that all nine financial tables are complete.
        receipt = Path(workspace) / "financial-repair.jsonl"
        E._path_check(receipt)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        with receipt.open("a", encoding="utf-8") as stream:
            stream.write(E.canonical_json(report) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    progress("QMT_FINANCIAL_REPAIR_SUMMARY=" + E.canonical_json(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--baseline-asof", default=BASELINE_ASOF)
    parser.add_argument("--asof", default=None,
                        help="Observation date, default: actual market-local today")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--apply", action="store_true",
                        help="Explicit immutable Parquet version commit")
    args = parser.parse_args(argv)
    if not 30 <= args.timeout_seconds <= 3600:
        parser.error("--timeout-seconds must be 30..3600")
    reconcile(args.root, asof=args.asof, baseline_asof=args.baseline_asof,
              timeout_seconds=args.timeout_seconds, apply=args.apply)


if __name__ == "__main__":
    main()
