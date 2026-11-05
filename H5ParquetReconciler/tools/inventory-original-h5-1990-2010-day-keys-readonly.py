#!/usr/bin/env python3
"""Bounded 1990-2010 original Hikyuu daily H5 key-only coverage inventory.

This is NOT a historical bootstrap/stage/merge and does not certify a security
master or purchased pre-2011 coverage. It reads only H5 native datetime
columns, classifies conservative A-share code candidates by the existing
reconciler, and prints aggregate counts. No market OHLCVA/stock identifiers are
exported; original H5, Parquet, versions, pointers and indexes remain intact.

Any malformed selected native daily time key, duplicate, missing source file,
unsafe symlink, over-budget input or source stat drift fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "h5_early_history_same_market_conservative_identity",
    HERE / "reconcile-local-a-share-h5-parquet.py")
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)

START_YEAR = 1990
END_YEAR = 2010
LOW = 199001010000
HIGH = 201101010000
MAX_ROWS_HARD = 80000000
MAX_SYMBOL_DATASETS = 50000
MARKETS = ("sh", "sz", "bj")


def _file_state(path):
    s = path.stat()
    return (s.st_size, s.st_mtime_ns)


def _checked_ymd(stamps, np):
    if len(stamps) == 0:
        return stamps
    if not np.issubdtype(stamps.dtype, np.integer):
        raise ValueError("Nonintegral original daily native time key")
    if np.any(stamps < LOW) or np.any(stamps >= HIGH):
        raise ValueError("Original selected H5 date escaped 1990-2010")
    if np.any(stamps % 10000 != 0):
        raise ValueError("Non-midnight original H5 daily date key")
    day8 = stamps // 10000
    years = day8 // 10000
    months = (day8 // 100) % 100
    days = day8 % 100
    if np.any(months < 1) or np.any(months > 12):
        raise ValueError("Malformed original H5 daily month")
    lengths = np.array([0,31,28,31,30,31,30,31,31,30,31,30,31],
                       dtype=np.int64)
    last_days = lengths[months]
    leap = (years % 4 == 0) & ((years % 100 != 0) | (years % 400 == 0))
    last_days = last_days + ((months == 2) & leap)
    if np.any(days < 1) or np.any(days > last_days):
        raise ValueError("Malformed original H5 daily calendar date")
    return day8


def inventory(root, *, max_rows=30000000, chunk_rows=16384):
    """Inventory source keys only; no original OHLCVA dataset read."""
    import h5py
    import numpy as np

    if (type(max_rows) is not int or not 1 <= max_rows <= MAX_ROWS_HARD
            or type(chunk_rows) is not int or not 1024 <= chunk_rows <= 65536):
        raise ValueError("Unsafe historical H5 scan budget")
    root = Path(root).resolve()
    source = root / "HikyuuData"
    if (not root.is_dir() or not source.is_dir()
            or root == HERE.parent or root.is_relative_to(HERE.parent)
            or source.is_symlink()):
        raise ValueError("Unsafe or nonexistent original Hikyuu H5 source")
    paths = [(market, source / (market + "_day.h5")) for market in MARKETS]
    before = {}
    for market, path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Original H5 daily market source missing or symlinked")
        before[market] = _file_state(path)
    years = {
        year: {
            "a_share_candidate_stockdays":0,
            "other_code_stockdays":0,
            "candidate_symbols":set(),
            "other_symbols":set(),
            "candidate_dates":set(),
            "other_dates":set(),
            "market_candidate_stockdays":Counter(),
            "market_other_stockdays":Counter(),
        } for year in range(START_YEAR, END_YEAR+1)
    }
    inspected = Counter()
    native_earliest = None
    earliest_pre_1990 = False
    total = 0
    seen_symbols = set()
    for market, path in paths:
        with h5py.File(path, "r") as fh:
            group = fh.get("data")
            if not isinstance(group, h5py.Group):
                raise ValueError("Original H5 day source lacks data group")
            for symbol in group:
                inspected["source_symbol_datasets"] += 1
                if inspected["source_symbol_datasets"] > MAX_SYMBOL_DATASETS:
                    raise ValueError("Original H5 contains too many symbol datasets")
                if (type(symbol) is not str or not symbol.startswith(market.upper())
                        or CORE.symbol_id(symbol) != symbol
                        or symbol in seen_symbols):
                    raise ValueError("Malformed or duplicated cross-market H5 symbol key")
                seen_symbols.add(symbol)
                ds = group.get(symbol)
                if (not isinstance(ds, h5py.Dataset)
                        or not set(CORE.H5_FIELDS).issubset(ds.dtype.names or ())):
                    raise ValueError("Original H5 daily dataset/schema invalid")
                if len(ds) == 0:
                    inspected["empty_source_datasets"] += 1
                    continue
                first = int(ds[0]["datetime"])
                last = int(ds[-1]["datetime"])
                if first > last:
                    raise ValueError("Original H5 day dataset first/last descending")
                if native_earliest is None or first < native_earliest:
                    native_earliest = first
                if first < LOW:
                    earliest_pre_1990 = True
                if first >= HIGH:
                    inspected["source_datasets_entirely_after_2010"] += 1
                    continue
                # Index lookup only; do not load entire H5 history or prices.
                lo, hi = CORE.h5_key_slice(ds, LOW, HIGH)
                if not 0 <= lo <= hi <= len(ds):
                    raise ValueError("Invalid H5 early-history key slice")
                if hi == lo:
                    continue
                inspected["source_datasets_with_pre2011_keys"] += 1
                candidate_by_year = {
                    y: CORE.is_a_share_candidate(symbol, y)
                    for y in range(START_YEAR, END_YEAR+1)
                }
                previous = None
                for begin in range(lo, hi, chunk_rows):
                    until = min(begin + chunk_rows, hi)
                    stamps = np.asarray(ds.fields("datetime")[begin:until],
                                        dtype=np.int64)
                    if len(stamps) != until - begin:
                        raise ValueError("Incomplete original H5 native time projection")
                    if previous is not None and int(stamps[0]) <= previous:
                        raise ValueError("Duplicate or unsorted H5 daily source key")
                    if np.any(np.diff(stamps) <= 0):
                        raise ValueError("Duplicate or unsorted H5 daily source key")
                    previous = int(stamps[-1])
                    days = _checked_ymd(stamps, np)
                    total += len(days)
                    if total > max_rows:
                        raise ValueError("Pre-2011 H5 native day-key row budget exceeded")
                    inspected["source_native_day_keys_projected"] = total
                    for y in np.unique(days // 10000):
                        year = int(y)
                        mask = (days // 10000) == year
                        n = int(np.count_nonzero(mask))
                        summary = years[year]
                        if candidate_by_year[year]:
                            summary["a_share_candidate_stockdays"] += n
                            summary["candidate_symbols"].add(symbol)
                            summary["candidate_dates"].update(
                                np.unique(days[mask]).tolist())
                            summary["market_candidate_stockdays"][market.upper()] += n
                        else:
                            summary["other_code_stockdays"] += n
                            summary["other_symbols"].add(symbol)
                            summary["other_dates"].update(
                                np.unique(days[mask]).tolist())
    after = {market: _file_state(path) for market, path in paths}
    if after != before:
        raise ValueError("Original H5 market source stat changed during inventory")
    annual = []
    for y in years:
        v = years[y]
        annual.append({
            "year":y,
            "h5_a_share_code_candidate_stockdays":v["a_share_candidate_stockdays"],
            "h5_other_code_stockdays":v["other_code_stockdays"],
            "a_share_candidate_source_symbol_count":len(v["candidate_symbols"]),
            "other_code_source_symbol_count":len(v["other_symbols"]),
            "a_share_candidate_distinct_dates":len(v["candidate_dates"]),
            "other_code_distinct_dates":len(v["other_dates"]),
            "candidate_stockdays_by_market":{
                m.upper():v["market_candidate_stockdays"][m]
                for m in MARKETS},
            "other_code_stockdays_by_market":{
                m.upper():v["market_other_stockdays"][m]
                for m in MARKETS},
        })
    stamp_state = hashlib.sha256(json.dumps(
        {m: list(before[m]) for m in MARKETS},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "state":"pre2011_hikyuu_daily_native_key_inventory_readonly_not_merged",
        "source_period":"day",
        "year_start":START_YEAR,
        "year_end":END_YEAR,
        "years_in_inventory":len(annual),
        "annual_coverage":annual,
        "source_symbol_datasets":inspected["source_symbol_datasets"],
        "source_datasets_with_pre2011_keys":
            inspected["source_datasets_with_pre2011_keys"],
        "source_datasets_entirely_after_2010":
            inspected["source_datasets_entirely_after_2010"],
        "source_native_day_keys_projected":total,
        "h5_a_share_code_candidate_stockdays_total":
            sum(v["h5_a_share_code_candidate_stockdays"] for v in annual),
        "h5_other_code_stockdays_total":
            sum(v["h5_other_code_stockdays"] for v in annual),
        "first_native_source_key_observed":native_earliest,
        "source_has_keys_before_1990":earliest_pre_1990,
        "source_file_size_mtime_state_sha256":stamp_state,
        "code_classification":"existing_conservative_year_specific_a_share_code_candidate_not_security_master",
        "native_keys_checked_for_calendar_validity_and_sorted_selected_range":True,
        "global_h5_datetime_order_certified":False,
        "purchased_parquet_pre2011_overlap_verified":False,
        "original_source_h5_file_stat_unchanged":True,
        "market_ohlcva_read":False,
        "source_security_codes_exported":False,
        "market_source_files_written":False,
        "private_candidate_or_version_created":False,
        "production_query_activated":False,
        "ready_to_merge_into_parquet":False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--max-rows", type=int, default=30000000)
    p.add_argument("--chunk-rows", type=int, default=16384)
    a = p.parse_args(argv)
    print(json.dumps(inventory(a.source_root, max_rows=a.max_rows,
                               chunk_rows=a.chunk_rows),
                     ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
