#!/usr/bin/env python3
"""Only read ORIGINAL purchased day Parquet file footers/schema metadata.

Report whether embedded metadata contain candidate *unit-description KEY
labels*, not their text VALUES. No market rows, private RAW, H5, per-stock,
timestamps, vendor strings, paths, source metadata values or raw schema
descriptions are emitted. An arbitrary metadata key is NEVER a trusted
independent vendor contract or physical-unit certificate.

Intended to decide whether to ask the vendor for a formal units/adjustment
data dictionary, before any unapproved historic normalization or H5 mirror.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools purchased all-day original Parquet footer-only vendor metadata presence v1"
MAX_TOTAL_ROW_GROUPS=50000
MAX_SOURCE_FILES=512
# These are candidate keyword labels, NOT trusted assertions or translations.
ROLE_LABELS={
    "unit": "generic_field_unit",
    "units": "generic_field_unit",
    "price_unit": "price_unit",
    "price_units": "price_unit",
    "volume_unit": "volume_unit",
    "volume_units": "volume_unit",
    "quantity_unit": "volume_unit",
    "amount_unit": "amount_unit",
    "amount_units": "amount_unit",
    "turnover_unit": "amount_unit",
    "adjustment": "adjustment_basis",
    "adjustment_basis": "adjustment_basis",
    "adjusted": "adjustment_basis",
    "price_adjustment": "adjustment_basis",
    "timestamp_unit": "timestamp_unit",
    "time_unit": "timestamp_unit",
    "time_zone": "timezone",
    "timezone": "timezone",
    "tz": "timezone",
    "data_version": "vendor_data_version",
    "schema_version": "vendor_data_version",
    "vendor_version": "vendor_data_version",
}
SAFE_ROLES=(
    "generic_field_unit","price_unit","volume_unit","amount_unit",
    "adjustment_basis","timestamp_unit","timezone","vendor_data_version",
)
# Filename/path/extra schema column names must never appear in output.
PUBLIC_FIELD_ROLES=(
    "ts","open","high","low","close","volume","amount","symbol","code",
)


def load(name,file):
    s=importlib.util.spec_from_file_location(name,HERE/file)
    m=importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


AUDIT=load("vendor_metadata_original_purchased_day_inventory",
           "inventory-pre2011-h5-parquet-day-readonly.py")


def metadata_roles(metadata):
    """Return finite canonical role NAMES only; never disclose values/keys."""
    if metadata is None:
        return set()
    if type(metadata) is not dict or len(metadata)>1024:
        raise ValueError("Unbounded Parquet field or table metadata map")
    roles=set()
    for key,value in metadata.items():
        if (type(key) is not bytes or type(value) is not bytes
                or len(key)>256 or len(value)>1048576):
            raise ValueError("Invalid or unbounded original Parquet metadata")
        try:
            name=key.decode("ascii").strip().lower()
        except UnicodeDecodeError:
            # Unknown metadata bytes are ignored, never printed.
            continue
        # A namespace-qualified key such as vendor.price_unit is accepted as
        # a *hint* only and cannot be interpreted as an attested vendor fact.
        suffix=re.split(r"[.:/]",name)[-1]
        if suffix in ROLE_LABELS:
            roles.add(ROLE_LABELS[suffix])
    return roles


def classify_fields(schema):
    """Allow field roles/types without exporting unexpected proprietary names."""
    present={role:0 for role in PUBLIC_FIELD_ROLES}
    role_types={role:Counter() for role in PUBLIC_FIELD_ROLES}
    field_hints=Counter()
    for field in schema:
        name=field.name.lower()
        if name in present:
            present[name]+=1
            kind=str(field.type)
            # Supported output is a finite, non-proprietary type vocabulary.
            kind=(kind if kind in ("double","float","int64","uint64","int32",
                                   "uint32","string","large_string",
                                   "timestamp[ms]","timestamp[us]") else "other")
            role_types[name][kind]+=1
            for role in metadata_roles(field.metadata):
                field_hints[role]+=1
        else:
            # Inspect key hints from unknown column without exporting its name.
            for role in metadata_roles(field.metadata):
                field_hints[role]+=1
    return present,role_types,field_hints


def output_target(out):
    p=Path(out)
    if (REPORTS.is_symlink() or not REPORTS.is_dir() or p.is_symlink()
            or p.exists() or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Only a brand-new directly module reports SAFE can be written")
    return p


def inspect(root,out):
    import pyarrow.parquet as pq
    p=Path(root)
    if not p.is_absolute() or p.is_symlink() or not p.is_dir() or p.resolve()!=p:
        raise ValueError("Purchased source root must be canonical absolute directory")
    target=output_target(out)
    folder,files=AUDIT.purchased_paths(p)
    if not files or len(files)>MAX_SOURCE_FILES:
        raise ValueError("No original day Parquet files or file budget exceeded")
    original={file:AUDIT.state(file) for file in files}
    files_processed=0
    row_groups=0
    records=0
    source_roles=Counter()
    types={name:Counter() for name in PUBLIC_FIELD_ROLES}
    field_hints=Counter()
    table_hints=Counter()
    inferred_schema=Counter()
    for source in files:
        pf=pq.ParquetFile(source,memory_map=False,pre_buffer=False)
        try:
            schema=pf.schema_arrow
            if "ts" not in schema.names:
                raise ValueError("Purchased Parquet day file has no ts field")
            present,role_types,hints=classify_fields(schema)
            if present["ts"]!=1:
                raise ValueError("Timestamp day field must occur exactly once")
            for name in PUBLIC_FIELD_ROLES:
                source_roles[name]+=int(present[name]>0)
                types[name].update(role_types[name])
            field_hints.update(hints)
            table_hints.update(metadata_roles(pf.metadata.metadata))
            inferred_schema[hashlib.sha256(
                schema.remove_metadata().serialize().to_pybytes()).hexdigest()]+=1
            row_groups+=pf.metadata.num_row_groups
            records+=pf.metadata.num_rows
            if row_groups>MAX_TOTAL_ROW_GROUPS or records>200000000:
                raise ValueError("Purchased Parquet footer budget exceeded")
            files_processed+=1
        finally:
            pf.close()
    if set(original)!=set(AUDIT.purchased_paths(p)[1]) or any(
            AUDIT.state(file)!=before for file,before in original.items()):
        raise ValueError("Original Parquet day file set or file stats changed mid-audit")
    result={
        "format":FORMAT,
        "status":"purchased_day_footer_metadata_presence_only_not_vendor_unit_attestation",
        "source_files_footer_only_read":files_processed,
        "row_groups_footer_only_scanned":row_groups,
        "total_footer_row_counts_not_row_data_read":records,
        "distinct_arrow_schemas":len(inferred_schema),
        "public_field_roles_present_file_count":{
            name:int(source_roles[name]) for name in PUBLIC_FIELD_ROLES},
        "public_field_roles_type_count":{
            name:dict(sorted(types[name].items())) for name in PUBLIC_FIELD_ROLES},
        "metadata_candidate_role_field_occurrences":{
            name:int(field_hints[name]) for name in SAFE_ROLES},
        "metadata_candidate_role_table_occurrences":{
            name:int(table_hints[name]) for name in SAFE_ROLES},
        "candidate_metadata_labels_are_not_authenticated_vendor_definitions":True,
        "parquet_footer_only_no_market_rows_read":True,
        "source_original_file_names_paths_or_metadata_values_exported":False,
        "purchased_day_file_set_and_stat_unchanged":True,
        "purchased_day_original_modified":False,
        "original_h5_private_raw_or_market_sqlite_accessed":False,
        "historical_physical_price_volume_amount_units_certified":False,
        "historical_adjustment_and_securities_certified":False,
        "source_vendor_data_dictionary_attached_and_verified":False,
        "ready_to_normalize_historical_raw_or_write_h5_mirror":False,
    }
    with target.open("x",encoding="utf-8") as fp:
        json.dump(result,fp,ensure_ascii=False,indent=2,sort_keys=True)
        fp.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-purchased-day-footer",
                   action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        result=inspect(args.root,args.out)
        print("Original purchased DAY Parquet footers inspected:",
              result["source_files_footer_only_read"])
        print("Original rows read: ZERO. Vendor unit certificate: NO.")
        print("SAFE:",args.out)
    except (ValueError,TypeError,KeyError,OSError,OverflowError,
            ImportError,ModuleNotFoundError,json.JSONDecodeError):
        p.error("Purchased day schema-metadata audit refused; no market file changed")


if __name__=="__main__":
    main()
