#!/usr/bin/env python3
"""Offline vendor-field-semantics evidence inventory; NEVER a unit certificate.

PLAN reads only an existing, verified purchased-day Parquet footer SAFE.
INTAKE additionally hashes a private vendor document and structured source
section locators. The document is NOT automatically trusted, independently
reviewed or promoted to a market-data conversion authorization.

All files live under H5ParquetReconciler; no H5 or Parquet market data read.
No source document text, product/vendor identifiers, section locators,
original proprietary metadata values or unit claims enter the SAFE report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
REPORTS=MODULE/"reports"
EVIDENCE=MODULE/"work"/"vendor_semantics"
FORMAT="AStockDataTools purchased-day vendor semantics private evidence inventory v1"
FOOTER_FORMAT=("AStockDataTools purchased all-day original Parquet "
               "footer-only vendor metadata presence v1")
ROLES=(
    "price_currency_and_unit",
    "price_precision_and_tick",
    "price_adjustment_policy_and_basis",
    "volume_physical_unit",
    "amount_physical_unit_and_currency",
    "amount_decimal_precision",
    "amount_rounding_and_null_policy",
    "timestamp_epoch_unit",
    "timestamp_timezone",
    "timestamp_bar_label",
    "symbol_market_security_type_and_reuse",
    "historical_version_and_rule_changes",
    "covered_product_batch_and_data_period",
)
KNOWN_METADATA_ROLES=(
    "generic_field_unit","price_unit","volume_unit","amount_unit",
    "adjustment_basis","timestamp_unit","timezone","vendor_data_version",
)
MAX_DOC_BYTES=50*1024*1024


def sha256(path,limit):
    size=path.stat().st_size
    if not 0<size<=limit:
        raise ValueError("Source evidence exceeds safe size budget")
    h=hashlib.sha256()
    with path.open("rb") as f:
        total=0
        while True:
            b=f.read(1024*1024)
            if not b:
                break
            total+=len(b)
            if total>limit:
                raise ValueError("Source evidence changed beyond size budget")
            h.update(b)
    if total!=size:
        raise ValueError("Source evidence length changed during digest")
    return h.hexdigest()


def confined_file(file,base,max_size):
    base=Path(base)
    file=Path(file)
    if (not file.is_file() or file.is_symlink() or base.is_symlink()
            or not base.is_dir() or file.resolve().parent!=base.resolve()
            or any(p.is_symlink() for p in (
                MODULE/"work",EVIDENCE,base,file))):
        raise ValueError("Evidence file must be a real direct child of private module directory")
    if file.stat().st_size>max_size or file.stat().st_size<=0:
        raise ValueError("Evidence file size budget invalid")
    return file


def read_footer_safe(file):
    file=confined_file(file,REPORTS,200000)
    original=file.read_bytes()
    obj=json.loads(original)
    if (type(obj) is not dict or obj.get("format")!=FOOTER_FORMAT
            or obj.get("status")!="purchased_day_footer_metadata_presence_only_not_vendor_unit_attestation"
            or type(obj.get("source_files_footer_only_read")) is not int
            or obj["source_files_footer_only_read"]<=0
            or type(obj.get("row_groups_footer_only_scanned")) is not int
            or obj["row_groups_footer_only_scanned"]<=0
            or obj.get("parquet_footer_only_no_market_rows_read") is not True
            or obj.get("purchased_day_file_set_and_stat_unchanged") is not True
            or obj.get("purchased_day_original_modified") is not False
            or obj.get("source_vendor_data_dictionary_attached_and_verified") is not False
            or obj.get("historical_physical_price_volume_amount_units_certified") is not False
            or obj.get("historical_adjustment_and_securities_certified") is not False
            or obj.get("ready_to_normalize_historical_raw_or_write_h5_mirror") is not False
            or type(obj.get("metadata_candidate_role_field_occurrences")) is not dict
            or type(obj.get("metadata_candidate_role_table_occurrences")) is not dict):
        raise ValueError("Prior footer SAFE is not a valid uncertified purchased source")
    for level in ("metadata_candidate_role_field_occurrences",
                  "metadata_candidate_role_table_occurrences"):
        if set(obj[level])!=set(KNOWN_METADATA_ROLES) or any(
                type(obj[level][k]) is not int or obj[level][k]<0
                for k in KNOWN_METADATA_ROLES):
            raise ValueError("Prior footer SAFE role count structure invalid")
    return obj,hashlib.sha256(original).hexdigest()


def private_document(filename):
    if (type(filename) is not str or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.(?:pdf|txt|md|html)",filename)):
        raise ValueError("Vendor document must use a safe private filename")
    return confined_file(EVIDENCE/filename,EVIDENCE,MAX_DOC_BYTES)


def read_notes(file):
    file=confined_file(file,EVIDENCE,64000)
    raw=file.read_bytes()
    n=json.loads(raw)
    if (type(n) is not dict
            or set(n)!={"format","document_filename","document_sha256",
                        "product_version_reference","purchase_batch_reference",
                        "role_loci"}
            or n["format"]!="private_vendor_semantics_source_loci_v1"
            or type(n["document_sha256"]) is not str
            or not re.fullmatch(r"[a-f0-9]{64}",n["document_sha256"])
            or any(type(n[k]) is not str or not 1<=len(n[k])<=160
                   for k in ("product_version_reference",
                             "purchase_batch_reference"))
            or type(n["role_loci"]) is not dict
            or set(n["role_loci"])!=set(ROLES)):
        raise ValueError("Private vendor source notes format invalid")
    for k,v in n["role_loci"].items():
        if (type(v) is not dict or set(v)!={"status","section_locator"}
                or v["status"] not in ("documented","unknown")
                or type(v["section_locator"]) is not str
                or len(v["section_locator"])>160
                or (v["status"]=="documented" and not v["section_locator"].strip())
                or (v["status"]=="unknown" and v["section_locator"]!="")):
            raise ValueError("Vendor evidence locus requires actual section or unknown")
    doc=private_document(n["document_filename"])
    doc_hash=sha256(doc,MAX_DOC_BYTES)
    if doc_hash!=n["document_sha256"]:
        raise ValueError("Private vendor document SHA does not match source notes")
    # A self-reported section locator never verifies text contents or
    # authenticates who provided the document.
    present=[k for k in ROLES if n["role_loci"][k]["status"]=="documented"]
    return {
        "private_doc_sha256":doc_hash,
        "private_notes_sha256":hashlib.sha256(raw).hexdigest(),
        "documented_role_names_only":present,
    }


def target_safe(out):
    out=Path(out)
    if (not REPORTS.is_dir() or REPORTS.is_symlink()
            or out.is_symlink() or out.exists() or out.suffix.lower()!=".json"
            or out.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Use a new direct module reports JSON, never overwrite SAFE")
    return out


def require_normalization_authorization(_any_supplied_evidence=None):
    """Deliberately closed: candidate/vendor-note inventory cannot authorize.

    Introduce a *separately reviewed* contract and a code-level signoff
    procedure before any future historical normalized data writer calls this.
    """
    raise PermissionError(
        "historical normalized Parquet/H5 mirror BLOCKED: "
        "verified vendor dictionary + rounding + adjustment + security review absent"
    )


def audit(action,footer_safe,out,notes=None):
    if action not in ("plan","intake"):
        raise ValueError("Action must be plan or intake")
    target=target_safe(out)
    footer,footer_sha=read_footer_safe(footer_safe)
    if action=="plan" and notes is not None:
        raise ValueError("PLAN cannot use unverified vendor notes")
    if action=="intake" and notes is None:
        raise ValueError("INTAKE requires private source notes + existing document")
    evidence=read_notes(notes) if action=="intake" else None
    documented=evidence["documented_role_names_only"] if evidence else []
    missing=[role for role in ROLES if role not in documented]
    result={
        "format":FORMAT,
        "status":("vendor_statement_locations_recorded_not_authenticated"
                  if evidence else "blocked_missing_vendor_semantics_source"),
        "source_purchased_day_footer_safe_sha256":footer_sha,
        "purchased_day_source_files_from_footer_safe":footer[
            "source_files_footer_only_read"],
        "purchased_day_row_groups_from_footer_safe":footer[
            "row_groups_footer_only_scanned"],
        "private_vendor_document_supplied":bool(evidence),
        "private_vendor_document_sha256":(
            evidence["private_doc_sha256"] if evidence else None),
        "private_vendor_source_notes_sha256":(
            evidence["private_notes_sha256"] if evidence else None),
        "documented_source_section_role_names_only":documented,
        "undocumented_required_role_names":missing,
        "required_semantic_roles_total":len(ROLES),
        "independent_document_authenticity_checked":False,
        "document_claims_independently_verified":False,
        "purchased_vendor_physical_units_certified":False,
        "historical_volume_amount_rounding_certified":False,
        "historical_adjustment_basis_certified":False,
        "historical_security_master_certified":False,
        "historical_normalized_parquet_authorized":False,
        "hikyuu_h5_mirror_authorized":False,
        "production_or_active_pointer_modified":False,
        "original_purchased_parquet_or_h5_accessed":False,
        "raw_vendor_document_or_claim_values_exported":False,
    }
    with target.open("x",encoding="utf-8") as f:
        json.dump(result,f,ensure_ascii=False,sort_keys=True,indent=2)
        f.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--action",choices=("plan","intake"),required=True)
    p.add_argument("--footer-safe",type=Path,required=True)
    p.add_argument("--vendor-notes",type=Path)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--offline-no-market-read",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        result=audit(args.action,args.footer_safe,args.out,args.vendor_notes)
        print("Vendor semantics inventory:",result["status"])
        print("Undocumented categories:",len(result["undocumented_required_role_names"]))
        print("Historical normalized Parquet / H5: BLOCKED")
        print("SAFE:",args.out)
    except (ValueError,TypeError,KeyError,OSError,json.JSONDecodeError):
        p.error("Evidence intake refused; no source market file or production write")


if __name__=="__main__":
    main()
