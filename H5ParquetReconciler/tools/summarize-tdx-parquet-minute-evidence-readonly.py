#!/usr/bin/env python3
"""Aggregate existing SAFE TDX/Parquet minute audit JSON across stock-days.

This is an evidence sufficiency gate, NOT a binary parser or normalization
engine. It never reads market bars, auto-converts the opening observation, or
modifies purchased Parquet/H5, native TDX, private overlays or production query.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools bounded TDX vs Parquet minute evidence cohort v1"
SOURCE_FORMAT="AStockDataTools TDX 240 vs purchased Parquet 241 minute opening audit v1"
FIELDS=("open","high","low","close","volume","amount")
MAX_REPORTS=12
MAX_REPORT_BYTES=256*1024
SHA=re.compile(r"[0-9a-f]{64}\Z")
STOCK=re.compile(r"(SH|SZ|BJ)[0-9]{6}\Z")


def _inside_reports(value,exists=True):
    candidate=Path(value)
    target=candidate if candidate.is_absolute() else MODULE/candidate
    resolved=target.resolve()
    root=REPORTS.resolve()
    if ((MODULE/"reports").is_symlink() or target.is_symlink()
            or not resolved.is_relative_to(root) or
            resolved.suffix.lower()!=".json" or
            (exists and not resolved.is_file()) or
            (not exists and resolved.exists())):
        raise ValueError("Use existing input / NEW output JSON under module reports/")
    return resolved


def _strict_json(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError("Duplicate report JSON key")
        result[key]=value
    return result


def _load(value):
    file=_inside_reports(value)
    before=file.stat()
    if (before.st_size<=0 or before.st_size>MAX_REPORT_BYTES):
        raise ValueError("Evidence report is empty or over byte budget")
    with file.open("rb") as fd:
        raw=fd.read(MAX_REPORT_BYTES+1)
    after=file.stat()
    if (len(raw)!=before.st_size or
            before.st_size!=after.st_size or
            before.st_mtime_ns!=after.st_mtime_ns):
        raise ValueError("Evidence report changed while reading")
    try:
        report=json.loads(raw.decode("utf-8"),
                          object_pairs_hook=_strict_json,
                          parse_constant=lambda _:
                          (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ValueError("Malformed safe evidence JSON") from exc
    if type(report) is not dict or report.get("format")!=SOURCE_FORMAT:
        raise ValueError("Unsupported evidence-report format")
    return report,hashlib.sha256(raw).hexdigest()


def _six_fields(report,expected_n):
    if type(report) is not dict or set(report)!=set(FIELDS):
        raise ValueError("Missing or extra OHLCVA diagnostic fields")
    for name in FIELDS:
        item=report[name]
        if (type(item) is not dict
                or type(item.get("n")) is not int
                or item["n"]!=expected_n
                or type(item.get("within_diagnostic_tolerance")) is not int
                or not 0<=item["within_diagnostic_tolerance"]<=expected_n
                or type(item.get("max_relative_error")) not in (int,float)
                or not 0<=item["max_relative_error"]<1e20):
            raise ValueError("Malformed or inconsistent field diagnostic")
    return all(item["within_diagnostic_tolerance"]==expected_n
               for item in report.values())


def _validate(r,raw_digest):
    if (not STOCK.fullmatch(str(r.get("symbol","")))
            or type(r.get("date")) is not str):
        raise ValueError("Noncanonical stock-day label")
    try:
        day=date.fromisoformat(r["date"])
    except ValueError as exc:
        raise ValueError("Malformed evidence day") from exc
    if day.isoformat()!=r["date"]:
        raise ValueError("Non-ISO evidence day")
    for name,expect in (("tdx_verified_minute_count",240),
                        ("parquet_verified_minute_count",241),
                        ("parquet_verified_five_minute_count",48)):
        if type(r.get(name)) is not int or r[name]!=expect:
            raise ValueError("Unexpected source period count")
    if not SHA.fullmatch(str(r.get("tdx_full_source_sha256",""))):
        raise ValueError("Missing full native TDX content hash")
    provenance=r.get("parquet_stat_only_provenance")
    if type(provenance) is not dict or set(provenance)!={"1min","5min"}:
        raise ValueError("Missing purchased Parquet stat provenance")
    for period,expected in (("1min",241),("5min",48)):
        p=provenance[period]
        if (type(p) is not dict or
                not SHA.fullmatch(str(p.get("source_manifest_stat_only_sha256","")))
                or type(p.get("matching_bar_count")) is not int
                or p["matching_bar_count"]!=expected
                or p.get("source_manifest_is_stat_only_not_content_authenticated") is not True):
            raise ValueError("Missing reliable purchased query provenance metadata")
    mandatory={
        "first_0930_key_never_synthesized_or_dropped_for_production":True,
        "amount_and_volume_unit_conversion_not_applied":True,
        "no_raw_ohlcva_or_individual_times_in_report":True,
        "private_cache_enabled":False,
        "h5_accessed":False,
        "sources_modified":False,
        "staging_or_production_union_performed":False,
        "eligible_for_automatic_production_union":False,
    }
    for key,expected in mandatory.items():
        if type(r.get(key)) is not bool or r[key] is not expected:
            raise ValueError("Unsafe or incomplete evidence safety contract: "+key)
    opening=r.get("opening_bar_diagnostics")
    if (type(opening) is not dict
            or opening.get("observed_separate_0930_opening_key") is not True
            or opening.get("opening_source_semantics_not_certified") is not True):
        raise ValueError("Opening semantics is not independently established")
    groups=r.get("first_minute_opening_merge_hypothesis")
    if type(groups) is not dict or groups.get(
            "opening_merge_is_only_a_hypothesis_not_a_mapping_rule") is not True:
        raise ValueError("Missing explicitly non-certified opening hypothesis")
    tests=(
        ("native_0931_vs_aggregation_of_parquet_0930_and_0931",1,
         "first_minute_all_six_fields_match_after_merge"),
        ("remaining_239_native_vs_parquet",239,
         "remaining_239_all_six_fields_match"),
        ("all_240_native_vs_first_merged_plus_remaining_239",240,
         "all_240_all_six_fields_match_after_merge"),
    )
    results={}
    for group,n,flag in tests:
        value=_six_fields(groups.get(group),n)
        if type(groups.get(flag)) is not bool or groups[flag]!=value:
            raise ValueError("Contradictory merge diagnostic: "+flag)
        results[flag]=value
    # Verify the separate 09:30 record contributes to the Parquet five-minute
    # interval; it may be zero-volume in some legitimate historical samples.
    fifth=_six_fields(
        r.get("parquet_opening_241_in_first_five_minute_vs_five_minute"),48)
    results["parquet_opening_included_five_minute_all_fields_match"]=fifth
    return {
        "symbol":r["symbol"],"date":r["date"],
        "safe_source_report_sha256":raw_digest,
        "first_minute_merge_matches":results[
            "first_minute_all_six_fields_match_after_merge"],
        "remaining_239_match":results[
            "remaining_239_all_six_fields_match"],
        "reconstructed_240_match":results[
            "all_240_all_six_fields_match_after_merge"],
        "parquet_opening_included_five_minute_matches":fifth,
        "all_required_diagnostics_match":all(results.values()),
        "opening_nonzero_volume":opening.get("opening_zero_volume") is False,
        "opening_nonzero_amount":opening.get("opening_zero_amount") is False,
        "native_full_source_sha256":r["tdx_full_source_sha256"],
        "parquet_manifest_fingerprints_stat_only":{
            period:provenance[period]["source_manifest_stat_only_sha256"]
            for period in ("1min","5min")},
    }


def summarize(sources):
    if not 1<=len(sources)<=MAX_REPORTS:
        raise ValueError("Supply 1..12 safe evidence reports")
    selected=[]
    seen=set()
    for file in sources:
        report,digest=_load(file)
        evidence=_validate(report,digest)
        identity=(evidence["symbol"],evidence["date"])
        if identity in seen:
            raise ValueError("Duplicate symbol-day evidence")
        seen.add(identity)
        selected.append(evidence)
    selected.sort(key=lambda x:(x["date"],x["symbol"]))
    symbols={item["symbol"] for item in selected}
    days={item["date"] for item in selected}
    all_match=all(item["all_required_diagnostics_match"] for item in selected)
    target_met=(len(selected)>=6 and len(symbols)>=2 and len(days)>=3)
    if not all_match:
        verdict="disagreement_observed_do_not_apply_mapping"
    elif not target_met:
        verdict="matched_but_exploratory_cohort_too_small"
    else:
        verdict="exploratory_sample_target_met_not_certified"
    return {
        "format":FORMAT,
        "evidence_only_no_source_market_bars_read":True,
        "unique_stock_days":len(selected),"distinct_symbols":len(symbols),
        "distinct_dates":len(days),
        "exploratory_target":{"minimum_stock_days":6,
                              "minimum_symbols":2,"minimum_dates":3},
        "exploratory_target_met":target_met,
        "all_supplied_stock_days_match":all_match,
        "verdict":verdict,
        "samples":selected,
        "input_reports_not_cryptographically_authenticated":True,
        "parquet_source_manifests_are_stat_only":True,
        "one_stock_day_does_not_prove_market_wide_mapping":True,
        "production_mapping_certified":False,
        "eligible_for_automatic_production_union":False,
        "private_overlay_or_original_market_data_modified":False,
        "no_raw_ohlcva_or_intraday_times_in_report":True,
    }


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report",action="append",required=True,type=Path,
                    help="Existing SAFE native-vs-purchased 1min opening JSON under reports/")
    ap.add_argument("--read-only",action="store_true",required=True)
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args(argv)
    try:
        out=_inside_reports(args.out,exists=False)
        result=summarize(args.report)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as fd:
            json.dump(result,fd,indent=2,ensure_ascii=False,allow_nan=False)
            fd.write("\n")
        print("Saved safe cohort-only summary:",out)
        print("Evidence samples:",result["unique_stock_days"],
              "verdict:",result["verdict"])
        print("Original OHLCVA and automatic production union are untouched.")
    except (ValueError,OSError,TypeError,OverflowError,KeyError) as exc:
        ap.error(str(exc))


if __name__=="__main__":
    main()
