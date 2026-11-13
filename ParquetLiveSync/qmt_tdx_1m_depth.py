#!/usr/bin/env python3
"""Deep independent QMT-vs-Tongdaxin 1m OHLCVA source audit, 2026-10-14..11-12.

Uses the public 7709 TDX *actual historical 1m Kline* protocol (pytdx,
get_security_bars category=8), not Tencent 320 bars nor Eastmoney trends2.
Queries backward in 800-bar pages until entire target interval is covered,
checks minute-by-minute against SHA-verified QMT private sources, and saves
restartable independent private TDX Arrow + per-day evidence. Not an A-share
production merge. pytdx and eltdx are two clients of TDX, not two vendors.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_1m_recover as R

FORMAT="qmt_tdx_7709_deep_1m_ohlcva_crosscheck_v1"
START=R.START
END=R.END
BASE=P.BASE/"tdx_1m_crosscheck"
TDX_CATEGORY_1MIN=8  # astock-data-toolkit minute/tdx_download.py (pytdx).
PAGE=800
MAX_PAGES=40
HOSTS=(("180.153.18.170",7709),("180.153.18.172",80),
       ("202.108.253.139",80),("60.191.117.167",7709),
       ("111.229.247.189",7709))
FIELDS=("open","high","low","close","volume","amount")
OHLC=FIELDS[:4]
SCALE_CANDIDATES=(.0001,.001,.01,.1,1.,10.,100.,1000.,10000.)
OFFSETS_MS=(-120000,-60000,0,60000,120000)
CN=P.CN


def normalized_tdx(raw,code):
    """Decode pytdx 'datetime', OHLC, vol and amount without guessing units."""
    result={}
    for x in raw:
        dt=datetime.fromisoformat(str(x["datetime"]).replace("T"," "))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=CN)
        else:
            dt=dt.astimezone(CN)
        ts=int(dt.timestamp()*1000)
        a={k:float(x["vol"] if k=="volume" else x[k]) for k in FIELDS}
        if (not all(math.isfinite(a[k]) for k in FIELDS)
                or min(a[k] for k in OHLC)<=0
                or a["high"]<max(a["open"],a["close"])-.01
                or a["low"]>min(a["open"],a["close"])+.01
                or a["volume"]<0 or a["amount"]<0):
            raise ValueError("Invalid TDX 1-minute OHLCVA record "+str(dt))
        # pytdx compact float32 'denormal' zero: do not count as a trade.
        for field in ("volume","amount"):
            if abs(a[field])<1e-12:
                a[field]=0.
        if ts in result:
            prior=result[ts]
            if any(not math.isclose(prior[k],a[k],rel_tol=1e-8,abs_tol=1e-6)
                   for k in FIELDS):
                raise ValueError("Conflicting duplicate minute in TDX source")
        else:
            result[ts]={"ts":ts,"symbol":L.normal_symbol(code),**a}
    return list(sorted(result.values(),key=lambda x:x["ts"]))


class TdxPages:
    """One bounded single-thread TDX TCP session, server rotation on transport failure."""
    def __init__(self,client_factory=None,pause=.07,sleep=time.sleep):
        if client_factory is None:
            from pytdx.hq import TdxHq_API
            client_factory=lambda:TdxHq_API(heartbeat=True)
        self.client_factory=client_factory
        self.pause=pause
        self.sleep=sleep
        self.client=None
        self.index=0
        self.endpoint=None

    def connect(self):
        if self.client is not None:
            try:self.client.disconnect()
            except Exception:pass
            self.client=None
        for n in range(len(HOSTS)):
            index=(self.index+n)%len(HOSTS)
            ip,port=HOSTS[index]
            api=self.client_factory()
            try:
                if api.connect(ip,port,time_out=7):
                    self.client=api
                    self.index=index
                    self.endpoint=f"{ip}:{port}"
                    return
            except Exception:
                pass
            try:api.disconnect()
            except Exception:pass
        raise ConnectionError("No TDX 7709 minute source server reachable")

    def request(self,code,start):
        if self.client is None:
            self.connect()
        category=TDX_CATEGORY_1MIN
        market=1 if code.endswith(".SH") else 0
        last=None
        for attempt in range(3):
            try:
                result=self.client.get_security_bars(
                    category,market,code[:6],start,PAGE)
                if result is None:
                    raise IOError("TDX returned None")
                if len(result)>PAGE:
                    raise ValueError("TDX exceeded hard page-size limit")
                if self.pause:
                    self.sleep(self.pause)
                return result
            except (OSError,ConnectionError,TimeoutError) as exc:
                last=exc
                self.index=(self.index+1)%len(HOSTS)
                self.connect()
                self.sleep(.25*(attempt+1))
        raise ConnectionError("TDX paging failed after retries: "+str(last))

    def fetch(self,code,start=START,end=END,max_pages=MAX_PAGES):
        received=[]
        seen_first=set()
        latest=None
        oldest=None
        page_count=0
        for offset in range(0,max_pages*PAGE,PAGE):
            frame=self.request(code,offset)
            if not frame:
                break
            page_count+=1
            parsed=normalized_tdx(frame,code)
            if not parsed:
                raise ValueError("Nonempty TDX packet contains no valid Kline")
            first=parsed[0]["ts"]
            last=parsed[-1]["ts"]
            if first in seen_first:
                raise ValueError("TDX historical page repeated; cannot certify coverage")
            seen_first.add(first)
            latest=max(latest or last,last)
            oldest=min(oldest or first,first)
            received.extend(parsed)
            first_day=datetime.fromtimestamp(first/1000,CN).date()
            if first_day<start:
                break
        else:
            raise ValueError("TDX page cap reached before demonstrating history boundary")
        if not received:
            raise ValueError("TDX server returned zero real historical 1m bars")
        rows=normalized_tdx([{"datetime":datetime.fromtimestamp(r["ts"]/1000,CN).isoformat(),
                              "open":r["open"],"high":r["high"],"low":r["low"],
                              "close":r["close"],"vol":r["volume"],
                              "amount":r["amount"]} for r in received],code)
        # Strict window filter; do not mistake today's partial minute candles for yesterday.
        accepted=[r for r in rows
                  if start<=datetime.fromtimestamp(r["ts"]/1000,CN).date()<=end]
        return accepted,{"pages":page_count,"source_oldest_cn":datetime.fromtimestamp(oldest/1000,CN).isoformat(),
                         "source_newest_cn":datetime.fromtimestamp(latest/1000,CN).isoformat(),
                         "retention_covers_requested_start":
                         datetime.fromtimestamp(oldest/1000,CN).date()<=start,
                         "source_endpoint":self.endpoint}

    def close(self):
        if self.client is not None:
            try:self.client.disconnect()
            except Exception:pass
            self.client=None


def score_ratio(pairs,field,*,threshold=.035,abs_tol=1.):
    positive=[(float(a[field]),float(b[field])) for a,b in pairs
              if a[field]>1e-10 and b[field]>1e-10]
    if len(positive)<30:
        return {"status":"INSUFFICIENT_POSITIVE_MINUTES","pairs":len(positive)}
    ranked=[]
    for factor in SCALE_CANDIDATES:
        fit=sum(math.isclose(a,b*factor,rel_tol=threshold,abs_tol=abs_tol)
                for a,b in positive)/len(positive)
        diffs=[abs(a-b*factor)/max(abs(a),1.) for a,b in positive]
        ranked.append((fit,-statistics.median(diffs),factor))
    ranked.sort(reverse=True)
    best=ranked[0]
    stable=best[0]>=.85 and best[0]-ranked[1][0]>=.15
    return {"status":"CONSISTENT_VENDOR_UNIT_FACTOR_DIAGNOSTIC" if stable
            else "NO_UNIQUE_STABLE_VENDOR_FACTOR",
            "pairs":len(positive),"factor_tdx_to_qmt":best[2] if stable else None,
            "matching_fraction":round(best[0],6),
            "runner_up_matching_fraction":round(ranked[1][0],6),
            "median_relative_residual":round(-best[1],8)}


def score_day(qmt,tdx):
    """Reconcile 241-bar QMT vs typically 240-bar TDX without forging auction K."""
    q={int(x["ts"]):x for x in qmt}
    t={int(x["ts"]):x for x in tdx}
    trials=[]
    for offset in OFFSETS_MS:
        pairs=[(q[ts+offset],r) for ts,r in t.items() if ts+offset in q]
        if len(pairs)<15:
            continue
        ohlc=sum(all(math.isclose(a[k],b[k],rel_tol=.0015,abs_tol=.015)
                     for k in OHLC) for a,b in pairs)/len(pairs)
        # Amounts may differ for 09:30/09:31 auction attribution.
        cash=sum(math.isclose(a["amount"],b["amount"],rel_tol=.035,abs_tol=30.)
                 for a,b in pairs)/len(pairs)
        trials.append((ohlc+cash*.5,len(pairs),-abs(offset),offset,pairs,
                       ohlc,cash))
    if not trials:
        return {"status":"NO_MINUTE_TIME_OVERLAP","qmt_count":len(q),
                "tdx_count":len(t),"compared":0}
    trials.sort(key=lambda row:row[:3],reverse=True)
    best=trials[0]
    _,n,_,delta,pairs,ohlc,cash=best
    ambiguity=(len(trials)>1 and trials[1][0]>=best[0]-.01
               and trials[1][1]>=n*.95)
    vm=score_ratio(pairs,"volume",threshold=.045,abs_tol=.5)
    am=score_ratio(pairs,"amount",threshold=.035,abs_tol=30.)
    # Full TDX days often have 240 Kline periods, QMT 241 due to 09:30 auction.
    complete=(len(t)==240 and len(q)==241 and n>=235)
    high_confidence=(complete and not ambiguity and ohlc>=.95
                     and cash>=.85 and
                     vm.get("matching_fraction",0)>=.85
                     and am.get("matching_fraction",0)>=.85)
    return {"status":"MATCHED_1MIN_OHLCVA" if high_confidence else
            ("TDX_INCOMPLETE_OR_DIFFERENT_MINUTE_GRID" if not complete else
             "MINUTE_SOURCE_DIFFERENCE_REVIEW"),
            "qmt_count":len(q),"tdx_count":len(t),"compared":n,
            "tdx_to_qmt_time_offset_ms":delta,
            "offset_ambiguous":ambiguity,
            "full_240_tdx_vs_241_qmt_grid":complete,
            "ohlc_all_fields_fit":round(ohlc,6),
            "amount_minute_raw_fit":round(cash,6),
            "volume_factor":vm,"amount_factor":am,
            "qmt_only_count":len(q)-n,"tdx_only_count":len(t)-n}


def source_original(stage,code,original,recovery,expected):
    if code in original:
        doc=original[code]
        p=stage/"source_parquet"/(code.replace(".","_")+".parquet")
    elif code in recovery:
        doc=recovery[code]
        p=stage/"day_recovery"/"source_parquet"/(code.replace(".","_")+".parquet")
        if not doc.get("approved_days"):
            return None,None,None
    else:
        return None,None,None
    if p.is_symlink() or not p.is_file() or L.hash_file(p)!=doc.get("sha256"):
        raise ValueError("QMT cross-source original SHA failed: "+code)
    q=pq.read_table(p)
    if q.schema!=P.PRIVATE_SCHEMA:
        raise ValueError("QMT private source Arrow schema changed")
    return doc,q.to_pylist(),doc["sha256"]


def evidence_for_stock(code,qmt,tdx,expected_days):
    qby=defaultdict(list)
    tby=defaultdict(list)
    for x in qmt:
        qby[datetime.fromtimestamp(x["ts"]/1000,CN).date()].append(x)
    for x in tdx:
        tby[datetime.fromtimestamp(x["ts"]/1000,CN).date()].append(x)
    out={}
    for day in expected_days:
        out[day.isoformat()]=score_day(qby.get(day,[]),tby.get(day,[]))
    return out


def private_save_stock(root,code,rows,days,source_info,fingerprint):
    folder=Path(root)
    target=folder/"source_parquet"/(code.replace(".","_")+".parquet")
    receipt=folder/"receipts"/(code.replace(".","_")+".json")
    if target.is_symlink() or receipt.is_symlink():
        raise ValueError("Private TDX symlink refused")
    target.parent.mkdir(parents=True,exist_ok=True)
    receipt.parent.mkdir(parents=True,exist_ok=True)
    if receipt.exists():
        raise ValueError("Existing TDX receipt requires explicit SHA reuse")
    table=pa.Table.from_pylist(rows,schema=P.PRIVATE_SCHEMA)
    if target.exists():
        # Atomic private Parquet rename may succeed just before process
        # interruption; reattach only independently identical data.
        previous=pq.read_table(target)
        if not previous.equals(table,check_metadata=False):
            raise ValueError("Orphan TDX source Parquet differs; refuse overwrite")
        del previous
    else:
        temp=target.with_suffix(".parquet.part")
        if temp.is_symlink():
            raise ValueError("TDX tmp symlink")
        pq.write_table(table,temp,compression="zstd",row_group_size=8192)
        verify=pq.read_table(temp)
        if not verify.equals(table,check_metadata=False):
            raise ValueError("TDX private Parquet roundtrip altered values")
        del verify
        R.retry_private_atomic(temp,target)
    digest=L.hash_file(target)
    receipt_data={"format":FORMAT,"symbol":code,"rows":len(rows),
                  "sha256":digest,"fingerprint":fingerprint,
                  "source":source_info,"days":days,
                  "market_modified":False,"production_merge_authorized":False}
    P.safe_save(receipt,P.canonical(receipt_data))
    return receipt_data


def reuse_stock(root,code,fingerprint):
    folder=Path(root)
    path=folder/"receipts"/(code.replace(".","_")+".json")
    target=folder/"source_parquet"/(code.replace(".","_")+".parquet")
    if not path.is_file():
        if path.is_symlink() or target.is_symlink():
            raise ValueError("Linked private TDX candidate")
        return None
    if path.is_symlink() or target.is_symlink() or not target.is_file():
        raise ValueError("TDX private source cache is redirected/missing")
    doc=json.loads(path.read_bytes())
    if (doc.get("format")!=FORMAT or doc.get("symbol")!=code
            or doc.get("fingerprint")!=fingerprint or
            L.hash_file(target)!=doc.get("sha256")):
        raise ValueError("TDX SHA/source version mismatch")
    f=pq.ParquetFile(target)
    try:
        if f.metadata.num_rows!=doc.get("rows") or f.schema_arrow!=P.PRIVATE_SCHEMA:
            raise ValueError("TDX private Parquet footer/schema changed")
    finally:
        f.close()
    return doc


def run(root,*,start=START,end=END,limit=0,workspace=BASE,
        provider=None,logger=print):
    if start!=START or end!=END or limit<0 or limit>10000:
        raise ValueError("Only certified original 2026-10-14..2026-11-12 window permitted")
    stage=P.BASE/f"{start:%Y%m%d}_{end:%Y%m%d}"
    if stage.is_symlink() or not stage.is_dir():
        raise ValueError("QMT full-market original stage missing")
    expected,stocks,plan,calibration=R.load_bound_context(root,stage,start,end)
    logger("QMT_TDX_STEP_1_READONLY_AUDIT_5039_QMT_SOURCE_SHA")
    originals=R.validate_original(stage,expected,stocks,progress=logger)
    recovery={}
    recover_root=stage/"day_recovery"
    fingerprint_rec=P.sha_bytes(P.canonical({
        "original_plan_sha256":P.sha_bytes(P.canonical(plan)),
        "calibration_sha256":plan["calibration_sha256"],"format":R.FORMAT}))
    for code in stocks:
        if code not in originals:
            days=sorted(d.isoformat() for d in expected if code in expected[d])
            saved=R.validate_recovery_receipt(recover_root,code,fingerprint_rec,days)
            if saved is not None:
                recovery[code]=saved
    logger(f"QMT_TDX_SOURCE_BASE_STOCKS_FULL={len(originals)} PARTIAL={len(recovery)}")
    folder=Path(workspace)/f"{start:%Y%m%d}_{end:%Y%m%d}"
    folder.mkdir(parents=True,exist_ok=True)
    original_plan_sha=P.sha_bytes(P.canonical(plan))
    # Anchor source provenance stays stable; any changed QMT stock SHA fails to reuse old TDX receipt.
    order=list(dict.fromkeys(
        [x for x in P.ANCHORS if x in originals]+
        [x for x in stocks if x in originals or x in recovery]))
    if provider is None:
        provider=TdxPages()
    accepted=0
    cached=0
    failed={}
    all_status=Counter()
    all_daykeys=0
    all_qualified=0
    tried=0
    stop=False
    try:
        for code in order:
            if limit and tried>=limit:
                stop=True
                break
            original,qrows,qsha=source_original(stage,code,originals,recovery,expected)
            if original is None:
                continue
            days=sorted(d for d in expected if code in expected[d])
            fp=P.sha_bytes(P.canonical({
                "format":FORMAT,"symbol":code,
                "plan_sha256":original_plan_sha,
                "qmt_private_sha256":qsha,"reference_days":[str(x) for x in days],
                "frequency":"1min","tdx_original_units":True}))
            try:
                cached_receipt=reuse_stock(folder,code,fp)
                if cached_receipt:
                    cached+=1
                    status=cached_receipt
                else:
                    tried+=1
                    trows,source_info=provider.fetch(code,start,end)
                    checks=evidence_for_stock(code,qrows,trows,days)
                    status=private_save_stock(folder,code,trows,checks,source_info,fp)
                accepted+=1
                for d,result in status["days"].items():
                    all_daykeys+=1
                    all_status[result["status"]]+=1
                    if result["status"]=="MATCHED_1MIN_OHLCVA":
                        all_qualified+=1
                if accepted<=3 or accepted%50==0:
                    logger(f"QMT_TDX_PROGRESS={accepted}/{len(order)} last={code} "
                           f"TDX_minutes={status['rows']} matched_days="+
                           str(sum(x["status"]=="MATCHED_1MIN_OHLCVA"
                                   for x in status["days"].values())))
            except Exception as exc:
                failed[code]=type(exc).__name__+": "+str(exc)[:250]
                logger(f"QMT_TDX_SOURCE_REJECT {code} {failed[code]}")
                if len(failed)>=12 and accepted==0:
                    raise RuntimeError("TDX source unavailable; fail closed before any broad fetch")
            if tried and tried%50==0:
                logger(f"QMT_TDX_NEW_SOURCE_STOCKS={tried}")
    finally:
        provider.close()
    summary={"format":FORMAT,"window":[str(start),str(end)],
             "total_market_symbols":len(stocks),
             "original_qmt_verified":len(originals),
             "qmt_partial_day_recovery_stocks":len(recovery),
             "tdx_stocks_accepted_or_cached":accepted,
             "tdx_private_cached":cached,"attempted_new_tdx_stocks":tried,
             "tdx_stock_failures":len(failed),
             "failure_examples":list(failed.items())[:10],
             "minute_level_checked_stock_days":all_daykeys,
             "strict_matched_stock_days":all_qualified,
             "status_distribution":dict(all_status),
             "stopped_by_limit":stop,
             "provider_independence":"TDX vs QMT (pytdx and eltdx are same TDX server family)",
             "market_modified":False,"production_merge_authorized":False,
             "private_root":str(folder)}
    P.safe_save(folder/"latest_report.json",P.canonical(summary))
    logger("QMT_TDX_DEEP_CROSSCHECK_SUMMARY="+json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path("D:/stock"))
    p.add_argument("--start",type=date.fromisoformat,default=START)
    p.add_argument("--end",type=date.fromisoformat,default=END)
    p.add_argument("--limit-stocks",type=int,default=0)
    args=p.parse_args(argv)
    run(args.root,start=args.start,end=args.end,limit=args.limit_stocks)


if __name__=="__main__":
    main()
