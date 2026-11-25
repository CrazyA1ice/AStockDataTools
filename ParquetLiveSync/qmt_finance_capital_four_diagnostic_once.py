#!/usr/bin/env python3
"""One guarded, read-only Capital source-cause audit for four blocked symbols.

Uses QMT's EXISTING cache once and selected verified historical snapshot files.
Never downloads, commits, normalizes, resolves pending, or changes active pins.
A duplicate raw historical row is evidence to investigate, NOT permission
to de-duplicate or weaken the nine-table recovery gate.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

CODES = ("002188.SZ", "002310.SZ", "002328.SZ", "002388.SZ")
TARGET = {"002188.SZ": "Capital", "002310.SZ": "Top10Holder",
          "002328.SZ": "HolderNum", "002388.SZ": "Top10FlowHolder"}
LEDGER_SHA = "4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1"
LEDGER_DATE = "2026-11-24"
LEDGER_FORMAT = "qmt_financial_cache_import_v1"
BEIJING = timezone(timedelta(hours=8))
NAME = re.compile(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{16}\.parquet\Z")


def protect_time(now=None):
    now = now or datetime.now(BEIJING)
    minutes = now.hour * 60 + now.minute
    if 18 * 60 + 30 <= minutes < 23 * 60 + 35:
        raise RuntimeError("CAPITAL_DIAG_NIGHTLY_SCHEDULE_WINDOW_STOP")


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_epoch(state, sha):
    if sha != LEDGER_SHA:
        raise RuntimeError("CAPITAL_DIAG_VERIFIED_LEDGER_SHA_CHANGED_STOP")
    if (not isinstance(state, dict) or state.get("format") != LEDGER_FORMAT
            or state.get("daily_date") != LEDGER_DATE
            or not isinstance(state.get("root"), str)
            or not isinstance(state.get("pending"), dict)
            or len(state["pending"]) != 54):
        raise RuntimeError("CAPITAL_DIAG_LEDGER_EPOCH_OR_SHAPE_CHANGED_STOP")
    if (not isinstance(state["pending"].get("688259.SH"), dict)
            or state["pending"]["688259.SH"].get("reason") != "CACHE_DECODE_ERROR"):
        raise RuntimeError("CAPITAL_DIAG_UTF8_QUARANTINE_DRIFT_STOP")
    for code in CODES:
        entry = state["pending"].get(code)
        if (not isinstance(entry, dict)
                or entry.get("reason") != "SOURCE_HISTORY_CONFLICT"
                or not re.search(r"\btable=" + re.escape(TARGET[code]) + r"\b",
                                 str(entry.get("detail", "")))):
            raise RuntimeError("CAPITAL_DIAG_TARGET_PENDING_CHANGED_" + code)


def key(row, E):
    if not isinstance(row, dict) or "m_quarter" not in row:
        raise ValueError("CAPITAL_DIAG_FIELD_LAYOUT_CHANGED")
    value = row.get("m_timetag")
    if (value is None or isinstance(value, (bool, dict, list))
            or str(value).strip() in ("", "0")):
        raise ValueError("CAPITAL_DIAG_REPORT_KEY_MALFORMED")
    return E.canonical_json(value)


def without_index(row):
    return {k: v for k, v in row.items() if k != "_index"}


def raw(row, E):
    return E.canonical_json(without_index(row))


def economic(row, E):
    return E.canonical_json({k: v for k, v in row.items()
                             if k not in ("_index", "m_quarter")})


def group_rows(rows, E):
    groups = defaultdict(list)
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("CAPITAL_DIAG_NON_MAPPING_RECORD")
        groups[key(r, E)].append(r)
    return groups


def historical_rows(counter, E):
    if not isinstance(counter, Counter):
        raise ValueError("CAPITAL_DIAG_HISTORICAL_COUNTER_REQUIRED")
    rows = []
    for record, count in counter.items():
        if not isinstance(record, str) or type(count) is not int or count < 1:
            raise ValueError("CAPITAL_DIAG_HISTORICAL_MULTIPLICITY_INVALID")
        value = json.loads(record)
        if not isinstance(value, dict) or raw(value, E) != record:
            raise ValueError("CAPITAL_DIAG_HISTORICAL_PAYLOAD_MISMATCH")
        rows.extend([value] * count)
    return rows


def analyze_capital(prior, current, E):
    """Explain, not waive, Capital history differences and duplicate counts."""
    old_rows = historical_rows(prior, E)
    if not isinstance(current, list):
        raise ValueError("CAPITAL_DIAG_INVALID_CURRENT_ROWS")
    new_rows = []
    for row in current:
        if not isinstance(row, dict) or not isinstance(row.get("_index"), str):
            raise ValueError("CAPITAL_DIAG_CURRENT_INDEX_INVALID")
        new_rows.append(without_index(row))

    old = group_rows(old_rows, E)
    new = group_rows(new_rows, E)
    old_keys, new_keys = set(old), set(new)
    missing_keys = sorted(old_keys - new_keys)
    added_keys = sorted(new_keys - old_keys)
    old_business_conflicts = []
    shared_business_changes = []
    mquarter_variation_keys = []
    duplicate_old_raw = sum(n - 1 for n in prior.values() if n > 1)
    dup_old_report_keys = sorted(k for k, v in old.items() if len(v) > 1)
    dup_new_report_keys = sorted(k for k, v in new.items() if len(v) > 1)
    for k in sorted(old_keys):
        old_business = {economic(r, E) for r in old[k]}
        if len(old_business) != 1:
            old_business_conflicts.append(k)
        if k in new:
            fresh_business = {economic(r, E) for r in new[k]}
            if old_business != fresh_business:
                shared_business_changes.append(k)
            elif {E.canonical_json(r["m_quarter"]) for r in old[k]} != {
                    E.canonical_json(r["m_quarter"]) for r in new[k]}:
                mquarter_variation_keys.append(k)

    old_counter = Counter(raw(r, E) for r in old_rows)
    new_counter = Counter(raw(r, E) for r in new_rows)
    old_missing = sum((old_counter - new_counter).values())
    new_extra = sum((new_counter - old_counter).values())
    if missing_keys:
        category = "REPORT_KEYS_MISSING_FROM_CURRENT"
    elif dup_new_report_keys:
        category = "CURRENT_DUPLICATE_REPORT_KEY"
    elif old_business_conflicts:
        category = "HISTORICAL_BUSINESS_CONFLICT"
    elif shared_business_changes:
        category = "SHARED_ECONOMIC_FIELD_CHANGE"
    elif duplicate_old_raw:
        category = "HISTORICAL_RAW_DUPLICATES_REVIEW"
    elif added_keys:
        category = "ADDITIVE_REPORT_KEYS_REVIEW"
    elif mquarter_variation_keys or old_missing:
        category = "M_QUARTER_OR_RAW_VERSION_REVIEW"
    else:
        category = "RAW_MATCH"
    return {
        "classification": category,
        "historical_raw_rows": len(old_rows),
        "historical_distinct_raw_rows": len(prior),
        "current_rows": len(new_rows),
        "old_report_keys": len(old_keys),
        "current_report_keys": len(new_keys),
        "new_report_keys": added_keys[:12],
        "removed_report_keys": missing_keys[:12],
        "new_report_keys_count": len(added_keys),
        "removed_report_keys_count": len(missing_keys),
        "historical_duplicate_raw_extra_rows": duplicate_old_raw,
        "historical_duplicate_report_keys_count": len(dup_old_report_keys),
        "current_duplicate_report_keys_count": len(dup_new_report_keys),
        "historical_economic_conflict_keys": len(old_business_conflicts),
        "shared_economic_changed_keys": len(shared_business_changes),
        "m_quarter_variant_shared_keys": len(mquarter_variation_keys),
        "old_unmatched_raw_rows": old_missing,
        "new_unmatched_raw_rows": new_extra,
        "historical_raw_union_sha256": hashlib.sha256(
            E.canonical_json(sorted(prior.items())).encode("utf-8")).hexdigest(),
        "current_raw_rows_sha256": hashlib.sha256(
            E.canonical_json(sorted(new_counter.items())).encode("utf-8")).hexdigest(),
        "approval_granted": False,
        "pending_clear_allowed": False,
    }


def selected_snapshot_diagnostics(root, code, E, F):
    """Reconcile _prior_rows Counter-maximum union against per-asof snapshots."""
    folder = root / "financial" / "Capital" / code / "snapshots"
    E._path_check(folder)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("CAPITAL_DIAG_SNAPSHOT_FOLDER_MISSING_OR_LINKED")
    names = sorted(p.name for p in folder.glob("*.parquet"))
    if not names or any(NAME.fullmatch(n) is None for n in names):
        raise ValueError("CAPITAL_DIAG_INVALID_SNAPSHOT_FILENAME")
    days = sorted({n[:10] for n in names})
    combined = Counter()
    per_day = []
    for day in days:
        selected = E._financial_snapshot_file(root, code, "Capital", day)
        if selected is None or not selected.is_file():
            raise ValueError("CAPITAL_DIAG_SELECTED_VERSION_MISSING")
        E._path_check(selected)
        records = E._financial_snapshot_rows(root, code, "Capital", day)
        if not isinstance(records, list):
            raise ValueError("CAPITAL_DIAG_SELECTED_SNAPSHOT_MALFORMED")
        counted = F._rows(records)
        combined |= counted
        report_keys = group_rows(records, E)
        per_day.append({
            "asof": day,
            "selected_filename": selected.name,
            "selected_file_sha256": file_sha(selected),
            "rows": len(records),
            "distinct_raw_rows": len(counted),
            "duplicate_raw_extra_rows": sum(n - 1 for n in counted.values() if n > 1),
            "duplicate_report_keys": sum(len(v) > 1 for v in report_keys.values()),
            "report_keys": len(report_keys),
        })
    latest, true_union = F._prior_rows(root, code, "Capital")
    if latest != max(days) or true_union != combined:
        raise RuntimeError("CAPITAL_DIAG_SELECTED_UNION_RECONCILIATION_FAILED")
    return combined, per_day


def run(base, E, F):
    base = Path(base)
    ledger = base / "work" / "qmt_extra" / "financial-cache-progress.json"
    before = file_sha(ledger)
    try:
        protect_time()
        state = json.loads(ledger.read_text(encoding="utf-8"))
        verify_epoch(state, before)
        root = Path(state["root"])
        E._path_check(root)
        if not root.is_dir() or root.is_symlink():
            raise RuntimeError("CAPITAL_DIAG_ROOT_INVALID")
        with tempfile.TemporaryDirectory(prefix="finance-capital-four-cause-") as tmp:
            protect_time()
            print("CAPITAL_FOUR_DIAG_CACHE_READ_START", flush=True)
            cache, missing = F._worker_batch(
                list(CODES), "cache", state["daily_date"], 120, tmp, 120,
                progress=lambda msg: print("CAPITAL_CACHE_WORKER=" + msg, flush=True))
            if missing or set(cache) != set(CODES):
                raise RuntimeError("CAPITAL_DIAG_FOUR_STOCK_CACHE_INCOMPLETE")
            outputs = []
            for code in CODES:
                protect_time()
                tables = cache[code]
                if not isinstance(tables, dict) or set(tables) != set(E.FIN_TABLES):
                    raise RuntimeError("CAPITAL_DIAG_NINE_TABLE_CACHE_MISSING_" + code)
                union, snapshots = selected_snapshot_diagnostics(root, code, E, F)
                proof = analyze_capital(union, tables["Capital"], E)
                # No provider rows or shareholder names are included.
                outputs.append({"symbol": code,
                                "original_blocked_table": TARGET[code],
                                "capital": proof,
                                "selected_snapshots": snapshots})
        # Do not publish evidence summaries until final ledger check succeeds.
    finally:
        after = file_sha(ledger)
        if after != before:
            raise RuntimeError("CAPITAL_DIAG_LEDGER_CHANGED_DURING_READ_STOP")
        print("CAPITAL_DIAG_LEDGER_UNCHANGED_VERIFIED sha256=" + after, flush=True)
    for item in outputs:
        print("CAPITAL_ROOT_CAUSE=" + json.dumps(
            item, ensure_ascii=True, sort_keys=True), flush=True)
    counts = Counter(x["capital"]["classification"] for x in outputs)
    print("CAPITAL_FOUR_ROOT_CAUSE_SUMMARY=" + json.dumps({
        "symbols": len(outputs), "classifications": dict(sorted(counts.items())),
        "approval_granted": False, "allow_apply": False,
        "allow_pending_clear": False, "no_parquet_or_pin_updates": True,
    }, sort_keys=True), flush=True)
    print("FINANCE_CAPITAL_FOUR_DIAG_COMPLETE_NO_DEPLOY", flush=True)


def main(argv=None):
    parser = __import__("argparse").ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    args = parser.parse_args(argv)
    if not args.base.is_dir() or args.base.is_symlink():
        parser.error("invalid production base")
    protect_time()
    sys.path.insert(0, str(args.base))
    import qmt_extra_financial_cache_import as F
    import qmt_extra_data as E
    run(args.base, E, F)


if __name__ == "__main__":
    main()
