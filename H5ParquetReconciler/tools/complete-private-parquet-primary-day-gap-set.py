#!/usr/bin/env python3
"""Finish *all audited whole-market H5-only day dates* as private Parquet.

This orchestrates EXISTING full A-share candidate coverage gate, H5-only day
stager and immutable version preparer; it is NOT a stock-sample snapshot.
Purchased original Parquet is always first and NEVER altered. The added
Parquet date partitions are kept separately in ignored work/; the prepared
version LOGICALLY references purchased source and verified missing dates.
Never activates the private pointer, creates an H5 mirror, or switches a
production route. H5 volume/amount candidate factors remain uncertified.

Use --action plan to check readiness without writing any data or version.
Use --action complete --allow-private-parquet-stage to fill only missing
whole-day partitions and PREPARE a new immutable *private* overlay version.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools complete audited full-market H5-only daily private Parquet gap set v1"
MAX_STAGE_DIRS=128
MAX_GAP_DAYS=31
MAX_GAP_ROWS=1000000


def import_local(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


OVERLAY=import_local("full_day_complete_existing_overlay",
                     "build-parquet-primary-day-overlay.py")
STAGE=OVERLAY.stage_tool


def output_path(target):
    out=Path(target)
    if (REPORTS.is_symlink() or out.is_symlink()
            or out.exists() or out.suffix.lower()!=".json"
            or out.resolve().parent!=REPORTS.resolve()):
        raise ValueError("SAFE must be a new JSON inside module reports")
    return out.resolve()


def evidence(gate_path,source_path):
    known=OVERLAY.verify_reports(gate_path,source_path)
    gate=json.loads(Path(gate_path).read_text(encoding="utf-8"))
    expected=known["expected"]
    rows=sum(expected.values())
    if (not 1<=len(expected)<=MAX_GAP_DAYS
            or not 1<=rows<=MAX_GAP_ROWS
            or gate.get("h5_only_rows_on_wholly_parquet_absent_dates")!=rows
            or gate.get("h5_only_rows_on_mixed_dates_need_symbol_day_manifest")!=0
            or any(type(n) is not int or n<=0 or n>20000
                   for n in expected.values())):
        raise ValueError("Only complete-date audited H5 gaps, with zero mixed-date gaps")
    if len({date.fromisoformat(d).year for d in expected})!=1:
        raise ValueError("Audited H5-only complete days must share one year")
    return known,gate


def existing_stages(known):
    staging=OVERLAY.STAGING
    if (staging.is_symlink() or (MODULE/"work").is_symlink()
            or (MODULE/"work"/"unified_parquet").is_symlink()):
        raise ValueError("Unsafe module private Parquet staging parent")
    if not staging.exists():
        return {}
    if not staging.is_dir():
        raise ValueError("Invalid private staging directory")
    candidates=list(staging.iterdir())
    if len(candidates)>MAX_STAGE_DIRS:
        raise ValueError("Private day staging directory count exceeds budget")
    found={}
    for folder in candidates:
        if folder.is_symlink():
            raise ValueError("Linked staging directory forbidden")
        if not folder.is_dir():
            continue
        manifest=folder/"manifest.json"
        if manifest.is_symlink():
            raise ValueError("Linked private stage manifest")
        if not manifest.is_file():
            continue
        raw=manifest.read_bytes()
        if len(raw)>100000:
            raise ValueError("Private day staging manifest too large")
        record=json.loads(raw)
        if not isinstance(record,dict):
            raise ValueError("Malformed private stage manifest")
        day=record.get("day")
        if (day in known["expected"]
                and record.get("format")==STAGE.FORMAT
                and record.get("raw_day_report_sha256")==known["source_sha"]
                and record.get("gate_report_sha256")==known["gate_sha"]):
            if day in found:
                raise ValueError("Ambiguous multiple private stages for one audited day")
            # Validate SHA + schema + ALL stock/day keys, no raw prices emitted.
            OVERLAY.inspect_stage(folder,known["expected"],known)
            found[day]=folder.resolve()
    return found


def verify_source_no_changes(root,year,initial):
    current=STAGE.source_file_states(root,year)
    if current!=initial:
        raise ValueError("Original Parquet/H5 source file stats changed")
    return True


def run(root,gate_path,source_path,out,action,allow_private_stage=False):
    safe=output_path(out)
    source_root=Path(root).resolve()
    if (not source_root.is_dir()
            or MODULE.is_relative_to(source_root)
            or action not in ("plan","complete")
            or (action=="complete" and allow_private_stage is not True)
            or (action=="plan" and allow_private_stage)):
        raise ValueError("Explicit private-stage authorization and safe market root required")
    gate=Path(gate_path).resolve()
    source=Path(source_path).resolve()
    known,original_gate=evidence(gate,source)
    expected=known["expected"]
    year=date.fromisoformat(next(iter(expected))).year
    state_before=STAGE.source_file_states(source_root,year)
    selected=existing_stages(known)
    missing={d:expected[d] for d in sorted(expected) if d not in selected}
    newly_staged=[]
    prepared=None
    if action=="complete":
        for day in sorted(missing):
            slug=day.replace("-","")
            folder=OVERLAY.STAGING/("complete-day-"+slug+"-v1")
            if folder.exists() or folder.is_symlink():
                raise ValueError("Untrusted preexisting missing-day stage; no overwrite")
            result=STAGE.stage(source_root,gate,source,
                               date.fromisoformat(day),folder,20000)
            if (result["staged_bars"]!=expected[day]
                    or result["original_market_data_modified"] is not False
                    or result["purchased_parquet_overwritten"] is not False):
                raise ValueError("New full-market staged day failed provenance checks")
            newly_staged.append(day)
            verify_source_no_changes(source_root,year,state_before)
        selected=existing_stages(known)
        if set(selected)!=set(expected):
            raise ValueError("All audited full-market missing days not staged")
        all_dirs=[selected[d] for d in sorted(expected)]
        ordered=OVERLAY.validate_stages(all_dirs,known)
        if sum(row["rows"] for row in ordered)!=sum(expected.values()):
            raise ValueError("Unexpected H5-only full-day private partition count")
        verify_source_no_changes(source_root,year,state_before)
        prepared=OVERLAY.prepare(source_root,gate,source,all_dirs)
        if (prepared["private_rows"]!=sum(expected.values())
                or prepared["prepared_days"]!=sorted(expected)
                or prepared["production_query_route_modified"] is not False):
            raise ValueError("Prepared immutable overlay did not cover all audited dates")
        # Guarantee no private pointer was changed as a side effect.
        entry=OVERLAY.load_version(prepared["version_sha256"])
        if (entry["rows_in_overlay"]!=sum(expected.values())
                or len(entry["stages"])!=len(expected)
                or entry["source_parquet_priority"] is not True
                or entry["purchased_historical_parquet_modified"] is not False
                or entry["h5_market_files_modified"] is not False):
            raise ValueError("Prepared all-market version failed read-back")
    verify_source_no_changes(source_root,year,state_before)
    # SAFE is counts/hashes only; real licensed bars remain in ignored work.
    summary={
        "format":FORMAT,
        "status":("all_audited_h5_only_day_parquet_partitions_prepared_not_activated"
                  if prepared else "full_market_h5_only_day_private_staging_plan"),
        "action":action,
        "audited_year":year,
        "audited_window":original_gate["audited_window"],
        "audited_complete_h5_only_days":len(expected),
        "audited_complete_h5_only_day_rows":sum(expected.values()),
        "date_counts":[{"date":d,"audited_h5_only_rows":expected[d],
                        "private_stage_available":d in selected}
                       for d in sorted(expected)],
        "existing_private_staged_days_before_action":len(expected)-len(missing),
        "staged_new_private_days_this_action":newly_staged,
        "missing_private_stage_dates":(
            [d for d in sorted(expected) if d not in selected]),
        "source_report_sha256":known["source_sha"],
        "gate_report_sha256":known["gate_sha"],
        "prepared_immutable_overlay_sha256":(
            prepared["version_sha256"] if prepared else None),
        "source_precedence":"purchased_parquet_existing_stockday_wins",
        "purchased_original_files_left_read_only":True,
        "historical_audit_says_full_dates_have_no_purchased_keys":True,
        "live_whole_day_absence_rechecked_during_action":action=="complete",
        "all_mixed_date_stockday_gaps_zero_required":True,
        "new_stages_always_separate_private_parquet":True,
        "private_active_pointer_changed":False,
        "h5_native_mirror_created":False,
        "h5_volume_amount_candidate_not_supplier_certified":True,
        "ready_for_production_h5_mirror":False,
        "minute_periods_not_yet_reconciled_by_this_day_flow":True,
        "original_market_files_modified":False,
        "production_query_route_modified":False,
        "no_raw_ohlcva_or_stock_codes_in_safe":True,
    }
    # Check again before writing the only reports/ artifact.
    verify_source_no_changes(source_root,year,state_before)
    with safe.open("x",encoding="utf-8") as stream:
        json.dump(summary,stream,sort_keys=True,ensure_ascii=False,indent=2)
        stream.write("\n")
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--gate-report",type=Path,required=True)
    p.add_argument("--source-report",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--action",choices=("plan","complete"),required=True)
    p.add_argument("--allow-new-private-parquet-stages",action="store_true")
    p.add_argument("--original-sources-read-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=run(a.root,a.gate_report,a.source_report,a.out,
                   a.action,a.allow_new_private_parquet_stages)
        print("SAFE full-market H5-only day Parquet completion:",a.out)
        print("Audited full dates:",result["audited_complete_h5_only_days"])
        print("Audited H5 missing day rows:",result["audited_complete_h5_only_day_rows"])
        print("New private dates staged:",len(result["staged_new_private_days_this_action"]))
        print("Prepared immutable version:",result["prepared_immutable_overlay_sha256"])
        print("Purchased originals / H5 sources / private pointer modified: NO")
        print("This day-only stage is NOT complete across 1min, 5min or original H5 mirror.")
    except (ValueError,OSError,TypeError,KeyError,OverflowError,
            ImportError,ModuleNotFoundError):
        p.error("All-day private Parquet completion rejected; no original source writes")


if __name__=="__main__":
    main()
