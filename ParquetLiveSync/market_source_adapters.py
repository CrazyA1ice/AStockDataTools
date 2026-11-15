#!/usr/bin/env python3
"""Optional minute-source adapters for *sampled cross-validation*, not blind fills.

Adapters expose comparable raw OHLCVA but do not assume any supplier's
volume/amount units or timestamp labels are equivalent. Primary QMT source
is separately calibrated against purchased Parquet and official TDX DAY.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
import math
import statistics

CN = timezone(timedelta(hours=8))
FIELDS = ("open", "high", "low", "close")
ALL = (*FIELDS, "volume", "amount")


def code_parts(symbol):
    import local_layout as L
    v = L.normal_symbol(symbol)
    if len(v) != 8 or v[:2] not in ("SH", "SZ") or not v[2:].isdigit():
        raise ValueError("Source adapter supports SH/SZ six-digit A shares only")
    return v[:2], v[2:]


def timestamp(value):
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=CN)
        return int(stamp.timestamp() * 1000)
    return int(datetime.fromisoformat(str(value).replace(" ", "T")).replace(tzinfo=CN).timestamp() * 1000)


def pytdx_1m(symbol, day, settings=None):
    """pytdx category 8 full one-minute OHLCVA; limited by server retention."""
    from pytdx.hq import TdxHq_API
    market, number = code_parts(symbol)
    cfg = settings or {}
    endpoints = cfg.get("servers") or [
        ["180.153.18.170", 7709], ["180.153.18.172", 80],
        ["202.108.253.139", 80], ["60.191.117.167", 7709]]
    api = TdxHq_API(heartbeat=False)
    rows = None
    for host, port in endpoints:
        try:
            if not api.connect(str(host), int(port), time_out=4):
                continue
            try:
                rows = api.get_security_bars(8, 1 if market == "SH" else 0,
                                             number, 0, 800)
                if rows:
                    break
            finally:
                api.disconnect()
        except (OSError, ConnectionError, TimeoutError):
            continue
    if rows is None:
        raise RuntimeError("pytdx returned no usable 1min server data")
    result = []
    for raw in rows:
        if str(raw["datetime"])[:10] != day.isoformat():
            continue
        result.append({
            "ts": timestamp(raw["datetime"]),
            **{name: float(raw[name]) for name in FIELDS},
            "volume": float(raw.get("vol", raw.get("volume", 0))),
            "amount": float(raw.get("amount", 0)),
        })
    return result


def eltdx_1m(symbol, day, settings=None):
    """eltdx minute K lines (not its price-only 'minutes.history')."""
    from eltdx import TdxClient
    market, number = code_parts(symbol)
    settings = settings or {}
    with TdxClient(timeout=int(settings.get("timeout", 4))) as client:
        series = client.bars.get(market.lower() + number, period="1m",
                                 count=800, bar_time="end", adjust="none")
    result = []
    for bar in series.bars:
        if bar.time.date() != day:
            continue
        result.append({
            "ts": timestamp(bar.time),
            **{name: float(getattr(bar, name)) for name in FIELDS},
            "volume": float(bar.volume_lots),
            "amount": float(bar.amount),
        })
    return result


def akshare_1m(symbol, day, settings=None):
    """Eastmoney near-five-trading-day 1min K lines, no adjustment."""
    import akshare as ak
    _, number = code_parts(symbol)
    start = day.strftime("%Y-%m-%d") + " 09:25:00"
    end = day.strftime("%Y-%m-%d") + " 15:05:00"
    df = ak.stock_zh_a_hist_min_em(
        symbol=number, start_date=start, end_date=end, period="1", adjust="")
    if df is None or df.empty:
        return []
    aliases = {"时间": "ts", "开盘": "open", "最高": "high",
               "最低": "low", "收盘": "close", "成交量": "volume",
               "成交额": "amount"}
    if not all(k in df.columns for k in ("时间", "开盘", "最高", "最低", "收盘")):
        raise ValueError("AKShare returned an unexpected 1minute schema")
    return [{aliases[k]: (timestamp(row[k]) if k == "时间" else float(row[k]))
             for k in aliases if k in df.columns}
            for _, row in df.iterrows()]


ADAPTERS = {"pytdx": pytdx_1m, "eltdx": eltdx_1m, "akshare": akshare_1m}
TDX_FAMILY = frozenset({"pytdx", "eltdx"})


def compare_minutes(primary, external, *, require=80):
    """Choose time offset by OHLC residual; do not guess provider units.

    Vendor labels may be left-edge (TDX) or right-edge (QMT/purchased).
    The best offset must independently pass >=85% OHLC and enough pairs.
    """
    if not primary or not external:
        return {"status": "NO_OVERLAP", "matched": 0}
    expected = {int(x["ts"]): x for x in primary}
    if len(expected) != len(primary):
        raise ValueError("Primary minute has duplicate timestamp")
    trials = []
    for offset in (-120000, -60000, 0, 60000, 120000):
        pairs = [(expected[x["ts"] + offset], x)
                 for x in external if x["ts"] + offset in expected]
        if len(pairs) < require:
            continue
        residuals = [sum(abs(float(a[k]) - float(b[k])) for k in FIELDS)
                     / max(1., abs(float(a["close"]))) for a, b in pairs]
        agreement = sum(all(math.isclose(float(a[k]), float(b[k]),
                                              rel_tol=.004, abs_tol=.025)
                            for k in FIELDS) for a, b in pairs) / len(pairs)
        trials.append((statistics.median(residuals), -agreement,
                       -len(pairs), offset, pairs))
    if not trials:
        return {"status": "NO_ENOUGH_COMPARABLE_MINUTES", "matched": 0}
    trials.sort(key=lambda x: x[:4])
    loss, neg_fit, minus_n, offset, pairs = trials[0]
    fit = -neg_fit
    # Both sources may originate in TDX upstream: caller groups them into
    # one evidence family rather than claiming two independent votes.
    checks = {"status": "AGREE" if fit >= .85 else "PRICE_DISAGREES",
              "matched": len(pairs), "ohlc_fit": round(fit, 5),
              "offset_ms": offset, "median_relative_ohlc_residual": round(loss, 8)}
    for field in ("volume", "amount"):
        samples = [(float(a.get(field, 0)), float(b.get(field, 0)))
                   for a, b in pairs if field in b
                   and float(a.get(field, 0)) > 1e-8
                   and float(b.get(field, 0)) > 1e-8]
        if len(samples) < 50:
            checks[field + "_ratio"] = "NOT_COMPARABLE"
            continue
        ratios = [a / b for a, b in samples]
        ratio = statistics.median(ratios)
        agree = sum(abs(a - b * ratio) <= max(1e-6, .07 * abs(a))
                    for a, b in samples) / len(samples)
        checks[field + "_ratio"] = {
            "observed_multiplier_not_assumed": round(ratio, 8),
            "fit": round(agree, 5),
            "pairs": len(samples),
            "status": "STABLE" if agree >= .85 else "UNSTABLE",
        }
    return checks


def sample_check(day, primary_by_symbol, config, *, progress=print):
    """Only configured providers; failures are visible but do not forge bars."""
    enabled = [name for name in ADAPTERS
               if config.get(name, {}).get("enabled", False)]
    count = int(config.get("sample_stocks", 8))
    if not 0 <= count <= 100:
        raise ValueError("Use at most 100 sampled cross-source stocks")
    symbols = sorted(primary_by_symbol)
    if not enabled or not symbols or not count:
        return {"enabled": enabled, "sampled": 0, "results": {},
                "independent_reference": "official_TDX_DAY"}
    import random
    chosen = random.Random(day.isoformat()).sample(
        symbols, min(count, len(symbols)))
    result = {}
    for name in enabled:
        matched = 0
        failures = []
        bad = []
        for symbol in chosen:
            try:
                other = ADAPTERS[name](symbol, day, config.get(name))
                detail = compare_minutes(primary_by_symbol[symbol], other)
                if detail["status"] == "AGREE":
                    matched += 1
                else:
                    bad.append({"symbol": symbol, **detail})
            except (ImportError, OSError, ValueError, RuntimeError, TimeoutError, ConnectionError) as exc:
                failures.append({"symbol": symbol,
                                 "reason": type(exc).__name__ + ": " + str(exc)[:100]})
        result[name] = {"agreed_stocks": matched, "sampled": len(chosen),
                        "disagreements": bad[:12], "fetch_errors": failures[:12],
                        "evidence_family": "TDX_7709" if name in TDX_FAMILY
                        else "EASTMONEY"}
        progress("MARKET_SOURCE_SAMPLE=" + name + " agreed=" +
                 str(matched) + "/" + str(len(chosen)))
    return {"enabled": enabled, "sampled": len(chosen),
            "results": result, "independent_reference": "official_TDX_DAY",
            "warning": "TDX pytdx and eltdx share an underlying source family"}
