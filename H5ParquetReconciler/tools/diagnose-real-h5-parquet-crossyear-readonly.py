#!/usr/bin/env python3
"""Privacy-safe read-only stage diagnosis for the fixed 2025/2026 day probe.

Bounded only to the SAME 2025-09-30 and 2026-08-24 two-symbol samples.
Does not rewrite the normal probe, run native C++, or change limits. This
diagnostic emits fixed enum phases and annual footer COUNTS, never exception
strings, local paths, OHLCVA, source timestamps, symbols, or HMAC values.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "real_h5_parquet_crossyear_diagnostic_target",
    HERE/"probe-real-h5-parquet-crossyear-day-readonly.py")
T=importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
AUDIT=T.AUDIT

FORMAT="AStockDataTools read-only crossyear daily bounded stage diagnostic v1"
STAGES=frozenset((
    "prior_safe_chain","source_file_selection","original_h5_source_check",
    "pyarrow_h5_read_libraries","annual_footer_file","annual_footer_schema",
    "annual_footer_group_budget","annual_footer_timestamp_statistics",
    "annual_target_rowgroup_selection","annual_target_row_budget",
    "annual_bounded_day_read","annual_target_original_h5_read",
    "monthly_bounded_day_read","monthly_target_original_h5_read",
    "four_pair_candidate_evaluation","source_footer_and_stat_unchanged",
    "completed",
))


class Blocked(Exception):
    """Local control flow only: message never leaves runtime."""


def inspect_annual_footer(path,pa,pq,result):
    """Metadata only: no column page reads, price or user filename exposure."""
    stamp=T.DAY.FOOTER.footer_guard(path)
    pf=None
    try:
        pf=pq.ParquetFile(str(path),memory_map=False,pre_buffer=False)
        schema=pf.schema_arrow
        result["last_stage"]="annual_footer_schema"
        if (not set(T.DAY.NEEDED).issubset(schema.names)
                or len(schema.names)>512
                or not pa.types.is_int64(schema.field("ts").type)
                or not pa.types.is_string(schema.field("symbol").type)
                or any(not pa.types.is_float64(schema.field(field).type)
                       for field in T.DAY.FIELDS)):
            raise Blocked()
        result["last_stage"]="annual_footer_group_budget"
        groups=pf.metadata.num_row_groups
        if not 1<=groups<=T.MAX_YEAR_ROW_GROUPS:
            raise Blocked()
        rows=sum(pf.metadata.row_group(i).num_rows for i in range(groups))
        if not 1<=rows<=T.MAX_YEAR_FOOTER_ROWS:
            raise Blocked()
        result["annual_2025_footer_rowgroup_count"]=groups
        result["annual_2025_footer_total_rows"]=rows
        result["last_stage"]="annual_footer_timestamp_statistics"
        low,high=T.DAY._range_ms("2025-09-30")
        year_low=T.DAY._range_ms("2025-01-01")[0]
        year_high=T.DAY._range_ms("2025-12-31")[1]
        field_idx=schema.names.index("ts")
        selected=[]
        for i in range(groups):
            rg=pf.metadata.row_group(i)
            stats=rg.column(field_idx).statistics
            if (rg.num_rows<1 or stats is None or not stats.has_min_max
                    or type(stats.min) is not int or type(stats.max) is not int
                    or stats.min>stats.max
                    or not year_low<=stats.min<year_high
                    or not year_low<=stats.max<year_high):
                raise Blocked()
            if stats.max>=low and stats.min<high:
                selected.append(i)
        result["annual_2025_candidate_rowgroups"]=len(selected)
        result["last_stage"]="annual_target_rowgroup_selection"
        if not 1<=len(selected)<=T.MAX_YEAR_SELECTED_ROW_GROUPS:
            raise Blocked()
        candidate_rows=sum(pf.metadata.row_group(i).num_rows
                           for i in selected)
        result["annual_2025_candidate_rows"]=candidate_rows
        result["last_stage"]="annual_target_row_budget"
        if not 1<=candidate_rows<=T.MAX_YEAR_READ_ROWS:
            raise Blocked()
    finally:
        if pf is not None:
            pf.close()
        if T.DAY.FOOTER.footer_guard(path)!=stamp:
            result["last_stage"]="source_footer_and_stat_unchanged"
            raise Blocked()


def diagnose(parquet_root,h5_root,raw_safe,native_safe,heldout_safe,out):
    """Generate one NEW SAFE result even when the real source cannot qualify."""
    target=AUDIT._path(out,False)
    report={
        "format":FORMAT,"status":"blocked",
        "last_stage":"prior_safe_chain",
        "stages_completed":[],
        "annual_2025_footer_total_rows":None,
        "annual_2025_footer_rowgroup_count":None,
        "annual_2025_candidate_rowgroups":None,
        "annual_2025_candidate_rows":None,
        "checked_date_count":2,
        "expected_stock_days":4,
        "raw_ohlcva_h5_integers_or_hmac_exported":False,
        "source_paths_or_source_timestamp_values_exported":False,
        "native_hikyuu_cpp_executed":False,
        "source_changes_requested":False,
        "source_files_stat_or_footer_unchanged":False,
        "vendor_physical_units_certified":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
    }
    stage="prior_safe_chain"
    parquet_paths={}
    parquet_before={}
    h5_paths={}
    h5_before={}
    try:
        T.check_calendar()
        T.verified_sources(raw_safe,native_safe,heldout_safe)
        report["stages_completed"].append("prior_safe_chain")
        stage="source_file_selection"
        report["last_stage"]=stage
        parquet_paths={day:T.DAY.FOOTER.selected_file(
            parquet_root,rel,"day") for day,rel in T.SAMPLES}
        if len({p.resolve() for p in parquet_paths.values()})!=2:
            raise Blocked()
        parquet_before={day:T.DAY.FOOTER.footer_guard(p)
                        for day,p in parquet_paths.items()}
        report["stages_completed"].append(stage)
        stage="original_h5_source_check"
        report["last_stage"]=stage
        h5_paths={symbol:T.PAIR._plain_h5_path(h5_root,symbol)
                  for symbol in T.PAIR.SYMBOLS}
        h5_before={symbol:(p.stat().st_size,p.stat().st_mtime_ns)
                   for symbol,p in h5_paths.items()}
        report["stages_completed"].append(stage)
        stage="pyarrow_h5_read_libraries"
        report["last_stage"]=stage
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
        import h5py
        import numpy as np
        report["stages_completed"].append(stage)
        stage="annual_footer_file"
        report["last_stage"]=stage
        inspect_annual_footer(parquet_paths["2025-09-30"],pa,pq,report)
        report["stages_completed"].append(stage)
        stage="annual_bounded_day_read"
        report["last_stage"]=stage
        annual,n,groups,total,ng=T.read_annual_2025_selected_day(
            parquet_paths["2025-09-30"],"2025-09-30",pa,pq,pc)
        if (n!=report["annual_2025_candidate_rows"]
                or groups!=report["annual_2025_candidate_rowgroups"]
                or total!=report["annual_2025_footer_total_rows"]
                or ng!=report["annual_2025_footer_rowgroup_count"]):
            raise Blocked()
        report["stages_completed"].append(stage)
        stage="annual_target_original_h5_read"
        report["last_stage"]=stage
        annual_h5={symbol:T.PAIR._read_single_h5(
            h5_root,symbol,"2025-09-30",h5py,np)
            for symbol in T.PAIR.SYMBOLS}
        report["stages_completed"].append(stage)
        stage="monthly_bounded_day_read"
        report["last_stage"]=stage
        monthly,mn,mg=T.DAY._read_bounded_daily(
            parquet_paths["2026-08-24"],"2026-08-24",pa,pq,pc)
        if n+mn>T.MAX_SCANNED_TOTAL or groups+mg>T.MAX_GROUPS_TOTAL:
            raise Blocked()
        report["stages_completed"].append(stage)
        stage="monthly_target_original_h5_read"
        report["last_stage"]=stage
        monthly_h5={symbol:T.PAIR._read_single_h5(
            h5_root,symbol,"2026-08-24",h5py,np)
            for symbol in T.PAIR.SYMBOLS}
        report["stages_completed"].append(stage)
        stage="four_pair_candidate_evaluation"
        report["last_stage"]=stage
        # Transient actual values are not placed into the diagnostic report.
        T.compare({
            "2025-09-30":{"parquet":annual,"h5":annual_h5},
            "2026-08-24":{"parquet":monthly,"h5":monthly_h5}})
        report["stages_completed"].append(stage)
        report["status"]="ready_to_rerun_original_proof"
        stage="completed"
        report["last_stage"]=stage
    except Exception:
        # IMPORTANT: no exception text, native logs or user paths are emitted.
        if report["last_stage"] not in STAGES:
            report["last_stage"]=stage if stage in STAGES else "prior_safe_chain"
    finally:
        try:
            # A failed preliminary source check means some source stamps
            # were never recorded: do not mistake that for a file mutation,
            # or overwrite the *real* diagnostic stage as "source_changed".
            observed_changed=False
            for day,path in parquet_paths.items():
                if day in parquet_before and T.DAY.FOOTER.footer_guard(
                        path)!=parquet_before[day]:
                    observed_changed=True
            for symbol,path in h5_paths.items():
                if symbol in h5_before and (path.stat().st_size,
                    path.stat().st_mtime_ns)!=h5_before[symbol]:
                    observed_changed=True
            fully_observed=(len(parquet_before)==2 and len(h5_before)==2)
            report["source_files_stat_or_footer_unchanged"]=(
                fully_observed and not observed_changed)
            if observed_changed:
                report["status"]="blocked"
                report["last_stage"]="source_footer_and_stat_unchanged"
        except Exception:
            report["status"]="blocked"
            report["last_stage"]="source_footer_and_stat_unchanged"
            report["source_files_stat_or_footer_unchanged"]=False
        # Never overwrite or write outside module reports.
        with target.open("x",encoding="utf-8") as file:
            json.dump(report,file,ensure_ascii=False,indent=2,sort_keys=True)
            file.write("\n")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parquet-root",required=True,type=Path)
    p.add_argument("--h5-root",required=True,type=Path)
    p.add_argument("--prior-raw-safe",required=True,type=Path)
    p.add_argument("--prior-native-safe",required=True,type=Path)
    p.add_argument("--prior-heldout-safe",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--diagnose-read-only-crossyear",required=True,
                   action="store_true")
    args=p.parse_args(argv)
    try:
        result=diagnose(args.parquet_root,args.h5_root,args.prior_raw_safe,
                        args.prior_native_safe,args.prior_heldout_safe,args.out)
    except Exception:
        p.error("Cannot safely generate bounded crossyear diagnostic")
    print("Diagnostic SAFE:",args.out)
    print("Status:",result["status"])
    print("Fixed failure phase:",result["last_stage"])
    print("Original market files were not modified by this diagnostic.")
    print("Production mapping and vendor units remain UNVERIFIED.")


if __name__=="__main__":
    main()
