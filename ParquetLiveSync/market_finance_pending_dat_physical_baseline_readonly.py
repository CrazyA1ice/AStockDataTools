#!/usr/bin/env python3
"""Recheck a pinned native DAT physical SHA using the accepted P3.26 reader.

Read-only: validates three externally supplied SHA pins, runs the full P3.26
pre/postflight and double-byte read, then compares its batch physical digest
with the prior Windows acceptance. No DAT parsing, QMT API, writes or waivers.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import re

FORMAT = "astock_finance_pending_dat_physical_baseline_recheck_v1"
STATUS = "PENDING_FINANCE_DAT_PHYSICAL_BASELINE_MATCHED_NO_PROVIDER_CERT"
PHYSICAL_MODULE = "market_finance_pending_dat_physical_sha_readonly"
PHYSICAL_STATUS = "PENDING_FINANCE_DAT_LOCAL_PHYSICAL_BYTES_VERIFIED_NO_SOURCE_DECODE"
HEX = re.compile(r"[0-9a-fA-F]{64}\Z")
DENIED = (
    "physical_DAT_bytes_saved_or_copied", "raw_DAT_format_decoded",
    "raw_DAT_financial_rows_parsed", "physical_DAT_manifest_proves_provider_origin",
    "DAT_business_table_mapping_certified", "nine_financial_tables_coverage_certified",
    "fresh_finance_raw_rows_authenticated", "fresh_and_old_finance_rows_compared",
    "cross_file_atomic_snapshot_certified", "financial_pending_resolved",
    "financial_repair_authorized", "original_run_receipt_authenticated",
    "original_quarantines_cleared", "market_files_written",
    "qmt_cache_queried_or_modified",
)


class BaselineError(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise BaselineError(reason)


def _pin(value, label):
    need(type(value) is str and bool(HEX.fullmatch(value)), label)
    return value.lower()


def inspect(module_root, stock_root, finance_dir,
            expected_ledger_sha256, expected_metadata_sha256,
            expected_physical_sha256):
    ledger = _pin(expected_ledger_sha256, "FINANCE_BASELINE_LEDGER_SHA_REQUIRED")
    metadata = _pin(expected_metadata_sha256,
                    "FINANCE_BASELINE_METADATA_SHA_REQUIRED")
    physical = _pin(expected_physical_sha256,
                    "FINANCE_BASELINE_PHYSICAL_SHA_REQUIRED")
    # The only native-file access is the already-accepted P3.26 read-only
    # inspector. Lazy import allows pure-stdlib isolated contract tests.
    source = importlib.import_module(PHYSICAL_MODULE)
    observed = source.inspect(module_root, stock_root, finance_dir,
                              ledger, metadata)
    need(type(observed) is dict and observed.get("status") == PHYSICAL_STATUS
         and observed.get("format") ==
         "astock_finance_pending_dat_physical_sha_readonly_v1",
         "FINANCE_BASELINE_READER_STATUS_INVALID")
    need(observed.get("pinned_saved_financial_ledger_sha256") == ledger
         and observed.get("pinned_P324_metadata_only_manifest_sha256") == metadata,
         "FINANCE_BASELINE_PRIOR_PINS_CHANGED")
    digest = observed.get("physical_DAT_file_manifest_sha256")
    need(type(digest) is str and bool(HEX.fullmatch(digest))
         and digest == physical,
         "FINANCE_BASELINE_PHYSICAL_SHA_MISMATCH")
    need(observed.get("physical_DAT_bytes_read_for_hashing_only") is True
         and observed.get("qmt_download_calls") == 0
         and type(observed.get("qmt_download_calls")) is int
         and all(observed.get(key) is False for key in DENIED),
         "FINANCE_BASELINE_AUTHORITY_FLAGS_INVALID")
    count = observed.get("scoped_DAT_files_double_hashed")
    length = observed.get("scoped_DAT_bytes_per_pass")
    total = observed.get("total_DAT_content_bytes_read_two_passes")
    need(type(count) is int and 0 <= count <= source.MAX_SCOPED_FILES
         and type(length) is int and 0 <= length <= source.MAX_ALL_DAT_BYTES
         and type(total) is int and total == 2 * length,
         "FINANCE_BASELINE_READ_COUNTS_INVALID")
    return {
        "format": FORMAT,
        "status": STATUS,
        "pinned_saved_financial_ledger_sha256": ledger,
        "pinned_P324_metadata_only_manifest_sha256": metadata,
        "pinned_physical_DAT_file_manifest_sha256": physical,
        "reobserved_physical_DAT_file_manifest_sha256": digest,
        "physical_baseline_match": True,
        "scoped_DAT_files_double_hashed": count,
        "scoped_DAT_bytes_per_pass": length,
        "total_DAT_content_bytes_read_two_passes": total,
        "physical_DAT_bytes_read_for_hashing_only": True,
        "raw_DAT_format_decoded": False,
        "DAT_business_table_mapping_certified": False,
        "nine_financial_tables_coverage_certified": False,
        "physical_DAT_manifest_proves_provider_origin": False,
        "financial_pending_resolved": False,
        "financial_repair_authorized": False,
        "original_quarantines_cleared": False,
        "cross_file_atomic_snapshot_certified": False,
        "market_files_written": False,
        "qmt_download_calls": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-root", type=Path, required=True)
    parser.add_argument("--stock-root", type=Path, required=True)
    parser.add_argument("--finance-dir", type=Path, required=True)
    parser.add_argument("--expected-ledger-sha256", required=True)
    parser.add_argument("--expected-dat-metadata-sha256", required=True)
    parser.add_argument("--expected-dat-physical-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect(args.module_root, args.stock_root, args.finance_dir,
                         args.expected_ledger_sha256,
                         args.expected_dat_metadata_sha256,
                         args.expected_dat_physical_sha256)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                         indent=2, allow_nan=False))
        return 0
    except Exception:
        # No private stock, file path or bytes escape the CLI on error.
        print("PENDING_DAT_PHYSICAL_BASELINE_READONLY_REVIEW_REQUIRED")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
