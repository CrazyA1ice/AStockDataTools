#!/usr/bin/env python3
"""Bounded read-only original QDC purchased daily Parquet bundle integrity gate.

Verifies all 24 original daily Parquet files against the separately pinned
bundle manifest's byte sizes, row counts and full SHA256, without decoding
any trading row. Optionally links the previously untrusted source-section
inventory SAFE. Vendor's README is part of the received bundle, NOT an
independent publisher signature or conversion license.

Do NOT use this as approval to normalize pre-2011 H5 or to write an H5 mirror.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools QDC original purchased DAY manifest file integrity v1"
INTAKE_FORMAT="AStockDataTools purchased-day vendor semantics private evidence inventory v1"
DAY_TOTAL_ROWS=14115707
EXPECTED_NAMES={f"{year}.parquet" for year in range(2011,2026)} | {
    f"2026-{month:02d}.parquet" for month in range(1,10)}
REQUIRED_DOCUMENTED={
    "price_currency_and_unit","price_adjustment_policy_and_basis",
    "volume_physical_unit","amount_physical_unit_and_currency",
    "timestamp_epoch_unit","timestamp_timezone","timestamp_bar_label",
}
REQUIRED_UNKNOWN={
    "price_precision_and_tick","amount_decimal_precision",
    "amount_rounding_and_null_policy",
    "symbol_market_security_type_and_reuse",
    "historical_version_and_rule_changes",
    "covered_product_batch_and_data_period",
}
HEX64=re.compile(r"[0-9a-fA-F]{64}\Z")
MAX_MANIFEST_BYTES=128*1024
MAX_README_BYTES=128*1024
MAX_SAFE_BYTES=256*1024


def pinned_hash(value):
    if type(value) is not str or HEX64.fullmatch(value) is None:
        raise ValueError("Expected 64-character SHA256 evidence pin")
    return value.lower()


def file_state(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Input original file missing or linked")
    info=path.stat()
    return (info.st_size,info.st_mtime_ns,info.st_dev,info.st_ino)


def digest_file(path,limit=None):
    before=file_state(path)
    if before[0]<1 or limit is not None and before[0]>limit:
        raise ValueError("Source evidence size budget exceeded")
    sha=hashlib.sha256()
    with path.open("rb") as file:
        while True:
            block=file.read(1024*1024)
            if not block:
                break
            sha.update(block)
    if file_state(path)!=before:
        raise ValueError("Original source changed during hash computation")
    return sha.hexdigest()


def parse_manifest(data):
    if type(data) is not bytes or not 0<len(data)<=MAX_MANIFEST_BYTES:
        raise ValueError("Invalid QDC manifest byte budget")
    try:
        lines=data.decode("utf-8-sig").splitlines()
    except UnicodeError:
        raise ValueError("QDC manifest is not UTF-8") from None
    records={}
    for line in lines:
        fields=line.split()
        if not fields or fields[0]!="日线":
            continue
        if len(fields)!=7:
            raise ValueError("Malformed daily record in QDC manifest")
        folder,name,byte_size,rows,first,last,sha=fields
        if (folder!="日线" or name not in EXPECTED_NAMES or name in records
                or not byte_size.isascii() or not byte_size.isdecimal()
                or not rows.isascii() or not rows.isdecimal()
                or not HEX64.fullmatch(sha)):
            raise ValueError("Unexpected, duplicate or invalid QDC daily record")
        size=int(byte_size)
        count=int(rows)
        if not 0<size<1024*1024*1024 or not 0<count<100000000:
            raise ValueError("Daily file or row budget invalid")
        try:
            begin=date.fromisoformat(first)
            finish=date.fromisoformat(last)
        except ValueError:
            raise ValueError("Invalid daily filename date range") from None
        if begin>finish:
            raise ValueError("Inverted manifest trading date")
        if name[:4]=="2026":
            year,month=2026,int(name[5:7])
            if (begin.year,begin.month)!=(year,month) or (
                    finish.year,finish.month)!=(year,month):
                raise ValueError("2026 monthly day manifest date range invalid")
        else:
            year=int(name[:4])
            if begin.year!=year or finish.year!=year:
                raise ValueError("Annual day manifest date range invalid")
        records[name]={"size":size,"rows":count,"sha":sha.lower()}
    if set(records)!=EXPECTED_NAMES:
        raise ValueError("QDC 24 purchased day files missing or unexpected")
    if sum(d["rows"] for d in records.values())!=DAY_TOTAL_ROWS:
        raise ValueError("QDC day manifest totals not expected 14,115,707")
    return records


def existing_intake_safe(safe,expected_readme):
    if safe is None:
        return None
    safe=Path(safe)
    if (safe.is_symlink() or not safe.is_file() or REPORTS.is_symlink()
            or safe.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Vendor intake SAFE must be in module reports")
    before=file_state(safe)
    if not 0<before[0]<=MAX_SAFE_BYTES:
        raise ValueError("Oversized vendor intake SAFE")
    raw=safe.read_bytes()
    if before!=file_state(safe):
        raise ValueError("Vendor SAFE changed")
    obj=json.loads(raw)
    if (type(obj) is not dict or obj.get("format")!=INTAKE_FORMAT
            or obj.get("status")!="vendor_statement_locations_recorded_not_authenticated"
            or obj.get("private_vendor_document_supplied") is not True
            or obj.get("private_vendor_document_sha256")!=expected_readme
            or type(obj.get("documented_source_section_role_names_only")) is not list
            or set(obj["documented_source_section_role_names_only"])!=REQUIRED_DOCUMENTED
            or len(obj["documented_source_section_role_names_only"])!=7
            or type(obj.get("undocumented_required_role_names")) is not list
            or set(obj["undocumented_required_role_names"])!=REQUIRED_UNKNOWN
            or len(obj["undocumented_required_role_names"])!=6
            or obj.get("required_semantic_roles_total")!=13
            or any(obj.get(k) is not False for k in (
                "independent_document_authenticity_checked",
                "document_claims_independently_verified",
                "purchased_vendor_physical_units_certified",
                "historical_normalized_parquet_authorized",
                "hikyuu_h5_mirror_authorized",
                "original_purchased_parquet_or_h5_accessed",
                "production_or_active_pointer_modified"))):
        raise ValueError("Vendor intake SAFE has incompatible or fabricated claims")
    return hashlib.sha256(raw).hexdigest()


def out_path(path):
    path=Path(path)
    if (REPORTS.is_symlink() or not REPORTS.is_dir()
            or path.exists() or path.is_symlink()
            or path.suffix.lower()!=".json"
            or path.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Output must be a NEW direct module reports JSON")
    return path


def inspect(source_root,readme_sha,manifest_sha,out,intake_safe=None):
    import pyarrow.parquet as pq
    root=Path(source_root)
    target=out_path(out)
    if (not root.is_absolute() or not root.is_dir()
            or root.is_symlink() or root.resolve()!=root):
        raise ValueError("Original QDC root must be canonical absolute folder")
    folder=root/"day"
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Purchased original day directory missing/linked")
    doc=root/"【先看我】数据说明.txt"
    manifest=root/"文件校验清单.txt"
    before_doc=file_state(doc)
    before_manifest=file_state(manifest)
    wanted_readme=pinned_hash(readme_sha)
    wanted_manifest=pinned_hash(manifest_sha)
    if digest_file(doc,MAX_README_BYTES)!=wanted_readme:
        raise ValueError("QDC readme SHA mismatch")
    if digest_file(manifest,MAX_MANIFEST_BYTES)!=wanted_manifest:
        raise ValueError("QDC manifest SHA mismatch")
    raw=manifest.read_bytes()
    if file_state(manifest)!=before_manifest:
        raise ValueError("Original manifest changed")
    records=parse_manifest(raw)
    note_sha=existing_intake_safe(intake_safe,wanted_readme)
    discovered={}
    for child in folder.iterdir():
        if child.is_symlink() or child.is_dir():
            raise ValueError("Unexpected linked or nested purchased day item")
        if child.suffix.lower()==".parquet":
            if child.name in discovered:
                raise ValueError("Duplicate purchased day file")
            discovered[child.name]=child
    if set(discovered)!=EXPECTED_NAMES:
        raise ValueError("Original purchased day file inventory differs from QDC manifest")
    before={name:file_state(path) for name,path in discovered.items()}
    verified_rows=0
    verified_bytes=0
    for name in sorted(EXPECTED_NAMES):
        file=discovered[name]
        expected=records[name]
        if before[name][0]!=expected["size"]:
            raise ValueError("Purchased day Parquet size differs from manifest")
        pf=pq.ParquetFile(file,memory_map=False,pre_buffer=False)
        try:
            actual=int(pf.metadata.num_rows)
        finally:
            pf.close()
        if actual!=expected["rows"]:
            raise ValueError("Purchased day Parquet row count differs from manifest")
        if digest_file(file)!=expected["sha"]:
            raise ValueError("Purchased day Parquet SHA differs from manifest")
        if file_state(file)!=before[name]:
            raise ValueError("Purchased day Parquet changed during footer scan")
        verified_rows+=actual
        verified_bytes+=expected["size"]
    if (set(child.name for child in folder.iterdir()
            if child.suffix.lower()==".parquet")!=EXPECTED_NAMES
            or any(file_state(discovered[name])!=state
                   for name,state in before.items())
            or file_state(doc)!=before_doc
            or file_state(manifest)!=before_manifest
            or digest_file(doc,MAX_README_BYTES)!=wanted_readme
            or digest_file(manifest,MAX_MANIFEST_BYTES)!=wanted_manifest):
        raise ValueError("Original QDC bundle source changed mid-verification")
    result={
        "format":FORMAT,
        "status":"all_24_purchased_day_originals_match_received_bundle_manifest_not_vendor_certification",
        "readme_original_sha256":wanted_readme,
        "manifest_original_sha256":wanted_manifest,
        "vendor_intake_safe_sha256":note_sha,
        "vendor_intake_seven_documented_six_unknown_linked":note_sha is not None,
        "purchased_day_file_count_verified":len(records),
        "purchased_day_row_count_verified":verified_rows,
        "purchased_day_total_original_bytes_verified":verified_bytes,
        "file_sizes_all_match_received_manifest":True,
        "parquet_footer_row_counts_all_match_received_manifest":True,
        "all_original_day_file_full_sha256_match_received_manifest":True,
        "readme_manifest_and_original_files_unchanged":True,
        "parquet_market_rows_decoded":False,
        "manifest_declared_start_end_dates_checked_against_market_rows":False,
        "market_source_h5_or_purchased_parquet_modified":False,
        "private_raw_or_active_pointer_modified":False,
        "source_vendor_publication_independently_authenticated":False,
        "amount_precision_or_rounding_rule_certified":False,
        "pre2011_h5_physical_units_and_securities_certified":False,
        "historical_normalized_parquet_authorized":False,
        "hikyuu_h5_mirror_authorized":False,
        "production_market_data_write_authorized":False,
    }
    with target.open("x",encoding="utf-8") as stream:
        json.dump(result,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,required=True)
    parser.add_argument("--readme-sha256",required=True)
    parser.add_argument("--manifest-sha256",required=True)
    parser.add_argument("--vendor-intake-safe",type=Path)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--read-only-all-original-purchased-day",
                        action="store_true",required=True)
    a=parser.parse_args(argv)
    try:
        info=inspect(a.source_root,a.readme_sha256,a.manifest_sha256,
                     a.out,a.vendor_intake_safe)
        print("Purchased original DAY bundle SHA matches:",
              info["purchased_day_file_count_verified"],"files")
        print("Footer records:",info["purchased_day_row_count_verified"])
        print("Vendor authenticity/amount rounding/H5 mirror: NOT CERTIFIED")
        print("SAFE:",a.out)
    except (ValueError,TypeError,KeyError,OSError,OverflowError,
            ImportError,ModuleNotFoundError,json.JSONDecodeError):
        parser.error("QDC source day integrity verification refused; no writes")


if __name__=="__main__":
    main()
