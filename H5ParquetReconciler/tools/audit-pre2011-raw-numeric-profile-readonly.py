#!/usr/bin/env python3
"""21-year historical native-H5 RAW numeric profile, never a units certificate.

Consumes a previously generated FULL-21 verification SAFE plus the 21 immutable
PRIVATE annual native-integer Parquets. Checks SHA and manifests and streams only
numeric columns. Never opens original H5, purchased Parquet, active pointers,
or production DB. No security code, date, price, volume or amount is emitted.
Existing full-21 SAFE is a snapshot, not a proof of source freshness today.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
TOTAL_ROWS=3682327
YEARS=tuple(range(1990,2011))
FORMAT="AStockDataTools pre2011 private RAW numeric aggregate profile v1"


def import_batch():
    spec=importlib.util.spec_from_file_location(
        "pre2011_private_raw_batch_profile",
        HERE/"batch-pre2011-native-h5-years-to-private-parquet.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BATCH=import_batch()
SINGLE=BATCH.SINGLE


def sha_text(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_safe(path):
    """Verify the FULL-21 status/annual counts/SHA and all no-write flags."""
    p=Path(path)
    if (REPORTS.is_symlink() or p.is_symlink() or not p.is_file()
            or p.resolve().parent!=REPORTS.resolve()
            or not 0<p.stat().st_size<=200000):
        raise ValueError("Full-21 input SAFE must exist directly under module reports")
    raw=p.read_bytes()
    obj=json.loads(raw)
    if (type(obj) is not dict
            or obj.get("status")!="all_21_historical_native_years_verified_not_normalized"
            or obj.get("years_verified")!=21
            or type(obj.get("total_native_rows")) is not int
            or obj["total_native_rows"]!=TOTAL_ROWS
            or not isinstance(obj.get("source_inventory_sha256"),str)
            or not re.fullmatch(r"[a-f0-9]{64}",obj["source_inventory_sha256"])
            or any(obj.get(k) is not False for k in (
                "purchased_normalized_schema_created",
                "historical_h5_units_certified",
                "historical_security_master_certified",
                "original_market_files_modified",
                "production_pointer_modified"))
            or type(obj.get("yearly")) is not list
            or len(obj["yearly"])!=len(YEARS)):
        raise ValueError("Previous full-21 historic source-native RAW SAFE not qualified")
    for year,item in zip(YEARS,obj["yearly"]):
        if (type(item) is not dict or type(item.get("year")) is not int
                or item["year"]!=year or type(item.get("rows")) is not int
                or not 1<=item["rows"]<=SINGLE.MAX_YEAR_ROWS
                or not isinstance(item.get("parquet_sha256"),str)
                or not re.fullmatch(r"[a-f0-9]{64}",item["parquet_sha256"])):
            raise ValueError("Unqualified annual record in full-21 SAFE")
    if sum(item["rows"] for item in obj["yearly"])!=TOTAL_ROWS:
        raise ValueError("Full-21 annual count does not match qualified total")
    return obj,hashlib.sha256(raw).hexdigest()


def target_safe(path):
    p=Path(path)
    if (REPORTS.is_symlink() or not REPORTS.is_dir() or p.is_symlink()
            or p.exists() or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Output must be a new direct-child module SAFE JSON")
    return p


def verified_private_files(full):
    """No source market access: bind each private year's content to prior full21 SHA."""
    by_year={}
    for folder in BATCH.list_jobs():
        if not re.fullmatch(
                r"native_pre2011_(?:199[0-9]|200[0-9]|2010)_[a-f0-9]{12,32}",
                folder.name):
            continue
        year=int(folder.name.split("_")[2])
        if year in by_year:
            raise ValueError("Ambiguous historical private stage for year")
        by_year[year]=folder
    if set(by_year)!=set(YEARS):
        raise ValueError("Missing or duplicate historical private yearly stage")
    result=[]
    for item in full["yearly"]:
        year=item["year"]
        folder=by_year[year]
        manifest=folder/"manifest.json"
        data=folder/"h5-native-day.parquet"
        if (manifest.is_symlink() or data.is_symlink()
                or not manifest.is_file() or not data.is_file()
                or not 0<manifest.stat().st_size<=200000):
            raise ValueError("Private historical manifest or Parquet missing/unsafe")
        m=json.loads(manifest.read_text(encoding="utf-8"))
        if (type(m) is not dict or m.get("format")!=SINGLE.PRIVATE_FORMAT
                or m.get("year")!=year
                or m.get("raw_h5_stockday_rows")!=item["rows"]
                or m.get("inventory_report_sha256")!=full["source_inventory_sha256"]
                or m.get("full_private_parquet_sha256")!=item["parquet_sha256"]
                or m.get("private_parquet_schema")!="native_uint64_all_ohlcva_no_renormalization"
                or m.get("purchased_parquet_footer_no_pre2011_rows") is not True
                or any(m.get(k) is not False for k in (
                    "private_normalized_purchased_schema",
                    "H5_native_quantity_and_amount_units_certified",
                    "H5_original_source_modified",
                    "purchased_parquet_original_modified",
                    "production_or_private_active_pointer_changed"))
                or SINGLE.hash_file(data)!=item["parquet_sha256"]):
            raise ValueError("Historical private manifest/SHA differs from full-21 SAFE")
        result.append((year,data,item["rows"],item["parquet_sha256"]))
    return result


def count_batch(columns):
    """Diagnostic counts only; zero bars and flat OHLC are NOT unit conclusions."""
    import numpy as np
    op,hi,lo,cl,vol,amt=(columns[k] for k in (
        "openPrice","highPrice","lowPrice","closePrice",
        "transCount","transAmount"))
    bounds=(lo>hi)|(op<lo)|(op>hi)|(cl<lo)|(cl>hi)
    zero_price=(op==0)|(hi==0)|(lo==0)|(cl==0)
    all_zero_price=(op==0)&(hi==0)&(lo==0)&(cl==0)
    no_qty=vol==0
    no_amt=amt==0
    above32=(
        (op>4294967295)|(hi>4294967295)|(lo>4294967295)|
        (cl>4294967295)|(vol>4294967295)|(amt>4294967295))
    return {
        "ohlc_order_or_bounds_violations":int(np.count_nonzero(bounds)),
        "any_ohlc_zero":int(np.count_nonzero(zero_price)),
        "all_ohlc_zero":int(np.count_nonzero(all_zero_price)),
        "open_high_low_close_all_equal":int(np.count_nonzero(
            (op==hi)&(hi==lo)&(lo==cl))),
        "volume_and_amount_both_zero":int(np.count_nonzero(no_qty&no_amt)),
        "volume_zero_amount_nonzero":int(np.count_nonzero(no_qty&~no_amt)),
        "volume_nonzero_amount_zero":int(np.count_nonzero(~no_qty&no_amt)),
        "any_value_exceeds_uint32":int(np.count_nonzero(above32)),
    }


def scan_native_year(path,expected,year):
    """Stream numeric data only, bounded by prior SHA manifest and row budget."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(path,memory_map=False,pre_buffer=False)
    try:
        if (tuple(pf.schema_arrow.names)!=SINGLE.FIELDS
                or pf.schema_arrow.field("symbol").type!=pa.string()
                or any(pf.schema_arrow.field(k).type!=pa.uint64()
                       for k in SINGLE.REQUIRED_NUMERIC)
                or pf.metadata.num_rows!=expected):
            raise ValueError("Historical private RAW schema/count changed")
        counters=Counter()
        seen=0
        names=list(SINGLE.REQUIRED_NUMERIC[1:])
        for batch in pf.iter_batches(batch_size=SINGLE.CHUNK,columns=names):
            if batch.num_rows==0 or seen+batch.num_rows>expected:
                raise ValueError("Invalid private RAW row count")
            if any(batch.column(i).null_count for i in range(len(names))):
                raise ValueError("Null numeric value in historical RAW record")
            cols={name:batch.column(i).to_numpy(zero_copy_only=False)
                  for i,name in enumerate(names)}
            counters.update(count_batch(cols))
            seen+=batch.num_rows
        if seen!=expected:
            raise ValueError("Historical private RAW decoded row count mismatch")
        return {"year":year,"rows":seen,
                **{name:int(counters[name]) for name in count_batch({
                    k:__empty_uint64() for k in names}).keys()}}
    finally:
        pf.close()


def __empty_uint64():
    import numpy as np
    return np.array([],dtype=np.uint64)


def run(full21_safe,out):
    full,ref_hash=source_safe(full21_safe)
    target=target_safe(out)
    entries=verified_private_files(full)
    byyear=[]
    for year,path,count,file_hash in entries:
        stat_before=(path.stat().st_size,path.stat().st_mtime_ns)
        metrics=scan_native_year(path,count,year)
        if (path.stat().st_size,path.stat().st_mtime_ns)!=stat_before:
            raise ValueError("Private RAW changed while profiling")
        if SINGLE.hash_file(path)!=file_hash:
            raise ValueError("Private RAW SHA changed while profiling")
        byyear.append(metrics)
    totals={key:sum(item[key] for item in byyear)
            for key in byyear[0] if key not in ("year","rows")}
    result={
        "format":FORMAT,
        "status":"historical_raw_numeric_diagnostics_only_not_units_certification",
        "verified_full21_source_safe_sha256":ref_hash,
        "verified_full21_snapshot_rows":TOTAL_ROWS,
        "years_scanned":len(byyear),
        "private_raw_rows_profiled":sum(r["rows"] for r in byyear),
        "yearly_aggregate_counts":byyear,
        "total_aggregate_counts":totals,
        "original_h5_or_purchased_parquet_opened":False,
        "original_sources_rechecked_live_during_this_profile":False,
        "private_raw_stage_modified":False,
        "production_or_active_pointer_modified":False,
        "normalized_purchased_day_parquet_created":False,
        "historical_units_certified":False,
        "historical_security_master_or_adjustment_basis_certified":False,
        "ready_for_production_query_or_h5_mirror":False,
        "raw_stock_codes_dates_and_ohlcva_excluded_from_safe":True,
    }
    if result["private_raw_rows_profiled"]!=TOTAL_ROWS:
        raise ValueError("Historical 21-year numeric profile incomplete")
    with target.open("x",encoding="utf-8") as fp:
        json.dump(result,fp,sort_keys=True,indent=2,ensure_ascii=False)
        fp.write("\n")
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full21-safe",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--read-only-private-raw",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        d=run(args.full21_safe,args.out)
        print("Historical 21-year RAW numeric profile:",d["private_raw_rows_profiled"])
        print("Numeric diagnostics only; physical units and adjustments NOT certified.")
        print("SAFE output:",args.out)
    except (ValueError,KeyError,TypeError,OSError,OverflowError,
            ImportError,ModuleNotFoundError,json.JSONDecodeError):
        parser.error("Private 21-year RAW profile refused; no original market writes")


if __name__=="__main__":
    main()
