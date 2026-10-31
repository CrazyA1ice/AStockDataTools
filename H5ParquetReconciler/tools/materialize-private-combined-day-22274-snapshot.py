#!/usr/bin/env python3
"""Materialize a BOUNDED 22,274-version Parquet-primary private day snapshot.

Reuses the established v1 private snapshot schema, reader and version
lifecycle, while treating both WHOLE and MIXED candidates as unlicensed
H5-gap candidates. Exact whole/mixed provenance counts are kept in the
additional SAFE and manifest fields, NOT misrepresented as purchased bars.
No original H5/Parquet writes, production pointer changes or H5 mirrors.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BATCH=load("combined_private_day_materializer_source_query",
           "query-private-combined-day-22274-batch-readonly.py")
BASE=load("combined_private_day_materializer_existing_snapshot",
          "materialize-private-unified-day-parquet-snapshot.py")
FORMAT=BASE.FORMAT
FIELDS=BASE.STOCK_FIELDS
ALLOWED={
    "purchased_parquet":"purchased_parquet",
    "private_h5_whole_date_candidate":"private_hikyuu_h5_gap_candidate",
    "private_h5_mixed_stockday_candidate":"private_hikyuu_h5_gap_candidate",
}


def transform(result,symbols,first,last,version_sha):
    s=result.get("safe_summary")
    members=result.get("bars_by_symbol")
    if (type(s) is not dict or type(members) is not dict
            or s.get("format")!=BATCH.FORMAT
            or s.get("state")!="explicit_private_combined_day_batch_one_live_gate_passed"
            or s.get("private_combined_version_sha256")!=version_sha
            or s.get("candidate_total_new_stockday_rows_in_immutable_version")!=22274
            or s.get("full_live_market_keyset_audit_count")!=1
            or s.get("requested_stock_count")!=len(symbols)
            or s.get("same_year_bounded_query") is not True
            or s.get("quarantined_2026_07_16_stockday_bars_not_included")!=5
            or s.get("no_raw_ohlcva_or_symbols_in_safe") is not True
            or s.get("source_priority")!="purchased_parquet_first_exact_stockday_fail_closed_on_overlap"
            or s.get("source_market_files_written") is not False
            or s.get("purchased_parquet_replaced") is not False
            or s.get("private_or_production_active_pointer_modified") is not False
            or s.get("h5_mirror_created") is not False
            or s.get("candidate_source_units_certified") is not False
            or s.get("ready_for_production_query") is not False
            or s.get("ready_for_automatic_market_merge") is not False
            or type(s.get("full_live_recheck_safe_sha256")) is not str
            or set(members)!=set(symbols)):
        raise ValueError("Combined 22,274 source query has no qualifying live gate")
    for k in ("private_combined_version_sha256","full_live_recheck_safe_sha256"):
        import re
        if not re.fullmatch("[0-9a-f]{64}",s[k]):
            raise ValueError("Untrusted 22,274 source SHA")
    start=date.fromisoformat(first)
    end=date.fromisoformat(last)
    if (start.isoformat()!=first or end.isoformat()!=last
            or start.year!=end.year or not start<=end
            or (end-start).days>30):
        raise ValueError("Private snapshot bounded single-year window invalid")
    rows=[]
    counts={name:0 for name in ALLOWED}
    per_symbol={}
    seen=set()
    for symbol in symbols:
        bars=members[symbol]
        if type(bars) is not list:
            raise ValueError("Combined query stock data is not a list")
        each={name:0 for name in ALLOWED}
        for bar in bars:
            if type(bar) is not dict or bar.get("symbol")!=symbol:
                raise ValueError("Combined source stock mismatch")
            source=bar.get("value_source")
            if type(source) is not str or source not in ALLOWED:
                raise ValueError("Unexpected 22,274 source provenance")
            clean=BATCH.Q.validated_source_row(bar,symbol,start,end,source)
            key=(symbol,clean["trading_date"])
            if key in seen:
                raise ValueError("Duplicate purchased/private stockday")
            seen.add(key)
            values={}
            for f in FIELDS:
                v=clean.get(f)
                if type(v) is not float or not math.isfinite(v):
                    raise ValueError("Expected unmodified source float64 OHLCVA")
                values[f]=v
            rows.append({
                "ts":clean["source_timestamp_ms"],
                "trading_date":clean["trading_date"],
                "symbol":symbol,
                **values,
                "value_source":ALLOWED[source],
            })
            counts[source]+=1
            each[source]+=1
        per_symbol[symbol]={
            "purchased_bars":each["purchased_parquet"],
            "private_bars":each["private_h5_whole_date_candidate"]+
                           each["private_h5_mixed_stockday_candidate"],
            "returned_bars":len(bars),
        }
    if (not 1<=len(rows)<=BASE.MAX_ROWS
            or s.get("query_result_stockday_bars")!=len(rows)
            or s.get("purchased_parquet_bars")!=counts["purchased_parquet"]
            or s.get("whole_h5_only_candidate_bars")!=counts["private_h5_whole_date_candidate"]
            or s.get("mixed_h5_only_candidate_bars")!=counts["private_h5_mixed_stockday_candidate"]):
        raise ValueError("Combined 22,274 stockday live provenance totals disagree")
    rows.sort(key=lambda r:(r["trading_date"],r["symbol"],r["ts"]))
    return rows,counts,per_symbol


def materialize(root,symbols,first,last,version_sha,live_safe,private_keys,
                ledger,source2016,source2026,mixed_plan,fresh_recheck_out,
                batch_query_out,snapshot_dir,safe_report,fast_bounded_h5_scan=False,
                max_candidate_rows_per_symbol=30000000,
                max_total_candidate_rows=30000000,
                max_overlay_source_rows=30000):
    folder,out=BASE.safe_paths(snapshot_dir,safe_report)
    fresh=BATCH.PRE.new_report(fresh_recheck_out)
    batch=BATCH.PRE.new_report(batch_query_out)
    if len({folder,out,fresh,batch})!=4:
        raise ValueError("Full-gate, batch, snapshot and materialization SAFE must differ")
    canon,start,end=BATCH.checked_requests(
        symbols,first,last,max_candidate_rows_per_symbol,BASE.MAX_ROWS,
        max_total_candidate_rows,BASE.MAX_ROWS)
    if list(canon)!=list(symbols):
        raise ValueError("Noncanonical private snapshot symbol list")
    # ONLY the established one-gate batch reads source market data. It
    # completes full live source proof and SHA/stat rechecks before this
    # function creates the first private Parquet output.
    result=BATCH.query_batch(
        root,symbols,first,last,version_sha,live_safe,private_keys,
        ledger,source2016,source2026,mixed_plan,fresh,batch,
        max_candidate_rows_per_symbol=max_candidate_rows_per_symbol,
        max_total_candidate_rows=max_total_candidate_rows,
        max_result_bars_per_symbol=BASE.MAX_ROWS,
        max_total_result_bars=BASE.MAX_ROWS,
        max_overlay_source_rows=max_overlay_source_rows,
        fast_bounded_h5_scan=fast_bounded_h5_scan)
    rows,source_counts,per_symbol=transform(result,symbols,first,last,version_sha)
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema=BASE.schema(pa)
    table=pa.Table.from_pylist(rows,schema=schema)
    if table.schema!=schema or table.num_rows!=len(rows):
        raise ValueError("Private combined day schema mismatch")
    folder.parent.mkdir(parents=True,exist_ok=True)
    folder.mkdir(exist_ok=False)
    parquet=folder/"day.parquet"
    pq.write_table(table,parquet,compression="zstd")
    sha=BASE.hash_file(parquet)
    saved=pq.read_table(parquet,schema=schema)
    if (saved.schema!=schema or saved.to_pylist()!=rows or BASE.hash_file(parquet)!=sha):
        raise ValueError("Physical combined private snapshot roundtrip failed")
    purchased=source_counts["purchased_parquet"]
    whole=source_counts["private_h5_whole_date_candidate"]
    mixed=source_counts["private_h5_mixed_stockday_candidate"]
    manifest={
        "format":FORMAT,
        "state":"private_materialized_verified_not_activated",
        "period":"day",
        "date_window":[first,last],
        "symbol_count":len(symbols),
        "rows":len(rows),
        "purchased_rows":purchased,
        "h5_gap_candidate_rows":whole+mixed,
        "per_symbol_counts":per_symbol,
        "origin_private_version_sha256":version_sha,
        "private_parquet_sha256":sha,
        "private_file":"day.parquet",
        "all_written_values_roundtrip_exactly":True,
        "private_h5_gap_units_remain_unverified_candidate":True,
        "licensed_parquet_to_native_h5_amount_lossless_certified":False,
        "source_market_files_written":False,
        "production_query_route_switched":False,
        "production_h5_mirror_created":False,
        "private_active_overlay_pointer_changed":False,
        # Backward-compatible additional lineage fields. Per-record H5
        # subcategory is not recoverable from v1 physical schema; the
        # authoritative live-gate query SAFE retains original breakdown.
        "combined_22274_source_version":True,
        "whole_date_h5_candidate_rows":whole,
        "mixed_date_h5_candidate_rows":mixed,
        "original_whole_mixed_lineage_in_batch_safe_only":True,
        "live_recheck_source_safe_sha256":
            result["safe_summary"]["full_live_recheck_safe_sha256"],
        "batch_query_safe_sha256":BASE.hash_file(batch),
    }
    manifest_path=folder/"manifest.json"
    with manifest_path.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(manifest,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")
    manifest_sha=BASE.hash_file(manifest_path)
    if BASE.hash_file(parquet)!=sha or BASE.hash_file(manifest_path)!=manifest_sha:
        raise ValueError("Private combined day SHA drift after manifest")
    # The full live gate checked original sources before returning bars.
    # Recheck the same registered source stat digest AFTER writing the
    # private snapshot; a concurrent original-market edit cannot silently
    # be considered a valid materialization. This is a stat drift alarm,
    # not a cryptographic hash of all original market source bytes.
    entry=BATCH.REG.load_version(version_sha)
    if (entry.get("original_source_stat_sha256")!=
            BATCH.PRE.KEYS.state_digest(Path(root).resolve(),(2016,2026))
            or BATCH.REG.LOCK.is_symlink() or BATCH.REG.LOCK.exists()
            or BASE.hash_file(batch)!=manifest["batch_query_safe_sha256"]
            or BASE.hash_file(parquet)!=sha or
            BASE.hash_file(manifest_path)!=manifest_sha):
        raise ValueError("Original daily source or snapshot evidence drift after writing")
    safe={
        "format":FORMAT,
        "state":manifest["state"],
        "snapshot_relative_path":str(folder.relative_to(BASE.MODULE)).replace("\\","/"),
        "manifest_sha256":manifest_sha,
        "private_parquet_sha256":sha,
        "period":"day",
        "symbol_count":len(symbols),
        "row_count":len(rows),
        "purchased_rows":purchased,
        "h5_gap_candidate_rows":whole+mixed,
        "origin_private_version_sha256":version_sha,
        "all_written_values_roundtrip_exactly":True,
        "h5_gap_units_unverified_candidate":True,
        "purchased_parquet_priority_verified":True,
        "original_market_files_modified":False,
        "production_query_route_switched":False,
        "original_hikyuu_h5_modified":False,
        "ready_for_full_market_mirror":False,
        "raw_ohlcva_or_original_source_paths_exported_in_safe":False,
        "combined_22274_source_version":True,
        "whole_date_h5_candidate_rows":whole,
        "mixed_date_h5_candidate_rows":mixed,
        "original_whole_mixed_lineage_in_batch_safe_only":True,
        "full_live_recheck_safe_sha256":
            result["safe_summary"]["full_live_recheck_safe_sha256"],
        "batch_query_safe_sha256":manifest["batch_query_safe_sha256"],
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "private_active_pointer_modified":False,
    }
    with out.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(safe,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--symbols",nargs="+",required=True)
    p.add_argument("--from-date",required=True)
    p.add_argument("--to-date",required=True)
    p.add_argument("--version-sha256",required=True)
    p.add_argument("--live-safe",type=Path,required=True)
    p.add_argument("--private-keys",type=Path,required=True)
    p.add_argument("--history-ledger",type=Path,required=True)
    p.add_argument("--source-2016",type=Path,required=True)
    p.add_argument("--source-2026",type=Path,required=True)
    p.add_argument("--mixed-plan",type=Path,required=True)
    p.add_argument("--fresh-recheck-out",type=Path,required=True)
    p.add_argument("--batch-query-out",type=Path,required=True)
    p.add_argument("--snapshot-dir",type=Path,required=True)
    p.add_argument("--safe-report",type=Path,required=True)
    p.add_argument("--fast-bounded-h5-scan",action="store_true")
    p.add_argument("--read-only-market-sources",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        safe=materialize(
            a.source_root,a.symbols,a.from_date,a.to_date,a.version_sha256,
            a.live_safe,a.private_keys,a.history_ledger,a.source_2016,
            a.source_2026,a.mixed_plan,a.fresh_recheck_out,a.batch_query_out,
            a.snapshot_dir,a.safe_report,a.fast_bounded_h5_scan)
        print("Materialized bounded private snapshot bars:",safe["row_count"])
        print("Purchased:",safe["purchased_rows"],
              "whole-day:",safe["whole_date_h5_candidate_rows"],
              "mixed-day:",safe["mixed_date_h5_candidate_rows"])
        print("Private SAFE:",a.safe_report)
        print("Original market sources unchanged; not production or H5 mirror")
    except (ValueError,OSError,TypeError,KeyError,ImportError,OverflowError):
        p.error("Private 22,274 combined snapshot materialization failed closed")


if __name__=="__main__":
    main()
