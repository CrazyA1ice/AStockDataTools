#!/usr/bin/env python3
"""Explicit pair-version eight-cycle purchased-primary research query.

Combine EXISTING immutable SHA-addressed eight-cycle purchased+H5 minute/high
catalog with EXISTING registered 22,274 daily H5-only candidate version.
The base eight-cycle catalog remains byte-for-byte untouched and all purchased
Parquet stays in place. This is NOT a materialization, H5 mirror or production
activation; the daily live evidence gate can create ONLY its usual SAFE
metadata under reports/, never source market files.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
STATUS="purchased_primary_catalog_and_registered_22274_day_live_research_query_v1"
DAY_SOURCES=(
    "purchased_parquet",
    "private_h5_whole_date_candidate",
    "private_h5_mixed_stockday_candidate",
)
FORMAT="AStockDataTools paired eight-cycle catalog / immutable 22274 day research v1"

def _load(tag,filename):
    spec=importlib.util.spec_from_file_location(tag,HERE/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

BOUND=_load("paired_eightcycle_sha_catalog_query",
            "query-catalog-bound-purchased-primary-eight-cycles-readonly.py")
RESOLVE=_load("paired_22274_sha_evidence_resolver",
              "resolve-registered-day-22274-evidence-offline.py")
ALL=BOUND.ALL

def paired_version(catalog_sha,day_version_sha):
    """A deterministic *research* pair identity, NOT a published production pointer."""
    if (type(catalog_sha) is not str or
            BOUND.CATALOG_SHA.fullmatch(catalog_sha) is None):
        raise ValueError("Invalid original catalog SHA256")
    if (type(day_version_sha) is not str or
            RESOLVE.SHA.fullmatch(day_version_sha) is None):
        raise ValueError("Invalid registered day version SHA256")
    body={
        "format":FORMAT,
        "purchased_primary_catalog_sha256":catalog_sha,
        "private_registered_22274_day_version_sha256":day_version_sha,
        "purchased_original_file_refs_not_copied":True,
        "daily_candidate_count":22274,
        "ready_for_production_query":False,
        "ready_for_h5_mirror":False,
    }
    digest=hashlib.sha256(json.dumps(
        body,sort_keys=True,ensure_ascii=False,separators=(",",":")
    ).encode("utf-8")).hexdigest()
    return digest

def query_bundle(root,symbol,periods,first,last,catalog_sha,day_version_sha,*,
                 allow_registered_private_day=False,
                 allow_private_minute_highcycle=False,
                 max_candidate_rows=30000000,max_result_bars=10000):
    if (type(periods) not in (tuple,list) or not periods
            or "day" not in periods
            or len(set(periods))!=len(periods)
            or any(period not in BOUND.CYCLE_ORDER for period in periods)):
        raise ValueError("Paired SHA research query requires unique periods including day")
    if (allow_registered_private_day is not True or
            type(allow_private_minute_highcycle) is not bool):
        raise ValueError("Explicit registered private-day opt-in and boolean minute/high opt-in required")
    canonical,start,end=ALL.PURCHASED.request_dates(
        symbol,"day",first,last,max_candidate_rows,max_result_bars)
    if start.year!=end.year or start.year not in (2016,2026):
        raise ValueError("Registered 22,274 day candidate evidence only covers 2016 or 2026")
    # First validate all SHA-linked registered evidence OFFLINE, with no raw
    # H5/Parquet values; never choose a latest version implicitly.
    RESOLVE.REG.load_version(day_version_sha)
    evidence=ALL.validate_private_day_evidence(RESOLVE.resolve(day_version_sha))
    if evidence["version_sha256"]!=day_version_sha:
        raise ValueError("Resolved day evidence is for another registered version")
    other=[period for period in periods if period!="day"]
    if other:
        original=BOUND.query_bundle(
            root,canonical,other,start.isoformat(),end.isoformat(),catalog_sha,
            allow_private_gap=allow_private_minute_highcycle,
            max_candidate_rows=max_candidate_rows,max_result_bars=max_result_bars)
        orig_safe=original["safe_summary"]
        if (orig_safe.get("status")!=BOUND.STATUS
                or orig_safe.get("catalog_sha256")!=catalog_sha
                or orig_safe.get("production_query_activated") is not False
                or orig_safe.get("vendor_physical_units_certified") is not False
                or orig_safe.get("private_candidate_source_and_file_shas_revalidated") is not True):
            raise ValueError("Base eight-cycle catalog source gate not verified")
        results=dict(original["bars_by_period"])
        summaries={entry["period"]:entry for entry in orig_safe["periods"]}
        original_count=orig_safe["matching_bars_across_requested_cycles"]
    else:
        BOUND.validate_version(root,catalog_sha)
        results={}
        summaries={}
        original_count=0
    # The existing registered-day API re-verifies FULL original H5+Parquet
    # exact stockday keys, 22,191 whole / 83 mixed candidates and entire
    # candidate/receipt physical SHAs on EACH invocation. Never bypass it.
    daily=ALL.query_bars(
        root,canonical,"day",start.isoformat(),end.isoformat(),
        max_candidate_rows=max_candidate_rows,
        max_result_bars=max_result_bars,
        private_day_evidence=evidence)
    day_safe=daily["safe_summary"]
    source=day_safe.get("bars_by_source")
    if (day_safe.get("period")!="day" or day_safe.get("symbol")!=canonical
            or day_safe.get("routing")!=
               "explicit_immutable_22274_day_live_verified_purchased_first"
            or day_safe.get("registered_private_day_version_sha256")!=day_version_sha
            or day_safe.get("registered_private_22274_day_overlay_explicitly_enabled") is not True
            or day_safe.get("verified_private_h5_fallback_enabled") is not False
            or day_safe.get("purchased_source_priority") is not True
            or day_safe.get("original_market_files_modified") is not False
            or day_safe.get("new_market_or_index_files_written") is not False
            or day_safe.get("production_query_activated") is not False
            or day_safe.get("vendor_physical_units_certified") is not False
            or day_safe.get("no_raw_ohlcva_in_safe_summary") is not True
            or type(source) is not dict or set(source)!=set(DAY_SOURCES)
            or any(type(source[s]) is not int or source[s]<0 for s in DAY_SOURCES)
            or sum(source.values())!=len(daily["bars"])
            or day_safe.get("matching_bar_count")!=len(daily["bars"])):
        raise ValueError("Registered private-day live source/priority gate unsafe")
    if (len({row["source_timestamp_ms"] for row in daily["bars"]})!=
            len(daily["bars"])
            or any(row["symbol"]!=canonical or row["period"]!="day"
                   or row["value_source"] not in DAY_SOURCES
                   for row in daily["bars"])):
        raise ValueError("Registered day records invalid or non-unique")
    results["day"]=daily["bars"]
    summaries["day"]={
        "period":"day",
        "matching_bar_count":len(daily["bars"]),
        "bars_by_source":source,
        "private_gap_requested":True,
        "source_priority":"purchased_Parquet_over_SHA_registered_22274_day_candidates",
        "candidate_vendor_units_certified":False,
        "production_activated":False,
        "full_original_H5_Parquet_day_source_live_reverified":True,
    }
    # Caller receives same ordering they requested. No licensed bars printed.
    bars_by_period={p:results[p] for p in periods}
    if BOUND.catalog_path(catalog_sha).is_symlink():
        raise ValueError("Base catalog became a symlink during registered day query")
    # A second catalog version check checks for modifications during the
    # expensive live-day audit, without re-reading billions of OHLCVA rows.
    BOUND.validate_version(root,catalog_sha)
    pair=paired_version(catalog_sha,day_version_sha)
    return {
        "bars_by_period":bars_by_period,
        "safe_summary":{
            "status":STATUS,
            "paired_research_version_sha256":pair,
            "original_eight_cycle_catalog_sha256":catalog_sha,
            "registered_private_day_version_sha256":day_version_sha,
            "registered_private_day_candidates":22274,
            "registered_whole_day_candidates":22191,
            "registered_mixed_stockday_candidates":83,
            "quarantined_2026_07_16_daily_candidates_excluded":5,
            "periods":[summaries[period] for period in periods],
            "symbol":canonical,
            "from_day":start.isoformat(),
            "through_day":end.isoformat(),
            "matching_bars_across_requested_cycles":original_count+len(daily["bars"]),
            "purchased_source_priority":True,
            "base_catalog_source_revalidated_at_start_and_end":True,
            "registered_day_live_original_source_reverified":True,
            "original_market_files_modified":False,
            "new_market_or_index_files_written":False,
            "only_research_SAFE_reports_may_be_created":True,
            "production_query_activated":False,
            "ready_for_production_query":False,
            "ready_for_h5_mirror":False,
            "physical_units_certified":False,
            "corporate_adjustments_certified":False,
            "time_label_semantics_certified":False,
            "no_raw_ohlcva_in_safe_summary":True,
        }
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--catalog-sha256",required=True)
    p.add_argument("--registered-day-version-sha256",required=True)
    p.add_argument("--symbol",required=True)
    p.add_argument("--periods",choices=BOUND.CYCLE_ORDER,nargs="+",required=True)
    p.add_argument("--from-day",required=True)
    p.add_argument("--through-day",required=True)
    p.add_argument("--allow-registered-private-day",action="store_true",required=True)
    p.add_argument("--allow-private-minute-highcycle",action="store_true")
    p.add_argument("--max-result-bars",type=int,default=10000)
    p.add_argument("--max-candidate-rows",type=int,default=30000000)
    a=p.parse_args(argv)
    try:
        result=query_bundle(
            a.root,a.symbol,a.periods,a.from_day,a.through_day,
            a.catalog_sha256,a.registered_day_version_sha256,
            allow_registered_private_day=a.allow_registered_private_day,
            allow_private_minute_highcycle=a.allow_private_minute_highcycle,
            max_result_bars=a.max_result_bars,
            max_candidate_rows=a.max_candidate_rows)
    except (ValueError,TypeError,KeyError,OSError,RuntimeError) as exc:
        p.error("Paired SHA source catalog+registered day NOT ACCEPTED: "+
                type(exc).__name__+": "+str(exc))
    print("CATALOG_REGISTERED_DAY_PAIRED_QUERY="+json.dumps(
        result["safe_summary"],ensure_ascii=False,sort_keys=True,
        separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
