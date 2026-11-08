#!/usr/bin/env python3
"""One-day bounded automatic stock selection from a SHA-gated PRIVATE H5 5min file.

Read only the existing, previously SAFE-verified unified 5min private Parquet
(4 metadata columns) to enumerate complete H5-only 48-slot stockdays.
Then delegate ALL original purchased high-cycle and per-stock OHLCVA checks to
the accepted isolated research staging tool. No source file writes/overwrites,
production pointers, official calendar or week/month/day assumptions.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MOD_PATH=HERE/"stage-2026-oct-verified-h5-high-cycle-private-parquet.py"

def _load():
    spec=importlib.util.spec_from_file_location(
        "oct_2026_h5_private_autobatch_stage",MOD_PATH)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

S=_load()
CANARY=frozenset(("SH600000","SZ000001"))
FIELDS=("ts","symbol","value_source","period")
MAX_SOURCE_SCAN=3000000
MAX_SYMBOLS_SEEN=10000
STATUS="oct_2026_sha_verified_private_h5_five_minute_complete_stockdays_inventory"

def discover(day,*,exclude=CANARY):
    """One bounded Arrow column scan; zero raw market OHLCVA in inventory."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    if type(day) is not date or day.year!=2026 or day.month!=10:
        raise ValueError("Only explicit October 2026 trading dates")
    path,expected_sha=S.source_receipt(day)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Unsafe private H5 minute source")
    if S._sha(path)!=expected_sha:
        raise ValueError("Private H5 five-minute SHA changed before inventory")
    available={}
    purchased=set()
    inspected=0
    with pq.ParquetFile(path,memory_map=False,pre_buffer=False) as pf:
        schema=pf.schema_arrow
        if (not set(FIELDS).issubset(schema.names)
                or not pa.types.is_integer(schema.field("ts").type)
                or not pa.types.is_string(schema.field("symbol").type)
                or not pa.types.is_string(schema.field("value_source").type)
                or not pa.types.is_string(schema.field("period").type)):
            raise ValueError("Unexpected private five-minute index column schema")
        if pf.metadata.num_rows>MAX_SOURCE_SCAN:
            raise ValueError("Existing private minute file exceeds bounded inventory budget")
        for batch in pf.iter_batches(batch_size=32768,columns=list(FIELDS),
                                     use_threads=False):
            inspected+=batch.num_rows
            if inspected>MAX_SOURCE_SCAN:
                raise ValueError("Minute inventory row scan budget exceeded")
            for row in batch.to_pylist():
                if row["period"]!="5min":
                    raise ValueError("Non-5min row in private 5min receipt")
                sym=row["symbol"]
                source=row["value_source"]
                stamp=row["ts"]
                if (type(sym) is not str or
                        type(stamp) is not int or
                        not S.SYMBOL.fullmatch(sym)):
                    # Noncanonical symbols cannot be used as research candidates;
                    # source file rows themselves remain unchanged.
                    continue
                if source=="purchased_parquet":
                    purchased.add(sym)
                    continue
                if source!="h5_only_complete_stockday":
                    raise ValueError("Unexpected private five-minute source provenance")
                if sym not in available:
                    if len(available)>=MAX_SYMBOLS_SEEN:
                        raise ValueError("Too many H5 stockdays in bounded minute source")
                    available[sym]=[]
                available[sym].append(stamp)
    if S._sha(path)!=expected_sha:
        raise ValueError("Private H5 five-minute SHA changed during inventory")
    expected_grid=set(S.C.grid_timestamps(day))
    counters=Counter()
    eligible=[]
    core=S.C.ALL.MINUTE.Q.core
    for sym,stamps in sorted(available.items()):
        if not core.is_a_share_candidate(sym,day.year):
            counters["non_a_share_or_unverified_symbol"]+=1
            continue
        if sym in purchased:
            counters["purchased_five_minute_priority"]+=1
            continue
        if len(stamps)!=48 or set(stamps)!=expected_grid:
            counters["incomplete_or_invalid_h5_five_minute_grid"]+=1
            continue
        if sym in exclude:
            counters["already_staged_canary_symbol"]+=1
            continue
        eligible.append(sym)
    return {
        "status":STATUS,
        "day":day.isoformat(),
        "private_h5_five_minute_source_rows_scanned":inspected,
        "h5_source_symbols_observed":len(available),
        "candidate_complete_stockdays":len(eligible),
        "excluded_by_reason":dict(sorted(counters.items())),
        "eligible_symbols":eligible,  # only canonical IDs, NEVER OHLCVA
        "source_5min_sha256":expected_sha,
        "strict_receipt_sha_verified":True,
        "purchased_original_high_cycle_absence_checked":False,
        "original_market_files_modified":False,
        "production_activated":False,
        "vendor_physical_units_certified":False,
    }

def run(root,day,run_id,*,batch_index=0,batch_size=16,exclude=CANARY):
    if (type(batch_index) is not int or not 0<=batch_index<=10000
            or type(batch_size) is not int or not 1<=batch_size<=100):
        raise ValueError("Bounded batch index or size out of range")
    # Do not write anything until all source and plan checks finish.
    plan=discover(day,exclude=exclude)
    selected=plan["eligible_symbols"][batch_index*batch_size:
                                       (batch_index+1)*batch_size]
    if not selected:
        raise ValueError("No complete SHA-verified H5 stockdays in requested batch")
    manifest=S.stage(root,[day.isoformat()],selected,run_id)
    expected={
        "15min":16*len(selected),"30min":8*len(selected),
        "60min":4*len(selected)}
    if (manifest["verified_source_stockdays"]!=len(selected)
            or {p:manifest["outputs"][p]["rows"] for p in S.PERIODS}!=expected
            or manifest["ready_for_production_merge"] is not False):
        raise ValueError("Unexpected isolated high-cycle candidate batch geometry")
    return {
        "status":"oct_2026_private_h5_highcycle_autobatch_staged_readback",
        "source_inventory":{
            k:plan[k] for k in plan if k!="eligible_symbols"
        },
        "batch_index":batch_index,
        "batch_size":batch_size,
        "selected_stockdays":len(selected),
        "eligible_stockdays_total_for_day":plan["candidate_complete_stockdays"],
        "remaining_after_batch":max(0,plan["candidate_complete_stockdays"]-
                                    (batch_index+1)*batch_size),
        "stage":manifest,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--day",default="2026-10-13")
    p.add_argument("--run-id",required=True)
    p.add_argument("--batch-index",type=int,default=0)
    p.add_argument("--batch-size",type=int,default=16)
    p.add_argument("--write-private-candidates-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        d=date.fromisoformat(a.day)
        result=run(a.root,d,a.run_id,batch_index=a.batch_index,batch_size=a.batch_size)
    except (ValueError,OSError,RuntimeError) as exc:
        p.error("Batched private high-cycle stage NOT accepted: "+
                type(exc).__name__+": "+str(exc)+
                "; no original market modifications; partial private run may remain")
    print("PRIVATE_OCT_HIGH_CYCLE_BATCH="+json.dumps(result,sort_keys=True,
                                                 ensure_ascii=False,
                                                 separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
