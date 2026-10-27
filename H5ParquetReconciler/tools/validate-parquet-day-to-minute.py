#!/usr/bin/env python3
"""Read-only same-vendor Parquet day vs 1min/5min OHLCVA conservation audit.

Keeps original source files immutable and exported JSON free of OHLCVA values.
Checks single fully traded stock-day only; incomplete grids are not approved.
Daily quantity/amount unit factors are HYPOTHESES, not automatic conversions.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "parquet_primary_minute_validator_for_day", HERE /
    "validate-parquet-1min-to-5min.py")
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)
core = validator.core
FIELDS = validator.FIELDS
FACTOR_CANDIDATES = (1, 100, 0.01)


def expected_keys(day):
    """241 end-labelled 1min (09:30 extra) and 48 start-labelled 5min."""
    day_text = day.strftime("%Y%m%d")
    one_minutes = ([9 * 60 + 30] +
                   list(range(9 * 60 + 31, 11 * 60 + 31)) +
                   list(range(13 * 60 + 1, 15 * 60 + 1)))
    five_minutes = list(validator.REGULAR_5MIN_STARTS)
    def stamp(minute):
        return int(day_text + f"{minute // 60:02d}{minute % 60:02d}")
    one = frozenset(map(stamp, one_minutes))
    five = frozenset(map(stamp, five_minutes))
    if len(one) != 241 or len(five) != 48:
        raise ValueError("Session key grid generation failed")
    return {"1min": one, "5min": five}


def aggregate_bars(records, sym, expected_stamps):
    """Full-session OHLCVA in timestamp order or None for incomplete/extra."""
    subset = {t: v for (source_sym, t), v in records.items()
              if source_sym == sym}
    if set(subset) != set(expected_stamps):
        return None
    ordered = [subset[t] for t in sorted(expected_stamps)]
    if not ordered:
        return None
    return (
        ordered[0][0], max(b[1] for b in ordered),
        min(b[2] for b in ordered), ordered[-1][3],
        math.fsum(b[4] for b in ordered),
        math.fsum(b[5] for b in ordered),
    )


def compare_day_values(daily, intraday):
    """No source OHLCVA printed. Separately report strict matches and factors."""
    if daily is None or intraday is None:
        return {"comparable": False, "strict_ohlc_agree": False,
                "strict_all_six_raw_agree": False,
                "strict_field_agree": {}, "existing_tolerance_field_agree": {},
                "volume_factor_strict_match": {}, "amount_factor_strict_match": {},
                "volume_factor_tolerance_match": {},
                "amount_factor_tolerance_match": {},
                "relative_ratio_day_over_intraday": {}}
    strict = {}
    tolerant = {}
    for i, field in enumerate(FIELDS):
        strict[field] = validator.strict_equal(daily[i], intraday[i])
        tolerant[field] = validator.diagnose.close_enough(
            daily[i], intraday[i], "price" if i < 4 else field)
    def factor_matches(index, field, strict_checker):
        return {str(f): bool(intraday[index] > 0 and daily[index] > 0
                and strict_checker(daily[index], intraday[index] * f))
                for f in FACTOR_CANDIDATES}
    result = {
        "comparable": True,
        "strict_ohlc_agree": all(strict[f] for f in validator.PRICE_FIELDS),
        "strict_all_six_raw_agree": all(strict.values()),
        "existing_tolerance_all_six_raw_agree": all(tolerant.values()),
        "strict_field_agree": strict,
        "existing_tolerance_field_agree": tolerant,
        "volume_factor_strict_match": factor_matches(
            4, "volume", validator.strict_equal),
        "amount_factor_strict_match": factor_matches(
            5, "amount", validator.strict_equal),
        "volume_factor_tolerance_match": factor_matches(
            4, "volume", lambda a,b:
            validator.diagnose.close_enough(a,b,"volume")),
        "amount_factor_tolerance_match": factor_matches(
            5, "amount", lambda a,b:
            validator.diagnose.close_enough(a,b,"amount")),
        # Ratios are exploratory magnitudes, not raw licensed OHLCVA.
        "relative_ratio_day_over_intraday": {
            field: (round(daily[i] / intraday[i], 9)
                    if intraday[i] != 0 else None)
            for i, field in ((4, "volume"), (5, "amount"))
        },
    }
    return result


def quality_of_day_record(daily):
    if daily is None:
        return {"day_bar_found": False, "quality_issues": []}
    issues = []
    if daily[1] < max(daily[0],daily[2],daily[3]) - 1e-7 or daily[2] > min(
            daily[0],daily[1],daily[3]) + 1e-7:
        issues.append("invalid_daily_ohlc_geometry")
    if daily[4] < 0 or daily[5] < 0:
        issues.append("negative_daily_quantity_or_amount")
    return {"day_bar_found": True, "quality_issues": issues}


def audit_stock_day(day, symbols, one, five, daily, scans):
    keys = expected_keys(day)
    day_stamp = int(day.strftime("%Y%m%d")) * 10000
    prior = validator.compare_symbols(
        one, five, scans["1min"], scans["5min"], symbols, day)
    result = {}
    for sym in symbols:
        d = daily.get((sym, day_stamp))
        one_keys = {k[1] for k in one if k[0] == sym}
        five_keys = {k[1] for k in five if k[0] == sym}
        extra_1min = len(one_keys - keys["1min"])
        missing_1min = len(keys["1min"] - one_keys)
        extra_5min = len(five_keys - keys["5min"])
        missing_5min = len(keys["5min"] - five_keys)
        one_agg = aggregate_bars(one, sym, keys["1min"])
        five_agg = aggregate_bars(five, sym, keys["5min"])
        daily_quality = quality_of_day_record(d)
        two_periods = prior[sym]
        opening_expected = "five_start_minute_end_plus_opening_0930"
        internal = two_periods["hypotheses"].get(opening_expected, {})
        internal_full = (
            two_periods["availability"] == "testable_parquet_both_periods_available"
            and internal.get("whole_day", {}).get(
                "strict_all_six_fields_agree") == 48
            and internal.get("whole_day", {}).get(
                "complete_one_minute_windows") == 48
            and missing_1min == extra_1min == missing_5min == extra_5min == 0
            and not two_periods["one_minute_quality"]["issue_counts"]
            and not two_periods["five_minute_quality"]["issue_counts"])
        no_scan_anomalies = all(
            not scans[period].get(field, 0)
            for period in ("day","1min","5min")
            for field in ("duplicate_keys", "nonfinite_source_rows",
                          "invalid_timestamp_rows"))
        result[sym] = {
            "day_bar_present": d is not None,
            "day_quality": daily_quality,
            "parquet_1min_rows": len(one_keys),
            "parquet_5min_rows": len(five_keys),
            "one_minute_missing_expected_stamps": missing_1min,
            "one_minute_outside_expected_grid": extra_1min,
            "five_minute_missing_expected_stamps": missing_5min,
            "five_minute_outside_expected_grid": extra_5min,
            "one_to_five_opening_rule_strict_48_of_48": internal_full,
            "day_vs_1min": compare_day_values(d, one_agg),
            "day_vs_5min": compare_day_values(d, five_agg),
            # Fully unscaled strict consistency; do not bless a volume
            # or amount factor until independently documented.
            "raw_all_three_periods_strict_agree": bool(
                d is not None and internal_full and no_scan_anomalies
                and not daily_quality["quality_issues"]
                and compare_day_values(d, one_agg)["strict_all_six_raw_agree"]
                and compare_day_values(d, five_agg)["strict_all_six_raw_agree"]),
            "unit_factor_matches_are_hypotheses_only": True,
            "not_certified_if_daily_missing_or_partial": True,
        }
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--symbols", nargs="+", required=True)
    ap.add_argument("--max-candidate-rows", type=int, default=30000000,
                    help="Maximum candidate source rows PER period, 1..100M")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
        symbols = tuple(dict.fromkeys(s.upper() for s in args.symbols))
        if not 1 <= len(symbols) <= 12 or any(
                core.symbol_id(s) != s or not core.is_a_share_candidate(
                    s, day.year) for s in symbols):
            raise ValueError("Provide 1..12 valid A-share candidate symbols")
        if not 1 <= args.max_candidate_rows <= 100000000:
            raise ValueError("row cap must be 1..100,000,000 per period")
        out, scratch = core.resolve_module_artifact_paths(args.out)
        root, _, _ = core.resolve_safe_paths(args.root, out, scratch)
        if (out.suffix.lower() != ".json"
                or not out.is_relative_to((HERE.parent / "reports").resolve())
                or out.exists()):
            raise ValueError("Choose a NEW JSON output inside module reports/")
        source = {}
        scans = {}
        for period in ("day", "5min", "1min"):
            source[period], scans[period] = validator.read_parquet_period(
                root, period, day, symbols, args.max_candidate_rows)
            print("Parquet", period, "selected", len(source[period]),
                  "candidate RowGroups", scans[period][
                      "candidate_row_groups_to_read"], flush=True)
        output = {
            "format": "AStockDataTools Parquet three-period full-day conservation v1",
            "date": day.isoformat(),
            "selected_symbols": list(symbols),
            "read_cost_by_period": scans,
            "expected_regular_1min_count_with_opening_0930": 241,
            "expected_regular_5min_count": 48,
            "stock_day_results": audit_stock_day(
                day, symbols, source["1min"], source["5min"],
                source["day"], scans),
            "strict_float_comparison": {
                "absolute": 1e-6, "relative": 1e-10},
            "source_daily_adjustment_or_quantity_units_certified": False,
            "raw_market_ohlcva_exported": False,
            "h5_source_accessed": False,
            "source_market_files_modified": False,
            "safe_to_automatically_union": False,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as fh:
            json.dump(output, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("Wrote Parquet day↔minute report:", out)
    except (ValueError, OSError, OverflowError, TypeError,
            json.JSONDecodeError) as error:
        ap.error(str(error))


if __name__ == "__main__":
    main()
