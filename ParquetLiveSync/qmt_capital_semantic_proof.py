#!/usr/bin/env python3
"""Conservative, WRITE-DISABLED proof for suspected QMT Capital.m_quarter noise.

The caller supplies the exact RAW historical union counter returned by
qmt_extra_financial_cache_import._prior_rows(), plus the latest QMT cache rows.
This verifies all previously selected snapshots, not merely the newest.
It must NOT remove a pending exception, change comparison policy, or publish
a new financial Parquet. A candidate result is evidence only.
"""
from __future__ import annotations

from collections import Counter
import json

import qmt_extra_data as E

FORMAT = "capital_mquarter_full_historical_union_proof_v1"
MQUARTER = "m_quarter"
KEY = "m_timetag"


def _report(status, old_keys, new_keys, versions, *, changes=0, note=""):
    return {
        "format": FORMAT,
        "classification": status,
        "history_report_dates": old_keys,
        "fresh_report_dates": new_keys,
        "historical_raw_variants": versions,
        "m_quarter_differences": changes,
        "only_unstable_field_candidate": status == "M_QUARTER_ONLY_CANDIDATE",
        "ready_to_commit": False,
        "old_parquet_modified": False,
        "pending_modified": False,
        "reason": note
    }


def _key(row):
    if not isinstance(row, dict):
        raise ValueError("Capital source record not a mapping")
    if KEY not in row or row[KEY] is None:
        raise ValueError("Capital source row missing m_timetag")
    value = row[KEY]
    if isinstance(value, (dict, list, bool)) or str(value).strip() in ("", "0"):
        raise ValueError("Capital report date key unrecognized")
    return E.canonical_json(value)


def _business(row):
    # Exclude precisely one *suspected* provider-private field. All economic
    # quantities, dates and other metadata continue to compare byte-exactly.
    return E.canonical_json({
        k: v for k, v in row.items() if k not in ("_index", MQUARTER)
    })


def prove_historical_union(saved_raw: Counter, current_rows: list):
    if not isinstance(saved_raw, Counter) or not isinstance(current_rows, list):
        raise ValueError("Need verified prior Counter and latest raw row list")
    if not saved_raw:
        return _report("BASELINE_MISSING", 0, len(current_rows), 0)
    # Historical Counter is a *union of snapshots*: multiple RAW variants
    # for a single report date are normal when QMT rewrites m_quarter. Count
    # distinct report dates, but reject two historical economic records with
    # different business content for the same report key.
    historical = {}
    variants = sum(saved_raw.values())
    try:
        for record_json, count in saved_raw.items():
            if not isinstance(record_json, str) or not isinstance(count, int) or count != 1:
                return _report("HISTORICAL_DUPLICATE_RAW_RECORD", 0, len(current_rows), variants)
            row = json.loads(record_json)
            key = _key(row)
            if MQUARTER not in row:
                return _report("M_QUARTER_FIELD_MISSING", 0, len(current_rows), variants,
                               note="Original Capital field layout not equivalent")
            historical.setdefault(key, []).append(row)
        fresh = {}
        for row in current_rows:
            key = _key(row)
            if MQUARTER not in row:
                return _report("M_QUARTER_FIELD_MISSING", len(historical),
                               len(current_rows), variants,
                               note="Fresh Capital field layout not equivalent")
            if key in fresh:
                return _report("FRESH_DUPLICATE_REPORT_KEY", len(historical),
                               len(current_rows), variants)
            fresh[key] = row
        old_keys = set(historical)
        new_keys = set(fresh)
        if old_keys != new_keys:
            return _report("REPORT_KEYS_ADDED_OR_REMOVED", len(old_keys),
                           len(new_keys), variants,
                           note=f"old_missing={len(old_keys-new_keys)} new={len(new_keys-old_keys)}")
        changed = 0
        for key in sorted(old_keys):
            rows = historical[key]
            stable = {_business(row) for row in rows}
            if len(stable) != 1:
                return _report("HISTORICAL_BUSINESS_FIELD_REVISION",
                               len(old_keys), len(new_keys), variants)
            if _business(fresh[key]) not in stable:
                return _report("BUSINESS_OR_DATE_FIELD_CHANGED",
                               len(old_keys), len(new_keys), variants)
            changed += sum(
                E.canonical_json(row[MQUARTER]) !=
                E.canonical_json(fresh[key][MQUARTER])
                for row in rows
            )
        return _report(
            "M_QUARTER_ONLY_CANDIDATE" if changed else "NO_CHANGE",
            len(old_keys), len(new_keys), variants, changes=changed,
            note=("All historical selected business fields, m_timetag keys, "
                  "record layouts and fresh values match; raw historical "
                  "observations stay immutable. Manual multi-market proof "
                  "still required before any production repair." if changed
                  else "All historical selected raw variants match current"))
    except (ValueError, TypeError, OverflowError, KeyError, json.JSONDecodeError) as exc:
        return _report("UNVERIFIED_MALFORMED_OR_UNKEYED_RECORD",
                       len(historical), len(current_rows), variants,
                       note=type(exc).__name__ + ": " + str(exc)[:140])
