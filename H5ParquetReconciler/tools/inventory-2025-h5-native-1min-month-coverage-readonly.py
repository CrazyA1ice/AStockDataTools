#!/usr/bin/env python3
"""2025 monthly Hikyuu H5 native 1min coverage by exchange (source-only).

This scans NO purchased Parquet and NO OHLCVA. Only reads per-stock native
datetime first/last and bounded binary-search probes from each H5 dataset.
Counts source rows, NOT certified stockdays, valid exchange bars, or exact
purchased-minus-H5 gaps. Prior 2025 Jan/Feb exact-key audit found ZERO
eligible native 1min rows; global SH first record in 2021 alone did not
establish that SH A-share minute data existed in Jan/Feb 2025.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MARKETS=("sh","sz","bj")
YEAR=2025
MAX_DATASETS=12000
MAX_PROBES=3500000


def core():
    spec=importlib.util.spec_from_file_location(
        "inventory_2025_h5_1min_bounded_existing_core",
        HERE/"reconcile-local-a-share-h5-parquet.py")
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


CORE=core()


def native_month_keys():
    # Each key is the first minute of the following calendar month in
    # Hikyuu native YYYYMMDDHHMM form.
    return [int(date(YEAR if m<12 else YEAR+1,
                     m+1 if m<12 else 1,1).strftime("%Y%m%d"))*10000
            for m in range(1,13)]


def market_sources(root):
    folder=root/"HikyuuData"
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Original H5 source directory missing or unsafe")
    paths={}
    for market in MARKETS:
        path=folder/(market+"_1min.h5")
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing/unsafe original H5 1min market: "+market)
        paths[market]=path
    return paths


def snapshot(paths):
    return {name:(p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ino)
            for name,p in paths.items()}


def inspect(root,*,max_datasets=MAX_DATASETS,max_probes=MAX_PROBES):
    import h5py
    if (type(max_datasets) is not int or not 1<=max_datasets<=MAX_DATASETS
            or type(max_probes) is not int or not 1<=max_probes<=MAX_PROBES):
        raise ValueError("Require bounded positive H5 dataset/probe budgets")
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid original market root")
    paths=market_sources(root)
    before=snapshot(paths)
    month_ends=native_month_keys()
    start=YEAR*100000000
    end=(YEAR+1)*100000000
    outputs={}
    seen_datasets=0
    probes=0

    def stamp(datetime_only,index):
        nonlocal probes
        probes+=1
        if probes>max_probes:
            raise ValueError("H5 datetime-only bounded probe budget exceeded")
        return int(datetime_only[index])

    def lower(ds,target,lo,hi):
        while lo<hi:
            mid=(lo+hi)//2
            if stamp(ds,mid)<target:
                lo=mid+1
            else:
                hi=mid
        return lo

    for market,path in paths.items():
        months={f"{YEAR}-{m:02d}":{"native_rows":0,
                                  "datasets_with_month_rows":0}
                for m in range(1,13)}
        checked=with_records=source_with_2025=rows=0
        first2025=last2025=None
        with h5py.File(path,"r") as fp:
            group=fp.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("Missing source H5 native data group: "+market)
            for symbol in group:
                if (not isinstance(symbol,str) or
                        not re.fullmatch(market.upper()+r"\d{6}",symbol) or
                        not CORE.is_a_share_candidate(symbol,YEAR)):
                    continue
                checked+=1
                seen_datasets+=1
                if seen_datasets>max_datasets:
                    raise ValueError("Excessive original H5 native A-share datasets")
                ds=group[symbol]
                if (not isinstance(ds,h5py.Dataset) or
                        "datetime" not in (ds.dtype.names or ())):
                    raise ValueError("Invalid 2025 native H5 A-share dataset")
                if not len(ds):
                    continue
                with_records+=1
                # H5 compound-field selector reads native datetime ONLY,
                # not full scalar records containing licensed OHLCVA fields.
                dt=ds.fields("datetime")
                left=stamp(dt,0)
                right=stamp(dt,len(ds)-1)
                if left>right or left<190000000000:
                    raise ValueError("Unsorted or malformed original H5 source endpoints")
                if right<start or left>=end:
                    continue
                lo=0 if left>=start else lower(dt,start,0,len(ds))
                hi=len(ds) if right<end else lower(dt,end,lo,len(ds))
                if not 0<=lo<=hi<=len(ds):
                    raise ValueError("Bad original H5 2025 date slice")
                if lo==hi:
                    continue
                source_with_2025+=1
                rows+=hi-lo
                first_in_year=stamp(dt,lo)
                last_in_year=stamp(dt,hi-1)
                if not start<=first_in_year<=last_in_year<end:
                    raise ValueError("Invalid bounded H5 native source 2025 edges")
                first2025=(first_in_year if first2025 is None else
                           min(first2025,first_in_year))
                last2025=(last_in_year if last2025 is None else
                          max(last2025,last_in_year))
                cursor=lo
                for idx,cutoff in enumerate(month_ends):
                    if cutoff<=first_in_year:
                        upper=lo
                    elif cutoff>last_in_year:
                        upper=hi
                    else:
                        upper=lower(dt,cutoff,cursor,hi)
                    n=upper-cursor
                    if n<0:
                        raise ValueError("Nonmonotone native month boundary")
                    label=f"{YEAR}-{idx+1:02d}"
                    months[label]["native_rows"]+=n
                    months[label]["datasets_with_month_rows"]+=int(n>0)
                    cursor=upper
                if cursor!=hi:
                    raise ValueError("H5 monthly source row conservation failed")
        if sum(item["native_rows"] for item in months.values())!=rows:
            raise ValueError("H5 annual native source row conservation failed")
        outputs[market]={
            "source_file_present":True,
            "candidate_a_share_datasets_examined":checked,
            "candidate_datasets_with_any_native_rows":with_records,
            "candidate_datasets_with_2025_rows":source_with_2025,
            "total_2025_native_rows":rows,
            "first_candidate_2025_native_stamp":first2025,
            "last_candidate_2025_native_stamp":last2025,
            "months":months,
        }

    if snapshot(paths)!=before:
        raise RuntimeError("Original H5 1min files changed during coverage inventory")
    combined={}
    for month in (f"{YEAR}-{i:02d}" for i in range(1,13)):
        combined[month]={
            "native_rows":sum(outputs[m]["months"][month]["native_rows"]
                              for m in MARKETS),
            "dataset_month_observations":sum(
                outputs[m]["months"][month]["datasets_with_month_rows"]
                for m in MARKETS),
            "markets_with_rows":[m for m in MARKETS
                                 if outputs[m]["months"][month]["native_rows"]>0],
        }
    return {
        "status":"2025_original_h5_native_one_minute_monthly_timestamp_coverage_readonly",
        "year":YEAR,
        "markets":outputs,
        "months":combined,
        "source_h5_files_checked":len(paths),
        "candidate_a_share_datasets_checked":seen_datasets,
        "source_native_datetime_scalar_probes":probes,
        "source_market_stat_unchanged":True,
        "source_row_count_sum_conserved":True,
        "no_purchased_parquet_opened":True,
        "no_native_h5_ohlcva_decoded":True,
        "source_security_ids_or_market_values_exported":False,
        "source_time_sorted_assumption_not_full_history_certified":True,
        "source_2025_full_session_completeness_certified":False,
        "independent_exchange_calendar_certified":False,
        "new_market_files_written":False,
        "ready_for_production_query":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",required=True,type=Path)
    args=p.parse_args(argv)
    obj=inspect(args.root)
    for month,stats in sorted(obj["months"].items()):
        print("H5_2025_1MIN_MONTH="+json.dumps({
            "month":month,
            "markets_with_rows":stats["markets_with_rows"],
            "native_rows_by_market":{
                market:obj["markets"][market]["months"][month]["native_rows"]
                for market in MARKETS},
            "candidate_datasets_with_month_rows_by_market":{
                market:obj["markets"][market]["months"][month]["datasets_with_month_rows"]
                for market in MARKETS},
        },sort_keys=True,separators=(",",":")),flush=True)
    print("H5_2025_1MIN_MONTH_SUMMARY="+json.dumps({
        k:obj[k] for k in (
            "status","year","source_h5_files_checked",
            "candidate_a_share_datasets_checked","source_native_datetime_scalar_probes",
            "source_market_stat_unchanged","source_row_count_sum_conserved",
            "no_purchased_parquet_opened","no_native_h5_ohlcva_decoded",
            "source_security_ids_or_market_values_exported",
            "source_time_sorted_assumption_not_full_history_certified",
            "source_2025_full_session_completeness_certified",
            "independent_exchange_calendar_certified",
            "new_market_files_written","ready_for_production_query")},
        sort_keys=True,separators=(",",":")),flush=True)


if __name__=="__main__":
    main()
