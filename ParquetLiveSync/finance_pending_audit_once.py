#!/usr/bin/env python3
"""One-shot, non-committing financial pending audit for an idle QMT client.

Reads the existing pending ledger and verified *selected* Parquet snapshots,
then queries existing QMT finance cache (no download calls). Uses temporary
worker JSON files only; never edits state, snapshots, or scheduled-task files.

The 688259.SH Top10Holder UTF-8 case is already diagnosed and intentionally
NOT queried here to avoid repeatedly exercising the bad provider response.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time

TABLES = frozenset(("Top10Holder", "Top10FlowHolder", "HolderNum", "Capital"))
HOLDER_TABLES = frozenset(("Top10Holder", "Top10FlowHolder", "HolderNum"))
KNOWN_UTF8_SYMBOL = "688259.SH"
ERROR_GUARD_START = 18 * 60 + 45
ERROR_GUARD_END = 23 * 60 + 35


def china_now():
    return datetime.now(timezone(timedelta(hours=8)))


def guarded_time(now=None):
    if now is None:
        now = china_now()
    minutes = now.hour * 60 + now.minute
    if ERROR_GUARD_START <= minutes < ERROR_GUARD_END:
        raise RuntimeError("NIGHTLY_SCHEDULE_PROTECTION_STOP")


def blob_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(row, F):
    return F.E.canonical_json(row)


def historical_items(counter):
    for raw, count in counter.items():
        if not isinstance(count, int) or count < 1:
            raise ValueError("INVALID_HISTORICAL_MULTIPLICITY")
        row = json.loads(raw)
        if not isinstance(row, dict):
            raise ValueError("INVALID_HISTORICAL_RECORD")
        for _ in range(count):
            yield row


def _stable(row, ignored, F):
    return canonical({key: val for key, val in row.items() if key not in ignored}, F)


def holder_result(saved, fresh, table, F):
    """No approval is inferred from diagnostic projection equality."""
    if table not in HOLDER_TABLES:
        raise ValueError("INVALID_HOLDER_TABLE")
    oldrows = list(historical_items(saved))
    newrows = [{k: v for k, v in row.items() if k != "_index"} for row in fresh]
    old_raw = saved
    new_raw = F._rows(fresh)
    old_missing = sum((old_raw - new_raw).values())
    newly_seen = sum((new_raw - old_raw).values())
    ignored = frozenset(("_index", "declareDate"))
    if table != "HolderNum":
        ignored |= frozenset(("type",))
    oldproj = Counter(_stable(row, ignored, F) for row in oldrows)
    newproj = Counter(_stable(row, ignored, F) for row in newrows)
    if old_missing == 0 and newly_seen == 0:
        category = "RAW_MATCH"
    elif oldproj == newproj:
        category = "DATE_OR_TYPE_ONLY"
    else:
        category = "OTHER_FIELD_OR_ROW_CHANGE"
    changed = []
    if len(oldrows) + len(newrows) <= 30000:
        fields = sorted(set().union(*(set(row) for row in (oldrows + newrows))))
        for field in fields:
            if field == "_index":
                continue
            def values(rows):
                return Counter(canonical(row[field], F) if field in row else "<ABSENT>" for row in rows)
            if values(oldrows) != values(newrows):
                changed.append(field)
    else:
        changed.append("TOO_MANY_ROWS_TO_ENUMERATE")
    ambiguous = (sum(number for number in oldproj.values() if number > 1)
                 if oldproj == newproj else None)
    return {
        "classification": category,
        "historical_rows": len(oldrows),
        "cache_rows": len(newrows),
        "old_unmatched": old_missing,
        "new_unmatched": newly_seen,
        "changed_fields": changed,
        "ambiguous_projection_rows": ambiguous,
    }


def capital_result(saved, fresh, F):
    """Strict business-field/quarter-key diagnostics, NEVER a waiver."""
    oldrows = list(historical_items(saved))
    newrows = list(fresh)
    for row in oldrows + newrows:
        if not isinstance(row, dict) or row.get("m_timetag") is None or "m_quarter" not in row:
            return {"classification": "CAPITAL_UNVERIFIABLE_LAYOUT"}

    def grouped(rows):
        groups = defaultdict(list)
        for row in rows:
            groups[canonical(row["m_timetag"], F)].append(row)
        return groups

    def business(row):
        return _stable(row, frozenset(("_index", "m_quarter")), F)

    a = grouped(oldrows)
    b = grouped(newrows)
    removed = set(a) - set(b)
    added = set(b) - set(a)
    old_conflicting = sum(len({business(x) for x in rows}) > 1 for rows in a.values())
    fresh_duplicate_keys = sum(len(rows) != 1 for rows in b.values())
    shared_business_change = sum(
        {business(x) for x in a[key]} != {business(x) for x in b[key]}
        for key in set(a) & set(b)
    )
    if removed or old_conflicting or fresh_duplicate_keys or shared_business_change:
        kind = "CAPITAL_REPORT_OR_BUSINESS_CONFLICT"
    elif added:
        kind = "CAPITAL_ADDITIVE_KEYS_WITH_PRIOR_VARIANTS"
    else:
        # A past revision of m_quarter is still not permission to discard it.
        kind = "CAPITAL_SAME_KEYS_RAW_VERSION_COMPARE"
    return {
        "classification": kind,
        "historical_raw_versions": len(oldrows),
        "historical_report_keys": len(a),
        "current_report_keys": len(b),
        "missing_old_report_keys": len(removed),
        "new_report_keys": len(added),
        "historical_business_conflict_keys": old_conflicting,
        "current_duplicate_report_keys": fresh_duplicate_keys,
        "shared_business_changed_keys": shared_business_change,
    }


def selected_cases(p):
    out = {}
    unclassified = []
    pending = p.get("pending")
    if not isinstance(pending, dict):
        raise ValueError("INVALID_PENDING_LEDGER")
    for code, entry in sorted(pending.items()):
        if not isinstance(entry, dict):
            raise ValueError("MALFORMED_PENDING_ENTRY")
        reason = entry.get("reason")
        if code == KNOWN_UTF8_SYMBOL and reason == "CACHE_DECODE_ERROR":
            print("KNOWN_UTF8_ISOLATED=688259.SH Top10Holder 20260930 buffer=199 last_byte=e5; no re-query")
            continue
        if reason != "SOURCE_HISTORY_CONFLICT":
            unclassified.append((code, reason))
            continue
        hit = re.search(r"\btable=([A-Za-z][A-Za-z0-9_]*)", str(entry.get("detail", "")))
        if hit is None or hit.group(1) not in TABLES:
            unclassified.append((code, reason))
            continue
        out[code] = hit.group(1)
    return out, unclassified


def plan_batches(codes, n=10):
    if not 1 <= n <= 20:
        raise ValueError("INVALID_BATCH_SIZE")
    codes = sorted(set(codes))
    return [codes[i:i + n] for i in range(0, len(codes), n)]


def receipt_summary(base):
    path = base / "work" / "last-afternoon-unified.json"
    if not path.is_file():
        print("RUN_RECEIPT=MISSING")
        return
    o = json.loads(path.read_text(encoding="utf-8"))
    val = o.get("validation") or {}
    print("RUN_RECEIPT=" + json.dumps({
        "china_start": o.get("china_start"), "status": o.get("status"),
        "execution": val.get("execution"),
        "data_validation": val.get("data_validation"),
        "cross_validation": val.get("cross_validation"),
        "routine_continuation": val.get("routine_continuation"),
        "operational_classification": o.get("operational_classification")
    }, ensure_ascii=True, sort_keys=True))


def audit(base, F, max_minutes=10, batch_size=10):
    base = Path(base)
    ledger = base / "work" / "qmt_extra" / "financial-cache-progress.json"
    before = blob_sha256(ledger)
    started = time.monotonic()
    results = Counter()
    by_table = Counter()
    seen = set()
    try:
        p = json.loads(ledger.read_text(encoding="utf-8"))
        if p.get("format") != "qmt_financial_cache_import_v1":
            raise ValueError("PROGRESS_FORMAT_MISMATCH")
        root = Path(p["root"])
        if not root.is_dir() or root.is_symlink():
            raise ValueError("PRIVATE_SNAPSHOT_ROOT_INVALID")
        cases, unknown = selected_cases(p)
        print("LEDGER_DATE=" + str(p.get("daily_date")))
        print("TOTAL_PENDING=" + str(len(p["pending"])))
        print("HISTORY_CASES=" + str(len(cases)))
        print("OTHER_PENDING=" + json.dumps(unknown, ensure_ascii=True))
        print("DAILY_CURSOR=" + str(p.get("daily_cursor", "")))
        print("PENDING_RETRY_CURSOR=" + str(p.get("pending_retry_cursor", "")))
        for idx, group in enumerate(plan_batches(cases, batch_size), 1):
            guarded_time()
            if time.monotonic() - started >= max_minutes * 60:
                raise TimeoutError("AUDIT_WALL_CLOCK_BUDGET_EXHAUSTED")
            print("CACHE_BATCH_START={} STOCKS={}".format(idx, len(group)), flush=True)
            # QMT request mode='cache'; worker never calls download_financial_data2.
            with tempfile.TemporaryDirectory(prefix="finance-pending54-audit-") as tmp:
                recovered = F._recover_utf8_group(
                    F._worker_batch, group, "cache", p["daily_date"], 120,
                    tmp, 90, progress=lambda msg: None
                )
                if [c for c, _, _ in recovered] != group:
                    raise ValueError("CACHE_STOCK_SET_MISMATCH")
                for code, data, reason in recovered:
                    seen.add(code)
                    table = cases[code]
                    if reason is not None:
                        classification = "CACHE_" + reason
                        detail = {"classification": classification}
                    else:
                        if not isinstance(data, dict) or table not in data:
                            raise ValueError("CACHE_TABLE_MISSING_" + code)
                        _, prior = F._prior_rows(root, code, table)
                        if prior is None:
                            raise ValueError("VERIFIED_HISTORY_MISSING_" + code)
                        if table == "Capital":
                            detail = capital_result(prior, data[table], F)
                        else:
                            detail = holder_result(prior, data[table], table, F)
                        classification = detail["classification"]
                    results[classification] += 1
                    by_table[(table, classification)] += 1
                    print("AUDIT=" + json.dumps({
                        "symbol": code, "table": table, **detail
                    }, ensure_ascii=True, sort_keys=True), flush=True)
        if seen != set(cases):
            raise ValueError("INCOMPLETE_COHORT")
        print("RESULTS=" + json.dumps(dict(sorted(results.items())), sort_keys=True))
        print("TABLE_RESULTS=" + json.dumps([
            {"table": t, "status": k, "stocks": count}
            for (t, k), count in sorted(by_table.items())
        ], sort_keys=True))
        receipt_summary(base)
        print("FINANCE_PENDING_COMPREHENSIVE_CACHE_AUDIT_PASS_NO_COMMIT")
    finally:
        after = blob_sha256(ledger)
        if after != before:
            raise RuntimeError("FINANCE_PENDING_LEDGER_CHANGED_DURING_AUDIT_STOP")
        print("FINANCE_LEDGER_UNCHANGED_VERIFIED sha256=" + after, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path, help="Production ParquetLiveSync directory")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-minutes", type=int, default=10)
    args = parser.parse_args(argv)
    if not args.base.is_dir() or args.max_minutes < 1:
        parser.error("Invalid production directory or time budget")
    guarded_time()
    sys.path.insert(0, str(args.base))
    import qmt_extra_financial_cache_import as F
    audit(args.base, F, max_minutes=args.max_minutes, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
