#!/usr/bin/env python3
"""Purchased-first eight-cycle LOCAL research query with OPT-IN Oct highcycle gap.

Existing purchased Parquet always wins for its entire (symbol,date,period).
Only for Oct 08/09/12/13 2026, a *fully SHA-verified* private H5 5min
15/30/60min candidate is returned when that purchased stockday has NO rows.
The candidate remains source/label/unit UNVERIFIED and is never production-ready.
No purchased re-materialization, market/H5 writes, indexes, pointers or new
private candidate staging. Licensed bars stay in local Python memory only.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
HIGH=frozenset(("15min","30min","60min"))
SAFE_DAYS=frozenset(("2026-10-08","2026-10-09","2026-10-12","2026-10-13"))
SOURCE_VALUE="research_derived_candidate_from_sha_verified_h5_5min"
OUTPUT_STATUS="purchased_primary_eight_cycle_private_highcycle_explicit_readonly_v1"

def _load(alias,filename):
    spec=importlib.util.spec_from_file_location(alias,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

ALL=_load("highcycle_all_eight_purchased_primary",
          "query-purchased-primary-all-eight-cycles-readonly.py")
N=_load("highcycle_immutable_private_registry",
        "stage-next-uncovered-oct-h5-high-cycle-private-parquet.py")
A=_load("highcycle_full_day_sha_audit",
        "audit-2026-oct-high-cycle-private-day-coverage-readonly.py")
S=N.S

def _day_iter(start,end):
    d=start
    while d<=end:
        yield d
        d+=timedelta(days=1)

def _private_subset(path,symbol,day,period):
    """Bounded one-stage Parquet scan; never publish other licensed securities."""
    import pyarrow.parquet as pq
    import pyarrow as pa
    if path.is_symlink() or not path.is_file():
        raise ValueError("Candidate private Parquet missing/unsafe")
    rows=[]
    with pq.ParquetFile(path,memory_map=False,pre_buffer=False) as pf:
        expected=("ts","symbol","trading_date","period","open","high","low",
                  "close","volume","amount","value_source","source_period",
                  "source_5min_private_sha256",
                  "time_label_and_vendor_units_certified",
                  "corporate_adjustments_applied")
        if tuple(pf.schema_arrow.names)!=expected:
            raise ValueError("Unexpected private highcycle schema")
        if pf.metadata.num_rows>2800:
            raise ValueError("Unexpected private highcycle stage row budget")
        for batch in pf.iter_batches(batch_size=32768,use_threads=False):
            for row in batch.to_pylist():
                if row["symbol"]==symbol and row["trading_date"]==day:
                    if row["period"]!=period:
                        raise ValueError("Foreign private candidate period")
                    rows.append(row)
    if len(rows)!={"15min":16,"30min":8,"60min":4}[period]:
        raise ValueError("Incomplete private highcycle stockday candidate")
    rows.sort(key=lambda x:x["ts"])
    if len({r["ts"] for r in rows})!=len(rows):
        raise ValueError("Duplicate private highcycle candidate timestamps")
    return rows

def _validated_private_rowset(root,day,symbol,period,registry):
    """Reject mutated receipts, stale source, purchased overlap, or wrong rows."""
    if (day,symbol) not in registry:
        return []
    stage_root=S._safe_stage_root()
    target=None
    for receipt in stage_root.glob("*/receipt.json"):
        doc=json.loads(receipt.read_text(encoding="utf-8"))
        if day in doc.get("source_days",[]) and symbol in doc.get("symbols",[]):
            if target is not None:
                raise ValueError("Duplicate private stockday stage receipts")
            target=(receipt.parent,doc)
    if target is None:
        raise ValueError("Registry key lacks its private source receipt")
    directory,doc=target
    metadata=doc["outputs"][period]
    file=directory/(period+".parquet")
    if (metadata["private_file"]!=file.relative_to(S.MODULE).as_posix()
            or S._sha(file)!=metadata["sha256"]
            or metadata.get("complete_row_by_row_readback_exact") is not True):
        raise ValueError("Private highcycle source physical SHA mismatch")
    actual=_private_subset(file,symbol,day,period)
    recomputed,sources=S.build_candidates(
        Path(root),(date.fromisoformat(day),),(symbol,))
    expected=recomputed[period]
    if actual!=expected:
        raise ValueError("Private highcycle candidate differs from verified 5min source")
    verified_sha=sources[day][1]
    if (doc["sources"][0]["sha256"]!=verified_sha
            or any(row["source_5min_private_sha256"]!=verified_sha
                   or row["value_source"]!=SOURCE_VALUE
                   or row["time_label_and_vendor_units_certified"] is not False
                   or row["corporate_adjustments_applied"] is not False
                   for row in actual)):
        raise ValueError("Private highcycle derived source provenance is unsafe")
    if S._sha(file)!=metadata["sha256"]:
        raise ValueError("Private highcycle Parquet changed during read")
    return actual

def query_bars(root,symbol,period,first,last,*,
               allow_private_highcycle=False,
               max_candidate_rows=30000000,max_result_bars=10000):
    if type(allow_private_highcycle) is not bool:
        raise ValueError("Private highcycle opt-in must be explicit boolean")
    if allow_private_highcycle and period not in HIGH:
        raise ValueError("Private 5min-derived highcycle only supports 15/30/60min")
    canonical,start,end=ALL.PURCHASED.request_dates(
        symbol,period,first,last,max_candidate_rows,max_result_bars)
    root=Path(root)
    # Existing eight-cycle purchased-original router remains the authority,
    # and is called once for the whole bounded 1..31-day query window.
    base=ALL.query_bars(
        root,canonical,period,start.isoformat(),end.isoformat(),
        max_candidate_rows=max_candidate_rows,max_result_bars=max_result_bars)
    bars=list(base["bars"])
    bought_days={r["trading_date"] for r in bars}
    private_count=0
    audited=[]
    if allow_private_highcycle:
        # Every prior private Parquet physical byte SHA + source SHA and
        # duplicate receipt is validated BEFORE any candidate is returned.
        registry,runs=N.existing_stockdays()
        if runs<1:
            raise ValueError("No SHA-verified private highcycle registry")
        for day in _day_iter(start,end):
            ds=day.isoformat()
            if ds not in SAFE_DAYS or ds in bought_days:
                continue
            if (ds,canonical) not in registry:
                continue
            covered=A.audit(day)
            if (covered.get("this_date_coverage_complete") is not True
                    or covered.get("this_date_unstaged_complete_stockdays")!=0
                    or covered.get("full_existing_receipt_and_parquet_sha_reverified") is not True):
                raise ValueError("Private candidate day not fully SHA-verified")
            rows=_validated_private_rowset(root,ds,canonical,period,registry)
            if not rows:
                raise ValueError("No matching validated private highcycle rows")
            for r in rows:
                ts=r["ts"]
                clock=datetime.fromtimestamp(ts/1000,tz=ALL.PURCHASED.core.UTC8)
                if clock.date()!=day:
                    raise ValueError("Private candidate raw timestamp crosses source day")
                bars.append({
                    "symbol":canonical,"period":period,"trading_date":ds,
                    "source_timestamp_ms":ts,
                    "source_beijing_time":clock.strftime("%Y-%m-%d %H:%M"),
                    "value_source":SOURCE_VALUE,
                    "source_file_relative_path":r["source_5min_private_sha256"],
                    "source_row_group":None,"h5_native_datetime":None,
                    **{f:r[f] for f in ALL.FIELDS},
                })
            private_count+=len(rows)
            audited.append(ds)
        if len(bars)>max_result_bars:
            raise ValueError("Combined stockday bars exceed query output bound")
    bars.sort(key=lambda r:r["source_timestamp_ms"])
    if len({r["source_timestamp_ms"] for r in bars})!=len(bars):
        raise ValueError("Purchased/private highcycle timestamp overlap")
    if any(row["symbol"]!=canonical or row["period"]!=period for row in bars):
        raise ValueError("Foreign symbol or period in unified research query")
    bought=len(base["bars"])
    if bought+private_count!=len(bars):
        raise ValueError("Purchased-first candidate source counts inconsistent")
    summary={
        "status":OUTPUT_STATUS,
        "symbol":canonical,"period":period,
        "from_date":start.isoformat(),"to_date":end.isoformat(),
        "matching_bar_count":len(bars),
        "bars_by_source":{"purchased_parquet":bought,
                          SOURCE_VALUE:private_count},
        "private_candidate_source_days_checked":sorted(audited),
        "private_highcycle_explicitly_enabled":allow_private_highcycle,
        "purchased_stockday_priority":True,
        "private_candidate_requires_no_purchased_highcycle_stockday":True,
        "private_source_5min_sha_rederived_for_selected_symbol_day":True
            if private_count else None,
        "vendor_physical_units_certified":False,
        "time_label_semantics_certified":False,
        "corporate_adjustments_certified":False,
        "ready_for_production_query":False,
        "ready_for_h5_mirror":False,
        "original_market_files_modified":False,
        "private_or_production_active_pointer_modified":False,
        "new_market_or_index_files_written":False,
        "no_raw_ohlcva_in_summary":True,
    }
    return {"bars":bars,"safe_summary":summary}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--symbol",required=True)
    p.add_argument("--period",choices=ALL.PERIODS,required=True)
    p.add_argument("--from-day",required=True)
    p.add_argument("--through-day",required=True)
    p.add_argument("--allow-private-highcycle",action="store_true")
    p.add_argument("--max-result-bars",type=int,default=10000)
    p.add_argument("--max-candidate-rows",type=int,default=30000000)
    a=p.parse_args(argv)
    try:
        result=query_bars(a.root,a.symbol,a.period,a.from_day,a.through_day,
            allow_private_highcycle=a.allow_private_highcycle,
            max_candidate_rows=a.max_candidate_rows,
            max_result_bars=a.max_result_bars)
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as err:
        p.error("Private highcycle purchased-first research query refused: "+
                type(err).__name__+": "+str(err))
    print(json.dumps(result["safe_summary"],ensure_ascii=False,
                     sort_keys=True,separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
