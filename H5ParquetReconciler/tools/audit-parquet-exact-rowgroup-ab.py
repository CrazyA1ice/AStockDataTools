#!/usr/bin/env python3
"""Offline, aggregate-only audit of full-first and restricted-first exact-RG A/B.

Never reads H5/Parquet, private cache or OHLCVA. Report input/output must live
under this module's reports/. Requires identical stat-only manifest, full
per-run parity, opposite engine orders, and candidate census before describing
timings. Payback query counts assume constant measured savings and no locator
rebuild; they are projections, not proven production performance.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "rg_reuse_audit_validation",HERE/"benchmark-parquet-exact-rowgroup-reuse.py")
v=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)
FORMAT="AStockDataTools exact 5min RowGroup reuse A/B v1"


def read_report(path):
    target=v.report_path(path)
    if target.stat().st_size>131072:
        raise ValueError("A/B report exceeds 128KiB limit")
    with target.open("r",encoding="utf-8") as handle:
        result=json.load(handle,parse_constant=lambda c: (_ for _ in ()).throw(
            ValueError("Invalid NaN/Infinity in report")))
    if type(result) is not dict:
        raise ValueError("A/B report must be JSON object")
    return result


def number(value,key,positive=True):
    if (type(value) not in (int,float) or not math.isfinite(value)
            or (value<=0 if positive else value<0)):
        raise ValueError("Invalid numerical "+key)
    return value


def count(value,key):
    if type(value) is not int or value<0:
        raise ValueError("Invalid count "+key)
    return value


def check(report,order):
    if report.get("format")!=FORMAT or report.get("requested_execution_order")!=order:
        raise ValueError("Invalid order or A/B report type")
    for k in ("source_stat_stable_during_comparison",
              "all_output_ohlcva_time_and_provenance_identical",
              "locator_key_count_and_group_membership_crosschecked_with_full_source",
              "legacy_rowgroup_exact_equality_verified_this_run",
              "source_stat_only_not_content_hash",
              "locator_build_cost_not_included_in_engine_comparison",
              "net_end_to_end_speedup_including_locator_creation_not_proven",
              "physical_parquet_io_saved_unknown",
              "not_production_pruning",
              "local_private_cache_not_used"):
        if report.get(k) is not True:
            raise ValueError("Missing required full-parity/caveat flag: "+k)
    for k in ("paid_ohlcva_exported","h5_source_accessed",
              "source_market_files_modified","automatic_source_union_or_import_performed"):
        if report.get(k) is not False:
            raise ValueError("Unexpected unsafe or modified source: "+k)
    if not (type(report.get("source_stat_manifest_sha256")) is str
            and len(report["source_stat_manifest_sha256"])==64
            and all(c in "0123456789abcdef" for c in report["source_stat_manifest_sha256"])):
        raise ValueError("Invalid source stat manifest")
    if (report.get("period")!="5min"
            or type(report.get("symbol")) is not str
            or type(report.get("date")) is not str):
        raise ValueError("Missing query identity")
    for k in ("matching_bar_count","full_footer_candidate_row_groups",
              "restricted_row_groups_actually_scanned",
              "row_groups_not_read_in_restricted_scan",
              "original_preflight_rows_upper_bound",
              "restricted_rowgroup_source_rows_upper_bound",
              "source_stat_manifest_file_count"):
        count(report.get(k),k)
    if (report["full_footer_candidate_row_groups"] !=
            report["restricted_row_groups_actually_scanned"]+
            report["row_groups_not_read_in_restricted_scan"] or
            report["restricted_rowgroup_source_rows_upper_bound"]>
            report["original_preflight_rows_upper_bound"]):
        raise ValueError("RowGroup membership or source budget census inconsistent")
    build=number(report.get("key_only_locator_build_seconds_from_prior_report"),
                 "key_only_locator_build_seconds_from_prior_report",positive=False)
    old=number(report.get("full_arrow_seconds"),"full_arrow_seconds")
    new=number(report.get("restricted_arrow_seconds"),"restricted_arrow_seconds")
    ratio=number(report.get("full_over_restricted_ratio"),"full_over_restricted_ratio")
    if abs(ratio-old/new)>0.00002:
        raise ValueError("Incorrect claimed speedup ratio")
    number(report.get("total_wall_seconds_including_all_parity_scans"),
           "total_wall_seconds_including_all_parity_scans")
    legacy=number(report.get("legacy_rowgroup_seconds_if_verified"),
                  "legacy_rowgroup_seconds_if_verified")
    if report["total_wall_seconds_including_all_parity_scans"]+0.00001 < old+new:
        raise ValueError("Total wall time smaller than engine portions")
    return build,old,new,legacy


def compare(full_first,restricted_first):
    rounds=(("full-first",full_first),("restricted-first",restricted_first))
    checked=[check(entry,order) for order,entry in rounds]
    identical=(
        "symbol","date","period","matching_bar_count",
        "full_footer_candidate_row_groups","restricted_row_groups_actually_scanned",
        "row_groups_not_read_in_restricted_scan",
        "original_preflight_rows_upper_bound",
        "restricted_rowgroup_source_rows_upper_bound",
        "source_stat_manifest_sha256","source_stat_manifest_file_count",
        "key_only_locator_build_seconds_from_prior_report",
    )
    if any(full_first[k]!=restricted_first[k] for k in identical):
        raise ValueError("Opposite order reports differ in query/source/locator identity")
    if (full_first["matching_bar_count"] == 0
            or full_first["full_footer_candidate_row_groups"]==0
            or full_first["row_groups_not_read_in_restricted_scan"]==0):
        raise ValueError("No useful nonempty exact-locator experiment")
    build=checked[0][0]
    records=[]
    all_faster=True
    paybacks=[]
    for (order,unused),(other_build,old,new,legacy) in zip(rounds,checked):
        savings=old-new
        faster=savings>0
        all_faster &= faster
        minimum_reuses=math.floor(build/savings)+1 if faster else None
        if minimum_reuses is not None:
            paybacks.append(minimum_reuses)
        records.append({
            "order":order,
            "full_arrow_seconds":old,
            "restricted_arrow_seconds":new,
            "full_over_restricted_ratio":round(old/new,6),
            "per_query_savings_seconds_observed":round(savings,6),
            "simple_build_cost_break_even_query_count":minimum_reuses,
            "reference_legacy_rowgroup_seconds":legacy,
        })
    return {
        "format":"AStockDataTools exact 5min RowGroup reuse offline reversed-order audit v1",
        "symbol":full_first["symbol"],
        "date":full_first["date"],"period":"5min",
        "matching_bar_count":full_first["matching_bar_count"],
        "full_candidate_row_groups":full_first["full_footer_candidate_row_groups"],
        "exact_selected_row_groups":full_first["restricted_row_groups_actually_scanned"],
        "omitted_unrelated_groups":full_first["row_groups_not_read_in_restricted_scan"],
        "original_rowgroup_row_upper_bound":full_first["original_preflight_rows_upper_bound"],
        "selected_rowgroup_row_upper_bound":full_first["restricted_rowgroup_source_rows_upper_bound"],
        "stat_manifest_sha256":full_first["source_stat_manifest_sha256"],
        "source_stat_only_not_content_hash":True,
        "per_order_measurements":records,
        "observation":("restricted_faster_both_orders" if all_faster
                       else "not_faster_both_orders"),
        "simple_locator_creation_seconds":build,
        "simple_break_even_query_count_range_if_both_faster":(
            [min(paybacks),max(paybacks)] if all_faster else None),
        "break_even_is_scenario_only_not_realized_savings":True,
        "all_reports_claim_full_arrow_and_legacy_parity":True,
        "paid_ohlcva_or_private_cache_exported":False,
        "source_market_files_modified":False,
        "source_scans_or_import_performed_by_this_audit":False,
        "production_default_engine_unchanged":True,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--full-first",type=Path,required=True)
    p.add_argument("--restricted-first",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        first=v.report_path(args.full_first)
        second=v.report_path(args.restricted_first)
        out=v.report_path(args.out,new_output=True)
        if len({first,second,out})!=3:
            raise ValueError("Input reports and output must be distinct")
        result=compare(read_report(first),read_report(second))
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as handle:
            json.dump(result,handle,indent=2,ensure_ascii=False,allow_nan=False)
            handle.write("\n")
        print("Saved offline exact RowGroup reuse audit:",out)
        print("Observation:",result["observation"])
        print("Simple payback query-count scenario:",
              result["simple_break_even_query_count_range_if_both_faster"])
    except (ValueError,TypeError,OSError,OverflowError,
            json.JSONDecodeError) as error:
        p.error(str(error))


if __name__=="__main__":
    main()
