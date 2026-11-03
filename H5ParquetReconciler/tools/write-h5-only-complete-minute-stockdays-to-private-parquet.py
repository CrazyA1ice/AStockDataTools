#!/usr/bin/env python3
"""Write REAL H5-only complete stock-days for 1min + 5min into NEW private
Parquet gap partitions. Original purchased Parquet / original Hikyuu H5
are strictly read-only. No active pointer and no source overwrite.

For a chosen actual trading date, *any* purchased Parquet minute bar for a
stock-day gives the purchased stock-day absolute priority. H5 contributes
ONLY entirely missing stock-days with a complete regular H5 session grid.
This deliberately does not infer individual missing minutes in mixed days.

H5 source carries integer native OHLCVA in extra columns so the later Hikyuu
mirror can recover the original source integers, rather than falsely claim
Float64 is bitwise invertible from a fixed-point H5 representation.

For a native H5 1min endpoint T, the candidate purchased-Parquet bar start
is T-1min; for 5min endpoint T, candidate bar start is T-5min. This time
convention remains explicitly labelled candidate in the SAFE and overlay.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import traceback
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
WORK=MODULE/"work"/"unified_parquet"/"minute_gap_staging"
PERIODS=("1min","5min")
RAW_FIELDS=("datetime","openPrice","highPrice","lowPrice","closePrice","transCount","transAmount")
FIELD_VALUES=("open","high","low","close","volume","amount")
FORMAT="AStockDataTools H5-only complete minute stockdays private Parquet write v1"
RUN=re.compile(r"[a-f0-9]{12}\Z")


def load():
    spec=importlib.util.spec_from_file_location(
        "private_h5_minute_gap_existing_reconciler",
        HERE/"reconcile-local-a-share-h5-parquet.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CORE=load()


def session_stamps(day,period):
    start=int(day.strftime("%Y%m%d"))*10000
    sessions=(
        ((9*60+31,11*60+30),(13*60+1,15*60))
        if period=="1min" else
        ((9*60+35,11*60+30),(13*60+5,15*60)))
    step=1 if period=="1min" else 5
    return frozenset(start+(minute//60)*100+minute%60
        for lo,hi in sessions for minute in range(lo,hi+1,step))


def completeness(stamps,day,period):
    expected=session_stamps(day,period)
    observed=list(stamps)
    if len(observed)!=len(set(observed)):
        return "duplicate_native_timestamp"
    if not observed or set(observed)-expected:
        return "outside_native_session_grid"
    missing=len(expected)-len(observed)
    if period=="5min":
        return "complete" if missing==0 else "incomplete_5min_session"
    return "complete" if missing in (0,1) else "incomplete_1min_session"


def pct_hash(path):
    digest=hashlib.sha256()
    with path.open("rb") as fp:
        for b in iter(lambda:fp.read(1024*1024),b""):
            digest.update(b)
    return digest.hexdigest()


def schema(pa):
    return pa.schema([
        pa.field("ts",pa.int64(),False),
        pa.field("symbol",pa.string(),False),
        *[pa.field(k,pa.float64(),False) for k in FIELD_VALUES],
        pa.field("h5_native_datetime",pa.int64(),False),
        *[pa.field("h5_native_"+k,pa.uint64(),False)
          for k in RAW_FIELDS[1:]],
        pa.field("value_source",pa.string(),False),
        pa.field("period",pa.string(),False),
    ])


def converted_row(row,symbol,period,day):
    raw={field:int(row[field]) for field in RAW_FIELDS}
    if any(v<0 for v in raw.values()):
        raise ValueError("Negative H5 unsigned native value")
    stamp=raw["datetime"]
    dt=datetime.strptime(str(stamp),"%Y%m%d%H%M").replace(tzinfo=CORE.UTC8)
    if dt.date()!=day:
        raise ValueError("H5 minute stamp outside requested date")
    # Match purchased Parquet time-label convention: 1min records carry
    # minute END timestamps, whereas 5min records carry START timestamps.
    # Preserve original H5 1min end; only subtract 5min for 5min sources.
    shift=0 if period=="1min" else 5
    started=dt-timedelta(minutes=shift)
    values=(
        raw["openPrice"]/1000,raw["highPrice"]/1000,
        raw["lowPrice"]/1000,raw["closePrice"]/1000,
        float(raw["transCount"]),float(raw["transAmount"])*1000)
    if (not all(math.isfinite(v) and v>=0 for v in values)
            or values[1]<max(values[0],values[3])
            or values[2]>min(values[0],values[3])
            or values[1]<values[2]):
        raise ValueError("H5 minute geometry/quantity invalid")
    return {
        "ts":int(started.timestamp()*1000),
        "symbol":symbol,
        **dict(zip(FIELD_VALUES,values)),
        "h5_native_datetime":stamp,
        **{"h5_native_"+k:v for k,v in raw.items() if k!="datetime"},
        "value_source":"h5_only_complete_stockday",
        "period":period,
    }


def purchased_stockdays(root,period,day,*,max_rows=6000000,
                      include_time_keys=False):
    """Read only purchased ts/symbol columns; budget *date-matched* keys.

    Large vendor rowgroups may span many dates. Scanning a rowgroup does NOT
    mean every row belongs to the requested stock-day; the old 6m budget
    incorrectly counted unrelated dates and failed on real January data.
    Use Arrow's vectorized timestamp filter before converting symbols to
    Python. Memory stays bounded by the 65,536-row Arrow batch.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    files=CORE.year_files(root,period,day.year)
    if not files:
        raise ValueError("Purchased Parquet year absent; refuse unknown stockday coverage")
    low=int(datetime(day.year,day.month,day.day,tzinfo=CORE.UTC8).timestamp()*1000)
    next_day=day+timedelta(days=1)
    high=int(datetime(next_day.year,next_day.month,next_day.day,
                      tzinfo=CORE.UTC8).timestamp()*1000)
    stocks=set()
    keys_by_stockday={} if include_time_keys else None
    scanned=0
    matched=0
    groups=0
    for file in files:
        with pq.ParquetFile(file,memory_map=False,pre_buffer=False) as f:
            if not {"ts","symbol"}.issubset(f.schema_arrow.names):
                raise ValueError("Parquet minute source lacks ts/symbol")
            if not pa.types.is_integer(f.schema_arrow.field("ts").type):
                raise ValueError("Purchased minute timestamp must be integer epoch_ms")
            symbol_type=f.schema_arrow.field("symbol").type
            if pa.types.is_dictionary(symbol_type):
                symbol_type=symbol_type.value_type
            if not (pa.types.is_string(symbol_type)
                    or pa.types.is_large_string(symbol_type)):
                raise ValueError("Purchased minute symbol must be string")
            for rg in range(f.metadata.num_row_groups):
                meta=f.metadata.row_group(rg)
                if not CORE.row_group_overlaps_timestamp(meta,low,high):
                    continue
                groups+=1
                for batch in f.iter_batches(
                        row_groups=[rg],batch_size=65536,
                        columns=["ts","symbol"],use_threads=False):
                    scanned+=batch.num_rows
                    # Arrow's null-aware predicate skips malformed missing
                    # timestamps, as the prior 'type(stamp) is int' did.
                    timestamps=batch.column(0)
                    within_day=pc.and_(
                        pc.greater_equal(timestamps,low),
                        pc.less(timestamps,high))
                    matched_symbols=pc.filter(batch.column(1),within_day)
                    matched+=len(matched_symbols)
                    if matched>max_rows:
                        raise ValueError(
                            "Minute purchased matching-day key budget exceeded")
                    matched_stamps=(pc.filter(timestamps,within_day).to_pylist()
                                    if include_time_keys else None)
                    source_symbols=matched_symbols.to_pylist()
                    if include_time_keys:
                        for stamp,source_symbol in zip(matched_stamps,source_symbols):
                            sym=CORE.symbol_id(source_symbol)
                            if sym and CORE.is_a_share_candidate(sym,day.year):
                                stocks.add(sym)
                                keys=keys_by_stockday.setdefault(sym,set())
                                if stamp in keys:
                                    raise ValueError(
                                        "Duplicate purchased minute key on target date")
                                keys.add(stamp)
                    else:
                        for source_symbol in source_symbols:
                            sym=CORE.symbol_id(source_symbol)
                            if sym and CORE.is_a_share_candidate(sym,day.year):
                                stocks.add(sym)
    scan={
        "purchased_files_opened":len(files),
        "purchased_rowgroups_read":groups,
        "purchased_key_candidate_rows_scanned":scanned,
        "purchased_timestamp_matched_day_rows":matched,
        "purchased_key_budget_applied_to":"matching_day_rows_only",
        "purchased_stockdays_present":len(stocks),
        "exact_time_keys_in_memory":bool(include_time_keys),
    }
    return (stocks,scan,keys_by_stockday) if include_time_keys else (stocks,scan)


def write_private_day(root,day,period,run_id,*,max_purchased_rows=6000000,
                      max_h5_rows=2500000):
    import h5py
    import pyarrow as pa
    import pyarrow.parquet as pq
    if (type(period) is not str or period not in PERIODS
            or type(run_id) is not str or RUN.fullmatch(run_id) is None
            or not date(2025,1,1)<=day<=date(2026,12,31)):
        raise ValueError("Only explicitly bounded 2025/2026 1min or 5min gap stage")
    if not root.is_dir():
        raise ValueError("Input root is missing")
    source_markets=[]
    missing_market_files=[]
    for market in ("sh","sz","bj"):
        p=root/"HikyuuData"/f"{market}_{period}.h5"
        if p.is_symlink() or (p.exists() and not p.is_file()):
            raise ValueError("Original minute H5 market source is unsafe")
        if p.is_file():
            source_markets.append(market)
        else:
            missing_market_files.append(market)
    if not source_markets:
        raise ValueError("No original Hikyuu minute H5 files available")
    purchased,scan=purchased_stockdays(
        root,period,day,max_rows=max_purchased_rows)
    target=WORK/run_id/period
    output=target/f"{day.isoformat()}.parquet"
    if (WORK.is_symlink() or target.is_symlink()
            or output.exists() or target.exists()):
        raise ValueError("Use a new unique isolated minute Parquet output")
    stats=Counter()
    reasons=Counter()
    parquet_schema=schema(pa)
    lower=int(day.strftime("%Y%m%d"))*10000
    upper=int((day+timedelta(days=1)).strftime("%Y%m%d"))*10000
    target.mkdir(parents=True,exist_ok=False)
    total=0
    input_digest=hashlib.sha256()
    buffer=[]
    # Bound working memory to about 32k bars even on a 1.3m-bar day.
    def flush(writer):
        if not buffer:
            return
        chunk=pa.Table.from_pylist(buffer,schema=parquet_schema)
        writer.write_table(chunk,row_group_size=32768)
        buffer.clear()

    with pq.ParquetWriter(output,parquet_schema,compression="zstd") as writer:
        for market in source_markets:
            file=root/"HikyuuData"/f"{market}_{period}.h5"
            with h5py.File(file,"r") as fh:
                group=fh.get("data")
                if not isinstance(group,h5py.Group):
                    raise ValueError("Missing original Hikyuu minute data group")
                for symbol in group:
                    if (not re.fullmatch(market.upper()+r"\d{6}",symbol)
                            or not CORE.is_a_share_candidate(symbol,day.year)):
                        continue
                    ds=group[symbol]
                    if (not isinstance(ds,h5py.Dataset)
                            or not set(RAW_FIELDS).issubset(ds.dtype.names or ())):
                        reasons["invalid_native_h5_schema"]+=1
                        continue
                    # Purchased source owns this entire stock-day. Do not
                    # binary-search the expensive H5 dataset just to discard
                    # it. The new count is explicitly an unprobed dataset,
                    # NOT a claimed observed H5 stock-day or verified H5 gap.
                    # Needed H5-only symbols still use identical complete-grid,
                    # conversion, lossless-native and SHA readback checks.
                    if symbol in purchased:
                        stats["h5_datasets_not_probed_purchased_stockday"]+=1
                        continue
                    a,b=CORE.h5_key_slice(ds,lower,upper)
                    if a==b:
                        continue
                    stats["h5_stockdays_seen"]+=1
                    if b-a>240 or stats["h5_rows_examined"]+(b-a)>max_h5_rows:
                        raise ValueError("Minute H5 source rows exceed bounded day budget")
                    original=ds[a:b]
                    stats["h5_rows_examined"]+=len(original)
                    classification=completeness(
                        [int(r["datetime"]) for r in original],day,period)
                    if classification!="complete":
                        reasons[classification]+=1
                        continue
                    try:
                        rows=[converted_row(r,symbol,period,day) for r in original]
                    except (TypeError,ValueError,OverflowError):
                        reasons["invalid_native_minute_values"]+=1
                        continue
                    rows.sort(key=lambda r:r["ts"])
                    if any(rows[k]["ts"]==rows[k-1]["ts"]
                           for k in range(1,len(rows))):
                        raise ValueError("Duplicate normalized H5 minute timestamp")
                    for row in rows:
                        input_digest.update(json.dumps(
                            row,sort_keys=True,allow_nan=False).encode())
                    buffer.extend(rows)
                    total+=len(rows)
                    stats["h5_full_stockdays_staged"]+=1
                    if len(buffer)>=32768:
                        flush(writer)
        flush(writer)
    # Full native integer and normalized OHLCVA row-by-row check.
    with pq.ParquetFile(output) as file:
        if file.schema_arrow!=parquet_schema or file.metadata.num_rows!=total:
            raise ValueError("Minute gap Parquet row/schema readback changed")
        digest=hashlib.sha256()
        allowed=session_stamps(day,period)
        for batch in file.iter_batches(batch_size=65536,use_threads=False):
            for row in batch.to_pylist():
                if (row["period"]!=period
                        or row["value_source"]!="h5_only_complete_stockday"
                        or row["h5_native_datetime"] not in allowed):
                    raise ValueError("Written native minute row identity changed")
                digest.update(json.dumps(
                    row,sort_keys=True,allow_nan=False).encode())
    if digest.digest()!=input_digest.digest():
        raise ValueError("H5 native integer fields changed during Parquet write")
    return {
        "format":FORMAT,
        "status":"h5_complete_stockday_minute_gap_private_parquet_written_readback_not_merged",
        "period":period,
        "day":day.isoformat(),
        "source_purchased_parquet_stockdays_priority_preserved":True,
        "original_purchased_parquet_or_h5_modified":False,
        "h5_time_convention_source_end_to_candidate_parquet_start_minutes":
            (0 if period=="1min" else 5),
        "standardized_minute_key_contract":
            ("native_1min_end_equals_purchased_1min_end" if period=="1min"
             else "native_5min_end_minus_5_equals_purchased_5min_start"),
        "minute_time_alignment_vendor_certified":False,
        "h5_raw_integer_fields_preserved":True,
        "private_parquet_rows":total,
        "private_parquet_stockdays":int(stats["h5_full_stockdays_staged"]),
        "purchased_scan":scan,
        "other_h5_counts":{k:int(v) for k,v in stats.items()},
        "missing_h5_market_files":missing_market_files,
        "quarantined_stockdays":{k:int(v) for k,v in reasons.items()},
        "private_parquet_relative_file":output.relative_to(MODULE).as_posix(),
        "private_parquet_sha256":pct_hash(output),
        "ready_for_production_query":False,
        "ready_for_h5_mirror":False,
        "ready_for_automatic_market_merge":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--day",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--max-purchased-key-rows",type=int,default=6000000)
    p.add_argument("--max-h5-rows",type=int,default=2500000)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--write-private-minute-gaps-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        day=date.fromisoformat(a.day)
        safe=Path(a.out)
        if (REPORTS.is_symlink() or safe.is_symlink() or safe.exists()
                or safe.resolve().parent!=REPORTS.resolve()
                or safe.suffix!=".json"):
            raise ValueError("Must use new aggregate-only reports JSON")
        result={}
        for period in PERIODS:
            result[period]=write_private_day(
                a.root,day,period,a.run_id,
                max_purchased_rows=a.max_purchased_key_rows,
                max_h5_rows=a.max_h5_rows)
            print("Actual H5 minute gap Parquet written:",
                  period,"rows:",result[period]["private_parquet_rows"],flush=True)
        summary={
            "format":FORMAT,
            "source_day":day.isoformat(),
            "period_results":result,
            "original_market_files_modified":False,
            "production_or_private_pointer_modified":False,
            "all_private_outputs_written_not_merged":True,
        }
        payload=json.dumps(summary,sort_keys=True,indent=2)+"\n"
        with safe.open("x",encoding="utf-8",newline="\n") as f:
            f.write(payload)
        print("PASS: 1min + 5min H5-only COMPLETE stockdays materialized in private Parquet")
        print("Aggregate-only SAFE:",a.out)
    except Exception as ex:
        last=traceback.extract_tb(ex.__traceback__)[-1]
        p.error("Minute private Parquet write incomplete ["+
                type(ex).__name__+"/"+last.name+":"+str(last.lineno)+
                "]; input sources unchanged; partial private files may remain")


if __name__=="__main__":
    main()
