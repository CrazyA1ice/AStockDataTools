"""S8 real-environment LOCAL read-only finance inventory and safety preflight.

Uses the canonical checkout ledger plus an explicitly selected stock data root.
No provider API imports, downloads, snapshot writes, ledger writes or approval.
Verifies only the latest *selected* snapshot of each of nine finance tables:
NOT an all-history audit or certificate of source authenticity.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import argparse
import json
from pathlib import Path
import re
import sys

import market_scoped_finance_history_review as REVIEW
import qmt_extra_data as E
import qmt_extra_financial_cache_import as I

MAX_SAMPLES = 5
MAX_FILES_PER_DIRECTORY = 4096
FILE_NAME = re.compile(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{16}\.parquet\Z")
PIN_NAME = re.compile(r"\d{4}-\d{2}-\d{2}\.json\Z")


class PreflightBlocked(ValueError):
    """Bad, changing, redirected or oversized local evidence is never green."""


def _safe(path: Path):
    E._path_check(path)
    if path.is_symlink():
        raise PreflightBlocked("SYMLINKED_EVIDENCE_REFUSED")


def _canonical_workspace(workspace: Path):
    workspace = Path(workspace)
    if (not workspace.is_absolute() or workspace.name != "qmt_extra"
            or workspace.parent.name != "work"
            or workspace.parent.parent.name != "ParquetLiveSync"
            or not workspace.is_dir()
            or not (workspace.parent.parent.parent / ".git").is_dir()):
        raise PreflightBlocked("CANONICAL_WORKSPACE_IN_MAIN_CHECKOUT_REQUIRED")
    _safe(workspace)
    return workspace


def _selected_symbols(raw: str | None, state: dict, limit: int):
    if type(limit) is not int or not 1 <= limit <= MAX_SAMPLES:
        raise PreflightBlocked("SAMPLE_COUNT_OUT_OF_BOUNDS")
    if raw is not None:
        if not raw:
            raise PreflightBlocked("EMPTY_EXPLICIT_STOCK_SCOPE")
        codes = raw.split(",")
        if (not 1 <= len(codes) <= MAX_SAMPLES
                or codes != sorted(set(codes))):
            raise PreflightBlocked("STOCK_SCOPE_MUST_BE_SORTED_UNIQUE")
    else:
        # Prioritize pending identities. This sample is deliberately biased
        # toward unresolved problems and MUST NOT imply global completeness.
        codes = sorted(state["pending"])[:limit]
        if not codes and state.get("daily_cursor"):
            codes = [state["daily_cursor"]]
    try:
        if any(E.valid_code(code) != code for code in codes):
            raise PreflightBlocked("INVALID_STOCK_IDENTITY")
    except (TypeError, ValueError) as exc:
        raise PreflightBlocked("INVALID_STOCK_IDENTITY") from exc
    return codes[:limit] if raw is None else codes


def _files(directory: Path, pattern: re.Pattern):
    """Return a stable, bounded listing. Unexpected residue fails closed."""
    _safe(directory)
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise PreflightBlocked("FINANCIAL_DIRECTORY_INVALID")
    items = []
    for item in directory.iterdir():
        if len(items) >= MAX_FILES_PER_DIRECTORY:
            raise PreflightBlocked("FINANCIAL_DIRECTORY_COUNT_LIMIT")
        _safe(item)
        if not item.is_file() or pattern.fullmatch(item.name) is None:
            raise PreflightBlocked("UNEXPECTED_FINANCIAL_FILE_OR_DIRECTORY")
        items.append(item.name)
    return tuple(sorted(items))


def _journal_counts(workspace: Path, evidence: list):
    counts = {}
    journal_pattern = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\.json\Z")
    for directory_name in (
            "scoped-finance-transaction-journals",
            "capital-recovery-journal"):
        directory = workspace / directory_name
        names = _files(directory, journal_pattern)
        evidence.append((directory, journal_pattern, names))
        counts[directory_name] = len(names)
    return counts


def _latest_table(extra: Path, code: str, table: str, evidence: list):
    group = extra / "financial" / table / code
    snap_dir = group / "snapshots"
    pin_dir = group / "active"
    snapshots = _files(snap_dir, FILE_NAME)
    pins = _files(pin_dir, PIN_NAME)
    evidence.append((snap_dir, FILE_NAME, snapshots))
    evidence.append((pin_dir, PIN_NAME, pins))
    if not snapshots:
        if pins:
            raise PreflightBlocked("ACTIVE_PIN_WITHOUT_SNAPSHOT")
        return {"table": table, "state": "NO_LOCAL_SNAPSHOT",
                "snapshot_files": 0, "active_pin_files": 0,
                "older_snapshot_dates_unverified": 0}
    observed_dates = sorted({name[:10] for name in snapshots})
    try:
        for value in observed_dates:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("not canonical")
    except ValueError as exc:
        raise PreflightBlocked("SNAPSHOT_FILENAME_DATE_INVALID") from exc
    latest = observed_dates[-1]
    if date.fromisoformat(latest) > datetime.now(E.L.UTC8).date():
        raise PreflightBlocked("FUTURE_FINANCIAL_SNAPSHOT_DAY")
    candidate = E._financial_snapshot_file(extra, code, table, latest)
    if candidate is None:
        raise PreflightBlocked("LATEST_SNAPSHOT_UNRESOLVED")
    selected_table = E._verify_financial_snapshot_file(
        extra, code, table, latest, candidate)
    pin = E._financial_active_path(extra, code, table, latest)
    _safe(pin)
    pinned = pin.exists()
    if pinned:
        if pin.name not in pins:
            raise PreflightBlocked("LATEST_PIN_CENSUS_CHANGED")
        evidence.append((pin, None, E.L.hash_file(pin)))
    evidence.append((candidate, None, E.L.hash_file(candidate)))
    return {
        "table": table,
        "state": ("LATEST_PIN_AND_SNAPSHOT_VERIFIED" if pinned
                  else "LEGACY_LATEST_UNPINNED_REQUIRES_REVIEW"),
        "latest_snapshot_day": latest,
        "latest_selected_rows": selected_table.num_rows,
        "snapshot_files": len(snapshots),
        "active_pin_files": len(pins),
        "older_snapshot_dates_unverified": len(observed_dates) - 1,
    }


def _revalidate(evidence):
    for path, kind, before in evidence:
        if kind is None:
            _safe(path)
            if not path.is_file() or E.L.hash_file(path) != before:
                raise PreflightBlocked("OBSERVED_FILE_CHANGED_DURING_PREFLIGHT")
        elif _files(path, kind) != before:
            raise PreflightBlocked("FINANCIAL_DIRECTORY_CHANGED_DURING_PREFLIGHT")


def inspect(root: Path, workspace: Path, *, symbols: str | None = None,
            sample_count: int = 3) -> dict:
    """Bounded snapshot metadata check; always returns can_commit=false."""
    workspace = _canonical_workspace(workspace)
    root = Path(root)
    if not root.is_absolute():
        raise PreflightBlocked("EXPLICIT_ABSOLUTE_STOCK_ROOT_REQUIRED")
    _safe(root)
    extra = E._storage(root)
    _safe(extra)
    progress = workspace / I.STATE_FILE
    progress_sha = REVIEW._hash_file(progress, REVIEW.MAX_LEDGER_BYTES)
    state = I._state(extra, workspace)
    codes = _selected_symbols(symbols, state, sample_count)
    evidence = []
    journal_counts = _journal_counts(workspace, evidence)
    issues = []
    if any(journal_counts.values()):
        issues.append("EXISTING_TRANSACTION_JOURNAL_NEEDS_MANUAL_REVIEW")
    if state["pending"]:
        issues.append("FINANCIAL_PENDING_NOT_EMPTY")
    if not codes:
        issues.append("NO_FINANCIAL_SAMPLE_IDENTITIES")
    stocks = []
    for code in codes:
        table_reports = []
        for table in E.FIN_TABLES:
            table_reports.append(_latest_table(extra, code, table, evidence))
        if any(t["state"] == "LEGACY_LATEST_UNPINNED_REQUIRES_REVIEW"
               for t in table_reports):
            issues.append("LEGACY_LATEST_SNAPSHOT_UNPINNED")
        if any(t["state"] == "NO_LOCAL_SNAPSHOT" for t in table_reports):
            issues.append("SAMPLE_HAS_EMPTY_FINANCIAL_TABLES")
        stocks.append({
            "symbol": code,
            "pending": code in state["pending"],
            "tables_inspected": len(table_reports),
            "table_summaries": table_reports,
        })
    _revalidate(evidence)
    if REVIEW._hash_file(progress, REVIEW.MAX_LEDGER_BYTES) != progress_sha:
        raise PreflightBlocked("FINANCE_LEDGER_CHANGED_DURING_PREFLIGHT")
    return {
        "status": "S8_REAL_ENVIRONMENT_READONLY_REVIEW_REQUIRED",
        "source": "CANONICAL_LOCAL_FINANCE_FILES_ONLY",
        "finance_progress_sha256": progress_sha,
        "pending_total": len(state["pending"]),
        "pending_by_reason": dict(sorted(
            Counter(item["reason"] for item in state["pending"].values()).items())),
        "journal_counts": journal_counts,
        "stocks_sampled": codes,
        "sample_selection": ("USER_EXPLICIT" if symbols else
                             "PENDING_FIRST_OR_CURSOR"),
        "stocks": stocks,
        "issues": sorted(set(issues)),
        "only_latest_selected_snapshot_per_table_verified": True,
        "all_historical_versions_verified": False,
        "source_authenticity_certified": False,
        "multisource_verified": False,
        "qmt_live_connection_checked": False,
        "qmt_calls": 0,
        "can_download": False,
        "can_commit": False,
        "can_apply": False,
        "financial_ledger_writes": 0,
        "official_market_writes": 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--symbols", help="Optional 1-5 sorted stock codes")
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({"status": "S8_EXPLICIT_READONLY_REQUIRED",
                          "can_commit": False, "qmt_calls": 0}))
        return 2
    try:
        output = inspect(
            args.root, args.workspace, symbols=args.symbols,
            sample_count=args.sample_count)
    except (PreflightBlocked, REVIEW.PrecommitBlocked) as exc:
        print(json.dumps({"status": "S8_READONLY_PREFLIGHT_BLOCKED",
                          "reason": str(exc)[:100],
                          "can_commit": False, "qmt_calls": 0}))
        return 2
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        print(json.dumps({"status": "S8_READONLY_PREFLIGHT_BLOCKED",
                          "reason": "LOCAL_HISTORY_OR_LAYOUT_CHECK_FAILED",
                          "can_commit": False, "qmt_calls": 0}))
        return 2
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
