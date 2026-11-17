#!/usr/bin/env python3
"""QMT Finance cache -> immutable isolated Parquet, plus bounded daily refresh.

Import mode NEVER calls a download API: batch-read existing QMT local cache.
Daily mode downloads only an announcement-date window via financial_data2
and then reads full cached histories to detect additions / source revisions.
No purchase-price, H5, schedule, or old financial scan-cursor modifications.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from time import monotonic

import qmt_extra_data as E

FORMAT = "qmt_financial_cache_import_v1"
MAX_GROUP = 20
MAX_PAYLOAD = 256 * 1024 * 1024
STATE_FILE = "financial-cache-progress.json"


class QMTCacheDecodeError(RuntimeError):
    """Verified provider UnicodeDecodeError only, not a generic source outage."""


def _state_file(workspace):
    path = Path(workspace) / STATE_FILE
    E._path_check(path)
    return path


def _state(extra, workspace):
    path = _state_file(workspace)
    if not path.exists():
        return {"format": FORMAT, "root": str(extra.resolve()),
                "import_cursor": "", "daily_date": "",
                "daily_cursor": "", "pending": {},
                "daily_sweep_start": "", "daily_sweep_reached_end": False,
                "daily_sweep_finished": ""}
    if not path.is_file() or path.is_symlink():
        raise ValueError("Invalid QMT cache import progress file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("format") != FORMAT
            or data.get("root") != str(extra.resolve())
            or not isinstance(data.get("import_cursor"), str)
            or not isinstance(data.get("daily_date"), str)
            or not isinstance(data.get("daily_cursor"), str)
            or not isinstance(data.get("pending"), dict)
            or not isinstance(data.get("daily_sweep_start", ""), str)
            or not isinstance(data.get("daily_sweep_reached_end", False), bool)
            or not isinstance(data.get("daily_sweep_finished", ""), str)):
        raise ValueError("Financial cache progress identity malformed")
    for code, entry in data["pending"].items():
        if (E.valid_code(code) != code or
                not isinstance(entry, dict) or
                entry.get("reason") not in
                ("NO_CACHE", "SOURCE_HISTORY_CONFLICT",
                 "CACHE_DECODE_ERROR") or
                not isinstance(entry.get("attempts"), int) or
                entry["attempts"] < 1):
            raise ValueError("Financial cache pending entry malformed")
    data.setdefault("daily_sweep_start", "")
    data.setdefault("daily_sweep_reached_end", False)
    data.setdefault("daily_sweep_finished", "")
    return data


def _save_state(workspace, state):
    E.S._save(_state_file(workspace), state)


def _rows(records):
    if any(not isinstance(row, dict) for row in records):
        raise ValueError("Malformed financial cache records")
    return Counter(E.canonical_json(
        {k: v for k, v in row.items() if k != "_index"})
        for row in records)


def _latest_snapshot_day(extra, code, table):
    folder = extra / "financial" / table / code / "snapshots"
    E._path_check(folder)
    if not folder.exists():
        return None
    dates = set()
    for path in folder.glob("*.parquet"):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{16}\.parquet",
                        path.name):
            dates.add(path.name[:10])
        else:
            # Fail closed rather than choosing arbitrary material.
            raise ValueError("Unexpected QMT financial snapshot name: " + str(path))
    return max(dates) if dates else None


def _prior_rows(extra, code, table):
    """Compare with UNION of all selected historical versions, not only latest.

    Existing old observations can contain unique records missing from a
    newer but incomplete snapshot; no previous record may silently vanish.
    """
    folder = extra / "financial" / table / code / "snapshots"
    E._path_check(folder)
    if not folder.exists():
        return None, None
    dates = set()
    for path in folder.glob("*.parquet"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{16}\.parquet",
                            path.name):
            raise ValueError("Unexpected QMT financial snapshot name: " +
                             str(path))
        dates.add(path.name[:10])
    if not dates:
        return None, None
    combined = Counter()
    for day in sorted(dates):
        old = E._financial_snapshot_rows(extra, code, table, day)
        if old is None:
            raise ValueError("Missing previous QMT financial source observation")
        combined |= _rows(old)
    return max(dates), combined


def _plan_symbol(extra, code, asof, source):
    if set(source) != set(E.FIN_TABLES):
        raise ValueError("QMT cache extraction omitted financial tables")
    result = {}
    staged = {}
    for table in E.FIN_TABLES:
        fresh = source[table]
        if (not isinstance(fresh, list) or
                any(not isinstance(row, dict) or
                    not isinstance(row.get("_index"), str) for row in fresh) or
                len(fresh) > 100000):
            raise ValueError("Invalid QMT cache response " + code + " " + table)
        old_date, saved = _prior_rows(extra, code, table)
        current = _rows(fresh)
        saved = saved or Counter()
        missing = saved - current
        if missing:
            raise ValueError("SOURCE_HISTORY_CONFLICT " + code +
                             " table=" + table + " removed_or_revised=" +
                             str(sum(missing.values())))
        if old_date is not None and old_date > asof:
            raise ValueError("QMT source observation older than saved snapshot")
        action = ("NO_SOURCE_RECORDS" if not fresh and old_date is None else
                  "UNCHANGED" if saved == current else "CREATE_VERSION")
        result[table] = {"rows": len(fresh), "previous_rows": sum(saved.values()),
                         "action": action, "previous_asof": old_date,
                         "extra_records": sum((current - saved).values())}
        if action == "CREATE_VERSION":
            staged[table] = fresh
    return result, staged


def _commit_symbol(extra, workspace, code, asof, source):
    """Validate ALL nine tables before any Parquet write for this stock."""
    report, staged = _plan_symbol(extra, code, asof, source)
    for table, records in staged.items():
        group = "financial/" + table + "/" + code
        # Same-day old version always pinned before a second immutable file.
        previous = E._financial_snapshot_file(extra, code, table, asof)
        pin = E._financial_active_path(extra, code, table, asof)
        if previous is not None and not pin.exists():
            E._pin_financial_snapshot(extra, code, table, asof, previous)
        arrow = E.snapshot_table(asof, code, table, records)
        path = E._snapshot_path(extra, group, asof, arrow)
        saved = E._snapshot_write(extra, group, asof, arrow, workspace)
        E._verify_financial_snapshot_file(extra, code, table, asof, path)
        E._pin_financial_snapshot(extra, code, table, asof, path)
        report[table]["commit_status"] = saved["status"]
        report[table]["snapshot"] = path.name
    # Existing coverage events already convey 'source not complete' status.
    E._financial_coverage_receipt(workspace, code, asof, report)
    return report


def _worker_batch(symbols, mode, asof, lookback_days, workspace, timeout_seconds,
                  progress=print):
    """Isolated one-request-for-nine-tables worker; non-destructive on failure."""
    if (not 1 <= len(symbols) <= MAX_GROUP or
            symbols != sorted(set(symbols)) or
            any(E.valid_code(s) != s for s in symbols)):
        raise ValueError("Invalid QMT cached financial worker group")
    workspace = Path(workspace)
    E._path_check(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    end = date.fromisoformat(asof)
    start = (end - timedelta(days=lookback_days)).strftime("%Y%m%d")
    with tempfile.TemporaryDirectory(prefix="finance-cache-batch-",
                                     dir=str(workspace)) as dirname:
        path = Path(dirname) / "records.json"
        cmd = [sys.executable, "-u", "-B",
               str(Path(__file__).resolve().with_name(
                   "qmt_extra_financial_cache_worker.py")),
               "--symbols", ",".join(symbols), "--output", str(path),
               "--mode", mode]
        if mode == "daily":
            cmd += ["--start", start, "--end", end.strftime("%Y%m%d")]
        # Retry exactly once ONLY on dedicated UTF-8 decode failure.
        # A transient truncated provider response can recover on the retry.
        for attempt in (1, 2):
            try:
                completed = subprocess.run(
                    cmd, timeout=timeout_seconds, check=False)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(
                    "QMT cache financial batch worker timed out: " +
                    E.canonical_json(symbols)) from exc
            if completed.returncode == 85:
                if path.exists():
                    raise ValueError("UTF-8 failed worker left unexpected output")
                progress("QMT_CACHE_BATCH_UTF8_RETRY=" + E.canonical_json({
                    "symbols": symbols, "attempt": attempt}))
                if attempt == 2:
                    raise QMTCacheDecodeError(
                        "QMT reported repeated UTF-8 decode failures: " +
                        E.canonical_json(symbols))
                continue
            if completed.returncode != 0:
                raise RuntimeError(
                    "QMT cache batch worker nonzero exit=" +
                    str(completed.returncode) + " stocks=" +
                    E.canonical_json(symbols))
            break
        E._path_check(path)
        if (not path.is_file() or path.is_symlink() or
                path.stat().st_size > MAX_PAYLOAD):
            raise ValueError("Invalid QMT cache worker result file")
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected_missing = set(symbols)
        if (not isinstance(payload, dict) or
                payload.get("format") != "qmt_financial_cache_batch_v1" or
                payload.get("mode") != mode or
                payload.get("symbols") != symbols or
                not isinstance(payload.get("records"), dict) or
                not isinstance(payload.get("missing_symbols"), list) or
                not isinstance(payload.get("row_counts"), dict)):
            raise ValueError("QMT financial cache worker envelope invalid")
        present = payload["records"]
        missing = payload["missing_symbols"]
        if (set(present) | set(missing) != expected_missing or
                set(present) & set(missing) or
                len(set(missing)) != len(missing)):
            raise ValueError("QMT financial cache worker stock coverage invalid")
        for code, tables in present.items():
            if not isinstance(tables, dict) or set(tables) != set(E.FIN_TABLES):
                raise ValueError("QMT cached worker table list incomplete: " + code)
            counts = payload["row_counts"].get(code)
            if (not isinstance(counts, dict)
                    or set(counts) != set(E.FIN_TABLES)):
                raise ValueError("QMT cached worker row counts missing: " + code)
            for name in E.FIN_TABLES:
                recs = tables[name]
                if (not isinstance(recs, list) or len(recs) > 100000
                        or not isinstance(counts[name], int)
                        or len(recs) != counts[name]):
                    raise ValueError("QMT cache worker count mismatch")
        progress("QMT_CACHE_BATCH_READ=" + E.canonical_json({
            "symbols": symbols, "present": len(present), "missing": missing,
            "mode": mode}))
        return present, missing


def _recover_utf8_group(worker, group, mode, asof, lookback_days,
                        workspace, timeout_seconds, progress):
    """Split ONLY known UTF-8 source decode failures; preserve stock ordering.

    All non-decode errors propagate. A permanently failing single stock is
    returned as a typed pending item, never as a successful/empty source.
    """
    try:
        records, missing = worker(
            group, mode, asof, lookback_days, workspace, timeout_seconds,
            progress=progress)
        if (not isinstance(records, dict) or
                not isinstance(missing, list) or
                set(records) | set(missing) != set(group) or
                set(records) & set(missing)):
            raise ValueError("QMT worker returned malformed stock batch")
        return [(code, records.get(code),
                 "NO_CACHE" if code in missing else None)
                for code in group]
    except QMTCacheDecodeError as exc:
        if len(group) == 1:
            code = group[0]
            progress("QMT_CACHE_STOCK_UTF8_DEFERRED=" + E.canonical_json({
                "symbol": code, "reason": str(exc)[:180]}))
            return [(code, None, "CACHE_DECODE_ERROR")]
        mid = len(group) // 2
        progress("QMT_CACHE_BATCH_UTF8_SPLIT=" + E.canonical_json({
            "symbols": group,
            "left": group[:mid], "right": group[mid:]}))
        return (
            _recover_utf8_group(
                worker, group[:mid], mode, asof, lookback_days,
                workspace, timeout_seconds, progress) +
            _recover_utf8_group(
                worker, group[mid:], mode, asof, lookback_days,
                workspace, timeout_seconds, progress))


def _pending_mark(state, code, reason, asof, detail):
    entry = state["pending"].get(code, {})
    state["pending"][code] = {
        "reason": reason, "asof": asof,
        "detail": str(detail)[:300],
        "attempts": entry.get("attempts", 0) + 1}


def _stock_universe(xt, finance_dir=None):
    """Current QMT A-share sector plus explicitly supplied local Finance names.

    Never parse proprietary DAT contents. Local filename discovery captures
    already cached delisted symbols and BJ suffixes when those folders exist.
    """
    current = E._tickers(xt, ("沪深A股",), required=True)
    if finance_dir is None:
        return current, {"sector_symbols": len(current),
                         "finance_file_symbols": None,
                         "finance_only_symbols": None,
                         "source_scope": "CURRENT_HUSHEN_A_SECTOR_ONLY"}
    finance_dir = Path(finance_dir)
    E._path_check(finance_dir)
    if not finance_dir.is_dir() or finance_dir.is_symlink():
        raise ValueError("Missing or redirected explicit QMT Finance directory")
    from_files = set()
    for exchange in ("SZ", "SH", "BJ"):
        folder = finance_dir / exchange / "86400"
        E._path_check(folder)
        if not folder.exists():
            continue
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError("Linked or invalid QMT Finance exchange folder")
        for path in folder.iterdir():
            match = re.fullmatch(r"([0-9]{6})_7[0-9]{3}\.DAT",
                                 path.name, re.IGNORECASE)
            if match:
                E._path_check(path)
                if not path.is_file() or path.is_symlink():
                    raise ValueError("Invalid QMT Finance cache entry")
                from_files.add(E.valid_code(match.group(1) + "." + exchange))
    if not from_files:
        raise ValueError("No stock-level QMT Finance DAT files found in " +
                         str(finance_dir))
    joined = sorted(set(current) | from_files)
    return joined, {"sector_symbols": len(current),
                    "finance_file_symbols": len(from_files),
                    "finance_only_symbols": len(from_files - set(current)),
                    "source_scope": "QMT_SECTOR_PLUS_EXPLICIT_FINANCE_DAT_NAMES",
                    "finance_directory": str(finance_dir)}


def _prepare_daily_sweep(state, asof, catalog, *, retry_pending=False):
    """Continue incomplete QMT daily sweeps across calendar days.

    'reached_end' means all source securities were visited, not that each
    pending history conflict was resolved. Existing v1 progress files without
    these optional keys remain valid and keep their existing cursors.
    """
    if retry_pending:
        return
    previous_date = state["daily_date"]
    if previous_date == asof:
        if not state["daily_sweep_start"]:
            state["daily_sweep_start"] = asof
        return
    exhausted = (state["daily_sweep_reached_end"] or
                 (bool(previous_date) and
                  state["daily_cursor"] >= catalog[-1]))
    if exhausted:
        state["daily_cursor"] = ""
        state["daily_sweep_start"] = asof
        state["daily_sweep_reached_end"] = False
    elif not state["daily_sweep_start"]:
        state["daily_sweep_start"] = previous_date or asof
    state["daily_date"] = asof


def run(root, *, xt, mode="cache", apply=False, max_symbols=6000,
        batch_size=5, max_minutes=0, worker_timeout_seconds=180,
        lookback_days=120, retry_pending=False, workspace=E.WORK,
        finance_dir=None, clock=None, progress=print, worker=None):
    if mode not in ("cache", "daily"):
        raise ValueError("Invalid financial import mode")
    if (not 1 <= batch_size <= MAX_GROUP or
            not 1 <= max_symbols <= 10000 or
            not 0 <= max_minutes <= 1440 or
            not 30 <= worker_timeout_seconds <= 3600 or
            not 1 <= lookback_days <= 1095):
        raise ValueError("Invalid QMT cache importer bounds")
    if clock is None:
        clock = lambda: datetime.now(E.L.UTC8)
    if worker is None:
        worker = _worker_batch
    raw_now = clock()
    if raw_now.tzinfo is None or raw_now.utcoffset() is None:
        raise ValueError("Financial importer needs aware clock")
    now = raw_now.astimezone(E.L.UTC8)
    asof = now.date().isoformat()
    deadline = (now + timedelta(minutes=max_minutes)
                if max_minutes else None)
    extra = E._storage(Path(root))
    state = _state(extra, workspace)
    cursor_key = "import_cursor" if mode == "cache" else "daily_cursor"
    universe_start = monotonic()
    progress("QMT_FINANCIAL_UNIVERSE_QUERY_START=" + E.canonical_json({
        "mode": mode, "finance_dir_enabled": finance_dir is not None}))
    catalog, catalog_metadata = _stock_universe(xt, finance_dir)
    progress("QMT_FINANCIAL_UNIVERSE_QUERY_DONE=" + E.canonical_json({
        "stocks": len(catalog),
        "elapsed_seconds": round(monotonic() - universe_start, 3)}))
    universe_hash = hashlib.sha256(
        E.canonical_json(catalog).encode("utf-8")).hexdigest()
    if mode == "daily" and state["import_cursor"] < catalog[-1]:
        raise ValueError("Initial QMT financial cache import has not reached "
                         "the end of current stock universe; finish --mode cache first")
    if mode == "daily":
        _prepare_daily_sweep(state, asof, catalog,
                             retry_pending=retry_pending)
    if retry_pending:
        missing = set(state["pending"]) - set(catalog)
        if missing:
            raise ValueError("Pending QMT cache symbols disappeared: " +
                             E.canonical_json(sorted(missing)[:20]))
        selected = sorted(state["pending"])[:max_symbols]
    else:
        selected = [s for s in catalog if s > state[cursor_key]][:max_symbols]
    positions = {code: idx for idx, code in enumerate(catalog)} if mode == "daily" else {}
    report = {
        "status": "PREVIEW", "mode": mode, "apply": apply,
        "asof": asof, "universe_symbols": len(catalog),
        "universe_sha256": universe_hash,
        "universe_metadata": catalog_metadata,
        "source_completeness_verified": False,
        "time_budget_minutes": max_minutes,
        "start_cursor": state[cursor_key],
        "end_cursor": state[cursor_key],
        "selected": len(selected), "selected_first": selected[0] if selected else None,
        "processed": 0, "pending_added": 0,
        "new_snapshots": 0, "unchanged_tables": 0,
        "empty_tables": 0, "pending_total": len(state["pending"]),
        "old_financial_scan_cursor_modified": False,
        "purchased_8_cycle_modified": False, "h5_modified": False,
        "qmt_full_download_called": False,
        "daily_sweep_start": (state["daily_sweep_start"] if mode == "daily"
                              else None),
        "daily_sweep_reached_end": (state["daily_sweep_reached_end"]
                                     if mode == "daily" else None),
        "daily_sweep_finished": (state["daily_sweep_finished"]
                                   if mode == "daily" else None),
        "daily_remaining_unvisited": (sum(code > state["daily_cursor"]
                                          for code in catalog)
                                      if mode == "daily" and not retry_pending
                                      else None)}
    if not apply:
        progress("QMT_FINANCIAL_CACHE_IMPORT_SUMMARY=" +
                 E.canonical_json(report))
        return report
    if not selected:
        report["status"] = ("NO_PENDING" if retry_pending else
                            "SOURCE_UNIVERSE_EXHAUSTED")
        progress("QMT_FINANCIAL_CACHE_IMPORT_SUMMARY=" +
                 E.canonical_json(report))
        return report
    consecutive_utf8_errors = 0
    for offset in range(0, len(selected), batch_size):
        now = clock().astimezone(E.L.UTC8)
        if now.date().isoformat() != asof:
            report["status"] = "PAUSED_DATE_ROLLOVER"
            break
        if deadline is not None and now >= deadline:
            report["status"] = "PAUSED_TIME_BUDGET"
            break
        group = selected[offset:offset + batch_size]
        # Exclusive writer held across QMT cache access and official commits.
        with E.LIVE.exclusive_writer():
            recovered = _recover_utf8_group(
                worker, group, mode, asof, lookback_days, workspace,
                worker_timeout_seconds, progress)
            if clock().astimezone(E.L.UTC8).date().isoformat() != asof:
                report["status"] = "PAUSED_DATE_ROLLOVER"
                break
            for code, source, reason in recovered:
                if reason is not None:
                    _pending_mark(
                        state, code, reason, asof,
                        "QMT provider UTF-8 decode failed twice even for one "
                        "stock" if reason == "CACHE_DECODE_ERROR" else
                        "QMT get_financial_data yielded no tables/rows")
                    report["pending_added"] += 1
                    if reason == "CACHE_DECODE_ERROR":
                        consecutive_utf8_errors += 1
                    else:
                        consecutive_utf8_errors = 0
                    progress("QMT_FINANCIAL_CACHE_PENDING=" +
                             E.canonical_json({"symbol": code,
                                               "reason": reason}))
                else:
                    consecutive_utf8_errors = 0
                    try:
                        # Compare source against ALL prior active versions.
                        table_report = _commit_symbol(
                            extra, workspace, code, asof, source)
                    except ValueError as exc:
                        if not str(exc).startswith("SOURCE_HISTORY_CONFLICT"):
                            raise
                        _pending_mark(
                            state, code, "SOURCE_HISTORY_CONFLICT", asof, exc)
                        report["pending_added"] += 1
                        progress("QMT_FINANCIAL_CACHE_PENDING=" +
                                 E.canonical_json({
                                     "symbol": code, "reason": str(exc)[:180]}))
                    else:
                        state["pending"].pop(code, None)
                        report["processed"] += 1
                        report["new_snapshots"] += sum(
                            v["action"] == "CREATE_VERSION"
                            for v in table_report.values())
                        report["unchanged_tables"] += sum(
                            v["action"] == "UNCHANGED"
                            for v in table_report.values())
                        report["empty_tables"] += sum(
                            v["action"] == "NO_SOURCE_RECORDS"
                            for v in table_report.values())
                        progress("QMT_FINANCIAL_CACHE_STOCK_COMMITTED=" +
                                 E.canonical_json({"symbol": code,
                                                   "tables": table_report}))
                if not retry_pending:
                    state[cursor_key] = code
                    if mode == "daily" and code == catalog[-1]:
                        state["daily_sweep_reached_end"] = True
                        state["daily_sweep_finished"] = asof
                _save_state(workspace, state)
                report["end_cursor"] = state[cursor_key]
                report["pending_total"] = len(state["pending"])
                if mode == "daily" and not retry_pending:
                    report["daily_sweep_reached_end"] = state["daily_sweep_reached_end"]
                    report["daily_sweep_finished"] = state["daily_sweep_finished"]
                    report["daily_remaining_unvisited"] = len(catalog) - positions[code] - 1
                progress("QMT_FINANCIAL_CACHE_CHECKPOINT=" +
                         E.canonical_json({"symbol": code,
                                           "cursor": state[cursor_key],
                                           "pending": report["pending_total"],
                                           "processed": report["processed"]}))
                if consecutive_utf8_errors >= 3:
                    # Three isolated single-stock UTF-8 failures in a row
                    # indicate a likely global broken provider, not three
                    # safely skippable independent cache records.
                    raise RuntimeError(
                        "Three consecutive QMT single-stock UTF-8 errors; "
                        "stopping to avoid mass false source deferrals")
    else:
        report["status"] = (
            "SOURCE_UNIVERSE_EXHAUSTED"
            if mode == "daily" and not retry_pending
            and state["daily_sweep_reached_end"]
            else "PAUSED_SYMBOL_LIMIT" if len(selected) == max_symbols
            else "SOURCE_UNIVERSE_EXHAUSTED")
    progress("QMT_FINANCIAL_CACHE_IMPORT_SUMMARY=" + E.canonical_json(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--mode", choices=("cache", "daily"), default="cache")
    parser.add_argument("--max-symbols", type=int, default=6000)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--max-minutes", type=int, default=0,
                        help="0 disables total job time limit; per-worker safety timeout stays")
    parser.add_argument("--worker-timeout-seconds", type=int, default=180)
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument("--finance-dir", type=Path,
                        help="Explicit local QMT Finance directory; include historical DAT filenames in stock universe without parsing their contents")
    parser.add_argument("--retry-pending", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    from xtquant import xtdata
    run(args.root, xt=xtdata, mode=args.mode, apply=args.apply,
        max_symbols=args.max_symbols, batch_size=args.batch_size,
        max_minutes=args.max_minutes,
        worker_timeout_seconds=args.worker_timeout_seconds,
        lookback_days=args.lookback_days,
        retry_pending=args.retry_pending,
        finance_dir=args.finance_dir)


if __name__ == "__main__":
    main()
