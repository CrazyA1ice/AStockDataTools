#!/usr/bin/env python3
"""Read-only OFFLINE rehash of the 26-day factor proof and five prior SAFE files.

Rehash all seven actual SAFE byte streams, re-run both aggregate evidence
validators and load the SHA-addressed private 22,274-candidate version through
its established registry verifier. This checks local evidence integrity, NOT
source/vendor authenticity, OHLCVA units, adjustment or production permission.
Never opens original H5 or purchased Parquet; never exports individual bars.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools offline 26-day source SAFE bytes plus private version integrity gate v1"
EXPECTED_ROLES=(
    "real_raw_stock_day",
    "real_native_stock_day",
    "same_month_heldout",
    "annual_2025_key_only",
    "crossyear_holdout",
)


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BRIDGE=load("offline_26_source_aggregate",
            "audit-private-day-26-factor-evidence-offline.py")
REG=load("offline_26_immutable_private_registry",
         "register-private-combined-day-22274-version.py")


def bounded_source(file):
    # Reuse established module/reports confinement and max-JSON safeguards.
    p=BRIDGE.reports_json(file,True)
    raw=p.read_bytes()
    if not 0<len(raw)<=BRIDGE.MAX_JSON:
        raise ValueError("SAFE source grew beyond aggregate limit")
    return raw,hashlib.sha256(raw).hexdigest()


def verify_inputs(bridge,prior,addition,role_files):
    if type(role_files) is not dict or set(role_files)!=set(EXPECTED_ROLES):
        raise ValueError("Exactly five named underlying historical SAFE paths required")
    named={"bridge_26":bridge,"ten":prior,"sixteen":addition,**role_files}
    if len({Path(p).resolve() for p in named.values()})!=len(named):
        raise ValueError("Each provenance SAFE must be a different source file")
    sources={}
    for role,p in named.items():
        raw,sha=bounded_source(p)
        try:
            parsed=json.loads(raw)
        except (ValueError,UnicodeError):
            raise ValueError("Invalid provenance SAFE JSON") from None
        if type(parsed) is not dict:
            raise ValueError("Malformed provenance SAFE document")
        sources[role]=(parsed,sha)
    aggregate=sources["bridge_26"][0]
    previous=sources["ten"][0]
    newer=sources["sixteen"][0]
    BRIDGE.check_prior(previous)
    _,accepted=BRIDGE.check_stratified(newer)
    expected={
        "prior_10_stockdays":sources["ten"][1],
        "new_fixed_16_stockdays":sources["sixteen"][1],
    }
    if (aggregate.get("format")!=BRIDGE.FORMAT
            or aggregate.get("status")!="26_sample_aggregate_evidence_only_vendor_units_blocked"
            or aggregate.get("registered_private_version_sha256")!=BRIDGE.VERSION
            or aggregate.get("total_distinct_daily_stockday_factor_observations")!=26
            or aggregate.get("original_10_distinct_stockdays_numeric_candidates_match") is not True
            or aggregate.get("additional_16_distinct_stockdays_numeric_candidates_match") is not accepted
            or aggregate.get("all_26_candidate_factors_matched") is not accepted
            or aggregate.get("source_aggregate_safe_sha256")!=expected
            or aggregate.get("prior_five_source_safe_sha256")!=previous["five_safe_sha256"]
            or aggregate.get("prior_five_source_files_independently_reopened") is not False
            or aggregate.get("private_immutable_registry_independently_loaded") is not False
            or aggregate.get("unresolved_independent_certification_blockers")!=list(BRIDGE.BLOCKERS)
            or aggregate.get("quarantined_2026_07_16_stockday_bars_not_included")!=5):
        raise ValueError("Linked 26-stockday SAFE has unexpected content or hashes")
    for k in (
        "candidate_source_units_certified",
        "price_adjustment_basis_certified",
        "vendor_amount_rounding_policy_certified",
        "source_timestamp_semantics_certified",
        "licensed_vendor_physical_price_volume_amount_units_certified",
        "all_22274_private_stockday_candidates_individually_certified",
        "ready_for_production_query",
        "ready_for_automatic_market_merge",
        "ready_for_full_market_mirror",
        "source_market_files_opened",
        "licensed_ohlcva_or_individual_stock_symbols_exported",
        "private_source_files_or_active_pointers_written",
        "original_h5_or_purchased_parquet_modified",
    ):
        if aggregate.get(k) is not False:
            raise ValueError("Linked evidence improperly claims production authority")
    if (type(previous.get("five_safe_sha256")) is not dict
            or set(previous["five_safe_sha256"])!=set(EXPECTED_ROLES)):
        raise ValueError("Existing original five-SAFE ancestry incomplete")
    for role in EXPECTED_ROLES:
        if sources[role][1]!=previous["five_safe_sha256"][role]:
            raise ValueError("Historical underlying SAFE byte SHA mismatch")
    return sources,accepted


def audit(bridge,prior,addition,role_files,version_sha256,out):
    dest=BRIDGE.reports_json(out,False)
    if dest.resolve() in {Path(x).resolve() for x in (bridge,prior,addition,*role_files.values())}:
        raise ValueError("Cannot overwrite an evidence source SAFE")
    if version_sha256 != BRIDGE.VERSION:
        raise ValueError("Wrong registered 22,274-stockday version")
    if REG.LOCK.exists() or REG.LOCK.is_symlink():
        raise ValueError("Private registered version is being modified")
    sources,matched=verify_inputs(bridge,prior,addition,role_files)
    entry=REG.load_version(version_sha256)
    if (entry.get("version_sha256")!=version_sha256
            or entry.get("candidate_total_new_stockday_rows")!=22274
            or entry.get("whole_day_candidate_rows")!=22191
            or entry.get("mixed_stockday_candidate_rows")!=83
            or entry.get("quarantined_2026_07_16_stockday_bars_not_included")!=5
            or entry.get("ready_for_production_query") is not False
            or entry.get("candidate_source_units_certified") is not False):
        raise ValueError("Registered private version cannot qualify evidence")
    # Guard against replacing any source or registered manifest mid-audit.
    again,matched_again=verify_inputs(bridge,prior,addition,role_files)
    second=REG.load_version(version_sha256)
    if (matched_again is not matched
            or {k:v[1] for k,v in sources.items()}!={k:v[1] for k,v in again.items()}
            or second!=entry
            or REG.LOCK.exists() or REG.LOCK.is_symlink()):
        raise ValueError("Provenance SAFE or immutable registry drift during verification")
    safe={
        "format":FORMAT,
        "status":"seven_real_safe_files_rehashed_and_immutable_private_manifest_verified_not_licensed_certification",
        "registered_private_version_sha256":version_sha256,
        "historical_underlying_safe_count":5,
        "total_aggregate_safe_count":2,
        "bridge_safe_count":1,
        "total_26_stockday_candidate_observations":26,
        "all_26_candidate_numeric_factors_matched":matched,
        "source_safe_sha256":{k:v[1] for k,v in sources.items()},
        "five_underlying_source_safe_files_independently_rehashed":True,
        "two_aggregate_source_safe_files_independently_rehashed":True,
        "old_five_safe_links_match_actual_bytes":True,
        "immutable_version_content_address_and_referenced_safes_rechecked":True,
        "original_market_files_reopened":False,
        "vendor_document_examined_or_authenticated":False,
        "candidate_source_units_certified":False,
        "source_adjustment_and_timestamp_semantics_certified":False,
        "universal_numeric_factor_certified":False,
        "all_22274_private_stockday_candidates_individually_certified":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_production_query":False,
        "ready_for_h5_mirror":False,
        "source_market_files_written":False,
        "purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
        "no_raw_ohlcva_or_stock_symbols_exported":True,
    }
    with dest.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(safe,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bridge-safe",type=Path,required=True)
    p.add_argument("--prior-ten-safe",type=Path,required=True)
    p.add_argument("--stratified-sixteen-safe",type=Path,required=True)
    p.add_argument("--real-raw-safe",type=Path,required=True)
    p.add_argument("--real-native-safe",type=Path,required=True)
    p.add_argument("--same-month-heldout-safe",type=Path,required=True)
    p.add_argument("--annual-2025-key-only-safe",type=Path,required=True)
    p.add_argument("--crossyear-heldout-safe",type=Path,required=True)
    p.add_argument("--version-sha256",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--offline-only",action="store_true",required=True)
    a=p.parse_args(argv)
    files=dict(zip(EXPECTED_ROLES,(
        a.real_raw_safe,a.real_native_safe,
        a.same_month_heldout_safe,a.annual_2025_key_only_safe,a.crossyear_heldout_safe)))
    try:
        result=audit(a.bridge_safe,a.prior_ten_safe,a.stratified_sixteen_safe,
                     files,a.version_sha256,a.out)
        print("Historical underlying SAFE files checked:",result["historical_underlying_safe_count"])
        print("Original market data opened: False; vendor units certified: False")
        print("Evidence-only SHA report:",a.out)
    except (OSError,ValueError,KeyError,TypeError,UnicodeError,ImportError):
        p.error("Offline 26-day provenance recheck failed closed")


if __name__=="__main__":
    main()
