#!/usr/bin/env python3
"""Bounded next-UNSTAGED Oct 2026 5m->15/30/60m PRIVATE research stage.

Read immutable prior candidate receipts and re-hash their physical Parquet
before selecting only previously UNSTAGED valid H5-only complete stockdays.
Same existing purchased-priority + H5 5min SHA/checks + exact full readback
are enforced again by the accepted isolated stager. No market files or active
pointers are written. Does not certify units, timestamps or adjustments.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
REGULAR_PERIODS=("15min","30min","60min")
ROW_COUNT_PER_STOCKDAY={"15min":16,"30min":8,"60min":4}
SUCCESS="research_only_private_oct_h5_5min_highcycle_candidates_written_readback"
PREVIOUS_SAFE_FIELDS={
    "purchased_high_cycle_source_blocks":0,
    "source_5min_original_SHA_receipts_verified":True,
    "all_48_native_start_grid_bars_required":True,
    "all_purchased_high_cycle_periods_must_be_absent":True,
    "no_day_week_month_materialized":True,
    "vendor_physical_units_certified":False,
    "timestamp_conversion_certified":False,
    "corporate_adjustments_certified":False,
    "original_market_files_modified":False,
    "production_or_private_active_pointer_modified":False,
    "ready_for_production_merge":False,
    "ready_for_h5_mirror":False,
    "raw_OHLCVA_in_report":False,
}
STATUS="oct_2026_only_unstaged_sha_verified_h5_5min_stockdays_private_research"

def _load(tag,name):
    spec=importlib.util.spec_from_file_location(tag,HERE/name)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

A=_load("oct_auto_unstaged_existing_inventory",
        "auto-batch-2026-oct-h5-high-cycle-private-parquet.py")
S=A.S

def existing_stockdays():
    """Fail closed on stale/malformed receipts, hashes, duplicates, partial runs.

    Return (stockday keys, validated-run count); a missing receipt in an
    existing run directory is NOT treated as a fresh/available stockday.
    """
    stage=S._safe_stage_root()
    if not stage.exists():
        return frozenset(),0
    if stage.is_symlink() or not stage.is_dir():
        raise ValueError("Unsafe existing private high-cycle stage root")
    records=set()
    runs=0
    for entry in sorted(stage.iterdir()):
        runs+=1
        if runs>10000:
            raise ValueError("Existing private stage run count exceeds bound")
        if (entry.is_symlink() or not entry.is_dir()
                or S.RUNID.fullmatch(entry.name) is None):
            raise ValueError("Unknown or unsafe existing private stage run")
        receipt=entry/"receipt.json"
        if receipt.is_symlink() or not receipt.is_file():
            raise ValueError("Incomplete existing private stage: receipt absent")
        doc=json.loads(receipt.read_text(encoding="utf-8"))
        days=doc.get("source_days")
        symbols=doc.get("symbols")
        if (doc.get("run_id")!=entry.name or doc.get("status")!=SUCCESS
                or any(doc.get(k)!=v for k,v in PREVIOUS_SAFE_FIELDS.items())
                or not isinstance(days,list) or not 1<=len(days)<=20
                or len(set(days))!=len(days)
                or not isinstance(symbols,list) or not 1<=len(symbols)<=100
                or len(set(symbols))!=len(symbols)
                or any(not isinstance(sym,str) or S.SYMBOL.fullmatch(sym) is None
                       for sym in symbols)
                or doc.get("verified_source_stockdays")!=len(days)*len(symbols)):
            raise ValueError("Untrusted existing candidate receipt identity/safety")
        for d in days:
            if type(d) is not str:
                raise ValueError("Invalid prior candidate date")
            dd=date.fromisoformat(d)
            if dd.year!=2026 or dd.month!=10:
                raise ValueError("Existing stage receipt outside October 2026")
        sources=doc.get("sources")
        if not isinstance(sources,list) or len(sources)!=len(days):
            raise ValueError("Existing private stage source receipt count mismatch")
        for source in sources:
            if (not isinstance(source,dict) or
                    source.get("day") not in days):
                raise ValueError("Existing private stage source provenance wrong")
            file,hash_from_verified_source=S.source_receipt(
                date.fromisoformat(source["day"]))
            if (source.get("sha256")!=hash_from_verified_source
                    or source.get("source_5min_private_file")!=
                       file.relative_to(S.MODULE).as_posix()):
                raise ValueError("Existing candidate source SHA no longer verified")
        if {src["day"] for src in sources}!=set(days):
            raise ValueError("Duplicate private source date in prior receipt")
        outputs=doc.get("outputs")
        if not isinstance(outputs,dict) or set(outputs)!=set(REGULAR_PERIODS):
            raise ValueError("Existing private output periods incorrect")
        for period in REGULAR_PERIODS:
            output=outputs[period]
            file=entry/(period+".parquet")
            n=len(days)*len(symbols)*ROW_COUNT_PER_STOCKDAY[period]
            if (not isinstance(output,dict)
                    or not file.is_file() or file.is_symlink()
                    or output.get("private_file")!=
                       file.relative_to(S.MODULE).as_posix()
                    or output.get("rows")!=n
                    or output.get("complete_row_by_row_readback_exact") is not True
                    or not isinstance(output.get("sha256"),str)
                    or S.SHA256.fullmatch(output["sha256"]) is None
                    or S._sha(file)!=output["sha256"]):
                raise ValueError("Existing private candidate Parquet changed or receipt invalid")
        for d in days:
            for sym in symbols:
                key=(d,sym)
                if key in records:
                    raise ValueError("Duplicate existing high-cycle private stockday")
                records.add(key)
    return frozenset(records),runs

def plan(day,*,batch_size=64):
    if type(day) is not date or day.year!=2026 or day.month!=10:
        raise ValueError("New private candidate plan limited to October 2026")
    if type(batch_size) is not int or not 1<=batch_size<=100:
        raise ValueError("Bounded batch size must be between 1 and 100")
    staged,runs=existing_stockdays()
    # Include both canary symbols in the original inventory and exclude them
    # only if their respective day was physically SHA-verified as staged.
    source=A.discover(day,exclude=frozenset())
    eligible=source["eligible_symbols"]
    candidates=[symbol for symbol in eligible
                if (day.isoformat(),symbol) not in staged]
    picked=candidates[:batch_size]
    report={
        "status":STATUS,
        "day":day.isoformat(),
        "batch_size":batch_size,
        "previous_private_runs_sha_rechecked":runs,
        "previous_private_stockdays_sha_rechecked":len(staged),
        "source_5min_private_SHA_checked":True,
        "h5_5min_complete_eligible_stockdays":len(eligible),
        "already_staged_complete_eligible_this_day":len(eligible)-len(candidates),
        "uncovered_complete_eligible_this_day":len(candidates),
        "chosen_stockdays":len(picked),
        "remaining_uncovered_stockdays_after_selection":len(candidates)-len(picked),
        "selected_symbols":picked,  # IDs only, no OHLCVA
        "source_sha256":source["source_5min_sha256"],
        "inventory_excluded_by_reason":source["excluded_by_reason"],
        "original_market_files_modified":False,
        "new_private_or_production_files_written":False,
        "production_activated":False,
        "vendor_physical_units_certified":False,
    }
    return report

def stage_next(root,day,run_id,*,batch_size=64):
    selected=plan(day,batch_size=batch_size)
    if not selected["selected_symbols"]:
        raise ValueError("No previously unstaged complete H5 5min stockdays")
    # S.stage performs independent purchased high-cycle check and full 48-bar
    # re-read, physical SHA, complete output Parquet row readback.
    written=S.stage(Path(root),[day.isoformat()],selected["selected_symbols"],run_id)
    expected={
        p:ROW_COUNT_PER_STOCKDAY[p]*selected["chosen_stockdays"]
        for p in REGULAR_PERIODS
    }
    if (written["verified_source_stockdays"]!=selected["chosen_stockdays"]
            or written["source_days"]!=[day.isoformat()]
            or written["symbols"]!=selected["selected_symbols"]
            or {p:written["outputs"][p]["rows"] for p in REGULAR_PERIODS}!=expected
            or written["sources"][0]["sha256"]!=selected["source_sha256"]
            or written["ready_for_production_merge"] is not False):
        raise ValueError("Next private high-cycle stage contract failed")
    return {
        "status":"oct_2026_next_uncovered_private_highcycle_written_readback",
        "plan":{k:v for k,v in selected.items() if k!="selected_symbols"},
        "stage":written,
        "only_unstaged_candidates_selected":True,
        "original_market_files_modified":False,
        "production_activated":False,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--day",default="2026-10-13")
    p.add_argument("--batch-size",type=int,default=64)
    p.add_argument("--run-id")
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--preview-only",action="store_true")
    group.add_argument("--write-private-candidates-only",action="store_true")
    a=p.parse_args(argv)
    try:
        dd=date.fromisoformat(a.day)
        if a.preview_only:
            result=plan(dd,batch_size=a.batch_size)
            label="PRIVATE_OCT_NEXT_UNSTAGED_PLAN="
        else:
            if a.run_id is None:
                raise ValueError("An explicit unique 12-hex-digit run ID is required")
            result=stage_next(a.root,dd,a.run_id,batch_size=a.batch_size)
            label="PRIVATE_OCT_NEXT_UNSTAGED_STAGE="
    except (ValueError,TypeError,OSError,RuntimeError,KeyError) as e:
        p.error("Next-unstaged Oct research candidate NOT accepted: "+
                type(e).__name__+": "+str(e)+
                "; no original market writes; an interrupted private run may remain")
    if a.preview_only:
        result.pop("selected_symbols") # never print even selected IDs by default
    print(label+json.dumps(result,ensure_ascii=False,sort_keys=True,
                           separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
