#!/usr/bin/env python3
"""QMT supplementary market data to separate, provenance-preserving Parquet trees.

Never touch the purchased 8-cycle folders, QMT market 1m ledger, or H5.
QMT data are stored AS QMT DATA (no implicit purchased-vendor semantics).
Use --dry-run to inspect universe; --apply to fetch/cache/commit incrementally.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
import live_sync as LIVE
import market_month_storage as S

FORMAT = "qmt_supplementary_parquet_v1"
WORK = Path(__file__).resolve().parent / "work" / "qmt_extra"
FIN_TABLES = ("Balance", "Income", "CashFlow", "Capital", "Top10FlowHolder",
              "Top10Holder", "HolderNum", "PershareIndex")
API_PERIODS = {"1min": "1m", "5min": "5m", "15min": "15m",
               "30min": "30m", "60min": "1h", "day": "1d",
               "week": "1w", "month": "1mon"}
OHLC_SCHEMA = pa.schema([
    pa.field("ts", pa.int64()), pa.field("symbol", pa.string()),
    *[pa.field(col, pa.float64()) for col in L.COLS[2:]]
])
RAW_SCHEMA = pa.schema([
    pa.field("asof", pa.string()), pa.field("symbol", pa.string()),
    pa.field("item", pa.string()), pa.field("index", pa.int32()),
    pa.field("payload_json", pa.string())
])
SECTOR_SCHEMA = pa.schema([
    pa.field("asof", pa.string()), pa.field("sector", pa.string()),
    pa.field("symbol", pa.string())
])
QUOTE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
SINCE = date(2011, 1, 1)


def valid_code(value: str) -> str:
    if not isinstance(value, str) or not QUOTE_RE.fullmatch(value.upper()):
        raise ValueError("Unsupported QMT security code: " + repr(value))
    return value.upper()


def canonical_json(value: Any) -> str:
    def tidy(v):
        if v is None or isinstance(v, (str, bool, int)):
            return v
        if hasattr(v, "item"):
            return tidy(v.item())
        if isinstance(v, float):
            return v if math.isfinite(v) else None
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        if isinstance(v, dict):
            return {str(k): tidy(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [tidy(x) for x in v]
        return str(v)
    return json.dumps(tidy(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def dataframe_records(frame):
    """Retain all provider columns AND index without making up data types."""
    if frame is None:
        return []
    if not hasattr(frame, "to_dict"):
        raise ValueError("Expected QMT pandas DataFrame")
    records = frame.to_dict(orient="records")
    indices = list(frame.index)
    if len(indices) != len(records):
        raise ValueError("QMT financial/adjustment index length differs")
    return [{"_index": str(i), **row} for i, row in zip(indices, records)]


def snapshot_table(asof, symbol, item, records):
    rows = [{"asof": asof, "symbol": symbol, "item": item,
             "index": i, "payload_json": canonical_json(record)}
            for i, record in enumerate(records)]
    return pa.Table.from_pylist(rows, schema=RAW_SCHEMA)


def _storage(root):
    base = L.storage_root(root)
    extra = base / "qmt_extra"
    if extra.is_symlink():
        raise ValueError("Linked supplementary data root")
    return extra


def _path_check(path):
    path = Path(path)
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError("Linked QMT supplementary output rejected: " + str(parent))


def _atomic_parquet(path, table, *, workspace=WORK, allow_changed=False):
    """Single-file transactional replacement; backup changed previous bytes."""
    path = Path(path)
    _path_check(path)
    if table.schema not in (RAW_SCHEMA, OHLC_SCHEMA, SECTOR_SCHEMA):
        raise ValueError("Unexpected supplementary Arrow schema")
    path.parent.mkdir(parents=True, exist_ok=True)
    _path_check(path)
    if path.exists():
        old = pq.read_table(path)
        if old.schema != table.schema:
            raise ValueError("QMT supplementary schema changed: " + str(path))
        if old.equals(table, check_metadata=False):
            return {"status": "UNCHANGED", "rows": table.num_rows}
        if not allow_changed:
            raise ValueError("Existing immutable supplementary snapshot changed: " + str(path))
    else:
        old = None
    scratch = path.with_suffix(".parquet.qmt-part")
    _path_check(scratch)
    if scratch.exists():
        scratch.unlink()
    pq.write_table(table, scratch, compression="zstd", row_group_size=65536)
    check = pq.read_table(scratch)
    if not check.equals(table, check_metadata=False):
        scratch.unlink(missing_ok=True)
        raise ValueError("QMT supplementary Parquet roundtrip changed")
    if old is not None:
        destination = Path(workspace) / "backups" / path.parent.name
        destination.mkdir(parents=True, exist_ok=True)
        _path_check(destination)
        old_hash = L.hash_file(path)
        backup = destination / (path.name + "." + old_hash[:16] + ".bak")
        _path_check(backup)
        if backup.exists():
            if L.hash_file(backup) != old_hash:
                raise ValueError("QMT supplementary backup SHA mismatch")
        else:
            shutil.copy2(path, backup)
            if L.hash_file(backup) != old_hash:
                raise ValueError("QMT supplementary backup bytes differ")
    os.replace(scratch, path)
    return {"status": "UPDATED" if old is not None else "CREATED",
            "rows": table.num_rows, "sha256": L.hash_file(path)}


def _snapshot_path(extra, group, asof, table):
    """Immutable content-addressed snapshots; no old data overwritten."""
    content = table.to_pylist()
    content_hash = hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()[:16]
    return extra / group / "snapshots" / (asof + "-" + content_hash + ".parquet")


def _snapshot_write(extra, group, asof, table, workspace=WORK):
    return _atomic_parquet(_snapshot_path(extra, group, asof, table),
                           table, workspace=workspace)


def _state_path(workspace):
    return Path(workspace) / "progress.json"


def _state(extra, workspace):
    path = _state_path(workspace)
    if not path.exists():
        return {"format": FORMAT, "root": str(extra.resolve()),
                "cursor": {}, "last_asof": {}, "last_asset_fetch": {}}
    _path_check(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT or data.get("root") != str(extra.resolve()):
        raise ValueError("QMT extra progress identity changed")
    if not isinstance(data.get("cursor"), dict):
        raise ValueError("QMT extra cursor invalid")
    return data


def _save_state(state, workspace):
    path = _state_path(workspace)
    _path_check(path)
    S._save(path, state)


def _batch(codes, previous, limit):
    codes = sorted(set(codes))
    if not codes:
        return []
    after = [code for code in codes if code > previous]
    if not after:
        after = codes
    return after[:limit] if limit else after


def _advance(state, key, code, workspace):
    state["cursor"][key] = code
    _save_state(state, workspace)


def _tickers(xt, sectors, *, required=False):
    found = set()
    attempted = {}
    for sector in sectors:
        try:
            values = xt.get_stock_list_in_sector(sector)
            for code in values or []:
                if isinstance(code, str) and QUOTE_RE.fullmatch(code.upper()):
                    found.add(code.upper())
            attempted[sector] = len(values or [])
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            attempted[sector] = type(exc).__name__ + ":" + str(exc)[:100]
    if required and not found:
        raise ValueError("QMT returned no symbols for sectors " +
                         canonical_json(attempted))
    return sorted(found)


def discover(xt):
    """Never guess a fund is an ETF just because it is listed as a fund."""
    stocks = _tickers(xt, ("沪深A股",), required=True)
    indices = _tickers(xt, ("沪深指数", "板块指数"), required=True)
    explicit_etfs = set(_tickers(xt, ("ETF", "ETF基金", "沪深ETF")))
    if hasattr(xt, "get_ETF_list"):
        try:
            explicit_etfs.update(
                valid_code(code) for code in (xt.get_ETF_list() or []))
        except (ValueError, KeyError, TypeError, RuntimeError):
            # Some broker builds expose the method name but not its service.
            # Independently classified fund sector members remain available.
            pass
    fund_candidates = _tickers(xt, ("沪深基金",))
    etfs = set(explicit_etfs)
    for code in fund_candidates:
        if code in etfs:
            continue
        try:
            kinds = xt.get_instrument_type(code)
        except (ValueError, KeyError, TypeError, RuntimeError):
            continue
        if isinstance(kinds, dict) and any(
            "ETF" in str(key).upper() and bool(value)
            for key, value in kinds.items()
        ):
            etfs.add(code)
    if not etfs:
        raise ValueError("QMT ETF universe unavailable or not classified")
    return {"financial": stocks, "adjustments": stocks,
            "index": indices, "etf": sorted(etfs)}


def _normalize_quote(symbol, frame, *, until):
    if frame is None:
        return []
    records = dataframe_records(frame)
    out = []
    seen = set()
    for raw in records:
        tick = raw.get("time")
        if isinstance(tick, bool) or tick is None:
            raise ValueError("QMT Kline lacks numeric Unix-millisecond time")
        stamp = int(tick)
        if float(tick) != stamp:
            raise ValueError("Fractional QMT index/ETF timestamp")
        if stamp < 946684800000 or stamp > 4102444800000:
            raise ValueError("Unsupported QMT Kline timestamp: " + repr(tick))
        trading = L.market_ts_day(stamp)
        if trading > until:
            continue
        if stamp in seen:
            raise ValueError("QMT duplicate Kline timestamp " + symbol)
        seen.add(stamp)
        numbers = {key: float(raw[key]) for key in L.COLS[2:]}
        if (any(not math.isfinite(v) for v in numbers.values())
                or numbers["volume"] < 0 or numbers["amount"] < 0
                or numbers["low"] <= 0
                or numbers["low"] > min(numbers["open"], numbers["close"])
                or numbers["high"] < max(numbers["open"], numbers["close"])):
            raise ValueError("QMT index/ETF Kline OHLCVA invalid: " + symbol)
        out.append({"ts": stamp, "symbol": L.normal_symbol(symbol), **numbers})
    return sorted(out, key=lambda record: record["ts"])


def _quote_target(extra, kind, cycle, symbol, trading, *, today):
    folder = extra / kind / cycle / symbol
    year = trading.year
    if year == today.year or any(folder.glob(str(year) + "-??.parquet")):
        name = trading.strftime("%Y-%m") + ".parquet"
    else:
        name = str(year) + ".parquet"
    return folder / name


def _upsert_quote(extra, kind, cycle, symbol, raw, *, today, workspace):
    grouped = defaultdict(list)
    for row in raw:
        trading = L.market_ts_day(row["ts"])
        # Never publish a not-yet-closed QMT WEEK/MONTH bar.
        if cycle == "week":
            # On Saturday/Sunday the preceding Friday is *closed*.
            upcoming_monday = today + timedelta(days=7-today.weekday())
            this_monday = today - timedelta(days=today.weekday())
            open_week_start = (
                upcoming_monday if today.weekday() >= 5 else this_monday)
            if trading >= open_week_start:
                continue
        if cycle == "month" and trading >= today.replace(day=1):
            continue
        target = _quote_target(extra, kind, cycle, symbol, trading, today=today)
        grouped[target].append(row)
    changed = 0
    for path, fresh in sorted(grouped.items()):
        old = pq.read_table(path).to_pylist() if path.exists() else []
        by_stamp = {int(r["ts"]): r for r in old}
        if len(by_stamp) != len(old):
            raise ValueError("Duplicate timestamps in existing QMT index/ETF file")
        for row in fresh:
            ts = row["ts"]
            if ts in by_stamp:
                if any(not math.isclose(float(row[c]), float(by_stamp[ts][c]),
                                        rel_tol=1e-8, abs_tol=1e-8)
                       for c in L.COLS[2:]):
                    raise ValueError("QMT quote historical overlap changed, refusing "
                                     + str(path) + " ts=" + str(ts))
            else:
                by_stamp[ts] = row
                changed += 1
        if len(by_stamp) == len(old):
            continue
        joined = pa.Table.from_pylist(
            sorted(by_stamp.values(), key=lambda r: r["ts"]),
            schema=OHLC_SCHEMA)
        _atomic_parquet(path, joined, workspace=workspace, allow_changed=True)
    return changed


def _fetch_quotes(xt, extra, kind, code, today, since, *, workspace):
    rows_added = {}
    for cycle, api in API_PERIODS.items():
        # Only ask QMT for history it can provide; no synthetic OHLCVA.
        xt.download_history_data(code, period=api,
                                 start_time=since.strftime("%Y%m%d"),
                                 end_time=today.strftime("%Y%m%d"))
        reply = xt.get_market_data_ex(
            field_list=["time", *L.COLS[2:]], stock_list=[code],
            period=api, start_time=since.strftime("%Y%m%d"),
            end_time=today.strftime("%Y%m%d"),
            count=-1, dividend_type="none", fill_data=False)
        if not isinstance(reply, dict) or code not in reply:
            raise ValueError("QMT missing requested " + kind + " " + cycle +
                             " response: " + code)
        rows = _normalize_quote(code, reply[code], until=today)
        rows_added[cycle] = _upsert_quote(
            extra, kind, cycle, code, rows, today=today, workspace=workspace)
    return rows_added


def _fetch_financial(xt, extra, code, today, workspace):
    # Empty table lists request every table supported by this particular
    # QMT SDK (Holdernum/HolderNum capitalization differs by release).
    xt.download_financial_data([code], [])
    data = xt.get_financial_data([code], [],
                                 start_time="", end_time="",
                                 report_type="report_time")
    if not isinstance(data, dict) or not isinstance(data.get(code), dict):
        raise ValueError("QMT financial response missing requested symbol " + code)
    summary = {}
    for name, frame in data[code].items():
        if not isinstance(name, str) or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_.]{0,95}", name):
            raise ValueError("Unsafe QMT financial table name: "+repr(name))
        values = dataframe_records(frame)
        if not values:
            continue
        table = snapshot_table(today.isoformat(), code, name, values)
        path = _snapshot_path(extra, "financial/" + name + "/" + code,
                              today.isoformat(), table)
        result = _atomic_parquet(path, table, workspace=workspace)
        summary[name] = {"rows": len(values), "status": result["status"]}
    return summary


def _fetch_adjustments(xt, extra, code, today, since, workspace):
    if not hasattr(xt, "get_divid_factors"):
        raise ValueError("QMT get_divid_factors API not supported")
    # Keep the underlying unadjusted DAILY history available in the QMT
    # cache before reading associated historical corporate actions.
    xt.download_history_data(code, period="1d",
                             start_time=since.strftime("%Y%m%d"),
                             end_time=today.strftime("%Y%m%d"))
    frame = xt.get_divid_factors(code)
    rows = dataframe_records(frame)
    if not rows:
        return {"rows": 0, "status": "NO_SOURCE_RECORDS"}
    table = snapshot_table(today.isoformat(), code, "divid_factors", rows)
    result = _snapshot_write(extra, "adjustments/" + code,
                             today.isoformat(), table, workspace)
    return {"rows": len(rows), "status": result["status"]}


def _fetch_sector_snapshot(xt, extra, today, workspace):
    # Caller refreshed QMT's sector cache before discovering equity/assets.
    names = xt.get_sector_list()
    if not isinstance(names, (list, tuple)) or not names:
        raise ValueError("QMT sector catalog is empty")
    records = []
    for sector in sorted(set(names)):
        members = xt.get_stock_list_in_sector(sector) or []
        for code in sorted(set(members)):
            records.append({"asof": today.isoformat(), "sector": str(sector),
                            "symbol": str(code)})
    if not records:
        raise ValueError("QMT no sector membership records")
    table = pa.Table.from_pylist(records, schema=SECTOR_SCHEMA)
    result = _snapshot_write(extra, "sectors", today.isoformat(),
                             table, workspace)
    return {"sectors": len(set(names)), "memberships": len(records),
            "status": result["status"]}


def _fetch_instrument(xt, extra, kind, code, today, workspace):
    info = xt.get_instrument_detail(code)
    if not info:
        raise ValueError("QMT instrument metadata missing for " + code)
    table = snapshot_table(today.isoformat(), code, "instrument", [info])
    _snapshot_write(extra, kind + "/instruments/" + code,
                    today.isoformat(), table, workspace)
    if kind == "index" and hasattr(xt, "get_index_weight"):
        weights = xt.get_index_weight(code)
        rows = ([{"member": k, "weight": v}
                 for k, v in sorted(weights.items())]
                if isinstance(weights, dict) else dataframe_records(weights))
        if rows:
            table = snapshot_table(today.isoformat(), code, "index_weight",
                                   rows)
            _snapshot_write(extra, "index/weights/" + code,
                            today.isoformat(), table, workspace)


def _fetch_etf_catalog(xt, extra, today, workspace):
    if not hasattr(xt, "download_etf_info") or not hasattr(xt, "get_etf_info"):
        raise ValueError("QMT ETF information APIs unavailable")
    xt.download_etf_info()
    info = xt.get_etf_info()
    if not isinstance(info, dict) or not info:
        raise ValueError("QMT ETF information response is empty")
    table = snapshot_table(today.isoformat(), "*", "etf_info",
                           [{"key": k, "value": v} for k, v in
                            sorted(info.items(), key=lambda pair: str(pair[0]))])
    result = _snapshot_write(extra, "etf/info", today.isoformat(),
                             table, workspace)
    return {"records": len(info), "status": result["status"]}


def run(root, *, xt, apply=False, today=None, since=SINCE,
        stock_limit=40, asset_limit=5, workspace=WORK, progress=print):
    """One bounded, repeatable batch. A complete historical import takes batches."""
    today = today or datetime.now(L.UTC8).date()
    if not isinstance(today, date) or not isinstance(since, date) or today < since:
        raise ValueError("Invalid supplementary requested date range")
    if stock_limit < 0 or asset_limit < 0:
        raise ValueError("Negative batch size")
    extra = _storage(root)
    if not apply:
        universe = discover(xt)
        state = _state(extra, workspace)
        report = {
            "status": "READONLY_PREVIEW", "dataset": str(extra),
            "counts": {key: len(values) for key, values in universe.items()},
            "next": {key: _batch(values, state["cursor"].get(key, ""),
                                stock_limit if key in ("financial", "adjustments")
                                else asset_limit)
                     for key, values in universe.items()},
            "sectors_will_be_downloaded": True,
            "data_files_modified": False,
            "windows_schedule_modified": False,
        }
        progress("MARKET_QMT_EXTRA_SUMMARY=" + canonical_json(report))
        return report
    results = {}
    with LIVE.exclusive_writer():
        # Refresh QMT's sector cache BEFORE deriving all stock/index/ETF
        # universes; never guess unavailable membership.
        xt.download_sector_data()
        universe = discover(xt)
        state = _state(extra, workspace)
        results["sectors"] = _fetch_sector_snapshot(xt, extra, today, workspace)
        results["etf_catalog"] = _fetch_etf_catalog(xt, extra, today, workspace)
        if hasattr(xt, "download_index_weight"):
            xt.download_index_weight()
            results["index_weight_cache"] = "DOWNLOAD_REQUESTED"
        else:
            results["index_weight_cache"] = "API_UNAVAILABLE"
        for key in ("financial", "adjustments", "index", "etf"):
            limit = stock_limit if key in ("financial", "adjustments") else asset_limit
            selected = _batch(universe[key], state["cursor"].get(key, ""), limit)
            done = []
            for code in selected:
                if key == "financial":
                    item = _fetch_financial(xt, extra, code, today, workspace)
                elif key == "adjustments":
                    item = _fetch_adjustments(xt, extra, code, today, since, workspace)
                else:
                    # Once the full historic ticker range is downloaded,
                    # use an overlapping rolling window, rather than asking
                    # the broker for 2011-onward minute history every cycle.
                    previous = state.setdefault("last_asset_fetch", {}).setdefault(
                        key, {}).get(code)
                    start = (max(since, date.fromisoformat(previous)
                                 - timedelta(days=15))
                             if previous else since)
                    _fetch_instrument(xt, extra, key, code, today, workspace)
                    item = _fetch_quotes(
                        xt, extra, key, code, today, start, workspace=workspace)
                    state["last_asset_fetch"][key][code] = today.isoformat()
                _advance(state, key, code, workspace)
                done.append({"symbol": code, "result": item})
                progress("MARKET_QMT_EXTRA_COMMITTED=" + canonical_json(
                    {"section": key, "symbol": code, "result": item}))
            results[key] = {
                "symbols_processed": len(done), "cursor": state["cursor"].get(key, ""),
                "universe_symbols": len(universe[key]),
                "next_batch_required": bool(
                    [x for x in universe[key] if x > state["cursor"].get(key, "")])
            }
        state["last_asof"] = today.isoformat()
        _save_state(state, workspace)
    report = {"status": "BATCH_COMMITTED_MORE_BATCHES_MAY_REMAIN",
              "dataset": str(extra), "asof": today.isoformat(),
              "sections": results, "stock_eight_periods_unchanged": True,
              "h5_unchanged": True}
    progress("MARKET_QMT_EXTRA_SUMMARY=" + canonical_json(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--start", type=date.fromisoformat, default=SINCE)
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--stock-limit", type=int, default=40,
                        help="Equity symbols for financial and dividend each run; 0=all")
    parser.add_argument("--asset-limit", type=int, default=5,
                        help="Index and ETF symbols each run; 0=all")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    from xtquant import xtdata
    run(args.root, xt=xtdata, apply=args.apply, today=args.day, since=args.start,
        stock_limit=args.stock_limit, asset_limit=args.asset_limit)


if __name__ == "__main__":
    main()
