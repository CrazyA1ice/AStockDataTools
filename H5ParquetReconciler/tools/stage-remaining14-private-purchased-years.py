#!/usr/bin/env python3
"""Preflight, then physically stage 14 remaining purchased DAY years (2011..2025).

Excludes already independently verified 2016 and 2026. The QDC originals,
H5 source, private active pointers and all production data are READ-ONLY.
No batch completion SAFE is issued unless EVERY year is independently verified.
Everything private stays under work/unified_parquet/physical_years and all
aggregate-only receipts remain under reports; no market rows are exported.

Mode --preflight-only checks every original annual source SHA, full footer,
required Arrow field types and at most one unknown source field, and binds
genuine, independently verified 2016 and 2026 anchor SAFE reports.

Mode --materialize-and-audit requires the preflight SAFE, rechecks its SHA,
creates immutable new per-year private Parquet/SQLite directories, verifies
each via the independent historical full-row auditor, and only then publishes
an aggregate 14-year completed batch SAFE. Aborts on first failure.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load(label,file):
    spec=importlib.util.spec_from_file_location(label,HERE/file)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M=load("remaining14_historical_private_year_builder",
       "materialize-private-2011-2025-purchased-year.py")
I=load("remaining14_historical_private_year_auditor",
       "verify-private-2011-2025-purchased-year.py")
Y2026=load("remaining14_2026_source_receipt_verifier",
           "verify-private-2026-purchased-plus-h5-year.py")
YEARS=tuple(y for y in range(2011,2026) if y!=2016)
FORMAT="AStockDataTools preflight SHA-bound remaining14 historical purchased DAY years v1"
BATCH_FORMAT="AStockDataTools all14 independently audited private historical physical DAY years v1"
PURCHASED_TOTAL_24_FILES=14115707
PURCHASED_2026_NINE_MONTHS=1010350
PURCHASED_2016_YEAR=655448
EXPECTED_OTHER14_ROWS=PURCHASED_TOTAL_24_FILES-PURCHASED_2026_NINE_MONTHS-PURCHASED_2016_YEAR
HEX=re.compile("[a-f0-9]{64}\\Z")
RUN_ID=re.compile("[a-f0-9]{12}\\Z")
MAX_SAFE=500000


def report(path,exists):
    p=Path(path)
    if (M.REPORTS.is_symlink() or p.is_symlink() or p.suffix.lower()!=".json"
            or p.resolve().parent!=M.REPORTS.resolve()
            or p.exists()!=exists
            or (exists and not 0<p.stat().st_size<=MAX_SAFE)):
        raise ValueError("Only requested module reports/ SAFE with expected existence accepted")
    return p.resolve()


def read_report(path):
    p=report(path,True)
    raw=p.read_bytes()
    doc=json.loads(raw)
    if type(doc) is not dict:
        raise ValueError("Evidence report must be one JSON object")
    return doc,hashlib.sha256(raw).hexdigest()


def fixed_anchors(accepted_2016_safe,accepted_2016_audit,
                  accepted_2026_safe,accepted_2026_audit,candidate_safe):
    # Source/manifest/unique SQLite hashes are checked by these readers,
    # but the full-row independent audits were already run and are bound
    # immutably by SHA. Never silently choose between two 2016 snapshots.
    doc16,sha16,_,_,_,_=I.source(report(accepted_2016_safe,True))
    audit16,hash16=read_report(accepted_2016_audit)
    if (audit16.get("status")!=
            "independent_historical_private_physical_year_all_rows_sha_and_keys_verified"
            or audit16.get("source_materialization_safe_sha256")!=sha16
            or audit16.get("source_private_manifest_sha256")!=
                doc16["private_manifest_sha256"]
            or audit16.get("year")!=2016
            or audit16.get("private_purchased_rows_verified")!=PURCHASED_2016_YEAR
            or audit16.get("private_h5_mixed_candidate_rows_verified")!=1
            or audit16.get("private_total_rows_verified")!=PURCHASED_2016_YEAR+1
            or audit16.get("private_byte_shadow_source_float64_rows_recompared") is not True
            or audit16.get("private_verbatim_original_purchased_shadow_sha_verified") is not True
            or any(audit16.get(k) is not False for k in (
                "ready_for_automatic_market_merge","ready_for_h5_mirror",
                "ready_for_production_query","original_market_files_written"))):
        raise ValueError("2016 anchor is not an independently approved private receipt")
    doc26,sha26,_,_,_,_=Y2026.source_report(report(accepted_2026_safe,True))
    audit26,hash26=read_report(accepted_2026_audit)
    if (audit26.get("status")!=
             "independent_full_2026_private_physical_parquet_sha_values_keys_verified"
            or audit26.get("source_materialization_safe_sha256")!=sha26
            or audit26.get("source_private_physical_manifest_sha256")!=
               doc26["private_manifest_sha256"]
            or audit26.get("private_purchased_records_verified")!=PURCHASED_2026_NINE_MONTHS
            or audit26.get("private_h5_whole_candidate_rows_verified")!=22191
            or audit26.get("private_h5_mixed_candidate_rows_verified")!=82
            or audit26.get("private_total_stockday_rows_verified")!=1032623
            or any(audit26.get(k) is not False for k in (
                "ready_for_automatic_market_merge","ready_for_h5_mirror",
                "ready_for_production_query","original_market_files_modified"))):
        raise ValueError("2026 anchor is not independently approved 1032623 rows")
    candidate,source_sha,_,_=M.V.source(candidate_safe)
    if (candidate.get("source_version_sha256")!=M.SOURCE_VERSION
            or candidate.get("candidate_year_rows")!={"2016":1,"2026":22273}
            or doc16.get("source_candidate_safe_sha256")!=source_sha
            or doc26.get("source_private_candidate_safe_sha256")!=source_sha):
        raise ValueError("2016 and 2026 anchors differ in source H5 candidate snapshot")
    return {
        "accepted_2016_private_year":doc16["private_relative_directory"],
        "accepted_2016_recovery_safe_sha256":sha16,
        "accepted_2016_independent_audit_sha256":hash16,
        "accepted_2016_private_manifest_sha256":doc16["private_manifest_sha256"],
        "accepted_2026_private_year":doc26["private_relative_directory"],
        "accepted_2026_materialization_safe_sha256":sha26,
        "accepted_2026_independent_audit_sha256":hash26,
        "accepted_2026_private_manifest_sha256":doc26["private_manifest_sha256"],
        "source_h5_candidate_safe_sha256":source_sha,
        "source_private_version_sha256":M.SOURCE_VERSION,
    }


def inspect_annual_sources(root,readme_sha,manifest_sha):
    import pyarrow as pa
    import pyarrow.parquet as pq
    annual={}
    total=0
    shadow_minimum=0
    input_bytes=0
    expected={"ts","symbol",*M.PHYS.F}
    types={"ts":pa.int64(),"symbol":pa.string(),
           **{f:pa.float64() for f in M.PHYS.F}}
    for year in YEARS:
        path,record,_,_=M.purchased_input(root,year,readme_sha,manifest_sha)
        pf=pq.ParquetFile(path,memory_map=False,pre_buffer=False)
        try:
            names=pf.schema_arrow.names
            named=set(names)
            unknown=named-expected
            if (pf.metadata.num_rows!=record["rows"]
                    or not 0<record["rows"]<=M.PHYS.MAX_ROWS
                    or len(named)!=len(names)
                    or not expected.issubset(named) or len(unknown)>1
                    or any(pf.schema_arrow.field(k).type!=v
                           for k,v in types.items())):
                raise ValueError("One original annual purchased Arrow footer/schema is unsupported")
            one_unknown=len(unknown)
            if one_unknown:
                shadow_minimum+=record["size"]
            annual[str(year)]={
                "original_sha256":record["sha"],
                "original_bytes":record["size"],
                "purchased_rows":record["rows"],
                "unclassified_extra_field_count":one_unknown,
                "original_arrow_footer_rowgroups":pf.metadata.num_row_groups,
                "ready_for_h5_mirror":False,
            }
            total+=record["rows"]
            input_bytes+=record["size"]
        finally:
            pf.close()
    if total!=EXPECTED_OTHER14_ROWS:
        raise ValueError("14 purchased annual row count does not match pinned QDC 24-file inventory")
    return annual,total,input_bytes,shadow_minimum


def preflight(root,candidate_safe,readme_sha,manifest_sha,
              safe16,audit16,safe26,audit26,out):
    output=report(out,False)
    anchors=fixed_anchors(safe16,audit16,safe26,audit26,candidate_safe)
    annual,total,input_bytes,shadow_bytes=inspect_annual_sources(
        root,readme_sha,manifest_sha)
    doc={
        "format":FORMAT,
        "status":"remaining_14_purchased_years_source_sha_and_arrow_footer_verified_not_materialized",
        "years":list(YEARS),
        "historical_year_files_verified":len(YEARS),
        "purchased_original_rows":total,
        "source_original_purchased_file_bytes":input_bytes,
        "minimum_extra_column_original_shadow_bytes":shadow_bytes,
        "purchased_original_rows_all_24_bundle":PURCHASED_TOTAL_24_FILES,
        "source_readme_sha256":M.QDC.pinned_hash(readme_sha),
        "source_qdc_manifest_sha256":M.QDC.pinned_hash(manifest_sha),
        "annual":annual,
        "anchors":anchors,
        "original_vendor_sha256_per_annual_verified":True,
        "source_2016_and_2026_private_anchors_unchanged":True,
        "actual_market_rows_loaded":False,
        "original_market_files_written":False,
        "physical_parquet_or_sqlite_created":False,
        "private_or_production_active_pointer_modified":False,
        "candidate_source_units_certified":False,
        "unknown_extra_field_semantics_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "no_market_ohlcva_or_stock_symbols_in_safe":True,
    }
    with output.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(doc,stream,indent=2,sort_keys=True)
        stream.write("\n")
    return doc


def stage(root,candidate_safe,readme_sha,manifest_sha,
          safe16,audit16,safe26,audit26,preflight_safe,
          preflight_sha256,batch_id,summary_out):
    if not RUN_ID.fullmatch(str(batch_id)):
        raise ValueError("Batch ID must be exactly 12 lowercase hex characters")
    summary=report(summary_out,False)
    preflight_doc,actual_sha=read_report(preflight_safe)
    if (not HEX.fullmatch(str(preflight_sha256))
            or actual_sha!=preflight_sha256
            or preflight_doc.get("format")!=FORMAT
            or preflight_doc.get("status")!=
              "remaining_14_purchased_years_source_sha_and_arrow_footer_verified_not_materialized"
            or preflight_doc.get("years")!=list(YEARS)
            or preflight_doc.get("historical_year_files_verified")!=14
            or preflight_doc.get("purchased_original_rows")!=EXPECTED_OTHER14_ROWS
            or type(preflight_doc.get("annual")) is not dict
            or set(preflight_doc["annual"])!={str(y) for y in YEARS}
            or any(preflight_doc.get(k) is not False for k in (
                "original_market_files_written","physical_parquet_or_sqlite_created",
                "private_or_production_active_pointer_modified",
                "candidate_source_units_certified",
                "ready_for_production_query","ready_for_automatic_market_merge",
                "ready_for_h5_mirror"))
            or preflight_doc.get("no_market_ohlcva_or_stock_symbols_in_safe") is not True):
        raise ValueError("Original 14-year preflight receipt is missing or not trusted")
    anchors=fixed_anchors(safe16,audit16,safe26,audit26,candidate_safe)
    if (preflight_doc["anchors"]!=anchors
            or preflight_doc.get("source_readme_sha256")!=M.QDC.pinned_hash(readme_sha)
            or preflight_doc.get("source_qdc_manifest_sha256")!=M.QDC.pinned_hash(manifest_sha)):
        raise ValueError("2016/2026 evidence changed since 14-year preflight")
    # Revalidate original source file SHA+footer immediately before any
    # private year is built. A complete preflight is a gate, not an
    # authorization to ignore subsequent file changes.
    annual,rows,original_bytes,shadow_bytes=inspect_annual_sources(
        root,readme_sha,manifest_sha)
    if (annual!=preflight_doc["annual"] or rows!=EXPECTED_OTHER14_ROWS
            or original_bytes!=preflight_doc["source_original_purchased_file_bytes"]
            or shadow_bytes!=preflight_doc["minimum_extra_column_original_shadow_bytes"]):
        raise ValueError("QDC 14 historical purchased annual source changed after preflight")
    # Conservative upfront disk safety for new private originals where an
    # unclassified column requires full verbatim QDC byte shadow.
    if M.ROOT.exists():
        free=shutil.disk_usage(M.ROOT).free
        if free < 2*original_bytes+1024*1024*1024:
            raise ValueError("Insufficient work directory free disk to materialize 14 annual years")
    elif M.ROOT.parent.exists():
        free=shutil.disk_usage(M.ROOT.parent).free
        if free < 2*original_bytes+1024*1024*1024:
            raise ValueError("Insufficient work directory free disk to materialize 14 annual years")
    # No source writes. Precheck output paths and per-year physical paths
    # for *all 14* years BEFORE first private build; do not reuse an orphan.
    targets={}
    for year in YEARS:
        f=M.ROOT/f"physical_{year}_{batch_id}"
        gate=M.REPORTS/f"remaining14-{batch_id}-{year}-scope.json"
        material=M.REPORTS/f"remaining14-{batch_id}-{year}-physical.json"
        audit=M.REPORTS/f"remaining14-{batch_id}-{year}-independent.json"
        M.locations(year,f,gate,material)
        report(audit,False)
        targets[year]=(f,gate,material,audit)
    verified={}
    for year in YEARS:
        folder,gate,material,audit=targets[year]
        # M.materialize audits QDC per-year original source SHA again and
        # creates a never-before-used private directory and per-year SAFE.
        material_doc=M.materialize(
            year,root,candidate_safe,readme_sha,manifest_sha,
            folder,gate,material)
        if (material_doc.get("status")!=
             "private_purchased_historical_day_physical_year_not_activated"
                or material_doc.get("year")!=year
                or material_doc.get("purchased_original_rows")!=annual[str(year)]["purchased_rows"]
                or material_doc.get("total_private_physical_rows")!=annual[str(year)]["purchased_rows"]
                or material_doc.get("h5_mixed_candidate_rows")!=0
                or material_doc.get("unclassified_purchased_extra_field_count")!=
                    annual[str(year)]["unclassified_extra_field_count"]
                or material_doc.get("source_purchased_original_parquet_sha256")!=
                    annual[str(year)]["original_sha256"]
                or material_doc.get("source_candidate_safe_sha256")!=
                    anchors["source_h5_candidate_safe_sha256"]
                or any(material_doc.get(k) is not False for k in (
                    "candidate_source_units_certified","ready_for_production_query",
                    "ready_for_automatic_market_merge","ready_for_h5_mirror",
                    "original_market_files_written",
                    "private_or_production_active_pointer_modified"))):
            raise ValueError("Annual purchased materialization result drifted")
        audited=I.verify(material,audit)
        if (audited.get("status")!=
              "independent_historical_private_physical_year_all_rows_sha_and_keys_verified"
                or audited.get("year")!=year
                or audited.get("private_purchased_rows_verified")!=annual[str(year)]["purchased_rows"]
                or audited.get("private_h5_mixed_candidate_rows_verified")!=0
                or audited.get("private_total_rows_verified")!=annual[str(year)]["purchased_rows"]
                or audited.get("private_unclassified_purchased_extra_field_count_verified")!=
                   annual[str(year)]["unclassified_extra_field_count"]
                or audited.get("source_materialization_safe_sha256")!=M.ST.sha(material)
                or audited.get("source_private_manifest_sha256")!=
                    material_doc["private_manifest_sha256"]
                or any(audited.get(k) is not False for k in (
                    "candidate_source_units_certified","ready_for_production_query",
                    "ready_for_automatic_market_merge","ready_for_h5_mirror",
                    "original_market_files_written",
                    "private_or_production_active_pointer_modified"))):
            raise ValueError("Independent full-row purchased annual physical audit did not pass")
        verified[str(year)]={
            "private_relative_directory":material_doc["private_relative_directory"],
            "purchased_rows":audited["private_purchased_rows_verified"],
            "original_purchased_sha256":annual[str(year)]["original_sha256"],
            "unclassified_extra_field_count":annual[str(year)]["unclassified_extra_field_count"],
            "materialization_safe_sha256":M.ST.sha(material),
            "independent_audit_sha256":M.ST.sha(audit),
            "private_manifest_sha256":material_doc["private_manifest_sha256"],
        }
        print("PASS private year",year,"purchased day rows",
              audited["private_purchased_rows_verified"],
              "original SHA and all private Float64/stockdays independently verified")
    if len(verified)!=14 or sum(x["purchased_rows"] for x in verified.values())!=EXPECTED_OTHER14_ROWS:
        raise ValueError("Incomplete historical 14-year totals")
    result={
        "format":BATCH_FORMAT,
        "status":"all_14_historical_purchased_years_independently_verified_private_not_activated",
        "batch_id":batch_id,
        "year_count":14,
        "years":list(YEARS),
        "historical_purchased_rows_verified":EXPECTED_OTHER14_ROWS,
        "source_preflight_safe_sha256":actual_sha,
        "source_qdc_manifest_sha256":M.QDC.pinned_hash(manifest_sha),
        "anchors":anchors,
        "annual":verified,
        "original_market_files_written":False,
        "private_or_production_active_pointer_modified":False,
        "candidate_source_units_certified":False,
        "unknown_extra_field_semantics_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "no_market_ohlcva_or_stock_symbols_in_safe":True,
        "all_years_independent_full_row_sha_and_key_verified":True,
    }
    with summary.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(result,stream,indent=2,sort_keys=True)
        stream.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    modes=p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preflight-only",action="store_true")
    modes.add_argument("--materialize-and-audit",action="store_true")
    p.add_argument("--purchased-root",type=Path,required=True)
    p.add_argument("--candidate-safe",type=Path,required=True)
    p.add_argument("--readme-sha256",required=True)
    p.add_argument("--manifest-sha256",required=True)
    p.add_argument("--accepted-2016-safe",type=Path,required=True)
    p.add_argument("--accepted-2016-audit",type=Path,required=True)
    p.add_argument("--accepted-2026-safe",type=Path,required=True)
    p.add_argument("--accepted-2026-audit",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--preflight-safe",type=Path)
    p.add_argument("--preflight-sha256")
    p.add_argument("--batch-id")
    a=p.parse_args(argv)
    try:
        if a.preflight_only:
            if a.preflight_safe or a.preflight_sha256 or a.batch_id:
                raise ValueError("Preflight never accepts batch write arguments")
            d=preflight(
                a.purchased_root,a.candidate_safe,a.readme_sha256,
                a.manifest_sha256,a.accepted_2016_safe,
                a.accepted_2016_audit,a.accepted_2026_safe,
                a.accepted_2026_audit,a.out)
            print("PASS: 14 purchased DAY years source SHA, Arrow footer and 2016/2026 anchors")
            print("Purchased total:",d["purchased_original_rows"],
                  "annual files:",d["historical_year_files_verified"])
            print("PRECHECK SAFE:",a.out,"NO physical year files written")
        else:
            if not a.preflight_safe or not a.preflight_sha256 or not a.batch_id:
                raise ValueError("Physical staging requires explicit accepted preflight SHA and batch ID")
            d=stage(
                a.purchased_root,a.candidate_safe,a.readme_sha256,
                a.manifest_sha256,a.accepted_2016_safe,
                a.accepted_2016_audit,a.accepted_2026_safe,
                a.accepted_2026_audit,a.preflight_safe,
                a.preflight_sha256,a.batch_id,a.out)
            print("PASS: all 14 purchased YEAR private parquet and SQLite independently verified")
            print("FULL BATCH SAFE:",a.out,
                  "purchased rows:",d["historical_purchased_rows_verified"])
            print("Production query, H5 mirror and market merge remain DISABLED")
    except Exception:
        p.error("14 historical years SHA/physical verification refused; retain all private data")


if __name__=="__main__":
    main()
