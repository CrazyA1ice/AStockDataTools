#!/usr/bin/env python3
"""Summarize already-produced SAFE 241->240 candidate preview reports.

Evidence-only, NOT a conversion, mapping certification, or production union.
Optionally reconcile each candidate preview with an independent existing SAFE
minute-opening audit cohort. Never reads licensed raw OHLCVA.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "tdx_parquet_preview_cohort_existing_gate",
    HERE/"summarize-tdx-parquet-minute-evidence-readonly.py")
cohort=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cohort)
FORMAT="AStockDataTools bounded 241-to-240 read-only candidate preview cohort v1"
SOURCE_FORMAT="AStockDataTools read-only TDX-aligned Parquet 241-to-240 minute candidate preview v1"
FIELDS=cohort.FIELDS
SHA=cohort.SHA
STOCK=cohort.STOCK
MAX_REPORTS=12
MAX_BYTES=256*1024
GROUPS={
    "candidate_vs_native_first_minute":(1,"first_candidate_matches_native"),
    "candidate_vs_native_remaining_239":(239,"remaining_239_match_native"),
    "candidate_vs_native_full_240":(240,"candidate_240_matches_native"),
    "candidate_240_to_purchased_48_five_minute":(48,"candidate_5min_matches_purchased_5min"),
}
GRID={
    "purchased_original_1min":"1min_opening_plus_end_241",
    "native_1min":"1min_end_240",
    "candidate_preview_1min":"1min_end_240",
    "purchased_original_5min":"5min_start_48",
}
LINEAGE={
    "original_purchased_minute_records":241,
    "candidate_minute_records_in_memory":240,
    "original_rows_used_by_first_candidate":2,
    "original_rows_used_by_remaining_candidates":239,
    "source_minute_records_accounted_for_once":241,
    "original_minutes_discarded":0,
    "synthetic_source_minutes_inserted":0,
}
SAFETY={
    "source_timestamp_label_semantics_not_certified":True,
    "purchased_source_manifest_not_content_authenticated":True,
    "native_source_hash_pinned_across_both_native_reads":True,
    "private_cache_enabled":False,
    "h5_accessed":False,
    "original_sources_modified":False,
    "private_staging_or_production_union_performed":False,
    "eligible_for_automatic_production_union":False,
    "no_raw_ohlcva_or_individual_times_in_report":True,
    "candidate_ohlcva_exported":False,
    "eligible_for_staging_or_automatic_production_union":False,
}


def _load(value,expected_format):
    path=cohort._inside_reports(value)
    start=path.stat()
    if not 0<start.st_size<=MAX_BYTES:
        raise ValueError("SAFE preview report empty or over byte limit")
    raw=path.read_bytes()
    end=path.stat()
    if (len(raw)!=start.st_size or start.st_size!=end.st_size or
            start.st_mtime_ns!=end.st_mtime_ns):
        raise ValueError("Evidence report changed while reading")
    try:
        doc=json.loads(raw.decode("utf-8"),
                       object_pairs_hook=cohort._strict_json,
                       parse_constant=lambda _: (_ for _ in ()).throw(
                           ValueError("Nonfinite JSON constant")))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ValueError("Malformed evidence JSON") from exc
    if type(doc) is not dict or doc.get("format")!=expected_format:
        raise ValueError("Unsupported evidence report format")
    return doc,hashlib.sha256(raw).hexdigest()


def _date(value):
    if type(value) is not str:
        raise ValueError("Missing canonical stock-day")
    try:
        d=date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid ISO date") from exc
    if d.isoformat()!=value:
        raise ValueError("Non-canonical date")
    return value


def _hash(value):
    if type(value) is not str or not SHA.fullmatch(value):
        raise ValueError("Missing or invalid source hash")
    return value


def _fields(metrics,n):
    if type(metrics) is not dict or set(metrics)!=set(FIELDS):
        raise ValueError("Missing/extra six-field comparison")
    maxima={}
    checks=[]
    for name in FIELDS:
        m=metrics[name]
        if type(m) is not dict:
            raise ValueError("Malformed comparison field")
        required={"n","within_diagnostic_tolerance",
                  "max_relative_error","mean_relative_error"}
        extras=(set() if name in FIELDS[:4] else {
            "ratio_actual_over_reference_median",
            "positive_reference_count","zero_reference_count"})
        if set(m)!=required|extras:
            raise ValueError("Unexpected field metric structure")
        count=m["within_diagnostic_tolerance"]
        mx=m["max_relative_error"]
        mean=m["mean_relative_error"]
        if (type(m["n"]) is not int or m["n"]!=n or
                type(count) is not int or not 0<=count<=n or
                type(mx) not in (int,float) or not math.isfinite(mx) or
                not 0<=mx<1e20 or
                type(mean) not in (int,float) or not math.isfinite(mean) or
                not 0<=mean<=mx+1e-9):
            raise ValueError("Invalid six-field metric value or count")
        if name in ("volume","amount"):
            pos=m["positive_reference_count"]
            zero=m["zero_reference_count"]
            ratio=m["ratio_actual_over_reference_median"]
            if (type(pos) is not int or type(zero) is not int or
                    pos+zero!=n or min(pos,zero)<0 or
                    (ratio is not None and
                     (type(ratio) not in (int,float) or
                      not math.isfinite(ratio) or ratio<0))):
                raise ValueError("Invalid volume/amount support count or ratio")
        maxima[name]=mx
        checks.append(count==n)
    return all(checks),maxima


def _validate_preview(r,report_sha):
    symbol=r.get("symbol")
    if type(symbol) is not str or not STOCK.fullmatch(symbol):
        raise ValueError("Noncanonical preview stock")
    day=_date(r.get("date"))
    native_hash=_hash(r.get("native_source_content_sha256"))
    expected_basename=symbol.lower()+".lc1"
    if r.get("native_source_basename")!=expected_basename:
        raise ValueError("Native TDX basename does not match symbol")
    if r.get("source_and_candidate_grid")!=GRID:
        raise ValueError("Unexpected candidate/raw timestamp grids")
    provenance=r.get("purchased_source_stat_only_provenance")
    if type(provenance) is not dict or set(provenance)!={"1min","5min"}:
        raise ValueError("Missing Parquet manifest evidence")
    pq={}
    for period,n in (("1min",241),("5min",48)):
        p=provenance[period]
        if (type(p) is not dict or
                p.get("source_manifest_is_stat_only_not_content_authenticated") is not True or
                type(p.get("matching_bar_count")) is not int or
                p["matching_bar_count"]!=n):
            raise ValueError("Malformed purchased source manifest")
        pq[period]=_hash(p.get("source_manifest_stat_only_sha256"))
    lineage=r.get("mapping_lineage_summary")
    if type(lineage) is not dict:
        raise ValueError("Missing full minute lineage")
    for name,expected in LINEAGE.items():
        if type(lineage.get(name)) is not int or lineage[name]!=expected:
            raise ValueError("Candidate does not account for all 241 source rows")
    for name in ("first_candidate_source_rows_folded_not_deleted",
                 "all_source_records_preserved_in_original_files",
                 "candidate_end_minute_labels_are_hypothetical"):
        if type(lineage.get(name)) is not bool or lineage[name] is not True:
            raise ValueError("Incomplete candidate lineage safety contract")
    for name,expected in SAFETY.items():
        if type(r.get(name)) is not bool or r[name] is not expected:
            raise ValueError("Unsafe preview report flag: "+name)

    gates=r.get("gates")
    if type(gates) is not dict or set(gates)!={
            *[v[1] for v in GROUPS.values()],
            "diagnostic_preview_consistent"}:
        raise ValueError("Malformed preview gates")
    verdict_matches=[]
    all_maxima={}
    for name,(n,gate) in GROUPS.items():
        okay,maxima=_fields(r.get(name),n)
        if type(gates[gate]) is not bool or gates[gate] is not okay:
            raise ValueError("Contradictory six-field preview gate: "+gate)
        verdict_matches.append(okay)
        if name=="candidate_vs_native_full_240":
            all_maxima=maxima
    matched=all(verdict_matches)
    if (type(gates["diagnostic_preview_consistent"]) is not bool
            or gates["diagnostic_preview_consistent"] is not matched):
        raise ValueError("Contradictory preview overall result")
    verdict=("diagnostic_candidate_matches_both_sources_not_production_certified"
             if matched else "diagnostic_candidate_mismatch_do_not_materialize")
    if r.get("preview_verdict")!=verdict:
        raise ValueError("Contradictory preview verdict")
    return {
        "symbol":symbol,"date":day,"preview_safe_report_sha256":report_sha,
        "native_full_source_sha256":native_hash,
        "parquet_manifest_fingerprints_stat_only":pq,
        "first_candidate_matches_native":verdict_matches[0],
        "remaining_239_match_native":verdict_matches[1],
        "candidate_240_matches_native":verdict_matches[2],
        "candidate_5min_matches_purchased_5min":verdict_matches[3],
        "all_preview_diagnostics_match":matched,
        "full_240_max_relative_error_by_field":all_maxima,
        "original_241_rows_accounted_once":True,
    }


def _cohort_baseline(path):
    baseline,_digest=_load(path,cohort.FORMAT)
    if (baseline.get("evidence_only_no_source_market_bars_read") is not True or
            baseline.get("production_mapping_certified") is not False or
            baseline.get("eligible_for_automatic_production_union") is not False or
            baseline.get("parquet_source_manifests_are_stat_only") is not True or
            baseline.get("no_raw_ohlcva_or_intraday_times_in_report") is not True):
        raise ValueError("Unsafe historical audit-cohort baseline")
    samples=baseline.get("samples")
    if type(samples) is not list or not 1<=len(samples)<=MAX_REPORTS:
        raise ValueError("Invalid historical cohort sample list")
    seen={}
    for sample in samples:
        if type(sample) is not dict:
            raise ValueError("Malformed historical cohort sample")
        symbol=sample.get("symbol")
        if type(symbol) is not str or not STOCK.fullmatch(symbol):
            raise ValueError("Malformed historical cohort stock")
        day=_date(sample.get("date"))
        key=(symbol,day)
        if key in seen:
            raise ValueError("Duplicate historical cohort stock-day")
        if type(sample.get("all_required_diagnostics_match")) is not bool:
            raise ValueError("Missing historical cohort verdict")
        p=sample.get("parquet_manifest_fingerprints_stat_only")
        if type(p) is not dict or set(p)!={"1min","5min"}:
            raise ValueError("Bad historical cohort manifest keys")
        seen[key]={
            "native":_hash(sample.get("native_full_source_sha256")),
            "pq":{period:_hash(p[period]) for period in ("1min","5min")},
            "match":sample["all_required_diagnostics_match"],
        }
    if (type(baseline.get("unique_stock_days")) is not int or
            baseline["unique_stock_days"]!=len(seen) or
            type(baseline.get("distinct_symbols")) is not int or
            baseline["distinct_symbols"]!=len({k[0] for k in seen}) or
            type(baseline.get("distinct_dates")) is not int or
            baseline["distinct_dates"]!=len({k[1] for k in seen})):
        raise ValueError("Contradictory historical cohort counts")
    return seen


def summarize(sources,baseline_file=None):
    if not 1<=len(sources)<=MAX_REPORTS:
        raise ValueError("Supply 1..12 SAFE preview reports")
    rows=[]
    ids=set()
    for f in sources:
        r,digest=_load(f,SOURCE_FORMAT)
        parsed=_validate_preview(r,digest)
        key=(parsed["symbol"],parsed["date"])
        if key in ids:
            raise ValueError("Duplicate candidate preview stock-day")
        ids.add(key)
        rows.append(parsed)
    if baseline_file is not None:
        before=_cohort_baseline(baseline_file)
        if set(before)!=ids:
            raise ValueError("Historical audit cohort and preview stock-days differ")
        for row in rows:
            ref=before[(row["symbol"],row["date"])]
            if (ref["native"]!=row["native_full_source_sha256"] or
                    ref["pq"]!=row["parquet_manifest_fingerprints_stat_only"] or
                    ref["match"]!=row["all_preview_diagnostics_match"]):
                raise ValueError("Historical audit vs candidate preview provenance/verdict mismatch")
    rows.sort(key=lambda x:(x["date"],x["symbol"]))
    symbols={x["symbol"] for x in rows}
    days={x["date"] for x in rows}
    matched=all(r["all_preview_diagnostics_match"] for r in rows)
    target=len(rows)>=6 and len(symbols)>=2 and len(days)>=3
    verdict=("preview_disagreement_do_not_materialize" if not matched else
             "exploratory_preview_target_met_not_certified" if target else
             "matched_but_preview_sample_too_small")
    return {
        "format":FORMAT,
        "unique_stock_days":len(rows),
        "distinct_symbols":len(symbols),"distinct_dates":len(days),
        "exploratory_target_met":target,
        "all_supplied_previews_match":matched,
        "original_audit_cohort_crosschecked":baseline_file is not None,
        "verdict":verdict,"samples":rows,
        "original_ohlcva_never_read_from_market_sources":True,
        "input_reports_not_cryptographically_authenticated":True,
        "purchased_parquet_manifests_remain_stat_only":True,
        "candidate_views_never_materialized":True,
        "production_mapping_certified":False,
        "eligible_for_automatic_production_union":False,
        "no_raw_ohlcva_or_intraday_times_in_report":True,
    }


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report",action="append",required=True,type=Path)
    ap.add_argument("--cohort",type=Path,help="Optional existing SAFE minute audit cohort")
    ap.add_argument("--read-only",required=True,action="store_true")
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args(argv)
    try:
        out=cohort._inside_reports(args.out,exists=False)
        result=summarize(args.report,args.cohort)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as fd:
            json.dump(result,fd,indent=2,ensure_ascii=False,allow_nan=False)
            fd.write("\n")
        print("Saved SAFE preview-only cohort:",out)
        print("Preview samples:",result["unique_stock_days"],
              "verdict:",result["verdict"])
        print("No original market bars read or production union performed.")
    except (ValueError,TypeError,OSError,OverflowError,KeyError) as exc:
        ap.error(str(exc))


if __name__=="__main__":
    main()
