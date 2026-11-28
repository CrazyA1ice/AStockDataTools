#!/usr/bin/env python3
"""Scope-limited, metadata-only census of saved finance pending DAT filenames.

No DAT bytes are read. No QMT API, data decoding, refresh, source
authentication, import, repairs or data writes. The only permitted directory
structure is explicitly supplied Finance/{SH,SZ,BJ}/86400, directly.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

import market_finance_adjustment_progress_readonly as LEDGER
import market_finance_pending_reason_triage_readonly as TRIAGE

FORMAT = "astock_finance_pending_dat_filename_metadata_readonly_v1"
STATUS = "PENDING_FINANCE_DAT_FILENAME_PRESENCE_ONLY_FRESH_RAW_NOT_VERIFIED"
EXCHANGES = ("SH", "SZ", "BJ")
DAT_RE = re.compile(r"^([0-9]{6})_7[0-9]{3}\.DAT$", re.IGNORECASE)
MAX_DIRECT_ENTRIES_PER_MARKET = 100000
MAX_TOTAL_DIRECT_ENTRIES = 250000
MAX_MATCHED_FILES = 100000
MAX_PENDING_STOCKS = 10000


class DATError(ValueError):
    pass


def need(ok, error):
    if not ok:
        raise DATError(error)


def _id(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode


def _reparse(s):
    return bool(getattr(s, "st_file_attributes", 0) & 0x400)


def _safe_dir(path, *, optional=False):
    path = Path(path)
    need(not path.is_symlink(), "FINANCE_DAT_DIRECTORY_SYMLINK")
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        if optional:
            return None
        raise DATError("FINANCE_DAT_DIRECTORY_NOT_PRESENT")
    need(stat.S_ISDIR(info.st_mode) and not _reparse(info),
         "FINANCE_DAT_DIRECTORY_NOT_REGULAR_OR_REPARSE")
    return _id(info)


def _anchor(finance_root):
    root = Path(finance_root)
    need(root.is_absolute(), "FINANCE_DAT_ROOT_MUST_BE_ABSOLUTE")
    # Reject any intermediate symlink/junction as well as the named root.
    for item in (root, *root.parents):
        need(not item.is_symlink(), "FINANCE_DAT_PARENT_SYMLINK")
        if item.exists():
            need(not _reparse(os.stat(item, follow_symlinks=False)),
                 "FINANCE_DAT_PARENT_REPARSE")
    return root, _safe_dir(root)


def _scan(finance_root, pending):
    all_observed = []
    by_stock = defaultdict(lambda: {"files": 0, "positive": 0,
                                   "zero": 0, "bytes": 0})
    direct_total = 0
    market_dirs = {}
    for market in EXCHANGES:
        exchange = finance_root / market
        exchange_id = _safe_dir(exchange, optional=True)
        if exchange_id is None:
            market_dirs[market] = {"present": False, "entries_seen": 0,
                                   "matched_pending_filenames": 0}
            continue
        daily = exchange / "86400"
        daily_id = _safe_dir(daily, optional=True)
        if daily_id is None:
            market_dirs[market] = {"present": False, "entries_seen": 0,
                                   "matched_pending_filenames": 0}
            continue
        count = 0
        relevant = 0
        with os.scandir(daily) as items:
            for ent in items:
                count += 1
                direct_total += 1
                need(count <= MAX_DIRECT_ENTRIES_PER_MARKET
                     and direct_total <= MAX_TOTAL_DIRECT_ENTRIES,
                     "FINANCE_DAT_DIRECT_ENTRY_BUDGET_EXCEEDED")
                match = DAT_RE.fullmatch(ent.name)
                if not match:
                    continue
                code = match.group(1) + "." + market
                if code not in pending:
                    continue
                relevant += 1
                need(len(all_observed) < MAX_MATCHED_FILES,
                     "FINANCE_DAT_MATCHED_FILE_BUDGET_EXCEEDED")
                need(not ent.is_symlink(), "FINANCE_DAT_SCOPED_SYMLINK")
                info = ent.stat(follow_symlinks=False)
                need(stat.S_ISREG(info.st_mode) and not _reparse(info)
                     and info.st_size >= 0,
                     "FINANCE_DAT_SCOPED_FILE_INVALID")
                curr = by_stock[code]
                curr["files"] += 1
                curr["bytes"] += info.st_size
                if info.st_size > 0:
                    curr["positive"] += 1
                else:
                    curr["zero"] += 1
                # Hash *metadata*, never file content. Do not return private
                # stock IDs or cache paths.
                all_observed.append((
                    market, code, ent.name, info.st_size, info.st_mtime_ns,
                    info.st_dev, info.st_ino))
        need(_safe_dir(exchange) == exchange_id
             and _safe_dir(daily) == daily_id,
             "FINANCE_DAT_DIRECTORY_CHANGED_DURING_CENSUS")
        market_dirs[market] = {
            "present": True, "entries_seen": count,
            "matched_pending_filenames": relevant}
    metadata_digest = sha256()
    for item in sorted(all_observed):
        metadata_digest.update(json.dumps(
            item, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8") + b"\n")
    groups = defaultdict(Counter)
    for code, reason in sorted(pending.items()):
        d = by_stock[code]
        c = groups[reason]
        c["pending_stocks"] += 1
        c["stocks_with_matching_filename"] += bool(d["files"])
        c["stocks_with_nonempty_filename"] += bool(d["positive"])
        c["stocks_with_no_matching_filename"] += not bool(d["files"])
        c["stocks_only_zero_byte_files"] += bool(d["files"]) and not bool(d["positive"])
        c["matched_file_names"] += d["files"]
        c["nonempty_file_names"] += d["positive"]
        c["zero_byte_file_names"] += d["zero"]
        c["observed_file_bytes"] += d["bytes"]
    return {"by_reason": {
                k: dict(sorted(v.items())) for k, v in sorted(groups.items())},
            "market_directories": market_dirs,
            "direct_directory_entries_seen": direct_total,
            "matching_pending_file_names": len(all_observed),
            "metadata_only_manifest_sha256": metadata_digest.hexdigest()}


def inspect(module_root, stock_root, finance_root, expected_ledger_sha256):
    need(type(expected_ledger_sha256) is str
         and bool(TRIAGE.HEX.fullmatch(expected_ledger_sha256)),
         "FINANCE_DAT_EXPECTED_LEDGER_SHA_REQUIRED")
    work, data_root = LEDGER._roots(module_root, stock_root)
    ledger = LEDGER._bytes(work, TRIAGE.NAME)
    need(ledger is not None and ledger["sha256"] ==
         expected_ledger_sha256.lower(), "FINANCE_DAT_LEDGER_SHA_CHANGED")
    state = LEDGER._cache(ledger["data"], data_root)
    pending = {code: entry["reason"]
               for code, entry in ledger["data"]["pending"].items()}
    need(len(pending) <= MAX_PENDING_STOCKS,
         "FINANCE_DAT_PENDING_STOCK_BUDGET")
    finance, anchor_id = _anchor(finance_root)
    before = _scan(finance, pending)
    # Run again, without modifying anything, to catch selected file
    # additions/deletions, file metadata drift, or path changes.
    after = _scan(finance, pending)
    need(before == after and _safe_dir(finance) == anchor_id,
         "FINANCE_DAT_METADATA_CHANGED_DURING_CENSUS")
    last = LEDGER._bytes(work, TRIAGE.NAME)
    need(last is not None and last["sha256"] == ledger["sha256"]
         and last["identity"] == ledger["identity"],
         "FINANCE_DAT_LEDGER_CHANGED_DURING_CENSUS")
    need(sum(v["pending_stocks"] for v in before["by_reason"].values())
         == state["pending_count"],
         "FINANCE_DAT_REASON_TOTAL_CHANGED")
    return {
        "format": FORMAT, "status": STATUS,
        "pinned_saved_financial_pending_ledger_sha256": ledger["sha256"],
        "saved_pending_stock_count": state["pending_count"],
        "scanned_explicit_finance_subtrees": [m + "/86400" for m in EXCHANGES],
        **before,
        "finance_dat_contents_read": False,
        "finance_dat_file_sha256_verified": False,
        "finance_dat_table_mapping_certified": False,
        "source_financial_nine_table_coverage_certified": False,
        "fresh_finance_original_rows_available": False,
        "fresh_finance_records_compared_to_old_union": False,
        "finance_dat_metadata_proves_provider_origin": False,
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
    a = p.parse_args(argv)
    try:
        print(json.dumps(inspect(a.module_root, a.stock_root,
                                 a.finance_dir,
                                 a.expected_ledger_sha256),
                         ensure_ascii=False, indent=2,
                         sort_keys=True, allow_nan=False))
        return 0
    except (DATError, LEDGER.ProgressError, OSError, ValueError,
            TypeError, RuntimeError, OverflowError) as exc:
        # Safe stop: never echo private stock identifiers or source paths.
        print("FINANCE_PENDING_DAT_FILENAME_CENSUS_REVIEW_REQUIRED: "
              + type(exc).__name__)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
