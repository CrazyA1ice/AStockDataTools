#!/usr/bin/env python3
"""Read-only calibration of 2026-09-30 purchased higher cycles and 2026-10-13 H5 candidates.

Use the existing purchased-first eight-cycle query ONLY. Purchased 5min
rollups on 2026-09-30 are compared against purchased 15/30/60min/day;
SHA-verified private H5 5min 2026-10-13 is checked for complete session
and purchased high-cycle absence. Nothing is written to a market file.
These are CANDIDATE counts, NOT production-ready adjusted/aggregated bars.
Never synthesize week/month from a single session.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
UTC8=timezone(timedelta(hours=8))
HIGH={"15min":3,"30min":6,"60min":12,"day":48}
FIELDS=("open","high","low","close","volume","amount")
ANCHOR=date(2026,9,30)
CANDIDATE=date(2026,10,13)
OCTOBER_VERIFIED_DAYS=(
    date(2026,10,8),date(2026,10,9),
    date(2026,10,12),date(2026,10,13))
INTRADAY=("15min","30min","60min")



def _load():
    spec=importlib.util.spec_from_file_location(
        "original_eight_cycle_purchased_first_2026_high_cycle_calibration",
        HERE/"query-purchased-primary-all-eight-cycles-readonly.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ALL=_load()


def grid_timestamps(day):
    """48 raw 5-minute START labels (24 morning + 24 afternoon)."""
    if type(day) is not date:
        raise ValueError("Trading day must be datetime.date")
    morning=datetime(day.year,day.month,day.day,9,30,tzinfo=UTC8)
    afternoon=datetime(day.year,day.month,day.day,13,0,tzinfo=UTC8)
    return tuple(int((base+timedelta(minutes=5*i)).timestamp()*1000)
                 for base in (morning,afternoon) for i in range(24))


def aggregate_complete_5min(day,symbol,rows,*,expected_source,period):
    """Actual OHLCVA stays only in process memory; return 16/8/4/1 rows."""
    if period not in HIGH:
        raise ValueError("Only single-day 15/30/60min/day aggregation candidates")
    expected=grid_timestamps(day)
    if len(rows)!=len(expected):
        raise ValueError("Refuse incomplete 5min source stockday")
    indexed={}
    for row in rows:
        stamp=row.get("source_timestamp_ms")
        if (type(stamp) is not int or stamp in indexed
                or row.get("period")!="5min" or row.get("symbol")!=symbol
                or row.get("trading_date")!=day.isoformat()
                or row.get("value_source")!=expected_source):
            raise ValueError("Bad provenance, symbol, date or repeated 5min key")
        floats=[]
        for field in FIELDS:
            value=row.get(field)
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError("Bad original 5min OHLCVA")
            floats.append(float(value))
        if (floats[1]<max(floats[0],floats[3]) or
                floats[2]>min(floats[0],floats[3]) or
                floats[4]<0 or floats[5]<0):
            raise ValueError("Invalid original 5min OHLCVA geometry")
        indexed[stamp]=dict(zip(FIELDS,floats))
    if set(indexed)!=set(expected):
        raise ValueError("Original 5min start-grid differs from 48 required timestamps")
    values=[indexed[stamp] for stamp in expected]
    width=HIGH[period]
    chunked=[values[i:i+width] for i in range(0,24,width)]
    chunked += [values[i:i+width] for i in range(24,48,width)]
    if period=="day":
        chunked=[values]
    result=[]
    for i,part in enumerate(chunked):
        if len(part)!=width:
            raise ValueError("Incomplete high cycle bucket")
        start_index=(i*width if period=="day" or i<(24//width)
                     else 24+(i-(24//width))*width)
        # Higher-cycle native timestamp label is explicitly a working
        # hypothesis, not a vendor certified conversion rule.
        candidate={
            "trading_date":day.isoformat(),
            "hypothesized_raw_start_timestamp_ms":expected[start_index],
            "open":part[0]["open"],
            "high":max(x["high"] for x in part),
            "low":min(x["low"] for x in part),
            "close":part[-1]["close"],
            "volume":math.fsum(x["volume"] for x in part),
            "amount":math.fsum(x["amount"] for x in part),
        }
        result.append(candidate)
    if len(result)!=(1 if period=="day" else 48//width):
        raise ValueError("Unexpected high cycle candidate count")
    return result


def compare_purchased_reference(day,period,derived,original):
    """Return ONLY aggregate matching counts, not market price deltas."""
    if period not in HIGH:
        raise ValueError("Unrecognized calibrated cycle")
    if len(original)!=len(derived):
        return {
            "original_purchased_rows":len(original),
            "candidate_buckets":len(derived),
            "matched_raw_label_keys":0,
            "bars_matching_all_six_fields":0,
            "matching_fields_count":{f:0 for f in FIELDS},
            "full_reference_count_and_keys_agree":False,
        }
    if period=="day":
        labels=[row.get("trading_date") for row in original]
        guesses=[row["trading_date"] for row in derived]
    else:
        labels=[row.get("source_timestamp_ms") for row in original]
        guesses=[row["hypothesized_raw_start_timestamp_ms"] for row in derived]
    same_labels=(labels==guesses and len(set(labels))==len(labels))
    field_counts=Counter()
    complete=0
    if same_labels:
        for guessed,real in zip(derived,original):
            yes=True
            for field in FIELDS:
                rv=real.get(field)
                if (type(rv) not in (int,float) or not math.isfinite(rv)):
                    raise ValueError("Invalid purchased high-cycle reference OHLCVA")
                gv=guessed[field]
                # Comparison is diagnostic, not a vendor unit certification.
                match=math.isclose(float(gv),float(rv),rel_tol=1e-8,abs_tol=1e-7)
                if match:
                    field_counts[field]+=1
                else:
                    yes=False
            if yes:
                complete+=1
    return {
        "original_purchased_rows":len(original),
        "candidate_buckets":len(derived),
        "matched_raw_label_keys":len(derived) if same_labels else 0,
        "bars_matching_all_six_fields":complete,
        "matching_fields_count":{field:field_counts[field] for field in FIELDS},
        "full_reference_count_and_keys_agree":same_labels,
    }


def _query(root,symbol,period,day,*,private=False):
    result=ALL.query_bars(
        root,symbol,period,day.isoformat(),day.isoformat(),
        allow_verified_private_h5=private,
        max_candidate_rows=30000000,max_result_bars=1000)
    safe=result["safe_summary"]
    if (safe.get("original_market_files_modified") is not False
            or safe.get("new_market_or_index_files_written") is not False
            or safe.get("production_query_activated") is not False
            or safe.get("matching_bar_count")!=len(result["bars"])
            or sum(safe.get("bars_by_source",{}).values())!=len(result["bars"])):
        raise ValueError("Existing eight-cycle source safety/provenance contract failed")
    return result["bars"]


def audit(root,symbols=("SH600000","SZ000001")):
    if (not isinstance(symbols,(tuple,list)) or not 1<=len(symbols)<=2
            or len(set(symbols))!=len(symbols)):
        raise ValueError("Require one or two unique source security IDs")
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Original source root must exist")
    summary=[]
    for symbol in symbols:
        anchor_rows=_query(root,symbol,"5min",ANCHOR,private=False)
        old=aggregate_complete_5min(
            ANCHOR,symbol,anchor_rows,expected_source="purchased_parquet",
            period="day")
        if len(old)!=1:
            raise ValueError("No complete purchased 5min reference source")
        candidate_rows=_query(root,symbol,"5min",CANDIDATE,private=True)
        new_day=aggregate_complete_5min(
            CANDIDATE,symbol,candidate_rows,
            expected_source="h5_only_complete_stockday",period="day")
        if len(new_day)!=1:
            raise ValueError("No complete verified private H5 5min source")
        comparison={}
        proposed={}
        for period in HIGH:
            old_bins=aggregate_complete_5min(
                ANCHOR,symbol,anchor_rows,
                expected_source="purchased_parquet",period=period)
            existing=_query(root,symbol,period,ANCHOR,private=False)
            comparison[period]=compare_purchased_reference(
                ANCHOR,period,old_bins,existing)
            candidate_bins=aggregate_complete_5min(
                CANDIDATE,symbol,candidate_rows,
                expected_source="h5_only_complete_stockday",period=period)
            actual=_query(root,symbol,period,CANDIDATE,private=False)
            proposed[period]={
                "existing_original_purchased_target_day_bars":len(actual),
                "candidate_derived_buckets_when_purchased_absent":
                    len(candidate_bins) if not actual else 0,
                "five_minute_H5_SHA_checked_by_existing_query":True,
                "candidate_source_full_native_session_grid":True,
                "not_materialized_and_not_vendor_unit_certified":True,
            }
        summary.append({
            "symbol":symbol,
            "source_anchor_day":ANCHOR.isoformat(),
            "candidate_day":CANDIDATE.isoformat(),
            "purchased_anchor_5min_rows":len(anchor_rows),
            "verified_private_H5_candidate_5min_rows":len(candidate_rows),
            "purchased_reference_agreement":comparison,
            "private_derived_target_day":proposed,
        })
    return {
        "status":"2026_oct_13_verified_h5_5min_high_cycle_derived_candidates_readonly_not_certified",
        "reference_day":ANCHOR.isoformat(),
        "candidate_day":CANDIDATE.isoformat(),
        "security_count":len(summary),
        "per_security":summary,
        "candidate_cycles":list(HIGH),
        "week_month_not_derived_from_single_day":True,
        "raw_purchased_time_labels_hypotheses_not_vendor_certified":True,
        "reference_OHLCVA_agreement_is_not_vendor_unit_certification":True,
        "verified_private_5min_vendor_units_certified":False,
        "independent_calendar_and_corporate_adjustment_certified":False,
        "original_H5_files_opened":False,
        "original_market_files_modified":False,
        "new_market_or_index_files_written":False,
        "no_licensed_OHLCVA_values_exported":True,
        "production_activated":False,
    }



def sweep_verified_october_intraday(root,symbols=("SH600000","SZ000001"),
                                    days=OCTOBER_VERIFIED_DAYS):
    """Check ONLY 4 previously vetted H5 dates, without writing derived rows.

    Purchased 15/30/60min source has strict priority, even if partial.
    Any absent private receipt, invalid SHA, unexpected clock/provenance,
    or incomplete source stockday fails closed rather than counting a gap.
    """
    if (type(days) not in (tuple,list)
            or tuple(days)!=OCTOBER_VERIFIED_DAYS
            or type(symbols) not in (tuple,list)
            or not 1<=len(symbols)<=2
            or len(set(symbols))!=len(symbols)):
        raise ValueError("Require exact four verified Oct days and one/two unique symbols")
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Original source root unavailable for Oct four-day sweep")
    per_stock=[]
    total=Counter()
    for symbol in symbols:
        days_out=[]
        for day in days:
            private=_query(root,symbol,"5min",day,private=True)
            if len(private)!=48:
                raise ValueError("Missing complete existing 48-bar H5 5min stockday receipt")
            records={}
            for period in INTRADAY:
                buckets=aggregate_complete_5min(
                    day,symbol,private,
                    expected_source="h5_only_complete_stockday",period=period)
                existing=_query(root,symbol,period,day,private=False)
                # No market write even when purchased high cycle is absent.
                count=len(buckets) if not existing else 0
                records[period]={
                    "original_purchased_target_bars":len(existing),
                    "source_h5_complete_5min_bars":len(private),
                    "candidate_buckets_if_purchased_absent":count,
                    "purchased_has_priority_even_if_partial":True,
                    "all_candidates_discarded_after_readonly_inspection":True,
                }
                total[period]+=count
                if existing:
                    total["purchased_high_cycle_source_blocks"]+=1
            days_out.append({"day":day.isoformat(),"cycles":records})
        per_stock.append({"symbol":symbol,"verified_days":days_out})
    result={
        "status":"oct_2026_four_sha_verified_h5_5min_days_intraday_only_research_candidates",
        "requested_days":[d.isoformat() for d in OCTOBER_VERIFIED_DAYS],
        "security_count":len(symbols),
        "per_security":per_stock,
        "total_candidate_buckets_by_cycle":{p:total[p] for p in INTRADAY},
        "purchased_high_cycle_source_blocks":total["purchased_high_cycle_source_blocks"],
        "only_complete_48_5min_source_stockdays_accepted":True,
        "existing_minute_source_receipt_and_sha_gate_reused":True,
        "daily_candidate_not_certified_or_materialized":True,
        "week_month_not_derived":True,
        "original_market_files_modified":False,
        "new_market_or_index_files_written":False,
        "verified_private_5min_vendor_units_certified":False,
        "no_licensed_OHLCVA_values_exported":True,
        "production_activated":False,
    }
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",required=True,type=Path)
    ap.add_argument("--symbols",nargs="+",default=["SH600000","SZ000001"])
    ap.add_argument("--oct-four-day-intraday-sweep",action="store_true",
                    help="Only 2026-10-08/09/12/13; keep 15/30/60m in memory")
    args=ap.parse_args(argv)
    report=audit(args.root,tuple(args.symbols))
    if args.oct_four_day_intraday_sweep:
        report["october_intraday_source_sweep"]=sweep_verified_october_intraday(
            args.root,tuple(args.symbols))
    print("HIGH_CYCLE_2026_OCT_SOURCE_GATE="+json.dumps(
        report,ensure_ascii=False,
        separators=(",",":"),sort_keys=True),flush=True)


if __name__=="__main__":
    main()
