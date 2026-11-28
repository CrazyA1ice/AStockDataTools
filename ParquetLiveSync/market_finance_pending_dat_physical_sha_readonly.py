#!/usr/bin/env python3
"""Read-only physical byte SHA of EXISTING pinned pending QMT Finance DAT files.

No QMT SDK, DAT format decoding, interpretation of source records, writes,
downloads, progress modification, market admission or provider authentication.
Only files named by the same P3.24 owner-verified pending-only metadata manifest
are read twice using bounded file descriptors. Returns aggregate SHA only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

import market_finance_adjustment_progress_readonly as LEDGER
import market_finance_pending_reason_triage_readonly as TRIAGE
import market_finance_pending_dat_filename_readonly as DAT
import market_finance_pending_dat_profile_readonly as PROFILE

FORMAT = "astock_finance_pending_dat_physical_sha_readonly_v1"
STATUS = "PENDING_FINANCE_DAT_LOCAL_PHYSICAL_BYTES_VERIFIED_NO_SOURCE_DECODE"
MAX_SCOPED_FILES = 2048
MAX_SINGLE_DAT_BYTES = 128 * 1024 * 1024
MAX_ALL_DAT_BYTES = 256 * 1024 * 1024
CHUNK = 1024 * 1024


class PhysicalError(ValueError):
    pass


def need(ok, status):
    if not ok:
        raise PhysicalError(status)


def _hex(value, status):
    need(type(value) is str and bool(TRIAGE.HEX.fullmatch(value)), status)
    return value.lower()


def _hash_once(path, ref):
    """Read only a regular, nonlinked native DAT; never deserialize bytes."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = None
    try:
        fd = os.open(path, flags)
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode)
             and not DAT._reparse(before)
             and DAT._id(before) == ref,
             "FINANCE_DAT_FILE_IDENTITY_CHANGED_BEFORE_READ")
        need(0 <= before.st_size <= MAX_SINGLE_DAT_BYTES,
             "FINANCE_DAT_SINGLE_PHYSICAL_READ_BUDGET")
        remaining = before.st_size
        h = sha256()
        while remaining:
            block = os.read(fd, min(remaining, CHUNK))
            need(bool(block), "FINANCE_DAT_PHYSICAL_TRUNCATED_DURING_READ")
            h.update(block)
            remaining -= len(block)
        need(not os.read(fd, 1), "FINANCE_DAT_PHYSICAL_GREW_DURING_READ")
        need(DAT._id(os.fstat(fd)) == ref,
             "FINANCE_DAT_FILE_IDENTITY_CHANGED_AFTER_READ")
        return h.hexdigest()
    except PhysicalError:
        raise
    except OSError as exc:
        # The CLI never exposes the private path, original exception, or code.
        raise PhysicalError("FINANCE_DAT_PHYSICAL_READ_FAILED") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _hash_two_passes(path, original):
    first = _hash_once(path, original)
    need(DAT._id(os.stat(path, follow_symlinks=False)) == original
         and not path.is_symlink(),
         "FINANCE_DAT_PHYSICAL_PATH_REPLACED")
    second = _hash_once(path, original)
    need(first == second, "FINANCE_DAT_PHYSICAL_TWO_READS_DIFFER")
    need(DAT._id(os.stat(path, follow_symlinks=False)) == original
         and not path.is_symlink(), "FINANCE_DAT_PHYSICAL_PATH_CHANGED")
    return first


def _read_scoped(finance, pending, exact_manifest):
    h_meta = sha256()
    h_physical = sha256()
    reason_totals = defaultdict(Counter)
    scoped = 0
    entries_total = 0
    total_bytes = 0
    # Exact native filename ordering matches P3.24's metadata SHA recipe;
    # hashed file content itself is consumed only through local file handles.
    descriptors = []
    directories = {}
    for market in DAT.EXCHANGES:
        ex = finance / market
        ex_id = DAT._safe_dir(ex, optional=True)
        if ex_id is None:
            continue
        day = ex / "86400"
        day_id = DAT._safe_dir(day, optional=True)
        if day_id is None:
            continue
        directories[market] = (ex, ex_id, day, day_id)
        count = 0
        with os.scandir(day) as contents:
            for entry in contents:
                count += 1
                entries_total += 1
                need(count <= DAT.MAX_DIRECT_ENTRIES_PER_MARKET
                     and entries_total <= DAT.MAX_TOTAL_DIRECT_ENTRIES,
                     "FINANCE_DAT_PHYSICAL_DIRECT_ENTRY_BUDGET")
                match = DAT.DAT_RE.fullmatch(entry.name)
                if match is None:
                    continue
                stock = match.group(1) + "." + market
                if stock not in pending:
                    continue
                scoped += 1
                need(scoped <= MAX_SCOPED_FILES
                     and scoped <= DAT.MAX_MATCHED_FILES,
                     "FINANCE_DAT_PHYSICAL_SCOPED_FILE_BUDGET")
                need(not entry.is_symlink(),
                     "FINANCE_DAT_PHYSICAL_PENDING_SYMLINK")
                info = entry.stat(follow_symlinks=False)
                need(stat.S_ISREG(info.st_mode) and not DAT._reparse(info),
                     "FINANCE_DAT_PHYSICAL_NOT_REGULAR")
                need(0 <= info.st_size <= MAX_SINGLE_DAT_BYTES,
                     "FINANCE_DAT_SINGLE_PHYSICAL_READ_BUDGET")
                total_bytes += info.st_size
                need(total_bytes <= MAX_ALL_DAT_BYTES,
                     "FINANCE_DAT_TOTAL_PHYSICAL_READ_BUDGET")
                descriptor = (
                    market, stock, entry.name, info.st_size,
                    info.st_mtime_ns, info.st_dev, info.st_ino
                )
                descriptors.append((
                    descriptor, Path(entry.path), DAT._id(info),
                    pending[stock]))
        need(DAT._safe_dir(ex) == ex_id
             and DAT._safe_dir(day) == day_id,
             "FINANCE_DAT_PHYSICAL_DIRECTORY_CHANGED")
    for desc, _, _, _ in sorted(descriptors):
        h_meta.update(json.dumps(
            desc, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8") + b"\n")
    need(h_meta.hexdigest() == exact_manifest,
         "FINANCE_DAT_PHYSICAL_METADATA_MANIFEST_DIFFERS")
    for desc, path, old_identity, reason in sorted(descriptors):
        digest = _hash_two_passes(path, old_identity)
        h_physical.update(json.dumps(
            [*desc, digest], ensure_ascii=False,
            separators=(",", ":")
        ).encode("utf-8") + b"\n")
        counter = reason_totals[reason]
        counter["physical_DAT_files_double_SHA_verified"] += 1
        counter["DAT_file_bytes_per_read_pass"] += desc[3]
        counter["zero_byte_DAT_files"] += (desc[3] == 0)
    for ex, ex_id, day, day_id in directories.values():
        need(DAT._safe_dir(ex) == ex_id
             and DAT._safe_dir(day) == day_id,
             "FINANCE_DAT_PHYSICAL_DIRECTORY_CHANGED_AFTER_READ")
    return {
        "physical_DAT_file_manifest_sha256": h_physical.hexdigest(),
        "metadata_only_manifest_sha256_recomputed": h_meta.hexdigest(),
        "scoped_DAT_files_double_hashed": scoped,
        "scoped_DAT_bytes_per_pass": total_bytes,
        "total_DAT_content_bytes_read_two_passes": total_bytes * 2,
        "per_pending_reason": {
            label: dict(sorted(counts.items()))
            for label, counts in sorted(reason_totals.items())
        },
    }


def inspect(module_root, stock_root, finance_dir,
            expected_ledger_sha256, expected_metadata_sha256):
    ledger_sha = _hex(expected_ledger_sha256,
                      "FINANCE_DAT_PHYSICAL_LEDGER_SHA_REQUIRED")
    meta_sha = _hex(expected_metadata_sha256,
                    "FINANCE_DAT_PHYSICAL_METADATA_SHA_REQUIRED")
    # Full owner-verified P3.24 and P3.25 metadata checks first.
    prior = PROFILE.inspect(
        module_root, stock_root, finance_dir, ledger_sha, meta_sha)
    need(prior["pinned_P324_metadata_only_manifest_sha256"] == meta_sha
         and prior["dat_content_bytes_read"] is False
         and prior["financial_pending_resolved"] is False,
         "FINANCE_DAT_PHYSICAL_PROFILE_GATE_FAILED")
    work, data_root = LEDGER._roots(module_root, stock_root)
    saved = LEDGER._bytes(work, TRIAGE.NAME)
    need(saved is not None and saved["sha256"] == ledger_sha,
         "FINANCE_DAT_PHYSICAL_LEDGER_CHANGED")
    state = LEDGER._cache(saved["data"], data_root)
    pending = {code: item["reason"]
               for code, item in saved["data"]["pending"].items()}
    need(len(pending) == prior["saved_pending_stocks"]
         and len(pending) <= DAT.MAX_PENDING_STOCKS,
         "FINANCE_DAT_PHYSICAL_PENDING_SCOPE_CHANGED")
    finance, root_identity = DAT._anchor(finance_dir)
    scanned = _read_scoped(finance, pending, meta_sha)
    need(scanned["scoped_DAT_files_double_hashed"]
         == prior["matching_DAT_filenames"],
         "FINANCE_DAT_PHYSICAL_SCOPED_FILE_COUNT_MISMATCH")
    for label, counts in prior["by_pending_reason"].items():
        matched = scanned["per_pending_reason"].get(label, {})
        need(matched.get("physical_DAT_files_double_SHA_verified", 0)
             == counts["matching_file_names"]
             and matched.get("DAT_file_bytes_per_read_pass", 0)
             == counts["files_total_bytes"]
             and matched.get("zero_byte_DAT_files", 0)
             == counts["zero_byte_file_names"],
             "FINANCE_DAT_PHYSICAL_REASON_TOTAL_MISMATCH")
    need(len(scanned["per_pending_reason"])
         == len(prior["by_pending_reason"]),
         "FINANCE_DAT_PHYSICAL_REASON_SET_MISMATCH")
    # An independent full metadata check after both actual byte reads;
    # there is no cross-file atomic filesystem lock or broker lock.
    after = PROFILE.inspect(
        module_root, stock_root, finance_dir, ledger_sha, meta_sha)
    need(after == prior and DAT._safe_dir(finance) == root_identity,
         "FINANCE_DAT_PHYSICAL_POSTFLIGHT_METADATA_CHANGED")
    final = LEDGER._bytes(work, TRIAGE.NAME)
    need(final is not None and final["sha256"] == saved["sha256"]
         and final["identity"] == saved["identity"],
         "FINANCE_DAT_PHYSICAL_LEDGER_CHANGED_DURING_READ")
    return {
        "format": FORMAT, "status": STATUS,
        "pinned_saved_financial_ledger_sha256": ledger_sha,
        "pinned_P324_metadata_only_manifest_sha256": meta_sha,
        "physical_DAT_file_manifest_sha256":
            scanned["physical_DAT_file_manifest_sha256"],
        "saved_pending_stocks": state["pending_count"],
        "scoped_DAT_files_double_hashed":
            scanned["scoped_DAT_files_double_hashed"],
        "scoped_DAT_bytes_per_pass": scanned["scoped_DAT_bytes_per_pass"],
        "total_DAT_content_bytes_read_two_passes":
            scanned["total_DAT_content_bytes_read_two_passes"],
        "per_pending_reason": scanned["per_pending_reason"],
        "physical_DAT_bytes_read_for_hashing_only": True,
        "physical_DAT_bytes_saved_or_copied": False,
        "raw_DAT_format_decoded": False,
        "raw_DAT_financial_rows_parsed": False,
        "physical_DAT_manifest_proves_provider_origin": False,
        "DAT_business_table_mapping_certified": False,
        "nine_financial_tables_coverage_certified": False,
        "fresh_finance_raw_rows_authenticated": False,
        "fresh_and_old_finance_rows_compared": False,
        "cross_file_atomic_snapshot_certified": False,
        "financial_pending_resolved": False,
        "financial_repair_authorized": False,
        "original_run_receipt_authenticated": False,
        "original_quarantines_cleared": False,
        "market_files_written": False,
        "qmt_cache_queried_or_modified": False,
        "qmt_download_calls": 0,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--module-root", type=Path, required=True)
    p.add_argument("--stock-root", type=Path, required=True)
    p.add_argument("--finance-dir", type=Path, required=True)
    p.add_argument("--expected-ledger-sha256", required=True)
    p.add_argument("--expected-dat-metadata-sha256", required=True)
    a = p.parse_args(argv)
    try:
        print(json.dumps(inspect(
            a.module_root, a.stock_root, a.finance_dir,
            a.expected_ledger_sha256, a.expected_dat_metadata_sha256
        ), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (PhysicalError, PROFILE.ProfileError, DAT.DATError,
            LEDGER.ProgressError, OSError, ValueError, TypeError,
            RuntimeError, OverflowError) as exc:
        print("PENDING_DAT_PHYSICAL_SHA_READONLY_REVIEW_REQUIRED: "
              + type(exc).__name__)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
