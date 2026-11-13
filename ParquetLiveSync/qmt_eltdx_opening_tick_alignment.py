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

FORMAT="qmt_eltdx_opening_trade_start_end_alignment_private_v2"
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


def infer_0931_bounds(qmt,tdx,trade_rows):
    """Analyze *identifiability*, not create a 241-bar dataset.

    QMT[09:30] is used ONLY as a temporary oracle for auction price/volume/
    amount because the earlier live formal 09:25 pilot certified these fields
    but did not retain their raw values. This is emphatically not a source-
    independent recovered minute K. Source-only use requires fetching and
    retaining the historical formal auction record independently.
    """
    if len(qmt)!=241 or len(tdx)!=240:
        raise ValueError("Full anchored 241/240 source required")
    opening=qmt[0]
    target=qmt[1]
    merged=tdx[0]
    auction_price=float(opening["open"])
    if not all(A.isnear(opening[k],auction_price,k) for k in A.OHLC):
        raise ValueError("Auction opening oracle is not a single-price bar")
    if not A.isnear(merged["open"],auction_price,"open"):
        raise ValueError("Merged native first minute not consistent with auction")
    # Only deviations strictly beyond the auction price make merged extrema
    # uniquely assignable to regular 09:31 trading.
    high_from_merged=(float(merged["high"])>auction_price+0.0001)
    low_from_merged=(float(merged["low"])<auction_price-0.0001)
    inferred_volume=float(merged["volume"])*.01-float(opening["volume"])
    inferred_amount=float(merged["amount"])-float(opening["amount"])
    trades=[r for r in trade_rows if r["minute"]==570]
    if not trades or inferred_volume<0 or inferred_amount<0:
        raise ValueError("No regular ticks or negative opening-subtracted trade")
    first_as_returned=float(trades[0]["price"])
    first_reversed=float(trades[-1]["price"])
    observed_high=max(float(r["price"]) for r in trades)
    observed_low=min(float(r["price"]) for r in trades)
    high=float(merged["high"]) if high_from_merged else None
    low=float(merged["low"]) if low_from_merged else None
    return {
        "status":"BOUNDED_INFERABILITY_ONLY_NOT_INDEPENDENT_RECONSTRUCTION",
        "merged_native_open_equals_auction_strict":
            strict_fit(merged["open"],auction_price,"open"),
        "auction_ohlc_are_one_price_strict":
            all(strict_fit(opening[k],auction_price,k) for k in A.OHLC),
        "known_field_match_to_qmt":{
            "close":strict_fit(merged["close"],target["close"],"close"),
            "volume":strict_fit(inferred_volume,target["volume"],"volume"),
            "amount":strict_fit(inferred_amount,target["amount"],"amount"),
            "high":(strict_fit(high,target["high"],"high") if
                    high is not None else None),
            "low":(strict_fit(low,target["low"],"low") if
                   low is not None else None)},
        "high_uniquely_determined_by_merged_extreme":high_from_merged,
        "low_uniquely_determined_by_merged_extreme":low_from_merged,
        "high_if_auction_is_merged_high":"unknown" if not high_from_merged
                else "inferred_from_native_240_high",
        "low_if_auction_is_merged_low":"unknown" if not low_from_merged
                else "inferred_from_native_240_low",
        "trade_0930_first_as_returned_open_match":
            strict_fit(first_as_returned,target["open"],"open"),
        "trade_0930_first_reversed_open_match":
            strict_fit(first_reversed,target["open"],"open"),
        "trade_0930_observed_high_match":
            strict_fit(observed_high,target["high"],"high"),
        "trade_0930_observed_low_match":
            strict_fit(observed_low,target["low"],"low"),
        "minute_volume_unit_scale_used":0.01,
        "formal_auction_price_volume_amount_raw_not_stored_in_old_pilot":True,
        "auction_values_from_qmt_oracle_for_feasibility_only":True,
        "historical_trade_sequence_chronology_unverified":True,
        "actual_0931_open_source_certified":False,
        "all_six_0931_fields_source_independently_certified":False,
        "production_merge_authorized":False,
    }


def bucket_compare(rows,target):
    trials=[]
    for direction in ("as_returned","reversed"):
        candle=T.entry_bucket(rows,target,direction)
        tolerant={k:A.isnear(candle[k],target[k],k) for k in FIELDS}
        strict={k:strict_fit(candle[k],target[k],k) for k in FIELDS}
        amount_difference=float(candle["amount"])-float(target["amount"])
        amount_relative=abs(amount_difference)/max(abs(float(target["amount"])),1.)
        trials.append({
            "order":direction,"tolerant_fields":tolerant,"strict_fields":strict,
            "tolerant_field_count":sum(tolerant.values()),
            "strict_field_count":sum(strict.values()),
            "tolerant_volume_and_amount_fit":
                tolerant["volume"] and tolerant["amount"],
            "strict_volume_and_amount_fit":
                strict["volume"] and strict["amount"],
            "volume_strict_amount_tolerant_fit":
                strict["volume"] and tolerant["amount"],
            "amount_relative_error_basis_points":round(amount_relative*10000,4),
            "amount_absolute_error_bucket":(
                "<=1CNY" if abs(amount_difference)<=1 else
                "<=10CNY" if abs(amount_difference)<=10 else
                "<=100CNY" if abs(amount_difference)<=100 else
                "<=1000CNY" if abs(amount_difference)<=1000 else ">1000CNY"),
            "amount_is_sum_of_trade_price_times_lots_times_100":True,
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
    forward_volume_cash=(trials["trade_0930_to_qmt_0931"]["volume_strict_amount_tolerant_fit"]
                         and trials["trade_0931_to_qmt_0932"]["volume_strict_amount_tolerant_fit"])
    same_volume_cash=(trials["trade_0930_to_qmt_0930"]["volume_strict_amount_tolerant_fit"]
                      and trials["trade_0931_to_qmt_0931"]["volume_strict_amount_tolerant_fit"])
    if forward and not same:
        model="HISTORICAL_TRADES_0930_0931_MATCH_NEXT_END_LABELED_MINUTES"
    elif same and not forward:
        model="HISTORICAL_TRADES_MATCH_SAME_LABELED_MINUTES"
    elif forward and same:
        model="BOTH_MINUTE_LABEL_MODELS_POSSIBLE"
    elif forward_volume_cash and not same_volume_cash:
        model="NEXT_MINUTE_LABEL_SUPPORTED_BY_EXACT_VOLUME_AND_TOLERANT_AMOUNT"
    elif same_volume_cash and not forward_volume_cash:
        model="SAME_MINUTE_LABEL_SUPPORTED_BY_EXACT_VOLUME_AND_TOLERANT_AMOUNT"
    elif same_volume_cash and forward_volume_cash:
        model="BOTH_MINUTE_MODELS_ONLY_TOLERANTLY_SUPPORTED"
    else:
        model="NEITHER_MINUTE_LABEL_MODEL_VOLUME_AND_AMOUNT_SUPPORTED"
    idx_pattern=("no_absolute_index" if not indices else
                 "monotone_increasing" if all(a<b for a,b in zip(indices,indices[1:])) else
                 "monotone_decreasing" if all(a>b for a,b in zip(indices,indices[1:])) else
                 "nonmonotone_or_repeated")
    return {
        "status":model,"minute_label_forward_strict_volume_amount_fit":forward,
        "minute_label_forward_volume_strict_amount_tolerant_fit":forward_volume_cash,
        "minute_label_same_volume_strict_amount_tolerant_fit":same_volume_cash,
        "minute_label_evidence_not_clock_semantics_certification":True,
        "inferred_0931_bounds":infer_0931_bounds(qmt,tdx,rows),
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
            "minute_label_forward_volume_strict_amount_tolerant_fit":
                result["minute_label_forward_volume_strict_amount_tolerant_fit"],
            "inferred_0931_bounds":result["inferred_0931_bounds"],
            "comparisons":{name:{
                "tolerant_fields":v["tolerant_fields"],
                "strict_fields":v["strict_fields"],
                "high_observed_inside_target":v["high_observed_inside_target"],
                "low_observed_inside_target":v["low_observed_inside_target"],
                "volume_strict_amount_tolerant_fit":v["volume_strict_amount_tolerant_fit"],
                "amount_relative_error_basis_points":v["amount_relative_error_basis_points"],
                "amount_absolute_error_bucket":v["amount_absolute_error_bucket"]
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
