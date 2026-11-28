#!/usr/bin/env python3
"""Read-only content-level verification of ONLY P3.20-pinned old finance files.

Parquet schema, snapshot row identity, canonical filename content fingerprint,
and saved historical row union are checked. NO fresh QMT source, financial
repairs, scheduled run receipts, market admission or write operation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re

import pyarrow.parquet as pq

import market_finance_adjustment_progress_readonly as LEDGER
import market_finance_pending_reason_triage_readonly as TRIAGE
import market_finance_prior_snapshot_census_readonly as PRIOR
import qmt_extra_data as EXTRA
import qmt_extra_financial_cache_import as IMPORT

FORMAT = "astock_finance_prior_raw_content_readonly_v1"
STATUS = "VERIFIED_STORED_PRIOR_RAW_ROWS_ONLY_FRESH_SOURCE_NOT_CHECKED"
MAX_SNAPSHOT_ROWS = 200000
MAX_TOTAL_ROWS = 1000000
MAX_UNCOMPRESSED_PER_FILE = 64 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 256 * 1024 * 1024
MAX_PAYLOAD_BYTES = 256 * 1024 * 1024
MAX_PAYLOAD_SINGLE_BYTES = 1024 * 1024
MAX_UNION_DISTINCT_PER_SCOPE = 200000


class ContentError(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise ContentError(code)


def _json_constant(value):
    raise ContentError("PRIOR_FINANCE_NON_FINITE_JSON_LITERAL")


def _parse_payload(value):
    need(type(value) is str, "PRIOR_FINANCE_PAYLOAD_NOT_STRING")
    need(0 < len(value.encode("utf-8")) <= MAX_PAYLOAD_SINGLE_BYTES,
         "PRIOR_FINANCE_SINGLE_PAYLOAD_BUDGET")
    try:
        obj = json.loads(value, object_pairs_hook=PRIOR._unique_pairs,
                         parse_constant=_json_constant)
    except (UnicodeError, ValueError, TypeError) as exc:
        if isinstance(exc, ContentError):
            raise
        raise ContentError("PRIOR_FINANCE_PAYLOAD_INVALID_JSON") from exc
    need(type(obj) is dict and type(obj.get("_index")) is str,
         "PRIOR_FINANCE_PAYLOAD_ROW_INDEX_INVALID")
    return obj


def _arrow_metadata(path):
    """Bound decompressed Arrow allocation *before* any Parquet table read."""
    try:
        reader = pq.ParquetFile(path)
        try:
            meta = reader.metadata
            need(reader.schema_arrow == EXTRA.RAW_SCHEMA,
                 "PRIOR_FINANCE_ARROW_SCHEMA_MISMATCH")
            need(0 < meta.num_rows <= MAX_SNAPSHOT_ROWS,
                 "PRIOR_FINANCE_SNAPSHOT_ROW_LIMIT")
            decoded = sum(meta.row_group(i).total_byte_size
                          for i in range(meta.num_row_groups))
            need(0 < decoded <= MAX_UNCOMPRESSED_PER_FILE,
                 "PRIOR_FINANCE_SNAPSHOT_DECODE_BUDGET")
            return meta.num_rows, decoded
        finally:
            reader.close()
    except ContentError:
        raise
    except Exception as exc:
        # Do not print private paths or proprietary payloads.
        raise ContentError("PRIOR_FINANCE_ARROW_METADATA_READ_FAILED") from exc


def _read_old_selected(path, extra, stock, table_name, day, expected_sha):
    """Verify exact old immutable bytes before AND after source-format parsing."""
    before = PRIOR._identity(os.stat(path, follow_symlinks=False))
    digest, size = PRIOR._read_file(path, PRIOR.MAX_SINGLE_FILE_BYTES)
    need(digest == expected_sha, "PRIOR_FINANCE_PRE_READ_PHYSICAL_SHA_CHANGED")
    row_count, decoded = _arrow_metadata(path)
    try:
        # The original production read-only validator strictly checks
        # RAW_SCHEMA, asof/symbol/table/index, filename canonical content hash.
        table = EXTRA._verify_financial_snapshot_file(
            extra, stock, table_name, day, path)
    except Exception as exc:
        raise ContentError("PRIOR_FINANCE_ORIGINAL_ROW_AND_FILENAME_PROOF_FAILED") from exc
    need(table.num_rows == row_count and table.schema == EXTRA.RAW_SCHEMA,
         "PRIOR_FINANCE_ARROW_COUNT_CHANGED")
    saved = []
    payload_bytes = 0
    for record in table.column("payload_json").to_pylist():
        need(type(record) is str, "PRIOR_FINANCE_INVALID_RAW_COLUMN")
        payload_bytes += len(record.encode("utf-8"))
        need(payload_bytes <= MAX_PAYLOAD_BYTES,
             "PRIOR_FINANCE_PAYLOAD_BYTES_LIMIT")
        saved.append(_parse_payload(record))
    need(len(saved) == row_count, "PRIOR_FINANCE_PAYLOAD_ROW_COUNT_CHANGED")
    digest_after, size_after = PRIOR._read_file(
        path, PRIOR.MAX_SINGLE_FILE_BYTES)
    need(digest_after == expected_sha and size_after == size
         and PRIOR._identity(os.stat(path, follow_symlinks=False)) == before,
         "PRIOR_FINANCE_FILE_CHANGED_DURING_ARROW_READ")
    return saved, row_count, decoded, payload_bytes


def _scopes(pending):
    result = []
    for stock, entry in pending.items():
        if entry["reason"] != "SOURCE_HISTORY_CONFLICT":
            continue
        kind, table = TRIAGE._conflict_kind(stock, entry.get("detail"))
        need(kind != "UNCLASSIFIED_DETAIL" and table in EXTRA.FIN_TABLES,
             "PRIOR_FINANCE_CONFLICT_SCOPE_UNCLASSIFIED")
        result.append((table, stock))
    result.sort()
    need(len(result) <= PRIOR.MAX_CONFLICT_SCOPES,
         "PRIOR_FINANCE_SCOPE_COUNT_LIMIT")
    return result


def inspect(module_root, stock_root, expected_ledger_sha256,
            expected_snapshot_manifest_sha256):
    need(type(expected_ledger_sha256) is str
         and bool(TRIAGE.HEX.fullmatch(expected_ledger_sha256)),
         "PRIOR_FINANCE_EXPECTED_LEDGER_SHA_INVALID")
    need(type(expected_snapshot_manifest_sha256) is str
         and bool(TRIAGE.HEX.fullmatch(expected_snapshot_manifest_sha256)),
         "PRIOR_FINANCE_EXPECTED_MANIFEST_SHA_INVALID")
    # Independently verify every physical old Parquet and active pin via P3.20.
    original = PRIOR.inspect(module_root, stock_root,
                             expected_ledger_sha256)
    need(original["physical_snapshot_manifest_sha256"]
         == expected_snapshot_manifest_sha256.lower(),
         "PRIOR_FINANCE_PINNED_SNAPSHOT_MANIFEST_SHA_MISMATCH")
    need(original["conflict_scopes_missing_snapshot_directory"] == 0
         and original["conflict_scopes_with_snapshot_directory"]
         == original["scopes_from_exact_conflict_details"],
         "PRIOR_FINANCE_MISSING_OLD_SNAPSHOT_SCOPE")
    files_declared = original["physical_snapshot_files_sha_verified"]
    required_pins = ({"ACTIVE_PIN_SELECTED_BYTES_MATCH": files_declared}
                     if files_declared else {})
    need(original["asof_active_pin_resolution_status_counts"]
         == required_pins,
         "PRIOR_FINANCE_OLD_SNAPSHOT_ACTIVE_PIN_NOT_UNIQUE")

    work, extra_string = LEDGER._roots(module_root, stock_root)
    extra = Path(extra_string)
    before = LEDGER._bytes(work, PRIOR.NAME)
    need(before is not None
         and before["sha256"] == expected_ledger_sha256.lower(),
         "PRIOR_FINANCE_LEDGER_SHA_CHANGED")
    LEDGER._cache(before["data"], extra_string)
    scopes = _scopes(before["data"]["pending"])
    need(len(scopes) == original["scopes_from_exact_conflict_details"],
         "PRIOR_FINANCE_SCOPE_COUNT_CHANGED")

    totals = defaultdict(Counter)
    files = 0
    raw_rows = 0
    decompressed = 0
    payload_bytes_total = 0
    source_union_manifest = sha256()
    base = extra / "financial"
    for table_name, stock in scopes:
        folder = base / table_name / stock / "snapshots"
        PRIOR._dir(folder)
        names, directory_identity = PRIOR._snapshot_names(folder)
        need(bool(names), "PRIOR_FINANCE_EMPTY_OLD_SNAPSHOT_SCOPE")
        by_day = defaultdict(list)
        for filename in names:
            by_day[filename[:10]].append(filename)
        union = Counter()
        table_counts = totals[table_name]
        table_counts["source_conflict_scopes"] += 1
        for day, candidates in sorted(by_day.items()):
            active = PRIOR._active_pin(
                folder, stock, table_name, day, candidates)
            need(type(active) is dict
                 and active["filename"] in candidates,
                 "PRIOR_FINANCE_NO_VALID_ACTIVE_SELECTION")
            # P3.20 exact manifest pin guards all prior names and hashes.
            # Only the explicitly active version participates in old union.
            filename = active["filename"]
            path = folder / filename
            count, bound = _arrow_metadata(path)
            need(files < PRIOR.MAX_TOTAL_FILES
                 and raw_rows + count <= MAX_TOTAL_ROWS
                 and decompressed + bound <= MAX_TOTAL_UNCOMPRESSED,
                 "PRIOR_FINANCE_TOTAL_ARROW_BUDGET")
            saved, checked, decoded, payload_size = _read_old_selected(
                path, extra, stock, table_name, day, active["sha256"])
            need(checked == count and decoded == bound,
                 "PRIOR_FINANCE_METADATA_DRIFT")
            payload_bytes_total += payload_size
            need(payload_bytes_total <= MAX_PAYLOAD_BYTES,
                 "PRIOR_FINANCE_TOTAL_PAYLOAD_BUDGET")
            # Identical semantic expression to importer._prior_rows(): each
            # date contributes Counter of original raw rows without _index,
            # historical union takes per-row maximum multiplicity, not sum.
            try:
                union |= IMPORT._rows(saved)
            except Exception as exc:
                raise ContentError("PRIOR_FINANCE_OLD_UNION_CANNOT_BE_COMPUTED") from exc
            need(len(union) <= MAX_UNION_DISTINCT_PER_SCOPE,
                 "PRIOR_FINANCE_UNION_DISTINCT_BUDGET")
            files += 1
            raw_rows += checked
            decompressed += decoded
            table_counts["active_snapshot_days_checked"] += 1
            table_counts["raw_rows_checked"] += checked
        table_counts["old_union_distinct_raw_rows"] += len(union)
        table_counts["old_union_multiset_rows"] += sum(union.values())
        # Scope IDs and raw row content are never emitted. The final digest is
        # only a change detector for these exact stored old union contents.
        scope_digest = sha256()
        for row, count in sorted(union.items()):
            scope_digest.update(json.dumps(
                [row, count], separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8") + b"\n")
        source_union_manifest.update(json.dumps(
            [table_name, stock, scope_digest.hexdigest()],
            separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8") + b"\n")
        need(PRIOR._identity(os.stat(folder, follow_symlinks=False))
             == directory_identity, "PRIOR_FINANCE_DIRECTORY_CHANGED")

    need(files == original["physical_snapshot_files_sha_verified"],
         "PRIOR_FINANCE_NOT_ALL_PINNED_OLD_SNAPSHOTS_CHECKED")
    # Cross-check all immutable physical SHA and active pins one more time
    # against the exact P3.20 manifest; do not claim this is a writer lock.
    after = PRIOR.inspect(module_root, stock_root,
                          expected_ledger_sha256)
    need(after["physical_snapshot_manifest_sha256"]
         == original["physical_snapshot_manifest_sha256"]
         and after["asof_active_pin_resolution_status_counts"]
         == original["asof_active_pin_resolution_status_counts"]
         and after["physical_snapshot_files_sha_verified"] == files,
         "PRIOR_FINANCE_PINNED_SNAPSHOT_PHYSICAL_MANIFEST_CHANGED")
    end = LEDGER._bytes(work, PRIOR.NAME)
    need(end is not None
         and end["sha256"] == before["sha256"]
         and end["identity"] == before["identity"],
         "PRIOR_FINANCE_PINNED_LEDGER_CHANGED_DURING_SCAN")
    return {
        "format": FORMAT,
        "status": STATUS,
        "pinned_financial_cache_ledger_sha256": before["sha256"],
        "verified_prior_snapshot_manifest_sha256":
            original["physical_snapshot_manifest_sha256"],
        "prior_content_union_manifest_sha256":
            source_union_manifest.hexdigest(),
        "conflict_scopes_checked": len(scopes),
        "active_old_snapshot_files_content_verified": files,
        "active_old_raw_rows_checked": raw_rows,
        "old_raw_payload_bytes_parsed": payload_bytes_total,
        "arrow_uncompressed_bytes_bounded": decompressed,
        "table_scoped_counts": {
            key: dict(sorted(counts.items()))
            for key, counts in sorted(totals.items())},
        "old_selected_historical_counter_union_computed": True,
        "all_physical_old_snapshot_manifest_rechecked": True,
        "source_ledger_and_old_files_atomic_snapshot_certified": False,
        "new_finance_source_consulted": False,
        "new_and_old_finance_records_compared": False,
        "financial_provider_authenticated": False,
        "financial_repair_authorized": False,
        "all_finance_pending_cleared": False,
        "original_run_receipt_authenticated": False,
        "original_quarantines_cleared": False,
        "market_files_written": False,
        "qmt_cache_queried_or_modified": False,
        "qmt_download_calls": 0
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-root", type=Path, required=True)
    parser.add_argument("--stock-root", type=Path, required=True)
    parser.add_argument("--expected-ledger-sha256", required=True)
    parser.add_argument("--expected-snapshot-manifest-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect(
            args.module_root, args.stock_root,
            args.expected_ledger_sha256,
            args.expected_snapshot_manifest_sha256),
            sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ContentError, PRIOR.SnapshotError, LEDGER.ProgressError,
            TRIAGE.TriageError, ValueError, OSError, TypeError,
            RuntimeError, OverflowError) as exc:
        print("PRIOR_FINANCE_RAW_CONTENT_READONLY_REVIEW_REQUIRED: "
              + type(exc).__name__)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
