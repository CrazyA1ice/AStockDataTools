#!/usr/bin/env python3
"""Read-only metadata coverage envelopes for selecting a real H5/Parquet 5min overlap.

H5: reads only first/last datetimes from candidate per-symbol datasets, plus
binary-search boundaries if a dataset extends beyond the selected year.
Parquet: reads only row-group footer ts statistics, NO OHLCV rows.
This is date discovery, not a missing-key audit or a vendor-truth certification.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE_DIR = HERE.parent
CORE_SPEC = importlib.util.spec_from_file_location(
    "dual_source_envelope_core", HERE / "reconcile-local-a-share-h5-parquet.py")
core = importlib.util.module_from_spec(CORE_SPEC)
CORE_SPEC.loader.exec_module(core)


def read_h5_year_edges(ds, year):
    """Return first/last observed year timestamps without decoding OHLCV."""
    if not len(ds) or "datetime" not in (ds.dtype.names or ()):
        return None
    first = int(ds[0]["datetime"])
    last = int(ds[len(ds)-1]["datetime"])
    year_low = year * 100000000
    next_low = (year + 1) * 100000000
    if first > last:
        raise ValueError("H5 dataset first timestamp exceeds last; unsorted source")
    if last < year_low or first >= next_low:
        return None
    # For data extending beyond either side of requested year, take the exact
    # sorted year slice; no OHLCV arrays are materialized.
    if first < year_low or last >= next_low:
        left, right = core.h5_year_slice(ds, year)
        if right <= left:
            return None
        first = int(ds[left]["datetime"])
        last = int(ds[right-1]["datetime"])
    if not year_low <= first <= last < next_low:
        raise ValueError("H5 year boundary violates sorted timestamp assumption")
    return first, last


def inspect_h5(root, year):
    import h5py

    counters = Counter()
    months = Counter()
    missing_files = []
    earliest = None
    latest = None
    for market in ("sh", "sz", "bj"):
        source = root / "HikyuuData" / f"{market}_5min.h5"
        if not source.is_file() or source.is_symlink():
            missing_files.append(market + "_5min.h5")
            continue
        with h5py.File(source, "r") as handle:
            group = handle.get("data")
            if not isinstance(group, h5py.Group):
                raise ValueError("Missing H5 data group: " + source.name)
            for symbol in group:
                if not core.is_a_share_candidate(symbol, year):
                    continue
                counters["candidate_symbol_datasets"] += 1
                dataset = group.get(symbol)
                if not isinstance(dataset, h5py.Dataset):
                    counters["invalid_candidate_datasets"] += 1
                    continue
                if "datetime" not in (dataset.dtype.names or ()):
                    counters["invalid_candidate_datasets"] += 1
                    continue
                bounds = read_h5_year_edges(dataset, year)
                if bounds is None:
                    continue
                left, right = bounds
                counters["candidate_datasets_with_year_records"] += 1
                earliest = left if earliest is None else min(earliest, left)
                latest = right if latest is None else max(latest, right)
                months[str(right)[:6]] += 1
    return {
        "candidate_symbol_datasets": counters["candidate_symbol_datasets"],
        "candidate_datasets_with_year_records": counters[
            "candidate_datasets_with_year_records"],
        "invalid_candidate_datasets": counters["invalid_candidate_datasets"],
        "missing_market_files": missing_files,
        "earliest_candidate_year_bar_end": earliest,
        "latest_candidate_year_bar_end": latest,
        "last_record_month_dataset_counts": dict(sorted(months.items())),
        "data_rows_materialized": False,
        "edge_timestamps_only": True,
        "sorted_dataset_assumption_not_independently_certified": True
    }


def parquet_rg_ts_range(row_group):
    """Return footer bounds, or None when any prerequisite is not trustworthy."""
    for i in range(row_group.num_columns):
        col = row_group.column(i)
        if col.path_in_schema != "ts":
            continue
        stats = col.statistics
        if stats is None or not stats.has_min_max:
            return None
        try:
            lo, hi = int(stats.min), int(stats.max)
        except (ValueError, TypeError, OverflowError):
            return None
        if lo > hi:
            return None
        return lo, hi
    return None


def inspect_parquet(root, year):
    import pyarrow.parquet as pq

    paths = core.year_files(root, "5min", year)
    counters = Counter()
    min_stamp = None
    max_stamp = None
    summaries = []
    for source in paths:
        parquet = pq.ParquetFile(str(source))
        file_total = parquet.metadata.num_row_groups
        counters["row_groups_total"] += file_total
        file_known = 0
        file_min = None
        file_max = None
        for index in range(file_total):
            group = parquet.metadata.row_group(index)
            if group.num_rows == 0:
                counters["empty_row_groups"] += 1
                continue
            bounds = parquet_rg_ts_range(group)
            if bounds is None:
                counters["groups_without_usable_ts_footer"] += 1
                continue
            try:
                lo = core.pq_stamp(bounds[0], "5min")
                hi = core.pq_stamp(bounds[1], "5min")
            except (ValueError, OverflowError, OSError):
                counters["groups_without_usable_ts_footer"] += 1
                continue
            if lo > hi:
                counters["groups_without_usable_ts_footer"] += 1
                continue
            min_stamp = lo if min_stamp is None else min(min_stamp, lo)
            max_stamp = hi if max_stamp is None else max(max_stamp, hi)
            file_min = lo if file_min is None else min(file_min, lo)
            file_max = hi if file_max is None else max(file_max, hi)
            file_known += 1
        summaries.append({
            "parquet_file": source.relative_to(
                root / "AllCycleAStockData" / "5min").as_posix(),
            "row_groups": file_total,
            "row_groups_with_usable_ts_footer": file_known,
            "earliest_footer_candidate_bar_end": file_min,
            "latest_footer_candidate_bar_end": file_max
        })
    return {
        "files": len(paths),
        "row_groups_total": counters["row_groups_total"],
        "empty_row_groups": counters["empty_row_groups"],
        "groups_without_usable_ts_footer": counters[
            "groups_without_usable_ts_footer"],
        "earliest_footer_candidate_bar_end": min_stamp,
        "latest_footer_candidate_bar_end": max_stamp,
        "file_coverage_envelopes": summaries,
        "no_parquet_data_rows_read": True,
        "footer_coverage_not_exact_key_presence": True,
        "time_convention_start_plus_5_minutes_unverified": True
    }


def proposed_window(h5, parquet, year, max_calendar_days=7):
    """Suggest bounded calendar dates only when source metadata is sufficient.

    The envelope is NOT proof that H5 and Parquet have a matching security
    on those days. Users must run the actual read-only reconciliation.
    """
    h_earliest = h5["earliest_candidate_year_bar_end"]
    h_latest = h5["latest_candidate_year_bar_end"]
    p_earliest = parquet["earliest_footer_candidate_bar_end"]
    p_latest = parquet["latest_footer_candidate_bar_end"]
    if (None in (h_earliest, h_latest, p_earliest, p_latest)
        or h5["missing_market_files"] or h5["invalid_candidate_datasets"]
        or parquet["groups_without_usable_ts_footer"]):
        return {
            "available": False, "reason": "incomplete_source_or_footer_metadata",
            "proves_real_overlap": False
        }
    start = max(h_earliest // 10000, p_earliest // 10000, year * 10000 + 101)
    end = min(h_latest // 10000, p_latest // 10000, year * 10000 + 1231)
    if start > end:
        return {
            "available": False, "reason": "source_date_envelopes_do_not_overlap",
            "proves_real_overlap": False
        }
    end_date = date.fromisoformat(str(end)[:4] + "-" + str(end)[4:6] + "-" + str(end)[6:])
    start_date = max(
        date.fromisoformat(str(start)[:4] + "-" + str(start)[4:6] + "-" + str(start)[6:]),
        end_date - timedelta(days=max_calendar_days - 1))
    return {
        "available": True,
        "from_date": start_date.isoformat(),
        "to_date": end_date.isoformat(),
        "reason": "candidate_latest_overlapping_date_envelopes",
        "proves_real_overlap": False,
        "warning": ("Only H5 sorted-data boundaries and Parquet footer min/max "
                    "have been examined; overlap and listing/trading days "
                    "still require exact key scans.")
    }


def make_report(root, year):
    h = inspect_h5(root, year)
    p = inspect_parquet(root, year)
    return {
        "format": "AStockDataTools dual-source 5min date-envelope probe v1",
        "year": year,
        "universe": "a-share-candidate",
        "h5": h,
        "parquet": p,
        "suggested_bounded_window": proposed_window(h, p, year),
        "original_sources_modified": False,
        "no_raw_ohlcv_exported": True,
        "scope": "H5 per-dataset datetime boundaries; Parquet rowgroup ts footers",
        "scan_complete_for_source_bounds": (
            not h["missing_market_files"]
            and h["invalid_candidate_datasets"] == 0
            and p["files"] > 0
            and p["groups_without_usable_ts_footer"] == 0),
        "validates_exact_overlap_or_absence": False,
        "safe_to_automatically_union": False
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=Path("reports") /
                        "dual-source-5min-2026-date-envelopes.json")
    parser.add_argument("--read-only", required=True, action="store_true")
    args = parser.parse_args(argv)
    try:
        if not 2011 <= args.year <= 2030:
            raise ValueError("Year out of supported range")
        output, scratch = core.resolve_module_artifact_paths(args.out, None)
        root, _, _ = core.resolve_safe_paths(args.root, output, scratch)
        report_dir = (MODULE_DIR / "reports").resolve()
        if not output.is_relative_to(report_dir) or output.suffix.lower() != ".json":
            raise ValueError("Output must be a JSON file under module reports/")
        if output.exists():
            raise ValueError("Refusing to overwrite an existing coverage report")
        if not (root / "HikyuuData").is_dir() or not (
            root / "AllCycleAStockData" / "5min").is_dir():
            raise ValueError("Missing H5 or Parquet 5min source directories")
        report = make_report(root, args.year)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        print("Saved read-only dual-source date envelopes:", output, flush=True)
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
