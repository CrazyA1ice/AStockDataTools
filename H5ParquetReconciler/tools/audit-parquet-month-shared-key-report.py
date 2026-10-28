#!/usr/bin/env python3
"""Offline integrity/consistency audit of bounded multisymbol month key reports.

This tool never opens purchased Parquet, H5, the OHLCVA cache, or source files.
It cannot certify that the user-editable report is genuine or current.
Produces a small aggregate-only audit under this module's reports/ folder.
Optional --single-day-report strictly compares every RowGroup locator/count
for the day against a previous independent single-day shared key-only report.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path, PurePosixPath

MODULE=Path(__file__).resolve().parent.parent
REPORTS=(MODULE/"reports").resolve()
MONTH_FORMAT="AStockDataTools bounded monthly multisymbol 5min key-only locator pilot v1"
DAY_FORMAT="AStockDataTools shared 5min single-day multiple-symbol key-only RowGroup plan v1"
AUDIT_FORMAT="AStockDataTools offline monthly multisymbol 5min key evidence audit v1"


def located_report(path, *, create=False):
    supplied=Path(path)
    candidate=supplied if supplied.is_absolute() else MODULE/supplied
    target=candidate.resolve()
    if (candidate.is_symlink() or not target.is_relative_to(REPORTS)
            or target.suffix.lower()!=".json"):
        raise ValueError("Only JSON within H5ParquetReconciler/reports allowed")
    if create and target.exists():
        raise ValueError("Existing reports may not be overwritten")
    if not create and not target.is_file():
        raise ValueError("Required input report is absent")
    return target


def read_json(path):
    loc=located_report(path)
    if loc.stat().st_size>3*1024*1024:
        raise ValueError("Report exceeds bounded 3 MiB input size")
    with loc.open("r",encoding="utf-8") as handle:
        data=json.load(handle,parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError("Nonfinite JSON constant is forbidden")))
    if type(data) is not dict:
        raise ValueError("Report must be one JSON object")
    return data


def integral(record,key,*,minimum=0):
    value=record.get(key)
    if type(value) is not int or value<minimum:
        raise ValueError("Bad bounded integer: "+key)
    return value


def elapsed(record,key):
    value=record.get(key)
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise ValueError("Bad nonnegative elapsed seconds: "+key)
    return float(value)


def source_fingerprint(report):
    value=report.get("source_stat_manifest_sha256")
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}",value):
        raise ValueError("Bad source stat-only fingerprint")
    integral(report,"source_stat_manifest_file_count",minimum=1)
    return value


def entries(entry):
    values=entry.get("nonempty_row_group_locators")
    if type(values) is not list:
        raise ValueError("Missing RowGroup locator list")
    group_count=integral(entry,"exact_row_groups_containing_keys")
    total=integral(entry,"matching_source_keys")
    if len(values)!=group_count:
        raise ValueError("Exact nonempty RowGroup count does not match locators")
    found={}
    for item in values:
        if type(item) is not dict:
            raise ValueError("Malformed RowGroup locator")
        name=item.get("source_file_relative_path")
        if (type(name) is not str or not name.startswith("AllCycleAStockData/5min/")
                or "\\" in name or PurePosixPath(name).is_absolute()
                or ".." in PurePosixPath(name).parts
                or PurePosixPath(name).suffix.lower()!=".parquet"):
            raise ValueError("Unsafe RowGroup source relative path")
        group=integral(item,"row_group")
        number=integral(item,"matching_key_count",minimum=1)
        key=(name,group)
        if key in found:
            raise ValueError("Duplicate RowGroup membership")
        found[key]=number
    if sum(found.values())!=total:
        raise ValueError("RowGroup matching key count conservation failed")
    return found


def audit(report, single_day=None):
    if report.get("format")!=MONTH_FORMAT or report.get("period")!="5min":
        raise ValueError("Invalid monthly report format/period")
    for key in ("source_stat_manifest_stable_during_scan",
                "source_manifest_stat_only_not_content_sha256",
                "all_union_footer_candidate_groups_key_columns_scanned",
                "only_ts_and_symbol_columns_read",
                "all_parquet_readers_explicitly_closed",
                "physical_disk_bytes_read_or_saved_unknown",
                "net_end_to_end_query_speedup_not_measured",
                "locator_unsigned_not_trusted_for_production",
                "production_default_engine_unchanged",
                "no_raw_ohlcva_or_individual_intraday_time_keys_exported"):
        if report.get(key) is not True:
            raise ValueError("Required evidence/caveat flag missing: "+key)
    # These provenance fields have opposite polarities by design:
    # "no_h5_read": True means the planner did NOT access H5;
    # the two action flags below must be False. Keep explicit expectations
    # so a correctly generated, read-only report is never rejected.
    if report.get("no_h5_read") is not True:
        raise ValueError("Expected no_h5_read=true (H5 was not accessed)")
    for key in ("source_market_files_modified",
                "automatic_source_union_or_import_performed"):
        if report.get(key) is not False:
            raise ValueError("Unexpected source modification or import: "+key)
    signature=source_fingerprint(report)
    try:
        first=date.fromisoformat(report["from_date"])
        last=date.fromisoformat(report["to_date"])
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError("Invalid month date window") from exc
    if (first>last or first.year!=last.year or first.month!=last.month
            or (last-first).days>=31):
        raise ValueError("Window must be within one month")
    days=[(first+timedelta(days=i)).isoformat()
          for i in range((last-first).days+1)]
    if integral(report,"requested_calendar_days")!=len(days):
        raise ValueError("Calendar day count mismatch")
    stocks=report.get("per_symbol")
    rows=report.get("per_symbol_day")
    if type(stocks) is not list or not 2<=len(stocks)<=8:
        raise ValueError("Stock list must contain 2..8 elements")
    if type(rows) is not list or len(rows)>248:
        raise ValueError("Invalid bounded stock-day rows")
    symbols=[]
    by_symbol={}
    for item in stocks:
        if type(item) is not dict or type(item.get("symbol")) is not str:
            raise ValueError("Bad per-symbol record")
        s=item["symbol"]
        if not re.fullmatch(r"(?:SH|SZ|BJ)[0-9]{6}",s) or s in by_symbol:
            raise ValueError("Invalid or repeated symbol")
        symbols.append(s)
        by_symbol[s]=item
        integral(item,"independent_footer_candidate_row_groups")
        integral(item,"independent_footer_candidate_source_rows_upper_bound")
        integral(item,"matching_source_keys_all_days")
    if symbols!=sorted(symbols):
        raise ValueError("Symbol ordering is not canonical")
    if (integral(report,"requested_distinct_symbol_count")!=len(symbols)
            or integral(report,"requested_symbol_day_count")
               !=len(symbols)*len(days)
            or len(rows)!=len(symbols)*len(days)):
        raise ValueError("Stock-day census mismatch")
    union=integral(report,"union_footer_candidate_row_groups")
    limit=integral(report,"union_footer_candidate_source_rows_upper_bound")
    scanned=integral(report,"union_source_key_rows_examined_once")
    independent=integral(
        report,"sum_of_independent_symbol_footer_row_upper_bounds")
    theoretical=integral(report,"theoretical_rows_avoided_vs_independent_symbol_scans")
    if (scanned!=limit or limit>independent or independent-limit!=theoretical
            or union<0):
        raise ValueError("Full candidate key scan source-row conservation failed")
    if sum(integral(item,"independent_footer_candidate_source_rows_upper_bound")
           for item in stocks)!=independent:
        raise ValueError("Independent symbol footer sums are inconsistent")
    integral(report,"source_file_footers_opened_once",minimum=1)
    elapsed(report,"one_pass_key_scan_seconds")
    elapsed(report,"whole_planning_seconds")
    if report["whole_planning_seconds"]+0.00001 < report["one_pass_key_scan_seconds"]:
        raise ValueError("Whole planning time cannot be shorter than scan")
    by_day={}
    monthly_groups={s:set() for s in symbols}
    entries_by_stock=Counter()
    totals=Counter()
    globally=set()
    for row in rows:
        if type(row) is not dict:
            raise ValueError("Bad stock-day row")
        pair=(row.get("symbol"),row.get("date"))
        if pair in by_day or pair[0] not in by_symbol or pair[1] not in days:
            raise ValueError("Duplicate or foreign stock-day")
        group=entries(row)
        by_day[pair]=group
        totals[pair[0]]+=row["matching_source_keys"]
        entries_by_stock[pair[0]]+=len(group)
        monthly_groups[pair[0]].update(group)
        globally.update(group)
    if (set(by_day)!={(s,d) for s in symbols for d in days}
            or len(globally)>union):
        raise ValueError("Incomplete/foreign RowGroup stock-day coverage")
    if sum(totals.values())!=integral(report,"matching_keys_all_stock_days"):
        raise ValueError("Global key count conservation failed")
    for s in symbols:
        item=by_symbol[s]
        if totals[s]!=item["matching_source_keys_all_days"]:
            raise ValueError("Stock monthly key count conservation failed: "+s)
        if len(monthly_groups[s])>item["independent_footer_candidate_row_groups"]:
            raise ValueError("Stock has keys outside independent Footer candidates")

    checked=None
    if single_day is not None:
        if (type(single_day) is not dict or single_day.get("format")!=DAY_FORMAT
                or single_day.get("period")!="5min"):
            raise ValueError("Wrong single-day reference format")
        day=single_day.get("date")
        if day not in days:
            raise ValueError("Reference day outside month")
        if (single_day.get("source_stat_manifest_sha256")!=signature
                or single_day.get("source_stat_manifest_file_count")!=
                   report["source_stat_manifest_file_count"]):
            raise ValueError("Single-day reference source stat mismatch")
        day_stocks=single_day.get("per_symbol")
        if type(day_stocks) is not list or len(day_stocks)!=len(symbols):
            raise ValueError("Reference has different stock population")
        reference=set()
        for record in day_stocks:
            if type(record) is not dict or record.get("symbol") not in by_symbol:
                raise ValueError("Reference has unexpected symbol")
            sym=record["symbol"]
            if sym in reference:
                raise ValueError("Reference has repeated symbol")
            reference.add(sym)
            if (integral(record,"matching_source_keys")!=
                    sum(by_day[(sym,day)].values())
                    or entries(record)!=by_day[(sym,day)]):
                raise ValueError("Monthly vs single-day RowGroup locator mismatch: "+sym)
        checked=day

    per_stock=[]
    zero_sets=[]
    for s in symbols:
        zero_dates=[d for d in days if not by_day[(s,d)]]
        zero_sets.append(set(zero_dates))
        active=[d for d in days if by_day[(s,d)]]
        non48=[{"date":d,"matching_keys":sum(by_day[(s,d)].values())}
               for d in active if sum(by_day[(s,d)].values())!=48]
        groups=[len(by_day[(s,d)]) for d in active]
        per_stock.append({
            "symbol":s,
            "total_matching_keys":totals[s],
            "nonempty_days":len(active),
            "zero_key_days":len(zero_dates),
            "zero_key_dates":zero_dates,
            "nonzero_non48_key_days":non48,
            "unique_row_groups_with_keys_across_month":len(monthly_groups[s]),
            "row_group_locator_entries_in_month":entries_by_stock[s],
            "min_nonempty_day_row_groups":min(groups) if groups else None,
            "max_nonempty_day_row_groups":max(groups) if groups else None,
            "mean_nonempty_day_row_groups":(
                round(sum(groups)/len(groups),6) if groups else None),
        })
    return {
        "format":AUDIT_FORMAT,
        "from_date":first.isoformat(),"to_date":last.isoformat(),
        "period":"5min",
        "number_of_symbols":len(symbols),
        "requested_calendar_days":len(days),
        "number_of_stock_days":len(rows),
        "matching_keys_all_stock_days":sum(totals.values()),
        "source_row_group_candidate_union_count":union,
        "month_unique_row_groups_with_any_selected_keys":len(globally),
        "monthly_full_union_key_rows_examined_once":scanned,
        "theoretical_rowgroup_rows_avoided_vs_separate_symbol_scans":theoretical,
        "per_stock":per_stock,
        "all_stocks_share_same_zero_key_dates":all(
            zero_sets[0]==x for x in zero_sets[1:]),
        "zero_key_dates_common_to_all_stocks":sorted(
            set.intersection(*zero_sets)),
        "total_nonempty_stock_days":sum(x["nonempty_days"] for x in per_stock),
        "total_row_group_locator_entries":sum(entries_by_stock.values()),
        "single_day_reference_exact_membership_verified":checked is not None,
        "reference_day_if_verified":checked,
        "original_month_plan_wall_seconds":elapsed(
            report,"whole_planning_seconds"),
        "original_month_two_column_scan_seconds":elapsed(
            report,"one_pass_key_scan_seconds"),
        "source_stat_manifest_sha256":signature,
        "source_stat_is_not_content_hash":True,
        "offline_report_self_consistency_verified":True,
        "not_original_market_source_verified_by_this_audit":True,
        "row_group_locators_unsigned_not_for_unattended_production":True,
        "source_market_files_accessed_by_this_audit":False,
        "paid_ohlcva_or_intraday_keys_exported":False,
        "source_market_files_modified":False,
        "production_query_or_index_changed":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month-report",type=Path,required=True)
    parser.add_argument("--single-day-report",type=Path)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--read-only",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        month=located_report(args.month_report)
        day=(located_report(args.single_day_report)
             if args.single_day_report else None)
        output=located_report(args.out,create=True)
        if output in (month,day):
            raise ValueError("Output must be distinct from all inputs")
        result=audit(read_json(month),read_json(day) if day else None)
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open("x",encoding="utf-8") as handle:
            json.dump(result,handle,indent=2,ensure_ascii=False,allow_nan=False)
            handle.write("\n")
        print("Saved aggregate-only monthly key report audit:",output)
        print("Stock-days:",result["number_of_stock_days"],
              "selected keys:",result["matching_keys_all_stock_days"],
              "reference crosscheck:",result[
                  "single_day_reference_exact_membership_verified"])
        print("This is offline self-consistency, NOT source authentication.")
    except (ValueError,TypeError,OSError,OverflowError,
            json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
