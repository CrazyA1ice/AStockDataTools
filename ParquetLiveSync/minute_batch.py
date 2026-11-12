#!/usr/bin/env python3
"""Resumable limited-rate SH/SZ/BJ five-period public minute-source collector.

Reads current physical purchased+TDX DAY monthly A-share symbols; downloads
at most 10 stocks per invocation by default; never modifies purchased
minute/month/day Parquet files. Only SHA-pinned private raw source samples
are stored. Because the 1m/5m source has finite retention and the original
provider's timestamp/amount semantics remain unverified, a sample success
is NEVER described as complete current full-market minute coverage.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

import pyarrow.parquet as pq

from live_sync import WORK,read_state,CN
from local_layout import normal_symbol,storage_root,market_ts_day
from minute_probe import run as collect,PERIODS

FORMAT="minute_public_batch_source_candidates_with_real_tencent_m1_v2"
PROGRESS=WORK/"minute_source_trials"/"batch-progress-tencent-v2.json"

def active_market_symbols(root):
    root=storage_root(root)
    files=sorted((root/"day").glob("????-??.parquet"))
    if not files:
        raise ValueError("No real physical current-year DAY monthly file")
    recent=files[-1]
    if recent.is_symlink():
        raise ValueError("Linked DAY source is not allowed")
    frame=pq.read_table(recent,columns=["ts","symbol"])
    if not frame.num_rows:
        raise ValueError("Latest physical monthly DAY Parquet is empty")
    days=frame["ts"].to_pylist()
    symbols=frame["symbol"].to_pylist()
    newest=max(days)
    latest=market_ts_day(newest)
    found=sorted(set(
        normal_symbol(sym) for ts,sym in zip(days,symbols)
        if market_ts_day(ts)==latest
    ))
    found=[item for item in found
           if len(item)==8 and item[:2] in ("SH","SZ","BJ")
           and item[2:].isdigit()]
    if len(found)<2000:
        raise ValueError("Last physical day is too sparse for real full-market minute candidate universe")
    return latest,found

def digest_symbols(values):
    return hashlib.sha256(",".join(values).encode()).hexdigest()

def save_atomic(path,doc):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():
        raise ValueError("Linked minute batch progress path refused")
    tmp=path.with_suffix(".json.part")
    if tmp.is_symlink():
        raise ValueError("Linked minute batch temporary path refused")
    tmp.write_text(json.dumps(doc,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
                   encoding="utf-8")
    os.replace(tmp,path)

def source_package_cached(result,symbol):
    """Raw 1m trend + all four valid Kline sources is a *cached package*,
    not a full five-period OHLCVA candidate or production certification.
    """
    periods=result.get("periods",{})
    if set(periods)!=set(PERIODS):
        return False
    first=periods.get("1min",{}).get(symbol,{})
    if symbol.startswith(("SH","SZ")):
        if (first.get("status")!="TENCENT_REAL_M1_OHLCV_NO_AMOUNT"
                or first.get("amount_cny_available") is not False
                or not first.get("raw_source_sha256")
                or not first.get("private_ohlcv_parquet")):
            return False
    else:
        # Tencent has no BJ m1; only raw Eastmoney trend can be cached.
        if (first.get("status")!="SOURCE_DOWNLOADED_BUT_OHLCVA_UNVERIFIED"
                or "EASTMONEY_TRENDS2_NOT_OHLCVA" not in first.get("reason","")
                or not first.get("raw_source_sha256")):
            return False
    for period in PERIODS[1:]:
        entry=periods.get(period,{}).get(symbol,{})
        if (entry.get("status")!="CANDIDATE_ONLY_NOT_MERGED"
                or not entry.get("raw_source_sha256")):
            return False
    return True

def run(root,*,limit=10,logger=print,stop=None,progress=PROGRESS,
        collector=collect,universe=None):
    if type(limit) is not int or not 1<=limit<=12:
        raise ValueError("Only 1..12 stocks per bounded source batch allowed")
    root=Path(root)
    market=storage_root(root)
    state=read_state()  # verify authoritative daily SHA receipts before building universe
    if not state.get("days"):
        raise ValueError("No official TDX daily SHA accepted")
    current,stocks=universe or active_market_symbols(market)
    progress=Path(progress)
    proof={
        "format":FORMAT,"day_universe":current.isoformat(),
        "latest_source_day":current.isoformat(),
        "stock_universe_sha256":digest_symbols(stocks),
        "symbols_in_universe":len(stocks),
        "all_five_periods_candidate_only":list(PERIODS),
        "accepted_stock_symbols":[],
        "accepted_scope":"true_Tencent_SH_SZ_1min_OHLCV_NO_AMOUNT_or_BJ_raw_trend_plus_valid_4_kline_candidates_only",
        "failed_stock_symbols":{},
        "market_files_modified":False,
        "complete_full_market_minute_coverage_verified":False,
        "source_volume_time_label_certified":False,
    }
    if progress.exists():
        if progress.is_symlink():
            raise ValueError("Linked batch progress source refused")
        previous=json.loads(progress.read_text(encoding="utf-8"))
        if (previous.get("format")!=FORMAT or
                previous.get("day_universe")!=proof["day_universe"] or
                previous.get("stock_universe_sha256")!=proof["stock_universe_sha256"]):
            raise ValueError("Local active-stock universe changed; cannot reuse stale full-market source trial index")
        proof=previous
    accepted=set(proof["accepted_stock_symbols"])
    # A known Eastmoney 1min source defect (traded bars with open=0)
    # must not permanently block the whole 5,500-stock candidate queue.
    # Take never-tried equities first; retry source-defective codes
    # only after the rest have had a chance to be sampled.
    failed=set(proof.get("failed_stock_symbols",{}))
    next_batch=(
        [sym for sym in stocks if sym not in accepted and sym not in failed]
        +[sym for sym in stocks if sym not in accepted and sym in failed]
    )[:limit]
    for sym in next_batch:
        if stop is not None and stop():
            logger("PAUSED_MINUTE_BATCH_WITH_INCOMPLETE_CANDIDATES")
            break
        result=collector(
            [sym],periods=PERIODS,logger=logger,
            stop=stop,work=progress.parent/"source",
            tencent_first=True)
        if source_package_cached(result,sym):
            accepted.add(sym)
            proof["failed_stock_symbols"].pop(sym,None)
        else:
            proof["failed_stock_symbols"][sym]=str(result.get("failed",[]))[:500]
        proof["accepted_stock_symbols"]=sorted(accepted)
        proof["completed_at_cn"]=datetime.now(CN).isoformat()
        save_atomic(progress,proof)  # durable per-stock checkpoint
        logger(f"MINUTE_BATCH_RAW_CANDIDATE_PROGRESS={len(accepted)}/{len(stocks)} "
               f"symbol={sym} candidate_with_true_tencent_1m_for_SH_SZ={sym in accepted} "
               "1m_turnover_amount_not_available=True")
    proof["status"]=(
        "CANDIDATE_SOURCE_INVENTORY_PARTIAL_NOT_MARKET_MERGED")
    proof["current_completed_stocks"]=len(accepted)
    proof["remaining_not_certified"]=len(stocks)-len(accepted)
    save_atomic(progress,proof)
    logger("MINUTE_BATCH_RESULT="+json.dumps(
        {"candidate_stocks":len(accepted),"universe":len(stocks),
         "source_failures":len(proof["failed_stock_symbols"]),
         "no_market_writes":True},
        ensure_ascii=False,sort_keys=True))
    return proof

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path("D:/stock"))
    p.add_argument("--limit",type=int,default=10)
    args=p.parse_args()
    run(args.root,limit=args.limit)

if __name__=="__main__":
    main()
