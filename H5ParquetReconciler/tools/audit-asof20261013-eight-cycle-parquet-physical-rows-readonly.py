#!/usr/bin/env python3
"""Exact PHYSICAL row census for the 2026-10-13 eight-cycle Parquet dataset.

Reads only Parquet footers / rowgroup timestamp statistics; never OHLCVA
values, raw security identifiers, source-market H5, or a new index. Reuses the
immutable DATASET manifest that has already passed real eight-dataset opening.
Each original paid Parquet is identified by size/mtime (not content SHA).
Each git-ignored H5 / private purchased-first physical Parquet is SHA checked.
Rows are counted by period and source class, NOT certified as unique A-share
bars or as complete expected exchange trading-date and session slot keys.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
MOD=HERE.parent
END="2026-10-13"
VERSION="asof_20261013_eight_cycle_physical_arrow_parquet_footer_row_census_v1"
SOURCE_NAMES={
    "purchased_original",
    "modern_16yr_purchased_first_day",
    "h5_only_verified_complete_stockday",
    "h5_5min_derived_unverified_units",
    "historical_1990_2010_h5_uncertified_candidate",
}

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,HERE/path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

D=load("exact_source_asof_20261013_eight_arrow_physical_dataset",
       "build-asof20261013-unified-eight-cycle-parquet-dataset.py")

def physical_file_stats(path):
    """Read exact physical footer count and all row-group timestamp envelopes."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    with pq.ParquetFile(path,memory_map=False) as pf:
        header=pf.schema_arrow
        if (any(k not in header.names for k in D.RAW_COLS)
                or header.field("ts").type!=pa.int64()
                or pf.metadata.num_rows<1 or pf.metadata.num_row_groups<1):
            raise ValueError("Invalid existing Parquet physical footer/schema")
        count=0
        lo,hi=None,None
        for i in range(pf.metadata.num_row_groups):
            group=pf.metadata.row_group(i)
            n=group.num_rows
            stats=group.column(0).statistics
            if (n<0 or stats is None or not stats.has_min_max
                    or type(stats.min) is not int
                    or type(stats.max) is not int
                    or stats.min>stats.max):
                raise ValueError("Missing exact ts bounds in original/private Parquet rowgroup")
            count+=n
            lo=stats.min if lo is None else min(lo,stats.min)
            hi=stats.max if hi is None else max(hi,stats.max)
        if count!=pf.metadata.num_rows or lo is None:
            raise ValueError("Source Parquet footer rowgroup count mismatch")
        return count,lo,hi,pf.metadata.num_row_groups

def audit(payload,root,*,periods=None):
    """One metadata-only audit of the *actual* manifest file graph."""
    periods=tuple(D.PERIODS if periods is None else periods)
    if (not periods or len(set(periods))!=len(periods)
            or any(p not in D.PERIODS for p in periods)
            or payload.get("format")!=D.MANIFEST_VERSION
            or payload.get("asof_inclusive")!=END
            or payload.get("strict_cutoff_next_day")!="2026-10-14"
            or payload.get("no_purchased_parquet_copy") is not True
            or payload.get("ready_for_production_query") is not False):
        raise ValueError("Invalid bounded research-only physical dataset version")
    upper=datetime(2026,10,14,tzinfo=timezone(timedelta(hours=8)))
    upper_ms=int(upper.timestamp()*1000)
    history_start=int(datetime(2011,1,1,tzinfo=timezone(
        timedelta(hours=8))).timestamp()*1000)
    seen=set()
    totals={}
    for period in periods:
        entries=payload["period_physical_files"][period]
        if type(entries) is not list or not entries:
            raise ValueError("Missing physical Parquet period")
        by_source=Counter()
        files_by_source=Counter()
        rows=0
        groups=0
        lo,hi=None,None
        for entry in entries:
            kind=entry["source_class"]
            if (kind not in SOURCE_NAMES or
                    kind=="historical_1990_2010_h5_uncertified_candidate"):
                raise ValueError("Unregistered research-only source in standard period")
            pair=(entry["root_kind"],entry["relative_file"])
            if pair in seen:
                raise ValueError("Duplicate physical Parquet input fragment across periods")
            seen.add(pair)
            file=D.checked(entry["root_kind"],entry["relative_file"],
                           Path(root).resolve(),D.MODULE,
                           entry.get("content_sha256"),
                           purchased_stat=entry.get("source_stat"))
            count,first,last,rg=physical_file_stats(file)
            if last>=upper_ms:
                raise ValueError("Physical K-line rowgroup extends beyond 2026-10-13 cutoff")
            if first<history_start:
                raise ValueError("Historical/cross-year stockday appears in standard dataset tier")
            if entry.get("source_rows",count)!=count:
                raise ValueError("Fragment physical row count disagrees with pinned receipt")
            by_source[kind]+=count
            files_by_source[kind]+=1
            groups+=rg
            rows+=count
            lo=first if lo is None else min(lo,first)
            hi=last if hi is None else max(hi,last)
        if period=="day":
            if (rows!=D.MODERN_ROWS
                    or by_source!={"modern_16yr_purchased_first_day":D.MODERN_ROWS}):
                raise ValueError("Materialized 16-year purchased+H5 day row conservation failed")
        else:
            paid=by_source.get("purchased_original",0)
            expected=payload["period_purchased_footer_rows_except_day"][period]
            if type(expected) is not int or expected!=paid:
                raise ValueError("Original purchased source footer row conservation failed")
        totals[period]={
            "physical_files":len(entries),"row_groups":groups,
            "physical_rows":rows,"rows_by_registered_source":dict(sorted(by_source.items())),
            "files_by_registered_source":dict(sorted(files_by_source.items())),
            "source_raw_earliest_timestamp_ms":lo,
            "source_raw_latest_timestamp_ms":hi,
            "physical_rows_not_exact_unique_stockday_or_bar_key_count":True,
        }
    historic=payload["historical_1990_2010_day"]["historical_files"]
    hist_count=0
    if periods==D.PERIODS:
        if type(historic) is not list or len(historic)!=21:
            raise ValueError("Previously verified independent 21-year research layer absent")
        for entry in historic:
            if (entry.get("source_class")!=
                    "historical_1990_2010_h5_uncertified_candidate"):
                raise ValueError("Historical tier source mislabeled")
            file=D.checked(entry["root_kind"],entry["relative_file"],
                           Path(root).resolve(),D.MODULE,
                           entry["content_sha256"])
            count,first,last,_=physical_file_stats(file)
            if last>=history_start or count!=entry["source_rows"]:
                raise ValueError("Uncertified historical H5 physical tier crossed 2011")
            hist_count+=count
        if hist_count!=3682327:
            raise ValueError("Historical 21-year raw candidate physical row conservation failed")
        high=sum(totals[p]["rows_by_registered_source"].get(
            "h5_5min_derived_unverified_units",0)
            for p in ("15min","30min","60min"))
        if high!=621348:
            raise ValueError("Four-day derived H5 high-cycle total is not 621348")
        if (sum(totals[p]["files_by_registered_source"].get(
                "h5_only_verified_complete_stockday",0)
                for p in ("1min","5min"))!=8):
            raise ValueError("Missing eight existing H5-only minute gap files")
    return {
        "status":VERSION,
        "dataset_coverage_end_inclusive":END,
        "period_count":len(totals),
        "periods":totals,
        "physical_source_rows_all_requested_periods":sum(
            x["physical_rows"] for x in totals.values()),
        "separate_historical_1990_2010_unverified_rows":hist_count,
        "historical_source_not_merged_into_standard_day":True,
        "source_rowgroup_timestamp_bounds_all_before_2026_10_14":True,
        "source_rows_counted_from_actual_Parquet_footers":True,
        "original_purchased_sources_checked_by_stat_not_full_content_SHA":True,
        "private_parquet_bytes_rechecked_by_content_SHA":True,
        "exact_stockday_time_key_coverage_certified":False,
        "exchange_trading_calendar_certified":False,
        "vendor_physical_units_or_adjustments_certified":False,
        "new_market_or_source_files_written":False,
        "ready_for_production_query":False,
    }

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",required=True,type=Path)
    parser.add_argument("--manifest",required=True,type=Path)
    parser.add_argument("--dataset-sha256",required=True)
    a=parser.parse_args(argv)
    try:
        payload,version=D.load_manifest(
            a.manifest,a.root,expected_sha=a.dataset_sha256,
            verify_sources=False)
        receipt=audit(payload,a.root)
        receipt["dataset_sha256"]=version
    except (KeyError,TypeError,ValueError,OSError,ImportError) as exc:
        parser.error("Physical eight-cycle metadata census NOT ACCEPTED: "+
                     type(exc).__name__+": "+str(exc))
    print("EIGHT_CYCLE_PHYSICAL_PARQUET_FOOTER_CENSUS="+json.dumps(
        receipt,ensure_ascii=False,sort_keys=True,
        separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
