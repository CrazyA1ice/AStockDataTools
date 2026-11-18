#!/usr/bin/env python3
"""P69: one-stock QMT Capital recovery, fail-closed and explicitly approved.

Never invoked by scheduled jobs. The CLI defaults to READ-ONLY preview.
A real apply requires the *same-day* exact stock, 64-byte ledger and nine-table
preflight digests, explicit approval phrase, canonical checkout and the global
writer lock. Historical immutable snapshots are NEVER deleted or overwritten.
An unfinished journal blocks replay; quarantine compensation is manual only.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I
import qmt_capital_nine_table_repair_preview as N
import qmt_capital_conflict_census_readonly as C
import qmt_capital_scoped_policy_reader as POL
import qmt_capital_semantic_proof as SEM

FORMAT = "qmt_capital_one_stock_transaction_v1"
SYMBOL = "002237.SZ"
APPROVAL = "AUTHORIZE_CAPITAL_ONLY_002237.SZ"
HEX = re.compile(r"[0-9a-f]{64}\Z")
JOURNAL = "capital-recovery-journal"
PHASES = ("PREPARED", "SNAPSHOT_COMMITTED", "POLICY_RECORDED",
          "LEDGER_RELEASED", "COMPLETE", "COMPENSATED")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paths(workspace):
    workspace = Path(workspace)
    return (workspace / I.STATE_FILE,
            workspace / JOURNAL / (SYMBOL + ".json"),
            workspace / "capital-approved-policies" / (SYMBOL + ".json"))


def _safe_file(path):
    E._path_check(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("P69_MISSING_OR_UNSAFE_EVIDENCE_FILE " + str(path))
    return path


def _save(path, doc):
    E._path_check(path)
    E.S._save(path, doc)


def _assert_pending(state):
    item = state["pending"].get(SYMBOL)
    if (not isinstance(item, dict) or
            item.get("reason") != "SOURCE_HISTORY_CONFLICT" or
            C.conflict_table(item) != "Capital"):
        raise ValueError("P69_TARGET_MUST_REMAIN_CAPITAL_PENDING")
    return item


def _allowed_records(saved, fresh):
    """Generate only exact report-date exceptions proved by nine-table guard."""
    historical = defaultdict(list)
    current = {}
    for raw, count in saved.items():
        if type(count) is not int or count != 1:
            raise ValueError("P69_DUPLICATE_HISTORY")
        row = json.loads(raw)
        historical[SEM._key(row)].append(row)
    for row in fresh:
        k = SEM._key(row)
        if k in current:
            raise ValueError("P69_DUPLICATE_FRESH_DATE")
        current[k] = row
    if set(historical) != set(current):
        raise ValueError("P69_NEW_OR_REMOVED_REPORT_DATES")
    allowed = []
    for k in sorted(current):
        now = current[k]
        old = historical[k]
        if any(SEM._business(x) != SEM._business(now) for x in old):
            raise ValueError("P69_BUSINESS_VARIANT")
        approved = E.canonical_json(now["m_quarter"])
        historical_values = {E.canonical_json(x["m_quarter"]) for x in old}
        if historical_values != {approved}:
            historical_values.add(approved)
            allowed.append({
                "report_key": k,
                "business_sha256": POL._business_sha(now),
                "approved_quarter": approved,
                "allowed_historical_quarters": sorted(historical_values)})
    if not 1 <= len(allowed) <= POL.MAX_ALLOWED_REPORT_DATES:
        raise ValueError("P69_NO_NARROW_M_QUARTER_DIFFERENCE")
    return allowed


def _preflight(extra, workspace, source, asof):
    ledger, journal_path, policy_path = paths(workspace)
    if journal_path.exists() or policy_path.exists():
        raise ValueError("P69_EXISTING_JOURNAL_OR_POLICY_REQUIRES_REVIEW")
    ledger_sha = sha(_safe_file(ledger))
    state = I._state(extra, workspace)
    pending = deepcopy(_assert_pending(state))
    proof = N.plan_symbol(extra, SYMBOL, asof, source)
    if proof["status"] != "ELIGIBLE_FOR_MANUAL_PILOT_PREVIEW":
        raise ValueError("P69_NINE_TABLE_PREVIEW_REFUSED " +
                         E.canonical_json(proof["blockers"]))
    if (any(proof["table_checks"][t]["status"] != "UNCHANGED"
            for t in E.FIN_TABLES if t != "Capital") or
            proof["table_checks"]["Capital"]["changed_m_quarter_rows"] < 1):
        raise ValueError("P69_OTHER_TABLES_NOT_EXACT")
    planned, staged = I._plan_symbol(
        extra, SYMBOL, asof, source, capital_approved_symbol=SYMBOL)
    if (set(staged) != {"Capital"} or
            planned["Capital"]["action"] != "CREATE_VERSION"):
        raise ValueError("P69_ONLY_ONE_NEW_CAPITAL_SNAPSHOT_ALLOWED")
    old_asof, saved = I._prior_rows(extra, SYMBOL, "Capital")
    if old_asof is None or saved is None or old_asof >= asof:
        raise ValueError("P69_REQUIRES_PRIOR_DAY_ORIGINAL_BASELINE")
    baseline = E._financial_snapshot_file(extra, SYMBOL, "Capital", old_asof)
    E._verify_financial_snapshot_file(extra, SYMBOL, "Capital", old_asof,
                                      _safe_file(baseline))
    if E._financial_snapshot_file(extra, SYMBOL, "Capital", asof) is not None:
        raise ValueError("P69_CURRENT_DAY_CAPITAL_ALREADY_EXISTS")
    rules = _allowed_records(saved, source["Capital"])
    return {
        "format": FORMAT, "status": "READY_FOR_EXPLICIT_ONE_STOCK_APPROVAL",
        "symbol": SYMBOL, "asof": asof,
        "ledger_sha256": ledger_sha,
        "nine_table_preflight_sha256": proof["read_only_preflight_digest"],
        "candidate_filename": proof["proposed_capital_immutable_filename"],
        "baseline_asof": old_asof, "baseline_filename": baseline.name,
        "baseline_sha256": sha(baseline),
        "allowed_report_dates": len(rules),
        "changed_historical_rows":
            proof["table_checks"]["Capital"]["changed_m_quarter_rows"],
        "original_snapshots_retained": True,
        "pending_not_modified_by_preview": True,
        "_rules": rules, "_saved": saved, "_pending": pending,
    }


def _policy(extra, candidate, plan):
    return {
        "format": POL.FORMAT, "status": "ACTIVE", "field": "m_quarter",
        "symbol": SYMBOL, "root": str(extra.resolve()),
        "activation_asof": plan["asof"], "baseline_asof": plan["baseline_asof"],
        "baseline_snapshot": plan["baseline_filename"],
        "baseline_snapshot_sha256": plan["baseline_sha256"],
        "candidate_snapshot": candidate.name,
        "candidate_snapshot_sha256": sha(candidate),
        "allowed_records": plan["_rules"],
    }


def _receipt(plan, applied=False):
    return {k: v for k, v in plan.items() if not k.startswith("_")} | {
        "mode": "APPLIED_WITH_EXPLICIT_APPROVAL" if applied else "READ_ONLY",
        "scheduled_finance_unblocked": False,
        "global_mass_conflict_guard_modified": False,
    }


def _run_locked(extra, workspace, source, asof, *,
                approval=None, expected_ledger=None, expected_proof=None):
    """Requires caller holding E.LIVE.exclusive_writer() throughout."""
    ledger, journal_path, policy_path = paths(workspace)
    plan = _preflight(extra, workspace, source, asof)
    if approval is None:
        return _receipt(plan)
    if (approval != APPROVAL or not isinstance(expected_ledger, str)
            or not HEX.fullmatch(expected_ledger)
            or not isinstance(expected_proof, str)
            or not HEX.fullmatch(expected_proof)
            or plan["ledger_sha256"] != expected_ledger
            or plan["nine_table_preflight_sha256"] != expected_proof):
        raise ValueError("P69_EXPLICIT_APPROVAL_OR_PREVIEW_SHA_MISMATCH")
    if datetime.now(E.L.UTC8).date().isoformat() != asof:
        raise ValueError("P69_ASOF_NOT_TODAY_REPREVIEW_REQUIRED")
    journal = {
        "format": FORMAT, "symbol": SYMBOL, "asof": asof,
        "phase": "PREPARED", "ledger_before_sha256": expected_ledger,
        "pending_before": deepcopy(plan["_pending"]),
        "preflight_digest": expected_proof,
        "baseline_asof": plan["baseline_asof"],
        "baseline_filename": plan["baseline_filename"],
        "baseline_sha256": plan["baseline_sha256"],
        "candidate_filename": plan["candidate_filename"],
        "policy_path": str(policy_path),
        "original_parquet_retained": True,
        "do_not_retry_without_recovery": True,
    }
    # Preserve exact ledger bytes before even the PREPARED journal.
    # Backup filename is bound to its CAS digest and cannot be overwritten.
    backup = Path(workspace) / "backups" / (
        "capital-ledger-" + SYMBOL + "-" + expected_ledger + ".json")
    E._path_check(backup)
    if backup.exists():
        if not backup.is_file() or sha(backup) != expected_ledger:
            raise ValueError("P69_LEDGER_BACKUP_DRIFT")
    else:
        backup.parent.mkdir(parents=True, exist_ok=True)
        with backup.open("xb") as stream:
            stream.write(ledger.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        if sha(backup) != expected_ledger:
            raise ValueError("P69_LEDGER_BACKUP_MISMATCH")
    journal["ledger_backup_path"] = str(backup)
    journal["ledger_backup_sha256"] = sha(backup)
    # Durable PREPARED before any candidate snapshot or pending mutation.
    _save(journal_path, journal)
    group = "financial/Capital/" + SYMBOL
    table = E.snapshot_table(asof, SYMBOL, "Capital", source["Capital"])
    candidate = E._snapshot_path(extra, group, asof, table)
    if candidate.name != plan["candidate_filename"]:
        raise ValueError("P69_CANDIDATE_FINGERPRINT_CHANGED")
    E._snapshot_write(extra, group, asof, table, workspace=workspace)
    E._verify_financial_snapshot_file(extra, SYMBOL, "Capital", asof, candidate)
    E._pin_financial_snapshot(extra, SYMBOL, "Capital", asof, candidate)
    journal["candidate_sha256"] = sha(candidate)
    journal["phase"] = "SNAPSHOT_COMMITTED"
    _save(journal_path, journal)
    policy = _policy(extra, candidate, plan)
    POL.validate_policy(extra, SYMBOL, asof, policy, plan["_saved"],
                        source["Capital"])
    _save(policy_path, policy)
    if POL.read_policy(extra, SYMBOL, workspace) != policy:
        raise ValueError("P69_POLICY_READBACK_CHANGED")
    journal["policy_sha256"] = sha(policy_path)
    journal["phase"] = "POLICY_RECORDED"
    _save(journal_path, journal)
    if sha(ledger) != expected_ledger:
        raise ValueError("P69_LEDGER_CAS_DRIFT")
    state = I._state(extra, workspace)
    if state["pending"].get(SYMBOL) != plan["_pending"]:
        raise ValueError("P69_PENDING_ENTRY_DRIFT")
    state["pending"].pop(SYMBOL)
    I._save_state(workspace, state)
    if SYMBOL in I._state(extra, workspace)["pending"]:
        raise ValueError("P69_LEDGER_RELEASE_READBACK_FAILED")
    journal["ledger_after_sha256"] = sha(ledger)
    journal["phase"] = "LEDGER_RELEASED"
    _save(journal_path, journal)
    journal["phase"] = "COMPLETE"
    _save(journal_path, journal)
    return {**_receipt(plan, applied=True),
            "status": "ONE_STOCK_APPLIED_PENDING_RELEASED",
            "candidate_sha256": journal["candidate_sha256"],
            "policy_sha256": journal["policy_sha256"],
            "journal_phase": journal["phase"],
            "pending_released": True,
            "original_parquet_retained": True}


def _quarantine_compensate_locked(extra, workspace):
    """Never remove candidate files; restore quarantine + revoke scoped policy.

    New-date candidate remains as an immutable observation. This is NOT a
    physical rollback and requires manual review before any future attempt.
    """
    ledger, journal_path, policy_path = paths(workspace)
    doc = json.loads(_safe_file(journal_path).read_text(encoding="utf-8"))
    if (doc.get("format") != FORMAT or doc.get("symbol") != SYMBOL
            or doc.get("phase") not in PHASES
            or not isinstance(doc.get("pending_before"), dict)):
        raise ValueError("P69_UNKNOWN_JOURNAL")
    if doc["phase"] == "COMPLETE":
        raise ValueError("P69_COMPLETE_NEEDS_SEPARATE_REVERSE_APPROVAL")
    if doc["phase"] == "COMPENSATED":
        return {"status": "ALREADY_COMPENSATED"}
    state = I._state(extra, workspace)
    observed = state["pending"].get(SYMBOL)
    if observed is not None and observed != doc["pending_before"]:
        raise ValueError("P69_PENDING_DRIFT_COMPENSATION_REFUSED")
    if policy_path.exists():
        policy = json.loads(_safe_file(policy_path).read_text(encoding="utf-8"))
        if (policy.get("format") != POL.FORMAT or
                policy.get("symbol") != SYMBOL or
                policy.get("activation_asof") != doc["asof"]):
            raise ValueError("P69_UNKNOWN_POLICY_COMPENSATION_REFUSED")
        policy["status"] = "REVOKED"
        _save(policy_path, policy)
    if observed is None:
        state["pending"][SYMBOL] = deepcopy(doc["pending_before"])
        I._save_state(workspace, state)
    journal = dict(doc, phase="COMPENSATED", physical_rollback_claimed=False,
                   pending_restored=True, candidate_immutable_retained=True)
    _save(journal_path, journal)
    return {"status": "COMPENSATED_QUARANTINED_NO_PHYSICAL_ROLLBACK",
            "pending_restored": True,
            "candidate_immutable_retained": True}


def _verify_canonical(repo, root):
    repo = Path(repo).resolve()
    if repo != Path(__file__).resolve().parent.parent or not (repo / ".git").is_dir():
        raise ValueError("P69_LIVE_REQUIRES_CANONICAL_NON_WORKTREE_CHECKOUT")
    if root.is_symlink():
        raise ValueError("P69_LINKED_STOCK_ROOT_REFUSED")
    E.L.storage_root(root)
    return repo


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("D:/ChatGPT/AStockDataTools"))
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--symbol", default=SYMBOL)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--compensate-quarantine", action="store_true")
    parser.add_argument("--compensation-ack")
    parser.add_argument("--approval")
    parser.add_argument("--expected-ledger-sha256")
    parser.add_argument("--expected-preflight-sha256")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    if args.symbol != SYMBOL or not 30 <= args.timeout_seconds <= 3600:
        parser.error("Only 002237.SZ and bounded worker timeout supported")
    if args.apply and args.compensate_quarantine:
        parser.error("Apply and compensation are mutually exclusive")
    if args.compensate_quarantine:
        if (args.compensation_ack != "RESTORE_QUARANTINE_002237.SZ"
                or any((args.approval, args.expected_ledger_sha256,
                        args.expected_preflight_sha256))):
            parser.error("Quarantine compensation requires exact acknowledgment")
    elif args.compensation_ack is not None:
        parser.error("Compensation acknowledgment requires compensation mode")
    if not args.apply and any((args.approval, args.expected_ledger_sha256,
                               args.expected_preflight_sha256)):
        parser.error("Approval options require --apply")
    if args.apply and (args.approval != APPROVAL or
                       not isinstance(args.expected_ledger_sha256, str) or
                       not HEX.fullmatch(args.expected_ledger_sha256) or
                       not isinstance(args.expected_preflight_sha256, str) or
                       not HEX.fullmatch(args.expected_preflight_sha256)):
        parser.error("Apply requires explicit stock approval and two SHA-256 pins")
    repo = _verify_canonical(args.repo, args.root)
    extra = E._storage(args.root)
    workspace = repo / "ParquetLiveSync" / "work" / "qmt_extra"
    if args.compensate_quarantine:
        with E.LIVE.exclusive_writer():
            receipt = _quarantine_compensate_locked(extra, workspace)
        print("P69_CAPITAL_COMPENSATION_RECEIPT=" + E.canonical_json(receipt))
        return
    with tempfile.TemporaryDirectory(prefix="p69-capital-one-stock-") as temp:
        with E.LIVE.exclusive_writer():
            now = datetime.now(E.L.UTC8).date().isoformat()
            recovered = I._recover_utf8_group(
                I._worker_batch, [SYMBOL], "cache", now, 120,
                Path(temp), args.timeout_seconds,
                progress=lambda line: None)
            if len(recovered) != 1 or recovered[0][0] != SYMBOL:
                raise ValueError("P69_QMT_WORKER_MISMATCH")
            _, source, reason = recovered[0]
            if reason is not None or source is None:
                raise ValueError("P69_QMT_CACHE_UNAVAILABLE " + str(reason))
            report = _run_locked(
                extra, workspace, source, now,
                approval=args.approval if args.apply else None,
                expected_ledger=args.expected_ledger_sha256,
                expected_proof=args.expected_preflight_sha256)
    print("P69_CAPITAL_ONE_STOCK_RECEIPT=" +
          E.canonical_json(report))


if __name__ == "__main__":
    main()
