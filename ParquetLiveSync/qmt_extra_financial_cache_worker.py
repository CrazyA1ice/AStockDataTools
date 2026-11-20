#!/usr/bin/env python3
"""Read an isolated batch of EXISTING QMT financial cache into private JSON.

cache: no download call whatsoever. daily: only announce-date range download
through QMT's synchronous download_financial_data2, then read FULL local cache.
Never writes official Parquet or any cursor/ledger itself.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import qmt_extra_data as E

MAX_SYMBOLS = 20
DOWNLOAD_TABLES = tuple(x for x in E.FIN_TABLES if x != "PerShare")


def collect(xt, symbols, output, *, mode="cache", start="", end="",
            progress=print):
    if (not isinstance(symbols, list) or not symbols
            or len(symbols) > MAX_SYMBOLS
            or symbols != sorted(set(symbols))
            or any(E.valid_code(code) != code for code in symbols)):
        raise ValueError("Invalid financial cache worker symbol group")
    if mode not in ("cache", "daily"):
        raise ValueError("Invalid financial cache worker mode")
    if mode == "daily":
        if (not E.re.fullmatch(r"\d{8}", start)
                or not E.re.fullmatch(r"\d{8}", end) or start > end):
            raise ValueError("Invalid QMT announcement date window")
    elif start or end:
        raise ValueError("Cache-only mode must not specify download window")
    output = Path(output)
    E._path_check(output)
    if output.exists() or output.with_suffix(".part").exists():
        raise ValueError("Private worker output already exists")
    if mode == "daily":
        if not hasattr(xt, "download_financial_data2"):
            raise RuntimeError("QMT lacks required bounded financial_data2 API")
        progress("QMT_CACHE_WORKER_INCREMENTAL_DOWNLOAD=" +
                 E.canonical_json({"symbols": len(symbols),
                                   "start": start, "end": end}))
        xt.download_financial_data2(
            symbols, list(DOWNLOAD_TABLES), start_time=start, end_time=end)
        progress("QMT_CACHE_WORKER_INCREMENTAL_DOWNLOAD_DONE=" +
                 E.canonical_json({"symbols": len(symbols)}))
    else:
        progress("QMT_CACHE_WORKER_EXISTING_CACHE_ONLY=" +
                 E.canonical_json({"symbols": len(symbols)}))
    data = xt.get_financial_data(
        symbols, list(E.FIN_TABLES), start_time="", end_time="",
        report_type="report_time")
    if not isinstance(data, dict) or set(data) - set(symbols):
        raise ValueError("Invalid QMT financial cache reply symbols")
    decoded = {}
    missing = []
    counts = {}
    for code in symbols:
        group = data.get(code)
        if group is None:
            missing.append(code)
            continue
        if not isinstance(group, dict) or set(group) - set(E.FIN_TABLES):
            raise ValueError("Invalid QMT financial cache table set: " + code)
        values = {}
        counts[code] = {}
        for table in E.FIN_TABLES:
            records = E.dataframe_records(group.get(table))
            if (len(records) > 100000 or any(
                    not isinstance(record, dict) or
                    not isinstance(record.get("_index"), str)
                    for record in records)):
                raise ValueError("Invalid QMT financial cache records: " +
                                 code + " " + table)
            values[table] = records
            counts[code][table] = len(records)
        if not any(counts[code].values()):
            missing.append(code)
            continue
        decoded[code] = values
    payload = E.canonical_json({
        "format": "qmt_financial_cache_batch_v1", "mode": mode,
        "symbols": symbols, "missing_symbols": missing,
        "records": decoded, "row_counts": counts,
        "refresh_start": start, "refresh_end": end})
    if len(payload.encode("utf-8")) > 256 * 1024 * 1024:
        raise ValueError("QMT financial cache batch exceeds 256 MiB")
    tmp = output.with_suffix(".part")
    E._path_check(tmp)
    with tmp.open("x", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, output)
    progress("QMT_CACHE_WORKER_DONE=" + E.canonical_json({
        "symbols": len(symbols), "present": len(decoded),
        "missing": len(missing)}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", required=True,
                        help="Comma-separated QMT stock codes, max 20")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("cache", "daily"), required=True)
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    args = parser.parse_args(argv)
    from xtquant import xtdata
    try:
        collect(xtdata, args.symbols.split(","), args.output, mode=args.mode,
                start=args.start, end=args.end)
    except UnicodeDecodeError as exc:
        # A dedicated return code lets the parent isolate a corrupt/truncated
        # QMT textual payload without suppressing unrelated worker errors.
        print("QMT_CACHE_WORKER_UTF8_DECODE_ERROR=" + E.canonical_json({
            "symbols": args.symbols.split(","),
            "encoding": exc.encoding, "start": exc.start,
            "reason": exc.reason}), file=sys.stderr, flush=True)
        raise SystemExit(85) from None
    except Exception as exc:
        # xtquant's get_client() may lose its local QMT connection between
        # successful stock batches. Only its specific connection error is
        # recoverable. All other exceptions must retain their original exit.
        if not str(exc).startswith("无法连接xtquant服务"):
            raise
        print("QMT_CACHE_WORKER_CONNECT_UNAVAILABLE=" + E.canonical_json({
            "symbols": args.symbols.split(","),
            "mode": args.mode,
            "reason": "XTQUANT_CLIENT_CONNECTION_UNAVAILABLE",
            "output_created": args.output.exists(),
        }), file=sys.stderr, flush=True)
        raise SystemExit(86) from None


if __name__ == "__main__":
    main()
