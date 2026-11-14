#!/usr/bin/env python3
"""Bounded read-only public minute source recovery: Sina and Tencent alternates.

Tests HTTPS transport and documented alternate endpoints and separately reports:
network/TLS failure, non-array schema, returned recent bars but target history
missing, or actual 2026-10-16 independently split 09:31 high evidence.
Existing SHA-pinned QMT 241 is validation-only; local paid originals stay intact.
In-memory only; no market values or response bodies in logs; no .parquet writes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import re
from urllib.parse import urlencode,urlparse
from urllib.request import Request,urlopen

import pyarrow.parquet as pq

import local_layout as L
import qmt_1m_pipeline as P
import qmt_eltdx_1m_probe as X
import qmt_eltdx_auction_241_probe as A
import qmt_241_public_minute_crossprobe as V

FORMAT="public_241_sina_tencent_endpoint_alternates_readonly_v2"
CODE="688001.SH"
DAY=date(2026,10,16)
MAX_RESPONSE=8*1024*1024
HOSTS={"quotes.sina.cn","proxy.finance.qq.com","web.ifzq.gtimg.cn"}
VARIANTS={
    "sina":[
        ("sina_jsonp_1970","https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData",
         {"symbol":"sh688001","scale":"1","ma":"no","datalen":"1970"}),
        ("sina_json_1023","https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData",
         {"symbol":"sh688001","scale":"1","ma":"no","datalen":"1023"}),
    ],
    "tencent":[
        ("tencent_proxy_8000","https://proxy.finance.qq.com/ifzqgtimg/appstock/app/kline/mkline",
         {"param":"sh688001,m1,,8000"}),
        ("tencent_direct_800","https://web.ifzq.gtimg.cn/appstock/app/kline/mkline",
         {"param":"sh688001,m1,,800"}),
    ],
}


def requests_for(provider):
    return [(name,url+"?"+urlencode(params))
            for name,url,params in VARIANTS[provider]]


def load(url,timeout=10):
    p=urlparse(url)
    if p.scheme!="https" or p.hostname not in HOSTS:
        raise ValueError("Only three pre-approved HTTPS market hosts")
    req=Request(url,headers={
        "User-Agent":"Mozilla/5.0",
        "Referer":"https://finance.sina.com.cn/"
                  if p.hostname=="quotes.sina.cn" else
                  "https://gu.qq.com/",
        "Accept":"application/json,text/javascript,text/plain,*/*"})
    with urlopen(req,timeout=timeout) as response:
        final=urlparse(response.geturl())
        if final.scheme!="https" or final.hostname not in HOSTS:
            raise ValueError("Unapproved redirect")
        raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:
            raise ValueError("Too-large public endpoint response")
        return raw.decode("utf-8-sig",errors="replace")


def classify(text):
    compact=text.lstrip()
    if not compact:
        return "EMPTY_BODY"
    if compact.startswith("<"):
        return "HTML_OR_GATEWAY_ERROR"
    if compact.startswith("["):
        return "JSON_ARRAY"
    if compact.startswith("{"):
        return "JSON_OBJECT"
    if re.search(r"=\s*\(",compact[:256]):
        return "JSONP_CALL"
    if compact.startswith(("null","undefined")):
        return "NULL_RESPONSE"
    return "UNRECOGNIZED_BODY"


def parse_sina(text):
    kind=classify(text)
    if kind=="JSON_ARRAY":
        rows=json.loads(text)
    elif kind=="JSONP_CALL":
        m=re.search(r"=\s*\(\s*(\[.*?\])\s*\)\s*;?\s*$",text,re.S)
        if not m:
            raise ValueError("NONARRAY_JSONP_RESPONSE")
        rows=json.loads(m.group(1))
    else:
        raise ValueError("NONARRAY_SINA_"+kind)
    if not isinstance(rows,list):
        raise ValueError("NONLIST_SINA")
    # Use the earlier, SHA-tested date and OHLC parser on canonical JSONP.
    return V.parse_rows("sina","cb=("+json.dumps(rows)+");",CODE)


def parse(provider,raw):
    if provider=="sina":
        return parse_sina(raw)
    if classify(raw)!="JSON_OBJECT":
        raise ValueError("TENCENT_"+classify(raw))
    return V.parse_rows("tencent",raw,CODE)


def test_api(*,provider,fetcher=load,logger=print):
    attempts=[]
    chosen=None
    for ident,url in requests_for(provider):
        try:
            raw=fetcher(url)
            body_class=classify(raw)
            rows,meta=parse(provider,raw)
            if meta["invalid"]:
                raise ValueError("Provider returned invalid OHLC rows")
            has_day=any(r["date"]==DAY for r in rows)
            entry={"endpoint":ident,"status":(
                "TARGET_DATE_IN_HISTORY" if has_day else
                "HISTORY_RECEIVED_BUT_TARGET_ABSENT" if rows
                else "PARSED_EMPTY_HISTORY"),"body_class":body_class,
                "parsed":len(rows),"earliest":meta["earliest"],
                "latest":meta["latest"],
                "contains_target":has_day}
            attempts.append(entry)
            if chosen is None or has_day:
                chosen=(rows,ident)
            if has_day:
                break
        except Exception as exc:
            # Never print the source payload or its bytes. Distinguish TLS
            # from provider schema errors via class and sanitized summary.
            name=type(exc).__name__
            category=("NETWORK_TLS_OR_TRANSPORT" if name in
                      ("URLError","SSLError","TimeoutError","HTTPError",
                       "ConnectionResetError") else "INVALID_PROVIDER_RESPONSE")
            attempts.append({"endpoint":ident,"status":category,
                             "error_type":name,
                             "error_summary":str(exc)[:140]})
    return chosen,attempts


def run(*,fetcher=load,logger=print):
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    cached=X.verified_cache(folder,CODE,stage,remote_only=False)
    q,sha=X.read_qmt_source(stage,CODE)
    path=folder/"source_parquet"/(CODE.replace(".","_")+".parquet")
    if (not cached or not q or path.is_symlink()
        or L.hash_file(path)!=cached["source_sha256"]):
        raise ValueError("SHA verified 240/241 source missing")
    table=pq.read_table(path)
    if table.schema!=P.PRIVATE_SCHEMA:
        raise ValueError("Original 240 Arrow schema changed")
    t=table.to_pylist()
    if len(A.day_rows(q,DAY))!=241 or len(A.day_rows(t,DAY))!=240:
        raise ValueError("Original day is not complete 241/240")
    counts=Counter()
    for provider in ("sina","tencent"):
        payload,attempts=test_api(provider=provider,fetcher=fetcher,logger=logger)
        if payload is None:
            evidence={"status":"NO_USABLE_PUBLIC_HISTORY",
                      "independent_high_candidate":False}
        else:
            rows,endpoint=payload
            evidence=V.evaluate(DAY,rows,q,t)
            evidence["endpoint_used"]=endpoint
        counts[evidence["status"]]+=1
        logger("PUBLIC_241_RECOVERY_SOURCE="+json.dumps({
            "provider":provider,"stock":CODE,"day":str(DAY),
            "attempts":attempts,"qmt_validation_only":evidence,
            "market_files_modified":False,"production_merge_authorized":False},
            ensure_ascii=False,sort_keys=True))
    summary={"format":FORMAT,"stocks":1,"target_day":str(DAY),
             "max_public_http_requests":4,
             "source_statuses":dict(counts),
             "raw_public_or_paid_OHLCVA_logged":False,
             "source_files_modified":False,"production_merge_authorized":False}
    logger("PUBLIC_241_RECOVERY_SUMMARY="+json.dumps(summary,sort_keys=True))
    return summary


if __name__=="__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
