#!/usr/bin/env python3
"""T+1 QMT 1m revision audit with independent Tencent m1 and Eastmoney 5m.

Immutable private evidence only. Never writes AllCycleAStockData or H5.
The Tencent API has no amount and is limited to the latest 320 bars;
Eastmoney trends2 is NOT an OHLC 1m source. Eastmoney 5m is used here.
No synthetic prices or fabricated 1m volumes/amounts.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_1m_probe as Q
import qmt_1m_recover as R
import tencent_m1 as T
import minute_probe as E

FORMAT="qmt_1m_independent_t1_tencent_m1_eastmoney_5m_v1"
DAY=date(2026,11,12)
SAMPLES=("600000.SH","000001.SZ","688001.SH","000404.SZ","300318.SZ","688022.SH")
FIELDS=("open","high","low","close")
FACTORS=(.001,.01,.1,1.,10.,100.,1000.)
PRIVATE=P.BASE/"independent_crosscheck"

def payload_bytes(doc):
    return P.canonical(doc)

def pin_raw(folder,provider,symbol,raw):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    if folder.is_symlink():
        raise ValueError("Untrusted linked cross-source work directory")
    digest=hashlib.sha256(raw).hexdigest()
    p=folder/(provider+"-"+symbol.replace(".","_")+"-"+digest[:20]+".json")
    if p.is_symlink():
        raise ValueError("Symlinked cross-source evidence")
    if p.exists():
        if L.hash_file(p)!=digest:
            raise ValueError("Previously pinned external evidence differs")
    else:
        P.safe_save(p,raw)
    return {"sha256":digest,"private_file":str(p)}

def source_for_day(stage,code,day):
    path=stage/"source_parquet"/(code.replace(".","_")+".parquet")
    receipt=stage/"receipts"/(code.replace(".","_")+".json")
    if not receipt.exists():
        return None
    if receipt.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError("Accepted historical QMT receipt Parquet missing/redirected")
    doc=json.loads(receipt.read_bytes())
    if (doc.get("symbol")!=code or doc.get("status")!="private_ohlcva_source_verified"
            or L.hash_file(path)!=doc.get("sha256")):
        raise ValueError("Accepted QMT source SHA/identity mismatch")
    if day.isoformat() not in doc.get("traded_days",[]):
        return None
    lo=P.source_day_ts(day)
    tab=pq.read_table(path,columns=list(L.COLS),
                      filters=[("ts",">=",lo),("ts","<",lo+86400000)])
    L.validate_schema(tab.schema)
    return {int(x["ts"]):x for x in tab.to_pylist()}

def by_timestamp_qmt(rows):
    return {P.stamp_ms(r["datetime_cn"]):r for r in rows}

def revision_check(original,now):
    if original is None:
        return {"status":"NO_PRIOR_ACCEPTED_STOCK_SOURCE","original_bars":0}
    recent=by_timestamp_qmt(now)
    missing=sorted(set(original)-set(recent))
    extra=sorted(set(recent)-set(original))
    changed=0
    examples=[]
    for key in sorted(set(original)&set(recent)):
        old,new=original[key],recent[key]
        diff={f:[float(old[f]),float(new[f])] for f in Q.FIELDS
              if not math.isclose(float(old[f]),float(new[f]),rel_tol=1e-10,abs_tol=1e-8)}
        if diff:
            changed+=1
            if len(examples)<4:
                examples.append({"timestamp":key,"changed_values":diff})
    return {"status":"SAME_AS_PRIOR_PRIVATE_SNAPSHOT"
            if not (missing or extra or changed) else "QMT_T1_REVISION_DETECTED",
            "original_bars":len(original),"current_bars":len(recent),
            "missing_original_minutes":len(missing),"new_minutes":len(extra),
            "changed_minutes":changed,"examples":examples}

def intersect_compare(qmt_rows,other_rows,*,price_tolerance=.02,relative=.003):
    mine={int(x["ts"]):x for x in qmt_rows}
    theirs={int(x["ts"]):x for x in other_rows}
    common=sorted(set(mine)&set(theirs))
    by_field={}
    for field in FIELDS:
        matches=sum(math.isclose(float(mine[k][field]),float(theirs[k][field]),
                     rel_tol=relative,abs_tol=price_tolerance) for k in common)
        by_field[field]={"matching":matches,"compared":len(common),
                         "fit":round(matches/len(common),6) if common else None}
    return {"qmt_bars":len(mine),"external_bars":len(theirs),
            "overlap_bars":len(common),
            "qmt_only_bars":len(set(mine)-set(theirs)),
            "external_only_bars":len(set(theirs)-set(mine)),
            "ohlc":by_field}

def volume_fit(qmt_rows,source_rows,*,source_field,field="volume"):
    q={r["ts"]:r for r in qmt_rows}
    s={r["ts"]:r for r in source_rows}
    pairs=[(float(q[t][field]),float(s[t][source_field]))
           for t in set(q)&set(s) if float(q[t][field])>0 and float(s[t][source_field])>0]
    if len(pairs)<10:
        return {"status":"INSUFFICIENT_POSITIVE_OVERLAP","pairs":len(pairs)}
    score=[]
    for factor in FACTORS:
        agreement=sum(math.isclose(a,b*factor,rel_tol=.04,abs_tol=.5)
                      for a,b in pairs)/len(pairs)
        med=statistics.median(abs(a-b*factor)/max(abs(a),1.) for a,b in pairs)
        score.append((agreement,-med,factor))
    score.sort(reverse=True)
    return {"status":"DIAGNOSTIC_NOT_PRODUCTION_UNITS",
            "pairs":len(pairs),
            "best_factor_external_to_QMT":score[0][2],
            "fit":round(score[0][0],6),
            "median_relative_residual":round(-score[0][1],8),
            "second_best_fit":round(score[1][0],6)}

def qmt_aggregate_5m(source,*,include_auction):
    """48 end-labeled 5m bars; first 09:35 group has optional 09:30 auction."""
    clock={r["datetime_cn"][11:16]:r for r in source}
    if len(clock)!=241:
        raise ValueError("QMT 1m source is not exactly 241 observations")
    morning=[f"{h:02d}:{m:02d}" for h in (9,10,11)
             for m in range(60)
             if (h==9 and m>=31) or h==10 or (h==11 and m<=30)]
    afternoon=[f"{h:02d}:{m:02d}" for h in (13,14,15)
               for m in range(60)
               if (h==13 and m>=1) or h==14 or (h==15 and m==0)]
    if len(morning)!=120 or len(afternoon)!=120 or "09:30" not in clock:
        raise ValueError("Unexpected QMT 241 minute label convention")
    result=[]
    for segment in (morning,afternoon):
        for start in range(0,len(segment),5):
            slots=segment[start:start+5]
            if include_auction and segment is morning and start==0:
                slots=["09:30"]+slots
            if any(t not in clock for t in slots):
                raise ValueError("Missing QMT source slot")
            bars=[clock[t] for t in slots]
            result.append({
                "ts":P.stamp_ms(bars[-1]["datetime_cn"]),
                "open":bars[0]["open"],"high":max(x["high"] for x in bars),
                "low":min(x["low"] for x in bars),"close":bars[-1]["close"],
                "volume":sum(x["volume"] for x in bars),
                "amount":sum(x["amount"] for x in bars)})
    assert len(result)==48
    return result

def fetch_tencent(symbol,day,folder,fetcher=None):
    symbol=L.normal_symbol(symbol)
    fetcher=fetcher or T.fetch_bytes
    errors=[]
    for host in T.HOSTS:
        try:
            url=T.url_for(symbol,host,320)
            raw=fetcher(url)
            decoded=T.decode(raw,symbol)
            evidence=pin_raw(folder,"tencent_m1",symbol,raw)
            dayrows=[x for x in decoded if x["date"]==day.isoformat()]
            return dayrows,{**evidence,
                "status":"OK" if dayrows else "TARGET_DAY_OUTSIDE_LATEST_320",
                "source":"Tencent true m1 OHLCV; no amount",
                "returned_bars":len(decoded),"target_bars":len(dayrows),
                "oldest_date":decoded[0]["date"],"newest_date":decoded[-1]["date"],
                "url":url}
        except Exception as exc:
            errors.append(type(exc).__name__+": "+str(exc)[:120])
    return [],{"status":"UNAVAILABLE","errors":errors,"target_bars":0}

def fetch_eastmoney_5m(symbol,day,folder,requester=None):
    symbol=L.normal_symbol(symbol)
    requester=requester or E.fetch
    try:
        raw,doc=requester(E.endpoint("5min",symbol,end=day))
        bars=E.parse_bars(doc,"5min",symbol)
        evidence=pin_raw(folder,"eastmoney_5m",symbol,raw)
        subset=[x for x in bars if x["date"]==day.isoformat()]
        return subset,{**evidence,"status":"OK" if subset else "TARGET_DAY_MISSING",
                       "source":"Eastmoney independent historical 5m OHLCVA",
                       "returned_bars":len(bars),"target_bars":len(subset)}
    except Exception as exc:
        return [],{"status":"UNAVAILABLE","error":type(exc).__name__+": "+str(exc)[:200]}

def run(root,*,day=DAY,symbols=SAMPLES,workspace=PRIVATE,xtdata=None,
        tencent_fetcher=None,eastmoney_fetcher=None,progress=print):
    if day>=datetime.now(P.CN).date():
        raise ValueError("Only COMPLETED previous trading-day data can be independently audited")
    root=Path(root)
    stage=P.BASE/f"{R.START:%Y%m%d}_{R.END:%Y%m%d}"
    if not stage.is_dir() or not R.START<=day<=R.END:
        raise ValueError("QMT historical accepted source stage missing/outside window")
    expected,universe,plan,calibration=R.load_bound_context(root,stage,R.START,R.END)
    if day not in expected:
        raise ValueError("Selected day absent from independently validated TDX day source")
    if xtdata is None:
        from xtquant import xtdata
    report={"format":FORMAT,"day":day.isoformat(),
            "requested_symbols":list(symbols),
            "original_day_reference_sha256":plan["calendar_sha256"],
            "calibration_sha256":plan["calibration_sha256"],
            "market_modified":False,"production_merge_authorized":False,
            "providers":{"QMT":"real 1m OHLCVA","Tencent":"m1 OHLCV/no amount/320 latest",
                         "Eastmoney":"historical 5m OHLCVA, not trends2 1m"},
            "stocks":{}}
    folder=Path(workspace)/day.strftime("%Y%m%d")
    for code in symbols:
        code=Q.normalize_code(code)
        sym=L.normal_symbol(code)
        detail={"day":day.isoformat()}
        if code not in expected[day]:
            detail["status"]="NO_OFFICIAL_TRADED_DAY_REFERENCE"
            report["stocks"][code]=detail
            continue
        progress("QMT_T1_CROSSCHECK "+code)
        try:
            stored=source_for_day(stage,code,day)
            rows=P.fetch_qmt(xtdata,code,day,day)
            fresh=pin_raw(folder,"qmt_t1_1m",code,payload_bytes(rows))
            detail["qmt_current"]={**fresh,"count":len(rows),
                                   "cross_provider_unit_conversion":False}
            detail["t1_revision"]=revision_check(stored,rows)
            day_summary={
                "open":rows[0]["open"],"close":rows[-1]["close"],
                "high":max(x["high"] for x in rows),"low":min(x["low"] for x in rows)}
            detail["tdx_day_ohlc_match"]=all(
                math.isclose(float(expected[day][code][k]),float(day_summary[k]),
                             rel_tol=.006,abs_tol=.04) for k in FIELDS)
            if len(rows)!=241:
                detail["qmt_complete_241"]=False
                detail["status"]="QMT_DAY_NOT_COMPLETE"
                report["stocks"][code]=detail
                continue
            detail["qmt_complete_241"]=True
            trows,tsource=fetch_tencent(sym,day,folder,fetcher=tencent_fetcher)
            detail["tencent_source"]=tsource
            if trows:
                transformed=[{"ts":x["ts"],**{k:x[k] for k in FIELDS},
                              "source_volume":x["source_volume"]} for x in trows]
                normalized=[{"ts":P.stamp_ms(x["datetime_cn"]),**x} for x in rows]
                detail["tencent_1m_ohlc"]=intersect_compare(normalized,transformed)
                detail["tencent_1m_volume"]=volume_fit(
                    normalized,transformed,source_field="source_volume")
                detail["tencent_no_amount"]=True
            public,ems=fetch_eastmoney_5m(sym,day,folder,requester=eastmoney_fetcher)
            detail["eastmoney_source"]=ems
            if public:
                modes={}
                for mode in (False,True):
                    agg=qmt_aggregate_5m(rows,include_auction=mode)
                    basic=intersect_compare(agg,public)
                    v=volume_fit(agg,public,source_field="provider_volume")
                    a=volume_fit(agg,public,source_field="amount_yuan",field="amount")
                    modes["auction_in_first_5m" if mode else "auction_not_in_first_5m"]={
                        "ohlc":basic,"volume":v,"amount":a}
                detail["eastmoney_5m_vs_qmt_1m_aggregates"]=modes
            detail["status"]="DIAGNOSTIC_CROSS_SOURCES_NO_PRODUCTION_AUTHORIZATION"
        except Exception as exc:
            detail["status"]="ERROR_NO_PRODUCTION_AUTHORIZATION"
            detail["error"]=type(exc).__name__+": "+str(exc)[:250]
        report["stocks"][code]=detail
        progress("QMT_T1_CROSSCHECK_RESULT "+json.dumps({
            "symbol":code,"status":detail["status"],
            "revision":detail.get("t1_revision",{}).get("status"),
            "tencent_target_bars":detail.get("tencent_source",{}).get("target_bars"),
            "eastmoney_target_5m":detail.get("eastmoney_source",{}).get("target_bars")},
            ensure_ascii=False,sort_keys=True))
        time.sleep(.15)
    report["counts"]={
        "samples":len(symbols),
        "qmt_revision_detected":sum(1 for x in report["stocks"].values()
                if x.get("t1_revision",{}).get("status")=="QMT_T1_REVISION_DETECTED"),
        "qmt_prior_same":sum(1 for x in report["stocks"].values()
                if x.get("t1_revision",{}).get("status")=="SAME_AS_PRIOR_PRIVATE_SNAPSHOT"),
        "tencent_with_target":sum(1 for x in report["stocks"].values()
                if x.get("tencent_source",{}).get("target_bars",0)>0),
        "eastmoney_with_target":sum(1 for x in report["stocks"].values()
                if x.get("eastmoney_source",{}).get("target_bars",0)>0),
        "errors":sum(1 for x in report["stocks"].values() if x.get("status")=="ERROR_NO_PRODUCTION_AUTHORIZATION")}
    report["market_modified"]=False
    report["production_merge_authorized"]=False
    P.safe_save(folder/("report-"+datetime.now(P.CN).strftime("%Y%m%dT%H%M%S")+".json"),
                payload_bytes(report))
    progress("QMT_T1_CROSSCHECK_SUMMARY="+json.dumps(
        {"day":str(day),**report["counts"],"market_modified":False,
         "production_merge_authorized":False},sort_keys=True,ensure_ascii=False))
    return report

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("D:/stock"))
    parser.add_argument("--date",type=date.fromisoformat,default=DAY)
    parser.add_argument("--symbols",default=",".join(SAMPLES))
    args=parser.parse_args(argv)
    codes=[Q.normalize_code(x) for x in args.symbols.split(",")]
    if not 1<=len(codes)<=12 or len(set(codes))!=len(codes):
        parser.error("Only 1..12 distinct SH/SZ codes permitted for public cross-source audit")
    run(args.root,day=args.date,symbols=codes)

if __name__=="__main__":
    main()
