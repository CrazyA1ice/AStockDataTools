#!/usr/bin/env python3
"""Find anomalous stock-days by scanning ONLY Parquet (ts, symbol) for one month.

No OHLCVA columns or H5 sources are read. No source files are changed.
Normal 1min 241-slot and 5min 48-slot conventions are hypotheses validated
for recent 2026 sampled stock-days, not a guarantee for earlier years.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE_SPEC = importlib.util.spec_from_file_location(
    "parquet_month_stock_day_core", HERE /
    "reconcile-local-a-share-h5-parquet.py")
core = importlib.util.module_from_spec(CORE_SPEC)
CORE_SPEC.loader.exec_module(core)
MODULE = HERE.parent
EPOCH = date(1970, 1, 1)
SLOTS = {
    "1min": {minute: idx for idx, minute in enumerate(
        list(range(570, 691)) + list(range(781, 901)))},
    "5min": {minute: idx for idx, minute in enumerate(
        list(range(570, 686, 5)) + list(range(780, 896, 5)))},
}
SIZES = {"1min": 241, "5min": 48}


def month_edges(year, month):
    if not 2011 <= year <= 2100 or not 1 <= month <= 12:
        raise ValueError("Invalid year-month")
    low = date(year, month, 1)
    high = date(year+1, 1, 1) if month == 12 else date(year, month+1, 1)
    start_ms = int(datetime(low.year, low.month, low.day,
                            tzinfo=core.UTC8).timestamp() * 1000)
    end_ms = int(datetime(high.year, high.month, high.day,
                          tzinfo=core.UTC8).timestamp() * 1000)
    return low, high, start_ms, end_ms


def decode_key(epoch_ms, year, month, ordinal_cache):
    """Minute precision Beijing time, raw 5min labels never shifted."""
    try:
        t = int(epoch_ms)
    except (ValueError, TypeError, OverflowError):
        return None, "bad_timestamp"
    if not 1_000_000_000_000 <= t < 10_000_000_000_000 or t % 60000:
        return None, "bad_timestamp"
    day_ordinal, minute_of_day = divmod(t // 60000 + 480, 1440)
    if day_ordinal not in ordinal_cache:
        try:
            ordinal_cache[day_ordinal] = EPOCH + timedelta(days=day_ordinal)
        except OverflowError:
            return None, "bad_timestamp"
    trade_date = ordinal_cache[day_ordinal]
    if trade_date.year != year or trade_date.month != month:
        return None, "outside_month"
    return (trade_date.isoformat(), minute_of_day), None


def group_key_statistics(source_rows, period, year, month,
                         universe="all", max_stock_days=1000000):
    """Stream test helper; input yields (ts, raw_symbol) without prices."""
    slots = SLOTS[period]
    found = {}
    counters = Counter()
    ordinals = {}
    for ts, raw_symbol in source_rows:
        counters["source_rows_considered"] += 1
        decoded, why = decode_key(ts, year, month, ordinals)
        if why:
            counters[why] += 1
            continue
        symbol = core.symbol_id(raw_symbol)
        if symbol is None:
            counters["unrecognized_symbol"] += 1
            continue
        if (universe == "a-share-candidate"
                and not core.is_a_share_candidate(symbol, year)):
            counters["excluded_non_candidate_symbol"] += 1
            continue
        day, minute = decoded
        key = (symbol, day)
        if key not in found:
            if len(found) >= max_stock_days:
                raise ValueError(
                    "Stock-day cardinality exceeds --max-stock-days")
            found[key] = [0, 0, 0]
        row = found[key]
        row[1] += 1
        slot = slots.get(minute)
        if slot is None:
            row[2] += 1
            counters["unexpected_session_labels"] += 1
        else:
            before = row[0]
            row[0] |= (1 << slot)
            if row[0] == before:
                counters["duplicate_session_labels"] += 1
            counters["valid_session_rows"] += 1
    return found, dict(sorted(counters.items()))


def grade_month(one, five, year, month, limit=60):
    masks = {p: (1 << n) - 1 for p, n in SIZES.items()}
    summary = Counter()
    affected = []
    combined = sorted(set(one) | set(five),
                      key=lambda x: (x[1], x[0]))
    for symbol, day in combined:
        vals = {}
        for p, source in (("1min", one), ("5min", five)):
            mask, rows, offgrid = source.get((symbol, day), (0, 0, 0))
            missing = SIZES[p] - int(mask).bit_count()
            duplicates = max(
                0, rows - offgrid - int(mask).bit_count())
            vals[p] = {"source_rows": rows,
                       "distinct_expected_labels": int(mask).bit_count(),
                       "missing_expected_labels": missing,
                       "duplicate_expected_labels": duplicates,
                       "unexpected_session_labels": offgrid}
            summary[p + "_total_rows"] += rows
            summary[p + "_missing_expected_labels"] += missing
            summary[p + "_duplicate_expected_labels"] += duplicates
            summary[p + "_unexpected_session_labels"] += offgrid
            if rows:
                summary[p + "_stock_days_present"] += 1
            if rows and missing == duplicates == offgrid == 0:
                summary[p + "_complete_stock_days"] += 1
        if vals["1min"]["source_rows"] and vals["5min"]["source_rows"]:
            summary["stock_days_with_both_periods"] += 1
        if vals["1min"]["source_rows"] and not vals["5min"]["source_rows"]:
            summary["stock_days_one_minute_only"] += 1
        if vals["5min"]["source_rows"] and not vals["1min"]["source_rows"]:
            summary["stock_days_five_minute_only"] += 1
        healthy = all(vals[p]["missing_expected_labels"] == 0
                      and vals[p]["duplicate_expected_labels"] == 0
                      and vals[p]["unexpected_session_labels"] == 0
                      for p in SIZES)
        if healthy:
            summary["complete_stock_days_in_both_periods"] += 1
        else:
            summary["stock_days_with_incomplete_or_unexpected_keys"] += 1
            if len(affected) < limit:
                affected.append({"date": day, "symbol": symbol,
                                 "one_minute": vals["1min"],
                                 "five_minute": vals["5min"]})
    return {
        "candidate_stock_day_universe_count": len(combined),
        "stock_day_summary": dict(sorted(summary.items())),
        "sample_anomalous_stock_days": affected,
        "anomalous_stock_day_examples_limit": limit,
        "examples_are_truncated": summary[
            "stock_days_with_incomplete_or_unexpected_keys"] > len(affected),
        "missing_expected_labels_are_hypothesis_based_not_exchange_truth": True,
        "historical_holidays_delistings_and_auctions_not_certified": True,
    }


def scan_period(root, year, month, period, universe, max_rows,
                max_stock_days):
    import pyarrow.parquet as pq

    low, high, start_ms, end_ms = month_edges(year, month)
    files = core.year_files(root, period, year)
    pending = []
    metadata = Counter()
    for path in files:
        pf = pq.ParquetFile(str(path))
        if not {"ts", "symbol"}.issubset(pf.schema_arrow.names):
            raise ValueError("Missing ts/symbol in: " + path.name)
        metadata["year_file_footers_examined"] += 1
        for index in range(pf.metadata.num_row_groups):
            rg = pf.metadata.row_group(index)
            metadata["row_groups_examined"] += 1
            if not core.row_group_overlaps_timestamp(rg, start_ms, end_ms):
                metadata["row_groups_pruned_outside_month"] += 1
                continue
            metadata["candidate_rows_upper_bound"] += int(rg.num_rows)
            pending.append((pf, index))
    if metadata["candidate_rows_upper_bound"] > max_rows:
        raise ValueError(
            f"{period} candidate rowgroups contain "
            f"{metadata['candidate_rows_upper_bound']:,} source rows; "
            f"exceeds --max-candidate-rows {max_rows:,}. "
            "Increase explicitly after reviewing the metadata budget.")
    def keys():
        for pf, idx in pending:
            for batch in pf.iter_batches(
                    row_groups=[idx], batch_size=65536,
                    columns=["ts", "symbol"], use_threads=True):
                metadata["projected_key_rows_read"] += batch.num_rows
                for t, symbol in zip(
                        batch.column(0).to_pylist(),
                        batch.column(1).to_pylist()):
                    yield t, symbol
    groups, counts = group_key_statistics(
        keys(), period, year, month, universe, max_stock_days)
    return groups, {
        **dict(sorted(metadata.items())),
        "key_classification": counts,
        "source_stock_days_seen": len(groups),
        "prices_volumes_amounts_read": False,
        "source_files_modified": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--universe", choices=("all","a-share-candidate"),
                    default="all")
    ap.add_argument("--max-candidate-rows", type=int, default=50000000,
                    help="Upper bound of projected candidate key rows PER period")
    ap.add_argument("--max-stock-days", type=int, default=1000000)
    ap.add_argument("--max-examples", type=int, default=60)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        month_edges(args.year, args.month)
        if not (1 <= args.max_candidate_rows <= 100000000
                and 1 <= args.max_stock_days <= 10000000
                and 1 <= args.max_examples <= 200):
            raise ValueError("Excessive or invalid budget/limit")
        out, scratch = core.resolve_module_artifact_paths(args.out)
        root, _, _ = core.resolve_safe_paths(args.root, out, scratch)
        if (out.suffix.lower() != ".json" or out.exists()
                or not out.is_relative_to((MODULE / "reports").resolve())):
            raise ValueError("Use a NEW report filename inside module reports/")
        source = {}
        scans = {}
        for period in ("1min","5min"):
            source[period], scans[period] = scan_period(
                root,args.year,args.month,period,args.universe,
                args.max_candidate_rows,args.max_stock_days)
            print("Month",period,"key-rows",scans[period].get(
                "projected_key_rows_read",0),flush=True)
        details = grade_month(source["1min"],source["5min"],
                              args.year,args.month,args.max_examples)
        report = {
            "format": "AStockDataTools Parquet month key-only stock-day audit v1",
            "year": args.year, "month": args.month,
            "universe": args.universe,
            "scan_cost": scans,
            **details,
            "raw_market_ohlcva_exported": False,
            "h5_source_accessed": False,
            "source_market_files_modified": False,
            "day_prices_or_amounts_verified": False,
            "eligible_for_auto_aggregation_or_import": False,
        }
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as f:
            json.dump(report,f,ensure_ascii=False,indent=2)
            f.write("\n")
        print("Saved month key-only Parquet anomaly report:",out)
        print("Anomalous stock-days:",details["stock_day_summary"].get(
            "stock_days_with_incomplete_or_unexpected_keys",0))
    except (ValueError,TypeError,OSError,OverflowError,
            ModuleNotFoundError) as error:
        ap.error(str(error))


if __name__=="__main__":
    main()
