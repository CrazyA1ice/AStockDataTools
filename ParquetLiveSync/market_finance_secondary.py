#!/usr/bin/env python3
"""Real external financial-announcement candidates + QMT snapshot cross-check.

Read-only pilot. Eastmoney via AKShare is an independent *aggregator*, not
proof of an exchange filing. An incomplete recent-pages listing MUST NOT be
used to skip the existing QMT safety rotation. No official market writes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import re
from time import monotonic

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I

SOURCE = "EASTMONEY_VIA_AKSHARE"
KIND = ("财务报告", "信息变更", "持股变动")
TABLES = {
    "Balance": ("stock_balance_sheet_by_report_em",
                (("tot_assets", "TOTAL_ASSETS"),
                 ("tot_liab", "TOTAL_LIABILITIES"),
                 ("total_equity", "TOTAL_EQUITY"))),
    "Income": ("stock_profit_sheet_by_report_em",
               (("revenue", "TOTAL_OPERATE_INCOME"),
                ("net_profit_excl_min_int_inc", "PARENT_NETPROFIT"))),
    "CashFlow": ("stock_cash_flow_sheet_by_report_em",
                 (("net_cash_flows_oper_act", "NETCASH_OPERATE"),)),
}
CST = timezone(timedelta(hours=8))


class SecondarySourceBlocked(ValueError):
    pass


def _day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and 10**11 <= value <= 4.2 * 10**12:
        try:
            return datetime.fromtimestamp(value / 1000, CST).date().isoformat()
        except (OverflowError, ValueError, OSError):
            return None
    if value is None:
        return None
    token = str(value).strip()
    if re.fullmatch(r"\d{14}", token):
        token = token[:8]
    if re.fullmatch(r"\d{8}", token):
        token = token[:4] + "-" + token[4:6] + "-" + token[6:]
    elif re.fullmatch(r"\d{13}", token):
        try:
            return datetime.fromtimestamp(int(token) / 1000, CST).date().isoformat()
        except (OverflowError, ValueError, OSError):
            return None
    elif len(token) >= 10:
        token = token[:10]
    try:
        return date.fromisoformat(token).isoformat()
    except ValueError:
        return None


def _dataframe_records(frame, *, cap=1500):
    if not hasattr(frame, "to_dict") or not hasattr(frame, "index"):
        raise SecondarySourceBlocked("EXTERNAL_DATAFRAME_SCHEMA_UNKNOWN")
    if len(frame.index) > cap:
        raise SecondarySourceBlocked("EXTERNAL_RESPONSE_BUDGET_EXCEEDED")
    records = frame.to_dict(orient="records")
    if not isinstance(records, list) or any(not isinstance(r, dict)
                                           for r in records):
        raise SecondarySourceBlocked("EXTERNAL_RECORDS_MALFORMED")
    return records


def _code_six(value):
    raw = str(value).strip()
    return raw if re.fullmatch(r"\d{6}", raw) else None


def _fingerprint(code, title, day, category):
    return hashlib.sha256(
        json.dumps([code, title, day, category], ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")).hexdigest()


def discover_recent(ak, *, observed_on: date, days=7, pages=2,
                    known_symbols=()):
    """Discover RECENT candidates, never assert feed completeness.

    AKShare's stock_notice_report is a bounded recent-page listing and
    supplies no verified permanent announcement ID, so events are leads only.
    Exact exchange suffix is resolved only against caller-supplied local codes.
    """
    if type(observed_on) is not date or not 1 <= days <= 30 or not 1 <= pages <= 3:
        raise SecondarySourceBlocked("INVALID_DISCOVERY_WINDOW")
    codes = defaultdict(set)
    for symbol in known_symbols:
        if not isinstance(symbol, str) or not re.fullmatch(
                r"\d{6}\.(?:SH|SZ|BJ)", symbol):
            raise SecondarySourceBlocked("INVALID_KNOWN_STOCK_IDENTITY")
        codes[symbol[:6]].add(symbol)
    cutoff = (observed_on - timedelta(days=days - 1)).isoformat()
    seen = {}
    scanned = 0
    latest = None
    failed_categories = []
    notice_fn = getattr(ak, "stock_notice_report", None)
    if not callable(notice_fn):
        raise SecondarySourceBlocked("AKSHARE_NOTICE_API_MISSING")
    params = inspect.signature(notice_fn).parameters
    # Modern AKShare is date-scoped; old versions used recent_page.
    date_scoped = "date" in params and "symbol" in params
    if date_scoped:
        if days > 7:
            raise SecondarySourceBlocked("DATE_NOTICE_API_MAX_SEVEN_DAYS")
        queries = [(category, (observed_on - timedelta(days=offset)).strftime(
                     "%Y%m%d"))
                   for offset in range(days) for category in KIND]
    elif "report_type" in params and "recent_page" in params:
        queries = [(category, None) for category in KIND]
    else:
        raise SecondarySourceBlocked("UNRECOGNIZED_AKSHARE_NOTICE_SIGNATURE")
    for category, query_date in queries:
        try:
            frame = (notice_fn(symbol=category, date=query_date)
                     if date_scoped else
                     notice_fn(report_type=category, recent_page=str(pages)))
            records = _dataframe_records(frame, cap=1500)
        except Exception as exc:
            failed_categories.append({"category": category,
                                      "date": query_date,
                                      "error_type": type(exc).__name__})
            continue
        scanned += len(records)
        for item in records:
            published = _day(item.get("公告日期"))
            code = _code_six(item.get("代码"))
            title = item.get("公告标题")
            if not published or not code or not isinstance(title, str):
                continue
            title = title.strip()[:180]
            if not title or published > observed_on.isoformat():
                continue
            latest = max(latest or published, published)
            if published < cutoff:
                continue
            resolved = codes.get(code, set())
            symbol = next(iter(resolved)) if len(resolved) == 1 else None
            identity = "LOCAL_STOCK_ID_CONFIRMED" if symbol else "UNRESOLVED"
            kind = ("CORRECTION_CANDIDATE"
                    if any(word in title for word in
                           ("更正", "修订", "补充", "差错", "追溯调整"))
                    else "ANNOUNCEMENT_CANDIDATE")
            fp = _fingerprint(code, title, published, category)
            seen[fp] = {"event_fingerprint": fp[:20],
                        "symbol": symbol, "code6": code,
                        "identity": identity, "date": published,
                        "category": category, "kind": kind,
                        "title": title}
    events = sorted(seen.values(),
                    key=lambda row: (row["date"], row["event_fingerprint"]),
                    reverse=True)
    candidates = sorted({e["symbol"] for e in events if e["symbol"]})
    return {
        "source": SOURCE,
        "status": ("RECENT_PAGED_LEADS_NOT_COMPLETE" if not failed_categories
                   else "RECENT_LEADS_PARTIAL_SOURCE_ERROR"),
        "failed_categories": failed_categories,
        "from_date": cutoff, "through_date": observed_on.isoformat(),
        "latest_listed_date": latest,
        "categories_requested": list(KIND),
        "query_strategy": ("MODERN_BY_DATE" if date_scoped else "LEGACY_PAGES"),
        "source_requests_attempted": len(queries),
        "pages_per_category": pages if not date_scoped else None,
        "rows_scanned": scanned, "unique_event_leads": len(events),
        "unresolved_identity_leads": sum(e["symbol"] is None for e in events),
        "candidate_symbols_in_known_scope": candidates,
        "events_sample": events[:20],
        "official_announcement_ids_verified": False,
        "feed_complete_for_date_range": False,
        "empty_means_no_financial_updates": False,
        "can_schedule_download": False, "can_commit": False,
    }


def _amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        v = Decimal(str(value).replace(",", "").strip())
        return v if v.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _rows_by_period(rows, *, qmt):
    result = defaultdict(list)
    for row in rows:
        day = _day(row.get("m_timetag" if qmt else "REPORT_DATE"))
        if day is None and not qmt:
            day = _day(row.get("报告日期"))
        if day is not None:
            result[day].append(row)
    return result


def _unanimous_value(rows, field):
    values = {_amount(r.get(field)) for r in rows}
    if not rows or None in values or len(values) != 1:
        return None
    return next(iter(values))


def compare_rows(table, qmt_records, eastmoney_records, *, max_periods=4):
    """Match report-end dates and narrowly documented numeric field pairs.

    Skip unavailable/ambiguous variants instead of choosing an arbitrary
    revised record. Differences are evidence for review, not commit approval.
    """
    if table not in TABLES or not 1 <= max_periods <= 8:
        raise SecondarySourceBlocked("INVALID_COMPARISON_TABLE")
    if (not isinstance(qmt_records, list)
            or not isinstance(eastmoney_records, list)
            or len(qmt_records) > 100000 or len(eastmoney_records) > 1500):
        raise SecondarySourceBlocked("COMPARISON_INPUT_TOO_LARGE")
    if any(not isinstance(x, dict) for x in qmt_records + eastmoney_records):
        raise SecondarySourceBlocked("COMPARISON_ROW_MALFORMED")
    q = _rows_by_period(qmt_records, qmt=True)
    e = _rows_by_period(eastmoney_records, qmt=False)
    periods = sorted(set(q) & set(e), reverse=True)[:max_periods]
    comparison = []
    for day in periods:
        for qname, ename in TABLES[table][1]:
            lhs = _unanimous_value(q[day], qname)
            rhs = _unanimous_value(e[day], ename)
            if lhs is None or rhs is None:
                status = "NOT_COMPARABLE_OR_REVISION_AMBIGUOUS"
            else:
                absolute = abs(lhs - rhs)
                status = ("EXACT_MATCH" if absolute == 0 else
                          "NEAR_WITHIN_TOLERANCE" if
                          absolute <= max(Decimal("1"), max(abs(lhs), abs(rhs)) *
                                          Decimal("0.000000001")) else
                          "VALUE_DIFFERENCE")
            comparison.append({
                "report_date": day, "qmt_field": qname,
                "eastmoney_field": ename, "status": status,
                "qmt_value_yuan": str(lhs) if lhs is not None else None,
                "eastmoney_value_yuan": str(rhs) if rhs is not None else None,
            })
    counts = Counter(row["status"] for row in comparison)
    comparable = sum(counts[k] for k in
                     ("EXACT_MATCH", "NEAR_WITHIN_TOLERANCE", "VALUE_DIFFERENCE"))
    inconclusive = counts["NOT_COMPARABLE_OR_REVISION_AMBIGUOUS"]
    return {"table": table, "report_dates_in_both": len(periods),
            "qmt_report_dates_seen": len(q), "eastmoney_report_dates_seen": len(e),
            "comparison_count": len(comparison),
            "fields_comparable": comparable,
            "fields_inconclusive": inconclusive,
            "status_counts": dict(counts),
            "comparisons": comparison,
            "source_version_certified": False,
            "notice_date_pit_aligned": False,
            "can_resolve_historical_pending": False}


def crosscheck_saved(root, code, ak, *, max_periods=4):
    """Compare verified immutable QMT snapshots, never mutate their active pins."""
    if not isinstance(code, str) or not re.fullmatch(
            r"\d{6}\.(?:SH|SZ|BJ)", code):
        raise SecondarySourceBlocked("INVALID_FINANCE_SYMBOL")
    root = Path(root)
    if not root.is_absolute() or root.is_symlink():
        raise SecondarySourceBlocked("INVALID_READONLY_STOCK_ROOT")
    E._path_check(root)
    extra = E._storage(root)
    tables = []
    for table, (method_name, _) in TABLES.items():
        asof = I._latest_snapshot_day(extra, code, table)
        if asof is None:
            tables.append({"table": table, "status": "NO_LOCAL_QMT_SNAPSHOT",
                           "can_resolve_historical_pending": False})
            continue
        q = E._financial_snapshot_rows(extra, code, table, asof)
        if not q:
            raise SecondarySourceBlocked("LOCAL_SNAPSHOT_UNVERIFIED_" + table)
        fn = getattr(ak, method_name, None)
        if not callable(fn):
            tables.append({"table": table, "status": "EXTERNAL_METHOD_UNAVAILABLE",
                           "can_resolve_historical_pending": False})
            continue
        try:
            e = _dataframe_records(fn(symbol=code[-2:] + code[:6]))
            result = compare_rows(table, q, e, max_periods=max_periods)
            result["status"] = (
                "NO_COMMON_REPORT_PERIOD" if not result["report_dates_in_both"]
                else "FIELDS_NOT_COMPARABLE_OR_REVISIONS"
                if not result["fields_comparable"]
                else "PARTIAL_FIELD_COMPARISON_NOT_CERTIFICATION")
            result["qmt_snapshot_asof"] = asof
        except SecondarySourceBlocked:
            raise
        except Exception:
            result = {"table": table, "status": "EXTERNAL_SOURCE_ERROR",
                      "can_resolve_historical_pending": False}
        tables.append(result)
    compared = sum(x.get("fields_comparable", 0) for x in tables)
    inconclusive = sum(x.get("fields_inconclusive", 0) for x in tables)
    attempted = sum(x.get("comparison_count", 0) for x in tables)
    differences = sum(x.get("status_counts", {}).get("VALUE_DIFFERENCE", 0)
                      for x in tables)
    return {"symbol": code, "source": SOURCE,
            "status": "READONLY_SECONDARY_FIELDS_NOT_SOURCE_CERTIFIED",
            "tables": tables, "fields_compared": compared,
            "fields_inconclusive": inconclusive,
            "fields_attempted": attempted,
            "value_differences": differences,
            "qmt_snapshot_pins_unchanged": True,
            "complete_nine_table_verification": False,
            "pit_announcement_time_certified": False,
            "can_commit": False, "can_clear_pending": False,
            "qmt_api_calls": 0, "qmt_download_calls": 0}



def discover_pending_sample(ak, *, observed_on: date, symbols, days=3):
    """One short individual-stock announcement query per pending sample.

    NOT a complete feed: this avoids AKShare's full-market, all-page loop.
    """
    if (type(observed_on) is not date or not 1 <= days <= 7
            or type(symbols) is not list or not 1 <= len(symbols) <= 3
            or len(set(symbols)) != len(symbols)
            or any(not isinstance(code, str)
                   or not re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", code)
                   for code in symbols)):
        raise SecondarySourceBlocked("INVALID_PENDING_SAMPLE_SCOPE")
    method = getattr(ak, "stock_individual_notice_report", None)
    if not callable(method):
        raise SecondarySourceBlocked("AKSHARE_INDIVIDUAL_NOTICE_API_UNAVAILABLE")
    cutoff = observed_on - timedelta(days=days - 1)
    scanned, seen, failed = 0, {}, []
    latest = None
    for code in symbols:
        try:
            records = _dataframe_records(method(
                symbol=code[:6], indicator="全部",
                start_date=cutoff.strftime("%Y%m%d"),
                end_date=observed_on.strftime("%Y%m%d")), cap=250)
        except Exception as exc:
            failed.append({"symbol": code, "error_type": type(exc).__name__})
            continue
        scanned += len(records)
        for row in records:
            date_text = _day(row.get("公告日期"))
            title = row.get("公告标题")
            if (_code_six(row.get("代码")) != code[:6] or not date_text
                    or not cutoff.isoformat() <= date_text <= observed_on.isoformat()
                    or not isinstance(title, str) or not title.strip()):
                continue
            title = title.strip()[:180]
            category = row.get("公告类型")
            category = category.strip()[:50] if isinstance(category, str) else "未分类"
            fp = _fingerprint(code[:6], title, date_text, category)
            seen[fp] = {
                "event_fingerprint": fp[:20], "symbol": code,
                "code6": code[:6], "identity": "LOCAL_STOCK_ID_CONFIRMED",
                "date": date_text, "category": category,
                "kind": "CORRECTION_CANDIDATE" if any(
                    word in title for word in ("更正", "修订", "补充", "差错", "追溯调整"))
                    else "ANNOUNCEMENT_CANDIDATE", "title": title}
            latest = max(latest or date_text, date_text)
    events = sorted(seen.values(),
                    key=lambda row: (row["date"], row["event_fingerprint"]),
                    reverse=True)
    return {
        "source": SOURCE, "scope": "EXPLICIT_PENDING_STOCK_SAMPLE_ONLY",
        "status": "SCOPED_PENDING_LEADS_PARTIAL_SOURCE_ERROR" if failed
                  else "SCOPED_PENDING_LEADS_NOT_COMPLETE",
        "failed_categories": failed,
        "from_date": cutoff.isoformat(), "through_date": observed_on.isoformat(),
        "latest_listed_date": latest,
        "categories_requested": ["全部（单股范围）"],
        "query_strategy": "INDIVIDUAL_BY_DATE_RANGE",
        "source_requests_attempted": len(symbols),
        "pending_stocks_queried": len(symbols),
        "rows_scanned": scanned, "unique_event_leads": len(events),
        "unresolved_identity_leads": 0,
        "candidate_symbols_in_known_scope": sorted({e["symbol"] for e in events}),
        "events_sample": events[:20],
        "official_announcement_ids_verified": False,
        "feed_complete_for_date_range": False,
        "full_market_coverage_checked": False,
        "empty_means_no_financial_updates": False,
        "can_schedule_download": False, "can_commit": False,
    }


def _best_pinned_crosscheck_stock(root, symbols):
    """Metadata only chooses one sample; full SHA verification occurs later."""
    try:
        root = Path(root)
        if not root.is_absolute() or root.is_symlink():
            return symbols[0]
        E._path_check(root)
        extra = E._storage(root)
    except (OSError, ValueError):
        return symbols[0]
    scores = {}
    for code in symbols:
        points = 0
        for table in TABLES:
            try:
                day = I._latest_snapshot_day(extra, code, table)
                if day:
                    pin = E._financial_active_path(extra, code, table, day)
                    E._path_check(pin)
                    if pin.is_file() and not pin.is_symlink():
                        points += 1
            except (OSError, ValueError):
                continue
        scores[code] = points
    return sorted(symbols, key=lambda code: (-scores[code], code))[0]


def pilot(root, symbols, ak, *, observed_on: date, days=7, pages=2,
          known_symbols=None, progress=None):
    """Only three pending announcement queries and ONE statement comparison."""
    if not isinstance(symbols, list) or not 1 <= len(symbols) <= 3:
        raise SecondarySourceBlocked("PILOT_LIMIT_THREE_SYMBOLS")
    if len(set(symbols)) != len(symbols):
        raise SecondarySourceBlocked("DUPLICATE_PILOT_SYMBOL")
    if known_symbols is None:
        known_symbols = symbols
    if not set(symbols).issubset(set(known_symbols)) or not 1 <= days <= 7:
        raise SecondarySourceBlocked("INVALID_PENDING_PILOT_SCOPE")
    tick = monotonic()
    if progress is not None:
        progress("SCOPED_NOTICES")
    try:
        discovery = discover_pending_sample(
            ak, observed_on=observed_on, symbols=symbols, days=days)
    except Exception as exc:
        discovery = {
            "source": SOURCE,
            "status": "EXTERNAL_ANNOUNCEMENT_SOURCE_UNAVAILABLE",
            "error_type": type(exc).__name__,
            "scope": "EXPLICIT_PENDING_STOCK_SAMPLE_ONLY",
            "feed_complete_for_date_range": False,
            "full_market_coverage_checked": False,
            "empty_means_no_financial_updates": False,
            "can_schedule_download": False, "can_commit": False}
    discovery_seconds = round(monotonic() - tick, 3)
    chosen = _best_pinned_crosscheck_stock(root, symbols)
    comparisons = []
    for code in symbols:
        if code != chosen:
            comparisons.append({
                "symbol": code, "source": SOURCE,
                "status": "NOT_RUN_ONE_STOCK_PILOT_BUDGET",
                "fields_compared": 0, "fields_inconclusive": 0,
                "value_differences": 0,
                "can_commit": False, "can_clear_pending": False,
                "qmt_api_calls": 0, "qmt_download_calls": 0})
            continue
        if progress is not None:
            progress("THREE_STATEMENTS")
        try:
            comparisons.append(crosscheck_saved(root, code, ak))
        except Exception as exc:
            comparisons.append({
                "symbol": code, "source": SOURCE,
                "status": "CROSSCHECK_BLOCKED_UNTRUSTED_LOCAL_OR_SOURCE",
                "error_type": type(exc).__name__,
                "can_commit": False, "can_clear_pending": False,
                "qmt_api_calls": 0, "qmt_download_calls": 0})
    total_seconds = round(monotonic() - tick, 3)
    return {"status": "EXTERNAL_FINANCE_PILOT_REVIEW_ONLY",
            "discovery_seconds": discovery_seconds,
            "crosscheck_seconds": round(max(0, total_seconds - discovery_seconds), 3),
            "total_seconds": total_seconds,
            "discovery": discovery, "crosschecks": comparisons,
            "crosscheck_sample_limit": 1,
            "crosscheck_stocks_not_attempted": len(symbols) - 1,
            "event_candidates_to_download": [],
            "source_discovery_not_complete": True,
            "can_apply": False, "can_commit": False,
            "changed_pending": False, "changed_20_05_task": False}


def _blocked_readonly_pilot(reason):
    """Emit only a bounded code; never print private paths or source records."""
    print("FINANCE_EXTERNAL_READONLY_ERROR=" + json.dumps({
        "status": reason, "can_apply": False, "can_commit": False,
    }, separators=(",", ":")))
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--known-symbols", default="")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        parser.error("External financial-source pilot requires --explicit-readonly")
    codes = [part.strip() for part in args.symbols.split(",")]
    if any(not re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", code)
           for code in codes):
        parser.error("Invalid explicit stock IDs")
    known = ([part.strip() for part in args.known_symbols.split(",")]
             if args.known_symbols else codes)
    if (len(known) > 500 or not known or any(
            not re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", code)
            for code in known) or len(set(known)) != len(known)):
        parser.error("Invalid known-stock identities (max 500)")
    try:
        ak = importlib.import_module("akshare")
    except ModuleNotFoundError as exc:
        return _blocked_readonly_pilot(
            "AKSHARE_NOT_INSTALLED" if exc.name == "akshare"
            else "AKSHARE_DEPENDENCY_MISSING")
    except Exception:
        return _blocked_readonly_pilot("AKSHARE_IMPORT_FAILED")
    try:
        result = pilot(args.root, codes, ak, observed_on=datetime.now(CST).date(),
                       days=args.lookback_days, pages=args.pages,
                       known_symbols=known,
                       progress=lambda phase: print(
                           'FINANCE_EXTERNAL_STAGE=' + phase, flush=True))
    except Exception:
        return _blocked_readonly_pilot("READONLY_PILOT_ABORTED")
    # Windows redirected stdout can use GBK/CP936. The GUI requires UTF-8.
    # ASCII-escape all non-ASCII report data, preserving Chinese in JSON while
    # making the receipt byte-identical under UTF-8 and legacy code pages.
    # Do not relax the GUI's strict UTF-8 / unique-tag trust boundary.
    print("FINANCE_EXTERNAL_READONLY=" +
          json.dumps(result, ensure_ascii=True, default=str,
                     separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
