#!/usr/bin/env python3
"""Two-stock one-day actual Parquet vs real Hikyuu H5 RAW record factor probe.

Only two existing H5 records and one already-bounded purchased day Parquet file
are read. NO source writes, H5 creation, SQLite, cache or automatic unit mapping.
All factors are hypotheses over numeric values in H5's raw compound records.
This is not a native C++ Hikyuu decoder or independent vendor unit certificate.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from datetime import date
from decimal import Decimal
from pathlib import Path

HERE=Path(__file__).resolve().parent


def _import(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


DAY=_import("real_day_float64_pilot","audit-real-parquet-day-float64-h5-tick-candidates.py")
AUDIT=DAY.AUDIT
FORMAT="AStockDataTools two-stock real Parquet vs raw Hikyuu H5 daily unit-factor candidates v1"
BRIDGE_FORMAT="AStockDataTools offline real float64 and crosssource evidence bridge v1"
SYMBOLS=("SH600000","SZ000001")
FIELDS=("open","high","low","close","volume","amount")
RAW=("datetime","openPrice","highPrice","lowPrice","closePrice","transCount","transAmount")
FACTORS=("0.01","0.1","1","10","100","1000")
REL_TOL=Decimal("0.00001")
PRICE_TOL=Decimal("0.005")
DAY_DATE="2026-09-30"
MAX_H5_DATASET_ROWS=25000


def check_bridge(path):
    p=AUDIT._path(path,True)
    doc=json.loads(p.read_text(encoding="utf-8"))
    if (type(doc) is not dict or doc.get("format")!=BRIDGE_FORMAT
            or doc.get("source_stock_files_or_market_db_opened") is not False
            or doc.get("real_ohlcva_or_individual_timestamps_emitted") is not False
            or doc.get("physical_amount_unit_certified") is not False
            or doc.get("physical_volume_unit_certified") is not False
            or doc.get("licensed_parquet_to_h5_mapping_certified") is not False
            or doc.get("ready_for_full_market_mirror") is not False
            or type(doc.get("precision")) is not dict
            or doc["precision"].get("two_real_stock_days_sampled")!=2
            or doc["precision"].get("trading_day")!=DAY_DATE
            or type(doc.get("tdx_vs_purchased_parquet")) is not dict
            or doc["tdx_vs_purchased_parquet"].get(
                "tdx_is_hikyuu_h5") is not False
            or type(doc.get("hikyuu_h5_vs_purchased_parquet")) is not dict
            or doc["hikyuu_h5_vs_purchased_parquet"].get(
                "any_field_candidate_conflict_bars")!=95):
        raise ValueError("Previous combined SAFE evidence missing or unsafe")
    return doc


def _plain_h5_path(root,symbol):
    root=Path(root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("H5 root must be an existing non-symlink absolute directory")
    market=symbol[:2].lower()
    if symbol not in SYMBOLS:
        raise ValueError("Only previously selected two symbols allowed")
    path=root/(market+"_day.h5")
    if (path.is_symlink() or not path.is_file()
            or path.resolve().parent!=root.resolve()):
        raise ValueError("Require original direct non-symlink market day H5")
    return path


def _read_single_h5(root,symbol,day,h5py,np):
    path=_plain_h5_path(root,symbol)
    before=(path.stat().st_size,path.stat().st_mtime_ns)
    if before[0]<=0:
        raise ValueError("Empty H5 source")
    try:
        with h5py.File(path,"r") as handle:
            group=handle.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("H5 data group absent")
            ds=group.get(symbol)
            if (not isinstance(ds,h5py.Dataset)
                    or ds.ndim!=1 or not 1<=len(ds)<=MAX_H5_DATASET_ROWS
                    or not set(RAW).issubset(ds.dtype.names or ())):
                raise ValueError("H5 dataset schema or budget invalid")
            for col in RAW:
                if not np.issubdtype(ds.dtype.fields[col][0],np.integer):
                    raise ValueError("Unexpected H5 integer record field type")
            key=int(day.replace("-",""))*10000
            # Binary search only the target day's key; never load whole H5.
            def lower(value):
                start,finish=0,len(ds)
                while start<finish:
                    mid=(start+finish)//2
                    if int(ds[mid]["datetime"])<value:
                        start=mid+1
                    else:
                        finish=mid
                return start
            left,right=lower(key),lower(key+1)
            if right-left!=1:
                raise ValueError("Required H5 stock-day missing or duplicated")
            raw=ds[left]
            if int(raw["datetime"])!=key:
                raise ValueError("Unexpected H5 day timestamp key")
            vals={field:int(raw[field]) for field in RAW}
            if any(vals[f]<0 for f in RAW):
                raise ValueError("Negative H5 unsigned value")
            return vals
    except Exception:
        # Suppress native HDF5 exceptions, which may contain local file paths.
        raise ValueError("Unable to read one bounded H5 stock-day") from None
    finally:
        after=(path.stat().st_size,path.stat().st_mtime_ns)
        if after!=before:
            raise ValueError("H5 source changed during read-only check")


def _ratio_hit(source,h5_integer,factor):
    reference=Decimal(h5_integer)*Decimal(factor)
    if source==0 and reference==0:
        return False
    if source<=0 or reference<=0:
        return False
    return abs(source-reference)/max(source,reference)<=REL_TOL


def evaluate(parquet,h5):
    if set(parquet)!=set(SYMBOLS) or set(h5)!=set(SYMBOLS):
        raise ValueError("Must compare exactly two selected stock-days")
    output={
        "candidate_factor_multiply_raw_h5_record_to_parquet_value":{
            field:{factor:0 for factor in FACTORS}
            for field in ("volume","amount")},
        "nonzero_positive_pair_count":{"volume":0,"amount":0},
        "both_zero_pair_count":{"volume":0,"amount":0},
        "one_zero_or_nonpositive_pair_count":{"volume":0,"amount":0},
        "raw_h5_price_divided_1000_within_0p005_count":{
            field:0 for field in ("open","high","low","close")},
    }
    price_to_h5={
        "open":"openPrice","high":"highPrice","low":"lowPrice",
        "close":"closePrice"}
    quantity_to_h5={"volume":"transCount","amount":"transAmount"}
    for symbol in SYMBOLS:
        row,raw=parquet[symbol],h5[symbol]
        if (type(row) is not dict or set(row)!=set(FIELDS)
                or type(raw) is not dict or set(raw)!=set(RAW)):
            raise ValueError("Unexpected raw field structure")
        for field in FIELDS:
            value=row[field]
            if type(value) is not float or not math.isfinite(value) or value<0:
                raise ValueError("Parquet float64 source value invalid")
        for field in RAW:
            if type(raw[field]) is not int or raw[field]<0:
                raise ValueError("H5 integer record invalid")
        for field,rawfield in price_to_h5.items():
            p=Decimal(str(row[field]))
            h=Decimal(raw[rawfield])/1000
            output["raw_h5_price_divided_1000_within_0p005_count"][field]+=int(
                abs(p-h)<=PRICE_TOL)
        for field,rawfield in quantity_to_h5.items():
            p=Decimal(str(row[field]))
            h=raw[rawfield]
            if p==0 and h==0:
                output["both_zero_pair_count"][field]+=1
                continue
            if p<=0 or h<=0:
                output["one_zero_or_nonpositive_pair_count"][field]+=1
                continue
            output["nonzero_positive_pair_count"][field]+=1
            for factor in FACTORS:
                output["candidate_factor_multiply_raw_h5_record_to_parquet_value"][
                    field][factor]+=int(_ratio_hit(p,h,factor))
    return output


def run(parquet_root,h5_root,trading_day,prior_bridge,out):
    destination=AUDIT._path(out,False)
    if trading_day!=DAY_DATE or date.fromisoformat(trading_day).isoformat()!=DAY_DATE:
        raise ValueError("Only the already reviewed 2026-09-30 sample is allowed")
    check_bridge(prior_bridge)
    parquet_path=DAY.FOOTER.selected_file(
        parquet_root,"day/2026-09.parquet","day")
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    import numpy as np
    import h5py
    # Reuse the already Windows-verified bounded Parquet day reader.
    pq_rows,scanned,groups=DAY._read_bounded_daily(
        parquet_path,trading_day,pa,pq,pc)
    h5_rows={symbol:_read_single_h5(h5_root,symbol,trading_day,h5py,np)
             for symbol in SYMBOLS}
    summary=evaluate(pq_rows,h5_rows)
    safe={
        "format":FORMAT,
        "sample_day":DAY_DATE,
        "two_selected_stock_days_compared":2,
        "parquet_month_day_rows_scanned_under_budget":scanned,
        "parquet_row_groups_read":groups,
        "h5_raw_day_records_read":2,
        "raw_h5_record_used_not_native_cpp_driver_decoding":True,
        "candidate_factor_definition":
            "parquet_original_float_value_approximately_equals_raw_h5_integer_times_factor",
        "relative_candidate_tolerance_decimal":"0.00001",
        "price_candidate_h5_raw_price_divisor":1000,
        "price_absolute_comparison_tolerance_decimal":"0.005",
        "comparison":summary,
        "no_real_ohlcva_or_raw_timestamp_values_in_report":True,
        "sources_read_only_no_h5_or_parquet_writes":True,
        "no_h5_output_generated":True,
        "no_market_sqlite_or_private_cache_accessed":True,
        "parquet_vendor_physical_amount_unit_certified":False,
        "parquet_vendor_physical_volume_unit_certified":False,
        "native_hikyuu_driver_unit_mapping_certified":False,
        "crosssource_factor_not_universal_outside_two_stock_days":True,
        "licensed_parquet_to_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
        "original_market_files_modified":False,
    }
    with destination.open("x",encoding="utf-8") as f:
        json.dump(safe,f,ensure_ascii=False,indent=2)
        f.write("\n")
    return safe


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet-root",type=Path,required=True)
    parser.add_argument("--h5-root",type=Path,required=True)
    parser.add_argument("--trading-day",required=True)
    parser.add_argument("--prior-bridge-safe",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--read-only-two-source-factor",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        safe=run(args.parquet_root,args.h5_root,args.trading_day,
                 args.prior_bridge_safe,args.out)
        print("SAFE two-source daily unit-factor candidate:",args.out)
        print("Selected stock-day pairs:",safe["two_selected_stock_days_compared"])
        print("Market source files modified: NO")
        print("Vendor physical units or native H5 mapping certified: NO")
    except (ValueError,OSError,TypeError,ImportError,json.JSONDecodeError):
        # Do not display vendor/HDF5/PyArrow exception messages.
        parser.error("Two-source bounded read-only evidence failed; verify sources and prior SAFE")


if __name__=="__main__":
    main()
