#!/usr/bin/env python3
"""Zero-download read-only QMT native datadir minute file inventory.

QMT datadir/SH/0 = tick (never descend or read), 60 = one minute,
300 = five minutes, 86400 = daily. Do not guess QMT .DAT binary schema
from TDX .lc1; do not call download_history_data, xtdata, or write files.
All output is metadata only, with up to three selected anchor securities.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path

FORMAT="qmt_main_datadir_1m_inventory_readonly_v1"
MARKETS=("SH","SZ","BJ")
PERIODS={"60":"1m","300":"5m","86400":"1d"}
STOCKS=("688001.SH","600000.SH","000001.SZ")
MAX_HASH_BYTES=64*1024*1024


def safe_dir(root,market,period):
    if market not in MARKETS or period not in PERIODS:
        raise ValueError("Only 60, 300, 86400 source directories")
    path=root/market/period
    if path.is_symlink():
        raise ValueError("Redirected QMT market folder")
    return path


def one_directory(root,market,period):
    path=safe_dir(root,market,period)
    result={"market":market,"period":PERIODS[period],
            "path":str(path),"read_only":True}
    if not path.is_dir():
        return {**result,"status":"MISSING","files":0,"bytes":0}
    counts=Counter()
    matched=[]
    size=0; latest=None
    for p in path.iterdir():
        if p.is_symlink():
            counts["symlink_skipped"]+=1
            continue
        if p.is_dir():
            counts["nested_directory"]+=1
            continue
        if not p.is_file():
            counts["unsupported_type"]+=1
            continue
        counts[p.suffix.lower() or "<none>"]+=1
        stat=p.stat()
        size+=stat.st_size
        if latest is None or stat.st_mtime>latest:
            latest=stat.st_mtime
        for stock in STOCKS:
            number,exchange=stock.split(".")
            if exchange!=market:
                continue
            # Different QMT builds may use 688001.DAT, 688001.SH.DAT.
            if p.stem.lower() not in (number.lower(),stock.lower()):
                continue
            proof={"stock":stock,"file_name":p.name,
                   "bytes":stat.st_size,
                   "modified_local":datetime.fromtimestamp(stat.st_mtime).isoformat(
                       timespec="seconds"),
                   "sha256":None,"hash_status":"SIZE_GT_64_MIB_NO_HASH"}
            if stat.st_size<=MAX_HASH_BYTES:
                h=hashlib.sha256()
                with p.open("rb") as f:
                    for b in iter(lambda:f.read(1024*1024),b""):
                        h.update(b)
                if p.stat().st_size!=stat.st_size:
                    proof["hash_status"]="FILE_CHANGED_DURING_READ"
                else:
                    proof["hash_status"]="SHA256_VERIFIED_READONLY"
                    proof["sha256"]=h.hexdigest()
            matched.append(proof)
    return {**result,"status":"PRESENT","files":sum(n for k,n in counts.items()
                 if k not in ("symlink_skipped","nested_directory",
                              "unsupported_type")),
            "bytes":size,"extension_counts":dict(sorted(counts.items())),
            "latest_modified_local":datetime.fromtimestamp(latest).isoformat(
                timespec="seconds") if latest is not None else None,
            "selected_anchor_files":matched,
            "minute_bar_count_not_inferred_from_Dat_bytes":True}


def run(root,logger=print):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("QMT datadir missing or symlink")
    details=[]
    # Explicitly DO NOT traverse '0': could contain hundreds of GB.
    for market in MARKETS:
        for period in PERIODS:
            result=one_directory(root,market,period)
            details.append(result)
            logger("QMT_LOCAL_DATADIR_PERIOD="+json.dumps(
                result,sort_keys=True,ensure_ascii=False))
    summary={"format":FORMAT,"root":str(root),
             "paths_checked":len(details),
             "one_min_file_count":sum(x["files"] for x in details
                                     if x["period"]=="1m"),
             "one_min_selected_anchor_files":sum(
                 len(x.get("selected_anchor_files",[])) for x in details
                 if x["period"]=="1m"),
             "tick_directory_0_never_read":True,
             "dat_file_contents_not_parsed":True,
             "historical_241_bar_coverage_not_yet_verified":True,
             "no_network":True,"no_files_written":True,
             "production_merge_authorized":False}
    logger("QMT_LOCAL_DATADIR_SUMMARY="+json.dumps(
        summary,sort_keys=True,ensure_ascii=False))
    return summary


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",required=True)
    a=p.parse_args()
    run(a.root)
