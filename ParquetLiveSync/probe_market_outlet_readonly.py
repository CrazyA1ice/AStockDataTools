#!/usr/bin/env python3
"""Read-only intraday QMT quote + independent provider endpoint diagnostic.

Never downloads QMT history, submits orders, changes Parquet, or touches
scheduled tasks. Checks 2 liquid sample stocks, not all-market correctness.
A quote timestamp during opening auction does not prove closed Kline
readiness; authoritative daily ingestion still waits until 16:30 China time.
"""
from __future__ import annotations

import argparse
from datetime import datetime, date, timezone, timedelta
import json
import math
from pathlib import Path

CN = timezone(timedelta(hours=8))
SAMPLES = ("600000.SH", "000001.SZ")


def _date_time(value):
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.replace(tzinfo=CN) if value.tzinfo is None else value.astimezone(CN)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        x = float(value)
        if not math.isfinite(x) or x <= 0:
            return None
        if 10**13 <= x < 10**15:
            try:
                return datetime.strptime(str(int(x)), "%Y%m%d%H%M%S").replace(tzinfo=CN)
            except ValueError:
                return None
        if 10**12 <= x < 10**13:
            return datetime.fromtimestamp(x / 1000, CN)
        if 10**9 <= x < 10**11:
            return datetime.fromtimestamp(x, CN)
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit() and len(value) == 14:
            try:
                return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=CN)
            except ValueError:
                return None
        try:
            x = datetime.fromisoformat(value.replace(" ", "T"))
            return x.replace(tzinfo=CN) if x.tzinfo is None else x.astimezone(CN)
        except ValueError:
            return None
    return None


def _one_tick(symbol, payload, now):
    if not isinstance(payload, dict):
        return {"status": "MISSING", "timestamp": None}
    stamp = _date_time(payload.get("time"))
    last = payload.get("lastPrice")
    try:
        last = float(last)
    except (TypeError, ValueError):
        last = None
    report = {"status": "TIMESTAMP_UNVERIFIED",
              "timestamp": stamp.isoformat() if stamp else None,
              "price_positive": last is not None and math.isfinite(last) and last > 0}
    if stamp is not None:
        age = (now - stamp).total_seconds() / 60
        report["age_minutes"] = round(age, 1)
        if stamp.date() != now.date():
            report["status"] = "NOT_TODAY"
        elif age < -5:
            report["status"] = "CLOCK_MISMATCH"
        elif age <= 20:
            report["status"] = "TODAY_RECENT_TICK"
        else:
            report["status"] = "TODAY_STALE_TICK"
    return report


def _qmt_kline(xt, symbol, now):
    try:
        # Local read ONLY; no xtdata.download_history_data call.
        payload = xt.get_market_data_ex(
            field_list=["time", "open", "high", "low", "close"],
            stock_list=[symbol], period="1m",
            start_time=now.strftime("%Y%m%d"),
            end_time="", count=5, dividend_type="none", fill_data=False)
        frame = payload.get(symbol) if isinstance(payload, dict) else None
        if frame is None or len(frame) == 0:
            return {"status": "NO_TODAY_1M_BARS"}
        stamps = []
        if "time" in getattr(frame, "columns", []):
            stamps = [_date_time(t) for t in frame["time"].tolist()]
        else:
            stamps = [_date_time(t) for t in list(frame.index)]
        stamps = [t for t in stamps if t is not None and t.date() == now.date()]
        if not stamps:
            return {"status": "BARS_PRESENT_BUT_DATE_UNVERIFIED",
                    "rows_returned": len(frame)}
        stamp = max(stamps)
        age = (now - stamp).total_seconds() / 60
        return {"status": ("TODAY_1M_AVAILABLE" if -5 <= age <= 25
                           else "TODAY_1M_STALE"),
                "latest_timestamp": stamp.isoformat(),
                "age_minutes": round(age, 1), "rows_returned": len(frame)}
    except Exception as exc:
        return {"status": "READ_FAILED",
                "error": type(exc).__name__ + ": " + str(exc)[:180]}


def probe(xt, *, now, sources=None):
    now = now.astimezone(CN)
    if sources is None:
        sources = {}
    result = {"format": "market_outlet_readonly_v1",
              "read_only": True, "china_now": now.isoformat(),
              "continuous_auction_or_market": (
                  "PRE_CONTINUOUS_OR_AUCTION" if
                  (now.hour, now.minute) < (9, 35) else
                  "TRADING_WINDOW" if
                  (now.hour, now.minute) <= (15, 0) else "AFTER_CLOSE"),
              "qmt": {}, "independent_sources": {},
              "important": "Tick and sample bar visibility is not full-day Kline validation; do not update production before 16:30"}
    try:
        ticks = xt.get_full_tick(list(SAMPLES))
        if not isinstance(ticks, dict):
            raise ValueError("QMT tick reply is not a symbol dictionary")
    except Exception as exc:
        ticks = {}
        result["qmt_tick_error"] = type(exc).__name__ + ": " + str(exc)[:180]
    for symbol in SAMPLES:
        result["qmt"][symbol] = {
            "tick": _one_tick(symbol, ticks.get(symbol), now),
            "minute": _qmt_kline(xt, symbol, now),
        }
    for name, fn in sources.items():
        try:
            bars = fn("SH600000", now.date())
            if not isinstance(bars, list):
                raise ValueError("Source returned non-list bars")
            stamps = [_date_time(item.get("ts")) for item in bars
                      if isinstance(item, dict)]
            valid = [s for s in stamps if s and s.date() == now.date()]
            result["independent_sources"][name] = {
                "status": "TODAY_SAMPLE_AVAILABLE" if valid else "NO_TODAY_SAMPLE_BARS",
                "bars": len(bars),
                "latest_timestamp": max(valid).isoformat() if valid else None}
        except Exception as exc:
            result["independent_sources"][name] = {
                "status": "PROBE_FAILED",
                "error": type(exc).__name__ + ": " + str(exc)[:180]}
    result["qmt_live_quote_observed"] = any(
        item["tick"]["status"] == "TODAY_RECENT_TICK"
        for item in result["qmt"].values())
    result["qmt_local_minute_observed"] = any(
        item["minute"]["status"] == "TODAY_1M_AVAILABLE"
        for item in result["qmt"].values())
    result["daily_closed_bar_validated"] = False
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-independent", action="store_true")
    args = ap.parse_args(argv)
    from xtquant import xtdata
    sources = {}
    if not args.skip_independent:
        import market_source_adapters as adapters
        sources = {
            "eltdx": adapters.eltdx_1m,
            "tencent": adapters.tencent_1m,
        }
    result = probe(xtdata, now=datetime.now(CN), sources=sources)
    print("MARKET_OUTLET_READONLY_PROBE=" +
          json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not result["qmt_live_quote_observed"] and not result["qmt_local_minute_observed"]:
        print("MARKET_OUTLET_QMT_FRESHNESS_NOT_CONFIRMED")
    else:
        print("MARKET_OUTLET_QMT_SAMPLE_AVAILABLE_NO_MARKET_WRITE")


if __name__ == "__main__":
    main()
