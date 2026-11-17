#!/usr/bin/env python3
"""Read-only physical inventory of canonical 8-cycle and QMT-extra Parquet.

This is an inventory, NOT a market-source correctness certificate. It reads
shard footers, filenames, and canonical local progress JSON. It never calls
QMT, downloads, changes data, creates progress or scans all historical rows.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

import local_layout as L

UTC8 = timezone(timedelta(hours=8))
FIN_TABLES = ("Balance", "Income", "CashFlow", "Capital", "Top10FlowHolder",
              "Top10Holder", "HolderNum", "PershareIndex", "PerShare")
SHARD_RE = re.compile(r"^(\d{4})(?:-(0[1-9]|1[0-2]))?\.parquet$")
SNAP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-[0-9a-f]{16}\.parquet$")
STEPS = ("EIGHT_PERIODS", "FINANCIAL_DAILY", "SECTORS", "ADJUSTMENTS_ROTATING")


def _read_json(path):
    if path.is_symlink() or not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError):
        return None


def _asof_now():
    return datetime.now(UTC8)


def _last_weekday(day):
    while day.weekday() > 4:
        day -= timedelta(days=1)
    return day


def _expected_day(now):
    day = now.date()
    if now.hour < 16 or (now.hour == 16 and now.minute < 30):
        day -= timedelta(days=1)
    return _last_weekday(day)


def _date_max(seq):
    dates = [x for x in seq if isinstance(x, str)]
    return max(dates, default=None)


def _newest_snapshots(folder):
    """Filename-only: observation date, not financial report date."""
    if folder.is_symlink() or not folder.is_dir():
        return {"count": 0, "latest_asof": None, "latest_file": None}
    count, latest, latest_path = 0, None, None
    try:
        for p in folder.iterdir():
            m = SNAP_RE.fullmatch(p.name)
            if not m or not p.is_file() or p.is_symlink():
                continue
            count += 1
            if latest is None or m.group(1) > latest:
                latest, latest_path = m.group(1), p
    except OSError:
        return {"count": count, "latest_asof": latest,
                "latest_file": None, "scan_error": True}
    return {"count": count, "latest_asof": latest,
            "latest_file": latest_path}


def _parquet_footer(path, *, market=False):
    """No row data or full-file hash read; verify footer, schema, row count."""
    if path.is_symlink() or not path.is_file():
        return {"status": "MISSING_OR_LINKED"}
    try:
        f = pq.ParquetFile(path)
        try:
            schema = f.schema_arrow
            if market:
                L.validate_schema(schema)
            row_count = f.metadata.num_rows
            if row_count == 0:
                return {"status": "EMPTY", "rows": 0}
            result = {"status": "FOOTER_SCHEMA_OK", "rows": row_count}
            if market:
                ts_idx = schema.get_field_index("ts")
                stamps, complete = [], True
                for rg_idx in range(f.metadata.num_row_groups):
                    stats = f.metadata.row_group(rg_idx).column(ts_idx).statistics
                    if stats is None or not stats.has_min_max:
                        complete = False
                    else:
                        stamps.append(int(stats.max))
                if complete and stamps:
                    raw = max(stamps)
                    stamp = datetime.fromtimestamp(raw / 1000, UTC8)
                    if not 1990 <= stamp.year <= 2035:
                        raise ValueError("Unexpected market timestamp unit")
                    result["latest_bar_date"] = stamp.date().isoformat()
                    result["latest_timestamp_local"] = stamp.isoformat()
                    result["timestamp_evidence"] = "ALL_ROWGROUP_FOOTER_MAX"
                else:
                    result["latest_bar_date"] = None
                    result["timestamp_evidence"] = "UNVERIFIED_MISSING_ROWGROUP_STATS"
            return result
        finally:
            f.close()
    except Exception as exc:
        return {"status": "FOOTER_OR_SCHEMA_INVALID",
                "error": type(exc).__name__ + ": " + str(exc)[:170]}


def _market(base, now):
    expected = _expected_day(now)
    output = {}
    for cycle in L.PERIODS:
        folder = base / cycle
        info = {"exists": folder.is_dir() and not folder.is_symlink(),
                "shards": 0, "rows_all_shard_footers": 0,
                "missing_prior_years": [], "missing_current_months": [],
                "invalid_files": [], "latest_shard": None,
                "latest_bar_date": None, "latest_file_footer": None,
                "date_check": "UNVERIFIED"}
        output[cycle] = info
        if not info["exists"]:
            info["date_check"] = "MISSING_DIRECTORY"
            continue
        paths = {}
        for p in folder.iterdir():
            if p.suffix.lower() != ".parquet" or p.is_symlink():
                continue
            m = SHARD_RE.fullmatch(p.name)
            if m is None:
                info["invalid_files"].append(p.name)
                continue
            paths[p.name] = p
        info["shards"] = len(paths)
        for year in range(2011, now.year):
            name = f"{year}.parquet"
            if name not in paths:
                info["missing_prior_years"].append(name)
        last_closed_week_end = now.date() - timedelta(days=now.weekday() + 3)
        required_month = (
            now.month - 1 if cycle == "month"
            else last_closed_week_end.month
            if cycle == "week" and last_closed_week_end.year == now.year
            else 0 if cycle == "week"
            else now.month
        )
        for month in range(1, required_month + 1):
            name = f"{now.year}-{month:02}.parquet"
            if name not in paths:
                info["missing_current_months"].append(name)
        latest_name = max(paths, key=lambda n: (
            int(n[:4]), int(n[5:7]) if len(n) > 12 else 12),
            default=None)
        info["latest_shard"] = latest_name
        # Footer check for *every* physical shard, including old history.
        for name, path in sorted(paths.items()):
            detail = _parquet_footer(path, market=True)
            if detail["status"] != "FOOTER_SCHEMA_OK":
                info["invalid_files"].append(name + ": " + detail["status"])
            else:
                info["rows_all_shard_footers"] += detail["rows"]
            if name == latest_name:
                info["latest_file_footer"] = detail
                info["latest_bar_date"] = detail.get("latest_bar_date")
        if info["invalid_files"]:
            info["date_check"] = "FILE_ISSUES"
        elif not latest_name:
            info["date_check"] = "NO_FILES"
        elif info["latest_bar_date"] is None:
            info["date_check"] = "UNVERIFIED_FOOTER_TS"
        elif cycle in ("week", "month"):
            # WEEK and MONTH are only published after close. Vendor time
            # labels are calibrated, so day-stamp comparisons are misleading.
            info["date_check"] = "CLOSED_PERIOD_LABEL_REQUIRES_RULE_AUDIT"
        elif info["latest_bar_date"] >= expected.isoformat():
            info["date_check"] = "AT_EXPECTED_WEEKDAY_CANDIDATE"
        else:
            info["date_check"] = "BEHIND_EXPECTED_WEEKDAY_CANDIDATE"
    return {"expected_latest_equity_weekday_candidate": expected.isoformat(),
            "expected_day_note": "weekday heuristic only; not official exchange calendar",
            "periods": output}


def _extra(base, now):
    extra = base / "qmt_extra"
    sectors = _newest_snapshots(extra / "sectors" / "snapshots")
    sector_last = sectors.pop("latest_file")
    sectors["latest_footer"] = (_parquet_footer(sector_last) if sector_last else None)
    adjustments_dir = extra / "adjustments"
    adjustments = {"security_dirs": 0, "securities_with_snapshots": 0,
                   "snapshot_files": 0, "latest_observation_asof": None,
                   "observed_today_securities": 0, "sample_footer": None}
    if adjustments_dir.is_dir() and not adjustments_dir.is_symlink():
        sample = None
        for stock in adjustments_dir.iterdir():
            if not stock.is_dir() or stock.is_symlink():
                continue
            adjustments["security_dirs"] += 1
            inventory = _newest_snapshots(stock / "snapshots")
            adjustments["snapshot_files"] += inventory["count"]
            if inventory["count"]:
                adjustments["securities_with_snapshots"] += 1
                if inventory["latest_asof"] == now.date().isoformat():
                    adjustments["observed_today_securities"] += 1
                if not adjustments["latest_observation_asof"] or (
                        inventory["latest_asof"] > adjustments["latest_observation_asof"]):
                    adjustments["latest_observation_asof"] = inventory["latest_asof"]
                if sample is None and inventory["latest_file"] is not None:
                    sample = inventory["latest_file"]
        if sample is not None:
            adjustments["sample_footer"] = _parquet_footer(sample)
    finance_dir = extra / "financial"
    finance = {}
    for table in FIN_TABLES:
        folder = finance_dir / table
        summary = {"exists": folder.is_dir() and not folder.is_symlink(),
                   "security_dirs": 0, "securities_with_snapshots": 0,
                   "snapshot_files": 0, "latest_observation_asof": None,
                   "observed_today_securities": 0, "sample_footer": None}
        finance[table] = summary
        if not summary["exists"]:
            continue
        sample = None
        for stock in folder.iterdir():
            if not stock.is_dir() or stock.is_symlink():
                continue
            summary["security_dirs"] += 1
            inventory = _newest_snapshots(stock / "snapshots")
            summary["snapshot_files"] += inventory["count"]
            if inventory["count"]:
                summary["securities_with_snapshots"] += 1
                if inventory["latest_asof"] == now.date().isoformat():
                    summary["observed_today_securities"] += 1
                if not summary["latest_observation_asof"] or (
                        inventory["latest_asof"] > summary["latest_observation_asof"]):
                    summary["latest_observation_asof"] = inventory["latest_asof"]
                if sample is None and inventory["latest_file"] is not None:
                    sample = inventory["latest_file"]
        if sample is not None:
            summary["sample_footer"] = _parquet_footer(sample)
    others = {}
    for group in ("index", "etf"):
        folder = extra / group
        others[group] = {"exists": folder.is_dir() and not folder.is_symlink(),
                         "cycles_present": sorted(x.name for x in folder.iterdir()
                                                  if x.is_dir() and not x.is_symlink())
                         if folder.is_dir() and not folder.is_symlink() else []}
    return {"exists": extra.is_dir() and not extra.is_symlink(),
            "sectors": sectors, "adjustments": adjustments,
            "financial_nine_tables": finance, "index_etf": others,
            "warning": "financial/sector/adjustment snapshot asof is observation date, not report/record date; sample footer checks are not exhaustive"}


def _private_state(state_root):
    market = _read_json(state_root / "market_update" / "commits.json")
    finance = _read_json(state_root / "qmt_extra" / "financial-cache-progress.json")
    extra = _read_json(state_root / "qmt_extra" / "progress.json")
    last = _read_json(state_root / "last-afternoon-unified.json")
    latest_market = None
    try:
        months = market["periods"]["1min"].values()
        latest_market = _date_max(
            day for m in months if isinstance(m, dict) for day in m.get("days", []))
    except (TypeError, KeyError):
        pass
    pending = finance.get("pending", {}) if isinstance(finance, dict) else {}
    return {
        "market_ledger_present": market is not None,
        "market_1min_last_ledger_day": latest_market,
        "finance_progress_present": finance is not None,
        "financial_initial_cursor": finance.get("import_cursor") if finance else None,
        "financial_daily_date": finance.get("daily_date") if finance else None,
        "financial_daily_sweep_start": finance.get("daily_sweep_start") if finance else None,
        "financial_daily_cursor": finance.get("daily_cursor") if finance else None,
        "financial_daily_sweep_reached_end": finance.get("daily_sweep_reached_end") if finance else None,
        "financial_daily_sweep_finished": finance.get("daily_sweep_finished") if finance else None,
        "financial_pending_count": len(pending) if isinstance(pending, dict) else None,
        "financial_pending_codes_sample": sorted(pending)[:20] if isinstance(pending, dict) else [],
        "extra_progress_present": extra is not None,
        "extra_last_asof": extra.get("last_asof") if extra else None,
        "extra_adjustments_cursor": (extra.get("cursor", {}).get("adjustments")
                                     if extra and isinstance(extra.get("cursor"), dict) else None),
        "last_unified_run_present": last is not None,
        "last_unified_run": ({
            "status": last.get("status"), "china_start": last.get("china_start"),
            "steps_completed": last.get("steps_completed"),
            "validation": {
                "data_validation": last.get("validation", {}).get("data_validation"),
                "cross_validation": last.get("validation", {}).get("cross_validation")}
                if isinstance(last.get("validation"), dict) else None
        } if last else None),
    }


def _source_config(module, state_root):
    local = state_root / "market_update" / "sources.local.json"
    bundled = module / "market_sources.json"
    src = local if local.is_file() and not local.is_symlink() else bundled
    config = _read_json(src)
    chk = config.get("minute_cross_checks", {}) if config else {}
    configured = {name: {"enabled": bool(value.get("enabled")),
                         "configured": True}
                  for name, value in chk.items() if isinstance(value, dict)}
    return {"source_config": str(src), "minute_cross_checks": configured,
            "verified_now": False, "reason": "configuration is not a live cross-check; check a same-run source receipt",
            "extra_independent_sources": {"financial": "NOT_CONFIGURED",
                                          "sectors": "NOT_CONFIGURED",
                                          "adjustments": "NOT_CONFIGURED"}}


def audit(stock_root, state_root, now):
    module = Path(__file__).resolve().parent
    stock_root = Path(stock_root)
    state_root = Path(state_root)
    if state_root.is_symlink() or not state_root.is_dir():
        raise ValueError("Canonical private state root missing or redirected")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("Expected timezone-aware now")
    now = now.astimezone(UTC8)
    base = L.storage_root(stock_root, require_all=False)
    market = _market(base, now)
    extras = _extra(base, now)
    private = _private_state(state_root)
    sources = _source_config(module, state_root)
    equity_late = [p for p in L.PERIODS[:6] if
                   market["periods"][p]["date_check"] != "AT_EXPECTED_WEEKDAY_CANDIDATE"]
    return {"format": "local_market_parquet_readonly_inventory_v1",
            "read_only": True, "china_now": now.isoformat(),
            "dataset": str(base), "canonical_state": str(state_root),
            "equity_periods_not_proven_current": equity_late,
            "all_eight_files_exist": all(market["periods"][p]["shards"] > 0
                                         for p in L.PERIODS),
            "market": market, "qmt_extra": extras, "private_progress": private,
            "cross_source_configuration": sources,
            "completeness_certified": False,
            "limitations": [
                "Footers prove physical schema/row count/timestamp maximum, not every ticker/trading-day key",
                "Week/month are closed periods with calibrated vendor timestamps, not intraday bars",
                "Only one sample footer per supplementary section/table is checked",
                "Financial historical completeness and independent non-market source parity are not established",
                "The 16:30 scheduler may have been installed after today's trigger",
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--state-root", type=Path, required=True,
                        help="CANONICAL primary checkout ParquetLiveSync/work; never detached worktree")
    parser.add_argument("--asof", type=date.fromisoformat,
                        help="Optional China market date; defaults to now")
    args = parser.parse_args(argv)
    now = _asof_now()
    if args.asof is not None:
        now = datetime(args.asof.year, args.asof.month, args.asof.day,
                       23, 59, tzinfo=UTC8)
    report = audit(args.stock_root, args.state_root, now)
    brief = {
        "china_now": report["china_now"],
        "expected_equity_day": report["market"]["expected_latest_equity_weekday_candidate"],
        "periods": {
            name: {
                "files": p["shards"], "latest_file": p["latest_shard"],
                "latest_day": p["latest_bar_date"], "status": p["date_check"],
                "missing_year_files": len(p["missing_prior_years"]),
                "missing_month_files": len(p["missing_current_months"]),
                "invalid_count": len(p["invalid_files"]),
            } for name, p in report["market"]["periods"].items()
        },
        "financial": {
            name: {
                "symbols": entry["securities_with_snapshots"],
                "latest_observed": entry["latest_observation_asof"]
            } for name, entry in report["qmt_extra"]["financial_nine_tables"].items()
        },
        "sector": {
            "snapshots": report["qmt_extra"]["sectors"]["count"],
            "latest_observed": report["qmt_extra"]["sectors"]["latest_asof"]
        },
        "adjustments": {
            "symbols": report["qmt_extra"]["adjustments"]["securities_with_snapshots"],
            "latest_observed": report["qmt_extra"]["adjustments"]["latest_observation_asof"],
            "observed_today": report["qmt_extra"]["adjustments"]["observed_today_securities"]
        },
        "finance_pending": report["private_progress"]["financial_pending_count"],
        "finance_daily_sweep_finished": report["private_progress"]["financial_daily_sweep_finished"],
        "last_unified_run": report["private_progress"]["last_unified_run"],
        "cross_sources": report["cross_source_configuration"]["minute_cross_checks"],
    }
    print("LOCAL_MARKET_PARQUET_BRIEF=" +
          json.dumps(brief, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    print("LOCAL_MARKET_PARQUET_AUDIT=" +
          json.dumps(report, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")))


if __name__ == "__main__":
    main()
