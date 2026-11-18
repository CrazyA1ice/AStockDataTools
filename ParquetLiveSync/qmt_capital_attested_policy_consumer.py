#!/usr/bin/env python3
"""P70: READ-ONLY attestation of a completed P69 one-stock transaction.

This only returns a narrowly approved Capital policy when both the durable
COMPLETE journal and exact policy, baseline, active candidate, immutable ledger
backup and private pending ledger have been verified. Merely placing an ACTIVE
policy file on disk is NEVER enough.

Not wired to the unattended financial importer or scheduler; no auto release,
no default waiver, no QMT calls, and no real-data write side effects.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I
import qmt_capital_scoped_policy_reader as POL
import qmt_capital_one_stock_transaction as TX

SYMBOL = TX.SYMBOL
HEX = re.compile(r"[0-9a-f]{64}\Z")
FILENAME = re.compile(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{16}\.parquet\Z")


def _refuse(message):
    raise ValueError("P70_ATTESTATION_REFUSED " + message)


def _sha_field(doc, name):
    value = doc.get(name)
    if not isinstance(value, str) or not HEX.fullmatch(value):
        _refuse("INVALID_SHA_" + name)
    return value


def _json_file(path):
    E._path_check(path)
    if not path.is_file() or path.is_symlink():
        _refuse("MISSING_OR_UNSAFE_FILE_" + path.name)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError):
        _refuse("UNREADABLE_JSON_" + path.name)
    if not isinstance(doc, dict):
        _refuse("INVALID_JSON_MAPPING")
    return doc


def _pinned_snapshot(extra, asof, filename, digest):
    if (not isinstance(asof, str)
            or not isinstance(filename, str)
            or not FILENAME.fullmatch(filename)
            or not filename.startswith(asof + "-")):
        _refuse("INVALID_IMMUTABLE_FILENAME")
    path = (extra / "financial" / "Capital" / SYMBOL /
            "snapshots" / filename)
    if TX.sha(TX._safe_file(path)) != digest:
        _refuse("IMMUTABLE_SNAPSHOT_SHA_MISMATCH")
    E._verify_financial_snapshot_file(extra, SYMBOL, "Capital", asof, path)
    return path


def read_completed_policy(extra, workspace, code):
    """Return an attested ACTIVE policy or None when absolutely none exists.

    Partial or malformed P69 evidence always raises; no silent fallback to an
    unverified policy. Only the exact P69 pilot stock is in scope.
    """
    if code != SYMBOL:
        return None
    extra = Path(extra).resolve()
    workspace = Path(workspace).resolve()
    ledger, journal_path, policy_path = TX.paths(workspace)
    E._path_check(extra)
    E._path_check(workspace)
    if not journal_path.exists() and not policy_path.exists():
        return None
    journal = _json_file(journal_path)
    policy = _json_file(policy_path)
    if (journal.get("format") != TX.FORMAT
            or journal.get("symbol") != SYMBOL
            or journal.get("phase") != "COMPLETE"
            or journal.get("policy_path") != str(policy_path)
            or journal.get("original_parquet_retained") is not True):
        _refuse("NOT_A_COMPLETED_EXACT_STOCK_P69_TRANSACTION")
    pre_sha = _sha_field(journal, "ledger_before_sha256")
    backup_sha = _sha_field(journal, "ledger_backup_sha256")
    _sha_field(journal, "ledger_after_sha256")
    policy_sha = _sha_field(journal, "policy_sha256")
    candidate_sha = _sha_field(journal, "candidate_sha256")
    baseline_sha = _sha_field(journal, "baseline_sha256")
    _sha_field(journal, "preflight_digest")
    expected_backup = workspace / "backups" / (
        "capital-ledger-" + SYMBOL + "-" + pre_sha + ".json")
    if (pre_sha != backup_sha
            or journal.get("ledger_backup_path") != str(expected_backup)
            or TX.sha(TX._safe_file(expected_backup)) != pre_sha):
        _refuse("ORIGINAL_LEDGER_BACKUP_NOT_ANCHORED")
    original = _json_file(expected_backup)
    if (original.get("format") != I.FORMAT
            or original.get("root") != str(extra)
            or not isinstance(original.get("pending"), dict)
            or original["pending"].get(SYMBOL) != journal.get("pending_before")
            or not isinstance(journal.get("pending_before"), dict)
            or journal["pending_before"].get("reason") != "SOURCE_HISTORY_CONFLICT"):
        _refuse("ORIGINAL_LEDGER_PENDING_NOT_PROVEN")
    actual = I._state(extra, workspace)
    if SYMBOL in actual["pending"]:
        _refuse("STOCK_STILL_QUARANTINED")
    if TX.sha(TX._safe_file(policy_path)) != policy_sha:
        _refuse("POLICY_SHA_MISMATCH")
    if (policy.get("format") != POL.FORMAT
            or policy.get("status") != "ACTIVE"
            or policy.get("root") != str(extra)
            or policy.get("symbol") != SYMBOL
            or policy.get("field") != "m_quarter"
            or policy.get("activation_asof") != journal.get("asof")
            or policy.get("baseline_asof") != journal.get("baseline_asof")
            or policy.get("baseline_snapshot") != journal.get("baseline_filename")
            or policy.get("baseline_snapshot_sha256") != baseline_sha
            or policy.get("candidate_snapshot") != journal.get("candidate_filename")
            or policy.get("candidate_snapshot_sha256") != candidate_sha):
        _refuse("POLICY_AND_TRANSACTION_IDENTITY_MISMATCH")
    old = _pinned_snapshot(extra, journal.get("baseline_asof"),
                           journal.get("baseline_filename"), baseline_sha)
    newest = _pinned_snapshot(extra, journal.get("asof"),
                              journal.get("candidate_filename"), candidate_sha)
    if E._financial_snapshot_file(extra, SYMBOL, "Capital", journal["asof"]) != newest:
        _refuse("APPROVED_CANDIDATE_PIN_CHANGED")
    if old == newest:
        _refuse("BASELINE_EQUALS_APPROVED_CANDIDATE")
    return policy


def verify_next_day_without_writes(extra, workspace, code, asof, nine_tables):
    """Full nine-table read-only P67 comparison; not apply authorization."""
    policy = read_completed_policy(extra, workspace, code)
    if policy is None:
        _refuse("NO_COMPLETED_APPROVAL")
    plan, staged = I._plan_symbol(
        Path(extra), code, asof, nine_tables, capital_policy=policy)
    return {
        "status": "ATTESTED_P69_NEXT_DAY_READONLY_CHECK",
        "symbol": code, "asof": asof,
        "capital_action": plan["Capital"]["action"],
        "capital_exception": plan["Capital"].get(
            "scoped_m_quarter_semantic_exception"),
        "staged_tables": sorted(staged),
        "applied": False,
        "unattended_waiver_enabled": False,
    }
