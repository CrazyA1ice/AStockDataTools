#!/usr/bin/env python3
"""Read-only agreement gate: Eastmoney 5/15/30/60m vs original PURCHASED.

A real day of purchased minute Parquet (2026-09-30 by default) must match
the independent public Kline provider's time labels, prices, volume and
amount, separately for each period and multiple markets. Unit multipliers
are inferred from overlapping actual trades, NEVER assumed from the daily
Parquet factor or the public API's descriptions. Results are SHA-pinned.

NO production month/H5 writes. Gate proof is needed before bulk joins.
"""
from __future__ import annotations

from datetime import date,datetime,timedelta
import json
import math
from pathlib import Path
import statistics

import pyarrow as pa
import pyarrow.parquet as pq

from live_sync import CN,WORK,source_day_ts
import local_layout as L
from minute_history import collect_one,PERIODS_OHLCVA,SOURCE_ROOT

CAL_DAY=date(2026,9,30)
SYMBOLS=("SH600000","SZ000001","BJ920021")
FORMAT="minute_purchased_cross_provider_ohlcva_gate_v1"
MIN_COMMON={"5min":65,"15min":24,"30min":13,"60min":7}
AMOUNT_FACTORS=(.0001,.01,.1,1.,10.,100.,10000.)
VOLUME_FACTORS=(.0001,.01,.1,1.,10.,100.,1000.,10000.)

def source_day_rows(root,period,day,symbols):
    root=L.storage_root(root)
    p=root/period/(f"{day.year}-{day.month:02}.parquet")
    if not p.is_file() or p.is_symlink():
        raise ValueError(f"Missing real purchased {period} {day.year}-{day.month:02} source")
    lo=source_day_ts(day)
    hi=lo+86400000
    selected=pq.read_table(p,columns=list(L.COLS),
                           filters=[("ts",">=",lo),("ts","<",hi)])
    L.validate_schema(selected.schema)
    wanted=set(symbols)
    rows={}
    for item in selected.to_pylist():
        sym=L.normal_symbol(item["symbol"])
        if sym not in wanted:
            continue
        ts=int(item["ts"])
        key=(sym,ts)
        if key in rows:
            raise ValueError("Duplicate original purchased minute timestamp/stock")
        rows[key]=item
    if not rows:
        raise ValueError("Cannot find sample equities in purchased minute month")
    return rows,p,L.hash_file(p)

def factor_agreement(pairs,attribute,factors,*,threshold=.82):
    """Pick unique scalar by independently measured real key overlap."""
    source_attr="provider_volume" if attribute=="volume" else "amount_yuan"
    matches=[(float(original[attribute]),float(source[source_attr]))
             for original,source in pairs
             if original[attribute]>0 and source[source_attr]>0]
    if len(matches)<6:
        raise ValueError("Insufficient nonzero historical amount/volume overlap")
    results=[]
    for factor in factors:
        good=0
        for original,external in matches:
            if math.isclose(original,external*factor,rel_tol=.035,
                            abs_tol=.1 if attribute=="volume" else 100.):
                good+=1
        results.append((good/len(matches),factor))
    results.sort(reverse=True)
    best,unit=results[0]
    if best<threshold or (len(results)>1 and best-results[1][0]<.15):
        raise ValueError(
            f"{attribute.upper()}_UNITS_NOT_PROVED best_fit={best:.4f} "
            f"best_factor={unit} second_fit={results[1][0]:.4f}")
    return {"factor":unit,"fit":round(best,5),"samples":len(matches)}

def time_candidate_offsets(period):
    minutes=int(period[:-3])
    return tuple(60_000*minutes*n for n in (-2,-1,0,1,2))

def pair_and_calibrate(period,source,original):
    if period not in PERIODS_OHLCVA:
        raise ValueError("Never calibrate trends2 1min as full OHLCVA Kline")
    source=[x for x in source if (x["symbol"],x["ts"]) not in set()]
    if not source:
        raise ValueError("No public source minute overlap candidates")
    scored=[]
    for offset in time_candidate_offsets(period):
        paired=[]
        for bar in source:
            old=original.get((bar["symbol"],bar["ts"]+offset))
            if old is not None:
                paired.append((old,bar))
        if not paired:
            continue
        price=0
        for old,bar in paired:
            if all(math.isclose(float(old[key]),float(bar[key]),
                                rel_tol=.005,abs_tol=.03)
                   for key in ("open","high","low","close")):
                price+=1
        score=price
        scored.append((score,len(paired),-abs(offset),offset,paired))
    if not scored:
        raise ValueError("Purchased and public source minute timestamps have zero overlap")
    scored.sort(reverse=True)
    score,n,_,offset,pairs=scored[0]
    price_fit=score/n
    minimum=MIN_COMMON[period]
    if n<minimum or price_fit<.93:
        raise ValueError(
            f"{period} PAID_PUBLIC_PRICE_OR_TIME_UNVERIFIED "
            f"paired={n} required={minimum} price_fit={price_fit:.4f}")
    if len(scored)>1 and scored[1][0]>=score*.95:
        raise ValueError(f"{period} timestamp offset ambiguous between historical sources")
    price_pairs=[pair for pair in pairs
                 if all(math.isclose(float(pair[0][field]),
                                     float(pair[1][field]),
                                     rel_tol=.005,abs_tol=.03)
                        for field in ("open","high","low","close"))]
    volume=factor_agreement(price_pairs,"volume",VOLUME_FACTORS)
    amount=factor_agreement(price_pairs,"amount",AMOUNT_FACTORS)
    symbols=sorted(set(x["symbol"] for _,x in pairs))
    if len(symbols)<2:
        raise ValueError("Cross-market minute time/price calibration has fewer than two stocks")
    return {"period":period,
            "timestamp_offset_source_to_purchased_ms":offset,
            "source_volume_to_purchased_factor":volume["factor"],
            "source_amount_to_purchased_factor":amount["factor"],
            "time_price_overlap":n,
            "price_fit":round(price_fit,6),
            "volume_fit":volume["fit"],"amount_fit":amount["fit"],
            "symbols_validated":symbols,
            "local_original_values_preserved":True,
            "limited_sample_not_full_market_approved":True}

def run(root,*,periods=PERIODS_OHLCVA,symbols=SYMBOLS,
        day=CAL_DAY,logger=print,collector=collect_one):
    root=Path(root)
    result={"format":FORMAT,"calibration_day":day.isoformat(),
            "periods":{},"failed":{},
            "production_market_files_modified":False}
    for period in periods:
        try:
            original,path,paid_sha=source_day_rows(root,period,day,symbols)
            bars=[]
            pages=[]
            for sym in symbols:
                receipt,items=collector(
                    period,sym,day,day,
                    logger=logger)
                pages.extend(receipt["pages"])
                bars.extend(items)
            proof=pair_and_calibrate(period,bars,original)
            proof["original_purchased_month_path"]=str(path)
            proof["original_purchased_month_sha256"]=paid_sha
            proof["public_source_pages"]=pages
            result["periods"][period]=proof
            logger("PASS_PAID_MINUTE_CROSS_SOURCE_CALIBRATION="+json.dumps(
                proof,ensure_ascii=False,sort_keys=True))
        except Exception as exc:
            result["failed"][period]=str(exc)[:600]
            logger(f"BLOCK_MINUTE_PERIOD_{period}_CALIBRATION {exc}")
    result["accepted_for_source_only"]=sorted(result["periods"])
    result["not_authorized_for_production"]=True
    return result

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("D:/stock"))
    parser.add_argument("--periods",default="5min,15min,30min,60min")
    args=parser.parse_args()
    print("MINUTE_PAID_CALIBRATION_RESULT="+json.dumps(
        run(args.root,periods=args.periods.split(",")),
        sort_keys=True,ensure_ascii=False))
