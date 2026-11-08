#!/usr/bin/env python3
"""Stage October 2026 verified H5 5min -> PRIVATE 15/30/60min candidates.

Each day/security is fail-closed on existing SHA-backed H5 minute receipts,
full 48-slot exchange grid and total absence of any purchased high-cycle bar.
This is an isolated, immutable research staging output, NOT an active market
overlay, vendor unit calibration, adjusted price view or Hikyuu mirror.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
STAGE_ROOT=MODULE/"work"/"unified_parquet"/"oct_high_cycle_staging"
PERIODS=("15min","30min","60min")
DEFAULT_DAYS=("2026-10-08","2026-10-09","2026-10-12","2026-10-13")
DEFAULT_SYMBOLS=("SH600000","SZ000001")
SHA256=re.compile(r"[0-9a-f]{64}\Z")
RUNID=re.compile(r"[0-9a-f]{12}\Z")
SYMBOL=re.compile(r"(?:SH|SZ|BJ)[0-9]{6}\Z")
FIELDS=("open","high","low","close","volume","amount")
VALUE_SOURCE="research_derived_candidate_from_sha_verified_h5_5min"
FORMAT="AStockDataTools Oct 2026 private H5 5min high-cycle candidate stage v1"

def _load():
    spec=importlib.util.spec_from_file_location(
        "private_oct_highcycle_existing_verified_audit",
        HERE/"audit-2026-oct-h5-five-minute-high-cycle-candidates-readonly.py")
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

C=_load()

def _sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for piece in iter(lambda:f.read(1048576),b""):
            h.update(piece)
    return h.hexdigest()

def _json(payload):
    return (json.dumps(payload,sort_keys=True,ensure_ascii=False,
                       allow_nan=False,indent=2)+"\n")

def _safe_stage_root():
    root=Path(STAGE_ROOT)
    if root.is_absolute() is False:
        raise ValueError("Private stage must be an absolute path")
    # No existing ancestor between the repository module and stage may be
    # redirected by a symlink; users cannot choose arbitrary output paths.
    expected=(MODULE/"work"/"unified_parquet"/"oct_high_cycle_staging")
    if root!=expected:
        raise ValueError("Private stage path must be canonical repository-owned")
    if MODULE.is_symlink():
        raise ValueError("Repository module may not be symlinked")
    for parent in (MODULE/"work",MODULE/"work"/"unified_parquet",root):
        if parent.is_symlink():
            raise ValueError("Private stage parent may not be symlinked")
    if not root.resolve().is_relative_to(MODULE.resolve()):
        raise ValueError("Private stage escapes repository")
    return root

def validate_plan(root,days,symbols,run_id):
    if not isinstance(root,Path) or not root.is_dir() or root.is_symlink():
        raise ValueError("Original market root absent/unsafe")
    if type(run_id) is not str or not RUNID.fullmatch(run_id):
        raise ValueError("Require new 12-digit hex run ID")
    if (not isinstance(days,(list,tuple)) or not 1<=len(days)<=20
            or len(set(days))!=len(days)):
        raise ValueError("Require 1..20 distinct October source dates")
    result_days=[]
    for item in days:
        if type(item) is not str:
            raise ValueError("Date must be ISO string")
        day=date.fromisoformat(item)
        if day.year!=2026 or day.month!=10:
            raise ValueError("Only October 2026 private candidate dates")
        result_days.append(day)
    if (not isinstance(symbols,(list,tuple)) or not 1<=len(symbols)<=100
            or len(set(symbols))!=len(symbols)
            or any(type(s) is not str or not SYMBOL.fullmatch(s)
                   for s in symbols)):
        raise ValueError("Require 1..100 unique canonical A-share security IDs")
    target=_safe_stage_root()/run_id
    if target.is_symlink() or target.exists():
        raise ValueError("Refuse to overwrite a previous private high-cycle run")
    return tuple(result_days),tuple(symbols),target

def source_receipt(day):
    """Uses the SAME minute reader's previously vetted SAFE and file SHA."""
    result=C.ALL.MINUTE._safe_private_file(day,"5min")
    if result is None:
        raise ValueError("Missing previously SAFE-verified 5min private source")
    path,entry=result
    expected=entry.get("unified_parquet_sha256")
    if not isinstance(expected,str) or not SHA256.fullmatch(expected):
        raise ValueError("Invalid existing H5 5min SHA receipt")
    if path.is_symlink() or not path.is_file() or _sha(path)!=expected:
        raise ValueError("Missing/changed H5 5min source data after SAFE gate")
    resolved=path.resolve()
    if not resolved.is_relative_to((MODULE/"work"/"unified_parquet").resolve()):
        raise ValueError("Minute source outside approved private workspace")
    return path,expected

def build_candidates(root,days,symbols):
    """Full read-only preflight; no output directories created by this phase."""
    by_period={period:[] for period in PERIODS}
    source_files={}
    counts=Counter()
    for day in days:
        source,source_hash=source_receipt(day)
        source_files[day.isoformat()]=(source,source_hash)
        for symbol in symbols:
            rows=C._query(root,symbol,"5min",day,private=True)
            if len(rows)!=48:
                raise ValueError("Absent/incomplete SHA-verified H5 5min stockday")
            for period in PERIODS:
                if C._query(root,symbol,period,day,private=False):
                    raise ValueError("Purchased high-cycle owns this stockday; refuse overlay")
                derived=C.aggregate_complete_5min(
                    day,symbol,rows,
                    expected_source="h5_only_complete_stockday",period=period)
                expected=48//C.HIGH[period]
                if len(derived)!=expected:
                    raise ValueError("Unexpected high-cycle source bucket count")
                for bar in derived:
                    record={
                        "ts":bar["hypothesized_raw_start_timestamp_ms"],
                        "symbol":symbol,
                        "trading_date":day.isoformat(),
                        "period":period,
                        **{field:float(bar[field]) for field in FIELDS},
                        "value_source":VALUE_SOURCE,
                        "source_period":"5min",
                        "source_5min_private_sha256":source_hash,
                        "time_label_and_vendor_units_certified":False,
                        "corporate_adjustments_applied":False,
                    }
                    if (any(not math.isfinite(record[f]) for f in FIELDS)
                            or record["volume"]<0 or record["amount"]<0):
                        raise ValueError("Invalid private derived OHLCVA")
                    by_period[period].append(record)
                counts[period]+=len(derived)
            counts["verified_stockdays"]+=1
    # Check no duplicated keys across all requested dates/symbols/periods.
    for period,rows in by_period.items():
        unique={(r["symbol"],r["ts"]) for r in rows}
        if len(unique)!=len(rows):
            raise ValueError("Duplicate private high-cycle candidate keys")
        expected=48//C.HIGH[period]*len(days)*len(symbols)
        if len(rows)!=expected:
            raise ValueError("Incomplete planned high-cycle candidate partition")
        rows.sort(key=lambda r:(r["trading_date"],r["symbol"],r["ts"]))
    if counts["verified_stockdays"]!=len(days)*len(symbols):
        raise ValueError("Missing verified H5 source stockday")
    return by_period,source_files

def stage(root,days,symbols,run_id):
    import pyarrow as pa
    import pyarrow.parquet as pq
    checked_days,checked_symbols,target=validate_plan(root,days,symbols,run_id)
    rows,source_files=build_candidates(root,checked_days,checked_symbols)
    root_stage=_safe_stage_root()
    schema=pa.schema([
        pa.field("ts",pa.int64(),nullable=False),
        pa.field("symbol",pa.string(),nullable=False),
        pa.field("trading_date",pa.string(),nullable=False),
        pa.field("period",pa.string(),nullable=False),
        *(pa.field(field,pa.float64(),nullable=False) for field in FIELDS),
        pa.field("value_source",pa.string(),nullable=False),
        pa.field("source_period",pa.string(),nullable=False),
        pa.field("source_5min_private_sha256",pa.string(),nullable=False),
        pa.field("time_label_and_vendor_units_certified",pa.bool_(),nullable=False),
        pa.field("corporate_adjustments_applied",pa.bool_(),nullable=False),
    ])
    if target.exists() or target.is_symlink():
        raise ValueError("Stage target appeared during preflight")
    root_stage.mkdir(parents=True,exist_ok=True)
    target.mkdir(exist_ok=False)
    outputs={}
    for period in PERIODS:
        path=target/(period+".parquet")
        if path.exists() or path.is_symlink():
            raise ValueError("Private candidate output already exists")
        table=pa.Table.from_pylist(rows[period],schema=schema)
        pq.write_table(table,path,compression="zstd",row_group_size=32768)
        with pq.ParquetFile(path,memory_map=False,pre_buffer=False) as pf:
            if pf.schema_arrow!=schema or pf.metadata.num_rows!=len(rows[period]):
                raise ValueError("Candidate private Parquet schema/row count failed readback")
            reloaded=[]
            for batch in pf.iter_batches(batch_size=32768,use_threads=False):
                reloaded.extend(batch.to_pylist())
        if reloaded!=rows[period]:
            raise ValueError("Private candidate OHLCVA/key/provenance readback mismatch")
        outputs[period]={
            "rows":len(rows[period]),
            "private_file":path.relative_to(MODULE).as_posix(),
            "sha256":_sha(path),
            "complete_row_by_row_readback_exact":True,
        }
    for source,expected in source_files.values():
        if _sha(source)!=expected:
            raise ValueError("Private H5 source SHA changed during candidate write")
    manifest={
        "format":FORMAT,
        "status":"research_only_private_oct_h5_5min_highcycle_candidates_written_readback",
        "run_id":run_id,
        "source_days":[day.isoformat() for day in checked_days],
        "symbols":list(checked_symbols),
        "verified_source_stockdays":len(checked_days)*len(checked_symbols),
        "sources":[{
            "day":day,
            "source_5min_private_file":file.relative_to(MODULE).as_posix(),
            "sha256":digest,
        } for day,(file,digest) in sorted(source_files.items())],
        "outputs":outputs,
        "purchased_high_cycle_source_blocks":0,
        "source_5min_original_SHA_receipts_verified":True,
        "all_48_native_start_grid_bars_required":True,
        "all_purchased_high_cycle_periods_must_be_absent":True,
        "no_day_week_month_materialized":True,
        "vendor_physical_units_certified":False,
        "timestamp_conversion_certified":False,
        "corporate_adjustments_certified":False,
        "original_market_files_modified":False,
        "production_or_private_active_pointer_modified":False,
        "ready_for_production_merge":False,
        "ready_for_h5_mirror":False,
        "raw_OHLCVA_in_report":False,
    }
    receipt=target/"receipt.json"
    with receipt.open("x",encoding="utf-8",newline="\n") as f:
        f.write(_json(manifest))
    # Readback receipt and immutable output SHA again before PASS.
    if json.loads(receipt.read_text(encoding="utf-8"))!=manifest:
        raise ValueError("Private stage receipt readback mismatch")
    for period in PERIODS:
        if _sha(target/(period+".parquet"))!=outputs[period]["sha256"]:
            raise ValueError("Private stage Parquet SHA mismatch after receipt")
    return manifest

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--days",nargs="+",default=list(DEFAULT_DAYS))
    p.add_argument("--symbols",nargs="+",default=list(DEFAULT_SYMBOLS))
    p.add_argument("--write-private-candidates-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=stage(a.root,a.days,a.symbols,a.run_id)
    except (ValueError,OSError,RuntimeError) as e:
        p.error("Private high-cycle staging NOT accepted: "+
                type(e).__name__+": "+str(e)+
                "; original market unchanged; partial private run may remain")
    print("PRIVATE_OCT_HIGH_CYCLE_STAGE="+json.dumps(result,sort_keys=True,
                                                 ensure_ascii=False,
                                                 separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
