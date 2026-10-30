#!/usr/bin/env python3
"""Qualify seven bounded historical Hikyuu H5 native-read targets (READ ONLY).

Select fixed year/market/quarter/factor cohorts from the immutable private RAW
Parquet already verified against original H5. For each selected record,
independently binary-locate ONE original H5 day row and compare ALL native
integer fields in memory. Save ONLY symbol, day and native H5 row index to a
NEW gitignored PRIVATE selection manifest for a subsequent isolated C++ HMAC
reader. SAFE JSON contains counts / proof hashes, no symbol, exact day,
individual OHLCVA or original H5 source paths.

No Hikyuu native read is attempted here. No original market H5 or purchased
Parquet is modified; units, corporate actions and security master are UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
WORK=MODULE/"work"/"h5_mirror"/"historical_native_qualification"
FORMAT="AStockDataTools pre2011 qualified original H5 historical native read targets v1"
PRIVATE_FORMAT="AStockDataTools private historical native read source coordinates v1"
# Seventh cohort deliberately tests the 1995 SH Q1 no-factor residual,
# not a blindly accepted 10000 factor. This is just a sample, not validation.
COHORTS=(
    (1992,"SH",2,100000),
    (1992,"SH",3,100000),
    (1992,"SH",4,10000),
    (1992,"SZ",2,10000),
    (1993,"SH",1,10000),
    (1993,"SZ",1,10000),
    (1995,"SH",1,0),
)
MAX_SOURCE_STOCK_DAYS=25000


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


V=load("historical_native_target_factor_math",
       "audit-pre2011-private-raw-vwap-factors-readonly.py")
P=V.P
SINGLE=P.SINGLE
FIELDS=SINGLE.FIELDS


def selection_score(row,cohort):
    """Private RAW row matches a fixed cohort; returns only a boolean."""
    year,market,quarter,factor=cohort
    symbol=row["symbol"]
    key=row["datetime"]
    if (type(symbol) is not str or not re.fullmatch(r"(SH|SZ)[0-9]{6}",symbol)
            or not SINGLE.AUDIT.CORE.is_a_share_candidate(symbol,year)
            or type(key) is not int or key%10000):
        raise ValueError("Invalid historical private RAW symbol/date")
    d=SINGLE.AUDIT.date_key(key)
    if d.year!=year:
        raise ValueError("Historical RAW candidate is outside its annual file")
    if symbol[:2]!=market or (d.month-1)//3+1!=quarter:
        return False
    if any(type(row[k]) is not int or not 0<=row[k]<2**64
           for k in SINGLE.REQUIRED_NUMERIC):
        raise ValueError("Invalid historical private H5 RAW integer")
    low,high=row["lowPrice"],row["highPrice"]
    if not 0<low<=row["openPrice"]<=high or not low<=row["closePrice"]<=high:
        raise ValueError("Invalid historical private H5 RAW OHLC bounds")
    volume,amount=row["transCount"],row["transAmount"]
    if not volume>0 or not amount>0:
        return False
    matching=[
        f for f in V.FACTOR_GRID
        if V.vwap_candidate_matches(amount,volume,low,high,f)
    ]
    return len(matching)==0 if factor==0 else matching==[factor]


def pick_from_private(file,year,expected):
    """One bounded sequential pass per selected year; never emit raw rows."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    wanted=[c for c in COHORTS if c[0]==year]
    selected={}
    seen=0
    reader=pq.ParquetFile(file,memory_map=False,pre_buffer=False)
    try:
        if (tuple(reader.schema_arrow.names)!=FIELDS
                or reader.schema_arrow.field("symbol").type!=pa.string()
                or any(reader.schema_arrow.field(k).type!=pa.uint64()
                       for k in SINGLE.REQUIRED_NUMERIC)
                or reader.metadata.num_rows!=expected):
            raise ValueError("Private annual original-native RAW schema/row count changed")
        for batch in reader.iter_batches(batch_size=SINGLE.CHUNK,columns=list(FIELDS)):
            if any(batch.column(i).null_count for i in range(len(FIELDS))):
                raise ValueError("Null private RAW historical field")
            for row in batch.to_pylist():
                if SINGLE.AUDIT.date_key(row["datetime"]).year!=year:
                    raise ValueError("Private year contains wrong source date")
                for cohort in wanted:
                    if selection_score(row,cohort):
                        # Lexical minimization is deterministic, independent
                        # of compression and batch/rowgroup iteration layout.
                        marker=(row["symbol"],row["datetime"])
                        current=selected.get(cohort)
                        if current is None or marker<(current["symbol"],current["datetime"]):
                            selected[cohort]=row
                seen+=1
                if seen>expected or seen>SINGLE.MAX_YEAR_ROWS:
                    raise ValueError("Private RAW source year exceeds bounded budget")
        if seen!=expected:
            raise ValueError("Private original-native RAW year incomplete")
    finally:
        reader.close()
    if set(selected)!=set(wanted):
        raise ValueError("No positive-quantity/amount historical RAW candidate in required cohort")
    return selected


def real_h5_files(root):
    p=Path(root)
    if (not p.is_absolute() or p.is_symlink() or not p.is_dir()
            or p.resolve()!=p):
        raise ValueError("Original H5 root must be canonical absolute directory")
    folder=p/"HikyuuData"
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Missing or linked original HikyuuData source folder")
    result={}
    for market in ("SH","SZ"):
        path=folder/(market.lower()+"_day.h5")
        SINGLE.AUDIT.state(path)
        result[market]=path
    return result


def real_h5_read_match(files,selected):
    """At most one original row per cohort + O(log N) datetime binary searches."""
    import h5py
    states={name:SINGLE.AUDIT.state(path) for name,path in files.items()}
    verified={}
    for market in ("SH","SZ"):
        with h5py.File(files[market],"r") as h5:
            group=h5.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("Original H5 source /data group missing")
            for cohort,row in selected.items():
                if cohort[1]!=market:
                    continue
                symbol=row["symbol"]
                ds=group.get(symbol)
                if (not isinstance(ds,h5py.Dataset) or ds.ndim!=1
                        or not 1<=len(ds)<=MAX_SOURCE_STOCK_DAYS
                        or not set(SINGLE.AUDIT.CORE.H5_FIELDS).issubset(
                            ds.dtype.names or ())):
                    raise ValueError("Selected historical original H5 stock dataset invalid")
                # Source-native timestamp is an exact day key YYYYMMDD0000.
                day=row["datetime"]
                lo,hi=SINGLE.AUDIT.CORE.h5_key_slice(ds,day,day+1)
                if hi-lo!=1:
                    raise ValueError("Historical native target is missing or duplicated in original H5")
                actual=ds[lo]
                if any(int(actual[name])!=row[name] for name in SINGLE.REQUIRED_NUMERIC):
                    raise ValueError("Original H5 selected row differs from immutable private RAW")
                verified[cohort]={
                    "year":cohort[0],"market":market,"quarter":cohort[2],
                    "candidate_factor":cohort[3],
                    "symbol":symbol,"datetime":day,
                    "source_native_stock_index":int(lo),
                    "source_stock_total_day_count":int(len(ds)),
                }
    if set(verified)!=set(COHORTS):
        raise ValueError("Not all historical native H5 target rows verified")
    if any(SINGLE.AUDIT.state(path)!=states[name]
           for name,path in files.items()):
        raise ValueError("Original market H5 file changed during target qualification")
    return verified


def target_private(run_id):
    if (type(run_id) is not str or not re.fullmatch(r"[a-f0-9]{12,32}",run_id)
            or any(p.is_symlink() for p in (
                MODULE/"work",MODULE/"work"/"h5_mirror",WORK))):
        raise ValueError("Unsafe private historical native selection run id or hierarchy")
    if WORK.exists() and not WORK.is_dir():
        raise ValueError("Private historical native work area invalid")
    target=WORK/("native_targets_"+run_id)
    if target.exists() or target.is_symlink():
        raise ValueError("Historical native selection run id already exists")
    return target


def run(root,full21_safe,run_id,out):
    full,full_hash=P.source_safe(full21_safe)
    dest=P.target_safe(out)
    private=target_private(run_id)
    entries=P.verified_private_files(full)
    selected={}
    needed={c[0] for c in COHORTS}
    for year,path,expected,digest in entries:
        if year in needed:
            stat=(path.stat().st_size,path.stat().st_mtime_ns)
            selected.update(pick_from_private(path,year,expected))
            if ((path.stat().st_size,path.stat().st_mtime_ns)!=stat
                    or SINGLE.hash_file(path)!=digest):
                raise ValueError("Private annual raw changed while qualifying H5 targets")
    if set(selected)!=set(COHORTS):
        raise ValueError("Not all required early H5 cohorts exist in private source")
    files=real_h5_files(root)
    coordinates=real_h5_read_match(files,selected)
    record={
        "format":PRIVATE_FORMAT,"source_full21_safe_sha256":full_hash,
        "sample_count":len(COHORTS),
        "sample_selections":[coordinates[c] for c in COHORTS],
        "source_original_h5_files_read_only":True,
        "physical_units_certified":False,
        "authorized_for_market_data_write":False,
    }
    # The private manifest deliberately holds stock/date/index selectors
    # (NOT prices, volume or amount) and is never added to the Git repository.
    WORK.mkdir(parents=True,exist_ok=True)
    private.mkdir(exist_ok=False)
    manifest=private/"selected-original-h5-native-targets.json"
    try:
        with manifest.open("x",encoding="utf-8") as f:
            json.dump(record,f,ensure_ascii=False,indent=2,sort_keys=True)
            f.write("\n")
        sha=SINGLE.hash_file(manifest)
        safe={
            "format":FORMAT,
            "status":"historical_native_h5_target_qualification_only_no_driver_called",
            "source_full21_safe_sha256":full_hash,
            "private_selection_manifest_sha256":sha,
            "private_selection_relative_path":manifest.relative_to(MODULE).as_posix(),
            "required_cohorts":[{"year":y,"market":m,"quarter":q,
                                  "candidate_factor":factor}
                                 for y,m,q,factor in COHORTS],
            "sample_count":len(COHORTS),
            "private_raw_original_h5_integer_rows_identical":True,
            "full21_private_raw_sha_chain_checked":True,
            "original_h5_file_stat_unchanged":True,
            "original_h5_full_content_sha256_rechecked":False,
            "current_all_original_sources_requalified":False,
            "purchased_parquet_opened":False,
            "original_h5_read_only":True,
            "hikyuu_native_driver_called":False,
            "historical_native_units_or_securities_certified":False,
            "production_or_private_active_pointer_modified":False,
            "standardized_parquet_or_h5_mirror_created":False,
            "raw_symbol_day_ohlcva_excluded_from_safe":True,
        }
        with dest.open("x",encoding="utf-8") as f:
            json.dump(safe,f,ensure_ascii=False,indent=2,sort_keys=True)
            f.write("\n")
        return safe
    except BaseException:
        # Remove only the new, exclusively owned private selection file/dir
        # if the SAFE output cannot be created; never clean other work files.
        if manifest.exists():
            manifest.unlink()
        private.rmdir()
        raise


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--full21-safe",type=Path,required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-historical-native-targets",
                   action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        summary=run(args.root,args.full21_safe,args.run_id,args.out)
        print("Qualified historical H5 original-native target samples:",
              summary["sample_count"])
        print("No native C++ Hikyuu driver run; no purchased Parquet read.")
        print("Historical physical units and stock identities NOT certified.")
        print("SAFE:",args.out)
    except (ValueError,KeyError,TypeError,OSError,OverflowError,ImportError,
            ModuleNotFoundError,json.JSONDecodeError):
        p.error("Historical H5 native target qualification refused; no market source modified")


if __name__=="__main__":
    main()
