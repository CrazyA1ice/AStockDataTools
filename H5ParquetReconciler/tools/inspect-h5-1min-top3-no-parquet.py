#!/usr/bin/env python3
"""Read-only H5 1min -> H5 5min crosscheck for verified 2026 top-3 symbols.

Do NOT read Parquet or infer vendor correctness. Prior same-day PQ/H5 evidence
provides symbols only. Compare two 1min time-label conventions and two possible
minute volume units against H5 5min raw transCount×100. Return only counters.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent

def import_local(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

one = import_local("h5_only_one_minute_reader", "validate-5min-against-h5-1min.py")
diagnose = one.diagnostic
core = one.core

VOLUME_ONE_MINUTE_FACTORS = (1, 100)
EXPECTED_FIVE_MINUTE_COUNT = 48
PRICE_FIELDS = ("open", "high", "low", "close")


def select_existing_symbols(report, day):
    """Use prior fully checked three-stock result; never invent selections."""
    if (not isinstance(report, dict)
        or report.get("format") !=
           "AStockDataTools x100 focused 5min residual session forensic v1"
        or report.get("date") != day.isoformat()
        or report.get("source_files_modified") is not False
        or report.get("no_raw_ohlcv_exported") is not True
        or report.get("unit_mapping_certified") is not False
        or report.get("safe_to_automatically_union") is not False
        or report.get("h5_five_minute_volume_factor_candidate") != 100):
        raise ValueError("Need the completed matching ×100 three-symbol session report")
    symbols = report.get("selected_symbols")
    summary = report.get("symbol_results")
    if (not isinstance(symbols, list) or not 1 <= len(symbols) <= 8
        or len(set(symbols)) != len(symbols) or not isinstance(summary, dict)
        or set(symbols) != set(summary)):
        raise ValueError("Invalid selected symbol identities in baseline")
    for symbol in symbols:
        item = summary[symbol]
        if (not isinstance(symbol, str)
            or core.symbol_id(symbol) != symbol
            or not core.is_a_share_candidate(symbol, day.year)
            or not isinstance(item, dict)
            or item.get("status") != "hypothesis_diagnostic_only"
            or item.get("h5_5min_bars") != EXPECTED_FIVE_MINUTE_COUNT
            or item.get("parquet_5min_bars") != EXPECTED_FIVE_MINUTE_COUNT
            or item.get("h5_only_bars") != 0
            or item.get("parquet_only_bars") != 0
            or item.get("candidate_volume_factor_h5") != 100
            or item.get("matched_only") is not True
            or sum(item.get("exact_residual_masks", {}).values())
               != EXPECTED_FIVE_MINUTE_COUNT):
            raise ValueError("Baseline has a non-comparable selected stock-day")
    return tuple(symbols)


def new_bucket():
    return {
        "complete_windows": 0, "incomplete_windows": 0,
        "all_ohlc_agree": 0,
        "price_field_agree": {field: 0 for field in PRICE_FIELDS},
        "amount_agree": 0,
        "volume_both_zero_windows": 0,
        "nonzero_volume_windows": 0,
        "volume_match_minute_multiplier": {
            str(multiplier): 0 for multiplier in VOLUME_ONE_MINUTE_FACTORS},
        "volume_match_nonzero_minute_multiplier": {
            str(multiplier): 0 for multiplier in VOLUME_ONE_MINUTE_FACTORS},
    }


def complete_window_result(five_rows, minute_rows, symbol, convention):
    """Only fully observed 5×1min windows contribute price/volume comparisons."""
    by_session = {"morning": new_bucket(), "afternoon": new_bucket()}
    overall = new_bucket()
    examples = []
    seen = 0
    for (ticker, stamp), bar in sorted(five_rows.items()):
        if ticker != symbol:
            continue
        seen += 1
        session = "morning" if 935 <= stamp % 10000 <= 1130 else (
            "afternoon" if 1305 <= stamp % 10000 <= 1500 else None)
        if session is None:
            raise ValueError("H5 five-minute out-of-session time label")
        pools = (overall, by_session[session])
        agg = one.aggregate_minute_window(minute_rows, symbol, stamp, convention)
        if agg is None:
            for pool in pools:
                pool["incomplete_windows"] += 1
            if len(examples) < 8:
                examples.append(str(stamp))
            continue
        for pool in pools:
            pool["complete_windows"] += 1
        ohlc_good = True
        for i, field in enumerate(PRICE_FIELDS):
            ok = diagnose.close_enough(bar[i], agg[i], "price")
            if not ok:
                ohlc_good = False
            for pool in pools:
                pool["price_field_agree"][field] += int(ok)
        for pool in pools:
            pool["all_ohlc_agree"] += int(ohlc_good)
            pool["amount_agree"] += int(
                diagnose.close_enough(bar[5], agg[5], "amount"))
        # H5 5min was independently strongly suggested to represent lots.
        # Compare in candidate share units to avoid a spurious 1-lot floor.
        five_in_shares = bar[4] * 100.0
        if five_in_shares == 0 and agg[4] == 0:
            for pool in pools:
                pool["volume_both_zero_windows"] += 1
        else:
            for pool in pools:
                pool["nonzero_volume_windows"] += 1
        for factor in VOLUME_ONE_MINUTE_FACTORS:
            ok = diagnose.close_enough(
                five_in_shares, agg[4] * factor, "volume")
            for pool in pools:
                pool["volume_match_minute_multiplier"][str(factor)] += int(ok)
                if five_in_shares != 0 or agg[4] != 0:
                    pool["volume_match_nonzero_minute_multiplier"][str(factor)] += int(ok)
    if seen != EXPECTED_FIVE_MINUTE_COUNT:
        raise ValueError("H5 5min source count changed since focused baseline")
    for bucket in (overall, *by_session.values()):
        if bucket["complete_windows"] + bucket["incomplete_windows"] > seen:
            raise ValueError("Minute window count exceeds H5 5min stock-day")
        if bucket["volume_both_zero_windows"] + bucket["nonzero_volume_windows"] != (
                bucket["complete_windows"]):
            raise ValueError("H5 minute volume candidate denominator mismatch")
    if sum(x["complete_windows"] for x in by_session.values()) != overall[
            "complete_windows"] or sum(x["incomplete_windows"] for x in by_session.values()
            ) != overall["incomplete_windows"]:
        raise ValueError("H5 minute session conservation failed")
    if (overall["complete_windows"] + overall["incomplete_windows"] != seen
        or (by_session["morning"]["complete_windows"]
            + by_session["morning"]["incomplete_windows"]) != 24
        or (by_session["afternoon"]["complete_windows"]
            + by_session["afternoon"]["incomplete_windows"]) != 24):
        raise ValueError("Incomplete H5 five-minute regular-session labels")
    return {
        "five_minute_bars": seen,
        "whole_day": overall,
        "sessions": by_session,
        "missing_minute_window_end_labels_examples": examples,
        "minute_time_convention_certified": False,
        "minute_volume_unit_certified": False,
    }


def build_report_from_sources(symbols, h5_five, h5_one, one_coverage):
    out = {}
    for sym in symbols:
        status = one_coverage[sym]
        if status.get("duplicate_minute_keys", 0):
            out[sym] = {"one_minute_source": status,
                        "availability": "not_verifiable_duplicate_one_minute_keys",
                        "minute_convention_candidates": {}}
            continue
        if status.get("availability") != "has_records":
            out[sym] = {"one_minute_source": status,
                        "availability": "not_verifiable_no_one_minute_data",
                        "minute_convention_candidates": {}}
            continue
        conventions = {name: complete_window_result(
            h5_five, h5_one, sym, name) for name in one.CONVENTIONS}
        out[sym] = {
            "one_minute_source": status,
            "availability": (
                "candidate_windows_available" if any(
                    result["whole_day"]["complete_windows"] > 0
                    for result in conventions.values())
                else "not_verifiable_no_complete_one_minute_windows"),
            "minute_convention_candidates": conventions,
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path, help="Local source root; this tool never opens Parquet")
    ap.add_argument("--date", required=True)
    ap.add_argument("--baseline-report", type=Path, required=True,
                    help="Previous ×100 top3 session JSON for source identifiers")
    ap.add_argument("--out", type=Path, required=True,
                    help="New JSON under H5ParquetReconciler/reports")
    ap.add_argument("--read-only", required=True, action="store_true")
    args = ap.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
        output, scratch = core.resolve_module_artifact_paths(args.out)
        root, _, _ = core.resolve_safe_paths(args.root, output, scratch)
        if output.suffix.lower() != ".json" or not output.is_relative_to(
                (HERE.parent / "reports").resolve()):
            raise ValueError("Output must be a new JSON inside the module reports directory")
        if output.exists():
            raise ValueError("Refusing to overwrite existing report")
        baseline = args.baseline_report.resolve()
        if baseline.suffix.lower() != ".json" or baseline == output:
            raise ValueError("Baseline must be a different JSON report")
        symbols = select_existing_symbols(
            json.loads(baseline.read_text(encoding="utf-8")), day)
        h5_five, coverage_five = diagnose.load_h5(root, symbols, day)
        minute, coverage_one = one.load_h5_minute_day(root, symbols, day)
        if any(coverage_five[s].get("h5_duplicate_keys", 0)
               or coverage_five[s].get("h5_rows") != EXPECTED_FIVE_MINUTE_COUNT
               for s in symbols):
            raise ValueError("Invalid H5 5min keys for selected symbols")
        result = {
            "format": "AStockDataTools H5 one-minute top3 no-Parquet check v1",
            "date": day.isoformat(),
            "selected_symbols": list(symbols),
            "baseline_report_name": baseline.name,
            "parquet_source_read": False,
            "h5_source_values_modified": False,
            "original_report_modified": False,
            "raw_ohlcv_exported": False,
            "h5_five_minute_volume_times_100_candidate": True,
            "minute_start_vs_end_label_hypotheses": list(one.CONVENTIONS),
            "one_minute_volume_factor_candidate_values": list(VOLUME_ONE_MINUTE_FACTORS),
            "h5_1min_not_independent_vendor_ground_truth": True,
            "minute_unit_certified": False,
            "source_timestamp_mapping_certified": False,
            "safe_to_automatically_union": False,
            "h5_5min_coverage": coverage_five,
            "symbol_results": build_report_from_sources(
                symbols, h5_five, minute, coverage_one)
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as fp:
            json.dump(result, fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        print("Saved H5-only one-minute/5min top3 crosscheck:", output, flush=True)
    except (ValueError, OSError, OverflowError, json.JSONDecodeError) as error:
        ap.error(str(error))


if __name__ == "__main__":
    main()
