"""S9 read-only all-pending stock/nine-table METADATA census.

Reuses strict P2 ledger first-blocker classification, P3 pin shape and S8
canonical root validation. No Parquet rows, QMT, downloads or market writes.
Missing local PerShare snapshot does NOT establish provider-side emptiness.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sys

import market_center_finance_pending_triage as P2
import market_center_finance_pending_snapshot_review as P3
import market_scoped_finance_live_readonly_preflight as S8
import qmt_extra_data as E
import qmt_extra_financial_cache_import as I

MAX_PENDING = 256
MAX_GLOBAL_FILES = 16000
MAX_GLOBAL_SNAPSHOT_BYTES = 40 * 1024 * 1024 * 1024
MAX_PAGE_SIZE = 20
MAX_PAGE = 256

STATE_CODES = {
    "M": "NO_LOCAL_SNAPSHOT_SOURCE_UNKNOWN",
    "U": "SNAPSHOTS_NO_ACTIVE_PINS",
    "R": "PARTIAL_DATE_PIN_COVERAGE",
    "P": "ALL_DATES_PIN_METADATA_PRESENT_NOT_CONTENT_VERIFIED",
    "A": "AMBIGUOUS_UNPINNED_SAME_DAY_VERSIONS",
}


class CensusBlocked(ValueError):
    """Fail closed on redirected, oversized, unstable, or ill-timed evidence."""


def _no_writer_window(now: datetime):
    if now.tzinfo is None or now.utcoffset() is None:
        raise CensusBlocked("TIMEZONE_AWARE_CLOCK_REQUIRED")
    current = now.astimezone(E.L.UTC8)
    minute = current.hour * 60 + current.minute
    if 19 * 60 + 50 <= minute < 20 * 60 + 25:
        raise CensusBlocked("RESERVED_2005_NO_FINANCE_INVENTORY")


def _snapshot_signature(directory: Path, pattern, *, pins: bool):
    """Metadata-only inventory with small pin hashes; never open Parquet rows."""
    files = P3._files(directory, pattern)
    result = []
    for path in files:
        stat = path.stat()
        if not path.is_file() or path.is_symlink():
            raise CensusBlocked("NONREGULAR_FINANCE_CANDIDATE")
        if pins and not 0 < stat.st_size <= P3.MAX_PIN_BYTES:
            raise CensusBlocked("FINANCE_PIN_READ_BUDGET")
        digest = sha256(path.read_bytes()).hexdigest() if pins else None
        result.append((path.name, stat.st_size, stat.st_mtime_ns, digest))
    return tuple(sorted(result))


def _table(finance: Path, code: str, table: str, evidence: list):
    base = finance / table / code
    snap_dir = base / "snapshots"
    pin_dir = base / "active"
    snap_sig = _snapshot_signature(snap_dir, P3.SNAP, pins=False)
    pin_sig = _snapshot_signature(pin_dir, P3.PIN, pins=True)
    evidence.extend(((snap_dir, P3.SNAP, False, snap_sig),
                     (pin_dir, P3.PIN, True, pin_sig)))
    # The existing conservative P3 validates the pin JSON identity, date,
    # filename and SHA *field* shape, but does not hash Parquet content.
    report = P3._inventory(finance, code, table)
    n_snapshot = report["immutable_snapshot_candidates"]
    n_pins = report["active_pin_metadata"]
    if n_snapshot != len(snap_sig) or n_pins != len(pin_sig):
        raise CensusBlocked("TABLE_METADATA_CHANGED_DURING_READ")
    dates = {name[:10] for name, *_ in snap_sig}
    pinned_days = {name[:10] for name, *_ in pin_sig}
    if not pinned_days <= dates:
        raise CensusBlocked("ACTIVE_PIN_WITHOUT_MATCHING_DATE")
    if not n_snapshot:
        status = "M"
    elif any(sum(name.startswith(day + "-") for name, *_ in snap_sig) > 1
             and day not in pinned_days for day in dates):
        status = "A"
    elif not pinned_days:
        status = "U"
    elif pinned_days != dates:
        status = "R"
    else:
        status = "P"
    return {
        "table": table,
        "state": status,
        "snapshot_files": n_snapshot,
        "active_pins": n_pins,
        "snapshot_days": len(dates),
        "unpinned_days": len(dates - pinned_days),
        "compressed_candidate_bytes": report["snapshot_candidate_bytes"],
    }


def _revalidate(evidence):
    for directory, pattern, pins, original in evidence:
        if _snapshot_signature(directory, pattern, pins=pins) != original:
            raise CensusBlocked("FINANCE_FILES_CHANGED_DURING_CENSUS")


def census(root: Path, workspace: Path, *, page: int = 1, page_size: int = 3,
           now: datetime | None = None) -> dict:
    """Exhaustive over pending LEDGER identities; NOT all market securities."""
    if (type(page) is not int or type(page_size) is not int
            or not 1 <= page <= MAX_PAGE
            or not 1 <= page_size <= MAX_PAGE_SIZE):
        raise CensusBlocked("INVALID_CENSUS_PAGE")
    _no_writer_window(now or datetime.now(E.L.UTC8))
    workspace = S8._canonical_workspace(Path(workspace))
    root = Path(root)
    if not root.is_absolute():
        raise CensusBlocked("ABSOLUTE_STOCK_ROOT_REQUIRED")
    S8._safe(root)
    extra = E._storage(root)
    S8._safe(extra)
    state_module = workspace.parent.parent
    # P2 checks every pending reason/asof/attempt/detail, parses the
    # FIRST recorded conflicting table only, and pins the ledger SHA.
    first = P2.summarize_pending(state_module)
    state_file = workspace / I.STATE_FILE
    state, ledger_sha = P2._read_ledger(state_file)
    if ledger_sha != first["progress_sha256"]:
        raise CensusBlocked("LEDGER_CHANGED_BEFORE_CENSUS")
    I._state(extra, workspace)  # Prove progress root is the requested data root.
    pending = state["pending"]
    if len(pending) > MAX_PENDING:
        raise CensusBlocked("PENDING_LEDGER_SCOPE_OVER_BUDGET")
    finance = P3._root(E.L.storage_root(root))
    evidence = []
    journals = S8._journal_counts(workspace, [])  # repeated at end too
    global_files = 0
    global_bytes = 0
    pending_rows = []
    table_states = Counter()
    first_tables = Counter()
    reasons = Counter()
    per_share_missing = []
    decode_cases = []
    for code, item in sorted(pending.items()):
        reason = item["reason"]
        reasons[reason] += 1
        if reason == "SOURCE_HISTORY_CONFLICT":
            first_table, kind, removed = P2._parse_first_conflict(
                code, item["detail"])
            first_tables[first_table] += 1
        else:
            first_table, kind, removed = None, None, None
        states = {}
        per_table_files = {}
        for table in E.FIN_TABLES:
            entry = _table(finance, code, table, evidence)
            states[table] = entry["state"]
            per_table_files[table] = {
                "snapshots": entry["snapshot_files"],
                "active_pins": entry["active_pins"],
                "unpinned_days": entry["unpinned_days"],
            }
            table_states[(table, entry["state"])] += 1
            global_files += entry["snapshot_files"] + entry["active_pins"]
            global_bytes += entry["compressed_candidate_bytes"]
            if (global_files > MAX_GLOBAL_FILES or
                    global_bytes > MAX_GLOBAL_SNAPSHOT_BYTES):
                raise CensusBlocked("FINANCE_METADATA_GLOBAL_BUDGET")
        if states["PerShare"] == "M":
            per_share_missing.append(code)
        if reason == "CACHE_DECODE_ERROR":
            decode_cases.append(code)
        pending_rows.append({
            "symbol": code,
            "reason": reason,
            "pending_asof": item["asof"],
            "attempts": item["attempts"],
            "first_recorded_conflict_table": first_table,
            "first_recorded_conflict_kind": kind,
            "reported_removed_or_revised_rows_unverified": removed,
            "ledger_detail": item["detail"][:180],
            "nine_table_states": {
                name: states[name] for name in E.FIN_TABLES},
            "nine_table_file_counts": per_table_files,
        })
    _revalidate(evidence)
    if S8._journal_counts(workspace, []) != journals:
        raise CensusBlocked("TRANSACTION_JOURNAL_CHANGED_DURING_CENSUS")
    end = P2.summarize_pending(state_module)
    if (end["progress_sha256"] != ledger_sha
            or P2._read_ledger(state_file)[1] != ledger_sha):
        raise CensusBlocked("LEDGER_CHANGED_DURING_CENSUS")
    _no_writer_window(datetime.now(E.L.UTC8) if now is None else now)
    # Put the only decode-error stock first, followed by ledger entries
    # whose first historical blocker cannot be classified; paginate the
    # detail rows, but aggregate evidence still covers ALL pending stocks.
    pending_rows.sort(key=lambda row: (
        0 if row["reason"] == "CACHE_DECODE_ERROR" else
        1 if row["first_recorded_conflict_table"] == "UNCLASSIFIED" else
        2 if row["reason"] == "NO_CACHE" else 3,
        row["symbol"],
    ))
    lower = (page - 1) * page_size
    shown = pending_rows[lower:lower + page_size]
    return {
        "status": "S9_FULL_PENDING_METADATA_CENSUS_READONLY_NOT_SOURCE_CERTIFIED",
        "ledger_sha256": ledger_sha,
        "ledger_pending_total": len(pending),
        "all_pending_ledger_symbols_enumerated": True,
        "all_nine_table_directories_metadata_scanned_per_pending": True,
        "pending_by_reason": dict(sorted(reasons.items())),
        "first_recorded_conflict_table_counts": dict(sorted(
            first_tables.items())),
        "first_conflict_only_not_all_nine_source_differences": True,
        "nine_table_local_state_legend": STATE_CODES,
        "nine_table_local_state_counts": [
            {"table": table, "state": state, "count": table_states[(table,state)]}
            for table in E.FIN_TABLES for state in STATE_CODES
            if table_states[(table, state)]
        ],
        "per_share_without_local_snapshots": len(per_share_missing),
        "per_share_missing_codes_preview": per_share_missing[:12],
        "per_share_qmt_source_empty_proven": False,
        "cache_decode_error_stocks": decode_cases,
        "journal_counts": journals,
        "global_candidate_files_enumerated": global_files,
        "global_snapshot_compressed_bytes_metadata": global_bytes,
        "page_order": "DECODE_THEN_UNCLASSIFIED_THEN_CODE",
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (len(pending_rows) + page_size - 1) // page_size),
        "rows_on_page": shown,
        "rows_on_page_count": len(shown),
        "page_is_complete_pending_census": len(pending_rows) <= page_size,
        "all_snapshot_contents_sha256_verified": False,
        "all_historical_versions_verified": False,
        "source_authenticity_certified": False,
        "multisource_verified": False,
        "qmt_live_connection_checked": False,
        "qmt_calls": 0, "can_download": False,
        "can_commit": False, "can_apply": False,
        "financial_ledger_writes": 0, "official_market_writes": 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=3)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({"status": "S9_EXPLICIT_READONLY_REQUIRED",
                          "can_apply": False, "qmt_calls": 0}))
        return 2
    try:
        result = census(args.root, args.workspace, page=args.page,
                        page_size=args.page_size)
    except (CensusBlocked, P2.PendingTriageBlocked,
            P3.SnapshotReviewBlocked, S8.PreflightBlocked) as exc:
        print(json.dumps({"status": "S9_READONLY_CENSUS_BLOCKED",
                          "reason": str(exc)[:130],
                          "can_apply": False, "qmt_calls": 0}))
        return 2
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        print(json.dumps({"status": "S9_READONLY_CENSUS_BLOCKED",
                          "reason": "LOCAL_PENDING_OR_FINANCE_METADATA_INVALID",
                          "can_apply": False, "qmt_calls": 0}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
