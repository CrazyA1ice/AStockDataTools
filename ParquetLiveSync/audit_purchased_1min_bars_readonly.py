#!/usr/bin/env python3
"""Read-only audit of *purchased* 1min Parquet bars per stock and trading day.

Does not read H5, QMT private receipts, derived 240-minute monthly files, or
write any file. Counts 09:30 labels; it cannot certify whether auction trades
were already folded into a 09:31 bar by the original data vendor.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

DAY_MS = 86_400_000
MAX_ROWS = 150_000_000
FIELDS = ("ts", "symbol", "volume", "amount")
FORMAT = "astock_purchased_one_minute_bar_count_readonly_v1"


def _day(value):
    if not isinstance(value, date) or isinstance(value, datetime):
        value = date.fromisoformat(value)
    return value


def _month_matches(path, target):
    # A year-file is also permitted for legacy purchased partitions.
    allowed = {f"{target.year}-{target.month:02d}.parquet",
               f"{target.year}.parquet"}
    if path.name not in allowed:
        raise ValueError("PURCHASED_MONTH_FILE_NAME_NOT_IN_DAY_SCOPE")


def inspect(path, day, *, timezone_hours=8):
    target = _day(day)
    filename = Path(path)
    _month_matches(filename, target)
    if filename.is_symlink() or not filename.is_file():
        raise ValueError("PURCHASED_FILE_MISSING_OR_LINKED")
    if type(timezone_hours) is not int or not -12 <= timezone_hours <= 14:
        raise ValueError("TIMEZONE_OFFSET_INVALID")
    if filename.stat().st_size <= 0:
        raise ValueError("PURCHASED_FILE_EMPTY")
    src = pq.ParquetFile(filename)
    names = src.schema_arrow.names
    if any(name not in names for name in FIELDS):
        raise ValueError("PURCHASED_SCHEMA_REQUIRED_FIELDS_MISSING")
    if src.schema_arrow.field("ts").type != pa.int64():
        raise ValueError("PURCHASED_TIMESTAMP_NOT_INT64_MILLISECONDS")
    if not pa.types.is_string(src.schema_arrow.field("symbol").type):
        raise ValueError("PURCHASED_SYMBOL_NOT_UTF8")
    if src.metadata.num_rows > MAX_ROWS:
        raise ValueError("PURCHASED_FILE_ROW_SCAN_BUDGET")
    tz = timezone(timedelta(hours=timezone_hours))
    lo = int(datetime.combine(target, time.min, tzinfo=tz).timestamp() * 1000)
    hi = lo + DAY_MS
    minute0930 = 9 * 60 + 30
    minute0931 = minute0930 + 1
    counts = Counter()
    # A count of 241 must not silently arise from a duplicated timestamp.
    seen_timestamps = defaultdict(set)
    duplicate_symbol_timestamp_rows = 0
    first = {}
    last = {}
    at0930 = Counter()
    at0931 = Counter()
    at0930_positive_pair = 0
    at0930_zero_pair = 0
    at0930_unpaired = 0
    matches = 0
    for batch in src.iter_batches(batch_size=65536, columns=list(FIELDS),
                                  use_threads=False):
        stamp = batch.column(0)
        mask = pc.and_(pc.greater_equal(stamp, lo), pc.less(stamp, hi))
        selected = batch.filter(mask)
        if selected.num_rows == 0:
            continue
        rows = zip(*(selected.column(j).to_pylist() for j in range(4)))
        for ts, symbol, vol, amount in rows:
            if type(ts) is not int or type(symbol) is not str or not symbol:
                raise ValueError("PURCHASED_ROW_KEY_INVALID")
            # All per-day observations use the same explicitly selected
            # market timezone; do not infer exchange sessions from counts.
            mm = ((ts + timezone_hours * 3600000) % DAY_MS) // 60000
            counts[symbol] += 1
            if ts in seen_timestamps[symbol]:
                duplicate_symbol_timestamp_rows += 1
            seen_timestamps[symbol].add(ts)
            first[symbol] = min(ts, first.get(symbol, ts))
            last[symbol] = max(ts, last.get(symbol, ts))
            matches += 1
            if mm == minute0930:
                at0930[symbol] += 1
                if vol is None or amount is None:
                    at0930_unpaired += 1
                elif vol > 0 and amount > 0:
                    at0930_positive_pair += 1
                elif vol == 0 and amount == 0:
                    at0930_zero_pair += 1
                else:
                    at0930_unpaired += 1
            if mm == minute0931:
                at0931[symbol] += 1
    if matches == 0:
        raise ValueError("PURCHASED_DAY_NOT_OBSERVED_OR_TIMESTAMP_UNVERIFIED")
    histogram = Counter(counts.values())
    earliest = Counter(datetime.fromtimestamp(stamp/1000, tz=tz)
                       .strftime("%H:%M") for stamp in first.values())
    latest = Counter(datetime.fromtimestamp(stamp/1000, tz=tz)
                     .strftime("%H:%M") for stamp in last.values())
    return {
        "format": FORMAT,
        "trading_day": target.isoformat(),
        "source_kind": "PURCHASED_PARQUET_ONLY",
        "partition_name": filename.name,
        "timezone_hours": timezone_hours,
        "purchased_file_rows_metadata": src.metadata.num_rows,
        "matching_rows_for_day": matches,
        "duplicate_stock_timestamp_rows": duplicate_symbol_timestamp_rows,
        "all_symbol_timestamp_keys_unique": duplicate_symbol_timestamp_rows == 0,
        "stock_days_observed": len(counts),
        "per_stock_day_bar_count_histogram": dict(sorted(histogram.items())),
        "stock_days_240_bars": histogram.get(240, 0),
        "stock_days_241_bars": histogram.get(241, 0),
        "stock_days_other_bar_counts": sum(v for k,v in histogram.items()
                                         if k not in (240, 241)),
        "stocks_with_0930_label": len(at0930),
        "0930_rows_with_positive_volume_and_amount": at0930_positive_pair,
        "0930_rows_with_zero_volume_and_amount": at0930_zero_pair,
        "0930_rows_with_unknown_or_unpaired_volume_amount": at0930_unpaired,
        "stocks_with_0931_label": len(at0931),
        "earliest_label_local_histogram": dict(sorted(earliest.items())),
        "latest_label_local_histogram": dict(sorted(latest.items())),
        "exact_original_source_byte_sha_verified": False,
        "auction_trades_included_in_first_bar_certified": False,
        "auction_raw_bids_or_ticks_observed": False,
        "h5_or_qmt_cache_read": False,
        "purchased_parquet_modified": False,
        "market_files_written": False,
        "interpretation": (
            "240 bars can include auction trade turnover folded into a "
            "regular bar; 241 labels can include zero-turnover placeholders. "
            "Neither bar count nor the presence of a 09:30 label proves "
            "complete 09:15-09:25 auction order/tick data."
        ),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--day", type=date.fromisoformat, required=True)
    p.add_argument("--timezone-hours", type=int, default=8)
    args = p.parse_args(argv)
    try:
        print(json.dumps(inspect(args.file, args.day,
                                 timezone_hours=args.timezone_hours),
                         ensure_ascii=False, sort_keys=True,
                         indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, OverflowError,
            pa.ArrowException):
        print("PURCHASED_1MIN_BAR_COUNT_READONLY_REVIEW_REQUIRED")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
