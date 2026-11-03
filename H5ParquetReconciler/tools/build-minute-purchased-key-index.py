#!/usr/bin/env python3
"""Bounded, reusable, purchased-Parquet minute *key* index (no OHLCVA copies).

Scans selected 1min/5min purchased Parquet date range ONCE and materializes
only per-(period, stockday, symbol) 1440-minute membership bits in a private
SQLite file. 180 bytes/stockday, not millions of per-bar SQLite rows.

This is an unactivated analysis index. The fast source signature consists of
path/size/mtime_ns/inode and is NOT a content-SHA authenticity certification.
The index is rejected when this metadata changes; original sources stay read-only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import date,datetime,timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
STORE=MODULE/"work"/"unified_parquet"/"minute_key_index"
BYTES_PER_DAY=180
MAX_DAYS=31
RUN_RE=re.compile(r"[0-9a-f]{12}\Z")


def load(tag,filename):
    spec=importlib.util.spec_from_file_location(tag,HERE/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


N=load("minute_key_index_existing_gap_preview",
       "run-minute-h5-gap-only-overlay.py")
ST=N.ST


def day_epoch_ms(day):
    return int(datetime(day.year,day.month,day.day,
                        tzinfo=ST.CORE.UTC8).timestamp()*1000)


def make_days(first,last):
    a=date.fromisoformat(first) if isinstance(first,str) else first
    b=date.fromisoformat(last) if isinstance(last,str) else last
    if (not isinstance(a,date) or not isinstance(b,date)
            or a>b or (b-a).days+1>MAX_DAYS or a.year!=b.year
            or a<date(2025,1,1) or b>date(2026,10,13)):
        raise ValueError("Index window must be 1..31 days in one source year")
    return [a+timedelta(days=x) for x in range((b-a).days+1)]


def purchased_masks(root,period,days,*,max_date_rows=50000000):
    """Read selected Parquet ts/symbol columns once; return packed key masks.

    File rowgroups may span many days; filter Arrow before Python iteration.
    Duplicated purchased A-share minute keys FAIL CLOSED. Timestamp must
    be integer UTC-ms aligned to one minute. Retain all minute-of-day slots,
    including vendor-only 09:30, without inferring session correctness.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    start=day_epoch_ms(days[0])
    stop=day_epoch_ms(days[-1]+timedelta(days=1))
    files=ST.CORE.year_files(root,period,days[0].year)
    if not files:
        raise ValueError("Purchased year-period parquet sources absent")
    masks={}
    selected=0
    a_share=0
    scanned=0
    groups=0
    duplicates=0
    for p in files:
        if p.is_symlink() or not p.is_file():
            raise ValueError("Unsafe purchased Parquet file")
        with pq.ParquetFile(p,memory_map=False,pre_buffer=False) as pf:
            if not {"ts","symbol"}.issubset(pf.schema_arrow.names):
                raise ValueError("Purchased Parquet missing ts/symbol")
            if not pa.types.is_integer(pf.schema_arrow.field("ts").type):
                raise ValueError("Purchased timestamp must be integer epoch-ms")
            symbol_type=pf.schema_arrow.field("symbol").type
            if pa.types.is_dictionary(symbol_type):
                symbol_type=symbol_type.value_type
            if not (pa.types.is_string(symbol_type) or
                    pa.types.is_large_string(symbol_type)):
                raise ValueError("Purchased symbol must be string")
            for rg in range(pf.metadata.num_row_groups):
                if not ST.CORE.row_group_overlaps_timestamp(
                        pf.metadata.row_group(rg),start,stop):
                    continue
                groups+=1
                for batch in pf.iter_batches(
                        row_groups=[rg],batch_size=65536,
                        columns=["ts","symbol"],use_threads=False):
                    scanned+=batch.num_rows
                    stamps=batch.column(0)
                    match=pc.and_(pc.greater_equal(stamps,start),
                                  pc.less(stamps,stop))
                    selected_stamps=pc.filter(stamps,match).to_pylist()
                    selected_symbols=pc.filter(
                        batch.column(1),match).to_pylist()
                    selected+=len(selected_stamps)
                    if selected>max_date_rows:
                        raise ValueError("Selected window Parquet row budget exceeded")
                    for stamp,src_symbol in zip(selected_stamps,selected_symbols):
                        sym=ST.CORE.symbol_id(src_symbol)
                        if not sym or not ST.CORE.is_a_share_candidate(
                                sym,days[0].year):
                            continue
                        delta=stamp-start
                        if delta%60000:
                            raise ValueError("Non minute-aligned purchased timestamp")
                        day_idx=delta//86400000
                        if not 0<=day_idx<len(days):
                            raise ValueError("Arrow date filter violated day range")
                        minute=(delta%86400000)//60000
                        key=(day_idx,sym)
                        mask=masks.get(key)
                        if mask is None:
                            mask=bytearray(BYTES_PER_DAY)
                            masks[key]=mask
                        byte,bit=divmod(minute,8)
                        if mask[byte]&(1<<bit):
                            duplicates+=1
                            raise ValueError("Duplicate purchased minute key in index window")
                        mask[byte]|=1<<bit
                        a_share+=1
    return masks,{
        "purchased_source_files":len(files),
        "rowgroups_read":groups,
        "candidate_rows_scanned":scanned,
        "target_window_timestamp_rows":selected,
        "a_share_unique_keys":a_share,
        "stockday_entries":len(masks),
        "duplicated_key_rows":duplicates,
        "period":period,
    }


def build(root,first,last,run_id,*,max_date_rows=50000000):
    root=Path(root)
    days=make_days(first,last)
    N.validate(root,days[0],"000000000000")
    if not isinstance(run_id,str) or RUN_RE.fullmatch(run_id) is None:
        raise ValueError("Require 12-char hex run ID")
    if STORE.is_symlink():
        raise ValueError("Unsafe private index store")
    target=STORE/f"purchased-minute-keys-{days[0]}-{days[-1]}-{run_id}.sqlite"
    if target.exists() or target.is_symlink():
        raise ValueError("Index output exists: choose a new isolated run ID")
    start_snapshot=N.source_snapshot(root,days[0].year)
    masks={}
    summaries={}
    for period in N.PERIODS:
        masks[period],summaries[period]=purchased_masks(
            root,period,days,max_date_rows=max_date_rows)
    if N.source_snapshot(root,days[0].year)!=start_snapshot:
        raise RuntimeError("Source metadata changed while building index")
    STORE.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix(".sqlite.partial")
    if temp.exists() or temp.is_symlink():
        raise ValueError("Index partial output already exists")
    info={
        "status":"private_purchased_source_minute_keys_only_not_market_data",
        "schema_version":1,
        "source_root":str(root.resolve()),
        "from_day":days[0].isoformat(),
        "through_day":days[-1].isoformat(),
        "days_in_window":len(days),
        "periods":summaries,
        "source_metadata_fingerprint":start_snapshot,
        "source_content_sha_certified":False,
        "purchased_ohlcva_rows_copied":0,
        "new_market_parquet_or_h5_files_written":False,
        "ready_for_production_query":False,
    }
    try:
        with sqlite3.connect(temp) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE stockday (period TEXT NOT NULL, day TEXT NOT NULL, "
                       "symbol TEXT NOT NULL, mask BLOB NOT NULL, "
                       "PRIMARY KEY(period,day,symbol)) WITHOUT ROWID")
            for period in N.PERIODS:
                for (i,sym),mask in masks[period].items():
                    db.execute("INSERT INTO stockday VALUES(?,?,?,?)",
                               (period,days[i].isoformat(),sym,bytes(mask)))
                db.execute("INSERT INTO meta VALUES(?,?)",
                           ("period_"+period,json.dumps(summaries[period],
                                                      sort_keys=True)))
            db.execute("INSERT INTO meta VALUES(?,?)",
                       ("manifest",json.dumps(info,sort_keys=True)))
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise ValueError("SQLite integrity validation failed")
        if N.source_snapshot(root,days[0].year)!=start_snapshot:
            raise RuntimeError("Source metadata changed after index construction")
        os.replace(temp,target)
    except Exception:
        # On failure keep partial private file for inspection, never publish
        # as completed. Original licensed sources are untouched.
        raise
    return dict(info,index_path=str(target))


def query_index(path,root,period,day):
    """Revalidate source signature and return exact timestamp sets for one day."""
    path=Path(path)
    root=Path(root)
    if path.is_symlink() or not path.is_file() or path.suffix!=".sqlite":
        raise ValueError("Index must be a real private SQLite file")
    if (not path.resolve().is_relative_to(STORE.resolve())
            or period not in N.PERIODS):
        raise ValueError("Index is outside private store or period invalid")
    d=date.fromisoformat(day) if isinstance(day,str) else day
    if not isinstance(d,date):
        raise ValueError("Invalid requested index day")
    with sqlite3.connect("file:"+path.resolve().as_posix()+"?mode=ro",uri=True) as db:
        found=db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()
        if not found:
            raise ValueError("Missing purchased index manifest")
        info=json.loads(found[0])
        if (info.get("schema_version")!=1
                or info.get("source_root")!=str(root.resolve())
                or not info.get("from_day")<=d.isoformat()<=info.get("through_day")
                or period not in info.get("periods",{})):
            raise ValueError("Index metadata/date/period/root mismatch")
        if N.source_snapshot(root,d.year)!=info["source_metadata_fingerprint"]:
            raise ValueError("Purchased/H5 source metadata changed; rebuild index")
        start=day_epoch_ms(d)
        keys={}
        for sym,raw in db.execute(
                "SELECT symbol,mask FROM stockday WHERE period=? AND day=?",
                (period,d.isoformat())):
            if len(raw)!=BYTES_PER_DAY:
                raise ValueError("Malformed purchased minute membership mask")
            stamps={start+(byte*8+bit)*60000
                    for byte,value in enumerate(raw)
                    for bit in range(8) if value&(1<<bit)}
            keys[sym]=stamps
    return keys,{
        "index_used":True,"index_path":str(path),
        "period":period,"day":d.isoformat(),
        "purchased_stockdays_present":len(keys),
        "purchased_a_share_date_key_count":sum(len(x) for x in keys.values()),
        "source_metadata_rechecked":True,
        "source_content_sha_certified":False,
        "no_purchased_parquet_scanned_during_lookup":True,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--from-day",required=True)
    p.add_argument("--through-day",required=True)
    p.add_argument("--run-id",required=True)
    args=p.parse_args(argv)
    result=build(args.root,args.from_day,args.through_day,args.run_id)
    # Aggregate only; never print individual market symbols, keys, OHLCVA.
    print(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False))


if __name__=="__main__":
    main()
