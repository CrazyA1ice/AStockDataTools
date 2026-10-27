#!/usr/bin/env python3
"""Read-only comparison of opposite-order Parquet cold-query A/B SAFE summaries.

Input is *only* the two aggregate JSON outputs from
benchmark-parquet-arrow-filter-cold.py. Never reads H5, paid Parquet, the
private OHLCVA cache, or the SQLite indexing database. Order reversal controls
one obvious timing bias but does NOT prove a cold OS cache or data-source hash.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]
REPORTS = (MODULE / "reports").resolve()
FORMAT = "AStockDataTools Parquet cold-read A/B comparison v1"
ORDERS = ("rowgroup-first", "arrow-first")
TRUE_FLAGS = (
    "query_output_all_values_times_and_source_provenance_identical",
    "execution_order_and_os_cache_could_bias_timings",
    "arrow_output_rows_are_not_number_of_physical_rows_read",
    "fast_cold_engine_not_automatically_enabled",
    "local_private_ohlcva_cache_not_used",
    "source_manifest_stat_only_not_content_sha256",
    "source_stat_manifest_stable_across_both_engines",
    "only_safe_aggregate_metadata_exported",
)
FALSE_FLAGS = (
    "raw_ohlcva_exported",
    "h5_source_accessed",
    "source_market_files_modified",
    "automatic_source_union_or_import_performed",
)
AGGREGATE_KEYS = (
    "symbol", "period", "from_date", "to_date", "matching_bar_count",
    "candidate_row_groups", "candidate_source_rows_upper_bound",
)
BASELINE_KEYS = (
    "source_rows_delivered_to_python_before_filter",
    "source_file_footers_opened",
)
ARROW_KEYS = (
    "arrow_rows_emitted_after_predicate",
    "row_groups_that_emitted_filtered_rows",
    "row_group_upper_bound_still",
)


def guarded_path(value: str | Path, *, is_output: bool = False) -> Path:
    """Resolve relative paths ONLY within this module's reports directory."""
    supplied = Path(value)
    path = supplied if supplied.is_absolute() else MODULE / supplied
    if path.is_symlink() or not path.resolve().is_relative_to(REPORTS):
        raise ValueError("Only non-symlink paths inside H5ParquetReconciler/reports/ are allowed")
    if path.suffix.lower() != ".json":
        raise ValueError("The report path must end in .json")
    if is_output:
        if path.exists():
            raise ValueError("Output report already exists; never overwrite")
    elif not path.is_file():
        raise ValueError("Input summary JSON does not exist")
    return path.resolve()


def read_summary(path: Path) -> dict:
    if path.stat().st_size > 131072:
        raise ValueError("Input summary exceeds 128 KiB safe limit")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("A/B report must be a JSON object")
    return validate_summary(data)


def finite_seconds(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(label + " must be a positive finite duration")
    val = float(value)
    if not math.isfinite(val) or val <= 0:
        raise ValueError(label + " must be a positive finite duration")
    return val


def nonnegative_int(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(label + " must be a nonnegative integer")
    return value


def validate_summary(data: dict) -> dict:
    if data.get("format") != FORMAT:
        raise ValueError("Unexpected A/B report format")
    if data.get("requested_execution_order") not in ORDERS:
        raise ValueError("Unknown execution order")
    for flag in TRUE_FLAGS:
        if data.get(flag) is not True:
            raise ValueError("Missing successful safe benchmark assertion: " + flag)
    for flag in FALSE_FLAGS:
        if data.get(flag) is not False:
            raise ValueError("Unsafe or incomplete benchmark assertion: " + flag)
    if (not isinstance(data.get("symbol"), str)
            or not data["symbol"].startswith(("SH", "SZ", "BJ"))
            or len(data["symbol"]) != 8
            or not data["symbol"][2:].isdigit()
            or data.get("period") not in ("day", "1min", "5min")):
        raise ValueError("Invalid query identity")
    try:
        first = date.fromisoformat(data["from_date"])
        last = date.fromisoformat(data["to_date"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("Invalid query dates") from exc
    if not first <= last or (last - first).days >= 31:
        raise ValueError("Invalid query window")
    for key in AGGREGATE_KEYS[4:]:
        nonnegative_int(data.get(key), key)
    nonnegative_int(data.get("source_stat_manifest_file_count"),
                    "source_stat_manifest_file_count")
    digest = data.get("source_stat_manifest_sha256")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)):
        raise ValueError("Missing or malformed stat-only source manifest SHA256")
    if not isinstance(data.get("baseline_existing_rowgroup"), dict):
        raise ValueError("Baseline measurement missing")
    if not isinstance(data.get("experimental_arrow_filtered"), dict):
        raise ValueError("Arrow measurement missing")
    baseline = data["baseline_existing_rowgroup"]
    arrow = data["experimental_arrow_filtered"]
    finite_seconds(baseline.get("elapsed_seconds"), "baseline elapsed_seconds")
    finite_seconds(arrow.get("elapsed_seconds"), "arrow elapsed_seconds")
    for key in BASELINE_KEYS:
        nonnegative_int(baseline.get(key), key)
    for key in ARROW_KEYS:
        nonnegative_int(arrow.get(key), key)
    if arrow.get("actual_parquet_rows_decoded_unknown") is not True:
        raise ValueError("Physical Parquet decode cost must remain unknown")
    if arrow.get("actual_disk_bytes_read_unknown") is not True:
        raise ValueError("Actual disk bytes must remain unknown")
    if (arrow["row_group_upper_bound_still"]
            != data["candidate_source_rows_upper_bound"]):
        raise ValueError("Candidate RowGroup bound differs between engines")
    if (baseline["source_rows_delivered_to_python_before_filter"]
            > data["candidate_source_rows_upper_bound"]):
        raise ValueError("Baseline scanned more source rows than preflight bound")
    if (arrow["arrow_rows_emitted_after_predicate"]
            > data["candidate_source_rows_upper_bound"]):
        raise ValueError("Arrow emitted more rows than preflight bound")
    if (data["matching_bar_count"]
            > min(baseline["source_rows_delivered_to_python_before_filter"],
                  arrow["arrow_rows_emitted_after_predicate"])):
        raise ValueError("Reported matching bars exceed engine row counts")
    if (arrow["row_groups_that_emitted_filtered_rows"]
            > data["candidate_row_groups"]):
        raise ValueError("Arrow emitting groups exceed candidate groups")
    return data


def compare(rowgroup_first: dict, arrow_first: dict) -> dict:
    left, right = (validate_summary(rowgroup_first),
                   validate_summary(arrow_first))
    if (left["requested_execution_order"] != "rowgroup-first"
            or right["requested_execution_order"] != "arrow-first"):
        raise ValueError("Provide exactly one report for each requested order")
    for key in AGGREGATE_KEYS:
        if left[key] != right[key]:
            raise ValueError("Mismatched query or RowGroup preflight: " + key)
    for key in ("source_stat_manifest_sha256",
                "source_stat_manifest_file_count"):
        if left[key] != right[key]:
            raise ValueError("Source stat manifest differs between A/B runs: " + key)
    for key in BASELINE_KEYS:
        if (left["baseline_existing_rowgroup"][key] !=
                right["baseline_existing_rowgroup"][key]):
            raise ValueError("Different baseline source census: " + key)
    for key in ARROW_KEYS:
        if (left["experimental_arrow_filtered"][key] !=
                right["experimental_arrow_filtered"][key]):
            raise ValueError("Different Arrow output census: " + key)
    trials = {}
    ratios = []
    for order, entry in zip(ORDERS, (left, right)):
        old = finite_seconds(entry["baseline_existing_rowgroup"]["elapsed_seconds"],
                             "baseline elapsed")
        new = finite_seconds(entry["experimental_arrow_filtered"]["elapsed_seconds"],
                             "arrow elapsed")
        ratio = old / new
        if not math.isfinite(ratio):
            raise ValueError("Timing ratio overflow")
        ratios.append(ratio)
        trials[order] = {
            "baseline_seconds": old,
            "arrow_seconds": new,
            "baseline_over_arrow_ratio": round(ratio, 6),
        }
    if all(v > 1.0 for v in ratios):
        result = "arrow_faster_in_both_orders"
    elif all(v < 1.0 for v in ratios):
        result = "baseline_faster_in_both_orders"
    else:
        result = "mixed_or_equal_order_sensitive"
    return {
        "format": "AStockDataTools Parquet cold-read reversed-order audit v1",
        "symbol": left["symbol"], "period": left["period"],
        "from_date": left["from_date"], "to_date": left["to_date"],
        "matching_bar_count": left["matching_bar_count"],
        "candidate_row_groups": left["candidate_row_groups"],
        "candidate_source_rows_upper_bound": left["candidate_source_rows_upper_bound"],
        "opposite_orders_and_identical_aggregate_counts_verified": True,
        "same_source_stat_manifest_in_both_runs_verified": True,
        "source_manifest_is_stat_only_not_content_hash": True,
        "each_order_ohlcva_time_provenance_identical_within_run": True,
        "measured_trials": trials,
        "preliminary_timing_observation": result,
        "weakest_observed_baseline_over_arrow_ratio": round(min(ratios), 6),
        "source_content_identity_between_runs_not_proven": True,
        "full_os_disk_cache_coldness_not_proven": True,
        "arrow_physical_decode_rows_and_disk_bytes_unknown": True,
        "two_single_runs_insufficient_to_enable_arrow_in_production": True,
        "cache_or_paid_market_data_exported": False,
        "source_market_files_modified": False,
        "automatic_source_union_or_import_performed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rowgroup-first", type=Path, required=True)
    parser.add_argument("--arrow-first", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--read-only", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        first = guarded_path(args.rowgroup_first)
        second = guarded_path(args.arrow_first)
        output = guarded_path(args.out, is_output=True)
        if len({first, second, output}) != 3:
            raise ValueError("Input and output JSON paths must all differ")
        report = compare(read_summary(first), read_summary(second))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as fd:
            json.dump(report, fd, ensure_ascii=False, indent=2, allow_nan=False)
            fd.write("\n")
        print("Saved aggregate reversed-order audit:", output)
        print("Observation:", report["preliminary_timing_observation"])
        print("Not sufficient for production engine switch.")
    except (ValueError, TypeError, OSError, OverflowError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
