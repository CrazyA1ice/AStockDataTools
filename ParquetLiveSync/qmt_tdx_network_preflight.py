#!/usr/bin/env python3
"""Bounded TDX TCP/Kline compatibility preflight; private-only, no market writes.

pytdx by default swallows its underlying parser/socket exception and returns
None. Use raise_exception=True and distinguish TCP setup from actual 1-minute
Kline support. Probe both pytdx category 8 and the TDX native 7/1 representation,
but accept only timestamps demonstrating one-minute cadence. Do not infer that
a successful TCP connect means a usable historical Kline provider.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path

import qmt_1m_pipeline as P
import qmt_tdx_1m_depth as D

FORMAT="tdx_7709_real_one_minute_live_endpoint_preflight_v1"
HOME=D.BASE
PROFILE=HOME/"network_profile.json"
HOSTS=(
    ("111.229.247.189",7709),
    ("180.153.18.170",7709),
    ("60.191.117.167",7709),
    ("101.227.73.20",7709),
    ("119.147.212.81",7709),
    ("182.131.3.252",7709),
    ("14.17.75.71",7709),
    ("115.238.56.198",7709),
    ("123.125.108.14",7709),
    ("218.75.126.9",7709),
    ("180.153.18.172",80),
    ("202.108.253.139",80),
    ("114.80.63.12",7709),
    ("58.63.254.219",7709),
)
CATEGORIES=(8,7)
RECENT_CUTOFF_DAYS=45


def validate_real_1m(packet,symbol,now=None):
    """Require a dense actual 1m Kline window, not 5m or stale empty payload."""
    if now is None:
        now=datetime.now(D.CN)
    if packet is None:
        raise ValueError("TDX_RETURNED_NONE")
    if not isinstance(packet,list) or len(packet)<16 or len(packet)>48:
        raise ValueError("TDX_NOT_16_TO_48_REAL_MINUTE_BARS")
    records=D.normalized_tdx(packet,symbol)
    if len(records)!=len(packet):
        raise ValueError("TDX_DUPLICATE_MINUTE_BARS")
    stamps=[datetime.fromtimestamp(x["ts"]/1000,D.CN) for x in records]
    if stamps[-1]<now-timedelta(days=RECENT_CUTOFF_DAYS):
        raise ValueError("TDX_LIVE_SERVER_RETURNS_STALE_BARS")
    if stamps[-1]>now+timedelta(minutes=2):
        raise ValueError("TDX_KLINE_DATE_IN_FUTURE")
    by_day={}
    for dt in stamps:
        hm=(dt.hour,dt.minute)
        if hm not in D.P.GRID:
            # 09:30 (QMT) may appear, but 7709 start labels can also
            # produce 13:00 and 14:59 at right-edge conventions.
            if not (hm==(13,0) or hm==(14,59)):
                raise ValueError("TDX_TIME_LABEL_OUTSIDE_A_SHARE_SESSION")
        by_day.setdefault(dt.date(),[]).append(dt)
    dense=0
    for dates in by_day.values():
        for x,y in zip(dates,dates[1:]):
            if (y-x)==timedelta(minutes=1):
                dense+=1
    if dense<14:
        raise ValueError(f"TDX_NOT_1MIN_KLINE_CADENCE consecutive={dense}")
    return {"bar_count":len(stamps),
            "first_cn":stamps[0].isoformat(),
            "last_cn":stamps[-1].isoformat(),
            "consecutive_1m":dense}


def diagnostic_error(exc):
    inner=getattr(exc,"original_exception",None)
    msg=f"{type(exc).__name__}: {str(exc)[:90]}"
    if inner is not None:
        msg+=f" / {type(inner).__name__}: {str(inner)[:130]}"
    return msg


def probe(hosts=HOSTS,client_factory=None,now=None,logger=print,
          profile=PROFILE,max_hosts=12):
    if client_factory is None:
        from pytdx.hq import TdxHq_API
        client_factory=lambda:TdxHq_API(heartbeat=False,raise_exception=True)
    if now is None:
        now=datetime.now(D.CN)
    failures=[]
    options=[]
    for i,(ip,port) in enumerate(hosts):
        if i>=max_hosts:
            break
        api=client_factory()
        try:
            if not api.connect(ip,port,time_out=3):
                raise ConnectionError("TCP_CONNECT_FALSE")
            for category in CATEGORIES:
                try:
                    bar=api.get_security_bars(category,1,"600000",0,48)
                    stats=validate_real_1m(bar,"600000.SH",now=now)
                    result={"format":FORMAT,"status":"REAL_1MIN_7709_CONFIRMED",
                            "ip":ip,"port":port,"category":category,
                            "sample_stock":"600000.SH","sample":stats,
                            "checked_at_cn":now.isoformat(),
                            "provider":"Tongdaxin 7709, not QMT, not Tencent HTTP",
                            "market_modified":False}
                    # Prefer the first verified endpoint from the ordered pool.
                    P.safe_save(profile,P.canonical(result))
                    logger("TDX_NETWORK_PREFLIGHT_PASS "+json.dumps(result,sort_keys=True,ensure_ascii=False))
                    return result
                except Exception as exc:
                    reason=diagnostic_error(exc)
                    failures.append({"endpoint":f"{ip}:{port}",
                                     "category":category,"error":reason})
                    logger(f"TDX_NETWORK_PROBE_REJECT {ip}:{port} cat={category} {reason}")
        except Exception as exc:
            reason=diagnostic_error(exc)
            failures.append({"endpoint":f"{ip}:{port}","category":None,"error":reason})
            logger(f"TDX_NETWORK_CONNECT_REJECT {ip}:{port} {reason}")
        finally:
            try:api.disconnect()
            except Exception:pass
    summary={"format":FORMAT,"status":"NO_COMPATIBLE_1MIN_7709_ENDPOINT",
             "hosts_tested":min(len(hosts),max_hosts),
             "failures":failures,"market_modified":False,
             "likely_causes":["Clash TUN/routing for outbound TCP","stale or dead TDX nodes",
                              "TDX protocol 7/8 server incompatibility"]}
    logger("TDX_NETWORK_PREFLIGHT_FAILED="+json.dumps(summary,sort_keys=True,ensure_ascii=False))
    raise ConnectionError("No independently verified real 1m TDX 7709 host; see TDX_NETWORK_PREFLIGHT_FAILED")


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--max-hosts",type=int,default=12)
    args=p.parse_args(argv)
    if not 1<=args.max_hosts<=len(HOSTS):
        p.error("Invalid TDX host preflight budget")
    probe(max_hosts=args.max_hosts)


if __name__=="__main__":
    main()
