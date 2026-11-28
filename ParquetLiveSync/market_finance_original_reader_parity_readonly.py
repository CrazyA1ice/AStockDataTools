#!/usr/bin/env python3
"""Read-only parity of P3.21 saved OLD union and original importer._prior_rows.

Checks ONLY SHA-pinned historical selected QMT finance snapshots. The importer
reader is called as a pure existing-data function; no financial fresh source,
cache refresh, download, schedule, write, or quarantine release is authorized.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path

import market_finance_adjustment_progress_readonly as LEDGER
import market_finance_pending_reason_triage_readonly as TRIAGE
import market_finance_prior_snapshot_census_readonly as PRIOR
import market_finance_prior_raw_content_readonly as RAW
import qmt_extra_financial_cache_import as IMPORT

FORMAT = "astock_original_finance_prior_reader_parity_readonly_v1"
STATUS = "PRODUCTION_READER_OLD_HISTORICAL_UNION_MATCHED_FRESH_NOT_CHECKED"
MAX_SCOPES = PRIOR.MAX_CONFLICT_SCOPES
MAX_UNION_DISTINCT_PER_SCOPE = RAW.MAX_UNION_DISTINCT_PER_SCOPE
MAX_TOTAL_OLD_UNION_MULTIPLICITY = RAW.MAX_TOTAL_ROWS


class ParityError(ValueError):
    pass


def need(test, error):
    if not test:
        raise ParityError(error)


def _sha_arg(value, error):
    need(type(value) is str and bool(TRIAGE.HEX.fullmatch(value)), error)
    return value.lower()


def _scope_digest(union):
    need(type(union) is Counter, "ORIGINAL_READER_UNION_NOT_COUNTER")
    need(0 < len(union) <= MAX_UNION_DISTINCT_PER_SCOPE,
         "ORIGINAL_READER_UNION_DISTINCT_BUDGET")
    h = sha256()
    count = 0
    # Use the SAME canonical byte ordering as the P3.21 independent source.
    for key, n in sorted(union.items()):
        need(type(key) is str and type(n) is int and n > 0,
             "ORIGINAL_READER_UNION_ENTRY_INVALID")
        count += n
        need(count <= MAX_TOTAL_OLD_UNION_MULTIPLICITY,
             "ORIGINAL_READER_UNION_MULTIPLICITY_BUDGET")
        h.update(json.dumps([key, n], separators=(",", ":"),
                            ensure_ascii=False).encode("utf-8") + b"\n")
    return h.hexdigest(), len(union), count


def inspect(module_root, stock_root, expected_ledger_sha256,
            expected_snapshot_manifest_sha256, expected_old_union_sha256):
    ledger_pin = _sha_arg(expected_ledger_sha256,
                          "EXPECTED_LEDGER_SHA_REQUIRED")
    old_manifest_pin = _sha_arg(expected_snapshot_manifest_sha256,
                                "EXPECTED_SNAPSHOT_MANIFEST_SHA_REQUIRED")
    old_union_pin = _sha_arg(expected_old_union_sha256,
                             "EXPECTED_OLD_UNION_SHA_REQUIRED")

    # Content-level P3.21 is a strict read-only gate: it enforces physical
    # ledger and all 91 old file/pin checks, row provenance, JSON rules,
    # immutable filename fingerprints, Arrow/row/byte limits, and the
    # independently computed old union digest BEFORE importer parity.
    verified = RAW.inspect(module_root, stock_root,
                           ledger_pin, old_manifest_pin)
    need(verified["prior_content_union_manifest_sha256"] == old_union_pin,
         "PRIOR_CONTENT_SHA_DIFFERENT_FROM_ACCEPTED_WINDOWS_PROOF")
    need(verified["old_selected_historical_counter_union_computed"] is True
         and verified["new_finance_source_consulted"] is False
         and verified["financial_repair_authorized"] is False
         and verified["original_quarantines_cleared"] is False,
         "PRIOR_CONTENT_AUTHORITY_GATE_FAILED")

    work, extra_string = LEDGER._roots(module_root, stock_root)
    extra = Path(extra_string)
    before = LEDGER._bytes(work, PRIOR.NAME)
    need(before is not None and before["sha256"] == ledger_pin,
         "ORIGINAL_READER_LEDGER_PIN_CHANGED")
    ledger_state = LEDGER._cache(before["data"], extra_string)
    scopes = RAW._scopes(before["data"]["pending"])
    need(len(scopes) == verified["conflict_scopes_checked"]
         and len(scopes) <= MAX_SCOPES,
         "ORIGINAL_READER_SCOPE_COUNT_CHANGED")

    table_counts = defaultdict(Counter)
    manifest = sha256()
    union_multiplicity = 0
    for table_name, stock in scopes:
        table_root = extra / "financial" / table_name
        stock_root_dir = table_root / stock
        folder = stock_root_dir / "snapshots"
        for d in (table_root, stock_root_dir, folder):
            PRIOR._dir(d)
        file_names, before_dir = PRIOR._snapshot_names(folder)
        need(bool(file_names), "ORIGINAL_READER_SCOPE_OLD_FILES_MISSING")
        last_day = max(name[:10] for name in file_names)
        # This call is the actual production definition of the OLD historical
        # raw multiset and active version selection. Its QMT/cache downloader
        # entrypoints are NOT called.
        try:
            original_last_day, original_union = IMPORT._prior_rows(
                extra, stock, table_name)
        except Exception as exc:
            raise ParityError("ORIGINAL_READER_OLD_SOURCE_PARSER_FAILED") from exc
        need(original_last_day == last_day,
             "ORIGINAL_READER_OLD_ASOF_DATES_DIFFER")
        digest, distinct, multiset = _scope_digest(original_union)
        union_multiplicity += multiset
        need(union_multiplicity <= MAX_TOTAL_OLD_UNION_MULTIPLICITY,
             "ORIGINAL_READER_TOTAL_UNION_MULTIPLICITY_BUDGET")
        manifest.update(json.dumps(
            [table_name, stock, digest],
            separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8") + b"\n")
        counts = table_counts[table_name]
        counts["source_conflict_scopes"] += 1
        counts["original_reader_union_distinct_rows"] += distinct
        counts["original_reader_union_multiset_rows"] += multiset
        need(PRIOR._identity(os.stat(folder, follow_symlinks=False))
             == before_dir, "ORIGINAL_READER_SNAPSHOT_DIRECTORY_CHANGED")

    need(manifest.hexdigest() == old_union_pin,
         "ORIGINAL_READER_CONTENT_UNION_DIGEST_DIVERGES_FROM_P321")
    for table_name, original in table_counts.items():
        accepted = verified["table_scoped_counts"].get(table_name)
        need(type(accepted) is dict
             and original["source_conflict_scopes"]
                == accepted["source_conflict_scopes"]
             and original["original_reader_union_distinct_rows"]
                == accepted["old_union_distinct_raw_rows"]
             and original["original_reader_union_multiset_rows"]
                == accepted["old_union_multiset_rows"],
             "ORIGINAL_READER_TABLE_UNION_COUNTS_DIVERGE")
    need(len(table_counts) == len(verified["table_scoped_counts"]),
         "ORIGINAL_READER_TABLE_COUNT_DIVERGES")

    after = LEDGER._bytes(work, PRIOR.NAME)
    need(after is not None
         and after["sha256"] == before["sha256"]
         and after["identity"] == before["identity"],
         "ORIGINAL_READER_LEDGER_CHANGED_DURING_SCAN")
    # Content and physical manifests must remain identical *after* the
    # original production reader's bounded old-file pass too.
    after_verified = RAW.inspect(module_root, stock_root,
                                 ledger_pin, old_manifest_pin)
    need(after_verified["prior_content_union_manifest_sha256"]
         == verified["prior_content_union_manifest_sha256"]
         and after_verified["verified_prior_snapshot_manifest_sha256"]
         == verified["verified_prior_snapshot_manifest_sha256"]
         and after_verified["active_old_snapshot_files_content_verified"]
         == verified["active_old_snapshot_files_content_verified"]
         and after_verified["table_scoped_counts"]
         == verified["table_scoped_counts"],
         "ORIGINAL_READER_OLD_CONTENT_CHANGED_DURING_PARITY_CHECK")

    return {
        "format": FORMAT, "status": STATUS,
        "pinned_saved_financial_ledger_sha256": ledger_pin,
        "pinned_old_snapshot_manifest_sha256": old_manifest_pin,
        "matched_old_union_manifest_sha256": manifest.hexdigest(),
        "old_content_union_manifest_rechecked_after": True,
        "old_conflict_scopes_original_reader_parity_checked": len(scopes),
        "old_active_snapshots_accepted_p321": verified[
            "active_old_snapshot_files_content_verified"],
        "old_raw_rows_accepted_p321": verified["active_old_raw_rows_checked"],
        "original_reader_union_distinct_total":
            sum(v["original_reader_union_distinct_rows"]
                for v in table_counts.values()),
        "original_reader_union_multiset_total": union_multiplicity,
        "by_table": {k: dict(sorted(v.items()))
                     for k, v in sorted(table_counts.items())},
        "saved_ledger_pending_count_unchanged": ledger_state["pending_count"],
        "legacy_original_reader_function": "qmt_extra_financial_cache_import._prior_rows",
        "only_existing_old_selected_snapshots_read": True,
        "production_saved_old_multiset_semantics_matched": True,
        "cross_file_atomic_snapshot_certified": False,
        "fresh_qmt_or_finance_source_queried": False,
        "fresh_finance_raw_records_compared": False,
        "original_finance_source_provider_authenticated": False,
        "all_historical_finance_coverage_certified": False,
        "financial_pending_resolved": False,
        "financial_repair_authorized": False,
        "original_run_receipt_authenticated": False,
        "original_quarantines_cleared": False,
        "market_files_written": False,
        "qmt_cache_queried_or_modified": False,
        "qmt_download_calls": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-root", type=Path, required=True)
    parser.add_argument("--stock-root", type=Path, required=True)
    parser.add_argument("--expected-ledger-sha256", required=True)
    parser.add_argument("--expected-snapshot-manifest-sha256", required=True)
    parser.add_argument("--expected-old-union-sha256", required=True)
    a = parser.parse_args(argv)
    try:
        print(json.dumps(inspect(
            a.module_root, a.stock_root, a.expected_ledger_sha256,
            a.expected_snapshot_manifest_sha256, a.expected_old_union_sha256
        ), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (ParityError, RAW.ContentError, PRIOR.SnapshotError,
            LEDGER.ProgressError, TRIAGE.TriageError, ValueError, OSError,
            TypeError, RuntimeError, OverflowError, RecursionError) as exc:
        print("PRODUCTION_PRIOR_READER_PARITY_READONLY_REVIEW_REQUIRED: "
              + type(exc).__name__)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
