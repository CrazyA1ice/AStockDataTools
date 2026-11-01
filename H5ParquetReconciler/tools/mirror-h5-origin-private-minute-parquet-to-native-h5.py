#!/usr/bin/env python3
"""Actually mirror previously staged 1min/5min H5-only private Parquet rows
into six NEW PyTables Hikyuu-layout TABLE H5 files; compare ALL raw integers.

Do not modify vendor Parquet, original Hikyuu H5, existing day mirror, or
production pointers. Missing 13 irregular stock-days remain quarantined.
For staged H5-origin rows this is EXACT native integer round-trip, not a
claim that the unverified minute timestamp mapping or purchased vendor
OHLCVA units are certified. Original purchased Parquet stock-days are NOT
included in this bounded missing-stock-day mirror.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import re
import traceback
from collections import Counter
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
MIRRORS=MODULE/"work"/"h5_mirror"
FORMAT="AStockDataTools H5-origin minute Parquet to native PyTables H5 exact integer mirror v1"
H5_NAMES=("closePrice","datetime","highPrice","lowPrice",
          "openPrice","transAmount","transCount")
RAW_NAMES=("openPrice","highPrice","lowPrice","closePrice","transCount","transAmount")
RUN=re.compile(r"[0-9a-f]{12}\Z")
REL=re.compile(
    r"work/unified_parquet/minute_gap_staging/([0-9a-f]{12})/"
    r"(1min|5min)/(\d{4}-\d{2}-\d{2})\.parquet\Z")


def local(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


STAGE=local("minute_native_mirror_staging","write-h5-only-complete-minute-stockdays-to-private-parquet.py")


def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def dtype_for_hikyuu(np):
    dt=np.dtype([
        ("closePrice","<u4"),("datetime","<u8"),
        ("highPrice","<u4"),("lowPrice","<u4"),
        ("openPrice","<u4"),("transAmount","<u8"),
        ("transCount","<u8"),
    ])
    if dt.itemsize!=40 or dt.names!=H5_NAMES or (
            tuple(dt.fields[k][1] for k in H5_NAMES)!=(0,4,12,16,20,24,32)):
        raise ValueError("Expected Hikyuu native 40byte TABLE record layout")
    return dt


def selected_source(report):
    import pyarrow as pa
    safe=Path(report)
    if (safe.is_symlink() or safe.suffix!=".json" or not safe.is_file()
            or safe.resolve().parent!=REPORTS.resolve()
            or safe.stat().st_size>100000):
        raise ValueError("Require existing module-only minute stage SAFE")
    doc=json.loads(safe.read_bytes())
    if (doc.get("format")!=STAGE.FORMAT
            or doc.get("all_private_outputs_written_not_merged") is not True
            or doc.get("original_market_files_modified") is not False
            or doc.get("production_or_private_pointer_modified") is not False
            or set(doc.get("period_results",{}))!=set(STAGE.PERIODS)):
        raise ValueError("Incomplete or untrusted staged minute source SAFE")
    day=date.fromisoformat(doc["source_day"])
    sources={}
    stage_id=None
    for period in STAGE.PERIODS:
        record=doc["period_results"][period]
        rel=record.get("private_parquet_relative_file")
        match=REL.fullmatch(rel) if isinstance(rel,str) else None
        if (match is None or match.group(2)!=period or
                match.group(3)!=day.isoformat()
                or record.get("status")!=
                    "h5_complete_stockday_minute_gap_private_parquet_written_readback_not_merged"
                or record.get("day")!=day.isoformat()
                or record.get("period")!=period
                or record.get("h5_raw_integer_fields_preserved") is not True
                or record.get("source_purchased_parquet_stockdays_priority_preserved") is not True
                or record.get("minute_time_alignment_vendor_certified") is not False
                or record.get("original_purchased_parquet_or_h5_modified") is not False
                or any(record.get(k) is not False for k in (
                    "ready_for_production_query","ready_for_h5_mirror",
                    "ready_for_automatic_market_merge"))
                or type(record.get("private_parquet_rows")) is not int
                or not 0<=record["private_parquet_rows"]<=2500000
                or type(record.get("private_parquet_stockdays")) is not int):
            raise ValueError("Untrusted private minute Parquet provenance")
        if stage_id is None:
            stage_id=match.group(1)
        elif match.group(1)!=stage_id:
            raise ValueError("Mixed minute stage versions refused")
        path=MODULE/rel
        expected=path.parent.parent.parent.parent.parent.parent
        if (path.is_symlink() or path.parent.is_symlink()
                or expected.resolve()!=MODULE.resolve()
                or not path.is_file() or sha(path)!=record.get("private_parquet_sha256")):
            raise ValueError("Staged minute Parquet source SHA changed")
        sources[period]=(path,record)
    return doc,day,sources


def native_rows(rows,period,day,dt,np):
    if not rows:
        raise ValueError("Empty minute native table batch")
    out=np.empty(len(rows),dtype=dt)
    allowed=STAGE.session_stamps(day,period)
    shift=1 if period=="1min" else 5
    previous=0
    for i,r in enumerate(rows):
        stamp=r["h5_native_datetime"]
        if (type(stamp) is not int or stamp not in allowed or stamp<=previous
                or r["period"]!=period
                or r["value_source"]!="h5_only_complete_stockday"):
            raise ValueError("Unsorted or off-grid staged minute record")
        previous=stamp
        parsed=datetime.strptime(str(stamp),"%Y%m%d%H%M").replace(
            tzinfo=STAGE.CORE.UTC8)
        if int((parsed-timedelta(minutes=shift)).timestamp()*1000)!=r["ts"]:
            raise ValueError("H5 minute endpoint and Parquet start key disagree")
        vals={}
        for f in RAW_NAMES:
            n=r["h5_native_"+f]
            maximum=(2**64-1 if f in ("transAmount","transCount")
                     else 2**32-1)
            if type(n) is not int or not 0<=n<=maximum:
                raise ValueError("Original native minute integer out of bounds")
            vals[f]=n
        for key,native in (
            ("open","openPrice"),("high","highPrice"),
            ("low","lowPrice"),("close","closePrice")):
            if type(r[key]) is not float or r[key]!=vals[native]/1000:
                raise ValueError("Staged minute Float64 price differs from H5 integer")
        if (type(r["volume"]) is not float
                or r["volume"]!=float(vals["transCount"])
                or type(r["amount"]) is not float
                or r["amount"]!=float(vals["transAmount"])*1000):
            raise ValueError("Staged minute amount/volume differs from H5 source integer")
        out[i]["datetime"]=stamp
        for f in RAW_NAMES:
            out[i][f]=vals[f]
    return out


def write_mirror(stage_safe,run_id,out,max_rows=3500000):
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    import tables
    if (type(run_id) is not str or RUN.fullmatch(run_id) is None
            or type(max_rows) is not int or not 1000<=max_rows<=5000000):
        raise ValueError("Invalid bounded native minute output")
    safe=Path(out)
    dest=MIRRORS/f"minute_gap_{run_id}"
    if (any(p.is_symlink() for p in (
            MODULE/"work",MIRRORS,REPORTS,safe,dest))
            or safe.exists() or dest.exists()
            or safe.suffix!=".json"
            or safe.resolve().parent!=REPORTS.resolve()
            or dest.resolve().parent!=MIRRORS.resolve()):
        raise ValueError("Must create NEW isolated native minute H5 files")
    stage,day,sources=selected_source(stage_safe)
    if sum(entry["private_parquet_rows"] for _,entry in sources.values())>max_rows:
        raise ValueError("Minute mirror row budget exceeded")
    dt=dtype_for_hikyuu(np)
    MIRRORS.mkdir(parents=True,exist_ok=True)
    dest.mkdir(exist_ok=False)
    written=Counter()
    expected_hash={}
    expected_count=Counter()
    symbols_per_period=Counter()
    sources_sha={}
    completed=False
    try:
        with ExitStack() as stack:
            handles={}
            groups={}
            for period in STAGE.PERIODS:
                for market in ("sh","sz","bj"):
                    p=dest/f"{market}_{period}.h5"
                    h=stack.enter_context(tables.open_file(str(p),"w"))
                    handles[period,market.upper()]=h
                    groups[period,market.upper()]=h.create_group("/","data")
            for period in STAGE.PERIODS:
                path,entry=sources[period]
                sources_sha[period]=entry["private_parquet_sha256"]
                last_sym=None
                last_stamp=None
                seen=set()
                with pq.ParquetFile(path,memory_map=False,pre_buffer=False) as parquet:
                    if (parquet.schema_arrow!=STAGE.schema(pa)
                            or parquet.metadata.num_rows!=entry["private_parquet_rows"]):
                        raise ValueError("Minute private Parquet schema/rows changed")
                    for batch in parquet.iter_batches(batch_size=16384,use_threads=False):
                        # A stock can cross batch boundaries. Each mini-group
                        # is monotonically increasing, never duplicate.
                        for symbol,group in itertools.groupby(
                                batch.to_pylist(),lambda r:r["symbol"]):
                            rank={"SH":0,"SZ":1,"BJ":2}
                            if (not re.fullmatch(r"(SH|SZ|BJ)\d{6}",symbol)
                                    or (last_sym is not None and
                                        (rank[symbol[:2]],symbol)<
                                        (rank[last_sym[:2]],last_sym))
                                    or (symbol!=last_sym and symbol in seen)):
                                raise ValueError("Minute Parquet symbols not grouped/sorted")
                            if symbol!=last_sym:
                                seen.add(symbol)
                                last_stamp=None
                                symbols_per_period[period]+=1
                            rows=list(group)
                            arr=native_rows(rows,period,day,dt,np)
                            if last_stamp is not None and int(arr[0]["datetime"])<=last_stamp:
                                raise ValueError("Minute native timestamps duplicate across batches")
                            last_stamp=int(arr[-1]["datetime"])
                            last_sym=symbol
                            handle=handles[period,symbol[:2]]
                            try:
                                table=handle.get_node("/data/"+symbol)
                            except tables.NoSuchNodeError:
                                table=handle.create_table(
                                    groups[period,symbol[:2]],symbol,
                                    description=dt,title=symbol,
                                    filters=tables.Filters(
                                        complevel=5,complib="zlib",shuffle=True),
                                    expectedrows=(240 if period=="1min" else 48))
                            table.append(arr)
                            key=(period,symbol)
                            digest=expected_hash.setdefault(key,hashlib.sha256())
                            digest.update(arr.tobytes())
                            expected_count[key]+=len(arr)
                            written[period]+=len(arr)
                            if written[period]>max_rows:
                                raise ValueError("Minute mirrored row budget exceeded")
                if (written[period]!=entry["private_parquet_rows"]
                        or symbols_per_period[period]!=entry["private_parquet_stockdays"]):
                    raise ValueError("Minute Parquet rows/stocks not conserved in native H5")
                print("Wrote isolated Hikyuu minute TABLEs:",period,
                      "rows:",written[period],"stocks:",symbols_per_period[period],
                      flush=True)
        # Full H5 native integer read-back on all 6 output files, including
        # per-symbol ordering and exact 40-byte TABLE field offsets.
        checked=Counter()
        for period in STAGE.PERIODS:
            for market in ("sh","sz","bj"):
                path=dest/f"{market}_{period}.h5"
                with tables.open_file(str(path),"r") as file:
                    for table in file.root.data:
                        symbol=table._v_name
                        key=(period,symbol)
                        if (key not in expected_hash or
                                table.dtype!=dt or
                                int(table.nrows)!=expected_count[key]):
                            raise ValueError("Minute native H5 TABLE schema/count mismatch")
                        digest=hashlib.sha256()
                        for lo in range(0,int(table.nrows),8192):
                            digest.update(table.read(
                                lo,min(int(table.nrows),lo+8192)).tobytes())
                        if digest.digest()!=expected_hash[key].digest():
                            raise ValueError("Minute native integer H5 bytes changed")
                        checked[period]+=int(table.nrows)
            if checked[period]!=written[period]:
                raise ValueError("Minute native H5 full readback incomplete")
        result={
            "format":FORMAT,
            "status":"h5_origin_1min_5min_native_h5_written_full_integer_readback_only",
            "stage_source_day":day.isoformat(),
            "source_stage_safe_sha256":sha(Path(stage_safe)),
            "source_staged_minute_parquet_sha256":sources_sha,
            "native_h5_bar_counts":{k:int(v) for k,v in written.items()},
            "native_h5_full_integer_readback_counts":{k:int(v) for k,v in checked.items()},
            "native_h5_stock_tables":{k:int(v) for k,v in symbols_per_period.items()},
            "native_h5_six_files_sha256":{
                p.name:sha(p) for p in sorted(dest.glob("*.h5"))},
            "native_h5_40byte_pytables_tables_verified":True,
            "staged_h5_source_raw_integer_values_preserved_exactly":True,
            "original_13_irregular_stockdays_resolved":False,
            "purchased_parquet_2025_2026_included_in_these_h5_files":False,
            "minute_time_alignment_vendor_certified":False,
            "native_hikyuu_cpp_minute_driver_verified":False,
            "full_period_minute_mirror_completed":False,
            "original_vendor_parquet_or_hikyuu_h5_modified":False,
            "production_or_private_active_pointer_modified":False,
            "source_symbols_exact_times_or_ohlcva_exported":False,
        }
        payload=json.dumps(result,sort_keys=True,indent=2)+"\n"
        with safe.open("x",encoding="utf-8",newline="\n") as f:
            f.write(payload)
        completed=True
        return result
    finally:
        if not completed:
            print("Minute mirror incomplete; original Parquet/H5 unchanged",
                  flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-safe",type=Path,required=True)
    parser.add_argument("--run-id",required=True)
    parser.add_argument("--max-rows",type=int,default=3500000)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--write-isolated-native-minute-mirror",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        summary=write_mirror(args.stage_safe,args.run_id,args.out,args.max_rows)
        print("PASS: real H5-origin 1min/5min staged Parquet -> 6 native H5 TABLE files")
        print("Counts:",summary["native_h5_bar_counts"])
        print("Native H5 integer readback complete; C++ minute driver NOT YET verified")
        print("SAFE:",args.out)
    except Exception as error:
        last=traceback.extract_tb(error.__traceback__)[-1]
        parser.error("Private minute native H5 write refused ["+
                     type(error).__name__+"/"+last.name+":"+str(last.lineno)+
                     "]; original market files unchanged")


if __name__=="__main__":
    main()
