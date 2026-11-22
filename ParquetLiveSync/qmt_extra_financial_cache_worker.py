#!/usr/bin/env python3
"""Read an isolated batch of EXISTING QMT financial cache into private JSON.

cache: no download call whatsoever. daily: only announce-date range download
through QMT's synchronous download_financial_data2, then read FULL local cache.
Never writes official Parquet or any cursor/ledger itself.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import os
import sys
from pathlib import Path

import qmt_extra_data as E

MAX_SYMBOLS = 20
DOWNLOAD_TABLES = tuple(x for x in E.FIN_TABLES if x != "PerShare")


class QMTCacheProviderDisconnected(RuntimeError):
    """Provider API confirmed a QMT client connection failure."""


def _qmt_provider_call(method, *args, **kwargs):
    """Classify a disconnect only when xtquant itself raises the message.

    Local path checks, provider-data conversion, JSON serialization, and
    filesystem errors must never be retried as an xtquant connection outage.
    Preserve UnicodeDecodeError for the existing dedicated exit 85.
    """
    try:
        return method(*args, **kwargs)
    except UnicodeDecodeError:
        raise
    except Exception as exc:
        if not str(exc).startswith("无法连接xtquant服务"):
            raise
        raise QMTCacheProviderDisconnected(
            "XTQUANT_CLIENT_CONNECTION_UNAVAILABLE") from exc


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
        _qmt_provider_call(
            xt.download_financial_data2, symbols, list(DOWNLOAD_TABLES),
            start_time=start, end_time=end)
        progress("QMT_CACHE_WORKER_INCREMENTAL_DOWNLOAD_DONE=" +
                 E.canonical_json({"symbols": len(symbols)}))
    else:
        progress("QMT_CACHE_WORKER_EXISTING_CACHE_ONLY=" +
                 E.canonical_json({"symbols": len(symbols)}))
    data = _qmt_provider_call(
        xt.get_financial_data, symbols, list(E.FIN_TABLES),
        start_time="", end_time="", report_type="report_time")
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


def probe_tables_readonly(xt, code, *, now=None):
    """Check each of the nine QMT table names without downloading or writing.

    Separate calls distinguish an unsupported optional PerShare table from a
    failing required table. This does NOT authenticate rows or source history.
    """
    if E.valid_code(code) != code:
        raise ValueError("Invalid probe stock code")
    local = now or datetime.now(E.L.UTC8)
    if local.tzinfo is None or local.utcoffset() is None:
        raise ValueError("Probe requires a timezone-aware clock")
    local = local.astimezone(E.L.UTC8)
    minute = local.hour * 60 + local.minute
    if 19 * 60 + 50 <= minute < 20 * 60 + 25:
        raise ValueError("QMT_FINANCE_PROBE_RESERVED_2005_WINDOW")
    results = []
    for table in E.FIN_TABLES:
        kind = "OPTIONAL_UNCONFIRMED" if table == "PerShare" else "DOCUMENTED_CORE"
        try:
            data = _qmt_provider_call(
                xt.get_financial_data, [code], [table],
                start_time="", end_time="", report_type="report_time")
            if not isinstance(data, dict) or set(data) - {code}:
                raise ValueError("Invalid QMT financial probe envelope")
            tables = data.get(code)
            if tables is None:
                status, count = "SYMBOL_NOT_RETURNED", None
            elif not isinstance(tables, dict) or set(tables) - {table}:
                raise ValueError("Invalid QMT financial probe table set")
            elif table not in tables:
                status, count = "TABLE_NOT_RETURNED", None
            elif tables[table] is None:
                status, count = "EMPTY_OR_NOT_CACHED", 0
            else:
                frame = tables[table]
                if not hasattr(frame, "index"):
                    raise ValueError("QMT finance table index missing")
                count = len(frame.index)
                if type(count) is not int or not 0 <= count <= 100000:
                    raise ValueError("QMT finance table row count invalid")
                status = "ROWS_IN_LOCAL_CACHE" if count else "EMPTY_OR_NOT_CACHED"
        except UnicodeDecodeError:
            status, count = "UTF8_DECODE_ERROR", None
        except QMTCacheProviderDisconnected:
            status, count = "QMT_CLIENT_UNAVAILABLE", None
        except (ValueError, TypeError, KeyError, AttributeError):
            status, count = "INVALID_PROVIDER_RESPONSE", None
        except Exception:
            # No tracebacks or source-content bytes in the operator report.
            status, count = "SOURCE_API_ERROR", None
        results.append({"table": table, "role": kind,
                        "status": status, "cached_rows": count})
    return {
        "status": "QMT_FINANCE_TABLE_READONLY_PROBE_REQUIRES_REVIEW",
        "symbol": code, "tables_checked": len(results), "tables": results,
        "per_share_optional_support_proven": False,
        "empty_cache_proves_provider_empty": False,
        "historical_consistency_verified": False,
        "qmt_get_financial_data_calls": len(results),
        "qmt_download_calls": 0, "can_download": False,
        "can_apply": False, "can_commit": False,
        "official_finance_writes": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", required=True,
                        help="Comma-separated QMT stock codes, max 20")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", choices=("cache", "daily"))
    parser.add_argument("--probe-readonly", action="store_true")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    args = parser.parse_args(argv)
    if args.probe_readonly:
        if (args.output is not None or args.mode is not None
                or args.start or args.end
                or not E.re.fullmatch(r"d{6}.(?:SH|SZ|BJ)", args.symbols)):
            parser.error("readonly probe requires exactly one stock and no write options")
        # Block QMT API access during the daily writer's protected window.
        local = datetime.now(E.L.UTC8)
        if 19 * 60 + 50 <= local.hour * 60 + local.minute < 20 * 60 + 25:
            print("QMT_FINANCE_PROBE_BLOCKED=RESERVED_2005_WINDOW", flush=True)
            return 2
        from xtquant import xtdata
        print("QMT_FINANCE_TABLE_READONLY_PROBE=" +
              E.canonical_json(probe_tables_readonly(xtdata, args.symbols)),
              flush=True)
        return 0
    if args.output is None or args.mode is None:
        parser.error("normal worker requires --output and --mode")
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
    except QMTCacheProviderDisconnected:
        # Exit 86 only for a typed exception raised at an actual xtquant
        # financial API boundary. Unrelated local failures propagate untyped.
        print("QMT_CACHE_WORKER_CONNECT_UNAVAILABLE=" + E.canonical_json({
            "symbols": args.symbols.split(","),
            "mode": args.mode,
            "reason": "XTQUANT_CLIENT_CONNECTION_UNAVAILABLE",
            "output_created": args.output.exists(),
        }), file=sys.stderr, flush=True)
        raise SystemExit(86) from None


if __name__ == "__main__":
    main()
