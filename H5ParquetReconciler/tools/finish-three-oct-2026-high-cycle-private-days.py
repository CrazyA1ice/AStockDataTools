#!/usr/bin/env python3
"""Finish exactly 2026-10-08/09/12 isolated H5 5min -> 15/30/60m candidates.

Re-uses the already Windows-proven bounded batch stager, purchased-priority
checks, receipts, and independent read-only full-date audit. NO production
merge, H5 mirror, market writes, vendor units or corporate-action certification.
Interruptions preserve successful immutable receipts and fail closed on partials.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
TARGETS=("2026-10-08","2026-10-09","2026-10-12")
BASELINE_DAY="2026-10-13"
SOURCE_ELIGIBLE={
    "2026-10-08":5546,
    "2026-10-09":5547,
    "2026-10-12":5549,
    "2026-10-13":5549,
}
ROWS_PER_STOCKDAY=28
BATCH_SIZE=100
MAX_BATCHES=60
AUDIT_STATUS="oct_2026_single_day_sha_verified_private_15_30_60min_candidate_coverage_readonly"
ROLLOUT_STATUS="oct_2026_bounded_resumable_private_highcycle_rollout"
FINAL_STATUS="oct_2026_three_day_private_highcycle_coverage_verified_readonly"

def _load(alias,filename):
    spec=importlib.util.spec_from_file_location(alias,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

A=_load("three_day_oct_private_final_audit",
        "audit-2026-oct-high-cycle-private-day-coverage-readonly.py")
R=_load("three_day_oct_private_bounded_rollout",
        "rollout-2026-oct-high-cycle-private-batches.py")

def validate(day,report):
    if (not isinstance(report,dict)
            or report.get("status")!=AUDIT_STATUS
            or report.get("day")!=day
            or report.get("eligible_full_h5_5min_source_stockdays")!=
               SOURCE_ELIGIBLE[day]
            or report.get("full_existing_receipt_and_parquet_sha_reverified") is not True
            or report.get("full_original_market_or_h5_files_modified") is not False
            or report.get("new_market_private_or_production_files_written") is not False
            or report.get("production_activated") is not False
            or report.get("vendor_physical_units_certified") is not False
            or report.get("unadjusted_time_label_semantics_certified") is not False
            or report.get("private_only_research_candidate_coverage") is not True
            or report.get("not_official_day_week_or_month_data") is not True
            or R.S.SHA256.fullmatch(str(
                report.get("existing_private_h5_source_sha256"))) is None):
        raise ValueError("Current "+day+" source eligibility/SHA/safety audit changed")
    eligible=report["eligible_full_h5_5min_source_stockdays"]
    staged=report.get("this_date_staged_complete_stockdays")
    missing=report.get("this_date_unstaged_complete_stockdays")
    prior=report.get("stage_stockdays_all_october_sha_verified")
    counts=(report.get("private_candidate_15min_rows_for_this_date"),
            report.get("private_candidate_30min_rows_for_this_date"),
            report.get("private_candidate_60min_rows_for_this_date"))
    if (any(type(x) is not int for x in (staged,missing,prior,*counts))
            or staged<0 or missing<0 or staged+missing!=eligible
            or report.get("this_date_coverage_complete") is not (missing==0)
            or counts!=(16*staged,8*staged,4*staged)
            or prior<staged
            or report.get("all_october_private_candidate_rows")!=
               ROWS_PER_STOCKDAY*prior):
        raise ValueError("Invalid "+day+" private stockday/Parquet row conservation")
    return report

def finish(root,*,preview_only=False,emit=print,rollout=R.rollout,audit=A.audit):
    if type(preview_only) is not bool:
        raise ValueError("Preview mode must be boolean")
    if not Path(root).is_dir() or Path(root).is_symlink():
        raise ValueError("Original market root missing or unsafe")
    # Preflight ALL dates before writing any date. Oct 13 is immutable
    # already-complete baseline; no work is ever scheduled for that date.
    initial={d:validate(d,audit(date.fromisoformat(d)))
             for d in (*TARGETS,BASELINE_DAY)}
    last=initial[BASELINE_DAY]
    if (not last["this_date_coverage_complete"]
            or last["this_date_staged_complete_stockdays"]!=5549):
        raise ValueError("Previously completed 2026-10-13 must remain SHA-verified")
    counts=[initial[d]["stage_stockdays_all_october_sha_verified"]
            for d in (*TARGETS,BASELINE_DAY)]
    if len(set(counts))!=1 or counts[0]<5555:
        raise ValueError("Existing verified private receipt registry changed during preflight")
    base=counts[0]
    new_total=0
    per_day={}
    for d in TARGETS:
        x=initial[d]
        remaining=x["this_date_unstaged_complete_stockdays"]
        required=(remaining+BATCH_SIZE-1)//BATCH_SIZE
        if required>MAX_BATCHES:
            raise ValueError("Private daily candidate batch bound exceeded")
        emit("OCT_THREE_DAY_PREFLIGHT "+json.dumps({
            "day":d,"complete_h5_stockdays":SOURCE_ELIGIBLE[d],
            "staged":x["this_date_staged_complete_stockdays"],
            "remaining":remaining,"bounded_batches":required,
            "preview_only":preview_only,
            "source_sha256":x["existing_private_h5_source_sha256"]},
            sort_keys=True))
        per_day[d]={
            "source_eligible":SOURCE_ELIGIBLE[d],
            "previous_stockdays":x["this_date_staged_complete_stockdays"],
            "uncovered_at_start":remaining,
            "needed_batches":required,
            "new_stockdays":0,
            "new_candidate_rows":0,
        }
    if preview_only:
        return {
            "status":FINAL_STATUS,
            "preview_only":True,"dates":list(TARGETS),
            "baseline_day_verified":True,
            "original_verified_stockdays_all_oct":base,
            "original_candidate_rows_all_oct":base*ROWS_PER_STOCKDAY,
            "per_day":per_day,
            "new_stockdays":0,"new_candidate_rows":0,
            "original_market_files_modified":False,
            "production_activated":False,
            "ready_for_production_merge":False,
        }
    for d in TARGETS:
        old=initial[d]
        remaining=old["this_date_unstaged_complete_stockdays"]
        count=per_day[d]["needed_batches"]
        if count:
            emit("OCT_THREE_DAY_START "+json.dumps({
                "day":d,"batches":count,"stockdays_remaining":remaining},
                sort_keys=True))
            summary=rollout(
                Path(root),date.fromisoformat(d),
                batch_size=BATCH_SIZE,max_batches=count,
                preview_only=False,emit=emit)
            if (not isinstance(summary,dict)
                    or summary.get("status")!=ROLLOUT_STATUS
                    or summary.get("day")!=d
                    or summary.get("preview_only") is not False
                    or summary.get("batch_size")!=BATCH_SIZE
                    or summary.get("max_batches")!=count
                    or summary.get("batches_completed")!=count
                    or summary.get("preexisting_stockdays")!=base+new_total
                    or summary.get("source_eligible")!=SOURCE_ELIGIBLE[d]
                    or summary.get("uncovered_before")!=remaining
                    or summary.get("uncovered_after")!=0
                    or summary.get("new_private_stockdays")!=remaining
                    or summary.get("new_rows")!=remaining*ROWS_PER_STOCKDAY
                    or summary.get("original_market_files_modified") is not False
                    or summary.get("production_activated") is not False
                    or summary.get("ready_for_production_merge") is not False
                    or summary.get("no_raw_ohlcva_printed") is not True
                    or not isinstance(summary.get("run_ids"),list)
                    or len(summary["run_ids"])!=count):
                raise ValueError("Unexpected bounded private rollout receipt: "+d)
        # Independently re-evaluate current source and SHA ALL prior
        # Parquet receipt physical files even when day was already complete.
        final=validate(d,audit(date.fromisoformat(d)))
        if (not final["this_date_coverage_complete"]
                or final["this_date_unstaged_complete_stockdays"]!=0
                or final["this_date_staged_complete_stockdays"]!=SOURCE_ELIGIBLE[d]
                or final["existing_private_h5_source_sha256"]!=
                   old["existing_private_h5_source_sha256"]
                or final["stage_stockdays_all_october_sha_verified"]!=
                   base+new_total+remaining):
            raise ValueError("Independent full-date SHA/coverage audit failed: "+d)
        new_total+=remaining
        per_day[d]["new_stockdays"]=remaining
        per_day[d]["new_candidate_rows"]=remaining*ROWS_PER_STOCKDAY
        emit("PASS_OCT_THREE_DAY_DATE_PRIVATE_HIGH_CYCLE "+json.dumps({
            "day":d,"verified_stockdays":SOURCE_ELIGIBLE[d],
            "uncovered":0,"date_candidate_rows":SOURCE_ELIGIBLE[d]*28,
            "new_candidate_rows":remaining*28,
            "original_market_files_modified":False,
            "production_activated":False},sort_keys=True))
    # One final immutable-read-only audit of ALL 4 dates and ALL receipts.
    end={d:validate(d,audit(date.fromisoformat(d)))
         for d in (*TARGETS,BASELINE_DAY)}
    if (any(not report["this_date_coverage_complete"]
            or report["existing_private_h5_source_sha256"]!=
               initial[d]["existing_private_h5_source_sha256"]
            or report["this_date_unstaged_complete_stockdays"]!=0
            or report["this_date_staged_complete_stockdays"]!=SOURCE_ELIGIBLE[d]
            or report["stage_stockdays_all_october_sha_verified"]!=base+new_total
            for d,report in end.items())):
        raise ValueError("Four-date private candidate final evidence changed")
    return {
        "status":FINAL_STATUS,"preview_only":False,
        "dates":list(TARGETS),"baseline_day_verified":True,
        "original_verified_stockdays_all_oct":base,
        "original_candidate_rows_all_oct":base*ROWS_PER_STOCKDAY,
        "per_day":per_day,
        "new_stockdays":new_total,"new_candidate_rows":new_total*ROWS_PER_STOCKDAY,
        "final_verified_stockdays_all_oct":base+new_total,
        "final_candidate_rows_all_oct":(base+new_total)*ROWS_PER_STOCKDAY,
        "all_four_dates_source_complete":True,
        "original_market_files_modified":False,
        "production_activated":False,
        "ready_for_production_merge":False,
        "source_vendor_units_certified":False,
        "no_day_week_month_materialized":True,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    flags=p.add_mutually_exclusive_group(required=True)
    flags.add_argument("--preview-only",action="store_true")
    flags.add_argument("--write-private-candidates-only",action="store_true")
    a=p.parse_args(argv)
    try:
        summary=finish(a.root,preview_only=a.preview_only,
                       emit=lambda msg:print(msg,flush=True))
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as err:
        p.error("Three-day Oct private candidate sequence STOPPED; completed "+
                "private receipts remain immutable; no source/production writes: "+
                type(err).__name__+": "+str(err))
    print("PRIVATE_OCT_THREE_DAY_FINAL="+json.dumps(
        summary,ensure_ascii=False,sort_keys=True,separators=(",",":")),
        flush=True)

if __name__=="__main__":
    main()
