#!/usr/bin/env python3
"""Read-only local Tongdaxin .lc1/.lc5 bar inventory and opening-grid probe.

Local TDX conventional paths:
  vipdoc/sh|minline/sh600000.lc1   (1-minute)
  vipdoc/sh|fzline/sh600000.lc5    (5-minute)
  vipdoc/sz|minline/sz000001.lc1
Records are 32 byte little-endian <HHfffffII:
 packed date, minute of day, OHLC floats, turnover float,
 raw volume unsigned int, reserved int.

Never downloads, installs dependencies, writes market data, converts
quantities or fabricates the missing independent 09:31 bar.
The report logs metadata/field-validity only; no paid OHLCVA raw values.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from datetime import date,datetime
import hashlib
import json
import math
from pathlib import Path
import re
import struct

FORMAT="tdx_vipdoc_lc1_lc5_readonly_32byte_probe_v1"
BAR=struct.Struct("<HHfffffII")
DEFAULT_CODES=("600000.SH","000001.SZ","688001.SH")
DEFAULT_DAYS=(date(2026,10,14),date(2026,10,15),date(2026,10,16))
SLOTS={1:(9*60+30,9*60+31,9*60+32,15*60),
       5:(9*60+30,9*60+35,9*60+40,15*60)}
MAX_SOURCE_BYTES=1024*1024*512


def symbol(code):
    if not isinstance(code,str):
        raise ValueError("Invalid security code")
    v=code.strip().upper()
    suffix=re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)",v)
    prefix=re.fullmatch(r"(SH|SZ|BJ)(\d{6})",v)
    if suffix:
        number,market=suffix.groups()
    elif prefix:
        market,number=prefix.groups()
    else:
        raise ValueError("Expected 600000.SH, SH600000 or a similar stock code")
    return market.lower(),number


def path_for(vipdoc,code,period):
    if period not in (1,5):
        raise ValueError("Only .lc1 and .lc5 minute periods supported")
    market,number=symbol(code)
    parent="minline" if period==1 else "fzline"
    return Path(vipdoc)/market/parent/(market+number+f".lc{period}")


def decode_record(raw):
    if len(raw)!=BAR.size:
        raise ValueError("Minute record is not 32 bytes")
    packed,minutes,op,hi,lo,cl,amount,volume,reserved=BAR.unpack(raw)
    year=2004+packed//2048
    tail=packed%2048
    month=tail//100
    day=tail%100
    try:
        trading_day=date(year,month,day)
    except ValueError as exc:
        raise ValueError("Corrupt packed TDX date") from exc
    if not 0<=minutes<24*60:
        raise ValueError("Invalid 0..1439 source minute")
    prices=(op,hi,lo,cl)
    if (not all(math.isfinite(x) and x>0 for x in prices)
        or not math.isfinite(amount) or amount<0
        or hi+1e-4<max(op,cl,lo) or lo-1e-4>min(op,cl,hi)):
        raise ValueError("Invalid OHLC/turnover float fields")
    return trading_day,minutes,{
        "open":op,"high":hi,"low":lo,"close":cl,
        "amount":amount,"volume_raw":volume,"reserved":reserved,
    }


def clock(n):
    return f"{n//60:02d}:{n%60:02d}"


def scan_file(path,*,period,days=DEFAULT_DAYS):
    """Scan one explicit file, hash all raw bytes; do not write to source."""
    path=Path(path)
    result={"path":str(path),"period":f"{period}min",
            "format":FORMAT,"read_only":True,"production_merge_authorized":False}
    if path.is_symlink():
        return {**result,"status":"REJECT_SYMLINK","present":False}
    if not path.is_file():
        return {**result,"status":"NOT_FOUND","present":False}
    stat=path.stat()
    if stat.st_size>MAX_SOURCE_BYTES:
        return {**result,"status":"SIZE_LIMIT_REJECT","present":True,
                "bytes":stat.st_size}
    if stat.st_size==0 or stat.st_size%BAR.size!=0:
        return {**result,"status":"INVALID_32BYTE_LENGTH","present":True,
                "bytes":stat.st_size}
    requested=set(days)
    requested_detail={d:{"count":0,"minute_sequence":[],
                         "opening":{},"duplicate_labels":0} for d in days}
    day_counts=Counter()
    invalid=0
    duplicate=0
    out_of_order=0
    first_stamp=None
    last_stamp=None
    previous=None
    sha=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(BAR.size*8192),b""):
            sha.update(chunk)
            if len(chunk)%BAR.size:
                raise ValueError("Source mutated mid-read or has short 32-byte record")
            for cells in BAR.iter_unpack(chunk):
                packed,minutes,op,hi,lo,cl,amount,volume,reserved=cells
                try:
                    # Work in constant memory for all historical records.
                    y=2004+packed//2048
                    m=(packed%2048)//100
                    d=packed%100
                    day=date(y,m,d)
                    if (minutes>1439
                        or not all(math.isfinite(x) and x>0 for x in (op,hi,lo,cl))
                        or not math.isfinite(amount) or amount<0
                        or hi+1e-4<max(op,cl,lo) or lo-1e-4>min(op,cl,hi)):
                        raise ValueError("Corrupt minute field")
                except ValueError:
                    invalid+=1
                    continue
                stamp=(day.toordinal(),minutes)
                if first_stamp is None:
                    first_stamp=stamp
                last_stamp=stamp
                if previous is not None:
                    if stamp==previous:duplicate+=1
                    if stamp<previous:out_of_order+=1
                previous=stamp
                day_counts[day]+=1
                if day in requested:
                    info=requested_detail[day]
                    info["count"]+=1
                    info["minute_sequence"].append(minutes)
                    if minutes in SLOTS[period]:
                        info["opening"][clock(minutes)]={
                            "record_present":True,
                            "price_fields_finite":True,
                            "volume_raw_nonnegative":True,
                            "amount_nonnegative":True,
                            "source_volume_unit_not_normalized":True,
                        }
    if path.stat().st_size!=stat.st_size:
        raise ValueError("Minute source size changed during scan")
    def label(stamp):
        return (date.fromordinal(stamp[0]).isoformat()+" "+clock(stamp[1])
                if stamp else None)
    details={}
    for day,info in requested_detail.items():
        series=info["minute_sequence"]
        by_min=Counter(series)
        details[str(day)]={
            "bars":info["count"],
            "first":clock(min(series)) if series else None,
            "last":clock(max(series)) if series else None,
            "first_five_labels":[clock(x) for x in sorted(series)[:5]],
            "opening_slot_presence":info["opening"],
            "duplicates":sum(c-1 for c in by_min.values() if c>1),
            "incomplete_or_special_grid":
                bool(series) and (len(series)!=(240 if period==1 else 48)),
        }
    distribution=Counter(day_counts.values())
    return {**result,"status":("VALID" if invalid==0 and duplicate==0 and
             out_of_order==0 else "REVIEW_CORRUPT_OR_NONMONOTONIC"),
            "present":True,"bytes":stat.st_size,
            "records":stat.st_size//BAR.size,
            "sha256":sha.hexdigest(),"earliest":label(first_stamp),
            "latest":label(last_stamp),
            "trading_days":len(day_counts),
            "day_bar_count_distribution":{str(k):v for k,v in
                                          sorted(distribution.items())},
            "invalid_records":invalid,"duplicate_stamps":duplicate,
            "decreasing_timestamp_pairs":out_of_order,
            "requested_days":details,
            "raw_volume_unit":"stock_shares_likely_index_differs",
            "raw_amount_unit":"yuan_float32",
            "source_values_modified":False}


def run(*,vipdoc,codes=DEFAULT_CODES,days=DEFAULT_DAYS,
        include_index=True,logger=print):
    root=Path(vipdoc)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("TDX vipdoc root missing or redirected: "+str(root))
    if not codes or len(codes)>30 or len(set(codes))!=len(codes):
        raise ValueError("Invalid anchor stock selection (max 30)")
    if not days or len(days)>12 or len(set(days))!=len(days):
        raise ValueError("Invalid target dates (max 12)")
    checks=tuple(codes)+( ("000001.SH",) if include_index and
                             "000001.SH" not in codes else ())
    state=Counter();count=Counter()
    for period in (1,5):
        for code in checks:
            path=path_for(root,code,period)
            if path.parent.is_symlink():
                result={"status":"REJECT_SYMLINK_DIRECTORY","path":str(path),
                        "period":f"{period}min","present":False}
            else:
                try:
                    result=scan_file(path,period=period,days=days)
                except (OSError,ValueError) as exc:
                    result={"status":"ERROR_OR_SOURCE_CHANGED",
                            "path":str(path),"period":f"{period}min",
                            "reason":type(exc).__name__+": "+str(exc)[:160]}
            result["stock"]=code
            state[result["status"]]+=1
            count[(period,"present")]+=int(result.get("present",False))
            logger("TDX_LOCAL_BAR_FILE="+json.dumps(result,ensure_ascii=False,sort_keys=True))
    summary={
        "format":FORMAT,"vipdoc":str(root),
        "requested_codes":list(codes),
        "requested_dates":[str(d) for d in days],
        "period_file_present_counts":{
            "1min":count[(1,"present")],
            "5min":count[(5,"present")]},
        "statuses":dict(state),
        "local_1min_needed_for_independent_0931_high":True,
        "no_network_requests":True,
        "no_output_files_written":True,
        "production_merge_authorized":False}
    logger("TDX_LOCAL_BAR_SUMMARY="+json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return summary


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--vipdoc",required=True,help=r"e.g. D:\software\TDX\vipdoc")
    cli.add_argument("--codes",default=",".join(DEFAULT_CODES),
                     help="Comma-separated stock codes e.g. 600000.SH")
    cli.add_argument("--dates",default=",".join(map(str,DEFAULT_DAYS)))
    cli.add_argument("--no-index",action="store_true")
    args=cli.parse_args()
    run(vipdoc=args.vipdoc,
        codes=tuple(x.strip().upper() for x in args.codes.split(",")),
        days=tuple(date.fromisoformat(x.strip()) for x in args.dates.split(",")),
        include_index=not args.no_index)
