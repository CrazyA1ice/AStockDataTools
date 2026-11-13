#!/usr/bin/env python3
"""Offline, SHA-bound targeted diagnostics of QMT/eltdx minute disagreement.

Only the existing 554 PRIVATE review-day receipts are read. No network, no
QMT downloads, and no canonical or purchased market Parquet/H5 writes.
The output is triage evidence, NEVER an automatic numeric calibration or
permission to merge cross-vendor minute sources.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import json
import math
from pathlib import Path
from statistics import median

import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_1m_recover as R
import qmt_tdx_1m_depth as D
import qmt_eltdx_1m_probe as X
import qmt_eltdx_market_audit as M
import qmt_eltdx_forensics as F

FORMAT = "qmt_eltdx_1m_existing_review_554_targeted_amount_triage_v1"
SOURCE = M.ROOT
OHLC = ("open", "high", "low", "close")
AMOUNT_REL_TOL = .035
AMOUNT_ABS_TOL = 30.
OHLC_REL_TOL = .0015
OHLC_ABS_TOL = .015
# Side of daily trading session where auction/time attribution may differ.
EDGE_TIMES = {(9,m) for m in range(30,36)} | {
    (13,m) for m in range(0,6)} | {(14,m) for m in range(55,60)} | {(15,0)}
SCALE_CANDIDATES = (1e-4, 1e-2, 1., 1e2, 1e4)


def by_date(rows):
    grouped=defaultdict(list)
    for row in rows:
        day=datetime.fromtimestamp(row["ts"]/1000,P.CN).date()
        grouped[day].append(row)
    return grouped


def positive_ratio_evidence(pairs):
    """Diagnose potential amount scale; NEVER infer an approved conversion."""
    raw=[(float(a["amount"]),float(b["amount"])) for a,b in pairs
         if float(a["amount"])>1e-8 and float(b["amount"])>1e-8]
    if len(raw)<30:
        return {"status":"INSUFFICIENT_POSITIVE_MINUTES","pairs":len(raw),
                "merge_calibration_authorized":False}
    ratios=sorted(a/b for a,b in raw)
    center=median(ratios)
    deviation=median(abs(x-center)/max(abs(center),1e-9) for x in ratios)
    scores={str(k):round(sum(math.isclose(a,b*k,
            rel_tol=AMOUNT_REL_TOL,abs_tol=AMOUNT_ABS_TOL)
             for a,b in raw)/len(raw),6) for k in SCALE_CANDIDATES}
    candidates=sorted(((float(v),float(k)) for k,v in scores.items()),reverse=True)
    suggested=(candidates[0][1] if len(candidates)>1 and
               candidates[0][0]>=.85 and candidates[0][0]-candidates[1][0]>=.15
               else None)
    return {"status":"STABLE_FACTOR_CANDIDATE_REQUIRES_INDEPENDENT_PAID_VALIDATION"
            if suggested is not None else "NO_STABLE_SCALE_CANDIDATE",
            "pairs":len(raw),"median_qmt_to_eltdx_amount_ratio":round(center,8),
            "median_relative_deviation":round(deviation,8),
            "candidate_factor_tdx_to_qmt":suggested,
            "candidate_fit_fraction":dict(scores),
            "merge_calibration_authorized":False}


def diagnostic(qmt,tdx,score):
    """Use the day-specific validated time offset, never forge auction bars."""
    q={int(row["ts"]):row for row in qmt}
    t={int(row["ts"]):row for row in tdx}
    if len(q)!=len(qmt) or len(t)!=len(tdx):
        raise ValueError("Repeated minute timestamp in forensic source")
    offset=score.get("tdx_to_qmt_time_offset_ms")
    if (offset is None or offset not in D.OFFSETS_MS or
            score.get("offset_ambiguous") is True):
        return {"triage":"TIME_GRID_UNPROVEN","aligned_minutes":0,
                "source_qmt_minutes":len(q),"source_tdx_minutes":len(t),
                "merge_calibration_authorized":False}
    pairs=[(q[ts+offset],row) for ts,row in sorted(t.items())
           if ts+offset in q]
    if len(pairs)!=score.get("compared",len(pairs)):
        raise ValueError("Source SHA and stored minute overlap do not reproduce")
    total_amt=0
    edge_amt=0
    core_amt=0
    price_bad=0
    examples=0
    max_rel=0.
    for a,b in pairs:
        x,y=float(a["amount"]),float(b["amount"])
        if not math.isclose(x,y,rel_tol=AMOUNT_REL_TOL,abs_tol=AMOUNT_ABS_TOL):
            total_amt+=1
            dt=datetime.fromtimestamp(a["ts"]/1000,P.CN)
            if (dt.hour,dt.minute) in EDGE_TIMES:
                edge_amt+=1
            else:
                core_amt+=1
            max_rel=max(max_rel,abs(x-y)/max(abs(x),1))
        if not all(math.isclose(float(a[f]),float(b[f]),
                   rel_tol=OHLC_REL_TOL,abs_tol=OHLC_ABS_TOL)
                   for f in OHLC):
            price_bad+=1
    evidence=positive_ratio_evidence(pairs)
    if price_bad:
        status="PRICE_AND_OR_AMOUNT_DISAGREEMENT"
    elif total_amt==0:
        status="RAW_MINUTE_AMOUNTS_REPRODUCE"
    elif core_amt==0:
        status="SESSION_BOUNDARY_AMOUNT_ONLY"
    elif evidence.get("candidate_factor_tdx_to_qmt") is not None:
        status="PERSISTENT_AMOUNT_RATIO_CANDIDATE"
    else:
        status="INTRADAY_AMOUNT_DIFF_UNEXPLAINED"
    return {"triage":status,"aligned_minutes":len(pairs),
            "source_qmt_minutes":len(q),"source_tdx_minutes":len(t),
            "time_offset_ms":offset,
            "raw_amount_bad_minutes":total_amt,
            "session_edge_amount_bad_minutes":edge_amt,
            "session_core_amount_bad_minutes":core_amt,
            "ohlc_bad_minutes":price_bad,
            "max_amount_relative_gap":round(max_rel,6),
            "amount_factor_research_only":evidence,
            "merge_calibration_authorized":False}


def inspect(root, *, workspace=SOURCE, logger=print):
    folder=Path(workspace)
    queue=folder/"latest_review_queue.private.json"
    for path in (folder,queue):
        if path.is_symlink():
            raise ValueError("Untrusted targeted review location")
    if not queue.is_file():
        raise ValueError("Run offline qmt_eltdx_forensics.py first to create review queue")
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    official,stocks,plan,calib=R.load_bound_context(Path(root),stage,X.START,X.END)
    psha=P.sha_bytes(P.canonical(plan))
    qdoc=json.loads(queue.read_bytes())
    if (qdoc.get("format")!=F.FORMAT or qdoc.get("plan_sha256")!=psha
            or qdoc.get("production_merge_authorized") is not False
            or qdoc.get("market_files_modified") is not False
            or not isinstance(qdoc.get("cases"),list)):
        raise ValueError("Source review queue is not tied to current plan")
    report_file=folder/"latest_forensics_report.json"
    report=json.loads(report_file.read_bytes())
    total=sum(report.get("review_exclusive_day_classes",{}).values())
    cases=qdoc["cases"]
    if not total or len(cases)!=total:
        raise ValueError("Review queue and forensic summary counts do not agree")
    expected_codes=set(stocks)
    unique=set()
    for item in cases:
        if not isinstance(item,dict):
            raise ValueError("Invalid case structure")
        code=R.P.normalize_code(item["stock"])
        dt=date.fromisoformat(item["day"])
        if (code not in expected_codes or dt not in official or
                code not in official[dt] or (code,dt) in unique or
                item.get("review_class") not in
                report["review_exclusive_day_classes"] or
                item.get("production_merge_authorized") is not False):
            raise ValueError("Unknown, duplicate or unsafe review case")
        unique.add((code,dt))
    originals=R.validate_original(stage,official,stocks,progress=lambda _:None)
    fp=P.sha_bytes(P.canonical({
       "original_plan_sha256":psha,
       "calibration_sha256":plan["calibration_sha256"],"format":R.FORMAT}))
    recovery={}
    for code,dt in unique:
        if code not in originals and code not in recovery:
            days=sorted(d.isoformat() for d,universe in official.items() if code in universe)
            rec=R.validate_recovery_receipt(stage/"day_recovery",code,fp,days)
            if rec is not None:
                recovery[code]=rec
    by_stock=defaultdict(list)
    for item in cases:
        by_stock[item["stock"]].append(item)
    result=[]
    triage_count=Counter()
    amt_bad=0
    core_bad=0
    prices_bad=0
    for code,items in sorted(by_stock.items()):
        doc,qr,sha=D.source_original(stage,code,originals,recovery,official)
        if qr is None:
            raise ValueError("Review day lacks independently SHA-verifiable QMT source")
        dates=sorted(d for d,universe in official.items() if code in universe)
        eltdx_doc=M.read_existing(folder,code,psha,sha,dates)
        if eltdx_doc is None:
            raise ValueError("Review day lacks independently SHA-verifiable eltdx source")
        src=folder/"source_parquet"/(code.replace(".","_")+".parquet")
        table=pq.read_table(src,columns=["ts","symbol",*D.FIELDS])
        if table.schema!=P.PRIVATE_SCHEMA:
            raise ValueError("Private eltdx Parquet schema unexpectedly changed")
        tdays=by_date(table.to_pylist())
        qdays=by_date(qr)
        for item in items:
            dt=date.fromisoformat(item["day"])
            original=eltdx_doc["day_comparison"][item["day"]]
            score=original.get("result",original)
            if (score.get("status")!="MINUTE_SOURCE_DIFFERENCE_REVIEW" or
                    F.categorize_review(score)!=item["review_class"]):
                raise ValueError("Original SHA-bound minute case no longer matches queue")
            evidence=diagnostic(qdays.get(dt,[]),tdays.get(dt,[]),score)
            # Counts are a regression check of the primary report, not an
            # opportunity to recompute or relax existing acceptance.
            old=original.get("minute_diagnostics",{})
            if (evidence.get("aligned_minutes",0)>0 and
                    old.get("field_mismatch_counts") is not None and
                    evidence["raw_amount_bad_minutes"]!=old["field_mismatch_counts"]["amount_raw"]):
                raise ValueError("Minute amount disagreement changed since SHA-pinned report")
            triage_count[evidence["triage"]]+=1
            amt_bad+=evidence.get("raw_amount_bad_minutes",0)
            core_bad+=evidence.get("session_core_amount_bad_minutes",0)
            prices_bad+=evidence.get("ohlc_bad_minutes",0)
            result.append({"stock":code,"day":item["day"],
                           "original_review_class":item["review_class"],
                           "diagnostic":evidence,
                           "market_files_modified":False,
                           "production_merge_authorized":False})
    summary={"format":FORMAT,"source_review_case_sha256":L.hash_file(queue),
             "sources_individually_sha_verified":len(by_stock),
             "targeted_review_days":len(result),
             "diagnostic_classes":dict(triage_count),
             "raw_amount_bad_minutes":amt_bad,
             "intraday_core_amount_bad_minutes":core_bad,
             "ohlc_bad_minutes":prices_bad,
             "source_vendor_independence":"QMT vs TDX eltdx, not third-party",
             "source_values_rewritten":False,
             "market_files_modified":False,
             "production_merge_authorized":False}
    output=folder/"latest_targeted_triage.private.json"
    if output.is_symlink():
        raise ValueError("Unsafe private targeted output link")
    P.safe_save(output,P.canonical({"summary":summary,"cases":result}))
    logger("ELTDX_TARGETED_TRIAGE_SUMMARY="+json.dumps(
        summary,sort_keys=True,ensure_ascii=False))
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("D:/stock"))
    args=parser.parse_args(argv)
    inspect(args.root)


if __name__=="__main__":
    main()
