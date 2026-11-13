#!/usr/bin/env python3
"""Zero-network, SHA-replayed holdout postmortem for 240->241 opening candles.

The existing six real stock-day holdout cases are the sole input. For each:
 - crosscheck the preserved private result SHA with its saved summary,
 - independently re-verify the original eltdx 240 and QMT 241 SHA snapshots,
 - reconstruct 09:30/09:31 candidates from saved eltdx formal 09:25
   execution, native 240 bar and filtered historical trades ONLY,
 - use QMT 241 only after candidate construction to explain validation.
No historical 0x0fc6 download, no market database writes or production merge.
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
import qmt_eltdx_opening_tick_alignment as J
import qmt_eltdx_241_cross_day_holdout as H

FORMAT="eltdx_241_cross_day_source_sha_replay_postmortem_private_v1"
FIELDS=A.VALUES


def amount_gap(candidate,reference):
    a=float(candidate); b=float(reference)
    if not math.isfinite(a) or not math.isfinite(b) or a<0 or b<0:
        raise ValueError("Invalid original source amount")
    delta=a-b
    return {
        "strict_match":J.strict_fit(a,b,"amount"),
        "original_tolerance_match":A.isnear(a,b,"amount"),
        "signed_error_basis_points":round(delta/max(b,1.)*10000,6),
        "absolute_error_bucket":(
            "<=1CNY" if abs(delta)<=1 else
            "<=10CNY" if abs(delta)<=10 else
            "<=100CNY" if abs(delta)<=100 else
            "<=1000CNY" if abs(delta)<=1000 else ">1000CNY"),
    }


def missing_extreme(case,q,t):
    candidate=case["source_only_candidate"]["regular_0931_source_only_candidate"]
    auction=case["source_only_candidate"]["auction_0930_source_only"]
    ticks=[v for v in case["source_only_candidate"].get("historical_source_rows",[])
           if v["minute"]==570]
    # The caller injects verified cached actual trade rows into its temporary
    # copy; this is never used to populate an unknown candidate field.
    report={}
    for field in ("high","low"):
        if candidate[field] is not None:
            continue
        price=float(auction["open"])
        q_val=float(q[1][field])
        native=float(t[0][field])
        observed=[float(v["price"]) for v in ticks]
        if not observed:
            raise ValueError("No regular 09:30 trade records to bound unknown extreme")
        candidate_extreme=(max(observed) if field=="high" else min(observed))
        trade_total_lots=sum(float(v["lots"]) for v in ticks)
        regular_lots=float(candidate["volume"])
        # Historical 0x0fc6 "trade" prices can reflect aggregated records;
        # exact quantity coverage alone does NOT prove price-extreme coverage.
        bound_price=price
        if field=="high":
            observed_bounded_by_merged=(candidate_extreme<=bound_price+0.0001)
            observed_gap_bps=(bound_price-candidate_extreme)/bound_price*10000
        else:
            observed_bounded_by_merged=(candidate_extreme>=bound_price-0.0001)
            observed_gap_bps=(candidate_extreme-bound_price)/bound_price*10000
        report[field]={
            "source_only_observed_extreme_candidate":candidate_extreme,
            "source_only_observed_extreme_between_regular_and_auction":
                observed_bounded_by_merged,
            "gap_from_auction_extreme_basis_points":round(observed_gap_bps,6),
            "trade_volume_matches_reconstructed_regular_volume_strict":
                J.strict_fit(trade_total_lots,regular_lots,"volume"),
            "historical_trade_price_extreme_complete_independently_proven":False,
            "observed_price_extreme_is_only_an_unverified_candidate":True,
            "source_only_production_field_stays_null":True,
            "native_merged_extreme_equals_auction":
                J.strict_fit(native,price,field),
            "qmt_oracle_extreme_equals_auction":
                J.strict_fit(q_val,price,field),
            "original_0930_trade_rows_count":len(ticks),
            "trade_rows_reach_auction_price":
                any(J.strict_fit(v,price,field) for v in observed),
            "trade_rows_reach_qmt_oracle_extreme":
                any(J.strict_fit(v,q_val,field) for v in observed),
            "observed_trades_extreme_strict_match_to_qmt":
                J.strict_fit(candidate_extreme,q_val,field),
            "observed_extreme_matches_oracle_not_production_certification":True,
            "independent_field_value_known":False,
            "can_promote_unknown_to_production":False,
        }
    return report


def diagnose(existing,q,t,raw_rows):
    # A testable pure function: inputs include previously SHA-verified source
    # data only. Never feed the QMT truth into the candidate builder.
    auction=existing["formal_0925_source"]
    candidate=H.R.derive_source_only(t[0],auction,raw_rows)
    ref=H.R.reference_check(candidate,q)
    copied=json.loads(json.dumps(existing["source_only_candidate_and_separate_validation"]))
    if (copied.get("status")!=H.per_day(q,t,auction,raw_rows)["status"]
        or copied["source_only_candidate"]["regular_0931_source_only_candidate"]!=
           candidate["regular_0931_source_only_candidate"]
        or copied["qmt_validation_only"]!=ref):
        raise ValueError("Original holdout candidate/result no longer reproducible")
    groups={}
    for name,bar,target in (
        ("auction_0930",candidate["auction_0930_source_only"],q[0]),
        ("regular_0931",candidate["regular_0931_source_only_candidate"],q[1])):
        strict_bad=[k for k in FIELDS if bar[k] is not None
                    and not J.strict_fit(bar[k],target[k],k)]
        tolerant_bad=[k for k in FIELDS if bar[k] is not None
                      and not A.isnear(bar[k],target[k],k)]
        groups[name]={
            "strict_failed_fields":strict_bad,
            "original_tolerance_failed_fields":tolerant_bad,
            "unknown_fields":[k for k in FIELDS if bar[k] is None],
            "amount_error":amount_gap(bar["amount"],target["amount"]),
            "known_field_count":sum(bar[k] is not None for k in FIELDS),
        }
    first=[x for x in raw_rows if x["minute"]==570]
    second=[x for x in raw_rows if x["minute"]==571]
    if not first or not second:
        raise ValueError("No adjacent opening trades in saved holdout")
    minute_amounts={
        "trade_0930_vs_qmt_0931":amount_gap(
            sum(float(v["price"])*float(v["lots"])*100 for v in first),
            q[1]["amount"]),
        "trade_0931_vs_qmt_0932":amount_gap(
            sum(float(v["price"])*float(v["lots"])*100 for v in second),
            q[2]["amount"])}
    tmp={"source_only_candidate":dict(candidate)}
    tmp["source_only_candidate"]["historical_source_rows"]=raw_rows
    ambiguous=missing_extreme(tmp,q,t)
    amount_sum=float(candidate["auction_0930_source_only"]["amount"])+float(
        candidate["regular_0931_source_only_candidate"]["amount"])
    ref_sum=float(q[0]["amount"])+float(q[1]["amount"])
    return {
        "status":"SHA_REPLAYED_SOURCE_ONLY_HOLDOUT_POSTMORTEM",
        "original_holdout_status":copied["status"],
        "auction_0930":groups["auction_0930"],
        "regular_0931":groups["regular_0931"],
        "unidentifiable_0931_extrema":ambiguous,
        "candidate_extrema_not_promoted_even_if_oracle_matches":True,
        "first_regular_trade_as_returned_strict_open_match":
            J.strict_fit(first[0]["price"],q[1]["open"],"open"),
        "last_regular_trade_as_returned_strict_open_match":
            J.strict_fit(first[-1]["price"],q[1]["open"],"open"),
        "history_records_chronologically_certified":False,
        "estimated_history_trade_amount_errors":minute_amounts,
        "merged_first_minute_amount_error":amount_gap(amount_sum,ref_sum),
        "formal_0925_amount_derived_not_exchange_certified":True,
        "candles_computed_from_eltdx_only_QMT_validation_only":True,
        "production_merge_authorized":False,
        "market_files_modified":False,
    }


def run(logger=print):
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    root=folder/"auction_0925_split_pilot"/"cross_day_holdout"
    summary=root/"20261015_20261016_holdout_summary.private.json"
    if (any(p.is_symlink() for p in (folder,root,summary))
        or not summary.is_file()):
        raise ValueError("Original two-day private holdout not found")
    previous=json.loads(summary.read_bytes())
    head=previous.get("summary",{})
    if (head.get("format")!=H.FORMAT
        or head.get("days")!=[str(d) for d in H.ALLOWED_DAYS]
        or head.get("cases")!=6
        or head.get("market_files_modified") is not False
        or head.get("production_merge_authorized") is not False
        or not isinstance(previous.get("stock_days"),dict)):
        raise ValueError("Unexpected holdout report format/provenance")
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    source={}
    for code in H.CODES:
        receipt=X.verified_cache(folder,code,stage,remote_only=False)
        qrows,qsha=X.read_qmt_source(stage,code)
        path=folder/"source_parquet"/(code.replace(".","_")+".parquet")
        if (not receipt or not qrows or path.is_symlink()
            or L.hash_file(path)!=receipt["source_sha256"]):
            raise ValueError("Old source receipt SHA mismatch: "+code)
        table=pq.read_table(path)
        if table.schema!=P.PRIVATE_SCHEMA:
            raise ValueError("Original eltdx Arrow schema changed")
        source[code]=(qrows,table.to_pylist(),qsha,receipt["source_sha256"])
    output={"format":FORMAT,"stock_days":{},
            "market_files_modified":False,"production_merge_authorized":False}
    statuses=Counter(); unknown=Counter(); strict_bad=Counter()
    for day in H.ALLOWED_DAYS:
        for code in H.CODES:
            key=f"{day}/{code}"
            receipt=previous["stock_days"].get(key)
            file=root/f"{day:%Y%m%d}_{code.replace('.','_')}_holdout.private.json"
            if (not isinstance(receipt,dict) or file.is_symlink()
                or not file.is_file()):
                raise ValueError("Historical holdout case missing "+key)
            data=file.read_bytes()
            if hashlib.sha256(data).hexdigest()!=receipt.get("private_SHA256"):
                raise ValueError("Historical holdout result SHA mismatch "+key)
            record=json.loads(data)
            qrows,trows,qsha,tsha=source[code]
            if (record.get("format")!=H.FORMAT or record.get("day")!=str(day)
                or record.get("stock")!=code
                or record.get("original_qmt_SHA256_validation_only")!=qsha
                or record.get("original_eltdx_240_SHA256")!=tsha
                or record.get("market_files_modified") is not False
                or record.get("production_merge_authorized") is not False):
                raise ValueError("Historical case/source SHA binding invalid "+key)
            q=A.day_rows(qrows,day); t=A.day_rows(trows,day)
            rows=record["historical_opening_0930_0931_trades"]
            result=diagnose(record,q,t,rows)
            output["stock_days"][key]=result
            statuses[receipt["status"]]+=1
            unknown.update(result["regular_0931"]["unknown_fields"])
            strict_bad.update(result["regular_0931"]["strict_failed_fields"])
            logger("ELTDX_241_HOLDOUT_POSTMORTEM_CASE="+json.dumps({
                "day":str(day),"stock":code,
                "old_status":result["original_holdout_status"],
                "auction_strict_failed_fields":
                    result["auction_0930"]["strict_failed_fields"],
                "regular_strict_failed_fields":
                    result["regular_0931"]["strict_failed_fields"],
                "regular_unknown_fields":
                    result["regular_0931"]["unknown_fields"],
                "unidentifiable_extrema":
                    result["unidentifiable_0931_extrema"],
                "history_trade_amount_errors":
                    result["estimated_history_trade_amount_errors"],
                "auction_amount_error":
                    result["auction_0930"]["amount_error"],
                "regular_amount_error":
                    result["regular_0931"]["amount_error"],
                "merged_amount_error":
                    result["merged_first_minute_amount_error"],
                "first_print_open_matches":
                    result["first_regular_trade_as_returned_strict_open_match"],
                "last_print_open_matches":
                    result["last_regular_trade_as_returned_strict_open_match"],
                "production_merge_authorized":False},
                ensure_ascii=False,sort_keys=True))
    summary_out={
        "format":FORMAT,"stock_days_verified":len(output["stock_days"]),
        "original_statuses":dict(statuses),
        "unknown_0931_field_counts":dict(unknown),
        "strict_mismatch_0931_field_counts":dict(strict_bad),
        "no_network":True,"market_files_modified":False,
        "production_merge_authorized":False}
    dest=root/"20261015_20261016_source_sha_postmortem.private.json"
    if dest.is_symlink():
        raise ValueError("Private postmortem path redirected")
    P.safe_save(dest,P.canonical({"summary":summary_out,**output}))
    logger("ELTDX_241_HOLDOUT_POSTMORTEM_SUMMARY="+json.dumps(
        summary_out,sort_keys=True,ensure_ascii=False))
    return {"summary":summary_out,**output}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.parse_args()
    run()
