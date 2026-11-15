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


# Adapted from the verified Tencent m1 payload and 3-host failover design
# documented by simonlin1212/a-stock-data SKILL.md, §1.2.
# Tencent 1m is OHLCV-only, so amount MUST NEVER be fabricated.
TENCENT_KLINE_HOSTS = (
    "https://web.ifzq.gtimg.cn",
    "https://proxy.finance.qq.com/ifzqgtimg",
    "https://ifzq.gtimg.cn",
)


def _tencent_parse_minute_payload(payload, symbol, day):
    """Strict Tencent m1 row: YYYYmmddHHMM, open, close, high, low, volume."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("TENCENT_BAD_PAYLOAD_ROOT")
    node = payload["data"].get(symbol)
    rows = node.get("m1") if isinstance(node, dict) else None
    if not isinstance(rows, list):
        raise ValueError("TENCENT_M1_LIST_MISSING")
    result = []
    seen = set()
    for item in rows:
        if not isinstance(item, list) or len(item) < 6:
            raise ValueError("TENCENT_M1_ROW_SHAPE_CHANGED")
        stamp = str(item[0])
        if len(stamp) != 12 or not stamp.isdigit():
            raise ValueError("TENCENT_M1_BAD_TIME")
        moment = datetime.strptime(stamp, "%Y%m%d%H%M")
        if moment.date() != day:
            continue
        values = [item[i] for i in (1, 3, 4, 2, 5)]
        if any(isinstance(v, bool) or v is None or
               (isinstance(v, str) and not v.strip()) for v in values):
            raise ValueError("TENCENT_M1_MISSING_OR_INVALID_PRICE_VOLUME")
        nums = [float(v) for v in values]
        if not all(math.isfinite(v) for v in nums):
            raise ValueError("TENCENT_M1_NONFINITE_OHLCV")
        op, hi, lo, close, vol = nums
        if not (0 < lo <= op <= hi and lo <= close <= hi and vol >= 0):
            raise ValueError("TENCENT_M1_IMPOSSIBLE_OHLCV")
        ts = timestamp(moment)
        if ts in seen:
            raise ValueError("TENCENT_M1_DUPLICATE_MINUTE")
        seen.add(ts)
        result.append({"ts": ts, "open": op, "high": hi,
                       "low": lo, "close": close,
                       "volume": vol})
    return sorted(result, key=lambda r: r["ts"])


def tencent_1m(symbol, day, settings=None):
    """Recent unadjusted Tencent m1 OHLCV: 320 latest bars, no amount.

    Uses Tencent's three HTTP gateways from a-stock-data, which are
    correlated mirrors of the same provider. It only performs sampled
    price checks; QMT remains the sole purchased-calibrated minute writer.
    """
    import requests
    market, code = code_parts(symbol)
    cfg = settings or {}
    hosts = cfg.get("hosts") or TENCENT_KLINE_HOSTS
    if not isinstance(hosts, (tuple, list)) or not 1 <= len(hosts) <= 3:
        raise ValueError("Tencent hosts must contain one to three endpoints")
    conn = float(cfg.get("connect_timeout_seconds", 3))
    read = float(cfg.get("read_timeout_seconds", 8))
    if not 0.5 <= conn <= 8 or not 1 <= read <= 20:
        raise ValueError("Tencent minute timeout outside safe bounds")
    prefix = market.lower() + code
    params = {"param": f"{prefix},m1,,320"}
    errors = []
    for host in hosts:
        if host not in TENCENT_KLINE_HOSTS:
            raise ValueError("Untrusted Tencent Kline host: " + str(host))
        try:
            response = requests.get(
                host + "/appstock/app/kline/mkline", params=params,
                headers={"Referer": "https://gu.qq.com/"},
                timeout=(conn, read))
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("msg") == "param error":
                raise ValueError("TENCENT_M1_BAD_PARAMETER")
            result = _tencent_parse_minute_payload(payload, prefix, day)
            # Empty matched day is normal for a requested day outside the
            # most recent 320-minute window; not a price discrepancy.
            return result
        except (requests.exceptions.RequestException, ValueError,
                TypeError, KeyError) as exc:
            errors.append(type(exc).__name__ + ":" + str(exc)[:85])
            continue
    raise MinuteSourceUnavailable(
        "TENCENT_M1_ALL_HTTP_GATEWAYS_UNAVAILABLE tried=" +
        str(len(hosts)) + " examples=" + ";".join(errors[:3]))



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


ADAPTERS = {"eltdx": eltdx_1m, "tencent": tencent_1m, "akshare": akshare_1m}
TDX_FAMILY = frozenset({"eltdx"})


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
            "warning": "Tencent OHLCV is independent of TDX; Tencent amount is not provided"}
