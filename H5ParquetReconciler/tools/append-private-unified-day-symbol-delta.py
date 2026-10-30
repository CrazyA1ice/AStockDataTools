#!/usr/bin/env python3
"""Build a NEW private Parquet symbol partition linked to a prepared base snapshot.

This is additive *stock-universe* expansion for the same bounded date window,
NOT a historical rewrite, production routing change, automatic trading update,
or a proof that H5 candidate monetary units are correct. Existing purchased
Parquet and Hikyuu H5 are always read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

VERSION=load("delta_private_snapshot_version",
             "version-private-unified-day-parquet-snapshot.py")
MAT=load("delta_private_snapshot_materializer",
         "materialize-private-unified-day-parquet-snapshot.py")
READER=VERSION.READER
MODULE=HERE.parent.resolve()
WORK=MODULE/"work"/"unified_parquet"
DELTAS=WORK/"snapshot_deltas"
FORMAT="AStockDataTools additive private day Parquet new-symbol delta v1"


def private_output(delta_dir,out):
    """Only new module-private directories and a new local SAFE JSON."""
    if any(p.is_symlink() for p in (
            MODULE/"work",WORK,DELTAS,READER.REPORTS)):
        raise ValueError("Unsafe private delta output parent")
    folder=Path(delta_dir)
    if (not re.fullmatch("delta_[0-9a-f]{12,32}",folder.name)
            or folder.exists() or folder.is_symlink()
            or folder.resolve().parent!=DELTAS.resolve()):
        raise ValueError("Delta must be a NEW direct private snapshot_deltas/delta_<hex>")
    report=READER.direct_report(out,for_output=True)
    return folder.resolve(),report


def trusted_parent(parent_sha):
    """No active pointer read. Parent MUST already be SHA-registered."""
    READER.require_sha(parent_sha)
    version=VERSION.load_version(parent_sha)
    VERSION.check_version_snapshot(version)
    path=VERSION.VERSIONS/(parent_sha+".json")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Unsafe registered base version file")
    version_file_sha=READER.sha256_file(path)
    safe_path=READER.REPORTS/version["snapshot_safe_basename"]
    safe,proof_sha,manifest_file,parquet=READER.source_snapshot(safe_path)
    manifest=READER.verified_manifest(manifest_file,safe)
    if (proof_sha!=version["snapshot_safe_sha256"]
            or safe["origin_private_version_sha256"]!=
                  version["origin_private_version_sha256"]
            or safe["row_count"]!=version["rows"]
            or manifest["rows"]!=version["rows"]):
        raise ValueError("Registered private base snapshot proof changed")
    return version,version_file_sha,safe,proof_sha,manifest


def validate_new_symbols(symbols,manifest):
    if (type(symbols) not in (tuple,list) or not 1<=len(symbols)<=5
            or any(type(s) is not str
                   or not re.fullmatch("(SH|SZ|BJ)[0-9]{6}",s)
                   for s in symbols)
            or len(set(symbols))!=len(symbols)):
        raise ValueError("Provide 1..5 distinct canonical new A-share symbols")
    old=set(manifest["per_symbol_counts"])
    if old.intersection(symbols):
        raise ValueError("New delta stocks overlap immutable existing snapshot")
    if len(old)+len(symbols)>10:
        raise ValueError("Private base plus delta exceeds 10-stock pilot budget")


def recheck_parent(parent_sha,expected_version_file_sha,proof_sha):
    version,vs,safe,ps,manifest=trusted_parent(parent_sha)
    if vs!=expected_version_file_sha or ps!=proof_sha:
        raise ValueError("Private parent proof changed during delta query")
    return version,safe,manifest


def append(root,parent_sha,overlay_sha,new_symbols,delta_dir,out):
    folder,report=private_output(delta_dir,out)
    version,version_file_sha,parent_safe,proof_sha,parent_manifest=trusted_parent(
        parent_sha)
    validate_new_symbols(new_symbols,parent_manifest)
    READER.require_sha(overlay_sha)
    if overlay_sha!=version["origin_private_version_sha256"]:
        raise ValueError("Delta must use exactly base snapshot's H5 gap overlay")
    first,last=parent_manifest["date_window"]
    # Complete live data-source check is delegated to the existing validated
    # batch path: original purchased Parquet always precedes verified H5 gaps.
    batch=MAT.BATCH.query_private_day_overlay_batch(
        root,list(new_symbols),first,last,overlay_sha,
        max_candidate_rows_per_symbol=300000,
        max_total_candidate_rows=3000000,
        max_result_bars_per_symbol=500,
        max_total_result_bars=2500,
        max_overlay_source_rows=30000,
        use_private_active=False)
    rows,source_counts,per_symbol=MAT.normalize_rows(
        batch,overlay_sha,new_symbols,first,last)
    if len(rows)>2500:
        raise ValueError("New symbol delta exceeded bounded row budget")
    # Query only the NEW symbols. Parent Parquet is never re-encoded/copied.
    recheck_parent(parent_sha,version_file_sha,proof_sha)
    import pyarrow as pa
    import pyarrow.parquet as pq
    table=pa.Table.from_pylist(rows,schema=MAT.schema(pa))
    if table.num_rows!=len(rows):
        raise ValueError("Private delta Arrow row count mismatch")
    folder.parent.mkdir(parents=True,exist_ok=True)
    folder.mkdir(exist_ok=False)
    parquet=folder/"day.parquet"
    pq.write_table(table,parquet,compression="zstd")
    sha=READER.sha256_file(parquet)
    decoded=pq.read_table(parquet,schema=MAT.schema(pa))
    if (decoded.schema!=MAT.schema(pa) or decoded.num_rows!=len(rows)
            or decoded.to_pylist()!=rows or READER.sha256_file(parquet)!=sha):
        raise ValueError("Private delta Parquet full roundtrip failed")
    # Recheck immutable parent and delta hashes BEFORE publishing manifest.
    recheck_parent(parent_sha,version_file_sha,proof_sha)
    metadata={
        "format":FORMAT,
        "status":"private_additive_symbol_delta_not_activated",
        "period":"day",
        "date_window":[first,last],
        "parent_private_snapshot_version_sha256":parent_sha,
        "parent_version_file_sha256":version_file_sha,
        "parent_snapshot_safe_sha256":proof_sha,
        "parent_parquet_sha256":parent_safe["private_parquet_sha256"],
        "parent_manifest_sha256":parent_safe["manifest_sha256"],
        "source_overlay_version_sha256":overlay_sha,
        "new_symbol_count":len(new_symbols),
        "new_symbols":list(new_symbols),
        "added_rows":len(rows),
        "purchased_rows":source_counts["purchased_parquet"],
        "h5_gap_candidate_rows":source_counts["private_hikyuu_h5_gap_candidate"],
        "per_symbol_counts":per_symbol,
        "delta_private_file":"day.parquet",
        "delta_parquet_sha256":sha,
        "all_new_private_values_roundtrip_exactly":True,
        "existing_snapshot_rows_rewritten":False,
        "original_market_sources_modified":False,
        "private_active_pointer_changed":False,
        "production_query_route_modified":False,
        "h5_gap_units_unverified_candidate":True,
        "ready_for_full_market_mirror":False,
    }
    manifest=folder/"manifest.json"
    with manifest.open("x",encoding="utf-8") as stream:
        json.dump(metadata,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")
    manifest_sha=READER.sha256_file(manifest)
    if (READER.sha256_file(parquet)!=sha
            or READER.sha256_file(manifest)!=manifest_sha):
        raise ValueError("Private delta files changed before SAFE")
    recheck_parent(parent_sha,version_file_sha,proof_sha)
    safe={
        "format":FORMAT,
        "status":metadata["status"],
        "private_delta_relative_path":str(folder.relative_to(MODULE)).replace("\\","/"),
        "period":"day",
        "new_symbol_count":len(new_symbols),
        "added_rows":len(rows),
        "purchased_rows":metadata["purchased_rows"],
        "h5_gap_candidate_rows":metadata["h5_gap_candidate_rows"],
        "parent_private_snapshot_version_sha256":parent_sha,
        "source_overlay_version_sha256":overlay_sha,
        "delta_parquet_sha256":sha,
        "delta_manifest_sha256":manifest_sha,
        "existing_snapshot_rows_rewritten":False,
        "private_active_pointer_changed":False,
        "original_market_sources_modified":False,
        "production_query_route_modified":False,
        "all_new_private_values_roundtrip_exactly":True,
        "new_h5_gap_units_unverified_candidate":True,
        "ready_for_full_market_mirror":False,
        "raw_ohlcva_or_absolute_market_paths_exported":False,
    }
    with report.open("x",encoding="utf-8") as stream:
        json.dump(safe,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")
    return safe


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,required=True)
    parser.add_argument("--parent-version",required=True)
    parser.add_argument("--overlay-version",required=True)
    parser.add_argument("--new-symbols",nargs="+",required=True)
    parser.add_argument("--delta-dir",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--read-only-market-sources",action="store_true",required=True)
    a=parser.parse_args(argv)
    try:
        result=append(a.source_root,a.parent_version,a.overlay_version,
                      a.new_symbols,a.delta_dir,a.out)
        print("SAFE private additive new-symbol delta:",a.out)
        print("New rows:",result["added_rows"],
              "purchased:",result["purchased_rows"],
              "H5 gap candidates:",result["h5_gap_candidate_rows"])
        print("Old private snapshot rewritten: NO")
        print("Original market files or production routes modified: NO")
    except (ValueError,TypeError,KeyError,OSError,OverflowError,
            ImportError,ModuleNotFoundError,json.JSONDecodeError):
        parser.error("Untrusted private additive delta rejected; no market source writes")


if __name__=="__main__":
    main()
