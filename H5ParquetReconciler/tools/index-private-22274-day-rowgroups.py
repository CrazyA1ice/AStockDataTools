#!/usr/bin/env python3
"""Content-addressed SQLite rowgroup index for the PRIVATE 22,274 H5 day gaps.

Builder: run the existing complete 22,274-row Parquet SHA/schema/key verifier
ONCE, then create a local symbol/date -> source rowgroup index. Verify all
source keys and partition hashes again before publishing immutable index SAFE.
Reader: hash original source Parquet + index bytes, then decode only indexed
rowgroups; check exact selected key equality with index. Not fresh H5/PQ
key absence evidence, licensed physical unit certification or production.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
WORK=MODULE/"work"/"unified_parquet"
INDEX_ROOT=WORK/"candidate_indexes"
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools private 22274 daily H5 candidate rowgroup index v1"
INDEX_SQL="candidate_rowgroups.sqlite3"
MAX_INDEX_BYTES=12*1024*1024
MAX_REPORT_BYTES=1000000


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


V=load("private_22274_index_source_verified_snapshot",
       "verify-private-full-22274-gap-candidates.py")
S=V.STAGER


def report(path,must_exist):
    p=Path(path)
    if (REPORTS.is_symlink() or p.is_symlink() or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Require direct module reports/ JSON")
    if must_exist and (not p.is_file() or not 0<p.stat().st_size<=MAX_REPORT_BYTES):
        raise ValueError("Existing index SAFE missing/oversized")
    if not must_exist and p.exists():
        raise ValueError("Refuse to overwrite prior index SAFE")
    return p


def index_folder(folder,read):
    p=Path(folder)
    if (any(x.is_symlink() for x in (
            MODULE/"work",WORK,INDEX_ROOT,p))
            or not re.fullmatch(r"index_[0-9a-f]{12,32}",p.name)
            or p.resolve().parent!=INDEX_ROOT.resolve()):
        raise ValueError("Private index directory escaped module work tree")
    if read and not p.is_dir():
        raise ValueError("Private index directory absent")
    if not read and p.exists():
        raise ValueError("Private index directory already exists")
    return p


def source_snapshot(snapshot_safe):
    source, source_sha, folder, manifest_file = V.source(snapshot_safe)
    if S.sha(manifest_file)!=source["manifest_sha256"]:
        raise ValueError("Source candidate manifest SHA changed")
    manifest=json.loads(manifest_file.read_bytes())
    if (manifest.get("source_version_sha256")!=source["source_version_sha256"]
            or manifest.get("partitions") is None
            or set(manifest["partitions"])!={"2016","2026"}):
        raise ValueError("Unqualified original candidate year partitions")
    hashes={}
    for year in ("2016","2026"):
        part=manifest["partitions"][year]
        if (part.get("relative_file")!=f"year={year}/day.parquet"
                or part.get("rows")!=S.YEAR_COUNTS[int(year)]
                or source.get("partition_sha256",{}).get(year)!=part.get("sha256")):
            raise ValueError("Original candidate source year manifest differs")
        path=folder/part["relative_file"]
        if (path.parent.is_symlink() or path.is_symlink()
                or not path.is_file() or not 0<path.stat().st_size<=S.MAX_BYTES
                or S.sha(path)!=part["sha256"]):
            raise ValueError("Original private candidate Parquet bytes changed")
        hashes[year]=part["sha256"]
    return source,source_sha,folder,manifest_file,hashes


def build(snapshot_safe,folder,verification_out,out):
    target=index_folder(folder,read=False)
    verification=report(verification_out,False)
    safe_output=report(out,False)
    if verification.resolve()==safe_output.resolve():
        raise ValueError("Index build verifier and final SAFE output must differ")
    # The one-time complete source proof includes 22,274 all-row key, OHLCVA,
    # schema and SHA checks. The index inherits *only that immutable snapshot*.
    checked=V.verify(snapshot_safe,verification)
    if (checked.get("total_h5_only_day_candidates_verified")!=22274
            or checked.get("whole_date_candidate_rows_verified")!=22191
            or checked.get("mixed_date_candidate_rows_verified")!=83
            or checked.get("candidate_source_units_certified") is not False):
        raise ValueError("Only exact complete verified candidate source may be indexed")
    source,src_sha,src_dir,_,hashes=source_snapshot(snapshot_safe)
    import pyarrow.parquet as pq
    import pyarrow as pa
    schema=S.candidate_schema(pa)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.mkdir(exist_ok=False)
    db=target/INDEX_SQL
    conn=sqlite3.connect(db)
    keys=Counter()
    label_counts=Counter()
    try:
        conn.execute("CREATE TABLE stockdays (year INTEGER NOT NULL, symbol TEXT NOT NULL,"
                     " day TEXT NOT NULL, source TEXT NOT NULL, rowgroup INTEGER NOT NULL,"
                     " PRIMARY KEY(year,symbol,day)) WITHOUT ROWID")
        for year in (2016,2026):
            path=src_dir/f"year={year}"/"day.parquet"
            pf=pq.ParquetFile(path,memory_map=False,pre_buffer=False)
            try:
                if (pf.schema_arrow!=schema or pf.metadata.num_rows!=S.YEAR_COUNTS[year]
                        or not 1<=pf.metadata.num_row_groups<=32):
                    raise ValueError("Indexed candidate source schema/rowgroup changed")
                for group in range(pf.metadata.num_row_groups):
                    slice_=pf.read_row_group(group,columns=[
                        "symbol","trading_date","value_source"],use_threads=False)
                    for row in slice_.to_pylist():
                        symbol,day,label=row["symbol"],row["trading_date"],row["value_source"]
                        if (type(symbol) is not str or type(day) is not str
                                or type(label) is not str
                                or not S.CORE.is_a_share_candidate(symbol,year)
                                or date.fromisoformat(day).year!=year
                                or label not in S.SOURCES.values()
                                or day=="2026-07-16"):
                            raise ValueError("Untrusted candidate index stockday/source")
                        try:
                            conn.execute("INSERT INTO stockdays(year,symbol,day,source,rowgroup)"
                                         " VALUES(?,?,?,?,?)",(year,symbol,day,label,group))
                        except sqlite3.IntegrityError:
                            raise ValueError("Duplicate private candidate stockday in index") from None
                        keys[str(year)]+=1
                        label_counts[label]+=1
            finally:
                pf.close()
            if S.sha(path)!=hashes[str(year)]:
                raise ValueError("Candidate source changed while indexing")
        if (dict(keys)!={"2016":1,"2026":22273}
                or label_counts["private_h5_whole_date_candidate"]!=22191
                or label_counts["private_h5_mixed_stockday_candidate"]!=83
                or sum(label_counts.values())!=22274):
            raise ValueError("22,274 indexed keys do not conserve all source rows")
        conn.commit()
        count=conn.execute("SELECT COUNT(*) FROM stockdays").fetchone()[0]
        if count!=22274 or conn.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("Private SQLite index integrity/count failed")
    finally:
        conn.close()
    if (not 0<db.stat().st_size<=MAX_INDEX_BYTES
            or any((target/(INDEX_SQL+suffix)).exists()
                   for suffix in ("-wal","-shm","-journal"))):
        raise ValueError("Private index bytes/transaction sidecars unsafe")
    index_sha=S.sha(db)
    source_again,src_sha_again,_,_,hashes_again=source_snapshot(snapshot_safe)
    if (source_again!=source or src_sha_again!=src_sha or hashes_again!=hashes
            or S.sha(db)!=index_sha):
        raise ValueError("Original source or index bytes drift after building")
    manifest={
        "format":FORMAT,
        "state":"private_22274_candidate_index_not_active",
        "source_candidate_safe_sha256":src_sha,
        "source_candidate_manifest_sha256":source["manifest_sha256"],
        "source_version_sha256":source["source_version_sha256"],
        "source_year_partition_sha256":hashes,
        "index_sqlite_sha256":index_sha,
        "index_row_count":22274,
        "source_year_rows":dict(keys),
        "source_kind_counts":dict(label_counts),
        "all_22274_source_rows_verified_at_index_build":True,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "original_market_files_opened":False,
        "original_market_files_written":False,
        "purchased_parquet_replaced":False,
        "private_active_pointer_changed":False,
        "h5_mirror_created":False,
    }
    mf=target/"manifest.json"
    with mf.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(manifest,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")
    mf_sha=S.sha(mf)
    if S.sha(db)!=index_sha or S.sha(mf)!=mf_sha:
        raise ValueError("Index manifest/sqlite changed before publication")
    safe={
        "format":FORMAT,
        "state":manifest["state"],
        "index_relative_dir":target.relative_to(MODULE).as_posix(),
        "index_manifest_sha256":mf_sha,
        "index_sqlite_sha256":index_sha,
        "source_candidate_safe_sha256":src_sha,
        "source_candidate_manifest_sha256":source["manifest_sha256"],
        "source_version_sha256":source["source_version_sha256"],
        "source_year_partition_sha256":hashes,
        "index_row_count":22274,
        "source_year_rows":dict(keys),
        "source_kind_counts":dict(label_counts),
        "verified_complete_source_safe_sha256":S.sha(verification),
        "all_22274_source_rows_verified_at_index_build":True,
        "all_22274_source_rows_redecoded_per_indexed_query":False,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "original_market_files_opened":False,
        "original_market_files_written":False,
        "purchased_parquet_replaced":False,
        "private_active_pointer_changed":False,
        "h5_mirror_created":False,
        "no_raw_ohlcva_or_stock_symbols_in_aggregate_safe":True,
    }
    with safe_output.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(safe,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")
    return safe


def indexed_source(index_safe,snapshot_safe):
    path=report(index_safe,True)
    raw=path.read_bytes()
    safe=json.loads(raw)
    if (safe.get("format")!=FORMAT
            or safe.get("state")!="private_22274_candidate_index_not_active"
            or safe.get("index_row_count")!=22274
            or safe.get("source_year_rows")!={"2016":1,"2026":22273}
            or safe.get("source_kind_counts")!={
                "private_h5_whole_date_candidate":22191,
                "private_h5_mixed_stockday_candidate":83}
            or safe.get("all_22274_source_rows_verified_at_index_build") is not True
            or safe.get("all_22274_source_rows_redecoded_per_indexed_query") is not False
            or any(safe.get(k) is not False for k in (
                "candidate_source_units_certified","ready_for_production_query",
                "ready_for_automatic_market_merge","original_market_files_opened",
                "original_market_files_written","purchased_parquet_replaced",
                "private_active_pointer_changed","h5_mirror_created"))):
        raise ValueError("Unqualified private candidate index SAFE")
    rel=safe.get("index_relative_dir")
    if (type(rel) is not str or not re.fullmatch(
            r"work/unified_parquet/candidate_indexes/index_[0-9a-f]{12,32}",rel)):
        raise ValueError("Private candidate index path escaped module work")
    target=index_folder(MODULE/rel,True)
    mf=target/"manifest.json"
    db=target/INDEX_SQL
    if (mf.is_symlink() or db.is_symlink() or not mf.is_file() or not db.is_file()
            or not 0<db.stat().st_size<=MAX_INDEX_BYTES
            or S.sha(mf)!=safe.get("index_manifest_sha256")
            or S.sha(db)!=safe.get("index_sqlite_sha256")):
        raise ValueError("Private candidate SQLite/manifest bytes changed")
    manifest=json.loads(mf.read_bytes())
    common=("format","state","source_candidate_safe_sha256",
            "source_candidate_manifest_sha256","source_version_sha256",
            "source_year_partition_sha256","index_sqlite_sha256",
            "index_row_count","source_year_rows","source_kind_counts",
            "all_22274_source_rows_verified_at_index_build",
            "candidate_source_units_certified","ready_for_production_query",
            "ready_for_automatic_market_merge")
    if any(manifest.get(k)!=safe.get(k) for k in common):
        raise ValueError("Private candidate index manifest/SAFE mismatch")
    src,src_sha,folder,_,hashes=source_snapshot(snapshot_safe)
    if (src_sha!=safe["source_candidate_safe_sha256"]
            or src["manifest_sha256"]!=safe["source_candidate_manifest_sha256"]
            or src["source_version_sha256"]!=safe["source_version_sha256"]
            or hashes!=safe["source_year_partition_sha256"]):
        raise ValueError("Indexed original private candidate bytes/source changed")
    return safe,hashlib.sha256(raw).hexdigest(),target,db,folder,src,src_sha


def select(index_safe,snapshot_safe,symbols,start,end,out):
    """Hash every SOURCE partition and INDEX; decode only selected rowgroups."""
    output=report(out,False)
    safe,index_sha,target,db,src_dir,src,src_sha=indexed_source(
        index_safe,snapshot_safe)
    year=str(start.year)
    grouped={s:{"private_h5_whole_date_candidate":[],
                "private_h5_mixed_stockday_candidate":[]} for s in symbols}
    if start.year!=end.year or len(set(symbols))!=len(symbols):
        raise ValueError("Indexed daily query requires distinct symbols/same year")
    keys={}
    groups=set()
    # Open SQLite strictly READ ONLY with immutable file URI. Its bytes are
    # already SHA-verified. No wal/journal or source-market writes are allowed.
    con=sqlite3.connect(db.resolve().as_uri()+"?mode=ro&immutable=1",uri=True)
    try:
        for sym in symbols:
            got=con.execute(
                "SELECT day,rowgroup,source FROM stockdays "
                "WHERE year=? AND symbol=? AND day>=? AND day<=? ORDER BY day",
                (int(year),sym,start.isoformat(),end.isoformat())).fetchall()
            for day,rg,label in got:
                if (type(rg) is not int or rg<0
                        or type(label) is not str or label not in grouped[sym]
                        or (sym,day) in keys):
                    raise ValueError("Untrusted indexed candidate stockday key")
                keys[(sym,day)]=(rg,label)
                groups.add(rg)
    finally:
        con.close()
    if year in src["candidate_year_rows"] and groups:
        import pyarrow as pa
        import pyarrow.parquet as pq
        source_path=src_dir/f"year={year}"/"day.parquet"
        schema=S.candidate_schema(pa)
        parquet=pq.ParquetFile(source_path,memory_map=False,pre_buffer=False)
        found=set()
        try:
            if (parquet.schema_arrow!=schema
                    or parquet.metadata.num_rows!=src["candidate_year_rows"][year]):
                raise ValueError("Indexed Parquet source schema/size changed")
            for rg in sorted(groups):
                if rg>=parquet.metadata.num_row_groups:
                    raise ValueError("Indexed candidate rowgroup out of bounds")
                table=parquet.read_row_group(rg,columns=schema.names,use_threads=False)
                for row in table.to_pylist():
                    sym,day=row["symbol"],row["trading_date"]
                    key=(sym,day)
                    if key not in keys:
                        continue
                    expected_rg,label=keys[key]
                    if expected_rg!=rg or row["value_source"]!=label or key in found:
                        raise ValueError("Indexed rowgroup/key/source mismatch")
                    found.add(key)
                    grouped[sym][label].append({
                        "symbol":sym,"period":"day","trading_date":day,
                        "source_timestamp_ms":row["ts"],
                        **{f:row[f] for f in S.FIELDS},
                    })
        finally:
            parquet.close()
        if found!=set(keys):
            raise ValueError("Indexed candidate selection missed a stockday key")
    # Check all candidate source years by SHA again (not only queried year).
    src2,src_sha2,_,_,hashes2=source_snapshot(snapshot_safe)
    if (src!=src2 or src_sha!=src_sha2 or
            hashes2!=safe["source_year_partition_sha256"]
            or S.sha(db)!=safe["index_sqlite_sha256"]
            or S.sha(target/"manifest.json")!=safe["index_manifest_sha256"]
            or hashlib.sha256(report(index_safe,True).read_bytes()).hexdigest()!=index_sha):
        raise ValueError("Indexed source or private SQLite changed during query")
    result={
        "format":FORMAT,
        "state":"sha_verified_private_rowgroup_index_selection_not_full_source_reddecode",
        "source_version_sha256":src["source_version_sha256"],
        "source_candidate_safe_sha256":src_sha,
        "index_safe_sha256":index_sha,
        "index_sqlite_sha256":safe["index_sqlite_sha256"],
        "source_year_parquet_sha_verified_this_query":True,
        "index_sqlite_sha_verified_this_query":True,
        "index_built_from_all_22274_verified_source_rows":True,
        "all_22274_source_rows_decoded_this_query":False,
        "requested_stock_count":len(symbols),
        "selected_candidate_rows":len(keys),
        "candidate_rowgroups_read":len(groups),
        "original_market_files_opened":False,
        "source_market_freshness_rechecked":False,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "h5_mirror_created":False,
        "no_raw_ohlcva_or_stock_symbols_in_aggregate_safe":True,
    }
    with output.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(result,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")
    return grouped,src,src_sha,result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate-safe",type=Path,required=True)
    p.add_argument("--index-dir",type=Path,required=True)
    p.add_argument("--full-verification-out",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--build-index-private-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=build(a.candidate_safe,a.index_dir,a.full_verification_out,a.out)
        print("Full private candidate rows indexed:",result["index_row_count"])
        print("Indexed source Parquet SHA & SQLite SHA sealed; NOT production")
        print("SAFE:",a.out)
    except (OSError,ValueError,TypeError,KeyError,ImportError,sqlite3.Error):
        p.error("Private 22274 candidate index build failed closed")


if __name__=="__main__":
    main()
