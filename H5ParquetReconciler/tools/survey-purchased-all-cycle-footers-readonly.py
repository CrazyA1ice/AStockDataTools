#!/usr/bin/env python3
"""Source-only Parquet footer inventory for all PURCHASED cycle directories.

2025/2026 discovery of existing period folders and year-named Parquet source
files. Reads Parquet file FOOTERS, NEVER OHLCVA or (ts,symbol) row batches.
This is a coverage ENVELOPE, not proof of individual trading day/bar presence.
Original market data, existing private indexes, and production pointers remain
untouched. The CLI prints only aggregate metadata; no report file is written.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")


def _load():
    spec = importlib.util.spec_from_file_location(
        "purchased_all_cycle_existing_footer_inventory",
        HERE / "inventory-parquet-primary-footers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


F = _load()


def discover_periods(root):
    """Only actual ordinary source period directories, no invented labels."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Original market root missing or unsafe")
    base = root / "AllCycleAStockData"
    if base.is_symlink() or not base.is_dir():
        raise ValueError("Missing or unsafe purchased Parquet period root")
    result = []
    for path in base.iterdir():
        if path.is_symlink():
            raise ValueError("Symlink in purchased cycle root; audit manually")
        if not path.is_dir():
            continue
        if not NAME.fullmatch(path.name):
            raise ValueError("Unexpected source cycle directory label")
        result.append(path.name)
    if not result or len(result) > 24:
        raise ValueError("Require 1..24 ordinary purchased period folders")
    return tuple(sorted(result))


def inventory(root, years=(2025, 2026), *,
              max_total_files=5000, max_row_groups_per_year_period=100000):
    root = Path(root)
    if (not isinstance(years, (list, tuple))
            or not years or len(set(years)) != len(years)
            or any(type(y) is not int or not 2011 <= y <= 2026 for y in years)
            or type(max_total_files) is not int
            or not 1 <= max_total_files <= 100000
            or type(max_row_groups_per_year_period) is not int
            or not 1 <= max_row_groups_per_year_period <= 1000000):
        raise ValueError("Invalid years or read-only Parquet footer budgets")
    periods = discover_periods(root)
    first, last = min(years), max(years)
    discovered, naming = F.source_files(root, periods, first, last)
    total_files = sum(len(discovered[p][y]) for p in periods for y in years)
    if total_files > max_total_files:
        raise ValueError("Source footer file count exceeds configured budget")
    results = {}
    for period in periods:
        annual = {}
        for year in years:
            files = discovered[period][year]
            # F.year_period_footer() does NOT read K-line columns or values.
            summary = F.year_period_footer(
                root.resolve(), files, year, period,
                max_row_groups_per_year_period)
            annual[str(year)] = {
                "source_files": summary["files"],
                "source_rows_from_parquet_footers": summary[
                    "source_rows_from_parquet_footers"],
                "row_groups": summary["row_groups"],
                "nonempty_row_groups_without_usable_ts_bounds": summary[
                    "nonempty_row_groups_without_usable_ts_bounds"],
                "row_groups_with_bounds_outside_filename_year": summary[
                    "row_groups_with_any_ts_bounds_outside_named_year"],
                "earliest_known_raw_beijing_timestamp": summary[
                    "earliest_known_raw_beijing_timestamp"],
                "latest_known_raw_beijing_timestamp": summary[
                    "latest_known_raw_beijing_timestamp"],
                "source_file_stat_identity_sha256_not_content_digest": summary[
                    "source_file_stat_identity_sha256_not_content_digest"],
                "footer_envelope_complete_for_nonempty_row_groups": summary[
                    "footer_envelope_complete_for_nonempty_row_groups"],
                "per_security_date_keys_validated": False,
                "full_calendar_coverage_certified": False,
            }
        results[period] = annual
    return {
        "format": "AStockDataTools purchased all-cycle source footer survey v1",
        "status": "read_only_purchased_parquet_footer_envelopes_not_exact_coverage",
        "source_root_period_directories": list(periods),
        "requested_years": list(years),
        "total_year_assigned_parquet_files": total_files,
        "period_years": results,
        "file_naming_caveats": naming,
        "only_original_parquet_file_footers_read": True,
        "original_h5_opened": False,
        "original_market_files_modified": False,
        "new_market_or_index_files_written": False,
        "production_pointer_modified": False,
        "no_ohlcva_rows_read_or_exported": True,
        "actual_stockday_and_full_exchange_calendar_coverage_certified": False,
        "missing_filename_year_means_absent_named_source_not_proof_of_no_data": True,
        "timestamp_and_vendor_physical_unit_semantics_certified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--years", type=int, nargs="+", default=[2025, 2026])
    parser.add_argument("--max-total-files", type=int, default=5000)
    parser.add_argument("--max-row-groups-per-year-period", type=int, default=100000)
    args = parser.parse_args(argv)
    result = inventory(
        args.root, tuple(args.years),
        max_total_files=args.max_total_files,
        max_row_groups_per_year_period=args.max_row_groups_per_year_period)
    # Aggregate metadata only: never export source paths, securities or OHLCVA.
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
