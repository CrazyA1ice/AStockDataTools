#!/usr/bin/env python3
"""Bounded read-only purchased DAY Parquet shared-rowgroup batch.

The current single-stock query scans a purchased rowgroup once per stock,
even when several requested symbols share the same physical rowgroup. This
module uses each stock's existing fail-closed metadata preflight and reads
the union of permitted (file,rowgroup) pairs ONCE. Exact source values remain
in process memory; not cached or exported in reports.
"""
from __future__ import annotations
import importlib.util
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
def load():
    spec=importlib.util.spec_from_file_location(
        "shared_day_batch_existing_purchased_query",
        HERE/"query-parquet-primary-readonly.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

P=load()
MAX_SYMBOLS=10
MAX_TOTAL_ROWS=100000000


def query_bars(root,symbols,first,last,max_candidate_rows_per_symbol=30000000,
               max_total_candidate_rows=30000000,max_result_bars_per_symbol=100,
               max_total_result_bars=1000):
    if (type(symbols) not in (list,tuple) or not 1<=len(symbols)<=MAX_SYMBOLS
            or len(set(symbols))!=len(symbols)
            or type(max_candidate_rows_per_symbol) is not int
            or not 1<=max_candidate_rows_per_symbol<=MAX_TOTAL_ROWS
            or type(max_total_candidate_rows) is not int
            or not 1<=max_total_candidate_rows<=MAX_TOTAL_ROWS
            or type(max_result_bars_per_symbol) is not int
            or not 1<=max_result_bars_per_symbol<=100000
            or type(max_total_result_bars) is not int
            or not 1<=max_total_result_bars<=100000):
        raise ValueError("Require 1..10 unique stocks and bounded purchased batch budgets")
    prepared=[
        P.request_dates(s,"day",first,last,max_candidate_rows_per_symbol,
                        max_result_bars_per_symbol) for s in symbols]
    if any(x[1:]!=prepared[0][1:] for x in prepared):
        raise ValueError("Purchased shared batch must have identical DAY window")
    contexts={}
    physical={}
    aliases={}
    for symbol in symbols:
        ctx=P.prepare_query(root,symbol,"day",first,last,
                            max_candidate_rows_per_symbol,max_result_bars_per_symbol)
        if (ctx["symbol"]!=symbol or ctx["period"]!="day"
                or ctx["start"]!=prepared[0][1] or ctx["end"]!=prepared[0][2]):
            raise ValueError("Noncanonical/inconsistent purchased source preflight")
        contexts[symbol]=ctx
        aliases[symbol]=set(ctx["aliases"])
        for path,pf,rg in ctx["pending"]:
            key=(str(Path(path).resolve()),rg)
            if key not in physical:
                physical[key]=[Path(path),pf,rg,set()]
            physical[key][3].add(symbol)
    physical_upper=sum(int(v[1].metadata.row_group(v[2]).num_rows)
                       for v in physical.values())
    if physical_upper>max_total_candidate_rows:
        raise ValueError("Shared purchased physical RowGroup source budget exceeded before scan")
    import pyarrow as pa
    import pyarrow.compute as pc
    low,high=P.day_bounds(prepared[0][1],prepared[0][2])
    values={symbol:{} for symbol in symbols}
    scanned=0
    matching=0
    for path,pf,rg,targets in physical.values():
        allowed=pa.array(sorted(set().union(*(aliases[s] for s in targets))),
                         type=pa.string())
        for batch in pf.iter_batches(row_groups=[rg],batch_size=65536,
                                     columns=list(P.NEEDED),use_threads=True):
            scanned+=batch.num_rows
            if scanned>max_total_candidate_rows:
                raise ValueError("Shared purchased runtime source rows exceeded budget")
            mask=pc.and_(pc.is_in(batch.column(1),value_set=allowed),
                         pc.and_(pc.greater_equal(batch.column(0),low),
                                 pc.less(batch.column(0),high)))
            for raw in batch.filter(mask).to_pylist():
                ts=raw["ts"]
                if type(ts) is not int or ts%60000:
                    raise ValueError("Invalid purchased daily source timestamp")
                dt=datetime.fromtimestamp(ts/1000,tz=P.core.UTC8)
                if not prepared[0][1]<=dt.date()<=prepared[0][2]:
                    continue
                parsed=P.core.symbol_id(raw["symbol"])
                if parsed not in targets:
                    continue
                row=tuple(float(raw[f]) for f in P.validator.FIELDS)
                if (not all(math.isfinite(v) for v in row)
                        or row[1]<max(row[0],row[2],row[3])-1e-7
                        or row[2]>min(row[0],row[1],row[3])+1e-7
                        or row[4]<0 or row[5]<0):
                    raise ValueError("Invalid purchased daily OHLCVA geometry")
                dst=values[parsed]
                if ts in dst:
                    raise ValueError("Duplicate purchased stock timestamp across shared rowgroups")
                if len(dst)>=max_result_bars_per_symbol:
                    raise ValueError("Purchased shared batch per-symbol result-row limit exceeded")
                dst[ts]=row
                matching+=1
                if matching>max_total_result_bars:
                    raise ValueError("Purchased shared batch total result-row limit exceeded")
    results={}
    for symbol in symbols:
        rows=[]
        for ts,fields in sorted(values[symbol].items()):
            dt=datetime.fromtimestamp(ts/1000,tz=P.core.UTC8)
            rows.append({
                "symbol":symbol,"period":"day",
                "trading_date":dt.date().isoformat(),
                "source_timestamp_ms":ts,
                **dict(zip(P.validator.FIELDS,fields)),
            })
        results[symbol]=rows
    return {
        "bars_by_symbol":results,
        "safe_summary":{
            "state":"one_physical_purchased_rowgroup_scan_per_requested_batch",
            "requested_stock_count":len(symbols),
            "shared_physical_candidate_rowgroups":len(physical),
            "shared_physical_rowgroups_upper_bound":physical_upper,
            "shared_physical_source_rows_scanned":scanned,
            "total_matching_purchased_rows":matching,
            "source_quantity_unit_rescaling_applied":False,
            "purchased_values_modified":False,
            "original_market_files_written":False,
            "original_h5_opened":False,
            "purchased_rows_returned_only_in_private_memory":True,
            "source_stat_is_not_full_content_authentication":True,
        },
    }
