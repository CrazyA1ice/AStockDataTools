#!/usr/bin/env python3
"""Bounded restartable private 1992-2010 daily H5 annual staging batch.

Each completed year's immutable candidate manifest is its checkpoint. A retry
revalidates the ORIGINAL H5 and purchased Parquet sources and all candidate
rows/SHA via the existing annual engine; it never overwrites a previous year.
No external job service, automatic production merge, market source writes or
raw OHLCVA/stock identifiers in terminal output.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
MAX_YEARS_PER_RUN=3
FIRST_YEAR=1992
LAST_YEAR=2010


def _load():
    spec=importlib.util.spec_from_file_location(
        "pre2011_daily_annual_private_batch_engine",
        HERE/"stage-original-h5-pre2011-annual-private-day.py")
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ANNUAL=_load()
FORMAT=ANNUAL.FORMAT
FLAGS=(
    "historical_security_master_certified",
    "official_historical_trading_calendar_certified",
    "h5_volume_amount_price_units_certified",
    "corporate_action_adjustment_certified",
    "raw_OHLCVA_in_manifest",
    "original_market_files_written",
    "purchased_parquet_replaced",
    "h5_mirror_created",
    "production_pointer_modified",
    "ready_for_production_merge",
)


def _check_manifest(summary,year):
    """Independent metadata/bytes proof; never re-export paid data."""
    import pyarrow.parquet as pq

    target=ANNUAL.EXPECTED[year]
    expected=(target[0],target[1],target[3])
    actual=(summary.get("candidate_stockday_rows"),
            summary.get("other_code_source_rows_not_staged"),
            summary.get("distinct_source_dates"))
    valid_states=("verified_private_candidate_not_promoted",
                  "already_verified_private_candidate_not_promoted")
    if (summary.get("format")!=FORMAT
            or summary.get("year")!=year or summary.get("period")!="day"
            or summary.get("state") not in valid_states
            or actual!=expected or any(summary.get(k) is not False for k in FLAGS)
            or summary.get("native_day_keys_and_OHLCVA_geometry_checked") is not True
            or summary.get("purchased_pre2011_all_day_files_confirmed_absent") is not True
            or summary.get("h5_original_state_sha256")!=ANNUAL.P90.EXPECTED_H5_STATE
            or summary.get("purchased_original_state_sha256")!=ANNUAL.P90.EXPECTED_PQ_STATE
            or summary.get("private_parquet_row_count")!=target[0]
            or summary.get("private_parquet_written") is not
                   (summary.get("state")=="verified_private_candidate_not_promoted")):
        raise ValueError("Private annual stage summary failed exact audited year/source safety gates")
    expected_relative=r"work/unified_parquet/historical_pre2011_daily_pilots/"+str(year)+r"-research-[a-f0-9]{16}"
    relative=summary.get("private_stage_relative_dir")
    sha=summary.get("private_parquet_sha256")
    if (type(relative) is not str or not re.fullmatch(expected_relative,relative)
            or type(sha) is not str or not re.fullmatch("[a-f0-9]{64}",sha)):
        raise ValueError("Private annual stage path/SHA not canonical")
    base=ANNUAL.MODULE
    folder=base/relative
    parquet=folder/"day.parquet"
    manifest=folder/"manifest.json"
    if (folder.is_symlink() or parquet.is_symlink() or manifest.is_symlink()
            or not folder.is_dir() or not parquet.is_file()
            or not manifest.is_file() or not 0<manifest.stat().st_size<=8192
            or not folder.resolve().is_relative_to(base.resolve())):
        raise ValueError("Private annual stage incomplete, symlinked, or escaped work")
    sha_now=ANNUAL.P90._digest(parquet)
    if sha_now!=sha:
        raise ValueError("Private annual staged Parquet SHA mismatch")
    meta=pq.ParquetFile(str(parquet))
    if meta.metadata.num_rows!=target[0] or meta.schema_arrow.names!=ANNUAL._candidate_schema().names:
        raise ValueError("Private annual staged Parquet footer rows/schema mismatch")
    saved=json.loads(manifest.read_text(encoding="utf-8"))
    # On resume the read-only response has a different state from immutable
    # manifest; all other immutable proof fields must remain identical.
    if (saved.get("format")!=FORMAT or
            saved.get("state")!="verified_private_candidate_not_promoted"
            or saved.get("private_parquet_written") is not True):
        raise ValueError("Existing annual checkpoint manifest state invalid")
    for key in (
        "year","period","candidate_stockday_rows",
        "other_code_source_rows_not_staged","distinct_source_dates",
        "h5_original_state_sha256","purchased_original_state_sha256",
        "private_stage_relative_dir","private_parquet_sha256",
        "private_parquet_row_count","purchased_pre2011_all_day_files_confirmed_absent",
        "native_day_keys_and_OHLCVA_geometry_checked",
        *FLAGS,
    ):
        if saved.get(key)!=summary.get(key):
            raise ValueError("Private annual stage manifest/source metadata drift: "+key)
    return {
        "year":year,"candidate_stockday_rows":target[0],
        "other_code_source_rows_excluded":target[1],
        "checkpoint":"new" if summary["private_parquet_written"] else "verified_existing",
        "private_day_parquet_sha256":sha,
        "private_relative_path":relative,
    }


def batch(root,start,stop,*,write=False,max_years=MAX_YEARS_PER_RUN):
    if type(start) is not int or type(stop) is not int or not (
            FIRST_YEAR<=start<=stop<=LAST_YEAR):
        raise ValueError("Only a selected contiguous range 1992-2010 is permitted")
    if (type(max_years) is not int or not 1<=max_years<=MAX_YEARS_PER_RUN
            or stop-start+1>max_years):
        raise ValueError("At most three annual private stages per invocation")
    if write is not True:
        raise ValueError("Private annual batch needs explicit --stage-private")
    if Path(root).resolve().is_relative_to(ANNUAL.MODULE.resolve()):
        raise ValueError("Market source cannot be inside private module")
    total=0
    completed=[]
    print(f"PRIVATE_H5_BATCH_BEGIN={start}..{stop} YEAR_LIMIT={max_years} NO_PRODUCTION=TRUE",flush=True)
    for year in range(start,stop+1):
        print(f"VERIFYING_PRIVATE_YEAR={year} AUDITED_EXPECTED={ANNUAL.EXPECTED[year][0]}",flush=True)
        # annual() always checks live H5 stat source SHA, all 24 purchased
        # daily original files / 139 RowGroups, exact H5 yearly stockdays,
        # year-roundtrip equality, existing stage SHA; fails closed.
        try:
            summary=ANNUAL.annual(root,year,write=True)
            proof=_check_manifest(summary,year)
        except Exception:
            print(f"PRIVATE_H5_BATCH_STOPPED_AT_YEAR={year} PRIOR_COMPLETED={len(completed)} SOURCE_AND_PRODUCTION_UNCHANGED_BY_BATCH",flush=True)
            raise
        completed.append(year)
        total+=proof["candidate_stockday_rows"]
        print(
            f"PRIVATE_H5_YEAR_PASS={year} STOCKDAYS={proof['candidate_stockday_rows']} "
            f"OTHER_EXCLUDED={proof['other_code_source_rows_excluded']} "
            f"CHECKPOINT={proof['checkpoint']} SHA256={proof['private_day_parquet_sha256']}",
            flush=True)
    result={
        "state":"private_annual_1992_2010_bounded_batch_completed_not_promoted",
        "from_year":start,"through_year":stop,
        "years_completed":completed,
        "new_or_revalidated_private_stockdays":total,
        "year_limit":max_years,
        "all_private_year_checkpoints_verified":True,
        "original_h5_and_purchased_parquet_modified":False,
        "production_activated":False,
        "historical_security_master_certified":False,
        "historical_trading_calendar_certified":False,
        "h5_price_volume_amount_units_certified":False,
        "candidate_OHLCVA_exported_to_console":False,
    }
    print("PRIVATE_H5_BATCH_SUMMARY="+json.dumps(result,sort_keys=True,separators=(",",":")),flush=True)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,required=True)
    parser.add_argument("--from-year",type=int,required=True)
    parser.add_argument("--through-year",type=int,required=True)
    parser.add_argument("--max-years",type=int,default=MAX_YEARS_PER_RUN)
    parser.add_argument("--stage-private",action="store_true")
    a=parser.parse_args(argv)
    batch(a.source_root,a.from_year,a.through_year,
          write=a.stage_private,max_years=a.max_years)


if __name__=="__main__":
    main()
