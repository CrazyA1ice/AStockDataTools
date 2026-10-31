#!/usr/bin/env python3
"""Offline conservative plan for stock-day gaps on dates having BOTH sources.

Requires the full 16-year exact source ledger and its SHA-matched 2016/2026
source audits.  Only counts and calendar days leave this tool: no raw stock
codes, OHLCVA, market IO, stage writes, native H5 conversion, or pointer change.
Whole-day H5-only gaps are explicitly excluded; July 16 2026 is quarantined
because independent same-day OHLC disagreements violate the price gate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools mixed-date H5-only stockday offline gate v1"
HISTORY_FORMAT="AStockDataTools Parquet-primary full historical exact day coverage ledger v1"
YEARS=(2016,2026)
EXPECTED_MIXED={2016:1,2026:87}
EXPECTED_COMPLETE=22191
EXPECTED_YEAR_ROWS=16
MAX_LEDGER_BYTES=1000000
MAX_SOURCE_BYTES=16000000

SPEC=importlib.util.spec_from_file_location(
    "mixed_h5_day_existing_gate",
    HERE/"plan-parquet-primary-day-bootstrap-offline.py")
GATE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def valid_path(value,read=False,limit=MAX_SOURCE_BYTES):
    raw=Path(value)
    if (REPORTS.is_symlink() or raw.is_symlink()
            or raw.suffix.lower()!=".json"
            or raw.resolve().parent!=REPORTS.resolve()):
        raise ValueError("All SAFE artifacts must be direct module reports JSON")
    result=raw.resolve()
    if read:
        if (not result.is_file() or not 0<result.stat().st_size<=limit):
            raise ValueError("Missing or oversized source SAFE")
    elif result.exists():
        raise ValueError("Never replace an existing SAFE")
    return result


def parse_json_bytes(raw):
    if type(raw) is not bytes:
        raise ValueError("Expected raw immutable JSON bytes")
    try:
        obj=json.loads(raw)
    except (ValueError,UnicodeError):
        raise ValueError("Malformed source JSON") from None
    if type(obj) is not dict:
        raise ValueError("Source JSON must be an object")
    return obj


def analyze(ledger_raw,source_raws):
    """Return counts/status only. source_raws maps source SAFE BASENAME to bytes."""
    ledger=parse_json_bytes(ledger_raw)
    if (ledger.get("format")!=HISTORY_FORMAT
            or ledger.get("as_of_date")!="2026-10-31"
            or ledger.get("annual_exact_day_audits_accepted")!=EXPECTED_YEAR_ROWS
            or ledger.get("full_2011_to_2026_as_of_source_key_coverage_audited") is not True
            or ledger.get("missing_exact_annual_day_audit_years")!=[]
            or ledger.get("historical_unified_parquet_materialized") is not False
            or ledger.get("ready_to_automatically_union_or_mirror") is not False
            or ledger.get("original_market_parquet_or_h5_written") is not False
            or ledger.get("private_or_production_active_pointer_modified") is not False):
        raise ValueError("Requires completed but NOT merged 2011-2026 exact annual ledger")
    rows=ledger.get("yearly_exact_source_coverage")
    if (type(rows) is not list or len(rows)!=EXPECTED_YEAR_ROWS
            or {x.get("year") for x in rows if type(x) is dict}
               !=set(range(2011,2027))):
        raise ValueError("Malformed 16 distinct annual evidence entries")
    by_year={x["year"]:x for x in rows}
    totals=ledger.get("audited_totals_only_for_accepted_years")
    if (type(totals) is not dict
            or totals.get("h5_only_mixed_date_candidates")!=sum(EXPECTED_MIXED.values())
            or totals.get("h5_only_complete_absent_date_candidates")!=EXPECTED_COMPLETE
            or totals.get("h5_unique_stockdays")!=
                totals.get("overlapping_stockday_keys",0)+
                totals.get("h5_only_mixed_date_candidates",0)+
                totals.get("h5_only_complete_absent_date_candidates",0)):
        raise ValueError("Full historical ledger missing-key totals inconsistent")
    if (type(source_raws) is not dict or len(source_raws)!=2):
        raise ValueError("Exactly two distinct annual source audits required")
    years_output=[]
    active_dates=[]
    quarantined=[]
    for year in YEARS:
        meta=by_year[year]
        basename=meta.get("audit_source_report_basename")
        sha=meta.get("audit_source_report_sha256")
        if (type(basename) is not str or basename!=Path(basename).name
                or basename not in source_raws):
            raise ValueError("Missing explicitly SHA-linked annual source report")
        raw=source_raws[basename]
        if (type(raw) is not bytes or not 0<len(raw)<=MAX_SOURCE_BYTES
                or hashlib.sha256(raw).hexdigest()!=sha):
            raise ValueError("Annual source report SHA differs from historical ledger")
        source=parse_json_bytes(raw)
        if source.get("requested_years")!=[year]:
            raise ValueError("Annual source date/year linkage mismatched")
        gate=GATE.analyze(source)
        if (gate.get("source_scan_complete") is not True
                or gate.get("source_key_conservation_verified") is not True
                or gate.get("safe_to_automatically_union") is not False
                or gate.get("h5_only_rows_on_mixed_dates_need_symbol_day_manifest")
                   !=EXPECTED_MIXED[year]
                or meta.get("h5_only_mixed_date_candidate_rows")!=EXPECTED_MIXED[year]
                or gate["source_totals"]["h5_only_rows"]!=
                    (gate["h5_only_rows_on_wholly_parquet_absent_dates"]+
                     gate["h5_only_rows_on_mixed_dates_need_symbol_day_manifest"])
                or meta.get("audited_original_h5_unique_stockdays")!=
                    gate["source_totals"]["h5_rows"]
                or meta.get("audited_purchased_unique_stockdays")!=
                    gate["source_totals"]["pq_rows"]
                or meta.get("audited_matching_stockday_keys")!=
                    gate["source_totals"]["matched_keys"]
                or meta.get("overlap_price_difference_existing_tolerance_rows")!=
                    gate["overlap_price_mismatch_rows"]):
            raise ValueError("Annual day conservation or ledger reconciliation failed")
        mixed=[]
        source_dates=source["results"][f"day/{year}"]["by_day"]
        for day in gate["daily_coverage"]:
            if day["category"]!="mixed_date_requires_exact_symbol_day_manifest":
                continue
            original=source_dates[day["date"]]
            price_mismatch=original.get("price_mismatch",0)
            if type(price_mismatch) is not int or not 0<=price_mismatch<=day["matched_keys"]:
                raise ValueError("Invalid daily price mismatch evidence")
            date_label=date.fromisoformat(day["date"][:4]+"-"+day["date"][4:6]+"-"+day["date"][6:])
            if date_label.year!=year:
                raise ValueError("Mixed source day outside its audited year")
            candidate={
                "date":date_label.isoformat(),
                "year":year,
                "h5_only_stockday_candidate_rows":day["h5_only_rows"],
                "purchased_source_stockday_rows":day["pq_rows"],
                "overlapping_source_stockday_rows":day["matched_keys"],
                "same_day_overlapping_price_disagreements":price_mismatch,
                "status":("quarantined_same_day_price_disagreement"
                          if price_mismatch else "candidate_requires_exact_stockday_live_recheck"),
                "exact_stock_symbols_exported":False,
                "private_market_rows_staged":False,
            }
            mixed.append(candidate)
            (quarantined if price_mismatch else active_dates).append(candidate)
        if sum(x["h5_only_stockday_candidate_rows"] for x in mixed)!=EXPECTED_MIXED[year]:
            raise ValueError("Mixed-date candidate rows do not reconcile to annual source")
        years_output.append({
            "year":year,
            "source_report_basename":basename,
            "source_report_sha256":sha,
            "h5_only_mixed_date_candidate_rows":EXPECTED_MIXED[year],
            "mixed_date_candidates":sorted(mixed,key=lambda x:x["date"]),
            "h5_only_complete_absent_date_rows_are_separate":
                gate["h5_only_rows_on_wholly_parquet_absent_dates"],
        })
    if sum(x["h5_only_stockday_candidate_rows"] for x in active_dates+quarantined)!=88:
        raise ValueError("Remaining mixed-date stockday total is not exactly 88")
    return {
        "format":FORMAT,
        "as_of_date":"2026-10-31",
        "full_history_ledger_sha256":hashlib.sha256(ledger_raw).hexdigest(),
        "all_16_years_audited_before_this_plan":True,
        "full_history_complete_day_candidates_already_separately_handled":EXPECTED_COMPLETE,
        "remaining_mixed_date_h5_only_stockday_candidates":88,
        "eligible_for_next_live_key_recheck_only":
            sum(x["h5_only_stockday_candidate_rows"] for x in active_dates),
        "quarantined_pending_price_disagreement_review":
            sum(x["h5_only_stockday_candidate_rows"] for x in quarantined),
        "years":years_output,
        "years_with_mixed_date_gaps":[2016,2026],
        "same_day_price_disagreement_quarantine_is_conservative":True,
        "whole_day_stager_must_not_accept_mixed_dates":True,
        "source_reports_are_exact_key_audits_not_raw_market_rechecks":True,
        "all_2011_2026_source_prices_identical":False,
        "license_or_unit_conversion_certified":False,
        "market_source_files_read_by_this_offline_gate":False,
        "actual_stock_symbols_or_ohlcva_exported":False,
        "original_market_files_modified":False,
        "private_stage_or_overlay_pointer_modified":False,
        "unified_parquet_or_h5_mirror_created":False,
        "safe_to_automatically_stage_promote_or_mirror":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-ledger",type=Path,required=True)
    parser.add_argument("--source-2016",type=Path,required=True)
    parser.add_argument("--source-2026",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--offline-reports-only",required=True,action="store_true")
    args=parser.parse_args(argv)
    try:
        ledger_path=valid_path(args.history_ledger,True,MAX_LEDGER_BYTES)
        source1=valid_path(args.source_2016,True)
        source2=valid_path(args.source_2026,True)
        out=valid_path(args.out)
        if len({ledger_path,source1,source2,out})!=4:
            raise ValueError("Separate ledger, annual reports and NEW output required")
        original={p:p.read_bytes() for p in (ledger_path,source1,source2)}
        result=analyze(original[ledger_path],
                       {p.name:original[p] for p in (source1,source2)})
        if any(p.read_bytes()!=raw for p,raw in original.items()):
            raise ValueError("Audit source changed during offline planning")
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as stream:
            json.dump(result,stream,ensure_ascii=False,indent=2,sort_keys=True)
            stream.write("\n")
        print("SAFE mixed-date key-only plan:",out)
        print("Remaining H5-only source stockday candidates:",
              result["remaining_mixed_date_h5_only_stockday_candidates"])
        print("Live recheck-only candidates:",
              result["eligible_for_next_live_key_recheck_only"])
        print("Quarantined due same-day source price disagreements:",
              result["quarantined_pending_price_disagreement_review"])
        print("No original market file, H5 mirror or active pointer modified.")
    except (ValueError,KeyError,TypeError,OSError,OverflowError,UnicodeError):
        parser.error("Mixed-date H5 stockday offline gate refused; no market writes")


if __name__=="__main__":
    main()
