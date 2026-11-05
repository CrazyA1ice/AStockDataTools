#!/usr/bin/env python3
"""2025 vendor source-code transition research gate: 300114 -> 302132.

Original issuer's disclosure (2025-02-14, published on SZSE):
https://disc.static.szse.cn/download/disc/disk03/finalpage/2025-02-15/cedb693a-f5ee-4463-9682-ea33d406b569.PDF
Issuer declared official new code 302132 effective 2025-02-17.
The source data's historic code strings MAY have been backfilled by vendor.
This tool NEVER silently relabels old bars, activates code aliases, reads
OHLCVA, reads H5, or changes the already verified private minute indexes.

Bounded 2025 original 5min Parquet ts/symbol projection ONLY; calendar
statistics and exact public security codes, not prices, are printed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
YEAR = 2025
PERIOD = "5min"
EFFECTIVE = date(2025, 2, 17)
OLD = "SZ300114"
NEW = "SZ302132"
PREFIX = "SZ302"
MAX_SOURCE_ROWS = 70000000
MAX_TARGET_STOCKDAYS = 2000
SOURCE_NOTICE = ("https://disc.static.szse.cn/download/disc/disk03/finalpage/"
                 "2025-02-15/cedb693a-f5ee-4463-9682-ea33d406b569.PDF")


def load(tag, filename):
    spec = importlib.util.spec_from_file_location(tag, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOURCE = load("2025_original_source_prefix_classifier",
              "audit-purchased-2025-unselected-5min-code-prefixes-readonly.py")
CORE = SOURCE.CORE


def audit_rows(root, paths, *, max_source_rows=MAX_SOURCE_ROWS):
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    root = Path(root).resolve()
    base = root / "AllCycleAStockData" / PERIOD
    if (type(max_source_rows) is not int or not 1 <= max_source_rows <= MAX_SOURCE_ROWS
            or not isinstance(paths, list) or not 1 <= len(paths) <= 12):
        raise ValueError("Unsafe source scope/budget")
    raw_codes = defaultdict(set)
    masks = {}
    mask_cache = {}
    source_stat = {}
    scanned = 0
    for source in paths:
        if (source.is_symlink() or not source.is_file()
                or not source.resolve().is_relative_to(base.resolve())):
            raise ValueError("Unsafe original purchased Parquet path")
        st = source.stat()
        source_stat[source] = (st.st_size, st.st_mtime_ns)
        with pq.ParquetFile(source, memory_map=False, pre_buffer=False) as pf:
            ts_type = pf.schema_arrow.field("ts").type
            symbol_type = pf.schema_arrow.field("symbol").type
            if not pa.types.is_int64(ts_type):
                raise ValueError("Untrusted purchased source timestamp type")
            if pa.types.is_dictionary(symbol_type):
                symbol_type = symbol_type.value_type
            if not (pa.types.is_string(symbol_type) or
                    pa.types.is_large_string(symbol_type)):
                raise ValueError("Untrusted source symbol type")
            scanned += int(pf.metadata.num_rows)
            if scanned > max_source_rows:
                raise ValueError("Original source 5min row budget exceeded")
            for batch in pf.iter_batches(
                    columns=["ts", "symbol"], batch_size=65536,
                    use_threads=False):
                symbols = batch.column(1)
                if pa.types.is_dictionary(symbols.type):
                    symbols = pc.cast(symbols, symbol_type)
                selected_raw = [
                    s for s in pc.unique(symbols).to_pylist()
                    if isinstance(s, str) and (
                        (c := CORE.symbol_id(s)) is not None
                        and (c == OLD or c.startswith(PREFIX)))
                ]
                if not selected_raw:
                    continue
                mask = pc.is_in(symbols, value_set=pa.array(
                    selected_raw, type=symbol_type))
                for row in batch.filter(mask).to_pylist():
                    canonical = CORE.symbol_id(row["symbol"])
                    if canonical is None or not (
                            canonical == OLD or canonical.startswith(PREFIX)):
                        raise ValueError("Selected source key failed code normalization")
                    stamp = row["ts"]
                    if type(stamp) is not int or stamp % 60000:
                        raise ValueError("Invalid target source timestamp")
                    try:
                        dt = datetime.fromtimestamp(stamp / 1000, tz=CORE.UTC8)
                    except (OverflowError, OSError, ValueError) as error:
                        raise ValueError("Invalid target source date") from error
                    day = dt.date()
                    if day.year != YEAR:
                        raise ValueError("Source target code row outside requested year")
                    identity = canonical, day.isoformat()
                    if identity not in masks and len(masks) >= MAX_TARGET_STOCKDAYS:
                        raise ValueError("Target stockday memory budget exceeded")
                    origin = SOURCE.D.I.day_epoch_ms(day)
                    minute = (stamp - origin) // 60000
                    if not 0 <= minute < 1440:
                        raise ValueError("Invalid source minute")
                    bit = 1 << minute
                    if masks.get(identity, 0) & bit:
                        raise ValueError("Duplicate target code/date/5minute key")
                    masks[identity] = masks.get(identity, 0) | bit
                    raw_codes[canonical].add(row["symbol"])
    for source, old_stat in source_stat.items():
        st = source.stat()
        if old_stat != (st.st_size, st.st_mtime_ns):
            raise RuntimeError("Original source changed during transition audit")
    group = defaultdict(lambda: {
        "observed_stockdays": 0, "five_minute_source_rows": 0,
        "earliest_day": None, "latest_day": None,
        "before_official_effective_stockdays": 0,
        "after_or_on_official_effective_stockdays": 0,
        "nonstandard_48_key_stockdays": 0,
    })
    observed_days_by_code = defaultdict(set)
    for (code, ds), bits in sorted(masks.items()):
        day = date.fromisoformat(ds)
        expected = SOURCE._grid(day, mask_cache)
        n = bits.bit_count()
        bucket = group[code]
        bucket["observed_stockdays"] += 1
        bucket["five_minute_source_rows"] += n
        bucket["earliest_day"] = min(bucket["earliest_day"] or ds, ds)
        bucket["latest_day"] = max(bucket["latest_day"] or ds, ds)
        if day < EFFECTIVE:
            bucket["before_official_effective_stockdays"] += 1
        else:
            bucket["after_or_on_official_effective_stockdays"] += 1
        if bits != expected:
            bucket["nonstandard_48_key_stockdays"] += 1
        observed_days_by_code[code].add(ds)
    suspicious_new = group.get(NEW, {}).get(
        "before_official_effective_stockdays", 0)
    prefix_stockdays = sum(
        data["observed_stockdays"]
        for code, data in group.items() if code.startswith(PREFIX))
    prefix_rows = sum(
        data["five_minute_source_rows"]
        for code, data in group.items() if code.startswith(PREFIX))
    simultaneous = len(
        observed_days_by_code.get(OLD, set()) &
        observed_days_by_code.get(NEW, set()))
    result = {
        "scanned_2025_5min_source_rows": scanned,
        "target_security_code_evidence": dict(sorted(group.items())),
        "raw_symbol_spellings_per_canonical_code": {
            code: sorted(values) for code, values in sorted(raw_codes.items())
        },
        "sz302_prefix_actual_source_stockdays": prefix_stockdays,
        "sz302_prefix_actual_source_rows": prefix_rows,
        "src_302132_pre_effective_history_stockdays": suspicious_new,
        "old_new_same_date_stockdays": simultaneous,
        "historical_new_code_present_before_official_code_change":
            bool(suspicious_new),
        "official_code_change_day": EFFECTIVE.isoformat(),
        "issuer_code_change_old": OLD,
        "issuer_code_change_new": NEW,
        "issuer_official_notice_reference": SOURCE_NOTICE,
        "source_code_mapping_changes_are_diagnostic_only": True,
        "A_share_alias_auto_applied": False,
        "source_ohlcva_read": False,
        "h5_source_bars_read": False,
        "original_market_files_modified": False,
        "private_stockday_index_written": False,
        "production_query_activated": False,
    }
    return result


def inspect(root, *, max_source_rows=MAX_SOURCE_ROWS):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Unsafe original market root")
    # Revalidate known 2025 full-year Parquet source footers & previously
    # accepted purchased A-share time-key receipts, but avoid *re-running*
    # expensive full 5min code-prefix classifier on this targeted audit.
    ref = SOURCE.R.reconcile(root)
    before = SOURCE.R.B.A.I.N.source_snapshot(root, YEAR)
    files, _ = SOURCE.R.F.source_files(root, (PERIOD,), YEAR, YEAR)
    out = audit_rows(root, files[PERIOD][YEAR],
                     max_source_rows=max_source_rows)
    if out["scanned_2025_5min_source_rows"] != (
            ref["whole_source_footer_rows"][PERIOD]):
        raise ValueError("Source scanned rows do not match checked 2025 footer")
    if out["sz302_prefix_actual_source_rows"] != 11664:
        raise ValueError("Source SZ302 prefix row count changed from verified prior audit")
    if out["sz302_prefix_actual_source_stockdays"] != 243:
        raise ValueError("Source SZ302 source stockday count changed from prior audit")
    if any(x["nonstandard_48_key_stockdays"]
           for x in out["target_security_code_evidence"].values()):
        raise ValueError("Selected official code transition evidence has nonstandard 5min day")
    if SOURCE.R.B.A.I.N.source_snapshot(root, YEAR) != before:
        raise RuntimeError("Source changed during verified code-transition audit")
    return {
        "format": "AStockDataTools 2025 issuer documented A-share code-transition source audit v1",
        "status": "2025_300114_302132_source_label_timeline_audited_not_mapped",
        **out,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--max-source-rows", type=int, default=MAX_SOURCE_ROWS)
    args = ap.parse_args(argv)
    print(json.dumps(inspect(args.root,max_source_rows=args.max_source_rows),
                     indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
