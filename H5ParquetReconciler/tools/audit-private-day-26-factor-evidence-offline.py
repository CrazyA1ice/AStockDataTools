#!/usr/bin/env python3
"""Offline SHA-linked synthesis of 10 earlier + 16 new DAY factor observations.

No original market access, imports of Arrow/H5, private key output or source
writes. A numeric candidate evidence chain is NOT vendor-physical-unit,
adjustment-basis, rounding or production merge certification.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
VERSION="e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23"
FORMAT="AStockDataTools immutable 26-stockday daily factor evidence bridge SAFE v1"
MAX_JSON=200000
YEARS=("2016","2020","2024","2026")
PRICE=("open","high","low","close")
QUANTITY=("volume","amount")
BLOCKERS=(
    "licensed_vendor_volume_physical_unit_unknown",
    "licensed_vendor_amount_physical_unit_and_rounding_unknown",
    "licensed_vendor_price_adjustment_and_basis_unknown",
    "original_source_timestamp_and_calendar_semantics_not_certified",
    "sample_matches_do_not_prove_all_22274_candidate_daily_bars",
    "historical_symbol_master_and_special_sessions_not_certified",
)

def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

OLD=load("bridge_verified_prior_ten_factor_evidence",
         "audit-parquet-primary-day-crossyear-factor-evidence-offline.py")
NEW=load("bridge_new_stratified_16_factor_evidence",
         "probe-private-day-overlap-stratified-factors-readonly.py")


def reports_json(path,read):
    p=Path(path)
    if (REPORTS.is_symlink() or not REPORTS.is_dir() or p.is_symlink()
            or p.suffix.lower()!=".json" or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Require direct non-symlink module reports JSON")
    if read:
        if not p.is_file() or not 0<p.stat().st_size<=MAX_JSON:
            raise ValueError("Missing or oversized offline SAFE input")
    elif p.exists():
        raise ValueError("Never overwrite previous offline evidence SAFE")
    return p


def source(path):
    p=reports_json(path,True)
    raw=p.read_bytes()
    if not 0<len(raw)<=MAX_JSON:
        raise ValueError("Offline original SAFE changed size while reading")
    try:
        obj=json.loads(raw)
    except (ValueError,UnicodeError):
        raise ValueError("Invalid source SAFE JSON") from None
    if type(obj) is not dict:
        raise ValueError("Expected aggregate SAFE object")
    return obj,hashlib.sha256(raw).hexdigest()


def check_prior(item):
    if (item.get("format")!=OLD.FORMAT
            or item.get("total_distinct_daily_stock_days_with_candidate_factor_matches")!=10
            or item.get("source_discovery_stock_days")!=2
            or item.get("same_month_holdout_stock_days")!=4
            or item.get("crossyear_holdout_stock_days")!=4
            or item.get("positive_volume_factor100_sample_count")!=10
            or item.get("positive_amount_factor1000_sample_count")!=10
            or item.get("all_four_ohlc_raw_div1000_sample_count_per_field")!=10
            or item.get("native_hikyuu_281_cpp_verified_real_stock_days")!=2
            or item.get("native_cpp_tested_on_crossyear_holdouts") is not False
            or item.get("sample_numeric_factor_candidate_supported") is not True
            or item.get("candidate_raw_h5_volume_multiply")!=100
            or item.get("candidate_raw_h5_amount_multiply")!=1000
            or item.get("candidate_raw_h5_price_divide")!=1000
            or item.get("raw_ohlcva_h5_integer_or_source_paths_exported") is not False
            or item.get("market_source_opened_or_modified_by_this_audit") is not False):
        raise ValueError("Prior 10-stockday candidate evidence invalid")
    for key in ("vendor_amount_physical_units_certified",
                "vendor_volume_physical_units_certified",
                "adjustment_and_timestamps_certified",
                "universal_period_factor_certified",
                "licensed_parquet_to_native_h5_mapping_certified",
                "ready_for_full_market_mirror",
                "ready_to_modify_parquet_primary_source"):
        if item.get(key) is not False:
            raise ValueError("Prior SAFE unexpectedly claims production/vendor certification")
    five=item.get("five_safe_sha256")
    if (type(five) is not dict or len(five)!=5
            or "crossyear_holdout" not in five
            or any(type(v) is not str or not re.fullmatch("[a-f0-9]{64}",v)
                   for v in five.values())):
        raise ValueError("Prior five-source SHA evidence is incomplete")
    return dict(five)


def check_stratified(item):
    if (item.get("format")!=NEW.FORMAT
            or item.get("state")!="fixed_historical_original_overlap_diagnostic_not_unit_certification"
            or item.get("registered_private_version_sha256")!=VERSION
            or item.get("samples_per_year")!=2
            or item.get("symbols_per_date")!=2
            or item.get("total_distinct_stockdays_compared")!=16
            or item.get("sample_years")!=[2016,2020,2024,2026]
            or item.get("hypothesis_raw_h5_price_divisor")!=1000
            or item.get("hypothesis_raw_h5_volume_multiplier")!=100
            or item.get("hypothesis_raw_h5_amount_multiplier")!=1000
            or item.get("original_h5_and_purchased_parquet_read_only") is not True
            or item.get("stock_ids_ohlcva_raw_integers_paths_not_exported") is not True
            or item.get("source_file_stat_before_after_unchanged") is not True
            or item.get("source_file_stat_is_not_cryptographic_content_proof") is not True
            or item.get("quarantined_2026_07_16_stockday_bars_not_included")!=5):
        raise ValueError("The 16-stockday cross-regime SAFE is incomplete")
    for field in ("candidate_source_units_certified",
                  "source_adjustment_and_timestamp_semantics_certified",
                  "universal_conversion_rules_across_all_stockdays_certified",
                  "ready_for_production_query","ready_for_automatic_market_merge",
                  "h5_mirror_created","source_market_files_written",
                  "purchased_parquet_replaced",
                  "private_or_production_active_pointer_modified"):
        if item.get(field) is not False:
            raise ValueError("The new stratified SAFE falsely claims source permission")
    rows=item.get("per_year_factor_counts")
    scanned=item.get("per_year_purchased_source_rows_scanned")
    groups=item.get("per_year_purchased_source_rowgroups_scanned")
    if any(type(x) is not dict or set(x)!=set(YEARS) for x in (rows,scanned,groups)):
        raise ValueError("Missing exact 2016/2020/2024/2026 year results")
    accepted=True
    summaries={}
    for year in YEARS:
        r=rows[year]
        if type(r) is not dict or r.get("paired_stockdays")!=4:
            raise ValueError("Incorrect stratified sample count")
        price=r.get("price_field_within_0p005")
        positive=r.get("positive_nonzero_pairs")
        quantity=r.get("candidate_factor_hit_pairs")
        if (type(price) is not dict or set(price)!=set(PRICE)
                or type(positive) is not dict or set(positive)!=set(QUANTITY)
                or type(quantity) is not dict or set(quantity)!=set(QUANTITY)):
            raise ValueError("Incomplete six-field factor evidence")
        for mapping in (price,positive,quantity):
            if any(type(v) is not int or not 0<=v<=4
                   for v in mapping.values()):
                raise ValueError("Invalid year sample count")
        if any(quantity[k]>positive[k] for k in QUANTITY):
            raise ValueError("Impossible quantity factor-hit evidence")
        expected=(all(price[k]==4 for k in PRICE)
                  and all(positive[k]==4 and quantity[k]==4 for k in QUANTITY))
        if r.get("all_sampled_numeric_candidates_match") is not expected:
            raise ValueError("Factor summary contradicts per-year sample counts")
        if (type(scanned[year]) is not int or not 0<scanned[year]<=5000000
                or type(groups[year]) is not int or not 0<groups[year]<=512):
            raise ValueError("Unbounded/missing original purchased row scan evidence")
        summaries[year]={"paired_stockdays":4,
                         "price_fields_within_tolerance":dict(price),
                         "positive_nonzero_pairs":dict(positive),
                         "factor_hit_pairs":dict(quantity),
                         "all_numeric_candidates_match":expected}
        accepted=accepted and expected
    if item.get("all_16_samples_numerically_within_candidate_tolerances") is not accepted:
        raise ValueError("Aggregate 16-sample conclusion contradicts year evidence")
    if item.get("numeric_mismatch_or_zero_requires_quarantine") is not (not accepted):
        raise ValueError("Aggregate quarantine rule contradicts year evidence")
    return summaries,accepted


def audit(prior_safe,stratified_safe,out):
    first=reports_json(prior_safe,True)
    second=reports_json(stratified_safe,True)
    dest=reports_json(out,False)
    if first.resolve()==second.resolve() or dest.resolve() in (first.resolve(),second.resolve()):
        raise ValueError("Prior, new and output SAFE must be distinct")
    old,old_sha=source(first)
    new,new_sha=source(second)
    ancestors=check_prior(old)
    year_rows,all_new_match=check_stratified(new)
    result={
        "format":FORMAT,
        "status":"26_sample_aggregate_evidence_only_vendor_units_blocked",
        "registered_private_version_sha256":VERSION,
        "original_10_distinct_stockdays_numeric_candidates_match":True,
        "additional_16_distinct_stockdays_numeric_candidates_match":all_new_match,
        "total_distinct_daily_stockday_factor_observations":26,
        "candidate_raw_h5_price_divisor":1000,
        "candidate_raw_h5_volume_multiplier":100,
        "candidate_raw_h5_amount_multiplier":1000,
        "per_year_new_16_sample_evidence":year_rows,
        "all_26_candidate_factors_matched":all_new_match,
        "old_real_native_hikyuu_cpp_verified_stockdays_only":2,
        "new_16_native_cpp_executed":False,
        "source_aggregate_safe_sha256":{
            "prior_10_stockdays":old_sha,"new_fixed_16_stockdays":new_sha},
        "prior_five_source_safe_sha256":ancestors,
        "unresolved_independent_certification_blockers":list(BLOCKERS),
        "licensed_vendor_physical_price_volume_amount_units_certified":False,
        "price_adjustment_basis_certified":False,
        "vendor_amount_rounding_policy_certified":False,
        "source_timestamp_semantics_certified":False,
        "candidate_source_units_certified":False,
        "all_22274_private_stockday_candidates_individually_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_full_market_mirror":False,
        "source_market_files_opened":False,
        "licensed_ohlcva_or_individual_stock_symbols_exported":False,
        "private_source_files_or_active_pointers_written":False,
        "original_h5_or_purchased_parquet_modified":False,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
    }
    with dest.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(result,f,ensure_ascii=False,sort_keys=True,indent=2)
        f.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prior-ten-safe",type=Path,required=True)
    p.add_argument("--stratified-sixteen-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--offline-evidence-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        r=audit(a.prior_ten_safe,a.stratified_sixteen_safe,a.out)
        print("Source aggregate SAFE reports: 2; distinct daily sample observations:",
              r["total_distinct_daily_stockday_factor_observations"])
        print("All candidate numeric ratios matched:",
              r["all_26_candidate_factors_matched"])
        print("Vendor physical units certified: False; production merge: False")
        print("Aggregate-only SHA-linked SAFE:",a.out)
    except (OSError,ValueError,KeyError,TypeError,UnicodeError,ImportError):
        p.error("Offline 26-stockday evidence bridge failed closed")


if __name__=="__main__":
    main()
