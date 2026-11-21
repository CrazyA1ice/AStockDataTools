"""Conservative ledger-only categorization of QMT finance pending conflicts.

Only reads the canonical progress ledger. Does NOT open Parquet, load xtquant,
acquire a writer mutex, download, retry, alter progress or certify history.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

MAX_LEDGER_BYTES = 2 * 1024 * 1024
STOCK = re.compile(r"\d{6}\.(?:SH|SZ|BJ)")
CONFLICT = re.compile(
    r"SOURCE_HISTORY_CONFLICT (\d{6}\.(?:SH|SZ|BJ)) "
    r"table=([A-Za-z0-9]+) "
    r"(?:removed_or_revised=(\d+)|scoped_m_quarter_proof=([A-Z0-9_]+))"
)
TABLES = (
    "Balance", "Income", "CashFlow", "Capital",
    "Top10FlowHolder", "Top10Holder", "HolderNum",
    "PershareIndex", "PerShare",
)
REASONS = ("SOURCE_HISTORY_CONFLICT", "CACHE_DECODE_ERROR", "NO_CACHE")


class PendingTriageBlocked(ValueError):
    """Untrusted, changed or oversized private ledger; never infer success."""


def _trusted_path(state_module: Path) -> Path:
    if (not state_module.is_absolute()
            or state_module.name.lower() != "parquetlivesync"
            or not state_module.is_dir()
            or any(p.is_symlink() for p in
                   (state_module, *state_module.parents))):
        raise PendingTriageBlocked("canonical_state_module_required")
    path = state_module / "work" / "qmt_extra" / "financial-cache-progress.json"
    if (any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file()):
        raise PendingTriageBlocked("missing_or_redirected_finance_progress")
    return path


def _read_ledger(path: Path) -> tuple[dict, str]:
    if path.stat().st_size > MAX_LEDGER_BYTES:
        raise PendingTriageBlocked("finance_progress_size_budget")
    raw = path.read_bytes()
    if len(raw) > MAX_LEDGER_BYTES:
        raise PendingTriageBlocked("finance_progress_read_budget")
    original_sha = sha256(raw).hexdigest()
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise PendingTriageBlocked("malformed_finance_progress_json") from exc
    if (type(doc) is not dict
            or doc.get("format") != "qmt_financial_cache_import_v1"
            or type(doc.get("pending")) is not dict
            or type(doc.get("daily_cursor")) is not str
            or type(doc.get("daily_date")) is not str):
        raise PendingTriageBlocked("untrusted_finance_progress_schema")
    return doc, original_sha


def _parse_first_conflict(code: str, detail: str) -> tuple[str, str, int | None]:
    """Extract ONLY the FIRST blocking table, never pretend all nine were checked."""
    if not isinstance(detail, str):
        return "UNCLASSIFIED", "UNKNOWN", None
    match = CONFLICT.fullmatch(detail)
    if match is None or match.group(1) != code or match.group(2) not in TABLES:
        return "UNCLASSIFIED", "UNKNOWN", None
    table = match.group(2)
    if match.group(3) is not None:
        return table, "REMOVED_OR_REVISED_UNVERIFIED", int(match.group(3))
    if table == "Capital":
        return table, "SCOPED_M_QUARTER_PROOF_REJECTED", None
    return "UNCLASSIFIED", "UNKNOWN", None


def summarize_pending(state_module: Path | str) -> dict:
    path = _trusted_path(Path(state_module))
    ledger, first_sha = _read_ledger(path)
    by_reason = Counter()
    by_table = Counter()
    by_class = Counter()
    attempts_by_reason = Counter()
    attempt_by_first_table = Counter()
    asof_by_reason = Counter()
    total_affected_rows = Counter()
    unknown_count = 0
    for code, item in ledger["pending"].items():
        if (type(code) is not str or STOCK.fullmatch(code) is None
                or type(item) is not dict
                or item.get("reason") not in REASONS
                or type(item.get("attempts")) is not int
                or not 1 <= item["attempts"] <= 1000000
                or type(item.get("asof")) is not str
                or type(item.get("detail")) is not str):
            raise PendingTriageBlocked("invalid_financial_pending_identity")
        try:
            if date.fromisoformat(item["asof"]).isoformat() != item["asof"]:
                raise ValueError("noncanonical")
        except ValueError as exc:
            raise PendingTriageBlocked("invalid_financial_pending_asof") from exc
        reason = item["reason"]
        by_reason[reason] += 1
        attempts_by_reason[(reason, item["attempts"])] += 1
        asof_by_reason[(reason, item["asof"])] += 1
        if reason == "SOURCE_HISTORY_CONFLICT":
            table, kind, count = _parse_first_conflict(code, item["detail"])
            by_table[table] += 1
            by_class[(table, kind)] += 1
            attempt_by_first_table[(table, item["attempts"])] += 1
            if count is not None:
                total_affected_rows[table] += count
            if table == "UNCLASSIFIED":
                unknown_count += 1
    # Compare before returning a summary. Never claim an atomic snapshot of
    # concurrently written files; a changed ledger is an explicit blocker.
    if (path.is_symlink() or not path.is_file()
            or path.stat().st_size > MAX_LEDGER_BYTES
            or sha256(path.read_bytes()).hexdigest() != first_sha):
        raise PendingTriageBlocked("finance_progress_changed_during_read")
    conflicts = by_reason["SOURCE_HISTORY_CONFLICT"]
    return {
        "status": "FINANCE_PENDING_LEDGER_READONLY_FIRST_BLOCKER_NOT_CERTIFIED",
        "daily_date": ledger["daily_date"],
        "daily_cursor": ledger["daily_cursor"],
        "pending_total": len(ledger["pending"]),
        "conflict_total": conflicts,
        "conflict_first_table_classified": conflicts - unknown_count,
        "conflict_first_table_unclassified": unknown_count,
        "reason_counts": [
            {"reason": reason, "count": by_reason[reason]} for reason in REASONS
        ],
        "first_blocking_table_counts": [
            {"table": table, "count": by_table[table]}
            for table in (*TABLES, "UNCLASSIFIED") if by_table[table]
        ],
        "first_blocker_kind_counts": [
            {"table": table, "kind": kind, "count": count}
            for (table, kind), count in sorted(by_class.items())
        ],
        "attempts_by_reason": [
            {"reason": reason, "attempts": attempts, "count": count}
            for (reason, attempts), count in sorted(attempts_by_reason.items())
        ],
        "attempts_by_first_conflicting_table": [
            {"table": table, "attempts": attempts, "count": count}
            for (table, attempts), count in sorted(attempt_by_first_table.items())
        ],
        "pending_asof_by_reason": [
            {"reason": reason, "asof": day, "count": count}
            for (reason, day), count in sorted(asof_by_reason.items())
        ],
        "missing_or_revised_row_count_claims_unverified": [
            {"table": table, "aggregate_reported_count": count}
            for table, count in sorted(total_affected_rows.items())
        ],
        "first_blocker_only": True,
        "all_nine_tables_checked": False,
        "source_authenticity_certified": False,
        "history_complete_certified": False,
        "pending_repair_approved": False,
        "can_download": False,
        "can_execute": False,
        "market_file_writes": False,
        "qmt_calls": 0,
        "progress_sha256": first_sha,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-module", type=Path, required=True)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({
            "status": "FINANCE_PENDING_TRIAGE_EXPLICIT_OPTIN_REQUIRED",
            "can_execute": False, "qmt_calls": 0, "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    try:
        report = summarize_pending(args.state_module)
    except (PendingTriageBlocked, OSError) as exc:
        print(json.dumps({
            "status": "FINANCE_PENDING_TRIAGE_BLOCKED",
            "reason": str(exc)[:150], "can_execute": False,
            "qmt_calls": 0, "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
