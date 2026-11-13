#!/usr/bin/env python3
"""Private all-market 2026-10-14..11-12 QMT/eltdx genuine 1m OHLCVA audit.

Source-only, NONCOMMERCIAL eltdx research. All market/monthly Parquet/H5 files
remain read-only. Requires the cryptographically pinned purchased DAY calendar,
paid 1m calibration and original QMT intake. Recovers previous source receipts
without fetching QMT again. One eltdx stock at a time, bounded 800-bar pages,
bounded retries and request rate, per-day minute mismatch evidence, resumable.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
import json
import math
from pathlib import Path
import time

import local_layout as L
import qmt_1m_pipeline as P
import qmt_1m_recover as R
import qmt_tdx_1m_depth as D
import qmt_eltdx_1m_probe as X

FORMAT = "qmt_eltdx_market_1m_22day_sha_bound_audit_v1"
ROOT = X.WORK / f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
OHLC = ("open","high","low","close")


def one_day_mismatches(qmt, tdx, result, sample_limit=8):
    """Minute-level evidence for every field, preserving QMT vs TDX units."""
    offset = result.get("tdx_to_qmt_time_offset_ms")
    if offset is None:
        return {"compared_minutes":0,"unmatched_qmt_minutes":len(qmt),
                "unmatched_eltdx_minutes":len(tdx),"field_mismatch_counts":None,
                "examples":[]}
    q = {int(x["ts"]):x for x in qmt}
    t = {int(x["ts"]):x for x in tdx}
    overlap = sorted((ts, ts+offset) for ts in t if ts+offset in q)
    missing = {x:0 for x in (*OHLC,"volume_scaled","amount_raw")}
    examples=[]
    factor=result.get("volume_factor",{}).get("factor_tdx_to_qmt")
    for tx, qx in overlap:
        a,b=q[qx],t[tx]
        diff={}
        for field in OHLC:
            if not math.isclose(float(a[field]),float(b[field]),rel_tol=.0015,abs_tol=.015):
                missing[field]+=1
                diff[field]=[round(float(a[field]),6),round(float(b[field]),6)]
        if factor is not None:
            if not math.isclose(float(a["volume"]),float(b["volume"])*float(factor),
                                rel_tol=.045,abs_tol=.5):
                missing["volume_scaled"]+=1
                diff["volume_scaled"]=[round(float(a["volume"]),4),
                                       round(float(b["volume"])*float(factor),4)]
        if not math.isclose(float(a["amount"]),float(b["amount"]),rel_tol=.035,abs_tol=30.):
            missing["amount_raw"]+=1
            diff["amount_raw"]=[round(float(a["amount"]),4),
                                round(float(b["amount"]),4)]
        if diff and len(examples)<sample_limit:
            examples.append({"qmt_minute_ts_ms":qx,"tdx_minute_ts_ms":tx,
                             "QMT_vs_eltdx":diff})
    return {"compared_minutes":len(overlap),
            "unmatched_qmt_minutes":len(q)-len(overlap),
            "unmatched_eltdx_minutes":len(t)-len(overlap),
            "tdx_to_qmt_offset_ms":offset,
            "field_mismatch_counts":missing,"examples":examples,
            "volume_comparison_available":factor is not None}


def day_proofs(qmt,tdx,dates):
    def by_day(rows):
        groups={}
        for x in rows:
            d=datetime.fromtimestamp(x["ts"]/1000,P.CN).date()
            groups.setdefault(d,[]).append(x)
        return groups
    q=by_day(qmt)
    t=by_day(tdx)
    return {d.isoformat():{
        "result":D.score_day(q.get(d,[]),t.get(d,[])),
        "minute_diagnostics":None
    } for d in dates},q,t


def make_comparison(qmt,tdx,dates):
    evidence,q,t=day_proofs(qmt,tdx,dates)
    for d in dates:
        result=evidence[d.isoformat()]["result"]
        evidence[d.isoformat()]["minute_diagnostics"]=one_day_mismatches(
            q.get(d,[]),t.get(d,[]),result)
    return evidence


def load_qmt_sources(stage,code,originals,recovery):
    if code not in originals and code not in recovery:
        return [],None,"QMT_MISSING_BOTH_FULL_AND_RECOVERY_RECEIPTS"
    doc,rows,digest=D.source_original(stage,code,originals,recovery,None)
    if rows is None:
        return [],None,"NO_ACCEPTED_QMT_DAYS"
    if digest!=doc["sha256"]:
        raise ValueError("QMT private source SHA differs from QMT receipt")
    return rows,digest,"QMT_FULL" if code in originals else "QMT_DAY_RECOVERY"


def read_existing(folder,code,plan_hash,qmt_hash,expect):
    folder=Path(folder)
    receipt=folder/"receipts"/(code.replace(".","_")+".json")
    path=folder/"source_parquet"/(code.replace(".","_")+".parquet")
    if not receipt.exists():
        if receipt.is_symlink() or path.is_symlink():
            raise ValueError("Untrusted private source symlink")
        return None
    if receipt.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError("eltdx private receipt/file missing or redirected")
    doc=json.loads(receipt.read_bytes())
    if (doc.get("format")!=X.FORMAT or doc.get("stock")!=code
            or doc.get("source_sha256")!=L.hash_file(path)
            or doc.get("rows",0)<0
            or doc.get("market_files_modified") is not False
            or doc.get("production_merge_authorized") is not False):
        raise ValueError("eltdx cached receipt/SHA/guard invalid")
    from pyarrow import parquet as pq
    pf=pq.ParquetFile(path)
    try:
        if pf.schema_arrow!=P.PRIVATE_SCHEMA or pf.metadata.num_rows!=doc["rows"]:
            raise ValueError("eltdx cached Arrow schema/footer invalid")
    finally:
        pf.close()
    meta=doc.get("meta",{})
    if meta.get("qmt_sha256")!=qmt_hash:
        raise ValueError("QMT private SHA changed since eltdx source receipt")
    if meta.get("plan_sha256") not in (plan_hash,None):
        raise ValueError("Original certified source plan changed; refuse stale cache")
    if meta.get("plan_sha256") is None and code not in X.ANCHORS:
        raise ValueError("Unpinned non-anchor source receipt")
    for d in expect:
        if d.isoformat() not in doc.get("day_comparison",{}):
            raise ValueError("Missing day comparison in cached source")
    return doc


def result_from_receipt(doc, dates, qmt_mode):
    day=doc["day_comparison"]
    counts=Counter()
    covered=0
    qmt_available=0
    minute_checked=0
    for d in dates:
        x=day[d.isoformat()]
        obj=x.get("result",x) if isinstance(x,dict) else {}
        status=obj.get("status","MISSING_EVIDENCE")
        counts[status]+=1
        if obj.get("tdx_count")==240:
            covered+=1
        if obj.get("qmt_count",0)>0:
            qmt_available+=1
        minute_checked+=obj.get("compared",0)
    return {"tdx_complete_days":covered,"qmt_available_days":qmt_available,
            "strict_matched_days":counts["MATCHED_1MIN_OHLCVA"],
            "minute_bars_compared":minute_checked,
            "statuses":dict(counts),"qmt_source_type":qmt_mode}


def audit(root,*,limit=0,workspace=ROOT,max_hosts=6,max_pages=16,
          pause=.18,client_factory=None,log=print):
    if not 0<=limit<=10000 or not 1<=max_hosts<=len(X.HOSTS) or not 8<=max_pages<=35:
        raise ValueError("Unsafe/unbounded request parameters")
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    dates,stocks,plan,calib=R.load_bound_context(root,stage,X.START,X.END)
    log("ELTDX_MARKET_STEP_1_SOURCE_DAY_SHA_PAID_1M_CALIBRATION_AND_QMT_RECHECK")
    originals=R.validate_original(stage,dates,stocks,progress=log)
    recovery={}
    fingerprint=P.sha_bytes(P.canonical({
       "original_plan_sha256":P.sha_bytes(P.canonical(plan)),
       "calibration_sha256":plan["calibration_sha256"],"format":R.FORMAT}))
    for code in stocks:
        if code in originals:
            continue
        trading_days=[d.isoformat() for d in dates if code in dates[d]]
        cached=R.validate_recovery_receipt(stage/"day_recovery",code,
                                            fingerprint,trading_days)
        if cached:
            recovery[code]=cached
    if len(originals)<2500:
        raise ValueError("Too few SHA-verified original QMT stocks")
    log(f"ELTDX_MARKET_STEP_2_QMT_FULL={len(originals)} QMT_RECOVERED_STOCKS={len(recovery)} TOTAL={len(stocks)}")
    folder=Path(workspace)
    folder.mkdir(parents=True,exist_ok=True)
    if folder.is_symlink():
        raise ValueError("Untrusted symlink market research workspace")
    plan_hash=P.sha_bytes(P.canonical(plan))
    order=list(dict.fromkeys([x for x in X.ANCHORS if x in stocks]+stocks))
    counts=Counter()
    date_stats={d.isoformat():Counter() for d in dates}
    errors={}
    shown=0
    processed=0
    new=0
    cached=0
    consecutive=0
    total_day_keys=0
    matched_day_keys=0
    total_minutes_compared=0
    for code in order:
        if limit and processed>=limit:
            break
        processed+=1
        trading_days=sorted(d for d in dates if code in dates[d])
        try:
            qmt,sha,qmode=load_qmt_sources(stage,code,originals,recovery)
            doc=read_existing(folder,code,plan_hash,sha,trading_days)
            if doc is None:
                attempts=[]
                for host in X.HOSTS[:max_hosts]:
                    try:
                        client=X.connect_host(host,client_factory)
                        with client:
                            rows,meta=X.fetch_history(client,code,
                                                      X.START,X.END,max_pages)
                        meta.update({"endpoint":host,
                                     "plan_sha256":plan_hash,
                                     "qmt_sha256":sha,
                                     "qmt_source_type":qmode,
                                     "official_day_count":len(trading_days)})
                        # Verify an independent complete day; never invent
                        # 240 missing rows to force a match.
                        comparison=make_comparison(qmt,rows,trading_days)
                        doc=X.save_private(folder,code,rows,meta,comparison)
                        new+=1
                        if pause:
                            time.sleep(pause)
                        break
                    except Exception as exc:
                        attempts.append(f"{host}: {type(exc).__name__}: {str(exc)[:160]}")
                else:
                    raise ConnectionError("ELTDX_ENDPOINTS_FAILED "+" | ".join(attempts[-3:]))
            else:
                cached+=1
            summary=result_from_receipt(doc,trading_days,qmode)
            counts["stocks_with_eltdx_private"]=counts["stocks_with_eltdx_private"]+1
            counts["full_22day_eltdx_stock"]=counts["full_22day_eltdx_stock"]+int(
                summary["tdx_complete_days"]==len(trading_days))
            counts["fully_qmt_matched_stock"]=counts["fully_qmt_matched_stock"]+int(
                summary["strict_matched_days"]==len(trading_days))
            counts["partial_or_no_qmt_stock"]=counts["partial_or_no_qmt_stock"]+int(
                summary["qmt_available_days"]!=len(trading_days))
            total_day_keys+=len(trading_days)
            matched_day_keys+=summary["strict_matched_days"]
            total_minutes_compared+=summary["minute_bars_compared"]
            for d in trading_days:
                v=doc["day_comparison"][d.isoformat()]
                status=(v.get("result",v) if isinstance(v,dict) else {}).get("status","UNKNOWN")
                date_stats[d.isoformat()][status]+=1
            consecutive=0
            if processed<=3 or processed%25==0:
                log(f"ELTDX_MARKET_PROGRESS={processed}/{len(stocks)} "
                    f"source_stocks={counts['stocks_with_eltdx_private']} cached={cached} "
                    f"matched_stock_days={matched_day_keys}/{total_day_keys} "
                    f"failed={len(errors)} last={code}")
        except Exception as exc:
            errors[code]=f"{type(exc).__name__}: {str(exc)[:320]}"
            counts["failed_stock_attempts"]+=1
            consecutive+=1
            log(f"ELTDX_MARKET_QUARANTINE {code} {errors[code]}")
            if consecutive>=12:
                log("ELTDX_MARKET_CIRCUIT_BREAKER_12_CONSECUTIVE_FAILURES")
                break
    result={"format":FORMAT,"window":[str(X.START),str(X.END)],
            "expected_stocks":len(stocks),"processed_stocks":processed,
            "qmt_original_full_stocks":len(originals),
            "qmt_partially_recovered_stocks":len(recovery),
            "eltdx_new_source_stocks":new,"eltdx_sha_reused_stocks":cached,
            "source_stocks_staged":counts["stocks_with_eltdx_private"],
            "eltdx_all_expected_days_stocks":counts["full_22day_eltdx_stock"],
            "fully_qmt_matched_stocks":counts["fully_qmt_matched_stock"],
            "stocks_missing_any_qmt_source_day":counts["partial_or_no_qmt_stock"],
            "stock_day_comparisons":total_day_keys,
            "matched_stock_days":matched_day_keys,
            "raw_one_minute_pairs_compared":total_minutes_compared,
            "failed_stock_attempts":len(errors),"failure_examples":list(errors.items())[:12],
            "per_day_status":{k:dict(v) for k,v in date_stats.items()},
            "stopped_early":processed<len(stocks),
            "plan_sha256":plan_hash,"private_workspace":str(folder),
            "source_independence":"QMT vs TDX server via eltdx Rust (noncommercial)",
            "market_files_modified":False,"production_merge_authorized":False}
    P.safe_save(folder/"latest_market_report.json",P.canonical(result))
    concise={k:v for k,v in result.items() if k not in (
        "failure_examples","per_day_status","plan_sha256","private_workspace")}
    log("ELTDX_MARKET_SUMMARY="+json.dumps(concise,ensure_ascii=False,sort_keys=True))
    log("ELTDX_MARKET_DAY_STATUS="+json.dumps(result["per_day_status"],
                                              ensure_ascii=False,sort_keys=True))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("D:/stock"))
    parser.add_argument("--limit-stocks",type=int,default=0)
    parser.add_argument("--max-hosts",type=int,default=6)
    parser.add_argument("--max-pages",type=int,default=16)
    args=parser.parse_args(argv)
    audit(args.root,limit=args.limit_stocks,max_hosts=args.max_hosts,
          max_pages=args.max_pages)


if __name__=="__main__":
    main()
