#!/usr/bin/env python3
"""Recheck an existing V3 Parquet 5min index without extending or modifying it.

Reads original Parquet file metadata only (no ts/symbol or OHLCV row batches).
Scans the existing SQLite key and locator tables for a full *partial-year*
audit; never upgrades an incomplete index into an approved union source.
Outputs a new report only inside H5ParquetReconciler.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "parquet_5min_index_for_readonly_audit", HERE / "index-parquet-5min-coverage.py")
indexer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(indexer)
core = indexer.core


def audit_existing_index(index_path: Path, manifest: dict, group_counts: list[int]) -> dict:
    """Check source fingerprint, valid checkpoints and exact key/locator totals.

    No Parquet data rows are read. This function uses an SQLite read-only
    connection; it does not change meta.completed, journal settings or rows.
    group_counts must come from current Parquet footers for the same manifest.
    """
    if len(group_counts) != len(manifest["files"]) or not group_counts or any(
            not isinstance(count, int) or count < 1 for count in group_counts):
        raise ValueError("Parquet row-group footer counts missing or invalid")
    if not index_path.is_file():
        raise ValueError(f"V3 index does not exist: {index_path}")
    db = sqlite3.connect(index_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    try:
        indexer.connect_udfs(db)
        saved = dict(db.execute("SELECT key,value FROM meta"))
        if saved.get("version") != indexer.VERSION:
            raise ValueError("Existing SQLite index version is not V3")
        if saved.get("fingerprint") != indexer.manifest_signature(manifest):
            raise ValueError("Parquet source fingerprint mismatch: refuse unsafe audit")
        seen = 0
        for file_id, row_group in db.execute(
                "SELECT file_id,row_group FROM groups_done"):
            if not (0 <= file_id < len(group_counts)
                    and 0 <= row_group < group_counts[file_id]):
                raise ValueError("Out-of-range row-group checkpoint in SQLite index")
            seen += 1
        total = sum(group_counts)
        if saved.get("completed") == "true" and seen != total:
            raise ValueError("Completed flag conflicts with incomplete row-group checkpoints")
        if seen == 0:
            raise ValueError("Index has no committed row groups to audit")
        summary = indexer.index_summary(db, manifest, total, detail="full")
        if seen != summary["row_groups_complete"]:
            raise ValueError("Row-group checkpoint count changed during read-only audit")
        summary.update({
            "audit_mode": "existing_index_read_only_full",
            "source_fingerprint": indexer.manifest_signature(manifest),
            "row_groups_checked_against_parquet_footers": True,
            "no_parquet_data_rows_read_this_run": True,
            "new_row_groups_this_run": 0,
            "sqlite_index_modified": False,
            "source_files_modified": False,
            "saved_meta_completed": saved.get("completed") == "true",
            "usable_for_automatic_union_from_this_audit": False,
            "audit_does_not_certify_data_vendor_truth": True,
        })
        return summary
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--universe", choices=("all", "a-share-candidate"),
                        default="a-share-candidate")
    parser.add_argument("--index", type=Path, default=None,
                        help="Existing V3 SQLite, resolved inside module/work/indexes")
    parser.add_argument("--report", type=Path, default=None,
                        help="New JSON audit report, resolved inside module/reports")
    parser.add_argument("--read-only", action="store_true", required=True,
                        help="Original Parquet and existing SQLite are read-only")
    args = parser.parse_args(argv)
    try:
        if not 2000 <= args.year <= 2100:
            raise ValueError("Year outside supported range")
        suffix = f"{args.year}-{args.universe}-v3"
        index_path, _ = core.resolve_module_artifact_paths(
            args.index or Path("work") / "indexes" / f"pq-5min-{suffix}.sqlite", None)
        report_path, _ = core.resolve_module_artifact_paths(
            args.report or Path("reports") / f"pq-5min-{suffix}-readonly-audit.json", None)
        root, _, _ = core.resolve_safe_paths(args.root, report_path, index_path)
        protected = {index_path, *(Path(str(index_path) + end)
                                     for end in ("-wal", "-shm", "-journal"))}
        if report_path in protected:
            raise ValueError("Report cannot overwrite the SQLite index or journal files")
        if report_path.exists():
            raise ValueError(f"Report exists; choose a new --report path: {report_path}")
        paths = core.year_files(root, "5min", args.year)
        if not paths:
            raise ValueError("Parquet year files not found")
        manifest = indexer.file_manifest(root, paths, args.year, args.universe)
        import pyarrow.parquet as pq
        started = time.monotonic()
        # ParquetFile only loads schema and footer metadata here, not key batches.
        group_counts = [pq.ParquetFile(str(path)).metadata.num_row_groups
                        for path in paths]
        result = audit_existing_index(index_path, manifest, group_counts)
        result["elapsed_seconds_this_run"] = round(time.monotonic() - started, 3)
        result["saved_index"] = index_path.relative_to(core.MODULE_DIR).as_posix()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        # 'x' is exclusive: even a racing process cannot silently replace a report.
        with report_path.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print("Read-only full index audit saved:", report_path, flush=True)
    except (ValueError, OSError, sqlite3.Error, OverflowError,
            AssertionError, ImportError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
