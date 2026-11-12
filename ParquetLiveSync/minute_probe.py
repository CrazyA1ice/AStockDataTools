#!/usr/bin/env python3
"""Conservative public-minute OHLCVA download experiment; NEVER edits market files.

Eastmoney offers 1min recent trends2 and 5/15/30/60-min non-adjusted
K-line series with f56 volume, f57 turnover amount. Coverage, timestamp,
adjustments and volume units are NOT the purchased-feed standard until
a separate local full-day calibration succeeds. This tool intentionally
writes ONLY Git-ignored ParquetLiveSync/work/minute_source_trials.

This is an adapter for external public data *not* a claim that the
upstream simonlin1212/a-stock-data includes these bars or licenses them.
Respect site terms, availability, rate limits, and source errors.
"""
from __future__ import annotations

from datetime import date,datetime,timedelta,timezone
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

CN=timezone(timedelta(hours=8))
BASE="https://push2his.eastmoney.com/api/qt/stock/kline/get"
TRENDS="https://push2his.eastmoney.com/api/qt/stock/trends2/get"
PERIODS=("1min","5min","15min","30min","60min")
KLT={"5min":5,"15min":15,"30min":30,"60min":60}
SAMPLES=("SH600000","SZ000001","BJ920021")
WORK=Path(__file__).resolve().parent/"work"/"minute_source_trials"
RECORD="public_eastmoney_minute_candidate_not_merged_v1"
USER_AGENT="Mozilla/5.0 (compatible; ParquetLiveSync-public-minute-probe/0.1)"
MAX_RESPONSE=4_000_000

def parse_symbols(value):
    if isinstance(value,str):
        raw=value.upper().replace("，",",").split(",")
    else:
        raw=list(value)
    output=[]
    for item in raw:
        value=str(item).strip().upper()
        if not re.fullmatch(r"(SH|SZ|BJ)\d{6}",value):
            raise ValueError(f"Invalid symbol {value!r}; format SH600000,SZ000001,BJ920021")
        if value not in output:
            output.append(value)
    if not 1<=len(output)<=12:
        raise ValueError("Pilot supports only 1 to 12 explicit stocks per run")
    return output

def secid(symbol):
    if not re.fullmatch(r"(SH|SZ|BJ)\d{6}",symbol):
        raise ValueError("Stock ticker is not market-prefixed A-share")
    # Eastmoney market code '0' covers BOTH Shenzhen and Beijing.
    return ("1" if symbol.startswith("SH") else "0")+"."+symbol[2:]

def endpoint(period,symbol,*,end=None):
    if period not in PERIODS:
        raise ValueError("Unknown minute period")
    parms={"secid":secid(symbol),"fields1":"f1,f2,f3,f4,f5,f6",
           "fields2":"f51,f52,f53,f54,f55,f56,f57,f58",
           "ut":"fa5fd1943c7b386f172d6893dbbd1d0c"}
    if period=="1min":
        parms["ndays"]="5"
        url=TRENDS
    else:
        parms.update(klt=str(KLT[period]),fqt="0",lmt="600",
                     end=(end or datetime.now(CN).date()).strftime("%Y%m%d"))
        url=BASE
    return url+"?"+urllib.parse.urlencode(parms)

def fetch(url,*,timeout=20):
    req=urllib.request.Request(url,headers={
        "User-Agent":USER_AGENT,
        "Accept":"application/json,text/plain,*/*",
        "Referer":"https://quote.eastmoney.com/"})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        raw=response.read(MAX_RESPONSE+1)
    if not 20<=len(raw)<=MAX_RESPONSE:
        raise ValueError("Eastmoney source returned empty/oversize reply")
    try:
        result=json.loads(raw)
    except (ValueError,UnicodeDecodeError) as exc:
        raise ValueError("External minute source response is not plain JSON") from exc
    if not isinstance(result,dict) or result.get("rc")!=0:
        raise ValueError("External minute source error/unauthenticated/rate limited")
    return raw,result

def parse_bars(doc,period,symbol):
    if period not in PERIODS or not isinstance(doc,dict):
        raise ValueError("Invalid minute source response metadata")
    data=doc.get("data")
    if not isinstance(data,dict):
        raise ValueError("No market data available for security and requested period")
    if str(data.get("code",""))!=symbol[2:]:
        raise ValueError("Returned minute security differs from requested code")
    key="trends" if period=="1min" else "klines"
    series=data.get(key)
    if not isinstance(series,list) or not series:
        raise ValueError("No minute price/amount bars returned")
    if len(series)>3000:
        raise ValueError("Excessive external minute K-line count")
    checked=[]
    seen=set()
    for row in series:
        values=row.split(",") if isinstance(row,str) else None
        if not values or len(values)<7:
            raise ValueError("Minute source missing one of time/OHLC/volume/amount fields")
        try:
            t=datetime.strptime(values[0],"%Y-%m-%d %H:%M").replace(tzinfo=CN)
            o,c,h,l,vol,amount=(float(x) for x in values[1:7])
        except (ValueError,TypeError,OverflowError) as exc:
            raise ValueError("Minute source has invalid datetime or numeric OHLCVA") from exc
        # Some feeds include a 09:30 auction / placeholder minute.
        # Don't silently alter data; keep genuine positive trade bars and
        # flag questionable source structure for follow-up review.
        if (not all(math.isfinite(x) for x in (o,c,h,l,vol,amount))
                or o<=0 or c<=0 or h<=0 or l<=0 or h<max(o,c)
                or l>min(o,c) or h<l or vol<0 or amount<0
                or ((vol==0)!=(amount==0))):
            raise ValueError(f"Invalid {symbol} {period} OHLCVA at {values[0]}")
        stamp=int(t.timestamp()*1000)
        if stamp in seen:
            raise ValueError("Duplicate minute datetime from public source")
        seen.add(stamp)
        checked.append({"ts":stamp,"date":t.date().isoformat(),
                        "local_time":t.strftime("%H:%M"),"symbol":symbol,
                        "open":o,"high":h,"low":l,"close":c,
                        "provider_volume":vol,"amount_yuan":amount})
    if checked!=sorted(checked,key=lambda row:row["ts"]):
        raise ValueError("External minute bars are not chronologically ordered")
    return checked

def daily_summary(bars):
    days={}
    for row in bars:
        d=row["date"]
        item=days.setdefault(d,{"count":0,"volume":0.0,"amount_yuan":0.0,
                                "first_time":row["local_time"],
                                "last_time":row["local_time"]})
        item["count"]+=1
        item["volume"]+=row["provider_volume"]
        item["amount_yuan"]+=row["amount_yuan"]
        item["last_time"]=row["local_time"]
    return days

def _atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Linked market probe report destination refused")
    temp=path.with_suffix(path.suffix+".part")
    if temp.is_symlink():
        raise ValueError("Linked candidate temporary JSON refused")
    temp.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
                    encoding="utf-8")
    os.replace(temp,path)

def run(symbols=SAMPLES,*,periods=PERIODS,work=WORK,logger=print,
        requester=fetch,pause=0.4,stop=None):
    """Small explicit-source experiment: 3 stocks x 5 periods by default.

    This NEVER writes any AllCycleAStockData or H5 bytes; data are
    private raw source JSON + evidence with SHA/coverage. Incomplete
    public source means the item is FAILED, never an empty successful day.
    """
    symbols=parse_symbols(symbols)
    periods=tuple(periods)
    if any(p not in PERIODS for p in periods):
        raise ValueError("Unrecognized minute source period")
    work=Path(work)
    if work.is_symlink():
        raise ValueError("Candidate work directory redirected")
    now=datetime.now(CN)
    folder=work/now.strftime("%Y%m%d")
    folder.mkdir(parents=True,exist_ok=True)
    report={"format":RECORD,"created_at_cn":now.isoformat(),
            "source":"Eastmoney public minute HTTP (not guaranteed full history)",
            "stock_symbols":symbols,"requested_periods":list(periods),
            "market_files_modified":False,"h5_modified":False,
            "volume_units_certified":False,"minute_timestamps_certified":False,
            "production_full_market_approved":False,
            "periods":{},"failed":[]}
    for period in periods:
        report["periods"][period]={}
        for symbol in symbols:
            if stop is not None and stop():
                report["status"]="STOPPED_INCOMPLETE_TRIAL"
                _atomic_json(folder/"latest-trial.json",report)
                return report
            url=endpoint(period,symbol,end=now.date())
            logger(f"MINUTE_SOURCE_FETCH {period} {symbol}")
            try:
                raw,doc=requester(url)
                data=parse_bars(doc,period,symbol)
                digest=hashlib.sha256(raw).hexdigest()
                rawfile=folder/(f"{period}_{symbol}_{digest[:12]}.json")
                if rawfile.exists():
                    if hashlib.sha256(rawfile.read_bytes()).hexdigest()!=digest:
                        raise ValueError("Existing minute source bytes were modified")
                else:
                    part=rawfile.with_suffix(".json.part")
                    if part.is_symlink() or rawfile.is_symlink():
                        raise ValueError("Linked private raw minute source refused")
                    part.write_bytes(raw)
                    os.replace(part,rawfile)
                proof={"raw_source_sha256":digest,"private_source_file":str(rawfile),
                       "count":len(data),"date_coverage":daily_summary(data),
                       "first_bar_cn":data[0]["date"]+" "+data[0]["local_time"],
                       "last_bar_cn":data[-1]["date"]+" "+data[-1]["local_time"],
                       "status":"CANDIDATE_ONLY_NOT_MERGED"}
                report["periods"][period][symbol]=proof
                logger(f"MINUTE_SOURCE_CANDIDATE {period} {symbol} bars={len(data)}")
            except Exception as exc:
                error={"period":period,"symbol":symbol,"error":str(exc)[:500]}
                report["failed"].append(error)
                report["periods"][period][symbol]={"status":"UNAVAILABLE_OR_UNVERIFIED",
                                                    "reason":str(exc)[:500]}
                logger(f"MINUTE_SOURCE_NOT_VERIFIED {period} {symbol} {str(exc)[:160]}")
            if pause>0:
                time.sleep(pause)
    report["status"]=("PROBE_COMPLETE_CANDIDATE_ONLY"
                      if not report["failed"] else "PROBE_PARTIAL_NOT_MERGED")
    _atomic_json(folder/"latest-trial.json",report)
    logger("MINUTE_SOURCE_TRIAL="+json.dumps(
        {"status":report["status"],"success":sum(
            x.get("status")=="CANDIDATE_ONLY_NOT_MERGED"
            for p in report["periods"].values() for x in p.values()),
         "failed":len(report["failed"]),"folder":str(folder)},
        ensure_ascii=False,sort_keys=True))
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols",default=",".join(SAMPLES))
    p.add_argument("--periods",default=",".join(PERIODS))
    args=p.parse_args()
    run(args.symbols,periods=args.periods.split(","))

if __name__=="__main__":
    main()
