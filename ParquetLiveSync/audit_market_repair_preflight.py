#!/usr/bin/env python3
"""2026-11-18 two-stock repair readiness: immutable source/target inspection.

No stock can be auto-repaired from a DAY high/low alone. Prints a bounded
read-only inventory that can later be used to design a CAS-controlled
multi-file repair, only after independent 1m evidence is SHA-pinned.
"""
from __future__ import annotations

from datetime import date, datetime, time
import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

import local_layout as L
import market_month_storage as S
import market_derived_cycles as D
import audit_market_history_readonly as A
import update_market as U


DAY = date(2026, 11, 18)
SYMBOLS = ("SH688129", "SZ300472")


def vendor_symbols(symbol):
    code = symbol[2:]
    market = symbol[:2]
    return [symbol, code + "." + market,
            code + "." + {"SH": "XSHG", "SZ": "XSHE"}[market]]


def inspect(root, project, day=DAY):
    if day != DAY:
        raise ValueError("This repair preflight is pinned to 2026-11-18")
    project = Path(project).resolve()
    root = Path(root)
    work = project / "ParquetLiveSync" / "work"
    workspace = work / "market_update"
    refs, _ = A.official_reference(project, day, day)
    minute_state = S.state_for(root, workspace=workspace)
    derived_state = D._ledger(root, workspace)
    receipt_file = workspace / "daily" / "2026-11-18.json"
    original_source = workspace / "daily" / "2026-11-18.parquet"
    receipt = S._json(receipt_file)
    if (receipt.get("format") != U.FORMAT
            or receipt.get("date") != str(day)
            or original_source.is_symlink() or not original_source.is_file()
            or receipt.get("sha256") != L.hash_file(original_source)):
        raise ValueError("Original QMT daily candidate identity changed")
    start = int(datetime.combine(day, time.min, tzinfo=L.UTC8).timestamp() * 1000)
    end = start + 86400000
    records = {}
    inspected_files = {}
    for period in A.PERIODS:
        path, sha = A.check_month_identity(
            root, project, period, "2026-11", minute_state, derived_state)
        inspected_files[period] = {"path": str(path), "sha256": sha}
        for symbol in SYMBOLS:
            table = pq.read_table(
                path, columns=list(L.COLS),
                filters=[("symbol", "in", vendor_symbols(symbol)),
                         ("ts", ">=", start), ("ts", "<", end)])
            rows = sorted(table.to_pylist(), key=lambda r: r["ts"])
            if any(L.normal_symbol(r["symbol"]) != symbol for r in rows):
                raise ValueError("Physical stock selector identity mismatch")
            ref = refs.get((A.day_number(day), symbol))
            if ref is None:
                raise ValueError("Missing independent official DAY " + symbol)
            fullhigh = max((float(r["high"]) for r in rows), default=None)
            fulllow = min((float(r["low"]) for r in rows), default=None)
            overflow = (fullhigh is not None
                        and (fullhigh > ref["high"] + A.PRICE_EPS
                             or fulllow < ref["low"] - A.PRICE_EPS))
            bucket = {
                "physical_rows": len(rows),
                "expected_rows": A.EXPECTED_ROWS[period],
                "physical_high": fullhigh,
                "physical_low": fulllow,
                "official_day_high": ref["high"],
                "official_day_low": ref["low"],
                "outside_official_day_envelope": bool(overflow),
                "status": ("MISSING" if not rows
                           else "PHYSICAL_PRICE_OUTSIDE_OFFICIAL_DAY" if overflow
                           else "PRESENT_UNMODIFIED"),
            }
            records.setdefault(symbol, {})[period] = bucket
        if L.hash_file(path) != sha:
            raise ValueError("Physical source modified during preflight " + str(path))
    return {
        "format": "market_two_stock_repair_readiness_readonly_v1",
        "date": day.isoformat(),
        "stocks": records,
        "original_daily_candidate_sha256": receipt["sha256"],
        "original_quarantine": {s: receipt.get("quarantined", {}).get(s)
                                for s in SYMBOLS},
        "source_months_sha_verified": inspected_files,
        "required_before_any_apply": [
            "independent minute source for any corrected 1min price",
            "sealed source SHA and exact changed key-value manifest",
            "single writer lock, all-five-period backups and compare-and-swap",
            "crash-safe recovery and all-five-period ledger reconciliation",
            "no overwrite of unrelated stock-days or official DAY history",
        ],
        "production_repair_authorized": False,
        "production_market_modified": False,
        "scheduled_task_modified": False,
        "qmt_download_called": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--day", type=date.fromisoformat, default=DAY)
    args = parser.parse_args(argv)
    print("MARKET_REPAIR_READONLY_PREFLIGHT=" + json.dumps(
        inspect(args.root, args.source_project, args.day),
        ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
