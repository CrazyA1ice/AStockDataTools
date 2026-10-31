#!/usr/bin/env python3
"""Read-only privacy-safe diagnostic of a refused 2016 private physical build.

Run after a refused 2016 materialization, BEFORE retrying. This tool never
creates physical Parquet or modifies market sources. It checks the QDC year
SHA, all historical original source rows against the SAME normalizer used by
the annual builder, and the single SHA-pinned 2016 H5-only candidate against
a temporary in-memory stockday uniqueness index. It emits only a bounded,
aggregate-only SAFE, with a fixed error code and no OHLCVA, stock identifiers,
original absolute paths, source row numbers or tracebacks.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools read-only 2016 historical purchased H5 candidate diagnostic v1"
HEX64=re.compile("[0-9a-f]{64}\\Z")


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M=load("hist_2016_refusal_original_source_reader",
       "materialize-private-2011-2025-purchased-year.py")


# Only static, generic errors can appear in the SAFE. Never expose raw
# error strings returned by Arrow/SQLite/third-party files.
SAFE_CODES={
    "Expected 64-character SHA256 evidence pin":"INPUT_SHA256_PIN_FORMAT_INVALID",
    "Invalid purchased/H5 input stockday schema":"SOURCE_FIELD_TYPE",
    "Original market stock symbol cannot be mapped conservatively":"SYMBOL_NOT_CANONICALIZABLE",
    "Original stockday timestamp is not valid":"SOURCE_TIMESTAMP_INVALID",
    "Purchased monthly source day escaped its declared partition":"YEAR_MISMATCH",
    "Nonfloat64 or invalid original source OHLCVA":"SOURCE_FLOAT64_INVALID",
    "Purchased/H5 stockday OHLC geometry is invalid":"SOURCE_PRICE_GEOMETRY_INVALID",
    "Private H5 candidate provenance/date is not certified":"H5_CANDIDATE_PROVENANCE_INVALID",
    "Original purchased historical Arrow footer/schema mismatched":"SOURCE_ARROW_SCHEMA_INVALID",
    "2016 original purchased footer row total differs from QDC manifest":"PURCHASED_FOOTER_ROW_COUNT_MISMATCH",
    "2016 original purchased expected field names are missing":"PURCHASED_REQUIRED_FIELDS_MISSING",
    "2016 original purchased contains additional field names":"PURCHASED_ADDITIONAL_FIELDS_PRESENT",
    "2016 original purchased required Arrow physical field types differ":"PURCHASED_REQUIRED_FIELD_TYPES_MISMATCH",
    "2016 original purchased Arrow field names repeat":"PURCHASED_DUPLICATE_FIELD_NAMES",
    "Original purchased annual file differs from full QDC SHA manifest":"PURCHASED_SOURCE_SHA_INVALID",
    "Original purchased README or manifest SHA differs":"QDC_DOC_SHA_INVALID",
    "Duplicate purchased/purchased or purchased/H5 stockday; fail closed":"DUPLICATE_STOCKDAY",
    "2016 private H5-only source category changed":"H5_CANDIDATE_SOURCE_CATEGORY",
    "2016 private H5 candidate Arrow source changed":"H5_CANDIDATE_ARROW_INVALID",
    "Historical 2016 private H5 candidate source SHA differs":"H5_CANDIDATE_SHA_INVALID",
    "Trusted historical H5-only source version missing":"CANDIDATE_VERSION_INVALID",
}


def code_for(error):
    message=str(error)
    if message in SAFE_CODES:
        return SAFE_CODES[message]
    if isinstance(error,sqlite3.IntegrityError):
        return "DUPLICATE_STOCKDAY"
    if isinstance(error,(OSError,ValueError,TypeError,KeyError,OverflowError)):
        return "UNCLASSIFIED_SOURCE_OR_CODE_FAILURE"
    return "UNCLASSIFIED_READER_FAILURE"


def destination(path):
    p=Path(path)
    if (REPORTS.is_symlink() or p.is_symlink() or p.exists()
            or p.suffix.lower()!=".json" or
            p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Require NEW aggregate-only module reports/ diagnostic SAFE")
    return p


def inspect(source_root,candidate_safe,readme_sha,manifest_sha,out):
    target=destination(out)
    stage="input_source_sha"
    error=None
    purchased_count=0
    h5_count=0
    source_sha_before_and_after=False
    stockdays_unique=False
    original_source_file_count=0
    # All footer details are boolean/count-only; no field names, ticker,
    # market values, original path, or raw Arrow metadata are exported.
    footer_rows_match=None
    footer_required_field_names_present=None
    footer_extra_field_count=None
    footer_missing_required_field_count=None
    footer_expected_field_types_match=None
    footer_rowgroup_count=None
    footer_schema_names_unique=None
    con=sqlite3.connect(":memory:")
    try:
        con.execute("CREATE TABLE stockday(symbol TEXT NOT NULL, trading_date TEXT NOT NULL,"
                    "PRIMARY KEY(symbol,trading_date)) WITHOUT ROWID")
        original, record, readme, mf = M.purchased_input(
            source_root,2016,readme_sha,manifest_sha)
        original_source_file_count=1
        start_digest=M.QDC.digest_file(original)
        if start_digest!=record["sha"]:
            raise ValueError("Original purchased annual file differs from full QDC SHA manifest")
        states={f.name:M.QDC.file_state(f) for f in (original,readme,mf)}
        stage="candidate_sha"
        c,source_sha,folder,manifest=M.V.source(candidate_safe)
        if (c.get("source_version_sha256")!=M.SOURCE_VERSION
                or c.get("candidate_year_rows")!={"2016":1,"2026":22273}):
            raise ValueError("Trusted historical H5-only source version missing")
        candidate=folder/"year=2016"/"day.parquet"
        if (candidate.parent.is_symlink() or candidate.is_symlink()
                or not candidate.is_file()
                or M.ST.sha(candidate)!=c["partition_sha256"]["2016"]):
            raise ValueError("Historical 2016 private H5 candidate source SHA differs")
        stage="purchased_footer"
        import pyarrow as pa
        import pyarrow.parquet as pq
        p=pq.ParquetFile(original,memory_map=False,pre_buffer=False)
        try:
            expected={"ts","symbol",*M.PHYS.F}
            observed=p.schema_arrow.names
            names=set(observed)
            footer_rows_match=(p.metadata.num_rows==record["rows"])
            footer_rowgroup_count=p.metadata.num_row_groups
            footer_schema_names_unique=(len(names)==len(observed))
            footer_missing_required_field_count=len(expected-names)
            footer_extra_field_count=len(names-expected)
            footer_required_field_names_present=(footer_missing_required_field_count==0)
            # Exact expected source physical types, never string-coerce
            # unexpected columns, and never silently remove extra fields.
            expected_types={"symbol":pa.string(),"ts":pa.int64(),
                            **{field:pa.float64() for field in M.PHYS.F}}
            footer_expected_field_types_match=(
                footer_required_field_names_present
                and footer_schema_names_unique
                and all(p.schema_arrow.field(field).type==arrow_type
                        for field,arrow_type in expected_types.items())
            )
            if not footer_rows_match:
                raise ValueError("2016 original purchased footer row total differs from QDC manifest")
            if not footer_schema_names_unique:
                raise ValueError("2016 original purchased Arrow field names repeat")
            if not footer_required_field_names_present:
                raise ValueError("2016 original purchased expected field names are missing")
            # One noncanonical column is now accepted only with a full,
            # SHA-pinned original vendor Parquet byte shadow in the private
            # materializer. No extra field is silently discarded or recast.
            if footer_extra_field_count>1:
                raise ValueError("2016 original purchased contains additional field names")
            if not footer_expected_field_types_match:
                raise ValueError("2016 original purchased required Arrow physical field types differ")
            stage="purchased_rows"
            for rg in range(p.metadata.num_row_groups):
                t=p.read_row_group(rg,columns=["ts","symbol",*M.PHYS.F],
                                   use_threads=False)
                if any(col.null_count for col in t.columns):
                    raise ValueError("Nonfloat64 or invalid original source OHLCVA")
                for raw in t.to_pylist():
                    item=M.PHYS.normalise(raw,"purchased_parquet",2016,None)
                    try:
                        con.execute("INSERT INTO stockday VALUES (?,?)",
                                    (item["symbol"],item["trading_date"]))
                    except sqlite3.IntegrityError:
                        raise ValueError(
                            "Duplicate purchased/purchased or purchased/H5 stockday; fail closed") from None
                    purchased_count+=1
        finally:
            p.close()
        if purchased_count!=record["rows"]:
            raise ValueError("Original purchased historical Arrow footer/schema mismatched")
        stage="h5_candidate"
        pf=pq.ParquetFile(candidate,memory_map=False,pre_buffer=False)
        try:
            if pf.schema_arrow!=M.ST.candidate_schema(pa) or pf.metadata.num_rows!=1:
                raise ValueError("2016 private H5 candidate Arrow source changed")
            for rg in range(pf.metadata.num_row_groups):
                for raw in pf.read_row_group(rg,use_threads=False).to_pylist():
                    if raw["value_source"]!="private_h5_mixed_stockday_candidate":
                        raise ValueError("2016 private H5-only source category changed")
                    item=M.PHYS.normalise(raw,raw["value_source"],2016,None)
                    try:
                        con.execute("INSERT INTO stockday VALUES (?,?)",
                                    (item["symbol"],item["trading_date"]))
                    except sqlite3.IntegrityError:
                        raise ValueError(
                            "Duplicate purchased/purchased or purchased/H5 stockday; fail closed") from None
                    h5_count+=1
        finally:
            pf.close()
        if h5_count!=1:
            raise ValueError("2016 private H5 candidate Arrow source changed")
        stage="source_sha_after"
        if (M.QDC.digest_file(original)!=start_digest
                or any(M.QDC.file_state(f)!=states[f.name] for f in (original,readme,mf))
                or M.QDC.digest_file(readme,M.QDC.MAX_README_BYTES)!=
                        M.QDC.pinned_hash(readme_sha)
                or M.QDC.digest_file(mf,M.QDC.MAX_MANIFEST_BYTES)!=
                        M.QDC.pinned_hash(manifest_sha)
                or M.V.source(candidate_safe)[1]!=source_sha
                or M.ST.sha(candidate)!=c["partition_sha256"]["2016"]
                or M.ST.sha(manifest)!=c["manifest_sha256"]):
            raise ValueError("Original purchased annual file differs from full QDC SHA manifest")
        source_sha_before_and_after=True
        stockdays_unique=True
        stage="complete"
    except Exception as exc:
        # Arrow/third-party exceptions must also be sanitized. Never emit a
        # raw exception string, traceback, symbol, date or licensed value.
        error=code_for(exc)
    finally:
        con.close()
    # Only invariant enum stage, conservative status and counts, never any
    # symbol, day, market value or file name beyond the fixed requested year.
    result={
        "format":FORMAT,
        "status":"readonly_2016_historical_preflight_pass" if error is None
                 else "readonly_2016_historical_preflight_rejected",
        "year":2016,
        "failure_stage":None if error is None else stage,
        "failure_code":error,
        "original_purchased_2016_source_file_count_seen":original_source_file_count,
        "purchased_footer_row_count_matches_received_manifest":footer_rows_match,
        "purchased_footer_rowgroup_count":footer_rowgroup_count,
        "purchased_required_fields_present":footer_required_field_names_present,
        "purchased_missing_required_field_count":footer_missing_required_field_count,
        "purchased_additional_field_count":footer_extra_field_count,
        "purchased_extra_field_requires_byte_identical_private_original_shadow":
            footer_extra_field_count==1,
        "purchased_extra_field_business_semantics_certified":False,
        "purchased_field_names_unique":footer_schema_names_unique,
        "purchased_required_arrow_types_match":footer_expected_field_types_match,
        "purchased_rows_checked_before_refusal":purchased_count,
        "h5_candidate_rows_checked_before_refusal":h5_count,
        "source_shas_and_stats_unchanged_after_complete_scan":source_sha_before_and_after,
        "all_purchased_h5_candidate_stockdays_unique":stockdays_unique,
        "original_h5_source_scanned":False,
        "original_market_files_written":False,
        "private_annual_parquet_or_sqlite_created":False,
        "private_or_production_active_pointer_modified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "candidate_source_units_certified":False,
        "no_licensed_ohlcva_or_stock_symbols_exported_in_safe":True,
    }
    with target.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(result,f,ensure_ascii=False,indent=2,sort_keys=True)
        f.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--purchased-root",type=Path,required=True)
    p.add_argument("--candidate-safe",type=Path,required=True)
    p.add_argument("--readme-sha256",required=True)
    p.add_argument("--manifest-sha256",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--diagnose-2016-readonly",action="store_true",required=True)
    a=p.parse_args(argv)
    result=inspect(a.purchased_root,a.candidate_safe,
                   a.readme_sha256,a.manifest_sha256,a.out)
    print("2016 original purchased and audited H5 candidate read-only probe:",
          result["status"])
    if result["failure_code"] is not None:
        print("SAFE failure stage:",result["failure_stage"])
        print("SAFE failure code:",result["failure_code"])
    print("Aggregate-only SAFE:",a.out)
    return 0 if result["failure_code"] is None else 2


if __name__=="__main__":
    raise SystemExit(main())
