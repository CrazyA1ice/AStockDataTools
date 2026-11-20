"""V2-D2C bounded historical finance version *metadata* closure, no writes.

The D2B inventory only looked at *run-day* snapshots. An old active pin or
older immutable snapshot may be needed to compare or roll back any
QMT financial correction. This module walks every date of the specified
failed-stock/table scopes, with strict file-count/size/time budgets.

It does not hash Parquet payloads, open market data, take the production
writer mutex, copy backups or authorize execution. Pin reference validation
is structural; content authenticity is NOT certified.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from itertools import islice
import json
import re

from market_center_v2_recovery_inventory import (
    FIN_TABLES, PreflightBlocked, CODE, _secure, _stat_file,
    inspect_recovery_prerequisites,
)

CN = timezone(timedelta(hours=8))
SNAP_RE = re.compile(r"(\d{4}-\d{2}-\d{2})-([0-9a-f]{16})\.parquet")
ACTIVE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.json")
SHA64_RE = re.compile(r"[0-9a-f]{64}")
MAX_FILES_PER_STOCK_TABLE = 512
MAX_TOTAL_FILES = 4800
MAX_TOTAL_CANDIDATE_BYTES = 40 * 1024 * 1024 * 1024
MAX_PIN_BYTES = 16 * 1024


def _read_pin(path: Path, symbol: str, table: str) -> dict:
    _secure(path)
    if path.stat().st_size > MAX_PIN_BYTES:
        raise PreflightBlocked("oversized_historical_finance_pin")
    raw = path.read_bytes()
    if len(raw) > MAX_PIN_BYTES:
        raise PreflightBlocked("finance_pin_read_budget_exceeded")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise PreflightBlocked("malformed_historical_finance_pin") from exc
    if type(doc) is not dict:
        raise PreflightBlocked("invalid_historical_pin_object")
    name = path.name
    match = ACTIVE_RE.fullmatch(name)
    if match is None:
        raise PreflightBlocked("unrecognized_finance_active_pin_filename")
    day = match.group(1)
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("not canonical")
    except ValueError as exc:
        raise PreflightBlocked("noncanonical_finance_active_date") from exc
    filename = doc.get("filename")
    if (doc.get("format") != "qmt_financial_active_v1"
            or doc.get("symbol") != symbol
            or doc.get("table") != table or doc.get("asof") != day
            or type(filename) is not str
            or SNAP_RE.fullmatch(filename) is None
            or not filename.startswith(day + "-")
            or type(doc.get("sha256")) is not str
            or SHA64_RE.fullmatch(doc["sha256"]) is None):
        raise PreflightBlocked("historical_finance_active_identity_mismatch")
    return {
        "asof": day, "filename": filename,
        "declared_snapshot_sha256": doc["sha256"],
        "pin_metadata_bytes": len(raw),
        "snapshot_content_hash_verified": False,
    }


def _entries(path: Path, suffix: str, *, cap: int):
    _secure(path)
    if not path.exists():
        return []
    if not path.is_dir():
        raise PreflightBlocked("invalid_historical_finance_folder_" + suffix)
    entries = []
    # .iterdir() is incremental and cap is fail-closed: even huge directories
    # cannot cause unbounded Python materialization.
    for item in islice(path.iterdir(), cap + 1):
        if len(entries) >= cap:
            raise PreflightBlocked("historical_finance_file_count_limit")
        _secure(item)
        if not item.is_file() or item.suffix.lower() != suffix:
            raise PreflightBlocked("unexpected_finance_history_entry")
        entries.append(item)
    return entries


def inventory_historical_versions(*, state_module: Path | str,
                                  market_root: Path | str,
                                  now: datetime | None = None) -> dict:
    """Safely inspect metadata of all 9 table histories for the FAILED batch."""
    now = now or datetime.now(CN)
    basic = inspect_recovery_prerequisites(
        state_module=state_module, market_root=market_root, now=now)
    market = Path(market_root)
    failed = basic["failed_batch"]
    if not failed:
        raise PreflightBlocked("no_verified_failed_stock_scope")
    finance = market / "qmt_extra" / "financial"
    if not basic["finance_storage_found"]:
        raise PreflightBlocked("finance_storage_missing_cannot_inventory_versions")
    scopes = []
    all_files = 0
    all_bytes = 0
    pin_count = 0
    snapshot_count = 0
    for symbol in failed:
        if CODE.fullmatch(symbol) is None:
            raise PreflightBlocked("invalid_failed_stock_symbol")
        for table in FIN_TABLES:
            parent = finance / table / symbol
            snap_dir = parent / "snapshots"
            pin_dir = parent / "active"
            _secure(parent)
            snap_files = _entries(
                snap_dir, ".parquet", cap=MAX_FILES_PER_STOCK_TABLE)
            pin_files = _entries(
                pin_dir, ".json", cap=MAX_FILES_PER_STOCK_TABLE)
            if len(snap_files) + len(pin_files) > MAX_FILES_PER_STOCK_TABLE:
                raise PreflightBlocked("historical_finance_scope_aggregate_limit")
            snapshots = {}
            scope_bytes = 0
            for item in snap_files:
                m = SNAP_RE.fullmatch(item.name)
                if m is None:
                    raise PreflightBlocked("unknown_finance_snapshot_name")
                try:
                    date.fromisoformat(m.group(1))
                except ValueError as exc:
                    raise PreflightBlocked("invalid_finance_snapshot_asof") from exc
                stat = _stat_file(item)
                snapshots[item.name] = stat
                scope_bytes += stat["bytes"]
            pins = []
            for item in pin_files:
                record = _read_pin(item, symbol, table)
                if record["filename"] not in snapshots:
                    raise PreflightBlocked("active_pin_refers_to_missing_snapshot")
                pins.append(record)
                scope_bytes += record["pin_metadata_bytes"]
            all_files += len(snapshots) + len(pins)
            all_bytes += scope_bytes
            pin_count += len(pins)
            snapshot_count += len(snapshots)
            if all_files > MAX_TOTAL_FILES:
                raise PreflightBlocked("historical_finance_global_file_budget")
            if all_bytes > MAX_TOTAL_CANDIDATE_BYTES:
                raise PreflightBlocked("historical_finance_global_byte_budget")
            scopes.append({
                "symbol": symbol, "table": table,
                "active_pin_count": len(pins),
                "immutable_snapshot_count": len(snapshots),
                "active_pin_references_present": True,
                "historical_snapshot_byte_total": sum(
                    item["bytes"] for item in snapshots.values()),
                "pin_metadata_byte_total": sum(
                    item["pin_metadata_bytes"] for item in pins),
                "snapshot_content_sha256_verified": False,
                "pins_content_sha256_verified": False,
                "historical_versions_backed_up": False,
                "restore_tested": False,
            })
    return {
        "status": "V2D2C_HISTORICAL_FINANCE_METADATA_NOT_RESTORABLE",
        "run_day": basic["run_day"],
        "failed_batch": failed,
        "observed_at_china": now.astimezone(CN).isoformat(),
        "receipt_sha256": basic["receipt_sha256"],
        "finance_progress_sha256": basic["finance_progress_sha256"],
        "canonical_code_fingerprints": basic["code_fingerprints"],
        "scopes": scopes,
        "scope_count": len(scopes),
        "historical_snapshot_count": snapshot_count,
        "historical_active_pin_count": pin_count,
        "historical_candidate_bytes": all_bytes,
        "zero_run_day_bytes_do_not_mean_no_historical_versions": True,
        "scope_is_limited_to_original_failed_stock_batch": True,
        "progress_ledger_bytes_not_included_in_estimate": True,
        "snapshot_content_sha256_verified": False,
        "backups_created": False,
        "rollback_verified": False,
        "canonical_worker_hash_approved": False,
        "writer_mutex_owned": False,
        "cross_day_old_daily_replay_allowed": False,
        "execution_blockers": [
            "no_atomic_production_writer_mutex",
            "no_preapproved_worker_sha_and_deployment",
            "no_verified_full_snapshot_backup",
            "no_verified_progress_backup",
            "no_verified_rollback",
            "no_current_qmt_recheck_inside_executor",
            "daily_sweep_cross_day_policy_not_approved",
        ],
        "can_execute": False, "can_download": False,
        "can_modify_finance_progress": False,
        "qmt_calls": 0, "market_file_writes": False, "files_created": 0,
    }
