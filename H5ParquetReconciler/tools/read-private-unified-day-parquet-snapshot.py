#!/usr/bin/env python3
"""Verify and read a small, immutable PRIVATE Parquet-first daily snapshot.

Only an explicit, previously created module-private SAFE summary may name the
snapshot. No purchased market sources, raw Hikyuu H5, production database, or
private active pointer are opened. This verifies SNAPSHOT integrity, NOT live
source freshness or licensed vendor amount-unit correctness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

MODULE=Path(__file__).resolve().parent.parent
WORK=MODULE/"work"
ROOT=WORK/"unified_parquet"/"snapshots"
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools immutable private Parquet-primary daily materialization v1"
READ_FORMAT="AStockDataTools verified private Parquet-primary day snapshot read v1"
PRIVATE_STATE="private_materialized_verified_not_activated"
FIELDS=("open","high","low","close","volume","amount")
SOURCES=("purchased_parquet","private_hikyuu_h5_gap_candidate")
MAX_ROWS=5000
MAX_FILE_BYTES=30*1024*1024
MAX_REPORT_BYTES=200000
UTC8=timezone(timedelta(hours=8))


def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(1<<20),b""):
            h.update(chunk)
    return h.hexdigest()


def require_sha(text):
    if type(text) is not str or not re.fullmatch("[0-9a-f]{64}",text):
        raise ValueError("Invalid snapshot SHA256")
    return text


def direct_report(path,for_output=False):
    p=Path(path)
    if (REPORTS.is_symlink() or p.is_symlink()
            or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()
            or (for_output and p.exists())
            or (not for_output and not p.is_file())):
        raise ValueError("SAFE must be a direct module reports JSON (new output if writing)")
    if not for_output and not 0<p.stat().st_size<=MAX_REPORT_BYTES:
        raise ValueError("SAFE size exceeds input budget")
    return p.resolve()


def source_snapshot(source_safe):
    proof=direct_report(source_safe)
    raw=proof.read_bytes()
    if not 0<len(raw)<=MAX_REPORT_BYTES:
        raise ValueError("Oversized SAFE input")
    try:
        safe=json.loads(raw)
    except (ValueError,UnicodeError):
        raise ValueError("Invalid private snapshot SAFE JSON") from None
    if (type(safe) is not dict or safe.get("format")!=FORMAT
            or safe.get("state")!=PRIVATE_STATE or safe.get("period")!="day"
            or safe.get("all_written_values_roundtrip_exactly") is not True
            or safe.get("purchased_parquet_priority_verified") is not True
            or safe.get("original_market_files_modified") is not False
            or safe.get("original_hikyuu_h5_modified") is not False
            or safe.get("production_query_route_switched") is not False
            or safe.get("h5_gap_units_unverified_candidate") is not True
            or safe.get("ready_for_full_market_mirror") is not False
            or safe.get("raw_ohlcva_or_original_source_paths_exported_in_safe") is not False):
        raise ValueError("Unqualified private materialization SAFE")
    for key in ("manifest_sha256","private_parquet_sha256",
                "origin_private_version_sha256"):
        require_sha(safe.get(key))
    if (type(safe.get("row_count")) is not int
            or not 1<=safe["row_count"]<=MAX_ROWS
            or type(safe.get("symbol_count")) is not int
            or not 1<=safe["symbol_count"]<=10
            or any(type(safe.get(k)) is not int or safe[k]<0
                   for k in ("purchased_rows","h5_gap_candidate_rows"))
            or safe["purchased_rows"]+safe["h5_gap_candidate_rows"]!=safe["row_count"]):
        raise ValueError("Unsafe private snapshot SAFE count")
    rel=safe.get("snapshot_relative_path")
    if type(rel) is not str:
        raise ValueError("Invalid private snapshot relative path")
    parts=PurePosixPath(rel).parts
    if (len(parts)!=4 or parts[:3]!=("work","unified_parquet","snapshots")
            or not re.fullmatch("snapshot_[0-9a-f]{12,32}",parts[3])
            or "\\" in rel or ".." in parts):
        raise ValueError("Untrusted snapshot path in SAFE")
    if any(p.is_symlink() for p in (
            WORK,WORK/"unified_parquet",ROOT)):
        raise ValueError("Private source parent symlink forbidden")
    directory=MODULE.joinpath(*parts)
    if (directory.is_symlink() or not directory.is_dir()
            or directory.resolve().parent!=ROOT.resolve()):
        raise ValueError("Expected direct private snapshot directory is missing")
    manifest=directory/"manifest.json"
    parquet=directory/"day.parquet"
    if any(p.is_symlink() or not p.is_file() for p in (manifest,parquet)):
        raise ValueError("Untrusted private snapshot files")
    if not 0<manifest.stat().st_size<=MAX_REPORT_BYTES:
        raise ValueError("Private manifest size invalid")
    if not 0<parquet.stat().st_size<=MAX_FILE_BYTES:
        raise ValueError("Private Parquet size exceeds budget")
    if (sha256_file(manifest)!=safe["manifest_sha256"]
            or sha256_file(parquet)!=safe["private_parquet_sha256"]):
        raise ValueError("Private snapshot SHA mismatch")
    return safe,hashlib.sha256(raw).hexdigest(),manifest,parquet


def expected_schema(pa):
    return pa.schema([
        pa.field("ts",pa.int64()),
        pa.field("trading_date",pa.string()),
        pa.field("symbol",pa.string()),
        *(pa.field(f,pa.float64()) for f in FIELDS),
        pa.field("value_source",pa.string()),
    ])


def verified_manifest(path,safe):
    try:
        manifest=json.loads(path.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError):
        raise ValueError("Invalid snapshot manifest JSON") from None
    if (type(manifest) is not dict
            or manifest.get("format")!=FORMAT
            or manifest.get("state")!=PRIVATE_STATE
            or manifest.get("period")!="day"
            or manifest.get("private_file")!="day.parquet"
            or manifest.get("origin_private_version_sha256")!=safe["origin_private_version_sha256"]
            or manifest.get("private_parquet_sha256")!=safe["private_parquet_sha256"]
            or manifest.get("rows")!=safe["row_count"]
            or manifest.get("symbol_count")!=safe["symbol_count"]
            or manifest.get("purchased_rows")!=safe["purchased_rows"]
            or manifest.get("h5_gap_candidate_rows")!=safe["h5_gap_candidate_rows"]
            or manifest.get("all_written_values_roundtrip_exactly") is not True
            or manifest.get("private_h5_gap_units_remain_unverified_candidate") is not True
            or manifest.get("licensed_parquet_to_native_h5_amount_lossless_certified") is not False
            or manifest.get("source_market_files_written") is not False
            or manifest.get("production_query_route_switched") is not False
            or manifest.get("production_h5_mirror_created") is not False
            or manifest.get("private_active_overlay_pointer_changed") is not False):
        raise ValueError("Private manifest and SAFE provenance disagree")
    window=manifest.get("date_window")
    if (type(window) is not list or len(window)!=2
            or any(type(x) is not str for x in window)):
        raise ValueError("Bad manifest date window")
    first,last=window
    try:
        if not (date.fromisoformat(first).isoformat()==first
                and date.fromisoformat(last).isoformat()==last
                and first<=last and date.fromisoformat(first).year==
                date.fromisoformat(last).year
                and (date.fromisoformat(last)-date.fromisoformat(first)).days<=30):
            raise ValueError("Bad snapshot interval")
    except (TypeError,ValueError):
        raise ValueError("Bad snapshot interval") from None
    per=manifest.get("per_symbol_counts")
    if (type(per) is not dict or not 1<=len(per)<=10
            or len(per)!=safe["symbol_count"]):
        raise ValueError("Malformed private per-symbol manifest counts")
    for sym,counts in per.items():
        if (type(sym) is not str or not re.fullmatch("(SH|SZ|BJ)[0-9]{6}",sym)
                or type(counts) is not dict
                or set(counts)!={"purchased_bars","private_bars","returned_bars"}
                or any(type(x) is not int or x<0 for x in counts.values())
                or counts["purchased_bars"]+counts["private_bars"]!=counts["returned_bars"]):
            raise ValueError("Malformed manifest symbol/source counts")
    if (sum(v["returned_bars"] for v in per.values())!=safe["row_count"]
            or sum(v["purchased_bars"] for v in per.values())!=safe["purchased_rows"]
            or sum(v["private_bars"] for v in per.values())!=safe["h5_gap_candidate_rows"]):
        raise ValueError("Manifest aggregate counts inconsistent")
    return manifest


def inspect_rows(rows,manifest):
    if type(rows) is not list or len(rows)!=manifest["rows"]:
        raise ValueError("Parquet row count mismatch")
    first,last=manifest["date_window"]
    per=manifest["per_symbol_counts"]
    observed={sym:Counter() for sym in per}
    seen=set()
    previous=None
    for row in rows:
        if type(row) is not dict or set(row)!={
                "ts","trading_date","symbol","value_source",*FIELDS}:
            raise ValueError("Private Parquet field mismatch")
        sym=row["symbol"]
        source=row["value_source"]
        date_text=row["trading_date"]
        ts=row["ts"]
        if (type(sym) is not str or sym not in per
                or source not in SOURCES or type(date_text) is not str
                or not first<=date_text<=last or type(ts) is not int):
            raise ValueError("Untrusted private snapshot stock/date/source")
        try:
            if date.fromisoformat(date_text).isoformat()!=date_text:
                raise ValueError("Noncanonical trading date")
            local_day=datetime.fromtimestamp(ts/1000,tz=UTC8).date().isoformat()
        except (ValueError,OverflowError,TypeError):
            raise ValueError("Invalid private snapshot timestamp") from None
        if local_day!=date_text:
            raise ValueError("Snapshot timestamp not on claimed trading date")
        key=(sym,date_text)
        if key in seen:
            raise ValueError("Duplicate purchased/private stock-day")
        seen.add(key)
        order=(date_text,sym,ts)
        if previous is not None and order<previous:
            raise ValueError("Private snapshot row order changed")
        previous=order
        for field in FIELDS:
            v=row[field]
            if type(v) is not float or not math.isfinite(v) or v<0:
                raise ValueError("Bad private Parquet OHLCVA value")
        op,hi,lo,close=(row[f] for f in ("open","high","low","close"))
        if (min(op,hi,lo,close)<=0 or hi+1e-8<max(op,lo,close)
                or lo-1e-8>min(op,hi,close)):
            raise ValueError("Invalid private snapshot OHLC geometry")
        observed[sym][source]+=1
    for sym,expected in per.items():
        if (observed[sym]["purchased_parquet"]!=expected["purchased_bars"]
                or observed[sym]["private_hikyuu_h5_gap_candidate"]!=expected["private_bars"]):
            raise ValueError("Private Parquet source provenance count mismatch")
    return observed


def read_verified(snapshot_safe,requested_symbols,first,last,out):
    """Read ONLY private Parquet, return selected bars in memory plus safe counts."""
    if (type(requested_symbols) not in (list,tuple)
            or not 1<=len(requested_symbols)<=10
            or len(set(requested_symbols))!=len(requested_symbols)
            or any(type(s) is not str or not re.fullmatch("(SH|SZ|BJ)[0-9]{6}",s)
                   for s in requested_symbols)):
        raise ValueError("Explicit 1..10 distinct canonical symbols required")
    if type(first) is not str or type(last) is not str:
        raise ValueError("Explicit ISO date window required")
    try:
        if (date.fromisoformat(first).isoformat()!=first
                or date.fromisoformat(last).isoformat()!=last
                or first>last):
            raise ValueError("Invalid requested date window")
    except ValueError:
        raise ValueError("Invalid requested date window") from None
    output=direct_report(out,for_output=True)
    safe,proof_sha,manifest_file,parquet=source_snapshot(snapshot_safe)
    manifest=verified_manifest(manifest_file,safe)
    if (first<manifest["date_window"][0] or last>manifest["date_window"][1]
            or any(s not in manifest["per_symbol_counts"] for s in requested_symbols)):
        raise ValueError("Request extends beyond verified private snapshot")
    import pyarrow as pa
    import pyarrow.parquet as pq
    expected=expected_schema(pa)
    pf=None
    try:
        pf=pq.ParquetFile(parquet,memory_map=False,pre_buffer=False)
        if (pf.schema_arrow!=expected or pf.metadata.num_row_groups<1
                or pf.metadata.num_row_groups>32
                or pf.metadata.num_rows!=manifest["rows"]):
            raise ValueError("Private snapshot Arrow schema or footer mismatch")
        table=pf.read(columns=list(expected.names),use_threads=False)
        if table.schema!=expected or table.num_rows!=manifest["rows"]:
            raise ValueError("Private snapshot decoded table mismatch")
        rows=table.to_pylist()
    except Exception:
        raise ValueError("Private snapshot schema or bounded decode failed") from None
    finally:
        if pf is not None:
            pf.close()
    inspect_rows(rows,manifest)
    if (source_snapshot(snapshot_safe)[1:]!=(
            proof_sha,manifest_file,parquet)):
        raise ValueError("Snapshot or SAFE proof bytes changed during read")
    # source_snapshot rehashes file & manifest; validate manifest once more
    # after decode to narrow TOCTOU and detect manifest replacement.
    verified_manifest(manifest_file,safe)
    if (sha256_file(manifest_file)!=safe["manifest_sha256"]
            or sha256_file(parquet)!=safe["private_parquet_sha256"]):
        raise ValueError("Snapshot changed after private decode")
    selected={s:[] for s in requested_symbols}
    for row in rows:
        if row["symbol"] in selected and first<=row["trading_date"]<=last:
            selected[row["symbol"]].append(row)
    per={s:{
        "purchased_bars":sum(r["value_source"]=="purchased_parquet" for r in selected[s]),
        "h5_gap_candidate_bars":sum(
            r["value_source"]=="private_hikyuu_h5_gap_candidate" for r in selected[s]),
        "returned_bars":len(selected[s]),
    } for s in requested_symbols}
    total=sum(x["returned_bars"] for x in per.values())
    summary={
        "format":READ_FORMAT,
        "source_snapshot_sha256":safe["private_parquet_sha256"],
        "source_manifest_sha256":safe["manifest_sha256"],
        "source_safe_sha256":proof_sha,
        "origin_private_version_sha256":safe["origin_private_version_sha256"],
        "snapshot_total_rows_verified":manifest["rows"],
        "selected_stock_count":len(requested_symbols),
        "selected_row_count":total,
        "selected_purchased_row_count":sum(v["purchased_bars"] for v in per.values()),
        "selected_h5_gap_candidate_row_count":sum(
            v["h5_gap_candidate_bars"] for v in per.values()),
        "requested_first":first,
        "requested_last":last,
        "snapshot_full_schema_keys_source_counts_and_sha_verified":True,
        "no_live_market_source_freshness_recheck":True,
        "purchased_parquet_priority_in_original_snapshot":True,
        "original_market_h5_or_parquet_opened":False,
        "private_active_pointer_read_or_modified":False,
        "production_query_route_modified":False,
        "no_raw_ohlcva_in_safe_summary":True,
        "h5_gap_units_remain_unverified_candidate":True,
        "ready_for_full_market_mirror":False,
    }
    # Refresh the three proof hashes just before publishing any aggregate SAFE.
    again,another_sha,m2,p2=source_snapshot(snapshot_safe)
    if (again!=safe or another_sha!=proof_sha or m2!=manifest_file or p2!=parquet):
        raise ValueError("Private source proof changed before output")
    with output.open("x",encoding="utf-8") as stream:
        json.dump(summary,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")
    return {"bars_by_symbol":selected,"safe_summary":summary}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot-safe",type=Path,required=True)
    p.add_argument("--symbols",nargs="+",required=True)
    p.add_argument("--from-date",required=True)
    p.add_argument("--to-date",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--explicit-private-snapshot-read",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        data=read_verified(args.snapshot_safe,args.symbols,
                           args.from_date,args.to_date,args.out)
        safe=data["safe_summary"]
        print("SAFE private snapshot read:",args.out)
        print("Rows:",safe["selected_row_count"],
              "purchased:",safe["selected_purchased_row_count"],
              "H5 gap candidate:",safe["selected_h5_gap_candidate_row_count"])
        print("Original market data read or modified: NO")
        print("Freshness rechecked against live market: NO")
    except (ValueError,TypeError,KeyError,OverflowError,OSError,ImportError,
            ModuleNotFoundError):
        p.error("Private snapshot proof or bounded read rejected; no original market files touched")


if __name__=="__main__":
    main()
