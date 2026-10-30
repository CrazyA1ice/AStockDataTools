#!/usr/bin/env python3
"""Find possible newer native TDX .day files in EXPLICIT local install roots.

This is a narrow, metadata/tail-key-only discovery tool, NOT a disk search.
It checks root/vipdoc, root if already vipdoc, and one immediate child/vipdoc.
It never scans arbitrary subtrees, downloads market data, or opens H5/PQ.
A newer positional tail is a CANDIDATE, not full .day validation or authority
for ingestion. Use the existing probe-tdx-native-readonly.py to qualify it.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools selected TDX vipdoc day landing source inventory v1"
MAX_ROOTS=4
MAX_CHILD_ENTRIES=512
MAX_CANDIDATES=64
MAX_SYMBOLS=10
TAIL_ROWS=8


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


NATIVE=load("inventory_native_tdx_probe","probe-tdx-native-readonly.py")
CORE=load("inventory_a_share_tdx_market_validator",
          "reconcile-local-a-share-h5-parquet.py")


def validate_selection(roots,symbols,baseline):
    if (type(roots) not in (list,tuple) or not 1<=len(roots)<=MAX_ROOTS
            or type(symbols) not in (list,tuple)
            or not 1<=len(symbols)<=MAX_SYMBOLS
            or len(set(symbols))!=len(symbols)):
        raise ValueError("Require <=4 explicit roots and 1..10 distinct stocks")
    if type(baseline) is not str:
        raise ValueError("Baseline must be canonical ISO day")
    try:
        day=date.fromisoformat(baseline)
    except ValueError:
        raise ValueError("Invalid baseline") from None
    if day.isoformat()!=baseline or not 2011<=day.year<=2100:
        raise ValueError("Baseline out of supported date range")
    if any(type(sym) is not str or not re.fullmatch(r"(?:SH|SZ|BJ)[0-9]{6}",sym)
           or not CORE.is_a_share_candidate(sym,day.year) for sym in symbols):
        raise ValueError("Only canonical A-share stock symbols supported")
    listed=[]
    unique=set()
    for root in roots:
        path=Path(root)
        if (path.is_symlink() or not path.is_dir()
                or path.resolve() in unique):
            raise ValueError("Explicit install root missing, linked or repeated")
        unique.add(path.resolve())
        listed.append(path.resolve())
    return listed,day


def candidate_dirs(root):
    """At most one directory level below each EXPLICIT root, no disk recursion."""
    if root.name.lower()=="vipdoc":
        return [(root,".")]
    variants=[(root/"vipdoc","vipdoc")]
    children=list(root.iterdir())
    if len(children)>MAX_CHILD_ENTRIES:
        raise ValueError("Explicit root too large for bounded one-level discovery")
    for child in sorted(children,key=lambda p:p.name.lower()):
        if child.is_symlink():
            continue
        if child.is_dir():
            variants.append((child/"vipdoc",child.name+"/vipdoc"))
    found=[]
    for path,label in variants:
        if path.is_symlink():
            raise ValueError("Linked vipdoc candidate directory rejected")
        if path.is_dir():
            found.append((path,label))
    return found


def _file_stat(file):
    if file.is_symlink() or not file.is_file():
        raise ValueError("TDX daily source must be regular non-linked file")
    st=file.stat()
    return int(st.st_size),int(st.st_mtime_ns)


def tail_record(file):
    before=_file_stat(file)
    size,_mtime=before
    if (size==0 or size>NATIVE.MAX_SOURCE_BYTES
            or size%NATIVE.ROW_BYTES):
        raise ValueError("TDX .day source empty or outside native 32-byte budget")
    count=size//NATIVE.ROW_BYTES
    with file.open("rb") as stream:
        stream.seek(max(0,count-TAIL_ROWS)*NATIVE.ROW_BYTES)
        raw=stream.read(min(TAIL_ROWS,count)*NATIVE.ROW_BYTES)
        if len(raw)!=min(TAIL_ROWS,count)*NATIVE.ROW_BYTES:
            raise ValueError("TDX daily tail truncated")
    observed=[]
    for pos in range(0,len(raw),NATIVE.ROW_BYTES):
        d,minute=NATIVE._decode(raw[pos:pos+NATIVE.ROW_BYTES],"day")
        if minute is not None:
            raise ValueError("Not a native TDX daily source")
        observed.append(d)
    if not observed or any(a>=b for a,b in zip(observed,observed[1:])):
        raise ValueError("Native TDX day tail not strictly increasing")
    if _file_stat(file)!=before:
        raise ValueError("TDX source changed during bounded tail inspection")
    return {
        "source_last_positional_day":observed[-1].isoformat(),
        "source_total_physical_rows":count,
        "bounded_last_eight_day_keys_ascending":True,
        "full_original_file_chronology_checked":False,
        "native_volume_amount_units_certified":False,
        "stat_only_source_size_bytes":size,
        "source_full_content_sha256_verified":False,
        "tail_bytes_sha256_not_full_file_hash":hashlib.sha256(raw).hexdigest(),
    },before


def safe_output(out):
    p=Path(out)
    if (REPORTS.is_symlink() or p.is_symlink() or p.exists()
            or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Use unused SAFE JSON directly inside module reports")
    return p.resolve()


def inventory(roots,symbols,baseline,out):
    target=safe_output(out)
    install_roots,day=validate_selection(roots,symbols,baseline)
    source_entries=[]
    watched={}
    matched=[]
    for root_slot,root in enumerate(install_roots,1):
        for vipdoc,label in candidate_dirs(root):
            if not vipdoc.resolve().is_relative_to(root):
                raise ValueError("vipdoc candidate escaped explicit root")
            if len(source_entries)>=MAX_CANDIDATES:
                raise ValueError("Too many vipdoc candidate locations")
            slot=len(source_entries)+1
            selected=[]
            for stock_slot,symbol in enumerate(symbols,1):
                venue=symbol[:2].lower()
                market_folder=vipdoc/venue
                subfolder=market_folder/"lday"
                if (market_folder.is_symlink() or subfolder.is_symlink()
                        or not subfolder.resolve().is_relative_to(vipdoc.resolve())):
                    raise ValueError("Linked or escaping native TDX market directory")
                file=subfolder/(symbol.lower()+".day")
                if (file.is_symlink()
                        or not file.resolve().is_relative_to(vipdoc.resolve())):
                    raise ValueError("Linked or escaping selected TDX native file")
                if not file.is_file():
                    selected.append({"requested_stock_slot":stock_slot,
                                     "native_day_file_present":False,
                                     "source_last_positional_day":None})
                    continue
                source_data,original=tail_record(file)
                if file in watched:
                    if watched[file]!=original:
                        raise ValueError("Duplicate TDX source changed within inventory")
                else:
                    watched[file]=original
                selected.append({
                    "requested_stock_slot":stock_slot,
                    "native_day_file_present":True,
                    **source_data,
                    "source_tail_newer_than_reference":(
                        source_data["source_last_positional_day"]>day.isoformat()),
                })
                if source_data["source_last_positional_day"]>day.isoformat():
                    matched.append({
                        "candidate_slot":slot,
                        "root_slot":root_slot,
                        "vipdoc_relative_to_root":label,
                        "requested_stock_slot":stock_slot,
                        "observed_newer_tail_day":source_data[
                            "source_last_positional_day"],
                    })
            source_entries.append({
                "candidate_slot":slot,
                "root_slot":root_slot,
                "vipdoc_relative_to_root":label,
                "selected_native_day_file_slots":selected,
            })
    if any(_file_stat(p)!=prior for p,prior in watched.items()):
        raise ValueError("TDX native selected files changed before SAFE publication")
    result={
        "format":FORMAT,
        "status":("newer_native_tdx_tail_candidates_require_full_probe"
                  if matched else "no_newer_tdx_tail_observed_in_explicit_roots"),
        "source_reference_baseline":day.isoformat(),
        "explicit_install_root_count":len(install_roots),
        "vipdoc_candidate_count":len(source_entries),
        "selected_stock_count":len(symbols),
        "existing_selected_native_day_file_count":len(watched),
        "candidate_locations":source_entries,
        "newer_native_tail_candidates":matched,
        "newer_tail_candidate_count":len(matched),
        "discovery_limited_to_explicit_roots_one_child_level":True,
        "other_drives_and_unlisted_installations_not_searched":True,
        "tail_candidate_is_not_verified_latest_data":True,
        "no_full_native_file_chronology_or_origin_authenticity_certified":True,
        "native_daily_volume_amount_units_unverified":True,
        "no_market_ohlcva_stock_codes_or_absolute_paths_in_safe":True,
        "no_private_parquet_or_h5_data_created":True,
        "original_tdx_h5_purchased_parquet_modified":False,
        "private_active_pointers_read_or_modified":False,
        "production_query_route_modified":False,
    }
    with target.open("x",encoding="utf-8") as stream:
        json.dump(result,stream,sort_keys=True,ensure_ascii=False,indent=2,
                  allow_nan=False)
        stream.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--roots",nargs="+",type=Path,required=True)
    p.add_argument("--symbols",nargs="+",required=True)
    p.add_argument("--reference-last-day",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-explicit-roots",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        result=inventory(args.roots,args.symbols,args.reference_last_day,args.out)
        print("SAFE bounded TDX native vipdoc landing inventory:",args.out)
        print("Vipdoc candidate directories:",result["vipdoc_candidate_count"])
        print("Existing selected .day files:",
              result["existing_selected_native_day_file_count"])
        print("Newer-than-reference candidate tail files:",
              result["newer_tail_candidate_count"])
        print("Explicit install roots only; full native validation not performed.")
        print("Original files / production and private pointers modified: NO")
    except (ValueError,OSError,TypeError,KeyError,OverflowError,
            ImportError,ModuleNotFoundError):
        p.error("TDX native landing inventory rejected; source files unchanged")


if __name__=="__main__":
    main()
