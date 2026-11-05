#!/usr/bin/env python3
"""Key-first, bounded purchased 2025 SZ302132 original 1m/5m bar reader.

Do not weaken the baseline Parquet query's RowGroup budget. Original 2025
Parquet files can have overbroad year-long RowGroup timestamp envelopes.
First stream only ts/symbol, map exact matching (file, RowGroup, epoch-ms)
keys, then allow OHLCVA decoding ONLY from matching RowGroups if their
combined physical row count fits a separate hard 2.25-million-row ceiling.
The new narrow ceiling is evidence-driven: the 2025-02-17 5m source's
exactly matched RowGroup contains 2,088,988 physical rows. This is NOT
a relaxation of the generic Parquet query or a permitted year-wide read.

Source key-only scanning may touch a full purchased 2025 year of symbol/ts
columns. Its distinct budget is capped at 350 million (1m source 321.7m,
5m source 64.1m). None of the resulting data is cached or written to disk.
This is an opt-in research-only pilot for 2025 SZ302132; does not change
the generic source query, A-share classifier, purchased key indexes or H5.
"""
from __future__ import annotations

import importlib.util
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PERIODS = ("1min", "5min")
SOURCE = "SZ302132"
YEAR = 2025
FIELDS = ("open", "high", "low", "close", "volume", "amount")
MAX_KEY_ONLY_ROWS = 350000000
MAX_OHLCVA_ROWS = 2250000
MAX_FILES = 12
MAX_ROW_GROUPS = 5000


def _load(tag, file):
    spec = importlib.util.spec_from_file_location(tag, HERE / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


Q = _load("302132_baseline_purchased_query_contract",
          "query-parquet-primary-readonly.py")
GRID = _load("302132_purchased_native_session_grid_for_preflight",
             "preview-minute-exact-key-diff-readonly.py")


def _expected_keys(day, period):
    keys = set(GRID.normalized_native_keys(day, period).values())
    if period == "1min":
        keys.add(GRID.I.day_epoch_ms(day) + 570 * 60000)
    if len(keys) != (241 if period == "1min" else 48):
        raise ValueError("Untrusted session grid reference")
    return keys


def query_bars(root, symbol, period, first, last, *,
               max_candidate_rows=30000000, max_result_bars=10000,
               max_key_only_rows=MAX_KEY_ONLY_ROWS,
               max_ohlcva_rows=MAX_OHLCVA_ROWS):
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    if (symbol != SOURCE or period not in PERIODS
            or type(max_key_only_rows) is not int
            or not 1 <= max_key_only_rows <= MAX_KEY_ONLY_ROWS
            or type(max_ohlcva_rows) is not int
            or not 1 <= max_ohlcva_rows <= MAX_OHLCVA_ROWS):
        raise ValueError("Bounded research key-first reader only allows 2025 SZ302132 1m/5m")
    symbol, start, end = Q.request_dates(
        symbol, period, first, last, max_candidate_rows, max_result_bars,
        allow_2025_302132_source=True)
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Unsafe purchased market source root")
    root = root.resolve()
    period_root = root / "AllCycleAStockData" / period
    if (period_root.is_symlink() or not period_root.is_dir()
            or (root / "AllCycleAStockData").is_symlink()):
        raise ValueError("Unsafe purchased cycle source folder")
    paths = Q.core.year_files(root, period, YEAR)
    if not 1 <= len(paths) <= MAX_FILES:
        raise ValueError("Purchased year file-count budget exceeded or no files")
    aliases = sorted(Q.diagnose.source_spellings(symbol))
    low, high = Q.day_bounds(start, end)
    file_before = {}
    group_reads = []
    key_only_rows = 0
    source_rg_examined = 0
    source_footers = 0
    target_keys = {}
    selected = 0
    candidate_full_rowgroup_rows = 0
    # Preflight all physical source sizes BEFORE opening any key column.
    total_footer_rows = 0
    total_rowgroups = 0
    for path in paths:
        if (path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(period_root.resolve())):
            raise ValueError("Unsafe purchased period file path")
        st = path.stat()
        file_before[path] = (st.st_size, st.st_mtime_ns)
        with pq.ParquetFile(path, memory_map=False, pre_buffer=False) as pf:
            if not set(("ts", "symbol", *FIELDS)).issubset(pf.schema_arrow.names):
                raise ValueError("Required source metadata columns missing")
            if not pa.types.is_int64(pf.schema_arrow.field("ts").type):
                raise ValueError("Expected source ts int64 ms")
            sym_type = pf.schema_arrow.field("symbol").type
            if pa.types.is_dictionary(sym_type):
                sym_type = sym_type.value_type
            if not (pa.types.is_string(sym_type) or
                    pa.types.is_large_string(sym_type)):
                raise ValueError("Expected purchased symbol string")
            total_footer_rows += pf.metadata.num_rows
            total_rowgroups += pf.metadata.num_row_groups
            if (total_footer_rows > max_key_only_rows
                    or total_rowgroups > MAX_ROW_GROUPS):
                raise ValueError("Purchased source key-only metadata budget exceeded")
    # Discover exact target (RowGroup, source timestamp) from ts/symbol ONLY.
    for path in paths:
        with pq.ParquetFile(path, memory_map=False, pre_buffer=False) as pf:
            source_footers += 1
            for rg_id in range(pf.metadata.num_row_groups):
                source_rg_examined += 1
                rg = pf.metadata.row_group(rg_id)
                if not Q.core.row_group_overlaps_timestamp(rg, low, high):
                    continue
                if not Q.diagnose.might_contain_symbols(rg, set(aliases)):
                    continue
                source_keys_here = set()
                for batch in pf.iter_batches(row_groups=[rg_id],
                        columns=["ts", "symbol"], batch_size=65536,
                        use_threads=False):
                    key_only_rows += batch.num_rows
                    if key_only_rows > max_key_only_rows:
                        raise ValueError("Purchased source key-only scan budget exceeded")
                    names = batch.column(1)
                    if pa.types.is_dictionary(names.type):
                        names = pc.cast(names, pa.string())
                    if batch.column(0).null_count:
                        raise ValueError("Original purchased timestamps contain nulls")
                    accepted = pc.and_(
                        pc.is_in(names, value_set=pa.array(
                            aliases, type=pa.string())),
                        pc.and_(pc.greater_equal(batch.column(0),low),
                                pc.less(batch.column(0),high)))
                    # ts/symbol ONLY; filtering to a bounded number of
                    # matching keys happens BEFORE any Python list creation.
                    hits = pc.filter(batch.column(0), accepted).to_pylist()
                    for ts in hits:
                        if type(ts) is not int or ts % 60000:
                            raise ValueError("Unaligned original target minute timestamp")
                        if ts in target_keys or ts in source_keys_here:
                            raise ValueError("Duplicate original target timestamp across source groups")
                        if selected >= max_result_bars:
                            raise ValueError("Selected target source key count exceeds query bar budget")
                        source_keys_here.add(ts)
                        selected += 1
                if source_keys_here:
                    candidate_full_rowgroup_rows += rg.num_rows
                    for ts in source_keys_here:
                        target_keys[ts] = (path, rg_id)
                    group_reads.append((path, rg_id))
    # Fail before OHLCVA on a missing/extra target minute. In particular a
    # large physical RG cannot be used to read bad/incomplete target days.
    observed_days = defaultdict(set)
    for ts in target_keys:
        day = datetime.fromtimestamp(ts / 1000, tz=Q.core.UTC8).date()
        observed_days[day].add(ts)
    for day, observed in observed_days.items():
        if observed != _expected_keys(day, period):
            raise ValueError(
                "Observed 2025 SZ302132 source stockday has nonstandard time keys "
                "before OHLCVA decoding")
    if candidate_full_rowgroup_rows > min(
            max_ohlcva_rows, max_candidate_rows):
        raise ValueError(
            "Exact target keys found, but OHLCVA rowgroup budget "
            f"would require {candidate_full_rowgroup_rows:,} physical rows; "
            "no paid OHLCVA columns opened")
    # Before exposing OHLCVA, check the scanned source files remained stable.
    for path, st in file_before.items():
        now = path.stat()
        if st != (now.st_size, now.st_mtime_ns):
            raise ValueError("Original purchased source metadata changed during key discovery")
    # Read paid columns ONLY from row groups with exact target symbols/keys,
    # never from all candidate rowgroups with generic footer overlap.
    values = {}
    rowgroups_opened = 0
    source_rows_ohlcva_read = 0
    src_type = pa.array(aliases, type=pa.string())
    for path, rg_id in group_reads:
        with pq.ParquetFile(path, memory_map=False, pre_buffer=False) as pf:
            rowgroups_opened += 1
            source_rows_ohlcva_read += pf.metadata.row_group(rg_id).num_rows
            for batch in pf.iter_batches(
                    row_groups=[rg_id], columns=list(Q.NEEDED),
                    batch_size=65536, use_threads=False):
                names = batch.column(1)
                if pa.types.is_dictionary(names.type):
                    names = pc.cast(names, pa.string())
                allowed = pc.and_(
                    pc.is_in(names, value_set=src_type),
                    pc.and_(pc.greater_equal(batch.column(0),low),
                            pc.less(batch.column(0),high)))
                for item in batch.filter(allowed).to_pylist():
                    if Q.core.symbol_id(item["symbol"]) != SOURCE:
                        continue
                    ts = item["ts"]
                    if ts not in target_keys or target_keys[ts] != (path,rg_id):
                        raise ValueError("OHLCVA source no longer agrees with selected key/rowgroup")
                    if ts in values:
                        raise ValueError("Duplicate selected original OHLCVA key")
                    raw = datetime.fromtimestamp(ts/1000,tz=Q.core.UTC8)
                    if not start <= raw.date() <= end:
                        raise ValueError("Source date outside selected original window")
                    o,h,l,c,v,a = (float(item[x]) for x in FIELDS)
                    if (not all(math.isfinite(x) for x in (o,h,l,c,v,a))
                            or h < max(o,l,c)-1e-7
                            or l > min(o,h,c)+1e-7 or v < 0 or a < 0):
                        raise ValueError("Invalid original purchased OHLCVA geometry")
                    values[ts] = (o,h,l,c,v,a)
    if set(values) != set(target_keys):
        raise ValueError("OHLCVA decoded keys differ from full original key-only probe")
    for path, st in file_before.items():
        now = path.stat()
        if st != (now.st_size, now.st_mtime_ns):
            raise ValueError("Original purchased source changed during OHLCVA reading")
    bars = []
    for ts in sorted(values):
        dt = datetime.fromtimestamp(ts / 1000,tz=Q.core.UTC8)
        path, rg_id = target_keys[ts]
        bars.append({
            "symbol": SOURCE, "period": period,
            "trading_date": dt.date().isoformat(),
            "source_timestamp_ms": ts,
            "source_beijing_time": dt.strftime("%Y-%m-%d %H:%M"),
            "normalized_query_label": dt.strftime("%Y-%m-%d %H:%M"),
            "source_file_relative_path": path.relative_to(root).as_posix(),
            "source_row_group": rg_id,
            **dict(zip(FIELDS, values[ts])),
        })
    return {
        "bars": bars,
        "safe_summary": {
            "format": "AStockDataTools exact-302132 key-first purchased research query v1",
            "symbol": SOURCE, "period": period,
            "from_day": start.isoformat(), "through_day": end.isoformat(),
            "matching_bar_count": len(bars),
            "key_only_source_rows_scanned": key_only_rows,
            "purchased_rowgroups_examined": source_rg_examined,
            "purchased_file_footers_examined": source_footers,
            "physical_ohlcva_rowgroups_read": rowgroups_opened,
            "physical_ohlcva_source_rows_read": source_rows_ohlcva_read,
            "physical_ohlcva_rows_budget": min(max_ohlcva_rows, max_candidate_rows),
            "keys_equal_between_key_probe_and_ohlcva": True,
            "native_session_grid_checked_before_ohlcva": True,
            "physical_ohlcva_exception_scope":
                "2025_SZ302132_only_exact_matching_rowgroups",
            "generic_purchased_query_budget_unchanged": True,
            "source_stat_checked_before_and_after": True,
            "source_original_preserved": True,
            "H5_used": False,
            "licensed_bar_cache_written": False,
            "production_query_activated": False,
            "no_ohlcva_values_in_safe_summary": True,
        },
    }
