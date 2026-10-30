#!/usr/bin/env python3
"""Read an immutable PRIVATE Parquet base + one new-stock Parquet delta.

Read-only coherent logical day view, NOT another physically merged Parquet,
version promotion, production routing change, or live market-freshness proof.
No market data or stock symbols are written to the aggregate SAFE report.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path, PurePosixPath
from datetime import date

HERE=Path(__file__).resolve().parent


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ADD=load("private_day_join_delta_producer",
         "append-private-unified-day-symbol-delta.py")
VERSION=ADD.VERSION
READER=ADD.READER
MODULE=HERE.parent.resolve()
FORMAT="AStockDataTools private snapshot and new-symbol delta joined read v1"
MAX_SAFE_SIZE=200000
MAX_DELTA_BYTES=30*1024*1024


def get_delta_safe(path,requested_parent):
    READER.require_sha(requested_parent)
    source=READER.direct_report(path)
    raw=source.read_bytes()
    if not 0<len(raw)<=MAX_SAFE_SIZE:
        raise ValueError("Delta SAFE exceeds bounded size")
    try:
        safe=json.loads(raw)
    except (ValueError,UnicodeError):
        raise ValueError("Invalid delta SAFE") from None
    if (type(safe) is not dict
            or safe.get("format")!=ADD.FORMAT
            or safe.get("status")!="private_additive_symbol_delta_not_activated"
            or safe.get("period")!="day"
            or safe.get("parent_private_snapshot_version_sha256")!=requested_parent
            or safe.get("existing_snapshot_rows_rewritten") is not False
            or safe.get("private_active_pointer_changed") is not False
            or safe.get("original_market_sources_modified") is not False
            or safe.get("production_query_route_modified") is not False
            or safe.get("all_new_private_values_roundtrip_exactly") is not True
            or safe.get("new_h5_gap_units_unverified_candidate") is not True
            or safe.get("ready_for_full_market_mirror") is not False
            or safe.get("raw_ohlcva_or_absolute_market_paths_exported") is not False):
        raise ValueError("Delta SAFE not a verified private additive source")
    for k in ("delta_parquet_sha256","delta_manifest_sha256",
              "source_overlay_version_sha256"):
        READER.require_sha(safe.get(k))
    if (type(safe.get("new_symbol_count")) is not int
            or not 1<=safe["new_symbol_count"]<=5
            or type(safe.get("added_rows")) is not int
            or not 1<=safe["added_rows"]<=2500
            or any(type(safe.get(k)) is not int or safe[k]<0
                   for k in ("purchased_rows","h5_gap_candidate_rows"))
            or safe["purchased_rows"]+safe["h5_gap_candidate_rows"]!=safe["added_rows"]):
        raise ValueError("Untrusted delta SAFE count")
    rel=safe.get("private_delta_relative_path")
    if type(rel) is not str:
        raise ValueError("Missing private relative delta location")
    parts=PurePosixPath(rel).parts
    if (len(parts)!=4 or parts[:3]!=(
            "work","unified_parquet","snapshot_deltas")
            or not re.fullmatch("delta_[a-f0-9]{12,32}",parts[3])
            or "\\" in rel or ".." in parts):
        raise ValueError("Delta escaped private module directory")
    root=MODULE.joinpath(*parts)
    if (any(p.is_symlink() for p in (
            MODULE/"work",MODULE/"work"/"unified_parquet",
            MODULE/"work"/"unified_parquet"/"snapshot_deltas",root))
            or root.resolve().parent!=(
                MODULE/"work"/"unified_parquet"/"snapshot_deltas").resolve()
            or not root.is_dir()):
        raise ValueError("Private delta directory is missing or unsafe")
    manifest,pq=root/"manifest.json",root/"day.parquet"
    if (manifest.is_symlink() or pq.is_symlink() or
            not manifest.is_file() or not pq.is_file()
            or not 0<manifest.stat().st_size<=MAX_SAFE_SIZE
            or not 0<pq.stat().st_size<=MAX_DELTA_BYTES):
        raise ValueError("Private delta file missing, linked, or too large")
    if (READER.sha256_file(manifest)!=safe["delta_manifest_sha256"]
            or READER.sha256_file(pq)!=safe["delta_parquet_sha256"]):
        raise ValueError("Private delta SAFE SHA mismatch")
    return safe,hashlib.sha256(raw).hexdigest(),manifest,pq


def check_manifest(delta,meta,parent_version,parent_file_sha,
                   parent_safe,parent_safe_sha,parent_manifest):
    if (type(meta) is not dict or meta.get("format")!=ADD.FORMAT
            or meta.get("status")!="private_additive_symbol_delta_not_activated"
            or meta.get("period")!="day"
            or meta.get("delta_private_file")!="day.parquet"
            or meta.get("parent_private_snapshot_version_sha256")!=
                parent_version["version_sha256"]
            or meta.get("parent_version_file_sha256")!=parent_file_sha
            or meta.get("parent_snapshot_safe_sha256")!=parent_safe_sha
            or meta.get("parent_parquet_sha256")!=parent_safe["private_parquet_sha256"]
            or meta.get("parent_manifest_sha256")!=parent_safe["manifest_sha256"]
            or meta.get("source_overlay_version_sha256")!=
                parent_version["origin_private_version_sha256"]
            or delta["source_overlay_version_sha256"]!=
                parent_version["origin_private_version_sha256"]
            or meta.get("date_window")!=parent_manifest["date_window"]
            or meta.get("new_symbol_count")!=delta["new_symbol_count"]
            or meta.get("added_rows")!=delta["added_rows"]
            or meta.get("purchased_rows")!=delta["purchased_rows"]
            or meta.get("h5_gap_candidate_rows")!=delta["h5_gap_candidate_rows"]
            or meta.get("delta_parquet_sha256")!=delta["delta_parquet_sha256"]
            or meta.get("all_new_private_values_roundtrip_exactly") is not True
            or meta.get("existing_snapshot_rows_rewritten") is not False
            or meta.get("original_market_sources_modified") is not False
            or meta.get("private_active_pointer_changed") is not False
            or meta.get("production_query_route_modified") is not False
            or meta.get("h5_gap_units_unverified_candidate") is not True
            or meta.get("ready_for_full_market_mirror") is not False):
        raise ValueError("Delta manifest provenance disagrees with immutable parent")
    symbols=meta.get("new_symbols")
    counts=meta.get("per_symbol_counts")
    if (type(symbols) is not list or len(symbols)!=delta["new_symbol_count"]
            or len(set(symbols))!=len(symbols)
            or type(counts) is not dict or set(counts)!=set(symbols)
            or len(set(symbols)|set(parent_manifest["per_symbol_counts"]))>10
            or set(symbols)&set(parent_manifest["per_symbol_counts"])):
        raise ValueError("New stock universe overlaps parent or exceeds budget")
    for sym in symbols:
        c=counts[sym]
        if (type(sym) is not str or not re.fullmatch("(SH|SZ|BJ)[0-9]{6}",sym)
                or type(c) is not dict
                or set(c)!={"purchased_bars","private_bars","returned_bars"}
                or any(type(v) is not int or v<0 for v in c.values())
                or c["purchased_bars"]+c["private_bars"]!=c["returned_bars"]):
            raise ValueError("Invalid per-symbol delta provenance count")
    if (sum(c["purchased_bars"] for c in counts.values())!=delta["purchased_rows"]
            or sum(c["private_bars"] for c in counts.values())!=delta["h5_gap_candidate_rows"]
            or sum(c["returned_bars"] for c in counts.values())!=delta["added_rows"]):
        raise ValueError("Private delta per-symbol totals mismatch")
    return {"rows":delta["added_rows"],
            "date_window":parent_manifest["date_window"],
            "per_symbol_counts":counts}


def decode(path,expected_rows):
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema=READER.expected_schema(pa)
    pf=None
    try:
        pf=pq.ParquetFile(path,memory_map=False,pre_buffer=False)
        if (pf.schema_arrow!=schema or
                not 1<=pf.metadata.num_row_groups<=32 or
                pf.metadata.num_rows!=expected_rows):
            raise ValueError("Arrow schema/footer mismatch")
        table=pf.read(columns=schema.names,use_threads=False)
        if table.schema!=schema or table.num_rows!=expected_rows:
            raise ValueError("Arrow decoded row count mismatch")
        return table.to_pylist()
    except Exception:
        raise ValueError("Private joined Parquet decode or schema refused") from None
    finally:
        if pf is not None:
            pf.close()


def read_joined(parent_sha,delta_safe,symbols,first,last,out,emit_safe=True):
    """Verify complete base and complete delta before returning any selected bars."""
    if (type(symbols) not in (list,tuple)
            or not 1<=len(symbols)<=10
            or any(type(s) is not str or
                   not re.fullmatch("(SH|SZ|BJ)[0-9]{6}",s) for s in symbols)
            or len(set(symbols))!=len(symbols)):
        raise ValueError("Select distinct canonical A-share symbols")
    try:
        if (type(first) is not str or type(last) is not str or
                date.fromisoformat(first).isoformat()!=first or
                date.fromisoformat(last).isoformat()!=last or first>last):
            raise ValueError("Bad date window")
    except (TypeError,ValueError):
        raise ValueError("Bad date window") from None
    if type(emit_safe) is not bool:
        raise ValueError("Invalid private SAFE publication mode")
    target=READER.direct_report(out,for_output=True) if emit_safe else None
    parent,parent_file_sha,parent_safe,parent_safe_sha,meta=ADD.trusted_parent(
        parent_sha)
    delta,delta_proof,delta_manifest,delta_pq=get_delta_safe(delta_safe,parent_sha)
    try:
        delta_meta=json.loads(delta_manifest.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError):
        raise ValueError("Malformed delta manifest") from None
    effective=check_manifest(delta,delta_meta,parent,parent_file_sha,
                             parent_safe,parent_safe_sha,meta)
    if (first<meta["date_window"][0] or last>meta["date_window"][1] or
            any(s not in set(meta["per_symbol_counts"])|
                set(delta_meta["new_symbols"]) for s in symbols)):
        raise ValueError("Requested stock/date outside parent+delta coverage")
    parent_safe_file=READER.REPORTS/parent["snapshot_safe_basename"]
    _,_,_,parent_parquet=READER.source_snapshot(parent_safe_file)
    parent_rows=decode(parent_parquet,parent_safe["row_count"])
    delta_rows=decode(delta_pq,delta["added_rows"])
    READER.inspect_rows(parent_rows,meta)
    READER.inspect_rows(delta_rows,effective)
    old_keys={(r["symbol"],r["trading_date"]) for r in parent_rows}
    new_keys={(r["symbol"],r["trading_date"]) for r in delta_rows}
    if old_keys&new_keys:
        raise ValueError("Purchased/private duplicate stock-day across partitions")
    # Rehash both private files plus their immutable proofs AFTER full decode;
    # the loader deliberately does NOT contact market sources.
    v2,vsha2,p2,psha2,m2=ADD.trusted_parent(parent_sha)
    if (v2!=parent or vsha2!=parent_file_sha or
            p2!=parent_safe or psha2!=parent_safe_sha or m2!=meta):
        raise ValueError("Parent private snapshot changed during joined read")
    d2,sha2,m3,p3=get_delta_safe(delta_safe,parent_sha)
    if (d2!=delta or sha2!=delta_proof or
            m3!=delta_manifest or p3!=delta_pq or
            READER.sha256_file(delta_manifest)!=delta["delta_manifest_sha256"]):
        raise ValueError("Delta private snapshot changed during joined read")
    result={s:[] for s in symbols}
    for row in parent_rows+delta_rows:
        if row["symbol"] in result and first<=row["trading_date"]<=last:
            result[row["symbol"]].append(row)
    for rows in result.values():
        rows.sort(key=lambda r:(r["trading_date"],r["ts"]))
    counts={
        "joined_full_rows":len(parent_rows)+len(delta_rows),
        "parent_rows":len(parent_rows),
        "delta_rows":len(delta_rows),
        "joined_stocks":len(meta["per_symbol_counts"])+len(delta_meta["new_symbols"]),
        "selected_stocks":len(symbols),
        "selected_rows":sum(len(v) for v in result.values()),
        "selected_purchased_rows":sum(
            r["value_source"]=="purchased_parquet"
            for v in result.values() for r in v),
        "selected_h5_gap_candidate_rows":sum(
            r["value_source"]=="private_hikyuu_h5_gap_candidate"
            for v in result.values() for r in v),
    }
    summary={
        "format":FORMAT,
        "period":"day",
        "parent_version_sha256":parent_sha,
        "parent_snapshot_sha256":parent_safe["private_parquet_sha256"],
        "delta_safe_sha256":delta_proof,
        "delta_parquet_sha256":delta["delta_parquet_sha256"],
        "delta_manifest_sha256":delta["delta_manifest_sha256"],
        "origin_overlay_version_sha256":parent["origin_private_version_sha256"],
        "requested_first":first,"requested_last":last,
        **counts,
        "parent_delta_full_schema_keys_counts_and_hashes_verified":True,
        "private_parent_parquet_rewritten":False,
        "private_delta_parquet_rewritten":False,
        "no_live_market_source_freshness_recheck":True,
        "original_market_h5_or_purchased_parquet_opened":False,
        "private_snapshot_pointer_read_or_modified":False,
        "production_query_route_modified":False,
        "h5_gap_units_remain_unverified_candidate":True,
        "ready_for_full_market_mirror":False,
        "no_raw_ohlcva_or_symbols_in_safe":True,
    }
    if emit_safe:
        with target.open("x",encoding="utf-8") as stream:
            json.dump(summary,stream,sort_keys=True,ensure_ascii=False,indent=2)
            stream.write("\n")
    return {"bars_by_symbol":result,"safe_summary":summary}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-version",required=True)
    parser.add_argument("--delta-safe",type=Path,required=True)
    parser.add_argument("--symbols",nargs="+",required=True)
    parser.add_argument("--from-date",required=True)
    parser.add_argument("--to-date",required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--explicit-private-joined-read",action="store_true",required=True)
    a=parser.parse_args(argv)
    try:
        result=read_joined(a.parent_version,a.delta_safe,a.symbols,
                           a.from_date,a.to_date,a.out)
        counts=result["safe_summary"]
        print("SAFE private joined Parquet read:",a.out)
        print("Stocks:",counts["joined_stocks"],"Joined rows:",counts["joined_full_rows"])
        print("Selected rows:",counts["selected_rows"],
              "purchased:",counts["selected_purchased_rows"],
              "H5 candidates:",counts["selected_h5_gap_candidate_rows"])
        print("Original market sources opened or modified: NO")
        print("Live market source freshness rechecked: NO")
    except (ValueError,KeyError,TypeError,OSError,OverflowError,
            ImportError,ModuleNotFoundError):
        parser.error("Private parent+delta joined read rejected; no market writes")


if __name__=="__main__":
    main()
