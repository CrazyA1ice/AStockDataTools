#!/usr/bin/env python3
"""Historical H5 DAY coverage inventory, fully read-only, NOT a gap merge.

Dates are user-selected, not artificially limited to minute-index history.
Each H5 dataset is probed with binary searches on its ordered native
datetime key; only metadata/counts are emitted, never OHLCVA or full bars.
Presence of an annual purchased Parquet file is NOT proof of row coverage:
this mode deliberately does not claim H5-only net gaps or fill anything.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter
from datetime import date,timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load():
    spec=importlib.util.spec_from_file_location(
        "historical_daily_coverage_source_core",
        HERE/"reconcile-local-a-share-h5-parquet.py")
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


CORE=load()
MARKETS=("sh","sz","bj")


def bounds(first,last):
    first=date.fromisoformat(first) if isinstance(first,str) else first
    last=date.fromisoformat(last) if isinstance(last,str) else last
    if not isinstance(first,date) or not isinstance(last,date) or first>last:
        raise ValueError("Historical daily dates require YYYY-MM-DD start <= end")
    return first,last


def plan(root,first,last):
    import h5py
    first,last=bounds(first,last)
    root=Path(root)
    market_files=[root/"HikyuuData"/(m+"_day.h5") for m in MARKETS]
    if (root.is_symlink() or not root.is_dir() or
            not (root/"AllCycleAStockData").is_dir() or
            not (root/"HikyuuData").is_dir()):
        raise ValueError("Original H5 and purchased Parquet source directories required")
    if not any(p.is_file() for p in market_files):
        raise ValueError("No historical H5 daily data files found")
    for path in market_files:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("Unsafe H5 historical daily source")
    result=[]
    for year in range(first.year,last.year+1):
        a=max(first,date(year,1,1))
        b=min(last,date(year,12,31))
        result.append({
            "first":a.isoformat(),"last":b.isoformat(),
            "mode":"historical_h5_day_coverage_only",
            "existing_index":None,
            "eligible_weekdays":1,
            "year":year,
        })
    return result


def detect_h5_day_bounds(root):
    """Discover actual A-share-candidate H5 DAY timestamps, not guessed 1990."""
    import h5py
    root=Path(root)
    # Validation checks source directories, H5 market files and symlinks.
    plan(root,date(1990,1,1),date(1990,1,1))
    earliest=None
    latest=None
    sources=0
    for market in MARKETS:
        path=root/"HikyuuData"/(market+"_day.h5")
        if not path.is_file():
            continue
        with h5py.File(path,"r") as h5:
            group=h5.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("H5 day data group missing")
            for raw_symbol in group:
                symbol=CORE.symbol_id(raw_symbol)
                if symbol is None or not symbol.startswith(market.upper()):
                    continue
                ds=group[raw_symbol]
                if not isinstance(ds,h5py.Dataset) or not len(ds) or (
                        "datetime" not in (ds.dtype.names or ())):
                    continue
                a=int(ds[0]["datetime"])//10000
                b=int(ds[-1]["datetime"])//10000
                try:
                    da=date.fromisoformat(f"{a:08d}"[:4]+"-"+f"{a:08d}"[4:6]+
                                        "-"+f"{a:08d}"[6:8])
                    db=date.fromisoformat(f"{b:08d}"[:4]+"-"+f"{b:08d}"[4:6]+
                                        "-"+f"{b:08d}"[6:8])
                except ValueError:
                    continue
                if not CORE.is_a_share_candidate(symbol,da.year):
                    continue
                earliest=da if earliest is None else min(earliest,da)
                latest=db if latest is None else max(latest,db)
                sources+=1
    if earliest is None or latest is None:
        raise ValueError("No valid A-share-candidate H5 daily dates found")
    return {"h5_earliest_candidate_day":earliest.isoformat(),
            "h5_latest_candidate_day":latest.isoformat(),
            "h5_candidate_series_examined":sources,
            "historical_day_gap_not_certified":True,
            "source_date_bounds_from_actual_H5":True}


def daily_source_snapshot(root,year=None):
    """Fast path/size/mtime/inode drift detector; NOT full content SHA."""
    root=Path(root)
    paths=[root/"HikyuuData"/(market+"_day.h5") for market in MARKETS]
    if year is not None:
        paths+=CORE.year_files(root,"day",year)
    observed={}
    for path in paths:
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ValueError("Unsafe daily source file")
            stat=path.stat()
            observed[str(path.relative_to(root))]=[
                stat.st_size,stat.st_mtime_ns,stat.st_ino]
    return hashlib.sha256(json.dumps(
        observed,sort_keys=True,separators=(",",":")).encode("utf-8")
        ).hexdigest()


def inspect_year(root,first,last):
    import h5py
    first,last=bounds(first,last)
    if first.year!=last.year:
        raise ValueError("Historical day inventory year shard cannot cross years")
    root=Path(root)
    # Validate the actual files; no static 1990 cutoff is assumed.
    plan(root,first,last)
    before=daily_source_snapshot(root,first.year)
    lower=int(first.strftime("%Y%m%d"))*10000
    # End-of-day exclusive bound without date+1 overflow at year 9999.
    upper=int(last.strftime("%Y%m%d"))*10000+2400
    source_markets=[]
    rows=0
    candidate_stockdays=0
    candidates=0
    excluded=Counter()
    for market in MARKETS:
        path=root/"HikyuuData"/(market+"_day.h5")
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError("Original H5 day file must not be a symlink")
        source_markets.append(market)
        with h5py.File(path,"r") as h5:
            group=h5.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("H5 day source missing data group")
            for raw_symbol in group:
                if not isinstance(raw_symbol,str):
                    continue
                symbol=CORE.symbol_id(raw_symbol)
                if symbol is None or not symbol.startswith(market.upper()):
                    continue
                if not CORE.is_a_share_candidate(symbol,first.year):
                    excluded["non_candidate_security_code"]+=1
                    continue
                dset=group[raw_symbol]
                if (not isinstance(dset,h5py.Dataset) or
                        "datetime" not in (dset.dtype.names or ())):
                    excluded["invalid_native_h5_schema"]+=1
                    continue
                lo,hi=CORE.h5_key_slice(dset,lower,upper)
                if lo<hi:
                    rows+=hi-lo
                    candidate_stockdays+=hi-lo
                    candidates+=1
    year=first.year
    parquet_files=CORE.year_files(root,"day",year)
    if daily_source_snapshot(root,year)!=before:
        raise RuntimeError("Original daily H5/Parquet source metadata changed during inventory")
    return {
        "year":year,
        "from_day":first.isoformat(),
        "through_day":last.isoformat(),
        "h5_a_share_candidate_daily_rows":rows,
        "h5_stockdays_with_native_day_rows":candidate_stockdays,
        "h5_candidate_symbols_present":candidates,
        "h5_markets_seen":source_markets,
        "purchased_day_parquet_year_file_count":len(parquet_files),
        "purchased_annual_files_prove_day_coverage":False,
        "h5_only_net_day_key_count":None,
        "daily_exact_parquet_key_diff_completed":False,
        "source_metadata_unchanged_during_read":True,
        "source_fingerprint_is_content_sha":False,
        "quarantined_h5_datasets_by_reason":dict(sorted(excluded.items())),
        "market_parquet_or_h5_written":False,
        "status":"H5_DAILY_HISTORICAL_COVERAGE_ONLY_NOT_GAP_CERTIFIED",
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--from-day",required=True)
    p.add_argument("--through-day",required=True)
    args=p.parse_args(argv)
    windows=plan(args.root,args.from_day,args.through_day)
    totals=Counter()
    for shard in windows:
        result=inspect_year(args.root,shard["first"],shard["last"])
        totals["h5_a_share_candidate_daily_rows"]+=result["h5_a_share_candidate_daily_rows"]
        print(json.dumps(result,ensure_ascii=False,sort_keys=True),flush=True)
    print(json.dumps({"status":"historical_h5_day_inventory_only",
                      "years":len(windows),
                      "h5_a_share_candidate_daily_rows":totals["h5_a_share_candidate_daily_rows"],
                      "h5_only_net_gap_not_yet_certified":True,
                      "market_files_written":False},ensure_ascii=False))


if __name__=="__main__":
    main()
