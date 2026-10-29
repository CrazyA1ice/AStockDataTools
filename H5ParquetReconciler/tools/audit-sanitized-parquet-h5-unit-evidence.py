#!/usr/bin/env python3
"""Audit ALREADY SANITIZED aggregate evidence; never open market files.

This tool accepts only pre-existing JSON directly under the module's reports/
directory. It does not import pyarrow/h5py/hikyuu, scan directories, access
licensed Parquet, read real H5 or market SQLite, or certify unit conversion.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

MODULE = Path(__file__).resolve().parent.parent
REPORTS = MODULE / "reports"
FORMAT = "AStockDataTools sanitized Parquet H5 unit-evidence intake v1"
OUTPUT_FORMAT = "AStockDataTools offline Parquet H5 unit-evidence assessment v1"
PERIODS = ("day", "5min", "1min")
SYMBOLS = frozenset(("SH600000", "SZ000001"))
TYPES = frozenset(("decimal128", "int64", "uint64", "float64", "float32", "unknown"))
TIME_TYPES = frozenset(("timestamp_ms", "timestamp_us", "timestamp_ns",
                        "date32", "integer_yyyymmdd", "unknown"))
WINDOW_KEYS = frozenset((
    "symbol", "date", "day_rows", "min5_rows", "min1_rows",
    "closed_session", "time_grid_checked", "same_adjustment_basis",
    "day_vs_5min_amount_relative_gap", "day_vs_1min_amount_relative_gap",
    "day_vs_5min_volume_relative_gap", "day_vs_1min_volume_relative_gap"))
SCHEMA_KEYS = frozenset((
    "date_type", "price_type", "amount_type", "volume_type",
    "timezone", "amount_unit_declared", "volume_unit_declared"))
DECLARED_UNITS = frozenset(("unknown", "unit_claim_from_source_documentation"))
TIMEZONES = frozenset(("Asia/Shanghai", "UTC", "naive", "unknown"))
GAP_KEYS = tuple(k for k in WINDOW_KEYS if k.endswith("_relative_gap"))
# This indicates an acceptable raw cross-period discrepancy for collecting
# follow-up evidence. It is NOT a unit factor and does NOT certify actual units.
CANDIDATE_GAP_LIMIT = Decimal("0.0001")


def _path(p, existing):
    p=Path(p)
    if (REPORTS.is_symlink() or p.is_symlink() or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Only direct non-symlink JSON under module reports/ allowed")
    if existing:
        if not p.is_file() or p.stat().st_size>200_000:
            raise ValueError("Existing sanitized evidence JSON required (<=200 KB)")
    elif p.exists():
        raise ValueError("Use a NEW SAFE output JSON; do not overwrite")
    return p


def _gap(value):
    if type(value) is not str or not re.fullmatch(
            r"(?:0|[0-9]{1,3}(?:\.[0-9]{1,12})?)",value):
        raise ValueError("Relative gaps must be decimal strings without exponent")
    try:
        result=Decimal(value)
    except InvalidOperation:
        raise ValueError("Malformed relative gap") from None
    if not result.is_finite() or result<0 or result>1:
        raise ValueError("Relative gaps must be finite values in [0,1]")
    return result


def check_evidence(doc):
    if (type(doc) is not dict or set(doc)!={
            "format","sanitized_aggregates_only","no_raw_market_rows",
            "schemas","windows","independent_unit_reference"}):
        raise ValueError("Unexpected evidence structure; raw data not allowed")
    if (doc["format"]!=FORMAT or doc["sanitized_aggregates_only"] is not True
            or doc["no_raw_market_rows"] is not True
            or doc["independent_unit_reference"] not in ("none","documented_external")):
        raise ValueError("Untrusted evidence provenance or unknown reference type")
    schemas=doc["schemas"]
    if type(schemas) is not dict or set(schemas)!=set(PERIODS):
        raise ValueError("Must describe day, 5min and 1min schemas")
    unknown_fields=[]
    declared_units=[]
    for period in PERIODS:
        v=schemas[period]
        if type(v) is not dict or set(v)!=SCHEMA_KEYS:
            raise ValueError("Schema must contain only approved aggregate labels")
        if (v["date_type"] not in TIME_TYPES
                or any(v[key] not in TYPES for key in (
                    "price_type","amount_type","volume_type"))
                or v["timezone"] not in TIMEZONES
                or any(v[key] not in DECLARED_UNITS for key in (
                    "amount_unit_declared","volume_unit_declared"))):
            raise ValueError("Unrecognized or unsafe schema metadata")
        if any(v[key]=="unknown" for key in (
                "date_type","price_type","amount_type","volume_type","timezone")):
            unknown_fields.append(period)
        if all(v[key]=="unit_claim_from_source_documentation" for key in (
                "amount_unit_declared","volume_unit_declared")):
            declared_units.append(period)
    windows=doc["windows"]
    if type(windows) is not list or len(windows)>24:
        raise ValueError("Supply up to 24 sanitized stock-date windows")
    found=set()
    complete=0
    low_gap=0
    for item in windows:
        if type(item) is not dict or set(item)!=WINDOW_KEYS:
            raise ValueError("Window may contain only counts, flags and aggregate gaps")
        sym=item["symbol"]
        day=item["date"]
        if sym not in SYMBOLS or type(day) is not str or not re.fullmatch(
                r"20[0-9]{2}-[0-9]{2}-[0-9]{2}",day):
            raise ValueError("Unexpected fictional symbol or date label")
        try:
            if date.fromisoformat(day).isoformat()!=day:
                raise ValueError("Noncanonical calendar date")
        except ValueError:
            raise ValueError("Invalid window date") from None
        key=(sym,day)
        if key in found:
            raise ValueError("Duplicate symbol/date window")
        found.add(key)
        if (any(type(item[k]) is not int or not lo<=item[k]<=hi
                for k,lo,hi in (
                    ("day_rows",1,1),("min5_rows",1,60),("min1_rows",1,300)))
                or any(type(item[k]) is not bool for k in (
                    "closed_session","time_grid_checked",
                    "same_adjustment_basis"))):
            raise ValueError("Invalid counts or window alignment flags")
        gaps=[_gap(item[k]) for k in GAP_KEYS]
        flags=all(item[k] for k in (
            "closed_session","time_grid_checked","same_adjustment_basis"))
        if flags:
            complete+=1
            if all(v<=CANDIDATE_GAP_LIMIT for v in gaps):
                low_gap+=1
    dates={day for _,day in found}
    # 2 stocks x at least 2 dates, with actual timestamp/price/volume/amount
    # typed schemas. Even satisfying this does not prove physical units.
    enough=(len(found)>=4 and len(dates)>=2 and
            {sym for sym,_ in found}==SYMBOLS and complete==len(found)
            and low_gap==len(found) and not unknown_fields)
    blockers=[]
    if len(found)<4 or len(dates)<2 or {sym for sym,_ in found}!=SYMBOLS:
        blockers.append("insufficient_distinct_stock_date_windows")
    if complete!=len(found):
        blockers.append("closed_session_time_grid_or_adjustment_unproven")
    if low_gap!=len(found):
        blockers.append("cross_period_aggregate_gap_not_small")
    if unknown_fields:
        blockers.append("missing_parquet_schema_type_or_timezone")
    if doc["independent_unit_reference"]!="documented_external":
        blockers.append("no_independent_physical_unit_documentation")
    if len(declared_units)!=len(PERIODS):
        blockers.append("amount_volume_units_not_declared_for_all_periods")
    if not blockers:
        blockers.append("aggregate_evidence_cannot_prove_row_level_unit_mapping")
    return {
        "format":OUTPUT_FORMAT,
        "input_was_sanitized_metadata_only":True,
        "no_licensed_parquet_or_market_h5_opened":True,
        "observed_window_count":len(found),
        "unique_stock_count":len({sym for sym,_ in found}),
        "unique_date_count":len(dates),
        "fully_aligned_window_count":complete,
        "low_cross_period_gap_window_count":low_gap,
        "schema_period_count":len(schemas),
        "ready_to_plan_independent_unit_check":bool(enough),
        "evidence_blockers":blockers,
        "amount_physical_unit_certified":False,
        "volume_physical_unit_certified":False,
        "price_precision_mapping_certified":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
        "original_market_files_modified":False,
        "no_raw_ohlcva_in_safe_summary":True,
    }


def assess(input_report,output):
    src=_path(input_report,True)
    dest=_path(output,False)
    if src.resolve()==dest.resolve():
        raise ValueError("Input and output must differ")
    report=json.loads(src.read_text(encoding="utf-8"))
    safe=check_evidence(report)
    with dest.open("x",encoding="utf-8") as f:
        json.dump(safe,f,ensure_ascii=False,indent=2)
        f.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sanitized-report",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--offline-evidence-only",required=True,action="store_true")
    args=p.parse_args(argv)
    try:
        safe=assess(args.sanitized_report,args.out)
        print("SAFE offline evidence assessment:",args.out)
        print("Aligned windows:",safe["fully_aligned_window_count"])
        print("Independent physical amount/volume units certified: NO")
        print("Full-market conversion enabled: NO")
    except (ValueError,OSError,TypeError,KeyError,json.JSONDecodeError) as exc:
        p.error(str(exc))


if __name__=="__main__":
    main()
