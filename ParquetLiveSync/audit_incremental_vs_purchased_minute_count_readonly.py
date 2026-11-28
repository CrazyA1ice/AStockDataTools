#!/usr/bin/env python3
"""Read-only comparison of purchased-minute labels and an updated month.

Only counts / date-scoped label summaries. A matching 241 count never proves
raw 09:15-09:25 auction order/tick content or minute semantics equivalence.
The tool deliberately has no write, QMT, or source-repair capability.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

import audit_purchased_1min_bars_readonly as PAID

FORMAT = "astock_purchased_vs_incremental_one_minute_grid_readonly_v1"
MATCH = "BAR_COUNT_AND_OPENING_LABEL_PROFILE_AGREE_NOT_BUSINESS_CERTIFIED"
CONFLICT = "PAID_241_VS_INCREMENTAL_BAR_GRID_CONFLICT_REVIEW_REQUIRED"


class ContractError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise ContractError(message)


def compare(purchased_file, purchased_day, incremental_file,
            incremental_day, *, expected_reference_stocks=None):
    left, right = Path(purchased_file), Path(incremental_file)
    need(left != right and left.resolve() != right.resolve(),
         "REFERENCE_AND_INCREMENTAL_MUST_BE_DIFFERENT_FILES")
    need(type(purchased_day) is date and type(incremental_day) is date,
         "DATES_MUST_BE_EXPLICIT")
    need(expected_reference_stocks is None or (
        type(expected_reference_stocks) is int and
        1 <= expected_reference_stocks <= 15000),
        "EXPECTED_REFERENCE_STOCKS_INVALID")
    left_result = PAID.inspect(left, purchased_day)
    if expected_reference_stocks is not None:
        need(left_result["stock_days_observed"] == expected_reference_stocks,
             "PREVIOUSLY_ACCEPTED_PAID_REFERENCE_CHANGED")
    # Our only meaningful source reference is the original purchased source,
    # not any private H5 overlay, QMT saved current, or another generated month.
    need(left_result["source_kind"] == "PURCHASED_PARQUET_ONLY"
         and left_result["matching_rows_for_day"] > 0
         and left_result["all_symbol_timestamp_keys_unique"] is True,
         "PAID_REFERENCE_INVALID")
    right_result = PAID.inspect(right, incremental_day)
    need(right_result["all_symbol_timestamp_keys_unique"] is True,
         "INCREMENTAL_REPEATED_MINUTE_KEYS")
    ref_hist = left_result["per_stock_day_bar_count_histogram"]
    new_hist = right_result["per_stock_day_bar_count_histogram"]
    ref_separate = (left_result["stocks_with_0930_label"] ==
                    left_result["stock_days_observed"])
    new_separate = (right_result["stocks_with_0930_label"] ==
                    right_result["stock_days_observed"])
    # This compares SHAPE, not numbers of stocks in different historical days.
    # Required contract: original same-number-of-bar stocks throughout;
    # generated update must have that identical per-stock count.
    shape = (len(ref_hist) == 1 and len(new_hist) == 1
             and next(iter(ref_hist)) == next(iter(new_hist)))
    same_opening_label = ref_separate == new_separate
    compatible_shape = bool(shape and same_opening_label
                            and left_result["stock_days_other_bar_counts"] == 0
                            and right_result["stock_days_other_bar_counts"] == 0)
    return {
        "format": FORMAT,
        "status": MATCH if compatible_shape else CONFLICT,
        "purchased_reference_day": purchased_day.isoformat(),
        "purchased_reference_file_name": left.name,
        "purchased_reference_stock_days": left_result["stock_days_observed"],
        "purchased_reference_bar_count_histogram": ref_hist,
        "purchased_reference_0930_present_for_all": ref_separate,
        "purchased_reference_0930_positive_volume_amount_rows":
            left_result["0930_rows_with_positive_volume_and_amount"],
        "incremental_day": incremental_day.isoformat(),
        "incremental_month_name": right.name,
        "incremental_stock_days": right_result["stock_days_observed"],
        "incremental_bar_count_histogram": new_hist,
        "incremental_0930_present_for_all": new_separate,
        "bar_count_and_opening_label_profile_match": compatible_shape,
        "purchased_09_30_auction_trades_source_certified": False,
        "incremental_09_30_auction_trades_source_certified": False,
        "minute_business_compatibility_certified": False,
        "original_purchased_data_modified": False,
        "incremental_data_modified": False,
        "QMT_or_H5_source_accessed": False,
        "parquet_files_written": False,
        "remediation_authorized": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--purchased-file", type=Path, required=True)
    p.add_argument("--purchased-day", type=date.fromisoformat, required=True)
    p.add_argument("--incremental-file", type=Path, required=True)
    p.add_argument("--incremental-day", type=date.fromisoformat, required=True)
    p.add_argument("--expected-reference-stocks", type=int)
    args = p.parse_args(argv)
    try:
        report = compare(
            args.purchased_file, args.purchased_day,
            args.incremental_file, args.incremental_day,
            expected_reference_stocks=args.expected_reference_stocks)
        print(json.dumps(report, ensure_ascii=False,
                         sort_keys=True, indent=2, allow_nan=False))
        # A completed diagnostic is not authorization to write market data.
        return 0
    except (ContractError, ValueError, TypeError, OSError,
            PAID.pa.ArrowException):
        print("ONE_MINUTE_CONTRACT_READONLY_REVIEW_REQUIRED")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
