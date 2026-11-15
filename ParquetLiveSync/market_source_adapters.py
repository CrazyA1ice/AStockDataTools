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


class MinuteSourceUnavailable(RuntimeError):
    """Network/provider outage. Not a price disagreement, not missing bars."""


def _pytdx_candidates(settings=None):
    """Bounded, deduplicated server list; include pytdx-distributed HQ hosts.

    Four legacy fixed IPs can disappear or reject clients. A live server
    from the installed pytdx package should be attempted first, without
    requiring any extra network discovery or third-party dependencies.
    """
    cfg = settings or {}
    max_servers = int(cfg.get("max_servers", 12))
    if not 1 <= max_servers <= 24:
        raise ValueError("pytdx max_servers must be in [1,24]")
    raw = []
    if cfg.get("discover_builtin_hosts", True):
        try:
            from pytdx.config.hosts import hq_hosts
        except (ImportError, AttributeError):
            hq_hosts = ()
        for entry in hq_hosts:
            if isinstance(entry, (tuple, list)) and len(entry) >= 3:
                raw.append([entry[1], entry[2]])
            elif isinstance(entry, (tuple, list)) and len(entry) == 2:
                raw.append([entry[0], entry[1]])
    raw += list(cfg.get("servers") or [])
    seen = set()
    chosen = []
    for item in raw:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError("pytdx server must be [host,port]")
        host = str(item[0]).strip()
        try:
            port = int(item[1])
        except (ValueError, TypeError) as exc:
            raise ValueError("pytdx server port invalid") from exc
        if (not host or len(host) > 253 or
                not all(c.isascii() and (c.isalnum() or c in ".:-")
                        for c in host) or not 1 <= port <= 65535):
            raise ValueError("Invalid pytdx host/port")
        if (host, port) not in seen:
            seen.add((host, port))
            chosen.append((host, port))
        if len(chosen) == max_servers:
            break
    if not chosen:
        raise ValueError("No configured or installed pytdx market hosts")
    preferred = cfg.get("_working_host")
    if preferred:
        endpoint = tuple(preferred)
        if endpoint in chosen:
            chosen.remove(endpoint)
            chosen.insert(0, endpoint)
    return chosen


def pytdx_1m(symbol, day, settings=None):
    """pytdx 1m Kline; rotate configured and installed TDX HQ endpoints.

    Distinguish network/empty-service failures from date-window absence
    and from genuine OHLC disagreement. Never fill QMT from this adapter.
    """
    from pytdx.hq import TdxHq_API
    market, number = code_parts(symbol)
    cfg = settings if isinstance(settings, dict) else {}
    endpoints = _pytdx_candidates(cfg)
    timeout = float(cfg.get("connect_timeout_seconds", 2.5))
    if not .5 <= timeout <= 8:
        raise ValueError("pytdx connection timeout outside [.5,8] seconds")
    connected, empty, failed = 0, 0, 0
    errors = []
    for host, port in endpoints:
        api = TdxHq_API(heartbeat=False)
        try:
            try:
                ok = api.connect(host, port, time_out=timeout)
            except Exception as exc:
                failed += 1
                if len(errors) < 4:
                    errors.append(host + ":" + str(port) + "=" +
                                  type(exc).__name__ + ":" + str(exc)[:65])
                continue
            if not ok:
                failed += 1
                if len(errors) < 4:
                    errors.append(host + ":" + str(port) + "=connect_false")
                continue
            connected += 1
            try:
                rows = api.get_security_bars(
                    8, 1 if market == "SH" else 0, number, 0, 800)
            except Exception as exc:
                failed += 1
                if len(errors) < 4:
                    errors.append(host + ":" + str(port) + "=" +
                                  type(exc).__name__ + ":" + str(exc)[:65])
                continue
            if not rows:
                empty += 1
                continue
            # Cache an actual responding endpoint only within this process.
            cfg["_working_host"] = [host, port]
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
        finally:
            try:
                api.disconnect()
            except Exception:
                pass
    raise MinuteSourceUnavailable(
        "PYTDX_NO_USABLE_HQ_HOST: attempted=" + str(len(endpoints)) +
        " connected=" + str(connected) + " empty_bars=" + str(empty) +
        " failures=" + str(failed) + " examples=" + ";".join(errors))


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
        attempted = 0
        outage = None
        for symbol in chosen:
            attempted += 1
            try:
                other = ADAPTERS[name](symbol, day, config.get(name))
                detail = compare_minutes(primary_by_symbol[symbol], other)
                if detail["status"] == "AGREE":
                    matched += 1
                else:
                    bad.append({"symbol": symbol, **detail})
            except MinuteSourceUnavailable as exc:
                outage = str(exc)[:550]
                failures.append({"symbol": symbol,
                                 "reason": type(exc).__name__ + ": " + outage})
                # Server-level outage affects other sampled symbols too.
                # Do not repeat N slow connection failures on the same day.
                break
            except (ImportError, OSError, ValueError, RuntimeError, TimeoutError, ConnectionError) as exc:
                failures.append({"symbol": symbol,
                                 "reason": type(exc).__name__ + ": " + str(exc)[:200]})
        status = ("UNAVAILABLE" if outage else
                  "PRICE_DISAGREES" if any(
                      x.get("status") == "PRICE_DISAGREES" for x in bad) else
                  "AGREE" if matched == len(chosen) else "INCONCLUSIVE")
        result[name] = {"status": status, "agreed_stocks": matched,
                        "sampled": len(chosen), "attempted": attempted,
                        "skipped_after_outage": len(chosen) - attempted if outage else 0,
                        "outage_reason": outage,
                        "disagreements": bad[:12], "fetch_errors": failures[:12],
                        "evidence_family": "TDX_7709" if name in TDX_FAMILY
                        else "EASTMONEY"}
        progress("MARKET_SOURCE_SAMPLE=" + name +
                 " status=" + status + " agreed=" + str(matched) +
                 "/" + str(len(chosen)) + " attempted=" + str(attempted))
    return {"enabled": enabled, "sampled": len(chosen),
            "results": result, "independent_reference": "official_TDX_DAY",
            "warning": "TDX pytdx and eltdx share an underlying source family"}
