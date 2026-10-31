#!/usr/bin/env python3
"""Conservative historical 2011..2026 PARQUET-FIRST daily coverage ledger.

Consumes one bounded, exact *day-only* source audit per year; audits themselves
must have been run with explicit --from-date and --to-date, even for a full
calendar year. This prevents the core reconciler's H5-empty whole-year
Parquet-FOOTER-ONLY fallback being mistaken for exact stock-day coverage.

This is an OFFLINE ledger. It never opens market H5, purchased Parquet, source
stock rows, active pointers, or production routes and never stages data.
Partial input is shown as MISSING years, never as a completed historical union.
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
FORMAT="AStockDataTools Parquet-primary full historical exact day coverage ledger v1"
YEARS=tuple(range(2011,2027))
MAX_BYTES_PER_SOURCE_REPORT=16000000
MAX_YEAR_REPORTS=16

SPEC=importlib.util.spec_from_file_location(
    "historical_day_existing_exact_gate",
    HERE/"plan-parquet-primary-day-bootstrap-offline.py")
GATE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def bounds(from_year,to_year,as_of_date):
    if (type(from_year) is not int or type(to_year) is not int
            or from_year!=2011 or to_year!=2026):
        raise ValueError("This ledger only scopes exact 2011..2026 day history")
    if type(as_of_date) is not str:
        raise ValueError("Explicit canonical as-of date required")
    try:
        until=date.fromisoformat(as_of_date)
    except ValueError:
        raise ValueError("Invalid as-of date") from None
    if until.isoformat()!=as_of_date or until.year!=to_year:
        raise ValueError("as-of must be canonical and within 2026")
    if until>date.today():
        raise ValueError("Do not audit dates in the future")
    return until


def safe_report(path,existing):
    candidate=Path(path)
    if (REPORTS.is_symlink() or candidate.is_symlink()
            or candidate.suffix.lower()!=".json"
            or candidate.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Only direct non-symlink JSON under module reports")
    if existing:
        if (not candidate.is_file() or not 0<candidate.stat().st_size
                <=MAX_BYTES_PER_SOURCE_REPORT):
            raise ValueError("Existing bounded audit JSON required")
    elif candidate.exists():
        raise ValueError("Never overwrite a historical day ledger SAFE")
    return candidate.resolve()


def year_from_source(doc):
    years=doc.get("requested_years") if type(doc) is dict else None
    if (type(years) is not list or len(years)!=1
            or type(years[0]) is not int or years[0] not in YEARS):
        raise ValueError("Each source audit must cover exactly one 2011..2026 year")
    return years[0]


def plan_reports(items,as_of_date="2026-10-31"):
    """items: [(safe report basename, original JSON bytes)], at most 16."""
    until=bounds(2011,2026,as_of_date)
    if (type(items) not in (list,tuple) or len(items)>MAX_YEAR_REPORTS):
        raise ValueError("Require at most 16 one-year source reports")
    by_year={}
    seen_names=set()
    for filename,blob in items:
        if (type(filename) is not str or len(filename)>128
                or not re.fullmatch(r"[A-Za-z0-9._-]+\.json",filename)
                or filename in seen_names
                or type(blob) is not bytes or not 0<len(blob)<=MAX_BYTES_PER_SOURCE_REPORT):
            raise ValueError("Unsafe or duplicate historical source audit")
        seen_names.add(filename)
        try:
            source=json.loads(blob)
        except (ValueError,UnicodeError):
            raise ValueError("Malformed historical source audit") from None
        year=year_from_source(source)
        if year in by_year:
            raise ValueError("Duplicate source audit for a historical year")
        expected_first=f"{year}-01-01"
        expected_end=(as_of_date if year==2026 else f"{year}-12-31")
        if (source.get("requested_from_date")!=expected_first
                or source.get("requested_to_date")!=expected_end):
            raise ValueError("Historical source audit is not a complete explicit year/as-of range")
        section=source.get("results",{}).get(f"day/{year}")
        # Requiring explicit dates is essential, but the next check separately
        # refuses any historical section that did NOT scan real Parquet keys.
        if (type(section) is not dict
                or section.get("parquet_key_coverage_exact_when_scan_complete") is not True
                or section.get("pq_year_metadata_only_no_h5_rows") is not False):
            raise ValueError("Parquet footer-only or unverified key coverage cannot enter ledger")
        exact=GATE.analyze(source)
        window=exact["audited_window"]
        if (window!={"from_date":expected_first,"to_date":expected_end}
                or exact["source_key_conservation_verified"] is not True
                or exact["source_scan_complete"] is not True
                or exact["market_source_files_read"] is not False
                or exact["market_source_files_modified"] is not False
                or exact["safe_to_automatically_union"] is not False):
            raise ValueError("Original audit or conservative daily gate inconsistent")
        coverage=exact["daily_coverage"]
        # Valid source audits have at least one observed date, but cannot
        # prove that unseen dates were or were not market trading sessions.
        if (type(coverage) is not list or not coverage
                or any(type(x) is not dict for x in coverage)):
            raise ValueError("No exact observed daily source date coverage")
        observed_dates=[date.fromisoformat(x["date"]) for x in coverage]
        if any(d.year!=year or d>until for d in observed_dates):
            raise ValueError("Source observations outside requested historical as-of date")
        totals=exact["source_totals"]
        if (totals["pq_rows"]<1 or
                totals["matched_keys"]+totals["h5_only_rows"]!=totals["h5_rows"]):
            raise ValueError("Missing purchased day source or inconsistent daily key partition")
        complete_candidates=exact["h5_only_rows_on_wholly_parquet_absent_dates"]
        mixed_candidates=exact["h5_only_rows_on_mixed_dates_need_symbol_day_manifest"]
        if complete_candidates+mixed_candidates!=totals["h5_only_rows"]:
            raise ValueError("Unclassified H5-only source stock-days")
        date_counts={}
        for row in coverage:
            group=row["category"]
            date_counts[group]=date_counts.get(group,0)+1
        by_year[year]={
            "year":year,
            "audited_first_date":expected_first,
            "audited_requested_end_date":expected_end,
            "latest_observed_source_stockday":max(observed_dates).isoformat(),
            "observed_source_dates":len(observed_dates),
            "audited_purchased_unique_stockdays":totals["pq_rows"],
            "audited_original_h5_unique_stockdays":totals["h5_rows"],
            "audited_matching_stockday_keys":totals["matched_keys"],
            "h5_only_complete_absent_date_candidate_rows":complete_candidates,
            "h5_only_mixed_date_candidate_rows":mixed_candidates,
            "purchased_only_stockday_rows":totals["pq_only_rows"],
            "overlap_price_difference_existing_tolerance_rows":
                exact["overlap_price_mismatch_rows"],
            "overlap_quantity_or_amount_difference_rows":
                exact["quantity_or_amount_difference_rows"],
            "overlap_price_gate_passed_for_this_year_only":
                exact["existing_tolerance_ohlc_overlap_pass"],
            "date_categories":dict(sorted(date_counts.items())),
            "audit_source_report_basename":filename,
            "audit_source_report_sha256":hashlib.sha256(blob).hexdigest(),
            "source_key_coverage_exact_within_requested_window":True,
            "historical_full_calendar_market_freshness_certified":False,
            "ready_for_unattended_data_fill":False,
        }
    missing=[y for y in YEARS if y not in by_year]
    rows=sorted(by_year.values(),key=lambda r:r["year"])
    sums=lambda field:sum(entry[field] for entry in rows)
    blockers={
        "years_missing_exact_day_source_audit":missing,
        "years_with_mixed_date_h5_only_stockdays":[
            r["year"] for r in rows if r["h5_only_mixed_date_candidate_rows"]>0],
        "years_with_existing_tolerance_price_disagreement":[
            r["year"] for r in rows
            if r["overlap_price_difference_existing_tolerance_rows"]>0],
        "years_with_no_paired_source_ohlc_comparison":[
            r["year"] for r in rows
            if not r["overlap_price_gate_passed_for_this_year_only"]],
    }
    fully=len(rows)==len(YEARS) and not missing
    return {
        "format":FORMAT,
        "status":("all_16_source_years_exact_audited_not_merged" if fully
                  else "partial_exact_source_year_ledger_not_merged"),
        "historical_years_requested":list(YEARS),
        "as_of_date":as_of_date,
        "annual_exact_day_audits_accepted":len(rows),
        "missing_exact_annual_day_audit_years":missing,
        "yearly_exact_source_coverage":rows,
        "audited_totals_only_for_accepted_years":{
            "purchased_unique_stockdays":sums("audited_purchased_unique_stockdays"),
            "h5_unique_stockdays":sums("audited_original_h5_unique_stockdays"),
            "overlapping_stockday_keys":sums("audited_matching_stockday_keys"),
            "h5_only_complete_absent_date_candidates":
                sums("h5_only_complete_absent_date_candidate_rows"),
            "h5_only_mixed_date_candidates":
                sums("h5_only_mixed_date_candidate_rows"),
            "purchased_only_stockday_keys":sums("purchased_only_stockday_rows"),
            "overlap_price_tolerance_disagreements":
                sums("overlap_price_difference_existing_tolerance_rows"),
            "overlap_quantity_or_amount_disagreements":
                sums("overlap_quantity_or_amount_difference_rows"),
        },
        "qualifying_years_must_be_scanned_with_explicit_date_window":True,
        "full_2011_to_2026_as_of_source_key_coverage_audited":fully,
        "missing_years_are_not_assumed_zero":True,
        "meta_only_h5_empty_annual_parquet_fallback_prohibited":True,
        "blockers":blockers,
        "annual_h5_private_staging_requires_separate_fresh_exact_gate":True,
        "mixed_date_h5_gaps_cannot_use_whole_day_stager":True,
        "candidate_h5_amount_volume_units_unverified":True,
        "no_market_files_opened_by_this_offline_ledger":True,
        "no_market_source_rows_or_raw_ohlcva_or_symbols_exported":True,
        "original_market_parquet_or_h5_written":False,
        "h5_mirror_created":False,
        "private_or_production_active_pointer_modified":False,
        "historical_unified_parquet_materialized":False,
        "ready_to_automatically_union_or_mirror":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reports",nargs="+",type=Path,required=True)
    p.add_argument("--as-of-date",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--offline-reports-only",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        output=safe_report(args.out,False)
        originals=[]
        for item in args.reports:
            file=safe_report(item,True)
            originals.append((file.name,file.read_bytes()))
        result=plan_reports(originals,args.as_of_date)
        # Input report files cannot change while this accounting executes.
        for (name,original),item in zip(originals,args.reports):
            if safe_report(item,True).read_bytes()!=original:
                raise ValueError("One historical audit SAFE changed while building ledger")
        with output.open("x",encoding="utf-8") as stream:
            json.dump(result,stream,sort_keys=True,ensure_ascii=False,indent=2)
            stream.write("\n")
        print("SAFE historical day coverage ledger:",output)
        print("Qualified exact annual sources:",result["annual_exact_day_audits_accepted"],
              "/ 16; no source writes")
        print("Still missing annual source audits:",result["missing_exact_annual_day_audit_years"])
        print("Candidate-only H5 whole/mixed gap rows:",
              result["audited_totals_only_for_accepted_years"][
                  "h5_only_complete_absent_date_candidates"],
              result["audited_totals_only_for_accepted_years"][
                  "h5_only_mixed_date_candidates"])
        print("No private Parquet union, native H5 mirror or production activation.")
    except (ValueError,OSError,KeyError,TypeError,UnicodeError,
            OverflowError,json.JSONDecodeError):
        p.error("Historical exact day source SAFE ledger rejected; no original writes")


if __name__=="__main__":
    main()
