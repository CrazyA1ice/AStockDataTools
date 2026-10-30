#!/usr/bin/env python3
"""Explicit native TDX .day -> PRIVATE normalized post-close daily JSON bridge.

Only a bounded *single* real purchased-independent local TDX .day stock-day is
selected, after full native validation. A SAFE source/availability report is
always produced. Raw normalized OHLCVA is NEVER sent to reports/ or GitHub.
PRIVATE normalized copy requires an explicit flag, is created only inside
module ignored work/, and is never activated, merged into purchased Parquet,
or mirrored to Hikyuu H5. Existing private overlay validates a *separate*
user-approved stage operation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
WORK=MODULE/"work"/"tdx_postclose_native_intake"
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools native TDX daily source private normalized intake v1"


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


NATIVE=load("private_tdx_day_native_probe","probe-tdx-native-readonly.py")
POSTCLOSE=load("private_tdx_day_normalized_contract",
               "tdx-postclose-private-overlay.py")


def private_outputs(directory,out,allow_copy):
    if any(p.is_symlink() for p in (
            MODULE/"work",WORK,REPORTS)):
        raise ValueError("Symlinked private output parent")
    p=Path(out)
    if (p.suffix.lower()!=".json" or p.exists() or p.is_symlink()
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("SAFE output must be new module reports JSON")
    folder=Path(directory) if directory is not None else None
    if allow_copy:
        if (folder is None or not re.fullmatch(
                r"intake_[0-9a-f]{12,32}",folder.name)
                or folder.is_symlink() or folder.exists()
                or folder.resolve().parent!=WORK.resolve()):
            raise ValueError("Private normalized copy needs unused module-local intake_<hex>")
    elif folder is not None:
        raise ValueError("No private directory without explicit copy consent")
    return (folder.resolve() if folder is not None else None,p.resolve())


def requested(date_text,after_text):
    if type(date_text) is not str or type(after_text) is not str:
        raise ValueError("Require canonical date labels")
    try:
        day=date.fromisoformat(date_text)
        earlier=date.fromisoformat(after_text)
    except ValueError:
        raise ValueError("Invalid day or baseline date") from None
    if (day.isoformat()!=date_text or earlier.isoformat()!=after_text
            or not 2011<=day.year<=2100 or day<=earlier):
        raise ValueError("Requested TDX day must be strictly later than parent end")
    return day


def read_native_candidate(path,sym,day,baseline):
    """Strict full file SHA/chronology via existing validated probe, plus one row."""
    requested(day,baseline)
    candidate=Path(path)
    actual,period=NATIVE._symbol_and_period(candidate)
    if actual!=sym or period!="day":
        raise ValueError("Only matching canonical TDX .day supported")
    proof=NATIVE.inspect(candidate,sym,day)
    if (proof["period"]!="day" or proof["symbol"]!=sym
            or proof["requested_date"]!=day
            or proof["time_grid_verdict"] not in (
                "recognized_native_time_grid","no_records_on_requested_date")
            or proof["source_stable_during_read"] is not True
            or proof["all_source_record_timestamps_strictly_ascending"] is not True
            or proof["source_market_file_modified"] is not False
            or proof["automatic_normalization_or_staging_performed"] is not False):
        raise ValueError("Untrusted native TDX complete read-only proof")
    if proof["requested_date_source_records"] not in (0,1):
        raise ValueError("Native daily source has duplicate selected stock-day")
    before=candidate.stat()
    if before.st_size>NATIVE.MAX_SOURCE_BYTES or before.st_size%NATIVE.ROW_BYTES:
        raise ValueError("Native daily source exceeds byte bound")
    digest=hashlib.sha256()
    chosen=None
    with candidate.open("rb") as stream:
        for _ in range(before.st_size//NATIVE.ROW_BYTES):
            raw=stream.read(NATIVE.ROW_BYTES)
            if len(raw)!=NATIVE.ROW_BYTES:
                raise ValueError("Native source truncated during normalized extraction")
            digest.update(raw)
            # The full native probe has already independently checked geometry,
            # timestamp order, and amount/quantity ranges for every row.
            packed,op,hi,lo,cl,amount,volume,_unused=NATIVE.DAY.unpack(raw)
            if packed==int(day.replace("-","")):
                if chosen is not None:
                    raise ValueError("Duplicate selected native TDX stock-day")
                values=(op/100.0,hi/100.0,lo/100.0,cl/100.0,
                        float(volume),float(amount))
                if not all(math.isfinite(v) for v in values):
                    raise ValueError("Nonfinite native TDX candidate")
                chosen={
                    "time":"00:00","open":values[0],"high":values[1],
                    "low":values[2],"close":values[3],
                    "volume":values[4],"amount":values[5],
                }
        if stream.read(1):
            raise ValueError("Native TDX source changed during extraction")
    after=candidate.stat()
    if (before.st_size!=after.st_size or before.st_mtime_ns!=after.st_mtime_ns
            or digest.hexdigest()!=proof["source_content_sha256"]
            or (chosen is not None)!=(proof["requested_date_source_records"]==1)):
        raise ValueError("Native TDX content or source stat changed after proof")
    return proof,chosen


def intake(source,symbol,day,baseline,private_dir,out,allow_copy=False):
    folder,safe=private_outputs(private_dir,out,allow_copy)
    proof,bar=read_native_candidate(source,symbol,day,baseline)
    record=None
    if bar is not None:
        record={
            "format":POSTCLOSE.DOC_FORMAT,
            "source":"tdx_postclose_local",
            "symbol":symbol,
            "period":"day",
            "date":day,
            "time_label_policy":POSTCLOSE.PERIOD_POLICY["day"],
            "bars":[bar],
        }
        checked=POSTCLOSE.validate(record)
        if (checked.get("matching_bar_count")!=1
                or checked.get("eligible_for_automatic_primary_source_union") is not False
                or checked.get("supplier_timestamp_and_quantity_units_unverified") is not True):
            raise ValueError("Normalized TDX candidate failed private adapter gate")
    if allow_copy and bar is None:
        raise ValueError("Cannot privately copy a missing native trading day")
    summary={
        "format":FORMAT,
        "status":("native_tdx_stockday_available_not_staged"
                  if bar is not None else "native_tdx_stockday_not_present"),
        "source_period":"day",
        "requested_date":day,
        "required_strictly_after":baseline,
        "source_first_date":proof["source_first_date"],
        "source_last_date":proof["source_last_date"],
        "source_total_records":proof["source_total_records"],
        "source_full_file_sha256":proof["source_content_sha256"],
        "native_candidate_stockday_rows":1 if bar is not None else 0,
        "normalized_private_json_created":False,
        "normalized_record_sha256":(POSTCLOSE.sha(record)
                                    if record is not None else None),
        "underlying_tdx_32byte_layout_confirmed_by_probe":True,
        "native_source_file_stable_and_sha_rechecked":True,
        "explicit_private_copy_requested":bool(allow_copy),
        "tdx_day_price_cents_divided_by_100_candidate":True,
        "tdx_volume_amount_physical_units_unverified":True,
        "vendor_original_source_authenticity_certified":False,
        "market_source_other_periods_crosschecked":False,
        "ready_for_automatic_parquet_h5_union":False,
        "original_tdx_h5_purchased_parquet_modified":False,
        "private_active_pointers_read_or_modified":False,
        "production_query_route_modified":False,
        "no_raw_ohlcva_or_stock_codes_in_safe":True,
    }
    if allow_copy:
        folder.parent.mkdir(parents=True,exist_ok=True)
        folder.mkdir(exist_ok=False)
        target=folder/"normalized-day.json"
        with target.open("x",encoding="utf-8") as stream:
            json.dump(record,stream,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2)
            stream.write("\n")
        decoded,rawsha=POSTCLOSE.load_input(target)
        if decoded!=record or POSTCLOSE.validate(decoded)["matching_bar_count"]!=1:
            raise ValueError("Private TDX normalized day roundtrip failed")
        # Source may have been replaced AFTER extraction, before publication.
        renewed=NATIVE.inspect(source,symbol,day)
        if (renewed["source_content_sha256"]!=proof["source_content_sha256"]
                or renewed["source_last_date"]!=proof["source_last_date"]):
            raise ValueError("Native TDX source changed before private SAFE")
        summary["normalized_private_json_created"]=True
        summary["private_normalized_relative_path"]=target.relative_to(MODULE).as_posix()
        summary["private_normalized_file_sha256"]=rawsha
    with safe.open("x",encoding="utf-8") as stream:
        json.dump(summary,stream,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2)
        stream.write("\n")
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--symbol",required=True)
    p.add_argument("--date",required=True)
    p.add_argument("--strictly-after",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--private-dir",type=Path)
    p.add_argument("--allow-private-normalized-copy",action="store_true")
    p.add_argument("--read-only-original-tdx",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        result=intake(args.source,args.symbol,args.date,args.strictly_after,
                      args.private_dir,args.out,args.allow_private_normalized_copy)
        print("SAFE TDX native day/private adapter:",args.out)
        print("TDX source last date:",result["source_last_date"])
        print("New selected stock-day rows:",result["native_candidate_stockday_rows"])
        print("Private normalized copy made:",result["normalized_private_json_created"])
        print("No original source, active pointer or production routing writes.")
    except (ValueError,TypeError,KeyError,OverflowError,OSError,
            ImportError,ModuleNotFoundError):
        p.error("TDX native daily private intake rejected; original data unchanged")


if __name__=="__main__":
    main()
