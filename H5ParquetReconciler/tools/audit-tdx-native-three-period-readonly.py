#!/usr/bin/env python3
"""Read-only same-stock/day TDX .day/.lc5/.lc1 OHLCVA consistency audit.

A diagnostic, NOT data normalization or permission for production union.
Strictly supports native 240 one-minute END labels and 48 five-minute END
labels; a distinct 241-bar Parquet convention is not interchangeable.
No licensed bars, price levels, volume/amount totals or source paths in report.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
SPEC=importlib.util.spec_from_file_location(
    "tdx_native_probe_for_three_period", HERE/"probe-tdx-native-readonly.py")
probe=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
FORMAT="AStockDataTools bounded TDX native three-period consistency audit v1"
FIELDS=("open","high","low","close","volume","amount")
PRICE_FIELDS=FIELDS[:4]


def _bar(raw,period):
    if period=="day":
        _,op,hi,lo,cl,amt,vol,_=probe.DAY.unpack(raw)
        return (op/100.,hi/100.,lo/100.,cl/100.,float(vol),float(amt))
    _,_,op,hi,lo,cl,amt,vol,_=probe.MINUTE.unpack(raw)
    return (float(op),float(hi),float(lo),float(cl),float(vol),float(amt))


def _read_day_values(file,period,day,inspected,max_source_bytes):
    """Second read is pinned to probe's full-file content SHA256."""
    file=Path(file)
    if file.is_symlink() or not file.is_file():
        raise ValueError("Non-regular or symlinked native source")
    st=file.stat()
    if (st.st_size != inspected["source_file_size_bytes"]
            or st.st_size > max_source_bytes or st.st_size%probe.ROW_BYTES):
        raise ValueError("Native source size/budget changed after probe")
    selected=[]
    digest=hashlib.sha256()
    with file.open("rb") as fd:
        for _ in range(st.st_size//probe.ROW_BYTES):
            buf=fd.read(probe.ROW_BYTES)
            if len(buf)!=probe.ROW_BYTES:
                raise ValueError("Native source truncated during reconciliation")
            digest.update(buf)
            d,minute=probe._decode(buf,period)
            if d==day:
                selected.append((minute,_bar(buf,period)))
        if fd.read(1):
            raise ValueError("Native source appended during reconciliation")
    current=file.stat()
    if (st.st_size!=current.st_size or st.st_mtime_ns!=current.st_mtime_ns
            or digest.hexdigest()!=inspected["source_content_sha256"]):
        raise ValueError("Native source mutated between scans or source hash mismatch")
    if len(selected)!=inspected["requested_date_source_records"]:
        raise ValueError("Selected stock-day record count changed between scans")
    return selected


def _aggregate(bars):
    if not bars:
        raise ValueError("Cannot aggregate empty bar group")
    values=[row[1] for row in bars]
    return (values[0][0],max(x[1] for x in values),
            min(x[2] for x in values),values[-1][3],
            math.fsum(x[4] for x in values),math.fsum(x[5] for x in values))


def _field_metrics(expected,actual,key):
    if len(expected)!=len(actual) or not expected:
        raise ValueError("Pairwise cross-period comparison has unequal/empty lengths")
    index=FIELDS.index(key)
    price=key in PRICE_FIELDS
    equal_count=0
    relative=[]
    ratios=[]
    zero_reference=0
    for a,b in zip(expected,actual):
        ref=a[1][index]
        got=b[1][index]
        if not math.isfinite(ref) or not math.isfinite(got):
            raise ValueError("Nonfinite aggregate result")
        if math.isclose(ref,got,rel_tol=1e-5,
                        abs_tol=0.0002 if price else 0.02):
            equal_count+=1
        relative.append(abs(got-ref)/max(abs(ref),1e-9))
        if not price:
            if ref>0:
                ratios.append(got/ref)
            else:
                zero_reference+=1
    summary={
        "n":len(expected),
        "within_diagnostic_tolerance":equal_count,
        "max_relative_error":round(max(relative),10),
        "mean_relative_error":round(statistics.fmean(relative),10),
    }
    if not price:
        summary.update({
            "ratio_actual_over_reference_median":
                round(statistics.median(ratios),8) if ratios else None,
            "positive_reference_count":len(ratios),
            "zero_reference_count":zero_reference,
        })
    return summary


def _compare(reference,actual):
    return {name:_field_metrics(reference,actual,name) for name in FIELDS}


def audit(day_file,minute5_file,minute1_file,symbol,day_text,
          max_source_bytes=probe.MAX_SOURCE_BYTES):
    """All OHLCVA lives only in memory. Output is aggregate-only evidence."""
    if len({Path(p).resolve() for p in (day_file,minute5_file,minute1_file)})!=3:
        raise ValueError("Three distinct source files are required")
    if type(max_source_bytes) is not int or not 32<=max_source_bytes<=probe.MAX_SOURCE_BYTES:
        raise ValueError("Invalid bounded source byte limit")
    day=probe._date(day_text,"day")
    files={"day":day_file,"5min":minute5_file,"1min":minute1_file}
    metadata={}
    for period,file in files.items():
        got=probe.inspect(file,symbol,day_text,max_source_bytes)
        if got["period"]!=period:
            raise ValueError(f"Wrong native source period for {period}")
        metadata[period]=got
    for period,required in (("day","single_daily_record"),
                             ("1min","1min_end_240"),
                             ("5min","5min_end_48")):
        if metadata[period]["time_grid_classification"]!=required:
            raise ValueError(
                f"{period} requires complete {required} source profile; "
                "do not fill missing bars or auto-convert 241-minute semantics")
    parsed={k:_read_day_values(path,k,day,metadata[k],max_source_bytes)
            for k,path in files.items()}
    minute1=parsed["1min"]
    minute5=parsed["5min"]
    if (tuple(x[0] for x in minute1)!=probe.time_profiles("1min")["1min_end_240"]
            or tuple(x[0] for x in minute5)!=probe.time_profiles("5min")["5min_end_48"]):
        raise ValueError("In-memory minute source grid changed after first probe")
    aggregated_5=[]
    for i,(end,_) in enumerate(minute5):
        group=minute1[i*5:(i+1)*5]
        if len(group)!=5 or tuple(x[0] for x in group)!=tuple(range(end-4,end+1)):
            raise ValueError("Cannot align TDX minute intervals to five-minute END labels")
        aggregated_5.append((end,_aggregate(group)))
    d1=_aggregate(minute1)
    d5=_aggregate(minute5)
    day_bars=parsed["day"]
    if len(day_bars)!=1:
        raise ValueError("Day source must have exactly one record")
    return {
        "format":FORMAT,
        "symbol":symbol,
        "date":day.isoformat(),
        "requested_source_records":{"day":1,"1min":240,"5min":48},
        "input":{period:{
            "native_basename":metadata[period]["native_source_basename"],
            "source_content_sha256":metadata[period]["source_content_sha256"],
            "source_total_records":metadata[period]["source_total_records"],
            "source_first_date":metadata[period]["source_first_date"],
            "source_last_date":metadata[period]["source_last_date"],
            "time_grid_classification":metadata[period]["time_grid_classification"],
        } for period in ("day","1min","5min")},
        "comparisons":{
            "one_minute_aggregate_vs_five_minute_native":_compare(
                aggregated_5,minute5),
            "five_minute_aggregate_vs_daily_native":_compare(
                [(None,d5)],day_bars),
            "one_minute_aggregate_vs_daily_native":_compare(
                [(None,d1)],day_bars),
        },
        "bar_timestamp_convention":"native end-of-interval, not Parquet start labels",
        "parquet_special_opening_241_not_mapped_or_synthesized":True,
        "amount_and_volume_units_not_assumed_identical":True,
        "numeric_tolerances_are_diagnostic_not_source_certification":True,
        "exchange_calendar_and_adjustment_unverified":True,
        "raw_ohlcva_or_individual_intraday_times_in_report":False,
        "source_market_files_modified":False,
        "private_staging_or_production_query_modified":False,
        "eligible_for_automatic_production_union":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day-file",type=Path,required=True)
    parser.add_argument("--minute5-file",type=Path,required=True)
    parser.add_argument("--minute1-file",type=Path,required=True)
    parser.add_argument("--symbol",required=True)
    parser.add_argument("--date",required=True)
    parser.add_argument("--max-source-bytes",type=int,default=probe.MAX_SOURCE_BYTES)
    parser.add_argument("--read-only",action="store_true",required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        out=probe.safe_out(args.out)
        report=audit(args.day_file,args.minute5_file,args.minute1_file,
                     args.symbol,args.date,args.max_source_bytes)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as fd:
            json.dump(report,fd,indent=2,ensure_ascii=False,allow_nan=False)
            fd.write("\n")
        print("Saved three-period aggregate-only TDX report:",out)
        print("Day/1min/5min recognized; no original price or bar exported.")
    except (ValueError,TypeError,OSError,OverflowError,ZeroDivisionError) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
