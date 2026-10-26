#!/usr/bin/env python3
"""Read-only, exact V3 SQLite comparison for matched source/pk-sorted pilots.

Both index copies must come from the same immutable V3 checkpoint and have
processed the same new row groups. No Parquet row batches, OHLCV or index writes.
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


indexer = load_module("v3_index_for_ab_comparison", "index-parquet-5min-coverage.py")
auditor = load_module("v3_readonly_audit_for_ab_comparison", "audit-parquet-5min-coverage.py")
core = indexer.core

# All three are V3 index logical tables, not raw licensed OHLCV.
QUERIES = (
    ("groups_done", "SELECT * FROM groups_done ORDER BY file_id,row_group"),
    ("daily_coverage", "SELECT * FROM daily_coverage ORDER BY symbol,trade_day"),
    ("row_group_locator",
     "SELECT * FROM row_group_locator ORDER BY symbol,trade_day,file_id"),
)
EQUAL_AUDIT_FIELDS = (
    "row_groups_complete", "row_groups_total", "candidate_source_rows",
    "unique_regular_session_keys", "duplicate_regular_session_keys",
    "stock_day_partitions", "row_group_locator_entries",
    "row_group_locator_compact_rows", "row_group_locator_payload_bytes",
    "row_groups_stats",
)


def compare_logical_tables(source_index: Path, sorted_index: Path) -> dict:
    """Stream exact primary-key ordered rows with bounded memory.

    Fail closed at the first mismatch, without printing any stock/date/slot key.
    Both connections operate in SQLite URI read-only mode.
    """
    if source_index.resolve() == sorted_index.resolve():
        raise ValueError("A/B SQLite indexes must be two distinct snapshots")
    counts = {}
    with (closing(sqlite3.connect(source_index.resolve().as_uri() + "?mode=ro",
                                  uri=True, timeout=60)) as source_db,
          closing(sqlite3.connect(sorted_index.resolve().as_uri() + "?mode=ro",
                                  uri=True, timeout=60)) as sorted_db):
        source_db.execute("BEGIN")
        sorted_db.execute("BEGIN")
        sentinel = object()
        for name, sql in QUERIES:
            count = 0
            for source_row, sorted_row in itertools.zip_longest(
                    source_db.execute(sql), sorted_db.execute(sql),
                    fillvalue=sentinel):
                if source_row != sorted_row:
                    raise ValueError(
                        f"A/B V3 index logical mismatch in {name}; "
                        "no key details are exposed")
                count += 1
            counts[name] = count
    return counts


def compare_matched_ab(source_index: Path, sorted_index: Path,
                       manifest: dict, group_counts: list[int],
                       source_report: dict, sorted_report: dict) -> dict:
    """Full independent audit + exact state comparison before showing speed."""
    if source_index.resolve() == sorted_index.resolve():
        raise ValueError("A/B indexes must be distinct")
    expected_fingerprint = indexer.manifest_signature(manifest)
    audits = (
        auditor.audit_existing_index(source_index, manifest, group_counts),
        auditor.audit_existing_index(sorted_index, manifest, group_counts),
    )
    for key in EQUAL_AUDIT_FIELDS:
        if audits[0][key] != audits[1][key]:
            raise ValueError(f"A/B audited aggregate mismatch: {key}")
    for label, report, expected_order, expected_index, audit in (
            ("source", source_report, "source", source_index, audits[0]),
            ("pk-sorted", sorted_report, "pk-sorted", sorted_index, audits[1])):
        if report.get("sqlite_write_order") != expected_order:
            raise ValueError(f"{label} benchmark report has wrong write order")
        if report.get("source_fingerprint") != expected_fingerprint:
            raise ValueError(f"{label} report source fingerprint mismatch")
        if report.get("saved_index") != expected_index.relative_to(core.MODULE_DIR).as_posix():
            raise ValueError(f"{label} report refers to another SQLite index")
        if (report.get("row_groups_complete") != audit["row_groups_complete"]
                or report.get("row_groups_total") != audit["row_groups_total"]
                or report.get("candidate_source_rows") != audit["candidate_source_rows"]
                or report.get("row_groups_stats") != audit["row_groups_stats"]):
            raise ValueError(f"{label} report disagrees with read-only full audit")
        if report.get("index_complete") != audit["index_complete"]:
            raise ValueError(f"{label} reported completion disagrees with audit")
        if report.get("clone_source_index") is None:
            raise ValueError(f"{label} is not documented as a clone A/B run")
        if report.get("stopped_for") != "max_new_groups":
            raise ValueError(f"{label} stopped for something other than matched group cap")
        if (report.get("soft_budget_reached") is not False
                or report.get("soft_wall_budget_reached") not in (False, None)):
            raise ValueError(f"{label} hit a soft budget; comparison invalid")
        new_groups = report.get("new_row_groups_this_run")
        if type(new_groups) is not int or new_groups <= 0:
            raise ValueError(f"{label} did not process any new row groups")
    if (source_report.get("clone_source_index") != sorted_report.get("clone_source_index")
            or source_report.get("sqlite_journal_mode") != sorted_report.get("sqlite_journal_mode")
            or source_report.get("new_row_groups_this_run") != sorted_report.get("new_row_groups_this_run")
            or source_report.get("row_groups_complete") != sorted_report.get("row_groups_complete")):
        raise ValueError("A/B different starting snapshots, journal modes or row-group extents")
    if source_report.get("sqlite_journal_mode") != "wal":
        raise ValueError("Matched write-order A/B must use the same WAL journal mode")

    def processed_group_ids(report):
        # The index profile exposes at most the slowest 5 groups. Require
        # all new group IDs to be present so equal totals cannot conceal
        # benchmarking DIFFERENT source RowGroups.
        n = report["new_row_groups_this_run"]
        profile = report.get("stage_profile_this_run")
        items = profile.get("slowest_row_group_wall_groups") if isinstance(profile, dict) else None
        if n > 5 or not isinstance(items, list) or len(items) != n:
            raise ValueError("A/B reports must expose every processed RowGroup (max 5)")
        result = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Invalid processed RowGroup evidence")
            file_id, row_group = item.get("file_id"), item.get("row_group")
            if type(file_id) is not int or type(row_group) is not int:
                raise ValueError("Invalid processed RowGroup identifier")
            result.append((file_id, row_group))
        if len(set(result)) != n:
            raise ValueError("Duplicate or missing processed RowGroup identifiers")
        return sorted(result)

    matched_processed_groups = processed_group_ids(source_report)
    if matched_processed_groups != processed_group_ids(sorted_report):
        raise ValueError("A/B runs processed different RowGroups; cannot compare speed")
    counts = compare_logical_tables(source_index, sorted_index)
    if counts["groups_done"] != audits[0]["row_groups_complete"]:
        raise ValueError("A/B checkpoint table size differs from full audit")
    if counts["daily_coverage"] != audits[0]["stock_day_partitions"]:
        raise ValueError("A/B daily rows differ from full audit")
    if counts["row_group_locator"] != audits[0]["row_group_locator_compact_rows"]:
        raise ValueError("A/B locator rows differ from full audit")

    def checked_seconds(report, path):
        value = report
        for part in path:
            if not isinstance(value, dict):
                raise ValueError("Missing A/B timing stage")
            value = value.get(part)
        if not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError("Invalid A/B timing stage")
        return float(value)

    durations = {}
    for label, report in (("source", source_report), ("pk_sorted", sorted_report)):
        durations[label] = {
            "total": checked_seconds(report, ("elapsed_seconds_this_run",)),
            "sqlite_group_commit": checked_seconds(
                report, ("stage_profile_this_run", "phases_seconds", "sqlite_group_commit")),
            "parquet_read_and_key_aggregation": checked_seconds(
                report, ("stage_profile_this_run", "phases_seconds",
                         "parquet_read_and_key_aggregation")),
        }
    return {
        "mode": "v3_matched_write_order_ab_readonly_comparison",
        "same_source_fingerprint": True,
        "same_clone_source": True,
        "same_journal_mode": True,
        "full_key_audit_both": True,
        "logical_tables_equal": True,
        "logical_rows_compared": counts,
        "year": manifest["year"],
        "universe": manifest["universe"],
        "row_groups_complete": audits[0]["row_groups_complete"],
        "new_groups_each_run": source_report["new_row_groups_this_run"],
        "matched_processed_rowgroups": [
            {"file_id": f, "row_group": rg} for f, rg in matched_processed_groups
        ],
        "candidate_source_rows": audits[0]["candidate_source_rows"],
        "unique_regular_session_keys": audits[0]["unique_regular_session_keys"],
        "duplicate_regular_session_keys": audits[0]["duplicate_regular_session_keys"],
        "source_fingerprint": expected_fingerprint,
        "times_seconds": durations,
        "total_speedup_pct_sorted_vs_source": (
            round(100 * (durations["source"]["total"] -
                         durations["pk_sorted"]["total"]) / durations["source"]["total"], 2)
            if durations["source"]["total"] > 0 else None),
        "commit_speedup_pct_sorted_vs_source": (
            round(100 * (durations["source"]["sqlite_group_commit"] -
                         durations["pk_sorted"]["sqlite_group_commit"])
                  / durations["source"]["sqlite_group_commit"], 2)
            if durations["source"]["sqlite_group_commit"] > 0 else None),
        "automatically_change_write_order": False,
        "incomplete_year_cannot_certify_union": not audits[0]["index_complete"],
        "source_files_modified": False,
        "indexes_modified": False,
        "notes": ("One matched sequential A/B remains vulnerable to file cache "
                  "and environment noise; never switch defaults from this alone.")
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--universe", choices=("all", "a-share-candidate"),
                   default="a-share-candidate")
    for field in ("source-index", "sorted-index", "source-report", "sorted-report"):
        p.add_argument("--" + field, type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--read-only", action="store_true", required=True)
    args = p.parse_args(argv)
    try:
        if not 2000 <= args.year <= 2100:
            raise ValueError("Year outside supported range")
        resolved = {}
        for key in ("source_index", "sorted_index", "source_report", "sorted_report", "out"):
            resolved[key], _ = core.resolve_module_artifact_paths(getattr(args, key), None)
        root, _, _ = core.resolve_safe_paths(args.root, resolved["out"], resolved["source_index"])
        if len(set(resolved.values())) != len(resolved):
            raise ValueError("A/B input and output paths must be distinct")
        protected_sidecars = {
            Path(str(resolved[key]) + suffix)
            for key in ("source_index", "sorted_index")
            for suffix in ("-wal", "-shm", "-journal")
        }
        if resolved["out"] in protected_sidecars:
            raise ValueError("Comparison report cannot use an SQLite journal path")
        if resolved["out"].exists():
            raise ValueError("Comparison report already exists: refuse overwrite")
        for key in ("source_report", "sorted_report"):
            if not resolved[key].is_file():
                raise ValueError("Missing source A/B report: " + key)
        paths = core.year_files(root, "5min", args.year)
        if not paths:
            raise ValueError("Parquet year files not found")
        manifest = indexer.file_manifest(root, paths, args.year, args.universe)
        import pyarrow.parquet as pq
        group_counts = [pq.ParquetFile(str(f)).metadata.num_row_groups for f in paths]
        inputs = [
            json.loads(resolved[key].read_text(encoding="utf-8"))
            for key in ("source_report", "sorted_report")]
        result = compare_matched_ab(resolved["source_index"], resolved["sorted_index"],
                                    manifest, group_counts, *inputs)
        resolved["out"].parent.mkdir(parents=True, exist_ok=True)
        with resolved["out"].open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print("Matched A/B logical equivalence report:", resolved["out"], flush=True)
    except (ValueError, OSError, sqlite3.Error, OverflowError,
            AssertionError, ImportError, json.JSONDecodeError) as exc:
        p.error(str(exc))


if __name__ == "__main__":
    main()
