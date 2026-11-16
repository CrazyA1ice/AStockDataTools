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
import subprocess
import sys
import tempfile
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
import live_sync as LIVE
import market_month_storage as S

FORMAT = "qmt_supplementary_parquet_v1"
WORK = Path(__file__).resolve().parent / "work" / "qmt_extra"
FIN_TABLES = ("Balance", "Income", "CashFlow", "Capital", "Top10FlowHolder",
              "Top10Holder", "HolderNum", "PershareIndex", "PerShare")
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


def _read_closed_parquet(path):
    """Read Arrow rows and deterministically release Windows file handles.

    pq.read_table(path) may keep a native dataset handle alive until GC.
    An explicit ParquetFile reader/close is required before os.replace().
    """
    reader = pq.ParquetFile(path)
    try:
        return reader.read()
    finally:
        reader.close()


def _atomic_parquet(path, table, *, workspace=WORK, allow_changed=False):
    """Single-file transactional replacement; backup changed previous bytes."""
    path = Path(path)
    _path_check(path)
    if table.schema not in (RAW_SCHEMA, OHLC_SCHEMA, SECTOR_SCHEMA):
        raise ValueError("Unexpected supplementary Arrow schema")
    path.parent.mkdir(parents=True, exist_ok=True)
    _path_check(path)
    if path.exists():
        old = _read_closed_parquet(path)
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
    check = _read_closed_parquet(scratch)
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


def _within_ohlc_roundoff(actual, boundary):
    """Allow at most four binary64 ULPs of OHLC boundary roundoff.

    Only used after an OHLC ordering comparison fails; never rewrites
    provider values and never makes NaN/Infinity or substantive gaps valid.
    """
    return (math.isfinite(actual) and math.isfinite(boundary)
            and abs(actual - boundary) <=
            4 * max(math.ulp(actual), math.ulp(boundary)))


def _normalize_quote(symbol, frame, *, until, since=None, period=None):
    """Fail closed on invalid QMT bars, identifying the exact source row.

    Diagnostics only: a broker's zero, inconsistent, or non-finite OHLCVA
    must not be silently changed, filled, skipped, or committed.
    """
    if frame is None:
        return []
    records = dataframe_records(frame)
    out = []
    seen = set()
    for row_index, raw in enumerate(records):
        tick = raw.get("time")
        if isinstance(tick, bool) or tick is None:
            raise ValueError("QMT Kline lacks numeric Unix-millisecond time")
        stamp = int(tick)
        if float(tick) != stamp:
            raise ValueError("Fractional QMT index/ETF timestamp")
        if stamp < 946684800000 or stamp > 4102444800000:
            raise ValueError("Unsupported QMT Kline timestamp: " + repr(tick))
        trading = L.market_ts_day(stamp)
        if trading > until or (since is not None and trading < since):
            continue
        if stamp in seen:
            raise ValueError("QMT duplicate Kline timestamp " + symbol)
        seen.add(stamp)
        info = {"period": period, "row_index": row_index,
                "timestamp_ms": stamp, "local_day": trading.isoformat()}
        try:
            numbers = {key: float(raw[key]) for key in L.COLS[2:]}
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            info["reason"] = "missing_or_nonnumeric_ohlcva"
            info["values"] = {key: raw.get(key) for key in L.COLS[2:]}
            raise ValueError("QMT index/ETF Kline OHLCVA invalid: " +
                             symbol + " " + canonical_json(info)) from exc
        violations = []
        if any(not math.isfinite(v) for v in numbers.values()):
            violations.append("non_finite")
        if numbers["volume"] < 0:
            violations.append("negative_volume")
        if numbers["amount"] < 0:
            violations.append("negative_amount")
        if numbers["low"] <= 0:
            violations.append("nonpositive_low")
        low_bound = min(numbers["open"], numbers["close"])
        high_bound = max(numbers["open"], numbers["close"])
        if (numbers["low"] > low_bound
                and not _within_ohlc_roundoff(numbers["low"], low_bound)):
            violations.append("low_above_open_or_close")
        if (numbers["high"] < high_bound
                and not _within_ohlc_roundoff(numbers["high"], high_bound)):
            violations.append("high_below_open_or_close")
        if violations:
            info["violations"] = violations
            info["values"] = numbers
            raise ValueError("QMT index/ETF Kline OHLCVA invalid: " +
                             symbol + " " + canonical_json(info))
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
        old = _read_closed_parquet(path).to_pylist() if path.exists() else []
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


def _fetch_quotes(xt, extra, kind, code, today, since, *,
                  workspace, progress=print):
    """Year-bounded QMT calls; never allocate 16 years of 1m in memory."""
    rows_added = {}
    any_rows_observed = False
    for cycle, api in API_PERIODS.items():
        total = 0
        observed = 0
        begin = since
        while begin <= today:
            end = min(today, date(begin.year, 12, 31))
            # QMT data availability is provider-specific; an empty response
            # never authorizes creating artificial bars.
            progress("MARKET_QMT_EXTRA_QUOTE_WINDOW_START=" + canonical_json(
                {"section": kind, "symbol": code, "period": cycle,
                 "since": begin.isoformat(), "until": end.isoformat()}))
            xt.download_history_data(code, period=api,
                                     start_time=begin.strftime("%Y%m%d"),
                                     end_time=end.strftime("%Y%m%d"))
            reply = xt.get_market_data_ex(
                field_list=["time", *L.COLS[2:]], stock_list=[code],
                period=api, start_time=begin.strftime("%Y%m%d"),
                end_time=end.strftime("%Y%m%d"),
                count=-1, dividend_type="none", fill_data=False)
            if not isinstance(reply, dict):
                raise ValueError("QMT returned invalid " + kind + " " + cycle +
                                 " response: " + code + " year=" + str(begin.year))
            if code not in reply:
                # The asset may not have existed in this historical year.
                # Do not fabricate records; later years are still queried.
                progress("MARKET_QMT_EXTRA_QUOTE_WINDOW_EMPTY=" + canonical_json(
                    {"section": kind, "symbol": code, "period": cycle,
                     "since": begin.isoformat(), "until": end.isoformat()}))
                begin = end + timedelta(days=1)
                continue
            rows = _normalize_quote(
                code, reply[code], since=begin, until=end, period=cycle)
            observed += len(rows)
            changed = _upsert_quote(
                extra, kind, cycle, code, rows, today=today,
                workspace=workspace)
            total += changed
            progress("MARKET_QMT_EXTRA_QUOTE_WINDOW_DONE=" + canonical_json(
                {"section": kind, "symbol": code, "period": cycle,
                 "since": begin.isoformat(), "until": end.isoformat(),
                 "observed": len(rows), "added": changed}))
            begin = end + timedelta(days=1)
        rows_added[cycle] = {"added": total, "observed": observed}
        any_rows_observed = any_rows_observed or observed > 0
    if not any_rows_observed:
        raise ValueError("QMT returned zero index/ETF OHLCVA for all eight "
                         "periods: "+kind+" "+code)
    return rows_added


def _financial_active_path(extra, code, name, asof):
    return extra / "financial" / name / code / "active" / (asof + ".json")


def _financial_snapshot_file(extra, code, name, asof):
    """Select only an unambiguous legacy snapshot or a pinned version.

    A pin permits historical immutable versions with the same observation
    date; no guessing from newest filename, mtime, or row count.
    """
    code = valid_code(code)
    if name not in FIN_TABLES:
        raise ValueError("Unsupported QMT financial table " + str(name))
    folder = extra / "financial" / name / code / "snapshots"
    pin_path = _financial_active_path(extra, code, name, asof)
    _path_check(folder)
    _path_check(pin_path)
    candidates = sorted(folder.glob(asof + "-*.parquet")) if folder.exists() else []
    if not pin_path.exists():
        if len(candidates) > 1:
            raise ValueError("Ambiguous QMT financial snapshots: " +
                             code + " table=" + name + " asof=" + asof)
        return candidates[0] if candidates else None
    if not pin_path.is_file() or pin_path.is_symlink():
        raise ValueError("Linked/invalid QMT financial active pin")
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    if (not isinstance(pin, dict)
            or pin.get("format") != "qmt_financial_active_v1"
            or pin.get("symbol") != code or pin.get("table") != name
            or pin.get("asof") != asof
            or not isinstance(pin.get("filename"), str)
            or not re.fullmatch(re.escape(asof) + r"-[0-9a-f]{16}\.parquet",
                                pin["filename"])
            or not isinstance(pin.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])):
        raise ValueError("Invalid QMT financial active pin: " + str(pin_path))
    selected = folder / pin["filename"]
    _path_check(selected)
    if selected not in candidates or not selected.is_file():
        raise ValueError("Missing QMT financial active snapshot: " + str(selected))
    if L.hash_file(selected) != pin["sha256"]:
        raise ValueError("QMT financial active snapshot SHA mismatch: " +
                         str(selected))
    return selected


def _verify_financial_snapshot_file(extra, code, name, asof, path):
    """Verify row identity, Arrow schema and immutable filename fingerprint."""
    _path_check(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Invalid QMT financial snapshot path: " + str(path))
    table = _read_closed_parquet(path)
    if table.schema != RAW_SCHEMA or table.num_rows <= 0:
        raise ValueError("QMT financial snapshot schema/rows invalid: " + str(path))
    for index, row in enumerate(table.to_pylist()):
        if (row["asof"] != asof or row["symbol"] != code
                or row["item"] != name or row["index"] != index
                or not isinstance(row["payload_json"], str)):
            raise ValueError("QMT financial snapshot identity invalid: " + str(path))
    expected = _snapshot_path(
        extra, "financial/" + name + "/" + code, asof, table)
    if expected != path:
        raise ValueError("QMT financial snapshot fingerprint mismatch: " + str(path))
    return table


def _verified_financial_snapshot(extra, code, name, asof):
    """Verified immutable selected snapshot rows, NOT proof of source coverage."""
    path = _financial_snapshot_file(extra, code, name, asof)
    if path is None:
        return None
    return _verify_financial_snapshot_file(extra, code, name, asof, path).num_rows


def _pin_financial_snapshot(extra, code, name, asof, path):
    """Atomically select a verified version while retaining all old files."""
    _verify_financial_snapshot_file(extra, code, name, asof, path)
    pin_path = _financial_active_path(extra, code, name, asof)
    _path_check(pin_path)
    S._save(pin_path, {
        "format": "qmt_financial_active_v1", "symbol": code,
        "table": name, "asof": asof, "filename": path.name,
        "sha256": L.hash_file(path)})
    if _financial_snapshot_file(extra, code, name, asof) != path:
        raise ValueError("QMT financial pin readback mismatch")


def _financial_snapshot_rows(extra, code, name, asof):
    """Read active verified JSON payloads for conservative superset comparison."""
    path = _financial_snapshot_file(extra, code, name, asof)
    if path is None:
        return None
    table = _verify_financial_snapshot_file(extra, code, name, asof, path)
    data = [json.loads(x) for x in table.column("payload_json").to_pylist()]
    if any(not isinstance(x, dict) for x in data):
        raise ValueError("Invalid financial snapshot JSON payload")
    return data


class FinancialDeferredError(Exception):
    """Only a failed isolated QMT worker is eligible for queued retry."""

    def __init__(self, code, table, cause):
        self.code = code
        self.table = table
        self.cause = str(cause)[:500]
        super().__init__(code + " table=" + table + ": " + self.cause)


def _pending_financial(state):
    pending = state.setdefault("financial_pending", {})
    if not isinstance(pending, dict):
        raise ValueError("QMT financial pending queue is malformed")
    for code, entry in pending.items():
        if (valid_code(code) != code or not isinstance(entry, dict)
                or entry.get("table") not in FIN_TABLES
                or not isinstance(entry.get("attempts"), int)
                or entry["attempts"] < 1):
            raise ValueError("Invalid pending QMT financial security: " + str(code))
    return pending


def _financial_selection(universe, state, limit, *, tolerate=False,
                         retry_pending=False):
    """High-water scan never wraps in opt-in tolerant mode.

    Pending retries are separately addressed. No failed security can silently
    become a successful security because the lexical scan passed its code.
    """
    if not tolerate:
        return _batch(universe, state["cursor"].get("financial", ""), limit)
    pending = _pending_financial(state)
    if retry_pending:
        missing = sorted(set(pending) - set(universe))
        if missing:
            raise ValueError("Pending QMT securities missing from universe: " +
                             canonical_json(missing[:20]))
        selected = sorted(pending)
    else:
        previous = state["cursor"].get("financial", "")
        selected = [code for code in sorted(set(universe))
                    if code > previous]
    return selected[:limit] if limit else selected


def _financial_defer(state, workspace, code, asof, failure, *, retry_pending):
    pending = _pending_financial(state)
    prior = pending.get(code, {})
    pending[code] = {
        "status": "PENDING_RETRY", "table": failure.table,
        "reason": failure.cause, "asof": asof,
        "attempts": prior.get("attempts", 0) + 1,
        "updated_at": datetime.now(L.UTC8).isoformat()}
    # The pending receipt and high-water cursor are written ATOMICALLY in
    # the same progress.json transaction. On crash they advance together.
    if not retry_pending:
        state["cursor"]["financial"] = code
    _save_state(state, workspace)
    return pending[code]


def _financial_coverage_receipt(workspace, code, asof, report):
    """Audit-only report of observed QMT row counts; not completeness proof."""
    workspace = Path(workspace)
    _path_check(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / "financial-coverage.jsonl"
    _path_check(path)
    entry = {
        "asof": asof, "symbol": code,
        "tables": report,
        "low_record_tables": [name for name in FIN_TABLES
                              if 0 < report[name]["rows"] < 20],
        "empty_source_tables": [name for name in FIN_TABLES
                                if report[name]["rows"] == 0],
        "coverage_status": "UNVERIFIED_HISTORICAL_COMPLETENESS"}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(canonical_json(entry) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _record_financial_failure(workspace, code, name, asof, reason, detail):
    """Append-only pending retry record; never marks a security complete."""
    workspace = Path(workspace)
    _path_check(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / "financial-failures.jsonl"
    _path_check(path)
    entry = {
        "at": datetime.now(L.UTC8).isoformat(), "asof": asof,
        "symbol": code, "table": name, "status": "PENDING_RETRY",
        "reason": reason, "detail": str(detail)[:500]}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(canonical_json(entry) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _read_financial_isolated(code, name, workspace, *, timeout_seconds,
                             asof, progress=print):
    """Run QMT financial calls in a killable worker; no worker Parquet writes."""
    code = valid_code(code)
    if name not in FIN_TABLES or not isinstance(timeout_seconds, int):
        raise ValueError("Invalid QMT financial worker arguments")
    if not 30 <= timeout_seconds <= 3600:
        raise ValueError("QMT financial timeout must be 30..3600 seconds")
    workspace = Path(workspace)
    _path_check(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="financial-worker-",
                                     dir=str(workspace)) as dirname:
        output = Path(dirname) / "records.json"
        command = [
            sys.executable, "-u", "-B",
            str(Path(__file__).resolve().with_name(
                "qmt_extra_financial_worker.py")),
            "--symbol", code, "--table", name, "--output", str(output)]
        progress("MARKET_QMT_EXTRA_FINANCIAL_WORKER_START=" +
                 canonical_json({"symbol": code, "table": name,
                                 "timeout_seconds": timeout_seconds}))
        try:
            completed = subprocess.run(command, timeout=timeout_seconds,
                                       check=False)
        except subprocess.TimeoutExpired as exc:
            _record_financial_failure(
                workspace, code, name, asof, "TIMEOUT",
                "QMT financial worker exceeded " +
                str(timeout_seconds) + " seconds")
            progress("MARKET_QMT_EXTRA_FINANCIAL_WORKER_TIMEOUT=" +
                     canonical_json({"symbol": code, "table": name,
                                     "timeout_seconds": timeout_seconds}))
            raise TimeoutError(
                "QMT financial worker timeout: " + code +
                " table=" + name + " seconds=" +
                str(timeout_seconds)) from exc
        if completed.returncode != 0:
            _record_financial_failure(
                workspace, code, name, asof, "WORKER_NONZERO_EXIT",
                "exit code=" + str(completed.returncode))
            raise RuntimeError(
                "QMT financial worker failed: " + code +
                " table=" + name + " exit=" + str(completed.returncode))
        try:
            _path_check(output)
            if not output.is_file() or output.is_symlink():
                raise ValueError("QMT worker produced no result file")
            if output.stat().st_size > 128 * 1024 * 1024:
                raise ValueError("QMT financial worker result too large")
            payload = json.loads(output.read_text(encoding="utf-8"))
            if (not isinstance(payload, dict)
                    or payload.get("format") != "qmt_financial_worker_v1"
                    or payload.get("symbol") != code
                    or payload.get("table") != name
                    or not isinstance(payload.get("records"), list)
                    or len(payload["records"]) > 100000
                    or any(not isinstance(row, dict) or
                           not isinstance(row.get("_index"), str)
                           for row in payload["records"])):
                raise ValueError("Invalid QMT financial worker payload")
            values = payload["records"]
        except (ValueError, OSError, UnicodeError, TypeError) as exc:
            _record_financial_failure(
                workspace, code, name, asof, "INVALID_WORKER_RESULT", exc)
            raise
        progress("MARKET_QMT_EXTRA_FINANCIAL_WORKER_DONE=" +
                 canonical_json({"symbol": code, "table": name,
                                 "rows": len(values)}))
        return values


def _fetch_financial(xt, extra, code, today, workspace, progress=print,
                     financial_timeout_seconds=None):
    """Download one QMT financial table at a time, emitting exact stop point.

    QMT's empty table_list expands to every report internally with no
    per-table visibility. Each verified table remains durable if the next
    table fails; the stock cursor advances only after all tables succeed.
    """
    summary = {}
    for name in FIN_TABLES:
        cached_rows = _verified_financial_snapshot(
            extra, code, name, today.isoformat())
        if cached_rows is not None:
            summary[name] = {"rows": cached_rows, "status": "REUSED_VERIFIED"}
            progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_REUSED=" +
                     canonical_json({"symbol": code, "table": name,
                                     **summary[name]}))
            progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_COMPLETE=" +
                     canonical_json({"symbol": code, "table": name,
                                     **summary[name]}))
            continue
        progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_START=" +
                 canonical_json({"symbol": code, "table": name,
                                 "api": "download_financial_data"}))
        if financial_timeout_seconds is not None:
            try:
                values = _read_financial_isolated(
                    code, name, workspace,
                    timeout_seconds=financial_timeout_seconds,
                    asof=today.isoformat(), progress=progress)
            except (TimeoutError, RuntimeError, ValueError) as exc:
                # Operating-system/disk errors must fail closed rather than
                # treating an unavailable local dataset as a broker failure.
                # Do not classify corrupted EXISTING Parquet or parent
                # serialization failures as provider retryable errors.
                raise FinancialDeferredError(code, name, exc) from exc
        else:
            # In-process fake XT for unit tests; live CLI uses the watchdog.
            xt.download_financial_data([code], [name])
            progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_FETCHED=" +
                     canonical_json({"symbol": code, "table": name}))
            progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_READ_START=" +
                     canonical_json({"symbol": code, "table": name,
                                     "api": "get_financial_data"}))
            data = xt.get_financial_data([code], [name],
                                         start_time="", end_time="",
                                         report_type="report_time")
            progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_READ_DONE=" +
                     canonical_json({"symbol": code, "table": name}))
            if not isinstance(data, dict) or not isinstance(data.get(code), dict):
                raise ValueError("QMT financial response missing requested symbol " + code
                                 + " table=" + name)
            received = data[code]
            if set(received) - {name}:
                raise ValueError("QMT financial response unexpected table for " +
                                 code + " requested=" + name +
                                 " keys=" + canonical_json(sorted(received)))
            progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_DECODE_START=" +
                     canonical_json({"symbol": code, "table": name}))
            values = dataframe_records(received.get(name))
            progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_DECODE_DONE=" +
                     canonical_json({"symbol": code, "table": name,
                                     "rows": len(values)}))
        if not values:
            summary[name] = {"rows": 0, "status": "NO_SOURCE_RECORDS"}
        else:
            progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_SNAPSHOT_START=" +
                     canonical_json({"symbol": code, "table": name,
                                     "rows": len(values)}))
            table = snapshot_table(today.isoformat(), code, name, values)
            path = _snapshot_path(extra, "financial/" + name + "/" + code,
                                  today.isoformat(), table)
            progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_SAVE_START=" +
                     canonical_json({"symbol": code, "table": name,
                                     "rows": len(values)}))
            result = _atomic_parquet(path, table, workspace=workspace)
            progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_SAVE_DONE=" +
                     canonical_json({"symbol": code, "table": name,
                                     "status": result["status"]}))
            summary[name] = {"rows": len(values), "status": result["status"]}
        progress("MARKET_QMT_EXTRA_FINANCIAL_TABLE_COMPLETE=" +
                 canonical_json({"symbol": code, "table": name, **summary[name]}))
    return summary


def _fetch_adjustments(xt, extra, code, today, since, workspace,
                       progress=print):
    if not hasattr(xt, "get_divid_factors"):
        raise ValueError("QMT get_divid_factors API not supported")
    # Keep the underlying unadjusted DAILY history available in the QMT
    # cache before reading associated historical corporate actions.
    progress("MARKET_QMT_EXTRA_DIVIDEND_DAILY_START=" + code)
    xt.download_history_data(code, period="1d",
                             start_time=since.strftime("%Y%m%d"),
                             end_time=today.strftime("%Y%m%d"))
    progress("MARKET_QMT_EXTRA_DIVIDEND_FACTORS_START=" + code)
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
    result = {"instrument": "SNAPSHOT_COMMITTED"}
    if kind == "index":
        if not hasattr(xt, "get_index_weight"):
            result["index_weights"] = {
                "status": "API_NOT_EXPOSED", "api": "get_index_weight"}
            return result
        weights = _optional_capability(
            "get_index_weight", lambda: xt.get_index_weight(code))
        if (isinstance(weights, dict) and
                weights.get("status") == "UNSUPPORTED_CLIENT_FUNCTION"):
            result["index_weights"] = weights
            return result
        rows = ([{"member": k, "weight": v}
                 for k, v in sorted(weights.items())]
                if isinstance(weights, dict) else dataframe_records(weights))
        if rows:
            table = snapshot_table(today.isoformat(), code, "index_weight",
                                   rows)
            save = _snapshot_write(extra, "index/weights/" + code,
                                   today.isoformat(), table, workspace)
            result["index_weights"] = {
                "status": save["status"], "records": len(rows)}
        else:
            result["index_weights"] = {"status": "NO_SOURCE_RECORDS"}
    return result


def _qmt_client_unsupported(exc):
    """Classify only the observed QMT terminal ErrorID=300000 failure.

    Never convert arbitrary SDK/network, permission, corrupted data, or
    filesystem errors into an apparently successful optional API skip.
    """
    msg = str(exc)
    return (isinstance(exc, RuntimeError) and "300000" in msg
            and ("function not realize" in msg
                 or "当前客户端未支持此功能" in msg))


def _optional_capability(name, callback):
    try:
        return callback()
    except RuntimeError as exc:
        if not _qmt_client_unsupported(exc):
            raise
        return {"status": "UNSUPPORTED_CLIENT_FUNCTION",
                "api": name, "qmt_error_id": 300000,
                "detail": "QMT client does not implement or license this API"}


def _fetch_etf_catalog(xt, extra, today, workspace):
    if not hasattr(xt, "download_etf_info") or not hasattr(xt, "get_etf_info"):
        return {"status": "API_NOT_EXPOSED",
                "api": "download_etf_info/get_etf_info"}
    download = _optional_capability("download_etf_info", xt.download_etf_info)
    if isinstance(download, dict) and download.get("status") == "UNSUPPORTED_CLIENT_FUNCTION":
        return download
    info = _optional_capability("get_etf_info", xt.get_etf_info)
    if isinstance(info, dict) and info.get("status") == "UNSUPPORTED_CLIENT_FUNCTION":
        return info
    if not isinstance(info, dict) or not info:
        raise ValueError("QMT ETF information response is empty")
    table = snapshot_table(today.isoformat(), "*", "etf_info",
                           [{"key": k, "value": v} for k, v in
                            sorted(info.items(), key=lambda pair: str(pair[0]))])
    result = _snapshot_write(extra, "etf/info", today.isoformat(),
                             table, workspace)
    return {"records": len(info), "status": result["status"]}


def run(root, *, xt, apply=False, today=None, since=SINCE,
        stock_limit=40, asset_limit=5, section="all",
        workspace=WORK, progress=print, financial_timeout_seconds=None,
        financial_continue_on_error=False, financial_retry_pending=False):
    """One bounded, repeatable batch. A complete historical import takes batches."""
    today = today or datetime.now(L.UTC8).date()
    if not isinstance(today, date) or not isinstance(since, date) or today < since:
        raise ValueError("Invalid supplementary requested date range")
    if stock_limit < 0 or asset_limit < 0:
        raise ValueError("Negative batch size")
    if section not in ("all", "sectors", "financial",
                       "adjustments", "index", "etf"):
        raise ValueError("Unsupported QMT extras section " + str(section))
    if (financial_continue_on_error or financial_retry_pending) and section != "financial":
        raise ValueError("Financial retry options require --section financial")
    if financial_retry_pending and not financial_continue_on_error:
        raise ValueError("Pending retry requires explicit financial continue-on-error")
    selected_sections = (("financial", "adjustments", "index", "etf")
                         if section == "all" else (section,))
    extra = _storage(root)
    if not apply:
        universe = discover(xt) if section != "sectors" else {}
        state = _state(extra, workspace)
        report = {
            "status": "READONLY_PREVIEW", "dataset": str(extra),
            "section": section,
            "counts": {key: len(values) for key, values in universe.items()
                       if key in selected_sections},
            "next": {key: (_financial_selection(
                            values, state, stock_limit,
                            tolerate=financial_continue_on_error,
                            retry_pending=financial_retry_pending)
                          if key == "financial" else
                          _batch(values, state["cursor"].get(key, ""),
                                 stock_limit if key == "adjustments"
                                 else asset_limit))
                     for key, values in universe.items()
                     if key in selected_sections},
            "financial_pending_count": (len(_pending_financial(state))
                                        if "financial" in selected_sections
                                        else 0),
            "financial_retry_mode": financial_retry_pending,
            "sectors_will_be_downloaded": section in ("all", "sectors"),
            "data_files_modified": False,
            "windows_schedule_modified": False,
        }
        progress("MARKET_QMT_EXTRA_SUMMARY=" + canonical_json(report))
        return report
    results = {}
    with LIVE.exclusive_writer():
        # Refresh QMT's sector cache BEFORE deriving all stock/index/ETF
        # universes; never guess unavailable membership.
        if section in ("all", "sectors"):
            progress("MARKET_QMT_EXTRA_STAGE_START=download_sector_data")
            xt.download_sector_data()
            progress("MARKET_QMT_EXTRA_STAGE_DONE=download_sector_data")
        universe = discover(xt) if section != "sectors" else {}
        state = _state(extra, workspace)
        if section in ("all", "sectors"):
            progress("MARKET_QMT_EXTRA_STAGE_START=sector_snapshot")
            results["sectors"] = _fetch_sector_snapshot(xt, extra, today, workspace)
            progress("MARKET_QMT_EXTRA_STAGE_DONE=sector_snapshot")
        if section in ("all", "etf"):
            results["etf_catalog"] = _fetch_etf_catalog(xt, extra, today, workspace)
            progress("MARKET_QMT_EXTRA_ETF_CATALOG=" +
                     canonical_json(results["etf_catalog"]))
        if section in ("all", "index"):
            progress("MARKET_QMT_EXTRA_STAGE_START=download_index_weight")
            if hasattr(xt, "download_index_weight"):
                index_fetch = _optional_capability(
                    "download_index_weight", xt.download_index_weight)
                results["index_weight_cache"] = (
                    index_fetch if isinstance(index_fetch, dict)
                    else {"status": "DOWNLOADED"})
            else:
                results["index_weight_cache"] = {
                    "status": "API_NOT_EXPOSED", "api": "download_index_weight"}
            progress("MARKET_QMT_EXTRA_INDEX_WEIGHT_CACHE=" +
                     canonical_json(results["index_weight_cache"]))
        for key in ("financial", "adjustments", "index", "etf"):
            if key not in selected_sections:
                continue
            limit = stock_limit if key in ("financial", "adjustments") else asset_limit
            selected = (_financial_selection(
                universe[key], state, limit,
                tolerate=financial_continue_on_error,
                retry_pending=financial_retry_pending)
                if key == "financial" else
                _batch(universe[key], state["cursor"].get(key, ""), limit))
            done = []
            deferred = []
            for code in selected:
                progress("MARKET_QMT_EXTRA_SYMBOL_START=" +
                         canonical_json({"section": key, "symbol": code}))
                if key == "financial":
                    try:
                        item = _fetch_financial(
                            xt, extra, code, today, workspace, progress=progress,
                            financial_timeout_seconds=financial_timeout_seconds)
                    except FinancialDeferredError as exc:
                        if not financial_continue_on_error:
                            raise
                        pending = _financial_defer(
                            state, workspace, code, today.isoformat(), exc,
                            retry_pending=financial_retry_pending)
                        deferred.append({"symbol": code, "table": exc.table,
                                         "attempts": pending["attempts"]})
                        progress("MARKET_QMT_EXTRA_FINANCIAL_DEFERRED=" +
                                 canonical_json({"symbol": code, **pending}))
                        continue
                    _financial_coverage_receipt(
                        workspace, code, today.isoformat(), item)
                    if financial_continue_on_error:
                        # Retrying an earlier pending security MUST NOT rewind
                        # the high-water cursor for unvisited securities.
                        _pending_financial(state).pop(code, None)
                        if financial_retry_pending:
                            _save_state(state, workspace)
                        else:
                            _advance(state, key, code, workspace)
                    else:
                        _advance(state, key, code, workspace)
                elif key == "adjustments":
                    item = _fetch_adjustments(xt, extra, code, today, since,
                                              workspace, progress=progress)
                else:
                    # Once the full historic ticker range is downloaded,
                    # use an overlapping rolling window, rather than asking
                    # the broker for 2011-onward minute history every cycle.
                    previous = state.setdefault("last_asset_fetch", {}).setdefault(
                        key, {}).get(code)
                    start = (max(since, date.fromisoformat(previous)
                                 - timedelta(days=15))
                             if previous else since)
                    instrument = _fetch_instrument(
                        xt, extra, key, code, today, workspace)
                    item = {"instrument": instrument, "quotes": _fetch_quotes(
                        xt, extra, key, code, today, start,
                        workspace=workspace, progress=progress)}
                    state["last_asset_fetch"][key][code] = today.isoformat()
                if key != "financial":
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
            if key == "financial":
                results[key].update({
                    "symbols_deferred": len(deferred),
                    "pending_retry_count": len(_pending_financial(state)),
                    "pending_retry_symbols": sorted(_pending_financial(state))[:20],
                    "retry_mode": financial_retry_pending,
                    "scan_exhausted": not results[key]["next_batch_required"]
                    if financial_continue_on_error else False})
        state["last_asof"] = today.isoformat()
        _save_state(state, workspace)
    report = {"status": ("BATCH_HAS_PENDING_FINANCIAL_RETRIES"
                         if "financial" in results and
                         results["financial"]["pending_retry_count"] > 0
                         else "BATCH_COMMITTED_MORE_BATCHES_MAY_REMAIN"),
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
    parser.add_argument("--section", choices=("all", "sectors", "financial",
                                              "adjustments", "index", "etf"),
                        default="all")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--financial-timeout-seconds", type=int, default=180,
                        help="QMT per-financial-table wall timeout, 30..3600 seconds")
    parser.add_argument("--financial-continue-on-error", action="store_true",
                        help="Opt-in fail-closed queued scan; does not mark failed stocks done")
    parser.add_argument("--financial-retry-pending", action="store_true",
                        help="Explicit retry of queued failed financial stocks")
    args = parser.parse_args(argv)
    if not 30 <= args.financial_timeout_seconds <= 3600:
        parser.error("--financial-timeout-seconds must be 30..3600")
    from xtquant import xtdata
    run(args.root, xt=xtdata, apply=args.apply, today=args.day, since=args.start,
        stock_limit=args.stock_limit, asset_limit=args.asset_limit,
        section=args.section,
        financial_timeout_seconds=args.financial_timeout_seconds,
        financial_continue_on_error=args.financial_continue_on_error,
        financial_retry_pending=args.financial_retry_pending)


if __name__ == "__main__":
    main()
