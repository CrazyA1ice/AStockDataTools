#!/usr/bin/env python3
"""Independent Parquet-only 1min -> 5min reconstruction, by selected stock-day.

Both periods come from PURCHASED PARQUET, never from H5. Read-only;
bounded source row-group projection. Try both source time-label hypotheses,
require five distinct observed 1min keys; report strict and existing-tolerance
agreement separately. This checks internal consistency, NOT exchange truth.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent


def import_local(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagnose = import_local("parquet_internal_diagnostic", "diagnose-5min-alignment.py")
core = diagnose.core
PRICE_FIELDS = ("open", "high", "low", "close")
FIELDS = PRICE_FIELDS + ("volume", "amount")
CONVENTIONS = (
    "five_start_minute_start",
    "five_start_minute_end",
    "five_start_minute_end_plus_opening_0930",
    "five_end_minute_start",
    "five_end_minute_end",
)
VOLUME_FACTORS = (1, 100, 0.01)
REGULAR_5MIN_STARTS = tuple(
    list(range(9 * 60 + 30, 11 * 60 + 26, 5))
    + list(range(13 * 60, 14 * 60 + 56, 5))
)
REGULAR_5MIN_ENDS = tuple(x + 5 for x in REGULAR_5MIN_STARTS)


def time_parts(ts):
    dt = datetime.strptime(str(ts), "%Y%m%d%H%M")
    return dt, dt.hour * 60 + dt.minute


def observed_one_minute_stamps(five_stamp, convention):
    if convention not in CONVENTIONS:
        raise ValueError("Unsupported Parquet label hypothesis")
    dt, _ = time_parts(five_stamp)
    five_starts = convention.startswith("five_start_")
    minute_starts = convention.endswith("minute_start")
    # The five-minute source label is at t0 if start, t0+5 if end.
    # A 1min source labels [t0,t0+1,...t0+4] if start;
    # [t0+1,t0+2,...t0+5] if end.
    offsets = [i + (0 if minute_starts else 1)
               - (0 if five_starts else 5) for i in range(5)]
    stamps = tuple(int((dt + timedelta(minutes=x)).strftime("%Y%m%d%H%M"))
                   for x in offsets)
    if (convention == "five_start_minute_end_plus_opening_0930"
            and dt.hour == 9 and dt.minute == 30):
        # Test (do not assume) that a separately labelled opening key 09:30
        # is included ONCE, only in the first 09:30-09:35 five-minute bar.
        # The other 47 five-minute bars retain exactly five 1min keys.
        return (five_stamp,) + stamps
    return stamps


def aggregate_one_minute(minute, sym, five_stamp, convention):
    keys = [(sym, t) for t in observed_one_minute_stamps(
        five_stamp, convention)]
    if any(key not in minute for key in keys):
        return None
    samples = [minute[key] for key in keys]
    return (samples[0][0], max(bar[1] for bar in samples),
            min(bar[2] for bar in samples), samples[-1][3],
            math.fsum(bar[4] for bar in samples),
            math.fsum(bar[5] for bar in samples))


def strict_equal(a, b):
    """Near exact numeric equality; distinct from loose historic audit rules."""
    return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-6)


def bucket():
    return {
        "five_minute_bars": 0,
        "complete_one_minute_windows": 0,
        "incomplete_one_minute_windows": 0,
        "ohlc_strict_all_agree": 0,
        "ohlc_existing_tolerance_all_agree": 0,
        "strict_all_six_fields_agree": 0,
        "existing_tolerance_all_six_fields_agree": 0,
        "strict_field_agree": {field: 0 for field in FIELDS},
        "existing_tolerance_field_agree": {field: 0 for field in FIELDS},
        "nonzero_volume_windows": 0,
        "volume_factor_existing_tolerance_nonzero": {
            str(factor): 0 for factor in VOLUME_FACTORS},
        "volume_both_zero_windows": 0,
    }


def compare_one_hypothesis(one, five, symbol, convention):
    """Returns aggregates only, with morning/afternoon conservation checks."""
    results = {"whole_day": bucket(), "morning": bucket(),
               "afternoon": bucket()}
    missing_examples = []
    mismatched_examples = []
    ratio = {"volume": [], "amount": []}
    for (sym, stamp), bar in sorted(five.items()):
        if sym != symbol:
            continue
        _, clock = time_parts(stamp)
        session = "morning" if clock < 12 * 60 else "afternoon"
        pools = (results["whole_day"], results[session])
        for dst in pools:
            dst["five_minute_bars"] += 1
        combined = aggregate_one_minute(one, sym, stamp, convention)
        if combined is None:
            for dst in pools:
                dst["incomplete_one_minute_windows"] += 1
            if len(missing_examples) < 8:
                missing_examples.append(str(stamp))
            continue
        for dst in pools:
            dst["complete_one_minute_windows"] += 1
        strict_flags, tolerant_flags = [], []
        for i, field in enumerate(FIELDS):
            strict = strict_equal(bar[i], combined[i])
            loose = diagnose.close_enough(
                bar[i], combined[i],
                "price" if i < 4 else field)
            strict_flags.append(strict)
            tolerant_flags.append(loose)
            for dst in pools:
                dst["strict_field_agree"][field] += int(strict)
                dst["existing_tolerance_field_agree"][field] += int(loose)
        if not all(strict_flags) and len(mismatched_examples) < 8:
            mismatched_examples.append({
                "five_minute_source_stamp": str(stamp),
                "strict_mismatched_fields": [
                    field for field, equal in zip(FIELDS, strict_flags)
                    if not equal],
                "existing_tolerance_mismatched_fields": [
                    field for field, equal in zip(FIELDS, tolerant_flags)
                    if not equal],
                "is_first_morning_five_minute_bar": clock == 570,
                "one_minute_input_keys": len(
                    observed_one_minute_stamps(stamp, convention)),
            })
        for dst in pools:
            dst["ohlc_strict_all_agree"] += int(all(strict_flags[:4]))
            dst["ohlc_existing_tolerance_all_agree"] += int(
                all(tolerant_flags[:4]))
            dst["strict_all_six_fields_agree"] += int(all(strict_flags))
            dst["existing_tolerance_all_six_fields_agree"] += int(
                all(tolerant_flags))
            if bar[4] == 0 and combined[4] == 0:
                dst["volume_both_zero_windows"] += 1
            else:
                dst["nonzero_volume_windows"] += 1
            for factor in VOLUME_FACTORS:
                if (bar[4] != 0 or combined[4] != 0) and diagnose.close_enough(
                        bar[4], combined[4] * factor, "volume"):
                    dst["volume_factor_existing_tolerance_nonzero"][
                        str(factor)] += 1
        for i, field in ((4, "volume"), (5, "amount")):
            if combined[i]:
                r = bar[i] / combined[i]
                if math.isfinite(r):
                    ratio[field].append(r)
    for value in results.values():
        if value["five_minute_bars"] != (
                value["complete_one_minute_windows"]
                + value["incomplete_one_minute_windows"]):
            raise ValueError("Parquet minute window count not conserved")
        if (value["volume_both_zero_windows"]
                + value["nonzero_volume_windows"]
                != value["complete_one_minute_windows"]):
            raise ValueError("Parquet minute volume denominator not conserved")
    whole = results["whole_day"]
    for field in ("five_minute_bars", "complete_one_minute_windows",
                  "incomplete_one_minute_windows", "strict_all_six_fields_agree",
                  "existing_tolerance_all_six_fields_agree"):
        if whole[field] != results["morning"][field] + results["afternoon"][field]:
            raise ValueError("Parquet minute morning/afternoon totals inconsistent")
    return {
        **results,
        "missing_five_minute_source_stamps_examples": missing_examples,
        "mismatched_five_minute_source_stamps_examples": mismatched_examples,
        "five_over_minute_volume_ratio_nonzero": diagnose.summarize_values(
            ratio["volume"], digits=6),
        "five_over_minute_amount_ratio_nonzero": diagnose.summarize_values(
            ratio["amount"], digits=6),
    }


def quality_checks(rows, symbol, period, day):
    """Do not hide unusual session keys or nonfinite/bad-OHLC records."""
    issues = Counter()
    stamps = set()
    for (sym, stamp), data in rows.items():
        if sym != symbol:
            continue
        stamps.add(stamp)
        dt, minute = time_parts(stamp)
        if dt.date() != day:
            issues["outside_requested_trading_day"] += 1
        if period == "5min":
            if minute not in REGULAR_5MIN_STARTS and minute not in REGULAR_5MIN_ENDS:
                issues["nonstandard_five_minute_source_label"] += 1
        else:
            if not ((570 <= minute <= 690) or (780 <= minute <= 900)):
                issues["outside_broad_regular_one_minute_label"] += 1
        if data[1] < max(data[0], data[3], data[2]) - 1e-7 or data[2] > min(
                data[0], data[3], data[1]) + 1e-7:
            issues["bad_ohlc_geometry"] += 1
        if data[4] < 0 or data[5] < 0:
            issues["negative_volume_or_amount"] += 1
    return {"unique_keys": len(stamps), "issue_counts": dict(issues)}


def compare_symbols(one, five, one_scan, five_scan, symbols, day):
    output = {}
    for sym in symbols:
        one_keys = sum(k[0] == sym for k in one)
        five_keys = sum(k[0] == sym for k in five)
        if not five_keys:
            availability = "not_verifiable_no_parquet_5min_rows"
        elif not one_keys:
            availability = "not_verifiable_no_parquet_1min_rows"
        elif one_scan["duplicate_keys"] or five_scan["duplicate_keys"]:
            availability = "not_verifiable_duplicate_parquet_keys"
        elif one_scan["nonfinite_source_rows"] or five_scan["nonfinite_source_rows"]:
            availability = "not_verifiable_nonfinite_parquet_values"
        else:
            availability = "testable_parquet_both_periods_available"
        source = {
            "parquet_1min_source_bars": one_keys,
            "parquet_5min_source_bars": five_keys,
            "one_minute_quality": quality_checks(one, sym, "1min", day),
            "five_minute_quality": quality_checks(five, sym, "5min", day),
            "opening_0930_one_minute_key_present": (
                (sym, int(day.strftime("%Y%m%d") + "0930")) in one),
            "first_0930_five_minute_key_present": (
                (sym, int(day.strftime("%Y%m%d") + "0930")) in five),
            "availability": availability,
        }
        if availability != "testable_parquet_both_periods_available":
            source["hypotheses"] = {}
            source["best_internal_convention_candidate"] = None
            source["internal_5min_all_bars_tolerance_match"] = False
            output[sym] = source
            continue
        results = {convention: compare_one_hypothesis(one, five, sym, convention)
                   for convention in CONVENTIONS}
        def rank(name):
            a = results[name]["whole_day"]
            return (a["existing_tolerance_all_six_fields_agree"],
                    a["strict_all_six_fields_agree"],
                    a["complete_one_minute_windows"])
        best = max(CONVENTIONS, key=rank)
        winner = results[best]["whole_day"]
        at_least_two = winner["complete_one_minute_windows"] > 0
        # Mark full-day match only with all 48 existing 5min source bars and
        # 1:1 volume/amount, plus no quality issues or duplicates.
        safe_full = (
            five_keys == 48 and winner["complete_one_minute_windows"] == 48
            and winner["existing_tolerance_all_six_fields_agree"] == 48
            and winner["nonzero_volume_windows"] > 0
            and winner["volume_factor_existing_tolerance_nonzero"]["1"]
                == winner["nonzero_volume_windows"]
            and not source["one_minute_quality"]["issue_counts"]
            and not source["five_minute_quality"]["issue_counts"])
        source["hypotheses"] = results
        source["opening_0930_included_once_by_candidate"] = (
            best == "five_start_minute_end_plus_opening_0930"
            and source["opening_0930_one_minute_key_present"]
            and source["first_0930_five_minute_key_present"])
        source["best_internal_convention_candidate"] = (
            best if at_least_two else None)
        source["internal_5min_all_bars_tolerance_match"] = safe_full
        source["strict_all_six_fields_agree_of_five_bars"] = winner[
            "strict_all_six_fields_agree"]
        source["interpretation"] = (
            "Strong single stock-day conditional internal evidence, NOT "
            "certified market truth" if safe_full else
            "Incomplete or inconsistent internal evidence; inspect counters")
        output[sym] = source
    return output


def read_parquet_period(root, period, day, symbols, max_candidate_source_rows, *, plan_only=False):
    """Bounded rowgroup scan; only selected symbol/day tuples persist in RAM."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    paths = core.year_files(root, period, day.year)
    result = {
        "availability": "source_files_present" if paths else "no_period_files_for_year",
        "files": len(paths),
        "row_groups_in_period_year": 0,
        "row_groups_skipped_time": 0,
        "row_groups_skipped_symbol_statistics": 0,
        "candidate_row_groups_to_read": 0,
        "candidate_source_rows_upper_bound": 0,
        "candidate_uncompressed_bytes_upper_bound": 0,
        "source_rows_examined": 0,
        "selected_source_rows": 0,
        "duplicate_keys": 0,
        "nonfinite_source_rows": 0,
        "invalid_timestamp_rows": 0,
        "parquet_schema_checked": True,
    }
    records = {}
    if not paths:
        return records, result
    _, _, start_ms, end_ms = core.parse_day_range(
        day.year, day.isoformat(), day.isoformat())
    aliases = set().union(*(diagnose.source_spellings(s) for s in symbols))
    aliases_pa = pa.array(sorted(aliases), type=pa.string())
    pending = []
    for path in paths:
        pf = pq.ParquetFile(str(path))
        if not set(core.NEEDED).issubset(pf.schema_arrow.names):
            raise ValueError("Missing Parquet OHLCVA/key columns in " + path.name)
        for idx in range(pf.metadata.num_row_groups):
            result["row_groups_in_period_year"] += 1
            rg = pf.metadata.row_group(idx)
            if not core.row_group_overlaps_timestamp(rg, start_ms, end_ms):
                result["row_groups_skipped_time"] += 1
                continue
            if not diagnose.might_contain_symbols(rg, aliases):
                result["row_groups_skipped_symbol_statistics"] += 1
                continue
            result["candidate_row_groups_to_read"] += 1
            result["candidate_source_rows_upper_bound"] += int(rg.num_rows)
            result["candidate_uncompressed_bytes_upper_bound"] += int(rg.total_byte_size)
            pending.append((path, pf, idx))
    if plan_only:
        # Strictly metadata-only: no iter_batches/column values, including
        # when candidate row-group count exceeds the selected decode budget.
        result["plan_only_metadata_opened"] = True
        result["market_ohlcva_columns_read"] = False
        result["source_rows_examined"] = 0
        result["candidate_rows_within_configured_cap"] = (
            result["candidate_source_rows_upper_bound"] <= max_candidate_source_rows)
        return {}, result
    if result["candidate_source_rows_upper_bound"] > max_candidate_source_rows:
        raise ValueError(
            f"{period} Parquet candidate rowgroups contain "
            f"{result['candidate_source_rows_upper_bound']:,} source rows; "
            f"exceeds --max-candidate-rows {max_candidate_source_rows:,}. "
            "No source K-line values have been read; increase cap consciously.")
    for path, pf, idx in pending:
        for batch in pf.iter_batches(
                row_groups=[idx], batch_size=131072,
                columns=list(core.NEEDED), use_threads=True):
            result["source_rows_examined"] += batch.num_rows
            try:
                yes = pc.is_in(batch.column(1), value_set=aliases_pa)
                yes = pc.and_(yes, pc.greater_equal(batch.column(0), start_ms))
                yes = pc.and_(yes, pc.less(batch.column(0), end_ms))
                matching = batch.filter(yes).to_pylist()
            except (pa.ArrowInvalid, pa.ArrowNotImplementedError, TypeError):
                matching = [row for row in batch.to_pylist()
                            if row["symbol"] in aliases and isinstance(
                                row["ts"], (int, float))
                            and start_ms <= row["ts"] < end_ms]
            result["selected_source_rows"] += len(matching)
            for row in matching:
                sym = core.symbol_id(row["symbol"])
                if sym not in symbols:
                    continue
                try:
                    timestamp = int(row["ts"])
                    if timestamp % 60000:
                        result["invalid_timestamp_rows"] += 1
                        continue
                    stamp = core.pq_stamp(timestamp, "day" if period == "day" else "1min")
                    values = tuple(float(row[field]) for field in FIELDS)
                    if not all(math.isfinite(x) for x in values):
                        result["nonfinite_source_rows"] += 1
                        continue
                except (TypeError, ValueError, OverflowError, OSError):
                    result["invalid_timestamp_rows"] += 1
                    continue
                key = (sym, stamp)  # minute labels raw; daily stamps normalized to YYYYMMDD0000
                if key in records:
                    result["duplicate_keys"] += 1
                    continue
                records[key] = values
    result["unique_selected_keys"] = len(records)
    if not records:
        result["availability"] = "no_selected_symbol_date_rows"
    return records, result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path, help="Original AllCycleAStockData root")
    ap.add_argument("--date", type=str, required=True, help="YYYY-MM-DD")
    ap.add_argument("--symbols", nargs="+",
                    default=["SH688629", "SH688017", "SH688172"])
    ap.add_argument("--max-candidate-rows", type=int, default=30000000,
                    help="Per-period source rowgroup decoded-row safety cap (default 30M)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--plan-only", action="store_true",
                    help="Only inspect both period Parquet row-group metadata; do not read any OHLCVA")
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
        symbols = tuple(dict.fromkeys(s.upper() for s in args.symbols))
        if not 1 <= len(symbols) <= 12 or any(core.symbol_id(s) != s
                                               or not core.is_a_share_candidate(
                                                   s, day.year) for s in symbols):
            raise ValueError("Supply 1..12 valid A-share candidate SH/SZ/BJ symbols")
        if not 1 <= args.max_candidate_rows <= 100000000:
            raise ValueError("--max-candidate-rows must be between 1 and 100M")
        output, scratch = core.resolve_module_artifact_paths(args.out)
        root, _, _ = core.resolve_safe_paths(args.root, output, scratch)
        if (output.suffix.lower() != ".json"
            or not output.is_relative_to((HERE.parent / "reports").resolve())
            or output.exists()):
            raise ValueError("Choose a new, unused JSON inside module reports/")
        if args.plan_only:
            _, five_plan = read_parquet_period(
                root, "5min", day, symbols, args.max_candidate_rows,
                plan_only=True)
            _, one_plan = read_parquet_period(
                root, "1min", day, symbols, args.max_candidate_rows,
                plan_only=True)
            report = {
                "format": "AStockDataTools Parquet only 1min to 5min metadata preflight v1",
                "date": day.isoformat(), "symbols": list(symbols),
                "parquet_5min_plan": five_plan, "parquet_1min_plan": one_plan,
                "max_candidate_rows_per_period": args.max_candidate_rows,
                "both_periods_within_configured_cap": (
                    five_plan["candidate_rows_within_configured_cap"]
                    and one_plan["candidate_rows_within_configured_cap"]),
                "plan_only_metadata_opened": True,
                "raw_ohlcva_columns_read": False,
                "no_h5_source_accessed": True,
                "source_market_files_modified": False,
                "source_correctness_certified": False,
                "safe_to_automatically_union": False,
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as fp:
                json.dump(report, fp, ensure_ascii=False, indent=2)
                fp.write("\n")
            print("Saved metadata-only 1min/5min Parquet read plan:", output, flush=True)
            return
        five, five_scan = read_parquet_period(
            root, "5min", day, symbols, args.max_candidate_rows)
        print("Parquet 5min selected:", len(five),
              "rowgroups:", five_scan["candidate_row_groups_to_read"], flush=True)
        one, one_scan = read_parquet_period(
            root, "1min", day, symbols, args.max_candidate_rows)
        print("Parquet 1min selected:", len(one),
              "rowgroups:", one_scan["candidate_row_groups_to_read"], flush=True)
        report = {
            "format": "AStockDataTools Parquet only 1min to 5min aggregation v1",
            "date": day.isoformat(), "symbols": list(symbols),
            "parquet_5min_read": five_scan,
            "parquet_1min_read": one_scan,
            "symbols_validation": compare_symbols(
                one, five, one_scan, five_scan, symbols, day),
            "tested_source_labels": list(CONVENTIONS),
            "one_to_five_minute_aggregation_hypotheses_only": True,
            "opening_0930_special_bar_not_assumed_without_data": True,
            "both_periods_are_same_purchased_parquet_vendor": True,
            "no_h5_source_accessed": True,
            "source_market_files_modified": False,
            "raw_ohlcva_exported": False,
            "source_correctness_certified": False,
            "safe_to_automatically_union": False,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("Saved Parquet-only cross-period evidence:", output, flush=True)
    except (ValueError, OSError, OverflowError, json.JSONDecodeError) as e:
        ap.error(str(e))


if __name__ == "__main__":
    main()
