"""Bounded, read-only finance pending proof grouping and snapshot metadata sample.

No xtquant, Parquet row reads, payload hashing, writer locks or data writes.
Pin shape/reference presence is not an authenticity/rollback certificate.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from itertools import islice
import json
from pathlib import Path
import re
import sys

import market_center_finance_pending_triage as T

CN = timezone(timedelta(hours=8))
MAX_FILES_PER_DIR = 256
MAX_GLOBAL_FILES = 4096
MAX_GLOBAL_CANDIDATE_BYTES = 40 * 1024 * 1024 * 1024
MAX_PIN_BYTES = 16 * 1024
SNAP = re.compile(r"(\d{4}-\d{2}-\d{2})-[a-f0-9]{16}\.parquet")
PIN = re.compile(r"(\d{4}-\d{2}-\d{2})\.json")
SHA256 = re.compile(r"[a-f0-9]{64}")
# Defined by qmt_capital_semantic_proof._report(). Unrecognized statuses
# are counted separately, never treated as an approved waiver.
KNOWN_PROOF_CLASSES = frozenset({
    "BASELINE_MISSING", "HISTORICAL_DUPLICATE_RAW_RECORD",
    "M_QUARTER_FIELD_MISSING", "FRESH_DUPLICATE_REPORT_KEY",
    "REPORT_KEYS_ADDED_OR_REMOVED",
    "HISTORICAL_BUSINESS_FIELD_REVISION",
    "BUSINESS_OR_DATE_FIELD_CHANGED",
    "M_QUARTER_ONLY_CANDIDATE", "NO_CHANGE",
    "UNVERIFIED_MALFORMED_OR_UNKEYED_RECORD",
})


class SnapshotReviewBlocked(ValueError):
    """Untrusted or changed evidence; do not infer repair permission."""


def _secure(path: Path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise SnapshotReviewBlocked("redirected_finance_snapshot_path")


def _root(market_root: Path) -> Path:
    if (not market_root.is_absolute()
            or market_root.name.lower() != "allcycleastockdata"
            or not market_root.is_dir()):
        raise SnapshotReviewBlocked("canonical_market_root_required")
    _secure(market_root)
    finance = market_root / "qmt_extra" / "financial"
    _secure(finance)
    if not finance.is_dir():
        raise SnapshotReviewBlocked("finance_snapshot_directory_not_found")
    return finance


def _day(text: str):
    try:
        if date.fromisoformat(text).isoformat() != text:
            raise ValueError("not canonical")
    except ValueError as exc:
        raise SnapshotReviewBlocked("uncanonical_historical_snapshot_day") from exc


def _files(folder: Path, pattern: re.Pattern) -> list[Path]:
    _secure(folder)
    if not folder.exists():
        return []
    if not folder.is_dir():
        raise SnapshotReviewBlocked("finance_snapshot_folder_not_directory")
    result = []
    for path in islice(folder.iterdir(), MAX_FILES_PER_DIR + 1):
        if len(result) >= MAX_FILES_PER_DIR:
            raise SnapshotReviewBlocked("finance_snapshot_file_budget")
        _secure(path)
        if not path.is_file():
            raise SnapshotReviewBlocked("finance_snapshot_entry_not_file")
        match = pattern.fullmatch(path.name)
        if match is None:
            raise SnapshotReviewBlocked("unexpected_finance_snapshot_entry_name")
        _day(match.group(1))
        result.append(path)
    return result


def _inventory(finance: Path, code: str, table: str) -> dict:
    if T.STOCK.fullmatch(code) is None or table not in T.TABLES:
        raise SnapshotReviewBlocked("invalid_finance_snapshot_scope")
    base = finance / table / code
    snapshots = _files(base / "snapshots", SNAP)
    pins = _files(base / "active", PIN)
    by_name = {path.name for path in snapshots}
    if len(by_name) != len(snapshots):
        raise SnapshotReviewBlocked("duplicate_finance_snapshot_filename")
    pin_refs = 0
    for path in pins:
        if path.stat().st_size > MAX_PIN_BYTES:
            raise SnapshotReviewBlocked("finance_snapshot_pin_size_budget")
        raw = path.read_bytes()
        if len(raw) > MAX_PIN_BYTES:
            raise SnapshotReviewBlocked("finance_snapshot_pin_read_budget")
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise SnapshotReviewBlocked("malformed_finance_snapshot_pin") from exc
        day = path.name[:10]
        if (type(doc) is not dict
                or doc.get("format") != "qmt_financial_active_v1"
                or doc.get("symbol") != code or doc.get("table") != table
                or doc.get("asof") != day
                or type(doc.get("filename")) is not str
                or SNAP.fullmatch(doc["filename"]) is None
                or not doc["filename"].startswith(day + "-")
                or type(doc.get("sha256")) is not str
                or SHA256.fullmatch(doc["sha256"]) is None
                or doc["filename"] not in by_name):
            raise SnapshotReviewBlocked("unmatched_finance_snapshot_pin_reference")
        pin_refs += 1
    candidate_bytes = sum(path.stat().st_size for path in snapshots)
    return {
        "stock": code, "table": table,
        "immutable_snapshot_candidates": len(snapshots),
        "active_pin_metadata": len(pins),
        "pin_references_structurally_present": pin_refs,
        "snapshot_candidate_bytes": candidate_bytes,
        "local_snapshot_candidates_exist": bool(snapshots),
        "content_sha256_verified": False,
        "active_pin_content_verified": False,
        "financial_business_values_read": False,
        "rollback_verified": False,
    }


def _pick_samples(rows: list[dict]) -> list[dict]:
    """At most two per first-blocker table: oldest and newest pending asof."""
    by_table = {}
    for row in rows:
        by_table.setdefault(row["first_table"], []).append(row)
    result = []
    for table in T.TABLES:
        items = by_table.get(table, [])
        if not items:
            continue
        oldest = sorted(items, key=lambda x: (x["asof"], -x["attempts"], x["stock"]))[0]
        newest = sorted(items, key=lambda x: (x["asof"], x["attempts"], x["stock"]), reverse=True)[0]
        result.append(oldest)
        if newest["stock"] != oldest["stock"]:
            result.append(newest)
    return result


def review(state_module: Path | str, market_root: Path | str, *,
           now: datetime | None = None) -> dict:
    now = now or datetime.now(CN)
    if now.tzinfo is None or now.utcoffset() is None:
        raise SnapshotReviewBlocked("timezone_aware_clock_required")
    current = now.astimezone(CN)
    minute = current.hour * 60 + current.minute
    if 19 * 60 + 50 <= minute < 20 * 60 + 25:
        raise SnapshotReviewBlocked("reserved_2005_no_snapshot_inventory")
    # Reuse P2's strict per-entry and before/after ledger SHA checks.
    first = T.summarize_pending(state_module)
    ledger_path = T._trusted_path(Path(state_module))
    ledger, ledger_sha = T._read_ledger(ledger_path)
    if ledger_sha != first["progress_sha256"]:
        raise SnapshotReviewBlocked("finance_progress_changed_before_inventory")
    classes = Counter()
    candidates = []
    for code, item in ledger["pending"].items():
        if item["reason"] != "SOURCE_HISTORY_CONFLICT":
            continue
        match = T.CONFLICT.fullmatch(item["detail"])
        if match is None or match.group(1) != code:
            continue  # P2 reports it as unclassified; never select it.
        table, _kind, _count = T._parse_first_conflict(code, item["detail"])
        if table == "UNCLASSIFIED":
            continue
        proof = match.group(4)
        if proof is not None:
            proof = (proof if proof in KNOWN_PROOF_CLASSES
                     else "UNRECOGNIZED_PROOF_STATUS")
            classes[proof] += 1
        candidates.append({
            "stock": code, "first_table": table,
            "asof": item["asof"], "attempts": item["attempts"],
            "capital_proof_class": proof,
        })
    selected = _pick_samples(candidates)
    finance = _root(Path(market_root))
    samples = []
    total_files = 0
    total_bytes = 0
    for row in selected:
        meta = _inventory(finance, row["stock"], row["first_table"])
        total_files += (meta["immutable_snapshot_candidates"]
                        + meta["active_pin_metadata"])
        total_bytes += meta["snapshot_candidate_bytes"]
        if total_files > MAX_GLOBAL_FILES or total_bytes > MAX_GLOBAL_CANDIDATE_BYTES:
            raise SnapshotReviewBlocked("finance_snapshot_global_inventory_budget")
        samples.append({
            "stock": row["stock"], "first_blocking_table": row["first_table"],
            "pending_asof": row["asof"], "attempts": row["attempts"],
            "capital_proof_class": row["capital_proof_class"],
            **meta,
        })
    _secure(ledger_path)
    if (ledger_path.stat().st_size > T.MAX_LEDGER_BYTES
            or sha256(ledger_path.read_bytes()).hexdigest() != ledger_sha):
        raise SnapshotReviewBlocked("finance_progress_changed_during_inventory")
    return {
        "status": "FINANCE_PENDING_SNAPSHOT_METADATA_READONLY_NOT_CERTIFIED",
        "observed_at_china": current.isoformat(),
        "progress_sha256": ledger_sha,
        "pending_total": first["pending_total"],
        "history_conflicts": first["conflict_total"],
        "capital_proof_rejection_counts": [
            {"proof_class": name, "count": count}
            for name, count in sorted(classes.items())
        ],
        "capital_proof_rejections_grouped": sum(classes.values()),
        "classified_first_blockers": first["conflict_first_table_classified"],
        "unclassified_first_blockers": first["conflict_first_table_unclassified"],
        "sample_rule": "MAX_TWO_PER_FIRST_BLOCKER_TABLE_OLDEST_AND_NEWEST",
        "samples": samples,
        "sample_count": len(samples),
        "sampled_local_candidate_files": total_files,
        "sampled_local_candidate_bytes": total_bytes,
        "only_first_blocking_table_inspected": True,
        "financial_payloads_read": False,
        "historical_business_fields_compared": False,
        "immutable_snapshot_content_verified": False,
        "source_authenticity_certified": False,
        "all_nine_tables_checked": False,
        "can_repair": False,
        "can_download": False,
        "can_execute": False,
        "market_file_writes": False,
        "qmt_calls": 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-module", type=Path, required=True)
    parser.add_argument("--market-root", type=Path, required=True)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({
            "status": "FINANCE_SNAPSHOT_REVIEW_EXPLICIT_READONLY_REQUIRED",
            "can_execute": False, "qmt_calls": 0, "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    try:
        report = review(args.state_module, args.market_root)
    except (T.PendingTriageBlocked, SnapshotReviewBlocked, OSError) as exc:
        print(json.dumps({
            "status": "FINANCE_SNAPSHOT_REVIEW_BLOCKED",
            "reason": str(exc)[:180],
            "can_execute": False, "qmt_calls": 0, "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
