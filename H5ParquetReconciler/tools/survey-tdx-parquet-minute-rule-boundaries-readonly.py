#!/usr/bin/env python3
"""Bounded read-only anomaly survey for a VERSIONED, UNAPPROVED 241->240 rule.

This executes the existing full native-TDX/Parquet preview in memory on
explicit symbol-days. A mismatched or unsupported source becomes a sanitized
failure category instead of a misleading pass; NO market bars, file paths,
or raw exception messages are put into the SAFE JSON. No conversion writes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "tdx_parquet_boundary_survey_preview",
    HERE/"preview-tdx-parquet-1min-normalization-readonly.py")
preview_mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview_mod)
probe=preview_mod.probe

FORMAT="AStockDataTools bounded read-only TDX Parquet candidate boundary survey v1"
RULE_ID="experimental_tdx_end240_from_pq241_opening_fold_v1"
MAX_CASES=12
STOCK=re.compile(r"(SH|SZ)[0-9]{6}\Z")
SUCCESS="diagnostic_candidate_matches_both_sources_not_production_certified"
MISMATCH="diagnostic_candidate_mismatch_do_not_materialize"
FIELDS=("open","high","low","close","volume","amount")
CATEGORIES={
    "candidate_six_field_disagreement",
    "native_source_not_found",
    "native_source_path_unsafe",
    "native_minute_grid_unsupported",
    "purchased_minute_grid_unsupported",
    "purchased_bad_ohlcva",
    "source_changed_or_provenance_invalid",
    "source_or_validation_error_unclassified",
}


def _validate_cases(cases):
    if type(cases) not in (tuple,list) or not 1<=len(cases)<=MAX_CASES:
        raise ValueError("Supply between 1 and 12 explicit --case pairs")
    unique=set()
    output=[]
    for item in cases:
        if type(item) not in (tuple,list) or len(item)!=2:
            raise ValueError("Each case requires SYMBOL DATE")
        symbol,day=item
        if type(symbol) is not str or not STOCK.fullmatch(symbol):
            raise ValueError("Use canonical SH/SZ six-digit stock symbol")
        if type(day) is not str:
            raise ValueError("Use ISO stock date")
        try:
            d=date.fromisoformat(day)
        except ValueError as exc:
            raise ValueError("Use ISO stock date") from exc
        if d.isoformat()!=day:
            raise ValueError("Noncanonical ISO stock date")
        if (symbol,day) in unique:
            raise ValueError("Duplicate requested stock-day")
        unique.add((symbol,day))
        output.append((symbol,day))
    return output


def _classify_exception(exc):
    # Important: Do NOT include str(exc) in output. Some OSError messages
    # contain private source paths. Only match exact stable parser fragments.
    reason=str(exc)
    if any(phrase in reason for phrase in (
            "Parquet 1min requires exactly",
            "Parquet 5min requires exactly",
            "Parquet 1min incomplete, duplicate or unexpected time grid",
            "Parquet 5min incomplete, duplicate or unexpected time grid",
            "Purchased bar date or period differs",
            "Purchased timestamp spills outside requested day",
            "Purchased Beijing minute label",
            "Purchased timestamp label")):
        return "purchased_minute_grid_unsupported"
    if any(phrase in reason for phrase in (
            "Malformed/nonfinite purchased OHLCVA",
            "Invalid purchased OHLCVA bar",
            "impossible OHLCVA geometry")):
        return "purchased_bad_ohlcva"
    if any(phrase in reason for phrase in (
            "Strict native 240 END-minute profile required",
            "TDX requires verified 240",
            "native 240 END",
            "Native minute grid changed",
            "time grid is not",
            "time-grid")):
        return "native_minute_grid_unsupported"
    if any(phrase in reason for phrase in (
            "source hash changed",
            "Source hash changed",
            "Source stat changed",
            "source stat changed",
            "source size",
            "Source size",
            "source content",
            "Source content",
            "manifest",
            "Manifest",
            "mutated",
            "between scans")):
        return "source_changed_or_provenance_invalid"
    return "source_or_validation_error_unclassified"


def _source_file(vipdoc,symbol):
    market=symbol[:2].lower()
    folder=vipdoc/market/"minline"
    file=folder/(symbol.lower()+".lc1")
    # Reject symlinked directories and files; never print their paths.
    if any(x.is_symlink() for x in (vipdoc,vipdoc/market,folder,file)):
        return None,"native_source_path_unsafe"
    if not file.is_file():
        return None,"native_source_not_found"
    return file,None


def survey(parquet_root,vipdoc,cases,max_source_bytes,max_rows):
    cases=_validate_cases(cases)
    vipdoc=Path(vipdoc)
    root=Path(parquet_root)
    if (not vipdoc.is_dir() or vipdoc.is_symlink()
            or not root.is_dir() or root.is_symlink()):
        raise ValueError("Real non-symlink TDX and purchased roots required")
    if type(max_source_bytes) is not int or not 32<=max_source_bytes<=probe.MAX_SOURCE_BYTES:
        raise ValueError("Invalid native source byte budget")
    if type(max_rows) is not int or not 1<=max_rows<=100000000:
        raise ValueError("Invalid purchased scan row budget")
    outcomes=[]
    counts=Counter()
    for symbol,day in cases:
        safe={
            "symbol":symbol,"date":day,
            "candidate_rule_id":RULE_ID,
            "original_sources_unchanged":True,
            "candidate_was_not_materialized":True,
            "eligible_for_automatic_production_union":False,
        }
        source,problem=_source_file(vipdoc,symbol)
        if problem:
            safe.update({"status":"unsupported","reason_category":problem})
        else:
            try:
                result=preview_mod.preview(
                    root,source,symbol,day,
                    max_source_bytes=max_source_bytes,
                    max_candidate_rows=max_rows)
                verdict=result.get("preview_verdict")
                gates=result.get("gates")
                if (type(gates) is not dict or
                        type(gates.get("diagnostic_preview_consistent")) is not bool or
                        (verdict==SUCCESS)!=gates["diagnostic_preview_consistent"] or
                        verdict not in (SUCCESS,MISMATCH) or
                        result.get("eligible_for_automatic_production_union") is not False or
                        result.get("original_sources_modified") is not False or
                        result.get("candidate_ohlcva_exported") is not False):
                    raise ValueError("Unexpected preview safety/verdict contract")
                if verdict==SUCCESS:
                    safe.update({
                        "status":"diagnostic_match",
                        "reason_category":None,
                        "native_source_content_sha256":
                            result["native_source_content_sha256"],
                        "parquet_manifest_fingerprints_stat_only":{
                            period:result["purchased_source_stat_only_provenance"][period][
                                "source_manifest_stat_only_sha256"]
                            for period in ("1min","5min")},
                    })
                else:
                    safe.update({
                        "status":"mismatch",
                        "reason_category":"candidate_six_field_disagreement",
                        "failed_gates":[name for name in (
                            "first_candidate_matches_native",
                            "remaining_239_match_native",
                            "candidate_240_matches_native",
                            "candidate_5min_matches_purchased_5min")
                            if gates.get(name) is not True],
                    })
            except (ValueError,OSError,TypeError,OverflowError,KeyError,
                    ModuleNotFoundError,ZeroDivisionError) as exc:
                safe.update({
                    "status":"unsupported",
                    "reason_category":_classify_exception(exc),
                })
        counts[safe["status"]]+=1
        outcomes.append(safe)
    matched=counts["diagnostic_match"]
    rejected=len(outcomes)-matched
    return {
        "format":FORMAT,
        "candidate_rule_id":RULE_ID,
        "candidate_rule_is_experimental":True,
        "rule_scope":"SH/SZ strict TDX 240-END / purchased Parquet 241-opening-plus-END / 48 five-minute only",
        "requested_stock_days":len(outcomes),
        "diagnostic_matches":matched,
        "mismatches":counts["mismatch"],
        "unsupported_source_profiles":counts["unsupported"],
        "all_requested_samples_match":rejected==0,
        "verdict":("all_requested_cases_diagnostic_match_not_certified"
                   if rejected==0 else "anomaly_observed_do_not_apply_mapping"),
        "samples":outcomes,
        "rejection_categories_are_conservative_not_authoritative":True,
        "source_parquet_fingerprints_are_stat_only":True,
        "market_ohlcva_read_locally_but_never_exported":True,
        "candidate_minutes_never_materialized":True,
        "sources_modified":False,
        "production_mapping_certified":False,
        "eligible_for_automatic_production_union":False,
        "no_raw_ohlcva_or_individual_intraday_times_in_report":True,
        "no_private_source_paths_in_report":True,
    }


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet-root",type=Path,required=True)
    ap.add_argument("--tdx-vipdoc",type=Path,required=True)
    ap.add_argument("--case",action="append",nargs=2,metavar=("SYMBOL","DATE"),required=True)
    ap.add_argument("--max-tdx-file-bytes",type=int,default=probe.MAX_SOURCE_BYTES)
    ap.add_argument("--max-candidate-rows",type=int,default=35000000)
    ap.add_argument("--read-only",action="store_true",required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        out=probe.safe_out(args.out)
        report=survey(args.parquet_root,args.tdx_vipdoc,args.case,
                      args.max_tdx_file_bytes,args.max_candidate_rows)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as fd:
            json.dump(report,fd,indent=2,ensure_ascii=False,allow_nan=False)
            fd.write("\n")
        print("Saved safe read-only candidate boundary survey:",out)
        print("Cases:",report["requested_stock_days"],
              "matched:",report["diagnostic_matches"],
              "mismatched:",report["mismatches"],
              "unsupported:",report["unsupported_source_profiles"])
        print("No licensed market OHLCVA exported or production union performed.")
    except (ValueError,OSError,TypeError,OverflowError,KeyError) as exc:
        ap.error(str(exc))


if __name__=="__main__":
    main()
