#!/usr/bin/env python3
"""Offline assessment of an ALREADY-GENERATED Parquet day/1min/5min JSON.

No Parquet/H5 market file access. Preserve strict comparison versus historic
tolerance, and report how close a small observed volume/amount mismatch is
without upgrading it to vendor, exchange, or unit certification.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]
EXPECTED_FORMAT = "AStockDataTools Parquet three-period full-day conservation v1"
SYMBOL_PATTERN = re.compile(r"^(SH|SZ|BJ)[0-9]{6}$")
FIELDS = ("open", "high", "low", "close", "volume", "amount")
EXPECTED_PERIODS = ("day", "1min", "5min")
DEFAULT_PPM_REVIEW_THRESHOLD = 10.0


def finite_ratio_gap_ppm(value):
    """Report magnitude only. Input day/minute ratios are rounded to 9 places."""
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("Nonfinite or nonnumeric day-to-minute ratio")
    if value <= 0:
        raise ValueError("Day/minute positive quantity ratio must be >0")
    return round(abs(value - 1.0) * 1_000_000, 6)


def require_bool(value, label):
    if type(value) is not bool:
        raise ValueError(label + " must be a JSON boolean")
    return value


def assess_stock(symbol, item, max_ppm):
    if not isinstance(item, dict):
        raise ValueError("Expected object for " + symbol)
    q = item.get("day_quality", {})
    if not isinstance(q, dict) or not isinstance(q.get("quality_issues"), list):
        raise ValueError("Invalid daily quality assessment for " + symbol)
    counts = {}
    for field in (
        "one_minute_missing_expected_stamps",
        "one_minute_outside_expected_grid",
        "five_minute_missing_expected_stamps",
        "five_minute_outside_expected_grid",
    ):
        x = item.get(field)
        if type(x) is not int or x < 0:
            raise ValueError("Invalid time-grid counter " + symbol + "/" + field)
        counts[field] = x
    day_present = require_bool(item.get("day_bar_present"), symbol + " day")
    minute_five_strict = require_bool(
        item.get("one_to_five_opening_rule_strict_48_of_48"),
        symbol + " minute-to-five")
    published_strict = require_bool(
        item.get("raw_all_three_periods_strict_agree"), symbol + " raw strict")
    basic_count = (item.get("parquet_1min_rows") == 241 and
                   item.get("parquet_5min_rows") == 48)
    complete = basic_count and not any(counts.values())
    valid_daily = day_present and q["day_bar_found"] is True and not q[
        "quality_issues"]
    out = {
        "raw_three_periods_strict_flag_from_original": published_strict,
        "day_present": day_present,
        "complete_241_and_48_time_grid": complete,
        "one_minute_to_five_strict_48_of_48": minute_five_strict,
        "daily_ohlc_quality_issues": list(q["quality_issues"]),
        "daily_vs_minute_evidence": {},
        "max_abs_relative_quantity_gap_ppm": None,
    }
    strict_all = True
    tolerant_all = True
    price_all = True
    ppm = []
    for period in ("1min", "5min"):
        src = item.get("day_vs_" + period)
        if not isinstance(src, dict):
            raise ValueError("Missing source comparison for " + symbol)
        comparable = require_bool(src.get("comparable"), symbol + " comparable")
        strict = require_bool(src.get("strict_all_six_raw_agree"),
                              symbol + " strict values")
        price = require_bool(src.get("strict_ohlc_agree"),
                             symbol + " strict prices")
        evidence = {
            "comparable": comparable,
            "strict_ohlc_agree": price,
            "strict_all_six_raw_agree": strict,
            "existing_tolerance_all_six_raw_agree": False,
            "strict_mismatch_fields": [],
            "existing_tolerance_mismatch_fields": [],
            "relative_quantity_gap_ppm": {"volume": None, "amount": None},
            "source_unit_factor_1_tolerance_candidate": False,
        }
        if comparable:
            strict_fields = src.get("strict_field_agree")
            loose_fields = src.get("existing_tolerance_field_agree")
            if (not isinstance(strict_fields, dict)
                    or not isinstance(loose_fields, dict)):
                raise ValueError("Missing per-field comparison in " + symbol)
            for field in FIELDS:
                require_bool(strict_fields.get(field), symbol + "/" + field)
                require_bool(loose_fields.get(field), symbol + "/" + field)
            evidence["strict_mismatch_fields"] = [
                f for f in FIELDS if not strict_fields[f]]
            evidence["existing_tolerance_mismatch_fields"] = [
                f for f in FIELDS if not loose_fields[f]]
            if strict != all(strict_fields[f] for f in FIELDS):
                raise ValueError("Contradictory strict flags in " + symbol)
            if price != all(strict_fields[f] for f in FIELDS[:4]):
                raise ValueError("Contradictory strict OHLC in " + symbol)
            tolerant = require_bool(
                src.get("existing_tolerance_all_six_raw_agree"),
                symbol + " tolerant")
            if tolerant != all(loose_fields[f] for f in FIELDS):
                raise ValueError("Contradictory tolerance flags in " + symbol)
            evidence["existing_tolerance_all_six_raw_agree"] = tolerant
            ratios = src.get("relative_ratio_day_over_intraday", {})
            if not isinstance(ratios, dict):
                raise ValueError("Invalid quantity ratios in " + symbol)
            for field in ("volume", "amount"):
                ratio = ratios.get(field)
                if ratio is not None:
                    gap = finite_ratio_gap_ppm(ratio)
                    evidence["relative_quantity_gap_ppm"][field] = gap
                    ppm.append(gap)
            factor = src.get("volume_factor_tolerance_match", {})
            amount_factor = src.get("amount_factor_tolerance_match", {})
            if not isinstance(factor, dict) or not isinstance(amount_factor, dict):
                raise ValueError("Missing quantity candidate comparisons")
            evidence["source_unit_factor_1_tolerance_candidate"] = (
                factor.get("1") is True and amount_factor.get("1") is True)
        else:
            if strict or price:
                raise ValueError("Non-comparable source claims a strict match")
        out["daily_vs_minute_evidence"][period] = evidence
        strict_all &= comparable and strict
        tolerant_all &= comparable and evidence[
            "existing_tolerance_all_six_raw_agree"]
        price_all &= comparable and price
    if published_strict and not (strict_all and price_all and valid_daily
                                 and complete and minute_five_strict):
        raise ValueError("Reported three-period strict success contradicts inputs")
    no_unexplained_quality = valid_daily and complete and minute_five_strict
    if ppm:
        out["max_abs_relative_quantity_gap_ppm"] = max(ppm)
    if published_strict and strict_all and no_unexplained_quality:
        status = "all_three_raw_strict_consistent_in_this_sample"
    elif (no_unexplained_quality and price_all and tolerant_all
          and len(ppm) == 4 and max(ppm) <= max_ppm
          and all(c["source_unit_factor_1_tolerance_candidate"]
                  for c in out["daily_vs_minute_evidence"].values())):
        status = "strict_OHLC_and_minute_aggregation_small_daily_quantity_gap_review"
    elif not complete or not valid_daily or not minute_five_strict:
        status = "cannot_certify_incomplete_or_quality_issue"
    else:
        status = "quantity_or_price_difference_requires_investigation"
    out["assessment"] = status
    out["not_market_truth_or_automatic_sync_approval"] = True
    return out


def summarize(report, max_ppm=DEFAULT_PPM_REVIEW_THRESHOLD):
    if (type(max_ppm) not in (int, float) or not math.isfinite(max_ppm)
            or not 0 < max_ppm <= 1000):
        raise ValueError("--review-ppm must be in (0, 1000]")
    if not isinstance(report, dict) or report.get("format") != EXPECTED_FORMAT:
        raise ValueError("Not a compatible Parquet three-period daily report")
    day = date.fromisoformat(report["date"])
    symbols = report.get("selected_symbols")
    values = report.get("stock_day_results")
    if (not isinstance(symbols, list) or not 1 <= len(symbols) <= 12
            or not isinstance(values, dict) or set(symbols) != set(values)
            or len(set(symbols)) != len(symbols)
            or any(type(s) is not str or not SYMBOL_PATTERN.fullmatch(s)
                   for s in symbols)):
        raise ValueError("Stock list and results must match valid symbols")
    for key, expected in (
        ("raw_market_ohlcva_exported", False),
        ("h5_source_accessed", False),
        ("source_market_files_modified", False),
        ("safe_to_automatically_union", False),
        ("source_daily_adjustment_or_quantity_units_certified", False),
    ):
        if report.get(key) is not expected:
            raise ValueError("Missing safety attestation: " + key)
    scans = report.get("read_cost_by_period")
    if not isinstance(scans, dict) or not set(EXPECTED_PERIODS) <= set(scans):
        raise ValueError("Daily, 1min and 5min source scans required")
    for period in EXPECTED_PERIODS:
        scan = scans[period]
        for field in ("duplicate_keys", "nonfinite_source_rows",
                      "invalid_timestamp_rows"):
            x = scan.get(field)
            if type(x) is not int or x < 0:
                raise ValueError("Invalid source anomaly count")
        if any(scan[field] for field in (
                "duplicate_keys", "nonfinite_source_rows",
                "invalid_timestamp_rows")):
            raise ValueError("Source anomalies require direct investigation")
    assessed = {s: assess_stock(s, values[s], max_ppm) for s in symbols}
    counts = Counter(a["assessment"] for a in assessed.values())
    return {
        "format": "Parquet report-only stock-day evidence grading v1",
        "source_report_date": day.isoformat(),
        "selected_symbols": list(symbols),
        "relative_quantity_gap_ppm_exploratory_review_limit": max_ppm,
        "source_report_consistency_checks": "passed",
        "summary_by_grade": dict(sorted(counts.items())),
        "stock_day_reviews": assessed,
        "derived_only_from_existing_json_not_from_market_files": True,
        "ppm_from_nine_decimal_rounded_ratios": True,
        "historical_tolerance_does_not_certify_unit_or_precision_cause": True,
        "raw_market_ohlcva_exported": False,
        "h5_or_parquet_source_files_accessed": False,
        "safe_to_automatically_union": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--review-ppm", type=float,
                        default=DEFAULT_PPM_REVIEW_THRESHOLD)
    args = parser.parse_args(argv)
    try:
        source = args.report.resolve()
        if source.suffix.lower() != ".json" or not source.is_file():
            raise ValueError("--report must be an existing JSON")
        output = args.out.resolve()
        if (output == source or output.suffix.lower() != ".json"
                or not output.is_relative_to((MODULE / "reports").resolve())
                or output.exists()):
            raise ValueError("--out must be a new JSON inside module reports/")
        report = json.loads(source.read_text(encoding="utf-8"))
        summary = summarize(report, args.review_ppm)
        summary["source_report_filename"] = source.name
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print("Saved safe offline interpretation:", output)
        print("Grades:", json.dumps(summary["summary_by_grade"], ensure_ascii=False))
    except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError) as e:
        parser.error(str(e))


if __name__ == "__main__":
    main()
