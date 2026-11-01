#!/usr/bin/env python3
"""Actually mirror already-written PURCHASED-FIRST physical minute Parquet to
NEW six native Hikyuu PyTables H5 files, with complete integer readback.

Sources: SHA-verified multi-day SAFE (e.g. Sep 28..30 purchased only) and
optional SHA-verified single-day unified SAFE (e.g. Oct 13 H5-only).
Purchased rows are the authority; native integer candidates are converted
using the previously tested DAY physical hypotheses: prices *1000,
volume /100, amount /1000. Unit scaling for MINUTES is NOT certified.
H5-origin staged rows retain their ORIGINAL seven native integers exactly.
Native timestamp is purchased Parquet bar start + period minutes; vendor
time alignment is not certified. Every output is isolated under module work/.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import traceback
from collections import Counter,defaultdict
from contextlib import ExitStack
from datetime import date,datetime,timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
DEST_ROOT=MODULE/"work"/"h5_mirror"
VERSION="AStockDataTools purchased-plus-H5 real minute Parquet to new native H5 v1"
SAFE_PATTERN=re.compile(r"work/unified_parquet/minute_complete_day/minute_([0-9a-f]{12})/(1min|5min)-(\d{4}-\d{2}-\d{2})\.parquet\Z")
RUN=re.compile(r"[0-9a-f]{12}\Z")


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,HERE/path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


M=load("native_full_minute_physical_stage","mirror-h5-origin-private-minute-parquet-to-native-h5.py")
U=load("native_full_minute_unified_physical","write-purchased-first-unified-minute-day-parquet.py")
ST=M.STAGE


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda:stream.read(1<<20),b""):
            digest.update(part)
    return digest.hexdigest()


def source_summary(path):
    p=Path(path)
    if (not p.is_file() or p.is_symlink() or
            p.resolve().parent!=REPORTS.resolve()
            or p.stat().st_size>1000000 or p.suffix!=".json"):
        raise ValueError("Require existing small aggregate SAFE in module reports")
    doc=json.loads(p.read_bytes())
    if (doc.get("format")!=U.FMT or
            doc.get("status")!="purchased_first_1min_5min_physical_parquet_unified_readback_only"
            or doc.get("original_purchased_parquet_or_hikyuu_h5_modified") is not False
            or doc.get("full_minute_history_unified") is not False
            or doc.get("minute_time_alignment_vendor_certified") is not False
            or set(doc.get("periods",{}))!=set(ST.PERIODS)):
        raise ValueError("Untrusted purchased-first physical minute SAFE")
    day=date.fromisoformat(doc["source_day"])
    result={}
    for period in ST.PERIODS:
        r=doc["periods"][period]
        rel=r.get("unified_parquet_relative_file")
        match=SAFE_PATTERN.fullmatch(rel) if type(rel) is str else None
        if (not match or match.group(2)!=period or match.group(3)!=str(day)
                or r.get("period")!=period or r.get("source_day")!=str(day)
                or r.get("full_merged_source_rows_and_vendor_extra_columns_readback_verified") is not True
                or r.get("ready_for_production_query") is not False
                or type(r.get("unified_rows")) is not int
                or type(r.get("source_rows")) is not dict
                or r["unified_rows"]!=sum(r["source_rows"].values())):
            raise ValueError("Untrusted daily physical unified Parquet source")
        file=MODULE/rel
        if (file.is_symlink() or file.parent.is_symlink()
                or file.resolve().parent.parent.parent.parent!=MODULE.resolve()
                or not file.is_file() or sha(file)!=r.get("unified_parquet_sha256")):
            raise ValueError("Physical unified minute Parquet SHA mismatch")
        result[period]=(file,r)
    return day,result


def collect(batch,additional):
    files=[]
    receipt_shas={}
    if batch is not None:
        p=Path(batch)
        if (not p.is_file() or p.is_symlink()
                or p.resolve().parent!=REPORTS.resolve()
                or p.stat().st_size>1000000):
            raise ValueError("Only module aggregate batch SAFE is accepted")
        b=json.loads(p.read_bytes())
        if (b.get("format")!="AStockDataTools real purchased-first two-period private minute batch v1"
                or b.get("status")!="bounded_two_period_actual_minute_days_physical_parquet_completed"
                or b.get("original_purchased_parquet_or_hikyuu_h5_modified") is not False
                or not 1<=b.get("batch_days",0)<=15
                or len(b.get("days",[]))!=b["batch_days"]):
            raise ValueError("Untrusted purchased-first multi-day batch SAFE")
        for item in b["days"]:
            day=date.fromisoformat(item["day"])
            safe_sha=item["unified_safe_sha256"]
            # Keep this discovery bound strictly to an accepted batch date/id.
            name="minute-batch-unified-"+day.strftime("%Y%m%d")+"-"
            matches=[
                file for file in REPORTS.glob(name+"*.json")
                if file.is_file() and not file.is_symlink()
                and sha(file)==safe_sha
            ]
            if len(matches)!=1:
                raise ValueError("A batch-day unified source SAFE is missing or ambiguous")
            files.append(matches[0])
        receipt_shas["batch_safe_sha256"]=sha(p)
    if additional is not None:
        files.append(Path(additional))
    if not files or len(files)>16:
        raise ValueError("Need 1..16 existing unified minute source SAFE files")
    days={}
    for file in files:
        day,sources=source_summary(file)
        if day in days:
            raise ValueError("Duplicate unified minute day in source receipts")
        days[day]=sources
        receipt_shas[str(day)]=sha(file)
    return sorted(days.items()),receipt_shas


def raw_purchased(row,period,day):
    ts=row["ts"]
    if type(ts) is not int:
        raise ValueError("Purchased minute timestamp not an int64")
    src=datetime.fromtimestamp(ts/1000,tz=ST.CORE.UTC8)
    if (src.date()!=day or src.second!=0 or src.microsecond!=0):
        raise ValueError("Purchased source timestamp off-day/off-minute")
    end=src+timedelta(minutes=1 if period=="1min" else 5)
    native_stamp=int(end.strftime("%Y%m%d%H%M"))
    if native_stamp not in ST.session_stamps(day,period):
        raise ValueError("Purchased source time cannot align with native Hikyuu grid")
    result={"datetime":native_stamp}
    loss={}
    for field,name,mult,limit in (
        ("open","openPrice",1000,2**32-1),
        ("high","highPrice",1000,2**32-1),
        ("low","lowPrice",1000,2**32-1),
        ("close","closePrice",1000,2**32-1),
        ("volume","transCount",0.01,2**64-1),
        ("amount","transAmount",0.001,2**64-1),
    ):
        value=row[field]
        if type(value) is not float or not math.isfinite(value) or value<0:
            raise ValueError("Purchased minute OHLCVA has invalid float")
        native=round(value*mult)
        if native<0 or native>limit:
            raise ValueError("Purchased minute value exceeds native H5 unsigned bounds")
        recon=native/mult
        loss[field]=abs(value-recon)
        result[name]=native
    return result,loss


def stage(batch_safe,additional_safe,run_id,out,*,max_total_rows=12000000):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    import numpy as np
    import tables
    if (type(run_id) is not str or RUN.fullmatch(run_id) is None
            or type(max_total_rows) is not int
            or not 1000<=max_total_rows<=16000000):
        raise ValueError("Invalid bounded purchased+H5 native minute mirror run")
    output=DEST_ROOT/f"minute_union_{run_id}"
    safe=Path(out)
    if (any(p.is_symlink() for p in (
            MODULE/"work",DEST_ROOT,REPORTS,output,safe))
            or safe.exists() or output.exists()
            or safe.suffix!=".json"
            or safe.resolve().parent!=REPORTS.resolve()
            or output.resolve().parent!=DEST_ROOT.resolve()):
        raise ValueError("Only fresh isolated native Hikyuu minute H5 and SAFE outputs")
    sources,source_sha=collect(batch_safe,additional_safe)
    expected_total=sum(r["unified_rows"] for _,records in sources
                       for _,r in records.values())
    if expected_total>max_total_rows:
        raise ValueError("Purchased/H5 unified minute rows exceed budget")
    native_dtype=M.dtype_for_hikyuu(np)
    fields=list(U.BASE)+["value_source"]+list(U.H5_NATIVE)
    counts=Counter()
    prices_changed=Counter()
    max_error={field:0.0 for field in U.BASE[2:]}
    expected_native_digest={}
    expected_stock_count=Counter()
    last_timestamp={}
    result_files={}
    DEST_ROOT.mkdir(parents=True,exist_ok=True)
    output.mkdir(exist_ok=False)
    completed=False
    try:
        with ExitStack() as stack:
            h5={}
            groups={}
            for period in ST.PERIODS:
                for market in ("sh","sz","bj"):
                    file=output/f"{market}_{period}.h5"
                    handle=stack.enter_context(tables.open_file(str(file),"w"))
                    h5[period,market.upper()]=handle
                    groups[period,market.upper()]=handle.create_group("/","data")
            for day,records in sources:
                for period in ST.PERIODS:
                    path,receipt=records[period]
                    before=sha(path)
                    # Table.take/Arrow sort avoids holding millions of
                    # heavyweight Python dictionaries for sorting.
                    with pq.ParquetFile(path,memory_map=False,pre_buffer=False) as parquet:
                        if (parquet.metadata.num_rows!=receipt["unified_rows"]
                                or not set(fields).issubset(parquet.schema_arrow.names)):
                            raise ValueError("Unified purchased/H5 schema/rowcount mismatch")
                        arr=pq.read_table(path,columns=fields,memory_map=False)
                    sorted_idx=pc.sort_indices(
                        arr,sort_keys=[("symbol","ascending"),("ts","ascending")])
                    arr=arr.take(sorted_idx)
                    del sorted_idx
                    by_source=Counter()
                    # group per stock even across record batch boundaries.
                    current=None
                    bucket=[]
                    def flush_stock(sym,rows):
                        if not rows:
                            return
                        market=sym[:2]
                        buffer=np.empty(len(rows),dtype=native_dtype)
                        last_key=last_timestamp.get((period,sym),0)
                        for i,row in enumerate(rows):
                            ts=row["ts"]
                            if type(ts) is not int:
                                raise ValueError("Invalid purchased/H5 minute physical key")
                            if row["value_source"]=="h5_only_complete_stockday":
                                record=M.native_rows([row],period,day,native_dtype,np)[0]
                                loss={}
                            elif row["value_source"]=="purchased_parquet":
                                raw,loss=raw_purchased(row,period,day)
                                record=np.zeros((),dtype=native_dtype)
                                for k,v in raw.items():
                                    record[k]=v
                            else:
                                raise ValueError("Unknown minute source class")
                            stamp=int(record["datetime"])
                            if stamp<=last_key:
                                raise ValueError("Native H5 timestamps duplicate or unordered")
                            last_key=stamp
                            buffer[i]=record
                            by_source[row["value_source"]]+=1
                            counts[period]+=1
                            counts[period+"_"+row["value_source"]]+=1
                            for field,error in loss.items():
                                if error:
                                    prices_changed[field]+=1
                                if error>max_error[field]:
                                    max_error[field]=error
                        last_timestamp[period,sym]=last_key
                        handle=h5[period,market]
                        try:
                            table=handle.get_node("/data/"+sym)
                        except tables.NoSuchNodeError:
                            table=handle.create_table(
                                groups[period,market],sym,
                                description=native_dtype,title=sym,
                                filters=tables.Filters(
                                    complevel=5,complib="zlib",shuffle=True),
                                expectedrows=1024)
                        table.append(buffer)
                        digest=expected_native_digest.setdefault(
                            (period,sym),hashlib.sha256())
                        digest.update(buffer.tobytes())
                        expected_stock_count[period,sym]+=len(buffer)
                    for batch in arr.to_batches(max_chunksize=8192):
                        for row in batch.to_pylist():
                            sym=row["symbol"]
                            if type(sym) is not str or not re.fullmatch(
                                    r"(SH|SZ|BJ)\d{6}",sym):
                                raise ValueError("Invalid unified minute canonical stock")
                            if current is not None and sym!=current:
                                flush_stock(current,bucket)
                                bucket=[]
                            current=sym
                            bucket.append(row)
                    if bucket:
                        flush_stock(current,bucket)
                    del arr
                    if (sum(by_source.values())!=receipt["unified_rows"]
                            or any(by_source.get(k,0)!=receipt["source_rows"].get(k,0)
                                for k in ("purchased_parquet","h5_only_complete_stockday"))
                            or sha(path)!=before):
                        raise ValueError("Native H5 mirror source count/SHA changed")
                    print("Committed real purchased-first native minute H5:",day,
                          period,"purchased:",by_source["purchased_parquet"],
                          "H5 gap:",by_source["h5_only_complete_stockday"],
                          flush=True)
        # Every market table re-opened and compared against the bytes
        # actually packed from the purchased/H5 physical unified Parquet.
        checked=Counter()
        for period in ST.PERIODS:
            for market in ("sh","sz","bj"):
                path=output/f"{market}_{period}.h5"
                result_files[path.name]=sha(path)
                with tables.open_file(str(path),"r") as handle:
                    for table in handle.root.data:
                        sym=table._v_name
                        key=(period,sym)
                        if (key not in expected_native_digest or
                                table.dtype!=native_dtype or
                                int(table.nrows)!=expected_stock_count[key]):
                            raise ValueError("Native full minute H5 table shape/count mismatch")
                        h=hashlib.sha256()
                        for begin in range(0,int(table.nrows),8192):
                            h.update(table.read(begin,min(
                                begin+8192,int(table.nrows))).tobytes())
                        if h.digest()!=expected_native_digest[key].digest():
                            raise ValueError("Purchased/H5 full minute native record bytes changed")
                        checked[period]+=int(table.nrows)
            if checked[period]!=counts[period]:
                raise ValueError("Purchased/H5 full minute H5 row count not conserved")
        summary={
            "format":VERSION,
            "status":"private_purchased_plus_h5_minute_40byte_native_h5_written_full_integer_readback",
            "source_days":[str(day) for day,_ in sources],
            "source_safe_sha256":source_sha,
            "native_bar_counts":{k:int(v) for k,v in checked.items()},
            "source_class_row_counts":{
                period:{
                    "purchased_parquet":int(counts[period+"_purchased_parquet"]),
                    "h5_only_complete_stockday":int(
                        counts[period+"_h5_only_complete_stockday"]),
                } for period in ST.PERIODS
            },
            "native_h5_files_sha256":result_files,
            "native_40byte_pytables_integer_full_readback_verified":True,
            "source_h5_raw_integer_rows_preserved":True,
            "purchased_float64_quantized_field_changed_rows":dict(prices_changed),
            "purchased_float64_quantized_max_abs_errors":max_error,
            "purchased_minute_unit_mapping_certified":False,
            "purchased_to_h5_minute_timestamp_mapping_certified":False,
            "native_cpp_full_minute_market_read_verified":False,
            "complete_minute_history_mirrored":False,
            "original_purchased_parquet_or_original_h5_modified":False,
            "production_pointer_modified":False,
            "source_stock_codes_timestamps_and_ohlcva_exported":False,
        }
        with safe.open("x",encoding="utf-8",newline="\n") as fp:
            fp.write(json.dumps(summary,sort_keys=True,indent=2)+"\n")
        completed=True
        return summary
    finally:
        if not completed:
            print("Native purchased/H5 minute mirror not complete; "
                  "original market Parquet/H5 untouched.",flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch-safe",type=Path,required=True)
    p.add_argument("--additional-unified-safe",type=Path)
    p.add_argument("--run-id",required=True)
    p.add_argument("--max-total-rows",type=int,default=12000000)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--write-isolated-full-minute-h5",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=stage(
            a.batch_safe,a.additional_unified_safe,
            a.run_id,a.out,max_total_rows=a.max_total_rows)
        print("PASS: real purchased+H5 minutes written as six isolated native H5 files")
        print("Native rows:",result["native_bar_counts"])
        print("Source float64 quantization counts:",
              result["purchased_float64_quantized_field_changed_rows"])
        print("Time/unit mapping certified: NO; original sources untouched")
        print("SAFE:",a.out)
    except Exception as error:
        last=traceback.extract_tb(error.__traceback__)[-1]
        p.error("Native purchased/H5 minute H5 mirror incomplete ["+
                type(error).__name__+"/"+last.name+":"+str(last.lineno)+
                "]; original vendors unchanged")


if __name__=="__main__":
    main()
