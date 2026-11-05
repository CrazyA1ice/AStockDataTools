#!/usr/bin/env python3
"""Checkpointed, bounded 2025 purchased 1min/5min key-grid audit.

Only pre-existing source-key SQLite indexes are reused; with explicit opt-in,
missing monthly indexes contain ONLY timestamps+symbols membership bits.
Never materializes paid OHLCVA, reads H5 bars or activates a market pointer.
Each accepted month has an aggregate-only private JSON receipt; verified
receipts are reused, not rescanned. On source metadata drift, fail closed.
Calendar weekdays without purchased keys are not certified exchange gaps.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
WORK = MODULE / "work" / "purchased_2025_minute_grid_batch"
FORMAT = "AStockDataTools checkpointed 2025 purchased minute source grid v1"


def _load():
    spec = importlib.util.spec_from_file_location(
        "purchased_2025_batch_existing_source_grid",
        HERE / "audit-purchased-2025-minute-source-grid-readonly.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = _load()


def months(first, last):
    a, b = A._month(first)[0], A._month(last)[0]
    if a > b:
        raise ValueError("Month range is reversed")
    dates = []
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        dates.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return dates


def _file(month):
    return WORK / ("verified-purchased-source-grid-" + month + ".json")


def _check_report(obj, month, fingerprint):
    if (not isinstance(obj, dict)
            or obj.get("format") != FORMAT
            or obj.get("status") != "verified_purchased_source_stockday_grids_not_exchange_calendar"
            or obj.get("month") != month
            or obj.get("source_metadata_fingerprint") != fingerprint):
        raise ValueError("Private month receipt is stale, changed or unsupported: " + month)
    a = obj.get("audit")
    if (not isinstance(a, dict) or a.get("month") != month
            or a.get("status") !=
            "read_only_purchased_minute_key_grid_audited_not_market_certified"
            or a.get("complete_time_grid_for_every_observed_stockday") is not True
            or a.get("same_stock_symbols_in_both_periods_on_each_date") is not True
            or a.get("weekend_dates_with_purchased_source_evidence") != []
            or a.get("h5_source_row_data_opened") is not False
            or a.get("original_purchased_parquet_ohlcva_opened") is not False
            or a.get("new_market_parquet_or_h5_files_written") is not False
            or a.get("purchased_market_bars_copied") != 0
            or a.get("production_query_activated") is not False
            or a.get("source_metadata_stable_during_audit") is not True
            or a.get("full_exchange_calendar_coverage_certified") is not False
            or a.get("ohlcva_vendor_unit_certified") is not False
            or set(a.get("periods", {})) != {"1min", "5min"}):
        raise ValueError("Unverified, incomplete or unsafe 2025 minute grid receipt: " + month)
    if (not isinstance(a.get("index_windows"), list)
            or not a["index_windows"]
            or not all(isinstance(w, dict) and "from_day" in w
                       and "through_day" in w for w in a["index_windows"])):
        raise ValueError("Receipt lacks verified month index windows: " + month)
    for period, expected in (("1min", 241), ("5min", 48)):
        p = a["periods"][period]
        n, keys = p.get("stockdays"), p.get("keys")
        if (type(n) is not int or n < 0 or type(keys) is not int
                or keys != expected * n
                or p.get("nonstandard_stockdays", 0) != 0
                or p.get("missing_expected_keys", 0) != 0
                or p.get("extra_unexpected_keys", 0) != 0):
            raise ValueError("Receipt stockday/key conservation mismatch: " + month)
    return a


def verified_receipt(month, root, fingerprint):
    path = _file(month)
    if path.is_symlink():
        raise ValueError("Unsafe monthly receipt symlink: " + month)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 200000:
        raise ValueError("Invalid private monthly receipt: " + month)
    data = json.loads(path.read_text(encoding="utf-8"))
    audit = _check_report(data, month, fingerprint)
    # Reconcile the exact old index windows with CURRENT inventory. Source
    # drift is rejected by index source signature, not silently accepted.
    first, last = A._month(month)
    actual = A.G.plan(root, str(first), str(last), allow_build=False, mode="minute")
    if [(v["first"], v["last"]) for v in actual] != [
            (v["from_day"], v["through_day"]) for v in audit["index_windows"]]:
        raise ValueError("Index windows differ from accepted month receipt: " + month)
    if any(v["mode"] != "reuse_existing_index" for v in actual):
        raise ValueError("Missing previously verified key index: " + month)
    for window in actual:
        path = Path(window["existing_index"])
        for period in ("1min", "5min"):
            A.I.query_index(path, root, period, window["first"])
            A.I.query_index(path, root, period, window["last"])
    return audit


def save_receipt(month, fingerprint, audit):
    if WORK.is_symlink() or WORK.parent.is_symlink():
        raise ValueError("Unsafe local private checkpoint directory")
    WORK.mkdir(parents=True, exist_ok=True)
    path = _file(month)
    partial = path.with_suffix(".json.partial")
    if path.exists() or path.is_symlink() or partial.exists() or partial.is_symlink():
        raise ValueError("Private month checkpoint exists or is incomplete: " + month)
    record = {
        "format": FORMAT,
        "status": "verified_purchased_source_stockday_grids_not_exchange_calendar",
        "month": month,
        "source_metadata_fingerprint": fingerprint,
        "audit": audit,
    }
    _check_report(record, month, fingerprint)
    with partial.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(partial, path)


def run(root, first="2025-01", last="2025-12", *,
        max_new_index_months=2, allow_build=False):
    root = Path(root)
    labels = months(first, last)
    if (root.is_symlink() or not root.is_dir()
            or type(max_new_index_months) is not int
            or not 0 <= max_new_index_months <= 12
            or type(allow_build) is not bool):
        raise ValueError("Invalid batch root, flags or monthly index budget")
    fingerprint = A.I.N.source_snapshot(root, 2025)
    made = 0
    results = {}
    pending = []
    for month in labels:
        saved = verified_receipt(month, root, fingerprint)
        if saved is not None:
            results[month] = saved
            print("REUSE_VERIFIED_MONTH", month, "1MIN_STOCKDAYS",
                  saved["periods"]["1min"]["stockdays"], flush=True)
            continue
        a, b = A._month(month)
        plan = A.G.plan(root, str(a), str(b), allow_build=True, mode="minute")
        required = sum(w["mode"] == "build_missing_private_index" for w in plan)
        if required and (not allow_build or made + required > max_new_index_months):
            pending.append(month)
            print("PENDING_NEW_PRIVATE_INDEX", month, "SHARDS", required,
                  "NO_MARKET_WRITES", True, flush=True)
            continue
        audit = A.inspect(root, month, allow_build=allow_build)
        if (not audit["complete_time_grid_for_every_observed_stockday"]
                or not audit["same_stock_symbols_in_both_periods_on_each_date"]
                or audit["weekend_dates_with_purchased_source_evidence"]):
            print("STOP_MONTH_GRID_EXCEPTIONS", month,
                  "PERIODS", json.dumps(audit["periods"], sort_keys=True),
                  "CROSS_PERIOD", json.dumps(audit["cross_period"], sort_keys=True),
                  flush=True)
            raise ValueError("2025 purchased source-grid exception: " + month +
                             "; no private accepted receipt published")
        if A.I.N.source_snapshot(root, 2025) != fingerprint:
            raise RuntimeError("Source metadata changed during 2025 monthly batch")
        save_receipt(month, fingerprint, audit)
        results[month] = audit
        made += audit["private_indexes_created"]
        print("VERIFIED_MONTH", month, "NEW_INDEX", audit["private_indexes_created"],
              "REUSED_INDEX", audit["existing_indexes_reused"],
              "1MIN_STOCKDAYS", audit["periods"]["1min"].get("stockdays", 0),
              "1MIN_KEYS", audit["periods"]["1min"].get("keys", 0),
              "5MIN_STOCKDAYS", audit["periods"]["5min"].get("stockdays", 0),
              "5MIN_KEYS", audit["periods"]["5min"].get("keys", 0),
              "NO_PURCHASED_SOURCE_WEEKDAYS",
              ",".join(audit["weekday_dates_without_purchased_source_evidence"]),
              flush=True)
    if A.I.N.source_snapshot(root, 2025) != fingerprint:
        raise RuntimeError("2025 input sources changed before batch conclusion")
    totals = {
        period: {
            "stockdays": sum(obj["periods"][period]["stockdays"]
                             for obj in results.values()),
            "keys": sum(obj["periods"][period]["keys"]
                        for obj in results.values()),
        }
        for period in ("1min", "5min")
    }
    result = {
        "status": "complete_private_key_grid_receipts_not_exchange_calendar"
        if len(results) == len(labels) else
        "partial_verified_resume_with_same_command",
        "from_month": first, "through_month": last,
        "verified_months": sorted(results),
        "pending_months": [x for x in labels if x not in results],
        "private_indexes_created_this_run": made,
        "source_only_stockday_totals": totals,
        "original_market_modified": False,
        "h5_ohlcva_read": False,
        "purchased_ohlcva_read_or_copied": False,
        "production_activated": False,
        "exchange_calendar_certified": False,
    }
    print("BATCH_RESULT", json.dumps(result, sort_keys=True, ensure_ascii=False),
          flush=True)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--from-month", default="2025-01")
    p.add_argument("--through-month", default="2025-12")
    p.add_argument("--max-new-index-months", type=int, default=2)
    p.add_argument("--build-missing-private-index", action="store_true")
    args = p.parse_args(argv)
    run(args.root, args.from_month, args.through_month,
        max_new_index_months=args.max_new_index_months,
        allow_build=args.build_missing_private_index)


if __name__ == "__main__":
    main()
