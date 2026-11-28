#!/usr/bin/env python3
"""Plan (never apply) migration from a SHA-pinned 240 month to paid 241.

Only existing commit ledgers, physical file hashes and previously accepted
private QMT 241 source receipts are read. The plan does not stage, rewrite,
append or fetch any 1minute market data, nor change the Windows scheduler.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import local_layout as L
import market_month_storage as S
import qmt_1m_private_month_bridge as B

FORMAT = "astock_paid_241_legacy_month_migration_readonly_plan_v1"
# Historical SHA-pinned private QMT full 241 source. It covers 11/02..11/12
# only, NOT every later production trading day in a mutable Nov 240 file.
PINNED_QMT_NOV_PRIVATE_SHA = (
    "d942d8036841fe6053ec49fbdf66d2229bcd07303b5a2de7f08aa5a0c509abc0"
)


def summarize(old_days, source_entries, month):
    """Pure set-level comparison; stock quantities are never invented."""
    original = set(old_days)
    if not original or any(not isinstance(x, str) or
                           not x.startswith(month) for x in original):
        raise ValueError("MIGRATION_OLD_MONTH_DAY_SET_INVALID")
    accepted = Counter()
    for entry in source_entries:
        if (not isinstance(entry, dict) or
                not isinstance(entry.get("code"), str) or
                not isinstance(entry.get("days"), list)):
            raise ValueError("MIGRATION_QMT_241_SOURCE_ENTRIES_INVALID")
        for day in entry["days"]:
            if day.startswith(month):
                accepted[day] += 1
    covered = original & set(accepted)
    missing = original - set(accepted)
    outside = set(accepted) - original
    return {
        "old_physical_month_trading_days": len(original),
        "source_241_verified_trading_days": len(accepted),
        "source_241_verified_stock_days": sum(accepted.values()),
        "old_days_with_any_pinned_qmt_241_source": len(covered),
        "old_days_without_pinned_qmt_241_source": len(missing),
        "source_days_outside_current_old_ledger": len(outside),
        # Having some QMT rows on a date is NOT all-stock coverage.
        "source_complete_for_all_old_stock_days_certified": False,
        "old_month_full_241_replacement_authorized": False,
    }


def inspect(root, stage, month, *, workspace=None):
    if month != "2026-11":
        raise ValueError("MIGRATION_ONLY_NOVEMBER_PILOT_SUPPORTED")
    if workspace is None or not Path(workspace).is_dir():
        raise ValueError("MIGRATION_CANONICAL_LEDGER_WORKSPACE_REQUIRED")
    old_state = S.state_for(root, workspace=workspace)
    old = old_state["periods"]["1min"].get(month)
    if (not isinstance(old, dict) or
            not isinstance(old.get("sha256"), str) or
            not isinstance(old.get("days"), list)):
        raise ValueError("MIGRATION_PRIOR_PHYSICAL_LEDGER_MISSING")
    if old.get("minute_grid_contract") == S.PAID_241_CONTRACT:
        raise ValueError("MIGRATION_SOURCE_ALREADY_PAID_241")
    target = S.target_path(root, month)
    if not target.is_file() or target.is_symlink() or L.hash_file(target) != old["sha256"]:
        raise ValueError("MIGRATION_PRIOR_PHYSICAL_240_SHA_CHANGED")
    candidate = Path(stage) / B.TARGET / (month + ".parquet")
    if (not candidate.is_file() or candidate.is_symlink()
            or L.hash_file(candidate) != PINNED_QMT_NOV_PRIVATE_SHA):
        raise ValueError("MIGRATION_QMT_NATIVE_241_SOURCE_SHA_CHANGED")
    plan = B.resolve(root, stage, progress=lambda _: None)
    accepted_meta = plan["months"][month]
    if (accepted_meta["stock_days_accepted"] * 241 !=
            accepted_meta["minute_rows_expected_from_accepted"]):
        raise ValueError("MIGRATION_QMT_241_ORIGINAL_ROW_COUNT_DRIFT")
    summary = summarize(old["days"], plan["entries"], month)
    if summary["source_241_verified_stock_days"] != accepted_meta["stock_days_accepted"]:
        raise ValueError("MIGRATION_QMT_SOURCE_RECEIPT_COVERAGE_DRIFT")
    return {
        "format": FORMAT,
        "month": month,
        "legacy_240_month_receipt_sha256": old["sha256"],
        "verified_native_241_private_source_sha256": PINNED_QMT_NOV_PRIVATE_SHA,
        "source_identity_sha256": plan["identity_sha256"],
        **summary,
        "raw_241_source_has_distinct_0930": True,
        "existing_purchased_parquet_modified": False,
        "existing_240_incremental_month_modified": False,
        "private_qmt_source_modified": False,
        "market_files_written": False,
        "qmt_download_called": False,
        "stock_level_source_comparison_done": False,
        "production_month_replacement_performed": False,
        "status": "MIGRATION_PLAN_ONLY_241_SOURCE_INCOMPLETE_OR_UNPROVEN",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--month", choices=("2026-11",), default="2026-11")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect(args.root, args.stage, args.month,
                                 workspace=args.workspace),
                         ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception:
        # Do not print private paths, per-symbol market values or receipts.
        print("PAID_241_LEGACY_MIGRATION_PLAN_READONLY_REVIEW_REQUIRED")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
