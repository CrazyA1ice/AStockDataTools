#!/usr/bin/env python3
"""Bounded 2025 purchased 1min/5min source-key-only monthly audit.

Uses existing source-key SQLite bitmaps, builds missing *private key indexes*
only with an explicit flag, and checks all observed stock-day session grids
and cross-period symbol sets. No H5 minute bars, OHLCVA or full-market copies.
No hard-coded exchange calendar: a weekday without purchased evidence is
NOT asserted a trading day. New indexes do not activate query pointers.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PERIODS = ("1min", "5min")


def _load(tag, name):
    spec = importlib.util.spec_from_file_location(tag, HERE / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load("purchased_2025_minute_window_planner", "minute-gap-audit-gui-worker.py")
D = _load("purchased_2025_source_grid", "preview-minute-exact-key-diff-readonly.py")
I = G.I


def _month(label):
    if type(label) is not str or len(label) != 7 or label[4] != "-":
        raise ValueError("Expected a single YYYY-MM month")
    y, m = (int(p) for p in label.split("-"))
    if y != 2025 or not 1 <= m <= 12:
        raise ValueError("Only bounded purchased 2025 month audit permitted")
    first = date(y, m, 1)
    last = (date(y + (m == 12), (m % 12) + 1, 1) -
            timedelta(days=1))
    return first, last


def _mask(keys, day):
    origin = I.day_epoch_ms(day)
    result = bytearray(I.BYTES_PER_DAY)
    for key in keys:
        if type(key) is not int or (key - origin) % 60000:
            raise ValueError("Invalid expected minute key")
        minute = (key - origin) // 60000
        if not 0 <= minute < 1440:
            raise ValueError("Expected minute key outside local calendar day")
        result[minute // 8] |= 1 << (minute % 8)
    return bytes(result)


def _reference(day, period):
    keys = set(D.normalized_native_keys(day, period).values())
    if period == "1min":
        keys.add(I.day_epoch_ms(day) + 570 * 60000)
    if len(keys) != (241 if period == "1min" else 48):
        raise ValueError("Unexpected purchased minute session reference length")
    return _mask(keys, day)


def inspect(root, month, *, allow_build=False):
    root = Path(root)
    first, last = _month(month)
    if type(allow_build) is not bool:
        raise ValueError("Explicit allow_build must be boolean")
    # Existing source-key windows have priority, including partial months.
    # Overlapping indexes fail in the existing GUI planner.
    plan = G.plan(root, str(first), str(last),
                  allow_build=allow_build, mode="minute")
    per_period = {p: Counter() for p in PERIODS}
    no_source_weekdays = set()
    detected_weekends = set()
    errors = Counter()
    days_source_sets = defaultdict(dict)
    built = 0
    reused = 0
    snapshot = I.N.source_snapshot(root, 2025)
    windows = []
    for window in plan:
        if window["existing_index"] is not None:
            index = Path(window["existing_index"])
            reused += 1
        else:
            if not allow_build:
                raise ValueError("Missing source-key index; explicit index build required")
            made = G.E.ensure(root, window["first"], window["last"])
            if made.get("new_private_index_created") is not True:
                raise ValueError("Index creation unexpectedly reused a source")
            index = Path(made["index_path"])
            built += 1
        if not index.is_file() or index.is_symlink():
            raise ValueError("Unsafe purchased minute-key index")
        # Both endpoints/periods validated using the existing source-signature
        # gate before directly examining compact 180-byte stockday masks.
        for period in PERIODS:
            for bound in (window["first"], window["last"]):
                I.query_index(index, root, period, bound)
        a = date.fromisoformat(window["first"])
        z = date.fromisoformat(window["last"])
        ref = {
            (d.isoformat(), p): _reference(d, p)
            for d in (a + timedelta(days=n)
                      for n in range((z - a).days + 1))
            for p in PERIODS
        }
        observed = defaultdict(set)
        with closing(sqlite3.connect(
                index.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            for period, day, symbol, raw in db.execute(
                "SELECT period,day,symbol,mask FROM stockday "
                "WHERE day>=? AND day<=? ORDER BY day,period,symbol",
                (window["first"], window["last"])):
                if period not in PERIODS or (day, period) not in ref:
                    raise ValueError("Unexpected index stockday period or date")
                if not isinstance(raw, bytes) or len(raw) != I.BYTES_PER_DAY:
                    raise ValueError("Malformed purchased minute-key mask")
                if symbol in observed[(day, period)]:
                    raise ValueError("Duplicate purchased stockday")
                observed[(day, period)].add(symbol)
                tally = per_period[period]
                tally["stockdays"] += 1
                bits = int.from_bytes(raw, "little")
                tally["keys"] += bits.bit_count()
                expected = int.from_bytes(ref[(day, period)], "little")
                if bits != expected:
                    tally["nonstandard_stockdays"] += 1
                    tally["missing_expected_keys"] += (expected & ~bits).bit_count()
                    tally["extra_unexpected_keys"] += (bits & ~expected).bit_count()
        for (day, period), symbols in observed.items():
            days_source_sets[day][period] = symbols
        for d in (a + timedelta(days=n) for n in range((z - a).days + 1)):
            key = d.isoformat()
            one = observed.get((key, "1min"), set())
            five = observed.get((key, "5min"), set())
            if one != five:
                errors["day_with_different_1min_5min_security_sets"] += 1
                errors["mismatched_securities_in_sets"] += len(one ^ five)
            if d.weekday() >= 5 and (one or five):
                detected_weekends.add(key)
            if d.weekday() < 5 and not (one or five):
                no_source_weekdays.add(key)
        windows.append({
            "from_day": window["first"], "through_day": window["last"],
            "source": window["mode"],
        })
    if I.N.source_snapshot(root, 2025) != snapshot:
        raise RuntimeError("Original source metadata changed during source-grid audit")
    for period in PERIODS:
        errors["nonstandard_" + period + "_stockdays"] = int(
            per_period[period]["nonstandard_stockdays"])
    return {
        "format": "AStockDataTools 2025 purchased minute exact stockday grid audit v1",
        "month": month,
        "status": "read_only_purchased_minute_key_grid_audited_not_market_certified",
        "index_windows": windows,
        "private_indexes_created": built,
        "existing_indexes_reused": reused,
        "periods": {p: dict(per_period[p]) for p in PERIODS},
        "cross_period": dict(errors),
        "weekday_dates_without_purchased_source_evidence":
            sorted(no_source_weekdays),
        "weekend_dates_with_purchased_source_evidence":
            sorted(detected_weekends),
        "independent_exchange_calendar_checked": False,
        "h5_source_row_data_opened": False,
        "original_purchased_parquet_ohlcva_opened": False,
        "purchased_market_bars_copied": 0,
        "new_market_parquet_or_h5_files_written": False,
        "production_query_activated": False,
        "source_metadata_stable_during_audit": True,
        "complete_time_grid_for_every_observed_stockday":
            all(per_period[p]["nonstandard_stockdays"] == 0 for p in PERIODS),
        "same_stock_symbols_in_both_periods_on_each_date":
            errors["day_with_different_1min_5min_security_sets"] == 0,
        "full_exchange_calendar_coverage_certified": False,
        "ohlcva_vendor_unit_certified": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--month", required=True)
    ap.add_argument("--build-missing-private-index", action="store_true")
    args = ap.parse_args(argv)
    summary = inspect(
        args.root, args.month,
        allow_build=args.build_missing_private_index)
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    if (not summary["complete_time_grid_for_every_observed_stockday"]
            or not summary["same_stock_symbols_in_both_periods_on_each_date"]
            or summary["weekend_dates_with_purchased_source_evidence"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
