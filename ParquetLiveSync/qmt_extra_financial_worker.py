#!/usr/bin/env python3
"""Short-lived isolated QMT financial table worker.

This process NEVER writes official Parquet, progress.json, or cursor state.
Its parent enforces a finite wall-clock timeout and owns the writer lock.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import qmt_extra_data as E


def collect(xt, code, table, output, *, progress=print, cached_only=False):
    code = E.valid_code(code)
    if table not in E.FIN_TABLES:
        raise ValueError("Unsupported financial table: " + str(table))
    output = Path(output)
    E._path_check(output)
    if output.exists():
        raise ValueError("QMT financial worker output already exists")
    if not cached_only:
        progress("MARKET_QMT_EXTRA_FINANCIAL_WORKER_DOWNLOAD_START=" +
                 E.canonical_json({"symbol": code, "table": table}))
        xt.download_financial_data([code], [table])
        progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_FETCHED=" +
                 E.canonical_json({"symbol": code, "table": table}))
    else:
        progress("MARKET_QMT_EXTRA_FINANCIAL_WORKER_CACHE_ONLY=" +
                 E.canonical_json({"symbol": code, "table": table}))
    progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_READ_START=" +
             E.canonical_json({"symbol": code, "table": table,
                               "api": "get_financial_data"}))
    data = xt.get_financial_data([code], [table], start_time="",
                                 end_time="", report_type="report_time")
    progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_READ_DONE=" +
             E.canonical_json({"symbol": code, "table": table}))
    if not isinstance(data, dict) or not isinstance(data.get(code), dict):
        raise ValueError("QMT financial response missing requested symbol " +
                         code + " table=" + table)
    received = data[code]
    if set(received) - {table}:
        raise ValueError("QMT financial response unexpected table for " +
                         code + " requested=" + table)
    progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_DECODE_START=" +
             E.canonical_json({"symbol": code, "table": table}))
    values = E.dataframe_records(received.get(table))
    progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_DECODE_DONE=" +
             E.canonical_json({"symbol": code, "table": table,
                               "rows": len(values)}))
    payload = E.canonical_json({
        "format": "qmt_financial_worker_v1",
        "symbol": code, "table": table, "records": values})
    # The parent creates the isolated per-invocation directory. Never write
    # to public market data, the scheduler, or any cursor from this worker.
    temp = output.with_suffix(".part")
    E._path_check(temp)
    with temp.open("x", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, output)
    progress("MARKET_QMT_EXTRA_FINANCIAL_WORKER_EXPORT_DONE=" +
             E.canonical_json({"symbol": code, "table": table,
                               "rows": len(values)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--table", required=True, choices=E.FIN_TABLES)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cached-only", action="store_true",
                        help="Read existing QMT cache without calling the downloader")
    args = parser.parse_args()
    from xtquant import xtdata
    collect(xtdata, args.symbol, args.table, args.output,
            cached_only=args.cached_only)


if __name__ == "__main__":
    main()
