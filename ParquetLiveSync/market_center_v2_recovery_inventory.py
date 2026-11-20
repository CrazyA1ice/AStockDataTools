"""V2-D2B strictly read-only production fingerprint + finance backup scope PREVIEW.

This report does not acquire the writer mutex, approve a deployed version,
copy/create a backup, load xtquant, download, mutate financial progress, or
authorize an old daily sweep to run. The *executor* must independently and
atomically acquire the same named production mutex and recheck everything.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
from itertools import islice
from pathlib import Path
import re

from market_center_v2_faults import diagnose_latest, FaultEvidenceBlocked

CN = timezone(timedelta(hours=8))
CODE = re.compile(r"\d{6}\.(?:SH|SZ|BJ)")
HEX_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
FIN_TABLES = (
    "Balance", "Income", "CashFlow", "Capital", "Top10FlowHolder",
    "Top10Holder", "HolderNum", "PershareIndex", "PerShare",
)
CODE_FILES = (
    "qmt_extra_financial_cache_import.py",
    "qmt_extra_financial_cache_worker.py",
    "qmt_extra_data.py",
    "run-qmt-financial-daily.ps1",
    "scheduled-afternoon-update.ps1",
)
MAX_CODE_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOTS_PER_SCOPE = 16
MAX_SYMBOLS = 20
MAX_METADATA_BYTES = 16 * 1024
MAX_CANDIDATE_BYTES = 2 * 1024 * 1024 * 1024


class PreflightBlocked(ValueError):
    """Fail closed when even read-only source identity is not established."""


def _clean_path(path: Path, *, expected_name: str):
    if (not path.is_absolute() or path.name.lower() != expected_name.lower()
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise PreflightBlocked("untrusted_" + expected_name.lower() + "_path")
    if not path.is_dir():
        raise PreflightBlocked("missing_" + expected_name.lower() + "_directory")


def _secure(path: Path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise PreflightBlocked("redirected_finance_inventory_path")


def _fingerprint(path: Path) -> dict:
    _secure(path)
    if not path.is_file():
        return {"name": path.name, "status": "CANONICAL_FILE_MISSING",
                "sha256": None, "bytes": None, "approved": False}
    length = path.stat().st_size
    if length > MAX_CODE_BYTES:
        raise PreflightBlocked("oversized_canonical_code_file")
    raw = path.read_bytes()
    if len(raw) > MAX_CODE_BYTES:
        raise PreflightBlocked("canonical_code_bytes_exceeded")
    return {
        "name": path.name, "status": "FINGERPRINT_OBSERVED_NOT_APPROVED",
        "sha256": sha256(raw).hexdigest(), "bytes": len(raw),
        "approved": False,
    }


def _stat_file(path: Path) -> dict:
    _secure(path)
    if not path.is_file():
        raise PreflightBlocked("nonfile_candidate_in_finance_snapshot_scope")
    stat = path.stat()
    if stat.st_size < 0 or stat.st_size > MAX_CANDIDATE_BYTES:
        raise PreflightBlocked("oversized_snapshot_candidate")
    return {"name": path.name, "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "content_sha256_verified": False}


def _scope_inventory(finance_root: Path, symbol: str, table: str, day: str) -> dict:
    if CODE.fullmatch(symbol) is None or table not in FIN_TABLES or HEX_DAY.fullmatch(day) is None:
        raise PreflightBlocked("untrusted_finance_inventory_scope")
    parent = finance_root / table / symbol
    active = parent / "active" / (day + ".json")
    snapshots = parent / "snapshots"
    _secure(parent)
    _secure(active)
    _secure(snapshots)
    active_meta = None
    if active.exists():
        if active.stat().st_size > MAX_METADATA_BYTES:
            raise PreflightBlocked("oversized_financial_active_pin")
        active_meta = _stat_file(active)
    listed = []
    if snapshots.exists():
        if not snapshots.is_dir():
            raise PreflightBlocked("invalid_financial_snapshots_directory")
        items = snapshots.glob(day + "-*.parquet")
        for item in islice(items, MAX_SNAPSHOTS_PER_SCOPE + 1):
            if len(listed) >= MAX_SNAPSHOTS_PER_SCOPE:
                raise PreflightBlocked("finance_scope_has_too_many_snapshot_candidates")
            if re.fullmatch(re.escape(day) + r"-[a-f0-9]{16}\.parquet",
                            item.name) is None:
                raise PreflightBlocked("finance_snapshot_filename_not_content_addressed")
            listed.append(_stat_file(item))
    return {
        "symbol": symbol, "table": table, "run_day": day,
        "active_pin": active_meta,
        "same_day_snapshot_candidates": sorted(listed, key=lambda x: x["name"]),
        "candidate_count": len(listed),
        "pin_references_verified": False,
        "snapshot_content_verified": False,
        "backup_created": False,
    }


def inspect_recovery_prerequisites(*, state_module: Path | str,
                                   market_root: Path | str,
                                   now: datetime | None = None) -> dict:
    """Observe bounded metadata for a proposed recovery scope, NEVER execute."""
    module = Path(state_module)
    market = Path(market_root)
    _clean_path(module, expected_name="ParquetLiveSync")
    _clean_path(market, expected_name="AllCycleAStockData")
    now = now or datetime.now(CN)
    if now.tzinfo is None or now.utcoffset() is None:
        raise PreflightBlocked("timezone_aware_clock_required")
    china = now.astimezone(CN)
    minute = china.hour * 60 + china.minute
    # An inventory is read-only but still touches snapshot metadata. Leave
    # extra margin either side of the scheduled market writer's guard.
    if 19 * 60 + 50 <= minute < 20 * 60 + 25:
        raise PreflightBlocked("reserved_2005_no_finance_file_inventory")
    source = diagnose_latest(module, now=now)
    preview = source["finance_resume_preview"]
    selected = preview.get("failed_batch", [])
    if (type(selected) is not list or len(selected) > MAX_SYMBOLS
            or any(type(symbol) is not str or CODE.fullmatch(symbol) is None
                   for symbol in selected)
            or selected != sorted(set(selected))):
        raise PreflightBlocked("untrusted_failed_batch_scope")
    checked = [_fingerprint(module / name) for name in CODE_FILES]
    run_day = source["run_day"]
    if HEX_DAY.fullmatch(run_day) is None:
        raise PreflightBlocked("invalid_run_day_inventory_scope")
    finance_root = market / "qmt_extra" / "financial"
    _secure(finance_root)
    has_finance_root = finance_root.is_dir()
    entries = []
    if has_finance_root:
        for symbol in selected:
            for table in FIN_TABLES:
                entries.append(_scope_inventory(
                    finance_root, symbol, table, run_day))
    blockers = []
    if preview["status"] != "PREVIEW_CHECKS_PASSED_EXECUTION_STILL_DISABLED":
        blockers.append("static_or_date_resume_gate_blocked")
    if not selected:
        blockers.append("no_verified_failed_batch")
    if not has_finance_root:
        blockers.append("finance_storage_root_not_found")
    if any(item["status"] != "FINGERPRINT_OBSERVED_NOT_APPROVED"
           for item in checked):
        blockers.append("canonical_code_files_missing")
    blockers.extend([
        "canonical_code_hashes_not_independently_approved",
        "finance_backup_not_created",
        "finance_immutable_snapshot_contents_not_verified",
        "production_writer_mutex_not_exclusively_acquired",
        "qmt_connection_not_reconfirmed_inside_executor",
    ])
    china = now.astimezone(CN)
    if china.date().isoformat() != run_day:
        blockers.append("previous_run_day_requires_daily_sweep_carry_forward_review")
    return {
        "status": "V2D2B_READONLY_RECOVERY_INVENTORY_NOT_EXECUTABLE",
        "run_day": run_day,
        "observed_at_china": china.isoformat(),
        "receipt_sha256": source["receipt_sha256"],
        "finance_progress_sha256": source["finance_progress_sha256"],
        "failed_batch": selected,
        "saved_daily_cursor": preview.get("saved_daily_cursor"),
        "static_evidence_preview_status": preview.get("status"),
        "code_fingerprints": checked,
        "canonical_code_hash_approved": False,
        "finance_storage_found": has_finance_root,
        "finance_scope_count": len(entries),
        "finance_scope_inventory": entries,
        "backup_plan": {
            "planned_only": True,
            "financial_progress_json_in_scope": True,
            "active_pins_and_matching_run_day_snapshots_in_scope": True,
            "all_historical_finance_versions_backed_up": False,
            "backup_created": False, "backup_integrity_verified": False,
            "rollback_tested": False,
            "estimated_candidate_bytes": sum(
                sum(p["bytes"] for p in e["same_day_snapshot_candidates"]) +
                (e["active_pin"] or {}).get("bytes", 0) for e in entries),
        },
        "resume_policy": (
            "BEIJING_SAME_DAY_STATIC_PREVIEW_ONLY"
            if china.date().isoformat() == run_day else
            "CROSS_DAY_NO_OLD_DAILY_REPLAY; "
            "INSPECT_ORIGINAL_DAILY_SWEEP_CARRY_FORWARD_RULE"),
        "blockers": blockers,
        "can_execute": False,
        "can_download": False,
        "can_modify_finance_progress": False,
        "can_acquire_writer_mutex": False,
        "qmt_calls": 0,
        "market_file_writes": False,
        "files_created": 0,
    }
