#!/usr/bin/env python3
"""Read-only diagnosis of QMT Capital history differences before repair.

No source downloads. Reads immutable Parquet snapshots and compares QMT's
single-table and one-stock nine-table cache APIs. Writes only ephemeral
private worker results that are removed after each isolated call.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I


def _counter(records):
    return I._rows(records)


def _columns(records):
    return sorted(set().union(*(set(x) - {"_index"} for x in records))) if records else []


def _key_value(row):
    for name in ("m_timetag", "m_reporttime", "m_report_time",
                 "report_time", "report_date", "m_anntime"):
        value = row.get(name)
        if value is not None and str(value).strip():
            return (name, str(value))
    return None


def _keyed_unique(records):
    grouped = {}
    for row in records:
        key = _key_value(row)
        if key is not None:
            grouped.setdefault(key, []).append(row)
    return {key: rows[0] for key, rows in grouped.items() if len(rows) == 1}


def _field_differences(old_records, new_records):
    a = _keyed_unique(old_records)
    b = _keyed_unique(new_records)
    keys = sorted(set(a) & set(b))
    changes = Counter()
    samples = []
    identical = 0
    for key in keys:
        old = {k: v for k, v in a[key].items() if k != "_index"}
        new = {k: v for k, v in b[key].items() if k != "_index"}
        if E.canonical_json(old) == E.canonical_json(new):
            identical += 1
            continue
        fields = [k for k in sorted(set(old) | set(new))
                  if E.canonical_json(old.get(k)) !=
                  E.canonical_json(new.get(k))]
        changes.update(fields)
        if len(samples) < 3:
            samples.append({
                "report_key": list(key),
                "diffs": [
                    {"field": k,
                     "old_type": type(old.get(k)).__name__,
                     "new_type": type(new.get(k)).__name__,
                     "old_value": str(old.get(k))[:80],
                     "new_value": str(new.get(k))[:80]}
                    for k in fields[:6]],
                "total_different_fields": len(fields)})
    return {
        "keyed_old": len(a), "keyed_new": len(b),
        "matched_unique_report_keys": len(keys),
        "matched_identical": identical,
        "matched_changed": len(keys) - identical,
        "changed_field_frequency_top": changes.most_common(12),
        "samples": samples}


def compare(old_records, new_records):
    old = _counter(old_records)
    new = _counter(new_records)
    return {
        "old_rows": len(old_records), "new_rows": len(new_records),
        "exact_common_rows": sum((old & new).values()),
        "old_missing_from_new": sum((old - new).values()),
        "new_not_in_old": sum((new - old).values()),
        "old_columns": _columns(old_records),
        "new_columns": _columns(new_records),
        "report_key_differences": _field_differences(
            old_records, new_records)}


def diagnose(root, symbols, *, workspace=E.WORK, timeout_seconds=180,
             progress=print):
    extra = E._storage(Path(root))
    state = I._state(extra, workspace)
    prior = state["pending"]
    day = datetime.now(E.L.UTC8).date().isoformat()
    report = []
    with E.LIVE.exclusive_writer():
        for code in symbols:
            code = E.valid_code(code)
            entry = prior.get(code)
            if not entry or entry.get("reason") != "SOURCE_HISTORY_CONFLICT":
                raise ValueError("Not an existing source-history conflict: " + code)
            old_day = I._latest_snapshot_day(extra, code, "Capital")
            if old_day is None:
                raise ValueError("Missing immutable Capital baseline for " + code)
            baseline = E._financial_snapshot_rows(
                extra, code, "Capital", old_day)
            per_table = E._read_financial_isolated(
                code, "Capital", workspace, timeout_seconds=timeout_seconds,
                asof=day, progress=progress, cached_only=True,
                record_failure=False)
            batch_records, absent = I._worker_batch(
                [code], "cache", day, 120, workspace, timeout_seconds,
                progress=progress)
            if absent or code not in batch_records:
                raise ValueError("QMT nine-table cache missing Capital " + code)
            batched = batch_records[code]["Capital"]
            current_report = {
                "symbol": code, "baseline_asof": old_day,
                "pending_reason": entry.get("reason"),
                "baseline_vs_single_table": compare(baseline, per_table),
                "baseline_vs_nine_table": compare(baseline, batched),
                "single_table_vs_nine_table": compare(per_table, batched),
                "download_called": False, "parquet_modified": False,
                "cursor_modified": False}
            progress("QMT_CAPITAL_CONFLICT_DIAGNOSIS=" +
                     E.canonical_json(current_report))
            report.append(current_report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--symbols", default="000008.SZ,000001.SZ")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    symbols = args.symbols.split(",")
    if (not 1 <= len(symbols) <= 4 or
            len(symbols) != len(set(symbols)) or
            not 30 <= args.timeout_seconds <= 3600):
        parser.error("Provide 1..4 unique symbols and timeout 30..3600")
    diagnose(args.root, symbols, timeout_seconds=args.timeout_seconds)
    print("QMT_CAPITAL_READONLY_DIAGNOSIS_COMPLETE")


if __name__ == "__main__":
    main()
