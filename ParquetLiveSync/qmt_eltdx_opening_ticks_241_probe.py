#!/usr/bin/env python3
"""Bounded formal 09:25 + historical trade-record feasibility for QMT 241 grid.

Source inputs: existing SHA-bound QMT 241 and eltdx TDX 240 private caches,
prior live 09:25 pilot report; one new live 0x0fc6 historical tick request
per specified stock-day. Do NOT treat virtual auction snapshots as trades.
0x0fc6 timestamps have minute, not second, precision and trade rows can
represent aggregated prints; a matching sample is diagnostic, not proof of
independently reconstructible OHLC. Never write production Parquet/H5.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_eltdx_1m_probe as X
import qmt_eltdx_auction_241_probe as A
import qmt_eltdx_auction_241_postmortem as M

FORMAT="qmt_eltdx_0931_historical_ticks_240_to_241_private_feasibility_v1"
FIELDS=A.VALUES
MAX_PAGES=48
PAGE_SIZE=1800


def trade_entry(item):
    """Select only actual regular trades, never status 8 auction snapshots."""
    kind=getattr(item,"event_kind",None)
    minute=getattr(item,"time_minutes",None)
    if (kind!="trade" or minute not in (9*60+30,9*60+31)
            or getattr(item,"status_raw",None)==8
            or getattr(item,"is_after_hours_fixed_price",False)):
        return None
    price=float(getattr(item,"price"))
    lots=float(getattr(item,"volume"))
    if (not math.isfinite(price) or not math.isfinite(lots)
        or price<=0 or lots<=0):
        raise ValueError("Invalid historical actual trade volume or price")
    idx=getattr(item,"absolute_index",None)
    if idx is not None and (not isinstance(idx,int) or idx<0):
        raise ValueError("Invalid historical trade global index")
    return {"minute":int(minute),"price":price,"lots":lots,
            "absolute_index":idx}


def entry_bucket(rows,target,order):
    """Aggregate observed prints; prices may be chronologically ambiguous."""
    if not rows:
        return None
    vals=list(rows) if order=="as_returned" else list(reversed(rows))
    prices=[x["price"] for x in vals]
    lots=sum(x["lots"] for x in vals)
    return {"open":prices[0],"high":max(prices),"low":min(prices),
            "close":prices[-1],"volume":lots,
            "amount":sum(x["price"]*x["lots"]*100 for x in vals)}


def bucket_trial(entries,target):
    groups={
        "minute_0930":[x for x in entries if x["minute"]==570],
        "minute_0931":[x for x in entries if x["minute"]==571],
        "minutes_0930_0931":list(entries)}
    summaries=[]
    for group,rows in groups.items():
        if not rows:
            summaries.append({"group":group,"status":"NO_ACTUAL_TRADES",
                              "trade_record_count":0})
            continue
        variations={}
        for direction in ("as_returned","reversed"):
            candidate=entry_bucket(rows,target,direction)
            fits={k:A.isnear(candidate[k],target[k],k) for k in FIELDS}
            variations[direction]=fits
        best=min(variations,key=lambda v:(-sum(variations[v].values()),v))
        fits=variations[best]
        summaries.append({
            "group":group,
            "trade_record_count":len(rows),
            "best_row_order_diagnostic":best,
            "field_fits":fits,
            "fields_passing":sum(fits.values()),
            "extrema_volume_amount_fit":all(fits[k] for k in
                                             ("high","low","volume","amount")),
            "all_six_fit":all(fits.values()),
            "price_order_not_chronologically_certified":True,
            "status":("ALL_SIX_FIELDS_MATCH_DIAGNOSTIC_ONLY"
                      if all(fits.values()) else "PARTIAL_OR_NO_FIT"),
        })
    return summaries


def interpret(trials):
    if any(t.get("all_six_fit") for t in trials):
        return "OBSERVED_TICK_BUCKET_ALL_SIX_FIELDS_FIT_BUT_SEQUENCE_NOT_CERTIFIED"
    if any(t.get("extrema_volume_amount_fit") for t in trials):
        return "OBSERVED_EXTREMA_VOLUME_AMOUNT_FIT_OPEN_CLOSE_UNCERTAIN"
    return "HISTORICAL_TICK_BUCKET_CANNOT_RECONSTRUCT_QMT_0931"


def formal_0925_from_trade_page(items,opening_qmt):
    events=[x for x in items if getattr(x,"event_kind",None)=="opening_match"
            and getattr(x,"time_minutes",None)==9*60+25
            and getattr(x,"status_raw",None)!=8]
    if len(events)!=1:
        return {"status":"FORMAL_0925_NOT_UNIQUE_IN_HISTORICAL_PAGE",
                "count":len(events)}
    event=events[0]
    price=float(event.price)
    lots=float(event.volume)
    amount=price*lots*100.
    if not (price>0 and lots>0):
        return {"status":"INVALID_HISTORICAL_0925_TRADE"}
    fits={
        **{k:A.isnear(opening_qmt[k],price,k) for k in A.OHLC},
        "volume":A.isnear(opening_qmt["volume"],lots,"volume"),
        "amount":A.isnear(opening_qmt["amount"],amount,"amount")}
    return {"status":("FORMAL_0925_MATCHES_QMT_0930"
                      if all(fits.values()) else "FORMAL_0925_QMT_MISMATCH"),
            "field_fits":fits,"count":1,
            "amount_is_derived_from_price_times_lots_times_100":True}


def inspect(qmt,tdx,pilot,trade_page):
    if len(qmt)!=241 or len(tdx)!=240:
        raise ValueError("Full source grids required")
    details=M.diagnostic(qmt,tdx,pilot)
    if details["model"]!="OPENING_MERGE_MATCH_AFTER_RESEARCH_ONLY_VOLUME_UNIT_ALIGNMENT":
        raise ValueError("No full SHA-certified source unit model for this stock-day")
    if not hasattr(trade_page,"ticks") or not hasattr(trade_page,"count"):
        raise ValueError("Invalid historical TradePage response")
    if trade_page.count!=len(trade_page.ticks):
        raise ValueError("Historical tick page count mismatch")
    seen=[]
    by_minutes=Counter()
    for item in trade_page.ticks:
        entry=trade_entry(item)
        if entry is not None:
            seen.append(entry)
            by_minutes[str(entry["minute"])]+=1
    trials=bucket_trial(seen,qmt[1])
    status=interpret(trials)
    opening=formal_0925_from_trade_page(trade_page.ticks,qmt[0])
    if opening["status"]!="FORMAL_0925_MATCHES_QMT_0930":
        status="HISTORICAL_FORMAL_0925_INCONSISTENT_WITH_QMT"
    return {
        "status":status,"opening":opening,
        "source_trade_page_record_count":trade_page.count,
        "selected_opening_trade_record_count":len(seen),
        "trade_record_minute_counts":dict(by_minutes),
        "bucket_trials":trials,
        "source_trade_rows":seen,
        "historical_trade_timestamp_resolution":"minute",
        "historical_trade_rows_not_guaranteed_level2_executions":True,
        "price_row_sequence_not_certified":True,
        "source_values_rewritten":False,
        "market_files_modified":False,
        "production_merge_authorized":False,
    }


def run(*,day=date(2026,10,14),stocks=A.DEFAULT_CODES,
        workspace=None,logger=print,client_factory=None):
    if not X.START<=day<=X.END:
        raise ValueError("Day outside SHA-bound original minute source")
    if (not 1<=len(stocks)<=len(A.DEFAULT_CODES)
        or len(set(stocks))!=len(stocks)
        or any(code not in A.DEFAULT_CODES for code in stocks)):
        raise ValueError("Only original three preaudited stocks permitted")
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    work=Path(workspace) if workspace else folder/"auction_0925_split_pilot"
    source_report=work/f"{day:%Y%m%d}_summary.private.json"
    if (folder.is_symlink() or work.is_symlink() or source_report.is_symlink()
        or not source_report.is_file()):
        raise ValueError("Missing/redirected original formal opening evidence")
    doc=json.loads(source_report.read_bytes())
    if (doc.get("format")!=A.FORMAT or doc.get("day")!=str(day)
        or doc.get("production_merge_authorized") is not False
        or doc.get("market_files_modified") is not False):
        raise ValueError("Original auction evidence version/provenance mismatch")
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    if client_factory is None:
        from eltdx import TdxClient
        client_factory=lambda:TdxClient(timeout=5,heartbeat_interval=None)
    outcomes={}
    counts=Counter()
    with client_factory() as client:
        if not hasattr(client.trades,"all_history"):
            raise RuntimeError("Installed eltdx version lacks historical trades")
        for code in stocks:
            try:
                evidence=doc["stocks"][code]
                if evidence.get("auction_0930_candidate_matches_qmt") is not True:
                    raise ValueError("09:25 formal opening match not certified")
                receipt=X.verified_cache(folder,code,stage,remote_only=False)
                qrows,qsha=X.read_qmt_source(stage,code)
                path=folder/"source_parquet"/(code.replace(".","_")+".parquet")
                if (not receipt or not qrows or path.is_symlink()
                    or evidence.get("qmt_sha256")!=qsha
                    or evidence.get("source_parquet_sha256")!=L.hash_file(path)):
                    raise ValueError("Old 240/241 evidence SHA or source changed")
                trows=pq.read_table(path).to_pylist()
                q=A.day_rows(qrows,day); t=A.day_rows(trows,day)
                # Validate the 100x volume explanation before any remote request.
                local=M.diagnostic(q,t,evidence)
                if (local["model"]!="OPENING_MERGE_MATCH_AFTER_RESEARCH_ONLY_VOLUME_UNIT_ALIGNMENT"
                    or local["volume_after_candidate_scale_all_240_fit"]!=240):
                    raise ValueError("First-minute volume-source calibration changed")
                remote=client.trades.all_history(
                    X.eltdx_code(code),day.isoformat(),
                    page_size=PAGE_SIZE,max_pages=MAX_PAGES,include_raw=False)
                if (remote.trading_date is not None
                    and str(remote.trading_date)!=str(day)):
                    raise ValueError("Historical tick source date mismatch")
                outcome=inspect(q,t,evidence,remote)
                # Save only opening vicinity original actual trade records, SHA
                # fingerprint, and summary to Git-ignored private work.
                raw=outcome.pop("source_trade_rows")
                payload=P.canonical({
                    "format":FORMAT,"day":str(day),"stock":code,
                    "source_qmt_sha256":qsha,
                    "source_tdx_1m_sha256":receipt["source_sha256"],
                    "limited_actual_trade_rows":raw,
                    "market_files_modified":False,
                    "production_merge_authorized":False})
                digest=hashlib.sha256(payload).hexdigest()
                file=work/f"{day:%Y%m%d}_{code.replace('.','_')}_opening_trade_rows.private.json"
                if file.is_symlink():
                    raise ValueError("Private trade evidence file is redirected")
                P.safe_save(file,payload)
                outcome["opening_trade_subset_sha256"]=digest
                outcome["source_qmt_sha256"]=qsha
                outcome["source_tdx_1m_sha256"]=receipt["source_sha256"]
            except Exception as exc:
                outcome={"status":"HISTORICAL_TICK_PILOT_ERROR",
                    "exception_type":type(exc).__name__,
                    "reason":str(exc)[:150],
                    "market_files_modified":False,
                    "production_merge_authorized":False}
            counts[outcome["status"]]+=1
            outcomes[code]=outcome
            logger("ELTDX_0931_TRADE_PILOT_STOCK="+json.dumps({
                "stock":code,"status":outcome["status"],
                "opening_formal_0925":outcome.get("opening",{}).get("status"),
                "selected_trade_records":outcome.get(
                    "selected_opening_trade_record_count"),
                "minute_counts":outcome.get("trade_record_minute_counts"),
                "trials":outcome.get("bucket_trials"),
                "error":outcome.get("reason"),
                "production_merge_authorized":False},
                ensure_ascii=False,sort_keys=True))
    dest=work/f"{day:%Y%m%d}_historical_ticks_feasibility.private.json"
    if dest.is_symlink():
        raise ValueError("Redirected private summary")
    result={"format":FORMAT,"day":str(day),"stocks":outcomes,
            "source_0931_ohlc_not_independently_certified":True,
            "market_files_modified":False,"production_merge_authorized":False}
    P.safe_save(dest,P.canonical(result))
    logger("ELTDX_0931_TRADE_PILOT_SUMMARY="+json.dumps({
        "format":FORMAT,"day":str(day),"stocks":len(stocks),
        "statuses":dict(counts),"market_files_modified":False,
        "production_merge_authorized":False},sort_keys=True,ensure_ascii=False))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day",type=date.fromisoformat,
                        default=date(2026,10,14))
    args=parser.parse_args()
    run(day=args.day)
