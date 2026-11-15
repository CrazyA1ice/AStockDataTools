#!/usr/bin/env python3
"""Read-only physical 1min Oct/Nov inventory and SHA-bound private-merge preflight.

This program CANNOT merge or write any market, private, QMT or H5 files.
It treats a shared *trading date* between private increment and existing
physical month as a conservative blocker requiring exact key reconciliation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_private_month_bridge as B

FORMAT = "qmt_1min_physical_target_readonly_preflight_v1"
EPOCH = date(1970, 1, 1)
DAY_MS = 86_400_000
CN_OFFSET_MS = 28_800_000
BATCH = 131072


def scan_physical_month(path, month, *, progress=print):
    """Stream timestamp column only; exact date population, bounded RAM.

    SHA checked both before and after reading to detect external changes.
    Does not assume Parquet row-group min/max statistics are present.
    """
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Physical monthly source missing or redirected " + month)
    before = L.hash_file(path)
    counter = Counter()
    seen_rows = 0
    first = None
    last = None
    reader = pq.ParquetFile(path)
    try:
        schema = reader.schema_arrow
        L.validate_schema(schema)
        if (schema.field("ts").type != pa.int64()
                or reader.metadata.num_rows < 0):
            raise ValueError("Physical monthly timestamp schema invalid " + month)
        footer_rows = reader.metadata.num_rows
        for batch in reader.iter_batches(batch_size=BATCH, columns=["ts"],
                                        use_threads=False):
            col = batch.column(0)
            if col.null_count:
                raise ValueError("Null timestamp in physical 1min month " + month)
            values = col.to_numpy(zero_copy_only=False)
            if values.dtype.kind not in ("i", "u"):
                raise ValueError("Noninteger physical timestamps " + month)
            if len(values) == 0:
                continue
            smallest = int(values.min())
            largest = int(values.max())
            first = smallest if first is None else min(first, smallest)
            last = largest if last is None else max(last, largest)
            day_ids, counts = np.unique((values + CN_OFFSET_MS) // DAY_MS,
                                        return_counts=True)
            for day_id, count in zip(day_ids, counts):
                actual_day = EPOCH + timedelta(days=int(day_id))
                if actual_day.strftime("%Y-%m") != month:
                    raise ValueError("Physical 1min month contains out-of-month timestamp " +
                                     actual_day.isoformat())
                counter[actual_day.isoformat()] += int(count)
            seen_rows += len(values)
            if seen_rows % 5_000_000 < BATCH and seen_rows > BATCH:
                progress("QMT_PHYSICAL_TARGET_SCAN_PROGRESS=" +
                         month + " rows=" + str(seen_rows))
        if footer_rows != seen_rows:
            raise ValueError("Physical monthly Parquet footer row count changed " + month)
    finally:
        reader.close()
    if L.hash_file(path) != before:
        raise ValueError("Physical 1min month changed while being scanned " + month)
    return {
        "exists": True,
        "sha256": before,
        "rows": seen_rows,
        "days": dict(sorted(counter.items())),
        "first_timestamp_ms": first,
        "last_timestamp_ms": last,
        "schema_valid": True,
    }


def inspect(root=Path("D:/stock"),
            stage=B.P.BASE / "20261014_20261112",
            *, progress=print, target_scanner=scan_physical_month):
    """Read-only; independently validate both private increments and target dates."""
    plan = B.resolve(root, stage, progress=progress)
    storage = L.storage_root(root)
    minute = storage / "1min"
    if minute.is_symlink() or not minute.is_dir():
        raise ValueError("Missing/noncanonical physical 1min directory")
    annual = minute / "2026.parquet"
    if annual.exists() or annual.is_symlink():
        raise ValueError("2026 annual 1min file exists; month insertion would double count")
    output = Path(stage) / B.TARGET
    if output.is_symlink() or not output.is_dir():
        raise ValueError("Missing or redirected sealed private month directory")
    all_days = sorted(d.isoformat() for d in plan["expected"])
    expected_source_days = {
        m: [d for d in all_days if d.startswith(m)] for m in B.MONTHS
    }
    results = {}
    blocked = []
    for month in B.MONTHS:
        incoming = output / (month + ".parquet")
        receipt_path = output / (month + ".receipt.json")
        manifest = B._json(receipt_path)
        if (manifest.get("month") != month
                or manifest.get("month_coverage") != plan["months"][month]
                or manifest.get("calibration_sha256") != plan["plan"]["calibration_sha256"]
                or manifest.get("remaining_quarantined_keys") != [
                    {"day": d, "symbol": code} for d, code in plan["gaps"]
                    if d.startswith(month)]):
            raise ValueError("Private monthly manifest coverage or gap map changed " + month)
        B.verify_private_month(incoming, manifest, plan["identity_sha256"])
        progress("QMT_PHYSICAL_PREFLIGHT_PRIVATE_SHA_VERIFIED=" + month)
        physical = minute / (month + ".parquet")
        if physical.is_symlink():
            raise ValueError("Symlinked physical target " + month)
        if physical.exists():
            data = target_scanner(physical, month, progress=progress)
            if not isinstance(data, dict) or not data.get("schema_valid"):
                raise ValueError("Target scanner returned invalid physical schema")
            existing_dates = sorted(data["days"])
            intersect = sorted(set(existing_dates) & set(expected_source_days[month]))
            status = "BLOCKED_SHARED_TRADING_DATES" if intersect else "DATE_DISJOINT_CANDIDATE"
        else:
            data = {"exists": False, "rows": 0, "sha256": None, "days": {},
                    "schema_valid": None}
            existing_dates = []
            intersect = []
            status = "TARGET_ABSENT_CANDIDATE"
        if intersect:
            blocked.append(month)
        results[month] = {
            "status": status, "target_file_exists": data["exists"],
            "target_sha256": data["sha256"], "existing_rows": data["rows"],
            "existing_trading_days": existing_dates,
            "private_increment_days": expected_source_days[month],
            "shared_trading_days": intersect,
            "private_rows": manifest["rows"],
            "private_sha256": manifest["sha256"],
            "stock_day_gaps": plan["months"][month]["stock_days_quarantined"],
            "physical_market_modified": False,
        }
        progress("QMT_PHYSICAL_TARGET_MONTH=" + json.dumps(
            {"month": month, **results[month]}, sort_keys=True))
    result = {
        "format": FORMAT, "source_window": [str(B.START), str(B.END)],
        "source_identity_sha256": plan["identity_sha256"],
        "original_day_calendar_sha256": plan["plan"]["calendar_sha256"],
        "private_verified_rows": sum(m["private_rows"] for m in results.values()),
        "private_stock_days": (plan["original"] + plan["recovered"] + plan["opening"]),
        "remaining_quarantined_keys": [
            {"day": d, "symbol": code} for d, code in plan["gaps"]],
        "target_months": results,
        "blocked_by_shared_dates": blocked,
        "date_disjoint_gate_passed": not blocked,
        "exact_key_overlap_audit_not_yet_completed": True,
        "native_0930_label_policy_still_requires_merge_review": True,
        "full_2026_month_coverage_not_proven": True,
        "physical_market_modified": False,
        "production_merge_authorized": False,
    }
    progress("QMT_PHYSICAL_PREFLIGHT_RESULT=" + json.dumps(result, sort_keys=True))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    args = parser.parse_args(argv)
    print("QMT_PHYSICAL_PREFLIGHT_READ_ONLY_NO_WRITES")
    inspect(root=args.root)


if __name__ == "__main__":
    main()
