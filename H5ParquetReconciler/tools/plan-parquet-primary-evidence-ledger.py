#!/usr/bin/env python3
"""Stage verified Parquet stock-day evidence from existing SAFE JSON reports.

Accepts raw Parquet three-period checks and/or their offline reviews.
No market file is read, no history is inferred between sampled dates,
no OHLCVA is exported, no source files are rewritten, and no import runs.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
SPEC = importlib.util.spec_from_file_location(
    "parquet_evidence_offline_review", HERE /
    "audit-parquet-day-minute-report-offline.py")
OFFLINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OFFLINE)

RAW = OFFLINE.EXPECTED_FORMAT
REVIEW = "Parquet report-only stock-day evidence grading v1"
ALLOWED_GRADES = {
    "all_three_raw_strict_consistent_in_this_sample",
    "strict_OHLC_and_minute_aggregation_small_daily_quantity_gap_review",
    "quantity_or_price_difference_requires_investigation",
    "cannot_certify_incomplete_or_quality_issue",
}
SAMPLE_CANDIDATES = {
    "all_three_raw_strict_consistent_in_this_sample",
    "strict_OHLC_and_minute_aggregation_small_daily_quantity_gap_review",
}


def checked_existing_review(report, max_ppm):
    """Do NOT re-grade weak reports into passing; keep original evidence limit."""
    if (report.get("source_report_consistency_checks") != "passed"
            or report.get("derived_only_from_existing_json_not_from_market_files")
            is not True
            or report.get("raw_market_ohlcva_exported") is not False
            or report.get("h5_or_parquet_source_files_accessed") is not False
            or report.get("safe_to_automatically_union") is not False
            or report.get("historical_tolerance_does_not_certify_unit_or_precision_cause")
            is not True):
        raise ValueError("Offline review safety flags missing or invalid")
    original_limit = report.get(
        "relative_quantity_gap_ppm_exploratory_review_limit")
    if type(original_limit) not in (int, float) or not math.isfinite(
            original_limit) or not 0 < original_limit <= 1000:
        raise ValueError("Offline review bound invalid")
    symbols = report.get("selected_symbols")
    items = report.get("stock_day_reviews")
    if (not isinstance(symbols, list) or not isinstance(items, dict)
            or not 1 <= len(symbols) <= 12
            or set(items) != set(symbols)
            or len(set(symbols)) != len(symbols)):
        raise ValueError("Offline selected symbols mismatch")
    mapped = {}
    for symbol in symbols:
        if not OFFLINE.SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError("Invalid stock symbol in offline review")
        row = items[symbol]
        grade = row.get("assessment")
        ppm = row.get("max_abs_relative_quantity_gap_ppm")
        if (grade not in ALLOWED_GRADES
                or type(ppm) not in (int, float, type(None))
                or (ppm is not None and (
                    not math.isfinite(ppm) or ppm < 0))):
            raise ValueError("Offline evidence grade or relative ratio invalid")
        reported_strict = row.get("raw_three_periods_strict_flag_from_original")
        if (row.get("not_market_truth_or_automatic_sync_approval") is not True
                or type(reported_strict) is not bool
                or (grade == "all_three_raw_strict_consistent_in_this_sample"
                    and not reported_strict)
                or (grade == "strict_OHLC_and_minute_aggregation_small_daily_quantity_gap_review"
                    and reported_strict)):
            raise ValueError("Offline row safety/strictness inconsistent")
        candidate = grade in SAMPLE_CANDIDATES
        # A smaller new review bound can ONLY demote, not upgrade.
        if candidate and grade.endswith("_review") and (
                ppm is None or ppm > max_ppm):
            grade = "quantity_or_price_difference_requires_investigation"
        mapped[symbol] = {"grade": grade, "max_gap_ppm": ppm}
    counts = Counter(r.get("assessment") for r in items.values())
    expected = report.get("summary_by_grade")
    if not isinstance(expected, dict) or dict(counts) != expected:
        raise ValueError("Offline summary contradicts stock-day assessments")
    if (grade := report.get("source_report_date")) is None:
        raise ValueError("Missing source date")
    return grade, mapped, "offline_review_existing_json", report.get(
        "source_report_filename")


def checked_raw_report(report, max_ppm):
    review = OFFLINE.summarize(report, max_ppm)
    mapped = {
        sym: {"grade": item["assessment"],
              "max_gap_ppm": item["max_abs_relative_quantity_gap_ppm"]}
        for sym, item in review["stock_day_reviews"].items()
    }
    return (review["source_report_date"], mapped,
            "raw_three_period_existing_json", None)


def plan_reports(reports, review_ppm=10):
    if not reports:
        raise ValueError("At least one already-generated report is required")
    if type(review_ppm) not in (float, int) or not 0 < review_ppm <= 1000:
        raise ValueError("--review-ppm outside (0,1000]")
    from datetime import date
    gathered = {}
    accepted = Counter()
    for filename, doc in reports:
        if not isinstance(doc, dict):
            raise ValueError("Expected JSON object: " + filename)
        kind = doc.get("format")
        if kind == RAW:
            day, entries, how, underlying = checked_raw_report(doc, review_ppm)
        elif kind == REVIEW:
            day, entries, how, underlying = checked_existing_review(doc, review_ppm)
        else:
            raise ValueError("Unsupported evidence report format: " + filename)
        date.fromisoformat(day)
        for symbol, e in entries.items():
            key = (day, symbol)
            if key in gathered:
                raise ValueError("Duplicate sampled stock-day across reports: "
                                 + day + "/" + symbol)
            grade = e["grade"]
            if grade not in ALLOWED_GRADES:
                raise ValueError("Unexpected grade")
            decision = ("candidate_parquet_primary_in_this_sample_only"
                        if grade in SAMPLE_CANDIDATES
                        else "not_a_qualified_sample_investigate")
            gathered[key] = {
                "date": day,
                "symbol": symbol,
                "candidate_source_id": "purchased_parquet",
                "sample_level_review": grade,
                "max_reported_relative_quantity_gap_ppm": e["max_gap_ppm"],
                "status": decision,
                "evidence_report_filename": filename,
                "evidence_type": how,
                "underlying_raw_report_filename_if_known": underlying,
                "verified_full_history_coverage": False,
                "eligible_for_unattended_import": False,
            }
            accepted[decision] += 1
    return {
        "format": "AStockDataTools sampled Parquet primary-source evidence ledger v1",
        "recommended_historical_primary_source": "purchased_parquet",
        "fallback_for_confirmed_gaps_only": "h5_original_read_only",
        "future_complete_postclose_update_candidate": "tdx_postclose",
        "selected_sampled_stock_days": [
            gathered[key] for key in sorted(gather)],
        "sampled_stock_day_count": len(gathered),
        "sampled_date_count": len({date for date, _ in gathered}),
        "summary_by_status": dict(sorted(accepted.items())),
        "sampling_is_not_a_full_market_or_full_history_audit": True,
        "does_not_prove_2011_to_2026_09_full_coverage": True,
        "requires_source_fingerprints_and_recorded_provenance_before_import": True,
        "historical_raw_market_files_read": False,
        "raw_market_ohlcva_exported": False,
        "data_import_performed": False,
        "source_market_files_modified": False,
        "eligible_for_automatic_source_merge": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reports", type=Path, nargs="+", required=True,
                    help="Previously created safe raw and/or offline review JSON")
    ap.add_argument("--review-ppm", type=float, default=10.0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        out = args.out.resolve()
        if out.suffix.lower() != ".json" or out.exists() or not (
                out.is_relative_to((MODULE / "reports").resolve())):
            raise ValueError("New JSON --out must stay in module reports/")
        input_reports = []
        for input_path in args.reports:
            src = input_path.resolve()
            if not src.is_file() or src.suffix.lower() != ".json" or src == out:
                raise ValueError("Existing safe JSON --reports are required")
            input_reports.append((src.name, json.loads(src.read_text(
                encoding="utf-8"))))
        plan = plan_reports(input_reports, args.review_ppm)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print("Saved evidence-only staged stock-day ledger:", out)
        print("Sampled stock-days:", plan["sampled_stock_day_count"])
        print("Statuses:", json.dumps(plan["summary_by_status"],
                                      ensure_ascii=False))
    except (ValueError, OSError, TypeError, KeyError,
            json.JSONDecodeError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
