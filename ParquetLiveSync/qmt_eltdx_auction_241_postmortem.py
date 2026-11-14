#!/usr/bin/env python3
"""Strictly offline source-SHA postmortem for the historical auction 240/241 pilot.

No network, no QMT connection, no recomputation of missing auction data.
The earlier live 09:25 result is bound to the same original QMT and TDX source
SHA, and per-field model comparisons are recomputed from those source files.
All outputs go only to Git-ignored private work. No Parquet/H5 market writes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_eltdx_1m_probe as X
import qmt_eltdx_auction_241_probe as A

FORMAT="qmt_eltdx_0925_0931_sha_bound_offline_model_diagnostics_v2"
FIELDS=A.VALUES
VOLUME_FACTORS=(.01,1.,100.)


def volume_factor_evidence(qmt_bars,tdx_bars):
    """Research-only fit of QMT volume = raw eltdx volume * factor.

    The eltdx private source deliberately preserves volume_wire_value, not
    volume_lots. No market or private source volume is rewritten.
    """
    if len(qmt_bars)!=len(tdx_bars) or not qmt_bars:
        raise ValueError("Volume audit requires equal nonempty minute grids")
    positive=[]
    both_zero=0
    one_zero=0
    for left,right in zip(qmt_bars,tdx_bars):
        q,t=float(left["volume"]),float(right["volume"])
        if not all(math.isfinite(v) and v>=0 for v in (q,t)):
            raise ValueError("Nonfinite/negative original volume")
        if q==0 and t==0:
            both_zero+=1
        elif q==0 or t==0:
            one_zero+=1
        else:
            positive.append((q,t))
    counts={str(factor):sum(A.isnear(q,t*factor,"volume") for q,t in positive)
            for factor in VOLUME_FACTORS}
    ranking=sorted(((counts[str(factor)],factor)
                    for factor in VOLUME_FACTORS),reverse=True)
    best_count,best_factor=ranking[0]
    second_count=ranking[1][0]
    proven=(len(positive)>=40 and one_zero==0
            and best_count>=len(positive)*.98
            and second_count<len(positive)*.80)
    return {
        "positive_minute_pairs":len(positive),
        "both_zero_minute_pairs":both_zero,
        "one_sided_zero_minute_pairs":one_zero,
        "candidate_fit_positive_counts":counts,
        "tdx_raw_volume_to_qmt_candidate_factor":best_factor if proven else None,
        "candidate_identified_for_research":proven,
        "raw_tdx_wire_volume_preserved":True,
        "volume_scale_applied_to_source":False,
        "production_merge_authorized":False,
    }


def compared(first, second):
    """Do not expose licensed raw OHLCVA values in the public console."""
    result={key:A.isnear(first[key],second[key],key) for key in FIELDS}
    relative={}
    for key in FIELDS:
        a,b=float(first[key]),float(second[key])
        if not math.isfinite(a) or not math.isfinite(b):
            raise ValueError("Nonfinite private source bar")
        relative[key]=round(abs(a-b)/max(abs(a),abs(b),1e-10),8)
    return result,relative


def diagnostic(qmt,tdx,pilot):
    if pilot.get("status") not in (
        "FIRST_MINUTE_SPLIT_REQUIRES_REVIEW",
        "FORMAL_0925_MATCHES_QMT_0930_AND_TDX_0931_MERGE"):
        return {"status":"NO_MATCHABLE_FORMAL_AUCTION_EVIDENCE",
                "production_merge_authorized":False}
    if (len(qmt)!=241 or len(tdx)!=240
        or A.label(qmt[0])!=(9,30) or A.label(qmt[1])!=(9,31)
        or A.label(tdx[0])!=(9,31)
        or [x["ts"] for x in qmt[1:]]!=[x["ts"] for x in tdx]):
        raise ValueError("Timestamp grid not exactly QMT 241 vs TDX 240")
    merged=A.combined(qmt[0],qmt[1])
    match_merge,rel_merge=compared(merged,tdx[0])
    match_direct,rel_direct=compared(qmt[1],tdx[0])
    if pilot.get("combined_first_1m_field_fits")!=match_merge:
        raise ValueError("Earlier live auction evidence differs from verified SHA source")
    # This independent count determines if disagreement is local to the
    # opening bar or affects the regular 09:32..15:00 session.
    later=Counter()
    for a,b in zip(qmt[2:],tdx[1:]):
        fits,_=compared(a,b)
        for key in FIELDS:
            if fits[key]:
                later[key]+=1
    volume_proof=volume_factor_evidence([merged,*qmt[2:]],tdx)
    factor=volume_proof["tdx_raw_volume_to_qmt_candidate_factor"]
    scaled_volume_matches=(sum(A.isnear(q["volume"],t["volume"]*factor,
                             "volume") for q,t in zip([merged,*qmt[2:]],tdx))
                           if factor is not None else None)
    if all(match_merge.values()):
        model="OPENING_0930_PLUS_0931_MERGE_ALL_SIX"
    elif all(match_direct.values()):
        model="DIRECT_0931_MATCH_ALL_SIX"
    elif (factor is not None and factor!=1.
          and scaled_volume_matches==240
          and all(match_merge[k] for k in (*A.OHLC,"amount"))
          and all(later[k]==239 for k in (*A.OHLC,"amount"))
          and pilot.get("auction_0930_candidate_matches_qmt") is True):
        model="OPENING_MERGE_MATCH_AFTER_RESEARCH_ONLY_VOLUME_UNIT_ALIGNMENT"
    elif all(match_merge[k] for k in (*A.OHLC,"amount")):
        model="MERGE_OHLC_AMOUNT_MATCH_VOLUME_DIFFERENCE"
    elif all(match_merge[k] for k in (*A.OHLC,"volume")):
        model="MERGE_OHLC_VOLUME_MATCH_AMOUNT_DIFFERENCE"
    elif all(match_merge[k] for k in ("volume","amount")):
        model="MERGE_VOLUME_AMOUNT_ONLY_PRICE_DISAGREES"
    else:
        model="NEITHER_FIRST_MINUTE_MODEL_FULLY_MATCHES"
    return {
        "status":"SHA_VERIFIED_SOURCE_MODEL_RECHECK",
        "model":model,
        "auction_to_qmt_0930_previously_verified":
            pilot.get("auction_0930_candidate_matches_qmt") is True,
        "merged_0930_0931_field_fits":match_merge,
        "direct_0931_field_fits":match_direct,
        "merged_failed_fields":[k for k in FIELDS if not match_merge[k]],
        "direct_failed_fields":[k for k in FIELDS if not match_direct[k]],
        "merged_relative_errors":rel_merge,
        "direct_relative_errors":rel_direct,
        "remaining_239_field_fit_counts":dict(later),
        "remaining_239_expected":239,
        "volume_unit_evidence":volume_proof,
        "volume_after_candidate_scale_all_240_fit":scaled_volume_matches,
        "original_volume_field_scaling_not_written_to_parquet":True,
        "auction_is_formal_not_virtual":True,
        "regular_0931_OHLC_recovery_proven":False,
        "market_files_modified":False,
        "production_merge_authorized":False,
    }


def run(*,day=date(2026,10,14),work=None,logger=print):
    if not X.START<=day<=X.END:
        raise ValueError("Date outside original SHA-pinned audit window")
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    work=Path(work) if work else folder/"auction_0925_split_pilot"
    report=work/f"{day:%Y%m%d}_summary.private.json"
    if folder.is_symlink() or work.is_symlink() or report.is_symlink() or not report.is_file():
        raise ValueError("Missing or redirected existing live auction pilot")
    doc=json.loads(report.read_bytes())
    if (doc.get("format")!=A.FORMAT or doc.get("day")!=day.isoformat()
        or doc.get("market_files_modified") is not False
        or doc.get("production_merge_authorized") is not False
        or not isinstance(doc.get("stocks"),dict)):
        raise ValueError("Unsupported or unauthenticated original private auction pilot")
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    output={"format":FORMAT,"day":day.isoformat(),"stocks":{},
            "market_files_modified":False,"production_merge_authorized":False}
    stats=Counter()
    field_fail=Counter()
    full_rest=0
    scaled_full=0
    candidate_factors=Counter()
    for code,pilot in sorted(doc["stocks"].items()):
        if code not in A.DEFAULT_CODES or not isinstance(pilot,dict):
            raise ValueError("Unexpected stock in fixed SHA-bound pilot")
        cached=X.verified_cache(folder,code,stage,remote_only=False)
        if cached is None:
            raise ValueError("Source receipt missing: "+code)
        qmt,sha=X.read_qmt_source(stage,code)
        if qmt is None or pilot.get("qmt_sha256")!=sha:
            raise ValueError("Pilot QMT SHA no longer matches: "+code)
        src=folder/"source_parquet"/(code.replace(".","_")+".parquet")
        if src.is_symlink() or L.hash_file(src)!=pilot.get("source_parquet_sha256"):
            raise ValueError("Pilot TDX SHA no longer matches: "+code)
        table=pq.read_table(src)
        if table.schema!=P.PRIVATE_SCHEMA:
            raise ValueError("Unexpected private minute Arrow schema")
        q=A.day_rows(qmt,day)
        t=A.day_rows(table.to_pylist(),day)
        result=diagnostic(q,t,pilot)
        output["stocks"][code]=result
        stats[result.get("model",result["status"])]+=1
        field_fail.update(result.get("merged_failed_fields",[]))
        if result.get("remaining_239_field_fit_counts")=={
            name:239 for name in FIELDS}:
            full_rest+=1
        if result.get("volume_after_candidate_scale_all_240_fit")==240:
            scaled_full+=1
        proof=result.get("volume_unit_evidence",{})
        factor=proof.get("tdx_raw_volume_to_qmt_candidate_factor")
        if factor is not None:
            candidate_factors[str(factor)]+=1
        logger("ELTDX_AUCTION_241_FIELD_DIAGNOSTIC="+json.dumps({
            "stock":code,"model":result.get("model"),
            "status":result["status"],
            "merged_failed_fields":result.get("merged_failed_fields"),
            "direct_failed_fields":result.get("direct_failed_fields"),
            "remaining_239_field_fit_counts":
                result.get("remaining_239_field_fit_counts"),
            "volume_unit_evidence":result.get("volume_unit_evidence"),
            "volume_after_candidate_scale_all_240_fit":
                result.get("volume_after_candidate_scale_all_240_fit"),
            "merged_relative_errors":
                {k:v for k,v in result.get("merged_relative_errors",{}).items()
                 if k in result.get("merged_failed_fields",[])},
            "production_merge_authorized":False,
        },sort_keys=True,ensure_ascii=False))
    out=work/f"{day:%Y%m%d}_field_postmortem.private.json"
    if out.is_symlink():
        raise ValueError("Redirected private output")
    P.safe_save(out,P.canonical(output))
    summary={
        "format":FORMAT,"day":day.isoformat(),
        "stocks_verified":len(output["stocks"]),
        "model_counts":dict(stats),
        "merged_mismatch_field_counts":dict(field_fail),
        "stocks_with_other_239_minutes_all_six_matching":full_rest,
        "stock_days_full_240_volume_fit_after_candidate_scale":scaled_full,
        "volume_candidate_factors_raw_tdx_to_qmt":dict(candidate_factors),
        "source_files_modified":False,"market_files_modified":False,
        "production_merge_authorized":False}
    logger("ELTDX_AUCTION_241_FIELD_SUMMARY="+json.dumps(
        summary,sort_keys=True,ensure_ascii=False))
    return output


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day",type=date.fromisoformat,default=date(2026,10,14))
    args=parser.parse_args(argv)
    run(day=args.day)


if __name__=="__main__":
    main()
