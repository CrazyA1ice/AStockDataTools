#!/usr/bin/env python3
"""Opt-in, LOCAL-ONLY post-close stock-day staging; no production source union.

This is a STRICT NORMALIZED JSON ADAPTER CONTRACT, not a parser for proprietary
Tongdaxin .day/.lc1/.lc5 binary files. The caller supplies one complete
symbol/date/period. No price or volume is printed or placed in reports/.
Explicit staging copies licensed/user data ONLY into git-ignored work/;
rollback changes an active pointer, never edits Parquet/H5 or source input.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
from contextlib import contextmanager
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
WORK=(MODULE/"work"/"tdx_postclose_overlay").resolve()
REPORTS=(MODULE/"reports").resolve()
SPEC=importlib.util.spec_from_file_location(
    "tdx_overlay_core",HERE/"reconcile-local-a-share-h5-parquet.py")
core=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)
PERIOD_POLICY={
    "day":"daily_session_date",
    "5min":"five_minute_start_label",
    "1min":"one_minute_end_plus_opening_0930",
}
BAR_FIELDS=("time","open","high","low","close","volume","amount")
DOC_FORMAT="AStockDataTools normalized local postclose stock-day v1"
STORE_FORMAT="AStockDataTools private postclose overlay version v1"
POINTER_FORMAT="AStockDataTools private postclose overlay active pointer v1"
MAX_INPUT_BYTES=256*1024


def canonical_bytes(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),
                      ensure_ascii=False,allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_input(path):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>MAX_INPUT_BYTES:
        raise ValueError("Input must be a regular <=256 KiB local JSON")
    stat_before=p.stat()
    raw=p.read_bytes()
    stat_after=p.stat()
    if (len(raw)>MAX_INPUT_BYTES or stat_before.st_size!=stat_after.st_size
            or stat_before.st_mtime_ns!=stat_after.st_mtime_ns):
        raise ValueError("Input changed while being read")
    digest=hashlib.sha256(raw).hexdigest()
    try:
        def strict_object(pairs):
            out={}
            for key,value in pairs:
                if key in out:
                    raise ValueError("Duplicate JSON object key: "+key)
                out[key]=value
            return out
        record=json.loads(raw.decode("utf-8"),object_pairs_hook=strict_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ValueError("JSON NaN/Infinity forbidden")))
    except (UnicodeDecodeError,json.JSONDecodeError) as e:
        raise ValueError("Invalid input JSON") from e
    return record,digest


def expected_times(period):
    if period=="day":
        return ["00:00"]
    if period=="5min":
        values=list(range(570,690,5))+list(range(780,900,5))
    elif period=="1min":
        values=list(range(570,691))+list(range(781,901))
    else:
        raise ValueError("Unknown period")
    return [f"{v//60:02d}:{v%60:02d}" for v in values]


def validate(record):
    """Validate exact source time grid and finite OHLCVA, do not re-scale."""
    if type(record) is not dict or set(record)!={
            "format","source","symbol","period","date","time_label_policy","bars"}:
        raise ValueError("Normalized stock-day document has unexpected fields")
    if record["format"]!=DOC_FORMAT or record["source"]!="tdx_postclose_local":
        raise ValueError("Unknown normalized format or source")
    period=record["period"]
    if type(period) is not str or period not in PERIOD_POLICY:
        raise ValueError("period must be day, 1min or 5min")
    if record["time_label_policy"]!=PERIOD_POLICY[period]:
        raise ValueError("Explicit time label convention required")
    date_text=record["date"]
    if type(date_text) is not str:
        raise ValueError("date must be YYYY-MM-DD")
    try:
        d=date.fromisoformat(date_text)
    except ValueError as exc:
        raise ValueError("Invalid trading date") from exc
    if d.isoformat()!=date_text or not 2011<=d.year<=2100:
        raise ValueError("Date must use canonical YYYY-MM-DD in 2011..2100")
    sym=record["symbol"]
    if (type(sym) is not str or core.symbol_id(sym)!=sym
            or not core.is_a_share_candidate(sym,d.year)):
        raise ValueError("Expected canonical A-share candidate symbol")
    bars=record["bars"]
    required=expected_times(period)
    if type(bars) is not list or len(bars)!=len(required):
        raise ValueError("Incomplete stock-day time grid or bar count")
    for index,(bar,time_label) in enumerate(zip(bars,required)):
        if type(bar) is not dict or set(bar)!=set(BAR_FIELDS):
            raise ValueError("Invalid OHLCVA fields at bar "+str(index))
        if type(bar["time"]) is not str or bar["time"]!=time_label:
            raise ValueError("Missing, duplicate or unordered source time key")
        values=[bar[key] for key in BAR_FIELDS[1:]]
        if any(type(value) not in (float,int) or not math.isfinite(value)
               for value in values):
            raise ValueError("Nonfinite/non-numeric OHLCVA")
        o,h,l,c,vol,amt=values
        if (min(o,h,l,c)<=0 or
                h<max(o,l,c)-1e-10 or l>min(o,h,c)+1e-10
                or vol<0 or amt<0 or
                any(abs(v)>1e20 for v in values)):
            raise ValueError("Invalid OHLC or negative/implausible quantity")
    return {
        "symbol":sym,"date":date_text,"period":period,
        "time_label_policy":PERIOD_POLICY[period],
        "matching_bar_count":len(bars),
        "complete_synthetic_grid_checked":True,
        "exchange_calendar_independently_verified":False,
        "supplier_timestamp_and_quantity_units_unverified":True,
        "periods_not_cross_reconciled":True,
        "eligible_for_automatic_primary_source_union":False,
    }


def private_dir(symbol,period,day):
    if (type(symbol) is not str or not re.fullmatch(r"(?:SH|SZ|BJ)[0-9]{6}",symbol)
            or period not in PERIOD_POLICY):
        raise ValueError("Invalid private overlay scope")
    try:
        parsed=date.fromisoformat(day)
    except (TypeError,ValueError) as e:
        raise ValueError("Invalid private overlay date") from e
    if parsed.isoformat()!=day:
        raise ValueError("Noncanonical private date")
    return WORK/period/parsed.strftime("%Y-%m")/symbol/day


@contextmanager
def exclusive_lock(directory):
    if (not WORK.is_relative_to(MODULE.resolve()/"work")
            or (MODULE/"work").is_symlink()):
        raise ValueError("Private overlay must remain within module work/")
    directory.mkdir(parents=True,exist_ok=True)
    if directory.is_symlink() or not directory.resolve().is_relative_to(WORK):
        raise ValueError("Unsafe private overlay destination")
    lock=directory/".operation.lock"
    try:
        fd=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as e:
        raise ValueError("Another overlay operation is active (lock exists)") from e
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def ensure_hash(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}",value):
        raise ValueError("Malformed private overlay content hash")
    return value


def read_pointer(directory):
    target=directory/"active.json"
    if not target.exists():
        return None
    if target.is_symlink():
        raise ValueError("Unsafe active overlay pointer")
    pointer=json.loads(target.read_text(encoding="utf-8"))
    if (type(pointer) is not dict or pointer.get("format")!=POINTER_FORMAT
            or set(pointer)!={"format","current_version_sha256"}
            or type(pointer["current_version_sha256"]) is not str):
        raise ValueError("Corrupt active overlay pointer")
    return ensure_hash(pointer["current_version_sha256"])


def read_version(directory,digest):
    digest=ensure_hash(digest)
    p=directory/"versions"/(digest+".json")
    if (not p.is_file() or p.is_symlink()
            or (directory/"versions").is_symlink()
            or not p.resolve().is_relative_to(WORK)):
        raise ValueError("Missing/corrupt private overlay version")
    if p.stat().st_size>MAX_INPUT_BYTES+8192:
        raise ValueError("Oversized private version")
    entry=json.loads(p.read_text(encoding="utf-8"))
    if (type(entry) is not dict or entry.get("format")!=STORE_FORMAT
            or set(entry)!={"format","record","source_input_sha256",
                             "previous_version_sha256","version_sha256"}):
        raise ValueError("Invalid immutable private version format")
    checksum=sha({
        "record":entry["record"],
        "source_input_sha256":entry["source_input_sha256"],
        "previous_version_sha256":entry["previous_version_sha256"]})
    if entry["version_sha256"]!=digest or checksum!=digest:
        raise ValueError("Private version checksum mismatch")
    validate(entry["record"])
    if entry["previous_version_sha256"] is not None:
        ensure_hash(entry["previous_version_sha256"])
    return entry


def atomic_pointer(directory,digest):
    # Only the ACTIVE pointer is ever rewritten; immutable versions remain.
    active=directory/"active.json"
    if active.is_symlink():
        raise ValueError("Unsafe active overlay pointer")
    tmp=directory/".active.tmp"
    if tmp.exists() or tmp.is_symlink():
        raise ValueError("Stale temporary active pointer, refusing overwrite")
    try:
        with tmp.open("x",encoding="utf-8") as fh:
            json.dump({"format":POINTER_FORMAT,
                       "current_version_sha256":digest},
                      fh,sort_keys=True,allow_nan=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp,active)
    finally:
        tmp.unlink(missing_ok=True)


def stage(record,raw_sha):
    summary=validate(record)
    ensure_hash(raw_sha)
    directory=private_dir(summary["symbol"],summary["period"],summary["date"])
    with exclusive_lock(directory):
        previous=read_pointer(directory)
        if previous is not None:
            old=read_version(directory,previous)
            if (old["record"]==record and
                    old["source_input_sha256"]==raw_sha):
                return dict(summary,action="stage",outcome="already_active",
                            local_private_version_sha256=previous,
                            prior_version_exists=old["previous_version_sha256"] is not None)
        version_body={"record":record,"source_input_sha256":raw_sha,
                      "previous_version_sha256":previous}
        digest=sha(version_body)
        version=dict(version_body,format=STORE_FORMAT,version_sha256=digest)
        versions=directory/"versions"
        if (versions.is_symlink() or
                not versions.resolve().is_relative_to(WORK)):
            raise ValueError("Unsafe private versions destination")
        versions.mkdir(exist_ok=True)
        target=versions/(digest+".json")
        if target.exists() or target.is_symlink():
            # A rollback may have disabled an otherwise valid immutable
            # snapshot. Reactivate only after verifying its bytes and chain.
            existing=read_version(directory,digest)
            if (existing["record"]!=record or
                    existing["source_input_sha256"]!=raw_sha or
                    existing["previous_version_sha256"]!=previous):
                raise ValueError("Existing version has mismatched provenance")
            if existing["record"]["symbol"]!=summary["symbol"]:
                raise ValueError("Existing version stock mismatch")
            atomic_pointer(directory,digest)
            return dict(summary,action="stage",
                        outcome="verified_private_version_reactivated",
                        local_private_version_sha256=digest,
                        prior_version_exists=previous is not None)
        try:
            with target.open("x",encoding="utf-8") as fh:
                json.dump(version,fh,sort_keys=True,allow_nan=False,
                          ensure_ascii=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            atomic_pointer(directory,digest)
        except BaseException:
            # No active pointer update if write fails. The immutable
            # orphan may remain for manual inspection/recovery.
            raise
    return dict(summary,action="stage",outcome="new_private_overlay_version",
                local_private_version_sha256=digest,
                prior_version_exists=previous is not None)


def rollback(symbol,period,day):
    directory=private_dir(symbol,period,day)
    if not directory.is_dir():
        raise ValueError("No private overlay to rollback")
    with exclusive_lock(directory):
        current=read_pointer(directory)
        if current is None:
            raise ValueError("No active private overlay version")
        entry=read_version(directory,current)
        v=entry["record"]
        if v["symbol"]!=symbol or v["period"]!=period or v["date"]!=day:
            raise ValueError("Private version provenance mismatches scope")
        previous=entry["previous_version_sha256"]
        if previous is not None:
            old=read_version(directory,previous)
            if (old["record"]["symbol"]!=symbol or
                    old["record"]["period"]!=period or
                    old["record"]["date"]!=day):
                raise ValueError("Private rollback chain is cross-scoped")
            atomic_pointer(directory,previous)
        else:
            (directory/"active.json").unlink()
    return {
        "symbol":symbol,"date":day,"period":period,"action":"rollback",
        "outcome":"previous_version_restored" if previous else "active_overlay_disabled",
        "old_version_sha256":current,
        "active_version_sha256_after_rollback":previous,
        "immutable_private_versions_preserved":True,
    }


def out_path(value):
    p=Path(value)
    dest=(p if p.is_absolute() else MODULE/p).resolve()
    if (not REPORTS.is_relative_to(MODULE.resolve())
            or REPORTS.name!="reports"
            or (MODULE/"reports").is_symlink()
            or p.is_symlink() or not dest.is_relative_to(REPORTS)
            or dest.suffix.lower()!=".json" or dest.exists()):
        raise ValueError("Use a NEW JSON file within H5ParquetReconciler/reports")
    return dest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action",choices=("validate","stage","rollback"),required=True)
    parser.add_argument("--input",type=Path)
    parser.add_argument("--symbol")
    parser.add_argument("--date")
    parser.add_argument("--period")
    parser.add_argument("--allow-private-copy",action="store_true")
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        dest=out_path(args.out)
        if args.action in ("validate","stage"):
            if args.input is None:
                raise ValueError("--input required for validate/stage")
            if args.action=="stage" and not args.allow_private_copy:
                raise ValueError("Explicit --allow-private-copy required to stage paid bars")
            record,raw_sha=load_input(args.input)
            summary=validate(record)
            if args.action=="stage":
                summary=stage(record,raw_sha)
            else:
                summary=dict(summary,action="validate",outcome="validated_only")
        else:
            if args.input is not None or args.allow_private_copy:
                raise ValueError("rollback never reads source or accepts a copy flag")
            summary=rollback(args.symbol,args.period,args.date)
        result=dict(summary,
            "format":"AStockDataTools local TDX postclose overlay safe action summary v1",
            "raw_ohlcva_in_report":False,
            "source_market_files_modified":False,
            "original_parquet_or_h5_accessed":False,
            "production_query_automatically_changed":False,
            "private_data_only_under_gitignored_work":args.action=="stage",
            "source_timestamp_units_and_adjustment_unverified":True)
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open("x",encoding="utf-8") as fh:
            json.dump(result,fh,ensure_ascii=False,indent=2,allow_nan=False)
            fh.write("\n")
        print("Saved safe postclose overlay action:",dest)
        print("Action:",args.action,"outcome:",summary["outcome"])
        print("No automatic production union; licensed bars kept in local work only.")
    except (OSError,ValueError,TypeError,OverflowError,json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
