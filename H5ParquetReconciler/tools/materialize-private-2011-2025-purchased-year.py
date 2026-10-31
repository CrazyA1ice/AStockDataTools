#!/usr/bin/env python3
"""One private historical purchased DAY physical year (2011..2025).

Only the original single annual QDC file is imported into an immutable,
unactivated private physical Parquet. Exactly ONE H5-only candidate from the
previously fully audited 22,274-gap snapshot is also included for year 2016.
Every (canonical stock, Beijing trading day) must be globally unique.
Raw vendor float64 and source symbol are not rescaled, rounded or relabeled.
Original market sources and any production/active pointers are never written.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
WORK=MODULE/"work"/"unified_parquet"
ROOT=WORK/"physical_years"
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools private purchased historical physical DAY year v1"
FIRST_YEAR=2011
LAST_YEAR=2025
MAX_PART_BYTES=512*1024*1024
SOURCE_VERSION="e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23"


def load(label,path):
    spec=importlib.util.spec_from_file_location(label,HERE/path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


PHYS=load("historical_2011_2025_reuse_private_2026_schema",
          "materialize-private-2026-purchased-plus-h5-year.py")
V=PHYS.V
QDC=PHYS.QDC
ST=PHYS.ST


def locations(year,folder,source_gate,out):
    if type(year) is not int or not FIRST_YEAR<=year<=LAST_YEAR:
        raise ValueError("Only purchased historical 2011..2025 DAY year accepted")
    f=Path(folder)
    p=Path(source_gate)
    s=Path(out)
    if (any(x.is_symlink() for x in (MODULE/"work",WORK,ROOT,REPORTS,f,p,s))
            or not re.fullmatch(f"physical_{year}_[0-9a-f]{{12,32}}",f.name)
            or f.exists() or f.resolve().parent!=ROOT.resolve()
            or p==s or p.resolve()==s.resolve()
            or any(q.suffix!=".json" or q.exists()
                   or q.resolve().parent!=REPORTS.resolve() for q in (p,s))):
        raise ValueError("Must use fresh private physical YEAR directory and two new reports")
    return f,p,s


def purchased_input(root,year,readme_sha,manifest_sha):
    source=Path(root)
    if (not source.is_absolute() or source.is_symlink() or not source.is_dir()
            or source.resolve()!=source):
        raise ValueError("QDC purchased source root must be canonical")
    day=source/"day"
    if day.is_symlink() or not day.is_dir():
        raise ValueError("Original purchased source/day is missing or linked")
    readme=source/"【先看我】数据说明.txt"
    mf=source/"文件校验清单.txt"
    if (QDC.digest_file(readme,QDC.MAX_README_BYTES)!=QDC.pinned_hash(readme_sha)
            or QDC.digest_file(mf,QDC.MAX_MANIFEST_BYTES)!=
               QDC.pinned_hash(manifest_sha)):
        raise ValueError("Original purchased README or manifest SHA differs")
    records=QDC.parse_manifest(mf.read_bytes())
    path=day/f"{year}.parquet"
    if (path.is_symlink() or not path.is_file()
            or path.resolve().parent!=day.resolve()):
        raise ValueError("Original purchased year file missing or linked")
    if path.stat().st_size!=records[path.name]["size"] or (
            QDC.digest_file(path)!=records[path.name]["sha"]):
        raise ValueError("Original purchased annual file differs from full QDC SHA manifest")
    return path,records[path.name],readme,mf


def materialize(year,source_root,candidate_safe,readme_sha,manifest_sha,
                folder,full_candidate_gate,out):
    folder,gate,out=locations(year,folder,full_candidate_gate,out)
    original,record,readme,qdc_mf=purchased_input(
        source_root,year,readme_sha,manifest_sha)
    original_states={x.name:QDC.file_state(x) for x in (original,readme,qdc_mf)}
    source_doc,source_safe_sha,source_dir,source_mf=V.source(candidate_safe)
    if (source_doc.get("source_version_sha256")!=SOURCE_VERSION
            or source_doc.get("candidate_year_rows")!={"2016":1,"2026":22273}):
        raise ValueError("Trusted historical H5-only source version missing")
    h5=None
    if year==2016:
        checked=V.verify(candidate_safe,gate)
        if (checked.get("total_h5_only_day_candidates_verified")!=22274
                or checked.get("mixed_date_candidate_rows_verified")!=83
                or checked.get("partition_year_rows_verified")!=
                    {"2016":1,"2026":22273}
                or checked.get("candidate_source_units_certified") is not False):
            raise ValueError("Historical 2016 H5 candidate not fully audited")
        h5=source_dir/"year=2016"/"day.parquet"
        if (h5.parent.is_symlink() or h5.is_symlink()
                or ST.sha(h5)!=source_doc["partition_sha256"]["2016"]):
            raise ValueError("Historical 2016 private H5 candidate source SHA differs")
    else:
        # An aggregate-only source receipt, not an unnecessary full H5 read
        # for years which have *zero* H5 candidate rows in the fixed snapshot.
        if not REPORTS.is_dir() or gate.exists():
            raise ValueError("Invalid historical SAFE receipt destination")
        with gate.open("x",encoding="utf-8",newline="\n") as stream:
            json.dump({
                "format":"AStockDataTools historical no-H5-year source scope v1",
                "year":year,"h5_candidate_rows_for_year":0,
                "source_h5_candidate_safe_sha256":source_safe_sha,
                "full_h5_candidate_rows_redecoded_now":False,
                "source_market_files_opened":False,
                "production_use_authorized":False,
            },stream,indent=2,sort_keys=True)
            stream.write("\n")
    import pyarrow as pa
    import pyarrow.parquet as pq
    sch=PHYS.schema(pa)
    folder.parent.mkdir(parents=True,exist_ok=True)
    folder.mkdir(exist_ok=False)
    db=folder/"stockday-unique.sqlite3"
    conn=sqlite3.connect(db)
    parts={}
    counts=Counter()
    try:
        conn.execute("CREATE TABLE stockday(year INTEGER NOT NULL,"
                     "symbol TEXT NOT NULL,trading_date TEXT NOT NULL,"
                     "kind TEXT NOT NULL,PRIMARY KEY(year,symbol,trading_date)) WITHOUT ROWID")
        raw=pq.ParquetFile(original,memory_map=False,pre_buffer=False)
        rel="purchased/day.parquet"
        private=folder/rel
        private.parent.mkdir(parents=True,exist_ok=False)
        sink=pq.ParquetWriter(private,sch,compression="zstd")
        digest=hashlib.sha256()
        rows=0
        try:
            if (raw.metadata.num_rows!=record["rows"]
                    or set(("ts","symbol",*PHYS.F))!=set(raw.schema_arrow.names)):
                raise ValueError("Original purchased historical Arrow footer/schema mismatched")
            for rg in range(raw.metadata.num_row_groups):
                batch=raw.read_row_group(rg,columns=["ts","symbol",*PHYS.F],
                                         use_threads=False)
                if (batch.null_count!=0):
                    raise ValueError("Purchased historical source Arrow contains nulls")
                rows+=PHYS.write_source_rows(batch.to_pylist(),"purchased_parquet",
                                             year,None,sink,conn,counts,sch,digest)
        finally:
            sink.close()
            raw.close()
        if rows!=record["rows"]:
            raise ValueError("Purchased historical annual full row-count mismatch")
        parts["purchased"]={
            "relative_file":rel,"rows":rows,
            "sha256":ST.sha(private),"source_kind":"purchased_parquet",
            "original_rows_float64_digest_sha256":digest.hexdigest(),
        }
        if year==2016:
            src=pq.ParquetFile(h5,memory_map=False,pre_buffer=False)
            rel="candidate/h5-gap-2016.parquet"
            dest=folder/rel
            dest.parent.mkdir(parents=True,exist_ok=False)
            writer=pq.ParquetWriter(dest,sch,compression="zstd")
            checksum=hashlib.sha256()
            try:
                if (src.schema_arrow!=ST.candidate_schema(pa)
                        or src.metadata.num_rows!=1):
                    raise ValueError("2016 private H5 candidate Arrow source changed")
                rows=0
                for rg in range(src.metadata.num_row_groups):
                    for item in src.read_row_group(rg,use_threads=False).to_pylist():
                        if item["value_source"]!="private_h5_mixed_stockday_candidate":
                            raise ValueError("2016 private H5-only source category changed")
                        rows+=PHYS.write_source_rows(
                            [item],item["value_source"],year,None,writer,
                            conn,counts,sch,checksum)
            finally:
                writer.close()
                src.close()
            if rows!=1:
                raise ValueError("2016 private H5 candidate must be exactly one stockday")
            parts["h5_gap_2016"]={
                "relative_file":rel,"rows":rows,"sha256":ST.sha(dest),
                "source_kind":"private_h5_mixed_stockday_candidate",
                "original_rows_float64_digest_sha256":checksum.hexdigest(),
            }
        conn.commit()
        unique=conn.execute("SELECT COUNT(*) FROM stockday").fetchone()[0]
        if (unique!=sum(counts.values())
                or conn.execute("PRAGMA integrity_check").fetchone()[0]!="ok"):
            raise ValueError("Global private historical stockday unique index failed")
    finally:
        conn.close()
    if any((folder/(db.name+ext)).exists() for ext in ("-shm","-wal","-journal")):
        raise ValueError("Historical private SQLite index has unsafe sidecar")
    # Independent local output read-back before success SAFE publication.
    for part in parts.values():
        file=folder/part["relative_file"]
        if (file.is_symlink() or file.parent.is_symlink()
                or not file.is_file() or not 0<file.stat().st_size<=MAX_PART_BYTES
                or ST.sha(file)!=part["sha256"]):
            raise ValueError("Historical physical output Parquet changed")
        pf=pq.ParquetFile(file,memory_map=False,pre_buffer=False)
        fingerprint=hashlib.sha256()
        count=0
        try:
            if pf.schema_arrow!=sch or pf.metadata.num_rows!=part["rows"]:
                raise ValueError("Historical physical output schema/footer mismatch")
            for rg in range(pf.metadata.num_row_groups):
                t=pf.read_row_group(rg,use_threads=False)
                if (t.schema!=sch or any(col.null_count for col in t.columns)):
                    raise ValueError("Historical physical output Arrow values invalid")
                for item in t.to_pylist():
                    fingerprint.update(PHYS.row_bytes(item))
                    count+=1
        finally:
            pf.close()
        if (count!=part["rows"]
                or fingerprint.hexdigest()!=part["original_rows_float64_digest_sha256"]
                or ST.sha(file)!=part["sha256"]):
            raise ValueError("Original historical float64 changed on output roundtrip")
    if (any(QDC.file_state(x)!=original_states[x.name]
            for x in (original,readme,qdc_mf))
            or QDC.digest_file(original)!=record["sha"]
            or QDC.digest_file(readme,QDC.MAX_README_BYTES)!=
                 QDC.pinned_hash(readme_sha)
            or QDC.digest_file(qdc_mf,QDC.MAX_MANIFEST_BYTES)!=
                 QDC.pinned_hash(manifest_sha)
            or V.source(candidate_safe)[1]!=source_safe_sha
            or ST.sha(source_mf)!=source_doc["manifest_sha256"]
            or (h5 is not None and ST.sha(h5)!=
                source_doc["partition_sha256"]["2016"])):
        raise ValueError("Historical purchased/H5 original source modified mid-copy")
    manifest={
        "format":FORMAT,
        "status":"private_purchased_historical_day_physical_year_not_activated",
        "year":year,
        "original_qdc_manifest_sha256":QDC.pinned_hash(manifest_sha),
        "source_purchased_original_parquet_sha256":record["sha"],
        "source_candidate_safe_sha256":source_safe_sha,
        "source_candidate_version_sha256":SOURCE_VERSION,
        "partition_files":parts,
        "original_purchased_rows":counts["purchased_parquet"],
        "h5_mixed_candidate_rows":counts["private_h5_mixed_stockday_candidate"],
        "total_private_physical_rows":unique,
        "stockday_unique_sqlite_sha256":ST.sha(db),
        "original_float64_roundtrip_exact":True,
        "original_market_files_written":False,
        "original_purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "pre2011_h5_history_included":False,
        "original_market_source_freshness_rechecked":True,
    }
    mf=folder/"manifest.json"
    with mf.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(manifest,stream,indent=2,sort_keys=True)
        stream.write("\n")
    sha=ST.sha(mf)
    if (ST.sha(db)!=manifest["stockday_unique_sqlite_sha256"]
            or any(ST.sha(folder/x["relative_file"])!=x["sha256"]
                   for x in parts.values())):
        raise ValueError("Historical private physical files changed before SAFE")
    safe={
        "format":FORMAT,
        "status":manifest["status"],
        "year":year,
        "private_relative_directory":folder.relative_to(MODULE).as_posix(),
        "private_manifest_sha256":sha,
        "private_sqlite_sha256":manifest["stockday_unique_sqlite_sha256"],
        "source_purchased_original_parquet_sha256":record["sha"],
        "source_candidate_safe_sha256":source_safe_sha,
        "source_candidate_version_sha256":SOURCE_VERSION,
        "physical_partition_sha256":{
            name:{"rows":p["rows"],"sha256":p["sha256"]}
            for name,p in parts.items()},
        "purchased_original_rows":counts["purchased_parquet"],
        "h5_mixed_candidate_rows":counts["private_h5_mixed_stockday_candidate"],
        "total_private_physical_rows":unique,
        "original_float64_roundtrip_exact":True,
        "original_market_files_written":False,
        "original_purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "no_market_ohlcva_or_symbols_in_safe":True,
    }
    with out.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(safe,stream,indent=2,sort_keys=True)
        stream.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--purchased-root",type=Path,required=True)
    p.add_argument("--candidate-safe",type=Path,required=True)
    p.add_argument("--readme-sha256",required=True)
    p.add_argument("--manifest-sha256",required=True)
    p.add_argument("--private-year-dir",type=Path,required=True)
    p.add_argument("--candidate-verification-out",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--private-historical-year-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        s=materialize(a.year,a.purchased_root,a.candidate_safe,a.readme_sha256,
                      a.manifest_sha256,a.private_year_dir,
                      a.candidate_verification_out,a.out)
        print("Historical private physical year:",s["year"])
        print("Purchased rows:",s["purchased_original_rows"])
        print("H5 mixed candidates:",s["h5_mixed_candidate_rows"])
        print("Total:",s["total_private_physical_rows"],"SAFE:",a.out)
        print("Original market/active pointer untouched; not a production conversion")
    except (OSError,ValueError,TypeError,KeyError,OverflowError,ImportError,
            sqlite3.Error):
        p.error("Historical purchased DAY annual private physical materialization refused")


if __name__=="__main__":
    main()
