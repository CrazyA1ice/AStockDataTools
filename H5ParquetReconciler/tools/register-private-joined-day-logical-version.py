#!/usr/bin/env python3
"""Content-addressed PRIVATE logical day version referencing base+new-stock delta.

A version is a SHA-bound manifest of two existing, immutable, separately stored
Parquet partitions. Prepare reads and verifies both, but NEVER copies OHLCVA.
The optional activation/rollback pointer is completely separate from the
existing base-snapshot and H5-overlay pointers and from production routing.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
WORK=MODULE/"work"/"unified_parquet"
VERSIONS=WORK/"joined_day_versions"
ACTIVE=WORK/"active-private-joined-day.json"
LOCK=WORK/".private-joined-day.lock"
FORMAT="AStockDataTools private immutable parent+delta logical day version v1"
POINTER_FORMAT="AStockDataTools private joined day view pointer v1"
MAX_JSON=200000


def import_tool(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    tool=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


J=import_tool("joined_private_day_version_source",
              "read-private-day-snapshot-with-symbol-delta.py")
READER=J.READER


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,
                      separators=(",",":"),allow_nan=False).encode("utf-8")


def sha256_body(value):
    return sha256_bytes(canonical(value))


def valid_sha(value):
    return READER.require_sha(value)


def safe_paths():
    for p in (MODULE/"work",WORK,VERSIONS,ACTIVE,LOCK):
        if p.is_symlink():
            raise ValueError("Symlinked private logical version path denied")
    if not WORK.resolve().is_relative_to((MODULE/"work").resolve()):
        raise ValueError("Private version directory escaped module work/")


@contextmanager
def locked():
    safe_paths()
    WORK.mkdir(parents=True,exist_ok=True)
    try:
        fd=os.open(LOCK,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        raise ValueError("Private joined version pointer lock exists") from None
    try:
        os.close(fd)
        yield
    finally:
        LOCK.unlink(missing_ok=True)


def read_pointer():
    safe_paths()
    if not ACTIVE.exists():
        return None
    if (not ACTIVE.is_file() or not 0<ACTIVE.stat().st_size<=MAX_JSON):
        raise ValueError("Private joined pointer invalid")
    try:
        data=json.loads(ACTIVE.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError):
        raise ValueError("Invalid private joined pointer JSON") from None
    if (type(data) is not dict or set(data)!={"format","version_sha256"}
            or data.get("format")!=POINTER_FORMAT):
        raise ValueError("Private joined pointer format invalid")
    return valid_sha(data.get("version_sha256"))


def load_version(sha):
    valid_sha(sha)
    safe_paths()
    p=VERSIONS/(sha+".json")
    if (p.is_symlink() or not p.is_file()
            or not 0<p.stat().st_size<=MAX_JSON):
        raise ValueError("Private joined version file missing/unsafe")
    try:
        data=json.loads(p.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError):
        raise ValueError("Invalid private joined version JSON") from None
    if (type(data) is not dict or data.get("version_sha256")!=sha
            or data.get("format")!=FORMAT
            or data.get("status")!="prepared_private_joined_day_not_production"
            or data.get("original_market_files_modified") is not False
            or data.get("parent_or_delta_parquet_rewritten") is not False
            or data.get("production_query_route_modified") is not False
            or data.get("h5_gap_units_certified") is not False
            or data.get("ready_for_full_market_mirror") is not False):
        raise ValueError("Untrusted private joined version declaration")
    body={k:v for k,v in data.items() if k!="version_sha256"}
    if sha256_body(body)!=sha:
        raise ValueError("Private joined version content SHA differs")
    for k in ("parent_private_version_sha256","parent_version_file_sha256",
              "parent_parquet_sha256","parent_manifest_sha256",
              "parent_safe_sha256","delta_safe_sha256",
              "delta_parquet_sha256","delta_manifest_sha256",
              "source_overlay_version_sha256"):
        valid_sha(data.get(k))
    prev=data.get("previous_joined_version_sha256")
    if prev is not None:
        valid_sha(prev)
    name=data.get("delta_safe_basename")
    if (type(name) is not str
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}\.json",name)
            or name.startswith(".")
            or type(data.get("joined_rows")) is not int
            or not 2<=data["joined_rows"]<=7500
            or type(data.get("joined_stocks")) is not int
            or not 2<=data["joined_stocks"]<=10
            or any(type(data.get(k)) is not int or data[k]<0
                   for k in ("parent_rows","delta_rows","purchased_rows",
                             "h5_gap_candidate_rows"))
            or data["parent_rows"]+data["delta_rows"]!=data["joined_rows"]
            or data["purchased_rows"]+data["h5_gap_candidate_rows"]!=
                data["joined_rows"]):
        raise ValueError("Untrusted private joined version counts")
    if (type(data.get("date_window")) is not list
            or len(data["date_window"])!=2):
        raise ValueError("Invalid logical day interval")
    return data


def validate_pair(parent_sha,delta_safe_path):
    """Check both FULL Parquets, parent version lineage and SHAs twice.

    No delta/source file creation, no pointer, no live D:\\stock source reads.
    """
    valid_sha(parent_sha)
    parent,pfile_sha,psafe,psafe_sha,pmeta=J.ADD.trusted_parent(parent_sha)
    dsafe,dproof,dmeta_file,dpq=J.get_delta_safe(delta_safe_path,parent_sha)
    try:
        dmeta=json.loads(dmeta_file.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError):
        raise ValueError("Invalid private delta manifest JSON") from None
    effective=J.check_manifest(dsafe,dmeta,parent,pfile_sha,psafe,psafe_sha,pmeta)
    parent_safe=READER.REPORTS/parent["snapshot_safe_basename"]
    _,_,_,ppq=READER.source_snapshot(parent_safe)
    base_rows=J.decode(ppq,psafe["row_count"])
    delta_rows=J.decode(dpq,dsafe["added_rows"])
    READER.inspect_rows(base_rows,pmeta)
    READER.inspect_rows(delta_rows,effective)
    old_keys={(r["symbol"],r["trading_date"]) for r in base_rows}
    new_keys={(r["symbol"],r["trading_date"]) for r in delta_rows}
    if old_keys&new_keys:
        raise ValueError("Private parent/delta overlapping stock-day keys")
    # Full snapshot and delta source hash check AFTER decoding as well.
    p2,pfile2,ps2,psha2,meta2=J.ADD.trusted_parent(parent_sha)
    d2,dsha2,dm2,dp2=J.get_delta_safe(delta_safe_path,parent_sha)
    if (p2!=parent or pfile2!=pfile_sha or ps2!=psafe or psha2!=psafe_sha
            or meta2!=pmeta or d2!=dsafe or dsha2!=dproof
            or dm2!=dmeta_file or dp2!=dpq
            or READER.sha256_file(dmeta_file)!=dsafe["delta_manifest_sha256"]):
        raise ValueError("Private parent/delta source changed during logical verification")
    result={
        "parent_private_version_sha256":parent_sha,
        "parent_version_file_sha256":pfile_sha,
        "parent_parquet_sha256":psafe["private_parquet_sha256"],
        "parent_manifest_sha256":psafe["manifest_sha256"],
        "parent_safe_sha256":psafe_sha,
        "delta_safe_basename":READER.direct_report(delta_safe_path).name,
        "delta_safe_sha256":dproof,
        "delta_parquet_sha256":dsafe["delta_parquet_sha256"],
        "delta_manifest_sha256":dsafe["delta_manifest_sha256"],
        "source_overlay_version_sha256":parent["origin_private_version_sha256"],
        "date_window":list(pmeta["date_window"]),
        "parent_rows":len(base_rows),
        "delta_rows":len(delta_rows),
        "joined_rows":len(base_rows)+len(delta_rows),
        "joined_stocks":len(pmeta["per_symbol_counts"])+len(dmeta["new_symbols"]),
        "purchased_rows":(psafe["purchased_rows"]+dsafe["purchased_rows"]),
        "h5_gap_candidate_rows":(
            psafe["h5_gap_candidate_rows"]+dsafe["h5_gap_candidate_rows"]),
    }
    if (result["joined_rows"]>7500
            or result["purchased_rows"]+result["h5_gap_candidate_rows"]!=
                result["joined_rows"]):
        raise ValueError("Joined private row accounting invalid")
    return result


def check_version_files(entry):
    expected={k:entry[k] for k in (
        "parent_private_version_sha256","parent_version_file_sha256",
        "parent_parquet_sha256","parent_manifest_sha256","parent_safe_sha256",
        "delta_safe_basename","delta_safe_sha256","delta_parquet_sha256",
        "delta_manifest_sha256","source_overlay_version_sha256","date_window",
        "parent_rows","delta_rows","joined_rows","joined_stocks",
        "purchased_rows","h5_gap_candidate_rows")}
    current=validate_pair(
        entry["parent_private_version_sha256"],
        READER.REPORTS/entry["delta_safe_basename"])
    if current!=expected:
        raise ValueError("Registered logical version no longer matches original partitions")
    return current


def atomic_pointer(sha):
    temporary=WORK/".joined-day-pointer.tmp"
    if temporary.exists() or temporary.is_symlink() or ACTIVE.is_symlink():
        raise ValueError("Unsafe private logical pointer temporary path")
    try:
        if sha is None:
            ACTIVE.unlink(missing_ok=True)
            return
        with temporary.open("x",encoding="utf-8") as f:
            json.dump({"format":POINTER_FORMAT,"version_sha256":sha},f,
                      ensure_ascii=False,sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary,ACTIVE)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(parent_sha,delta_safe):
    proof=validate_pair(parent_sha,delta_safe)
    with locked():
        if validate_pair(parent_sha,delta_safe)!=proof:
            raise ValueError("Joined source changed before immutable registration")
        previous=read_pointer()
        if previous is not None:
            old=load_version(previous)
            check_version_files(old)
        body={
            "format":FORMAT,
            "status":"prepared_private_joined_day_not_production",
            **proof,
            "previous_joined_version_sha256":previous,
            "original_market_files_modified":False,
            "parent_or_delta_parquet_rewritten":False,
            "production_query_route_modified":False,
            "h5_gap_units_certified":False,
            "ready_for_full_market_mirror":False,
        }
        sha=sha256_body(body)
        item={**body,"version_sha256":sha}
        VERSIONS.mkdir(parents=True,exist_ok=True)
        file=VERSIONS/(sha+".json")
        if file.exists():
            if load_version(sha)!=item:
                raise ValueError("Existing private logical version conflict")
        else:
            with file.open("x",encoding="utf-8") as f:
                json.dump(item,f,ensure_ascii=False,sort_keys=True,indent=2)
                f.write("\n")
    return {
        "status":body["status"],"version_sha256":sha,
        "previous_joined_version_sha256":previous,
        "joined_rows":proof["joined_rows"],
        "joined_stocks":proof["joined_stocks"],
        "purchased_rows":proof["purchased_rows"],
        "h5_gap_candidate_rows":proof["h5_gap_candidate_rows"],
        "private_joined_pointer_changed":False,
        "production_query_route_modified":False,
    }


def activate(sha):
    valid_sha(sha)
    with locked():
        entry=load_version(sha)
        if entry["previous_joined_version_sha256"]!=read_pointer():
            raise ValueError("Joined pointer advanced after version was prepared")
        check_version_files(entry)
        atomic_pointer(sha)
    return {"status":"private_joined_pointer_activated",
            "version_sha256":sha,"production_query_route_modified":False}


def rollback():
    with locked():
        existing=read_pointer()
        if existing is None:
            raise ValueError("No active private joined pointer")
        record=load_version(existing)
        prior=record["previous_joined_version_sha256"]
        if prior is not None:
            check_version_files(load_version(prior))
        atomic_pointer(prior)
    return {"status":"private_joined_pointer_restored_or_disabled",
            "previous_active_version_sha256":existing,
            "restored_version_sha256":prior,
            "old_partitions_preserved":True,
            "production_query_route_modified":False}


def status():
    if LOCK.exists() or LOCK.is_symlink():
        raise ValueError("Private joined pointer update in progress")
    sha=read_pointer()
    entry=load_version(sha) if sha is not None else None
    if entry is not None:
        check_version_files(entry)
    if LOCK.exists() or LOCK.is_symlink() or read_pointer()!=sha:
        raise ValueError("Joined pointer changed during status")
    return {"status":"private_joined_pointer_status",
            "active_joined_version_sha256":sha,
            "active_joined_rows":entry["joined_rows"] if entry else 0,
            "active_joined_stocks":entry["joined_stocks"] if entry else 0,
            "original_market_files_accessed":False,
            "production_query_route_modified":False}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--action",choices=("prepare","status","activate","rollback"),
                   required=True)
    p.add_argument("--parent-version")
    p.add_argument("--delta-safe",type=Path)
    p.add_argument("--version")
    p.add_argument("--confirm-private-joined-pointer",action="store_true")
    a=p.parse_args(argv)
    try:
        if a.action=="prepare":
            if (not a.parent_version or not a.delta_safe
                    or a.version or a.confirm_private_joined_pointer):
                raise ValueError("Prepare needs only --parent-version and --delta-safe")
            result=prepare(a.parent_version,a.delta_safe)
        elif a.action=="activate":
            if (not a.version or not a.confirm_private_joined_pointer
                    or a.parent_version or a.delta_safe):
                raise ValueError("Activation requires version and explicit confirmation")
            result=activate(a.version)
        elif a.action=="rollback":
            if (not a.confirm_private_joined_pointer
                    or a.parent_version or a.delta_safe or a.version):
                raise ValueError("Rollback requires explicit confirmation only")
            result=rollback()
        else:
            if (a.parent_version or a.delta_safe or a.version
                    or a.confirm_private_joined_pointer):
                raise ValueError("Status accepts no additional parameters")
            result=status()
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        print("PRIVATE joined pointer only; NO source market/production data writes.")
    except (OSError,ValueError,TypeError,KeyError,OverflowError,
            ImportError,ModuleNotFoundError):
        p.error("Private logical day version refused; original market untouched")


if __name__=="__main__":
    main()
