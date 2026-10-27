#!/usr/bin/env python3
"""Explicit opt-in PRIVATE cache for repeated local Parquet stock-period queries.

Cache stores licensed OHLCVA values locally. NEVER include its contents in
safe reports or version control. Missing/changed source-file stat manifests
invalidate a cache; stat fingerprints ARE NOT cryptographic file hashes.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

MODULE=Path(__file__).resolve().parents[1]
CACHE=MODULE/"work"/"primary_query_cache"
VERSION="parquet-primary-private-query-cache-v1"


def source_signature(root, period, first, last, core):
    """Metadata-only, fail-closed source inventory for all matching year files."""
    root=Path(root).resolve()
    purchased=(root/"AllCycleAStockData").resolve()
    result=[]
    for year in range(first.year,last.year+1):
        for source in core.year_files(root,period,year):
            if (source.is_symlink() or not source.is_file()
                    or not source.resolve().is_relative_to(purchased)):
                raise ValueError("Unsafe source path in cache manifest")
            stat=source.stat()
            result.append((source.relative_to(root).as_posix(),
                           int(stat.st_size),int(stat.st_mtime_ns)))
    result.sort()
    encoded=json.dumps(result,ensure_ascii=False,separators=(",",":"))
    return {
        "manifest_sha256_stat_only":hashlib.sha256(
            encoded.encode("utf-8")).hexdigest(),
        "manifest_file_count":len(result),
    }


def cache_target(root,symbol,period,first,last,max_candidate_rows,
                 max_result_bars):
    """Stable key from query, safety limits, and data root. No path traversal."""
    fields=(VERSION,str(Path(root).resolve()),symbol,period,
            first.isoformat(),last.isoformat(),
            int(max_candidate_rows),int(max_result_bars))
    name=hashlib.sha256(json.dumps(
        fields,ensure_ascii=False,separators=(",",":")
    ).encode("utf-8")).hexdigest()+".json"
    return CACHE/name


def ensure_private_dir():
    """Refuse symlink escapes and keep licensed bars under ignored work/."""
    work=MODULE/"work"
    if work.is_symlink() or CACHE.is_symlink():
        raise ValueError("Local cache workspace must not be symlinked")
    work.mkdir(exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    if CACHE.resolve().parent!=work.resolve():
        raise ValueError("Private cache directory escaped module work/")


def read_cache(target,signature,symbol,period,first,last,max_result_bars):
    if not target.exists():
        return None
    if target.is_symlink() or not target.is_file() or target.parent!=CACHE:
        raise ValueError("Unsafe local query cache path")
    try:
        with target.open("r",encoding="utf-8") as f:
            item=json.load(f)
    except (ValueError,OSError,TypeError,json.JSONDecodeError):
        return None
    if (not isinstance(item,dict) or item.get("format")!=VERSION
            or item.get("source_stat_signature")!=signature
            or not isinstance(item.get("bars"),list)
            or not isinstance(item.get("safe_summary"),dict)):
        return None
    bars=item["bars"]
    if len(bars)>max_result_bars:
        return None
    for bar in bars:
        if not isinstance(bar,dict):
            return None
        if bar.get("symbol")!=symbol or bar.get("period")!=period:
            return None
        try:
            dt=date.fromisoformat(bar["trading_date"])
        except (ValueError,TypeError,KeyError):
            return None
        if not first<=dt<=last:
            return None
        if any(type(bar.get(field)) not in (int,float) for field in (
                "source_timestamp_ms","open","high","low","close",
                "volume","amount")):
            return None
    summary=item["safe_summary"]
    if (summary.get("matching_bar_count")!=len(bars)
            or summary.get("symbol")!=symbol
            or summary.get("period")!=period
            or summary.get("from_date")!=first.isoformat()
            or summary.get("to_date")!=last.isoformat()
            or summary.get("no_raw_ohlcva_in_safe_summary") is not True):
        return None
    result=dict(summary)
    # These counters reflect THIS invocation, not the original cold scan.
    result["previous_source_rows_scanned_to_build_cache"]=summary.get(
        "source_rows_scanned")
    result["source_rows_scanned"]=0
    result["source_rows_scanned_this_invocation"]=0
    result["source_file_footers_opened_this_invocation"]=0
    result["query_delivery"]="local_private_cache_hit"
    result["private_cache_contains_licensed_ohlcva"]=True
    result["local_cache_validated_by_source_stat_only_not_content_hash"]=True
    result["local_cache_source_file_count"]=signature["manifest_file_count"]
    result["local_cache_used"]=True
    return {"bars":bars,"safe_summary":result}


def write_cache(target,signature,result):
    """Atomic local-only write; do not place raw OHLCVA in reports/."""
    ensure_private_dir()
    if target.is_symlink():
        raise ValueError("Refusing symlink cache file target")
    body={
        "format":VERSION,
        "source_stat_signature":signature,
        "bars":result["bars"],
        "safe_summary":result["safe_summary"],
    }
    data=json.dumps(body,ensure_ascii=False,separators=(",",":"))
    if len(data.encode("utf-8"))>16*1024*1024:
        raise ValueError("Single private cached query exceeds 16 MiB")
    fd,path=tempfile.mkstemp(prefix=".tmp-query-",dir=str(CACHE))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            f.write(data)
            f.write("\n")
        os.replace(path,target)
    finally:
        if os.path.exists(path):
            os.unlink(path)
