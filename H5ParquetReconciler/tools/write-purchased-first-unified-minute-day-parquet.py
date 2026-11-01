#!/usr/bin/env python3
"""Create REAL per-day unified 1min and 5min private physical Parquet.

Retain purchased Parquet precedence/extra vendor columns. Add only already
staged, SHA-verified H5-only full stockdays. Never overwrite original vendor
Parquet, original Hikyuu H5, or previously generated 16-year DAY mirror.

This is a real merged Parquet output, not another index or pointer. H5 minute
timestamp alignment remains explicitly CANDIDATE, not vendor-certified.
Historical minute coverage is incomplete until this is run across all dates
with purchased and H5 sources. Original H5 integers are retained as nullable
extra fields for a later real combined native Hikyuu H5 rebuild.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import traceback
from collections import Counter
from datetime import datetime,timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
OUT=MODULE/"work"/"unified_parquet"/"minute_complete_day"
FMT="AStockDataTools purchased-first H5-gap physical unified minute Parquet v1"
RUN=re.compile(r"[0-9a-f]{12}\Z")
BASE=("ts","symbol","open","high","low","close","volume","amount")
META=("period","value_source","source_symbol","source_ts")
H5_NATIVE=("h5_native_datetime","h5_native_openPrice",
           "h5_native_highPrice","h5_native_lowPrice",
           "h5_native_closePrice","h5_native_transCount",
           "h5_native_transAmount")


def load(tag,name):
    spec=importlib.util.spec_from_file_location(tag,HERE/name)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


G=load("unified_day_minute_staged_gap","mirror-h5-origin-private-minute-parquet-to-native-h5.py")
ST=G.STAGE


def hash_file(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as fp:
        for buf in iter(lambda:fp.read(1<<20),b""):
            digest.update(buf)
    return digest.hexdigest()


def as_utc8_day_bound(day):
    lower=int(datetime(day.year,day.month,day.day,
                       tzinfo=ST.CORE.UTC8).timestamp()*1000)
    after=day+timedelta(days=1)
    upper=int(datetime(after.year,after.month,after.day,
                       tzinfo=ST.CORE.UTC8).timestamp()*1000)
    return lower,upper


def merged_schema(purchased_files,period):
    import pyarrow as pa
    extra={}
    purchased_count=0
    for source in purchased_files:
        import pyarrow.parquet as pq
        with pq.ParquetFile(source,memory_map=False,pre_buffer=False) as f:
            fields=f.schema_arrow
        missing=set(BASE)-set(fields.names)
        if missing:
            raise ValueError("Original purchased minute file has missing OHLCVA columns")
        purchased_count+=1
        for field in fields:
            if field.name in BASE:
                continue
            if field.name in extra and extra[field.name]!=field.type:
                raise ValueError("Inconsistent purchased vendor extra column types")
            extra[field.name]=field.type
    normalized=[
        pa.field("ts",pa.int64(),False),
        pa.field("symbol",pa.string(),False),
        *[pa.field(name,pa.float64(),False) for name in BASE[2:]],
        pa.field("period",pa.string(),False),
        pa.field("value_source",pa.string(),False),
        pa.field("source_symbol",pa.string(),False),
        pa.field("source_ts",pa.int64()),
        pa.field("h5_native_datetime",pa.int64()),
        *[pa.field(k,pa.uint64()) for k in H5_NATIVE[1:]],
        *[pa.field("purchased__"+name,kind) for name,kind in sorted(extra.items())],
    ]
    if len({f.name for f in normalized})!=len(normalized):
        raise ValueError("Purchased vendor fields collide with physical target schema")
    return pa.schema(normalized),tuple(sorted(extra))


def canonical_purchased(row,period,low,high,year,extras):
    source_ts=row["ts"]
    source_symbol=row["symbol"]
    if type(source_ts) is not int or not low<=source_ts<high:
        return None
    symbol=ST.CORE.symbol_id(source_symbol)
    if symbol is None or not ST.CORE.is_a_share_candidate(symbol,year):
        return None
    converted={}
    for field in BASE[2:]:
        value=row[field]
        if type(value) not in (int,float) or not math.isfinite(float(value)):
            raise ValueError("Purchased minute OHLCVA non-finite")
        converted[field]=float(value)
    return {
        "ts":source_ts,"symbol":symbol,**converted,
        "period":period,
        "value_source":"purchased_parquet",
        "source_symbol":str(source_symbol),"source_ts":source_ts,
        **{"purchased__"+k:row.get(k) for k in extras},
    }


def canonical_h5(row,period,day):
    if (row.get("period")!=period
            or row.get("value_source")!="h5_only_complete_stockday"
            or not re.fullmatch(r"(SH|SZ|BJ)\d{6}",row["symbol"])
            or row["h5_native_datetime"] not in ST.session_stamps(day,period)):
        raise ValueError("H5 staged row metadata invalid")
    original_dt=datetime.strptime(
        str(row["h5_native_datetime"]),"%Y%m%d%H%M"
    ).replace(tzinfo=ST.CORE.UTC8)
    expected=original_dt-timedelta(minutes=1 if period=="1min" else 5)
    if row["ts"]!=int(expected.timestamp()*1000):
        raise ValueError("H5 candidate minute timestamp differs from original")
    original={k:row[k] for k in ST.schema(__import__("pyarrow")).names}
    del original["value_source"]
    del original["period"]
    return {
        **{k:original[k] for k in BASE},
        "period":period,
        "value_source":"h5_only_complete_stockday",
        "source_symbol":row["symbol"],
        "source_ts":None,
        **{k:row[k] for k in H5_NATIVE},
    }


def stage_unified(root,stage_report,run_id,out,*,max_rows=4500000):
    import pyarrow as pa
    import pyarrow.parquet as pq
    if (type(run_id) is not str or RUN.fullmatch(run_id) is None
            or type(max_rows) is not int or not 1000<=max_rows<=6000000):
        raise ValueError("Invalid bounded private physical minute merge")
    if not root.is_dir():
        raise ValueError("Purchased Parquet root unavailable")
    dest=OUT/f"minute_{run_id}"
    safe=Path(out)
    if (any(p.is_symlink() for p in (
            MODULE/"work",OUT,REPORTS,dest,safe))
            or dest.exists() or safe.exists()
            or safe.suffix!=".json"
            or safe.resolve().parent!=REPORTS.resolve()
            or dest.resolve().parent!=OUT.resolve()):
        raise ValueError("Only NEW private physical minute Parquet files")
    doc,day,sources=G.selected_source(stage_report)
    sha_before=hash_file(stage_report)
    low,high=as_utc8_day_bound(day)
    # Check all source paths and metadata before creating any output files.
    setups={}
    for period in ST.PERIODS:
        files=ST.CORE.year_files(root,period,day.year)
        if not files:
            raise ValueError("Purchased minute year absent; cannot claim purchased precedence")
        if any(not x.is_file() or x.is_symlink() for x in files):
            raise ValueError("Purchased source file unsafe")
        target_schema,extras=merged_schema(files,period)
        setups[period]=(files,target_schema,extras)
    OUT.mkdir(parents=True,exist_ok=True)
    dest.mkdir(exist_ok=False)
    period_summary={}
    for period in ST.PERIODS:
        files,target_schema,extras=setups[period]
        staged_file,entry=sources[period]
        target=dest/f"{period}-{day.isoformat()}.parquet"
        purchased_keys=set()
        purchased_stockdays=set()
        counts=Counter()
        fingerprint=hashlib.sha256()
        seen_h5=set()
        buffer=[]
        def digest_row(record):
            return json.dumps(record,sort_keys=True,default=str,
                              allow_nan=False,separators=(",",":")).encode("utf-8")
        def prepared(row):
            # Include ALL purchased vendor extra cols, nullable raw H5
            # values and provenance for both source classes.
            return {f.name:row.get(f.name) for f in target_schema}
        def add_record(writer,row):
            canonical=prepared(row)
            fingerprint.update(digest_row(canonical))
            buffer.append(canonical)
            if len(buffer)>=32768:
                writer.write_table(pa.Table.from_pylist(
                    buffer,schema=target_schema),row_group_size=32768)
                buffer.clear()
        with pq.ParquetWriter(target,target_schema,compression="zstd") as writer:
            for src in files:
                with pq.ParquetFile(src,memory_map=False,pre_buffer=False) as pf:
                    for rg in range(pf.metadata.num_row_groups):
                        if not ST.CORE.row_group_overlaps_timestamp(
                                pf.metadata.row_group(rg),low,high):
                            continue
                        for batch in pf.iter_batches(
                                row_groups=[rg],batch_size=32768,use_threads=False):
                            for source in batch.to_pylist():
                                row=canonical_purchased(source,period,low,high,
                                                        day.year,extras)
                                if row is None:
                                    continue
                                key=(row["symbol"],row["ts"])
                                if key in purchased_keys:
                                    raise ValueError("Original purchased minute key duplicated")
                                purchased_keys.add(key)
                                purchased_stockdays.add(row["symbol"])
                                add_record(writer,row)
                                counts["purchased_parquet"]+=1
                                if sum(counts.values())>max_rows:
                                    raise ValueError("Purchased minute stockday merge budget exceeded")
            with pq.ParquetFile(staged_file,memory_map=False,pre_buffer=False) as pf:
                if (pf.schema_arrow!=ST.schema(pa)
                        or pf.metadata.num_rows!=entry["private_parquet_rows"]):
                    raise ValueError("H5 minute gap source Parquet schema/count changed")
                for batch in pf.iter_batches(batch_size=32768,use_threads=False):
                    for original in batch.to_pylist():
                        row=canonical_h5(original,period,day)
                        key=(row["symbol"],row["ts"])
                        if row["symbol"] in purchased_stockdays:
                            raise ValueError("H5 stage overlaps purchased stockday")
                        if key in purchased_keys or key in seen_h5:
                            raise ValueError("Duplicate purchased/H5 minute key")
                        seen_h5.add(key)
                        add_record(writer,row)
                        counts["h5_only_complete_stockday"]+=1
                        if sum(counts.values())>max_rows:
                            raise ValueError("H5 minute merge budget exceeded")
            if buffer:
                writer.write_table(pa.Table.from_pylist(
                    buffer,schema=target_schema),row_group_size=32768)
                buffer.clear()
        if (counts["h5_only_complete_stockday"]!=entry["private_parquet_rows"]
                or hash_file(staged_file)!=entry["private_parquet_sha256"]):
            raise ValueError("H5 minute stage source changed during physical merge")
        # Full readback of the physically merged Parquet including vendor
        # extra columns, source provenance, SHA-pinned H5 native integer cols.
        observed=hashlib.sha256()
        verified=Counter()
        with pq.ParquetFile(target,memory_map=False,pre_buffer=False) as pf:
            if (pf.schema_arrow!=target_schema
                    or pf.metadata.num_rows!=sum(counts.values())):
                raise ValueError("Physical unified Parquet schema/rowcount differs")
            for batch in pf.iter_batches(batch_size=32768,use_threads=False):
                for row in batch.to_pylist():
                    observed.update(digest_row(row))
                    verified[row["value_source"]]+=1
        if (observed.digest()!=fingerprint.digest() or verified!=counts):
            raise ValueError("Physical unified minute full-row readback mismatch")
        period_summary[period]={
            "format":FMT,
            "period":period,
            "source_day":day.isoformat(),
            "unified_rows":int(sum(counts.values())),
            "source_rows":{k:int(v) for k,v in counts.items()},
            "purchased_vendor_extra_columns_retained":len(extras),
            "purchased_stockdays":len(purchased_stockdays),
            "h5_gap_stockdays":entry["private_parquet_stockdays"],
            "source_h5_gap_parquet_sha256":entry["private_parquet_sha256"],
            "unified_parquet_relative_file":target.relative_to(MODULE).as_posix(),
            "unified_parquet_sha256":hash_file(target),
            "full_merged_source_rows_and_vendor_extra_columns_readback_verified":True,
            "minute_time_alignment_vendor_certified":False,
            "ready_for_production_query":False,
        }
        print("Wrote purchased-first unified private minute Parquet:",period,
              "rows:",sum(counts.values()),"purchased:",counts["purchased_parquet"],
              "H5-only:",counts["h5_only_complete_stockday"],flush=True)
    if sha_before!=hash_file(stage_report):
        raise ValueError("Staged minute SAFE changed during physical merge")
    safe_doc={
        "format":FMT,
        "status":"purchased_first_1min_5min_physical_parquet_unified_readback_only",
        "source_day":day.isoformat(),
        "source_minute_gap_safe_sha256":sha_before,
        "periods":period_summary,
        "purchased_vendor_extra_fields_not_discarded":True,
        "original_purchased_parquet_or_hikyuu_h5_modified":False,
        "full_minute_history_unified":False,
        "minute_time_alignment_vendor_certified":False,
        "production_or_private_active_pointer_modified":False,
    }
    payload=json.dumps(safe_doc,sort_keys=True,indent=2)+"\n"
    with safe.open("x",encoding="utf-8",newline="\n") as fp:
        fp.write(payload)
    return safe_doc


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--stage-safe",type=Path,required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--max-rows",type=int,default=4500000)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--write-purchased-first-private-minute-parquet",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        doc=stage_unified(
            a.root,a.stage_safe,a.run_id,a.out,max_rows=a.max_rows)
        print("PASS: purchased Parquet + H5-only gaps physically unified in 1min/5min")
        print("Original purchased Parquet and original Hikyuu H5 unchanged")
        print("SAFE:",a.out)
    except Exception as e:
        last=traceback.extract_tb(e.__traceback__)[-1]
        p.error("Purchased/H5 minute physical merge failed ["+
                type(e).__name__+"/"+last.name+":"+str(last.lineno)+
                "]; original market sources unchanged; incomplete private files retained")


if __name__=="__main__":
    main()
