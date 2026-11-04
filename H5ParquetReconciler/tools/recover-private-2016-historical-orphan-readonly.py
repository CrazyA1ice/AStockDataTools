#!/usr/bin/env python3
"""Recover an already-materialized SHA-bound 2016 private physical YEAR.

The earlier CLI could fail at last SAFE publication because its private
folder was relative to CWD while MODULE was an absolute path. This tool
never rebuilds/modifies existing Parquet, SQLite, manifests, original QDC,
or H5. It recovers only a complete, non-activated, SHA-verified private
orphan and issues fresh aggregate-only receipts in module reports/.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

M=load("recover_historical_2016_builder","materialize-private-2011-2025-purchased-year.py")
I=load("recover_historical_2016_verifier","verify-private-2011-2025-purchased-year.py")
HEX=re.compile("[0-9a-f]{64}\\Z")
PARTS={"purchased":("purchased/day.parquet","purchased_parquet"),
       "h5_gap_2016":("candidate/h5-gap-2016.parquet",
                       "private_h5_mixed_stockday_candidate")}

def report(path):
    p=Path(path)
    if (M.REPORTS.is_symlink() or p.is_symlink() or p.exists()
            or p.suffix.lower()!=".json"
            or p.resolve().parent!=M.REPORTS.resolve()):
        raise ValueError("Only NEW aggregate module reports accepted")
    return p.resolve()

def recover(folder,source_root,candidate_safe,readme_sha,manifest_sha,
            candidate_gate,recovery_safe,independent_out):
    folder=Path(folder)
    gate=report(candidate_gate)
    out=report(recovery_safe)
    audit=report(independent_out)
    if len({gate,out,audit})!=3:
        raise ValueError("Distinct output SAFE paths required")
    if (not re.fullmatch("physical_2016_[0-9a-f]{12,32}",folder.name)
            or not folder.is_dir() or folder.is_symlink()
            or folder.resolve().parent!=M.ROOT.resolve()
            or any(p.is_symlink() for p in (
                M.MODULE/"work",M.WORK,M.ROOT,
                folder/"purchased",folder/"candidate"))):
        raise ValueError("2016 orphan must already exist in private module work")
    folder=folder.resolve()
    mf=folder/"manifest.json"
    db=folder/"stockday-unique.sqlite3"
    if (mf.is_symlink() or not mf.is_file()
            or db.is_symlink() or not db.is_file()
            or not 0<mf.stat().st_size<=1000000):
        raise ValueError("Incomplete 2016 orphan private manifest/index")
    original,record,readme,qdc_manifest=M.purchased_input(
        source_root,2016,readme_sha,manifest_sha)
    before={p.name:M.QDC.file_state(p) for p in (original,readme,qdc_manifest)}
    candidate,candidate_sha,candidate_folder,candidate_mf=M.V.source(candidate_safe)
    if (candidate.get("source_version_sha256")!=M.SOURCE_VERSION
            or candidate.get("candidate_year_rows")!={"2016":1,"2026":22273}):
        raise ValueError("Unrecognized private source snapshot")
    full=M.V.verify(candidate_safe,gate)
    if (full.get("total_h5_only_day_candidates_verified")!=22274
            or full.get("mixed_date_candidate_rows_verified")!=83
            or full.get("partition_year_rows_verified")!=
                {"2016":1,"2026":22273}
            or full.get("candidate_source_units_certified") is not False):
        raise ValueError("All 22274 H5-only source candidates must be reverified")
    candidate_part=candidate_folder/"year=2016"/"day.parquet"
    if (candidate_part.is_symlink() or candidate_part.parent.is_symlink()
            or not candidate_part.is_file()
            or M.ST.sha(candidate_part)!=candidate["partition_sha256"]["2016"]):
        raise ValueError("Original candidate 2016 source partition changed")
    mf_sha=M.ST.sha(mf)
    m=json.loads(mf.read_bytes())
    if (type(m) is not dict or m.get("format")!=M.FORMAT
            or m.get("status")!=
               "private_purchased_historical_day_physical_year_not_activated"
            or m.get("year")!=2016
            or m.get("original_qdc_manifest_sha256")!=M.QDC.pinned_hash(manifest_sha)
            or m.get("source_purchased_original_parquet_sha256")!=record["sha"]
            or m.get("source_candidate_safe_sha256")!=candidate_sha
            or m.get("source_candidate_version_sha256")!=M.SOURCE_VERSION
            or m.get("original_purchased_rows")!=record["rows"]
            or m.get("h5_mixed_candidate_rows")!=1
            or m.get("total_private_physical_rows")!=record["rows"]+1
            or m.get("unclassified_purchased_extra_field_count")!=1
            or m.get("unknown_extra_field_semantics_certified") is not False
            or m.get("original_float64_roundtrip_exact") is not True
            or any(m.get(x) is not False for x in (
                "original_market_files_written",
                "original_purchased_parquet_replaced",
                "private_or_production_active_pointer_modified",
                "candidate_source_units_certified","ready_for_production_query",
                "ready_for_automatic_market_merge","ready_for_h5_mirror"))):
        raise ValueError("Untrusted 2016 orphan manifest cannot be activated")
    parts=m.get("partition_files")
    shadow=m.get("original_purchased_full_bytes_shadow")
    if (type(parts) is not dict or set(parts)!=set(PARTS)
            or type(shadow) is not dict
            or shadow.get("relative_file")!=
                "purchased/original-with-unclassified-extra.parquet"
            or shadow.get("sha256")!=record["sha"]
            or shadow.get("source_bytes")!=record["size"]
            or shadow.get("extra_field_count")!=1
            or shadow.get("source_semantics_certified") is not False):
        raise ValueError("Private 2016 original extra-field archive not complete")
    archive=folder/shadow["relative_file"]
    if (archive.is_symlink() or not archive.is_file()
            or M.ST.sha(archive)!=record["sha"]
            or archive.stat().st_size!=record["size"]):
        raise ValueError("Original QDC 2016 full source byte archive SHA mismatch")
    partition_receipts={}
    for name,(relative,kind) in PARTS.items():
        part=parts[name]
        p=folder/relative
        if (type(part) is not dict
                or part.get("relative_file")!=relative
                or part.get("source_kind")!=kind
                or type(part.get("rows")) is not int
                or part["rows"]!=(record["rows"] if name=="purchased" else 1)
                or not HEX.fullmatch(str(part.get("sha256")))
                or not HEX.fullmatch(str(part.get("original_rows_float64_digest_sha256")))
                or p.is_symlink() or p.parent.is_symlink()
                or not p.is_file() or not 0<p.stat().st_size<=M.MAX_PART_BYTES
                or M.ST.sha(p)!=part["sha256"]):
            raise ValueError("Private 2016 output Parquet changed/incomplete")
        partition_receipts[name]={"rows":part["rows"],"sha256":part["sha256"]}
    if (not HEX.fullmatch(str(m.get("stockday_unique_sqlite_sha256")))
            or M.ST.sha(db)!=m["stockday_unique_sqlite_sha256"]
            or M.ST.sha(mf)!=mf_sha
            or any(M.QDC.file_state(p)!=before[p.name]
                   for p in (original,readme,qdc_manifest))
            or M.QDC.digest_file(original)!=record["sha"]
            or M.V.source(candidate_safe)[1]!=candidate_sha
            or M.ST.sha(candidate_mf)!=candidate["manifest_sha256"]
            or M.ST.sha(candidate_part)!=candidate["partition_sha256"]["2016"]):
        raise ValueError("Source or private orphan changed during verification")
    safe={
        "format":M.FORMAT,
        "status":m["status"],
        "year":2016,
        "private_relative_directory":folder.relative_to(M.MODULE).as_posix(),
        "private_manifest_sha256":mf_sha,
        "private_sqlite_sha256":m["stockday_unique_sqlite_sha256"],
        "source_purchased_original_parquet_sha256":record["sha"],
        "source_candidate_safe_sha256":candidate_sha,
        "source_candidate_version_sha256":M.SOURCE_VERSION,
        "physical_partition_sha256":partition_receipts,
        "unclassified_purchased_extra_field_count":1,
        "verbatim_original_purchased_extra_field_shadow_created":True,
        "unknown_extra_field_semantics_certified":False,
        "purchased_original_rows":record["rows"],
        "h5_mixed_candidate_rows":1,
        "total_private_physical_rows":record["rows"]+1,
        "original_float64_roundtrip_exact":True,
        "original_market_files_written":False,
        "original_purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "no_market_ohlcva_or_symbols_in_safe":True,
        "recovered_from_existing_immutable_orphan_without_physical_rewrite":True,
    }
    with out.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(safe,f,indent=2,sort_keys=True)
        f.write("\n")
    verified=I.verify(out,audit)
    if (verified.get("status")!=
            "independent_historical_private_physical_year_all_rows_sha_and_keys_verified"
            or verified.get("year")!=2016
            or verified.get("private_purchased_rows_verified")!=record["rows"]
            or verified.get("private_h5_mixed_candidate_rows_verified")!=1
            or verified.get("private_verbatim_original_purchased_shadow_sha_verified") is not True
            or verified.get("private_byte_shadow_source_float64_rows_recompared") is not True
            or verified.get("ready_for_automatic_market_merge") is not False
            or verified.get("ready_for_h5_mirror") is not False):
        raise ValueError("Existing orphan did not pass complete independent audit")
    return verified

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--private-year-dir",type=Path,required=True)
    p.add_argument("--purchased-root",type=Path,required=True)
    p.add_argument("--candidate-safe",type=Path,required=True)
    p.add_argument("--readme-sha256",required=True)
    p.add_argument("--manifest-sha256",required=True)
    p.add_argument("--candidate-verification-out",type=Path,required=True)
    p.add_argument("--recovered-safe-out",type=Path,required=True)
    p.add_argument("--independent-out",type=Path,required=True)
    p.add_argument("--recover-existing-readonly",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        v=recover(args.private_year_dir,args.purchased_root,args.candidate_safe,
                  args.readme_sha256,args.manifest_sha256,
                  args.candidate_verification_out,args.recovered_safe_out,
                  args.independent_out)
        print("PASS: 2016 private orphan recovered without physical rewrite")
        print("Purchased:",v["private_purchased_rows_verified"],
              "H5 mixed:",v["private_h5_mixed_candidate_rows_verified"],
              "Total:",v["private_total_rows_verified"])
        print("Full vendor byte shadow, float64 and SQLite stockdays independently audited")
        print("RECOVERED SAFE:",args.recovered_safe_out)
        print("INDEPENDENT AUDIT SAFE:",args.independent_out)
        print("No original/production/H5/pointer files modified")
    except Exception:
        p.error("Original private 2016 orphan does not satisfy recovery gates; preserve it")

if __name__=="__main__":
    main()
