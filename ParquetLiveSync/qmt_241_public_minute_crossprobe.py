#!/usr/bin/env python3
"""Read-only public Sina/Tencent m1 availability for QMT 241 opening research.

Only SHA-verified, preapproved 2026-10-14..16 QMT/eltdx anchor stock-days.
Public responses stay in memory, no licensed OHLCVA printed or uploaded.
No assumption that a public source retains 2026-10-16 or separates auction.
Never modify market Parquet/H5. No file output.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date,datetime
import json
import math
import re
import urllib.parse
import urllib.request

import pyarrow.parquet as pq
import local_layout as L
import qmt_1m_pipeline as P
import qmt_eltdx_1m_probe as X
import qmt_eltdx_auction_241_probe as A
import qmt_eltdx_opening_tick_alignment as J

FORMAT="qmt_public_sina_tencent_m1_source_provenance_readonly_v1"
CODES=("688001.SH","600000.SH","000001.SZ")
DAYS=(date(2026,10,14),date(2026,10,15),date(2026,10,16))
MAX_BYTES=8*1024*1024
STAMP=re.compile(r"(20\d{2})-?(\d{2})-?(\d{2})[ T]?(\d{2}):?(\d{2})")
OHLC=("open","high","low","close")


def source_url(provider,code):
    if code not in CODES:
        raise ValueError("Stock outside 3 allowed anchors")
    name=code[-2:].lower()+code[:6]
    if provider=="sina":
        base="https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"
        query=urllib.parse.urlencode({"symbol":name,"scale":"1",
                                     "ma":"no","datalen":"20000"})
    elif provider=="tencent":
        base="https://web.ifzq.gtimg.cn/appstock/app/kline/mkline"
        query=urllib.parse.urlencode({"param":name+",m1,,20000"})
    else:
        raise ValueError("Unsupported public source")
    return base+"?"+query


def fetch_text(url,timeout=12):
    parts=urllib.parse.urlparse(url)
    if parts.scheme!="https" or parts.hostname not in (
        "quotes.sina.cn","web.ifzq.gtimg.cn"):
        raise ValueError("Unapproved public source host")
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (research read-only; source probe)",
        "Accept":"application/json,text/plain,*/*"})
    with urllib.request.urlopen(req,timeout=timeout) as result:
        host=urllib.parse.urlparse(result.geturl()).hostname
        if host not in ("quotes.sina.cn","web.ifzq.gtimg.cn"):
            raise ValueError("Unexpected public source redirect")
        data=result.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:
            raise ValueError("Public response over read limit")
        return data.decode("utf-8-sig")


def decode_time(raw):
    match=STAMP.search(str(raw))
    if match is None:
        raise ValueError("Invalid minute timestamp")
    return datetime(*(int(x) for x in match.groups()))


def parse_rows(provider,text,code):
    if provider=="sina":
        # JSONP of the form SinaCall=([{"day":..., ...}]);
        index=text.find("[")
        if index<0:
            raise ValueError("Sina returned no JSON minute array")
        data,_=json.JSONDecoder().raw_decode(text[index:])
        if not isinstance(data,list):
            raise ValueError("Unexpected Sina response")
        def unpack(r):
            return r["day"],r
    elif provider=="tencent":
        doc=json.loads(text)
        symbol=code[-2:].lower()+code[:6]
        data=doc.get("data",{}).get(symbol,{}).get("m1",[])
        if not isinstance(data,list):
            raise ValueError("Unexpected Tencent response")
        def unpack(r):
            return r[0],{"open":r[1],"close":r[2],"high":r[3],
                         "low":r[4],"volume":r[5] if len(r)>5 else None,
                         "amount":r[6] if len(r)>6 else None}
    else:
        raise ValueError("Unsupported public source")
    result=[];bad=0
    for row in data:
        try:
            stamp,item=unpack(row)
            dt=decode_time(stamp)
            p={k:float(item[k]) for k in OHLC}
            if (not all(math.isfinite(v) and v>0 for v in p.values())
                or p["high"]<max(p["open"],p["close"],p["low"])-.0001
                or p["low"]>min(p["open"],p["close"],p["high"])+.0001):
                raise ValueError("Invalid public price data")
            result.append({"date":dt.date(),"minute":dt.hour*60+dt.minute,
                           **p,"amount_present":item.get("amount") not in (None,"")})
        except (ValueError,KeyError,IndexError,TypeError):
            bad+=1
    result.sort(key=lambda r:(r["date"],r["minute"]))
    return result,{"fetched":len(data),"parsed":len(result),"invalid":bad,
                   "earliest":str(result[0]["date"]) if result else None,
                   "latest":str(result[-1]["date"]) if result else None}


def evaluate(day,rows,qmt,tdx):
    q=A.day_rows(qmt,day);t=A.day_rows(tdx,day)
    if len(q)!=241 or len(t)!=240:
        raise ValueError("Original paid anchor not 241/240")
    observed=[r for r in rows if r["date"]==day]
    slots=Counter(r["minute"] for r in observed)
    first=next((r for r in observed if r["minute"]==570),None)
    regular=next((r for r in observed if r["minute"]==571),None)
    if not observed:
        return {"status":"TARGET_DATE_UNAVAILABLE","bars":0,
                "independent_high_candidate":False}
    if max(slots.values())>1:
        return {"status":"DUPLICATE_MINUTE_LABELS","bars":len(observed),
                "independent_high_candidate":False}
    if regular is None:
        return {"status":"NO_0931_LABEL","bars":len(observed),
                "independent_high_candidate":False}
    q_regular=q[1];native=t[0]
    matches={k:J.strict_fit(regular[k],q_regular[k],k) for k in OHLC}
    unequal_native=not J.strict_fit(regular["high"],native["high"],"high")
    status=("HIGH_CANDIDATE_MATCHES_QMT_AND_DIFFERS_MERGED"
            if matches["high"] and unequal_native else
            "PUBLIC_0931_HIGH_IS_MERGED" if
            J.strict_fit(regular["high"],native["high"],"high")
            else "PUBLIC_SOURCE_DIFFERENCE_OR_TIME_ALIGNMENT_UNKNOWN")
    return {
        "status":status,"bars":len(observed),
        "first_five_labels":[f"{n//60:02d}:{n%60:02d}" for n in sorted(slots)[:5]],
        "has_0930":first is not None,"has_0931":True,
        "0930_ohlc_strict_match_qmt_auction":
            all(J.strict_fit(first[k],q[0][k],k) for k in OHLC)
            if first is not None else None,
        "0931_ohlc_strict_match_qmt_regular":matches,
        "0931_high_differs_tdx_merged":unequal_native,
        "0931_high_equals_qmt_auction":
            J.strict_fit(regular["high"],q[0]["high"],"high"),
        "independent_high_candidate":bool(matches["high"] and unequal_native),
        "provider_0931_amount_present":regular["amount_present"],
        "provider_241_grid":len(observed)==241,
        "source_vendor_independence_unverified":True,
        "production_merge_authorized":False}


def run(*,codes=("688001.SH",),days=DAYS,fetcher=fetch_text,logger=print):
    if (not codes or len(codes)>len(CODES) or len(set(codes))!=len(codes)
        or any(c not in CODES for c in codes)):
        raise ValueError("Only 3 SHA-verified research symbols")
    if (not days or len(days)>len(DAYS) or len(set(days))!=len(days)
        or any(d not in DAYS for d in days)):
        raise ValueError("Only 2026-10-14/15/16 research dates")
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    statuses=Counter()
    for code in codes:
        receipt=X.verified_cache(folder,code,stage,remote_only=False)
        qmt,qsha=X.read_qmt_source(stage,code)
        path=folder/"source_parquet"/(code.replace(".","_")+".parquet")
        if (not receipt or not qmt or path.is_symlink()
            or L.hash_file(path)!=receipt["source_sha256"]):
            raise ValueError("Original QMT/Tongdaxin SHA or receipt changed")
        table=pq.read_table(path)
        if table.schema!=P.PRIVATE_SCHEMA:
            raise ValueError("Original 7709 Arrow schema changed")
        tdx=table.to_pylist()
        for d in days:
            if len(A.day_rows(qmt,d))!=241 or len(A.day_rows(tdx,d))!=240:
                raise ValueError("Original daily bar grid incomplete")
        for provider in ("sina","tencent"):
            error=None
            try:
                body=fetcher(source_url(provider,code))
                rows,meta=parse_rows(provider,body,code)
                if meta["invalid"]:
                    raise ValueError("Public minute response has corrupt rows")
            except Exception as exc:
                rows=[];meta={"fetched":0,"earliest":None,"latest":None}
                error=type(exc).__name__+":"+str(exc)[:120]
            for d in days:
                info=evaluate(d,rows,qmt,tdx) if error is None else {
                    "status":"PUBLIC_SOURCE_UNAVAILABLE",
                    "provider_error":error,"independent_high_candidate":False}
                statuses[info["status"]]+=1
                logger("PUBLIC_241_MINUTE_CASE="+json.dumps({
                    "stock":code,"day":str(d),"source":provider,
                    "source_history":meta,"result":info,
                    "market_files_modified":False,
                    "production_merge_authorized":False},
                    sort_keys=True,ensure_ascii=False))
    summary={
        "format":FORMAT,"cases":len(codes)*2*len(days),
        "statuses":dict(statuses),"max_requests":len(codes)*2,
        "raw_market_rows_saved_or_uploaded":False,
        "market_files_modified":False,"production_merge_authorized":False}
    logger("PUBLIC_241_MINUTE_SUMMARY="+json.dumps(summary,sort_keys=True))
    return summary


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--codes",default="688001.SH")
    p.add_argument("--days",default="2026-10-14,2026-10-15,2026-10-16")
    a=p.parse_args()
    run(codes=tuple(v.strip().upper() for v in a.codes.split(",")),
        days=tuple(date.fromisoformat(v.strip()) for v in a.days.split(",")))
