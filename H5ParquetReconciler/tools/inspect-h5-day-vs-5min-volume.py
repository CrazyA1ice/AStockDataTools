#!/usr/bin/env python3
"""Read-only H5 day-vs-5min volume conservation probe on bounded A-share windows.

This checks consistency of TWO H5 cycles, not vendor/trading truth.
It uses existing candidate day transCount*100 vs two minute scenarios
(unchanged H5 minute transCount, or transCount*100).
No purchased Parquet data rows or raw OHLCV values enter the output.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
SPEC = importlib.util.spec_from_file_location(
    "h5_cross_cycle_core", HERE / "reconcile-local-a-share-h5-parquet.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)

# Candidate exchange regular session ending labels. If observed timestamps
# contain the known H5 13:00 anomaly, exclude those stock-days from exact
# 48-bar conservation rather than accepting a misleading match.
REGULAR_FIVE_MINUTE_ENDS = frozenset(
    int((datetime(2000, 1, 1, 9, 35) + timedelta(minutes=5*i)).strftime("%H%M"))
    for i in range(24)
) | frozenset(
    int((datetime(2000, 1, 1, 13, 5) + timedelta(minutes=5*i)).strftime("%H%M"))
    for i in range(24)
)
if len(REGULAR_FIVE_MINUTE_ENDS) != 48:
    raise RuntimeError("Expected 48 distinct candidate regular-session bar ends")


def read_candidate_market_file(root, market, period, year, lower, upper):
    import h5py

    path = root / "HikyuuData" / (market + "_" + period + ".h5")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or symlinked H5 market file: " + path.name)
    values = {}
    invalid = 0
    with h5py.File(path, "r") as h5:
        group = h5.get("data")
        if not isinstance(group, h5py.Group):
            raise ValueError("H5 data group unavailable: " + path.name)
        for symbol in group:
            if not core.is_a_share_candidate(symbol, year):
                continue
            ds = group.get(symbol)
            if not isinstance(ds, h5py.Dataset) or not {
                    "datetime", "transCount"}.issubset(ds.dtype.names or ()):
                invalid += 1
                continue
            if len(ds) and int(ds[0]["datetime"]) > int(ds[-1]["datetime"]):
                invalid += 1
                continue
            left, right = core.h5_key_slice(ds, lower, upper)
            if left == right:
                continue
            # Use h5py field selection: only timestamps and volumes are
            # fetched. Do not materialize OHLC or transAmount source values.
            stamps = ds.fields("datetime")[left:right]
            volume = ds.fields("transCount")[left:right]
            for stamp, amount in zip(stamps, volume):
                stamp, amount = int(stamp), int(amount)
                key = (symbol, stamp // 10000)
                values.setdefault(key, []).append((stamp % 10000, amount))
    return values, invalid


def matching_volume(day_raw, five_minute_raw, relative_tolerance=0.001):
    """Use identical 0.1% tolerance for both candidate conversions."""
    target = day_raw * 100
    return (abs(five_minute_raw - target) <=
            max(1, relative_tolerance * max(abs(five_minute_raw), abs(target))))


def tally_one_stock_day(day_records, minute_records, counters):
    """Keep only complete/unique trading day pairs in volume comparisons."""
    counters["stock_days_with_both_cycles"] += 1
    days = [x for x in day_records if x[0] == 0]
    if len(day_records) != 1 or len(days) != 1:
        counters["day_bar_not_single_midnight"] += 1
        return
    stamps = [stamp for stamp, _ in minute_records]
    if len(stamps) != 48 or len(set(stamps)) != 48 or set(stamps) != REGULAR_FIVE_MINUTE_ENDS:
        counters["five_minute_session_not_48_exact"] += 1
        return
    daily_raw = days[0][1]
    minute_raw_sum = sum(q for _, q in minute_records)
    daily_normalized = daily_raw * 100
    baseline_minute = minute_raw_sum
    candidate_minute = minute_raw_sum * 100

    counters["complete_48_bar_stock_days_compared"] += 1
    counters["baseline_day_minute_volume_agree_0_1pct"] += int(
        matching_volume(daily_raw, baseline_minute))
    counters["candidate_day_minute_volume_agree_0_1pct"] += int(
        matching_volume(daily_raw, candidate_minute))
    counters["h5_raw_daily_equals_sum_minute_raw_exact"] += int(
        daily_raw == minute_raw_sum)
    counters["daily_and_minute_both_zero"] += int(
        daily_normalized == 0 and candidate_minute == 0)
    counters["day_minute_raw_mismatch_above_0_1pct"] += int(
        not matching_volume(daily_raw, candidate_minute))
    # No numbers from this stock-day are written to report.


def make_report(root, year, from_date, to_date):
    low, high, _, _ = core.parse_day_range(year, from_date, to_date)
    result = {
        "format": "AStockDataTools H5 day-vs-5min volume candidate audit v1",
        "year": year, "from_date": from_date, "to_date": to_date,
        "universe": "a-share-candidate",
        "expected_session_end_labels": 48,
        "time_label_rule_certified": False,
        "h5_day_volume_factor_100_certified": False,
        "h5_five_minute_volume_factor_100_certified": False,
        "candidate_day_target": "H5 day transCount * 100",
        "baseline_minute_test": "sum(H5 5min transCount) versus candidate day target",
        "candidate_minute_test": "sum(H5 5min transCount * 100) versus candidate day target",
        "volume_match_relative_tolerance": 0.001,
        "only_exact_48_label_stock_days_are_compared": True,
        "sorted_dataset_assumption_not_independently_certified": True,
        "not_independent_vendor_ground_truth": True,
        "does_not_validate_parquet_units": True,
        "source_files_modified": False,
        "no_raw_ohlcv_exported": True,
        "safe_to_automatically_union": False
    }
    totals = Counter()
    by_day = {}
    for market in ("sh", "sz", "bj"):
        day, day_invalid = read_candidate_market_file(
            root, market, "day", year, low, high)
        minute, min_invalid = read_candidate_market_file(
            root, market, "5min", year, low, high)
        totals["invalid_day_candidate_datasets"] += day_invalid
        totals["invalid_minute_candidate_datasets"] += min_invalid
        for key in set(day) | set(minute):
            symbol, stamp_day = key
            bucket = by_day.setdefault(str(stamp_day), Counter())
            totals["candidate_stock_days_either_cycle"] += 1
            bucket["candidate_stock_days_either_cycle"] += 1
            d = day.get(key)
            m = minute.get(key)
            if d is None:
                totals["stock_days_only_minute"] += 1
                bucket["stock_days_only_minute"] += 1
            elif m is None:
                totals["stock_days_only_day"] += 1
                bucket["stock_days_only_day"] += 1
            else:
                tally_one_stock_day(d, m, totals)
                tally_one_stock_day(d, m, bucket)
    if (totals["candidate_stock_days_either_cycle"]
        != totals["stock_days_only_minute"] + totals["stock_days_only_day"]
           + totals["stock_days_with_both_cycles"]):
        raise ValueError("Cross-cycle stock-day coverage did not conserve")
    if (totals["stock_days_with_both_cycles"]
        != totals["day_bar_not_single_midnight"]
           + totals["five_minute_session_not_48_exact"]
           + totals["complete_48_bar_stock_days_compared"]):
        raise ValueError("Complete 48-bar subset did not conserve")
    for key in ("baseline_day_minute_volume_agree_0_1pct",
                "candidate_day_minute_volume_agree_0_1pct",
                "h5_raw_daily_equals_sum_minute_raw_exact",
                "daily_and_minute_both_zero",
                "day_minute_raw_mismatch_above_0_1pct"):
        if totals[key] > totals["complete_48_bar_stock_days_compared"]:
            raise ValueError("Cross-cycle agreement exceeds compared count")
    if (totals["candidate_day_minute_volume_agree_0_1pct"]
        + totals["day_minute_raw_mismatch_above_0_1pct"]
        != totals["complete_48_bar_stock_days_compared"]):
        raise ValueError("Cross-cycle candidate matches do not conserve")
    result["totals"] = dict(sorted(totals.items()))
    result["by_day"] = {
        d: dict(sorted(c.items())) for d, c in sorted(by_day.items())
    }
    result["scan_complete"] = (
        totals["invalid_day_candidate_datasets"] == 0
        and totals["invalid_minute_candidate_datasets"] == 0)
    result["unit_mapping_certified"] = False
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        if not 2000 <= args.year <= 2030:
            raise ValueError("Year outside supported range")
        output, scratch = core.resolve_module_artifact_paths(args.out)
        root, _, _ = core.resolve_safe_paths(args.root, output, scratch)
        report_dir = (MODULE / "reports").resolve()
        if output.suffix.lower() != ".json" or not output.is_relative_to(report_dir):
            raise ValueError("Output must be JSON under module reports/")
        if output.exists():
            raise ValueError("Refusing to overwrite existing report")
        if not (root / "HikyuuData").is_dir():
            raise ValueError("Missing HikyuuData source")
        report = make_report(root, args.year, args.from_date, args.to_date)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("Saved readonly H5 cross-cycle volume report:", output, flush=True)
    except (OSError, ValueError) as error:
        ap.error(str(error))


if __name__ == "__main__":
    main()
