#!/usr/bin/env python3
"""Double-SHA-pinned, pending-only Finance DAT filename profile; metadata only.

Uses P3.24's exact already-owner-verified metadata manifest as the independent
input pin. No .DAT content reading, source decode, QMT, mutation or admission.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

import market_finance_adjustment_progress_readonly as LEDGER
import market_finance_pending_reason_triage_readonly as TRIAGE
import market_finance_pending_dat_filename_readonly as DAT

FORMAT = "astock_finance_pending_dat_filename_profile_readonly_v1"
STATUS = "PINNED_PENDING_DAT_FILENAME_PROFILE_ONLY_NO_FRESH_FINANCE_CONTENT"
DAY_NS = 86400 * 10**9
MAX_PROFILE_STOCKS = DAT.MAX_PENDING_STOCKS


class ProfileError(ValueError):
    pass


def need(ok, error):
    if not ok:
        raise ProfileError(error)


def _sha(value, label):
    need(type(value) is str and bool(TRIAGE.HEX.fullmatch(value)), label)
    return value.lower()


def _mtime_month(ns):
    try:
        return datetime.fromtimestamp(ns / 10**9, timezone.utc).strftime("%Y-%m")
    except (ValueError, OSError, OverflowError) as exc:
        raise ProfileError("FINANCE_DAT_METADATA_TIMESTAMP_UNSUPPORTED") from exc


def _skew_bucket(values):
    if len(values) <= 1 or min(values) == max(values):
        return "0d"
    span = max(values) - min(values)
    if span <= DAY_NS:
        return "within_1d"
    if span <= 7 * DAY_NS:
        return "within_7d"
    return "over_7d"


def _collect(finance_root, pending):
    """Mirror P3.24's scoped metadata manifest, not a separate data source."""
    observed = []
    per_stock = defaultdict(list)
    direct = 0
    for market in DAT.EXCHANGES:
        exchange = finance_root / market
        exchange_id = DAT._safe_dir(exchange, optional=True)
        if exchange_id is None:
            continue
        directory = exchange / "86400"
        day_id = DAT._safe_dir(directory, optional=True)
        if day_id is None:
            continue
        market_entries = 0
        with os.scandir(directory) as names:
            for item in names:
                market_entries += 1
                direct += 1
                need(market_entries <= DAT.MAX_DIRECT_ENTRIES_PER_MARKET
                     and direct <= DAT.MAX_TOTAL_DIRECT_ENTRIES,
                     "FINANCE_DAT_PROFILE_DIRECT_ENTRY_BUDGET")
                match = DAT.DAT_RE.fullmatch(item.name)
                if match is None:
                    continue
                code = match.group(1) + "." + market
                if code not in pending:
                    continue
                need(len(observed) < DAT.MAX_MATCHED_FILES,
                     "FINANCE_DAT_PROFILE_MATCH_LIMIT")
                need(not item.is_symlink(),
                     "FINANCE_DAT_PROFILE_SCOPED_LINK")
                info = item.stat(follow_symlinks=False)
                need(stat.S_ISREG(info.st_mode)
                     and not DAT._reparse(info)
                     and info.st_size >= 0,
                     "FINANCE_DAT_PROFILE_INVALID_ENTRY")
                descriptor = (
                    market, code, item.name, info.st_size, info.st_mtime_ns,
                    info.st_dev, info.st_ino
                )
                observed.append(descriptor)
                suffix = item.name[7:11].upper()  # '7xxx', not a table ID
                per_stock[code].append((suffix, info.st_size, info.st_mtime_ns))
        need(DAT._safe_dir(exchange) == exchange_id
             and DAT._safe_dir(directory) == day_id,
             "FINANCE_DAT_PROFILE_DIRECTORY_MUTATED")
    h = sha256()
    for row in sorted(observed):
        h.update(json.dumps(row, separators=(",", ":"),
                            ensure_ascii=False).encode("utf-8") + b"\n")
    return per_stock, observed, h.hexdigest(), direct


def inspect(module_root, stock_root, finance_dir,
            expected_ledger_sha256, expected_dat_metadata_manifest_sha256):
    ledger_sha = _sha(expected_ledger_sha256,
                      "FINANCE_DAT_PROFILE_LEDGER_SHA_REQUIRED")
    manifest_sha = _sha(expected_dat_metadata_manifest_sha256,
                        "FINANCE_DAT_PROFILE_MANIFEST_SHA_REQUIRED")
    before = DAT.inspect(module_root, stock_root, finance_dir, ledger_sha)
    need(before["metadata_only_manifest_sha256"] == manifest_sha,
         "FINANCE_DAT_PROFILE_OLD_METADATA_MANIFEST_MISMATCH")
    work, data_root = LEDGER._roots(module_root, stock_root)
    saved = LEDGER._bytes(work, TRIAGE.NAME)
    need(saved is not None and saved["sha256"] == ledger_sha,
         "FINANCE_DAT_PROFILE_SAVED_LEDGER_CHANGED")
    state = LEDGER._cache(saved["data"], data_root)
    pending = {code: entry["reason"]
               for code, entry in saved["data"]["pending"].items()}
    need(len(pending) <= MAX_PROFILE_STOCKS,
         "FINANCE_DAT_PROFILE_STOCK_LIMIT")
    finance, root_id = DAT._anchor(finance_dir)
    details, matched, rebuilt_manifest, direct = _collect(finance, pending)
    need(rebuilt_manifest == manifest_sha
         and len(matched) == before["matching_pending_file_names"]
         and direct == before["direct_directory_entries_seen"],
         "FINANCE_DAT_PROFILE_COLLECTED_METADATA_DIFFERS_FROM_P324")

    counts = defaultdict(Counter)
    reason_suffixes = defaultdict(Counter)
    months = Counter()
    max_names = 0
    for code, reason in sorted(pending.items()):
        records = details[code]
        file_count = len(records)
        max_names = max(max_names, file_count)
        positive = sum(size > 0 for _, size, _ in records)
        suffixes = tuple(sorted(set(item[0] for item in records)))
        dates = [mtime for _, _, mtime in records]
        c = counts[reason]
        c["pending_stocks"] += 1
        c["matching_file_names"] += file_count
        c["positive_file_names"] += positive
        c["zero_byte_file_names"] += file_count - positive
        c["files_total_bytes"] += sum(size for _, size, _ in records)
        c["file_count_histogram_" + str(file_count)] += 1
        c["positive_file_count_histogram_" + str(positive)] += 1
        c["stocks_with_exactly_8_names"] += (file_count == 8)
        c["stocks_with_8_positive_names"] += (file_count == 8 and positive == 8)
        c["stocks_with_non_8_count"] += (file_count != 8)
        c["stock_metadata_mtime_spread_" + _skew_bucket(dates)] += 1
        reason_suffixes[reason][suffixes] += 1
        for _, _, mtime in records:
            months[_mtime_month(mtime)] += 1

    profile = {}
    for reason, c in sorted(counts.items()):
        c["distinct_filename_suffix_sets"] = len(reason_suffixes[reason])
        c["largest_shared_suffix_set_stock_count"] = max(
            reason_suffixes[reason].values(), default=0)
        profile[reason] = dict(sorted(c.items()))
        previous = before["by_reason"].get(reason, {})
        need(c["pending_stocks"] == previous["pending_stocks"]
             and c["matching_file_names"] == previous["matched_file_names"]
             and c["positive_file_names"] == previous["nonempty_file_names"]
             and c["files_total_bytes"] == previous["observed_file_bytes"],
             "FINANCE_DAT_PROFILE_REASON_TOTALS_DIVERGE")

    need(sum(c["pending_stocks"] for c in counts.values())
         == state["pending_count"],
         "FINANCE_DAT_PROFILE_PENDING_TOTAL_DIVERGE")
    need(sum(months.values()) == len(matched),
         "FINANCE_DAT_PROFILE_MTIME_TOTAL_DIVERGE")

    after = DAT.inspect(module_root, stock_root, finance_dir, ledger_sha)
    need(before == after and DAT._safe_dir(finance) == root_id,
         "FINANCE_DAT_PROFILE_POSTFLIGHT_METADATA_CHANGED")
    end = LEDGER._bytes(work, TRIAGE.NAME)
    need(end is not None and end["sha256"] == saved["sha256"]
         and end["identity"] == saved["identity"],
         "FINANCE_DAT_PROFILE_LEDGER_CHANGED_DURING_SCAN")

    return {
        "format": FORMAT, "status": STATUS,
        "pinned_saved_financial_pending_ledger_sha256": ledger_sha,
        "pinned_P324_metadata_only_manifest_sha256": manifest_sha,
        "saved_pending_stocks": state["pending_count"],
        "matching_DAT_filenames": len(matched),
        "files_per_stock_max_observed": max_names,
        "by_pending_reason": profile,
        "filesystem_mtime_utc_month_filename_counts": dict(sorted(months.items())),
        "filesystem_mtime_not_financial_report_date": True,
        "filename_suffixes_not_financial_table_proof": True,
        "dat_content_bytes_read": False,
        "dat_physical_file_sha256_checked": False,
        "new_finance_raw_rows_read": False,
        "financial_nine_table_completeness_certified": False,
        "fresh_provider_provenance_certified": False,
        "fresh_vs_old_finance_compared": False,
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
    args = p.parse_args(argv)
    try:
        print(json.dumps(inspect(
            args.module_root, args.stock_root, args.finance_dir,
            args.expected_ledger_sha256, args.expected_dat_metadata_sha256
        ), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (ProfileError, DAT.DATError, LEDGER.ProgressError,
            OSError, ValueError, TypeError, RuntimeError,
            OverflowError) as exc:
        print("PINNED_PENDING_DAT_FILENAME_PROFILE_READONLY_REVIEW_REQUIRED: "
              + type(exc).__name__)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
