#!/usr/bin/env python3
"""Explicit local research query: purchased minute Parquet first; verified private H5 gaps second.

This is a READ-ONLY, opt-in research interface, NOT a new physical market
database or a production source switch. Each stock-day is routed using an
existing purchased-only minute-key SQLite index; H5 can NEVER override a
purchased stock-day, including a purchased stock-day with partial keys.

A private H5 gap is readable only when its pre-existing stage/unified SAFE
receipts and physical Parquet SHA pass the original verifier. No original H5
market file is read, no purchased OHLCVA is copied, and no files are written.
CLI prints aggregate provenance/counts, never licensed price/volume values.
H5 minute vendor units are NOT certified for production or H5 mirroring.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX_NAME = re.compile(
    r"purchased-minute-keys-(\d{4}-\d\d-\d\d)-(\d{4}-\d\d-\d\d)-([0-9a-f]{12})\.sqlite\Z")
PERIODS = ("1min", "5min")
FIELDS = ("open", "high", "low", "close", "volume", "amount")


def _load(tag, filename):
    spec = importlib.util.spec_from_file_location(tag, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


Q = _load("purchased_primary_minute_source_query", "query-parquet-primary-readonly.py")
D = _load("purchased_primary_minute_indexed_diff", "preview-minute-exact-key-diff-readonly.py")
W = _load("purchased_primary_minute_existing_safe_verifier", "minute-private-parquet-worker.py")


def locate_index(day):
    """One and only one existing key index may cover a requested calendar day."""
    directory = D.I.STORE
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Private minute source-key index store is unavailable")
    matches = []
    for path in directory.glob("purchased-minute-keys-*.sqlite"):
        m = INDEX_NAME.fullmatch(path.name)
        if m is None:
            raise ValueError("Unexpected filename in purchased minute-key index store")
        if path.is_symlink() or not path.is_file():
            raise ValueError("Unsafe purchased minute-key index")
        first, last = date.fromisoformat(m[1]), date.fromisoformat(m[2])
        if first <= day <= last:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError("Missing or overlapping purchased minute-key index for " +
                         day.isoformat() + ": " + str(len(matches)))
    return matches[0]


def _safe_private_file(day, period):
    """Resolve an existing H5-private Parquet only from original verified receipts."""
    old = W.verified_existing_batch(day.isoformat())
    if old is None:
        return None
    receipt = Path(old["safe"])
    if (receipt.is_symlink() or not receipt.is_file()
            or receipt.resolve().parent != W.REPORTS.resolve()):
        raise ValueError("Untrusted existing minute SAFE location")
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    if (doc.get("source_day") != day.isoformat()
            or doc.get("original_purchased_parquet_or_hikyuu_h5_modified") is not False
            or doc.get("status") !=
            "purchased_first_1min_5min_physical_parquet_unified_readback_only"):
        raise ValueError("Untrusted existing minute SAFE provenance")
    entry = doc["periods"][period]
    if (entry.get("period") != period
            or entry.get("source_rows", {}).get("h5_only_complete_stockday", 0) <= 0
            or entry.get("full_merged_source_rows_and_vendor_extra_columns_readback_verified")
            is not True):
        return None
    relative = entry.get("unified_parquet_relative_file")
    if not isinstance(relative, str) or not re.fullmatch(
        r"work/unified_parquet/minute_complete_day/minute_[0-9a-f]{12}/"
        + period + "-" + re.escape(day.isoformat()) + r"\.parquet", relative
    ):
        raise ValueError("Untrusted private minute Parquet path")
    path = W.MODULE / relative
    if (path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(
                (W.MODULE / "work" / "unified_parquet").resolve())):
        raise ValueError("Unsafe or missing private minute Parquet")
    if W.sha(path) != entry.get("unified_parquet_sha256"):
        raise ValueError("Existing private minute Parquet SHA mismatch")
    return path, entry


def _read_verified_private_gap(day, period, symbol, *, max_result_bars):
    """Read H5-origin rows in memory from SHA-verified existing private Parquet."""
    selected = _safe_private_file(day, period)
    if selected is None:
        return []
    path, entry = selected
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    columns = ["ts", "symbol", "period", "value_source", "h5_native_datetime",
               *FIELDS]
    result = []
    with pq.ParquetFile(path, memory_map=False, pre_buffer=False) as pf:
        if not set(columns).issubset(pf.schema_arrow.names):
            raise ValueError("Private gap Parquet required schema absent")
        for batch in pf.iter_batches(batch_size=32768, columns=columns,
                                     use_threads=False):
            mask = pc.equal(batch.column(batch.schema.get_field_index("symbol")),
                            pa.scalar(symbol))
            for row in batch.filter(mask).to_pylist():
                if row["period"] != period or row["value_source"] != "h5_only_complete_stockday":
                    raise ValueError("Purchased/provenance row in H5-only fallback")
                stamp = row["ts"]
                native = row["h5_native_datetime"]
                if type(stamp) is not int or type(native) is not int:
                    raise ValueError("Invalid private minute timestamp type")
                try:
                    end = datetime.strptime(str(native), "%Y%m%d%H%M").replace(
                        tzinfo=Q.core.UTC8)
                except ValueError as exc:
                    raise ValueError("Invalid native H5 minute timestamp") from exc
                normalized = end - timedelta(minutes=0 if period == "1min" else 5)
                if (normalized.date() != day
                        or int(normalized.timestamp() * 1000) != stamp):
                    raise ValueError("Unverified H5 native-to-Parquet time mapping")
                values = [float(row[k]) for k in FIELDS]
                if (not all(math.isfinite(v) and v >= 0 for v in values)
                        or values[1] < max(values[0], values[3])
                        or values[2] > min(values[0], values[3])):
                    raise ValueError("Private H5 minute OHLCVA geometry invalid")
                result.append({
                    "symbol": symbol, "period": period,
                    "trading_date": day.isoformat(),
                    "source_timestamp_ms": stamp,
                    "source_beijing_time": normalized.strftime("%Y-%m-%d %H:%M"),
                    "value_source": "h5_only_complete_stockday",
                    "source_file_relative_path":
                        path.relative_to(W.MODULE).as_posix(),
                    "source_row_group": None,
                    "h5_native_datetime": native,
                    **dict(zip(FIELDS, values)),
                })
                if len(result) > max_result_bars:
                    raise ValueError("Requested private gap exceeds row budget")
    # Not stat_result equality: reading can change Windows atime.
    if W.sha(path) != entry["unified_parquet_sha256"]:
        raise ValueError("Existing private minute Parquet SHA changed during read")
    timestamps = [row["source_timestamp_ms"] for row in result]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("Duplicate private H5 fallback timestamp")
    expected = set(D.normalized_native_keys(day, period).values())
    if result:
        if not set(timestamps).issubset(expected):
            raise ValueError("Private H5 timestamps are outside the session grid")
        missing = len(expected - set(timestamps))
        if missing > (1 if period == "1min" else 0):
            raise ValueError("Private H5 stock-day is incomplete")
    return sorted(result, key=lambda row: row["source_timestamp_ms"])


def query_bars(root, symbol, period, first, last, *,
               allow_verified_private_h5=False,
               max_candidate_rows=30000000, max_result_bars=10000):
    """Return original OHLCVA locally with provenance and a nonprice SAFE summary.

    An indexed purchased stock-day always wins, even when its grid is partial.
    An absent purchased stock-day may use explicitly opted-in, SHA-verified
    private H5-only rows. Absent/unverified dates are reported, not invented.
    """
    if period not in PERIODS:
        raise ValueError("Only 1min and 5min are supported")
    if type(allow_verified_private_h5) is not bool:
        raise ValueError("Explicit H5 fallback flag must be boolean")
    canonical, start, stop = Q.request_dates(
        symbol, period, first, last, max_candidate_rows, max_result_bars)
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Original market root unavailable")
    all_bars = []
    by_day = {}
    tally = Counter()
    current = start
    while current <= stop:
        # Require a complete existing purchased-source index even on days
        # with zero bars; otherwise absence could be a false H5 gap.
        index = locate_index(current)
        purchased, _ = D.I.query_index(index, root, period, current)
        purchased_keys = purchased.get(canonical)
        if purchased_keys is not None:
            remaining = max_result_bars - len(all_bars)
            if remaining <= 0:
                raise ValueError("Total query bar budget exhausted")
            original = Q.query_bars(
                root, canonical, period, current.isoformat(),
                current.isoformat(), max_candidate_rows=max_candidate_rows,
                max_result_bars=remaining, local_cache=False)["bars"]
            keys = [x["source_timestamp_ms"] for x in original]
            if len(keys) != len(set(keys)) or set(keys) != purchased_keys:
                raise ValueError("Purchased query disagrees with indexed stock-day")
            bars = [{
                "symbol": row["symbol"], "period": row["period"],
                "trading_date": row["trading_date"],
                "source_timestamp_ms": row["source_timestamp_ms"],
                "source_beijing_time": row.get("source_beijing_time"),
                "value_source": "purchased_parquet",
                "source_file_relative_path": row.get("source_file_relative_path"),
                "source_row_group": row.get("source_row_group"),
                "h5_native_datetime": None,
                **{name: row[name] for name in FIELDS},
            } for row in original]
            kind = "purchased_parquet"
        elif allow_verified_private_h5:
            bars = _read_verified_private_gap(
                current, period, canonical,
                max_result_bars=max_result_bars-len(all_bars))
            kind = "verified_private_h5_gap" if bars else "no_verified_source"
        else:
            bars = []
            kind = "no_purchased_source_h5_not_enabled"
        if len(all_bars) + len(bars) > max_result_bars:
            raise ValueError("Total query bar budget exceeded")
        by_day[current.isoformat()] = {"source": kind, "bars": len(bars)}
        tally[kind] += len(bars)
        all_bars.extend(bars)
        current += timedelta(days=1)
    stamps = [(row["trading_date"], row["source_timestamp_ms"]) for row in all_bars]
    if len(stamps) != len(set(stamps)):
        raise ValueError("Duplicate merged minute keys")
    all_bars.sort(key=lambda row: row["source_timestamp_ms"])
    return {
        "bars": all_bars,
        "safe_summary": {
            "format": "AStockDataTools purchased-primary explicit minute research query v1",
            "period": period, "symbol": canonical,
            "from_day": start.isoformat(), "through_day": stop.isoformat(),
            "matching_bar_count": len(all_bars),
            "bars_by_source": dict(sorted(tally.items())),
            "dates": by_day,
            "purchased_parquet_is_authoritative_per_stockday": True,
            "h5_fallback_explicitly_enabled": allow_verified_private_h5,
            "h5_private_physical_SHA_checked": bool(tally["verified_private_h5_gap"]),
            "original_market_files_modified": False,
            "new_market_files_written": False,
            "production_query_activated": False,
            "h5_minute_vendor_physical_units_certified": False,
            "no_raw_ohlcva_in_safe_summary": True,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--period", required=True, choices=PERIODS)
    parser.add_argument("--from-day", required=True)
    parser.add_argument("--through-day", required=True)
    parser.add_argument("--allow-verified-private-h5", action="store_true")
    parser.add_argument("--max-result-bars", type=int, default=10000)
    args = parser.parse_args(argv)
    result = query_bars(
        args.root, args.symbol, args.period, args.from_day, args.through_day,
        allow_verified_private_h5=args.allow_verified_private_h5,
        max_result_bars=args.max_result_bars)
    # No licensed OHLCVA, file paths or market values are emitted.
    print(json.dumps(result["safe_summary"], indent=2, sort_keys=True,
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
