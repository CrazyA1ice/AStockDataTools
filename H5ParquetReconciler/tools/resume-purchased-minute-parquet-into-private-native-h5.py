#!/usr/bin/env python3
"""Persistent, resumable Parquet-first Hikyuu minute H5 candidate (NOT market).

ONE-TIME copies six accepted native 1min/5min H5 files (already including
previous 6,427,013 four-day records and Sep24 1,609,152 purchased records).
Thereafter new 1-3 day purchased batches UPDATE ONLY THESE SIX PRIVATE COPIES
with per-stock H5 scratch/undo TABLEs and a committed SQLite progress journal.
No additional six-file original copy for each day; no purchased OHLCVA copy
into separate Parquet; no original D:/stock market file opens in write mode.
Do not activate Hikyuu production: purchased minute units remain hypotheses.
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
import traceback
from collections import Counter
from contextlib import contextmanager
from datetime import date,datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
MIRRORS=MODULE/"work"/"h5_mirror"
BASE_RUN="22dc038f17a2"
BASE_SAFE=REPORTS/("purchased-minute-native-h5-copy-20260924-"+BASE_RUN+".json")
BASE_DIR=MIRRORS/("minute_purchased_wave_"+BASE_RUN)
LIVE=MIRRORS/("minute_resumable_"+BASE_RUN)
SOURCE_SHA="a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01"
STATUS="private_resumable_native_minute_H5_parquet_purchased_wave_committed"
PERIODS=("1min","5min")
MARKETS=("sh","sz","bj")
H5_NAMES=tuple(m+"_"+p+".h5" for p in PERIODS for m in MARKETS)
RUNID_RE=re.compile(r"[0-9a-f]{12}\Z")
CODE_RE=re.compile(r"(SH|SZ|BJ)[0-9]{6}\Z")

def local(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

BASE=local("minute_resume_original_purchased_first_real_h5",
           "mirror-asof20261013-purchased-minute-parquet-into-copied-native-h5.py")
MERGE=BASE.MERGE

def sha(path):
    return MERGE.sha(Path(path))

def write_json_atomic(path,doc):
    path=Path(path)
    body=json.dumps(doc,ensure_ascii=False,sort_keys=True,
                    separators=(",",":"),allow_nan=False)+"\n"
    temp=path.with_name(path.name+".updating")
    if temp.exists() or temp.is_symlink():
        # A crashed rename may leave only this file, never trust it.
        temp.unlink()
    with temp.open("x",encoding="utf-8") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp,path)

def base_receipt():
    if (BASE_SAFE.is_symlink() or not BASE_SAFE.is_file()
            or BASE_SAFE.stat().st_size>200000
            or BASE_DIR.is_symlink() or not BASE_DIR.is_dir()):
        raise ValueError("Previously verified 2026-09-24 purchased+H5 native baseline absent")
    doc=json.loads(BASE_SAFE.read_bytes())
    maps=doc.get("new_native_h5_files_sha256")
    if (doc.get("status")!=
            "purchased_2026_september_bounded_native_1m5m_H5_copy_merged_verified"
            or doc.get("physical_dataset_sha256")!=SOURCE_SHA
            or doc.get("window")!=["2026-09-24","2026-09-24"]
            or doc.get("prior_four_day_native_mirror_reused_not_reconverted") is not True
            or doc.get("already_written_prior_four_day_native_rows_reused")!=
               {"1min":5358629,"5min":1068384}
            or doc.get("purchased_parquet_source_rows_written_as_native_h5")!=
               {"1min":1341888,"5min":267264}
            or doc.get("all_original_H5_files_copied_and_untouched") is not True
            or doc.get("native_minute_table_40byte_all_changed_stock_integer_readback_verified")
               is not True
            or doc.get("production_H5_activated") is not False
            or type(maps) is not dict or set(maps)!=set(H5_NAMES)):
        raise ValueError("Accepted complete native 1m5m baseline identity mismatch")
    for name,value in maps.items():
        f=BASE_DIR/name
        if (f.is_symlink() or not f.is_file()
                or type(value) is not str or re.fullmatch(r"[0-9a-f]{64}",value) is None
                or sha(f)!=value):
            raise ValueError("Immutable prior accepted real native minute H5 SHA drift")
    return maps,sha(BASE_SAFE)

def initialize_live(maps,baseline_safe_sha):
    """Copy immutable baseline only the FIRST time; never on later batches."""
    MIRRORS.mkdir(parents=True,exist_ok=True)
    if any(p.is_symlink() for p in (MODULE/"work",MIRRORS,LIVE)):
        raise ValueError("Private H5 workspace path is a link")
    initialized=LIVE/"initialized.json"
    if initialized.is_symlink():
        raise ValueError("Linked private native H5 state is not permitted")
    if initialized.exists():
        d=json.loads(initialized.read_bytes())
        if (d.get("source_baseline_safe_sha256")!=baseline_safe_sha
                or d.get("dataset_sha256")!=SOURCE_SHA
                or set(d.get("initial_native_h5_sha256",{}))!=set(H5_NAMES)):
            raise ValueError("Private ongoing H5 workspace base receipt drift")
        return d
    # If the first copy is interrupted, only repair files byte-identical to
    # the approved initial baseline; no already-started batch is overwritten.
    if (LIVE.exists() and
            (any((LIVE/"batches").glob("*")) if (LIVE/"batches").exists() else False)):
        raise ValueError("Incomplete workspace with batch data needs manual isolation")
    size=sum((BASE_DIR/n).stat().st_size for n in H5_NAMES)
    if shutil.disk_usage(MIRRORS).free<size*1.15+250000000:
        raise ValueError("Insufficient disk for ONE permanent six-file native H5 base copy")
    LIVE.mkdir(exist_ok=True)
    for name in H5_NAMES:
        dest=LIVE/name
        if dest.exists() and sha(dest)==maps[name]:
            continue
        if dest.is_symlink():
            raise ValueError("Unsafe linked destination while initializing private H5")
        print("ONE_TIME_COPY_ACCEPTED_NATIVE_H5_BASE="+name,flush=True)
        shutil.copyfile(BASE_DIR/name,dest)
        if sha(dest)!=maps[name]:
            raise ValueError("One-time copied H5 bytes differ from accepted base")
    d={
        "format":"resumable_private_native_minute_H5_initialized_v1",
        "source_baseline_safe_sha256":baseline_safe_sha,
        "dataset_sha256":SOURCE_SHA,
        "initial_native_h5_sha256":maps,
        "completed_windows":[],
        "latest_h5_files_sha256":maps,
        "original_market_H5_modified":False,
        "production_H5_activated":False,
    }
    (LIVE/"batches").mkdir(exist_ok=True)
    write_json_atomic(initialized,d)
    return d

def batch_dates(first,last):
    # Use already-addressable purchased 1m/5m Parquet back to 2011;
    # private 1990-2010 history is in H5 and never converted from paid
    # Parquet under an unproven historical mapping.
    start,end=date.fromisoformat(first),date.fromisoformat(last)
    if (start>end or start<date(2011,1,1)
            or end>date(2026,9,23) or (end-start).days>6):
        raise ValueError("Bound native 1m/5m purchase window to <=7 calendar days, 2011-01-01..2026-09-23")
    return start,end

def stage_receipt(root,start,end,payload):
    """Persist source keys before ANY private H5 change, resume them as-is."""
    p=LIVE/"batches"/("batch_"+start.isoformat()+"_"+end.isoformat())
    if p.is_symlink():
        raise ValueError("Unsafe private batch path")
    p.mkdir(exist_ok=True)
    db=p/"purchased_native_keys.sqlite3"
    ready=p/"ready.json"
    refs=BASE.purchased_refs(payload,root)
    if ready.is_file():
        receipt=json.loads(ready.read_bytes())
        if (receipt.get("start")!=start.isoformat()
                or receipt.get("end")!=end.isoformat()
                or receipt.get("dataset_sha256")!=SOURCE_SHA):
            raise ValueError("Existing native minute batch checkpoint mismatched request")
        store=sqlite3.connect(str(db))
        observed={x:int(y) for x,y in store.execute(
            "SELECT period,COUNT(*) FROM bars GROUP BY period")}
        if observed!=receipt["source_purchased_bar_counts"]:
            store.close()
            raise ValueError("Persistent purchased minute SQLite staged keys were altered")
        return store,receipt,p
    if db.exists():
        # Safe: no ready.json means not a single H5 transaction was started.
        db.unlink()
    store,scan=BASE.stage_sqlite(
        db,refs,root,start,end,max_source_rows=12000000)
    counts=scan["purchased_canonical_a_share_rows"]
    if any(counts.get(period,0)<1 for period in PERIODS):
        store.close()
        raise ValueError("Requested real minute Parquet day has no purchased rows")
    store.execute("CREATE TABLE stock_progress (period TEXT NOT NULL, "
                  "symbol TEXT NOT NULL, state TEXT NOT NULL, existed INTEGER NOT NULL,"
                  "target_sha TEXT, original_only INTEGER, replacements INTEGER,"
                  "PRIMARY KEY(period,symbol)) WITHOUT ROWID")
    store.commit()
    receipt={
        "start":start.isoformat(),"end":end.isoformat(),
        "dataset_sha256":SOURCE_SHA,
        "source_purchased_bar_counts":counts,
        "stage_provenance":scan,
    }
    write_json_atomic(ready,receipt)
    return store,receipt,p

def reset_pending(table,store,period,symbol,tables):
    """Restore original table from HDF5 undo node after interrupted swap."""
    node="/data/"+symbol
    backup="/data/__undo_"+symbol
    temporary="/data/__next_"+symbol
    exists=lambda key: bool(table.__contains__(key))
    progress=store.execute(
        "SELECT state,existed,target_sha FROM stock_progress "
        "WHERE period=? AND symbol=?",(period,symbol)).fetchone()
    if progress and progress[0]=="done":
        if not exists(node):
            raise ValueError("Committed private H5 stock table is missing")
        current=sha_array(table.get_node(node).read())
        if current!=progress[2]:
            raise ValueError("Committed private H5 stock integer bytes no longer match")
        if exists(backup):
            table.remove_node(backup)
        if exists(temporary):
            table.remove_node(temporary)
        return True
    if progress and progress[0]=="pending":
        if exists(backup):
            if exists(node):
                table.remove_node(node)
            table.rename_node(table.get_node(backup),symbol)
        elif not bool(progress[1]) and exists(node):
            table.remove_node(node)
        elif bool(progress[1]) and not exists(node):
            raise ValueError("Interrupted HDF5 stock swap lost its original backup")
        if exists(temporary):
            table.remove_node(temporary)
        table.flush()
        store.execute(
            "DELETE FROM stock_progress WHERE period=? AND symbol=?",
            (period,symbol))
        store.commit()
    elif exists(backup) or exists(temporary):
        raise ValueError("Unjournaled H5 scratch/undo stock node encountered")
    return False

def sha_array(array):
    return hashlib.sha256(array.tobytes()).hexdigest()

def commit_stock(db,store,period,symbol,purchased,tables,np,dtype):
    """One-stock H5 COW swap, progress journal supports recovery mid-rename."""
    if not CODE_RE.fullmatch(symbol):
        raise ValueError("Invalid purchased native H5 stock symbol")
    key="/data/"+symbol
    if reset_pending(db,store,period,symbol,tables):
        return False
    try:
        old=MERGE.convert_records(db.get_node(key).read(),dtype,np)
        existed=True
    except tables.NoSuchNodeError:
        old=np.empty(0,dtype=dtype)
        existed=False
    incoming=MERGE.convert_records(purchased,dtype,np)
    merged,proof=MERGE.merge_stock(old,incoming,np,dtype)
    expect=sha_array(merged)
    store.execute(
        "INSERT INTO stock_progress(period,symbol,state,existed,target_sha,"
        "original_only,replacements) VALUES(?,?,?,?,?,?,?)",
        (period,symbol,"pending",int(existed),expect,
         len(merged)-len(incoming),proof["original_post2010_replaced_by_purchased"]))
    store.commit()
    temp=db.create_table(
        "/data","__next_"+symbol,description=dtype,title=symbol,
        expectedrows=len(merged),
        filters=tables.Filters(complevel=5,complib="zlib",shuffle=True))
    for i in range(0,len(merged),16384):
        temp.append(merged[i:i+16384])
    temp.flush()
    if (int(temp.nrows)!=len(merged) or sha_array(temp.read())!=expect):
        raise ValueError("New stock native integer H5 scratch did not roundtrip")
    if existed:
        db.rename_node(db.get_node(key),"__undo_"+symbol)
    db.rename_node(temp,symbol)
    db.flush()
    if sha_array(db.get_node(key).read())!=expect:
        raise ValueError("Native H5 swap integer readback mismatch")
    store.execute(
        "UPDATE stock_progress SET state='done' WHERE period=? AND symbol=?",
        (period,symbol))
    store.commit()
    if existed:
        db.remove_node("/data/__undo_"+symbol)
    db.flush()
    return True

def process_stock_batch(store,period,market,file,*,days,dtype,np,tables):
    source=store.execute(
        "SELECT DISTINCT symbol FROM bars WHERE period=? AND symbol LIKE ? "
        "ORDER BY symbol",(period,market.upper()+"%"))
    counters=Counter()
    with tables.open_file(str(file),"a") as h5:
        if not hasattr(h5.root,"data"):
            raise ValueError("Private minute H5 /data table group missing")
        for (symbol,) in source:
            packed=[b for (b,) in store.execute(
                "SELECT record FROM bars WHERE period=? AND symbol=? "
                "ORDER BY stamp",(period,symbol))]
            # A 5-day purchased week is committed as one stock replacement,
            # avoiding repeated full-history table rewrites each day.
            # Allow only one trading-session maximum per calendar day.
            ceiling=days*(241 if period=="1min" else 48)
            if not packed or len(packed)>ceiling:
                raise ValueError("Unexpected stock/week minute Parquet bar count")
            arr=np.frombuffer(b"".join(packed),dtype=dtype).copy()
            changed=commit_stock(h5,store,period,symbol,arr,tables,np,dtype)
            counters["purchased_rows_checked"]+=len(arr)
            counters["stock_tables_checked"]+=1
            if changed:
                counters["stock_tables_updated"]+=1
            if counters["stock_tables_checked"]%500==0:
                print("NATIVE_H5_RESUME_STOCK_PROGRESS="+period+"/"+market+
                      " CHECKED="+str(counters["stock_tables_checked"]),
                      flush=True)
        h5.flush()
    print("DONE_RESUMABLE_H5_MARKET="+period+"/"+market+
          " STOCKS="+str(counters["stock_tables_checked"]),flush=True)
    return counters

def run(root,manifest,from_day,through_day,*,expected_sha=SOURCE_SHA):
    import numpy as np
    import tables
    start,end=batch_dates(from_day,through_day)
    if (REPORTS.is_symlink() or MIRRORS.is_symlink() or LIVE.is_symlink()):
        raise ValueError("Linked private output path refused")
    base_map,base_safe_sha=base_receipt()
    doc=initialize_live(base_map,base_safe_sha)
    window=[start.isoformat(),end.isoformat()]
    if window in doc["completed_windows"]:
        for filename,known in doc["latest_h5_files_sha256"].items():
            if sha(LIVE/filename)!=known:
                raise ValueError("Completed private minute H5 source changed")
        print("PASS_EXISTING_RESUMABLE_NATIVE_H5_MINUTE_WINDOW="+
              "-".join(window),flush=True)
        return
    for prior_start,prior_end in doc["completed_windows"]:
        if (start<=date.fromisoformat(prior_end)
                and end>=date.fromisoformat(prior_start)):
            raise ValueError("New purchased-minute batch overlaps already committed H5 days")
    finished=LIVE/"batches"/("batch_"+start.isoformat()+"_"+end.isoformat())/"done.json"
    if finished.exists():
        # A power cut between writing the immutable batch receipt and
        # replacing initialized.json is recoverable without rewriting H5.
        saved=json.loads(finished.read_bytes())
        if (saved.get("status")!=STATUS or saved.get("window")!=window
                or saved.get("dataset_sha256")!=SOURCE_SHA
                or set(saved.get("full_private_six_file_H5_sha256",{}))!=set(H5_NAMES)):
            raise ValueError("Interrupted completed minute H5 batch receipt invalid")
        for filename,known in saved["full_private_six_file_H5_sha256"].items():
            if sha(LIVE/filename)!=known:
                raise ValueError("Interrupted completed private H5 candidate bytes changed")
        doc["completed_windows"].append(window)
        doc["latest_h5_files_sha256"]=saved["full_private_six_file_H5_sha256"]
        write_json_atomic(LIVE/"initialized.json",doc)
        print("PASS_RECOVERED_COMPLETE_NATIVE_H5_MINUTE_BATCH="+
              "-".join(window),flush=True)
        return
    in_progress=[p for p in (LIVE/"batches").glob("batch_*")
                 if p.is_dir() and (p/"ready.json").is_file()
                 and (p/"done.json").is_file() is False]
    wanted="batch_"+start.isoformat()+"_"+end.isoformat()
    if any(p.name!=wanted for p in in_progress):
        raise ValueError("Another interrupted native H5 window must resume first")
    # Check unchanged H5 bytes between *successful* windows; an interrupted
    # requested batch must recover via its journal instead.
    if not in_progress:
        for filename,known in doc["latest_h5_files_sha256"].items():
            if sha(LIVE/filename)!=known:
                raise ValueError("Previously accepted private H5 bytes changed")
    source=BASE.src_input(root,manifest,expected_sha)
    store,stage,where=stage_receipt(root,start,end,source)
    dtype=MERGE.canonical_dtype(np)
    counts=Counter()
    completed=False
    try:
        for period in PERIODS:
            for market in MARKETS:
                counters=process_stock_batch(
                    store,period,market,LIVE/(market+"_"+period+".h5"),
                    days=(end-start).days+1,
                    dtype=dtype,np=np,tables=tables)
                counts[period]+=counters["purchased_rows_checked"]
        if any(counts[p]!=stage["source_purchased_bar_counts"].get(p,0)
               for p in PERIODS):
            raise ValueError("Resumable private native H5 minute bar row conservation failed")
        hashes={n:sha(LIVE/n) for n in H5_NAMES}
        receipt={
            "status":STATUS,"dataset_sha256":SOURCE_SHA,
            "window":window,
            "source_baseline_safe_sha256":base_safe_sha,
            "purchased_parquet_rows_processed_by_period":dict(counts),
            "committed_stock_tables":store.execute(
                "SELECT COUNT(*) FROM stock_progress WHERE state='done'").fetchone()[0],
            "full_private_six_file_H5_sha256":hashes,
            "all_stock_swaps_completed_and_journal_committed":True,
            "original_purchased_parquet_or_hikyuu_H5_modified":False,
            "original_markets_never_opened_in_write_mode":True,
            "numeric_unit_mapping_vendor_certified":False,
            "native_cpp_full_market_read_verified":False,
            "production_H5_activated":False,
            "complete_2011_2026_minute_history":False,
        }
        write_json_atomic(where/"done.json",receipt)
        doc["completed_windows"].append(window)
        doc["latest_h5_files_sha256"]=hashes
        write_json_atomic(LIVE/"initialized.json",doc)
        print("PASS_RESUMABLE_PURCHASED_PARQUET_TO_NATIVE_MINUTE_H5="+
              json.dumps({"window":window,"counts":dict(counts),
                          "updated_stock_tables":receipt["committed_stock_tables"],
                          "workspace":str(LIVE),"original_market_unchanged":True},
                         sort_keys=True),flush=True)
        completed=True
    finally:
        store.close()
    if completed:
        # Once the H5 six-file hashes, done.json, AND initialized.json are
        # durable, the staged purchased key database is not required for
        # replay or rollback. Avoid accumulating hundreds of gigabytes of
        # copied temporary key rows over 2011-2026.
        staged=where/"purchased_native_keys.sqlite3"
        if staged.is_symlink():
            raise ValueError("Unexpected symlink to committed staged market key store")
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            # Disk cleanup is nonessential after an accepted H5 commit.
            print("STAGED_KEY_DB_CLEANUP_SKIPPED="+window[0]+
                  ".."+window[1],flush=True)

@contextmanager
def exclusive_working_h5_lock():
    """OS-held single writer lock; released even after a killed process.

    Windows msvcrt range locks (and POSIX flock) avoid stale lockfiles and
    prevent two H5 writers corrupting the same continuous candidate.
    """
    MIRRORS.mkdir(parents=True,exist_ok=True)
    if LIVE.is_symlink():
        raise ValueError("Linked private H5 workspace refused")
    LIVE.mkdir(exist_ok=True)
    file=LIVE/"single_writer.lock"
    if file.is_symlink():
        raise ValueError("Linked H5 single-writer lock refused")
    with file.open("a+b") as fd:
        fd.seek(0,2)
        if fd.tell()==0:
            fd.write(b"0")
            fd.flush()
        fd.seek(0)
        try:
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(fd.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(fd.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another minute H5 copy writer already active") from exc
        try:
            yield
        finally:
            if os.name=="nt":
                msvcrt.locking(fd.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(fd.fileno(),fcntl.LOCK_UN)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--from-day",required=True)
    p.add_argument("--through-day",required=True)
    p.add_argument("--write-resumable-private-h5",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        with exclusive_working_h5_lock():
            run(a.root,a.manifest,a.from_day,a.through_day)
    except (ValueError,OSError,TypeError,KeyError,sqlite3.Error,RuntimeError) as exc:
        last=traceback.extract_tb(exc.__traceback__)[-1]
        p.error("Resumable native minute H5 source/staged/batch REFUSED ["+
                type(exc).__name__+"/"+last.name+":"+str(last.lineno)+
                "]; original market files remain unchanged")

if __name__=="__main__":
    main()
