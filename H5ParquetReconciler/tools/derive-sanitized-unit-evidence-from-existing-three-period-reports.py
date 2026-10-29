#!/usr/bin/env python3
"""Reduce existing read-only three-period conservation JSON to sanitized evidence.

NO market source reading. Accept only already-generated JSON directly inside
H5ParquetReconciler/reports/. Schema, time zone, physical units, and adjustment
are UNKNOWN unless independently established; do not invent them.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
TOOLS=Path(__file__).resolve().parent
SOURCE_FORMAT="AStockDataTools Parquet three-period full-day conservation v1"
SPEC=importlib.util.spec_from_file_location(
    "strict_sanitized_unit_evidence",
    TOOLS/"audit-sanitized-parquet-h5-unit-evidence.py")
AUDIT=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
SYMBOLS=("SH600000","SZ000001")
PERIODS=("day","5min","1min")
SCHEMA_UNKNOWN={
    "date_type":"unknown",
    "price_type":"unknown",
    "amount_type":"unknown",
    "volume_type":"unknown",
    "timezone":"unknown",
    "amount_unit_declared":"unknown",
    "volume_unit_declared":"unknown",
}


def _small_decimal(x):
    """Accept JSON numeric Decimal ratios, not float maths or raw OHLC."""
    if type(x) not in (Decimal,int):
        raise ValueError("Missing numeric aggregate ratio in existing report")
    d=Decimal(x)
    if not d.is_finite() or d<0 or d>2:
        raise ValueError("Invalid aggregate ratio")
    gap=abs(Decimal(1)-d)
    if gap>1:
        raise ValueError("Aggregate ratio is too far from unity")
    # All real reports are rounded JSON ratios. Preserve only their
    # literal precision: never advertise raw-market exact arithmetic.
    literal=format(gap,"f")
    if len(literal.split(".")[-1])>12 and "." in literal:
        raise ValueError("Existing ratio precision exceeds safe intake contract")
    return literal


def _strict_int(value,lo,hi):
    if type(value) is not int or not lo<=value<=hi:
        raise ValueError("Unexpected report bar count")
    return value


def _window(symbol,date,entry,period_info,report):
    if type(entry) is not dict:
        raise ValueError("Missing existing stock-day summary")
    quality=entry.get("day_quality")
    day_present=(entry.get("day_bar_present") is True
                 and type(quality) is dict
                 and quality.get("day_bar_found") is True
                 and quality.get("quality_issues")==[])
    rows5=_strict_int(entry.get("parquet_5min_rows"),0,60)
    rows1=_strict_int(entry.get("parquet_1min_rows"),0,300)
    valid_grid=(entry.get("one_minute_missing_expected_stamps")==0
                and entry.get("one_minute_outside_expected_grid")==0
                and entry.get("five_minute_missing_expected_stamps")==0
                and entry.get("five_minute_outside_expected_grid")==0
                and entry.get("one_to_five_opening_rule_strict_48_of_48") is True
                and rows1==report.get("expected_regular_1min_count_with_opening_0930")
                and rows5==report.get("expected_regular_5min_count"))
    comparisons={}
    for period in ("5min","1min"):
        match=entry.get("day_vs_"+period)
        if type(match) is not dict:
            raise ValueError("Existing day-vs-minute aggregate comparison missing")
        ratios=match.get("relative_ratio_day_over_intraday")
        if type(ratios) is not dict or set(ratios)!={"amount","volume"}:
            raise ValueError("Missing existing amount and volume ratios")
        comparisons[period]=(
            match.get("comparable") is True,
            match.get("strict_ohlc_agree") is True,
            _small_decimal(ratios["amount"]),
            _small_decimal(ratios["volume"]),
        )
    all_compared=all(c and o for c,o,_,_ in comparisons.values())
    grids=all(period_info[k].get("parquet_schema_checked") is True
              and period_info[k].get("duplicate_keys")==0
              and period_info[k].get("nonfinite_source_rows")==0
              and period_info[k].get("invalid_timestamp_rows")==0
              for k in PERIODS)
    # 'closed_session' requires an independent market-session provenance,
    # missing in these reports. Even when we found a day bar, NO proof of
    # normalization/adjustment basis exists. Therefore do not infer True.
    return {
        "symbol":symbol,
        "date":date,
        "day_rows":1 if day_present else 0,
        "min5_rows":rows5,
        "min1_rows":rows1,
        "closed_session":False,
        "time_grid_checked":bool(valid_grid and grids and all_compared),
        "same_adjustment_basis":False,
        "day_vs_5min_amount_relative_gap":comparisons["5min"][2],
        "day_vs_1min_amount_relative_gap":comparisons["1min"][2],
        "day_vs_5min_volume_relative_gap":comparisons["5min"][3],
        "day_vs_1min_volume_relative_gap":comparisons["1min"][3],
    }


def convert(reports):
    if type(reports) not in (list,tuple) or len(reports)!=2:
        raise ValueError("Exactly two distinct preexisting report dates required")
    windows=[]
    dates=set()
    for doc in reports:
        if (type(doc) is not dict or doc.get("format")!=SOURCE_FORMAT
                or type(doc.get("date")) is not str
                or type(doc.get("read_cost_by_period")) is not dict
                or type(doc.get("stock_day_results")) is not dict
                or type(doc.get("selected_symbols")) is not list):
            raise ValueError("Not a known three-period conservation report")
        date=doc["date"]
        if date in dates:
            raise ValueError("Expected two distinct stock dates")
        dates.add(date)
        if (not set(SYMBOLS).issubset(doc["selected_symbols"])
                or not set(PERIODS).issubset(doc["read_cost_by_period"])):
            raise ValueError("Missing required securities/periods in old report")
        for symbol in SYMBOLS:
            windows.append(_window(
                symbol,date,doc["stock_day_results"].get(symbol),
                doc["read_cost_by_period"],doc))
    sanitized={
        "format":AUDIT.FORMAT,
        "sanitized_aggregates_only":True,
        "no_raw_market_rows":True,
        "independent_unit_reference":"none",
        "schemas":{k:dict(SCHEMA_UNKNOWN) for k in PERIODS},
        "windows":windows,
    }
    # Self-validating: cannot produce a document rejected by the downstream
    # strict report auditor. It correctly remains NOT READY when independent
    # physical-unit/schema/adjustment evidence is missing.
    assessment=AUDIT.check_evidence(sanitized)
    if (assessment["licensed_parquet_to_h5_mapping_certified"]
            or assessment["ready_for_full_market_mirror"]
            or assessment["ready_to_plan_independent_unit_check"]):
        raise ValueError("Old reports unexpectedly promoted unknown physical units")
    return sanitized,assessment


def derive(first,second,output,assessment_path):
    sources=[AUDIT._path(p,True) for p in (first,second)]
    if sources[0].resolve()==sources[1].resolve():
        raise ValueError("Distinct existing reports required")
    dest=AUDIT._path(output,False)
    assess_dest=AUDIT._path(assessment_path,False)
    if dest.resolve()==assess_dest.resolve():
        raise ValueError("Two distinct new report filenames required")
    reports=[]
    for source in sources:
        # Decimal parses the *printed* JSON ratios, not raw source market
        # values. This distinction matters for small aggregate discrepancies.
        reports.append(json.loads(source.read_text(encoding="utf-8"),
                                  parse_float=Decimal))
    sanitized,assessment=convert(reports)
    # Write only two new, fixed-contract, sanitized JSON reports.
    with dest.open("x",encoding="utf-8") as out:
        json.dump(sanitized,out,indent=2,ensure_ascii=False)
        out.write("\n")
    with assess_dest.open("x",encoding="utf-8") as out:
        json.dump(assessment,out,indent=2,ensure_ascii=False)
        out.write("\n")
    return assessment


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--existing-report-a",type=Path,required=True)
    p.add_argument("--existing-report-b",type=Path,required=True)
    p.add_argument("--sanitized-out",type=Path,required=True)
    p.add_argument("--assessment-out",type=Path,required=True)
    p.add_argument("--offline-existing-reports-only",action="store_true",
                   required=True)
    args=p.parse_args(argv)
    try:
        result=derive(args.existing_report_a,args.existing_report_b,
                      args.sanitized_out,args.assessment_out)
        print("SAFE sanitized windows:",result["observed_window_count"])
        print("Independent unit check ready:",
              result["ready_to_plan_independent_unit_check"])
        print("Still missing:",", ".join(result["evidence_blockers"]))
        print("Market source files opened: NO")
    except (ValueError,KeyError,OSError,TypeError,InvalidOperation) as e:
        p.error(str(e))


if __name__=="__main__":
    main()
