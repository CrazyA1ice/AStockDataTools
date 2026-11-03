#!/usr/bin/env python3
"""One-shot resumable 1990-2026 PRIVATE daily historical candidate version.

Stage the already proven immutable 1990-2010 RAW into explicitly noncertified
purchase-schema candidates plus lossless RAW quarantine. Link but NEVER copy
or rewrite already validated 2011-2026 original-purchased-first physical year
Parquets. The resulting version is NOT a production-unified version: 1990s
vendor units/stock identity and quarantined records are not certified.
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
FORMAT="AStockDataTools full 1990-2026 DAY candidate-plus-quarantine logical version NOT activated v1"
YEARS=tuple(range(1990,2011))
OLD_ROWS=3682327
MODERN_ROWS=14137981

def load(label,filename):
    spec=importlib.util.spec_from_file_location(label,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

W=load("full_historical_candidate_writer",
       "stage-pre2011-day-normalized-candidates-with-quarantine.py")
Q=load("full_historical_existing_modern_version",
       "query-private-2011-2026-all16-coverage-readonly.py")

def year_report(year,run_id):
    return REPORTS/f"pre2011-day-candidate-{year}-{run_id}.json"

def verified_existing(year,run_id,full_sha,source):
    import pyarrow.parquet as pq
    import pyarrow as pa
    safe=year_report(year,run_id)
    if not safe.is_file() or safe.is_symlink() or safe.stat().st_size>200000:
        raise ValueError("Incomplete older historical year SAFE; preserve and use a new job")
    obj=json.loads(safe.read_text(encoding="utf-8"))
    folder=W.WORK/f"historical_{year}_{run_id}"
    if (obj.get("format")!=W.FORMAT
            or obj.get("status")!="historical_day_candidate_and_raw_quarantine_materialized_not_merged"
            or obj.get("year")!=year
            or obj.get("raw_source_full21_safe_sha256")!=full_sha
            or obj.get("original_annual_raw_parquet_sha256")!=source[2]
            or obj.get("total_raw_h5_rows")!=source[1]
            or obj.get("all_historical_raw_rows_preserved_in_either_qualified_candidate_or_raw_quarantine") is not True
            or obj.get("ready_for_production_query") is not False
            or obj.get("historical_vendor_units_corporate_actions_securities_certified") is not False
            or obj.get("purchased_parquet_or_hikyuu_h5_original_modified") is not False
            or obj.get("private_active_pointer_or_production_modified") is not False):
        raise ValueError("Prior year candidate/quarantine receipt not qualified")
    pairs=(
        ("candidate_parquet_relative_path","candidate_parquet_sha256","purchased_schema_candidate_rows_not_vendor_certified",W.PHYS.schema(pa)),
        ("quarantine_parquet_relative_path","quarantine_parquet_sha256","lossless_native_quarantine_rows",
          pa.schema([*W.SINGLE.schema(pa),
                     pa.field("quarantine_reason",pa.string())])),
    )
    for relative,hash_field,rows_field,schema in pairs:
        path=MODULE/obj[relative]
        if (path.is_symlink() or path.parent.is_symlink()
                or path.resolve().parent!=folder.resolve()
                or not path.is_file() or W.sha(path)!=obj[hash_field]):
            raise ValueError("Prior standardized candidate/quarantine physical SHA changed")
        with pq.ParquetFile(path) as pf:
            if pf.schema_arrow!=schema or pf.metadata.num_rows!=obj[rows_field]:
                raise ValueError("Prior standardized candidate/quarantine count/schema changed")
    if obj["purchased_schema_candidate_rows_not_vendor_certified"]+obj[
            "lossless_native_quarantine_rows"]!=source[1]:
        raise ValueError("Historical candidate plus quarantine does not conserve rows")
    return obj

def assemble(full21,modern_safe,modern_sha,run_id,out):
    if not re.fullmatch(r"[0-9a-f]{12}",run_id):
        raise ValueError("Require bounded 12-hex run ID")
    target=Path(out)
    if (REPORTS.is_symlink() or target.is_symlink()
            or target.exists() or target.suffix!=".json"
            or target.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Only fresh standalone private candidate version SAFE")
    full,full_sha=W.PROFILE.source_safe(full21)
    sources={year:(file,count,sha) for year,file,count,sha in
             W.PROFILE.verified_private_files(full)}
    if set(sources)!=set(YEARS) or sum(item[1] for item in sources.values())!=OLD_ROWS:
        raise ValueError("Full 21-year RAW Parquet source not qualified")
    modern=Q.version(modern_safe,modern_sha)
    if modern["private_total_stockday_records"]!=MODERN_ROWS:
        raise ValueError("Modern 16-year authoritative source count different")
    records={}
    for year in YEARS:
        safe=year_report(year,run_id)
        folder=W.WORK/f"historical_{year}_{run_id}"
        if safe.exists():
            obj=verified_existing(year,run_id,full_sha,sources[year])
            print("SHA reverified pre2011 year",year,"rows:",
                  obj["total_raw_h5_rows"],flush=True)
        else:
            if folder.exists():
                raise ValueError("Partial historical year preserved: "+str(year)+
                                 ". Do not overwrite; start a new isolated run ID")
            obj=W.annual(year,full21,run_id,safe,
                         verified_sources=sources,full_sha_override=full_sha)
            print("New actual historical DAY candidate/quarantine:",
                  year,"candidate=",obj[
                      "purchased_schema_candidate_rows_not_vendor_certified"],
                  "quarantine=",obj["lossless_native_quarantine_rows"],flush=True)
        records[str(year)]={
            "raw_h5_rows":obj["total_raw_h5_rows"],
            "candidate_rows_unverified_unit_hypothesis":obj[
                "purchased_schema_candidate_rows_not_vendor_certified"],
            "native_raw_quarantine_rows":obj["lossless_native_quarantine_rows"],
            "year_receipt_sha256":W.sha(safe),
            "candidate_parquet_relative_path":obj["candidate_parquet_relative_path"],
            "candidate_parquet_sha256":obj["candidate_parquet_sha256"],
            "quarantine_parquet_relative_path":obj["quarantine_parquet_relative_path"],
            "quarantine_parquet_sha256":obj["quarantine_parquet_sha256"],
        }
    candidates=sum(v["candidate_rows_unverified_unit_hypothesis"] for v in records.values())
    rejects=sum(v["native_raw_quarantine_rows"] for v in records.values())
    if candidates+rejects!=OLD_ROWS:
        raise ValueError("Full 1990-2010 source conservation failed")
    # No physical 2011-2026 duplication: reference the immutable SHA-pinned
    # modern version, whose 16 annual private physical Parquet shards
    # already exist and passed independent all-row audits.
    final={
        "format":FORMAT,
        "status":"1990_2026_day_full_history_private_candidates_with_raw_quarantine_not_activated",
        "historical_native_start":"1990-12-20",
        "historical_native_end":"2010-12-31",
        "modern_purchase_first_start":"2011-01-04",
        "modern_end":"2026",
        "raw_1990_2010_h5_rows_preserved":OLD_ROWS,
        "purchase_schema_historical_hypothesis_rows":candidates,
        "historical_native_raw_quarantined_rows":rejects,
        "modern_2011_2026_accepted_private_rows":MODERN_ROWS,
        "all_1990_2026_source_rows_without_overlap":OLD_ROWS+MODERN_ROWS,
        "all_21_historical_sources_sha_qualified_at_start":True,
        "historical_full21_safe_sha256":full_sha,
        "modern_all16_version_sha256":modern_sha,
        "historical_years":records,
        "modern_2011_2026_shards_are_referenced_not_rewritten":True,
        "historical_candidate_vendor_units_or_corporate_actions_certified":False,
        "quarantined_pre2011_rows_part_of_purchase_schema_query":False,
        "historical_candidate_rows_active_in_production_query":False,
        "no_original_h5_or_purchased_parquet_files_opened_by_this_workflow":True,
        "original_market_files_or_previous_private_shards_modified":False,
        "private_active_pointer_modified":False,
        "native_h5_full_mirror_modified":False,
    }
    with target.open("x",encoding="utf-8") as f:
        json.dump(final,f,ensure_ascii=False,indent=2,sort_keys=True)
        f.write("\n")
    return final

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--full21-safe",type=Path,required=True)
    p.add_argument("--modern-version-safe",type=Path,required=True)
    p.add_argument("--modern-version-sha256",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--build-full-history-day-candidate-version",action="store_true",required=True)
    a=p.parse_args(argv)
    result=assemble(a.full21_safe,a.modern_version_safe,
                    a.modern_version_sha256,a.run_id,a.out)
    print("PASS: original historical RAW rows classified:",
          result["raw_1990_2010_h5_rows_preserved"],flush=True)
    print("Historical purchase-schema tentative rows:",
          result["purchase_schema_historical_hypothesis_rows"],flush=True)
    print("Historical lossless raw quarantine:",
          result["historical_native_raw_quarantined_rows"],flush=True)
    print("Existing modern private DAY rows referenced and unchanged:",
          result["modern_2011_2026_accepted_private_rows"],flush=True)
    print("This is NOT a vendor-certified or production unified 1990-2026 DAY. SAFE:",
          a.out,flush=True)

if __name__=="__main__":
    main()
