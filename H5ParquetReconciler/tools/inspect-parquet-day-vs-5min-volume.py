#!/usr/bin/env python3
"""Compare purchased Parquet day volume against 5min sums, read-only.

Only bounded ts/symbol/volume Arrow columns are decoded; uses row-group
timestamp footers to prune irrelevant data. This audits Parquet internal
consistency independently of H5, not official exchange volume truth.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
SPEC = importlib.util.spec_from_file_location(
    "pq_cross_cycle_core", HERE / "reconcile-local-a-share-h5-parquet.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)
H5_SPEC = importlib.util.spec_from_file_location(
    "h5_session_labels", HERE / "inspect-h5-day-vs-5min-volume.py")
h5probe = importlib.util.module_from_spec(H5_SPEC)
H5_SPEC.loader.exec_module(h5probe)
EXPECTED_ENDS = h5probe.REGULAR_FIVE_MINUTE_ENDS


def volume_match(left, right, rel=0.001):
    return abs(left-right) <= max(1.0, rel * max(abs(left), abs(right)))


def load_cycle(root, year, period, from_date, to_date, batch_size):
    import pyarrow.parquet as pq

    paths = core.year_files(root, period, year)
    if not paths:
        raise ValueError("No Parquet files for " + period + "/" + str(year))
    _, _, low_ms, high_ms = core.parse_day_range(year, from_date, to_date)
    totals = Counter({"source_files": len(paths)})
    # For a bounded window only: record one volume per symbol+minute key.
    rows = {}
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing or symlinked Parquet source")
        parquet = pq.ParquetFile(str(path))
        if not {"ts", "symbol", "volume"}.issubset(
                parquet.schema_arrow.names):
            raise ValueError("Parquet cycle missing required fields: " + period)
        for rgid in range(parquet.metadata.num_row_groups):
            rg = parquet.metadata.row_group(rgid)
            totals["row_groups_total"] += 1
            if not core.row_group_overlaps_timestamp(rg, low_ms, high_ms):
                totals["row_groups_skipped_by_footer"] += 1
                continue
            totals["row_groups_read"] += 1
            for batch in parquet.iter_batches(
                    row_groups=[rgid], batch_size=batch_size,
                    columns=["ts", "symbol", "volume"], use_threads=True):
                times = batch.column(0).to_pylist()
                symbols = batch.column(1).to_pylist()
                volumes = batch.column(2).to_pylist()
                totals["source_rows_inspected_in_read_groups"] += len(times)
                for raw_stamp, raw_sym, raw_vol in zip(times, symbols, volumes):
                    stamp_ms = int(raw_stamp)
                    if not low_ms <= stamp_ms < high_ms:
                        continue
                    sym = core.symbol_id(raw_sym)
                    if sym is None:
                        totals["unrecognized_symbol_rows"] += 1
                        continue
                    if not core.is_a_share_candidate(sym, year):
                        totals["excluded_non_equity_candidate_rows"] += 1
                        continue
                    stamp = core.pq_stamp(stamp_ms, period)
                    if not (int(from_date.replace("-", "")) <= stamp // 10000
                            <= int(to_date.replace("-", ""))):
                        continue
                    v = float(raw_vol)
                    if not math.isfinite(v) or v < 0:
                        raise ValueError("Non-finite/negative Parquet volume encountered")
                    key = (sym, stamp)
                    if key in rows:
                        totals["duplicate_source_keys"] += 1
                        continue
                    rows[key] = v
                    totals["unique_candidate_keys"] += 1
    return rows, dict(totals)


def compare_cycles(day_rows, minute_rows):
    days = {}
    minutes = {}
    for (sym, stamp), vol in day_rows.items():
        key = (sym, stamp // 10000)
        days.setdefault(key, []).append((stamp % 10000, vol))
    for (sym, stamp), vol in minute_rows.items():
        key = (sym, stamp // 10000)
        minutes.setdefault(key, []).append((stamp % 10000, vol))

    overall = Counter()
    by_date = {}
    examples = []
    for key in sorted(days.keys() | minutes.keys()):
        sym, trading_day = key
        totals = by_date.setdefault(str(trading_day), Counter())
        overall["candidate_stock_days_either_cycle"] += 1
        totals["candidate_stock_days_either_cycle"] += 1
        d, m = days.get(key), minutes.get(key)
        if d is None or m is None:
            label = ("stock_days_only_five_minute" if d is None
                     else "stock_days_only_day")
            overall[label] += 1
            totals[label] += 1
            continue
        for stats in (overall, totals):
            stats["stock_days_with_both_cycles"] += 1
        if len(d) != 1 or d[0][0] != 0:
            for stats in (overall, totals):
                stats["day_record_not_one_midnight"] += 1
            continue
        labels = [label for label, _ in m]
        if (len(labels) != 48 or len(set(labels)) != 48
            or set(labels) != EXPECTED_ENDS):
            for stats in (overall, totals):
                stats["five_minute_session_not_48_exact"] += 1
            continue
        day_volume = d[0][1]
        minute_sum = math.fsum(vol for _, vol in m)
        matches = {
            "raw_day_equals_sum_five_minute_0_1pct":
                volume_match(day_volume, minute_sum),
            "day_times_100_equals_sum_five_minute_0_1pct":
                volume_match(day_volume * 100, minute_sum),
            "day_equals_sum_five_minute_times_100_0_1pct":
                volume_match(day_volume, minute_sum * 100)
        }
        for stats in (overall, totals):
            stats["complete_48_bar_stock_days_compared"] += 1
            for name, matched in matches.items():
                stats[name] += int(matched)
        if not matches["raw_day_equals_sum_five_minute_0_1pct"] and len(examples) < 12:
            examples.append({"symbol": sym, "day": str(trading_day),
                             "issue": "Parquet_day_vs_5min_raw_sum_over_0.1pct"})
    if (overall["candidate_stock_days_either_cycle"]
        != overall["stock_days_only_five_minute"]
           + overall["stock_days_only_day"]
           + overall["stock_days_with_both_cycles"]):
        raise ValueError("Parquet day/5min candidate stock-day count inconsistent")
    if (overall["stock_days_with_both_cycles"]
        != overall["day_record_not_one_midnight"]
           + overall["five_minute_session_not_48_exact"]
           + overall["complete_48_bar_stock_days_compared"]):
        raise ValueError("Parquet day/5min valid subset inconsistent")
    for name in (
        "raw_day_equals_sum_five_minute_0_1pct",
        "day_times_100_equals_sum_five_minute_0_1pct",
        "day_equals_sum_five_minute_times_100_0_1pct"
    ):
        if overall[name] > overall["complete_48_bar_stock_days_compared"]:
            raise ValueError("Parquet volume hypothesis count above denominator")
    return dict(sorted(overall.items())), {
        day: dict(sorted(stats.items())) for day, stats in sorted(by_date.items())
    }, examples


def make_report(root, year, from_date, to_date, batch_size=8192):
    left, right = date.fromisoformat(from_date), date.fromisoformat(to_date)
    core.parse_day_range(year, from_date, to_date)
    if (right-left).days > 6:
        raise ValueError("Parquet cross-cycle probe is limited to 7 calendar days")
    daily, dmeta = load_cycle(root, year, "day", from_date, to_date, batch_size)
    minute, mmeta = load_cycle(root, year, "5min", from_date, to_date, batch_size)
    totals, by_day, examples = compare_cycles(daily, minute)
    return {
        "format": "AStockDataTools Parquet day-vs-5min volume candidate audit v1",
        "year": year, "from_date": from_date, "to_date": to_date,
        "universe": "a-share-candidate",
        "day_source": dmeta,
        "five_minute_source": mmeta,
        "totals": totals, "by_day": by_day,
        "nonconserving_stock_day_examples": examples,
        "time_mapping": "day local date, 5min ts starts +5 minutes (unverified)",
        "candidate_regular_session_ends": 48,
        "regular_session_labels_certified": False,
        "volume_match_relative_tolerance": 0.001,
        "source_values_modified": False,
        "raw_ohlcv_exported": False,
        "unit_mapping_certified": False,
        "safe_to_automatically_union": False,
        "scan_complete": (
            dmeta.get("duplicate_source_keys", 0) == 0
            and mmeta.get("duplicate_source_keys", 0) == 0
            and dmeta.get("unrecognized_symbol_rows", 0) == 0
            and mmeta.get("unrecognized_symbol_rows", 0) == 0),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--to-date", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=8192)
    parser.add_argument("--read-only", required=True, action="store_true")
    args = parser.parse_args(argv)
    try:
        if not 2000 <= args.year <= 2030 or not 512 <= args.batch_size <= 65536:
            raise ValueError("Invalid year or batch size")
        output, scratch = core.resolve_module_artifact_paths(args.out)
        root, _, _ = core.resolve_safe_paths(args.root, output, scratch)
        directory = (MODULE / "reports").resolve()
        if output.suffix != ".json" or not output.is_relative_to(directory):
            raise ValueError("Output must be JSON under module reports/")
        if output.exists():
            raise ValueError("Refusing to overwrite an existing report")
        if not (root / "AllCycleAStockData" / "day").is_dir() or not (
                root / "AllCycleAStockData" / "5min").is_dir():
            raise ValueError("Missing purchased Parquet day/5min source folder")
        report = make_report(root, args.year, args.from_date, args.to_date,
                             args.batch_size)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        print("Saved read-only Parquet day/5min volume audit:", output)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
