#!/usr/bin/env python3
"""SYNTHETIC-ONLY Capital recovery transaction and crash-compensation lab.

This module has NO CLI, cannot operate on the production stock root, and
cannot grant approval to the real scheduled importer.  Its only purpose is to
prove journal ordering and state restoration using isolated temporary Parquet
fixtures BEFORE a separately authorized production implementation exists.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I
import qmt_capital_nine_table_repair_preview as N
import qmt_capital_conflict_census_readonly as C

FORMAT = "synthetic_capital_recovery_transaction_v1"
MARKER = "SYNTHETIC_ONLY_CAPITAL_PILOT_V1\n"
TARGET = "002237.SZ"
PHASES = ("PREPARED", "SNAPSHOT_COMMITTED", "POLICY_RECORDED",
          "LEDGER_RELEASED", "COMPLETE", "COMPENSATED")
FAULTS = ("AFTER_PREPARED", "AFTER_SNAPSHOT", "AFTER_POLICY",
          "AFTER_LEDGER")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_synthetic(extra, workspace):
    extra = Path(extra).resolve()
    workspace = Path(workspace).resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if (workspace == temporary or not workspace.is_relative_to(temporary)
            or not extra.is_relative_to(temporary)
            or workspace == extra
            or not workspace.is_dir()
            or not (workspace / "synthetic-only.marker").is_file()
            or (workspace / "synthetic-only.marker").read_text(
                encoding="utf-8") != MARKER):
        raise ValueError("SYNTHETIC_TEMP_ROOT_AND_EXACT_MARKER_REQUIRED")
    E._path_check(extra)
    E._path_check(workspace)
    return extra, workspace


def _paths(workspace):
    return (workspace / I.STATE_FILE,
            workspace / "capital-recovery-journal" / (TARGET + ".json"),
            workspace / "capital-recovery-policy" / (TARGET + ".json"))


def _load_journal(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError("Missing synthetic transaction journal")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if (obj.get("format") != FORMAT or obj.get("symbol") != TARGET
            or obj.get("phase") not in PHASES
            or not isinstance(obj.get("pending_before"), dict)):
        raise ValueError("Malformed recovery journal")
    return obj


def _persist(path, value):
    E._path_check(path)
    E.S._save(path, value)


def synthetic_run(extra, workspace, *, code, asof, source, fault=None):
    """Persist a synthetic transaction with explicit fault injection points.

    No production approval is created: policy files are TEST-ONLY fixtures.
    The caller is responsible for synthetic fixture setup; all nine tables
    must match the strict preview before any write or pending release.
    """
    extra, workspace = _validate_synthetic(extra, workspace)
    if code != TARGET or fault not in (None, *FAULTS):
        raise ValueError("Pilot permits only 002237.SZ synthetic fixtures")
    date.fromisoformat(asof)
    ledger, journal_path, policy_path = _paths(workspace)
    with E.LIVE.exclusive_writer():
        if journal_path.exists() or policy_path.exists():
            raise ValueError("Existing transaction or policy requires compensation")
        state = I._state(extra, workspace)
        entry = state["pending"].get(code)
        if not (isinstance(entry, dict)
                and entry.get("reason") == "SOURCE_HISTORY_CONFLICT"
                and C.conflict_table(entry) == "Capital"):
            raise ValueError("Pilot target is not quarantined for Capital")
        frozen_state = _sha(ledger)
        proof = N.plan_symbol(extra, code, asof, source)
        if proof["status"] != "ELIGIBLE_FOR_MANUAL_PILOT_PREVIEW":
            raise ValueError("NINE_TABLE_SOURCE_PROOF_REJECTED " +
                             E.canonical_json(proof["blockers"]))
        # Further narrow the pilot: other eight tables must have zero delta.
        if any(proof["table_checks"][name]["status"] != "UNCHANGED"
               for name in E.FIN_TABLES if name != "Capital"):
            raise ValueError("OTHER_FINANCIAL_TABLE_NOT_IDENTICAL")
        planned, staged = I._plan_symbol(
            extra, code, asof, source, capital_approved_symbol=code)
        if planned["Capital"]["action"] != "CREATE_VERSION":
            raise ValueError("REHEARSAL_EXPECTS_FRESH_CAPITAL_VERSION")
        if set(staged) != {"Capital"}:
            raise ValueError("UNEXPECTED_STAGED_NON_CAPITAL_TABLE")
        original_same_day = E._financial_snapshot_file(
            extra, code, "Capital", asof)
        prior_filename = original_same_day.name if original_same_day else None
        prior_hash = E.L.hash_file(original_same_day) if original_same_day else None
        journal = {
            "format": FORMAT, "symbol": code, "asof": asof,
            "phase": "PREPARED", "pending_before": deepcopy(entry),
            "ledger_before_sha256": frozen_state,
            "historical_same_day_filename": prior_filename,
            "historical_same_day_sha256": prior_hash,
            "preflight_digest": proof["read_only_preflight_digest"],
            "candidate_filename": proof["proposed_capital_immutable_filename"],
            "scope": "TEST_ONLY_NOT_AN_ACTIVE_IMPORTER_ALLOWANCE"}
        _persist(journal_path, journal)
        if fault == "AFTER_PREPARED":
            raise RuntimeError("INJECTED_AFTER_PREPARED")
        # Using real Parquet write helpers, but ONLY under OS TEMP.
        I._commit_symbol(extra, workspace, code, asof, source,
                         capital_approved_symbol=code)
        observed = E._financial_snapshot_file(extra, code, "Capital", asof)
        if observed is None or observed.name != journal["candidate_filename"]:
            raise ValueError("Synthetic immutable candidate hash mismatch")
        journal["candidate_parquet_sha256"] = E.L.hash_file(observed)
        journal["phase"] = "SNAPSHOT_COMMITTED"
        _persist(journal_path, journal)
        if fault == "AFTER_SNAPSHOT":
            raise RuntimeError("INJECTED_AFTER_SNAPSHOT")
        policy = {
            "format": FORMAT, "symbol": code, "field": "m_quarter",
            "status": "SYNTHETIC_APPROVAL_EVIDENCE_ONLY",
            "preflight_digest": journal["preflight_digest"],
            "candidate_filename": observed.name,
            "candidate_parquet_sha256": journal["candidate_parquet_sha256"],
            "scope": journal["scope"]}
        _persist(policy_path, policy)
        journal["phase"] = "POLICY_RECORDED"
        _persist(journal_path, journal)
        if fault == "AFTER_POLICY":
            raise RuntimeError("INJECTED_AFTER_POLICY")
        latest = I._state(extra, workspace)
        if _sha(ledger) != frozen_state or latest["pending"].get(code) != entry:
            raise ValueError("PENDING_LEDGER_DRIFT_BEFORE_RELEASE")
        latest["pending"].pop(code)
        I._save_state(workspace, latest)
        if code in I._state(extra, workspace)["pending"]:
            raise ValueError("Pending release readback failed")
        if fault == "AFTER_LEDGER":
            raise RuntimeError("INJECTED_AFTER_LEDGER")
        journal["phase"] = "LEDGER_RELEASED"
        _persist(journal_path, journal)
        journal["phase"] = "COMPLETE"
        _persist(journal_path, journal)
        return {"status": "SYNTHETIC_COMPLETED_NOT_LIVE_AUTHORIZED",
                "original_parquet_retained": True,
                "applies_to_production_importer": False,
                "phase": journal["phase"]}


def synthetic_compensate(extra, workspace):
    """Restore pending and previous same-day pin; retain any immutable files.

    For a new observation day without a previous version, immutable candidate
    is intentionally NOT deleted; such a run cannot claim full physical
    rollback. Pending restoration + revoked policy keep data quarantined.
    """
    extra, workspace = _validate_synthetic(extra, workspace)
    ledger, journal_path, policy_path = _paths(workspace)
    with E.LIVE.exclusive_writer():
        journal = _load_journal(journal_path)
        if journal["phase"] == "COMPENSATED":
            return {"status": "ALREADY_COMPENSATED", "pending_restored": True}
        state = I._state(extra, workspace)
        old = journal["pending_before"]
        current = state["pending"].get(TARGET)
        if current is not None and current != old:
            raise ValueError("PENDING_ENTRY_DRIFT_REFUSE_COMPENSATION")
        if current is None:
            state["pending"][TARGET] = deepcopy(old)
            I._save_state(workspace, state)
        previous = journal["historical_same_day_filename"]
        old_pin_restored = False
        if previous is not None:
            path = (extra / "financial" / "Capital" / TARGET /
                    "snapshots" / previous)
            if (not path.is_file() or
                    E.L.hash_file(path) != journal["historical_same_day_sha256"]):
                raise ValueError("ORIGINAL_SAME_DAY_SNAPSHOT_CORRUPTED")
            E._pin_financial_snapshot(
                extra, TARGET, "Capital", journal["asof"], path)
            old_pin_restored = True
        if policy_path.exists():
            if not policy_path.is_file() or policy_path.is_symlink():
                raise ValueError("Invalid synthetic policy file")
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            if policy.get("format") != FORMAT or policy.get("symbol") != TARGET:
                raise ValueError("Unrecognized synthetic policy")
            policy["status"] = "SYNTHETIC_REVOKED"
            _persist(policy_path, policy)
        journal["phase"] = "COMPENSATED"
        journal["old_same_day_pin_restored"] = old_pin_restored
        journal["candidate_immutable_file_retained"] = bool(
            journal.get("candidate_parquet_sha256"))
        _persist(journal_path, journal)
        if I._state(extra, workspace)["pending"].get(TARGET) != old:
            raise ValueError("Pending compensation readback failed")
        return {"status": "COMPENSATED_PENDING_QUARANTINED",
                "pending_restored": True,
                "old_same_day_pin_restored": old_pin_restored,
                "candidate_immutable_file_retained":
                    journal["candidate_immutable_file_retained"],
                "physical_rollback_claimed": False,
                "applies_to_production_importer": False}
