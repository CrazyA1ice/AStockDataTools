#!/usr/bin/env python3
"""Verify real H5-only (symbol,day) keys for 83 permitted mixed-day candidates.

Fresh bounded source-key reads, never an automatic market merge. Keep the
exact stock identifiers ONLY in a new module-private ignored work/ manifest,
NOT the aggregate reports/ SAFE. The 5 quarantined July-16 keys are excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
REPORTS=MODULE/"reports"
WORK=MODULE/"work"
PRIVATE=WORK/"unified_parquet"/"mixed_day_key_manifests"
FORMAT="AStockDataTools live exact H5-only mixed stockday key verification v1"
PRIVATE_FORMAT="AStockDataTools private exact mixed stockday key manifest v1"
MAX_KEYS_PER_YEAR=150000
MAX_SOURCE_JSON=16000000


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OFFLINE=load("live_mixed_day_offline_gate","plan-private-mixed-h5-day-gaps-offline.py")
STAGE=load("live_mixed_day_stage_library","stage-h5-only-day-to-parquet.py")
CORE=STAGE.core


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_file(path,read=False,max_bytes=MAX_SOURCE_JSON):
    candidate=Path(path)
    if (REPORTS.is_symlink() or candidate.is_symlink()
            or candidate.suffix.lower()!=".json"
            or candidate.resolve().parent!=REPORTS.resolve()):
        raise ValueError("SAFE inputs/outputs must be direct non-symlink module reports JSON")
    target=candidate.resolve()
    if read:
        if (not target.is_file() or not 0<target.stat().st_size<=max_bytes):
            raise ValueError("Required bounded existing SAFE JSON is missing")
    elif target.exists():
        raise ValueError("No overwrite of live verification SAFE is allowed")
    return target


def private_folder(path):
    proposed=Path(path)
    if any(p.is_symlink() for p in (
            WORK,WORK/"unified_parquet",PRIVATE,proposed)):
        raise ValueError("Private market-key output must not involve symlinks")
    if (not re.fullmatch(r"keys_[a-f0-9]{12,32}",proposed.name)
            or proposed.exists()
            or proposed.resolve().parent!=PRIVATE.resolve()):
        raise ValueError("Require NEW keys_<hex> folder immediately under module private work")
    return proposed.resolve()


def verified_existing_plan(ledger,source2016,source2026,plan):
    originals={}
    for label,path in (("ledger",ledger),("2016",source2016),
                       ("2026",source2026),("plan",plan)):
        limit=1000000 if label in ("ledger","plan") else MAX_SOURCE_JSON
        file=safe_file(path,True,limit)
        originals[label]=(file,file.read_bytes())
    if len({obj[0] for obj in originals.values()})!=4:
        raise ValueError("SAFE evidence files must be distinct")
    source_raws={
        originals[str(y)][0].name:originals[str(y)][1]
        for y in (2016,2026)
    }
    expected=OFFLINE.analyze(originals["ledger"][1],source_raws)
    actual=json.loads(originals["plan"][1])
    if actual!=expected:
        raise ValueError("Mixed-day offline SAFE differs from SHA-bound source recomputation")
    if (actual["eligible_for_next_live_key_recheck_only"]!=83
            or actual["quarantined_pending_price_disagreement_review"]!=5
            or actual["safe_to_automatically_stage_promote_or_mirror"] is not False):
        raise ValueError("Mixed-day candidate policy not certified for live checking")
    dates={}
    quarantine=[]
    for entry in actual["years"]:
        year=entry["year"]
        chosen=[]
        for item in entry["mixed_date_candidates"]:
            d=date.fromisoformat(item["date"])
            if d.isoformat()!=item["date"] or d.year!=year:
                raise ValueError("Noncanonical mixed-day candidate")
            if item["status"]=="quarantined_same_day_price_disagreement":
                quarantine.append(d.isoformat())
                continue
            if (item["status"]!="candidate_requires_exact_stockday_live_recheck"
                    or item["same_day_overlapping_price_disagreements"]!=0):
                raise ValueError("Unexpected mixed-day candidate status")
            chosen.append(item)
        dates[year]=sorted(chosen,key=lambda x:x["date"])
    if (set(dates)!={2016,2026} or len(quarantine)!=1
            or quarantine!=["2026-07-16"]
            or sum(x["h5_only_stockday_candidate_rows"] for a in dates.values()
                   for x in a)!=83):
        raise ValueError("Mixed-day candidate keys or quarantine set changed")
    return originals,dates


def scan_h5_keys(root,year,days):
    """Read each symbol dataset once, probing only explicitly allowed day keys."""
    import h5py

    wanted={int(x["date"].replace("-",""))*10000 for x in days}
    keys=set()
    for market in ("sh","sz","bj"):
        filename=root/"HikyuuData"/(market+"_day.h5")
        if filename.is_symlink() or not filename.is_file():
            raise ValueError("Original daily H5 missing or symlinked")
        with h5py.File(filename,"r") as fh:
            group=fh.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("Invalid original H5 data group")
            for symbol in group:
                if (not symbol.startswith(market.upper())
                        or not CORE.is_a_share_candidate(symbol,year)):
                    continue
                ds=group.get(symbol)
                if (not isinstance(ds,h5py.Dataset)
                        or not set(CORE.H5_FIELDS).issubset(ds.dtype.names or ())):
                    raise ValueError("Bad original H5 candidate dataset")
                for stamp in wanted:
                    lo,hi=CORE.h5_key_slice(ds,stamp,stamp+1)
                    if hi==lo:
                        continue
                    if hi-lo!=1 or int(ds[lo]["datetime"])!=stamp:
                        raise ValueError("Duplicate or corrupt source H5 key")
                    key=(symbol,stamp)
                    if key in keys:
                        raise ValueError("Duplicate H5 stockday key")
                    keys.add(key)
                    if len(keys)>MAX_KEYS_PER_YEAR:
                        raise ValueError("H5 candidate year key budget exceeded")
    return keys


def scan_parquet_keys(root,year,days):
    """Project ts + symbol ONLY from relevant year row groups; reject duplicates."""
    import pyarrow.parquet as pq

    wanted={int(x["date"].replace("-",""))*10000 for x in days}
    files=CORE.year_files(root,"day",year)
    if not files:
        raise ValueError("No purchased day Parquet source for year")
    selected=sorted(x["date"] for x in days)
    _,_,low_ms,high_ms=CORE.parse_day_range(year,selected[0],selected[-1])
    keys=set()
    rows_scanned=0
    for path in files:
        if path.is_symlink():
            raise ValueError("Purchased market source symlink rejected")
        parquet=pq.ParquetFile(path)
        if not {"ts","symbol"}.issubset(parquet.schema_arrow.names):
            raise ValueError("Purchased day ts/symbol columns missing")
        for group in range(parquet.metadata.num_row_groups):
            if not CORE.row_group_overlaps_timestamp(
                    parquet.metadata.row_group(group),low_ms,high_ms):
                continue
            for batch in parquet.iter_batches(
                    row_groups=[group],batch_size=65536,
                    columns=["ts","symbol"],use_threads=True):
                ts_col=batch.column(0).to_pylist()
                sym_col=batch.column(1).to_pylist()
                rows_scanned+=len(ts_col)
                if rows_scanned>20000000:
                    raise ValueError("Purchased year two-column row scan budget exceeded")
                for ts,raw_symbol in zip(ts_col,sym_col):
                    if type(ts) is not int or not low_ms<=ts<high_ms:
                        continue
                    keytime=CORE.pq_stamp(ts,"day")
                    if keytime not in wanted:
                        continue
                    symbol=CORE.symbol_id(raw_symbol)
                    if symbol is None:
                        raise ValueError("Unknown purchased source symbol in selected day")
                    if not CORE.is_a_share_candidate(symbol,year):
                        continue
                    key=(symbol,keytime)
                    if key in keys:
                        raise ValueError("Duplicated purchased source daily key")
                    keys.add(key)
                    if len(keys)>MAX_KEYS_PER_YEAR:
                        raise ValueError("Purchased candidate year key budget exceeded")
    return keys,rows_scanned


def classify_exact_days(year,days,h5,purchased):
    """Check each stockday set against full annual audit, not just totals."""
    output=[]
    missing=[]
    wanted=set()
    for info in days:
        d=info["date"]
        stamp=int(d.replace("-",""))*10000
        wanted.add(stamp)
        h={k for k in h5 if k[1]==stamp}
        p={k for k in purchased if k[1]==stamp}
        intersection=h & p
        newly=h-p
        if (len(h)!=info["overlapping_source_stockday_rows"]+
                         info["h5_only_stockday_candidate_rows"]
                or len(p)!=info["purchased_source_stockday_rows"]
                or len(intersection)!=info["overlapping_source_stockday_rows"]
                or len(newly)!=info["h5_only_stockday_candidate_rows"]):
            raise ValueError("Live exact stockday key sets disagree with original audit on "+d)
        if any(k in purchased for k in newly):
            raise ValueError("Attempted shadow of purchased stockday")
        missing.extend(newly)
        output.append({
            "date":d,
            "h5_only_verified_unique_stockdays":len(newly),
            "purchased_keys_live_verified":len(p),
            "source_overlap_keys_live_verified":len(intersection),
        })
    if (any(x[1] not in wanted for x in h5)
            or any(x[1] not in wanted for x in purchased)):
        raise ValueError("Live key scan escaped the selected day set")
    return output,missing


def state_digest(root,years):
    states=[]
    for year in years:
        for path,size,mtime in STAGE.source_file_states(root,year):
            relative=Path(path).relative_to(root).as_posix()
            states.append((relative,int(size),int(mtime)))
    return digest(json.dumps(states,separators=(",",":"),
                             ensure_ascii=True).encode())


def execute(root,ledger,source2016,source2026,plan,manifest_dir,out):
    root=Path(root).resolve()
    if not (root/"HikyuuData").is_dir() or not (
            root/"AllCycleAStockData"/"day").is_dir():
        raise ValueError("Original H5 and purchased day roots required")
    manifest=private_folder(manifest_dir)
    safe=safe_file(out)
    if (root==MODULE or MODULE.is_relative_to(root)
            or root.is_relative_to(MODULE)
            or safe.is_relative_to(root) or manifest.is_relative_to(root)):
        raise ValueError("Private outputs must be outside original source tree")
    originals,dates=verified_existing_plan(
        ledger,source2016,source2026,plan)
    before=state_digest(root,(2016,2026))
    result_by_year=[]
    all_keys=[]
    projected_rows=0
    for year in (2016,2026):
        source_h5=scan_h5_keys(root,year,dates[year])
        source_pq,rows=scan_parquet_keys(root,year,dates[year])
        projected_rows+=rows
        outcome,keys=classify_exact_days(
            year,dates[year],source_h5,source_pq)
        all_keys.extend((day_key,symbol) for symbol,stamp in keys
                        for day_key in [date(stamp//100000000,
                                             (stamp//1000000)%100,
                                             (stamp//10000)%100).isoformat()])
        result_by_year.append({
            "year":year,"date_counts":outcome,
            "live_h5_candidate_keys":len(source_h5),
            "live_purchased_candidate_keys":len(source_pq),
            "live_verified_h5_only_stockdays":len(keys),
        })
    all_keys.sort()
    if len(all_keys)!=83 or len(set(all_keys))!=83 or any(
            d=="2026-07-16" for d,_ in all_keys):
        raise ValueError("Expected 83 strictly unique nonquarantined H5-only keys")
    if state_digest(root,(2016,2026))!=before:
        raise ValueError("Original source H5 or purchased Parquet changed during live read")
    if any(p.read_bytes()!=raw for p,raw in originals.values()):
        raise ValueError("Original SAFE source reports changed during live read")
    private_doc={
        "format":PRIVATE_FORMAT,
        "period":"day",
        "source_state_stat_sha256":before,
        "offline_mixed_plan_sha256":digest(originals["plan"][1]),
        "original_historical_ledger_sha256":digest(originals["ledger"][1]),
        "candidate_key_count":83,
        "candidate_symbol_day_keys":[{"date":d,"symbol":s}
                                     for d,s in all_keys],
        "source_purchased_parquet_priority_required":True,
        "h5_values_or_ohlcva_exported":False,
        "ready_for_unattended_staging":False,
        "quarantined_day_excluded":"2026-07-16",
    }
    blob=(json.dumps(private_doc,sort_keys=True,ensure_ascii=False,
                     indent=2)+"\n").encode("utf-8")
    if manifest.exists() or safe.exists():
        raise ValueError("Output files appeared during live read")
    manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.mkdir(exist_ok=False)
    private_path=manifest/"keys.json"
    with private_path.open("xb") as stream:
        stream.write(blob)
    summary={
        "format":FORMAT,
        "live_verified_nonquarantined_h5_only_stockdays":83,
        "quarantined_stockdays_excluded_from_exact_live_keyset":5,
        "years":result_by_year,
        "purchased_two_column_rows_projected":projected_rows,
        "private_key_manifest_sha256":digest(blob),
        "private_key_manifest_relative_path":
            private_path.relative_to(MODULE).as_posix(),
        "original_source_stat_sha256":before,
        "offline_mixed_plan_sha256":digest(originals["plan"][1]),
        "original_historical_ledger_sha256":digest(originals["ledger"][1]),
        "private_manifest_contains_exact_stock_codes_not_for_git_or_upload":True,
        "safe_summary_has_no_stock_symbols_or_raw_ohlcva":True,
        "all_source_h5_purchased_market_files_read_only":True,
        "original_market_files_written":False,
        "private_parquet_market_rows_staged":False,
        "native_h5_mirror_created":False,
        "private_or_production_active_pointer_modified":False,
        "ready_for_automatic_merge":False,
    }
    with safe.open("x",encoding="utf-8") as stream:
        json.dump(summary,stream,sort_keys=True,ensure_ascii=False,indent=2)
        stream.write("\n")
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--history-ledger",type=Path,required=True)
    p.add_argument("--source-2016",type=Path,required=True)
    p.add_argument("--source-2026",type=Path,required=True)
    p.add_argument("--mixed-plan",type=Path,required=True)
    p.add_argument("--key-manifest-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--verify-only-read-only-sources",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        result=execute(
            args.source_root,args.history_ledger,
            args.source_2016,args.source_2026,args.mixed_plan,
            args.key_manifest_dir,args.out)
        print("Verified H5-only mixed stockday keys:",
              result["live_verified_nonquarantined_h5_only_stockdays"])
        print("Private key-only manifest (no OHLCVA; NEVER upload):",
              result["private_key_manifest_relative_path"])
        print("SAFE aggregate-only report:",args.out)
        print("No original source market writes, private bar staging or production activation")
    except (OSError,ValueError,TypeError,KeyError,ImportError,
            ModuleNotFoundError,OverflowError):
        p.error("Live mixed-day key verification failed closed; original sources unchanged")


if __name__=="__main__":
    main()
