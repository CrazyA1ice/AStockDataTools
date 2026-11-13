#!/usr/bin/env python3
"""No-network time-label crosscheck of the 2026-10-14 opening trade subset.

Consumes only the already SHA-pinned QMT 241, eltdx 240, the prior formal
09:25 receipt and the saved 09:30/09:31 real historical trades. Diagnose
minute START-label versus END-label, and missing OHLC extrema, without
inventing independent 09:31 candles or altering production Parquet/H5.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import argparse
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

FORMAT="qmt_eltdx_opening_trade_start_end_alignment_private_v1"
PAIRS=(("trade_0930_to_qmt_0930",570,"qmt_0930"),
       ("trade_0930_to_qmt_0931",570,"qmt_0931"),
       ("trade_0930_to_tdx_0931",570,"tdx_0931"),
       ("trade_0931_to_qmt_0931",571,"qmt_0931"),
       ("trade_0931_to_qmt_0932",571,"qmt_0932"),
       ("trade_0931_to_tdx_0932",571,"tdx_0932"))
FIELDS=A.VALUES


def strict_fit(x,y,field):
    """Stricter diagnostic than original A.isnear; not exchange certification."""
    a=float(x);b=float(y)
    return math.isclose(a,b,rel_tol=1e-6,
                        abs_tol=.0001 if field in A.OHLC else
                                .001 if field=="volume" else 1.)


def bucket_compare(rows,target):
    trials=[]
    for direction in ("as_returned","reversed"):
        candle=T.entry_bucket(rows,target,direction)
        tolerant={k:A.isnear(candle[k],target[k],k) for k in FIELDS}
        strict={k:strict_fit(candle[k],target[k],k) for k in FIELDS}
        trials.append({
            "order":direction,"tolerant_fields":tolerant,"strict_fields":strict,
            "tolerant_field_count":sum(tolerant.values()),
            "strict_field_count":sum(strict.values()),
            "tolerant_volume_and_amount_fit":
                tolerant["volume"] and tolerant["amount"],
            "strict_volume_and_amount_fit":
                strict["volume"] and strict["amount"],
            "high_observed_inside_target":float(candle["high"])<=float(target["high"])+.0001,
            "low_observed_inside_target":float(candle["low"])>=float(target["low"])-.0001,
        })
    # Reversing record order does not change high/low/volume/amount, only open/close.
    return min(trials,key=lambda t:(-t["strict_field_count"],
                                    -t["tolerant_field_count"],t["order"]))


def assess(rows,qmt,tdx):
    if (len(qmt)!=241 or len(tdx)!=240 or
        A.label(qmt[0])!=(9,30) or A.label(qmt[1])!=(9,31)
        or A.label(qmt[2])!=(9,32) or
        A.label(tdx[0])!=(9,31) or A.label(tdx[1])!=(9,32)):
        raise ValueError("Not the SHA-pinned 241-to-240 timestamp grid")
    buckets={570:[],571:[]}
    indices=[]
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError("Unexpected opening trade record")
        minute=row.get("minute")
        if minute not in buckets:
            raise ValueError("Trade record out of original opening window")
        price=float(row["price"]);lots=float(row["lots"])
        if (not math.isfinite(price) or not math.isfinite(lots)
                or price<=0 or lots<=0):
            raise ValueError("Nonpositive/nonfinite original historical trade")
        idx=row.get("absolute_index")
        if idx is not None:
            if not isinstance(idx,int) or idx<0:
                raise ValueError("Invalid historical source index")
            indices.append(idx)
        buckets[minute].append(row)
    if not buckets[570] or not buckets[571]:
        raise ValueError("Both historical minute buckets must exist")
    targets={"qmt_0930":qmt[0],"qmt_0931":qmt[1],
             "qmt_0932":qmt[2],
             "tdx_0931":tdx[0],"tdx_0932":tdx[1]}
    trials={}
    for title,minute,target_name in PAIRS:
        trial=bucket_compare(buckets[minute],targets[target_name])
        trial["source_record_count"]=len(buckets[minute])
        trials[title]=trial
    forward=(trials["trade_0930_to_qmt_0931"]["strict_volume_and_amount_fit"]
             and trials["trade_0931_to_qmt_0932"]["strict_volume_and_amount_fit"])
    same=(trials["trade_0930_to_qmt_0930"]["strict_volume_and_amount_fit"]
          and trials["trade_0931_to_qmt_0931"]["strict_volume_and_amount_fit"])
    if forward and not same:
        model="HISTORICAL_TRADES_0930_0931_MATCH_NEXT_END_LABELED_MINUTES"
    elif same and not forward:
        model="HISTORICAL_TRADES_MATCH_SAME_LABELED_MINUTES"
    elif forward and same:
        model="BOTH_MINUTE_LABEL_MODELS_POSSIBLE"
    else:
        model="NEITHER_MINUTE_LABEL_MODEL_STRICTLY_FITS"
    idx_pattern=("no_absolute_index" if not indices else
                 "monotone_increasing" if all(a<b for a,b in zip(indices,indices[1:])) else
                 "monotone_decreasing" if all(a>b for a,b in zip(indices,indices[1:])) else
                 "nonmonotone_or_repeated")
    return {
        "status":model,"minute_label_forward_strict_volume_amount_fit":forward,
        "minute_label_same_strict_volume_amount_fit":same,
        "historical_trade_index_sequence":idx_pattern,
        "observed_trade_count_by_minute":
            {"09:30":len(buckets[570]),"09:31":len(buckets[571])},
        "comparisons":trials,
        "historical_trade_minute_only_no_seconds":True,
        "price_extrema_may_be_missing_from_sampled_or_aggregated_trades":True,
        "chronological_trade_order_not_certified":True,
        "source_values_rewritten":False,
        "production_merge_authorized":False,
        "market_files_modified":False,
    }


def run(day=date(2026,10,14),*,logger=print):
    if not X.START<=day<=X.END:
        raise ValueError("Date outside original SHA-verified source window")
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    work=folder/"auction_0925_split_pilot"
    pilot_file=work/f"{day:%Y%m%d}_summary.private.json"
    trade_file=work/f"{day:%Y%m%d}_historical_ticks_feasibility.private.json"
    if (any(x.is_symlink() for x in (folder,work,pilot_file,trade_file))
        or not pilot_file.is_file() or not trade_file.is_file()):
        raise ValueError("Original formal auction/trade pilot missing or redirected")
    audit=json.loads(pilot_file.read_bytes())
    trade=json.loads(trade_file.read_bytes())
    if (audit.get("format")!=A.FORMAT or trade.get("format")!=T.FORMAT
        or audit.get("day")!=str(day) or trade.get("day")!=str(day)
        or audit.get("market_files_modified") is not False
        or trade.get("market_files_modified") is not False
        or audit.get("production_merge_authorized") is not False
        or trade.get("production_merge_authorized") is not False):
        raise ValueError("Earlier live pilot provenance not certified")
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    results={}
    counts=Counter()
    for code in A.DEFAULT_CODES:
        if code not in audit.get("stocks",{}) or code not in trade.get("stocks",{}):
            raise ValueError("Historical trade pilot has no cached stock "+code)
        old=audit["stocks"][code]
        old_trade=trade["stocks"][code]
        if (old.get("auction_0930_candidate_matches_qmt") is not True
            or old_trade.get("status") in
              (None,"HISTORICAL_TICK_PILOT_ERROR")):
            raise ValueError("Live formal/trade evidence missing for "+code)
        receipt=X.verified_cache(folder,code,stage,remote_only=False)
        qrows,qsha=X.read_qmt_source(stage,code)
        source=folder/"source_parquet"/(code.replace(".","_")+".parquet")
        if (not receipt or qrows is None or source.is_symlink()
            or old.get("qmt_sha256")!=qsha
            or old.get("source_parquet_sha256")!=L.hash_file(source)
            or receipt.get("source_sha256")!=old.get("source_parquet_sha256")):
            raise ValueError("Original 240/241 snapshot SHA changed for "+code)
        q=A.day_rows(qrows,day)
        t=A.day_rows(pq.read_table(source).to_pylist(),day)
        unit=M.diagnostic(q,t,old)
        if unit.get("model")!="OPENING_MERGE_MATCH_AFTER_RESEARCH_ONLY_VOLUME_UNIT_ALIGNMENT":
            raise ValueError("Original volume calibration no longer validates")
        raw_file=work/f"{day:%Y%m%d}_{code.replace('.','_')}_opening_trade_rows.private.json"
        if raw_file.is_symlink() or not raw_file.is_file():
            raise ValueError("Missing/redirected private historical ticks")
        data=raw_file.read_bytes()
        if hashlib.sha256(data).hexdigest()!=old_trade.get("opening_trade_subset_sha256"):
            raise ValueError("Prior limited historical trade subset SHA changed")
        original=json.loads(data)
        if (original.get("format")!=T.FORMAT or original.get("day")!=str(day)
            or original.get("stock")!=code
            or original.get("source_qmt_sha256")!=qsha
            or original.get("source_tdx_1m_sha256")!=receipt["source_sha256"]
            or original.get("production_merge_authorized") is not False
            or original.get("market_files_modified") is not False):
            raise ValueError("Private historical trades no longer bound to QMT/TDX")
        rows=original.get("limited_actual_trade_rows")
        if (not isinstance(rows,list)
            or len(rows)!=old_trade.get("selected_opening_trade_record_count")):
            raise ValueError("Historical trade subset length changed")
        result=assess(rows,q,t)
        results[code]=result
        counts[result["status"]]+=1
        logger("ELTDX_OPENING_LABEL_STOCK="+json.dumps({
            "stock":code,"status":result["status"],
            "per_minute_trade_counts":result["observed_trade_count_by_minute"],
            "historical_index_order":result["historical_trade_index_sequence"],
            "comparisons":{name:{
                "tolerant_fields":v["tolerant_fields"],
                "strict_fields":v["strict_fields"],
                "high_observed_inside_target":v["high_observed_inside_target"],
                "low_observed_inside_target":v["low_observed_inside_target"]
                } for name,v in result["comparisons"].items()},
            "production_merge_authorized":False},
            ensure_ascii=False,sort_keys=True))
    summary={"format":FORMAT,"day":str(day),"model_counts":dict(counts),
             "stock_days":len(results),"historical_trade_minute_only":True,
             "market_files_modified":False,"production_merge_authorized":False}
    out=work/f"{day:%Y%m%d}_opening_label_alignment.private.json"
    if out.is_symlink():
        raise ValueError("Redirected private output")
    P.safe_save(out,P.canonical({"summary":summary,"stocks":results}))
    logger("ELTDX_OPENING_LABEL_SUMMARY="+json.dumps(
        summary,ensure_ascii=False,sort_keys=True))
    return {"summary":summary,"stocks":results}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day",type=date.fromisoformat,
                        default=date(2026,10,14))
    args=parser.parse_args()
    run(args.day)
