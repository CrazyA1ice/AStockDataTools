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
    missing_day_examples = []
    missing_minute_examples = []
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
            if d is None and len(missing_day_examples) < 24:
                labels = [stamp for stamp, _ in m]
                missing_day_examples.append({
                    "symbol": sym, "day": str(trading_day),
                    "five_minute_keys": len(labels),
                    "complete_48_candidate_labels": (
                        len(labels) == 48 and len(set(labels)) == 48
                        and set(labels) == EXPECTED_ENDS)
                })
            if m is None and len(missing_minute_examples) < 24:
                missing_minute_examples.append({
                    "symbol": sym, "day": str(trading_day),
                    "day_keys": len(d)
                })
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
    }, examples, missing_day_examples, missing_minute_examples


def validated_focus_symbols(symbols, year):
    if not symbols:
        return []
    out = []
    for raw in symbols:
        symbol = core.symbol_id(raw)
        if symbol is None or not core.is_a_share_candidate(symbol, year):
            raise ValueError("Focus symbol must be an A-share candidate: " + str(raw))
        if symbol not in out:
            out.append(symbol)
    if len(out) > 12:
        raise ValueError("Focus symbol list is limited to 12 securities")
    return sorted(out)


def read_h5_focused(root, year, from_date, to_date, focus_symbols):
    """Read only selected H5 securities, not all H5/Parquet stock records."""
    import h5py

    low, high, _, _ = core.parse_day_range(year, from_date, to_date)
    values = {}
    duplicates = 0
    for period in ("day", "5min"):
        for market in sorted({sym[:2].lower() for sym in focus_symbols}):
            path = root / "HikyuuData" / (market + "_" + period + ".h5")
            if path.is_symlink() or not path.is_file():
                raise ValueError("Missing or symlinked H5 focus market file: " + path.name)
            with h5py.File(path, "r") as file:
                group = file.get("data")
                if not isinstance(group, h5py.Group):
                    raise ValueError("Missing H5 focus data group: " + path.name)
                for symbol in focus_symbols:
                    if symbol[:2].lower() != market or symbol not in group:
                        continue
                    ds = group[symbol]
                    if not isinstance(ds, h5py.Dataset) or not {
                            "datetime", "transCount"}.issubset(ds.dtype.names or ()):
                        raise ValueError("Invalid H5 focus dataset: " + symbol)
                    if len(ds) and int(ds[0]["datetime"]) > int(ds[-1]["datetime"]):
                        raise ValueError("H5 focus timestamps not sorted: " + symbol)
                    left, right = core.h5_key_slice(ds, low, high)
                    stamps = ds.fields("datetime")[left:right]
                    volumes = ds.fields("transCount")[left:right]
                    for stamp, volume in zip(stamps, volumes):
                        key = (period, symbol, int(stamp))
                        if key in values:
                            duplicates += 1
                            continue
                        values[key] = float(volume)
    if duplicates:
        raise ValueError("Duplicate H5 focus time keys")
    return values


def relative_error_band(left, right):
    """Categorical anomaly magnitude; never export actual source quantities."""
    if left == 0 and right == 0:
        return "both_zero"
    if left == 0 or right == 0:
        return "one_side_zero"
    delta = abs(left-right) / max(abs(left), abs(right))
    if delta <= 0.0001:
        return "within_0.01pct"
    if delta <= 0.001:
        return "0.01_to_0.1pct"
    if delta <= 0.01:
        return "0.1_to_1pct"
    if delta <= 0.05:
        return "1_to_5pct"
    return "above_5pct"


def summarize_focus_day(root, year, from_date, to_date, focus_symbols,
                        parquet_day, parquet_minute):
    """Compare H5 and Parquet at both cycles without exposing licensed values."""
    if not focus_symbols:
        return {}
    h5 = read_h5_focused(root, year, from_date, to_date, focus_symbols)
    out = {}
    left = date.fromisoformat(from_date)
    last = date.fromisoformat(to_date)
    while left <= last:
        day_code = int(left.strftime("%Y%m%d"))
        for symbol in focus_symbols:
            hday = {t: v for (p,s,t),v in h5.items()
                    if p == "day" and s == symbol and t//10000 == day_code}
            hmin = {t: v for (p,s,t),v in h5.items()
                    if p == "5min" and s == symbol and t//10000 == day_code}
            pday = {t: v for (s,t),v in parquet_day.items()
                    if s == symbol and t//10000 == day_code}
            pmin = {t: v for (s,t),v in parquet_minute.items()
                    if s == symbol and t//10000 == day_code}
            # All comparisons use candidate end-label alignment; no source values
            # or trade-size ratios are included in the JSON.
            item = {
                "h5_day_keys": len(hday), "h5_5min_keys": len(hmin),
                "pq_day_keys": len(pday), "pq_5min_keys": len(pmin),
                "h5_complete_48_candidate_labels": (
                    len(hmin) == 48
                    and {t % 10000 for t in hmin} == EXPECTED_ENDS),
                "pq_complete_48_candidate_labels": (
                    len(pmin) == 48
                    and {t % 10000 for t in pmin} == EXPECTED_ENDS),
                "h5_day_vs_minute_raw_sum_agree_0_1pct": None,
                "pq_day_vs_minute_sum_agree_0_1pct": None,
                "h5_day_times_100_vs_pq_day_agree_0_1pct": None,
                "h5_minute_times_100_vs_pq_minute_sum_agree_0_1pct": None,
                "same_cycle_five_minute_intersection": len(hmin.keys() & pmin.keys()),
                "h5_only_five_minute_keys": len(hmin.keys() - pmin.keys()),
                "pq_only_five_minute_keys": len(pmin.keys() - hmin.keys()),
                "five_minute_volume_x100_mismatch_original_tolerance": 0,
                "five_minute_volume_x100_mismatch_0_1pct": 0,
                "minute_x100_discrepancy_bands": {},
                "mismatched_end_label_examples": []
            }
            hv = math.fsum(hmin.values())
            pv = math.fsum(pmin.values())
            if len(hday) == 1 and day_code * 10000 in hday and hmin:
                item["h5_day_vs_minute_raw_sum_agree_0_1pct"] = volume_match(
                    hday[day_code*10000], hv)
            if len(pday) == 1 and day_code * 10000 in pday and pmin:
                item["pq_day_vs_minute_sum_agree_0_1pct"] = volume_match(
                    pday[day_code*10000], pv)
            if (len(hday) == 1 and len(pday) == 1
                and day_code*10000 in hday and day_code*10000 in pday):
                item["h5_day_times_100_vs_pq_day_agree_0_1pct"] = volume_match(
                    hday[day_code*10000]*100,pday[day_code*10000])
            if hmin and pmin:
                item["h5_minute_times_100_vs_pq_minute_sum_agree_0_1pct"] = volume_match(
                    hv*100,pv)
            hist = Counter()
            for stamp in sorted(hmin.keys() & pmin.keys()):
                lhs, rhs = hmin[stamp]*100, pmin[stamp]
                hist[relative_error_band(lhs, rhs)] += 1
                strict_diff = abs(lhs-rhs) > max(
                    1.0, 0.00001 * max(abs(lhs),abs(rhs)))
                item["five_minute_volume_x100_mismatch_original_tolerance"] += int(
                    strict_diff)
                item["five_minute_volume_x100_mismatch_0_1pct"] += int(
                    not volume_match(lhs,rhs))
                if strict_diff and len(item["mismatched_end_label_examples"]) < 12:
                    item["mismatched_end_label_examples"].append(stamp % 10000)
            item["minute_x100_discrepancy_bands"] = dict(sorted(hist.items()))
            out[symbol + "@" + str(day_code)] = item
        left += timedelta(days=1)
    return out


def make_report(root, year, from_date, to_date, batch_size=8192,
                focus_symbols=()):
    left, right = date.fromisoformat(from_date), date.fromisoformat(to_date)
    core.parse_day_range(year, from_date, to_date)
    if (right-left).days > 6:
        raise ValueError("Parquet cross-cycle probe is limited to 7 calendar days")
    focus_symbols = validated_focus_symbols(focus_symbols, year)
    daily, dmeta = load_cycle(root, year, "day", from_date, to_date, batch_size)
    minute, mmeta = load_cycle(root, year, "5min", from_date, to_date, batch_size)
    totals, by_day, examples, gaps_day, gaps_minute = compare_cycles(daily, minute)
    focus = summarize_focus_day(root, year, from_date, to_date,
                                focus_symbols, daily, minute)
    return {
        "format": "AStockDataTools Parquet day-vs-5min volume candidate audit v1",
        "year": year, "from_date": from_date, "to_date": to_date,
        "universe": "a-share-candidate",
        "day_source": dmeta,
        "five_minute_source": mmeta,
        "totals": totals, "by_day": by_day,
        "nonconserving_stock_day_examples": examples,
        "missing_day_stock_day_examples": gaps_day,
        "missing_five_minute_stock_day_examples": gaps_minute,
        "focused_four_cycle_stock_days": focus,
        "focused_identifiers": focus_symbols,
        "focus_uses_only_h5_datetime_and_transCount_fields": True,
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
    parser.add_argument("--focus-symbols", nargs="*", default=[],
                        help="Optional <=12 A-share candidate symbols for H5/PQ 4-cycle focused checks")
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
                             args.batch_size, args.focus_symbols)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        print("Saved read-only Parquet day/5min volume audit:", output)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
