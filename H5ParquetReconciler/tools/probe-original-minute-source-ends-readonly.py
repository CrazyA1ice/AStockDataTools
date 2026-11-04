#!/usr/bin/env python3
"""Read ONLY source coverage end points for purchased minute Parquet and Hikyuu
1min/5min H5. No full market row scan, no index, no price/code export.

For each H5 security table read only its FIRST and LAST native datetime.
MAX(last-record) is valid as a market coverage end only if native stock tables
are time-sorted; it does not certify all bars have been ingested.
For purchased Parquet read ONLY rowgroup ts statistics; missing statistics
are explicitly reported and NEVER treated as proof of no later data.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
import traceback
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
FMT="AStockDataTools 1min/5min purchased Parquet and H5 coverage end-only v1"
PERIODS=("1min","5min")
MARKETS=("sh","sz","bj")

def load_core():
    spec=importlib.util.spec_from_file_location(
        "minute_source_coverage_core",HERE/"reconcile-local-a-share-h5-parquet.py")
    core=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    return core

CORE=load_core()

def h5_bounds(root,period,market):
    import h5py
    src=root/"HikyuuData"/f"{market}_{period}.h5"
    if src.is_symlink() or (src.exists() and not src.is_file()):
        raise ValueError("Unsafe original Hikyuu H5 source")
    if not src.is_file():
        return {"source_file_present":False,"native_tables_checked":0,
                "native_tables_with_rows":0,"native_tables_bad_order":0,
                "max_of_stock_last_native_stamps":None,
                "min_of_stock_first_native_stamps":None}
    tables=nonempty=bad=0
    latest=first=None
    with h5py.File(src,"r") as fp:
        g=fp.get("data")
        if not isinstance(g,h5py.Group):
            raise ValueError("Original Hikyuu minute H5 missing data group")
        for symbol in g:
            if not re.fullmatch(market.upper()+r"\d{6}",symbol):
                continue
            ds=g[symbol]
            if not isinstance(ds,h5py.Dataset):
                raise ValueError("Native stock member not a table")
            if "datetime" not in (ds.dtype.names or ()):
                raise ValueError("Native H5 stock dataset has no datetime")
            tables+=1
            if not len(ds):
                continue
            nonempty+=1
            stamp0=int(ds[0]["datetime"])
            stamp1=int(ds[-1]["datetime"])
            if stamp1<stamp0:
                bad+=1
            first=stamp0 if first is None else min(first,stamp0)
            latest=stamp1 if latest is None else max(latest,stamp1)
    return {
        "source_file_present":True,
        "native_tables_checked":tables,
        "native_tables_with_rows":nonempty,
        "native_tables_bad_first_last_order":bad,
        "max_of_stock_last_native_stamps":latest,
        "min_of_stock_first_native_stamps":first,
        "last_native_calendar_day":(str(latest)[:8] if latest is not None else None),
        "coverage_cutoff_proven":False,
    }

def purchased_footer(root,period,year):
    import pyarrow.parquet as pq
    src=CORE.year_files(root,period,year)
    if not src:
        return {"year":year,"source_files":0,"total_rowgroups":0,
                "rowgroups_without_ts_statistics":0,"max_rowgroup_ts_ms":None,
                "max_rowgroup_ts_local":None,"source_coverage_certified":False}
    groups=unknown=0
    latest=None
    for file in src:
        if not file.is_file() or file.is_symlink():
            raise ValueError("Purchased minute Parquet source file unsafe")
        with pq.ParquetFile(file,memory_map=False,pre_buffer=False) as pf:
            idx=pf.schema_arrow.get_field_index("ts")
            if idx<0:
                raise ValueError("Purchased minute footer lacks ts column")
            for rg in range(pf.metadata.num_row_groups):
                groups+=1
                stats=pf.metadata.row_group(rg).column(idx).statistics
                if stats is None or not stats.has_min_max:
                    unknown+=1
                    continue
                maxi=stats.max
                if type(maxi) not in (int,) or maxi<0:
                    unknown+=1
                    continue
                latest=maxi if latest is None else max(latest,maxi)
    if latest is None:
        label=None
    else:
        label=datetime.fromtimestamp(latest/1000,
                                     tz=CORE.UTC8).isoformat()
    return {"year":year,"source_files":len(src),
            "total_rowgroups":groups,
            "rowgroups_without_ts_statistics":unknown,
            "max_rowgroup_ts_ms":latest,
            "max_rowgroup_ts_local":label,
            "source_coverage_certified":False,
            "rowgroup_bounds_cover_all_groups":unknown==0}

def inspect(root,years):
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Invalid original market root")
    if not years or any(type(y) is not int or y<2025 or y>2026 for y in years):
        raise ValueError("Only purchased minute 2025-2026 year footer checks")
    result={}
    for period in PERIODS:
        h5={market:h5_bounds(root,period,market) for market in MARKETS}
        purchased={str(y):purchased_footer(root,period,y) for y in years}
        latest=max((x["max_of_stock_last_native_stamps"]
                    for x in h5.values()
                    if x["max_of_stock_last_native_stamps"] is not None),
                   default=None)
        result[period]={
            "h5_by_market":h5,
            "purchased_parquet_year_footers":purchased,
            "last_native_day_across_markets":(
                str(latest)[:8] if latest is not None else None),
            "source_last_day_evidence_is_not_a_full_exchange_calendar":True,
        }
        print("Minute source end-only read:",period,
              "H5 native max(last stock bar):",latest,
              "purchased max timestamps by year:",
              {k:v["max_rowgroup_ts_local"] for k,v in purchased.items()},
              flush=True)
    return {
        "format":FMT,
        "status":"original_minute_market_coverage_end_only_readonly",
        "periods":result,
        "source_h5_last_rows_only":True,
        "source_purchased_parquet_footer_only":True,
        "source_stock_identifiers_or_ohlcva_exported":False,
        "original_market_files_modified":False,
        "production_pointer_modified":False,
        "complete_trading_calendar_or_intraday_coverage_verified":False,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--years",type=int,nargs="+",default=[2025,2026])
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--inspect-original-minute-source-end-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        safe=Path(a.out)
        if (REPORTS.is_symlink() or safe.is_symlink() or safe.exists()
                or safe.suffix!=".json"
                or safe.resolve().parent!=REPORTS.resolve()):
            raise ValueError("Only fresh small aggregate-only SAFE in reports")
        report=inspect(a.root,a.years)
        with safe.open("x",encoding="utf-8",newline="\n") as f:
            f.write(json.dumps(report,indent=2,sort_keys=True)+"\n")
        print("PASS: only original 1min/5min source terminal timestamps inspected")
        print("Original vendor market files untouched. SAFE:",safe)
    except Exception as error:
        last=traceback.extract_tb(error.__traceback__)[-1]
        p.error("Source coverage end-only probe failed ["+type(error).__name__+
                "/"+last.name+":"+str(last.lineno)+
                "]; original purchased Parquet/H5 untouched")

if __name__=="__main__":
    main()
