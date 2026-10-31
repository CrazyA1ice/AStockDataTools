#!/usr/bin/env python3
"""One full live-gate -> all 22,274 H5-only DAY candidates as PRIVATE year partitions.

This is a candidate-only snapshot, NOT a unified purchased+H5 market database.
The purchased original is authoritative. H5 units are unverified numeric
candidates; no production writes, native mirror, private pointer or promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
WORK=MODULE/"work"/"unified_parquet"
CANDIDATES=WORK/"candidate_snapshots"
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools all 22274 H5 only private day candidate year partitions v1"
SOURCES={
    "hikyuu_h5_tail_candidate":"private_h5_whole_date_candidate",
    "hikyuu_h5_mixed_day_candidate":"private_h5_mixed_stockday_candidate",
}
FIELDS=("open","high","low","close","volume","amount")
YEAR_COUNTS={2016:1,2026:22273}
MAX_BYTES=40*1024*1024


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


B=load("full_private_gap_stages_from_proven_batch",
       "query-private-combined-day-22274-batch-readonly.py")
PRE=B.PRE
REG=B.REG
WHOLE=B.WHOLE
CORE=PRE.KEYS.CORE


def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1<<20),b""):
            h.update(chunk)
    return h.hexdigest()


def candidate_schema(pa):
    return pa.schema([
        pa.field("ts",pa.int64()),
        pa.field("trading_date",pa.string()),
        pa.field("symbol",pa.string()),
        *(pa.field(f,pa.float64()) for f in FIELDS),
        pa.field("value_source",pa.string()),
    ])


def guarded_paths(folder,gate_out,out):
    f=Path(folder)
    if (any(p.is_symlink() for p in (WORK,CANDIDATES,REPORTS))
            or not re.fullmatch(r"candidates_[0-9a-f]{12,32}",f.name)
            or f.is_symlink() or f.exists()
            or f.resolve().parent!=CANDIDATES.resolve()):
        raise ValueError("Require NEW direct module private candidate_snapshots/candidates_<hex>")
    gate=PRE.new_report(gate_out)
    safe=PRE.new_report(out)
    if gate==safe:
        raise ValueError("Source gate and final aggregate SAFE must be distinct")
    if any(p.resolve().is_relative_to(f.resolve()) for p in (gate,safe)):
        raise ValueError("Aggregate SAFE cannot reside inside candidate partition")
    return f.resolve(),gate,safe


def normalise(item,source,day=None):
    """Reject duplicate/noncanonical/malformed source records before conversion."""
    if type(item) is not dict or set(item)!=set(PRE.MIXED.STAGE.SCHEMA_FIELDS):
        raise ValueError("Private day stage original schema changed")
    if type(item["ts"]) is not int or type(item["symbol"]) is not str:
        raise ValueError("Untrusted candidate daily timestamp or symbol")
    symbol=CORE.symbol_id(item["symbol"])
    if symbol is None:
        raise ValueError("Unrecognised original H5 candidate stock symbol")
    try:
        dt=datetime.fromtimestamp(item["ts"]/1000,tz=CORE.UTC8)
    except (ValueError,OverflowError,OSError):
        raise ValueError("Invalid H5 day candidate timestamp") from None
    if (dt.hour!=0 or dt.minute!=0 or dt.second!=0 or dt.microsecond!=0
            or not CORE.is_a_share_candidate(symbol,dt.year)
            or dt.date().isoformat()=="2026-07-16"):
        raise ValueError("Non-midnight, unsupported or quarantined H5 candidate day")
    d=dt.date().isoformat()
    if day is not None and d!=day:
        raise ValueError("Whole-date candidate escaped immutable staged date")
    if type(item["source"]) is not str or item["source"]!=source or source not in SOURCES:
        raise ValueError("Original whole/mixed candidate source distinction changed")
    values={}
    for field in FIELDS:
        v=item[field]
        if type(v) is not float or not math.isfinite(v) or v<0:
            raise ValueError("Nonfloat64, negative or nonfinite original candidate value")
        values[field]=v
    op,hi,lo,cl=(values[f] for f in FIELDS[:4])
    if min(op,hi,lo,cl)<=0 or hi+1e-8<max(op,lo,cl) or lo-1e-8>min(op,hi,cl):
        raise ValueError("Bad H5 candidate OHLC geometry")
    return {
        "ts":item["ts"],"trading_date":d,"symbol":symbol,
        **values,"value_source":SOURCES[source],
    }


def collect(whole_stages,mixed_rows,mixed_expected):
    """Use each immutable STAGE exactly once, not each stock with 180s live gate."""
    import pyarrow.parquet as pq
    if (type(whole_stages) is not list or len(whole_stages)!=4
            or {s["day"] for s in whole_stages}!=PRE.WHOLE_DATES):
        raise ValueError("Full-market candidate stage set incomplete")
    if (type(mixed_rows) is not list or len(mixed_rows)!=PRE.MIXED_ROWS
            or type(mixed_expected) not in (list,set,tuple)
            or len(mixed_expected)!=PRE.MIXED_ROWS):
        raise ValueError("83 mixed-day candidate records incomplete")
    grouped={2016:[],2026:[]}
    counts=Counter()
    keys=set()
    for stage in whole_stages:
        folder=WHOLE.versioner.safe_stage_path(
            WHOLE.versioner.MODULE/stage["stage_dir"])
        path=folder/"day.parquet"
        pf=pq.ParquetFile(path)
        try:
            if (tuple(pf.schema_arrow.names)!=tuple(WHOLE.versioner.stage_tool.SCHEMA_FIELDS)
                    or pf.metadata.num_rows!=stage["rows"]):
                raise ValueError("Invalid immutable whole-date candidate Arrow schema/footer")
            table=pf.read(columns=list(WHOLE.versioner.stage_tool.SCHEMA_FIELDS))
        finally:
            pf.close()
        if table.num_rows!=stage["rows"]:
            raise ValueError("Whole-date stage decoded count differs from manifest")
        for raw in table.to_pylist():
            row=normalise(raw,"hikyuu_h5_tail_candidate",stage["day"])
            key=(row["symbol"],row["trading_date"])
            if key in keys:
                raise ValueError("Duplicate H5-only whole-date stockday key")
            keys.add(key)
            grouped[2026].append(row)
            counts["whole"]+=1
        if sha(path)!=stage["parquet_sha256"]:
            raise ValueError("Original whole-date stage Parquet mutated while reading")
    expected=set(mixed_expected)
    if len(expected)!=PRE.MIXED_ROWS:
        raise ValueError("Mixed private expected key list contains duplicates")
    observed=set()
    for raw in mixed_rows:
        row=normalise(raw,"hikyuu_h5_mixed_day_candidate")
        key=(row["symbol"],int(datetime.fromtimestamp(
            row["ts"]/1000,tz=CORE.UTC8).strftime("%Y%m%d%H%M")))
        if key in observed or key not in expected:
            raise ValueError("Mixed staged H5 key differs from exact 83-key evidence")
        observed.add(key)
        simple=(row["symbol"],row["trading_date"])
        if simple in keys:
            raise ValueError("Mixed/private whole-date H5 candidate overlap")
        keys.add(simple)
        grouped[int(row["trading_date"][:4])].append(row)
        counts["mixed"]+=1
    if (observed!=expected or counts["whole"]!=PRE.WHOLE_ROWS
            or counts["mixed"]!=PRE.MIXED_ROWS
            or len(keys)!=PRE.TOTAL_ROWS
            or {y:len(rows) for y,rows in grouped.items()}!=YEAR_COUNTS):
        raise ValueError("22,274 candidate key conservation or year totals failed")
    for year,rows in grouped.items():
        rows.sort(key=lambda r:(r["trading_date"],r["symbol"],r["ts"]))
        if len({(x["symbol"],x["trading_date"]) for x in rows})!=len(rows):
            raise ValueError("Duplicate final year-partition stockday key")
    return grouped,dict(counts)


def snapshot(root,version_sha,live_safe,private_keys,ledger,source2016,
             source2026,mixed_plan,folder,gate_out,out,fast_bounded=True):
    directory,gate,report=guarded_paths(folder,gate_out,out)
    if type(fast_bounded) is not bool:
        raise ValueError("Explicit bounded H5 option must be boolean")
    root=Path(root).resolve()
    if REG.LOCK.is_symlink() or REG.LOCK.exists():
        raise ValueError("Private combined version currently locked")
    version=REG.load_version(version_sha)
    if (version.get("whole_day_candidate_rows")!=PRE.WHOLE_ROWS
            or version.get("mixed_stockday_candidate_rows")!=PRE.MIXED_ROWS
            or version.get("candidate_total_new_stockday_rows")!=PRE.TOTAL_ROWS
            or version.get("ready_for_production_query") is not False):
        raise ValueError("Invalid immutable H5-only candidate registry")
    whole_sha=version["whole_day_overlay_version_sha256"]
    mixed_stage_safe=PRE.REPORTS/version["mixed_stage_safe_basename"]
    # The expensive true market gate runs EXACTLY ONCE FOR THE WHOLE 22,274
    # records, before any original candidate Parquet is materialized.
    current=PRE.verify(root,whole_sha,mixed_stage_safe,live_safe,private_keys,
        ledger,source2016,source2026,mixed_plan,gate,
        bounded_h5_scan=fast_bounded)
    original_path,_,original=REG.read_audit(
        PRE.REPORTS/version["original_preflight_safe_basename"])
    proof_sha=sha(gate)
    if (current!=original or proof_sha!=version["fresh_recheck_safe_sha256"]
            or current["original_source_stat_sha256"]!=version["original_source_stat_sha256"]):
        raise ValueError("Fresh full live market source proof differs from immutable registry")
    before=PRE.KEYS.state_digest(root,(2016,2026))
    if before!=version["original_source_stat_sha256"]:
        raise ValueError("Original H5/purchased year source changed")
    whole,evidence,stages=WHOLE.verified_version(whole_sha,30000)
    originals,year_dates=PRE.KEYS.verified_existing_plan(
        ledger,source2016,source2026,mixed_plan)
    _,selected,mixed_file,mixed_meta,mixed_sha,mixed_rows,mixed_safe=(
        PRE.verify_mixed_stage(mixed_stage_safe,live_safe,private_keys,
                               originals,year_dates))
    if (len(selected)!=PRE.MIXED_ROWS
            or mixed_sha!=version["mixed_stage_parquet_sha256"]
            or sha(mixed_meta)!=version["mixed_stage_manifest_sha256"]
            or sha(mixed_safe)!=version["mixed_stage_safe_sha256"]):
        raise ValueError("Immutable 83 mixed-day stage SHA/keys diverged")
    rows,counts=collect(stages,mixed_rows,selected)
    # Nothing from the large proprietary candidate set is committed to git,
    # reports/ or external locations: only module work/<ignored> partitions.
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema=candidate_schema(pa)
    directory.parent.mkdir(parents=True,exist_ok=True)
    directory.mkdir(exist_ok=False)
    parts={}
    for year in sorted(rows):
        year_dir=directory/("year="+str(year))
        year_dir.mkdir(exist_ok=False)
        path=year_dir/"day.parquet"
        table=pa.Table.from_pylist(rows[year],schema=schema)
        if table.schema!=schema or table.num_rows!=YEAR_COUNTS[year]:
            raise ValueError("Candidate Arrow original source schema or year rows invalid")
        pq.write_table(table,path,compression="zstd",row_group_size=4096)
        if (not 0<path.stat().st_size<=MAX_BYTES
                or pq.read_table(path,schema=schema).to_pylist()!=rows[year]):
            raise ValueError("Private year candidate Parquet write/roundtrip failed")
        parts[str(year)]={
            "relative_file":f"year={year}/day.parquet",
            "rows":len(rows[year]),
            "sha256":sha(path),
        }
    manifest={
        "format":FORMAT,
        "state":"all_h5_only_day_candidates_materialized_private_not_merged",
        "period":"day",
        "source_version_sha256":version_sha,
        "whole_overlay_version_sha256":whole_sha,
        "source_fresh_full_live_safe_sha256":proof_sha,
        "original_source_stat_sha256":before,
        "mixed_stage_parquet_sha256":mixed_sha,
        "whole_date_candidate_rows":counts["whole"],
        "mixed_date_candidate_rows":counts["mixed"],
        "total_h5_only_candidate_rows":PRE.TOTAL_ROWS,
        "candidate_year_rows":dict((str(y),v) for y,v in YEAR_COUNTS.items()),
        "partitions":parts,
        "all_parquet_values_roundtrip_exactly":True,
        "purchased_parquet_historical_rows_included":False,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "source_market_files_written":False,
        "purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "h5_mirror_created":False,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
    }
    mf=directory/"manifest.json"
    with mf.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(manifest,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")
    # Recheck the full market stat alarm, both underlying immutable
    # partitions and source report/registration before publishing SAFE.
    if (PRE.KEYS.state_digest(root,(2016,2026))!=before
            or sha(mixed_file)!=mixed_sha
            or sha(mixed_meta)!=version["mixed_stage_manifest_sha256"]
            or sha(mixed_safe)!=version["mixed_stage_safe_sha256"]
            or sha(original_path)!=version["original_preflight_safe_sha256"]
            or sha(gate)!=proof_sha
            or REG.load_version(version_sha)!=version
            or WHOLE.verified_version(whole_sha,30000)!=(whole,evidence,stages)
            or sha(mf)!=sha(mf)
            or REG.LOCK.is_symlink() or REG.LOCK.exists()):
        raise ValueError("Postwrite stage/live proof or private registry drift")
    for year,record in parts.items():
        if sha(directory/record["relative_file"])!=record["sha256"]:
            raise ValueError("Postwrite private Parquet hash drift")
    output={
        "format":FORMAT,
        "state":manifest["state"],
        "snapshot_relative_dir":directory.relative_to(MODULE).as_posix(),
        "manifest_sha256":sha(mf),
        "source_version_sha256":version_sha,
        "source_fresh_full_live_safe_sha256":proof_sha,
        "original_source_stat_sha256":before,
        "whole_date_candidate_rows":counts["whole"],
        "mixed_date_candidate_rows":counts["mixed"],
        "total_h5_only_candidate_rows":PRE.TOTAL_ROWS,
        "candidate_year_rows":manifest["candidate_year_rows"],
        "partition_sha256":{k:r["sha256"] for k,r in parts.items()},
        "purchased_parquet_historical_rows_included":False,
        "all_parquet_values_roundtrip_exactly":True,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "source_market_files_written":False,
        "purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "h5_mirror_created":False,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
        "no_real_market_ohlcva_or_stock_ids_exported_in_safe":True,
    }
    with report.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(output,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")
    return output


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("source-root","version-sha256","live-safe","private-keys",
                 "history-ledger","source-2016","source-2026","mixed-plan",
                 "candidate-dir","fresh-recheck-out","out"):
        p.add_argument("--"+name,required=True,type=Path if name not in ("version-sha256",) else str)
    p.add_argument("--fast-bounded-h5-scan",action="store_true")
    p.add_argument("--private-candidate-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        r=snapshot(a.source_root,a.version_sha256,a.live_safe,a.private_keys,
                   a.history_ledger,a.source_2016,a.source_2026,a.mixed_plan,
                   a.candidate_dir,a.fresh_recheck_out,a.out,
                   a.fast_bounded_h5_scan)
        print("ALL private H5-only stockdays:",r["total_h5_only_candidate_rows"])
        print("Whole:",r["whole_date_candidate_rows"],
              "mixed:",r["mixed_date_candidate_rows"])
        print("Partition counts:",r["candidate_year_rows"])
        print("Aggregate-only SAFE:",a.out)
        print("NOT the full purchased+H5 day market; no original writes or mirror")
    except (OSError,ValueError,TypeError,KeyError,ImportError,OverflowError):
        p.error("Full private H5-only day candidate materialization failed closed")


if __name__=="__main__":
    main()
