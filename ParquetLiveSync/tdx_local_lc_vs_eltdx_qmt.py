#!/usr/bin/env python3
"""No-network, read-only three-way local .lc1/.lc5, eltdx-240 and QMT-241.

Three pre-approved stocks and 2026-10-14..16 only. The local desktop TDX 1m
file may derive from the SAME TDX feed as the eltdx 7709 1m cache: even exact
agreement is NOT independent certification of the missing regular 09:31 high.
Do not split or synthesize an opening bar, or modify any Parquet/H5/TDX file.
QMT 241 is a SHA-pinned validation oracle, never a source for new market data.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date,datetime
import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq
import local_layout as L
import qmt_1m_pipeline as P
import qmt_eltdx_1m_probe as X
import qmt_eltdx_auction_241_probe as A
import qmt_eltdx_opening_tick_alignment as J
import tdx_local_lc_probe as T

FORMAT="tdx_local_lc1_lc5_vs_eltdx_240_qmt_241_sha_readonly_v1"
CODES=A.DEFAULT_CODES
DAYS=(date(2026,10,14),date(2026,10,15),date(2026,10,16))
FIELDS=A.VALUES
SCALES=(.01,1.,100.)


def read_local(path,*,period,days):
    """Read only selected dates, ensure whole-file SHA agrees with first scan."""
    report=T.scan_file(path,period=period,days=days)
    if report.get("status")!="VALID":
        raise ValueError("Local source missing, invalid, or nonmonotonic")
    rows={d:[] for d in days}
    sha=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda:stream.read(T.BAR.size*8192),b""):
            sha.update(part)
            if len(part)%T.BAR.size:
                raise ValueError("Local source changed during read")
            for wire in T.BAR.iter_unpack(part):
                packed,minute,op,hi,lo,cl,amount,volume,reserved=wire
                y=2004+packed//2048
                d=date(y,(packed%2048)//100,(packed%2048)%100)
                if d in rows:
                    rows[d].append({
                        "minute":minute,"open":float(op),"high":float(hi),
                        "low":float(lo),"close":float(cl),
                        "volume":float(volume),"amount":float(amount)})
    if sha.hexdigest()!=report["sha256"]:
        raise ValueError("Local LC source SHA changed between validation reads")
    for day in days:
        values=sorted(rows[day],key=lambda x:x["minute"])
        expected=240 if period==1 else 48
        if len(values)!=expected or len({x["minute"] for x in values})!=expected:
            raise ValueError(f"Local {period}min full-grid missing on {day}")
        rows[day]=values
    return rows,report["sha256"]


def normal_day_bar(bar):
    """QMT/online Parquet row to minute and six-value dict."""
    hour,minute=A.label(bar)
    return {"minute":hour*60+minute,**{k:float(bar[k]) for k in FIELDS}}


def fit_counts(left,right,*,factors=None):
    """Field comparisons in original numbers; volume scales remain research only."""
    if len(left)!=len(right) or not left:
        raise ValueError("Expected equal nonempty bar timelines")
    if [x["minute"] for x in left]!=[x["minute"] for x in right]:
        raise ValueError("Minute labels differ; no silent shift")
    strict={k:0 for k in FIELDS}
    tolerant={k:0 for k in FIELDS}
    for a,b in zip(left,right):
        for k in FIELDS:
            strict[k]+=int(J.strict_fit(a[k],b[k],k))
            tolerant[k]+=int(A.isnear(a[k],b[k],k))
    counts={}
    if factors is not None:
        for factor in factors:
            counts[str(factor)]=sum(
                J.strict_fit(float(a["volume"])*factor,float(b["volume"]),"volume")
                for a,b in zip(left,right))
    return {"bars":len(left),"strict_field_match_counts":strict,
            "tolerant_field_match_counts":tolerant,
            "volume_factor_local_to_reference_counts":counts}


def best_factor(fit):
    counts=fit["volume_factor_local_to_reference_counts"]
    if not counts:
        raise ValueError("Missing volume candidate factors")
    ordered=sorted(((n,float(f)) for f,n in counts.items()),reverse=True)
    count,factor=ordered[0]
    runner=ordered[1][0] if len(ordered)>1 else 0
    if count!=fit["bars"] or runner>=fit["bars"]*.8:
        return None
    return factor


def local_to_five(local1):
    """One 5min candle per consecutive 5 regular minutes; local feed only."""
    if len(local1)!=240:
        raise ValueError("Expected 240 1m records to aggregate to 48 local 5m")
    result=[]
    for i in range(0,240,5):
        group=local1[i:i+5]
        if group[-1]["minute"]!=[575+5*(i//5) if i<120 else
                                 785+5*((i-120)//5)][0]:
            # The two sessions are independent; never bridge lunch.
            raise ValueError("Invalid local 1m to 5m grouping")
        result.append({
            "minute":group[-1]["minute"],
            "open":group[0]["open"],"high":max(x["high"] for x in group),
            "low":min(x["low"] for x in group),"close":group[-1]["close"],
            "amount":sum(x["amount"] for x in group),
            "volume":sum(x["volume"] for x in group)})
    return result


def evaluate(day,local1,local5,online,qmt):
    if (len(local1)!=240 or len(local5)!=48 or
        len(online)!=240 or len(qmt)!=241 or
        A.label(qmt[0])!=(9,30) or A.label(qmt[1])!=(9,31)):
        raise ValueError("Missing 240/241 source bar grids")
    t=[normal_day_bar(x) for x in online]
    q=[normal_day_bar(x) for x in qmt]
    if [x["minute"] for x in local1]!=[x["minute"] for x in t] or [x["minute"] for x in q[1:]]!=[x["minute"] for x in t]:
        raise ValueError("Local eltdx and QMT grid not identical 09:31..15:00")
    # Research-only first-minute aggregate, used to TEST mapping, not to write.
    qmerged=[{
        "minute":q[1]["minute"],"open":q[0]["open"],
        "high":max(q[0]["high"],q[1]["high"]),
        "low":min(q[0]["low"],q[1]["low"]),
        "close":q[1]["close"],
        "volume":q[0]["volume"]+q[1]["volume"],
        "amount":q[0]["amount"]+q[1]["amount"]},*q[2:]]
    loc_online=fit_counts(local1,t,factors=SCALES)
    loc_qmerged=fit_counts(local1,qmerged,factors=SCALES)
    five=fit_counts(local_to_five(local1),local5,factors=SCALES)
    scale_online=best_factor(loc_online)
    scale_qmt=best_factor(loc_qmerged)
    first=local1[0]
    online_first=t[0]
    qa=q[0]
    qr=q[1]
    first_high_equal_auction=J.strict_fit(first["high"],qa["high"],"high")
    regular_high_known_from_merged=(first["high"]>qa["high"]+.0001)
    first_low_equal_auction=J.strict_fit(first["low"],qa["low"],"low")
    regular_low_known_from_merged=(first["low"]<qa["low"]-.0001)
    high_matches=J.strict_fit(first["high"],qr["high"],"high")
    low_matches=J.strict_fit(first["low"],qr["low"],"low")
    # A high equal to auction is NOT an independent regular 09:31 high,
    # even if the local source exactly reproduces online 240.
    outcome=("LOCAL_LC1_MATCHES_ONLINE_FULL_DAY"
             if all(n==240 for k,n in loc_online["strict_field_match_counts"].items()
                    if k in A.OHLC)
             else "LOCAL_AND_ONLINE_PRICE_DIFFERENCES")
    return {
        "day":str(day),"status":outcome,
        "local_1min_vs_online_eltdx_240":loc_online,
        "local_1min_vs_qmt_aggregated_240":loc_qmerged,
        "local_1min_rolled_to_local_5min":five,
        "volume_factor_local_to_online":scale_online,
        "volume_factor_local_to_qmt_merged":scale_qmt,
        "opening_0931_high_evidence":{
            "local_merged_high_equals_online_merged_high_strict":
                J.strict_fit(first["high"],online_first["high"],"high"),
            "local_merged_high_equals_qmt_auction_high_strict":
                first_high_equal_auction,
            "local_merged_high_equals_qmt_regular_high_strict":high_matches,
            "online_merged_high_equals_qmt_auction_high_strict":
                J.strict_fit(online_first["high"],qa["high"],"high"),
            "local_merged_high_above_qmt_auction_high":
                regular_high_known_from_merged,
            "qmt_regular_high_below_auction_high":
                qr["high"]<qa["high"]-.0001,
            "local_source_independently_certifies_regular_high":False,
            "local_same_vendor_feed_possible":True,
            "unresolved_0931_high_not_filled_from_qmt":True},
        "opening_0931_low_evidence":{
            "local_merged_low_equals_online_merged_low_strict":
                J.strict_fit(first["low"],online_first["low"],"low"),
            "local_merged_low_equals_qmt_auction_low_strict":
                first_low_equal_auction,
            "local_merged_low_equals_qmt_regular_low_strict":low_matches,
            "local_merged_low_below_qmt_auction_low":
                regular_low_known_from_merged},
        "source_240_vs_241_no_candidate_materialization":True,
        "source_chronology_certified":False,
        "source_market_files_modified":False,
        "production_merge_authorized":False}


def run(*,vipdoc,days=DAYS,codes=CODES,logger=print):
    if (not days or len(days)>len(DAYS) or len(set(days))!=len(days)
        or any(d not in DAYS for d in days)):
        raise ValueError("Only original three Oct 14-16 research days allowed")
    if (not codes or len(codes)>len(CODES) or len(set(codes))!=len(codes)
        or any(c not in CODES for c in codes)):
        raise ValueError("Only original three research stocks allowed")
    vipdoc=Path(vipdoc)
    if vipdoc.is_symlink() or not vipdoc.is_dir():
        raise ValueError("Local TDX vipdoc unavailable")
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    states=Counter()
    rows=[]
    for code in codes:
        # Read both local files only after existing first-stage file SHA review.
        p1=T.path_for(vipdoc,code,1)
        p5=T.path_for(vipdoc,code,5)
        if any(p.is_symlink() or p.parent.is_symlink() for p in (p1,p5)):
            raise ValueError("Redirected local TDX file/directory")
        local1,lsha=read_local(p1,period=1,days=days)
        local5,fsha=read_local(p5,period=5,days=days)
        receipt=X.verified_cache(folder,code,stage,remote_only=False)
        qrows,qsha=X.read_qmt_source(stage,code)
        path=folder/"source_parquet"/(code.replace(".","_")+".parquet")
        if (not receipt or not qrows or path.is_symlink()
            or L.hash_file(path)!=receipt["source_sha256"]):
            raise ValueError("Original QMT/eltdx 241/240 SHA binding missing")
        file=pq.read_table(path)
        if file.schema!=P.PRIVATE_SCHEMA:
            raise ValueError("Original eltdx Arrow schema changed")
        online=file.to_pylist()
        for day in days:
            q=A.day_rows(qrows,day)
            t=A.day_rows(online,day)
            info=evaluate(day,local1[day],local5[day],t,q)
            states[info["status"]]+=1
            info["stock"]=code
            rows.append(info)
            logger("TDX_LOCAL_THREE_WAY_CASE="+json.dumps({
                "stock":code,"day":str(day),
                "status":info["status"],
                "local_vs_online":info["local_1min_vs_online_eltdx_240"],
                "local_vs_qmt_merged":info["local_1min_vs_qmt_aggregated_240"],
                "local_1min_to_5min":info["local_1min_rolled_to_local_5min"],
                "high":info["opening_0931_high_evidence"],
                "low":info["opening_0931_low_evidence"],
                "production_merge_authorized":False},
                ensure_ascii=False,sort_keys=True))
    result={
        "format":FORMAT,"stock_days":len(rows),
        "statuses":dict(states),
        "local_lc1_and_lc5_source_files_SHA_verified":True,
        "online_eltdx_and_qmt_sources_SHA_verified":True,
        "no_network":True,"output_files_written":False,
        "market_files_modified":False,
        "production_merge_authorized":False}
    logger("TDX_LOCAL_THREE_WAY_SUMMARY="+json.dumps(
        result,ensure_ascii=False,sort_keys=True))
    return {"summary":result,"cases":rows}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vipdoc",required=True)
    p.add_argument("--days",default=",".join(map(str,DAYS)))
    args=p.parse_args()
    run(vipdoc=args.vipdoc,
        days=tuple(date.fromisoformat(d.strip()) for d in args.days.split(",")))
