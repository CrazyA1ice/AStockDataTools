#!/usr/bin/env python3
"""Read-only cross-VENDOR TDX vs purchased Parquet day+5min audit.

One canonical symbol, one Beijing date. The Parquet 5min START labels are
matched with TDX 5min END labels by +5 minutes, not by raw timestamp.
The distinct Parquet 241-minute opening record is deliberately NOT read or
reconciled here. No OHLCVA or per-bar residuals leave Python memory.
No source, private cache, overlay or production query changes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent


def _load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


native=_load("tdx_cross_source_native","audit-tdx-native-three-period-readonly.py")
parquet=_load("tdx_cross_source_purchased","query-parquet-primary-readonly.py")
FIELDS=native.FIELDS
FORMAT="AStockDataTools bounded TDX vs Parquet daily and 5min parity audit v1"


def _native_bars(files,symbol,day_text,max_source_bytes):
    # Mandatory 1min/5min/day source integrity gate. This is a real
    # recalculation, never a user-editable report used as a shortcut.
    evidence=native.audit(files["day"],files["5min"],files["1min"],
                          symbol,day_text,max_source_bytes)
    day=native.probe._date(day_text,"day")
    result={}
    for period in ("day","5min"):
        meta=native.probe.inspect(files[period],symbol,day_text,max_source_bytes)
        result[period]=native._read_day_values(
            files[period],period,day,meta,max_source_bytes)
        if meta["source_content_sha256"]!=evidence["input"][period][
                "source_content_sha256"]:
            raise ValueError("TDX source hash changed since native consistency audit")
    return evidence,result


def _verify_stat_manifest(root,manifest):
    # Query planning holds file sizes/mtimes, not content SHA. Fail closed
    # when any original source stat changes between planning and reporting.
    base=Path(root).resolve()
    purchased=(base/"AllCycleAStockData").resolve()
    if type(manifest) is not list or not manifest:
        raise ValueError("Empty purchased stat manifest")
    names=set()
    for entry in manifest:
        if type(entry) is not dict or set(entry)!={
                "relative_path","size_bytes","mtime_ns"}:
            raise ValueError("Malformed purchased stat manifest entry")
        name=entry["relative_path"]
        if (type(name) is not str or "\\\\" in name or
                not name.startswith("AllCycleAStockData/") or
                ".." in Path(name).parts or name in names):
            raise ValueError("Unsafe purchased stat manifest path")
        names.add(name)
        file=base/name
        if (file.is_symlink() or not file.is_file() or
                not file.resolve().is_relative_to(purchased)):
            raise ValueError("Purchased source path escaped or disappeared")
        st=file.stat()
        if (type(entry["size_bytes"]) is not int
                or type(entry["mtime_ns"]) is not int
                or st.st_size!=entry["size_bytes"]
                or st.st_mtime_ns!=entry["mtime_ns"]):
            raise ValueError("Purchased source stat changed during reconciliation")


def _purchase_bars(root,symbol,day_text,budget):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Parquet root must be a real existing data directory")
    if not (root/"AllCycleAStockData").is_dir():
        raise ValueError("Purchased AllCycleAStockData root missing")
    got={}
    provenance={}
    for period,max_results in (("day",2),("5min",49)):
        query=parquet.query_bars(
            root,symbol,period,day_text,day_text,
            max_candidate_rows=budget,max_result_bars=max_results,
            local_cache=False)
        summary=query["safe_summary"]
        if (summary.get("symbol")!=symbol or summary.get("period")!=period
                or summary.get("from_date")!=day_text
                or summary.get("to_date")!=day_text
                or summary.get("local_cache_used") is not False
                or summary.get("no_h5_read") is not True):
            raise ValueError("Unexpected purchased Parquet query metadata")
        got[period]=query["bars"]
        # These are STAT-ONLY attributes, not content SHA or proof of
        # source immutability. Never export individual paths.
        manifest=summary.get("source_file_stat_provenance")
        _verify_stat_manifest(root,manifest)
        stamp=hashlib.sha256(json.dumps(
            sorted(manifest,key=lambda x:x["relative_path"]),sort_keys=True,
            separators=(",",":")).encode("utf-8")).hexdigest()
        provenance[period]={
            "source_manifest_stat_only_sha256":stamp,
            "source_files_examined":summary["source_files_examined"],
            "candidate_source_rows_upper_bound":
                summary["candidate_source_rows_upper_bound"],
            "matching_bar_count":summary["matching_bar_count"],
            "source_manifest_is_stat_only_not_content_authenticated":True,
        }
    return got,provenance


def _convert_purchased(bars,period,day_text):
    if period=="day":
        if len(bars)!=1 or bars[0]["trading_date"]!=day_text:
            raise ValueError("Parquet daily record missing, duplicate or foreign")
        return [(None,tuple(float(bars[0][name]) for name in FIELDS))]
    expected=tuple(t-5 for t in native.probe.time_profiles("5min")[
        "5min_end_48"])
    if len(bars)!=48:
        raise ValueError("Parquet 5min requires exactly 48 records")
    formatted=[]
    for idx,bar in enumerate(bars):
        if bar.get("trading_date")!=day_text:
            raise ValueError("Foreign purchased five-minute source date")
        label=bar.get("source_beijing_time")
        if type(label) is not str:
            raise ValueError("Purchased timestamp label is not text")
        try:
            parsed=datetime.strptime(label,"%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise ValueError("Malformed Parquet raw Beijing time label") from exc
        if (parsed.date().isoformat()!=day_text or
                parsed.hour*60+parsed.minute!=expected[idx]):
            raise ValueError(
                "Parquet 5min time grid is not 48 START labels; "
                "never align to TDX END labels by equal raw timestamps")
        if any(type(bar.get(k)) not in (float,int) or
               not math.isfinite(bar[k]) for k in FIELDS):
            raise ValueError("Nonfinite/malformed purchased OHLCVA")
        # Output tuple uses canonical END key, derived from original START
        # label by +5 minutes. The raw input record is never changed.
        formatted.append((expected[idx]+5,
                          tuple(float(bar[k]) for k in FIELDS)))
    return formatted


def audit(root,day_file,minute5_file,minute1_file,symbol,day_text,
          max_source_bytes=native.probe.MAX_SOURCE_BYTES,
          max_candidate_rows=15000000):
    if (type(max_candidate_rows) is not int or
            not 1<=max_candidate_rows<=30000000):
        raise ValueError("Bound candidate rows in 1..30000000")
    if type(symbol) is not str or symbol!=symbol.upper():
        raise ValueError("Canonical uppercase stock symbol required")
    if (type(max_source_bytes) is not int
            or not 32<=max_source_bytes<=native.probe.MAX_SOURCE_BYTES):
        raise ValueError("Invalid TDX source byte budget")
    files={"day":day_file,"5min":minute5_file,"1min":minute1_file}
    prior,tdx=_native_bars(files,symbol,day_text,max_source_bytes)
    purchased,src_meta=_purchase_bars(
        root,symbol,day_text,max_candidate_rows)
    converted={p:_convert_purchased(purchased[p],p,day_text)
               for p in ("day","5min")}
    if [key for key,_ in tdx["5min"]] != [
            key for key,_ in converted["5min"]]:
        raise ValueError("Five-minute interval END keys mismatch")
    comparisons={
        "tdx_5min_vs_parquet_5min_by_interval":
            native._compare(tdx["5min"],converted["5min"]),
        "tdx_daily_vs_parquet_daily":
            native._compare(tdx["day"],converted["day"]),
        "parquet_5min_aggregate_vs_parquet_daily":
            native._compare(
                [(None,native._aggregate(converted["5min"]))],
                converted["day"]),
    }
    tdx_internal_all_close=all(
        item["within_diagnostic_tolerance"]==item["n"]
        for comparison in prior["comparisons"].values()
        for item in comparison.values())
    return {
        "format":FORMAT,"symbol":symbol,"date":day_text,
        "tdx_internal_three_period_checked_against_real_bytes":True,
        "tdx_internal_three_period_all_fields_within_tolerance":
            tdx_internal_all_close,
        "tdx_source_sha256":{
            p:prior["input"][p]["source_content_sha256"]
            for p in ("day","1min","5min")},
        "tdx_source_counts":{"day":1,"1min":240,"5min":48},
        "parquet_source_counts":{"day":1,"5min":48},
        "parquet_stat_only_provenance":src_meta,
        "comparisons":comparisons,
        "five_minute_alignment":"TDX ending label == Parquet starting label + 5 minutes",
        "parquet_one_minute_241_special_opening_not_compared":True,
        "cross_vendor_volume_and_amount_unit_convention_unverified":True,
        "strict_and_tolerant_price_fields_not_auto_corrected":True,
        "no_raw_ohlcva_or_individual_times_in_report":True,
        "only_tdx_and_purchased_parquet_read":True,
        "h5_accessed":False,
        "local_private_cache_read_or_written":False,
        "source_market_files_modified":False,
        "staging_or_production_union_performed":False,
        "eligible_for_automatic_production_union":False,
    }


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet-root",type=Path,required=True)
    ap.add_argument("--tdx-day-file",type=Path,required=True)
    ap.add_argument("--tdx-5min-file",type=Path,required=True)
    ap.add_argument("--tdx-1min-file",type=Path,required=True)
    ap.add_argument("--symbol",required=True)
    ap.add_argument("--date",required=True)
    ap.add_argument("--max-tdx-file-bytes",type=int,default=native.probe.MAX_SOURCE_BYTES)
    ap.add_argument("--max-candidate-rows",type=int,default=15000000)
    ap.add_argument("--read-only",action="store_true",required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        output=native.probe.safe_out(args.out)
        result=audit(
            args.parquet_root,args.tdx_day_file,args.tdx_5min_file,
            args.tdx_1min_file,args.symbol,args.date,
            args.max_tdx_file_bytes,args.max_candidate_rows)
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open("x",encoding="utf-8") as fd:
            json.dump(result,fd,indent=2,ensure_ascii=False,allow_nan=False)
            fd.write("\n")
        print("Saved read-only cross-vendor TDX/Parquet summary:",output)
        print("48 corresponding five-minute intervals and daily record examined.")
        print("No purchased/TDX OHLCVA values exported or source modified.")
    except (ValueError,TypeError,OSError,OverflowError,
            ModuleNotFoundError,KeyError,ZeroDivisionError) as exc:
        ap.error(str(exc))


if __name__=="__main__":
    main()
