"""P4: bounded immutable finance snapshot identity verification, read only.

Uses the existing canonical Parquet fingerprint/identity validator on at most
8 P3-selected stock/table scopes. Never connects to xtquant or writes files.
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

import pyarrow.parquet as pq

import market_center_finance_pending_snapshot_review as P3
import market_center_finance_pending_triage as P2
import qmt_extra_data as E

MAX_SAMPLES = 8
MAX_SNAPSHOTS = 32
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ROWS_PER_FILE = 20000
MAX_ROW_GROUPS = 16
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
EXPECTED_SHA = re.compile(r"[a-fA-F0-9]{64}")


class IntegrityBlocked(ValueError):
    """Insufficient or inconsistent evidence; never authorize a repair."""


def _reader_budget(path: Path):
    P3._secure(path)
    if not path.is_file() or path.is_symlink():
        raise IntegrityBlocked("snapshot_not_regular_file")
    if not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise IntegrityBlocked("snapshot_compressed_byte_budget")
    pf = pq.ParquetFile(path)
    try:
        meta = pf.metadata
        if (meta.num_rows <= 0 or meta.num_rows > MAX_ROWS_PER_FILE
                or meta.num_row_groups > MAX_ROW_GROUPS
                or sum(meta.row_group(i).total_byte_size
                       for i in range(meta.num_row_groups))
                > MAX_DECOMPRESSED_BYTES):
            raise IntegrityBlocked("snapshot_arrow_decode_budget")
    finally:
        pf.close()


def _snapshot(entry: dict, path: Path, extra: Path):
    code, table = entry["stock"], entry["first_blocking_table"]
    m = P3.SNAP.fullmatch(path.name)
    if m is None:
        raise IntegrityBlocked("unrecognized_snapshot_file")
    asof = m.group(1)
    before = path.stat()
    _reader_budget(path)
    # Existing production validator checks original RAW_SCHEMA, every row
    # identity and content-addressed filename. Never call its write helpers.
    arr = E._verify_financial_snapshot_file(extra, code, table, asof, path)
    if arr.num_rows > MAX_ROWS_PER_FILE:
        raise IntegrityBlocked("snapshot_rows_exceeded_post_read")
    # Only historical counts leave the process. Raw financial fields/keys do not.
    out = {
        "asof": asof, "rows": arr.num_rows,
        "filename_content_fingerprint_verified": True,
        "schema_and_stock_table_identity_verified": True,
        "original_financial_values_output": False,
    }
    if table == "Capital":
        valid_keys = Counter()
        invalid_keys = 0
        for value in arr.column("payload_json").to_pylist():
            try:
                row = json.loads(value)
                if type(row) is not dict:
                    raise ValueError("capital payload not mapping")
                key = row.get("m_timetag")
                if key is None or type(key) in (dict, list, bool) or str(key).strip() in ("", "0"):
                    raise ValueError("unkeyed capital report")
                valid_keys[E.canonical_json(key)] += 1
            except (ValueError, TypeError, OverflowError):
                invalid_keys += 1
        out["historical_report_keys_observed"] = len(valid_keys)
        out["historical_report_key_duplicate_rows"] = sum(
            max(0, count - 1) for count in valid_keys.values())
        out["historical_unkeyed_rows"] = invalid_keys
    after = path.stat()
    if (before.st_size != after.st_size or
            before.st_mtime_ns != after.st_mtime_ns):
        raise IntegrityBlocked("snapshot_changed_during_read")
    return out


def verify(state_module: Path | str, market_root: Path | str,
           expected_progress_sha256: str) -> dict:
    if (type(expected_progress_sha256) is not str or
            EXPECTED_SHA.fullmatch(expected_progress_sha256) is None):
        raise IntegrityBlocked("explicit_expected_progress_sha_required")
    expected = expected_progress_sha256.lower()
    # Recheck P3 first. It denies the 20:05 writer window, symlinks,
    # unmatched pins, ledger drift and unbounded filesystem enumeration.
    report = P3.review(state_module, market_root)
    if report["progress_sha256"] != expected:
        raise IntegrityBlocked("financial_ledger_sha_changed")
    samples = report["samples"]
    if not 1 <= len(samples) <= MAX_SAMPLES:
        raise IntegrityBlocked("empty_or_oversized_verified_sample_scope")
    extra = Path(market_root) / "qmt_extra"
    finance = extra / "financial"
    if P3._root(Path(market_root)) != finance:
        raise IntegrityBlocked("untrusted_market_root")
    checked = []
    nfiles = 0
    nbytes = 0
    pin_verified = 0
    for entry in samples:
        code = entry["stock"]
        table = entry["first_blocking_table"]
        files = P3._files(finance / table / code / "snapshots", P3.SNAP)
        pins = P3._files(finance / table / code / "active", P3.PIN)
        if not files:
            raise IntegrityBlocked("missing_selected_snapshot_scope")
        if len(files) != entry["immutable_snapshot_candidates"]:
            raise IntegrityBlocked("snapshot_count_changed_since_p3_review")
        nfiles += len(files)
        nbytes += sum(p.stat().st_size for p in files)
        if nfiles > MAX_SNAPSHOTS or nbytes > MAX_TOTAL_BYTES:
            raise IntegrityBlocked("bounded_sample_snapshot_byte_budget")
        originals = []
        for path in sorted(files):
            originals.append(_snapshot(entry, path, extra))
        # For every day, canonical selected snapshot is unambiguous.
        for d in sorted({x["asof"] for x in originals}):
            chosen = E._financial_snapshot_file(extra, code, table, d)
            if chosen is None or chosen.name not in {p.name for p in files}:
                raise IntegrityBlocked("snapshot_selection_ambiguous_or_missing")
        for pin in pins:
            p = json.loads(pin.read_text(encoding="utf-8"))
            selected = finance / table / code / "snapshots" / p["filename"]
            P3._secure(selected)
            # Hash bytes of pinned files only, bounded by MAX_FILE_BYTES.
            if sha256(selected.read_bytes()).hexdigest() != p["sha256"]:
                raise IntegrityBlocked("active_pin_sha256_mismatch")
            pin_verified += 1
        checked.append({
            "stock": code, "first_blocking_table": table,
            "historical_snapshot_rows": sum(x["rows"] for x in originals),
            "historical_snapshot_versions": len(originals),
            "snapshot_checks": originals,
            "active_pin_sha256_checks_passed": len(pins),
            "fresh_qmt_financial_source_checked": False,
            "report_keys_compared_to_current_qmt": False,
        })
    # A second P2 read validates ledger identity after the Parquet checks.
    final = P2.summarize_pending(state_module)
    if final["progress_sha256"] != expected:
        raise IntegrityBlocked("financial_ledger_sha_changed_during_verification")
    return {
        "status": "FINANCE_P4_LOCAL_SNAPSHOT_INTEGRITY_NOT_SOURCE_CERTIFICATION",
        "progress_sha256": expected,
        "sample_count": len(checked),
        "immutable_snapshot_files_verified": nfiles,
        "active_pin_sha256_verified": pin_verified,
        "snapshot_compressed_bytes_checked": nbytes,
        "samples": checked,
        "local_file_integrity_only": True,
        "financial_original_values_emitted": False,
        "source_authenticity_certified": False,
        "fresh_qmt_report_keys_compared": False,
        "historical_finance_completeness_certified": False,
        "nine_tables_verified_per_stock": False,
        "can_download": False,
        "can_repair": False,
        "can_execute": False,
        "market_file_writes": False,
        "qmt_calls": 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-module", type=Path, required=True)
    parser.add_argument("--market-root", type=Path, required=True)
    parser.add_argument("--expected-progress-sha256", required=True)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({
            "status": "FINANCE_P4_EXPLICIT_READONLY_REQUIRED",
            "can_execute": False, "qmt_calls": 0, "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    try:
        result = verify(
            args.state_module, args.market_root, args.expected_progress_sha256)
    except (IntegrityBlocked, P3.SnapshotReviewBlocked,
            P2.PendingTriageBlocked, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "FINANCE_P4_LOCAL_SNAPSHOT_INTEGRITY_BLOCKED",
            "reason": str(exc)[:180],
            "can_execute": False, "qmt_calls": 0, "market_file_writes": False,
        }, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
