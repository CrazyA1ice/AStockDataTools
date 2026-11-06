#!/usr/bin/env python3
"""Exact original H5 daily OHLCVA -> already staged Parquet recheck, READ ONLY.

1990..2010 annual date slices only, bounded to <=366 H5 records per symbol.
This does NOT certify historical securities, official calendar, adjustment
or price/volume/amount UNITS; it proves exact application of the PREVIOUSLY
DECLARED, still-uncertified candidate H5 normalization arithmetic.

The existing 21-year Parquet integrity auditor validates manifests and content
SHA independently. This tool additionally reads all selected original H5 A-code
compound records, matches exact symbol+day keys bijectively to private Parquet,
and compares six projected numeric columns bit-for-bit. No output is written.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import date, datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent


def _load(tag,filename):
    spec=importlib.util.spec_from_file_location(tag,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


FULL=_load("h5_pre2011_existing_21_year_private_file_integrity",
           "audit-original-h5-pre2011-private-21-year-day-readonly.py")
P90=FULL.P90
CORE=P90.CORE
FIELDS=("open","high","low","close","volume","amount")
RAW_FIELDS=("openPrice","highPrice","lowPrice","closePrice",
            "transCount","transAmount")
SYMBOL_LENGTH=11
MAX_A_STOCKDAYS_PER_YEAR=400000
MAX_NATIVE_DAY_ROWS_PER_SYMBOL=366


def _day_to_ms(native,year,cache):
    if (type(native) is not int or native%10000
            or not year*100000000<=native<(year+1)*100000000):
        raise ValueError("Original native H5 year/day key invalid")
    if native not in cache:
        try:
            day=date.fromisoformat(str(native//10000))
        except ValueError:
            raise ValueError("Original native H5 calendar date invalid") from None
        if day.year!=year:
            raise ValueError("Original native H5 date escaped annual audit")
        cache[native]=int(datetime(
            day.year,day.month,day.day,tzinfo=CORE.UTC8).timestamp()*1000)
    return cache[native]


def _stage_array(year,parquet,expected_count):
    """One annual <=400k rows bounded in RAM; sortable for H5 symbol slices."""
    import numpy as np
    import pyarrow.parquet as pq

    schema=FULL.ANNUAL._candidate_schema()
    pf=pq.ParquetFile(str(parquet))
    if (expected_count<1 or expected_count>MAX_A_STOCKDAYS_PER_YEAR
            or pf.schema_arrow!=schema or pf.metadata.num_rows!=expected_count
            or not 1<=pf.metadata.num_row_groups<=10000):
        raise ValueError("Private H5 exact-source comparison Parquet schema/row budget failed")
    dtype=np.dtype([("symbol","S11"),("ts","<i8"),
                    *((f,"<f8") for f in FIELDS)])
    staged=np.empty(expected_count,dtype=dtype)
    position=0
    for batch in pf.iter_batches(batch_size=16384,use_threads=False):
        n=batch.num_rows
        if (n<1 or position+n>expected_count
                or batch.schema!=schema
                or any(batch.column(i).null_count for i in range(len(schema)))):
            raise ValueError("Private candidate Parquet batch invalid/incomplete")
        symbols=batch.column(1).to_pylist()
        encoded=[]
        for item in symbols:
            if type(item) is not str or re.fullmatch(r"\d{6}\.(XSHG|XSHE|XBSE)",item) is None:
                raise ValueError("Noncanonical original-private stock code in annual candidate")
            encoded.append(item.encode("ascii"))
        if any(v!=FULL.SOURCES[year] for v in batch.column(8).to_pylist()):
            raise ValueError("Original-private provenance field differs")
        staged["symbol"][position:position+n]=encoded
        staged["ts"][position:position+n]=batch.column(0).to_numpy(zero_copy_only=False)
        for field_index,field in enumerate(FIELDS,start=2):
            staged[field][position:position+n]=batch.column(field_index).to_numpy(
                zero_copy_only=False)
        position+=n
    if position!=expected_count:
        raise ValueError("Private candidate Parquet row count incomplete")
    ordering=np.lexsort((staged["ts"],staged["symbol"]))
    staged=staged[ordering]
    if (np.any((staged["symbol"][1:]==staged["symbol"][:-1])
               & (staged["ts"][1:]==staged["ts"][:-1]))):
        raise ValueError("Duplicated original-private stockday key")
    symbols,offsets,counts=np.unique(staged["symbol"],return_index=True,
                                    return_counts=True)
    ranges={symbol:(int(begin),int(begin+count))
            for symbol,begin,count in zip(symbols,offsets,counts)}
    return staged,ranges


def compare_year(root,year,folder,h5_sha,pq_sha):
    """Compare 100% of one year's original H5 A-code records to saved Parquet."""
    import h5py
    import numpy as np

    expected,expected_other,expected_symbols,expected_dates=FULL._expected(year)
    parquet,manifest=FULL._check_manifest(year,folder,h5_sha,pq_sha)
    stage,positions=_stage_array(year,parquet,expected)
    stage_stat_before=(parquet.stat().st_size,parquet.stat().st_mtime_ns)
    compared=0
    other=0
    matched=set()
    observed_days=set()
    date_cache={}
    for market in P90.MARKETS:
        original=Path(root)/"HikyuuData"/(market+"_day.h5")
        if original.is_symlink() or not original.is_file():
            raise ValueError("Missing/symlinked original H5 annual market source")
        with h5py.File(original,"r") as hf:
            group=hf.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("Original historical H5 daily data group absent")
            for source_symbol in group:
                if (type(source_symbol) is not str
                        or not source_symbol.startswith(market.upper())
                        or CORE.symbol_id(source_symbol)!=source_symbol):
                    raise ValueError("Untrusted original H5 source security key")
                ds=group.get(source_symbol)
                if (not isinstance(ds,h5py.Dataset) or ds.ndim!=1
                        or not set(CORE.H5_FIELDS).issubset(ds.dtype.names or ())
                        or not np.issubdtype(ds.dtype.fields["datetime"][0],np.integer)):
                    raise ValueError("Untrusted original daily H5 security dataset schema")
                left,right=CORE.h5_key_slice(
                    ds,year*100000000,(year+1)*100000000)
                if (not 0<=left<=right<=len(ds)
                        or right-left>MAX_NATIVE_DAY_ROWS_PER_SYMBOL):
                    raise ValueError("Original daily H5 annual key-slice row budget exceeded")
                if left==right:
                    continue
                native=[int(x) for x in ds.fields("datetime")[left:right]]
                if (len(native)!=right-left or
                        any(a>=b for a,b in zip(native,native[1:]))):
                    raise ValueError("Original H5 annual day keys duplicated/unsorted")
                ms=np.asarray([_day_to_ms(stamp,year,date_cache)
                               for stamp in native],dtype=np.int64)
                if not CORE.is_a_share_candidate(source_symbol,year):
                    other+=len(native)
                    continue  # no original non-A OHLCVA read
                candidate=(source_symbol[2:]+"."+P90.SUFFIX[market.upper()]).encode("ascii")
                if candidate in matched or candidate not in positions:
                    raise ValueError("Original H5 vs private year security set mismatch")
                begin,end=positions[candidate]
                if end-begin!=len(native) or not np.array_equal(
                        stage["ts"][begin:end],ms):
                    raise ValueError("Original H5 vs private year exact stockday keys mismatch")
                # One bounded compound read for approved stock, <=366 records.
                records=ds[left:right]
                if len(records)!=len(native) or not np.array_equal(
                        records["datetime"].astype(np.int64),
                        np.asarray(native,dtype=np.int64)):
                    raise ValueError("Original H5 read changed source native datetime keys")
                raw=[]
                for key in RAW_FIELDS:
                    raw_type=np.dtype(ds.dtype.fields[key][0])
                    if not np.issubdtype(raw_type,np.integer):
                        raise ValueError("Original source numeric OHLCVA field not integer")
                    col=records[key]
                    if np.any(col<0):
                        raise ValueError("Original H5 has negative native OHLCVA")
                    raw.append(col)
                # Match exact Python historical staging arithmetic (float64).
                expected_columns=[
                    raw[0].astype(np.float64)/1000.0,
                    raw[1].astype(np.float64)/1000.0,
                    raw[2].astype(np.float64)/1000.0,
                    raw[3].astype(np.float64)/1000.0,
                    raw[4].astype(np.float64)*100.0,
                    raw[5].astype(np.float64)*1000.0,
                ]
                for field,reference in zip(FIELDS,expected_columns):
                    if (not np.all(np.isfinite(reference))
                            or not np.array_equal(
                                stage[field][begin:end].view(np.uint64),
                                reference.view(np.uint64))):
                        raise ValueError(
                            f"Original H5 candidate arithmetic/Parquet field {field} mismatch"
                        )
                compared+=len(native)
                observed_days.update(native)
                matched.add(candidate)
    if (compared!=expected or other!=expected_other
            or len(matched)!=expected_symbols or len(matched)!=len(positions)
            or len(observed_days)!=expected_dates):
        raise ValueError("Original H5 vs private Parquet annual source count conservation failed")
    if ((parquet.stat().st_size,parquet.stat().st_mtime_ns)!=stage_stat_before
            or P90._digest(parquet)!=manifest["private_parquet_sha256"]):
        raise ValueError("Private Parquet changed during original H5 record comparison")
    return {
        "year":year,"source_candidate_stockdays_compared":compared,
        "excluded_other_source_day_keys":other,
        "exact_keys_and_all_six_canonical_fields_equal":True,
        "private_parquet_sha256":manifest["private_parquet_sha256"],
    }


def compare(root,first=1990,last=2010):
    if (type(first) is not int or type(last) is not int
            or not 1990<=first<=last<=2010):
        raise ValueError("Only an explicitly bounded 1990..2010 annual range")
    original=Path(root).resolve()
    h5_sha,pq_sha=FULL._source_gate(original)
    all_paths=FULL._private_paths()
    total=0
    excluded=0
    for year in range(first,last+1):
        print(f"EXACT_H5_PRIVATE_YEAR_VERIFYING={year} EXPECTED={FULL._expected(year)[0]}",
              flush=True)
        proof=compare_year(original,year,all_paths[year],h5_sha,pq_sha)
        if P90.h5_state(original)!=h5_sha:
            raise ValueError("Original H5 source state changed mid-comparison")
        total+=proof["source_candidate_stockdays_compared"]
        excluded+=proof["excluded_other_source_day_keys"]
        print(
            f"EXACT_H5_PRIVATE_YEAR_PASS={year} STOCKDAYS={proof['source_candidate_stockdays_compared']} "
            f"OTHER_EXCLUDED={proof['excluded_other_source_day_keys']} "
            f"SIX_FIELDS=EXACT SHA256={proof['private_parquet_sha256']}",
            flush=True)
    if FULL._source_gate(original)!=(h5_sha,pq_sha):
        raise ValueError("Original H5/PQ source state changed during exact comparison")
    if (first==1990 and last==2010
            and (total!=FULL.EXPECTED_ALL_STOCKDAYS
                 or excluded!=FULL.EXPECTED_ALL_OTHER)):
        raise ValueError("Full 21-year original H5 compared count mismatch")
    result={
        "state":"original_h5_vs_pre2011_private_parquet_exact_candidate_6field_readonly_not_promoted",
        "first_year":first,"last_year":last,
        "years_verified":last-first+1,
        "exact_h5_source_stockdays_compared":total,
        "excluded_other_source_day_keys":excluded,
        "full_1990_2010_coverage_compared":first==1990 and last==2010,
        "all_selected_h5_candidate_keys_and_six_fields_exact_equal":True,
        "price_volume_amount_candidate_factors_verified_as_applied":True,
        "h5_price_volume_amount_units_certified":False,
        "historical_security_master_certified":False,
        "official_trading_calendar_certified":False,
        "corporate_action_adjustment_certified":False,
        "original_source_stat_not_full_byte_hash":True,
        "original_market_sources_modified":False,
        "private_candidate_files_modified":False,
        "production_activated":False,
        "ready_for_production_merge":False,
    }
    print("EXACT_H5_PRIVATE_SOURCE_COMPARE_SUMMARY="+json.dumps(
        result,ensure_ascii=False,sort_keys=True,separators=(",",":")),flush=True)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--from-year",type=int,default=1990)
    p.add_argument("--through-year",type=int,default=2010)
    a=p.parse_args(argv)
    compare(a.source_root,a.from_year,a.through_year)


if __name__=="__main__":
    main()
