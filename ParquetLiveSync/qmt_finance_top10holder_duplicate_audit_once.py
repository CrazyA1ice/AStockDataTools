#!/usr/bin/env python3
"""Trace 002188.SZ Top10Holder selected historical raw multiplicities.

One existing-cache read; no downloads, imports, deduplication, pending changes,
active-pin edits or Parquet writes. Raw holder names never appear in output.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

CODE = "002188.SZ"
TABLE = "Top10Holder"
LEDGER_SHA = "4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1"
LEDGER_DATE = "2026-11-24"
NAME = re.compile(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{16}\.parquet\Z")


def sha_bytes(v):
    return hashlib.sha256(v).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def guard_clock(now=None):
    now = now or datetime.now(timezone(timedelta(hours=8)))
    minute = now.hour * 60 + now.minute
    if 18 * 60 + 30 <= minute < 23 * 60 + 35:
        raise RuntimeError("DUPLICATE_AUDIT_SCHEDULE_WINDOW_STOP")


def verify_ledger(state, digest):
    if digest != LEDGER_SHA:
        raise RuntimeError("DUPLICATE_AUDIT_LEDGER_PIN_CHANGED_STOP")
    if (not isinstance(state, dict)
            or state.get("format") != "qmt_financial_cache_import_v1"
            or state.get("daily_date") != LEDGER_DATE
            or not isinstance(state.get("root"), str)
            or not isinstance(state.get("pending"), dict)
            or len(state["pending"]) != 54):
        raise RuntimeError("DUPLICATE_AUDIT_LEDGER_EPOCH_CHANGED_STOP")
    target = state["pending"].get(CODE)
    bad = state["pending"].get("688259.SH")
    if (not isinstance(target, dict)
            or target.get("reason") != "SOURCE_HISTORY_CONFLICT"
            or re.search(r"\btable=Capital\b", str(target.get("detail", ""))) is None
            or not isinstance(bad, dict)
            or bad.get("reason") != "CACHE_DECODE_ERROR"):
        raise RuntimeError("DUPLICATE_AUDIT_PENDING_SCOPE_CHANGED_STOP")


def examine(day_rows, current_rows, F):
    """Pure Counter(MAX) reconstruction with old/current raw row counts."""
    if not isinstance(day_rows, dict) or not day_rows:
        raise ValueError("DUPLICATE_AUDIT_DAYS_INVALID")
    if not isinstance(current_rows, list):
        raise ValueError("DUPLICATE_AUDIT_CURRENT_ROWS_INVALID")
    daily = {}
    for day, rows in sorted(day_rows.items()):
        if not isinstance(rows, list) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("DUPLICATE_AUDIT_PER_DAY_INVALID")
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("DUPLICATE_AUDIT_SNAPSHOT_ROW_INVALID")
        daily[day] = F._rows(rows)
    if any(not isinstance(row, dict) for row in current_rows):
        raise ValueError("DUPLICATE_AUDIT_CACHE_ROW_INVALID")
    current = F._rows(current_rows)
    union = Counter()
    for day in sorted(daily):
        union |= daily[day]
    if any(not isinstance(raw, str) or type(n) is not int or n < 1
           for raw, n in union.items()):
        raise ValueError("DUPLICATE_AUDIT_COUNTER_INVALID")
    duplicated = sorted(raw for raw, n in union.items() if n > 1)
    records = []
    for raw in duplicated:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError("DUPLICATE_AUDIT_RAW_PAYLOAD_INVALID")
        provenance = []
        for day in sorted(daily):
            n = daily[day][raw]
            if n:
                positions = {
                    str(r.get("_index")) for r in day_rows[day]
                    if F.E.canonical_json({k: v for k, v in r.items()
                                           if k != "_index"}) == raw}
                provenance.append({
                    "asof": day, "raw_row_occurrences": n,
                    "distinct_snapshot_row_positions": len(positions)})
        records.append({
            "raw_sha256": sha_bytes(raw.encode("utf-8")),
            "report_endDate": obj.get("endDate"),
            "history_union_max_count": union[raw],
            "history_extra_count": union[raw] - 1,
            "current_cache_count": current[raw],
            "selected_snapshot_days": provenance,
            "separate_economic_owner_identity_unproven": True,
            "allow_deduplication": False,
        })
    extra = sum(v-1 for v in union.values() if v > 1)
    summary = {
        "symbol": CODE, "table": TABLE,
        "selected_days": len(daily),
        "historical_distinct_raw_records": len(union),
        "historical_records_with_multiplicity": sum(union.values()),
        "historical_raw_duplicate_groups": len(records),
        "historical_extra_raw_occurrences": extra,
        "matches_prior_779_distinct_plus_9": len(union) == 779 and extra == 9,
        "current_rows": len(current_rows),
        "current_distinct_raw_records": len(current),
        "current_extra_raw_occurrences": sum(n-1 for n in current.values() if n > 1),
        "missing_historical_occurrences_in_current": sum((union-current).values()),
        "new_current_occurrences": sum((current-union).values()),
        "historical_union_sha256": sha_bytes(
            F.E.canonical_json(sorted(union.items())).encode("utf-8")),
        "allow_deduplication": False, "allow_apply": False,
        "allow_pending_clear": False,
    }
    return summary, records, union, daily


def run(base, E, F):
    base = Path(base)
    ledger = base / "work" / "qmt_extra" / "financial-cache-progress.json"
    before = sha_file(ledger)
    try:
        guard_clock()
        state = json.loads(ledger.read_text(encoding="utf-8"))
        verify_ledger(state, before)
        root = Path(state["root"])
        E._path_check(root)
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError("DUPLICATE_AUDIT_SOURCE_ROOT_INVALID")
        with tempfile.TemporaryDirectory(prefix="finance-holder-duplicate-readonly-") as temp:
            guard_clock()
            cache, missing = F._worker_batch(
                [CODE], "cache", LEDGER_DATE, 120, temp, 120,
                progress=lambda s: print("DUPLICATE_AUDIT_CACHE_WORKER=" + s, flush=True))
            if missing or set(cache) != {CODE}:
                raise RuntimeError("DUPLICATE_AUDIT_CACHE_INCOMPLETE")
            source = cache[CODE]
            if not isinstance(source, dict) or set(source) != set(E.FIN_TABLES):
                raise RuntimeError("DUPLICATE_AUDIT_NINE_TABLES_MISSING")
            folder = root / "financial" / TABLE / CODE / "snapshots"
            E._path_check(folder)
            if folder.is_symlink() or not folder.is_dir():
                raise RuntimeError("DUPLICATE_AUDIT_SNAPSHOT_FOLDER_INVALID")
            filenames = sorted(p.name for p in folder.glob("*.parquet"))
            if not filenames or any(NAME.fullmatch(name) is None for name in filenames):
                raise RuntimeError("DUPLICATE_AUDIT_SNAPSHOT_NAMES_INVALID")
            days = sorted({name[:10] for name in filenames})
            daily = {}
            selected_files = []
            for day in days:
                guard_clock()
                path = E._financial_snapshot_file(root, CODE, TABLE, day)
                if path is None or path.is_symlink() or not path.is_file():
                    raise RuntimeError("DUPLICATE_AUDIT_ACTIVE_VERSION_MISSING")
                E._path_check(path)
                digest = sha_file(path)
                rows = E._financial_snapshot_rows(root, CODE, TABLE, day)
                if rows is None or sha_file(path) != digest:
                    raise RuntimeError("DUPLICATE_AUDIT_SNAPSHOT_CHANGED_DURING_READ")
                daily[day] = rows
                counts = F._rows(rows)
                selected_files.append({
                    "asof": day, "filename": path.name,
                    "snapshot_sha256": digest,
                    "rows": len(rows),
                    "distinct_raw_records": len(counts),
                    "extra_raw_occurrences": sum(n-1 for n in counts.values() if n > 1)})
            summary, records, union, _ = examine(daily, source[TABLE], F)
            latest, production_union = F._prior_rows(root, CODE, TABLE)
            if latest != days[-1] or production_union != union:
                raise RuntimeError("DUPLICATE_AUDIT_COUNTER_MAX_UNION_MISMATCH")
            result = {"snapshots": selected_files, "records": records, "summary": summary}
    finally:
        after = sha_file(ledger)
        if before != after:
            raise RuntimeError("DUPLICATE_AUDIT_LEDGER_CHANGED_DURING_RUN_STOP")
        print("DUPLICATE_AUDIT_LEDGER_UNCHANGED_VERIFIED sha256=" + after, flush=True)
    for item in result["snapshots"]:
        print("DUPLICATE_AUDIT_SELECTED_SNAPSHOT=" + json.dumps(item, sort_keys=True), flush=True)
    for item in result["records"]:
        print("DUPLICATE_AUDIT_ROW_PROVENANCE=" + json.dumps(item, sort_keys=True), flush=True)
    print("DUPLICATE_AUDIT_SUMMARY=" + json.dumps(result["summary"], sort_keys=True), flush=True)
    print("DUPLICATE_AUDIT_COMPLETE_NO_DEPLOY", flush=True)
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    args = parser.parse_args(argv)
    if not args.base.is_dir() or args.base.is_symlink():
        parser.error("invalid canonical production base")
    guard_clock()
    sys.path.insert(0, str(args.base))
    import qmt_extra_data as E
    import qmt_extra_financial_cache_import as F
    run(args.base, E, F)


if __name__ == "__main__":
    main()
