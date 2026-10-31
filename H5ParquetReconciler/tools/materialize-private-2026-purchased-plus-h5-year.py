#!/usr/bin/env python3
"""Private physical YEAR=2026 purchased DAY + verified H5-gap candidate dataset.

This is a new immutable research-only *candidate* dataset, NOT replacement
of purchased Parquet, a production database, or an authorized Hikyuu mirror.
Nine original purchased 2026 monthly Parquets are full SHA-verified against
the customer's received QDC bundle manifest. Original OHLCVA floats and raw
timestamps are copied without rescaling. The 22,273 H5-only candidates for
2026 retain their separate whole/mixed provenance. A private SQLite unique
(year,symbol,day) constraint checks ALL purchased+H5 keys before SAFE publish.
No original source files or active pointers are written.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import re
import sqlite3
import struct
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
WORK=MODULE/"work"/"unified_parquet"
ROOT=WORK/"physical_years"
REPORTS=MODULE/"reports"
YEAR=2026
FORMAT="AStockDataTools private purchased-first physical 2026 DAY with H5 candidate v1"
F=("open","high","low","close","volume","amount")
SOURCE_KINDS={
    "purchased_parquet",
    "private_h5_whole_date_candidate",
    "private_h5_mixed_stockday_candidate",
}
EXPECTED_MONTH_FILES={f"2026-{m:02d}.parquet" for m in range(1,10)}
MAX_ROWS=5_000_000
MAX_PART_BYTES=512*1024*1024


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


QDC=load("physical_2026_qdc_manifest_source",
         "verify-qdc-purchased-day-bundle-integrity-readonly.py")
V=load("physical_2026_h5_gap_candidate_verifier",
       "verify-private-full-22274-gap-candidates.py")
ST=V.STAGER


def output_paths(directory,precheck,report):
    d=Path(directory)
    if (any(p.is_symlink() for p in (MODULE/"work",WORK,ROOT,REPORTS))
            or d.is_symlink() or d.exists()
            or not re.fullmatch("physical_2026_[0-9a-f]{12,32}",d.name)
            or d.resolve().parent!=ROOT.resolve()):
        raise ValueError("Require new module work/unified_parquet/physical_years/physical_2026_<hex>")
    p1,p2=Path(precheck),Path(report)
    if (p1.resolve()==p2.resolve()
            or any(p.is_symlink() or p.exists() or p.suffix!=".json"
                   or p.resolve().parent!=REPORTS.resolve() for p in (p1,p2))):
        raise ValueError("Require distinct NEW module reports/ SAFE outputs")
    return d.resolve(),p1.resolve(),p2.resolve()


def schema(pa):
    return pa.schema([
        pa.field("ts",pa.int64()),
        pa.field("trading_date",pa.string()),
        pa.field("symbol",pa.string()),
        pa.field("source_symbol",pa.string()),
        *(pa.field(f,pa.float64()) for f in F),
        pa.field("value_source",pa.string()),
    ])


def normalise(raw,kind,year=YEAR,month=None):
    if (type(raw) is not dict or kind not in SOURCE_KINDS
            or type(raw.get("symbol")) is not str
            or type(raw.get("ts")) is not int):
        raise ValueError("Invalid purchased/H5 input stockday schema")
    source_symbol=raw["symbol"]
    canonical=ST.CORE.symbol_id(source_symbol)
    if canonical is None:
        raise ValueError("Original market stock symbol cannot be mapped conservatively")
    try:
        dt=datetime.fromtimestamp(raw["ts"]/1000,tz=ST.CORE.UTC8)
    except (ValueError,OverflowError,OSError):
        raise ValueError("Original stockday timestamp is not valid") from None
    day=dt.date().isoformat()
    if dt.year!=year or (month is not None and dt.month!=month):
        raise ValueError("Purchased monthly source day escaped its declared partition")
    if kind!="purchased_parquet":
        if (raw.get("trading_date")!=day
                or raw.get("value_source")!=kind
                or day=="2026-07-16"
                or dt.time().hour!=0 or dt.time().minute!=0
                or dt.time().second!=0 or dt.time().microsecond!=0
                or not ST.CORE.is_a_share_candidate(canonical,year)):
            raise ValueError("Private H5 candidate provenance/date is not certified")
    values={}
    for f in F:
        x=raw.get(f)
        if type(x) is not float or not math.isfinite(x) or x<0:
            raise ValueError("Nonfloat64 or invalid original source OHLCVA")
        values[f]=x
    op,hi,lo,cl=(values[k] for k in F[:4])
    if min(op,hi,lo,cl)<=0 or hi+1e-8<max(op,lo,cl) or lo-1e-8>min(op,hi,cl):
        raise ValueError("Purchased/H5 stockday OHLC geometry is invalid")
    return {
        "ts":raw["ts"],"trading_date":day,
        "symbol":canonical,"source_symbol":source_symbol,
        **values,"value_source":kind,
    }


def row_bytes(item):
    """Exact float64+raw-label bytes; a local roundtrip digest, not vendor proof."""
    return (item["symbol"].encode("utf-8")+b"\0"+
            item["source_symbol"].encode("utf-8")+b"\0"+
            item["trading_date"].encode("ascii")+b"\0"+
            item["value_source"].encode("ascii")+b"\0"+
            struct.pack(">q6d",item["ts"],*(item[f] for f in F)))


def write_source_rows(rows,kind,year,month,writer,connection,counters,arrow_schema,
                      source_digest=None):
    """Streaming per-source row validation + global stockday unique constraint."""
    import pyarrow as pa
    out=[]
    for raw in rows:
        item=normalise(raw,kind,year,month)
        try:
            connection.execute(
                "INSERT INTO stockday(year,symbol,trading_date,kind) VALUES(?,?,?,?)",
                (year,item["symbol"],item["trading_date"],kind))
        except sqlite3.IntegrityError:
            raise ValueError("Duplicate purchased/purchased or purchased/H5 stockday; fail closed") from None
        out.append(item)
        if source_digest is not None:
            source_digest.update(row_bytes(item))
        counters[kind]+=1
        if sum(counters.values())>MAX_ROWS:
            raise ValueError("Year source rows exceed private materialization budget")
    if out:
        writer.write_table(pa.Table.from_pylist(out,schema=arrow_schema),
                           row_group_size=8192)
    return len(out)


def purchased_manifest(root,readme_sha,manifest_sha):
    source=Path(root)
    if (not source.is_absolute() or source.is_symlink() or not source.is_dir()
            or source.resolve()!=source):
        raise ValueError("Purchased QDC source must be canonical absolute directory")
    day=source/"day"
    if not day.is_dir() or day.is_symlink():
        raise ValueError("Original purchased day directory is unsafe")
    readme=source/"【先看我】数据说明.txt"
    manifest_file=source/"文件校验清单.txt"
    if (QDC.digest_file(readme,QDC.MAX_README_BYTES)!=QDC.pinned_hash(readme_sha)
            or QDC.digest_file(manifest_file,QDC.MAX_MANIFEST_BYTES)!=
            QDC.pinned_hash(manifest_sha)):
        raise ValueError("Original QDC README or full manifest SHA mismatch")
    records=QDC.parse_manifest(manifest_file.read_bytes())
    discovered={
        p.name:p for p in day.iterdir()
        if p.suffix.lower()==".parquet" and p.name.startswith("2026-")
    }
    if (set(discovered)!=EXPECTED_MONTH_FILES
            or any(x.is_symlink() or not x.is_file()
                   or x.resolve().parent!=day.resolve() for x in discovered.values())):
        raise ValueError("Original purchased 2026 day partition set changed")
    return source,readme,manifest_file,discovered,records


def materialize(source_root,candidate_safe,readme_sha,manifest_sha,
                destination,full_recheck_safe,output_safe):
    directory,gate,out=output_paths(destination,full_recheck_safe,output_safe)
    source,readme,original_manifest,files,records=purchased_manifest(
        source_root,readme_sha,manifest_sha)
    # Full private 22,274 source audit: performed once BEFORE any new output.
    verified=V.verify(candidate_safe,gate)
    if (verified.get("total_h5_only_day_candidates_verified")!=22274
            or verified.get("whole_date_candidate_rows_verified")!=22191
            or verified.get("mixed_date_candidate_rows_verified")!=83
            or verified.get("candidate_source_units_certified") is not False):
        raise ValueError("Only exact all-row audited H5 candidate may be materialized")
    candidate, candidate_sha, source_folder, source_manifest=V.source(candidate_safe)
    if (candidate.get("candidate_year_rows")!={"2016":1,"2026":22273}
            or candidate.get("source_version_sha256")!=
                "e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23"):
        raise ValueError("Expected immutable 22,274 source version not available")
    cand_path=source_folder/"year=2026"/"day.parquet"
    original_state={p.name:QDC.file_state(p) for p in (readme,original_manifest,*files.values())}
    source_hashes={}
    for name,path in files.items():
        if (QDC.file_state(path)[0]!=records[name]["size"]
                or QDC.digest_file(path)!=records[name]["sha"]):
            raise ValueError("Original purchased month SHA differs from QDC received bundle")
        source_hashes[name]=records[name]["sha"]
    import pyarrow as pa
    import pyarrow.parquet as pq
    sch=schema(pa)
    directory.parent.mkdir(parents=True,exist_ok=True)
    directory.mkdir(exist_ok=False)
    con=sqlite3.connect(directory/"stockday-unique.sqlite3")
    results={}
    counters=Counter()
    try:
        con.execute("CREATE TABLE stockday (year INTEGER NOT NULL, symbol TEXT NOT NULL,"
                    " trading_date TEXT NOT NULL,kind TEXT NOT NULL,"
                    " PRIMARY KEY(year,symbol,trading_date)) WITHOUT ROWID")
        for m in range(1,10):
            name=f"2026-{m:02d}.parquet"
            path=files[name]
            reader=pq.ParquetFile(path,memory_map=False,pre_buffer=False)
            relative=f"purchased/month={m:02d}/day.parquet"
            dst=directory/relative
            dst.parent.mkdir(parents=True,exist_ok=False)
            count=0
            source_digest=hashlib.sha256()
            w=pq.ParquetWriter(dst,sch,compression="zstd")
            try:
                if (reader.metadata.num_rows!=records[name]["rows"]
                        or not set(("symbol","ts",*F)).issubset(reader.schema_arrow.names)):
                    raise ValueError("Purchased original Parquet footer/schema mismatch")
                for rg in range(reader.metadata.num_row_groups):
                    batch=reader.read_row_group(rg,columns=["ts","symbol",*F],
                                                use_threads=False)
                    count+=write_source_rows(batch.to_pylist(),"purchased_parquet",
                        YEAR,m,w,con,counters,sch,source_digest)
            finally:
                w.close()
                reader.close()
            if count!=records[name]["rows"]:
                raise ValueError("Purchased monthly stockday count differs from bundle manifest")
            results[name]={
                "relative_file":relative,"rows":count,"sha256":ST.sha(dst),
                "source_kind":"purchased_parquet",
                "original_rows_float64_digest_sha256":source_digest.hexdigest(),
            }
        candidate_pf=pq.ParquetFile(cand_path,memory_map=False,pre_buffer=False)
        rel="candidate/h5-gap-2026.parquet"
        dst=directory/rel
        dst.parent.mkdir(parents=True,exist_ok=False)
        source_digest=hashlib.sha256()
        w=pq.ParquetWriter(dst,sch,compression="zstd")
        try:
            if (candidate_pf.schema_arrow!=ST.candidate_schema(pa)
                    or candidate_pf.metadata.num_rows!=22273):
                raise ValueError("2026 H5-only candidate source Parquet schema/footer mismatch")
            count=0
            for rg in range(candidate_pf.metadata.num_row_groups):
                table=candidate_pf.read_row_group(rg,use_threads=False)
                source_rows=table.to_pylist()
                # Stable source ordering matters for reproducible physical
                # row fingerprints; never depend on Python set iteration.
                for kind in ("private_h5_whole_date_candidate",
                             "private_h5_mixed_stockday_candidate"):
                    subset=[r for r in source_rows if r["value_source"]==kind]
                    count+=write_source_rows(subset,kind,YEAR,None,w,con,counters,sch,
                                             source_digest)
        finally:
            w.close()
            candidate_pf.close()
        if count!=22273 or counters["private_h5_whole_date_candidate"]!=22191 or (
                counters["private_h5_mixed_stockday_candidate"]!=82):
            raise ValueError("Full 2026 H5 candidate counts/source provenance disagree")
        results["h5_gap_2026"]={
            "relative_file":rel,"rows":count,"sha256":ST.sha(dst),
            "source_kind":"mixed_whole_h5_candidates",
            "original_rows_float64_digest_sha256":source_digest.hexdigest(),
        }
        con.commit()
        total=con.execute("SELECT COUNT(*) FROM stockday").fetchone()[0]
        if (total!=sum(counters.values())
                or con.execute("PRAGMA integrity_check").fetchone()[0]!="ok"):
            raise ValueError("Global purchased/H5 stockday uniqueness or SQLite integrity failed")
    finally:
        con.close()
    index=directory/"stockday-unique.sqlite3"
    if any((directory/(index.name+x)).exists() for x in ("-wal","-shm","-journal")):
        raise ValueError("Private global stockday unique index left SQLite sidecars")
    # Re-read all physical partition values; fail closed on decoding mismatch.
    # Input values were streamed to writer from source without adjustment.
    for part in results.values():
        file=directory/part["relative_file"]
        if (file.is_symlink() or not 0<file.stat().st_size<=MAX_PART_BYTES
                or ST.sha(file)!=part["sha256"]):
            raise ValueError("Written private 2026 partition bytes drifted")
        pqf=pq.ParquetFile(file,memory_map=False,pre_buffer=False)
        check_digest=hashlib.sha256()
        try:
            if pqf.schema_arrow!=sch or pqf.metadata.num_rows!=part["rows"]:
                raise ValueError("Written 2026 partition Arrow/footer mismatch")
            for rg in range(pqf.metadata.num_row_groups):
                # Read all actual market values, not only footer row counts.
                t=pqf.read_row_group(rg,use_threads=False)
                if (t.schema!=sch or t.num_rows>8192 or
                        any(col.null_count for col in t.columns)):
                    raise ValueError("Written private 2026 Arrow data malformed")
                for item in t.to_pylist():
                    check_digest.update(row_bytes(item))
        finally:
            pqf.close()
        if check_digest.hexdigest()!=part["original_rows_float64_digest_sha256"]:
            raise ValueError("Private 2026 purchased/H5 original float64 roundtrip digest mismatch")
    # Full SHA for original licensed inputs before and after materialization;
    # original bundle README/manifest unchanged, candidate snapshots unchanged.
    if (any(QDC.file_state(p)!=original_state[p.name]
            for p in (readme,original_manifest,*files.values()))
            or QDC.digest_file(readme,QDC.MAX_README_BYTES)!=
                QDC.pinned_hash(readme_sha)
            or QDC.digest_file(original_manifest,QDC.MAX_MANIFEST_BYTES)!=
                QDC.pinned_hash(manifest_sha)
            or any(QDC.digest_file(files[n])!=h for n,h in source_hashes.items())
            or V.source(candidate_safe)[1]!=candidate_sha
            or ST.sha(source_manifest)!=candidate["manifest_sha256"]
            or ST.sha(cand_path)!=candidate["partition_sha256"]["2026"]):
        raise ValueError("Original purchased or candidate source changed mid-materialization")
    m={
        "format":FORMAT,
        "status":"private_full_2026_purchased_and_h5_candidate_physical_not_activated",
        "year":YEAR,
        "source_qdc_readme_sha256":QDC.pinned_hash(readme_sha),
        "source_qdc_manifest_sha256":QDC.pinned_hash(manifest_sha),
        "source_private_candidate_safe_sha256":candidate_sha,
        "source_private_version_sha256":candidate["source_version_sha256"],
        "purchased_original_2026_source_files":len(files),
        "source_purchased_original_file_sha256":source_hashes,
        "partition_files":results,
        "purchased_original_rows":counters["purchased_parquet"],
        "h5_whole_candidate_rows":counters["private_h5_whole_date_candidate"],
        "h5_mixed_candidate_rows":counters["private_h5_mixed_stockday_candidate"],
        "total_private_physical_rows":total,
        "global_stockday_unique_index_sha256":ST.sha(index),
        "all_purchased_source_floats_unmodified":True,
        "h5_units_remain_uncertified_candidates":True,
        "vendor_source_authenticity_independently_certified":False,
        "candidate_source_units_certified":False,
        "historical_2011_2025_purchased_all_included":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "original_market_files_written":False,
        "original_purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
    }
    manifest=directory/"manifest.json"
    with manifest.open("x",encoding="utf-8",newline="\n") as fp:
        json.dump(m,fp,indent=2,sort_keys=True,ensure_ascii=False)
        fp.write("\n")
    manifest_sha=ST.sha(manifest)
    if (manifest_sha!=ST.sha(manifest) or ST.sha(index)!=m["global_stockday_unique_index_sha256"]
            or any(ST.sha(directory[p["relative_file"]])!=p["sha256"]
                   for p in results.values())):
        raise ValueError("2026 physical private output bytes changed before success SAFE")
    safe={
        "format":FORMAT,"status":m["status"],"year":YEAR,
        "private_relative_directory":directory.relative_to(MODULE).as_posix(),
        "private_manifest_sha256":manifest_sha,
        "private_stockday_unique_index_sha256":m["global_stockday_unique_index_sha256"],
        "physical_partition_sha256":{
            k:{"sha256":p["sha256"],"rows":p["rows"]}
            for k,p in results.items()},
        "purchased_original_2026_source_files":len(files),
        "purchased_original_rows":m["purchased_original_rows"],
        "h5_whole_candidate_rows":m["h5_whole_candidate_rows"],
        "h5_mixed_candidate_rows":m["h5_mixed_candidate_rows"],
        "total_private_physical_rows":total,
        "source_private_candidate_safe_sha256":candidate_sha,
        "source_private_version_sha256":m["source_private_version_sha256"],
        "source_qdc_manifest_sha256":m["source_qdc_manifest_sha256"],
        "source_all_nine_2026_original_purchased_parquet_sha_verified":True,
        "original_market_files_written":False,
        "original_purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "historical_2011_2025_purchased_all_included":False,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
        "no_market_ohlcva_or_stock_symbols_exported_in_safe":True,
    }
    with out.open("x",encoding="utf-8",newline="\n") as fp:
        json.dump(safe,fp,indent=2,sort_keys=True,ensure_ascii=False)
        fp.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--purchased-root",type=Path,required=True)
    p.add_argument("--candidate-safe",type=Path,required=True)
    p.add_argument("--readme-sha256",required=True)
    p.add_argument("--manifest-sha256",required=True)
    p.add_argument("--private-year-dir",type=Path,required=True)
    p.add_argument("--candidate-verification-out",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--private-physical-2026-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=materialize(a.purchased_root,a.candidate_safe,
            a.readme_sha256,a.manifest_sha256,a.private_year_dir,
            a.candidate_verification_out,a.out)
        print("Private 2026 physical DAY stockdays:",result["total_private_physical_rows"])
        print("Purchased original:",result["purchased_original_rows"],
              "H5 whole:",result["h5_whole_candidate_rows"],
              "H5 mixed:",result["h5_mixed_candidate_rows"])
        print("SAFE:",a.out)
        print("Original purchased/H5 untouched, NO production or H5 mirror")
    except (OSError,ValueError,TypeError,KeyError,ImportError,OverflowError,
            sqlite3.Error):
        p.error("2026 purchased+H5 private physical DAY year materialization refused")


if __name__=="__main__":
    main()
