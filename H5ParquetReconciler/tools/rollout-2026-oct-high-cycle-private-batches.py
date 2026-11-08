#!/usr/bin/env python3
"""Resume-safe bounded sequence of October 2026 PRIVATE 15/30/60m stages.

Per batch, start from live SHA-verified receipts (NOT page offsets), verify
complete H5 5m stockdays and original purchased priority, then use the
previously Windows-accepted full-row Parquet stager. Each batch is a separate
immutable run. Stops on ANY unexpected condition, never auto-skips failed
source/purchased checks, and NEVER touches original market/active H5/PQ.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
PERIODS=("15min","30min","60min")
ROWS_PER_STOCKDAY={"15min":16,"30min":8,"60min":4}
PLAN_STATUS="oct_2026_only_unstaged_sha_verified_h5_5min_stockdays_private_research"
STAGE_STATUS="oct_2026_next_uncovered_private_highcycle_written_readback"
OUTPUT_STATUS="oct_2026_bounded_resumable_private_highcycle_rollout"
MAX_BATCHES=60

def _load():
    spec=importlib.util.spec_from_file_location(
        "oct_private_bounded_next_uncovered",
        HERE/"stage-next-uncovered-oct-h5-high-cycle-private-parquet.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

N=_load()
S=N.S

def _validate(day,batch_size,max_batches):
    if type(day) is not date or day.year!=2026 or day.month!=10:
        raise ValueError("Only explicitly selected October 2026 source dates")
    if type(batch_size) is not int or not 1<=batch_size<=100:
        raise ValueError("Batch size must be in 1..100")
    if type(max_batches) is not int or not 1<=max_batches<=MAX_BATCHES:
        raise ValueError("Max batches must be in 1..60")

def _validate_plan(report,day,batch_size):
    if (report.get("status")!=PLAN_STATUS or report.get("day")!=day.isoformat()
            or report.get("batch_size")!=batch_size
            or report.get("source_5min_private_SHA_checked") is not True
            or S.SHA256.fullmatch(str(report.get("source_sha256"))) is None
            or report.get("original_market_files_modified") is not False
            or report.get("new_private_or_production_files_written") is not False
            or report.get("production_activated") is not False
            or report.get("vendor_physical_units_certified") is not False):
        raise ValueError("Unsafe next-uncovered source preview")
    eligible=report.get("h5_5min_complete_eligible_stockdays")
    staged=report.get("already_staged_complete_eligible_this_day")
    uncovered=report.get("uncovered_complete_eligible_this_day")
    chosen=report.get("chosen_stockdays")
    pending=report.get("remaining_uncovered_stockdays_after_selection")
    symbols=report.get("selected_symbols")
    if (any(type(x) is not int for x in (eligible,staged,uncovered,chosen,pending))
            or not isinstance(symbols,list) or
            not 0<=staged<=eligible or uncovered!=eligible-staged
            or chosen!=min(batch_size,uncovered) or len(symbols)!=chosen
            or len(set(symbols))!=chosen or
            any(not isinstance(s,str) or S.SYMBOL.fullmatch(s) is None for s in symbols)
            or pending!=uncovered-chosen):
        raise ValueError("Unsafe next-uncovered stockday/count conservation")

def _verify_written(result,initial,day,runid):
    written=result.get("stage")
    inplan=result.get("plan")
    if (result.get("status")!=STAGE_STATUS
            or result.get("only_unstaged_candidates_selected") is not True
            or result.get("original_market_files_modified") is not False
            or result.get("production_activated") is not False
            or not isinstance(inplan,dict) or not isinstance(written,dict)
            or inplan.get("day")!=day.isoformat()
            or inplan.get("chosen_stockdays")!=initial["chosen_stockdays"]
            or inplan.get("source_sha256")!=initial["source_sha256"]
            or written.get("run_id")!=runid
            or written.get("status")!=N.SUCCESS
            or written.get("source_days")!=[day.isoformat()]
            or written.get("symbols")!=initial["selected_symbols"]
            or written.get("verified_source_stockdays")!=initial["chosen_stockdays"]
            or written.get("purchased_high_cycle_source_blocks")!=0
            or any(written.get(k)!=v for k,v in N.PREVIOUS_SAFE_FIELDS.items())):
        raise ValueError("Stage success manifest did not match private source plan")
    outputs=written.get("outputs")
    if not isinstance(outputs,dict) or set(outputs)!=set(PERIODS):
        raise ValueError("Unexpected private output periods")
    receipt=S._safe_stage_root()/runid/"receipt.json"
    if receipt.is_symlink() or not receipt.is_file():
        raise ValueError("Written private stage receipt absent")
    if json.loads(receipt.read_text(encoding="utf-8"))!=written:
        raise ValueError("Written private receipt content disagrees with result")
    counts={}
    hashes={}
    for period in PERIODS:
        meta=outputs[period]
        path=receipt.parent/(period+".parquet")
        expected=ROWS_PER_STOCKDAY[period]*initial["chosen_stockdays"]
        if (meta.get("rows")!=expected
                or meta.get("complete_row_by_row_readback_exact") is not True
                or meta.get("private_file")!=path.relative_to(S.MODULE).as_posix()
                or S.SHA256.fullmatch(str(meta.get("sha256"))) is None
                or not path.is_file() or path.is_symlink()
                or S._sha(path)!=meta["sha256"]):
            raise ValueError("Written private "+period+" Parquet SHA/readback mismatch")
        counts[period]=expected
        hashes[period]=meta["sha256"]
    return {"run_id":runid,"new_stockdays":initial["chosen_stockdays"],
            "rows_by_period":counts,"sha256_by_period":hashes,
            "new_rows":sum(counts.values()),
            "receipt_relative_file":receipt.relative_to(S.MODULE).as_posix()}

def rollout(root,day,*,batch_size=100,max_batches=8,
            preview_only=False,emit=print,id_factory=None):
    _validate(day,batch_size,max_batches)
    if type(preview_only) is not bool:
        raise ValueError("Preview-only switch must be boolean")
    if not Path(root).is_dir() or Path(root).is_symlink():
        raise ValueError("Original market root unavailable or unsafe")
    make_id=id_factory or (lambda:secrets.token_hex(6))
    total=0
    stockdays=0
    records=[]
    initial=N.plan(day,batch_size=batch_size)
    _validate_plan(initial,day,batch_size)
    emit("OCT_BOUNDED_ROLLOUT_PREVIEW "+json.dumps({
        "day":day.isoformat(),
        "already_staged_source_stockdays":initial["previous_private_stockdays_sha_rechecked"],
        "eligible_complete_source_stockdays":initial["h5_5min_complete_eligible_stockdays"],
        "previously_staged_on_day":initial["already_staged_complete_eligible_this_day"],
        "uncovered_source_stockdays":initial["uncovered_complete_eligible_this_day"],
        "next_batch_stockdays":initial["chosen_stockdays"],
        "batch_size":batch_size,"max_batches":max_batches,
        "preview_only":preview_only,
        "no_raw_ohlcva_printed":True},sort_keys=True))
    if preview_only:
        return {
            "status":OUTPUT_STATUS,
            "preview_only":True,
            "day":day.isoformat(),
            "preexisting_stockdays":initial["previous_private_stockdays_sha_rechecked"],
            "source_eligible":initial["h5_5min_complete_eligible_stockdays"],
            "uncovered_before":initial["uncovered_complete_eligible_this_day"],
            "planned_first_batch":initial["chosen_stockdays"],
            "new_private_stockdays":0,
            "new_rows":0,
            "batches_completed":0,
            "original_market_files_modified":False,
            "production_activated":False,
            "ready_for_production_merge":False,
        }
    plan=initial
    for step in range(max_batches):
        _validate_plan(plan,day,batch_size)
        if not plan["selected_symbols"]:
            break
        runid=make_id()
        if type(runid) is not str or S.RUNID.fullmatch(runid) is None:
            raise ValueError("Invalid generated private run ID")
        if (S._safe_stage_root()/runid).exists():
            raise ValueError("Generated private run ID already exists")
        emit("OCT_BOUNDED_BATCH_BEGIN "+json.dumps({
            "ordinal":step+1,"run_id":runid,
            "stockdays":plan["chosen_stockdays"],
            "uncovered_before":plan["uncovered_complete_eligible_this_day"]},
            sort_keys=True))
        result=N.stage_next(Path(root),day,runid,batch_size=batch_size)
        # A valid receipt exists already at this point. Print its path BEFORE
        # post-write checks; if those checks fail, rerun will use the receipt.
        emit("OCT_BOUNDED_BATCH_RECEIPT "+
             (S._safe_stage_root()/runid/"receipt.json").as_posix())
        checked=_verify_written(result,plan,day,runid)
        records.append(checked)
        stockdays+=checked["new_stockdays"]
        total+=checked["new_rows"]
        emit("OCT_BOUNDED_BATCH_PASS "+json.dumps({
            **checked,"ordinal":step+1,
            "original_market_files_modified":False,
            "production_activated":False},sort_keys=True))
        # Next plan always re-hashes ALL prior successful private receipts;
        # any half-written batch or changed SHA fails BEFORE another write.
        if step+1<max_batches:
            next_plan=N.plan(day,batch_size=batch_size)
            _validate_plan(next_plan,day,batch_size)
            if (next_plan["source_sha256"]!=initial["source_sha256"]
                    or next_plan["h5_5min_complete_eligible_stockdays"]!=
                       initial["h5_5min_complete_eligible_stockdays"]
                    or next_plan["previous_private_stockdays_sha_rechecked"]!=
                       plan["previous_private_stockdays_sha_rechecked"]+
                       plan["chosen_stockdays"]
                    or next_plan["uncovered_complete_eligible_this_day"]!=
                       plan["uncovered_complete_eligible_this_day"]-
                       plan["chosen_stockdays"]):
                raise ValueError("Source inventory/receipt ledger changed during rollout")
            plan=next_plan
    # Count source-inventory remainder by subtracting successfully validated
    # batches only; no optimistic claimed coverage for interrupted operations.
    remaining=initial["uncovered_complete_eligible_this_day"]-stockdays
    if remaining<0 or total!=28*stockdays:
        raise ValueError("Rollout candidate row/stockday counts inconsistent")
    return {
        "status":OUTPUT_STATUS,
        "day":day.isoformat(),
        "preview_only":False,
        "batch_size":batch_size,"max_batches":max_batches,
        "preexisting_stockdays":initial["previous_private_stockdays_sha_rechecked"],
        "source_eligible":initial["h5_5min_complete_eligible_stockdays"],
        "uncovered_before":initial["uncovered_complete_eligible_this_day"],
        "uncovered_after":remaining,
        "new_private_stockdays":stockdays,
        "new_rows":total,
        "batches_completed":len(records),
        "run_ids":[r["run_id"] for r in records],
        "original_market_files_modified":False,
        "production_activated":False,
        "ready_for_production_merge":False,
        "no_raw_ohlcva_printed":True,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--day",default="2026-10-13")
    p.add_argument("--batch-size",type=int,default=100)
    p.add_argument("--max-batches",type=int,default=8)
    switches=p.add_mutually_exclusive_group(required=True)
    switches.add_argument("--preview-only",action="store_true")
    switches.add_argument("--write-private-candidates-only",action="store_true")
    a=p.parse_args(argv)
    try:
        result=rollout(
            a.root,date.fromisoformat(a.day),
            batch_size=a.batch_size,max_batches=a.max_batches,
            preview_only=a.preview_only,
            emit=lambda msg:print(msg,flush=True))
    except (ValueError,TypeError,OSError,RuntimeError,KeyError) as exc:
        p.error("Bounded private rollout interrupted; already completed receipts "+
                "remain immutable and checked before restart: "+
                type(exc).__name__+": "+str(exc))
    print("PRIVATE_OCT_BOUNDED_ROLLOUT="+json.dumps(
        result,ensure_ascii=False,sort_keys=True,separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
