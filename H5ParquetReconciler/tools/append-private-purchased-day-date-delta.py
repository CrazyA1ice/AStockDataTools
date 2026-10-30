#!/usr/bin/env python3
"""Append real NEW TRADING DATES from purchased day Parquet to a private v2 view.

The base is an explicitly registered, independently verified private joined
logical version (base snapshot + earlier stock-universe delta). Only newly
observed purchased *daily* bars strictly later than its end date are admitted.
H5 isn't opened or used as fallback; a date absent from purchased data stays
ABSENT, not implicitly filled. This never modifies the parent's two Parquets,
original licensed sources, private active pointers or production routing.

If no purchased bars exist, write a truthful aggregate NO_DATA SAFE only,
with NO empty Parquet delta. This is an availability observation rather than
a guarantee about exchange trading dates, or future source deliveries.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
from datetime import date,datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
WORK=MODULE/"work"/"unified_parquet"
PARTITIONS=WORK/"date_deltas"
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools private additive purchased-only new-day Parquet partition v1"
MAX_ROWS=500
MAX_SYMBOLS=10
FIELDS=("open","high","low","close","volume","amount")


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


REG=load("purchased_newdate_parent_logical_registry",
         "register-private-joined-day-logical-version.py")
READER=REG.READER
PURCHASED=load("purchased_newdate_readonly_source_query",
               "query-parquet-primary-readonly.py")
MAT=load("purchased_newdate_private_parquet_schema",
         "materialize-private-unified-day-parquet-snapshot.py")


def outputs(directory,out):
    if any(p.is_symlink() for p in (MODULE/"work",WORK,PARTITIONS,REPORTS)):
        raise ValueError("Unsafe private new-date output parent symlink")
    root=Path(directory)
    if (not re.fullmatch(r"date_delta_[0-9a-f]{12,32}",root.name)
            or root.is_symlink() or root.exists()
            or root.resolve().parent!=PARTITIONS.resolve()):
        raise ValueError("New date delta requires unused module-private date_delta_<hex>")
    report=READER.direct_report(out,for_output=True)
    return root.resolve(),report


def validate_dates(entry,symbols,first,last):
    if (type(symbols) not in (list,tuple)
            or not 1<=len(symbols)<=MAX_SYMBOLS or len(set(symbols))!=len(symbols)
            or any(type(s) is not str
                   or not re.fullmatch("(SH|SZ|BJ)[0-9]{6}",s) for s in symbols)):
        raise ValueError("1..10 distinct canonical A-share stocks required")
    if type(first) is not str or type(last) is not str:
        raise ValueError("New inclusive day range must use ISO dates")
    try:
        a,b=date.fromisoformat(first),date.fromisoformat(last)
        parent_end=date.fromisoformat(entry["date_window"][1])
        if (a.isoformat()!=first or b.isoformat()!=last
                or a<=parent_end or a>b or (b-a).days>30
                or a.year!=b.year):
            raise ValueError("Date delta must be a later bounded 1..31-day window")
    except (IndexError,KeyError,TypeError,ValueError):
        raise ValueError("Date delta must be a later bounded 1..31-day window") from None
    return a,b


def normalize_one(result,sym,first,last):
    safe=result.get("safe_summary")
    raw=result.get("bars")
    if (type(safe) is not dict or type(raw) is not list
            or safe.get("format")!="AStockDataTools purchased Parquet bounded query summary v1"
            or safe.get("symbol")!=sym or safe.get("period")!="day"
            or safe.get("from_date")!=first or safe.get("to_date")!=last
            or safe.get("matching_bar_count")!=len(raw)
            or safe.get("no_h5_read") is not True
            or safe.get("source_market_files_modified") is not False
            or safe.get("no_automatic_gaps_fill") is not True
            or safe.get("source_quantity_unit_rescaling_applied") is not False
            or safe.get("no_raw_ohlcva_in_safe_summary") is not True
            or safe.get("local_cache_used") is not False
            or safe.get("query_delivery")!="parquet_source_scan"):
        raise ValueError("Only source-verified purchased-only cold Parquet daily query admitted")
    rows=[]
    seen=set()
    for bar in raw:
        if (type(bar) is not dict or bar.get("symbol")!=sym
                or bar.get("period")!="day"):
            raise ValueError("Untrusted purchased new-date row identity")
        day=bar.get("trading_date")
        ts=bar.get("source_timestamp_ms")
        if (type(day) is not str or type(ts) is not int
                or ts<=0 or ts%60000 or not first<=day<=last):
            raise ValueError("Untrusted new purchased day timestamp")
        try:
            if (date.fromisoformat(day).isoformat()!=day
                    or datetime.fromtimestamp(
                        ts/1000,tz=PURCHASED.core.UTC8).date().isoformat()!=day):
                raise ValueError("New purchased source day/time mismatch")
        except (OverflowError,ValueError):
            raise ValueError("New purchased source day/time mismatch") from None
        if day in seen:
            raise ValueError("Duplicate purchased stock-day")
        seen.add(day)
        values={}
        for field in FIELDS:
            v=bar.get(field)
            if type(v) is not float or not math.isfinite(v) or v<0:
                raise ValueError("New purchased OHLCVA missing or nonfinite")
            values[field]=v
        op,hi,lo,cl=(values[k] for k in ("open","high","low","close"))
        if min(op,hi,lo,cl)<=0 or hi+1e-8<max(op,lo,cl) or lo-1e-8>min(op,hi,cl):
            raise ValueError("Unsafe purchased day OHLC geometry")
        rows.append({"ts":ts,"trading_date":day,"symbol":sym,
                     **values,"value_source":"purchased_parquet"})
    rows.sort(key=lambda x:(x["trading_date"],x["symbol"],x["ts"]))
    return rows


def precheck(version_sha,symbols,first,last):
    READER.require_sha(version_sha)
    if REG.LOCK.exists() or REG.LOCK.is_symlink():
        raise ValueError("Private logical version update in progress")
    entry=REG.load_version(version_sha)
    REG.check_version_files(entry)
    a,b=validate_dates(entry,symbols,first,last)
    # New DATE partition is only for stocks in the registered prior view.
    # Prevent accidentally smuggling a brand-new stock into a date extension.
    _,_,_,_,parent_meta=REG.J.ADD.trusted_parent(
        entry["parent_private_version_sha256"])
    delta_safe=READER.REPORTS/entry["delta_safe_basename"]
    _,_,delta_manifest,_=REG.J.get_delta_safe(
        delta_safe,entry["parent_private_version_sha256"])
    additional=json.loads(delta_manifest.read_text(encoding="utf-8"))
    universe=set(parent_meta["per_symbol_counts"])|set(additional["new_symbols"])
    if (len(universe)!=entry["joined_stocks"]
            or any(s not in universe for s in symbols)):
        raise ValueError("New-date stocks must exist in registered logical parent")
    entry_file=REG.VERSIONS/(version_sha+".json")
    file_sha=READER.sha256_file(entry_file)
    return entry,file_sha,a,b


def append(source_root,version_sha,symbols,first,last,delta_dir,out):
    folder,report=outputs(delta_dir,out)
    base,base_file_sha,start,end=precheck(version_sha,symbols,first,last)
    # A metadata-only stat fingerprint helps catch additions/updates between
    # per-stock purchased queries. Not a cryptographic market-source hash.
    sig=PURCHASED.private_cache.source_signature(
        source_root,"day",start,end,PURCHASED.core)
    rows=[]
    counts=[]
    for sym in symbols:
        result=PURCHASED.query_bars(
            source_root,sym,"day",first,last,
            max_candidate_rows=300000,
            max_result_bars=40,
            local_cache=False)
        group=normalize_one(result,sym,first,last)
        if len(group)>40:
            raise ValueError("New purchased stock-day budget exceeded")
        rows.extend(group)
        counts.append(len(group))
        if len(rows)>MAX_ROWS:
            raise ValueError("Bounded purchased new-date result too large")
    if sig!=PURCHASED.private_cache.source_signature(
            source_root,"day",start,end,PURCHASED.core):
        raise ValueError("Purchased source file stat inventory changed while reading")
    second,sha2,_,_=precheck(version_sha,symbols,first,last)
    if second!=base or sha2!=base_file_sha:
        raise ValueError("Registered logical parent changed during new-date query")
    # Never guess that a missing purchased date is a verified H5 gap.
    # Only observed purchased daily keys can become new private records.
    rows.sort(key=lambda x:(x["trading_date"],x["symbol"],x["ts"]))
    if len({(r["symbol"],r["trading_date"]) for r in rows})!=len(rows):
        raise ValueError("Duplicate purchased stock-day across requested symbols")
    summary={
        "format":FORMAT,
        "status":"purchased_new_date_not_available_no_partition" if not rows
                 else "private_purchased_new_date_delta_verified_not_activated",
        "parent_joined_version_sha256":version_sha,
        "parent_version_file_sha256":base_file_sha,
        "parent_joined_rows_unchanged":base["joined_rows"],
        "parent_joined_stocks":base["joined_stocks"],
        "period":"day",
        "requested_first":first,"requested_last":last,
        "requested_stock_count":len(symbols),
        "new_purchased_rows":len(rows),
        "stocks_with_new_purchased_rows":sum(c>0 for c in counts),
        "source_stat_manifest_sha256_stat_only":sig["manifest_sha256_stat_only"],
        "source_stat_manifest_file_count":sig["manifest_file_count"],
        "source_stat_proof_is_not_cryptographic_file_hash":True,
        "no_h5_fallback_or_implicit_gap_fill":True,
        "missing_source_dates_not_declared_exchange_holidays":True,
        "new_date_parquet_created":bool(rows),
        "parent_partitions_rewritten":False,
        "purchased_market_parquet_modified":False,
        "original_hikyuu_h5_opened_or_modified":False,
        "private_active_pointers_read_or_modified":False,
        "production_query_route_modified":False,
        "h5_candidate_amount_units_still_unverified":True,
        "ready_for_full_market_mirror":False,
        "no_raw_ohlcva_or_stock_symbols_in_safe":True,
    }
    if rows:
        import pyarrow as pa
        import pyarrow.parquet as pq
        folder.parent.mkdir(parents=True,exist_ok=True)
        folder.mkdir(exist_ok=False)
        parquet=folder/"day.parquet"
        table=pa.Table.from_pylist(rows,schema=READER.expected_schema(pa))
        pq.write_table(table,parquet,compression="zstd")
        parquet_sha=READER.sha256_file(parquet)
        decoded=pq.read_table(parquet,schema=READER.expected_schema(pa))
        if (decoded.schema!=READER.expected_schema(pa)
                or decoded.to_pylist()!=rows
                or READER.sha256_file(parquet)!=parquet_sha):
            raise ValueError("Purchased-only new-date private Arrow roundtrip failed")
        per={s:n for s,n in zip(symbols,counts)}
        meta={
            "format":FORMAT,"status":summary["status"],
            "period":"day","requested_first":first,"requested_last":last,
            "parent_joined_version_sha256":version_sha,
            "parent_version_file_sha256":base_file_sha,
            "parent_joined_rows_unchanged":base["joined_rows"],
            "new_purchased_rows":len(rows),
            "per_stock_purchased_counts":per,
            "delta_private_file":"day.parquet",
            "delta_parquet_sha256":parquet_sha,
            "source_stat_manifest_sha256_stat_only":sig[
                "manifest_sha256_stat_only"],
            "source_stat_proof_is_not_cryptographic_file_hash":True,
            "all_values_roundtrip_exactly":True,
            "h5_source_read_or_fallback_used":False,
            "purchased_market_parquet_modified":False,
            "parent_partitions_rewritten":False,
            "private_active_pointers_read_or_modified":False,
            "production_query_route_modified":False,
            "ready_for_full_market_mirror":False,
        }
        manifest=folder/"manifest.json"
        with manifest.open("x",encoding="utf-8") as stream:
            json.dump(meta,stream,sort_keys=True,ensure_ascii=False,indent=2)
            stream.write("\n")
        summary["new_date_delta_relative_path"]=(
            str(folder.relative_to(MODULE)).replace("\\","/"))
        summary["delta_parquet_sha256"]=parquet_sha
        summary["delta_manifest_sha256"]=READER.sha256_file(manifest)
        summary["all_new_values_roundtrip_exactly"]=True
    else:
        summary["new_date_delta_relative_path"]=None
        summary["all_new_values_roundtrip_exactly"]=False
    # Fail before reporting success if original source inventory or parent
    # changed during the materialization. If it did, the untrusted, unreported
    # newly created private directory is not eligible for subsequent use.
    third,sha3,_,_=precheck(version_sha,symbols,first,last)
    if (third!=base or sha3!=base_file_sha
            or sig!=PURCHASED.private_cache.source_signature(
                source_root,"day",start,end,PURCHASED.core)):
        raise ValueError("Private parent or purchased source changed before SAFE")
    with report.open("x",encoding="utf-8") as stream:
        json.dump(summary,stream,sort_keys=True,ensure_ascii=False,indent=2)
        stream.write("\n")
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--parent-joined-version",required=True)
    p.add_argument("--symbols",nargs="+",required=True)
    p.add_argument("--from-date",required=True)
    p.add_argument("--to-date",required=True)
    p.add_argument("--delta-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-purchased-source",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=append(a.source_root,a.parent_joined_version,a.symbols,
                      a.from_date,a.to_date,a.delta_dir,a.out)
        print("SAFE purchased-only new-date scan:",a.out)
        print("Status:",result["status"])
        print("New purchased day rows:",result["new_purchased_rows"])
        print("Private new-date Parquet created:",result["new_date_parquet_created"])
        print("Original licensed Parquet/H5 or production route modified: NO")
        print("No H5 fallback attempted; empty purchased days remain UNKNOWN")
    except (ValueError,TypeError,KeyError,OSError,OverflowError,
            ImportError,ModuleNotFoundError):
        p.error("Private purchased-only new-day delta rejected; no original source writes")


if __name__=="__main__":
    main()
