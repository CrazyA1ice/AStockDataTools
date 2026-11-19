#!/usr/bin/env python3
"""Read-only accepted daily minute gate replay; no QMT or market writes.

Use only with explicitly named CLOSED trading days. For the 2026-11-19
repair freeze, audit may not examine any date after 2026-11-18.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from unittest.mock import patch

import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import update_market as U


FREEZE_DATE = date(2026, 11, 18)


def audit(root: Path, trading_day: date, source_project: Path):
    if trading_day > FREEZE_DATE:
        raise ValueError("READONLY_AUDIT_FROZEN_ASOF_20261118")
    # This tool may execute from a detached verification worktree, while
    # immutable day receipts live under the canonical production checkout.
    # Never infer data paths from this script's __file__.
    source_project = Path(source_project).resolve()
    work = source_project / "ParquetLiveSync" / "work"
    official_state = work / "state.json"
    source = work / "market_update" / "daily" / (trading_day.isoformat() + ".parquet")
    receipt = source.with_suffix(".json")
    if (work.is_symlink() or official_state.is_symlink()
            or not official_state.is_file()):
        raise FileNotFoundError("Canonical official DAY state missing or redirected")
    if source.is_symlink() or receipt.is_symlink():
        raise ValueError("Redirected immutable QMT daily candidate")
    if not source.is_file() or not receipt.is_file():
        raise FileNotFoundError("Missing immutable QMT daily candidate pair")
    doc = U.S._json(receipt)
    if (doc.get("format") != U.FORMAT
            or doc.get("date") != trading_day.isoformat()
            or doc.get("sha256") != L.hash_file(source)):
        raise ValueError("Saved QMT daily receipt SHA/identity mismatch")
    # Reuse the authoritative source's full state and daily SHA checks;
    # only redirect the read-only reference lookup, never write any state.
    with (patch.object(U.LIVE, "WORK", work),
          patch.object(U.LIVE, "STATE", official_state)):
        reference = U._reference_for_day(root, trading_day)
    if not reference:
        raise ValueError("Official DAY reference is empty for selected date")
    reader = pq.ParquetFile(source)
    errors = []
    accepted = 0
    zero_volume_bars = 0
    try:
        if reader.schema_arrow != P.PRIVATE_SCHEMA:
            raise ValueError("Immutable 1minute daily source schema mismatch")
        if reader.metadata.num_rows != doc.get("rows"):
            raise ValueError("Immutable 1minute daily source row count mismatch")
        for i in range(reader.num_row_groups):
            table = reader.read_row_group(i)
            rows = table.to_pylist()
            symbols = {L.normal_symbol(row["symbol"]) for row in rows}
            if len(rows) != 240 or len(symbols) != 1:
                raise ValueError("Daily source row group is not an exact stock-day")
            symbol = next(iter(symbols))
            if any(L.market_ts_day(int(row["ts"])) != trading_day
                   for row in rows):
                raise ValueError("Source stock-day timestamp outside selected date")
            accepted += 1
            zero_volume_bars += sum(float(row["volume"]) == 0 for row in rows)
            try:
                if symbol not in reference:
                    raise ValueError("Accepted symbol absent from official DAY")
                U.verify_materialized_ohlc(rows, reference[symbol])
            except (ValueError, KeyError, TypeError) as exc:
                errors.append({
                    "symbol": symbol,
                    "reason": type(exc).__name__ + ": " + str(exc)[:240]
                })
    finally:
        reader.close()
    if accepted != doc["stock_days_accepted"]:
        raise ValueError("QMT stock-day receipt count differs from physical groups")
    quarantined = doc.get("quarantined", {})
    if not isinstance(quarantined, dict):
        raise ValueError("Malformed original daily quarantine ledger")
    report = {
        "date": trading_day.isoformat(),
        "source_project": str(source_project),
        "status": "SOURCE_ANOMALIES_DETECTED" if errors or quarantined else "RECHECK_PASS",
        "accepted_stock_days": accepted,
        "expected_stock_days": doc.get("expected_stock_days"),
        "originally_quarantined": len(quarantined),
        "original_quarantine_examples": dict(list(sorted(quarantined.items()))[:15]),
        "new_gate_rejected_existing_stock_days": len(errors),
        "new_gate_reject_examples": errors[:40],
        "zero_volume_minute_rows": zero_volume_bars,
        "candidate_sha256": doc["sha256"],
        "candidate_sha_verified": True,
        "production_market_files_modified": False,
        "qmt_download_called": False,
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--source-project", type=Path, required=True,
                        help="Canonical checkout holding work/state.json and market_update/daily")
    parser.add_argument("--day", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    print("MARKET_ZERO_VOLUME_READONLY_AUDIT=" +
          json.dumps(audit(args.root, args.day, args.source_project), ensure_ascii=False,
                     sort_keys=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
