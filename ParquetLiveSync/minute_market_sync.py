#!/usr/bin/env python3
"""Real 5/15/30/60m market-month updater; source-only stage unless explicit.

First supported physical month: November 2026 (the first modern month with
no unverified purchased/H5 minute history before the 2026-10-13 cutoff).
For October 2026 the frozen source dataset has 1/5-minute H5 candidates
and 15/30/60 H5-derived candidates flagged UNVERIFIED UNITS: the October
month MUST NOT be overwritten from only October-14-onward public bars.

Safety:
  * Source 5m pages historical-paginated with per-response SHA receipts.
  * Purchased 2026-09-30 5/15/30/60 OHLCVA, time and units independently
    calibrated with 3 exchanges; original purchased physical SHA pinned.
  * Every traded stock/day in official verified DAY physical month must
    have exactly 48 source 5m bars, with correct CN midday break.
  * All 15/30/60 bars derive from *complete* real 5m OHLCVA.
  * Per-stock/day official DAY total/OHLC/volume/amount must agree.
  * All expected equities staged and SHA-verified BEFORE any physical
    minute Parquet write; never silently mark partial market "complete".
  * Single transaction per period, keeps original same-key bar values
    only if they match the newly verified data; backup and atomic replace.
  * 1m remains BLOCKED: trends2 is not OHLCVA; never fabricate 1m.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date,datetime,timedelta
import hashlib
import json
import math
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
from live_sync import CN,WORK,read_state,exclusive_writer,source_day_ts,parquet_schema
from minute_history import collect_one
from minute_5m_rollup import PERIODS,derive_from_5min
import minute_paid_calibration as C

FORMAT="paid_calibrated_four_minute_market_month_v1"
CUTOFF=date(2026,10,13)
WORK_ROOT=WORK/"minute_market_sync"
CAL_PATH=WORK_ROOT/"purchased_sep30_source_calibration.json"
MIN_EQUITIES=2500

def canonical(doc):
    return (json.dumps(doc,ensure_ascii=False,sort_keys=True,
                       separators=(",",":"),allow_nan=False)+"\n").encode()

def write_json(path,data):
    path=Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Linked private minute work path not permitted")
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(".json.part")
    if temp.is_symlink():
        raise ValueError("Linked minute receipt temp file")
    temp.write_bytes(canonical(data))
    os.replace(temp,path)

def official_days(root,start,end):
    """SHA-accepted official full-market DAY stock-day/bar reference."""
    storage=L.storage_root(root)
    if not start.year==end.year==datetime.now(CN).year or start>end:
        raise ValueError("Only current-year single-month minute live append")
    if (start.month!=end.month or start<=CUTOFF
            or (end-start).days>31):
        raise ValueError("Only post-cutoff one-calendar-month minute source windows")
    # November 2026 is the first eligible month: 2026-10 contains
    # unverified vendor H5-derived "prior purchased" records before Oct14.
    if start<date(2026,11,1):
        raise ValueError(
            "OCTOBER_MINUTE_BASELINE_UNVERIFIED: do not create incomplete "
            "October files omitting 2026-10-01..13; stage separately first")
    p=storage/"day"/f"{start.year}-{start.month:02}.parquet"
    if not p.is_file() or p.is_symlink():
        raise ValueError("Physical official DAY monthly reference missing")
    before=source_day_ts(start)
    through=source_day_ts(end)+86400000
    rows=pq.read_table(
        p,columns=list(L.COLS),
        filters=[("ts",">=",before),("ts","<",through)])
    L.validate_schema(rows.schema)
    if rows.num_rows<MIN_EQUITIES:
        raise ValueError("Incomplete official traded daily stock universe")
    selected=defaultdict(dict)
    for row in rows.to_pylist():
        day=L.market_ts_day(row["ts"])
        sym=L.normal_symbol(row["symbol"])
        if not (len(sym)==8 and sym[:2] in ("SH","SZ","BJ")
                and sym[2:].isdigit()):
            continue
        if sym in selected[day]:
            raise ValueError("Duplicate official DAY security for given date")
        selected[day][sym]=row
    if any(len(x)<MIN_EQUITIES for x in selected.values()):
        raise ValueError("Official full-market DAY underpopulation")
    state=read_state()
    current=start
    while current<=end:
        if current.weekday()<5 and str(current) not in state["days"]:
            raise ValueError("OFFICIAL_DAY_NOT_SHA_ACCEPTED "+str(current))
        current+=timedelta(days=1)
    if not selected:
        raise ValueError("No official current source days to update")
    if min(selected)!=start:
        # For November 2026 the first trading session is November 2.
        if not (start==date(2026,11,2) and min(selected)==start):
            raise ValueError("Window must start on first complete month trading day")
    if start.day>3:
        raise ValueError("Only full new-month source window is promotable")
    rows_sorted=sorted((day.isoformat(),sym,bar["ts"],
                        bar["open"],bar["high"],bar["low"],bar["close"],
                        bar["volume"],bar["amount"])
                       for day,eq in selected.items() for sym,bar in eq.items())
    snapshot=hashlib.sha256(canonical(rows_sorted)).hexdigest()
    return selected,snapshot

def calibrate_sep30(root,*,logger=print,collector=collect_one,
                    storage=WORK_ROOT):
    """Use SINGLE purchased Sep30 vs 5m provider for all 4 derived periods."""
    storage=Path(storage)
    path=storage/"purchased_sep30_source_calibration.json"
    bars=[]
    proof=[]
    for sym in C.SYMBOLS:
        receipt,items=collector("5min",sym,C.CAL_DAY,C.CAL_DAY,
                                logger=logger)
        proof.extend(receipt["pages"])
        bars.extend(items)
    aggregated,failures=derive_from_5min(bars)
    if failures:
        raise ValueError("Historical 5m trading-time-grid incomplete for sample "+str(failures))
    gates={}
    for period in PERIODS:
        purchased,original_path,paid_sha=C.source_day_rows(
            root,period,C.CAL_DAY,C.SYMBOLS)
        gate=C.pair_and_calibrate(period,aggregated[period],purchased)
        gate["purchased_month_sha256"]=paid_sha
        gate["purchased_month_path"]=str(original_path)
        gates[period]=gate
        logger("PASS_REAL_PAID_DERIVED_MINUTE_GATE "+period+" "+
               json.dumps({key:gate[key] for key in
                           ("time_price_overlap","price_fit",
                            "source_volume_to_purchased_factor",
                            "source_amount_to_purchased_factor",
                            "timestamp_offset_source_to_purchased_ms")},
                          sort_keys=True))
    result={"format":FORMAT,"reference_day":"2026-09-30",
            "calibrations":gates,"source_pages":proof,
            "original_licensed_parquet_modified":False,
            "vendor_units_proved_on_reference_day_not_global":True}
    if path.exists():
        if path.is_symlink():
            raise ValueError("Linked private calibration file")
        old=json.loads(path.read_bytes())
        if old!=result:
            raise ValueError("Existing Sep30 minute calibration changed; review provenance")
    else:
        write_json(path,result)
    return result

def check_calibration(root,*,storage=WORK_ROOT):
    path=Path(storage)/"purchased_sep30_source_calibration.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Run and pass 2026-09-30 paid minute calibration first")
    doc=json.loads(path.read_bytes())
    if doc.get("format")!=FORMAT or set(doc["calibrations"])!=set(PERIODS):
        raise ValueError("Wrong paid minute calibration schema")
    for period,gate in doc["calibrations"].items():
        p=L.storage_root(root)/period/"2026-09.parquet"
        if (p.is_symlink() or L.hash_file(p)!=gate["purchased_month_sha256"]
                or str(p)!=gate["purchased_month_path"]):
            raise ValueError("Purchased historical minute original SHA drift: "+period)
    return doc

def compare_day(period,day,source_day_bars,daily,gate):
    # Independent per-stock official TDX DAY OHLCVA:
    # five-minute source bars sum into daily OHLC and turnover.
    if not source_day_bars:
        raise ValueError("No real five-minute bars")
    src=source_day_bars
    prices={"open":src[0]["open"],"close":src[-1]["close"],
            "high":max(x["high"] for x in src),
            "low":min(x["low"] for x in src)}
    for name,new in prices.items():
        old=float(daily[name])
        if not math.isclose(new,old,rel_tol=.006,abs_tol=.04):
            raise ValueError(
                f"{period} official DAY OHLC differs {day} {name}: "
                f"TDX={old} source={new}")
    for srcfield,field,factor in (
        ("provider_volume","volume",gate["source_volume_to_purchased_factor"]),
        ("amount_yuan","amount",gate["source_amount_to_purchased_factor"])):
        old=float(daily[field])
        new=sum(float(x[srcfield])*factor for x in src)
        if not math.isclose(old,new,rel_tol=.025,abs_tol=300):
            raise ValueError(
                f"Official DAY {field} mismatch on {day}: "
                f"TDX={old} sum_of_5min={new}")

def stage_stock(root,symbol,expected,calendar_sha,gates,*,start,end,
                collector=collect_one,stage_root=WORK_ROOT,logger=print,
                stop=None):
    days={day for day,symbols in expected.items() if symbol in symbols}
    if not days:
        raise ValueError("Selected stock not present in verified official DAY")
    name=f"{start:%Y%m%d}_{end:%Y%m%d}"
    folder=Path(stage_root)/"staged"/name
    receipt_path=folder/"receipts"/(symbol+".json")
    if receipt_path.exists():
        old=json.loads(receipt_path.read_bytes())
        if (old.get("calendar_sha256")!=calendar_sha or
                old.get("period_calibration_sha256")!=
                hashlib.sha256(canonical(gates)).hexdigest()):
            raise ValueError("Existing minute stock receipt bound to old DAY/calendar")
        for p,info in old["period_files"].items():
            source=Path(info["path"])
            if (source.is_symlink() or not source.is_file() or
                    L.hash_file(source)!=info["sha256"]):
                raise ValueError("Previously staged minute stock Parquet tampered")
        return old,False
    _,raw=collector("5min",symbol,start,end,logger=logger,stop=stop)
    generated,invalid=derive_from_5min(raw)
    for day in days:
        key=(symbol,day.isoformat())
        if key not in generated.get("5min",[]) and key in invalid:
            raise ValueError(
                f"INCOMPLETE_5MIN_STOCKDAY {symbol} {day}: {invalid[key]}")
    # Verify the complete 48 time grid for every official trade day.
    five=defaultdict(list)
    for bar in generated["5min"]:
        if bar["date"]>=start.isoformat() and bar["date"]<=end.isoformat():
            five[date.fromisoformat(bar["date"])].append(bar)
    if set(five)!=days or any(len(five[day])!=48 for day in days):
        raise ValueError(
            f"INCOMPLETE_5MIN_STOCKDAYS {symbol} "
            f"expected={len(days)} verified={len(five)}")
    for day in days:
        compare_day("5min",day,five[day],expected[day][symbol],
                    gates["5min"])
    files={}
    for period in PERIODS:
        calibration=gates[period]
        subset=[bar for bar in generated[period]
                if date.fromisoformat(bar["date"]) in days]
        if len(subset)!=len(days)*{"5min":48,"15min":16,
                                   "30min":8,"60min":4}[period]:
            raise ValueError("Derived minutes have missing bar count")
        rows=[{
            "symbol":symbol,
            "ts":bar["ts"]+calibration[
                "timestamp_offset_source_to_purchased_ms"],
            "open":float(bar["open"]),"high":float(bar["high"]),
            "low":float(bar["low"]),"close":float(bar["close"]),
            "volume":float(bar["provider_volume"])*
                     calibration["source_volume_to_purchased_factor"],
            "amount":float(bar["amount_yuan"])*
                     calibration["source_amount_to_purchased_factor"],
        } for bar in subset]
        frame=pa.Table.from_pylist(rows,schema=parquet_schema())
        L.checked_records(frame,target_year=start.year,target_month=start.month)
        target=folder/period/(symbol+".parquet")
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.is_symlink():
            raise ValueError("Private staged Parquet path redirected")
        temporary=target.with_suffix(".parquet.part")
        pq.write_table(frame,temporary,compression="zstd")
        readback=pq.read_table(temporary)
        if not readback.equals(frame,check_metadata=False):
            raise ValueError("Staged minute Parquet Arrow read-back mismatch")
        os.replace(temporary,target)
        files[period]={"path":str(target),"sha256":L.hash_file(target),
                       "rows":len(rows)}
    receipt={"format":FORMAT,"symbol":symbol,
             "requested_window":[start.isoformat(),end.isoformat()],
             "official_stock_trading_days":sorted(d.isoformat() for d in days),
             "calendar_sha256":calendar_sha,
             "period_calibration_sha256":hashlib.sha256(canonical(gates)).hexdigest(),
             "period_files":files,"status":"all_four_minute_periods_staged_not_market_merged",
             "market_parquet_modified":False}
    write_json(receipt_path,receipt)
    return receipt,True

def execute(root,*,start=date(2026,11,2),end=date(2026,11,11),
            limit=25,apply=False,logger=print,collector=collect_one,
            work=WORK_ROOT,stop=None):
    """Process <=limit symbols per call; 0 means all pending (slow)."""
    if not isinstance(limit,int) or limit<0 or limit>1000:
        raise ValueError("Per-call stock limit must be 0..1000")
    expected,day_sha=official_days(root,start,end)
    cal_path=Path(work)/"purchased_sep30_source_calibration.json"
    if not cal_path.exists():
        calibrate_sep30(root,logger=logger,collector=collector,storage=work)
    receipt=check_calibration(root,storage=work)
    gates=receipt["calibrations"]
    symbols=sorted(set().union(*(set(v) for v in expected.values())))
    name=f"{start:%Y%m%d}_{end:%Y%m%d}"
    receipts=Path(work)/"staged"/name/"receipts"
    receipts.mkdir(parents=True,exist_ok=True)
    failures={}
    processed=0
    for sym in symbols:
        if stop is not None and stop():
            break
        path=receipts/(sym+".json")
        if path.exists():
            # Full prior SHA and calendar validation, but no network.
            stage_stock(root,sym,expected,day_sha,gates,
                        start=start,end=end,collector=collector,
                        stage_root=work,logger=logger,stop=stop)
            continue
        if limit and processed>=limit:
            break
        processed+=1
        try:
            stage_stock(root,sym,expected,day_sha,gates,
                        start=start,end=end,collector=collector,
                        stage_root=work,logger=logger,stop=stop)
            logger(f"PASS_PRIVATE_FOUR_PERIODS_STAGED {sym}")
        except InterruptedError:
            break
        except Exception as exc:
            failures[sym]=str(exc)[:300]
            logger(f"RETRYABLE_MINUTE_STOCK_SOURCE_OR_DAY_GAP {sym} {exc}")
    ready=sum((receipts/(sym+".json")).is_file() for sym in symbols)
    result={"status":"PRIVATE_FOUR_PERIOD_MINUTE_STAGE",
            "window":[start.isoformat(),end.isoformat()],
            "expected_distinct_stocks":len(symbols),
            "stock_receipts_present":ready,"attempted_this_run":processed,
            "source_or_coverage_failures":failures,
            "physical_market_parquet_modified":False,
            "full_market_source_approved":ready==len(symbols),
            "one_minute_source_unsupported":True}
    logger("MINUTE_FOUR_PERIOD_STAGE_RESULT="+json.dumps(
        result,ensure_ascii=False,sort_keys=True))
    if apply:
        if ready!=len(symbols) or failures:
            raise ValueError(
                f"ALL_MARKET_STOCKS_NOT_STAGED {ready}/{len(symbols)}; "
                "no official minute month files modified")
        result["commits"]=commit_month(
            root,expected,day_sha,gates,start=start,end=end,work=work,
            receipts=receipts,symbols=symbols,logger=logger)
        result["status"]="FOUR_MINUTE_PERIOD_MONTH_ATOMIC_SWAPS_COMPLETED"
        result["physical_market_parquet_modified"]=True
    return result

def commit_month(root,expected,day_sha,gates,*,start,end,work,receipts,
                 symbols,logger=print):
    """All-symbol four-period preflight BEFORE performing any month swap."""
    import rollup_week_month as R
    if start<date(2026,11,1) or start.day>3:
        raise ValueError("Never create October partial minute month without original baseline")
    groups=[]
    for period in PERIODS:
        tables=[]
        expected_total=0
        for symbol in symbols:
            path=receipts/(symbol+".json")
            if not path.is_file() or path.is_symlink():
                raise ValueError("Missing private per-stock market receipt")
            doc=json.loads(path.read_bytes())
            if (doc.get("calendar_sha256")!=day_sha or
                    doc.get("period_calibration_sha256")!=
                    hashlib.sha256(canonical(gates)).hexdigest()
                    or doc.get("status")!="all_four_minute_periods_staged_not_market_merged"):
                raise ValueError("Unverified stage source identity")
            info=doc["period_files"][period]
            f=Path(info["path"])
            if not f.is_file() or f.is_symlink() or L.hash_file(f)!=info["sha256"]:
                raise ValueError("Private minute candidate Arrow SHA mismatch")
            tables.append(pq.read_table(f))
            expected_total+=int(info["rows"])
        all_rows=pa.concat_tables(tables,promote_options="none")
        if all_rows.num_rows!=expected_total:
            raise ValueError("Staged minute source row total mismatch")
        L.checked_records(all_rows,target_year=start.year,target_month=start.month)
        R.verify_existing_period_keys(root,period,start.year,start.month,all_rows)
        groups.append((period,all_rows))
    # Reconfirm source day input and paid 2026-09 calibration just before write.
    if official_days(root,start,end)[1]!=day_sha:
        raise ValueError("Official day stock-date facts changed after staging")
    check_calibration(root,storage=work)
    commits=[]
    with exclusive_writer():
        if official_days(root,start,end)[1]!=day_sha:
            raise ValueError("Official day stock-date facts changed during lock")
        for period,frame in groups:
            R.verify_existing_period_keys(
                root,period,start.year,start.month,frame)
        for period,frame in groups:
            result=L.write_month(
                root,period,start.year,start.month,frame,
                WORK,current_year=start.year)
            commits.append({"period":period,**result})
            logger("PASS_LOCAL_MINUTE_MONTH_PARQUET "+
                   f"{period} {start.year}-{start.month:02} "+
                   f"NEW={result['added']} ALL={result['total_rows']}")
    return commits

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path("D:/stock"))
    p.add_argument("--start",type=date.fromisoformat,default=date(2026,11,2))
    p.add_argument("--end",type=date.fromisoformat,default=date(2026,11,11))
    p.add_argument("--limit-stocks",type=int,default=25)
    p.add_argument("--commit-complete-month-source",action="store_true")
    args=p.parse_args()
    execute(args.root,start=args.start,end=args.end,
            limit=args.limit_stocks,apply=args.commit_complete_month_source)

if __name__=="__main__":
    main()
