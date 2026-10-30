#!/usr/bin/env python3
"""Content-addressed version and explicit rollback of PRIVATE day snapshots.

A private pointer is NOT a production query route. Registration only creates
immutable module-private metadata; activation and rollback require explicit
confirmation. No source market file is opened, copied or modified.
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
SPEC=importlib.util.spec_from_file_location(
    "snapshot_verified_reader_for_version",
    HERE/"read-private-unified-day-parquet-snapshot.py")
READER=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)

MODULE=HERE.parent.resolve()
WORK=MODULE/"work"/"unified_parquet"
VERSIONS=WORK/"snapshot_versions"
ACTIVE=WORK/"active-private-snapshot.json"
LOCK=WORK/".private-snapshot-version.lock"
VERSION_FORMAT="AStockDataTools private Parquet daily snapshot version v1"
POINTER_FORMAT="AStockDataTools private Parquet daily snapshot pointer v1"
MAX_VERSION_BYTES=200000


def canonical(doc):
    return json.dumps(doc,sort_keys=True,separators=(",",":"),
                      ensure_ascii=False,allow_nan=False).encode("utf-8")


def digest(doc):
    return hashlib.sha256(canonical(doc)).hexdigest()


def safe_private():
    if (MODULE.joinpath("work").is_symlink()
            or WORK.is_symlink() or VERSIONS.is_symlink()
            or ACTIVE.is_symlink() or LOCK.is_symlink()
            or not WORK.resolve().is_relative_to(MODULE/"work")):
        raise ValueError("Unsafe private version directory or pointer symlink")


@contextmanager
def locked():
    safe_private()
    WORK.mkdir(parents=True,exist_ok=True)
    try:
        fd=os.open(str(LOCK),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        raise ValueError("Private snapshot version lock already exists") from None
    try:
        os.close(fd)
        yield
    finally:
        LOCK.unlink(missing_ok=True)


def read_pointer():
    safe_private()
    if not ACTIVE.exists():
        return None
    if not ACTIVE.is_file() or ACTIVE.stat().st_size>MAX_VERSION_BYTES:
        raise ValueError("Unsafe private snapshot active pointer")
    try:
        info=json.loads(ACTIVE.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError):
        raise ValueError("Invalid private snapshot pointer") from None
    if (type(info) is not dict or set(info)!={"format","version_sha256"}
            or info["format"]!=POINTER_FORMAT):
        raise ValueError("Invalid private snapshot pointer")
    return READER.require_sha(info["version_sha256"])


def load_version(version):
    READER.require_sha(version)
    safe_private()
    p=VERSIONS/(version+".json")
    if (p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<=MAX_VERSION_BYTES):
        raise ValueError("Private snapshot version is absent or unsafe")
    try:
        doc=json.loads(p.read_text(encoding="utf-8"))
    except (ValueError,UnicodeError):
        raise ValueError("Malformed private snapshot version") from None
    if (type(doc) is not dict or doc.get("version_sha256")!=version
            or doc.get("format")!=VERSION_FORMAT
            or doc.get("status")!="prepared_private_snapshot_not_production"
            or doc.get("private_original_market_files_modified") is not False
            or doc.get("production_query_route_modified") is not False
            or doc.get("h5_gap_amount_units_certified") is not False
            or doc.get("ready_for_full_market_mirror") is not False):
        raise ValueError("Unsafe private snapshot version claims")
    body={k:v for k,v in doc.items() if k!="version_sha256"}
    if digest(body)!=version:
        raise ValueError("Private snapshot version content hash mismatch")
    prev=doc.get("previous_version_sha256")
    if prev is not None:
        READER.require_sha(prev)
    for key in ("snapshot_safe_sha256","private_parquet_sha256",
                "manifest_sha256","origin_private_version_sha256"):
        READER.require_sha(doc.get(key))
    if (type(doc.get("snapshot_safe_basename")) is not str
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}\.json",
                                doc["snapshot_safe_basename"])
            or type(doc.get("rows")) is not int or not 1<=doc["rows"]<=5000
            or type(doc.get("purchased_rows")) is not int
            or type(doc.get("h5_gap_candidate_rows")) is not int
            or doc["purchased_rows"]+doc["h5_gap_candidate_rows"]!=doc["rows"]):
        raise ValueError("Malformed private snapshot version row metadata")
    return doc


def verify_snapshot(snapshot_safe):
    """Fully verify existing private snapshot before binding its version.

    Runs no source-data freshness check. Does not save any selected bars.
    """
    safe,source_sha,manifest_path,pq_path=READER.source_snapshot(snapshot_safe)
    doc=READER.verified_manifest(manifest_path,safe)
    import pyarrow as pa
    import pyarrow.parquet as pq
    pf=None
    try:
        pf=pq.ParquetFile(pq_path,memory_map=False,pre_buffer=False)
        schema=READER.expected_schema(pa)
        if (pf.schema_arrow!=schema
                or pf.metadata.num_row_groups<1
                or pf.metadata.num_row_groups>32
                or pf.metadata.num_rows!=safe["row_count"]):
            raise ValueError("Private snapshot schema/footer invalid")
        table=pf.read(columns=schema.names,use_threads=False)
        if table.schema!=schema or table.num_rows!=safe["row_count"]:
            raise ValueError("Private snapshot decoded schema mismatch")
        READER.inspect_rows(table.to_pylist(),doc)
    except Exception:
        raise ValueError("Unverified private snapshot data; registration denied") from None
    finally:
        if pf is not None:
            pf.close()
    check,after_sha,m2,p2=READER.source_snapshot(snapshot_safe)
    if (check!=safe or source_sha!=after_sha
            or m2!=manifest_path or p2!=pq_path):
        raise ValueError("Snapshot or original SAFE changed during verification")
    # Pin proof after full verification; no data values leave private memory.
    return safe,source_sha


def atomic_pointer(version):
    tmp=WORK/".active-private-snapshot.tmp"
    if tmp.exists() or tmp.is_symlink() or ACTIVE.is_symlink():
        raise ValueError("Unsafe/stale private snapshot pointer temp")
    try:
        if version is None:
            ACTIVE.unlink(missing_ok=True)
            return
        with tmp.open("x",encoding="utf-8") as stream:
            json.dump({"format":POINTER_FORMAT,"version_sha256":version},
                      stream,sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp,ACTIVE)
    finally:
        tmp.unlink(missing_ok=True)


def prepare(snapshot_safe):
    # Inspect sources BEFORE acquiring private pointer lock; under the lock,
    # repeat the hash checks to detect replaced snapshot and stale base.
    safe,proof_sha=verify_snapshot(snapshot_safe)
    p=READER.direct_report(snapshot_safe)
    with locked():
        latest,again_sha=verify_snapshot(p)
        if again_sha!=proof_sha or latest!=safe:
            raise ValueError("Source snapshot changed before registration")
        previous=read_pointer()
        if previous is not None:
            load_version(previous)
        body={
            "format":VERSION_FORMAT,
            "status":"prepared_private_snapshot_not_production",
            "snapshot_safe_basename":p.name,
            "snapshot_safe_sha256":proof_sha,
            "private_parquet_sha256":safe["private_parquet_sha256"],
            "manifest_sha256":safe["manifest_sha256"],
            "origin_private_version_sha256":safe["origin_private_version_sha256"],
            "rows":safe["row_count"],
            "purchased_rows":safe["purchased_rows"],
            "h5_gap_candidate_rows":safe["h5_gap_candidate_rows"],
            "previous_version_sha256":previous,
            "private_original_market_files_modified":False,
            "production_query_route_modified":False,
            "h5_gap_amount_units_certified":False,
            "ready_for_full_market_mirror":False,
        }
        version=digest(body)
        entry={**body,"version_sha256":version}
        VERSIONS.mkdir(parents=True,exist_ok=True)
        output=VERSIONS/(version+".json")
        if output.exists():
            if load_version(version)!=entry:
                raise ValueError("Existing private snapshot version conflicts")
        else:
            with output.open("x",encoding="utf-8") as stream:
                json.dump(entry,stream,sort_keys=True,ensure_ascii=False,indent=2)
                stream.write("\n")
    return {
        "status":body["status"],
        "version_sha256":version,
        "previous_version_sha256":previous,
        "rows":safe["row_count"],
        "private_snapshot_pointer_changed":False,
        "production_query_route_modified":False,
    }


def check_version_snapshot(entry):
    safe_path=READER.REPORTS/entry["snapshot_safe_basename"]
    safe,proof_sha=verify_snapshot(safe_path)
    if (proof_sha!=entry["snapshot_safe_sha256"]
            or safe["private_parquet_sha256"]!=entry["private_parquet_sha256"]
            or safe["manifest_sha256"]!=entry["manifest_sha256"]
            or safe["origin_private_version_sha256"]!=entry["origin_private_version_sha256"]
            or safe["row_count"]!=entry["rows"]
            or safe["purchased_rows"]!=entry["purchased_rows"]
            or safe["h5_gap_candidate_rows"]!=entry["h5_gap_candidate_rows"]):
        raise ValueError("Private snapshot version no longer matches immutable file")
    return True


def activate(version):
    READER.require_sha(version)
    with locked():
        entry=load_version(version)
        if entry["previous_version_sha256"]!=read_pointer():
            raise ValueError("Private pointer advanced since snapshot was prepared")
        check_version_snapshot(entry)
        atomic_pointer(version)
    return {"status":"private_snapshot_pointer_activated",
            "version_sha256":version,
            "production_query_route_modified":False,
            "original_market_files_modified":False}


def rollback():
    with locked():
        old=read_pointer()
        if old is None:
            raise ValueError("No private snapshot pointer to rollback")
        record=load_version(old)
        previous=record["previous_version_sha256"]
        if previous is not None:
            parent=load_version(previous)
            check_version_snapshot(parent)
        atomic_pointer(previous)
    return {"status":"private_snapshot_pointer_restored_or_disabled",
            "previous_active_version_sha256":old,
            "restored_version_sha256":previous,
            "snapshot_files_preserved":True,
            "production_query_route_modified":False}


def status():
    if LOCK.exists() or LOCK.is_symlink():
        raise ValueError("Private snapshot pointer update in progress")
    current=read_pointer()
    entry=load_version(current) if current else None
    if entry is not None:
        check_version_snapshot(entry)
    if LOCK.exists() or LOCK.is_symlink() or read_pointer()!=current:
        raise ValueError("Private snapshot pointer changed during status read")
    return {"status":"private_snapshot_pointer_status",
            "active_version_sha256":current,
            "verified_active_snapshot_rows":entry["rows"] if entry else 0,
            "original_market_files_accessed":False,
            "production_query_route_modified":False}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--action",choices=("prepare","activate","rollback","status"),
                   required=True)
    p.add_argument("--snapshot-safe",type=Path)
    p.add_argument("--version")
    p.add_argument("--confirm-private-pointer",action="store_true")
    a=p.parse_args(argv)
    try:
        if a.action=="prepare":
            if a.version or a.confirm_private_pointer or not a.snapshot_safe:
                raise ValueError("Prepare takes only --snapshot-safe")
            result=prepare(a.snapshot_safe)
        elif a.action=="activate":
            if a.snapshot_safe or not a.version or not a.confirm_private_pointer:
                raise ValueError("Activation requires --version and --confirm-private-pointer")
            result=activate(a.version)
        elif a.action=="rollback":
            if a.snapshot_safe or a.version or not a.confirm_private_pointer:
                raise ValueError("Rollback requires only --confirm-private-pointer")
            result=rollback()
        else:
            if a.snapshot_safe or a.version or a.confirm_private_pointer:
                raise ValueError("Status does not accept extra options")
            result=status()
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        print("Private pointer ONLY; no purchased Parquet/H5 or production writes.")
    except (ValueError,KeyError,TypeError,OSError,OverflowError,
            ImportError,ModuleNotFoundError,json.JSONDecodeError):
        p.error("Private snapshot version action rejected; original data unchanged")


if __name__=="__main__":
    main()
