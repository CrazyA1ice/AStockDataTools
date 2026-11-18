#!/usr/bin/env python3
"""READ-ONLY pilot policy verification for QMT Capital.m_quarter.

A policy is evidence, not authorization: no policy writer, CLI, or scheduled
auto-activation exists here. Never accept this module's JSON as proof that a
human approved a live repair. Callers must separately authorize the policy.
The default financial importer does NOT load or use policy files.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re

import qmt_extra_data as E
import qmt_capital_semantic_proof as P

FORMAT = "qmt_capital_explicit_record_allowance_v1"
FIELD = "m_quarter"
MAX_ALLOWED_REPORT_DATES = 256
HEX = re.compile(r"[0-9a-f]{64}\Z")
FILENAME = re.compile(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{16}\.parquet\Z")


def _business_sha(row):
    return hashlib.sha256(P._business(row).encode("utf-8")).hexdigest()


def _refuse(reason):
    raise ValueError("CAPITAL_POLICY_REFUSED " + reason)


def _raw(row):
    if not isinstance(row, dict) or FIELD not in row:
        _refuse("INVALID_CAPITAL_RAW_RECORD")
    return E.canonical_json({k: v for k, v in row.items() if k != "_index"})


def _snapshot_rows(extra, code, asof, filename):
    """Verify a referenced immutable file even when not the active version."""
    if (not isinstance(filename, str) or not FILENAME.fullmatch(filename)
            or not filename.startswith(asof + "-")):
        _refuse("INVALID_SNAPSHOT_FILENAME")
    path = (extra / "financial" / "Capital" / code /
            "snapshots" / filename)
    table = E._verify_financial_snapshot_file(extra, code, "Capital", asof, path)
    records = [json.loads(s) for s in table.column("payload_json").to_pylist()]
    if any(not isinstance(row, dict) for row in records):
        _refuse("INVALID_IMMUTABLE_PAYLOAD")
    return path, records


def validate_policy(extra, code, asof, policy, saved, current_rows):
    """Fail closed unless original snapshots and EVERY raw historical row agree.

    Exact, dated whitelisting means only the explicitly listed m_timetag values
    may differ. All other original fields and the other eight financial tables
    retain existing strict comparison. New report dates are NOT waived in P67.
    """
    extra = Path(extra).resolve()
    code = E.valid_code(code)
    try:
        date.fromisoformat(asof)
    except (ValueError, TypeError):
        _refuse("INVALID_CURRENT_ASOF")
    if not isinstance(policy, dict):
        _refuse("INVALID_POLICY_PAYLOAD")
    fields = ("format", "status", "field", "symbol", "root",
              "activation_asof", "baseline_asof",
              "baseline_snapshot", "baseline_snapshot_sha256",
              "candidate_snapshot", "candidate_snapshot_sha256",
              "allowed_records")
    if any(k not in policy for k in fields):
        _refuse("MISSING_POLICY_IDENTITY")
    if (policy["format"] != FORMAT or policy["status"] != "ACTIVE"
            or policy["field"] != FIELD or policy["symbol"] != code
            or policy["root"] != str(extra)):
        _refuse("IDENTITY_OR_STATUS_MISMATCH")
    activation = policy["activation_asof"]
    baseline = policy["baseline_asof"]
    if (not isinstance(activation, str) or
            not isinstance(baseline, str)):
        _refuse("INVALID_SNAPSHOT_DATES")
    try:
        date.fromisoformat(activation)
        date.fromisoformat(baseline)
    except ValueError:
        _refuse("INVALID_SNAPSHOT_DATES")
    if not baseline <= activation <= asof:
        _refuse("STALE_OR_FUTURE_ACTIVATION")
    old_path, old_rows = _snapshot_rows(
        extra, code, baseline, policy["baseline_snapshot"])
    new_path, candidate_rows = _snapshot_rows(
        extra, code, activation, policy["candidate_snapshot"])
    if any(not isinstance(policy[key], str) or not HEX.fullmatch(policy[key])
           for key in ("baseline_snapshot_sha256", "candidate_snapshot_sha256")):
        _refuse("INVALID_FILE_SHA256")
    if (E.L.hash_file(old_path) != policy["baseline_snapshot_sha256"]
            or E.L.hash_file(new_path) != policy["candidate_snapshot_sha256"]):
        _refuse("IMMUTABLE_SNAPSHOT_SHA256_CHANGED")
    if E._financial_snapshot_file(extra, code, "Capital", activation) != new_path:
        _refuse("APPROVED_CANDIDATE_NOT_ACTIVE")
    allowed = policy["allowed_records"]
    if (not isinstance(allowed, list) or
            not 1 <= len(allowed) <= MAX_ALLOWED_REPORT_DATES):
        _refuse("INVALID_ALLOWED_REPORT_DATE_COUNT")
    rules = {}
    for entry in allowed:
        if not isinstance(entry, dict) or set(entry) != {
                "report_key", "business_sha256", "approved_quarter",
                "allowed_historical_quarters"}:
            _refuse("INVALID_REPORT_RULE_SHAPE")
        key, digest = entry["report_key"], entry["business_sha256"]
        values = entry["allowed_historical_quarters"]
        current = entry["approved_quarter"]
        if (not isinstance(key, str) or not isinstance(digest, str)
                or not HEX.fullmatch(digest)
                or not isinstance(current, str)
                or not isinstance(values, list) or len(values) < 2
                or len(values) != len(set(values))
                or any(not isinstance(x, str) for x in values)
                or current not in values
                or key in rules):
            _refuse("INVALID_REPORT_RULE_VALUES")
        rules[key] = entry
    # Incorporate original immutable baseline, not only selected daily
    # history; an older same-asof snapshot may have been unpinned.
    if not isinstance(saved, Counter) or not isinstance(current_rows, list):
        _refuse("INVALID_RAW_HISTORIES")
    merged = saved | Counter(_raw(r) for r in old_rows)
    history = defaultdict(list)
    fresh = {}
    candidate = {}
    try:
        for raw, multiplicity in merged.items():
            if not isinstance(raw, str) or type(multiplicity) is not int or multiplicity != 1:
                _refuse("DUPLICATE_HISTORICAL_RAW_RECORD")
            row = json.loads(raw)
            history[P._key(row)].append(row)
        for row in candidate_rows:
            k = P._key(row)
            if k in candidate:
                _refuse("DUPLICATE_APPROVED_SNAPSHOT_KEY")
            candidate[k] = row
        for row in current_rows:
            k = P._key(row)
            if k in fresh:
                _refuse("DUPLICATE_CURRENT_REPORT_KEY")
            fresh[k] = row
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if str(exc).startswith("CAPITAL_POLICY_REFUSED "):
            raise
        _refuse("MALFORMED_HISTORY:" + type(exc).__name__)
    if set(history) != set(fresh) or set(candidate) != set(history):
        _refuse("ADDED_OR_REMOVED_REPORT_DATE_REQUIRES_REVIEW")
    if not set(rules).issubset(history):
        _refuse("APPROVED_REPORT_DATE_MISSING")
    changes = 0
    for k, current in fresh.items():
        past = history[k]
        accepted = candidate[k]
        if k in rules:
            rule = rules[k]
            if (P._business(current) != P._business(accepted)
                    or _business_sha(current) != rule["business_sha256"]
                    or E.canonical_json(current[FIELD]) != rule["approved_quarter"]
                    or E.canonical_json(accepted[FIELD]) != rule["approved_quarter"]):
                _refuse("APPROVED_BUSINESS_OR_QUARTER_DRIFT")
            observed_quarters = set()
            for old in past:
                if FIELD not in old or P._business(old) != P._business(current):
                    _refuse("UNAPPROVED_BUSINESS_HISTORY_VARIANT")
                quarter = E.canonical_json(old[FIELD])
                if quarter not in rule["allowed_historical_quarters"]:
                    _refuse("UNAPPROVED_HISTORICAL_VARIANT")
                observed_quarters.add(quarter)
                changes += (quarter != rule["approved_quarter"])
            if observed_quarters != set(rule["allowed_historical_quarters"]):
                _refuse("EXTRA_OR_MISSING_APPROVED_QUARTER_VARIANT")
        else:
            if (len(past) != 1 or _raw(past[0]) != _raw(current)
                    or _raw(accepted) != _raw(current)):
                _refuse("UNAPPROVED_REPORT_CHANGED")
    if not changes:
        _refuse("NO_APPROVED_EXCEPTION_PRESENT")
    return {
        "status": "SCOPED_POLICY_READONLY_MATCH",
        "symbol": code,
        "report_dates": len(history),
        "allowed_report_dates": len(rules),
        "approved_historical_quarter_differences": changes,
        "other_fields_changed": False,
        "approved_source_version": policy["candidate_snapshot"],
        "policy_is_apply_authorization": False,
    }


def read_policy(extra, code, workspace):
    """Read optional policy file; missing is NOT an error or an approval."""
    code = E.valid_code(code)
    path = Path(workspace) / "capital-approved-policies" / (code + ".json")
    E._path_check(path)
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        _refuse("POLICY_PATH_UNSAFE")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError) as exc:
        _refuse("POLICY_CANNOT_BE_READ:" + type(exc).__name__)
    if not isinstance(doc, dict):
        _refuse("POLICY_DOCUMENT_NOT_MAPPING")
    return doc
