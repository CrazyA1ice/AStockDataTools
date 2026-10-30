#!/usr/bin/env python3
"""Query PRIVATE parent+delta day data by one registered logical version SHA.

Uses only existing, SHA-bound module-private Parquet partitions. The logical
version is supplied EXPLICITLY; no active pointer, live purchased Parquet,
original H5, production source or network service is ever consulted.

This is a bounded research-only read of one historical snapshot, not a
statement that the purchased data or H5 candidate amount units are current.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
FORMAT="AStockDataTools explicit private joined day logical version query v1"


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REG=load("query_private_joined_day_version_registry",
         "register-private-joined-day-logical-version.py")
JOIN=REG.J
READER=REG.READER


def guarded_version(sha):
    """Validate immutable metadata, no active version pointer access."""
    REG.valid_sha(sha)
    if REG.LOCK.is_symlink() or REG.LOCK.exists():
        raise ValueError("Private joined version update in progress")
    entry=REG.load_version(sha)
    file=REG.VERSIONS/(sha+".json")
    if file.is_symlink() or not file.is_file():
        raise ValueError("Unsafe registered logical version file")
    file_sha=READER.sha256_file(file)
    REG.check_version_files(entry)
    if REG.LOCK.is_symlink() or REG.LOCK.exists():
        raise ValueError("Private joined version update occurred during read")
    if READER.sha256_file(file)!=file_sha:
        raise ValueError("Registered version SHA changed during validation")
    return entry,file_sha


def query_version(version_sha,symbols,first,last,out):
    """Return original OHLCVA in caller's LOCAL process; SAFE has counts only.

    The underlying join is fully validated but called with emit_safe=False so
    the only persistent output is one final SHA-bound aggregate SAFE, created
    after the registered version has been rechecked.
    """
    output=READER.direct_report(out,for_output=True)
    entry,proof_sha=guarded_version(version_sha)
    # Always explicit: neither the private joined active pointer nor the
    # independent H5 overlay/old snapshot pointer is loaded by this API.
    result=JOIN.read_joined(
        entry["parent_private_version_sha256"],
        READER.REPORTS/entry["delta_safe_basename"],
        symbols,first,last,None,emit_safe=False)
    s=result["safe_summary"]
    if (s.get("format")!=JOIN.FORMAT
            or s.get("parent_version_sha256")!=entry["parent_private_version_sha256"]
            or s.get("parent_snapshot_sha256")!=entry["parent_parquet_sha256"]
            or s.get("delta_safe_sha256")!=entry["delta_safe_sha256"]
            or s.get("delta_parquet_sha256")!=entry["delta_parquet_sha256"]
            or s.get("delta_manifest_sha256")!=entry["delta_manifest_sha256"]
            or s.get("origin_overlay_version_sha256")!=entry[
                "source_overlay_version_sha256"]
            or s.get("parent_rows")!=entry["parent_rows"]
            or s.get("delta_rows")!=entry["delta_rows"]
            or s.get("joined_full_rows")!=entry["joined_rows"]
            or s.get("joined_stocks")!=entry["joined_stocks"]
            or s.get("parent_delta_full_schema_keys_counts_and_hashes_verified") is not True
            or s.get("private_parent_parquet_rewritten") is not False
            or s.get("private_delta_parquet_rewritten") is not False
            or s.get("original_market_h5_or_purchased_parquet_opened") is not False
            or s.get("private_snapshot_pointer_read_or_modified") is not False
            or s.get("production_query_route_modified") is not False
            or s.get("h5_gap_units_remain_unverified_candidate") is not True
            or s.get("ready_for_full_market_mirror") is not False
            or s.get("no_raw_ohlcva_or_symbols_in_safe") is not True
            or s.get("no_live_market_source_freshness_recheck") is not True
            or type(s.get("selected_rows")) is not int
            or not 0<=s["selected_rows"]<=entry["joined_rows"]
            or type(s.get("selected_purchased_rows")) is not int
            or type(s.get("selected_h5_gap_candidate_rows")) is not int
            or s["selected_purchased_rows"]+
                s["selected_h5_gap_candidate_rows"]!=s["selected_rows"]):
        raise ValueError("Joined query does not match registered immutable version")
    # Check again AFTER rows have been decoded, filtered and kept only in
    # memory. An updated version or market snapshot aborts BEFORE SAFE output.
    again,again_sha=guarded_version(version_sha)
    if again!=entry or again_sha!=proof_sha:
        raise ValueError("Logical version mutated during private joined read")
    summary={
        "format":FORMAT,
        "status":"explicit_private_joined_version_read_not_activated",
        "period":"day",
        "logical_version_sha256":version_sha,
        "logical_version_file_sha256":proof_sha,
        "parent_private_version_sha256":entry["parent_private_version_sha256"],
        "parent_snapshot_sha256":entry["parent_parquet_sha256"],
        "delta_safe_sha256":entry["delta_safe_sha256"],
        "delta_parquet_sha256":entry["delta_parquet_sha256"],
        "delta_manifest_sha256":entry["delta_manifest_sha256"],
        "origin_overlay_version_sha256":entry["source_overlay_version_sha256"],
        "requested_first":first,
        "requested_last":last,
        "full_joined_rows_verified":entry["joined_rows"],
        "full_joined_stocks_verified":entry["joined_stocks"],
        "full_purchased_rows_verified":entry["purchased_rows"],
        "full_h5_gap_candidate_rows_verified":entry["h5_gap_candidate_rows"],
        "selected_stocks":len(symbols),
        "selected_rows":s["selected_rows"],
        "selected_purchased_rows":s["selected_purchased_rows"],
        "selected_h5_gap_candidate_rows":s["selected_h5_gap_candidate_rows"],
        "logical_version_parent_delta_parquet_manifest_and_safe_sha_verified":True,
        "private_active_pointers_read_or_modified":False,
        "original_market_sources_opened_or_modified":False,
        "no_live_market_source_freshness_recheck":True,
        "production_query_route_modified":False,
        "raw_ohlcva_or_stock_symbols_in_safe":False,
        "h5_gap_units_unverified_candidate":True,
        "ready_for_full_market_mirror":False,
    }
    if (REG.LOCK.is_symlink() or REG.LOCK.exists()
            or READER.sha256_file(REG.VERSIONS/(version_sha+".json"))!=proof_sha):
        raise ValueError("Logical version mutated immediately before SAFE publication")
    with output.open("x",encoding="utf-8") as stream:
        json.dump(summary,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")
    return {"bars_by_symbol":result["bars_by_symbol"],"safe_summary":summary}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--logical-version",required=True)
    p.add_argument("--symbols",nargs="+",required=True)
    p.add_argument("--from-date",required=True)
    p.add_argument("--to-date",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--explicit-private-version-read",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=query_version(a.logical_version,a.symbols,
                             a.from_date,a.to_date,a.out)
        s=result["safe_summary"]
        print("SAFE explicit private logical version query:",a.out)
        print("Full joined stocks:",s["full_joined_stocks_verified"],
              "Full rows:",s["full_joined_rows_verified"])
        print("Selected rows:",s["selected_rows"],
              "purchased:",s["selected_purchased_rows"],
              "H5 gap candidates:",s["selected_h5_gap_candidate_rows"])
        print("Original market files / private active pointers touched: NO")
        print("Market freshness rechecked: NO")
    except (ValueError,TypeError,KeyError,OSError,OverflowError,
            ImportError,ModuleNotFoundError):
        p.error("Explicit private logical version SHA query rejected; original data unchanged")


if __name__=="__main__":
    main()
