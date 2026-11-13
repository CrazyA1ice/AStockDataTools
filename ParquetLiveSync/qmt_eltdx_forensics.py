#!/usr/bin/env python3
"""Read-only QMT/eltdx 1m forensic rollup for source disagreement and gaps.

Consumes SHA-pinned private receipts from the completed 5223-stock run.
Does not download bars, repair/copy official Klines, or mutate purchased or
canonical Parquet/H5. Only writes a PRIVATE diagnostic JSON report.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_1m_recover as R
import qmt_eltdx_1m_probe as X
import qmt_eltdx_market_audit as M

FORMAT="qmt_eltdx_1m_private_reconciliation_forensics_v1"
WORK=M.ROOT
OHLC=("open","high","low","close")
FIELDS=("open","high","low","close","volume_scaled","amount_raw")


def review_reason(result):
    """Nonexclusive mechanical causes of the existing day-level gate."""
    reasons=[]
    if result.get("offset_ambiguous"):
        reasons.append("TIME_OFFSET_AMBIGUOUS")
    if result.get("ohlc_all_fields_fit",1.)<.95:
        reasons.append("OHLC_FIT_BELOW_GATE")
    if result.get("amount_minute_raw_fit",1.)<.85:
        reasons.append("RAW_MINUTE_AMOUNT_BELOW_GATE")
    for field,name in (("volume_factor","VOLUME_FACTOR_BELOW_GATE"),
                       ("amount_factor","AMOUNT_FACTOR_BELOW_GATE")):
        factor=result.get(field,{})
        if factor.get("matching_fraction",0.)<.85:
            reasons.append(name)
        if factor.get("status")=="NO_UNIQUE_STABLE_VENDOR_FACTOR":
            reasons.append(field.upper()+"_FACTOR_AMBIGUOUS")
    if result.get("tdx_count",0)!=240:
        reasons.append("ELTDX_NOT_240_MINUTE_BARS")
    if result.get("qmt_count",0)!=241:
        reasons.append("QMT_NOT_241_MINUTE_BARS")
    return reasons or ["OTHER_REVIEW_REQUIRED"]


def independently_compare_tdx_day_to_official(rows, official):
    """OHLC only, no manufactured 09:30 QMT bar or volume/amount conversion."""
    if len(rows)!=240:
        return {"status":"TDX_DAY_NOT_240_BARS","bars":len(rows)}
    prices={
        "open":float(rows[0]["open"]),
        "high":max(float(x["high"]) for x in rows),
        "low":min(float(x["low"]) for x in rows),
        "close":float(rows[-1]["close"])}
    fits={k:math.isclose(prices[k],float(official[k]),rel_tol=.006,abs_tol=.04)
          for k in OHLC}
    return {"status":"TDX_240_VS_OFFICIAL_DAY_OHLC_DIAGNOSTIC_ONLY",
            "bars":240,"fits":fits,"all_four_fit":all(fits.values()),
            "auction_0930_not_reconstructed":True}


def inspect(root, *, workspace=WORK, logger=print):
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    official,stocks,plan,calibration=R.load_bound_context(Path(root),stage,X.START,X.END)
    market_report=Path(workspace)/"latest_market_report.json"
    if market_report.is_symlink() or not market_report.is_file():
        raise ValueError("Missing complete SHA-bound independent minute market report")
    prior=json.loads(market_report.read_bytes())
    plan_hash=P.sha_bytes(P.canonical(plan))
    if (prior.get("format")!=M.FORMAT or prior.get("plan_sha256")!=plan_hash
            or prior.get("expected_stocks")!=len(stocks)
            or prior.get("market_files_modified") is not False
            or prior.get("production_merge_authorized") is not False):
        raise ValueError("Source plan/report mismatch; refuse forensic inference")
    status=Counter()
    reason=Counter()
    field_minutes=Counter()
    date_status=defaultdict(Counter)
    failed={}
    review_examples=[]
    gap_candidates=[]
    qmt_source_missing=0
    verified_stocks=0
    verified_days=0
    legacy_no_detail=0
    for i,code in enumerate(stocks):
        receipt=Path(workspace)/"receipts"/(code.replace(".","_")+".json")
        source=Path(workspace)/"source_parquet"/(code.replace(".","_")+".parquet")
        days=sorted(d for d in official if code in official[d])
        if receipt.is_symlink() or source.is_symlink():
            raise ValueError("Private minute evidence symlink: "+code)
        if not receipt.exists():
            failed[code]={"first_certified_trading_day":str(days[0]) if days else None,
                          "expected_days":len(days)}
            continue
        if not source.is_file():
            raise ValueError("Missing SHA-pinned source: "+code)
        doc=json.loads(receipt.read_bytes())
        if (doc.get("stock")!=code or doc.get("format")!=X.FORMAT
                or doc.get("source_sha256")!=L.hash_file(source)
                or doc.get("market_files_modified") is not False
                or doc.get("production_merge_authorized") is not False):
            raise ValueError("Changed private minute source/receipt: "+code)
        metadata=doc.get("meta",{})
        if metadata.get("plan_sha256") not in (plan_hash,None):
            raise ValueError("Outdated source plan: "+code)
        if metadata.get("plan_sha256") is None and code not in X.ANCHORS:
            raise ValueError("Unpinned non-anchor source: "+code)
        for d in days:
            if d.isoformat() not in doc.get("day_comparison",{}):
                raise ValueError("Missing day-level source evidence: "+code+" "+str(d))
        verified_stocks+=1
        gap_days=[]
        day_diagnostics=doc["day_comparison"]
        for d in days:
            ds=d.isoformat()
            item=day_diagnostics[ds]
            result=item.get("result",item)
            k=result.get("status","UNCLASSIFIED")
            status[k]+=1
            date_status[ds][k]+=1
            verified_days+=1
            if k=="NO_MINUTE_TIME_OVERLAP":
                qmt_source_missing+=1
                gap_days.append(d)
            if k=="MINUTE_SOURCE_DIFFERENCE_REVIEW":
                causes=review_reason(result)
                reason.update(causes)
                minute=item.get("minute_diagnostics",{}) or {}
                counts=minute.get("field_mismatch_counts")
                if counts is None:
                    legacy_no_detail+=1
                else:
                    for field in FIELDS:
                        field_minutes[field]+=int(counts.get(field,0))
                if len(review_examples)<16:
                    review_examples.append({
                        "stock":code,"day":ds,"reasons":causes,
                        "compared":result.get("compared"),
                        "OHLC_fit":result.get("ohlc_all_fields_fit"),
                        "amount_fit":result.get("amount_minute_raw_fit"),
                        "offset_ms":result.get("tdx_to_qmt_time_offset_ms")})
        if gap_days:
            # Only ~180 stocks have QMT gaps. Read each independent eltdx
            # private file once and compare real 240-bar daily OHLC directly
            # against the separately pinned official DAY source.
            table=pq.read_table(source,columns=["ts",*OHLC])
            by_day=defaultdict(list)
            selected=set(gap_days)
            for item in table.to_pylist():
                d=datetime.fromtimestamp(item["ts"]/1000,P.CN).date()
                if d in selected:
                    by_day[d].append(item)
            for d in gap_days:
                rows=sorted(by_day.get(d,[]),key=lambda x:x["ts"])
                diag=independently_compare_tdx_day_to_official(rows,official[d][code])
                gap_candidates.append({
                    "stock":code,"day":d.isoformat(),
                    "result":diag,
                    "source":"independent eltdx 1m 240 bars; QMT 241 not reconstructed"})
        if i and i%1000==0:
            logger("ELTDX_FORENSICS_VERIFIED_SOURCE_SHA="+str(verified_stocks))
    official_days=sum(len(v) for v in official.values())
    if verified_days+sum(x["expected_days"] for x in failed.values())!=official_days:
        raise ValueError("Forensic day count does not reconcile to official DAY universe")
    source_present=Counter(x["result"]["status"] for x in gap_candidates)
    candidate_fit=sum(x["result"].get("all_four_fit",False) for x in gap_candidates)
    result={
        "format":FORMAT,"window":[str(X.START),str(X.END)],
        "official_expected_stock_days":official_days,
        "independent_source_stocks_sha_verified":verified_stocks,
        "independent_source_stock_days_sha_verified":verified_days,
        "source_not_available_stocks":len(failed),
        "source_not_available_stock_days":sum(x["expected_days"] for x in failed.values()),
        "source_failure_first_trading_dates":failed,
        "stock_day_statuses":dict(status),
        "review_reason_days_nonexclusive":dict(reason),
        "review_field_minute_mismatch_counts":dict(field_minutes),
        "review_days_without_minute_details":legacy_no_detail,
        "review_examples_no_market_prices":review_examples,
        "qmt_no_overlap_stock_days_with_eltdx":qmt_source_missing,
        "tdx_240_bar_gap_candidate_days":source_present.get(
            "TDX_240_VS_OFFICIAL_DAY_OHLC_DIAGNOSTIC_ONLY",0),
        "tdx_gap_days_all_four_official_day_ohlc_fit":candidate_fit,
        "gap_candidate_examples":gap_candidates[:12],
        "daily_statuses":{k:dict(v) for k,v in sorted(date_status.items())},
        "private_alternative_only_no_241_bar_fabrication":True,
        "market_files_modified":False,"production_merge_authorized":False}
    output=Path(workspace)/"latest_forensics_report.json"
    if output.is_symlink():
        raise ValueError("Redirected forensic report")
    P.safe_save(output,P.canonical(result))
    concise={k:v for k,v in result.items() if k not in (
        "source_failure_first_trading_dates","review_examples_no_market_prices",
        "gap_candidate_examples","daily_statuses")}
    logger("ELTDX_FORENSICS_SUMMARY="+json.dumps(concise,sort_keys=True,ensure_ascii=False))
    logger("ELTDX_FORENSICS_MISSING_SOURCES="+json.dumps(failed,sort_keys=True,ensure_ascii=False))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("D:/stock"))
    args=parser.parse_args(argv)
    inspect(args.root)


if __name__=="__main__":
    main()
