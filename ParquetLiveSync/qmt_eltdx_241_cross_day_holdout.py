#!/usr/bin/env python3
"""Independent 240->241 first-bar inference: SHA-bound two-date holdout.

NOT production data conversion. Two predeclared out-of-sample days, three
predeclared stocks, original cached 240 eltdx and 241 QMT physical sources.
New actual 0x0fc6 historical trade page per stock-day. Source-only candidate
first, QMT reference validation second. Source values never rewritten.
eltdx trade order is not proven independently chronological, its estimated
turnover is not an authoritative independent amount.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_eltdx_1m_probe as X
import qmt_eltdx_auction_241_probe as A
import qmt_eltdx_opening_ticks_241_probe as T
import qmt_eltdx_opening_tick_alignment as J
import qmt_eltdx_source_independent_241_pilot as R

FORMAT="eltdx_source_only_241_cross_day_holdout_private_v1"
ALLOWED_DAYS=(date(2026,10,15),date(2026,10,16))
CODES=A.DEFAULT_CODES
PAGE_SIZE=1800
MAX_PAGES=48


def extract_live_page(page,day):
    if (not hasattr(page,"ticks") or not hasattr(page,"count")
        or page.count!=len(page.ticks)):
        raise ValueError("Incomplete or invalid historical trade page")
    if getattr(page,"trading_date",None) is not None and str(page.trading_date)!=str(day):
        raise ValueError("Historical trade page date mismatch")
    formal=[x for x in page.ticks if getattr(x,"event_kind",None)=="opening_match"
            and getattr(x,"time_minutes",None)==565
            and getattr(x,"status_raw",None)!=8]
    if len(formal)!=1:
        raise ValueError("Formal 09:25 opening match missing or nonunique")
    auction=R.formal_event(formal[0],day)
    rows=[rec for item in page.ticks if (rec:=T.trade_entry(item)) is not None]
    minute_counts=Counter(r["minute"] for r in rows)
    if minute_counts[570]==0 or minute_counts[571]==0:
        raise ValueError("Historical regular trade minute 09:30/09:31 missing")
    if len(rows)>40000:
        raise ValueError("Unexpectedly many opening minute records")
    return auction,rows,{"09:30":minute_counts[570],"09:31":minute_counts[571]}


def per_day(q,t,auction,rows):
    if (len(q)!=241 or len(t)!=240
        or A.label(q[0])!=(9,30) or A.label(q[1])!=(9,31)
        or A.label(q[2])!=(9,32) or A.label(t[0])!=(9,31)
        or [x["ts"] for x in q[1:]]!=[x["ts"] for x in t]):
        raise ValueError("Missing/full-day incompatible 241/240 source grid")
    # Never call QMT-based inference to compute values. QMT validation later.
    source=R.derive_source_only(t[0],auction,rows)
    ref=R.reference_check(source,q)
    inferred=source["regular_0931_source_only_candidate"]
    genuine_0930=[r for r in rows if r["minute"]==570]
    genuine_0931=[r for r in rows if r["minute"]==571]
    if not genuine_0930 or not genuine_0931:
        raise ValueError("No adjacent regular transaction minutes")
    minute_0930=T.entry_bucket(genuine_0930,q[1],"as_returned")
    minute_0931=T.entry_bucket(genuine_0931,q[2],"as_returned")
    flow={
        "09:30_trades_to_QMT_09:31_exact_volume":
            J.strict_fit(minute_0930["volume"],q[1]["volume"],"volume"),
        "09:31_trades_to_QMT_09:32_exact_volume":
            J.strict_fit(minute_0931["volume"],q[2]["volume"],"volume"),
        "09:30_trades_to_QMT_09:31_amount_tolerant":
            A.isnear(minute_0930["amount"],q[1]["amount"],"amount"),
        "09:31_trades_to_QMT_09:32_amount_tolerant":
            A.isnear(minute_0931["amount"],q[2]["amount"],"amount"),
        "historical_09:30_first_record_open_matches_QMT_strict":
            J.strict_fit(inferred["open"],q[1]["open"],"open")}
    # Independent 240-bar source price/amount check on regular 239:
    rest_field_fit={k:sum(A.isnear(qi[k],ti[k],k)
         for qi,ti in zip(q[2:],t[1:])) for k in (*A.OHLC,"amount")}
    rest_volume_fit=sum(J.strict_fit(qi["volume"],ti["volume"]*.01,"volume")
                        for qi,ti in zip(q[2:],t[1:]))
    known=ref["0930_auction"]["all_six_known"] and ref["0931_regular"]["all_six_known"]
    tolerant=ref["0930_auction"]["all_known_tolerantly_match"] and ref["0931_regular"]["all_known_tolerantly_match"]
    strict=ref["0930_auction"]["all_known_strictly_match"] and ref["0931_regular"]["all_known_strictly_match"]
    minute_support=all(flow.values())
    if not known:
        status="HOLDOUT_PRICE_EXTREME_OR_FIELD_NOT_IDENTIFIABLE"
    elif not tolerant or rest_volume_fit!=239 or any(v!=239 for v in rest_field_fit.values()):
        status="HOLDOUT_CROSS_SOURCE_DIFFERENCES_REVIEW"
    elif not minute_support:
        status="HOLDOUT_TRADE_MINUTE_ALIGNMENT_REVIEW"
    elif strict:
        status="HOLDOUT_ALL_SIX_STRICTLY_MATCH_SOURCE_CANDIDATE"
    else:
        status="HOLDOUT_ALL_SIX_TOLERANTLY_MATCH_NOT_STRICT"
    return {
        "status":status,
        "source_only_candidate":source,
        "qmt_validation_only":ref,
        "minute_label_trades_to_next_kline_evidence":flow,
        "remaining_239_ohlc_amount_tolerant_match_counts":rest_field_fit,
        "remaining_239_volume_exact_after_factor_001":rest_volume_fit,
        "original_240_to_241_candidate_not_written_to_market":True,
        "source_chronology_independently_certified":False,
        "formal_amount_is_computed_not_independent_turnover":True,
        "market_files_modified":False,"production_merge_authorized":False}


def run(*,days=ALLOWED_DAYS,stocks=CODES,preflight_only=False,
        client_factory=None,logger=print):
    if (not days or len(days)>2 or len(set(days))!=len(days)
        or any(d not in ALLOWED_DAYS for d in days)):
        raise ValueError("Only explicit 2026-10-15/16 days are allowed")
    if (not 1<=len(stocks)<=3 or len(set(stocks))!=len(stocks)
        or any(code not in CODES for code in stocks)):
        raise ValueError("Only original three anchor stocks are allowed")
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    output=folder/"auction_0925_split_pilot"/"cross_day_holdout"
    if folder.is_symlink() or output.is_symlink():
        raise ValueError("Redirected private holdout workspace")
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    # Preflight the entire specified local workload *before* any 7709 call.
    verified={}
    for code in stocks:
        receipt=X.verified_cache(folder,code,stage,remote_only=False)
        qrows,qsha=X.read_qmt_source(stage,code)
        path=folder/"source_parquet"/(code.replace(".","_")+".parquet")
        if (receipt is None or not qrows or path.is_symlink()
            or L.hash_file(path)!=receipt["source_sha256"]):
            raise ValueError("Source SHA/receipt missing for "+code)
        file=pq.read_table(path)
        if file.schema!=P.PRIVATE_SCHEMA:
            raise ValueError("Original TDX Arrow schema changed")
        trows=file.to_pylist()
        for day in days:
            q=A.day_rows(qrows,day)
            t=A.day_rows(trows,day)
            if (len(q)!=241 or len(t)!=240
                or A.label(q[0])!=(9,30) or A.label(t[0])!=(9,31)
                or [x["ts"] for x in q[1:]]!=[x["ts"] for x in t]):
                raise ValueError("Full-day 241/240 grid missing "+code+" "+str(day))
            verified[(day,code)]={
                "q":q,"t":t,"qsha":qsha,"tsha":receipt["source_sha256"]}
    result={"format":FORMAT,"days":[str(d) for d in days],
            "stock_days":{},"preflight_only":preflight_only,
            "market_files_modified":False,"production_merge_authorized":False}
    if preflight_only:
        logger("ELTDX_241_HOLDOUT_PREFLIGHT="+json.dumps({
            "format":FORMAT,"stock_days_verified":len(verified),
            "days":[str(d) for d in days],
            "market_files_modified":False,"production_merge_authorized":False},
            sort_keys=True))
        return result
    if client_factory is None:
        from eltdx import TdxClient
        client_factory=lambda:TdxClient(timeout=5,heartbeat_interval=None)
    totals=Counter()
    with client_factory() as client:
        if not hasattr(client.trades,"all_history"):
            raise RuntimeError("Installed eltdx lacks historical all_history API")
        for day in days:
            for code in stocks:
                original=verified[(day,code)]
                key=f"{day}/{code}"
                try:
                    page=client.trades.all_history(
                        X.eltdx_code(code),str(day),
                        page_size=PAGE_SIZE,max_pages=MAX_PAGES,
                        include_raw=False)
                    auction,rows,record_counts=extract_live_page(page,day)
                    audited=per_day(original["q"],original["t"],auction,rows)
                    # Persist only this new date's opening historical evidence:
                    private=P.canonical({
                        "format":FORMAT,"day":str(day),"stock":code,
                        "original_qmt_SHA256_validation_only":original["qsha"],
                        "original_eltdx_240_SHA256":original["tsha"],
                        "formal_0925_source":auction,
                        "historical_opening_0930_0931_trades":rows,
                        "trade_record_counts":record_counts,
                        "source_only_candidate_and_separate_validation":audited,
                        "market_files_modified":False,
                        "production_merge_authorized":False})
                    digest=hashlib.sha256(private).hexdigest()
                    file=output/f"{day:%Y%m%d}_{code.replace('.','_')}_holdout.private.json"
                    if file.is_symlink():
                        raise ValueError("Private holdout file redirected")
                    P.safe_save(file,private)
                    audited["private_SHA256"]=digest
                    audited["record_counts"]=record_counts
                    # Keep summary small: no licensed raw OHLCVA in terminal.
                    outcome=audited
                except Exception as exc:
                    outcome={"status":"HOLDOUT_PROBE_ERROR",
                             "reason":type(exc).__name__+": "+str(exc)[:150],
                             "market_files_modified":False,
                             "production_merge_authorized":False}
                result["stock_days"][key]=outcome
                totals[outcome["status"]]+=1
                logger("ELTDX_241_HOLDOUT_CASE="+json.dumps({
                    "day":str(day),"stock":code,"status":outcome["status"],
                    "minute_label_flow":outcome.get(
                        "minute_label_trades_to_next_kline_evidence"),
                    "regular_0931_six_tolerant_match":outcome.get(
                        "qmt_validation_only",{}).get("0931_regular",{}).get(
                            "all_known_tolerantly_match"),
                    "regular_0931_six_strict_match":outcome.get(
                        "qmt_validation_only",{}).get("0931_regular",{}).get(
                            "all_known_strictly_match"),
                    "unknown_0931_fields":6-outcome.get(
                        "qmt_validation_only",{}).get("0931_regular",{}).get(
                            "known_fields",0),
                    "first_trade_open_chronology_certified":False,
                    "error":outcome.get("reason"),
                    "production_merge_authorized":False},sort_keys=True))
    summary={"format":FORMAT,"days":[str(d) for d in days],
             "cases":len(verified),"statuses":dict(totals),
             "source_0931_open_time_order_independently_certified":False,
             "amount_strictness_independent_source_unproven":True,
             "market_files_modified":False,"production_merge_authorized":False}
    report=output/"20261015_20261016_holdout_summary.private.json"
    if report.is_symlink():
        raise ValueError("Private summary redirected")
    P.safe_save(report,P.canonical({"summary":summary,"stock_days":result["stock_days"]}))
    logger("ELTDX_241_HOLDOUT_SUMMARY="+json.dumps(
        summary,sort_keys=True,ensure_ascii=False))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days",default="2026-10-15,2026-10-16")
    parser.add_argument("--preflight-only",action="store_true")
    args=parser.parse_args()
    run(days=tuple(date.fromisoformat(s.strip()) for s in args.days.split(",")),
        preflight_only=args.preflight_only)
