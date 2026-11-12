#!/usr/bin/env python3
"""Page real 5/15/30/60-min OHLCVA through Eastmoney's historical end date.

Strict source-only provenance staging (not market Parquet/H5):
- end=YYYYMMDD is verified against timestamps in the returned records.
- Page backwards by earliest returned DAY minus one, not guessed fixed
  number of trading days; 5min usually needs multiple pages.
- Cache exact raw response bytes SHA before parsing, with bounded
  retries delegated to minute_probe.fetch.
- No 1min trends2 fake OHLC bars.
- Do not treat a partly observed first/last day as a complete session.
"""
from __future__ import annotations

from datetime import date,timedelta
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from minute_probe import fetch,parse_bars,endpoint,parse_symbols,PERIODS
from live_sync import CN,WORK

PERIODS_OHLCVA=PERIODS[1:]
SOURCE_ROOT=WORK/"minute_source_trials"/"paged"
FORMAT="source_only_public_minute_history_pages_v1"

def safe_name(period,symbol):
    if period not in PERIODS_OHLCVA:
        raise ValueError("1min trends2 is NOT minute OHLCVA; do not stage it as K-line")
    [stock]=parse_symbols([symbol])
    return period,stock

def _atomic_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Linked source cache destination refused")
    part=path.with_suffix(path.suffix+".part")
    if part.is_symlink():
        raise ValueError("Linked source cache temporary path refused")
    part.write_bytes(data)
    os.replace(part,path)

def save_page(root,period,symbol,end_day,raw,doc):
    period,symbol=safe_name(period,symbol)
    root=Path(root)
    filename=root/period/symbol/(end_day.strftime("%Y%m%d")+".json")
    sha=hashlib.sha256(raw).hexdigest()
    if filename.is_file():
        previous=filename.read_bytes()
        if hashlib.sha256(previous).hexdigest()!=sha:
            # A prior cached source snapshot has changed; do NOT quietly
            # reuse or replace it. Rerun calibration / review provenance.
            raise ValueError("Private page bytes conflict with previous SHA")
    else:
        _atomic_write(filename,raw)
    values=parse_bars(doc,period,symbol)
    return filename,sha,values

def load_page(root,period,symbol,end_day):
    period,symbol=safe_name(period,symbol)
    filename=Path(root)/period/symbol/(end_day.strftime("%Y%m%d")+".json")
    if not filename.is_file() or filename.is_symlink():
        return None
    raw=filename.read_bytes()
    try:
        doc=json.loads(raw)
    except ValueError as exc:
        raise ValueError("Source cache has invalid JSON") from exc
    if doc.get("rc")!=0:
        raise ValueError("Previously saved Eastmoney page not success")
    return filename,hashlib.sha256(raw).hexdigest(),parse_bars(doc,period,symbol)

def collect_one(period,symbol,start,end,*,root=SOURCE_ROOT,
                requester=fetch,logger=print,stop=None,pause=.6,max_pages=35):
    """Return strict private bar series+source receipts for one security.

    Guard: only historical closed A-share dates 2026-10-14 onward, the
    previously purchased original minute data are never modified.
    """
    period,symbol=safe_name(period,symbol)
    if not isinstance(start,date) or not isinstance(end,date) or start>end:
        raise ValueError("Invalid minute history start/end")
    if start<date(2026,9,1) or (end-start).days>180:
        raise ValueError("Minute backfill window must be <=180 days and since Sep 2026")
    if not 1<=max_pages<=100:
        raise ValueError("Excessive requested minute page count")
    collected={}
    pages=[]
    current=end
    for number in range(max_pages):
        if stop is not None and stop():
            raise InterruptedError("User requested safe stop of source-only minute download")
        cached=load_page(root,period,symbol,current)
        if cached is not None:
            filename,sha,bars=cached
            logger(f"MINUTE_PAGE_CACHED {period} {symbol} END={current}")
        else:
            logger(f"MINUTE_PAGE_FETCH {period} {symbol} END={current}")
            raw,doc=requester(endpoint(period,symbol,end=current))
            # Immediately persist the raw evidence, and validate it.
            filename,sha,bars=save_page(root,period,symbol,current,raw,doc)
            if pause:
                time.sleep(pause)
        if not bars:
            raise ValueError("Empty private source page")
        actual_last=date.fromisoformat(bars[-1]["date"])
        earliest=date.fromisoformat(bars[0]["date"])
        if actual_last>current:
            raise ValueError(
                f"MINUTE_HISTORY_END_NOT_RESPECTED period={period}"
                f" requested={current} actual={actual_last}")
        if actual_last<start and number==0:
            raise ValueError("Requested minute historical window not offered by source")
        if earliest>current:
            raise ValueError("Source has impossible chronology")
        added=0
        for bar in bars:
            d=date.fromisoformat(bar["date"])
            if d<start or d>end:
                continue
            key=bar["ts"]
            if key in collected:
                original=collected[key]
                if original!=bar:
                    raise ValueError("Same minute timestamp conflicts across source pages")
            else:
                collected[key]=bar
                added+=1
        pages.append({"period":period,"symbol":symbol,
                      "requested_end":current.isoformat(),
                      "raw_sha256":sha,"raw_path":str(filename),
                      "source_first":earliest.isoformat(),
                      "source_last":actual_last.isoformat(),
                      "bars_accepted_in_window":added})
        logger(f"MINUTE_PAGE_CACHED_AND_VERIFIED {period} {symbol} "
               f"END={current} FOUND={len(bars)} IN_WINDOW={added}")
        if earliest<=start:
            break
        previous=earliest-timedelta(days=1)
        if previous>=current:
            raise ValueError("Source minute page could not advance backward")
        current=previous
    else:
        raise ValueError("Minute history pagination exceeded verified page limit")
    values=[collected[k] for k in sorted(collected)]
    covered=sorted(set(bar["date"] for bar in values))
    result={"format":FORMAT,"period":period,"symbol":symbol,
            "requested_start":start.isoformat(),
            "requested_end":end.isoformat(),
            "pages":pages,"count":len(values),
            "covered_days":covered,
            "source_minute_bars_only_not_full_market_verified":True,
            "physical_allcycle_parquet_modified":False,
            "original_h5_modified":False}
    return result,values

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols",default="SH600000,SZ000001,BJ920021")
    parser.add_argument("--periods",default="5min,15min,30min,60min")
    parser.add_argument("--start",type=date.fromisoformat,default=date(2026,10,14))
    parser.add_argument("--end",type=date.fromisoformat,default=date(2026,11,11))
    args=parser.parse_args()
    symbols=parse_symbols(args.symbols)
    periods=args.periods.split(",")
    for symbol in symbols:
        for period in periods:
            try:
                info,_=collect_one(period,symbol,args.start,args.end)
                print("MINUTE_HISTORY_SOURCE_RESULT="+json.dumps(
                    info,ensure_ascii=False,sort_keys=True))
            except Exception as exc:
                print(f"MINUTE_HISTORY_REJECTED {period} {symbol} {exc}")
                raise

if __name__=="__main__":
    main()
