#!/usr/bin/env python3
"""Generate 15/30/60-minute candidate OHLCVA from COMPLETE real 5m Kline.

This reduces 4 public HTTP streams per stock to only one 5m source.
Strictly require 48 exact 5-minute time stamps, 24 per morning and
afternoon session, before deriving any traded stock-day higher K-lines.
No 1-minute source is inferred from five-minute data.

Source 5m vendor bar labels are end-of-window 09:35..11:30 and
13:05..15:00. Never join over lunch; all output bars end at the last
5m bar in their actual segment. Amount/volume remain source units until
an independent purchased-original period-level calibration proves scale.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime,timedelta
import math

PERIODS=("5min","15min","30min","60min")
SIZE={"5min":1,"15min":3,"30min":6,"60min":12}
STARTS=("09:35","13:05")

def time_grid():
    out=[]
    for start in STARTS:
        start_time=datetime.strptime(start,"%H:%M")
        out.append([
            (start_time+timedelta(minutes=5*j)).strftime("%H:%M")
            for j in range(24)])
    return tuple(out)

GRID=time_grid()

def split_complete_5min(bars):
    groups=defaultdict(list)
    for bar in bars:
        if bar["symbol"] is None:
            raise ValueError("Missing source symbol")
        groups[(bar["symbol"],bar["date"])].append(bar)
    result={}
    failures={}
    for key,source in groups.items():
        data=sorted(source,key=lambda x:x["ts"])
        actual=[x["local_time"] for x in data]
        expected=GRID[0]+GRID[1]
        if actual!=expected or len(set(x["ts"] for x in data))!=48:
            failures[key]={
                "reason":"MISSING_OR_INVALID_5MIN_TRADING_TIME_GRID",
                "observed_bars":len(data),
                "first":actual[0] if actual else None,
                "last":actual[-1] if actual else None}
            continue
        for bar in data:
            if not all(isinstance(bar[f],(int,float)) and math.isfinite(bar[f])
                       for f in ("open","high","low","close",
                                 "provider_volume","amount_yuan")):
                raise ValueError("Nonfinite source 5min amount or price")
            if bar["open"]<=0 or bar["close"]<=0 or bar["high"]<bar["low"]:
                raise ValueError("Invalid traded 5min OHLC grid")
        result[key]=data
    return result,failures

def derive_from_5min(bars,*,periods=PERIODS):
    grouped,failures=split_complete_5min(bars)
    out={p:[] for p in periods}
    for period in periods:
        if period not in PERIODS:
            raise ValueError("Cannot derive unsupported minute period")
        n=SIZE[period]
        for (symbol,day),sequence in sorted(grouped.items()):
            for session in (sequence[:24],sequence[24:]):
                for offset in range(0,24,n):
                    segment=session[offset:offset+n]
                    last=segment[-1]
                    out[period].append({
                        "symbol":symbol,"date":day,"ts":last["ts"],
                        "local_time":last["local_time"],
                        "open":segment[0]["open"],
                        "high":max(x["high"] for x in segment),
                        "low":min(x["low"] for x in segment),
                        "close":last["close"],
                        "provider_volume":sum(x["provider_volume"] for x in segment),
                        "amount_yuan":sum(x["amount_yuan"] for x in segment)})
    return out,failures
