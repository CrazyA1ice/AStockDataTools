"""S5: read-only commit intent for a bounded QMT finance snapshot batch.

Strict all-nine-table review is prerequisite. This module NEVER calls the
financial importer commit method, updates pins, writes journal, or advances
the official ledger. A signed intent is NOT user approval or a commit token.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import re
import argparse
import json
from pathlib import Path
import sys

import market_scoped_finance_history_review as REVIEW
import qmt_extra_data as E
import qmt_extra_financial_cache_import as I

FORMAT = "scoped_finance_transaction_intent_v1"
PHASES = ("PREPARED", "SNAPSHOT_WRITTEN", "PINS_UPDATED",
          "LEDGER_RELEASED", "COMPLETE", "QUARANTINED")
BLOCKED_RESULTS = frozenset(("SOURCE_CACHE_MISSING", "BLOCKED_HISTORY_CONFLICT",
                            "LOCAL_HISTORY_UNCHANGED_NOT_CERTIFIED"))
MAX_CANDIDATES = 5


class IntentBlocked(ValueError):
    """Ambiguous or changing commit evidence is never an authorization."""


def _digest(doc: dict) -> str:
    return sha256(E.canonical_json(doc).encode("utf-8")).hexdigest()


def _manifest_target(extra: Path, code: str, table: str, asof: str,
                     records: list[dict]) -> dict:
    """Project an immutable content-addressed filename without writing."""
    E._path_check(extra)
    folder = extra / "financial" / table / code
    E._path_check(folder)
    new_arrow = E.snapshot_table(asof, code, table, records)
    target = E._snapshot_path(
        extra, "financial/" + table + "/" + code, asof, new_arrow)
    E._path_check(target)
    if target.exists() or target.is_symlink():
        # No silent adoption of an existing unselected version.
        raise IntentBlocked("TARGET_ALREADY_EXISTS_REEVALUATE_HISTORY")
    previous = E._financial_snapshot_file(extra, code, table, asof)
    active_pin = E._financial_active_path(extra, code, table, asof)
    E._path_check(active_pin)
    if active_pin.exists() and not active_pin.is_file():
        raise IntentBlocked("INVALID_ACTIVE_PIN")
    prior_sha = None
    pin_sha = None
    if previous is not None:
        E._verify_financial_snapshot_file(extra, code, table, asof, previous)
        prior_sha = E.L.hash_file(previous)
        if not active_pin.exists():
            # Same-day legacy snapshots must be pinned before adding a
            # different version. Until that operation is journalled and
            # crash-tested, this is a mandatory manual safety hold.
            raise IntentBlocked("SAME_DAY_UNPINNED_HISTORY_REQUIRES_REVIEW")
    if active_pin.exists():
        if active_pin.is_symlink():
            raise IntentBlocked("LINKED_ACTIVE_PIN")
        pin_sha = E.L.hash_file(active_pin)
    return {
        "table": table,
        "rows": len(records),
        "target_filename": target.name,
        "prior_same_day_filename": previous.name if previous else None,
        "prior_snapshot_sha256": prior_sha,
        "active_pin_sha256": pin_sha,
        "target_absent_verified": True,
    }


def build_intent(payload: dict, review: dict, *, extra: Path, asof: str,
                 cache_sha: str, progress_sha: str, planner=None) -> dict:
    """Build deterministic target list. Never authorizes writing.

    For any ineligible stock, the entire batch remains blocked. No
    subset is silently committed or removed from the user's selection.
    """
    if (type(review) is not dict
            or review.get("status") !=
               "SCOPED_FINANCE_NINE_TABLE_PRECOMMIT_READONLY"
            or review.get("can_commit") is not False
            or review.get("official_market_writes") != 0
            or review.get("financial_ledger_writes") != 0
            or review.get("multisource_verified") is not False
            or review.get("source_authenticity_certified") is not False
            or type(payload) is not dict
            or type(payload.get("records")) is not dict
            or type(payload.get("symbols")) is not list
            or type(review.get("stock_results")) is not list
            or len(review["stock_results"]) != len(payload["symbols"])
            or not 1 <= len(payload["symbols"]) <= MAX_CANDIDATES
            or not isinstance(cache_sha, str)
            or re.fullmatch(r"[a-fA-F0-9]{64}", cache_sha) is None
            or not isinstance(progress_sha, str)
            or re.fullmatch(r"[a-fA-F0-9]{64}", progress_sha) is None):
        raise IntentBlocked("STRICT_NINE_TABLE_REVIEW_REQUIRED")
    try:
        if date.fromisoformat(asof).isoformat() != asof:
            raise ValueError("date not canonical")
    except (TypeError, ValueError) as exc:
        raise IntentBlocked("INVALID_ASOF_FOR_TRANSACTION_INTENT") from exc
    planner = I._plan_symbol if planner is None else planner
    codes = payload["symbols"]
    if codes != sorted(set(codes)):
        raise IntentBlocked("STOCK_SCOPE_MUST_BE_SORTED")
    try:
        if any(E.valid_code(code) != code for code in codes):
            raise IntentBlocked("INVALID_INTENT_STOCK_ID")
    except ValueError as exc:
        raise IntentBlocked("INVALID_INTENT_STOCK_ID") from exc
    reports = review["stock_results"]
    if [item.get("symbol") for item in reports] != codes:
        raise IntentBlocked("REVIEW_SYMBOL_COVERAGE_DRIFT")
    manifest = []
    blocked = []
    for item in reports:
        code = item["symbol"]
        status = item.get("status")
        if (status != "CANDIDATE_NEW_VERSION_NOT_COMMITTED"
                or item.get("pending_previously_recorded") is not False):
            if status not in BLOCKED_RESULTS and status != "CANDIDATE_NEW_VERSION_NOT_COMMITTED":
                raise IntentBlocked("UNKNOWN_STRICT_REVIEW_RESULT")
            blocked.append({"symbol": code,
                            "reason": ("EXISTING_PENDING_REQUIRES_MANUAL_REVIEW"
                                       if item.get("pending_previously_recorded")
                                       else status)})
            continue
        data = payload["records"].get(code)
        if type(data) is not dict or set(data) != set(E.FIN_TABLES):
            raise IntentBlocked("SOURCE_PAYLOAD_CHANGED_AFTER_REVIEW")
        try:
            checked, staged = planner(extra, code, asof, data)
        except (ValueError, OSError) as exc:
            raise IntentBlocked("STRICT_PLANNER_CHANGED_AFTER_REVIEW") from exc
        if (set(checked) != set(E.FIN_TABLES)
                or not set(staged) <= set(E.FIN_TABLES)
                or not staged):
            raise IntentBlocked("NEW_VERSION_ACTIONS_INCONSISTENT")
        files = []
        for table in E.FIN_TABLES:
            action = checked[table].get("action")
            if (table in staged) != (action == "CREATE_VERSION"):
                raise IntentBlocked("PLANNED_TABLE_ACTION_DRIFT")
            if table in staged:
                files.append(_manifest_target(
                    extra, code, table, asof, staged[table]))
        manifest.append({
            "symbol": code, "table_count": len(files),
            "immutable_targets": files,
        })
    core = {
        "format": FORMAT,
        "asof": asof,
        "cache_sha256": cache_sha.lower(),
        "progress_sha256": progress_sha.lower(),
        "selected_stocks": codes,
        "candidate_stocks": manifest,
        "blocked_stocks": blocked,
    }
    return {
        "status": "SCOPED_FINANCE_TRANSACTION_INTENT_READONLY",
        "intent_sha256": _digest(core),
        "intent": core,
        "batch_fully_eligible_for_future_manual_review":
            not blocked and bool(manifest),
        "candidate_immutable_files": sum(
            x["table_count"] for x in manifest),
        "batch_has_unresolved_blockers": bool(blocked),
        "existing_snapshots_preserved": True,
        "pending_entries_preserved": True,
        "source_authenticity_certified": False,
        "multisource_verified": False,
        "can_commit": False,
        "can_apply": False,
        "journal_written": False,
        "official_market_writes": 0,
        "financial_ledger_writes": 0,
        "qmt_calls": 0,
    }


def recovery_decision(journal: dict) -> dict:
    """Pure fail-closed crash policy. NEVER autonomously roll back files."""
    if (type(journal) is not dict or journal.get("format") != FORMAT
            or journal.get("phase") not in PHASES
            or not isinstance(journal.get("intent_sha256"), str)
            or re.fullmatch(r"[a-fA-F0-9]{64}",
                            journal["intent_sha256"]) is None):
        raise IntentBlocked("INVALID_OR_UNKNOWN_TRANSACTION_JOURNAL")
    state = journal["phase"]
    return {
        "phase": state,
        "decision": ("AUDIT_COMPLETED_TRANSACTION" if state == "COMPLETE"
                     else "QUARANTINE_PENDING_MANUAL_RECOVERY"),
        "automated_replay_allowed": False,
        "automated_delete_or_rollback_allowed": False,
        "original_immutable_versions_retained": True,
        "financial_ledger_release_allowed": False,
    }


def preview(*, root: Path, workspace: Path, cache_file: Path,
            expected_cache_sha256: str, expected_progress_sha256: str,
            symbols: str, start: str, end: str) -> dict:
    """Re-run S4, then bind target filenames to unchanged SHA evidence."""
    review = REVIEW.review(
        root=root, workspace=workspace, cache_file=cache_file,
        expected_cache_sha256=expected_cache_sha256,
        expected_progress_sha256=expected_progress_sha256,
        symbols=symbols, start=start, end=end)
    E._path_check(cache_file)
    if REVIEW._hash_file(cache_file, REVIEW.MAX_STAGE_BYTES) != review["cache_sha256"]:
        raise IntentBlocked("STAGE_CHANGED_AFTER_NINE_TABLE_REVIEW")
    try:
        with Path(cache_file).open("rb") as stream:
            payload = json.load(stream)
    except (ValueError, UnicodeError) as exc:
        raise IntentBlocked("INVALID_STAGED_CACHE_JSON") from exc
    asof = datetime.now(E.L.UTC8).date().isoformat()
    extra = E._storage(root)
    result = build_intent(
        payload, review, extra=extra, asof=asof,
        cache_sha=review["cache_sha256"],
        progress_sha=review["progress_sha256"])
    if (REVIEW._hash_file(cache_file, REVIEW.MAX_STAGE_BYTES) != review["cache_sha256"]
            or REVIEW._hash_file(Path(workspace) / I.STATE_FILE,
                                 REVIEW.MAX_LEDGER_BYTES) != review["progress_sha256"]
            or datetime.now(E.L.UTC8).date().isoformat() != asof):
        raise IntentBlocked("EVIDENCE_OR_DAY_CHANGED_DURING_INTENT_PREVIEW")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--cache-file", required=True, type=Path)
    parser.add_argument("--expected-cache-sha256", required=True)
    parser.add_argument("--expected-progress-sha256", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({"status": "S5_EXPLICIT_READONLY_REQUIRED",
                          "can_commit": False, "official_market_writes": 0}))
        return 2
    try:
        report = preview(
            root=args.root, workspace=args.workspace,
            cache_file=args.cache_file,
            expected_cache_sha256=args.expected_cache_sha256,
            expected_progress_sha256=args.expected_progress_sha256,
            symbols=args.symbols, start=args.start, end=args.end)
    except (IntentBlocked, REVIEW.PrecommitBlocked) as exc:
        print(json.dumps({"status": "S5_TRANSACTION_INTENT_BLOCKED",
                          "reason": str(exc)[:120],
                          "can_commit": False, "official_market_writes": 0}))
        return 2
    except (OSError, KeyError, TypeError, ValueError, RuntimeError):
        print(json.dumps({"status": "S5_TRANSACTION_INTENT_BLOCKED",
                          "reason": "EVIDENCE_OR_HISTORY_CHECK_FAILED",
                          "can_commit": False, "official_market_writes": 0}))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
