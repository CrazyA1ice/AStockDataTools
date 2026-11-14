#!/usr/bin/env python3
"""Source-only 09:30+09:31 candidate reconstruction against a separate QMT oracle.

Bounded 3-stock historical 2026-10-14 research.  The 09:30 auction record
comes from a NEW eltdx 0x0fc6 formal opening-match query (its actual numeric
fields are persisted privately with SHA). The regular 09:31 candidates use
ONLY the original eltdx 240-bar opening K and previously SHA-pinned real
historical minute-09:30 trades, not the QMT 241-bar answers.
Only afterwards compare against original QMT for validation. This is NOT a
production merge: the trade-record ordering/coverage are not certified, trade
amount is price*lots*100 derived, and ambiguous extrema remain NULL.
No modifications to original 240/241, licensed Parquet or H5.
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
import qmt_eltdx_opening_ticks_241_probe as T
import qmt_eltdx_opening_tick_alignment as J

FORMAT="eltdx_source_only_0925_plus_240_to_241_0931_candidate_v1"
FIELDS=A.VALUES
VOLUME_FACTOR=.01
PRICE_EPS=.0001


def formal_event(event,day):
    """Extract true executed 09:25; virtual matching snapshots never qualify."""
    if (event is None or getattr(event,"event_kind",None)!="opening_match"
        or getattr(event,"time_label",None)!="09:25"
        or getattr(event,"is_opening_match",False) is not True
        or getattr(event,"status_raw",None)==8):
        raise ValueError("Missing/invalid 09:25 formally executed trade")
    when=getattr(event,"trade_datetime",None)
    if when is not None and when.date()!=day:
        raise ValueError("Opening-match trading date mismatch")
    price=float(event.price)
    lots=float(event.volume)
    if (not math.isfinite(price) or not math.isfinite(lots)
        or price<=0 or lots<=0):
        raise ValueError("Invalid 09:25 executed price/volume")
    amount=price*lots*100.
    if (not math.isfinite(amount) or amount<=0
        or not A.isnear(amount,float(event.trade_amount_yuan),"amount")):
        raise ValueError("Inconsistent calculated auction trade amount")
    return {
        "event_kind":"opening_match","time_label":"09:25",
        "price":price,"volume_lots":lots,
        "trade_amount_yuan_derived":amount,
        "amount_not_independent_exchange_turnover":True,
        "unit_lot_shares":100,
    }


def derive_source_only(native,auction,rows):
    """Infer possible first regular minute without reading any QMT reference.

    All fields of the derived candidate come exclusively from eltdx source
    values; first real trade is only a PROVISIONAL open, not a certified trade
    chronology. Price extrema from merged bar are valid iff not solely auction
    extrema, or a real minute-09:30 trade explicitly observed that price.
    """
    if not rows:
        raise ValueError("No historical 09:30 actual trade prints")
    ticks=[]
    indices=[]
    for row in rows:
        if row.get("minute")!=570:
            continue
        p=float(row["price"]);v=float(row["lots"])
        if not (math.isfinite(p) and math.isfinite(v) and p>0 and v>0):
            raise ValueError("Invalid regular 09:30 print")
        idx=row.get("absolute_index")
        if idx is not None:
            if not isinstance(idx,int) or idx<0:
                raise ValueError("Invalid original trade index")
            indices.append(idx)
        ticks.append((p,v))
    if not ticks:
        raise ValueError("No real source transactions tagged 09:30")
    price=float(auction["price"])
    lot=float(auction["volume_lots"])
    amt=float(auction["trade_amount_yuan_derived"])
    values={k:float(native[k]) for k in FIELDS}
    if (not all(math.isfinite(v) for v in values.values())
        or values["volume"]<=0 or values["amount"]<=0
        or values["high"]<max(values["open"],values["close"])-.01
        or values["low"]>min(values["open"],values["close"])+.01
        or not A.isnear(values["open"],price,"open")):
        raise ValueError("Native first minute not consistent with auction")
    v=values["volume"]*VOLUME_FACTOR-lot
    a=values["amount"]-amt
    if v<=0 or a<=0:
        raise ValueError("Auction subtraction leaves no regular volume/amount")
    high=values["high"]
    low=values["low"]
    if high<price-PRICE_EPS or low>price+PRICE_EPS:
        raise ValueError("Native merged extrema do not contain auction price")
    hits_auction=any(abs(p-price)<=PRICE_EPS for p,_ in ticks)
    if high>price+PRICE_EPS:
        high_source="merged_high_above_auction"
        regular_high=high
    elif abs(high-price)<=PRICE_EPS and hits_auction:
        high_source="regular_trade_observed_at_auction_high"
        regular_high=high
    else:
        high_source="not_identifiable_from_merged_extreme"
        regular_high=None
    if low<price-PRICE_EPS:
        low_source="merged_low_below_auction"
        regular_low=low
    elif abs(low-price)<=PRICE_EPS and hits_auction:
        low_source="regular_trade_observed_at_auction_low"
        regular_low=low
    else:
        low_source="not_identifiable_from_merged_extreme"
        regular_low=None
    # A 09:30 minute label for 0x0fc6 maps to QMT 09:31, as supported by
    # the 3-stock strict volume alignment; ordering is *not* independently
    # certified despite monotonic original index.
    regular={
        "open":ticks[0][0],"high":regular_high,
        "low":regular_low,"close":values["close"],
        "volume":v,"amount":a}
    auction_bar={
        "open":price,"high":price,"low":price,"close":price,
        "volume":lot,"amount":amt}
    if not (J.strict_fit(values["close"],regular["close"],"close")
        and (regular_high is None or high>=regular["open"]-PRICE_EPS)
        and (regular_low is None or low<=regular["open"]+PRICE_EPS)):
        raise ValueError("Derived OHLC violates independent market bounds")
    order="monotone_increasing" if indices and all(
        x<y for x,y in zip(indices,indices[1:])) else "unverified"
    return {
        "auction_0930_source_only":auction_bar,
        "regular_0931_source_only_candidate":regular,
        "identified_field_count":sum(v is not None for v in regular.values()),
        "high_reason":high_source,"low_reason":low_source,
        "candidate_open_from_first_returned_regular_trade":True,
        "trade_original_index_order":order,
        "trade_sequence_chronology_certified":False,
        "independent_0931_open_certified":False,
        "auction_amount_derived_not_exchange_independent":True,
        "candidate_241_bar_set_not_written":True,
        "source_only_candidate_does_not_use_qmt_answers":True,
        "production_merge_authorized":False,
    }


def reference_check(candidate,qmt):
    """QMT is only a sealed validation oracle, never candidate construction."""
    if len(qmt)!=241 or A.label(qmt[0])!=(9,30) or A.label(qmt[1])!=(9,31):
        raise ValueError("Reference QMT grid invalid")
    auction=candidate["auction_0930_source_only"]
    regular=candidate["regular_0931_source_only_candidate"]
    out={}
    for name,actual,reference in (("0930_auction",auction,qmt[0]),
                                   ("0931_regular",regular,qmt[1])):
        fits={}
        strict={}
        for k in FIELDS:
            fits[k]=(A.isnear(actual[k],reference[k],k)
                     if actual[k] is not None else None)
            strict[k]=(J.strict_fit(actual[k],reference[k],k)
                       if actual[k] is not None else None)
        out[name]={
            "known_field_fits":fits,"known_field_strict_fits":strict,
            "known_fields":sum(v is not None for v in fits.values()),
            "all_six_known":all(v is not None for v in fits.values()),
            "all_known_tolerantly_match":all(v is True for v in fits.values()
                                             if v is not None),
            "all_known_strictly_match":all(v is True for v in strict.values()
                                           if v is not None)}
    return out


def run(day=date(2026,10,14),*,stocks=A.DEFAULT_CODES,
        client_factory=None,logger=print):
    if not X.START<=day<=X.END:
        raise ValueError("Date outside pinned 2026 pilot")
    if (not 1<=len(stocks)<=3 or len(set(stocks))!=len(stocks)
        or any(code not in A.DEFAULT_CODES for code in stocks)):
        raise ValueError("Only the original 3 pilot symbols are permitted")
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    work=folder/"auction_0925_split_pilot"
    old_open=work/f"{day:%Y%m%d}_summary.private.json"
    old_ticks=work/f"{day:%Y%m%d}_historical_ticks_feasibility.private.json"
    if (any(p.is_symlink() for p in (folder,work,old_open,old_ticks))
        or not old_open.is_file() or not old_ticks.is_file()):
        raise ValueError("Missing SHA-bound previous 09:25/09:31 pilot")
    prior=json.loads(old_open.read_bytes())
    prior_ticks=json.loads(old_ticks.read_bytes())
    if (prior.get("format")!=A.FORMAT or prior_ticks.get("format")!=T.FORMAT
        or prior.get("day")!=str(day) or prior_ticks.get("day")!=str(day)
        or prior.get("market_files_modified") is not False
        or prior_ticks.get("market_files_modified") is not False
        or prior.get("production_merge_authorized") is not False
        or prior_ticks.get("production_merge_authorized") is not False):
        raise ValueError("Incompatible previous private pilot reports")
    if client_factory is None:
        from eltdx import TdxClient
        client_factory=lambda:TdxClient(timeout=5,heartbeat_interval=None)
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    result={"format":FORMAT,"day":str(day),"stocks":{},
            "qmt_reference_used_for_validation_only":True,
            "source_only_0931_open_chronology_not_certified":True,
            "source_file_values_modified":False,
            "market_files_modified":False,"production_merge_authorized":False}
    counts=Counter()
    with client_factory() as client:
        if not hasattr(client.trades,"opening_match_history"):
            raise RuntimeError("Installed eltdx has no historical formal match API")
        for code in stocks:
            try:
                old=prior["stocks"][code]
                prior_tick=prior_ticks["stocks"][code]
                if (old.get("auction_0930_candidate_matches_qmt") is not True
                    or prior_tick.get("status") in (None,"HISTORICAL_TICK_PILOT_ERROR")):
                    raise ValueError("Previous formal/trade history not certified")
                receipt=X.verified_cache(folder,code,stage,remote_only=False)
                qrows,qsha=X.read_qmt_source(stage,code)
                path=folder/"source_parquet"/(code.replace(".","_")+".parquet")
                if (not receipt or not qrows or path.is_symlink()
                    or old.get("qmt_sha256")!=qsha
                    or old.get("source_parquet_sha256")!=L.hash_file(path)
                    or receipt["source_sha256"]!=old["source_parquet_sha256"]):
                    raise ValueError("240/241 market source SHA or receipt changed")
                old_subset=work/f"{day:%Y%m%d}_{code.replace('.','_')}_opening_trade_rows.private.json"
                if old_subset.is_symlink() or not old_subset.is_file():
                    raise ValueError("Missing private original real trades")
                raw=old_subset.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=prior_tick.get("opening_trade_subset_sha256"):
                    raise ValueError("Historical trade subset SHA changed")
                tickdoc=json.loads(raw)
                if (tickdoc.get("format")!=T.FORMAT or tickdoc.get("day")!=str(day)
                    or tickdoc.get("stock")!=code
                    or tickdoc.get("source_qmt_sha256")!=qsha
                    or tickdoc.get("source_tdx_1m_sha256")!=receipt["source_sha256"]
                    or tickdoc.get("market_files_modified") is not False
                    or tickdoc.get("production_merge_authorized") is not False):
                    raise ValueError("Original real trades no longer bound to source")
                ticks=tickdoc.get("limited_actual_trade_rows")
                if (not isinstance(ticks,list)
                    or len(ticks)!=prior_tick["selected_opening_trade_record_count"]):
                    raise ValueError("Historical trades absent or changed")
                tdx=A.day_rows(pq.read_table(path).to_pylist(),day)
                qmt=A.day_rows(qrows,day)
                previous=M.diagnostic(qmt,tdx,old)
                if (previous["model"]!="OPENING_MERGE_MATCH_AFTER_RESEARCH_ONLY_VOLUME_UNIT_ALIGNMENT"
                    or previous["volume_after_candidate_scale_all_240_fit"]!=240):
                    raise ValueError("Previously certified raw volume units changed")
                # Independent 09:25 numeric source; NOT pulled from QMT:
                event=client.trades.opening_match_history(
                    X.eltdx_code(code),day.isoformat(),
                    page_size=1800,max_pages=24)
                auction=formal_event(event,day)
                candidate=derive_source_only(tdx[0],auction,ticks)
                reference=reference_check(candidate,qmt)
                provenance=P.canonical({
                    "format":FORMAT,"day":str(day),"stock":code,
                    "formal_0925_source":auction,
                    "formal_0925_quantity_unit":"lot",
                    "original_limited_trades_sha256":
                        prior_tick["opening_trade_subset_sha256"],
                    "original_tdx_sha256":receipt["source_sha256"],
                    "original_qmt_oracle_sha256":qsha,
                    "candidate_source_only":candidate,
                    "reference_validation":reference,
                    "market_files_modified":False,
                    "production_merge_authorized":False})
                digest=hashlib.sha256(provenance).hexdigest()
                private=work/f"{day:%Y%m%d}_{code.replace('.','_')}_source_only_241_candidate.private.json"
                if private.is_symlink():
                    raise ValueError("Private derived candidate path redirected")
                P.safe_save(private,provenance)
                status=("ALL_SIX_SOURCE_CANDIDATE_FIELDS_VALIDATE_TO_QMT"
                        if (reference["0930_auction"]["all_six_known"]
                            and reference["0931_regular"]["all_six_known"]
                            and reference["0930_auction"]["all_known_tolerantly_match"]
                            and reference["0931_regular"]["all_known_tolerantly_match"])
                        else "SOURCE_CANDIDATE_NOT_FULLY_VALIDATED")
                outcome={
                    "status":status,"candidate":candidate,
                    "reference_validation":reference,
                    "private_source_only_candidate_sha256":digest,
                    "market_files_modified":False,
                    "production_merge_authorized":False}
            except Exception as exc:
                outcome={"status":"SOURCE_INDEPENDENT_PILOT_ERROR",
                         "reason":type(exc).__name__+": "+str(exc)[:190],
                         "market_files_modified":False,
                         "production_merge_authorized":False}
            result["stocks"][code]=outcome
            counts[outcome["status"]]+=1
            logger("ELTDX_241_SOURCE_ONLY_STOCK="+json.dumps({
                "stock":code,"status":outcome["status"],
                "known_field_count":outcome.get("candidate",{}).get("identified_field_count"),
                "opening_price_from_source_not_qmt":outcome.get("candidate",{}).get(
                    "source_only_candidate_does_not_use_qmt_answers"),
                "independent_0931_open_certified":outcome.get("candidate",{}).get(
                    "independent_0931_open_certified"),
                "high_reason":outcome.get("candidate",{}).get("high_reason"),
                "low_reason":outcome.get("candidate",{}).get("low_reason"),
                "validation":outcome.get("reference_validation"),
                "error":outcome.get("reason"),"production_merge_authorized":False},
                sort_keys=True,ensure_ascii=False))
    private_summary=work/f"{day:%Y%m%d}_source_only_241_candidates.private.json"
    if private_summary.is_symlink():
        raise ValueError("Private summary output path redirected")
    P.safe_save(private_summary,P.canonical(result))
    logger("ELTDX_241_SOURCE_ONLY_SUMMARY="+json.dumps({
        "format":FORMAT,"day":str(day),"stock_days":len(stocks),
        "statuses":dict(counts),
        "0931_open_trade_chronology_certified":False,
        "source_market_files_modified":False,
        "production_merge_authorized":False},sort_keys=True))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--day",type=date.fromisoformat,default=date(2026,10,14))
    args=p.parse_args()
    run(args.day)
