#!/usr/bin/env python3
"""Read-only, full-source-key pre-2011 H5 day coverage vs ALL purchased day footers.

H5: project ONLY 'datetime' field in bounded chunks, verify all selected
A-share candidate datasets are strictly increasing and count 1990..2010 dates
exactly. Purchased Parquet: inspect ts min/max in EVERY existing day file's
row-group footer, regardless of misleading or missing YYYY filename.
Missing Parquet footer statistics are UNKNOWN, never proof of absence.

This is discovery, not a permission to normalize/append legacy H5. No H5/PQ
raw OHLCVA is exported and neither market source nor private pointer is written.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools pre2011 original H5 vs purchased all-day Parquet source evidence v1"
FIRST_YEAR=1990
LAST_YEAR=2010
H5_CHUNK_ROWS=16384
MAX_H5_DATASETS=20000
MAX_PQ_FILES=512
MAX_PQ_ROW_GROUPS=50000
CUTOFF=date(2011,1,1)
MINIMUM=date(1990,1,1)


def load_core():
    spec=importlib.util.spec_from_file_location(
        "pre2011_day_core",HERE/"reconcile-local-a-share-h5-parquet.py")
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


CORE=load_core()


def state(p):
    if p.is_symlink() or not p.is_file():
        raise ValueError("Missing or symlinked original market source")
    s=p.stat()
    return (int(s.st_size),int(s.st_mtime_ns))


def digest_states(items):
    # Entries must contain source-relative names, never absolute source paths.
    return hashlib.sha256(json.dumps(sorted(items),
        separators=(",",":"),ensure_ascii=True).encode()).hexdigest()


def date_key(key):
    if key<=0 or key%10000!=0:
        raise ValueError("Invalid H5 daily time key (not YYYYMMDD0000)")
    number=key//10000
    try:
        return date(number//10000,(number//100)%100,number%100)
    except ValueError:
        raise ValueError("Invalid H5 historical day calendar key") from None


def inspect_h5(root):
    import h5py
    import numpy as np
    folder=root/"HikyuuData"
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Original HikyuuData directory unavailable or linked")
    files=[folder/(m+"_day.h5") for m in ("sh","sz","bj")]
    # BJ is optional for 1990..2010, but SH and SZ must be inspected.
    for path in files[:2]:
        state(path)
    selected=[p for p in files if p.is_file()]
    before={p:state(p) for p in selected}
    per_year={str(y):{"H5_candidate_stockday_rows":0,
                      "H5_candidate_stocks_with_rows":0,
                      "market_prefix_row_counts":{"SH":0,"SZ":0,"BJ":0}}
              for y in range(FIRST_YEAR,LAST_YEAR+1)}
    rows=Counter()
    stocksets={str(y):set() for y in range(FIRST_YEAR,LAST_YEAR+1)}
    excluded=0
    datasets=0
    all_keys_scanned=0
    early_keys=0
    first_seen=None
    last_seen=None
    for p in selected:
        market=p.name[:2].upper()
        with h5py.File(p,"r") as h:
            group=h.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("Missing H5 /data group")
            for symbol in group:
                if not re.fullmatch(market+r"[0-9]{6}",symbol):
                    continue
                ds=group.get(symbol)
                if (not isinstance(ds,h5py.Dataset) or ds.ndim!=1
                        or "datetime" not in (ds.dtype.names or ())):
                    raise ValueError("Invalid original H5 day dataset")
                # Prefix filter is deliberately NOT a security master.
                if not CORE.is_a_share_candidate(symbol,2010):
                    excluded+=1
                    continue
                datasets+=1
                if datasets>MAX_H5_DATASETS:
                    raise ValueError("H5 selected dataset budget exceeded")
                prev=None
                for begin in range(0,len(ds),H5_CHUNK_ROWS):
                    # h5py .fields("datetime") returns a plain 1-D
                    # uint64 ndarray, not a structured record array.
                    projected=ds.fields("datetime")[begin:begin+H5_CHUNK_ROWS]
                    keys=np.asarray(projected,dtype=np.uint64)
                    if not len(keys):
                        continue
                    if prev is not None and int(keys[0])<=prev:
                        raise ValueError("H5 full-source day keys not strictly ascending")
                    if len(keys)>1 and bool(np.any(keys[1:]<=keys[:-1])):
                        raise ValueError("H5 full-source day keys not strictly ascending")
                    prev=int(keys[-1])
                    all_keys_scanned+=len(keys)
                    # Check selected old years EXACTLY, not via binary search
                    # assuming full history sorted (we actually verified it).
                    for value in keys:
                        k=int(value)
                        if k>=201101010000:
                            continue
                        d=date_key(k)
                        if d<MINIMUM:
                            early_keys+=1
                            continue
                        label=str(d.year)
                        per_year[label]["H5_candidate_stockday_rows"]+=1
                        per_year[label]["market_prefix_row_counts"][market]+=1
                        stocksets[label].add(symbol)
                        rows[market]+=1
                        if first_seen is None or d<first_seen:
                            first_seen=d
                        if last_seen is None or d>last_seen:
                            last_seen=d
    for year in per_year:
        per_year[year]["H5_candidate_stocks_with_rows"]=len(stocksets[year])
    if {p:state(p) for p in selected}!=before:
        raise ValueError("Original H5 market file changed during inventory")
    return {
        "source_market_day_files":len(selected),
        "candidate_a_share_code_pattern_datasets":datasets,
        "excluded_non_candidate_symbol_datasets":excluded,
        "all_selected_h5_daily_datetime_keys_scanned":int(all_keys_scanned),
        "pre_1990_day_keys_ignored_for_scope":early_keys,
        "pre2011_candidate_h5_stockday_rows":sum(rows.values()),
        "pre2011_candidate_h5_market_row_counts":{
            m:int(rows[m]) for m in ("SH","SZ","BJ")},
        "earliest_pre2011_candidate_h5_date":(
            first_seen.isoformat() if first_seen else None),
        "latest_pre2011_candidate_h5_date":(
            last_seen.isoformat() if last_seen else None),
        "yearly_source_key_inventory":per_year,
        "selected_dataset_datetime_keys_full_scan_strictly_increasing":True,
        "A_share_selection_is_historical_code_pattern_not_security_master":True,
        "original_h5_prices_volume_amount_not_read":True,
        "source_stat_only_sha256":digest_states([
            [p.name,*before[p]] for p in selected]),
    }, before


def to_day(ms):
    if type(ms) is not int:
        raise ValueError("Noninteger Parquet ts footer")
    try:
        d=datetime.fromtimestamp(ms/1000,tz=CORE.UTC8).date()
    except (ValueError,OverflowError,OSError):
        raise ValueError("Unparseable Parquet ts footer") from None
    return d


def purchased_paths(root):
    folder=root/"AllCycleAStockData"/"day"
    parent=folder.parent
    if (not folder.is_dir() or folder.is_symlink()
            or parent.is_symlink()):
        raise ValueError("Original purchased day Parquet directory unavailable")
    # Inspect ALL filenames regardless of year convention, including 2011+
    # files that might accidentally contain data from 2010.
    paths=[]
    examined=0
    for file in folder.rglob("*"):
        examined+=1
        if examined>MAX_PQ_FILES*12:
            raise ValueError("Purchased day directory entry budget exceeded")
        # Do not silently skip a linked directory potentially hiding older
        # purchased dates. Evidence must cover the entire selected tree.
        if file.is_symlink():
            raise ValueError("Linked purchased day file or directory")
        if file.is_dir() or file.suffix.lower()!=".parquet":
            continue
        if (not file.is_file()
                or not file.resolve().is_relative_to(folder.resolve())):
            raise ValueError("Unsafe purchased day Parquet path")
        paths.append(file)
        if len(paths)>MAX_PQ_FILES:
            raise ValueError("Purchased Parquet file budget exceeded")
    return folder,sorted(paths)


def inspect_purchased(root):
    import pyarrow.parquet as pq
    folder,files=purchased_paths(root)
    before={p:state(p) for p in files}
    total_groups=0
    with_stats=0
    unknown=0
    possibly_old=0
    earliest=None
    latest=None
    for source in files:
        pf=pq.ParquetFile(source,memory_map=False,pre_buffer=False)
        try:
            if "ts" not in pf.schema_arrow.names:
                raise ValueError("Purchased daily Parquet has no ts column")
            for i in range(pf.metadata.num_row_groups):
                total_groups+=1
                if total_groups>MAX_PQ_ROW_GROUPS:
                    raise ValueError("Purchased daily row-group budget exceeded")
                rg=pf.metadata.row_group(i)
                if rg.num_rows==0:
                    continue
                bounds=None
                for col in range(rg.num_columns):
                    c=rg.column(col)
                    if c.path_in_schema=="ts":
                        st=c.statistics
                        if st is not None and st.has_min_max:
                            bounds=(int(st.min),int(st.max))
                        break
                if bounds is None:
                    unknown+=1
                    continue
                lo,hi=(to_day(k) for k in bounds)
                if lo>hi:
                    raise ValueError("Parquet footer min/max inverted")
                with_stats+=1
                possibly_old+=int(lo<CUTOFF)
                earliest=lo if earliest is None else min(earliest,lo)
                latest=hi if latest is None else max(latest,hi)
        finally:
            pf.close()
    if {p:state(p) for p in files}!=before:
        raise ValueError("Original purchased day Parquet changed during inventory")
    if unknown:
        status="unknown_pre2011_purchased_coverage_missing_row_group_stats"
    elif possibly_old:
        status="pre2011_timestamp_ranges_possible_in_purchased_day_files"
    else:
        status="all_scanned_nonempty_purchased_day_footers_start_2011_or_later"
    return {
        "source_day_parquet_files_scanned":len(files),
        "source_day_row_groups_scanned":total_groups,
        "nonempty_row_groups_with_valid_ts_bounds":with_stats,
        "nonempty_row_groups_without_ts_stats":unknown,
        "row_groups_with_possible_pre2011_timestamp":possibly_old,
        "earliest_all_stock_footer_candidate_day":(
            earliest.isoformat() if earliest else None),
        "latest_all_stock_footer_candidate_day":(
            latest.isoformat() if latest else None),
        "pre2011_original_purchased_coverage_status":status,
        "no_pre2011_parquet_rows_proven_by_complete_footer_bounds":(
            unknown==0 and possibly_old==0),
        "parquet_footer_bound_is_all_stock_not_a_verified_stock_key":True,
        "original_purchased_OHLCVA_columns_not_read":True,
        "source_stat_only_sha256":digest_states([
            [p.relative_to(folder).as_posix(),*before[p]] for p in files]),
    }, before


def destination(out):
    p=Path(out)
    if (REPORTS.is_symlink() or p.is_symlink() or p.exists()
            or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("SAFE report must be NEW module reports JSON")
    return p.resolve()


def inventory(root,out):
    dest=destination(out)
    root=Path(root).resolve()
    if (not root.is_dir() or MODULE.is_relative_to(root)
            or (root/"HikyuuData").is_symlink()
            or (root/"AllCycleAStockData").is_symlink()):
        raise ValueError("Unsafe original sources or overlapping project directory")
    h5,hs=inspect_h5(root)
    purchased,ps=inspect_purchased(root)
    if (any(state(p)!=s for p,s in hs.items())
            or any(state(p)!=s for p,s in ps.items())):
        raise ValueError("Original H5/PQ changed before SAFE publishing")
    summary={
        "format":FORMAT,
        "status":"pre2011_full_source_day_timestamp_coverage_inventory_not_staged",
        "historical_inclusive_start":"1990-01-01",
        "historical_inclusive_end":"2010-12-31",
        "original_h5":h5,
        "original_purchased_parquet":purchased,
        "pre2011_h5_rows_certified_as_A_share_equities":False,
        "historical_h5_quantity_amount_physical_units_certified":False,
        "historical_h5_stock_price_adjustment_factors_certified":False,
        "pre2011_h5_to_new_private_parquet_authorized":False,
        "missing_or_unscanned_external_parquet_directories_excluded":True,
        "original_market_files_modified":False,
        "private_active_pointers_read_or_modified":False,
        "production_query_route_modified":False,
        "no_original_ohlcva_or_stock_codes_in_safe":True,
    }
    with dest.open("x",encoding="utf-8") as stream:
        json.dump(summary,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-all-original-day-sources",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=inventory(a.source_root,a.out)
        print("SAFE 1990-2010 source day inventory:",a.out)
        print("Historical eligible H5 candidate rows:",
              result["original_h5"]["pre2011_candidate_h5_stockday_rows"])
        print("Earliest historical H5 day:",
              result["original_h5"]["earliest_pre2011_candidate_h5_date"])
        print("Purchased all-filename footer status:",
              result["original_purchased_parquet"][
                  "pre2011_original_purchased_coverage_status"])
        print("Original H5/PQ market files and production paths changed: NO")
    except (ValueError,TypeError,KeyError,OSError,OverflowError,
            ImportError,ModuleNotFoundError):
        p.error("1990-2010 original day coverage inventory refused; no source writes")


if __name__=="__main__":
    main()
