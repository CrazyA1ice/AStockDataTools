"""S6: isolated finance transaction sandbox using the real immutable writer.

No live --apply, no user-supplied filesystem root, no QMT, no market task,
no production ledger or pending mutation. A sandbox success is not evidence
that a live finance transaction has been approved.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import tempfile

import market_scoped_finance_history_review as REVIEW
import market_scoped_finance_transaction_intent as INTENT
import qmt_extra_data as E
import qmt_extra_financial_cache_import as I

STOCK = "000001.SZ"  # synthetic identity only
ASOF = "2026-11-21"  # fixed fixture, not trading-day inference
ANNOUNCED = "20261120"
FAIL_POINTS = (
    "PREPARED", "AFTER_SNAPSHOT_BEFORE_JOURNAL", "SNAPSHOT_WRITTEN",
    "AFTER_PIN_BEFORE_JOURNAL", "PINS_UPDATED",
    "AFTER_LEDGER_BEFORE_JOURNAL", "LEDGER_RELEASED", "COMPLETE",
    "CORRUPT_BACKUP_BEFORE_VERIFY",
)


class SyntheticInterruption(Exception):
    """Injected exception, never an instruction to undo or replay data."""


class SandboxRefused(ValueError):
    """Never allow caller-defined canonical financial paths."""


def _hash(path: Path) -> str:
    E._path_check(path)
    if not path.is_file() or path.is_symlink():
        raise SandboxRefused("MISSING_SANDBOX_EVIDENCE")
    return E.L.hash_file(path)


def _require_owned_sandbox(home: Path) -> None:
    root = Path(home)
    expected = Path(tempfile.gettempdir()).resolve()
    if (not root.is_absolute() or root.is_symlink()
            or root.resolve().parent != expected
            or not root.name.startswith("astock-finance-s6-")
            or not root.is_dir()
            or (root / "marker.txt").read_text(encoding="utf-8")
               != "SYNTHETIC_FINANCE_ONLY_V1"):
        raise SandboxRefused("S6_ONLY_INTERNAL_EPHEMERAL_SANDBOX")
    E._path_check(root)


def _sample():
    old = {"_index": "1", "m_timetag": "20260630",
           "m_quarter": "2026Q2", "total": 100}
    new = {"_index": "2", "m_timetag": "20260930",
           "m_quarter": "2026Q3", "total": 200}
    source = {t: ([deepcopy(old), deepcopy(new)]
                  if t == "Capital" else []) for t in E.FIN_TABLES}
    return old, source


def _save_journal(journal: Path, record: dict):
    E._path_check(journal)
    E.S._save(journal, record)
    verified = json.loads(journal.read_text(encoding="utf-8"))
    if verified != record:
        raise SandboxRefused("JOURNAL_WRITE_READBACK_MISMATCH")


def _durable_backup(source: Path, destination: Path):
    E._path_check(destination)
    if destination.exists() or destination.is_symlink():
        raise SandboxRefused("BACKUP_ALREADY_EXISTS")
    blob = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(blob)
        output.flush()
        os.fsync(output.fileno())
    if _hash(destination) != sha256(blob).hexdigest():
        raise SandboxRefused("BACKUP_SHA_MISMATCH")
    return _hash(destination)


def _sandbox_case(home: Path, *, failure_at: str | None,
                  observer=None) -> dict:
    _require_owned_sandbox(home)
    if failure_at is not None and failure_at not in FAIL_POINTS:
        raise SandboxRefused("UNKNOWN_SYNTHETIC_FAULT_POINT")
    extra = home / "AllCycleAStockData" / "qmt_extra"
    workspace = home / "work"
    extra.mkdir(parents=True)
    workspace.mkdir(parents=True)
    # A fixture ledger, never the user's financial-cache-progress.json.
    initial = {
        "format": I.FORMAT, "root": str(extra.resolve()),
        "import_cursor": "", "daily_date": ASOF, "daily_cursor": "",
        "pending_retry_cursor": "", "pending": {},
        "daily_sweep_start": "", "daily_sweep_reached_end": False,
        "daily_sweep_finished": "",
    }
    I._save_state(workspace, initial)
    ledger = workspace / I.STATE_FILE
    ledger_sha = _hash(ledger)
    old, source = _sample()
    group = "financial/Capital/" + STOCK
    old_table = E.snapshot_table(ASOF, STOCK, "Capital", [old])
    original = E._snapshot_path(extra, group, ASOF, old_table)
    E._snapshot_write(extra, group, ASOF, old_table, workspace=workspace)
    E._pin_financial_snapshot(extra, STOCK, "Capital", ASOF, original)
    original_sha = _hash(original)
    pin = E._financial_active_path(extra, STOCK, "Capital", ASOF)
    old_pin_sha = _hash(pin)

    cache = {
        "format": "qmt_financial_cache_batch_v1",
        "mode": "daily", "symbols": [STOCK],
        "refresh_start": ANNOUNCED, "refresh_end": ANNOUNCED,
        "missing_symbols": [],
        "records": {STOCK: source},
        "row_counts": {
            STOCK: {t: len(source[t]) for t in E.FIN_TABLES},
        },
    }
    review = REVIEW.evaluate(
        cache, stocks=[STOCK], start=ANNOUNCED, end=ANNOUNCED,
        extra=extra, asof=ASOF, pending={})
    if review["stocks_candidate_for_review"] != 1:
        raise SandboxRefused("STRICT_NINE_TABLE_SANDBOX_PREVIEW_REFUSED")
    intent = INTENT.build_intent(
        cache, review, extra=extra, asof=ASOF,
        cache_sha=sha256(E.canonical_json(cache).encode("utf-8")).hexdigest(),
        progress_sha=ledger_sha,
        journal_workspace=workspace)
    if (intent["can_commit"] is not False
            or not intent["batch_fully_eligible_for_future_manual_review"]
            or intent["candidate_immutable_files"] != 1):
        raise SandboxRefused("STRICT_INTENT_SANDBOX_PREVIEW_REFUSED")
    target_name = intent["intent"]["candidate_stocks"][0][
        "immutable_targets"][0]["target_filename"]
    target = original.parent / target_name
    journal = (workspace / "scoped-finance-transaction-journals" /
               (STOCK + ".json"))
    backup_ledger = workspace / "backups" / "original-ledger.json"
    backup_pin = workspace / "backups" / "original-capital-pin.json"

    # The ledger and the pin are backed up BEFORE the durable PREPARED journal.
    if _durable_backup(ledger, backup_ledger) != ledger_sha:
        raise SandboxRefused("LEDGER_BACKUP_CHANGED")
    if _durable_backup(pin, backup_pin) != old_pin_sha:
        raise SandboxRefused("ACTIVE_PIN_BACKUP_CHANGED")
    record = {
        "format": INTENT.FORMAT, "intent_sha256": intent["intent_sha256"],
        "phase": "PREPARED", "symbol": STOCK,
        "sandbox_only": True, "ledger_backup_sha256": ledger_sha,
        "pin_backup_sha256": old_pin_sha,
        "original_snapshot_sha256": original_sha,
        "candidate_snapshot": target_name,
        "phase_history": ["PREPARED"],
    }
    _save_journal(journal, record)

    def advance(phase):
        record["phase"] = phase
        record["phase_history"].append(phase)
        _save_journal(journal, record)

    def trip(point):
        if failure_at == point:
            raise SyntheticInterruption("INJECTED_" + point)

    outcome = "SANDBOX_TRANSACTION_COMPLETE"
    try:
        trip("PREPARED")
        arrow = E.snapshot_table(ASOF, STOCK, "Capital", source["Capital"])
        if E._snapshot_path(extra, group, ASOF, arrow) != target:
            raise SandboxRefused("INTENDED_TARGET_DRIFT")
        E._snapshot_write(extra, group, ASOF, arrow, workspace=workspace)
        E._verify_financial_snapshot_file(extra, STOCK, "Capital", ASOF, target)
        if _hash(original) != original_sha:
            raise SandboxRefused("ORIGINAL_SNAPSHOT_CHANGED")
        trip("AFTER_SNAPSHOT_BEFORE_JOURNAL")
        advance("SNAPSHOT_WRITTEN")
        trip("SNAPSHOT_WRITTEN")
        E._pin_financial_snapshot(extra, STOCK, "Capital", ASOF, target)
        if E._financial_snapshot_file(extra, STOCK, "Capital", ASOF) != target:
            raise SandboxRefused("PIN_READBACK_NOT_TARGET")
        trip("AFTER_PIN_BEFORE_JOURNAL")
        advance("PINS_UPDATED")
        trip("PINS_UPDATED")
        # Synthetic isolated fixture ledger entry; NEVER a live cursor or
        # pending modification. This stage tests the crash ordering only.
        latest = I._state(extra, workspace)
        if _hash(ledger) != ledger_sha or latest["pending"] != initial["pending"]:
            raise SandboxRefused("SYNTHETIC_LEDGER_CAS_DRIFT")
        latest["sandbox_committed_intent"] = intent["intent_sha256"]
        I._save_state(workspace, latest)
        if I._state(extra, workspace)["sandbox_committed_intent"] != intent["intent_sha256"]:
            raise SandboxRefused("SANDBOX_LEDGER_READBACK_FAILED")
        trip("AFTER_LEDGER_BEFORE_JOURNAL")
        advance("LEDGER_RELEASED")
        trip("LEDGER_RELEASED")
        advance("COMPLETE")
        trip("COMPLETE")
    except SyntheticInterruption:
        outcome = "SANDBOX_INTERRUPTED_QUARANTINE_REQUIRED"
    # Corrupt a private synthetic backup to prove integrity failure blocks
    # recovery and cannot be treated as a completed transaction.
    if failure_at == "CORRUPT_BACKUP_BEFORE_VERIFY":
        with backup_pin.open("ab") as stream:
            stream.write(b"synthetic-corruption")
            stream.flush()
            os.fsync(stream.fileno())
    # We NEVER rollback/replay on an incomplete phase, regardless of where
    # the injected failure occurred, because bytes may already have changed.
    persisted = json.loads(journal.read_text(encoding="utf-8"))
    recovery = INTENT.recovery_decision(persisted)
    if (recovery["automated_replay_allowed"]
            or recovery["financial_ledger_release_allowed"]
            or _hash(original) != original_sha
            or _hash(backup_ledger) != ledger_sha
            or _hash(backup_pin) != old_pin_sha):
        raise SandboxRefused("SYNTHETIC_RECOVERY_INVARIANT_FAILED")
    observed = {
        "status": outcome,
        "at": persisted["phase"],
        "candidate_exists": target.exists(),
        "active_pin_is_candidate": (
            E._financial_snapshot_file(extra, STOCK, "Capital", ASOF) == target),
        "original_snapshot_sha256_unchanged": _hash(original) == original_sha,
        "backup_ledger_sha256_valid": _hash(backup_ledger) == ledger_sha,
        "backup_pin_sha256_valid": _hash(backup_pin) == old_pin_sha,
        "ledger_pending_unchanged": (
            I._state(extra, workspace)["pending"] == initial["pending"]),
        "ledger_cursor_unchanged": (
            I._state(extra, workspace)["daily_cursor"] == initial["daily_cursor"]),
        "recovery_decision": recovery["decision"],
        "auto_replay_allowed": False,
        "physical_rollback_attempted": False,
        "real_market_writes": 0,
        "real_qmt_calls": 0,
        "sandbox_only": True,
    }
    if observer is not None:
        observer(home, extra, workspace, deepcopy(observed))
    return observed


def run_sandbox(*, failure_at: str | None = None, observer=None) -> dict:
    """Creates own OS temporary directory; accepts no production root."""
    with tempfile.TemporaryDirectory(prefix="astock-finance-s6-") as temp:
        home = Path(temp)
        (home / "marker.txt").write_text(
            "SYNTHETIC_FINANCE_ONLY_V1", encoding="utf-8")
        return _sandbox_case(home, failure_at=failure_at, observer=observer)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--fault-after", choices=FAIL_POINTS)
    args = parser.parse_args(argv)
    if not args.synthetic_only:
        print(json.dumps({"status": "S6_SYNTHETIC_ONLY_REQUIRED",
                          "real_market_writes": 0, "real_qmt_calls": 0}))
        return 2
    try:
        result = run_sandbox(failure_at=args.fault_after)
    except (SandboxRefused, OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "S6_SANDBOX_BLOCKED",
                          "reason": str(exc)[:120],
                          "real_market_writes": 0, "real_qmt_calls": 0}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
