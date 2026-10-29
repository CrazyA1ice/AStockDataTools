#!/usr/bin/env python3
"""Offline gate for Parquet-first daily coverage bootstrap (NO market row reads).

Consumes a completed, bounded, day-only H5/Parquet reconciliation JSON.
Classifies exact daily key coverage and checks OHLC mismatch counters;
does not select individual bars, convert units, stage data, or modify sources.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "parquet_primary_day_gate_core",
    HERE / "reconcile-local-a-share-h5-parquet.py",
)
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)

SOURCE_FORMAT = "AStockDataTools H5-Parquet local coverage/difference report v1"
OUTPUT_FORMAT = "AStockDataTools Parquet-primary daily bootstrap gate v1"
COUNTERS = ("h5_rows", "pq_rows", "matched_keys", "h5_only_rows",
            "pq_only_rows", "value_mismatch_rows")


def checked_nonnegative(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(label + " must be a nonnegative integer")
    return value


def checked_day_key(key, year, begin, end):
    if not isinstance(key, str) or len(key) != 8 or not key.isdigit():
        raise ValueError("Invalid YYYYMMDD day key")
    try:
        d = date.fromisoformat(key[:4] + "-" + key[4:6] + "-" + key[6:])
    except ValueError as exc:
        raise ValueError("Invalid calendar day in by_day") from exc
    if d.year != year or not begin <= d <= end:
        raise ValueError("by_day key outside the bounded audit window")
    return d


def analyze(report):
    """Conservation-checked stock-day COVERAGE plan; not a row-level fill permit."""
    if (not isinstance(report, dict)
            or report.get("format") != SOURCE_FORMAT
            or report.get("status") != "complete"
            or report.get("requested_periods") != ["day"]
            or report.get("universe_mode") != "a-share-candidate"
            or report.get("sources_modified") is not False
            or report.get("eligible_for_automatic_union") is not False):
        raise ValueError("Need complete day-only, a-share-candidate read-only source report")

    years = report.get("requested_years")
    if (not isinstance(years, list) or len(years) != 1
            or type(years[0]) is not int or not 2000 <= years[0] <= 2030):
        raise ValueError("Require one audited year")
    year = years[0]
    from_text = report.get("requested_from_date")
    to_text = report.get("requested_to_date")
    if (not isinstance(from_text, str) or not isinstance(to_text, str)):
        raise ValueError("Only bounded daily scans qualify")
    try:
        begin, end = date.fromisoformat(from_text), date.fromisoformat(to_text)
    except ValueError as exc:
        raise ValueError("Invalid requested date bound") from exc
    if (begin.isoformat() != from_text or end.isoformat() != to_text
            or begin.year != year or end.year != year or begin > end):
        raise ValueError("Bounds must be ordered ISO dates within the audited year")

    sections = report.get("results")
    key = f"day/{year}"
    if not isinstance(sections, dict) or set(sections) != {key}:
        raise ValueError("Expected exactly one requested day/year section")
    section = sections[key]
    if (not isinstance(section, dict) or section.get("period") != "day"
            or section.get("year") != year
            or section.get("from_date") != from_text
            or section.get("to_date") != to_text
            or section.get("universe_mode") != "a-share-candidate"
            or section.get("scan_complete") is not True
            or section.get("issues") != []
            or section.get("pq_year_metadata_only_no_h5_rows") is not False
            or section.get("h5_duplicate_keys") != 0
            or section.get("pq_duplicate_keys_within_batch") != 0
            or section.get("pq_duplicate_keys_across_batches") != 0):
        raise ValueError("Day section incomplete, inconsistent, or not exact key evidence")

    totals = {name: checked_nonnegative(section.get(name), name)
              for name in COUNTERS}
    price_mismatch = checked_nonnegative(
        section.get("price_mismatch_rows"), "price_mismatch_rows")
    quantity_mismatch = checked_nonnegative(
        section.get("quantity_mismatch_rows"), "quantity_mismatch_rows")
    if (totals["h5_rows"] != totals["matched_keys"] + totals["h5_only_rows"]
            or totals["pq_rows"] != totals["matched_keys"] + totals["pq_only_rows"]
            or price_mismatch > totals["value_mismatch_rows"]
            or quantity_mismatch > totals["value_mismatch_rows"]):
        raise ValueError("Day global key or mismatch conservation failed")

    by_day = section.get("by_day")
    if not isinstance(by_day, dict) or not by_day:
        raise ValueError("Missing exact day coverage partitions")
    accum = {name: 0 for name in COUNTERS}
    result_days = []
    for day, row in sorted(by_day.items()):
        checked_day_key(day, year, begin, end)
        if not isinstance(row, dict):
            raise ValueError("Invalid daily partition")
        values = {
            "h5_rows": checked_nonnegative(row.get("h5_unique", 0), "day.h5_unique"),
            "pq_rows": checked_nonnegative(row.get("parquet_unique", 0), "day.parquet_unique"),
            "matched_keys": checked_nonnegative(row.get("matched", 0), "day.matched"),
            "h5_only_rows": checked_nonnegative(row.get("h5_only", 0), "day.h5_only"),
            "pq_only_rows": checked_nonnegative(row.get("pq_only", 0), "day.pq_only"),
            "value_mismatch_rows": checked_nonnegative(
                row.get("value_mismatch", 0), "day.value_mismatch"),
        }
        if (values["h5_rows"] != values["matched_keys"] + values["h5_only_rows"]
                or values["pq_rows"] != values["matched_keys"] + values["pq_only_rows"]
                or values["value_mismatch_rows"] > values["matched_keys"]
                or row.get("intersection_unique") != values["matched_keys"]
                or row.get("union_candidate_unique") != (
                    values["h5_rows"] + values["pq_rows"] - values["matched_keys"])):
            raise ValueError("Daily unique key partition conservation failed")
        for field in COUNTERS:
            accum[field] += values[field]

        if values["h5_rows"] and not values["pq_rows"]:
            category = "entire_date_h5_only_candidate"
        elif values["pq_rows"] and not values["h5_rows"]:
            category = "entire_date_parquet_only"
        elif values["h5_only_rows"] and values["pq_rows"]:
            category = "mixed_date_requires_exact_symbol_day_manifest"
        elif values["matched_keys"] and values["pq_only_rows"]:
            category = "parquet_primary_existing_overlap_plus_pq_only"
        elif values["matched_keys"]:
            category = "parquet_primary_existing_overlap"
        else:
            raise ValueError("Empty date partition must not be reported as a trading day")
        result_days.append({"date": day, "category": category, **values})
    if accum != totals:
        raise ValueError("Sum of per-date counters differs from exact audited totals")

    overlap_proven = totals["matched_keys"] > 0
    price_gate_pass = overlap_proven and price_mismatch == 0
    h5_only_candidate = sum(
        row["h5_only_rows"] for row in result_days
        if row["category"] == "entire_date_h5_only_candidate")
    mixed_candidate = sum(
        row["h5_only_rows"] for row in result_days
        if row["category"] == "mixed_date_requires_exact_symbol_day_manifest")
    if h5_only_candidate + mixed_candidate != totals["h5_only_rows"]:
        raise ValueError("Unclassified H5-only stock-day key count")
    return {
        "format": OUTPUT_FORMAT,
        "audited_window": {"from_date": from_text, "to_date": to_text},
        "source_report_type": SOURCE_FORMAT,
        "period": "day",
        "universe_mode": "a-share-candidate",
        "source_scan_complete": True,
        "source_key_conservation_verified": True,
        "source_price_comparison_is_existing_tolerance_not_strict_equality": True,
        "existing_tolerance_ohlc_overlap_pass": price_gate_pass,
        "overlap_price_mismatch_rows": price_mismatch,
        "overlap_ohlc_keys_tested": totals["matched_keys"],
        "quantity_or_amount_difference_rows": quantity_mismatch,
        "source_totals": totals,
        "h5_only_rows_on_wholly_parquet_absent_dates": h5_only_candidate,
        "h5_only_rows_on_mixed_dates_need_symbol_day_manifest": mixed_candidate,
        "daily_coverage": result_days,
        "source_preference": "Parquet wins all existing keys; H5 only for separately verified absent complete symbol-days",
        "next_step": ("verify source unit/schema and full symbol-day completeness before "
                      "staging new Parquet files, never rewrite purchased originals"),
        "contains_no_raw_ohlcva": True,
        "market_source_files_read": False,
        "market_source_files_modified": False,
        "daily_price_gate_does_not_certify_all_history": True,
        "ready_for_unattended_data_fill": False,
        "safe_to_automatically_union": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        out, _ = core.resolve_module_artifact_paths(args.out)
        reports = (HERE.parent / "reports").resolve()
        source = args.report.resolve()
        if (source == out or not source.is_file()
                or source.suffix.lower() != ".json"
                or not source.is_relative_to(reports)
                or out.suffix.lower() != ".json"
                or not out.is_relative_to(reports)
                or out.exists()):
            raise ValueError("Input and unused output must be distinct JSON files inside module reports/")
        raw = source.read_bytes()
        result = analyze(json.loads(raw))
        result["source_report_basename"] = source.name
        result["source_report_sha256"] = hashlib.sha256(raw).hexdigest()
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print("Saved read-only Parquet-first daily coverage gate:", out)
        print("Daily price gate:", result["existing_tolerance_ohlc_overlap_pass"],
              "H5-only complete-date candidates:",
              result["h5_only_rows_on_wholly_parquet_absent_dates"],
              "mixed-date H5-only keys:",
              result["h5_only_rows_on_mixed_dates_need_symbol_day_manifest"])
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
