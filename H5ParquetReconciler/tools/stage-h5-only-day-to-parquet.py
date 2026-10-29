#!/usr/bin/env python3
"""Stage ONE complete H5-only daily date as a NEW, private Parquet partition.

Never writes the original purchased Parquet or Hikyuu H5; never promotes
staged output. Requires two SHA-linked, fully validated audit reports and
rechecks the selected trading day against LIVE source keys before export.
H5 scaling is an explicit diagnostic conversion candidate, not certified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from collections import Counter
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent.resolve()


def import_tool(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = import_tool("h5_to_parquet_day_core", "reconcile-local-a-share-h5-parquet.py")
gate_tool = import_tool("h5_to_parquet_day_gate", "plan-parquet-primary-day-bootstrap-offline.py")
FORMAT = "AStockDataTools H5-only daily Parquet staging v1"
SCHEMA_FIELDS = ("ts", "symbol", "open", "high", "low", "close",
                 "volume", "amount", "source")
MARKET_SUFFIX = {"SH": "XSHG", "SZ": "XSHE", "BJ": "XBSE"}
STAGING = (MODULE / "work" / "unified_parquet" / "staging").resolve()
REPORTS = (MODULE / "reports").resolve()


def file_digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_file_states(root, year):
    paths = [root / "HikyuuData" / (market + "_day.h5")
             for market in ("sh", "sz", "bj")]
    paths.extend(core.year_files(root, "day", year))
    if len(paths) < 4 or any(not x.is_file() or x.is_symlink() for x in paths):
        raise ValueError("All three H5 daily market files and purchased year Parquet files must exist")
    return tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns)
                 for p in sorted(paths))


def verified_gate(gate, original, original_raw, requested_day):
    verified = gate_tool.analyze(original)
    if (not isinstance(gate, dict)
            or gate.get("format") != gate_tool.OUTPUT_FORMAT
            or gate.get("source_report_sha256") != hashlib.sha256(original_raw).hexdigest()
            or gate.get("source_report_type") != gate_tool.SOURCE_FORMAT
            or gate.get("audited_window") != verified["audited_window"]
            or gate.get("source_totals") != verified["source_totals"]
            or gate.get("daily_coverage") != verified["daily_coverage"]
            or gate.get("existing_tolerance_ohlc_overlap_pass") is not True
            or verified["existing_tolerance_ohlc_overlap_pass"] is not True
            or gate.get("market_source_files_modified") is not False
            or gate.get("ready_for_unattended_data_fill") is not False
            or gate.get("safe_to_automatically_union") is not False):
        raise ValueError("Gate mismatch, failed price audit, or stale original report")
    key = requested_day.strftime("%Y%m%d")
    matches = [row for row in verified["daily_coverage"] if row["date"] == key]
    if len(matches) != 1:
        raise ValueError("Requested date not present exactly once in verified gate")
    chosen = matches[0]
    if (chosen["category"] != "entire_date_h5_only_candidate"
            or chosen["pq_rows"] != 0 or chosen["matched_keys"] != 0
            or chosen["h5_rows"] <= 0
            or chosen["h5_rows"] != chosen["h5_only_rows"]):
        raise ValueError("Only whole-day H5-only dates are eligible for this staging path")
    return chosen


def read_h5_day(root, day, max_bars):
    """Read selected date slices only; no raw record is written to reports/."""
    import h5py

    stamp = int(day.strftime("%Y%m%d")) * 10000
    collected, counts = [], Counter()
    keys = set()
    for market in ("sh", "sz", "bj"):
        path = root / "HikyuuData" / (market + "_day.h5")
        with h5py.File(path, "r") as fh:
            group = fh.get("data")
            if not isinstance(group, h5py.Group):
                raise ValueError("Invalid H5 data group for " + market)
            for symbol in sorted(group):
                if not core.is_a_share_candidate(symbol, day.year):
                    continue
                if not symbol.startswith(market.upper()):
                    continue
                ds = group.get(symbol)
                if not isinstance(ds, h5py.Dataset) or not set(core.H5_FIELDS).issubset(ds.dtype.names or ()):
                    raise ValueError("Invalid H5 day schema for candidate symbol")
                left, right = core.h5_key_slice(ds, stamp, stamp + 1)
                if right == left:
                    continue
                if right - left != 1 or (symbol, stamp) in keys:
                    raise ValueError("Duplicate H5 stock-day detected; fail closed")
                rec = ds[left]
                if int(rec["datetime"]) != stamp:
                    raise ValueError("Invalid H5 daily time key")
                raw = [int(rec[field]) for field in (
                    "openPrice", "highPrice", "lowPrice", "closePrice",
                    "transCount", "transAmount")]
                if any(x < 0 for x in raw):
                    raise ValueError("Negative source value")
                op, hi, lo, close = (x / 1000.0 for x in raw[:4])
                volume = raw[4] * 100.0
                amount = raw[5] * 1000.0
                if (not all(math.isfinite(x) for x in (op, hi, lo, close, volume, amount))
                        or min(op, hi, lo, close) <= 0
                        or hi + 1e-8 < max(op, close, lo)
                        or lo - 1e-8 > min(op, close, hi)):
                    raise ValueError("Invalid normalized H5 daily OHLCVA geometry")
                keys.add((symbol, stamp))
                collected.append({
                    "ts": int(datetime(day.year, day.month, day.day,
                                       tzinfo=core.UTC8).timestamp() * 1000),
                    "symbol": symbol[2:] + "." + MARKET_SUFFIX[market.upper()],
                    "open": op, "high": hi, "low": lo, "close": close,
                    "volume": volume, "amount": amount,
                    "source": "hikyuu_h5_tail_candidate",
                })
                counts[market.upper()] += 1
                if len(collected) > max_bars:
                    raise ValueError("Exceeded bounded --max-bars safeguard")
    collected.sort(key=lambda row: row["symbol"])
    return collected, counts


def verify_live_absence(root, scratch, day, expected):
    # Re-run exact KEY scan at execution time; a stale offline gate can never
    # authorize writing into the private staging area.
    result = core.reconcile_section(
        root, scratch, "day", day.year, 8192, "a-share-candidate",
        day.isoformat(), day.isoformat(), False)
    bucket = result.get("by_day", {}).get(day.strftime("%Y%m%d"), {})
    if (result.get("scan_complete") is not True
            or result.get("issues") != []
            or result.get("pq_year_metadata_only_no_h5_rows") is not False
            or result.get("parquet_year_files", 0) <= 0
            or result.get("h5_rows") != expected
            or result.get("pq_rows") != 0
            or result.get("matched_keys") != 0
            or result.get("h5_only_rows") != expected
            or result.get("pq_only_rows") != 0
            or bucket.get("h5_unique") != expected
            or bucket.get("parquet_unique", 0) != 0):
        raise ValueError("Live source recheck disagrees with original complete-date gap")
    return result


def stage(root, gate_path, report_path, day, stage_dir, max_bars):
    import pyarrow as pa
    import pyarrow.parquet as pq

    root = Path(root).resolve()
    gate_path, report_path = Path(gate_path).resolve(), Path(report_path).resolve()
    stage_dir = Path(stage_dir).resolve()
    if (gate_path.parent != REPORTS or report_path.parent != REPORTS
            or gate_path == report_path or not gate_path.is_file()
            or not report_path.is_file()
            or stage_dir.parent != STAGING
            or stage_dir == STAGING
            or not 1 <= max_bars <= 20000):
        raise ValueError("Reports must exist in module reports/; stage must be NEW immediate child of work/unified_parquet/staging")
    for path in (gate_path, report_path, stage_dir):
        if path == root or path.is_relative_to(root):
            raise ValueError("Never store or use audit artifacts inside original market source tree")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    original_raw = report_path.read_bytes()
    original = json.loads(original_raw)
    if gate.get("source_report_basename") != report_path.name:
        raise ValueError("Gate does not reference the supplied exact source report")
    selected = verified_gate(gate, original, original_raw, day)
    expected = selected["h5_only_rows"]
    if expected > max_bars:
        raise ValueError("Audited number exceeds configured --max-bars")
    before = source_file_states(root, day.year)
    scratch = (MODULE / "work" / "stage_day_live_recheck").resolve()
    if scratch == root or scratch.is_relative_to(root):
        raise ValueError("Source and scratch path overlap")
    scratch.mkdir(parents=True, exist_ok=True)
    verify_live_absence(root, scratch, day, expected)
    bars, markets = read_h5_day(root, day, max_bars)
    if len(bars) != expected:
        raise ValueError("H5 decoded row count differs from original and live audits")
    if source_file_states(root, day.year) != before:
        raise ValueError("Source file sizes/timestamps changed during staging preflight")

    schema = pa.schema([
        pa.field("ts", pa.int64()), pa.field("symbol", pa.string()),
        *(pa.field(n, pa.float64()) for n in (
            "open", "high", "low", "close", "volume", "amount")),
        pa.field("source", pa.string())])
    assert tuple(schema.names) == SCHEMA_FIELDS
    table = pa.Table.from_pylist(bars, schema=schema)
    if stage_dir.exists():
        raise ValueError("Staging job already exists; refuse overwrite")
    stage_dir.parent.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(exist_ok=False)
    target = stage_dir / "day.parquet"
    pq.write_table(table, target, compression="snappy", row_group_size=8192)
    roundtrip = pq.read_table(target)
    if not table.equals(roundtrip, check_metadata=True):
        raise ValueError("Staged Parquet full row/field roundtrip mismatch")
    if source_file_states(root, day.year) != before:
        raise ValueError("Sources changed during staged Parquet writing")
    manifest = {
        "format": FORMAT, "day": day.isoformat(), "period": "day",
        "state": "staged_verified_not_promoted",
        "audited_h5_only_bars": expected,
        "staged_bars": len(bars),
        "market_prefix_counts": dict(sorted(markets.items())),
        "staged_parquet_sha256": file_digest(target),
        "gate_report_sha256": file_digest(gate_path),
        "raw_day_report_sha256": hashlib.sha256(original_raw).hexdigest(),
        "h5_daily_price_factor_candidate": 0.001,
        "h5_daily_volume_factor_candidate": 100,
        "h5_daily_amount_factor_candidate": 1000,
        "original_market_data_modified": False,
        "purchased_parquet_overwritten": False,
        "h5_mirror_created": False,
        "market_source_files_read": True,
        "private_staged_market_rows_present": True,
        "ready_for_production_promotion": False,
        "safe_to_automatically_union": False,
    }
    (stage_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--gate-report", type=Path, required=True)
    ap.add_argument("--source-report", type=Path, required=True)
    ap.add_argument("--stage-dir", type=Path, required=True)
    ap.add_argument("--max-bars", type=int, default=20000)
    ap.add_argument("--read-only-sources", action="store_true", required=True)
    args = ap.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
        if args.date != day.isoformat():
            raise ValueError("Expected canonical ISO date")
        staging = args.stage_dir
        if not staging.is_absolute():
            parts = staging.parts
            if parts and parts[0].lower() == MODULE.name.lower():
                parts = parts[1:]
            staging = MODULE.joinpath(*parts)
        output = stage(args.root, args.gate_report, args.source_report,
                       day, staging, args.max_bars)
        print("STAGED verified only:", output["day"], output["staged_bars"],
              "private bars; NO source writes or production promotion")
        print("SHA256:", output["staged_parquet_sha256"])
    except (ValueError, OSError, OverflowError, KeyError, json.JSONDecodeError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
