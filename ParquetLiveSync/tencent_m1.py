#!/usr/bin/env python3
"""True Tencent SH/SZ 1-minute OHLCV K-line, after a-stock-data SKILL §1.2.

Path /appstock/app/kline/mkline param=sh600000,m1,,320.
Upstream semantics: true OPEN/HIGH/LOW/CLOSE, VOLUME, turnover-rate,
NO per-minute turnover AMOUNT. SH 688/689 stock volume is shares;
other A shares are lots. Latest <=320 rows only, BJ not supported.
Save private original raw JSON with SHA plus *OHLCV-only* Arrow Parquet.
No official AllCycleAStockData or H5 files are modified.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

CN=timezone(timedelta(hours=8))
HERE=Path(__file__).resolve().parent
WORK=HERE/"work"/"minute_source_trials"/"tencent_m1"
HOSTS=("https://web.ifzq.gtimg.cn",
       "https://proxy.finance.qq.com/ifzqgtimg",
       "https://ifzq.gtimg.cn")
PATH="/appstock/app/kline/mkline"
FORMAT="tencent_m1_true_ohlcv_source_only_no_turnover_amount_v1"
MAX_BODY=3_000_000

def market_symbol(symbol):
    value=str(symbol).strip().upper()
    if not re.fullmatch(r"(SH|SZ)\d{6}",value):
        raise ValueError("Tencent 1min requires SH/SZ code; no Beijing minute support")
    return value

def url_for(symbol,host=HOSTS[0],count=320):
    symbol=market_symbol(symbol)
    if type(count) is not int or not 1<=count<=320:
        raise ValueError("Tencent 1min count must be 1..320")
    if host not in HOSTS:
        raise ValueError("Unexpected Tencent hostname")
    return host+PATH+"?"+urllib.parse.urlencode({
        "param":f"{symbol.lower()},m1,,{count}"})

def fetch_bytes(url,*,timeout=22,opener=None):
    opener=opener or urllib.request.urlopen
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; AStockDataTools/ParquetLiveSync)",
        "Referer":"https://gu.qq.com/",
        "Accept":"application/json,text/plain,*/*",
        "Connection":"close"})
    with opener(req,timeout=timeout) as response:
        raw=response.read(MAX_BODY+1)
    if not 16<=len(raw)<=MAX_BODY:
        raise ValueError("Tencent K-line body empty/oversized")
    return raw

def decode(raw,symbol):
    symbol=market_symbol(symbol)
    try:
        obj=json.loads(raw)
    except (ValueError,UnicodeDecodeError) as exc:
        raise ValueError("Tencent 1min response is not JSON") from exc
    if not isinstance(obj,dict):
        raise ValueError("Tencent 1min root not object")
    if obj.get("msg")=="param error":
        raise ValueError("Tencent minute endpoint rejected parameters")
    key=symbol.lower()
    data=obj.get("data")
    if not isinstance(data,dict) or not isinstance(data.get(key),dict):
        raise ValueError("Tencent response returned wrong stock or exchange")
    records=data[key].get("m1")
    if not isinstance(records,list) or not records:
        raise ValueError("Tencent 1min returned no real K-line bars")
    if len(records)>320:
        raise ValueError("Tencent 1min >320 bars unexpected")
    seen=set()
    rows=[]
    for item in records:
        if not isinstance(item,(list,tuple)) or len(item)<6:
            raise ValueError("Tencent minute K-line missing timestamp/OHLC/volume")
        if not isinstance(item[0],str) or re.fullmatch(r"\d{12}",item[0]) is None:
            raise ValueError("Tencent minute timestamp malformed")
        try:
            dt=datetime.strptime(item[0],"%Y%m%d%H%M").replace(tzinfo=CN)
            o,c,h,l,v=(float(item[i]) for i in (1,2,3,4,5))
        except (ValueError,TypeError,OverflowError) as exc:
            raise ValueError("Tencent minute OHLCV numeric invalid") from exc
        clock=dt.strftime("%H:%M")
        if not (clock=="09:30" or "09:31"<=clock<="11:30"
                or "13:01"<=clock<="15:00"):
            raise ValueError("Tencent minute bar outside Chinese stock session")
        if (not all(math.isfinite(x) for x in (o,c,h,l,v))
                or min(o,c,h,l)<=0 or h<max(o,c) or l>min(o,c)
                or v<0):
            raise ValueError("Tencent minute OHLCV price/volume invalid")
        stamp=int(dt.timestamp()*1000)
        if stamp in seen:
            raise ValueError("Duplicate Tencent 1min stock timestamp")
        seen.add(stamp)
        # item[7] is turnover-rate basis points, NOT turnover amount.
        rate=(float(item[7]) if len(item)>7
              and item[7] not in ("",None) else None)
        if rate is not None and not math.isfinite(rate):
            raise ValueError("Tencent turnover rate invalid")
        rows.append({
            "ts":stamp,"symbol":symbol,
            "date":dt.date().isoformat(),"local_time":clock,
            "open":o,"high":h,"low":l,"close":c,
            "source_volume":v,
            "source_volume_unit":(
                "shares" if symbol[2:5] in ("688","689") else "lots_100_shares"),
            "turnover_rate_basis_points":rate})
    if rows!=sorted(rows,key=lambda row:row["ts"]):
        raise ValueError("Tencent K-line bars unsorted")
    return rows

def save_immutable(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Linked private source cache refused")
    sha=hashlib.sha256(raw).hexdigest()
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError("Previously cached Tencent raw bytes changed")
    else:
        part=path.with_suffix(path.suffix+".part")
        if part.is_symlink():
            raise ValueError("Linked Tencent part file refused")
        part.write_bytes(raw)
        os.replace(part,path)
    return sha

def collect(symbol,*,count=320,work=WORK,requester=fetch_bytes,
            hosts=HOSTS,logger=print,pause=.5):
    symbol=market_symbol(symbol)
    if Path(work).is_symlink():
        raise ValueError("Linked Tencent work root refused")
    failures=[]
    for host in hosts:
        try:
            url=url_for(symbol,host,count)
            logger(f"TENCENT_1MIN_FETCH {symbol} count={count} host={host}")
            raw=requester(url)
            bars=decode(raw,symbol)
            today=datetime.now(CN).strftime("%Y%m%d")
            folder=Path(work)/today
            digest=hashlib.sha256(raw).hexdigest()
            path=folder/f"{symbol}_{digest[:16]}.json"
            save_immutable(path,raw)
            import pyarrow as pa
            import pyarrow.parquet as pq
            schema=pa.schema([
                ("ts",pa.int64()),("symbol",pa.string()),
                ("open",pa.float64()),("high",pa.float64()),
                ("low",pa.float64()),("close",pa.float64()),
                ("source_volume",pa.float64())])
            frame=pa.Table.from_pylist([
                {column:row[column] for column in schema.names}
                for row in bars],schema=schema)
            target=folder/f"{symbol}_{digest[:16]}_ohlcv_only.parquet"
            if target.is_symlink():
                raise ValueError("Linked private 1min Arrow refused")
            if target.exists():
                with pq.ParquetFile(target) as file:
                    if file.schema_arrow!=schema or file.metadata.num_rows!=frame.num_rows:
                        raise ValueError("Private cached 1m Arrow file changed")
                if not pq.read_table(target).equals(frame,check_metadata=False):
                    raise ValueError("Private cached 1m Arrow values modified")
            else:
                part=target.with_suffix(".parquet.part")
                pq.write_table(frame,part,compression="zstd")
                with pq.ParquetFile(part) as file:
                    if file.metadata.num_rows!=frame.num_rows:
                        raise ValueError("Tencent private Arrow staged count mismatch")
                if not pq.read_table(part).equals(frame,check_metadata=False):
                    raise ValueError("Tencent private Arrow readback mismatch")
                os.replace(part,target)
            days={}
            for row in bars:
                days[row["date"]]=days.get(row["date"],0)+1
            result={
                "format":FORMAT,"status":"TENCENT_REAL_M1_OHLCV_NO_AMOUNT",
                "symbol":symbol,"count":len(bars),"source_url":url,
                "source_json_path":str(path),"source_sha256":digest,
                "ohlcv_only_parquet_path":str(target),
                "ohlcv_only_parquet_sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
                "first_cn":bars[0]["date"]+" "+bars[0]["local_time"],
                "last_cn":bars[-1]["date"]+" "+bars[-1]["local_time"],
                "bars_per_day":days,"source_volume_unit":bars[0]["source_volume_unit"],
                "amount_cny_available":False,"full_1min_ohlcva_certified":False,
                "source_field_7_is_turnover_rate_not_amount":True,
                "sh_sz_only":True,"current_market_parquet_modified":False,
                "original_h5_modified":False}
            logger("PASS_TENCENT_REAL_1MIN_OHLCV_SOURCE "+
                   json.dumps({"stock":symbol,"bars":len(bars),"days":days,
                               "has_amount":False},ensure_ascii=False))
            return result
        except (ValueError,RuntimeError,OSError,urllib.error.URLError) as exc:
            failures.append(f"{host}: {type(exc).__name__}: {str(exc)[:150]}")
            logger(f"TENCENT_1MIN_HOST_FAILED {symbol} {host} {type(exc).__name__}")
            if pause>0:time.sleep(pause)
    raise RuntimeError("Tencent all three 1min hosts unavailable: "+"; ".join(failures))

def collect_samples(symbols,*,logger=print,stop=None,
                    collector=collect,**kwargs):
    """Small GUI-friendly sequential SH/SZ true 1min OHLCV samples."""
    results={}
    errors={}
    for symbol in symbols:
        if stop is not None and stop():
            break
        try:
            value=market_symbol(symbol)
            results[value]=collector(value,logger=logger,**kwargs)
        except Exception as exc:
            errors[str(symbol)]={"error":str(exc)[:350],
                                 "market_written":False}
            logger(f"TENCENT_REAL_1MIN_NOT_VERIFIED {symbol} {str(exc)[:180]}")
    status=("TENCENT_1MIN_OHLCV_CANDIDATES_COLLECTED"
            if not errors and len(results)==len(symbols) else
            "TENCENT_1MIN_PARTIAL_CANDIDATES_NOT_MERGED")
    return {"format":FORMAT,"status":status,
            "symbols_verified":sorted(results),
            "samples":results,"failures":errors,
            "requested_symbols":list(symbols),
            "full_1min_ohlcva_certified":False,
            "amount_cny_available":False,
            "market_files_modified":False,
            "original_h5_modified":False}

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol",default="SH600000")
    p.add_argument("--count",type=int,default=320)
    args=p.parse_args()
    print(json.dumps(collect(args.symbol,count=args.count),
                     ensure_ascii=False,sort_keys=True))
