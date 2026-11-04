#!/usr/bin/env python3
"""Materialize 2011..2026 accepted private DAY Parquet into new native Hikyuu
sh_day.h5/sz_day.h5/bj_day.h5 files (not original market files).

Reuses already independent SHA-audited 16-year Parquet physical partitions.
One year at a time in memory; per-stock H5 table rows are written in sorted
day order. No index/pointer/production mutation. Every stored 40-byte Hikyuu
TABLE record is read back and SHA-compared with the exact integers sent to
PyTables. H5 amount conversion is quantized: never claim Float64 identity.

The input is the already verified 2011..2026 private day snapshot, NOT
D:/stock/AllCycleAStockData. All output under module work/h5_mirror/.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
import traceback
from collections import Counter,defaultdict
from contextlib import ExitStack
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
MIRRORS=MODULE/"work"/"h5_mirror"
FORMAT="AStockDataTools whole accepted private day Parquet to native Hikyuu H5 v1"

def tool(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    v=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v)
    return v

Q=tool("whole_day_h5_source_version","query-private-2011-2026-all16-coverage-readonly.py")
S=tool("whole_day_h5_integer_converter","write-private-parquet-day-to-hikyuu-h5-canary.py")

def hsha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def mirror(version_path,version_sha,run_id,out,
           *,first_year=2011,last_year=2026,max_year_rows=2500000):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import numpy as np
    import tables
    if (type(run_id) is not str or
            re.fullmatch(r"[0-9a-f]{12}",run_id) is None
            or type(first_year) is not int or type(last_year) is not int
            or first_year<2011 or last_year>2026 or first_year>last_year
            or type(max_year_rows) is not int or
            not 1000<=max_year_rows<=3000000):
        raise ValueError("Only bounded audited 2011..2026 physical DAY years")
    dest=MIRRORS/f"full_day_{run_id}"
    safe=Path(out)
    if (any(p.is_symlink() for p in (
            MODULE/"work",MIRRORS,REPORTS,dest,safe))
            or dest.exists() or safe.exists()
            or safe.suffix!=".json"
            or safe.resolve().parent!=REPORTS.resolve()
            or dest.resolve().parent!=MIRRORS.resolve()):
        raise ValueError("Must use NEW isolated H5 files and module reports")
    version=Q.version(version_path,version_sha)
    selected=list(range(first_year,last_year+1))
    dtype=np.dtype([
        ("closePrice","<u4"),("datetime","<u8"),
        ("highPrice","<u4"),("lowPrice","<u4"),
        ("openPrice","<u4"),("transAmount","<u8"),
        ("transCount","<u8"),
    ])
    if (dtype.itemsize!=40 or tuple(dtype.fields[k][1] for k in dtype.names)
            !=(0,4,12,16,20,24,32)):
        raise ValueError("Cannot create audited native Hikyuu H5 TABLE dtype")
    MIRRORS.mkdir(parents=True,exist_ok=True)
    dest.mkdir(exist_ok=False)
    market_handles={}
    grouped={}
    digests={}
    last_key={}
    counts=Counter()
    categories=Counter()
    loss=Counter()
    maximum={k:0.0 for k in S.FIELDS}
    annual_rows={}
    partition_files=0
    completed=False
    try:
        with ExitStack() as stack:
            for venue in ("SH","SZ","BJ"):
                file=dest/(venue.lower()+"_day.h5")
                handle=stack.enter_context(tables.open_file(str(file),mode="w"))
                market_handles[venue]=handle
                grouped[venue]=handle.create_group("/","data")
            for year in selected:
                node=version["annual"][str(year)]
                relative=node.get("private_relative_directory")
                if (type(relative) is not str or
                        Q.YEAR_DIR.fullmatch(relative) is None or
                        int(Q.YEAR_DIR.fullmatch(relative).group(1))!=year):
                    raise ValueError("Year directory not pinned in version")
                folder=MODULE/relative
                manifest_path=folder/"manifest.json"
                sqlite_path=folder/"stockday-unique.sqlite3"
                if (folder.is_symlink() or manifest_path.is_symlink()
                        or sqlite_path.is_symlink() or
                        folder.resolve().parent!=Q.M.ROOT.resolve()
                        or Q.M.ST.sha(manifest_path)!=node.get("physical_manifest_sha256")
                        or Q.M.ST.sha(sqlite_path)!=node.get("private_stockday_index_sha256")):
                    raise ValueError("Audited private annual source changed")
                m=json.loads(manifest_path.read_bytes())
                if m.get("year")!=year or m.get("total_private_physical_rows")!=node["total_rows"]:
                    raise ValueError("Annual manifest row count changed")
                if not 0<node["total_rows"]<=max_year_rows:
                    raise ValueError("Year source exceeds bounded memory budget")
                year_data=defaultdict(list)
                loaded=0
                for key,path,part in Q.entries(year,folder,m):
                    if (path.is_symlink() or path.parent.is_symlink()
                            or not path.is_file() or
                            Q.M.ST.sha(path)!=part["sha256"]):
                        raise ValueError("Audited annual partition SHA mismatch")
                    partition_files+=1
                    with pq.ParquetFile(path,memory_map=False,pre_buffer=False) as pqfile:
                        if (pqfile.schema_arrow!=Q.PHYS.schema(pa)
                                or pqfile.metadata.num_rows!=part["rows"]):
                            raise ValueError("Annual normalized DAY Arrow schema mismatch")
                        for batch in pqfile.iter_batches(batch_size=32768):
                            for row in batch.to_pylist():
                                sym=row["symbol"]
                                if (type(sym) is not str
                                        or not re.fullmatch(r"(SH|SZ|BJ)[0-9]{6}",sym)
                                        or row["trading_date"][:4]!=str(year)):
                                    raise ValueError("Untrusted normalized stockday identity")
                                record,errors=S.raw_row(row)
                                year_data[sym].append(record)
                                categories[row["value_source"]]+=1
                                for field,error in errors.items():
                                    maximum[field]=max(maximum[field],error)
                                    if error:
                                        loss[field]+=1
                                loaded+=1
                                if loaded>max_year_rows:
                                    raise ValueError("Annual Parquet exceeds memory budget")
                if loaded!=node["total_rows"]:
                    raise ValueError("Purchased/H5 annual row count not conserved")
                for symbol,rows in sorted(year_data.items()):
                    rows.sort(key=lambda rec:rec[0])
                    if (symbol in last_key and
                            rows[0][0]<=last_key[symbol]):
                        raise ValueError("Cross-year mirror day ordering/overlap invalid")
                    if any(rows[i][0]>=rows[i+1][0]
                           for i in range(len(rows)-1)):
                        raise ValueError("Duplicate or unsorted stockday in private year")
                    last_key[symbol]=rows[-1][0]
                    array=np.empty(len(rows),dtype=dtype)
                    for i,r in enumerate(rows):
                        array[i]["datetime"]=r[0]
                        array[i]["openPrice"]=r[1]
                        array[i]["highPrice"]=r[2]
                        array[i]["lowPrice"]=r[3]
                        array[i]["closePrice"]=r[4]
                        array[i]["transCount"]=r[5]
                        array[i]["transAmount"]=r[6]
                    venue=symbol[:2]
                    handle=market_handles[venue]
                    try:
                        table=handle.get_node("/data/"+symbol)
                    except tables.NoSuchNodeError:
                        table=handle.create_table(
                            grouped[venue],symbol,description=dtype,title=symbol,
                            filters=tables.Filters(
                                complevel=5,complib="zlib",shuffle=True),
                            expectedrows=4096)
                    table.append(array)
                    table.flush()
                    digest=digests.setdefault(symbol,hashlib.sha256())
                    digest.update(array.tobytes())
                    counts[venue]+=len(rows)
                annual_rows[str(year)]=loaded
                print("Committed private native H5 day year:",year,
                      "rows:",loaded,flush=True)
                del year_data
        # Independent full integer readback after closing all source writers:
        readback=0
        for venue in ("SH","SZ","BJ"):
            with tables.open_file(str(dest/(venue.lower()+"_day.h5")),"r") as handle:
                for table in handle.root.data:
                    sym=table._v_name
                    if (sym not in digests or
                            table.dtype!=dtype or
                            table.nrows<=0):
                        raise ValueError("Native Hikyuu market TABLE dtype mismatch")
                    check=hashlib.sha256()
                    for offset in range(0,table.nrows,8192):
                        check.update(table.read(offset,min(table.nrows,offset+8192)).tobytes())
                    if check.digest()!=digests[sym].digest():
                        raise ValueError("Private H5 TABLE bytes differ from Parquet-derived integers")
                    # PyTables may expose nrows as numpy.int64; never let
                    # NumPy scalars escape into JSON SAFE statistics.
                    readback+=int(table.nrows)
        full=sum(annual_rows.values())
        if (readback!=full or sum(counts.values())!=full
                or sum(categories.values())!=full):
            raise ValueError("Native H5 full row conservation/readback failed")
        safe_result={
            "format":FORMAT,
            "status":"private_day_native_h5_40byte_tables_written_all_integer_rows_readback_not_activated",
            "source_16year_private_version_sha256":version_sha,
            "year_range":[first_year,last_year],
            "annual_rows":{str(k):int(v) for k,v in annual_rows.items()},
            "purchased_h5_candidate_source_counts":{str(k):int(v) for k,v in categories.items()},
            "total_private_parquet_rows":int(full),
            "total_h5_native_integer_records":int(readback),
            "venue_record_counts":{str(k):int(v) for k,v in counts.items()},
            "stock_tables_count":int(len(digests)),
            "source_parquet_partitions_sha_verified":int(partition_files),
            "h5_native_integer_changed_field_rows":{str(k):int(v) for k,v in loss.items()},
            "h5_native_integer_max_abs_purchased_unit_error":{str(k):float(v) for k,v in maximum.items()},
            "all_source_ohlcva_bitwise_exactly_representable":not bool(loss),
            "native_40byte_table_integer_sha_readback_verified":True,
            "native_hikyuu_cpp_full_market_read_verified":False,
            "h5_source_amount_units_explicitly_not_certified":True,
            "private_h5_files_sha256":{
                p.name:hsha(p) for p in sorted(dest.glob("*_day.h5"))},
            "original_purchased_parquet_files_modified":False,
            "original_hikyuu_h5_files_modified":False,
            "production_or_private_active_pointer_modified":False,
            "full_mirror_ready_for_production":False,
            "source_ohlcva_values_or_stock_symbols_exported_to_safe":False,
        }
        # Encode BEFORE creating the SAFE output. A malformed statistic
        # must never leave behind a truncated JSON that looks like a report.
        safe_text=json.dumps(safe_result,sort_keys=True,indent=2)+"\n"
        with safe.open("x",encoding="utf-8",newline="\n") as fp:
            fp.write(safe_text)
        completed=True
        return safe_result
    finally:
        # On failure retain the newly-created private partial files for
        # investigation, but publish NO successful SAFE. Never touch originals.
        if not completed:
            print("Private mirror incomplete; original market sources unchanged.",
                  flush=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version-safe",type=Path,required=True)
    p.add_argument("--version-sha256",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--start-year",type=int,default=2011)
    p.add_argument("--end-year",type=int,default=2026)
    p.add_argument("--max-year-rows",type=int,default=2500000)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--write-private-native-day-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        r=mirror(a.version_safe,a.version_sha256,a.run_id,a.out,
                 first_year=a.start_year,last_year=a.end_year,
                 max_year_rows=a.max_year_rows)
        print("PASS: Actual private native PyTables DAY H5 mirrored and integer read back")
        print("Rows:",r["total_h5_native_integer_records"])
        print("Amount precision-loss row count:",
              r["h5_native_integer_changed_field_rows"].get("amount",0))
        print("H5 C++ full market verified: NO; original market modified: NO")
        print("SAFE:",a.out)
    except Exception as exc:
        last=traceback.extract_tb(exc.__traceback__)[-1]
        p.error("Private native DAY H5 batch failed ["+
                type(exc).__name__+"/"+last.name+":"+str(last.lineno)+
                "]; no source or original H5 changed; incomplete private output retained")


if __name__=="__main__":
    main()
