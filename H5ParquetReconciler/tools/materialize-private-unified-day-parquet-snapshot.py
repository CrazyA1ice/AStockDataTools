#!/usr/bin/env python3
"""Materialize a BOUNDED PRIVATE daily Parquet-first + H5-gap candidate snapshot.

This is a non-production research artifact, never a replacement for purchased
Parquet, original Hikyuu H5, or the production query route. All real prices,
amounts and quantities remain ONLY in module-private ignored work/, not SAFE
reports or git. An explicit *prepared* overlay version is mandatory.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
WORK=MODULE/"work"
SNAPSHOTS=WORK/"unified_parquet"/"snapshots"
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools immutable private Parquet-primary daily materialization v1"
STOCK_FIELDS=("open","high","low","close","volume","amount")
SOURCES=("purchased_parquet","private_hikyuu_h5_gap_candidate")
MAX_ROWS=5000

SPEC=importlib.util.spec_from_file_location(
    "bounded_daily_batch_consumer",
    HERE/"query-parquet-primary-day-overlay-batch-readonly.py")
BATCH=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BATCH)


def hash_file(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(1<<20),b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_paths(snapshot_dir,report_path):
    """Require two NEW module-local outputs; no existing or symlinked parents."""
    if any(p.is_symlink() for p in (
            WORK,WORK/"unified_parquet",SNAPSHOTS,REPORTS)):
        raise ValueError("Unsafe module output parent symlink")
    proposed=Path(snapshot_dir)
    if (not re.fullmatch(r"snapshot_[a-f0-9]{12,32}",proposed.name)
            or proposed.is_symlink() or proposed.exists()
            or proposed.resolve().parent!=SNAPSHOTS.resolve()):
        raise ValueError("Snapshot must be a NEW direct private snapshots/snapshot_<hex> directory")
    safe=Path(report_path)
    if (safe.suffix.lower()!=".json" or safe.is_symlink() or safe.exists()
            or safe.resolve().parent!=REPORTS.resolve()):
        raise ValueError("SAFE output must be NEW JSON directly under module reports/")
    return proposed.resolve(),safe.resolve()


def normalize_rows(result,version_sha,expected_symbols,first,last):
    summary=result.get("safe_summary")
    by_symbol=result.get("bars_by_symbol")
    if (type(summary) is not dict or type(by_symbol) is not dict
            or summary.get("format")!=BATCH.FORMAT
            or summary.get("private_version_sha256")!=version_sha
            or summary.get("from_date")!=first
            or summary.get("to_date")!=last
            or summary.get("symbols")!=list(expected_symbols)
            or summary.get("purchased_parquet_priority") is not True
            or summary.get("private_overlay_stages_sha_and_keys_verified") is not True
            or summary.get("selected_private_stages_final_snapshot_reverified") is not True
            or summary.get("no_source_market_writes") is not True
            or summary.get("no_production_query_switch") is not True
            or summary.get("no_raw_ohlcva_in_safe_summary") is not True
            or summary.get("no_active_pointer_read_or_change") is not True
            or summary.get("private_version_selection_mode")!="explicit_immutable_version_sha256"
            or type(summary.get("per_symbol_counts")) is not dict
            or not 1<=summary.get("symbol_count",0)<=BATCH.MAX_SYMBOLS
            or not isinstance(summary.get("symbols"),list)
            or set(by_symbol)!=set(summary["symbols"])
            or set(by_symbol)!=set(summary["per_symbol_counts"])):
        raise ValueError("Explicit verified immutable purchased-first query required")
    if type(version_sha) is not str or not re.fullmatch("[a-f0-9]{64}",version_sha):
        raise ValueError("Explicit immutable version SHA256 is required")
    rows=[]
    seen=set()
    per_source={key:0 for key in SOURCES}
    per_symbol={}
    for sym in summary["symbols"]:
        values=by_symbol[sym]
        if (type(sym) is not str or not re.fullmatch("(SH|SZ|BJ)[0-9]{6}",sym)
                or type(values) is not list):
            raise ValueError("Invalid canonical A-share batch member")
        per_source_sym={key:0 for key in SOURCES}
        for bar in values:
            if type(bar) is not dict or bar.get("symbol")!=sym or bar.get("period")!="day":
                raise ValueError("Invalid original batched day bar")
            try:
                d=date.fromisoformat(bar["trading_date"])
            except (KeyError,ValueError,TypeError):
                raise ValueError("Bad private query trading date") from None
            if d.isoformat()!=bar["trading_date"] or not first<=d.isoformat()<=last:
                raise ValueError("Noncanonical or out-of-window trading date")
            key=(sym,d.isoformat())
            if key in seen:
                raise ValueError("Purchased/private duplicate stock-day blocked")
            seen.add(key)
            ts=bar.get("source_timestamp_ms")
            source=bar.get("value_source")
            if type(ts) is not int or ts<=0 or source not in SOURCES:
                raise ValueError("Bad timestamp or untrusted source label")
            values_for_fields={}
            for f in STOCK_FIELDS:
                v=bar.get(f)
                if type(v) is not float or not math.isfinite(v) or v<0:
                    raise ValueError("Missing or nonfinite native day value")
                values_for_fields[f]=v
            if (min(values_for_fields[k] for k in ("open","high","low","close"))<=0
                    or values_for_fields["high"]+1e-8<max(
                        values_for_fields["open"],values_for_fields["low"],
                        values_for_fields["close"])
                    or values_for_fields["low"]-1e-8>min(
                        values_for_fields["open"],values_for_fields["high"],
                        values_for_fields["close"])):
                raise ValueError("Unsafe original OHLC geometry")
            per_source[source]+=1
            per_source_sym[source]+=1
            rows.append({
                "ts":ts, "trading_date":d.isoformat(),
                "symbol":sym, **values_for_fields,
                "value_source":source,
            })
        expected=summary["per_symbol_counts"][sym]
        if (type(expected) is not dict
                or expected.get("purchased_bars")!=per_source_sym["purchased_parquet"]
                or expected.get("private_bars")!=per_source_sym["private_hikyuu_h5_gap_candidate"]
                or expected.get("returned_bars")!=len(values)):
            raise ValueError("Source accounting and original batch disagree")
        per_symbol[sym]={
            "purchased_bars":per_source_sym["purchased_parquet"],
            "private_bars":per_source_sym["private_hikyuu_h5_gap_candidate"],
            "returned_bars":len(values)}
    if (not 1<=len(rows)<=MAX_ROWS
            or summary.get("matching_bar_count")!=len(rows)
            or summary.get("purchased_parquet_bars_returned")!=per_source["purchased_parquet"]
            or summary.get("private_overlay_bars_returned")!=per_source[
                "private_hikyuu_h5_gap_candidate"]):
        raise ValueError("Bounded row accounting failed")
    rows.sort(key=lambda b:(b["trading_date"],b["symbol"],b["ts"]))
    return rows,per_source,per_symbol


def schema(pa):
    return pa.schema([
        pa.field("ts",pa.int64()),
        pa.field("trading_date",pa.string()),
        pa.field("symbol",pa.string()),
        *(pa.field(f,pa.float64()) for f in STOCK_FIELDS),
        pa.field("value_source",pa.string()),
    ])


def materialize(root,symbols,first,last,version_sha,snapshot_dir,safe_report,
                max_candidate_rows_per_symbol=300000,
                max_total_candidate_rows=3000000,
                max_overlay_source_rows=30000):
    """Create one additive private Parquet, its hash-verified manifest and SAFE.

    The supplied private version is NEVER activated. Original source files are
    read-only and the caller gets no unverified partial SAFE on failure.
    """
    folder,report=safe_paths(snapshot_dir,safe_report)
    if type(symbols) not in (list,tuple) or not 1<=len(symbols)<=BATCH.MAX_SYMBOLS:
        raise ValueError("Explicit bounded symbol list required")
    # No filesystem writes until the existing read-only batch has passed all
    # live-source, version, purchased priority and stage snapshot verification.
    result=BATCH.query_private_day_overlay_batch(
        root,symbols,first,last,version_sha,
        max_candidate_rows_per_symbol=max_candidate_rows_per_symbol,
        max_total_candidate_rows=max_total_candidate_rows,
        max_result_bars_per_symbol=MAX_ROWS,
        max_total_result_bars=MAX_ROWS,
        max_overlay_source_rows=max_overlay_source_rows,
        use_private_active=False)
    rows,by_source,per_symbol=normalize_rows(
        result,version_sha,symbols,first,last)
    import pyarrow as pa
    import pyarrow.parquet as pq
    target_schema=schema(pa)
    table=pa.Table.from_pylist(rows,schema=target_schema)
    if table.num_rows!=len(rows) or table.schema!=target_schema:
        raise ValueError("Private day schema or row count failed")
    folder.parent.mkdir(parents=True,exist_ok=True)
    folder.mkdir(exist_ok=False)
    parquet=folder/"day.parquet"
    pq.write_table(table,parquet,compression="zstd")
    file_sha=hash_file(parquet)
    # Do not call a Parquet file 'validated' solely because write returned.
    actual=pq.read_table(parquet,schema=target_schema)
    if (actual.num_rows!=len(rows)
            or actual.schema!=target_schema
            or actual.to_pylist()!=rows):
        raise ValueError("Written private Parquet does not exactly roundtrip")
    if hash_file(parquet)!=file_sha:
        raise ValueError("Private Parquet file changed while verifying snapshot")
    manifest={
        "format":FORMAT,
        "state":"private_materialized_verified_not_activated",
        "period":"day",
        "date_window":[first,last],
        "symbol_count":len(symbols),
        "rows":len(rows),
        "purchased_rows":by_source["purchased_parquet"],
        "h5_gap_candidate_rows":by_source["private_hikyuu_h5_gap_candidate"],
        "per_symbol_counts":per_symbol,
        "origin_private_version_sha256":version_sha,
        "private_parquet_sha256":file_sha,
        "private_file":"day.parquet",
        "all_written_values_roundtrip_exactly":True,
        "private_h5_gap_units_remain_unverified_candidate":True,
        "licensed_parquet_to_native_h5_amount_lossless_certified":False,
        "source_market_files_written":False,
        "production_query_route_switched":False,
        "production_h5_mirror_created":False,
        "private_active_overlay_pointer_changed":False,
    }
    manifest_path=folder/"manifest.json"
    with manifest_path.open("x",encoding="utf-8") as stream:
        json.dump(manifest,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")
    manifest_sha=hash_file(manifest_path)
    if hash_file(parquet)!=file_sha or hash_file(manifest_path)!=manifest_sha:
        raise ValueError("Final private snapshot hash drift")
    safe={
        "format":FORMAT,
        "state":manifest["state"],
        "snapshot_relative_path":str(folder.relative_to(MODULE)).replace("\\","/"),
        "manifest_sha256":manifest_sha,
        "private_parquet_sha256":file_sha,
        "period":"day",
        "symbol_count":len(symbols),
        "row_count":len(rows),
        "purchased_rows":manifest["purchased_rows"],
        "h5_gap_candidate_rows":manifest["h5_gap_candidate_rows"],
        "origin_private_version_sha256":version_sha,
        "all_written_values_roundtrip_exactly":True,
        "h5_gap_units_unverified_candidate":True,
        "purchased_parquet_priority_verified":True,
        "original_market_files_modified":False,
        "production_query_route_switched":False,
        "original_hikyuu_h5_modified":False,
        "ready_for_full_market_mirror":False,
        "raw_ohlcva_or_original_source_paths_exported_in_safe":False,
    }
    with report.open("x",encoding="utf-8") as stream:
        json.dump(safe,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--symbols",nargs="+",required=True)
    p.add_argument("--from-date",required=True)
    p.add_argument("--to-date",required=True)
    p.add_argument("--version-sha256",required=True)
    p.add_argument("--snapshot-dir",type=Path,required=True)
    p.add_argument("--safe-report",type=Path,required=True)
    p.add_argument("--read-only-sources",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        safe=materialize(
            args.source_root,args.symbols,args.from_date,args.to_date,
            args.version_sha256,args.snapshot_dir,args.safe_report)
        print("PRIVATE Parquet-first day snapshot:",safe["snapshot_relative_path"])
        print("Rows:",safe["row_count"],"purchased:",safe["purchased_rows"],
              "H5 gap candidates:",safe["h5_gap_candidate_rows"])
        print("SAFE proof:",args.safe_report)
        print("Purchased Parquet, original H5 or production routing changed: NO")
    except (ValueError,TypeError,KeyError,OverflowError,OSError,
            ImportError,ModuleNotFoundError):
        p.error("Private immutable materialization rejected; source data unchanged")


if __name__=="__main__":
    main()
