#!/usr/bin/env python3
"""Read-only physical purchased Parquet daily pre-2011 coverage audit.

Inspects EVERY day/*.parquet file, including misleadingly named partitions.
Prunes rowgroups only when typed ts footer bounds prove no date before
2011-01-01; physically projects ts/symbol ONLY for uncertain/overlapping
rowgroups. Never reads licensed OHLCVA, writes market files, indexes,
candidate partitions, or records exact security codes in the SAFE result.

The result is an existence/coverage audit, NOT security master validation,
not an exact H5 vs Parquet union or production merge authorization.
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
SPEC = importlib.util.spec_from_file_location(
    "pre2011_purchased_daily_source_core",
    HERE / "reconcile-local-a-share-h5-parquet.py")
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)
LOW_MS = int(datetime(1990, 1, 1, tzinfo=CORE.UTC8).timestamp() * 1000)
HIGH_MS = int(datetime(2011, 1, 1, tzinfo=CORE.UTC8).timestamp() * 1000)
MAX_FILES = 5000
MAX_GROUPS = 300000
MAX_ROWS_TO_PROJECT = 10000000
MAX_OLD_STOCKDAYS = 6000000
YEARS = tuple(range(1990, 2011))


def _source_paths(root):
    base = root / "AllCycleAStockData"
    folder = base / "day"
    if (not root.is_dir() or not base.is_dir() or not folder.is_dir()
            or base.is_symlink() or folder.is_symlink()
            or base.resolve().is_relative_to(HERE.parent)
            or root.resolve().is_relative_to(HERE.parent)):
        raise ValueError("Missing or unsafe purchased original day source")
    paths = []
    # rglob returns directory symlinks as entries on supported pathlib.
    # Disallow any such source rather than silently omitting its content.
    for path in folder.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symlinked purchased day path is not an audited source")
        if path.is_dir():
            continue
        if not path.is_file() or path.suffix.lower() != ".parquet":
            raise ValueError("Unexpected non-Parquet purchased day source artifact")
        if not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError("Purchased day source path escapes immutable root")
        paths.append(path)
        if len(paths) > MAX_FILES:
            raise ValueError("Purchased day source file budget exceeded")
    if not paths:
        raise ValueError("No purchased day files: cannot claim historical absence")
    return sorted(paths, key=lambda p: p.relative_to(folder).as_posix())


def _footer_ts_bounds(rowgroup, ts_index):
    """Return exact integer footer min/max, otherwise None: MUST key-scan."""
    column = rowgroup.column(ts_index)
    stats = column.statistics
    if stats is None or not stats.has_min_max:
        return None
    a, b = stats.min, stats.max
    if type(a) is not int or type(b) is not int or a > b:
        return None
    return (a, b)


def audit(root, *, max_projected_rows=MAX_ROWS_TO_PROJECT,
          max_stockdays=MAX_OLD_STOCKDAYS):
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    if (type(max_projected_rows) is not int
            or not 1 <= max_projected_rows <= MAX_ROWS_TO_PROJECT
            or type(max_stockdays) is not int
            or not 1 <= max_stockdays <= MAX_OLD_STOCKDAYS):
        raise ValueError("Invalid pre-2011 Parquet key projection budget")
    root = Path(root).resolve()
    files = _source_paths(root)
    before = [(p, p.stat().st_size, p.stat().st_mtime_ns) for p in files]
    counts = Counter()
    annual = {
        y: {"candidate": 0, "other": 0,
            "candidate_symbols": set(), "other_symbols": set(),
            "dates": set()} for y in YEARS
    }
    observed = set()
    earliest_physical_ms = None
    all_rg_upper_ge_2011 = True
    for path in files:
        pf = pq.ParquetFile(str(path))
        names = pf.schema_arrow.names
        if names.count("ts") != 1 or names.count("symbol") != 1:
            raise ValueError("Untrusted purchased day key-only Parquet schema")
        ts_index = names.index("ts")
        if not pa.types.is_integer(pf.schema_arrow.field("ts").type):
            raise ValueError("Purchased day time key must be original integer epoch milliseconds")
        if not (pa.types.is_string(pf.schema_arrow.field("symbol").type)
                or pa.types.is_large_string(pf.schema_arrow.field("symbol").type)):
            raise ValueError("Purchased day symbol must be original text")
        counts["source_files"] += 1
        counts["physical_rows_in_all_purchased_day_files"] += pf.metadata.num_rows
        for rg_id in range(pf.metadata.num_row_groups):
            counts["rowgroups_total"] += 1
            if counts["rowgroups_total"] > MAX_GROUPS:
                raise ValueError("Purchased source footer rowgroup budget exceeded")
            rg = pf.metadata.row_group(rg_id)
            if rg.num_rows < 0:
                raise ValueError("Negative purchased source rowgroup size")
            bounds = _footer_ts_bounds(rg, ts_index)
            if bounds is not None:
                if bounds[0] < HIGH_MS:
                    all_rg_upper_ge_2011 = False
                if bounds[0] >= HIGH_MS:
                    counts["rowgroups_pruned_proven_by_min_ts_ge_2011"] += 1
                    counts["physical_rows_pruned_proven_by_min_ts_ge_2011"] += rg.num_rows
                    continue
            else:
                counts["rowgroups_missing_or_untrusted_timestamp_footer"] += 1
                all_rg_upper_ge_2011 = False
            # Before ever opening two key columns, validate the total
            # physical row-group work. No OHLCVA can be read on this path.
            counts["rowgroups_key_projected"] += 1
            if (counts["physical_rows_key_projected"] + rg.num_rows
                    > max_projected_rows):
                raise ValueError(
                    "Pre-2011 Parquet key-only rowgroup projection budget exceeded;"
                    " no OHLCVA opened and no historical absence inferred")
            counts["physical_rows_key_projected"] += rg.num_rows
            scanned = 0
            for batch in pf.iter_batches(
                    row_groups=[rg_id], columns=["ts", "symbol"],
                    batch_size=65536, use_threads=False):
                scanned += batch.num_rows
                # Check the physical projected schema instead of relying on
                # column order: Parquet can store symbol before ts.
                index = batch.schema.get_field_index("ts")
                if index < 0:
                    raise ValueError("Missing projected native ts column")
                physical_ts = batch.column(index)
                if physical_ts.null_count:
                    raise ValueError("Null purchased day timestamp in projected source")
                # Only materialize rows whose ts is earlier than 2011:
                # irrelevant 2011+ security identities never leave Arrow.
                old = batch.filter(pc.less(physical_ts,
                                           pa.scalar(HIGH_MS, type=pa.int64())))
                for record in old.to_pylist():
                    ts, raw_symbol = record["ts"], record["symbol"]
                    if type(ts) is not int or type(raw_symbol) is not str:
                        raise ValueError("Noncanonical physical pre-2011 daily row")
                    canonical = CORE.symbol_id(raw_symbol)
                    if canonical is None:
                        raise ValueError("Unknown original purchased day security code")
                    if earliest_physical_ms is None or ts < earliest_physical_ms:
                        earliest_physical_ms = ts
                    if ts < LOW_MS:
                        counts["before_1990_physical_rows"] += 1
                        continue
                    day = datetime.fromtimestamp(ts / 1000, tz=CORE.UTC8).date()
                    year = day.year
                    if year not in annual:
                        raise ValueError("Original daily time key escaped 1990-2010")
                    key = (canonical, day.isoformat())
                    if key in observed:
                        raise ValueError("Duplicated purchased pre-2011 stockday key")
                    if len(observed) >= max_stockdays:
                        raise ValueError("Purchased physical historical exact key budget exceeded")
                    observed.add(key)
                    row = annual[year]
                    row["dates"].add(day.isoformat())
                    if CORE.is_a_share_candidate(canonical, year):
                        row["candidate"] += 1
                        row["candidate_symbols"].add(canonical)
                    else:
                        row["other"] += 1
                        row["other_symbols"].add(canonical)
            if scanned != rg.num_rows:
                raise ValueError("Purchased Parquet projected key rows were incomplete")
    if [(p, p.stat().st_size, p.stat().st_mtime_ns) for p in files] != before:
        raise ValueError("Purchased original Parquet source stat changed during audit")
    out = [{
        "year": y,
        "purchased_a_share_code_candidate_stockdays": annual[y]["candidate"],
        "purchased_other_instrument_stockdays": annual[y]["other"],
        "purchased_distinct_native_date_labels": len(annual[y]["dates"]),
        "purchased_a_share_candidate_symbol_count": len(annual[y]["candidate_symbols"]),
    } for y in YEARS]
    old_total = sum(x["purchased_a_share_code_candidate_stockdays"]
                    + x["purchased_other_instrument_stockdays"] for x in out)
    if (old_total != len(observed)
            or counts["physical_rows_key_projected"] +
               counts["physical_rows_pruned_proven_by_min_ts_ge_2011"] !=
               counts["physical_rows_in_all_purchased_day_files"]):
        raise ValueError("Original purchased day source key conservation mismatch")
    state_sha = hashlib.sha256(json.dumps(
        [(p.relative_to(root).as_posix(), size, mtime) for p, size, mtime in before],
        separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return {
        "state": "pre2011_purchased_parquet_original_day_keys_audited_readonly",
        "years": "1990-2010", "annual_coverage": out,
        "source_files": counts["source_files"],
        "rowgroups_total": counts["rowgroups_total"],
        "rowgroups_pruned_proven_by_min_ts_ge_2011":
            counts["rowgroups_pruned_proven_by_min_ts_ge_2011"],
        "rowgroups_missing_or_untrusted_timestamp_footer":
            counts["rowgroups_missing_or_untrusted_timestamp_footer"],
        "rowgroups_key_projected": counts["rowgroups_key_projected"],
        "physical_rows_in_all_purchased_day_files":
            counts["physical_rows_in_all_purchased_day_files"],
        "physical_rows_pruned_by_footer":
            counts["physical_rows_pruned_proven_by_min_ts_ge_2011"],
        "physical_rows_key_projected": counts["physical_rows_key_projected"],
        "pre1990_physical_rows_detected": counts["before_1990_physical_rows"],
        "purchased_1990_2010_a_share_code_candidate_stockdays":
            sum(x["purchased_a_share_code_candidate_stockdays"] for x in out),
        "purchased_1990_2010_other_instrument_stockdays":
            sum(x["purchased_other_instrument_stockdays"] for x in out),
        "purchased_1990_2010_all_stockday_keys": old_total,
        "no_1990_2010_purchased_keys_in_audited_files": old_total == 0,
        "all_rowgroups_have_trusted_min_ts_ge_2011": all_rg_upper_ge_2011,
        "source_file_size_mtime_state_sha256": state_sha,
        "purchased_original_source_stat_unchanged": True,
        "all_source_day_parquet_paths_scanned_irrespective_of_filename": True,
        "source_key_only_no_ohlcva_read": True,
        "exact_security_codes_or_prices_exported": False,
        "h5_stockday_key_overlap_ever_compared": False,
        "historical_candidate_staged_or_merged": False,
        "market_files_written": False,
        "production_activated": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--max-project-rows", type=int, default=MAX_ROWS_TO_PROJECT)
    p.add_argument("--max-stockdays", type=int, default=MAX_OLD_STOCKDAYS)
    a = p.parse_args(argv)
    print(json.dumps(audit(a.source_root, max_projected_rows=a.max_project_rows,
                           max_stockdays=a.max_stockdays),
                     ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
