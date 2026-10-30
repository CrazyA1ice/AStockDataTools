#!/usr/bin/env python3
"""Bounded original H5 vs purchased Parquet STOCK-DAY availability audit.

This is a *selected-stock* read-only candidate survey, NOT proof that a whole
market date is absent in purchased Parquet or fully present in Hikyuu H5.
No H5 candidate is staged/promoted or used to write a Parquet/H5 database.
The original source files and all active pointers remain untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from collections import Counter
from datetime import date,timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
FORMAT="AStockDataTools bounded selected-stock post-snapshot H5-PQ daily key audit v1"


def import_local(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


DATE=import_local("post_snapshot_audit_new_date_parent",
                  "append-private-purchased-day-date-delta.py")
H5=import_local("post_snapshot_audit_h5_native_contract",
                "probe-hikyuu-native-day-h5-readonly.py")
READER=DATE.READER


def h5_selected_keys(root,symbols,start,end):
    """Check the 2026 day H5Record layout and a bounded date slice per stock."""
    import h5py

    paths=H5._market_sources(root,symbols)
    before={market:H5._file_state(p) for market,p in paths.items()}
    dates={}
    for venue,path in sorted(paths.items()):
        with h5py.File(path,"r") as original:
            group=original.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("Original daily H5 missing /data group")
            for symbol in symbols:
                if symbol[:2].lower()!=venue:
                    continue
                ds=group.get(symbol)
                if not isinstance(ds,h5py.Dataset):
                    raise ValueError("Selected original H5 stock dataset not found")
                layout=H5._schema(ds)
                if (not layout["one_dimensional_compound_dataset"]
                        or not layout["expected_field_set"]
                        or not layout["integer_width_sign_compatible_with_h5record"]):
                    # Read by verified field NAME; differing field order is
                    # not evidence that selected stock-day keys are absent.
                    # This is NOT certification of a native Hikyuu driver.
                    raise ValueError("Original H5 stock dataset field contract invalid")
                lower=int(start.strftime("%Y%m%d"))*10000
                upper=int((end+timedelta(days=1)).strftime("%Y%m%d"))*10000
                left,right=H5.core.h5_key_slice(ds,lower,upper)
                if not 0<=left<=right<=len(ds) or right-left>31:
                    raise ValueError("H5 date selection exceeds bounded per-stock budget")
                selected=ds[left:right]
                found=[]
                old_key=None
                for record in selected:
                    rawday=int(record["datetime"])
                    if (rawday<lower or rawday>=upper or rawday%10000!=0
                            or (old_key is not None and rawday<=old_key)):
                        raise ValueError("Unsorted/duplicate/invalid selected H5 day key")
                    old_key=rawday
                    try:
                        day=date.fromisoformat(str(rawday//10000))
                    except ValueError:
                        # YYYYMMDD is not ISO; parse explicitly.
                        from datetime import datetime
                        try:
                            day=datetime.strptime(str(rawday//10000),"%Y%m%d").date()
                        except ValueError:
                            raise ValueError("Invalid original H5 calendar day") from None
                    if not start<=day<=end:
                        raise ValueError("Selected H5 day escaped requested range")
                    prices=[int(record[f]) for f in (
                        "openPrice","highPrice","lowPrice","closePrice")]
                    amount=int(record["transAmount"])
                    volume=int(record["transCount"])
                    if (min(prices)<=0 or amount<0 or volume<0
                            or prices[1]<max(prices[0],prices[2],prices[3])
                            or prices[2]>min(prices[0],prices[1],prices[3])):
                        raise ValueError("H5 native raw integer OHLCVA geometry invalid")
                    found.append(day.isoformat())
                dates[symbol]=set(found)
                if len(dates[symbol])!=len(found):
                    raise ValueError("Duplicate daily key in original H5 stock series")
    after={market:H5._file_state(p) for market,p in paths.items()}
    if before!=after:
        raise ValueError("Original H5 file stat changed during selected-key audit")
    return dates,before


def purchased_selected_keys(root,symbols,first,last):
    """Independent cold purchased scan; do not use earlier empty-date SAFE as proof."""
    a=date.fromisoformat(first)
    b=date.fromisoformat(last)
    stat=DATE.PURCHASED.private_cache.source_signature(
        root,"day",a,b,DATE.PURCHASED.core)
    found={}
    for sym in symbols:
        result=DATE.PURCHASED.query_bars(
            root,sym,"day",first,last,
            max_candidate_rows=300000,max_result_bars=40,local_cache=False)
        rows=DATE.normalize_one(result,sym,first,last)
        days=[r["trading_date"] for r in rows]
        if len(days)!=len(set(days)):
            raise ValueError("Duplicate purchased stock-day")
        found[sym]=set(days)
    after=DATE.PURCHASED.private_cache.source_signature(
        root,"day",a,b,DATE.PURCHASED.core)
    if stat!=after:
        raise ValueError("Purchased source inventory changed during audit")
    return found,stat


def fingerprint(stats):
    rows=sorted((venue,s["size_bytes"],s["mtime_ns"])
                for venue,s in stats.items())
    return hashlib.sha256(json.dumps(rows,separators=(",",":")).encode()).hexdigest()


def audit(root,version_sha,symbols,first,last,out):
    # This audit does NOT create any private Parquet data: only a sanitized SAFE.
    safe=READER.direct_report(out,for_output=True)
    base,version_file_sha,start,end=DATE.precheck(
        version_sha,symbols,first,last)
    h5_keys,before=h5_selected_keys(root,symbols,start,end)
    purchased_keys,pq_signature=purchased_selected_keys(
        root,symbols,first,last)
    day_rows=[]
    cursor=start
    while cursor<=end:
        day=cursor.isoformat()
        both=sum(day in h5_keys[s] and day in purchased_keys[s] for s in symbols)
        h5only=sum(day in h5_keys[s] and day not in purchased_keys[s]
                   for s in symbols)
        pqonly=sum(day in purchased_keys[s] and day not in h5_keys[s]
                   for s in symbols)
        none=sum(day not in h5_keys[s] and day not in purchased_keys[s]
                 for s in symbols)
        if both+h5only+pqonly+none!=len(symbols):
            raise ValueError("Source stock-date accounting mismatch")
        day_rows.append({
            "day":day,"selected_stocks_both_sources":both,
            "selected_stocks_h5_only_candidate":h5only,
            "selected_stocks_purchased_only":pqonly,
            "selected_stocks_neither_source":none,
            "selected_stock_count":len(symbols),
        })
        cursor+=timedelta(days=1)
    first_h5=Counter(d for dates in h5_keys.values() for d in dates)
    first_pq=Counter(d for dates in purchased_keys.values() for d in dates)
    total_h5=sum(first_h5.values())
    total_pq=sum(first_pq.values())
    candidate=sum(r["selected_stocks_h5_only_candidate"] for r in day_rows)
    overlap=sum(r["selected_stocks_both_sources"] for r in day_rows)
    missing=sum(r["selected_stocks_neither_source"] for r in day_rows)
    # Recheck both market inventories and full logical parent before publishing
    # the SAFE. Stat snapshots are NOT content-level cryptographic evidence.
    source_root=Path(root)
    paths=H5._market_sources(source_root,symbols)
    after={market:H5._file_state(p) for market,p in paths.items()}
    after_signature=DATE.PURCHASED.private_cache.source_signature(
        root,"day",start,end,DATE.PURCHASED.core)
    newer,version_sha2,_,_=DATE.precheck(version_sha,symbols,first,last)
    if (after!=before or after_signature!=pq_signature
            or newer!=base or version_sha2!=version_file_sha):
        raise ValueError("H5/PQ source or logical parent changed during audit")
    result={
        "format":FORMAT,
        "status":"bounded_selected_stockday_h5_candidate_audit_not_staged",
        "period":"day",
        "requested_first":first,"requested_last":last,
        "parent_joined_version_sha256":version_sha,
        "parent_version_file_sha256":version_file_sha,
        "selected_stock_count":len(symbols),
        "selected_calendar_days":len(day_rows),
        "observed_h5_stock_days":total_h5,
        "observed_purchased_stock_days":total_pq,
        "selected_stockdays_both_sources":overlap,
        "selected_stockdays_h5_only_candidate":candidate,
        "selected_stockdays_purchased_only":sum(
            r["selected_stocks_purchased_only"] for r in day_rows),
        "selected_stockdays_neither_source":missing,
        "per_calendar_day_selected_stock_counts":day_rows,
        "source_h5_market_file_count":len(before),
        "source_h5_stat_only_sha256":fingerprint(before),
        "source_purchased_file_count":pq_signature["manifest_file_count"],
        "source_purchased_stat_only_sha256":pq_signature[
            "manifest_sha256_stat_only"],
        "source_fingerprints_are_not_content_hashes":True,
        "h5_native_field_geometry_checked_for_selected_stockdays":True,
        "h5_full_history_sortedness_verified":False,
        "whole_market_date_purchased_absence_certified":False,
        "whole_market_h5_date_completeness_certified":False,
        "selected_stockday_candidates_authorized_for_staging":False,
        "h5_volume_amount_physical_units_certified":False,
        "no_h5_to_parquet_normalized_bars_written":True,
        "no_raw_ohlcva_h5_integers_or_stock_codes_in_safe":True,
        "original_market_sources_modified":False,
        "private_active_pointers_read_or_modified":False,
        "production_query_route_modified":False,
        "ready_for_full_market_mirror":False,
    }
    with safe.open("x",encoding="utf-8") as stream:
        json.dump(result,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--parent-joined-version",required=True)
    p.add_argument("--symbols",nargs="+",required=True)
    p.add_argument("--from-date",required=True)
    p.add_argument("--to-date",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--explicit-source-readonly-audit",
                   action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=audit(a.source_root,a.parent_joined_version,
                     a.symbols,a.from_date,a.to_date,a.out)
        print("SAFE H5/PQ selected stock-date audit:",a.out)
        print("H5 source stock-days:",result["observed_h5_stock_days"])
        print("Purchased source stock-days:",result["observed_purchased_stock_days"])
        print("H5-only unqualified candidates:",
              result["selected_stockdays_h5_only_candidate"])
        print("Whole-market completeness and H5 units certified: NO")
        print("No market file, private pointer, or production writes.")
    except (ValueError,KeyError,TypeError,OSError,OverflowError,
            ImportError,ModuleNotFoundError):
        p.error("Untrusted selected-stock source audit rejected; no market writes")


if __name__=="__main__":
    main()
