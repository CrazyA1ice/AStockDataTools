#!/usr/bin/env python3
"""READ ONLY: recover/verify an already-written October 2026 private high-cycle batch.

Find an isolated 15m/30m/60m receipt by explicitly supplied known file SHA256
when the launcher failed AFTER physical file readback. No new candidates,
market files, receipt, query pointer, cache, active partition or index written.
Recompute all candidate rows from currently SHA-verified H5 and independently
purchased-checked 15/30/60m sources, and compare full private Parquet payloads.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
H16=re.compile(r"[a-f0-9]{64}\Z")

def _load():
    spec=importlib.util.spec_from_file_location(
        "oct_private_recover_existing_stager",
        HERE/"stage-2026-oct-verified-h5-high-cycle-private-parquet.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

S=_load()
STATUS="research_only_private_oct_h5_5min_highcycle_candidates_written_readback"
EXPECTED_COLUMNS=("ts","symbol","trading_date","period",
                  "open","high","low","close","volume","amount",
                  "value_source","source_period","source_5min_private_sha256",
                  "time_label_and_vendor_units_certified",
                  "corporate_adjustments_applied")

def _sha_arg(s):
    if type(s) is not str or H16.fullmatch(s) is None:
        raise ValueError("Require precise lowercase SHA256 hex digest")
    return s

def find_existing(first_sha):
    """Match only receipt-owned SHA under module-owned non-symlink stage root."""
    _sha_arg(first_sha)
    stage=S._safe_stage_root()
    if not stage.is_dir() or stage.is_symlink():
        raise ValueError("Missing safe private high-cycle staging directory")
    matches=[]
    receipt_count=0
    for receipt in stage.glob("*/receipt.json"):
        receipt_count+=1
        if receipt_count>10000:
            raise ValueError("Private receipt lookup budget exceeded")
        directory=receipt.parent
        if (directory.is_symlink() or receipt.is_symlink()
                or not S.RUNID.fullmatch(directory.name)
                or not receipt.is_file()):
            raise ValueError("Unexpected unsafe high-cycle private receipt path")
        doc=json.loads(receipt.read_text(encoding="utf-8"))
        if (doc.get("outputs",{}).get("15min",{}).get("sha256")==first_sha):
            matches.append((directory,doc))
    if len(matches)!=1:
        raise ValueError("Expected one existing stage receipt matching exact 15min SHA, found "+
                         str(len(matches)))
    return matches[0]

def verify(root,first_sha,second_sha,third_sha,*,expected_day="2026-10-13",
           expected_stockdays=16):
    import pyarrow as pa
    import pyarrow.parquet as pq
    for digest in (first_sha,second_sha,third_sha):
        _sha_arg(digest)
    if (type(expected_stockdays) is not int or not 1<=expected_stockdays<=100
            or expected_day!="2026-10-13"):
        raise ValueError("Only exact recovered 2026-10-13 bounded batch")
    directory,doc=find_existing(first_sha)
    run_id=directory.name
    days=doc.get("source_days")
    symbols=doc.get("symbols")
    if (doc.get("status")!=STATUS
            or doc.get("run_id")!=run_id
            or days!=[expected_day]
            or type(symbols) is not list
            or len(symbols)!=expected_stockdays
            or len(set(symbols))!=len(symbols)
            or any(not isinstance(sym,str) or not S.SYMBOL.fullmatch(sym)
                   or sym in ("SH600000","SZ000001") for sym in symbols)
            or doc.get("verified_source_stockdays")!=expected_stockdays
            or doc.get("purchased_high_cycle_source_blocks")!=0):
        raise ValueError("Recovered receipt has wrong batch identity or source ownership")
    required={
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
    if any(doc.get(key)!=val for key,val in required.items()):
        raise ValueError("Recovered receipt safety flags invalid")
    expected_hashes={"15min":first_sha,"30min":second_sha,"60min":third_sha}
    if set(doc.get("outputs",{}))!=set(S.PERIODS):
        raise ValueError("Recovered receipt must contain exactly three intraday periods")
    sources=doc.get("sources")
    if (not isinstance(sources,list) or len(sources)!=1
            or sources[0].get("day")!=expected_day):
        raise ValueError("Recovered receipt source day missing")
    minute_source,minute_sha=S.source_receipt(date.fromisoformat(expected_day))
    if (sources[0].get("sha256")!=minute_sha
            or sources[0].get("source_5min_private_file")!=
            minute_source.relative_to(S.MODULE).as_posix()):
        raise ValueError("Recovered source receipt no longer matches verified source")
    expected_rows,_=S.build_candidates(
        Path(root),tuple(date.fromisoformat(x) for x in days),tuple(symbols))
    actual_counts={}
    for period,hash_expected in expected_hashes.items():
        meta=doc["outputs"][period]
        file=directory/(period+".parquet")
        wanted_rows=expected_stockdays*{"15min":16,"30min":8,"60min":4}[period]
        if (file.is_symlink() or not file.is_file()
                or meta.get("rows")!=wanted_rows
                or meta.get("complete_row_by_row_readback_exact") is not True
                or meta.get("sha256")!=hash_expected
                or meta.get("private_file")!=
                file.relative_to(S.MODULE).as_posix()
                or S._sha(file)!=hash_expected):
            raise ValueError("Recovered "+period+" source file/receipt SHA or count changed")
        with pq.ParquetFile(file,memory_map=False,pre_buffer=False) as pf:
            if (pf.metadata.num_rows!=wanted_rows
                    or tuple(pf.schema_arrow.names)!=EXPECTED_COLUMNS
                    or not pa.types.is_int64(pf.schema_arrow.field("ts").type)):
                raise ValueError("Recovered "+period+" Parquet schema/count mismatch")
            actual=[]
            for batch in pf.iter_batches(batch_size=32768,use_threads=False):
                actual.extend(batch.to_pylist())
        if actual!=expected_rows[period]:
            raise ValueError("Recovered "+period+" Parquet contents no longer match H5 and purchased sources")
        if S._sha(file)!=hash_expected:
            raise ValueError("Recovered "+period+" Parquet changed during verification")
        actual_counts[period]=len(actual)
    if S._sha(minute_source)!=minute_sha:
        raise ValueError("Recovered H5 five-minute private source changed during read-only check")
    return {
        "status":"verified_existing_oct_13_private_high_cycle_batch_readonly",
        "run_id":run_id,
        "day":expected_day,
        "verified_source_stockdays":expected_stockdays,
        "period_rows":actual_counts,
        "total_rows":sum(actual_counts.values()),
        "outputs_sha256":expected_hashes,
        "original_market_files_modified":False,
        "new_private_or_production_files_written":False,
        "production_activated":False,
        "ready_for_production_merge":False,
        "independent_vendor_units_certified":False,
        "full_row_by_row_rederived_readback":True,
        "market_OHLCVA_not_printed":True,
        "receipt_relative_file":
            (directory/"receipt.json").relative_to(S.MODULE).as_posix(),
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--expected-15min-sha256",required=True)
    p.add_argument("--expected-30min-sha256",required=True)
    p.add_argument("--expected-60min-sha256",required=True)
    p.add_argument("--verify-existing-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=verify(a.root,a.expected_15min_sha256,a.expected_30min_sha256,
                      a.expected_60min_sha256)
    except (ValueError,TypeError,OSError,RuntimeError,KeyError) as exc:
        p.error("Existing Oct high-cycle batch NOT VERIFIED: "+
                type(exc).__name__+": "+str(exc)+"; nothing written")
    print("PRIVATE_OCT_HIGH_CYCLE_EXISTING_VERIFY="+json.dumps(
        result,ensure_ascii=False,sort_keys=True,separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
