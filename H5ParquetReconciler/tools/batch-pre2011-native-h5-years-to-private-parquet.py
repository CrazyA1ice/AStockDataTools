#!/usr/bin/env python3
"""Bounded, resumable H5-native integer annual Parquet research staging.

One full 1990-2010 H5/date-key and purchased-all-footer requalification for
the REQUEST BATCH (not once for each year). Existing private year stages are
verified in full before reuse; missing years can be explicitly staged. No
unit-normalized market rows, production H5, purchased original changes, or
private active pointer writes are supported.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
MAX_BATCH_YEARS=3
MAX_PRIVATE_JOBS=128
MAX_BATCH_ROWS=750000
FORMAT="AStockDataTools bounded resumable pre2011 H5-native annual Parquet staging v1"


def import_one(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SINGLE=import_one("batch_legacy_h5_native_stager",
                  "stage-pre2011-native-h5-year-to-private-parquet.py")


def validate_selection(years,action,job_id,allow_stage):
    if (type(years) not in (list,tuple)
            or not 1<=len(years)<=MAX_BATCH_YEARS
            or any(type(y) is not int or not 1990<=y<=2010 for y in years)
            or len(set(years))!=len(years)
            or action not in ("plan","stage")):
        raise ValueError("Require 1..3 distinct selected 1990-2010 years")
    if action=="plan":
        if allow_stage or job_id is not None:
            raise ValueError("Read-only plan must not include stage permission or job ID")
    elif (allow_stage is not True or type(job_id) is not str
          or not re.fullmatch(r"[a-f0-9]{12,32}",job_id)):
        raise ValueError("Private annual Parquet stage needs explicit permission and hex job ID")
    return sorted(years)


def list_jobs():
    private=SINGLE.PRIVATE
    if (private.is_symlink() or (SINGLE.MODULE/"work").is_symlink()
            or (SINGLE.MODULE/"work"/"unified_parquet").is_symlink()):
        raise ValueError("Unsafe private stage directory hierarchy")
    if not private.exists():
        return []
    if not private.is_dir():
        raise ValueError("Invalid private raw H5 staging parent")
    jobs=list(private.iterdir())
    if len(jobs)>MAX_PRIVATE_JOBS:
        raise ValueError("Excessive private raw stage job directories")
    if any(p.is_symlink() for p in jobs):
        raise ValueError("Linked private stage job directory")
    return [p for p in jobs if p.is_dir()]


def digest_private_rows(file,year):
    import pyarrow as pa
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(file,memory_map=False,pre_buffer=False)
    try:
        if tuple(pf.schema_arrow.names)!=SINGLE.FIELDS:
            raise ValueError("Existing private H5 raw Parquet field list differs")
        if (pf.schema_arrow.field("symbol").type!=pa.string()
                or any(pf.schema_arrow.field(k).type!=pa.uint64()
                       for k in SINGLE.REQUIRED_NUMERIC)):
            raise ValueError("Existing private H5 raw Parquet types differ")
        seen=set()
        prior={}
        count=0
        sha=hashlib.sha256()
        markets=Counter()
        for batch in pf.iter_batches(
                batch_size=SINGLE.CHUNK,columns=list(SINGLE.FIELDS)):
            for item in batch.to_pylist():
                symbol=item["symbol"]
                if (type(symbol) is not str
                        or not re.fullmatch(r"(SH|SZ|BJ)[0-9]{6}",symbol)
                        or not SINGLE.AUDIT.CORE.is_a_share_candidate(symbol,2010)
                        or any(type(item[k]) is not int or item[k]<0
                               or item[k]>2**64-1 for k in SINGLE.REQUIRED_NUMERIC)):
                    raise ValueError("Invalid original H5 native private row")
                day=SINGLE.AUDIT.date_key(item["datetime"])
                if day.year!=year:
                    raise ValueError("Private native H5 row outside manifest year")
                if (symbol,item["datetime"]) in seen:
                    raise ValueError("Duplicate historical private stock/day")
                # A physical year has at most 500k rows; exact-key set bounded.
                seen.add((symbol,item["datetime"]))
                if symbol in prior and item["datetime"]<=prior[symbol]:
                    raise ValueError("Private source-native stock dates unordered")
                prior[symbol]=item["datetime"]
                sha.update(SINGLE.row_bytes(item))
                count+=1
                if count>SINGLE.MAX_YEAR_ROWS:
                    raise ValueError("Existing private year exceeds safe count budget")
                markets[symbol[:2]]+=1
        if count!=pf.metadata.num_rows:
            raise ValueError("Private year footer count differs from decoded rows")
        return count,sha.hexdigest(),dict(sorted(markets.items()))
    finally:
        pf.close()


def checked_existing(known,selected,inventory_sha):
    matches={}
    for folder in list_jobs():
        if not re.fullmatch(r"native_pre2011_(?:199[0-9]|200[0-9]|2010)_[a-f0-9]{12,32}",
                            folder.name):
            continue
        year=int(folder.name.split("_")[2])
        if year not in selected:
            continue
        manifest_path=folder/"manifest.json"
        data=folder/"h5-native-day.parquet"
        if (manifest_path.is_symlink() or data.is_symlink()
                or not manifest_path.is_file() or not data.is_file()):
            raise ValueError("Historical private job missing manifest or data")
        if manifest_path.stat().st_size>200000:
            raise ValueError("Oversized private annual manifest")
        m=json.loads(manifest_path.read_text(encoding="utf-8"))
        expected=known["yearly_source_key_inventory"][str(year)][
            "H5_candidate_stockday_rows"]
        if (not isinstance(m,dict) or m.get("format")!=SINGLE.PRIVATE_FORMAT
                or m.get("year")!=year
                or m.get("raw_h5_stockday_rows")!=expected
                or m.get("inventory_report_sha256")!=inventory_sha
                or m.get("purchased_parquet_footer_no_pre2011_rows") is not True
                or m.get("private_normalized_purchased_schema") is not False
                or m.get("H5_native_quantity_and_amount_units_certified") is not False
                or m.get("H5_original_source_modified") is not False
                or m.get("purchased_parquet_original_modified") is not False
                or m.get("production_or_private_active_pointer_changed") is not False
                or m.get("private_parquet_schema")!="native_uint64_all_ohlcva_no_renormalization"
                or m.get("full_private_parquet_sha256")!=SINGLE.hash_file(data)):
            raise ValueError("Historical private year manifest or data digest mismatches")
        count,stream_hash,markets=digest_private_rows(data,year)
        if (count!=expected or stream_hash!=m.get("raw_row_stream_sha256")
                or markets!=m.get("per_market_rows")):
            raise ValueError("Historical private year full decoding/checksum mismatches")
        if year in matches:
            raise ValueError("Multiple verified private raw stages for same year")
        matches[year]={
            "folder":folder,
            "parquet_sha256":m["full_private_parquet_sha256"],
            "row_stream_sha256":stream_hash,
            "row_count":count,
        }
    return matches


def stage_missing(root,year,inventory_sha,sources_before,job_id,expected):
    folder=SINGLE.PRIVATE/("native_pre2011_"+str(year)+"_"+job_id)
    SINGLE.private_folder(folder,year)
    # Claim an exclusively owned folder first. Never delete a foreign job
    # if a concurrent process creates the same folder name.
    folder.parent.mkdir(parents=True,exist_ok=True)
    folder.mkdir(exist_ok=False)
    h5,pq=sources_before
    try:
        result=SINGLE.stage_year(root,year,folder,expected)
        SINGLE.sources_unchanged(root,h5,pq)
        with (folder/"manifest.json").open("x",encoding="utf-8") as stream:
            json.dump({
                "format":SINGLE.PRIVATE_FORMAT,**result,
                "inventory_report_sha256":inventory_sha,
                "purchased_parquet_footer_no_pre2011_rows":True,
                "private_normalized_purchased_schema":False,
                "H5_native_quantity_and_amount_units_certified":False,
                "H5_original_source_modified":False,
                "purchased_parquet_original_modified":False,
                "production_or_private_active_pointer_changed":False,
            },stream,ensure_ascii=False,indent=2,sort_keys=True)
            stream.write("\n")
        return folder
    except Exception:
        shutil.rmtree(folder)
        raise


def run(root,inventory_report,years,out,action="plan",job_id=None,allow_stage=False):
    selected=validate_selection(years,action,job_id,allow_stage)
    safe=SINGLE.new_safe(out)
    market=Path(root).resolve()
    if not market.is_dir() or SINGLE.MODULE.is_relative_to(market):
        raise ValueError("Invalid source root or overlap with private staging")
    reference,inventory_sha=SINGLE.audit_file(inventory_report)
    # One complete source requalification (including *all* 24 original
    # purchased day file footers), irrespective of number of requested years.
    h5,pq,h5files,pqfiles=SINGLE.requalify(market,reference)
    expected={year:h5["yearly_source_key_inventory"][str(year)][
        "H5_candidate_stockday_rows"] for year in selected}
    if any(n<0 or n>SINGLE.MAX_YEAR_ROWS for n in expected.values()):
        raise ValueError("Historical annual key count outside stage budget")
    if sum(expected.values())>MAX_BATCH_ROWS:
        raise ValueError("Historical batch key count outside stage budget")
    existing=checked_existing(h5,selected,inventory_sha)
    needed=[year for year in selected if expected[year]>0 and year not in existing]
    newly=[]
    if action=="stage":
        for year in needed:
            SINGLE.sources_unchanged(market,h5files,pqfiles)
            stage_missing(market,year,inventory_sha,(h5files,pqfiles),
                          job_id,expected[year])
            newly.append(year)
            SINGLE.sources_unchanged(market,h5files,pqfiles)
        # Verify ALL versions, including newly generated jobs, before SAFE.
        existing=checked_existing(h5,selected,inventory_sha)
        if any(year not in existing for year in selected if expected[year]):
            raise ValueError("Not all nonempty historical annual partitions are verified")
    SINGLE.sources_unchanged(market,h5files,pqfiles)
    summary={
        "format":FORMAT,
        "status":("full_selected_historical_native_years_staged_verified_not_normalized"
                  if action=="stage" else "historical_native_year_batch_plan_only"),
        "action":action,
        "selected_years":selected,
        "historical_all_year_h5_candidate_rows":h5[
            "pre2011_candidate_h5_stockday_rows"],
        "selected_year_source_native_rows":sum(expected.values()),
        "yearly_status":[{
            "year":year,
            "audited_h5_native_rows":expected[year],
            "private_raw_parquet_present_and_verified":year in existing,
            "raw_parquet_sha256":existing[year]["parquet_sha256"]
                if year in existing else None,
            "has_no_original_h5_stockday_rows":expected[year]==0,
        } for year in selected],
        "existing_verified_years_before_action":[
            year for year in selected if year in existing and year not in newly],
        "newly_staged_years_this_action":newly,
        "remaining_nonempty_missing_years":[
            year for year in selected if expected[year]>0 and year not in existing],
        "one_full_source_inventory_requalification_per_batch":True,
        "original_source_inventory_sha256":inventory_sha,
        "purchased_all_day_parquet_earliest_footer":pq[
            "earliest_all_stock_footer_candidate_day"],
        "original_purchased_parquet_pre2011_absence_certified_for_scanned_dir":True,
        "prior_private_raw_stages_not_rewritten":True,
        "new_market_history_only_in_gitignored_private_raw_parquet":True,
        "purchased_compatible_normalized_day_parquet_created":False,
        "historic_H5_quantity_amount_units_certified":False,
        "historic_security_master_and_corporate_actions_certified":False,
        "original_market_files_modified":False,
        "private_active_pointer_changed":False,
        "production_query_route_modified":False,
        "native_h5_mirror_created":False,
        "no_raw_ohlcva_or_symbol_codes_in_safe":True,
    }
    # Only after all existing/new stages pass full content hash/readback,
    # and all original files AND the file sets are unchanged.
    SINGLE.sources_unchanged(market,h5files,pqfiles)
    with safe.open("x",encoding="utf-8") as stream:
        json.dump(summary,stream,ensure_ascii=False,indent=2,sort_keys=True)
        stream.write("\n")
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--inventory-report",type=Path,required=True)
    p.add_argument("--years",type=int,nargs="+",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--action",choices=("plan","stage"),required=True)
    p.add_argument("--job-id")
    p.add_argument("--allow-private-raw-parquet",action="store_true")
    p.add_argument("--read-only-original-sources",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        summary=run(a.root,a.inventory_report,a.years,a.out,a.action,
                    a.job_id,a.allow_private_raw_parquet)
        print("SAFE historical annual raw H5 Parquet batch:",a.out)
        print("Years:",summary["selected_years"])
        print("Actual audited H5 native rows:",
              summary["selected_year_source_native_rows"])
        print("Existing verified years before action:",
              summary["existing_verified_years_before_action"])
        print("New years staged this action:",
              summary["newly_staged_years_this_action"])
        print("Purchases/H5/production/private pointers modified: NO")
        print("RAW private schema is NOT purchased standardized daily schema.")
    except (ValueError,KeyError,TypeError,OSError,OverflowError,
            ImportError,ModuleNotFoundError):
        p.error("Bounded historical H5 annual private batch refused; original sources unchanged")


if __name__=="__main__":
    main()
