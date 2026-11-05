#!/usr/bin/env python3
"""Audit the 2025 unselected PURCHASED 5min source rows by code prefix.

Revalidate all twelve already accepted source-key receipts and the five
purchased Parquet footer totals FIRST. Then stream only ts/symbol columns
from the original 2025 purchased 5min Parquet. Never decode OHLCVA or H5,
write indexes, create market copies, or activate production sources.

An unselected symbol code prefix is evidence of the vendor's raw code
spelling, NOT a certified security class (fund, bond, B share etc.).
Exactly 48 source bars per unselected 5min stockday is an independently
checked GRID, not a listing/real trading-day certification.

Does not scan the 321m 1min rows: 1min unselected count remains an
independent footer-only aggregate until a later targeted cross-check.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
YEAR = 2025
PERIOD = "5min"
MAX_SOURCE_ROWS = 70000000
MAX_STOCKDAYS = 100000


def _load(tag, name):
    spec = importlib.util.spec_from_file_location(tag, HERE / name)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


R = _load("2025_revalidated_footer_and_selected_source_keys",
          "reconcile-2025-selected-minute-keys-to-five-cycle-footers-readonly.py")
D = _load("2025_session_native_source_key_grid",
          "preview-minute-exact-key-diff-readonly.py")
CORE = R.F.core


def code_group(raw):
    """Conservative raw-code PREFIX classification, never a security master."""
    canonical = CORE.symbol_id(raw)
    if canonical is None:
        return False, "UNRECOGNIZED", "unrecognized_raw_symbol"
    if CORE.is_a_share_candidate(canonical, YEAR):
        return True, None, "selected_ashare_code_candidate"
    return False, canonical[:5], "recognized_code_but_not_selected_ashare"


def _grid(day, cache):
    mask = cache.get(day)
    if mask is None:
        native = D.normalized_native_keys(day, PERIOD)
        expected = set(native.values())
        if len(expected) != 48:
            raise ValueError("Source 5min standard reference must have 48 unique keys")
        origin = D.I.day_epoch_ms(day)
        mask = 0
        for stamp in expected:
            delta = stamp-origin
            if delta < 0 or delta % 60000 or delta >= 86400000:
                raise ValueError("Invalid regular source 5min timestamp")
            mask |= 1 << (delta // 60000)
        cache[day] = mask
    return mask


def scan_5min_sources(root, paths, *, expected_total, expected_selected,
                      max_source_rows=MAX_SOURCE_ROWS,
                      max_stockdays=MAX_STOCKDAYS):
    """Return aggregate 5min source code groups with checked unselected grids."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    if (type(max_source_rows) is not int or not 1 <= max_source_rows <= MAX_SOURCE_ROWS
            or type(max_stockdays) is not int or not 1 <= max_stockdays <= MAX_STOCKDAYS
            or type(expected_total) is not int or type(expected_selected) is not int
            or not 0 <= expected_selected <= expected_total <= max_source_rows
            or not isinstance(paths, list) or not 1 <= len(paths) <= 12):
        raise ValueError("Invalid source-only year or bounded scan budget")
    root = Path(root).resolve()
    code_cache = {}
    stockday_masks = {}
    grid_cache = {}
    groups = Counter()
    category_counts = Counter()
    symbols_by_group = defaultdict(set)
    stockdays_by_group = defaultdict(set)
    all_unselected_symbols = set()
    source_files_before = {}
    total_rows = selected_rows = 0
    for path in paths:
        if (path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(
                    root / "AllCycleAStockData" / PERIOD)):
            raise ValueError("Unsafe purchased 5min Parquet source")
        stat = path.stat()
        source_files_before[path] = (stat.st_size, stat.st_mtime_ns)
        with pq.ParquetFile(path, memory_map=False, pre_buffer=False) as pf:
            names = pf.schema_arrow.names
            if "ts" not in names or "symbol" not in names:
                raise ValueError("Purchased 5min source missing ts/symbol")
            typ = pf.schema_arrow.field("ts").type
            if not pa.types.is_int64(typ):
                raise ValueError("Purchased timestamp must be int64 epoch-ms")
            symbol_type = pf.schema_arrow.field("symbol").type
            if pa.types.is_dictionary(symbol_type):
                symbol_type = symbol_type.value_type
            if not (pa.types.is_string(symbol_type) or
                    pa.types.is_large_string(symbol_type)):
                raise ValueError("Purchased symbol must be string")
            total_rows += pf.metadata.num_rows
            if total_rows > max_source_rows:
                raise ValueError("Original source row budget exceeded before Arrow scan")
            for batch in pf.iter_batches(
                    columns=["ts", "symbol"], batch_size=65536,
                    use_threads=False):
                if batch.num_columns != 2 or batch.column(0).null_count:
                    raise ValueError("Untrusted timestamp projection")
                stamps, symbols = batch.column(0), batch.column(1)
                # Classify each DISTINCT source symbol once, vectorized
                # Arrow mask removes selected A shares before Python rows.
                unique = pc.unique(symbols).to_pylist()
                approved = []
                for raw in unique:
                    key = raw if raw is not None else None
                    if key not in code_cache:
                        code_cache[key] = code_group(raw)
                    if code_cache[key][0] and raw is not None:
                        approved.append(raw)
                mask = pc.is_in(symbols, value_set=pa.array(
                    approved, type=pa.string()))
                selected_rows += int(pc.sum(pc.cast(mask, pa.int64())).as_py() or 0)
                excluded = batch.filter(pc.invert(mask)).to_pylist()
                for item in excluded:
                    stamp = item["ts"]
                    raw = item["symbol"]
                    if type(stamp) is not int or stamp % 60000:
                        raise ValueError("Unselected source minute timestamp invalid")
                    try:
                        dt = datetime.fromtimestamp(stamp / 1000, tz=CORE.UTC8)
                    except (ValueError, OSError, OverflowError) as exc:
                        raise ValueError("Unselected source calendar invalid") from exc
                    if dt.year != YEAR:
                        raise ValueError("Unselected row outside source filename year")
                    d = dt.date()
                    origin = D.I.day_epoch_ms(d)
                    minute = (stamp - origin) // 60000
                    if minute < 0 or minute >= 1440:
                        raise ValueError("Invalid local minute of day")
                    group, category = code_cache[raw][1:]
                    identity = (raw, d.isoformat())
                    if identity not in stockday_masks:
                        if len(stockday_masks) >= max_stockdays:
                            raise ValueError("Unselected stockday memory budget exceeded")
                        stockday_masks[identity] = 0
                    bit = 1 << minute
                    if stockday_masks[identity] & bit:
                        raise ValueError("Duplicate unselected source security/day/minute key")
                    stockday_masks[identity] |= bit
                    groups[group] += 1
                    category_counts[category] += 1
                    symbols_by_group[group].add(raw)
                    stockdays_by_group[group].add(identity)
                    all_unselected_symbols.add(raw)
    if total_rows != expected_total or selected_rows != expected_selected:
        raise ValueError("Selected stockday source keys or full footer row count disagree")
    if sum(groups.values()) != total_rows - selected_rows:
        raise ValueError("Unselected security prefix row conservation mismatch")
    full = 0
    nonstandard = Counter()
    for (symbol, day_str), bits in stockday_masks.items():
        d = datetime.strptime(day_str, "%Y-%m-%d").date()
        expected = _grid(d, grid_cache)
        if bits == expected:
            full += 1
        else:
            nonstandard["nonstandard_stockdays"] += 1
            nonstandard["missing_expected_keys"] += (expected & ~bits).bit_count()
            nonstandard["extra_unexpected_keys"] += (bits & ~expected).bit_count()
    for path, old in source_files_before.items():
        now = path.stat()
        if old != (now.st_size, now.st_mtime_ns):
            raise RuntimeError("Purchased source changed during excluded-key scan")
    prefix_breakdown = {
        k: {
            "source_rows": groups[k],
            "distinct_raw_symbol_count": len(symbols_by_group[k]),
            "observed_unselected_stockday_count": len(stockdays_by_group[k]),
            "security_class_master_verified": False,
        }
        for k in sorted(groups)
    }
    return {
        "period": PERIOD,
        "scanned_source_rows": total_rows,
        "selected_ashare_code_candidate_rows": selected_rows,
        "unselected_source_rows": sum(groups.values()),
        "unselected_code_groups": prefix_breakdown,
        "unselected_recognized_or_unknown_code_categories": dict(sorted(
            category_counts.items())),
        "unselected_distinct_raw_symbols": len(all_unselected_symbols),
        "unselected_observed_stockdays": len(stockday_masks),
        "unselected_complete_48_key_stockdays": full,
        "unselected_nonstandard_key_stockdays": dict(sorted(nonstandard.items())),
        "unselected_all_observed_stockdays_match_48_key_grid":
            full == len(stockday_masks),
        "prefix_groups_are_not_certified_security_classes": True,
        "no_unselected_raw_security_codes_exported": True,
        "no_ohlcva_columns_opened": True,
    }


def inspect(root, *, max_source_rows=MAX_SOURCE_ROWS):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Untrusted market root")
    prior = R.reconcile(root)
    if prior["status"] != (
            "2025_source_footer_and_selected_ashare_key_totals_exactly_conserved"):
        raise ValueError("Prior 2025 annual key/footer check missing")
    before = R.B.A.I.N.source_snapshot(root, YEAR)
    files, _ = R.F.source_files(root, (PERIOD,), YEAR, YEAR)
    paths = files[PERIOD][YEAR]
    read = scan_5min_sources(
        root, paths, expected_total=prior["whole_source_footer_rows"][PERIOD],
        expected_selected=prior["selected_ashare_minute_keys"][PERIOD],
        max_source_rows=max_source_rows)
    if before != R.B.A.I.N.source_snapshot(root, YEAR):
        raise RuntimeError("Purchased/H5 source metadata changed during classification")
    if read["unselected_source_rows"] != (
            prior["unselected_source_rows_unknown_security_class"][PERIOD]):
        raise ValueError("2025 source remainder disagrees with verified footers")
    return {
        "format": "AStockDataTools 2025 purchased excluded 5min ts-symbol code-prefix audit v1",
        "status": "2025_5min_unselected_source_code_prefixes_audited_not_security_master",
        **read,
        "original_1min_unselected_source_rows_footer_only":
            prior["unselected_source_rows_unknown_security_class"]["1min"],
        "five_cycle_source_footer_stockday_equivalents":
            prior["whole_source_standard_stockday_equivalents_by_cycle"],
        "independent_exchange_calendar_certified": False,
        "security_type_by_code_prefix_certified": False,
        "2025_1min_excluded_code_classification_completed": False,
        "original_market_files_modified": False,
        "new_private_index_or_market_files_written": False,
        "h5_market_bars_opened": False,
        "production_source_activated": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--max-source-rows", type=int, default=MAX_SOURCE_ROWS)
    args = p.parse_args(argv)
    result = inspect(args.root, max_source_rows=args.max_source_rows)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    if not result["unselected_all_observed_stockdays_match_48_key_grid"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
