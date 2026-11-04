#!/usr/bin/env python3
"""Publish a SHA-bound, NOT ACTIVATED 2011..2026 private DAY version manifest.

This is a manifest-only operation: it NEVER copies or rewrites historical
Parquet/SQLite, opens original vendor QDC/H5, updates active pointers,
produces an H5 mirror, or authorizes production queries.

Every underlying annual physical snapshot was independently audited earlier.
Re-verify all 16 manifest/SQLite/original-shadow SHA and audit receipts,
then inspect SQLite stockday keys read-only to prove each yearly shard contains
only its declared year. Distinct disjoint trading years imply no cross-year
(symbol,trading_date) collision. No raw keys or OHLCVA in aggregate receipt.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
from pathlib import Path

HERE=Path(__file__).resolve().parent
def load(label,name):
    spec=importlib.util.spec_from_file_location(label,HERE/name)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

B=load("private_16yr_existing_14_batch","stage-remaining14-private-purchased-years.py")
H=B.I
Y=B.Y2026
M=B.M
FORMAT="AStockDataTools 2011-2026 all16 immutable private physical DAY version v1"
YEAR_SET=set(range(2011,2027))
TOTAL_ROWS=14137981
TOTAL_PURCHASED=14115707
TOTAL_H5=22274
MAX_JSON=1000000
SHA=re.compile("[0-9a-f]{64}\\Z")


def safe_file(path):
    p=Path(path)
    if (p.is_symlink() or p.suffix!=".json" or
            p.resolve().parent!=M.REPORTS.resolve()
            or M.REPORTS.is_symlink() or not p.is_file()
            or not 0<p.stat().st_size<=MAX_JSON):
        raise ValueError("Require pinned existing module reports/ SAFE")
    return p.resolve()


def sha_json(path):
    p=safe_file(path)
    raw=p.read_bytes()
    obj=json.loads(raw)
    if type(obj) is not dict:
        raise ValueError("Input SAFE must contain one aggregate JSON object")
    return obj,hashlib.sha256(raw).hexdigest()


def open_index_readonly(path,year,expected_rows):
    p=Path(path)
    if (p.is_symlink() or p.parent.is_symlink() or not p.is_file()):
        raise ValueError("Missing private immutable stockday index")
    con=sqlite3.connect(p.resolve().as_uri()+"?mode=ro&immutable=1",uri=True)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("Year private SQLite integrity is invalid")
        total=con.execute("SELECT COUNT(*) FROM stockday").fetchone()[0]
        # Check the year recorded in the key and trading_date, not only
        # a synthetic year field. Avoid exporting the actual symbol/day.
        wrong=con.execute(
            "SELECT COUNT(*) FROM stockday WHERE year != ? OR "
            "trading_date IS NULL OR length(trading_date) != 10 OR "
            "substr(trading_date,1,5) != ?",
            (year,f"{year}-")).fetchone()[0]
        if total!=expected_rows or wrong!=0:
            raise ValueError("Stockday shard contains invalid/out-of-year keys")
        return total
    finally:
        con.close()


def certify(batch_safe,batch_sha,accepted_2016_safe,accepted_2016_audit,
            accepted_2026_safe,accepted_2026_audit,
            candidate_safe,version_out):
    output=Path(version_out)
    if (M.REPORTS.is_symlink() or output.is_symlink()
            or output.exists() or output.suffix!=".json"
            or output.resolve().parent!=M.REPORTS.resolve()):
        raise ValueError("New immutable all16 version SAFE must be in module reports/")
    if not SHA.fullmatch(str(batch_sha)):
        raise ValueError("Explicit known 14-year batch SHA256 required")
    batch,actual_batch_sha=sha_json(batch_safe)
    if (actual_batch_sha!=batch_sha
            or batch.get("format")!=B.BATCH_FORMAT
            or batch.get("status")!=
               "all_14_historical_purchased_years_independently_verified_private_not_activated"
            or batch.get("batch_id")!="44edd84e21ee"
            or batch.get("year_count")!=14
            or batch.get("years")!=list(B.YEARS)
            or batch.get("historical_purchased_rows_verified")!=B.EXPECTED_OTHER14_ROWS
            or batch.get("all_years_independent_full_row_sha_and_key_verified") is not True
            or type(batch.get("annual")) is not dict
            or set(batch["annual"])!={str(y) for y in B.YEARS}
            or any(batch.get(k) is not False for k in (
                "original_market_files_written",
                "private_or_production_active_pointer_modified",
                "candidate_source_units_certified",
                "ready_for_production_query","ready_for_automatic_market_merge",
                "ready_for_h5_mirror"))):
        raise ValueError("Only the completed accepted original 14-year batch may be bound")
    # The anchor function compares existing source manifests and both
    # already completed independent audits. Never select a different
    # 2016 orphan or silently substitute a 2026 snapshot.
    anchors=B.fixed_anchors(accepted_2016_safe,accepted_2016_audit,
                            accepted_2026_safe,accepted_2026_audit,candidate_safe)
    if anchors!=batch.get("anchors"):
        raise ValueError("2016/2026 private anchor SHA differs from 14-year batch")
    selected={}
    purchased_count=0
    h5_count=0
    stockday_total=0
    # Physical 2011..2025 annual reports reside in module reports.
    for year in range(2011,2026):
        if year==2016:
            source=safe_file(accepted_2016_safe)
            audit=safe_file(accepted_2016_audit)
            expected_purchased=B.PURCHASED_2016_YEAR
            expected_h5=1
            bundle_entry=None
        else:
            source=safe_file(M.REPORTS/f"remaining14-{batch['batch_id']}-{year}-physical.json")
            audit=safe_file(M.REPORTS/f"remaining14-{batch['batch_id']}-{year}-independent.json")
            bundle_entry=batch["annual"][str(year)]
            expected_purchased=bundle_entry["purchased_rows"]
            expected_h5=0
            if (bundle_entry.get("private_relative_directory")!=
                    f"work/unified_parquet/physical_years/physical_{year}_{batch['batch_id']}"
                    or bundle_entry.get("original_purchased_sha256") is None):
                raise ValueError("Unexpected 14-year source snapshot directory")
        doc,src_sha,folder,manifest_path,index,manifest=H.source(source)
        independently_audited,audit_sha=sha_json(audit)
        if (doc.get("year")!=year
                or doc.get("purchased_original_rows")!=expected_purchased
                or doc.get("h5_mixed_candidate_rows")!=expected_h5
                or doc.get("total_private_physical_rows")!=expected_purchased+expected_h5
                or doc.get("source_candidate_safe_sha256")!=anchors[
                    "source_h5_candidate_safe_sha256"]
                or independently_audited.get("status")!=
                    "independent_historical_private_physical_year_all_rows_sha_and_keys_verified"
                or independently_audited.get("year")!=year
                or independently_audited.get("source_materialization_safe_sha256")!=src_sha
                or independently_audited.get("source_private_manifest_sha256")!=
                   doc["private_manifest_sha256"]
                or independently_audited.get("private_purchased_rows_verified")!=expected_purchased
                or independently_audited.get("private_h5_mixed_candidate_rows_verified")!=expected_h5
                or independently_audited.get("private_total_rows_verified")!=expected_purchased+expected_h5
                or independently_audited.get("original_float64_roundtrip_fingerprint_verified") is not True
                or any(independently_audited.get(k) is not False for k in (
                    "candidate_source_units_certified","ready_for_production_query",
                    "ready_for_automatic_market_merge","ready_for_h5_mirror",
                    "original_market_files_written",
                    "private_or_production_active_pointer_modified"))):
            raise ValueError("Annual independent full-row SHA receipt no longer matches snapshot")
        if bundle_entry is not None and (
                bundle_entry.get("materialization_safe_sha256")!=src_sha
                or bundle_entry.get("independent_audit_sha256")!=audit_sha
                or bundle_entry.get("private_manifest_sha256")!=doc["private_manifest_sha256"]
                or bundle_entry.get("original_purchased_sha256")!=
                    doc["source_purchased_original_parquet_sha256"]):
            raise ValueError("14-year batch annual evidence changed")
        # 2016 selected recovery SAFE was already explicitly SHA-pinned.
        if year==2016 and (
                src_sha!=anchors["accepted_2016_recovery_safe_sha256"]
                or audit_sha!=anchors["accepted_2016_independent_audit_sha256"]):
            raise ValueError("Accepted 2016 recovered evidence SHA changed")
        checked=open_index_readonly(index,year,expected_purchased+expected_h5)
        if folder.relative_to(M.MODULE).as_posix()!=doc["private_relative_directory"]:
            raise ValueError("Year private path and receipt not consistent")
        selected[str(year)]={
            "private_relative_directory":doc["private_relative_directory"],
            "physical_manifest_sha256":doc["private_manifest_sha256"],
            "materialization_safe_sha256":src_sha,
            "independent_audit_sha256":audit_sha,
            "private_stockday_index_sha256":doc["private_sqlite_sha256"],
            "purchased_rows":expected_purchased,
            "h5_only_rows":expected_h5,
            "total_rows":checked,
            "source_original_purchased_sha256":doc[
                "source_purchased_original_parquet_sha256"],
            "unknown_extra_field_semantics_certified":False,
        }
        purchased_count+=expected_purchased
        h5_count+=expected_h5
        stockday_total+=checked
    doc26,sha26,folder26,manifest26,index26,m26=Y.source_report(
        safe_file(accepted_2026_safe))
    v26,ind26_sha=sha_json(accepted_2026_audit)
    if (sha26!=anchors["accepted_2026_materialization_safe_sha256"]
            or ind26_sha!=anchors["accepted_2026_independent_audit_sha256"]
            or v26.get("status")!=
               "independent_full_2026_private_physical_parquet_sha_values_keys_verified"
            or v26.get("source_materialization_safe_sha256")!=sha26
            or v26.get("source_private_physical_manifest_sha256")!=
                doc26["private_manifest_sha256"]
            or v26.get("private_purchased_records_verified")!=B.PURCHASED_2026_NINE_MONTHS
            or v26.get("private_h5_whole_candidate_rows_verified")!=22191
            or v26.get("private_h5_mixed_candidate_rows_verified")!=82
            or v26.get("private_total_stockday_rows_verified")!=1032623
            or v26.get("quarantined_2026_07_16_stockday_bars_not_included")!=5
            or any(v26.get(k) is not False for k in (
                "candidate_source_units_certified","ready_for_production_query",
                "ready_for_automatic_market_merge","ready_for_h5_mirror",
                "original_market_files_modified",
                "private_or_production_active_pointer_modified"))):
        raise ValueError("2026 private independent receipt is inconsistent")
    checked=open_index_readonly(index26,2026,1032623)
    selected["2026"]={
        "private_relative_directory":doc26["private_relative_directory"],
        "physical_manifest_sha256":doc26["private_manifest_sha256"],
        "materialization_safe_sha256":sha26,
        "independent_audit_sha256":ind26_sha,
        "private_stockday_index_sha256":doc26["private_stockday_unique_index_sha256"],
        "purchased_rows":B.PURCHASED_2026_NINE_MONTHS,
        "h5_only_rows":22273,
        "total_rows":checked,
        "source_original_purchased_sha256":None,
        "unknown_extra_field_semantics_certified":False,
    }
    purchased_count+=B.PURCHASED_2026_NINE_MONTHS
    h5_count+=22273
    stockday_total+=checked
    if (set(int(y) for y in selected)!=YEAR_SET or len(selected)!=16
            or purchased_count!=TOTAL_PURCHASED
            or h5_count!=TOTAL_H5 or stockday_total!=TOTAL_ROWS
            or sum(x["total_rows"] for x in selected.values())!=stockday_total
            or len({x["private_relative_directory"] for x in selected.values()})!=16):
        raise ValueError("All16 year/rows are not exactly conserved")
    # Since every per-year SQLite row's year and trading_date prefix were
    # directly validated and all 16 years are disjoint, a shared stock/day
    # cannot span two years. In-year uniqueness is from each SQLite PK and
    # previously completed full-row independent Parquet->SQLite checks.
    result={
        "format":FORMAT,
        "status":"all16_private_annual_physical_shards_sha_and_stockday_years_verified_not_activated",
        "year_count":16,
        "years":list(range(2011,2027)),
        "purchased_original_records":purchased_count,
        "verified_h5_only_gap_records":h5_count,
        "private_total_stockday_records":stockday_total,
        "historical_14_batch_safe_sha256":actual_batch_sha,
        "source_candidate_safe_sha256":anchors["source_h5_candidate_safe_sha256"],
        "selected_2016_recovery_safe_sha256":anchors["accepted_2016_recovery_safe_sha256"],
        "selected_2026_materialization_safe_sha256":anchors[
            "accepted_2026_materialization_safe_sha256"],
        "per_year_private_manifest_sha_and_independent_audit_bound":True,
        "per_year_private_sqlite_index_integrity_rechecked_readonly":True,
        "cross_year_stockday_key_ranges_disjoint":True,
        "all_original_licensed_market_values_reread_now":False,
        "all_16_full_row_parquet_audits_previously_verified_and_sha_pinned":True,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
        "annual":selected,
        "source_market_files_opened":False,
        "original_market_files_written":False,
        "private_physical_parquet_or_sqlite_written":False,
        "private_or_production_active_pointer_modified":False,
        "candidate_source_units_certified":False,
        "unknown_extra_field_semantics_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "no_market_ohlcva_or_stock_symbols_in_safe":True,
    }
    with output.open("x",encoding="utf-8",newline="\n") as fp:
        json.dump(result,fp,indent=2,sort_keys=True,ensure_ascii=False)
        fp.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--historical14-batch-safe",type=Path,required=True)
    p.add_argument("--historical14-batch-sha256",required=True)
    p.add_argument("--accepted-2016-safe",type=Path,required=True)
    p.add_argument("--accepted-2016-audit",type=Path,required=True)
    p.add_argument("--accepted-2026-safe",type=Path,required=True)
    p.add_argument("--accepted-2026-audit",type=Path,required=True)
    p.add_argument("--candidate-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--certify-private-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        r=certify(
            a.historical14_batch_safe,a.historical14_batch_sha256,
            a.accepted_2016_safe,a.accepted_2016_audit,
            a.accepted_2026_safe,a.accepted_2026_audit,
            a.candidate_safe,a.out)
        print("PASS: all16 SHA-anchored private day years, per-year SQLite key ranges")
        print("Purchased:",r["purchased_original_records"],
              "H5-only:",r["verified_h5_only_gap_records"],
              "Private total:",r["private_total_stockday_records"])
        print("Aggregate-only immutable private 2011-2026 SAFE:",a.out)
        print("No production, H5 mirror, private physical writes or source changes")
    except Exception:
        p.error("Refused to certify 2011-2026 private all16 sources; preserve existing immutable annual data")


if __name__=="__main__":
    main()
