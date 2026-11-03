#!/usr/bin/env python3
"""Materialize SHA-qualified 1990..2010 DAY source-native H5 history as
PURCHASED-SCHEMA-COMPATIBLE *CANDIDATES*, with separate lossless quarantine.

This is NOT a certified purchased-price/volume/amount conversion. Candidate
factors are the specific cross-source hypothesis (price/1000, transCount*100,
transAmount*1000) previously studied, and only a per-row RAW VWAP arithmetic
test can pass a candidate. A pass is NOT historical physical unit evidence.
No production/active pointer or vendor H5/PQ is touched. Original RAW
integer data remains immutable in its 21 independently SHA-verified Parquets.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
WORK=MODULE/"work"/"unified_parquet"/"pre2011_day_candidates"
UTC8=timezone(timedelta(hours=8))
FORMAT="AStockDataTools 1990-2010 H5 RAW purchased-schema tentative day candidates and quarantine v1"
SOURCE_KIND="h5_pre2011_numeric_hypothesis_not_vendor_certified"
MAX_ROWS=500000
CHUNK=8192

def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

PROFILE=load("historical_candidate_source_full21",
             "audit-pre2011-raw-numeric-profile-readonly.py")
FACTOR=load("historical_candidate_vwap_evidence",
            "audit-pre2011-private-raw-vwap-factors-readonly.py")
PHYS=load("historical_candidate_purchased_schema",
          "materialize-private-2026-purchased-plus-h5-year.py")
SINGLE=PROFILE.SINGLE

def sha(path):
    return SINGLE.hash_file(path)

def qualify(row,year):
    """Return (candidate_record, reason) without discarding any raw record.

    The vendor physical-unit hypothesis is not proven even when this is
    arithmetically consistent. Early anomalous records remain lossless RAW.
    """
    if type(row) is not dict or type(row.get("symbol")) is not str:
        raise ValueError("Historical RAW row missing symbol")
    symbol=row["symbol"]
    if not re.fullmatch(r"(SH|SZ|BJ)\d{6}",symbol):
        raise ValueError("Invalid original stock code in RAW")
    fields=tuple(SINGLE.REQUIRED_NUMERIC)
    if any(type(row.get(x)) is not int or not 0<=row[x]<2**64 for x in fields):
        raise ValueError("Historical RAW integer field missing/invalid")
    key=row["datetime"]
    if key%10000!=0 or key//100000000!=year:
        raise ValueError("Unrecognized historical daily stamp")
    try:
        when=date(key//100000000,(key//1000000)%100,(key//10000)%100)
    except ValueError:
        raise ValueError("Invalid historical H5 daily stamp") from None
    op,hi,lo,cl=(row[k] for k in
                 ("openPrice","highPrice","lowPrice","closePrice"))
    vol=row["transCount"]
    amt=row["transAmount"]
    if not 0<lo<=min(op,cl)<=max(op,cl)<=hi:
        return None,"price_zero_or_ohlc_bounds"
    if vol==0 or amt==0:
        return None,"native_volume_or_amount_zero"
    # Exact integer test; do not silently force a single factor on all years.
    if not FACTOR.vwap_candidate_matches(amt,vol,lo,hi,10000):
        return None,"historical_vwap_factor10000_not_supported"
    ts=int(datetime(when.year,when.month,when.day,tzinfo=UTC8).timestamp()*1000)
    item={
        "ts":ts,"trading_date":when.isoformat(),
        "symbol":symbol,"source_symbol":symbol,
        "open":op/1000.0,"high":hi/1000.0,
        "low":lo/1000.0,"close":cl/1000.0,
        "volume":float(vol*100),"amount":float(amt*1000),
        "value_source":SOURCE_KIND,
    }
    if any(not math.isfinite(item[k]) or item[k]<0 for k in PHYS.F):
        return None,"candidate_float_overflow"
    return item,None

def output_paths(run_id,year,out):
    if (type(run_id) is not str
            or re.fullmatch(r"[a-f0-9]{12}",run_id) is None
            or type(year) is not int or not 1990<=year<=2010):
        raise ValueError("Only distinct 1990..2010 historical annual version")
    dest=WORK/f"historical_{year}_{run_id}"
    safe=Path(out)
    if (any(x.is_symlink() for x in (
            MODULE/"work",MODULE/"work"/"unified_parquet",
            WORK,REPORTS,dest,safe))
            or dest.exists() or safe.exists() or safe.suffix!=".json"
            or safe.resolve().parent!=REPORTS.resolve()
            or dest.resolve().parent!=WORK.resolve()):
        raise ValueError("Only new private historical candidate directory and SAFE")
    return dest,safe

def row_digest(row,columns):
    return (json.dumps([row[x] for x in columns],ensure_ascii=True,
                       separators=(",",":"),allow_nan=False)+"\n").encode()

def annual(year,full21,run_id,out):
    import pyarrow as pa
    import pyarrow.parquet as pq
    full,full_sha=PROFILE.source_safe(full21)
    # Checks 21 immutable original H5 RAW stage manifest, Parquet SHA and
    # FULL21 original source-inventory provenance; no vendor source opened.
    sources={y:(f,n,h) for y,f,n,h in PROFILE.verified_private_files(full)}
    if set(sources)!=set(range(1990,2011)):
        raise ValueError("Complete 1990-2010 RAW year set unavailable")
    file,n,raw_sha=sources[year]
    if n>MAX_ROWS:
        raise ValueError("Annual historical source rows exceed safe limit")
    folder,safe=output_paths(run_id,year,out)
    expected_schema=PHYS.schema(pa)
    quarantine_schema=pa.schema([
        *SINGLE.schema(pa),pa.field("quarantine_reason",pa.string())])
    dest_hash=hashlib.sha256()
    discard_hash=hashlib.sha256()
    counts=Counter()
    kept=excluded=total=0
    folder.mkdir(parents=True,exist_ok=False)
    candidate_file=folder/"purchased_schema_day_candidates.parquet"
    quarantine_file=folder/"source_native_quarantine.parquet"
    try:
        with pq.ParquetFile(file,memory_map=False,pre_buffer=False) as src, \
                pq.ParquetWriter(candidate_file,expected_schema,compression="zstd") as ok, \
                pq.ParquetWriter(quarantine_file,quarantine_schema,compression="zstd") as rejected:
            if (src.schema_arrow!=SINGLE.schema(pa)
                    or src.metadata.num_rows!=n):
                raise ValueError("RAW annual schema/count different")
            prior={}
            seen=set()
            for batch in src.iter_batches(batch_size=CHUNK,use_threads=False):
                good=[]
                bad=[]
                for row in batch.to_pylist():
                    raw_key=(row["symbol"],row["datetime"])
                    if raw_key in seen:
                        raise ValueError("Duplicate historical H5 stockday")
                    seen.add(raw_key)
                    if row["symbol"] in prior and row["datetime"]<=prior[row["symbol"]]:
                        raise ValueError("H5 native stockday order failed")
                    prior[row["symbol"]]=row["datetime"]
                    value,reason=qualify(row,year)
                    if reason is None:
                        good.append(value)
                        dest_hash.update(row_digest(value,expected_schema.names))
                        kept+=1
                    else:
                        augmented={**row,"quarantine_reason":reason}
                        bad.append(augmented)
                        discard_hash.update(row_digest(
                            augmented,quarantine_schema.names))
                        excluded+=1
                        counts[reason]+=1
                    total+=1
                if good:
                    ok.write_table(pa.Table.from_pylist(
                        good,schema=expected_schema),row_group_size=CHUNK)
                if bad:
                    rejected.write_table(pa.Table.from_pylist(
                        bad,schema=quarantine_schema),row_group_size=CHUNK)
        if total!=n or total!=kept+excluded:
            raise ValueError("Raw historical year not completely classified")
        for path,schema,count,expected in (
                (candidate_file,expected_schema,kept,dest_hash.digest()),
                (quarantine_file,quarantine_schema,excluded,discard_hash.digest())):
            with pq.ParquetFile(path) as pf:
                if pf.schema_arrow!=schema or pf.metadata.num_rows!=count:
                    raise ValueError("Historical candidate/quarantine schema/count mismatch")
                verify=hashlib.sha256()
                for batch in pf.iter_batches(batch_size=CHUNK,use_threads=False):
                    for row in batch.to_pylist():
                        verify.update(row_digest(row,schema.names))
                if verify.digest()!=expected:
                    raise ValueError("Historical candidate/quarantine full-row readback differs")
        if sha(file)!=raw_sha:
            raise ValueError("Historical immutable private RAW source changed during stage")
        safe.parent.mkdir(parents=True,exist_ok=True)
        record={
            "format":FORMAT,
            "status":"historical_day_candidate_and_raw_quarantine_materialized_not_merged",
            "year":year,
            "total_raw_h5_rows":total,
            "purchased_schema_candidate_rows_not_vendor_certified":kept,
            "lossless_native_quarantine_rows":excluded,
            "quarantine_by_reason":dict(sorted(counts.items())),
            "raw_source_full21_safe_sha256":full_sha,
            "original_annual_raw_parquet_sha256":raw_sha,
            "candidate_parquet_relative_path":candidate_file.relative_to(MODULE).as_posix(),
            "candidate_parquet_sha256":sha(candidate_file),
            "quarantine_parquet_relative_path":quarantine_file.relative_to(MODULE).as_posix(),
            "quarantine_parquet_sha256":sha(quarantine_file),
            "candidate_price_divisor":1000,
            "candidate_native_volume_multiplier":100,
            "candidate_native_amount_multiplier":1000,
            "historical_numeric_hypothesis_raw_vwap_factor":10000,
            "historical_vendor_units_corporate_actions_securities_certified":False,
            "old_purchased_2011_2026_physical_parts_untouched":True,
            "purchased_parquet_or_hikyuu_h5_original_modified":False,
            "private_active_pointer_or_production_modified":False,
            "ready_for_production_query":False,
            "original_source_files_opened_during_stage":False,
            "all_historical_raw_rows_preserved_in_either_qualified_candidate_or_raw_quarantine":True,
        }
        with safe.open("x",encoding="utf-8") as f:
            json.dump(record,f,sort_keys=True,indent=2,ensure_ascii=False)
            f.write("\n")
        return record
    except BaseException:
        # Preserve partial isolated outputs for inspection, never touch
        # original market files, immutable historical RAW, or prior versions.
        raise

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--full21-safe",type=Path,required=True)
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--write-isolated-historical-candidates",action="store_true",required=True)
    a=p.parse_args(argv)
    result=annual(a.year,a.full21_safe,a.run_id,a.out)
    print("Actual historical RAW daily rows classified:",result["total_raw_h5_rows"],flush=True)
    print("Purchased-schema hypothesis candidates (not certified):",
          result["purchased_schema_candidate_rows_not_vendor_certified"],flush=True)
    print("Full RAW-value quarantine preserved:",
          result["lossless_native_quarantine_rows"],flush=True)
    print("No raw vendor files changed, no version activated; SAFE:",a.out,flush=True)

if __name__=="__main__":
    main()
