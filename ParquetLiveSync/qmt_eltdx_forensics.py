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
            reasons.append(field.upper()+"_AMBIGUOUS")
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



def reference_source(day, plan):
    """Infer the pinned DAY source, not assume it is provider-independent.

    QMT month stage may use TDX DAILY private overlay for days not present
    in purchased/physical Parquet. TDX-1m vs TDX-DAY does not count as a
    third independent provider confirmation.
    """
    versions=plan.get("day_file_sha256",{})
    if not isinstance(versions,dict):
        return "DAY_REFERENCE_ORIGIN_UNKNOWN"
    overlay=versions.get("tdx_overlay",{})
    if isinstance(overlay,dict) and day.isoformat() in overlay:
        return "TDX_DAY_OVERLAY_SAME_VENDOR_FAMILY"
    physical=versions.get("physical",{})
    if isinstance(physical,dict) and day.strftime("%Y-%m")+".parquet" in physical:
        return "PHYSICAL_PARQUET_DAY_PROVIDER_UNVERIFIED"
    return "DAY_REFERENCE_ORIGIN_UNKNOWN"


def categorize_review(result):
    """One exclusive operational triage class; NOT a data acceptance result."""
    if result.get("status")!="MINUTE_SOURCE_DIFFERENCE_REVIEW":
        raise ValueError("Only discrepancy days can be triaged")
    if result.get("offset_ambiguous"):
        return "TIME_OFFSET_NEEDS_REVIEW"
    if result.get("tdx_count")!=240 or result.get("qmt_count")!=241:
        return "MINUTE_GRID_NEEDS_REVIEW"
    if result.get("ohlc_all_fields_fit",0)<.95:
        return "PRICE_DISAGREEMENT_NEEDS_REVIEW"
    am=result.get("amount_factor",{}) or {}
    vm=result.get("volume_factor",{}) or {}
    if am.get("pairs",0)<30 or vm.get("pairs",0)<30:
        return "THIN_TRADING_UNIT_FACTOR_UNPROVEN"
    if result.get("amount_minute_raw_fit",0)<.85:
        return "PRICES_ALIGN_AMOUNT_NEEDS_REVIEW"
    if vm.get("matching_fraction",0)<.85:
        return "PRICES_ALIGN_VOLUME_NEEDS_REVIEW"
    return "FACTOR_OR_OTHER_NEEDS_REVIEW"


def classify_gap_candidate(diagnostic, day_source):
    """A DAY price match is diagnostic, never a license to fabricate 241m."""
    if diagnostic.get("status")!="TDX_240_VS_OFFICIAL_DAY_OHLC_DIAGNOSTIC_ONLY":
        return "REJECT_INCOMPLETE_INDEPENDENT_MINUTES"
    if not diagnostic.get("all_four_fit",False):
        return "REJECT_DAY_OHLC_CONFLICT"
    if day_source=="TDX_DAY_OVERLAY_SAME_VENDOR_FAMILY":
        return "TDX_FAMILY_SELF_CONSISTENT_NOT_INDEPENDENT"
    if day_source=="PHYSICAL_PARQUET_DAY_PROVIDER_UNVERIFIED":
        return "OHLC_CONSISTENT_DAY_PROVIDER_UNVERIFIED"
    return "DAY_SOURCE_UNKNOWN_FURTHER_PROOF_REQUIRED"


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
    review_items=[]
    review_category=Counter()
    gap_quality=Counter()
    gap_provenance=Counter()
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
                category=categorize_review(result)
                review_category[category]+=1
                reason.update(causes)
                minute=item.get("minute_diagnostics",{}) or {}
                counts=minute.get("field_mismatch_counts")
                if counts is None:
                    legacy_no_detail+=1
                else:
                    for field in FIELDS:
                        field_minutes[field]+=int(counts.get(field,0))
                review_record={"stock":code,"day":ds,"review_class":category,
                               "reasons":causes,
                               "minute_field_mismatches":counts,
                               "offset_ms":result.get("tdx_to_qmt_time_offset_ms"),
                               "qmt_bars":result.get("qmt_count"),
                               "tdx_bars":result.get("tdx_count"),
                               "OHLC_fit":result.get("ohlc_all_fields_fit"),
                               "amount_raw_fit":result.get("amount_minute_raw_fit"),
                               "amount_factor":result.get("amount_factor"),
                               "volume_factor":result.get("volume_factor"),
                               "production_merge_authorized":False}
                review_items.append(review_record)
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
                provenance=reference_source(d,plan)
                disposition=classify_gap_candidate(diag,provenance)
                gap_quality[disposition]+=1
                gap_provenance[provenance]+=1
                gap_candidates.append({
                    "stock":code,"day":d.isoformat(),
                    "result":diag,
                    "day_reference_provenance":provenance,
                    "review_disposition":disposition,
                    "auto_fill_prohibited":True,
                    "source":"eltdx native 240m + source-tagged DAY; QMT 241 not reconstructed"})
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
        "review_exclusive_day_classes":dict(review_category),
        "gap_review_dispositions":dict(gap_quality),
        "gap_reference_provenance":dict(gap_provenance),
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
    # Complete case queues, not only first 12/16 examples in summary.
    # These are private diagnostic metadata, not licensed raw market bars.
    if len(review_items)!=status.get("MINUTE_SOURCE_DIFFERENCE_REVIEW",0):
        raise ValueError("Private review queue count does not reconcile")
    if len(gap_candidates)!=status.get("NO_MINUTE_TIME_OVERLAP",0):
        raise ValueError("Private gap queue count does not reconcile")
    for name,items in (("latest_review_queue.private.json",review_items),
                       ("latest_gap_queue.private.json",gap_candidates)):
        dest=Path(workspace)/name
        if dest.is_symlink():
            raise ValueError("Symlinked private forensic queue")
        P.safe_save(dest,P.canonical({"format":FORMAT,"plan_sha256":plan_hash,
                 "cases":items,"market_files_modified":False,
                 "production_merge_authorized":False}))
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
