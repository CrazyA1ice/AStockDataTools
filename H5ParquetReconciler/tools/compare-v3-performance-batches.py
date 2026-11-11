#!/usr/bin/env python3
"""Read-only comparison of consecutive V3 coverage-index progress JSON reports.

This is an observational trend report, NOT a causal benchmark. No paid Parquet
data, source symbols, timestamps, SQLite indexes or OHLCV rows are read.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[1]
EXPECTED_FORMAT = "parquet-5min-coverage-index-v3"
STAGES = (
    "parquet_read_and_key_aggregation",
    "sqlite_group_commit",
)
SQL_SUBSTAGES = (
    "prepare_seconds",
    "daily_coverage_upsert_seconds",
    "row_group_locator_upsert_seconds",
    "groups_done_insert_seconds",
    "commit_and_other_seconds",
    "outside_insert_group_seconds",
)


def report_path(value: str | Path, *, new: bool = False) -> Path:
    """Require all three JSONs inside this module's reports/ directory."""
    root = MODULE_DIR.resolve()
    reports = (root / "reports").resolve()
    path = Path(value)
    resolved = (root / path if not path.is_absolute() else path).resolve()
    if not resolved.is_relative_to(reports) or resolved.suffix.lower() != ".json":
        raise ValueError("All V3 report JSON paths must be inside module reports/")
    if new:
        if resolved.exists():
            raise ValueError("Comparison report exists; refuse to overwrite")
    elif not resolved.is_file():
        raise ValueError("Input report does not exist inside reports/")
    return resolved


def numeric(obj, key, *, integer=False) -> float | int:
    value = obj.get(key) if isinstance(obj, dict) else None
    if integer:
        if type(value) is not int or value < 0:
            raise ValueError("Invalid integer aggregate: " + key)
    elif (type(value) not in (float, int) or not math.isfinite(value)
          or value < 0):
        raise ValueError("Invalid nonnegative timing/size: " + key)
    return value


def group_set(report):
    profile = report.get("stage_profile_this_run")
    if not isinstance(profile, dict):
        raise ValueError("Missing stage profile")
    n = numeric(report, "new_row_groups_this_run", integer=True)
    if not 1 <= n <= 5:
        raise ValueError("Only consecutive 1-5 RowGroup runs have complete group IDs")
    if numeric(profile, "profiled_new_groups", integer=True) != n:
        raise ValueError("Profiled row-group count mismatch")
    groups = profile.get("slowest_row_group_wall_groups")
    if not isinstance(groups, list) or len(groups) != n:
        raise ValueError("RowGroup identity evidence incomplete")
    ids = []
    for row in groups:
        if not isinstance(row, dict):
            raise ValueError("Malformed RowGroup profile")
        a = numeric(row, "file_id", integer=True)
        b = numeric(row, "row_group", integer=True)
        ids.append((a, b))
    if len(set(ids)) != len(ids):
        raise ValueError("Repeated RowGroup IDs inside one report")
    return sorted(ids)


def checked_profile(report):
    profile = report["stage_profile_this_run"]
    phases = profile.get("phases_seconds")
    breakdown = profile.get("sqlite_write_breakdown_seconds")
    if not isinstance(phases, dict) or not isinstance(breakdown, dict):
        raise ValueError("Missing detailed timing breakdown")
    if numeric(profile, "sqlite_write_breakdown_profiled_groups", integer=True) != (
        numeric(report, "new_row_groups_this_run", integer=True)
    ):
        raise ValueError("Not all newly processed groups were SQL-profiled")
    stage = {k: float(numeric(phases, k)) for k in STAGES}
    inner = {k: float(numeric(breakdown, k)) for k in SQL_SUBSTAGES}
    if abs(sum(inner.values()) - stage["sqlite_group_commit"]) > 0.055:
        raise ValueError("SQL stage sum does not conserve total SQLite write time")
    context = profile.get("sqlite_transaction_boundary_seconds")
    if context is None:
        boundary = None
    else:
        keys = ("context_enter_seconds", "context_exit_seconds",
                "other_within_commit_and_other_seconds")
        if not isinstance(context, dict):
            raise ValueError("Invalid transaction boundary metrics")
        boundary = {k: float(numeric(context, k)) for k in keys}
        if abs(sum(boundary.values()) - inner["commit_and_other_seconds"]) > 0.055:
            raise ValueError("Transaction context timing not nested within commit-and-other")
    return stage, inner, boundary


def compare_reports(previous: dict, current: dict) -> dict:
    for label, report in (("previous", previous), ("current", current)):
        if report.get("format") != EXPECTED_FORMAT:
            raise ValueError("Unexpected " + label + " V3 format")
        if report.get("report_detail_effective") != "progress":
            raise ValueError("Comparison requires original progress reports")
        if report.get("index_complete") is not False:
            raise ValueError("Incomplete-year performance report expected")
        if (report.get("sqlite_journal_mode") != "wal"
            or report.get("sqlite_write_order") != "source"
            or report.get("clone_source_index") is not None):
            raise ValueError("Both reports must come from original main WAL/source index")
        if report.get("source_files_modified") is not False:
            raise ValueError("Source modification status not confirmed false")
        if report.get("stopped_for") != "max_new_groups":
            raise ValueError("Unexpected termination; do not compare runtimes")
        if (report.get("soft_budget_reached") is not False
            or report.get("soft_wall_budget_reached") is not False):
            raise ValueError("Soft budget triggered; do not compare runtimes")
        for field in ("row_groups_complete", "row_groups_total", "year",
                      "candidate_source_rows", "source_rows_this_run",
                      "sqlite_main_and_wal_on_disk_bytes"):
            numeric(report, field, integer=True)
        for field in ("elapsed_seconds_this_run", "process_cpu_seconds_this_run"):
            numeric(report, field)
    stable_fields = ("format", "year", "universe", "files", "row_groups_total",
                     "source_fingerprint", "saved_index", "sqlite_journal_mode",
                     "sqlite_write_order", "max_index_mib_soft_budget",
                     "max_run_seconds_soft_budget")
    for field in stable_fields:
        if not previous.get(field) or previous.get(field) != current.get(field):
            raise ValueError("Mismatched previous/current identity or safety budget: " + field)
    old_groups = group_set(previous)
    new_groups = group_set(current)
    if previous["row_groups_complete"] + len(new_groups) != current["row_groups_complete"]:
        raise ValueError("Main index cumulative group count is not consecutive")
    if set(old_groups).intersection(new_groups):
        raise ValueError("Input reports reuse a RowGroup")
    if old_groups[-1][0] != new_groups[0][0] or (
        old_groups[-1][1] + 1 != new_groups[0][1]):
        raise ValueError("RowGroup ranges are not adjacent")
    if any(a[0] != new_groups[0][0] or a[1] != new_groups[0][1] + i
           for i, a in enumerate(new_groups)):
        raise ValueError("Current RowGroups are not consecutive")
    if previous["candidate_source_rows"] > current["candidate_source_rows"]:
        raise ValueError("Candidate source rows went backwards")
    if previous["row_groups_stats"]["source_rows"] + current["source_rows_this_run"] != (
        current["row_groups_stats"]["source_rows"]
    ):
        raise ValueError("Source row-count conservation failed")
    old_stage, old_inner, old_boundary = checked_profile(previous)
    new_stage, new_inner, new_boundary = checked_profile(current)
    def delta(a, b):
        return round(float(b) - float(a), 3)
    out = {
        "mode": "v3_consecutive_main_progress_trend_readonly",
        "source_fingerprint": current["source_fingerprint"],
        "year": current["year"],
        "universe": current["universe"],
        "main_index_groups_before": previous["row_groups_complete"],
        "main_index_groups_after": current["row_groups_complete"],
        "rowgroup_range_previous": {
            "first": {"file_id": old_groups[0][0], "row_group": old_groups[0][1]},
            "last": {"file_id": old_groups[-1][0], "row_group": old_groups[-1][1]},
        },
        "rowgroup_range_current": {
            "first": {"file_id": new_groups[0][0], "row_group": new_groups[0][1]},
            "last": {"file_id": new_groups[-1][0], "row_group": new_groups[-1][1]},
        },
        "source_files_modified": False,
        "sqlite_index_modified": False,
        "both_runs_equal_groups": len(old_groups) == len(new_groups),
        "new_rows_current_run": current["source_rows_this_run"],
        "new_candidate_rows_between_reports": (
            current["candidate_source_rows"]-previous["candidate_source_rows"]),
        "time_seconds": {
            "previous_total": previous["elapsed_seconds_this_run"],
            "current_total": current["elapsed_seconds_this_run"],
            "delta_total": delta(previous["elapsed_seconds_this_run"],
                                 current["elapsed_seconds_this_run"]),
            "stages_previous": old_stage,
            "stages_current": new_stage,
            "stages_delta": {key: delta(old_stage[key],new_stage[key]) for key in STAGES},
            "sql_breakdown_previous": old_inner,
            "sql_breakdown_current": new_inner,
            "sql_breakdown_delta": {
                key: delta(old_inner[key],new_inner[key]) for key in SQL_SUBSTAGES
            },
            "sqlite_transaction_previous": old_boundary,
            "sqlite_transaction_current": new_boundary,
        },
        "main_and_wal_disk_bytes_previous": previous["sqlite_main_and_wal_on_disk_bytes"],
        "main_and_wal_disk_bytes_current": current["sqlite_main_and_wal_on_disk_bytes"],
        "main_and_wal_growth_bytes": (
            current["sqlite_main_and_wal_on_disk_bytes"] -
            previous["sqlite_main_and_wal_on_disk_bytes"]),
        "no_full_audit_this_run": True,
        "safe_to_automatically_union": False,
        "causal_sqlite_storage_or_fsync_conclusion_supported": False,
        "notes": ("Different RowGroups and Windows scheduling/disk caches can affect "
                  "timings. SQLite transaction __exit__ includes COMMIT call but "
                  "does not isolate kernel flush duration. Never sum nested phases.")
    }
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--read-only", required=True, action="store_true")
    args = parser.parse_args(argv)
    try:
        previous = report_path(args.previous)
        current = report_path(args.current)
        output = report_path(args.report, new=True)
        if len({previous, current, output}) != 3:
            raise ValueError("Previous/current/output reports must be distinct")
        before = json.loads(previous.read_text(encoding="utf-8"))
        after = json.loads(current.read_text(encoding="utf-8"))
        result = compare_reports(before, after)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print("Saved read-only V3 main-index performance trend:", output, flush=True)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
