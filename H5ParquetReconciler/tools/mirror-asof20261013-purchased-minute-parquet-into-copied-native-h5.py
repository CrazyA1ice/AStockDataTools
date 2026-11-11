#!/usr/bin/env python3
"""Real bounded Parquet-primary 1m/5m into COPIES of original Hikyuu H5.

Stage purchased Parquet into an on-disk (period,symbol,native-end-time)
SQLite integer-key store, never build a whole-market Python object. Read only
footer-pruned rowgroups for the requested 2026 Sep source days. Copy original
H5 ONCE, then replace only overlapping original native keys in the copies.
All original-only keys and other H5 groups survive. Full typed INTEGER
readback per changed stock. Purchased amount/volume scaling is a CANDIDATE
and must not be declared vendor-certified. NO source-market modifications.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import struct
import traceback
from collections import Counter
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
MIRRORS=MODULE/"work"/"h5_mirror"
SOURCE_SHA="a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01"
SOURCE_NAME="eight_cycle_asof_20261013_"+SOURCE_SHA[:16]
PERIODS=("1min","5min")
MARKETS=("sh","sz","bj")
RUN=re.compile(r"[0-9a-f]{12}\Z")
UTC8=timezone(timedelta(hours=8))
NAME="asof_20261013_purchased_minute_into_original_copy_native_H5_v1"
STATUS="purchased_2026_september_bounded_native_1m5m_H5_copy_merged_verified"

def local(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

D=local("approved_eight_cycle_parquet_physical_manifest",
        "build-asof20261013-unified-eight-cycle-parquet-dataset.py")
N=local("previous_native_minute_float_and_clock_mapping",
        "mirror-real-purchased-first-minute-unified-parquet-to-native-h5.py")
C=local("original_stock_security_code_aliases",
        "reconcile-local-a-share-h5-parquet.py")
MERGE=local("preserve_native_h5_original_only_keys",
            "merge-existing-native-day-h5-original-history-and-2011-2026-parquet-mirror.py")

def stamp(day):
    return int(datetime(day.year,day.month,day.day,tzinfo=UTC8).timestamp()*1000)

def validate_days(first,last):
    start,end=date.fromisoformat(first),date.fromisoformat(last)
    if (start>end or start.year!=2026 or end.year!=2026
            or start<date(2026,9,1) or end>date(2026,9,30)
            or (end-start).days>2):
        raise ValueError("Bound actual first native minute H5 wave to <=3 September 2026 days")
    return start,end

def src_input(root,manifest,expected_sha):
    path=Path(manifest)
    if expected_sha!=SOURCE_SHA:
        raise ValueError("Unaccepted eight-cycle purchased-primary source identity")
    expected=D.DATASETS/SOURCE_NAME/"manifest.json"
    if path.resolve()!=expected.resolve():
        raise ValueError("Require previously accepted eight-cycle dataset manifest path")
    payload,version=D.load_manifest(
        path,root,expected_sha=expected_sha,verify_sources=False)
    if (version!=SOURCE_SHA or payload["asof_inclusive"]!="2026-10-13"
            or payload["ready_for_production_query"] is not False):
        raise ValueError("Eight-cycle accepted physical manifest changed")
    return payload

def purchased_refs(payload,root):
    records={}
    for period in PERIODS:
        refs=[]
        for entry in payload["period_physical_files"][period]:
            if entry["source_class"]!="purchased_original":
                continue
            file=D.checked(entry["root_kind"],entry["relative_file"],
                           Path(root).resolve(),D.MODULE,
                           purchased_stat=entry.get("source_stat"))
            refs.append((file,entry))
        if not refs:
            raise ValueError("No original purchased minute Parquet physical file")
        records[period]=refs
    return records

def stage_sqlite(dbpath,refs,root,start,end,*,max_source_rows=12000000):
    """Only purchased rows, no H5 raw re-conversion or purchased file rewrite."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    lower=stamp(start)
    upper=stamp(end+timedelta(days=1))
    calendar={}
    day=start
    while day<=end:
        for period in PERIODS:
            calendar[period,day]=N.purchased_minute_map(day,period)
        day+=timedelta(days=1)
    store=sqlite3.connect(str(dbpath))
    counts=Counter()
    skipped=Counter()
    files_examined=Counter()
    rowgroups_read=Counter()
    source_rows_read=Counter()
    changed=Counter()
    maximum=Counter()
    src_states={}
    try:
        store.execute("PRAGMA synchronous=FULL")
        store.execute("CREATE TABLE bars (period TEXT NOT NULL,symbol TEXT NOT NULL,"
                      "stamp INTEGER NOT NULL,record BLOB NOT NULL,"
                      "PRIMARY KEY(period,symbol,stamp)) WITHOUT ROWID")
        for period in PERIODS:
            for path,entry in refs[period]:
                src_states[str(path)]=(path.stat().st_size,path.stat().st_mtime_ns)
                with pq.ParquetFile(path,memory_map=False,pre_buffer=False) as file:
                    if not set(D.RAW_COLS).issubset(file.schema_arrow.names):
                        raise ValueError("Unrecognized purchased minute OHLCVA columns")
                    files_examined[period]+=1
                    rg_count=file.metadata.num_row_groups
                    for gi in range(rg_count):
                        meta=file.metadata.row_group(gi)
                        if meta.num_rows<1:
                            continue
                        idx=file.schema_arrow.get_field_index("ts")
                        if idx<0:
                            raise ValueError("Missing source timestamp column")
                        # Map Arrow schema name to actual Parquet metadata index.
                        parquet_idx=file.schema.names.index("ts")
                        stats=meta.column(parquet_idx).statistics
                        if (stats is None or not stats.has_min_max
                                or not isinstance(stats.min,int)
                                or not isinstance(stats.max,int)):
                            raise ValueError("Original purchased time envelope not proven")
                        if stats.max<lower or stats.min>=upper:
                            continue
                        rowgroups_read[period]+=1
                        for batch in file.iter_batches(
                                row_groups=[gi],columns=list(D.RAW_COLS),
                                batch_size=32768,use_threads=False):
                            source_rows_read[period]+=batch.num_rows
                            mask=pc.and_(pc.greater_equal(batch.column(0),lower),
                                         pc.less(batch.column(0),upper))
                            selected=batch.filter(mask)
                            if selected.num_rows==0:
                                continue
                            inserts=[]
                            for row in selected.to_pylist():
                                t=row["ts"]
                                day=datetime.fromtimestamp(t/1000,tz=UTC8).date()
                                normalized=C.symbol_id(row["symbol"])
                                if normalized is None or not C.is_a_share_candidate(
                                        normalized,2026):
                                    skipped[period]+=1
                                    continue
                                clock=calendar[period,day]
                                native,errors=N.raw_purchased(row,clock)
                                blob=struct.pack("<IQIIIQQ",
                                    native["closePrice"],native["datetime"],
                                    native["highPrice"],native["lowPrice"],
                                    native["openPrice"],native["transAmount"],
                                    native["transCount"])
                                inserts.append((period,normalized,
                                                native["datetime"],blob))
                                for field,e in errors.items():
                                    if e:
                                        changed[period+"_"+field]+=1
                                        maximum[period+"_"+field]=max(
                                            maximum[period+"_"+field],e)
                            if inserts:
                                try:
                                    store.executemany(
                                        "INSERT INTO bars(period,symbol,stamp,record)"
                                        " VALUES (?,?,?,?)",inserts)
                                except sqlite3.IntegrityError as exc:
                                    raise ValueError(
                                        "Duplicate normalized purchased (period,symbol,native time) key") from exc
                                counts[period]+=len(inserts)
                                if sum(counts.values())>max_source_rows:
                                    raise ValueError("Too many real purchased bars for bounded H5 wave")
                st=path.stat()
                if (st.st_size,st.st_mtime_ns)!=src_states[str(path)]:
                    raise ValueError("Original purchased Parquet source changed during read")
                if (st.st_size!=entry["source_stat"]["size_bytes"]
                        or st.st_mtime_ns!=entry["source_stat"]["mtime_ns"]):
                    raise ValueError("Vendor Parquet source drift since physical manifest")
        store.commit()
        return store,{
            "purchased_canonical_a_share_rows":dict(counts),
            "non_A_share_or_unrecognized_source_rows_skipped":dict(skipped),
            "source_parquet_files_footer_opened":dict(files_examined),
            "source_parquet_rowgroups_with_requested_time_scanned":dict(rowgroups_read),
            "source_rowgroup_rows_scanned_not_market_rows_copied":dict(source_rows_read),
            "quantized_changed_rows_by_field":dict(changed),
            "max_absolute_candidate_unit_loss":{k:float(v) for k,v in maximum.items()},
            "source_identity_is_stat_not_commercial_full_SHA":True,
        }
    except Exception:
        store.close()
        raise

def source_h5(root):
    folder=Path(root)/"HikyuuData"
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Original Hikyuu native minute root unavailable")
    result={}
    for period in PERIODS:
        for market in MARKETS:
            source=folder/(market+"_"+period+".h5")
            if source.is_symlink() or not source.is_file():
                raise ValueError("Original native H5 minute file missing")
            result[period,market]=source
    return result

def merge_wave(root,manifest,sha,first,last,run_id,out,*,max_source_rows=12000000):
    import numpy as np
    import tables
    start,end=validate_days(first,last)
    if type(run_id) is not str or RUN.fullmatch(run_id) is None:
        raise ValueError("Require bounded run ID")
    output=Path(out)
    dest=MIRRORS/("minute_purchased_wave_"+run_id)
    if (output.suffix!=".json" or output.is_symlink() or output.exists()
            or output.resolve().parent!=REPORTS.resolve()
            or dest.exists() or dest.is_symlink()
            or any(x.is_symlink() for x in (MODULE/"work",MIRRORS,REPORTS))
            or not Path(root).is_dir() or Path(root).is_symlink()
            or Path(root).resolve().is_relative_to(MODULE.resolve())):
        raise ValueError("Cannot write outside unique isolated native H5 mirror directory")
    payload=src_input(root,manifest,sha)
    refs=purchased_refs(payload,root)
    originals=source_h5(root)
    original_stat={(p,m):(f.stat().st_size,f.stat().st_mtime_ns)
                   for (p,m),f in originals.items()}
    total_size=sum(s[0] for s in original_stat.values())
    MIRRORS.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(MIRRORS).free < total_size*1.20 + 250000000:
        raise ValueError("Insufficient free disk for full original-H5 COPY and temp key index")
    dest.mkdir(exist_ok=False)
    dbfile=dest/"minute_purchased_new_keys.sqlite3"
    store,scan=stage_sqlite(dbfile,refs,root,start,end,
                            max_source_rows=max_source_rows)
    dtype=MERGE.canonical_dtype(np)
    changed_stocks=Counter()
    total_after=Counter()
    purchased=Counter()
    originals_replaced=Counter()
    original_keys_kept=Counter()
    try:
        for period in PERIODS:
            for market in MARKETS:
                file=originals[period,market]
                copy=dest/file.name
                shutil.copyfile(file,copy)
                with tables.open_file(str(copy),"a") as target:
                    if not hasattr(target.root,"data"):
                        raise ValueError("Copied Hikyuu native minute H5 lacks /data")
                    sql=store.execute(
                        "SELECT DISTINCT symbol FROM bars WHERE period=? "
                        "AND symbol LIKE ? ORDER BY symbol",
                        (period,market.upper()+"%"))
                    for (sym,) in sql:
                        records=store.execute(
                            "SELECT record FROM bars WHERE period=? AND symbol=? "
                            "ORDER BY stamp",(period,sym)).fetchall()
                        if not records:
                            raise ValueError("No purchased native minute bars for key")
                        if len(records)>(end-start).days*241+241:
                            raise ValueError("Unbounded per-stock purchased wave rows")
                        raw=b"".join(b for (b,) in records)
                        modern=np.frombuffer(raw,dtype=dtype).copy()
                        try:
                            old=target.get_node("/data/"+sym).read()
                            exists=True
                        except tables.NoSuchNodeError:
                            old=np.empty(0,dtype=dtype)
                            exists=False
                        combined,counts=MERGE.merge_stock(old,modern,np,dtype)
                        tbl=target.create_table("/data","_new_"+sym,
                            description=dtype,title=sym,expectedrows=len(combined),
                            filters=tables.Filters(
                                complevel=5,complib="zlib",shuffle=True))
                        for pos in range(0,len(combined),16384):
                            tbl.append(combined[pos:pos+16384])
                        tbl.flush()
                        if exists:
                            target.remove_node("/data",sym)
                        target.rename_node(tbl,sym)
                        new=target.get_node("/data/"+sym)
                        if (new.dtype!=dtype or int(new.nrows)!=len(combined)
                                or new.read().tobytes()!=combined.tobytes()):
                            raise ValueError("Full copied native minute H5 integer row readback differs")
                        changed_stocks[period]+=1
                        purchased[period]+=len(modern)
                        originals_replaced[period]+=counts[
                            "original_post2010_replaced_by_purchased"]
                        original_keys_kept[period]+=len(combined)-len(modern)
                        total_after[period]+=len(combined)
                    target.flush()
                print("DONE_MINUTE_H5_COPY_SOURCE="+period+"/"+market.upper()+
                      " STOCKS="+str(changed_stocks[period]),flush=True)
                after=file.stat()
                if (after.st_size,after.st_mtime_ns)!=original_stat[period,market]:
                    raise ValueError("Original Hikyuu native H5 modified while copied")
        if any(purchased[p]!=scan["purchased_canonical_a_share_rows"].get(p,0)
               or purchased[p]<=0 for p in PERIODS):
            raise ValueError("Purchased native minute rows not conserved")
        result={
            "status":STATUS,"format":NAME,
            "window":[first,last],
            "physical_dataset_sha256":sha,
            "native_h5_files":6,
            "purchased_parquet_source_rows_written_as_native_h5":dict(purchased),
            "changed_native_stock_tables":dict(changed_stocks),
            "original_h5_same_keys_overridden_from_purchased":dict(originals_replaced),
            "original_h5_only_keys_preserved_in_changed_stocks":dict(original_keys_kept),
            "copied_h5_rows_in_changed_stocks":dict(total_after),
            "purchased_source_scan":scan,
            "native_minute_table_40byte_all_changed_stock_integer_readback_verified":True,
            "all_original_H5_files_copied_and_untouched":True,
            "original_purchased_parquet_files_unmodified":True,
            "purchase_numeric_units_and_time_labels_vendor_certified":False,
            "whole_history_H5_completed":False,
            "production_H5_activated":False,
            "new_native_h5_files_sha256":{
                p.name:MERGE.sha(p) for p in sorted(dest.glob("*.h5"))},
        }
        output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",
                          encoding="utf-8")
        print("PASS_PURCHASED_2026_MINUTE_PARQUET_INTO_COPIED_HIKYUU_H5="+
              json.dumps({"window":[first,last],"run_id":run_id,
                           "source_parquet_rows":dict(purchased),
                           "h5_copies":6,"original_modified":False},
                         sort_keys=True),flush=True)
        return result
    finally:
        store.close()

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--manifest",required=True,type=Path)
    p.add_argument("--dataset-sha256",default=SOURCE_SHA)
    p.add_argument("--from-day",required=True)
    p.add_argument("--through-day",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--max-source-rows",type=int,default=12000000)
    p.add_argument("--write-isolated-minute-h5",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        merge_wave(a.root,a.manifest,a.dataset_sha256,a.from_day,
                   a.through_day,a.run_id,a.out,
                   max_source_rows=a.max_source_rows)
    except Exception as exc:
        last=traceback.extract_tb(exc.__traceback__)[-1]
        p.error("Native minute H5 copied-source purchased-primary wave REFUSED ["+
                type(exc).__name__+"/"+last.name+":"+str(last.lineno)+
                "]; original Parquet/H5 sources not modified")

if __name__=="__main__":
    main()
