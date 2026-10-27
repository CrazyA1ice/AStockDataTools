#!/usr/bin/env python3
"""Read-only Parquet footer inventory for planning a historical primary source.

Reads path metadata + Parquet footers ONLY (no ts/symbol batches, no OHLCVA).
Yearly/monthly path labels are not proof of actual trade-date or ticker coverage.
No primary database or union is created.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
CORE_SPEC = importlib.util.spec_from_file_location(
    "parquet_footer_inventory_core",
    HERE / "reconcile-local-a-share-h5-parquet.py")
core = importlib.util.module_from_spec(CORE_SPEC)
CORE_SPEC.loader.exec_module(core)
PERIODS = ("day", "1min", "5min")


def beijing_stamp(epoch_ms):
    """Raw Parquet local wall-time; DO NOT shift 5min stamps by 5m here."""
    dt = datetime.fromtimestamp(int(epoch_ms) / 1000, tz=core.UTC8)
    if not 1990 <= dt.year <= 2100:
        raise ValueError("timestamp outside supported inventory calendar")
    return dt.strftime("%Y-%m-%d %H:%M"), dt.date().isoformat()


def footer_bounds(group):
    """None denotes an untrustworthy/missing Parquet ts-statistic."""
    for index in range(group.num_columns):
        col = group.column(index)
        if col.path_in_schema != "ts":
            continue
        st = col.statistics
        if st is None or not st.has_min_max:
            return None
        try:
            low, high = int(st.min), int(st.max)
            if low > high:
                return None
            first, first_day = beijing_stamp(low)
            last, last_day = beijing_stamp(high)
            if first > last:
                return None
            return first, last, first_day, last_day
        except (ValueError, TypeError, OSError, OverflowError):
            return None
    return None


def source_files(root, periods, start_year, end_year):
    """Discover each period ONCE; quarantine filenames without one year."""
    base = root / "AllCycleAStockData"
    discovered = {p: {year: [] for year in range(
        start_year, end_year + 1)} for p in periods}
    unassigned, skipped_symlink, outside_requested = Counter(), Counter(), Counter()
    for period in periods:
        folder = base / period
        if not folder.is_dir() or folder.is_symlink():
            continue
        for path in folder.rglob("*.parquet"):
            if not path.is_file():
                continue
            relative = path.relative_to(folder)
            if any(p.is_symlink() for p in (
                    path, *list(path.parents)[:len(relative.parts)])):
                skipped_symlink[period] += 1
                continue
            years = set(map(int, core.YEAR_NAME.findall(
                relative.as_posix())))
            if len(years) != 1:
                unassigned[period] += 1
                continue
            year = next(iter(years))
            if start_year <= year <= end_year:
                discovered[period][year].append(path)
            else:
                outside_requested[period] += 1
        for files in discovered[period].values():
            files.sort()
    return discovered, {
        "year_ambiguous_or_absent_parquet_filenames_by_period":
            dict(sorted(unassigned.items())),
        "symlinked_parquet_files_skipped_by_period":
            dict(sorted(skipped_symlink.items())),
        "file_year_outside_requested_range_by_period":
            dict(sorted(outside_requested.items())),
    }


def year_period_footer(root, paths, year, period, max_groups):
    """Read a bounded number of source footers; totals never mean full coverage."""
    import pyarrow.parquet as pq

    totals = Counter()
    files = []
    minimum = maximum = None
    file_identity = []
    for source in paths:
        stat = source.stat()
        relative = source.relative_to(root).as_posix()
        # Stat-based identity is NOT a cryptographic hash of source contents.
        file_identity.append({
            "relative_source_path": relative, "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns})
        parquet = pq.ParquetFile(str(source))
        columns = set(parquet.schema_arrow.names)
        if not {"ts", "symbol"}.issubset(columns):
            raise ValueError(f"Missing key fields ts/symbol in Parquet: {relative}")
        count = parquet.metadata.num_row_groups
        if totals["row_groups"] + count > max_groups:
            raise ValueError(
                f"Footer row groups would exceed --max-row-groups {max_groups} "
                f"for {year}/{period}; only metadata read, no market bars read")
        totals["row_groups"] += count
        totals["rows_in_parquet_file_footers"] += int(parquet.metadata.num_rows)
        totals["bytes"] += int(stat.st_size)
        file_min = file_max = None
        unknown = 0
        for i in range(count):
            group = parquet.metadata.row_group(i)
            if group.num_rows == 0:
                totals["zero_row_groups"] += 1
                continue
            edges = footer_bounds(group)
            if edges is None:
                unknown += 1
                totals["nonempty_groups_without_usable_ts_bounds"] += 1
                continue
            first, last, first_day, last_day = edges
            totals["nonempty_groups_with_usable_ts_bounds"] += 1
            if first_day[:4] != str(year) or last_day[:4] != str(year):
                totals["groups_with_any_ts_bounds_outside_named_year"] += 1
            file_min = first if file_min is None else min(first, file_min)
            file_max = last if file_max is None else max(last, file_max)
            minimum = first if minimum is None else min(first, minimum)
            maximum = last if maximum is None else max(last, maximum)
        files.append({
            "relative_source_path": relative,
            "file_size_bytes": int(stat.st_size),
            "rows_from_footer": int(parquet.metadata.num_rows),
            "row_groups": count,
            "unknown_nonempty_ts_row_groups": unknown,
            "earliest_known_raw_source_timestamp": file_min,
            "latest_known_raw_source_timestamp": file_max,
            "file_time_bounds_are_only_footer_envelopes": True,
        })
    file_identity.sort(key=lambda x: x["relative_source_path"])
    signature = hashlib.sha256(json.dumps(
        file_identity, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    complete = (
        len(paths) > 0
        and totals["nonempty_groups_without_usable_ts_bounds"] == 0
        and totals["groups_with_any_ts_bounds_outside_named_year"] == 0
        and minimum is not None
        and maximum is not None)
    return {
        "period": period, "filename_year": year,
        "files": len(paths),
        "source_bytes": totals["bytes"],
        "source_rows_from_parquet_footers": totals[
            "rows_in_parquet_file_footers"],
        "row_groups": totals["row_groups"],
        "zero_row_groups": totals["zero_row_groups"],
        "nonempty_row_groups_with_usable_ts_bounds": totals[
            "nonempty_groups_with_usable_ts_bounds"],
        "nonempty_row_groups_without_usable_ts_bounds": totals[
            "nonempty_groups_without_usable_ts_bounds"],
        "row_groups_with_any_ts_bounds_outside_named_year": totals[
            "groups_with_any_ts_bounds_outside_named_year"],
        "earliest_known_raw_beijing_timestamp": minimum,
        "latest_known_raw_beijing_timestamp": maximum,
        "earliest_known_calendar_date": minimum[:10] if minimum else None,
        "latest_known_calendar_date": maximum[:10] if maximum else None,
        "footer_envelope_complete_for_nonempty_row_groups": complete,
        "source_file_stat_identity_sha256_not_content_digest": signature,
        "file_footer_summaries": files,
        "per_security_date_keys_validated": False,
        "actual_trading_day_completeness_validated": False,
        "time_label_policy_certified_for_all_years": False,
    }


def inventory(root, start_year, end_year, periods, max_files, max_groups):
    if not (1990 <= start_year <= end_year <= 2100
            and end_year - start_year <= 40):
        raise ValueError("Invalid or unbounded year range")
    if not periods or len(set(periods)) != len(periods) or any(
            p not in PERIODS for p in periods):
        raise ValueError("Periods must be unique day, 1min, or 5min")
    if not (1 <= max_files <= 100000 and 1 <= max_groups <= 1000000):
        raise ValueError("File/row-group safety caps outside supported range")
    root = Path(root).resolve()
    discovered, naming = source_files(root, periods, start_year, end_year)
    total = sum(len(paths) for entries in discovered.values()
                for paths in entries.values())
    if total > max_files:
        raise ValueError(
            f"Named-year Parquet file count {total} exceeds --max-files "
            f"{max_files}; no Parquet footer opened")
    all_entries = []
    for year in range(start_year, end_year + 1):
        for period in periods:
            files = discovered[period][year]
            all_entries.append(year_period_footer(
                root, files, year, period, max_groups))
    return {
        "format": "AStockDataTools Parquet primary footer coverage inventory v1",
        "year_start": start_year,
        "year_end": end_year,
        "periods": list(periods),
        "filename_year_and_period_footer_entries": all_entries,
        "files_with_supported_year_in_requested_range": total,
        "file_naming_caveats": naming,
        "only_parquet_file_footers_read": True,
        "no_parquet_row_batches_or_paid_ohlcva_read": True,
        "raw_market_ohlcva_exported": False,
        "coverage_is_envelope_not_exact_stock_day_presence": True,
        "absence_of_file_is_not_proof_of_no_exchange_trades": True,
        "stock_master_or_delisting_dates_verified": False,
        "files_copied_or_modified": False,
        "automatic_union_or_import_performed": False,
        "safe_to_automatically_fill_gaps": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path, help='Data root, e.g. D:\\stock')
    ap.add_argument("--from-year", type=int, default=2011)
    ap.add_argument("--to-year", type=int, default=2026)
    ap.add_argument("--periods", nargs="+", choices=PERIODS, default=list(PERIODS))
    ap.add_argument("--max-files", type=int, default=5000)
    ap.add_argument("--max-row-groups", type=int, default=100000,
                    help="Per year/period footer rowgroup safety cap")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--read-only", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        out, scratch = core.resolve_module_artifact_paths(args.out)
        root, _, _ = core.resolve_safe_paths(args.root, out, scratch)
        if not root.is_dir() or not (
                root / "AllCycleAStockData").is_dir():
            raise ValueError("Missing purchased Parquet root AllCycleAStockData")
        if (out.suffix.lower() != ".json"
                or not out.is_relative_to((MODULE / "reports").resolve())
                or out.exists()):
            raise ValueError("Use a new unique JSON path within module reports/")
        result = inventory(
            root, args.from_year, args.to_year, args.periods,
            args.max_files, args.max_row_groups)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print("Saved footer-only inventory:", out, flush=True)
        print("Named-year source files:", result[
            "files_with_supported_year_in_requested_range"], flush=True)
    except (ValueError, TypeError, OSError, OverflowError,
            ModuleNotFoundError) as error:
        ap.error(str(error))


if __name__ == "__main__":
    main()
