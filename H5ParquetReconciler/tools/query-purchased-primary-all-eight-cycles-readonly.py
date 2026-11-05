#!/usr/bin/env python3
"""Read-only bounded eight-cycle purchased-primary research query.

Native purchased Parquet is read in place for day, 15min, 30min, 60min, week,
month. 1min/5min delegate to the previously verified purchased-primary
stockday key-index router with explicitly opt-in, SHA-checked PRIVATE H5
fallback. No source copies, new indexes, H5 mirror or production activation.
The CLI emits counts/provenance only; local Python API returns licensed OHLCVA.

No vendor certification of physical units, corporate actions/adjustments,
non-5m cycle labels or weekly/monthly date semantics is implied.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PERIODS = ("1min", "5min", "15min", "30min", "60min", "day", "week", "month")
MINUTES = ("1min", "5min")
FIELDS = ("open", "high", "low", "close", "volume", "amount")


def _load(tag, name):
    spec = importlib.util.spec_from_file_location(tag, HERE / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PURCHASED = _load("all_cycle_original_parquet_query", "query-parquet-primary-readonly.py")
MINUTE = _load("all_cycle_private_gap_minute_query",
               "query-purchased-primary-minute-with-private-gap-readonly.py")


def query_bars(root, symbol, period, first, last, *,
               allow_verified_private_h5=False,
               max_candidate_rows=30000000, max_result_bars=10000):
    """Return original-source bars in local memory; no writes or silent fill."""
    if period not in PERIODS:
        raise ValueError("Unsupported K-line cycle (adjustment factors are not K-lines)")
    if type(allow_verified_private_h5) is not bool:
        raise ValueError("Private H5 fallback must be explicitly boolean")
    if allow_verified_private_h5 and period not in MINUTES:
        raise ValueError("Verified private H5 fallback exists only for 1min/5min")
    # The original purchased API enforces single-security identity and bounded
    # 1..31 calendar day range before any market file is opened.
    canonical, _, _ = PURCHASED.request_dates(
        symbol, period, first, last, max_candidate_rows, max_result_bars)
    if period in MINUTES:
        result = MINUTE.query_bars(
            root, canonical, period, first, last,
            allow_verified_private_h5=allow_verified_private_h5,
            max_candidate_rows=max_candidate_rows,
            max_result_bars=max_result_bars)
        bars = result["bars"]
        sources = result["safe_summary"]["bars_by_source"]
        # Querying a period with purchased missing indexes still fails closed.
        source_gate = "purchased_key_index_first_with_explicit_h5_stockday_fallback"
    else:
        result = PURCHASED.query_bars(
            root, canonical, period, first, last,
            max_candidate_rows=max_candidate_rows,
            max_result_bars=max_result_bars, local_cache=False)
        bars = [{
            "symbol": row["symbol"], "period": row["period"],
            "trading_date": row["trading_date"],
            "source_timestamp_ms": row["source_timestamp_ms"],
            "source_beijing_time": row["source_beijing_time"],
            "value_source": "purchased_parquet",
            "source_file_relative_path": row["source_file_relative_path"],
            "source_row_group": row["source_row_group"],
            "h5_native_datetime": None,
            **{field: row[field] for field in FIELDS},
        } for row in result["bars"]]
        sources = {"purchased_parquet": len(bars)}
        source_gate = "original_purchased_parquet_direct_no_h5"
    if any(row.get("symbol") != canonical or row.get("period") != period
           for row in bars):
        raise ValueError("Unified cycle query returned a foreign symbol/period")
    if sum(sources.values()) != len(bars):
        raise ValueError("Unified cycle provenance counts mismatch")
    if len({row["source_timestamp_ms"] for row in bars}) != len(bars):
        raise ValueError("Unified cycle returned duplicate timestamps")
    return {
        "bars": bars,
        "safe_summary": {
            "format": "AStockDataTools purchased-primary eight-cycle research query v1",
            "period": period, "symbol": canonical,
            "from_day": str(first), "through_day": str(last),
            "matching_bar_count": len(bars),
            "bars_by_source": sources,
            "routing": source_gate,
            "purchased_source_priority": True,
            "verified_private_h5_fallback_enabled": allow_verified_private_h5,
            "vendor_physical_units_certified": False,
            "corporate_action_adjustments_certified": False,
            "period_time_label_semantics_certified_for_all_cycles": False,
            "weekly_monthly_labels_are_raw_source_dates": period in ("week", "month"),
            "original_market_files_modified": False,
            "new_market_or_index_files_written": False,
            "production_query_activated": False,
            "no_raw_ohlcva_in_safe_summary": True,
        },
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--period", choices=PERIODS, required=True)
    p.add_argument("--from-day", required=True)
    p.add_argument("--through-day", required=True)
    p.add_argument("--allow-verified-private-h5", action="store_true")
    p.add_argument("--max-result-bars", type=int, default=10000)
    p.add_argument("--max-candidate-rows", type=int, default=30000000)
    args = p.parse_args(argv)
    result = query_bars(
        args.root, args.symbol, args.period, args.from_day, args.through_day,
        allow_verified_private_h5=args.allow_verified_private_h5,
        max_candidate_rows=args.max_candidate_rows,
        max_result_bars=args.max_result_bars)
    print(json.dumps(result["safe_summary"], ensure_ascii=False,
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
