#!/usr/bin/env python3
"""Public TDX official ZIP source-quality probe (read-only, no Parquet writes).

The probe never reads paid local stock data or modifies the real market
dataset. Supply --zip for a previously downloaded private rejected package
or --date to probe one public official dated ZIP via the network. The
published .cod/.md1 binary schema is based on a-stock-data v3.10.4.
"""
from __future__ import annotations

import argparse
from datetime import date
import io
import json
from pathlib import Path
import struct
import urllib.request
import zipfile

from tdx_source import (
    TDX_URL,ZIP_MAX,is_equity,parse_daily_zip,sha256,
)

def counters(raw,day):
    answer={}
    key=day.strftime("%Y%m%d")[2:]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for market in ("sh","sz","bj"):
            cod_name=f"{market}{key}.cod"
            quote_name=f"{market}{key}.md1"
            if cod_name not in z.namelist() or quote_name not in z.namelist():
                answer[market]={"missing_source":True}
                continue
            cod,md1=z.read(cod_name),z.read(quote_name)
            stats={"priced_equities":0,"zero_volume_zero_amount":0,
                   "traded_nonpositive_close":0,
                   "traded_invalid_price_grid":0,
                   "volume_amount_disagree":0,
                   "examples":[]}
            for offset in range(0,len(cod)-149,150):
                rec=cod[offset:offset+150]
                code=rec[:6].decode("ascii","replace")
                if not is_equity(market,code,day.year):
                    continue
                index=struct.unpack_from("<H",rec,32)[0]
                b=md1[index*512:(index+1)*512]
                if len(b)<512:
                    continue
                open_,high,low,close=struct.unpack_from("<4d",b,12)
                volume=struct.unpack_from("<Q",b,56)[0]
                amount=struct.unpack_from("<d",b,72)[0]
                if close>0:
                    stats["priced_equities"]+=1
                category=None
                if close<=0 and (volume or amount):
                    category="traded_nonpositive_close"
                elif close>0 and volume==0 and amount==0:
                    category="zero_volume_zero_amount"
                elif close>0 and (not volume or amount<=0):
                    category="volume_amount_disagree"
                elif close>0 and (min(open_,high,low,close)<=0
                     or low>min(open_,close)+0.0001
                     or high+0.0001<max(open_,close)
                     or low>high+0.0001):
                    category="traded_invalid_price_grid"
                if category:
                    stats[category]+=1
                    if len(stats["examples"])<15:
                        stats["examples"].append({
                            "symbol":market.upper()+code,"category":category,
                            "o":open_,"h":high,"l":low,"c":close,
                            "volume_shares":volume,"amount_yuan":amount})
            answer[market]=stats
    return answer

def run(day,zip_path=None):
    if zip_path:
        source=Path(zip_path)
        if source.is_symlink() or not source.is_file():
            raise ValueError("Untrusted or missing diagnostic source ZIP")
        raw=source.read_bytes()
    else:
        url=TDX_URL.format(ymd=day.strftime("%Y%m%d"))
        with urllib.request.urlopen(url,timeout=22) as resp:
            raw=resp.read(ZIP_MAX+1)
    if not 10<len(raw)<=ZIP_MAX or not raw.startswith(b"PK"):
        raise ValueError("Official ZIP corrupted or exceeds source size limit")
    report={"date":day.isoformat(),"public_raw_zip_sha256":sha256(raw),
            "market_source_quote_diagnostics":counters(raw,day)}
    try:
        bars,meta=parse_daily_zip(raw,day)
        report["strict_source_accepted"]=True
        report["accepted_equities"]=len(bars)
        report["skipped_nontrading_a_shares"]=meta.get(
            "zero_turnover_nontrading_a_shares_by_market",{})
    except ValueError as exc:
        report["strict_source_accepted"]=False
        report["strict_source_error"]=str(exc)
    print(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2))
    return 0 if report["strict_source_accepted"] else 2

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date",required=True,help="Source date YYYY-MM-DD")
    p.add_argument("--zip",type=Path,default=None,
                   help="Optional existing rejected private raw ZIP; otherwise public HTTPS")
    args=p.parse_args()
    raise SystemExit(run(date.fromisoformat(args.date),args.zip))

if __name__=="__main__":
    main()
