#!/usr/bin/env python3
"""Offline full-content reader for a PRIVATE 22,274 H5-only daily gap snapshot.

It verifies BOTH year partition bytes, complete Arrow row values/keys, immutable
manifest SHA and aggregate source SAFE. This is NOT live source freshness, a
purchased+H5 full market union, a vendor unit certificate or H5 mirroring.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from collections import Counter
from datetime import date,datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
ROOT=MODULE/"work"/"unified_parquet"/"candidate_snapshots"
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools offline 22274 H5-only day candidate partition verifier v1"


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


STAGER=load("private_22274_partitions_shared_schema",
            "materialize-private-full-22274-gap-candidates.py")


def source(safe_path):
    file=Path(safe_path)
    if (REPORTS.is_symlink() or file.is_symlink()
            or file.suffix.lower()!=".json"
            or file.resolve().parent!=REPORTS.resolve()
            or not file.is_file() or not 0<file.stat().st_size<=1000000):
        raise ValueError("Only a direct existing private candidate SAFE is allowed")
    data=file.read_bytes()
    safe=json.loads(data)
    if (type(safe) is not dict or safe.get("format")!=STAGER.FORMAT
            or safe.get("state")!="all_h5_only_day_candidates_materialized_private_not_merged"
            or safe.get("total_h5_only_candidate_rows")!=22274
            or safe.get("whole_date_candidate_rows")!=22191
            or safe.get("mixed_date_candidate_rows")!=83
            or safe.get("candidate_year_rows")!={"2016":1,"2026":22273}
            or safe.get("all_parquet_values_roundtrip_exactly") is not True
            or safe.get("purchased_parquet_historical_rows_included") is not False
            or safe.get("candidate_source_units_certified") is not False
            or safe.get("ready_for_production_query") is not False
            or safe.get("ready_for_automatic_market_merge") is not False
            or safe.get("source_market_files_written") is not False
            or safe.get("purchased_parquet_replaced") is not False
            or safe.get("private_or_production_active_pointer_modified") is not False
            or safe.get("h5_mirror_created") is not False
            or safe.get("quarantined_2026_07_16_stockday_bars_not_included")!=5
            or safe.get("no_real_market_ohlcva_or_stock_ids_exported_in_safe") is not True):
        raise ValueError("Untrusted candidate-only SAFE status or conservative gates")
    for key in ("source_version_sha256","source_fresh_full_live_safe_sha256",
                "original_source_stat_sha256","manifest_sha256"):
        if not re.fullmatch("[a-f0-9]{64}",str(safe.get(key))):
            raise ValueError("Untrusted candidate source SHA")
    rel=safe.get("snapshot_relative_dir")
    if (type(rel) is not str or not re.fullmatch(
            r"work/unified_parquet/candidate_snapshots/candidates_[0-9a-f]{12,32}",rel)):
        raise ValueError("Candidate partition escaped private module work tree")
    if any(p.is_symlink() for p in (MODULE/"work",
            MODULE/"work"/"unified_parquet",ROOT)):
        raise ValueError("Symlinked private candidate source root")
    directory=MODULE/rel
    mf=directory/"manifest.json"
    if (directory.is_symlink() or mf.is_symlink()
            or not directory.is_dir() or not mf.is_file()
            or directory.resolve().parent!=ROOT.resolve()
            or not 0<mf.stat().st_size<=1000000
            or STAGER.sha(mf)!=safe["manifest_sha256"]):
        raise ValueError("Candidate manifest or SHA unsafe/mismatched")
    return safe,hashlib.sha256(data).hexdigest(),directory,mf


def verify(snapshot_safe,out):
    output=Path(out)
    if (REPORTS.is_symlink() or output.is_symlink()
            or output.suffix.lower()!=".json"
            or output.resolve().parent!=REPORTS.resolve() or output.exists()):
        raise ValueError("Require NEW direct module reports/ output")
    safe,safe_sha,folder,mf=source(snapshot_safe)
    manifest=json.loads(mf.read_bytes())
    fields=("format","state","total_h5_only_candidate_rows",
            "whole_date_candidate_rows","mixed_date_candidate_rows",
            "candidate_year_rows","source_version_sha256",
            "source_fresh_full_live_safe_sha256","original_source_stat_sha256")
    for key in fields:
        if manifest.get(key)!=safe.get(key):
            raise ValueError("Private candidate manifest and SAFE disagree")
    if (manifest.get("purchased_parquet_historical_rows_included") is not False
            or manifest.get("candidate_source_units_certified") is not False
            or manifest.get("ready_for_automatic_market_merge") is not False
            or manifest.get("h5_mirror_created") is not False
            or manifest.get("quarantined_2026_07_16_stockday_bars_not_included")!=5):
        raise ValueError("Candidate manifest incorrectly claims production permission")
    parts=manifest.get("partitions")
    if type(parts) is not dict or set(parts)!={"2016","2026"}:
        raise ValueError("Private candidate partition set must cover 2016 and 2026")
    import pyarrow.parquet as pq
    import pyarrow as pa
    schema=STAGER.candidate_schema(pa)
    counts=Counter()
    years={}
    keys=set()
    for year in (2016,2026):
        part=parts[str(year)]
        expected=f"year={year}/day.parquet"
        if (type(part) is not dict or set(part)!={"relative_file","rows","sha256"}
                or part["relative_file"]!=expected
                or part["rows"]!=STAGER.YEAR_COUNTS[year]
                or not re.fullmatch("[a-f0-9]{64}",str(part["sha256"]))
                or safe.get("partition_sha256",{}).get(str(year))!=part["sha256"]):
            raise ValueError("Candidate year partition manifest fields are invalid")
        year_folder=folder/("year="+str(year))
        file=year_folder/"day.parquet"
        if (year_folder.is_symlink() or file.is_symlink()
                or not file.is_file() or file.resolve().parent!=year_folder.resolve()
                or not 0<file.stat().st_size<=STAGER.MAX_BYTES
                or STAGER.sha(file)!=part["sha256"]):
            raise ValueError("Private year candidate Parquet missing/changed")
        parquet=pq.ParquetFile(file,memory_map=False,pre_buffer=False)
        try:
            if (parquet.schema_arrow!=schema or parquet.metadata.num_rows!=part["rows"]
                    or not 1<=parquet.metadata.num_row_groups<=32):
                raise ValueError("Candidate partition Arrow type/footer/row-group invalid")
            table=parquet.read(columns=schema.names,use_threads=False)
        finally:
            parquet.close()
        if table.schema!=schema or table.num_rows!=part["rows"]:
            raise ValueError("Candidate partition decoded Arrow data is incomplete")
        prev=None
        for row in table.to_pylist():
            if type(row) is not dict or set(row)!=set(schema.names):
                raise ValueError("Unexpected candidate source columns")
            sym=row["symbol"]
            dt=row["trading_date"]
            if (type(sym) is not str or not STAGER.CORE.is_a_share_candidate(sym,year)
                    or type(dt) is not str):
                raise ValueError("Unrecognised private A-share candidate stock/day")
            d=date.fromisoformat(dt)
            if d.isoformat()!=dt or d.year!=year or dt=="2026-07-16":
                raise ValueError("Invalid/quarantined candidate date")
            source_name=row["value_source"]
            if source_name not in STAGER.SOURCES.values():
                raise ValueError("Invalid candidate whole/mixed provenance label")
            if (source_name=="private_h5_whole_date_candidate"
                    and dt not in STAGER.PRE.WHOLE_DATES):
                raise ValueError("Whole-date candidate outside exactly four audited days")
            if (source_name=="private_h5_mixed_stockday_candidate"
                    and dt in STAGER.PRE.WHOLE_DATES):
                raise ValueError("Mixed candidate overlaps a whole-date partition")
            ts=row["ts"]
            try:
                time=datetime.fromtimestamp(ts/1000,tz=STAGER.CORE.UTC8)
            except (ValueError,OverflowError,TypeError,OSError):
                raise ValueError("Bad private day source timestamp") from None
            if time.strftime("%Y-%m-%d %H:%M:%S")!=dt+" 00:00:00":
                raise ValueError("Non-Beijing-midnight private H5 daily source")
            for f in STAGER.FIELDS:
                x=row[f]
                if type(x) is not float or not math.isfinite(x) or x<0:
                    raise ValueError("Invalid candidate float64 OHLCVA field")
            op,hi,lo,cl=[row[x] for x in STAGER.FIELDS[:4]]
            if min(op,hi,lo,cl)<=0 or hi+1e-8<max(op,lo,cl) or lo-1e-8>min(op,hi,cl):
                raise ValueError("Candidate OHLC geometry failed")
            key=(sym,dt)
            order=(dt,sym,ts)
            if key in keys or prev is not None and order<prev:
                raise ValueError("Duplicate/unsorted candidate stockday key")
            keys.add(key)
            prev=order
            counts[source_name]+=1
        if STAGER.sha(file)!=part["sha256"]:
            raise ValueError("Candidate Parquet was replaced during decoding")
        years[str(year)]=part["rows"]
    if (years!={"2016":1,"2026":22273}
            or len(keys)!=22274
            or counts["private_h5_whole_date_candidate"]!=22191
            or counts["private_h5_mixed_stockday_candidate"]!=83):
        raise ValueError("Year/source/key conservation failed for all 22,274 candidates")
    again,again_sha,again_dir,again_mf=source(snapshot_safe)
    if (again!=safe or again_sha!=safe_sha or again_dir!=folder or again_mf!=mf
            or STAGER.sha(mf)!=safe["manifest_sha256"]
            or any(STAGER.sha(folder/x["relative_file"])!=x["sha256"]
                   for x in parts.values())):
        raise ValueError("Private source Parquet/manifest changed during verification")
    result={
        "format":FORMAT,
        "state":"all_22274_candidate_rows_partition_sha_schema_and_keys_verified_not_merged",
        "source_materialization_safe_sha256":safe_sha,
        "source_private_version_sha256":safe["source_version_sha256"],
        "source_private_manifest_sha256":safe["manifest_sha256"],
        "total_h5_only_day_candidates_verified":len(keys),
        "whole_date_candidate_rows_verified":counts["private_h5_whole_date_candidate"],
        "mixed_date_candidate_rows_verified":counts["private_h5_mixed_stockday_candidate"],
        "partition_year_rows_verified":years,
        "candidate_source_units_certified":False,
        "full_purchased_parquet_historical_market_included":False,
        "original_h5_or_purchased_parquet_opened":False,
        "original_market_source_freshness_rechecked":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "h5_mirror_created":False,
        "private_or_production_active_pointer_modified":False,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
        "no_market_OHLCVA_or_stock_codes_in_safe":True,
    }
    with output.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(result,f,ensure_ascii=False,sort_keys=True,indent=2)
        f.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--verify-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        r=verify(a.candidate_safe,a.out)
        print("Verified private candidate-only rows:",r["total_h5_only_day_candidates_verified"])
        print("By year:",r["partition_year_rows_verified"])
        print("SAFE:",a.out)
        print("Not full purchased+H5 market; original source freshness NOT rechecked")
    except (ValueError,OSError,TypeError,KeyError,ImportError,OverflowError):
        p.error("All-candidate private partition offline verification failed closed")


if __name__=="__main__":
    main()
