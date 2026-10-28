#!/usr/bin/env python3
"""Bounded read-only probe for common TDX native .day/.lc5/.lc1 files.

No normalized bars, private values, or intraday timestamps are exported.
No conversion, production overlay, historical source modification, or network.
The common 32-byte layouts are a hypothesis requiring validation on real
local TDX samples before any source priority or data integration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
from datetime import date
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
REPORTS=(MODULE/"reports").resolve()
MAX_SOURCE_BYTES=64*1024*1024
ROW_BYTES=32
DAY=struct.Struct("<IIIIIfII")
MINUTE=struct.Struct("<HHfffffII")
FORMAT="AStockDataTools bounded TDX native binary read-only probe v1"
# YYYYMMDD day files can contain records from before the compressed
# intraday format's 2004 epoch. Shanghai's exchange opened in 1990.
MIN_DAY_YEAR=1990
MIN_INTRADAY_YEAR=2004
MAX_YEAR=2100


def time_profiles(period):
    if period=="day":
        return {"single_daily_record":(None,)}
    if period=="5min":
        return {
            "5min_start_48":tuple(list(range(570,690,5))+
                                   list(range(780,900,5))),
            "5min_end_48":tuple(list(range(575,695,5))+
                                 list(range(785,905,5))),
        }
    if period=="1min":
        return {
            "1min_start_240":tuple(list(range(570,690))+
                                     list(range(780,900))),
            "1min_end_240":tuple(list(range(571,691))+
                                   list(range(781,901))),
            "1min_opening_plus_end_241":tuple(list(range(570,691))+
                                                list(range(781,901))),
        }
    raise ValueError("Unsupported TDX native period")


def _symbol_and_period(file):
    ext=file.suffix.lower()
    period={".day":"day",".lc5":"5min",".lc1":"1min"}.get(ext)
    if period is None:
        raise ValueError("Expected a native TDX .day, .lc5 or .lc1 file")
    match=re.fullmatch(r"(SH|SZ|BJ)([0-9]{6})",file.stem.upper())
    if not match:
        raise ValueError("Expected a TDX filename such as sh600000.day")
    return match.group(0),period


def _date(value,period):
    if type(value) is not str:
        raise ValueError("Date must be YYYY-MM-DD")
    try:
        d=date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Bad probe date") from exc
    lower=MIN_DAY_YEAR if period=="day" else MIN_INTRADAY_YEAR
    if d.isoformat()!=value or not lower<=d.year<=MAX_YEAR:
        raise ValueError(f"Probe {period} date outside {lower}..{MAX_YEAR}")
    return d


def _decode(raw,period):
    if period=="day":
        packed,op,high,low,close,amount,volume,_=DAY.unpack(raw)
        y,m,d=packed//10000,(packed//100)%100,packed%100
        prices=(op/100.0,high/100.0,low/100.0,close/100.0)
        minute=None
    else:
        packed,minute,op,high,low,close,amount,volume,_=MINUTE.unpack(raw)
        y=packed//2048+2004
        monthday=packed%2048
        m,d=monthday//100,monthday%100
        prices=(op,high,low,close)
        if not 0<=minute<24*60:
            raise ValueError("Invalid native TDX minute field")
    try:
        decoded=date(y,m,d)
    except ValueError as exc:
        raise ValueError("Invalid native TDX packed calendar date") from exc
    earliest=MIN_DAY_YEAR if period=="day" else MIN_INTRADAY_YEAR
    if not earliest<=decoded.year<=MAX_YEAR:
        raise ValueError(
            f"Native TDX {period} source calendar year {decoded.year} "
            f"is outside {earliest}..{MAX_YEAR}")
    if (any(not math.isfinite(v) or v<=0 or v>1e9 for v in prices)
            or not math.isfinite(amount) or amount<0 or amount>1e20
            or volume<0 or
            prices[1]+0.00001<max(prices[0],prices[2],prices[3])
            or prices[2]-0.00001>min(prices[0],prices[1],prices[3])):
        raise ValueError("Nonfinite, negative or inconsistent native OHLCVA")
    return decoded,minute


def inspect(source,symbol,requested_date,max_source_bytes=MAX_SOURCE_BYTES):
    """Inspect one complete source file; return SAFE aggregate metadata only.

    The full file is hashed/checked in a bounded forward read; only a single
    user-selected date's time keys are retained in memory, never exported.
    """
    file=Path(source)
    canonical,period=_symbol_and_period(file)
    if type(symbol) is not str or canonical!=symbol:
        raise ValueError("Requested symbol must equal canonical filename")
    target=_date(requested_date,period)
    if (type(max_source_bytes) is not int or
            not ROW_BYTES<=max_source_bytes<=MAX_SOURCE_BYTES):
        raise ValueError("Invalid bounded source byte limit")
    if not file.is_file() or file.is_symlink():
        raise ValueError("Source must be a regular native TDX file, not a symlink")
    stats=file.stat()
    if (stats.st_size==0 or stats.st_size>max_source_bytes or
            stats.st_size%ROW_BYTES):
        raise ValueError("Source empty, over byte budget or not 32-byte aligned")
    seen=[]
    count=0
    first=None
    last=None
    prev=None
    digest=hashlib.sha256()
    with file.open("rb") as handle:
        for row_index in range(stats.st_size//ROW_BYTES):
            raw=handle.read(ROW_BYTES)
            if len(raw)!=ROW_BYTES:
                raise ValueError("Source truncated during read")
            digest.update(raw)
            try:
                day,minute=_decode(raw,period)
            except ValueError as exc:
                # Reveal record position and decoded calendar year (if bad),
                # never licensed OHLCVA or individual source time keys.
                raise ValueError(
                    f"Native TDX record #{row_index + 1}: {exc}") from exc
            current=(day,minute if minute is not None else -1)
            if prev is not None and current<=prev:
                raise ValueError("Native source has duplicate/nonascending time keys")
            prev=current
            first=first or day
            last=day
            count+=1
            if day==target:
                seen.append(minute)
        if handle.read(1):
            raise ValueError("Native source was appended during read")
    after=file.stat()
    if (stats.st_size!=after.st_size or
            stats.st_mtime_ns!=after.st_mtime_ns):
        raise ValueError("Native source stat changed during read")
    profiles=time_profiles(period)
    matched=next((name for name,expected in profiles.items()
                  if tuple(seen)==expected),None)
    if not seen:
        verdict="no_records_on_requested_date"
    elif matched:
        verdict="recognized_native_time_grid"
    else:
        verdict="unrecognized_or_partial_time_grid"
    return {
        "format":FORMAT,
        "period":period,
        "symbol":canonical,
        "requested_date":target.isoformat(),
        "native_source_basename":file.name,
        "source_file_size_bytes":stats.st_size,
        "source_total_records":count,
        "source_first_date":first.isoformat(),
        "source_last_date":last.isoformat(),
        "source_content_sha256":digest.hexdigest(),
        "source_stable_during_read":True,
        "requested_date_source_records":len(seen),
        "time_grid_classification":matched,
        "time_grid_verdict":verdict,
        "recognized_profiles":list(profiles),
        "all_source_record_timestamps_strictly_ascending":True,
        "candidate_native_binary_layout":"32-byte little-endian common TDX layout",
        "native_amount_and_volume_units_not_independently_verified":True,
        "minute_label_convention_not_assumed_for_staging":True,
        "source_authenticity_not_cryptographically_established":True,
        "source_market_file_modified":False,
        "raw_ohlcva_or_intraday_time_keys_in_report":False,
        "automatic_normalization_or_staging_performed":False,
        "production_query_modified":False,
    }


def safe_out(value):
    p=Path(value)
    candidate=p if p.is_absolute() else MODULE/p
    output=candidate.resolve()
    if (not REPORTS.is_relative_to(MODULE.resolve())
            or REPORTS.name!="reports"
            or (MODULE/"reports").is_symlink()
            or p.is_symlink() or output.exists()
            or not output.is_relative_to(REPORTS) or output.suffix.lower()!=".json"):
        raise ValueError("Use NEW JSON under H5ParquetReconciler/reports")
    return output


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--symbol",required=True)
    parser.add_argument("--date",required=True)
    parser.add_argument("--max-source-bytes",type=int,default=MAX_SOURCE_BYTES)
    parser.add_argument("--read-only",action="store_true",required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        output=safe_out(args.out)
        result=inspect(args.source,args.symbol,args.date,args.max_source_bytes)
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open("x",encoding="utf-8") as fd:
            json.dump(result,fd,indent=2,ensure_ascii=False,allow_nan=False)
            fd.write("\n")
        print("Saved bounded read-only native TDX probe:",output)
        print("Period:",result["period"],"matching records:",
              result["requested_date_source_records"],
              "time-grid verdict:",result["time_grid_verdict"])
        print("No bars or raw times exported; no staging/production change.")
    except (ValueError,OSError,TypeError,OverflowError,
            struct.error) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
