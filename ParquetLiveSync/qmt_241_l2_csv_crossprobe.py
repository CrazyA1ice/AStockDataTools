#!/usr/bin/env python3
"""Strict read-only untrusted public L2 CSV 2026-10-16 688001.SH research.

Requires a locally extracted trade CSV; NEVER downloads archives, launches
executables, infers price scales from QMT, or writes market files. This is a
SCHEMA-BOUND probe, not a blanket guarantee of third-party provenance. Unknown
event codes are excluded, and matching volume does not guarantee full extrema.
Only OHLCVA match flags, 09:25 vs 09:30 coverage, SHA are printed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import csv
import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq
import local_layout as L
import qmt_1m_pipeline as P
import qmt_eltdx_1m_probe as X
import qmt_eltdx_auction_241_probe as A
import qmt_eltdx_opening_tick_alignment as J

FORMAT="qmt_241_l2_csv_untrusted_source_readonly_v1"
TARGET_DAY=date(2026,10,16)
CODE="688001.SH"
MAX_BYTES=512*1024*1024
HEADERS=("万得代码","自然日","时间","成交代码","成交价格","成交数量")
FIELDS=("open","high","low","close","volume","amount")


def timestamp(raw):
    t=str(raw).strip().split(".")[0]
    if not t.isdigit() or len(t) not in (8,9):
        raise ValueError("Unsupported L2 integer HHMMSSmmm clock")
    v=t.zfill(9)
    h,m,s,ms=int(v[:2]),int(v[2:4]),int(v[4:6]),int(v[6:])
    if h>23 or m>59 or s>59 or ms>999:
        raise ValueError("Invalid L2 trade clock")
    return h*3600+m*60+s+ms/1000


def hash_file(file):
    sha=hashlib.sha256()
    with file.open("rb") as stream:
        for part in iter(lambda:stream.read(1024*1024),b""):
            sha.update(part)
    return sha.hexdigest()


def read_tick_csv(file,*,day=TARGET_DAY,code=CODE,price_divisor=10000):
    file=Path(file)
    if (file.is_symlink() or file.suffix.lower()!=".csv"
        or not file.is_file()):
        raise ValueError("Only an actual local CSV file, no symlinks or archives")
    size=file.stat().st_size
    if size<=0 or size>MAX_BYTES:
        raise ValueError("L2 individual stock-day CSV outside bounded size")
    if not math.isfinite(float(price_divisor)) or price_divisor<=0:
        raise ValueError("Invalid caller-selected price divisor")
    stat=file.stat()
    digest=hash_file(file)
    records=[];codes=Counter()
    # A sample uses UTF-8; many real Wind-like exports are GB18030.
    for encoding in ("utf-8-sig","gb18030"):
        try:
            with file.open("r",encoding=encoding,newline="") as stream:
                reader=csv.DictReader(stream,strict=True)
                if not reader.fieldnames or not set(HEADERS).issubset(reader.fieldnames):
                    raise ValueError("Unrecognized L2 schema, inspect CSV header")
                for i,row in enumerate(reader):
                    if i>4_000_000:
                        raise ValueError("L2 stock-day record cap exceeded")
                    if (row.get("万得代码","").strip().upper()!=code
                        or row.get("自然日","").strip()!=f"{day:%Y%m%d}"):
                        raise ValueError("Wrong stock or date inside L2 file")
                    kind=row["成交代码"].strip()
                    codes[kind]+=1
                    if kind!="0":
                        # Wind-like demonstration maps 0 to execution, C to
                        # cancellation. Real archives MUST independently verify.
                        continue
                    ts=timestamp(row["时间"])
                    px=float(row["成交价格"])/float(price_divisor)
                    shares=float(row["成交数量"])
                    if (not math.isfinite(px) or not math.isfinite(shares)
                        or px<=0 or shares<=0):
                        raise ValueError("Invalid L2 execution price or quantity")
                    if 9*3600+24*60<=ts<9*3600+26*60 or (
                        9*3600+30*60<=ts<9*3600+32*60):
                        records.append((ts,px,shares))
            break
        except UnicodeDecodeError:
            if encoding=="gb18030":
                raise
            records.clear();codes.clear()
            continue
    if file.stat().st_size!=stat.st_size or file.stat().st_mtime_ns!=stat.st_mtime_ns:
        raise ValueError("Local third-party L2 file changed during read")
    if hash_file(file)!=digest:
        raise ValueError("Local L2 CSV hash changed during read")
    return records,{
        "sha256":digest,"bytes":size,"event_code_counts":dict(codes),
        "trade_code_0_is_assumed_only_not_independently_certified":True,
        "price_divisor_user_selected_not_auto_inferred":price_divisor,
        "time_format_assumed":"HHMMSSmmm",
        "source_vendor_and_completeness_unverified":True}


def bucket(rows,begin,end):
    valid=[(ts,p,v) for ts,p,v in rows if begin<=ts<end]
    if not valid:
        return None
    return {"records":len(valid),
            "first":valid[0][1],"last":valid[-1][1],
            "high":max(p for _,p,_ in valid),
            "low":min(p for _,p,_ in valid),
            "shares":sum(v for _,p,v in valid),
            "amount_derived":sum(p*v for _,p,v in valid),
            "nondecreasing_time":all(a[0]<=b[0] for a,b in zip(valid,valid[1:]))}


def compare(rows,q,t):
    if len(q)!=241 or len(t)!=240 or A.label(q[0])!=(9,30) or A.label(q[1])!=(9,31):
        raise ValueError("Original SHA QMT/TDX day grid not complete")
    a=bucket(rows,9*3600+25*60,9*3600+26*60)
    r=bucket(rows,9*3600+30*60,9*3600+31*60)
    subsequent=bucket(rows,9*3600+31*60,9*3600+32*60)
    if r is None:
        return {"status":"NO_REGULAR_0930_L2_EXECUTIONS",
                "L2_first_minute_complete_certified":False}
    qa,qr,native=q[0],q[1],t[0]
    expected_shares=float(qr["volume"])*100
    fits={
        "regular_0931_open":J.strict_fit(r["first"],qr["open"],"open"),
        "regular_0931_high":J.strict_fit(r["high"],qr["high"],"high"),
        "regular_0931_low":J.strict_fit(r["low"],qr["low"],"low"),
        "regular_0931_close":J.strict_fit(r["last"],qr["close"],"close"),
        "regular_0931_volume_shares":J.strict_fit(
            r["shares"],expected_shares,"volume"),
        "regular_0931_amount_strict":J.strict_fit(
            r["amount_derived"],qr["amount"],"amount"),
    }
    auction=({
        "volume_strict":J.strict_fit(a["shares"],
                                     qa["volume"]*100,"volume"),
        "price_strict":J.strict_fit(a["high"],qa["open"],"open"),
        "amount_strict":J.strict_fit(a["amount_derived"],
                                     qa["amount"],"amount"),
    } if a else None)
    return {
        "status":"OBSERVED_L2_EXTREMA_MATCH_QMT_0931"
                 if fits["regular_0931_high"] and fits["regular_0931_low"]
                 else "OBSERVED_L2_EXTREMA_DIFFER_FROM_QMT",
        "regular_0930_trade_count":r["records"],
        "historical_0931_record_count":subsequent["records"] if subsequent else 0,
        "auction_0925_trade_count":a["records"] if a else 0,
        "regular_0931_matches":fits,
        "formal_0925_matches":auction,
        "source_0931_high_differs_from_tdx_merged":
            not J.strict_fit(r["high"],native["high"],"high"),
        "source_time_order_nondecreasing":r["nondecreasing_time"],
        "source_time_order_not_trade_sequence_certified":True,
        "L2_first_minute_complete_certified":False,
        "price_extrema_sample_matches_not_authorized_for_production":True,
        "production_merge_authorized":False}


def run(*,file,day=TARGET_DAY,code=CODE,divisor=10000,logger=print):
    if day!=TARGET_DAY or code!=CODE:
        raise ValueError("Only 688001.SH 2026-10-16 actual gap permitted")
    stage=P.BASE/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    folder=X.WORK/f"{X.START:%Y%m%d}_{X.END:%Y%m%d}"
    receipt=X.verified_cache(folder,code,stage,remote_only=False)
    qrows,qsha=X.read_qmt_source(stage,code)
    path=folder/"source_parquet"/(code.replace(".","_")+".parquet")
    if (not receipt or not qrows or path.is_symlink()
        or L.hash_file(path)!=receipt["source_sha256"]):
        raise ValueError("Original QMT and eltdx 240 SHA anchor changed")
    original=pq.read_table(path)
    if original.schema!=P.PRIVATE_SCHEMA:
        raise ValueError("Original eltdx Arrow schema mismatch")
    q=A.day_rows(qrows,day)
    t=A.day_rows(original.to_pylist(),day)
    # Never use QMT to infer the divisor or select accepted event types.
    raw,meta=read_tick_csv(file,day=day,code=code,price_divisor=divisor)
    result=compare(raw,q,t)
    logger("PUBLIC_L2_241_CROSSCHECK="+json.dumps({
        "stock":code,"day":str(day),"file_sha256":meta["sha256"],
        "source_meta":meta,"result":result,
        "licensed_market_values_not_printed":True,
        "file_writes":False,"production_merge_authorized":False},
        ensure_ascii=False,sort_keys=True))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv",required=True,help="Local extracted 688001.SH 20261016 逐笔成交.csv")
    p.add_argument("--price-divisor",type=float,default=10000)
    args=p.parse_args()
    run(file=args.csv,divisor=args.price_divisor)
