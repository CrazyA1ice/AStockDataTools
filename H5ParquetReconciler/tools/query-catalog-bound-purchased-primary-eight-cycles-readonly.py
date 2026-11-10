#!/usr/bin/env python3
"""Explicit SHA-version-bound eight-cycle purchased-first RESEARCH query.

One immutable source catalog is REQUIRED. Every invocation re-assembles the
original purchased footers/file-stat identities, all October private highcycle
receipt/Parquet/H5 5min SHA, and four-day 1/5min private SHA. It REFUSES to
query if current sources no longer reproduce the requested catalog payload.
The only licensed OHLCVA result is local in-memory Python API; CLI outputs
aggregate counts/provenance WITHOUT prices. Nothing is promoted or written.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
CYCLE_ORDER=("1min","5min","15min","30min","60min","day","week","month")
MINUTE=frozenset(("1min","5min"))
HIGH=frozenset(("15min","30min","60min"))
H5_FALLBACK=MINUTE|HIGH
CATALOG_SHA=re.compile(r"[0-9a-f]{64}\Z")
MAX_CATALOG_BYTES=4*1024*1024
STATUS="purchased_primary_catalog_sha_bound_eight_cycle_research_query_v1"

def _load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

CATALOG=_load("bound_original_purchased_and_private_source_catalog",
              "build-purchased-primary-eight-cycle-private-source-catalog.py")
ALL=_load("bound_original_purchased_eight_cycle_reader",
          "query-purchased-primary-all-eight-cycles-readonly.py")
HIGHQUERY=_load("bound_purchased_primary_sha_verified_highcycle_reader",
                "query-purchased-primary-with-private-highcycle-readonly.py")

def _no_duplicate_keys(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError("Duplicate key in immutable catalog JSON")
        result[key]=value
    return result

def catalog_path(version):
    if type(version) is not str or CATALOG_SHA.fullmatch(version) is None:
        raise ValueError("Explicit lowercase 64-hex source catalog SHA256 required")
    module=CATALOG.MODULE
    base=module/"work"/"unified_parquet"/"source_catalog"
    for path in (module,module/"work",module/"work"/"unified_parquet",base):
        if path.is_symlink():
            raise ValueError("Symlink in private source catalog ancestry")
    if not base.is_dir() or not base.resolve().is_relative_to(module.resolve()):
        raise ValueError("Immutable private source catalog directory unavailable")
    target=base/("catalog_"+version+".json")
    if (target.is_symlink() or not target.is_file()
            or not target.resolve().is_relative_to(base.resolve())):
        raise ValueError("Explicit immutable catalog version file missing or unsafe")
    if not 1<=target.stat().st_size<=MAX_CATALOG_BYTES:
        raise ValueError("Unexpected immutable source catalog metadata size")
    return target

def validate_version(root, version):
    """Prove request's version is byte-exact and sources still match it."""
    path=catalog_path(version)
    original=path.read_bytes()
    try:
        recorded=json.loads(original,object_pairs_hook=_no_duplicate_keys)
    except (ValueError,UnicodeDecodeError,TypeError) as exc:
        raise ValueError("Immutable source catalog metadata invalid") from exc
    if type(recorded) is not dict or set(recorded)!={"catalog_sha256","payload"}:
        raise ValueError("Immutable source catalog envelope malformed")
    if recorded["catalog_sha256"]!=version or not isinstance(recorded["payload"],dict):
        raise ValueError("Explicit SHA does not identify source catalog payload")
    if hashlib.sha256(CATALOG._json(recorded["payload"])).hexdigest()!=version:
        raise ValueError("Catalog SHA256 differs from its source reference payload")
    if original!=CATALOG._json(recorded):
        raise ValueError("Noncanonical/modified immutable source catalog bytes")
    payload=recorded["payload"]
    if (payload.get("status")!=CATALOG.STATUS
            or payload.get("periods")!=list(CYCLE_ORDER)
            or payload.get("purchased_reference_mode")!=
               "original_parquet_file_refs_not_copied"
            or payload.get("research_query_explicit_opt_in_required") is not True
            or payload.get("original_market_files_modified") is not False
            or payload.get("market_OHLCVA_read_or_copied_for_catalog") is not False
            or payload.get("new_market_index_or_parquet_materialized") is not False
            or payload.get("production_or_private_active_pointer_modified") is not False
            or payload.get("ready_for_production_merge") is not False
            or payload.get("ready_for_h5_mirror") is not False
            or payload.get("vendor_units_certified") is not False
            or payload.get("timestamp_semantics_certified") is not False
            or payload.get("corporate_actions_certified") is not False
            or payload.get("full_historical_stockday_key_coverage_certified") is not False):
        raise ValueError("Catalog is not an approved research-only source version")
    if (payload.get("purchased",{}).get("purchased_source_files_copied") is not False
            or payload.get("purchased",{}).get(
                "original_purchased_file_identity_is_stat_not_full_content_sha256"
            ) is not True
            or payload.get("private_research_candidates",{}).get(
                "all_private_candidates_research_only") is not True):
        raise ValueError("Catalog source identity or research-only flags unsafe")
    # Trust neither filename nor a frozen catalog. Re-run the already proven
    # source-only catalog builder in read-only mode, including the physical
    # SHA of ALL preexisting private highcycles and H5 1/5min gaps.
    live=CATALOG.seal(CATALOG.assemble(Path(root)))
    if live!=recorded:
        raise ValueError(
            "Requested source catalog is stale: original Parquet stat/footer "
            "or private H5 candidate receipt/physical SHA changed")
    if path.read_bytes()!=original:
        raise ValueError("Private catalog changed during source-version validation")
    ref_files=sum(len(v) for v in payload["purchased"][
        "original_source_files_by_period_year"].values())
    return {
        "catalog_sha256":version,
        "purchased_original_file_refs":ref_files,
        "highcycle_candidate_stockdays":sum(payload[
            "private_research_candidates"]["stockdays_by_date"].values()),
        "highcycle_candidate_rows":payload[
            "private_research_candidates"]["highcycle_total_candidate_rows"],
        "verified_private_minute_refs":len(payload[
            "private_research_candidates"]["minute_h5_gap_private_references"]),
        "original_parquet_identity_is_stat_not_full_content_sha":True,
        "all_private_candidate_physical_sha_revalidated":True,
        "full_historical_security_key_coverage_certified":False,
        "catalog_path":path,
        "catalog_bytes":original,
    }

def query_bundle(root,symbol,periods,first,last,version,*,allow_private_gap=False,
                 max_candidate_rows=30000000,max_result_bars=10000):
    """Return {period: original OHLCVA rows} ONLY to the local Python caller."""
    if (type(periods) not in (list,tuple) or not periods
            or len(set(periods))!=len(periods)
            or any(p not in CYCLE_ORDER for p in periods)):
        raise ValueError("Explicit unique eight-cycle K-line periods required")
    if type(allow_private_gap) is not bool:
        raise ValueError("Private H5 research-only opt-in must be boolean")
    # Cheap request validation before the potentially expensive full source
    # SHA+footer audit. All periods share the same single 1..31-day window.
    canonical,start,end=ALL.PURCHASED.request_dates(
        symbol,periods[0],first,last,max_candidate_rows,max_result_bars)
    checked=validate_version(root,version)
    results={}
    safe=[]
    for period in periods:
        if period in HIGH:
            r=HIGHQUERY.query_bars(
                root,canonical,period,start.isoformat(),end.isoformat(),
                allow_private_highcycle=allow_private_gap,
                max_candidate_rows=max_candidate_rows,
                max_result_bars=max_result_bars)
            s=r["safe_summary"]
            if (s.get("status")!=HIGHQUERY.OUTPUT_STATUS
                    or s.get("ready_for_production_query") is not False
                    or s.get("original_market_files_modified") is not False
                    or s.get("new_market_or_index_files_written") is not False
                    or s.get("private_or_production_active_pointer_modified") is not False
                    or s.get("vendor_physical_units_certified") is not False):
                raise ValueError("Highcycle router no longer research-only")
        else:
            r=ALL.query_bars(
                root,canonical,period,start.isoformat(),end.isoformat(),
                allow_verified_private_h5=allow_private_gap and period in MINUTE,
                max_candidate_rows=max_candidate_rows,
                max_result_bars=max_result_bars)
            s=r["safe_summary"]
            if (s.get("production_query_activated") is not False
                    or s.get("original_market_files_modified") is not False
                    or s.get("new_market_or_index_files_written") is not False
                    or s.get("vendor_physical_units_certified") is not False):
                raise ValueError("Purchased/minute/day/week/month router unsafe")
        bars=r["bars"]
        sources=s["bars_by_source"]
        if (s.get("period")!=period or s.get("symbol")!=canonical
                or s.get("matching_bar_count")!=len(bars)
                or type(sources) is not dict
                or any(type(n) is not int or n<0 for n in sources.values())
                or sum(sources.values())!=len(bars)
                or len(bars)>max_result_bars
                or any(b.get("symbol")!=canonical or b.get("period")!=period
                       for b in bars)
                or len({b["source_timestamp_ms"] for b in bars})!=len(bars)):
            raise ValueError("Untrusted period routing or source row conservation")
        if (not allow_private_gap and
                any(name not in ("purchased_parquet",) and n>0
                    for name,n in sources.items())):
            raise ValueError("Unapproved H5 candidate returned without explicit opt-in")
        if period in ("day","week","month") and any(
                name!="purchased_parquet" and n>0
                for name,n in sources.items()):
            raise ValueError("Day/week/month were NOT included as private catalog overlays")
        results[period]=bars
        safe.append({
            "period":period,
            "matching_bar_count":len(bars),
            "bars_by_source":sources,
            "private_gap_requested":allow_private_gap and period in H5_FALLBACK,
            "source_priority":"purchased_Parquet_over_private_H5_complete_stockday",
            "candidate_vendor_units_certified":False,
            "production_activated":False,
        })
    # Detect an unexpected catalog version-file overwrite DURING the query.
    if checked["catalog_path"].read_bytes()!=checked["catalog_bytes"]:
        raise ValueError("Immutable source catalog modified during bounded query")
    return {
        "bars_by_period":results,
        "safe_summary":{
            "status":STATUS,
            "symbol":canonical,"from_day":start.isoformat(),
            "through_day":end.isoformat(),
            "catalog_sha256":checked["catalog_sha256"],
            "catalog_all_purchased_and_private_sources_revalidated_at_start":True,
            "purchased_original_file_refs":checked["purchased_original_file_refs"],
            "h5_private_minute_refs":checked["verified_private_minute_refs"],
            "highcycle_private_candidate_stockdays":
                checked["highcycle_candidate_stockdays"],
            "highcycle_private_candidate_rows":checked["highcycle_candidate_rows"],
            "periods":safe,
            "matching_bars_across_requested_cycles":sum(
                v["matching_bar_count"] for v in safe),
            "private_h5_gap_explicitly_enabled":allow_private_gap,
            "purchase_reference_identity_is_stat_not_full_content_sha256":True,
            "private_candidate_source_and_file_shas_revalidated":True,
            "day_week_month_candidate_overlays_not_registered_here":True,
            "corporate_adjustments_certified":False,
            "time_label_semantics_certified":False,
            "vendor_physical_units_certified":False,
            "ready_for_production_query":False,
            "ready_for_h5_mirror":False,
            "original_market_files_modified":False,
            "new_market_or_index_files_written":False,
            "production_query_activated":False,
            "no_raw_ohlcva_in_safe_summary":True,
        },
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--catalog-sha256",required=True)
    p.add_argument("--symbol",required=True)
    p.add_argument("--periods",nargs="+",required=True,choices=CYCLE_ORDER)
    p.add_argument("--from-day",required=True)
    p.add_argument("--through-day",required=True)
    p.add_argument("--allow-private-gap",action="store_true",
                   help="Research opt-in to vetted H5 1/5min and derived 15/30/60min; NOT day/week/month")
    p.add_argument("--max-candidate-rows",type=int,default=30000000)
    p.add_argument("--max-result-bars",type=int,default=10000)
    a=p.parse_args(argv)
    try:
        result=query_bundle(
            a.root,a.symbol,a.periods,a.from_day,a.through_day,a.catalog_sha256,
            allow_private_gap=a.allow_private_gap,
            max_candidate_rows=a.max_candidate_rows,
            max_result_bars=a.max_result_bars)
    except (ValueError,TypeError,KeyError,OSError,RuntimeError) as exc:
        p.error("Catalog-bound purchased-primary research query NOT ACCEPTED: "+
                type(exc).__name__+": "+str(exc))
    print("CATALOG_BOUND_EIGHT_CYCLE_READONLY_QUERY="+json.dumps(
        result["safe_summary"],ensure_ascii=False,sort_keys=True,
        separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
