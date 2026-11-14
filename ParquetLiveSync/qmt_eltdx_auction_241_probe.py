#!/usr/bin/env python3
"""Bounded live 09:25 eltdx auction-vs-QMT 241/Tongdaxin 240 first-minute audit.

Uses the already SHA-validated QMT and eltdx PRIVATE snapshots. Network access
is limited to the explicitly listed stocks' historical *formal opening matches*.
Results are diagnostic only: auction series virtual matches are never treated
as trades, no synthetic 09:31 OHLC is invented, and purchased Parquet/H5 files
are never read for writing or modified.  Typical normal A-share LOT = 100 shares.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from datetime import date,datetime
import json
import math
from pathlib import Path

import pyarrow.parquet as pq
import local_layout as L
import qmt_1m_pipeline as P
import qmt_eltdx_1m_probe as X

FORMAT="qmt_eltdx_historical_0925_auction_to_241_1m_readonly_probe_v1"
DEFAULT_CODES=("600000.SH","000001.SZ","688001.SH")
OHLC=("open","high","low","close")
VALUES=(*OHLC,"volume","amount")
VOLUME_FACTORS=(.01,1.,100.)


def isnear(x,y,field):
    return math.isclose(float(x),float(y),
        rel_tol=.045 if field=="volume" else .035 if field=="amount" else .0015,
        abs_tol=.5 if field=="volume" else 30. if field=="amount" else .015)


def day_rows(rows,target):
    return sorted((v for v in rows
        if datetime.fromtimestamp(v["ts"]/1000,P.CN).date()==target),
        key=lambda r:r["ts"])


def label(row):
    dt=datetime.fromtimestamp(row["ts"]/1000,P.CN)
    return dt.hour,dt.minute


def combined(a,b):
    if a["ts"]>=b["ts"]:
        raise ValueError("QMT opening bar order invalid")
    return {"open":a["open"],"high":max(a["high"],b["high"]),
            "low":min(a["low"],b["low"]),"close":b["close"],
            "volume":a["volume"]+b["volume"],
            "amount":a["amount"]+b["amount"]}


def evaluate(qmt,tdx,*,auction_price,auction_lots,auction_amount):
    """Reconciliation; successful pair is NOT permission to invent new bars."""
    result={"status":"SOURCE_INCOMPLETE","opening_price_fit":False,
            "opening_ohlc_fit":False,"auction_amount_fit":False,
            "opening_volume_unit_factors_compatible":[],
            "combined_first_1m_field_fits":{},"first_minute_all_fields_fit":False,
            "remaining_239_fields_not_tested":True,
            "cannot_derive_regular_0931_open_from_merged_kline_alone":True,
            "cannot_derive_regular_0931_extrema_from_merged_kline_alone":True,
            "source_values_rewritten":False,"production_merge_authorized":False}
    if len(qmt)!=241 or len(tdx)!=240 or label(qmt[0])!=(9,30) or label(qmt[1])!=(9,31) or label(tdx[0])!=(9,31):
        return result
    if (not all(math.isfinite(float(x)) for x in
               (auction_price,auction_lots,auction_amount)) or
               auction_price<=0 or auction_lots<=0 or auction_amount<=0):
        return {**result,"status":"INVALID_FORMAL_AUCTION"}
    a,b,c=qmt[0],qmt[1],tdx[0]
    result["opening_price_fit"]=isnear(a["open"],auction_price,"open")
    result["opening_ohlc_fit"]=all(
        isnear(a[key],auction_price,key) for key in OHLC)
    result["auction_amount_fit"]=isnear(a["amount"],auction_amount,"amount")
    result["opening_volume_unit_factors_compatible"]=[
        factor for factor in VOLUME_FACTORS
        if isnear(a["volume"],auction_lots*factor,"volume")]
    result["combined_first_1m_field_fits"]={
        field:isnear(combined(a,b)[field],c[field],field) for field in VALUES}
    result["first_minute_all_fields_fit"]=all(
        result["combined_first_1m_field_fits"].values())
    result["auction_0930_candidate_matches_qmt"]=bool(
        result["opening_ohlc_fit"] and result["auction_amount_fit"] and
        result["opening_volume_unit_factors_compatible"])
    result["status"]=(
        "FORMAL_0925_MATCHES_QMT_0930_AND_TDX_0931_MERGE"
        if result["auction_0930_candidate_matches_qmt"] and
           result["first_minute_all_fields_fit"]
        else "FIRST_MINUTE_SPLIT_REQUIRES_REVIEW")
    return result


def run(*,day,stocks=DEFAULT_CODES,workspace=None,logger=print,
        client_factory=None):
    if not X.START<=day<=X.END:
        raise ValueError("Use only the certified existing 22-trading-day original source window")
    if not 1<=len(stocks)<=6 or len(set(stocks))!=len(stocks):
        raise ValueError("Only 1..6 distinct bounded pilot stocks")
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    workspace=Path(workspace) if workspace else folder/"auction_0925_split_pilot"
    if workspace.is_symlink() or folder.is_symlink():
        raise ValueError("Redirected private pilot workspace")
    if client_factory is None:
        from eltdx import TdxClient
        client_factory=lambda:TdxClient(timeout=4,heartbeat_interval=None)
    result={"format":FORMAT,"day":day.isoformat(),"stocks":{},
            "market_files_modified":False,"production_merge_authorized":False,
            "cannot_certify_missing_0931_OHLC_from_0925_and_240_bars":True}
    counts=Counter()
    client=client_factory()
    try:
        with client:
            if not hasattr(client.trades,"opening_match_history"):
                raise RuntimeError(
                    "Installed eltdx lacks trades.opening_match_history; upgrade SDK first")
            for code in stocks:
                code=X.D.P.normalize_code(code)
                try:
                    # Verifies byte SHA, Arrow schema and source-QMT binding.
                    cached=X.verified_cache(folder,code,stage,remote_only=False)
                    if cached is None:
                        raise ValueError("Missing cached 240-bar eltdx SHA receipt")
                    original,q_sha=X.read_qmt_source(stage,code)
                    if not original:
                        raise ValueError("No SHA-verified full 241-bar QMT source")
                    source=folder/"source_parquet"/(code.replace(".","_")+".parquet")
                    if source.is_symlink() or L.hash_file(source)!=cached["source_sha256"]:
                        raise ValueError("eltdx source SHA changed")
                    tdx=pq.read_table(source).to_pylist()
                    q=day_rows(original,day)
                    t=day_rows(tdx,day)
                    # Unlike 0x056a process points, 0x0fc6 gives formal
                    # 09:25 executions. Its amount is computed price*lots*100.
                    event=client.trades.opening_match_history(
                        L.normal_symbol(code).lower(),day.isoformat(),
                        page_size=1800,max_pages=24)
                    if event is None:
                        outcome={"status":"NO_HISTORICAL_FORMAL_0925_MATCH"}
                    elif (event.time_label!="09:25" or
                          event.event_kind!="opening_match" or
                          not event.is_opening_match):
                        outcome={"status":"INVALID_AUCTION_EVENT_KIND"}
                    else:
                        outcome=evaluate(q,t,auction_price=event.price,
                            auction_lots=event.volume,
                            auction_amount=event.trade_amount_yuan)
                        outcome["formal_auction_record"]={
                            "source":"eltdx historical 0x0fc6 actual opening match",
                            "volume_unit":"lots",
                            "amount_is_derived_from_price_times_lots_times_100":True}
                    outcome["source_parquet_sha256"]=cached["source_sha256"]
                    outcome["qmt_sha256"]=q_sha
                except Exception as exc:
                    outcome={"status":"HISTORICAL_AUCTION_PILOT_ERROR",
                             "reason":type(exc).__name__+": "+str(exc)[:180]}
                counts[outcome["status"]]+=1
                result["stocks"][code]=outcome
                logger("ELTDX_AUCTION_SPLIT_STOCK="+json.dumps(
                    {"stock":code,"status":outcome["status"],
                     "first_minute_all_fields_fit":outcome.get(
                       "first_minute_all_fields_fit"),
                     "auction_0930_candidate_matches_qmt":outcome.get(
                       "auction_0930_candidate_matches_qmt")},
                    sort_keys=True,ensure_ascii=False))
    finally:
        pass  # TdxClient manages its own context
    out=workspace/f"{day:%Y%m%d}_summary.private.json"
    if out.is_symlink():
        raise ValueError("Redirected private report")
    P.safe_save(out,P.canonical(result))
    summary={"format":FORMAT,"day":day.isoformat(),"stocks_checked":len(stocks),
             "statuses":dict(counts),"production_merge_authorized":False,
             "formal_auction_not_virtual_auction_snapshot":True,
             "regular_0931_OHLC_not_yet_reconstructible_without_trade_detail":True,
             "market_files_modified":False}
    logger("ELTDX_AUCTION_241_FEASIBILITY_SUMMARY="+json.dumps(
        summary,sort_keys=True,ensure_ascii=False))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day",type=date.fromisoformat,default=date(2026,10,14))
    parser.add_argument("--stocks",default=",".join(DEFAULT_CODES))
    args=parser.parse_args(argv)
    run(day=args.day,stocks=tuple(v.strip() for v in args.stocks.split(",")))


if __name__=="__main__":
    main()
