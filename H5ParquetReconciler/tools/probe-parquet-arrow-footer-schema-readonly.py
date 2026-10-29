#!/usr/bin/env python3
"""Read exactly three explicitly selected Parquet FOOTERS; never read K-line rows.

Supply a user-chosen external root and one RELATIVE .parquet filename per
period. Only a narrow schema/typed metadata summary is returned to the
module's reports/ directory. This does not infer physical amount/volume units.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import struct
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
TOOLS=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "sanitized_parquet_h5_unit_audit",
    TOOLS/"audit-sanitized-parquet-h5-unit-evidence.py")
AUDIT=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
FORMAT="AStockDataTools bounded real Parquet Arrow footer-only schema v1"
PERIODS=("day","5min","1min")
FOOTER_MAX=16*1024*1024
ALIASES={
    "date":("datetime","timestamp","trade_time","trade_datetime",
            "trade_date","date","time","dt","ts"),
    "open":("open",),
    "high":("high",),
    "low":("low",),
    "close":("close",),
    "amount":("amount","turnover","money","transamount"),
    "volume":("volume","vol","qty","quantity","transcount"),
}


def selected_file(root,rel,period):
    """No globbing, walking, links, imports, writes, or absolute source files."""
    root=Path(root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("Use an existing non-symlink ABSOLUTE source root")
    rel=Path(rel)
    if (rel.is_absolute() or len(rel.parts)!=2 or rel.parts[0]!=period
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}\.parquet",rel.parts[1])
            or rel.parts[1] in (".","..")):
        raise ValueError("Select exactly one safe period/filename.parquet")
    folder=root/period
    path=folder/rel.parts[1]
    if (folder.is_symlink() or not folder.is_dir() or path.is_symlink()
            or not path.is_file() or path.resolve().parent!=folder.resolve()
            or path.stat().st_size<12):
        raise ValueError("Selected Parquet source must be an existing plain file")
    return path


def footer_guard(path,max_footer=FOOTER_MAX):
    """Inspect only the 4-byte header and 8-byte Parquet trailer."""
    if (type(max_footer) is not int or max_footer<1024
            or max_footer>FOOTER_MAX):
        raise ValueError("Unsupported Parquet footer budget")
    pre=path.stat()
    with path.open("rb") as src:
        first=src.read(4)
        src.seek(-8,2)
        last=src.read(8)
    if first!=b"PAR1" or len(last)!=8 or last[4:]!=b"PAR1":
        raise ValueError("Parquet magic missing or encrypted/unsupported footer")
    n=struct.unpack("<I",last[:4])[0]
    if not 0<n<=max_footer or n+12>pre.st_size:
        raise ValueError("Parquet metadata footer exceeds bounded budget")
    return (pre.st_size,pre.st_mtime_ns,n)


def _type_label(t,pa):
    if pa.types.is_decimal(t):
        return "decimal128" if pa.types.is_decimal128(t) else "unknown"
    if pa.types.is_int64(t):
        return "int64"
    if pa.types.is_uint64(t):
        return "uint64"
    if pa.types.is_float64(t):
        return "float64"
    if pa.types.is_float32(t):
        return "float32"
    return "unknown"


def _datetime_type(t,pa):
    if pa.types.is_timestamp(t):
        return {"ms":"timestamp_ms","us":"timestamp_us",
                "ns":"timestamp_ns"}.get(t.unit,"unknown")
    if pa.types.is_date32(t):
        return "date32"
    # An int/string field cannot prove YYYYMMDD encoding from its dtype.
    return "unknown"


def _timezone(t,pa):
    if pa.types.is_timestamp(t):
        return {None:"naive","Asia/Shanghai":"Asia/Shanghai",
                "UTC":"UTC"}.get(t.tz,"unknown")
    if pa.types.is_date32(t):
        return "naive"
    return "unknown"


def canonical_schema(schema,pa):
    """Do not return raw field names, free-text metadata or arbitrary type repr."""
    fields={}
    for f in schema:
        name=f.name
        if type(name) is not str or len(name)>120:
            continue
        key=name.casefold()
        fields.setdefault(key,[]).append(f.type)
    found={}
    ambiguous=[]
    for label,aliases in ALIASES.items():
        choices=[(name,t) for name in aliases for t in fields.get(name,[])]
        if len(choices)==1:
            found[label]=choices[0][1]
        else:
            found[label]=None
            if len(choices)>1:
                ambiguous.append(label)
    price=[_type_label(found[x],pa) if found[x] is not None else "unknown"
           for x in ("open","high","low","close")]
    date_t=found["date"]
    date_type=_datetime_type(date_t,pa) if date_t is not None else "unknown"
    tz=_timezone(date_t,pa) if date_t is not None else "unknown"
    price_kind=price[0] if all(p==price[0] for p in price) else "unknown"
    return {
        "audit_schema":{
            "date_type":date_type,
            "price_type":price_kind,
            "amount_type":(_type_label(found["amount"],pa)
                           if found["amount"] is not None else "unknown"),
            "volume_type":(_type_label(found["volume"],pa)
                           if found["volume"] is not None else "unknown"),
            "timezone":tz,
            # Arrow types NEVER establish physical money/shares units.
            "amount_unit_declared":"unknown",
            "volume_unit_declared":"unknown",
        },
        "recognized_alias_presence":{key:found[key] is not None
                                     for key in ALIASES},
        "ambiguous_alias_roles":sorted(ambiguous),
        "arrow_columns_in_schema":len(schema),
    }


def inspect_footer(path,period,pq,pa):
    before=footer_guard(path)
    reader=None
    try:
        # pq.ParquetFile reads the footer; never call read, read_row_group,
        # read_table, iter_batches, scan or any column-data function.
        reader=pq.ParquetFile(str(path),memory_map=False,pre_buffer=False)
        schema=reader.schema_arrow
        metadata=reader.metadata
        if (metadata is None or metadata.num_row_groups<1
                or metadata.num_row_groups>100_000
                or metadata.num_rows<0
                or len(schema)>512):
            raise ValueError("Parquet footer schema/row-group limits invalid")
        out=canonical_schema(schema,pa)
        out.update({
            "period":period,
            "parquet_metadata_only":True,
            "source_file_size_bytes":before[0],
            "footer_bytes":before[2],
            "row_group_count":metadata.num_row_groups,
            "total_source_rows_from_footer":metadata.num_rows,
        })
        return out
    except Exception:
        # Arrow error messages may expose absolute market file paths.
        raise ValueError("Unable to inspect approved Parquet footer") from None
    finally:
        if reader is not None:
            reader.close()
        after=footer_guard(path)
        if before!=after:
            raise ValueError("Source Parquet file changed during footer inspection")


def enrich_existing_sanitized(old,records):
    if not isinstance(old,dict):
        raise ValueError("Existing sanitized evidence must be JSON object")
    # Require the previously reviewed metadata-only report, not arbitrary
    # market rows or free-form fields.
    AUDIT.check_evidence(old)
    schemas=old["schemas"]
    if (set(schemas)!=set(PERIODS)
            or any(any(schemas[p][k]!="unknown" for k in (
                "date_type","price_type","amount_type","volume_type",
                "timezone","amount_unit_declared","volume_unit_declared"))
                for p in PERIODS)
            or old.get("independent_unit_reference")!="none"):
        raise ValueError("Only enrich original unknown-only sanitized evidence")
    updated={
        "format":AUDIT.FORMAT,
        "sanitized_aggregates_only":True,
        "no_raw_market_rows":True,
        "independent_unit_reference":"none",
        "schemas":{p:dict(records[p]["audit_schema"]) for p in PERIODS},
        "windows":[dict(w) for w in old["windows"]],
    }
    # Existing dates/ratios/flags are unchanged, and unknown physical units,
    # closed-session and adjustment proofs MUST NOT silently become true.
    if updated["windows"]!=old["windows"]:
        raise ValueError("Prior stock-date windows cannot change")
    assessment=AUDIT.check_evidence(updated)
    if (assessment["amount_physical_unit_certified"]
            or assessment["volume_physical_unit_certified"]
            or assessment["licensed_parquet_to_h5_mapping_certified"]
            or assessment["ready_for_full_market_mirror"]):
        raise ValueError("Schema-only scan cannot certify market units")
    return updated,assessment


def probe(root,day_rel,min5_rel,min1_rel,existing_sanitized,
          schema_out,enriched_out,assessment_out,reader=None):
    """Run exactly 3 footer reads; output 3 non-overwriting sanitized JSON."""
    schema_path=AUDIT._path(schema_out,False)
    enriched_path=AUDIT._path(enriched_out,False)
    assessment_path=AUDIT._path(assessment_out,False)
    prior_path=AUDIT._path(existing_sanitized,True)
    allpaths=(schema_path,enriched_path,assessment_path,prior_path)
    if len(set(p.resolve() for p in allpaths))!=4:
        raise ValueError("Require 4 distinct report JSON paths")
    selections={
        "day":selected_file(root,day_rel,"day"),
        "5min":selected_file(root,min5_rel,"5min"),
        "1min":selected_file(root,min1_rel,"1min"),
    }
    if len(set(p.resolve() for p in selections.values()))!=3:
        raise ValueError("One different Parquet file per period required")
    original=json.loads(prior_path.read_text(encoding="utf-8"))
    # Validate prior JSON BEFORE reading any source.
    AUDIT.check_evidence(original)
    import pyarrow as pa
    import pyarrow.parquet as pq
    scan=reader or inspect_footer
    records={p:scan(path,p,pq,pa) for p,path in selections.items()}
    enriched,assessment=enrich_existing_sanitized(original,records)
    # Three SAFE JSONs contain only bounded metadata (no source path or
    # exact file name, Arrow user metadata, raw rows or physical-unit claims).
    info={
        "format":FORMAT,
        "periods":{p:records[p] for p in PERIODS},
        "footer_only_no_row_data_loaded":True,
        "sources_read_only":True,
        "source_root_or_filenames_in_safe_output":False,
        "original_h5_or_sqlite_opened":False,
        "raw_ohlcva_exported":False,
        "amount_physical_unit_certified":False,
        "volume_physical_unit_certified":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
    }
    # Write with x mode: preserve previous reports. No output path can
    # resolve to one of the selected source files.
    for path,doc in ((schema_path,info),
                     (enriched_path,enriched),
                     (assessment_path,assessment)):
        with path.open("x",encoding="utf-8") as f:
            json.dump(doc,f,ensure_ascii=False,indent=2)
            f.write("\n")
    return info,assessment


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--day-relative",type=Path,required=True)
    p.add_argument("--min5-relative",type=Path,required=True)
    p.add_argument("--min1-relative",type=Path,required=True)
    p.add_argument("--existing-sanitized",type=Path,required=True)
    p.add_argument("--schema-out",type=Path,required=True)
    p.add_argument("--enriched-out",type=Path,required=True)
    p.add_argument("--assessment-out",type=Path,required=True)
    p.add_argument("--footer-metadata-only",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        info,assessment=probe(
            args.source_root,args.day_relative,args.min5_relative,
            args.min1_relative,args.existing_sanitized,args.schema_out,
            args.enriched_out,args.assessment_out)
        print("SAFE Parquet footer schema:",args.schema_out)
        print("Footer-only periods:",len(info["periods"]))
        print("Independent unit review ready:",
              assessment["ready_to_plan_independent_unit_check"])
        print("Amount/volume physical units certified: NO")
        print("Production market H5/SQLite modified: NO")
    except (OSError,ValueError,TypeError,ImportError,
            json.JSONDecodeError) as err:
        # Never display Arrow's unrestricted source-path-bearing exceptions.
        p.error(str(err) if isinstance(err,ValueError)
                else "Footer-only schema inspection failed")


if __name__=="__main__":
    main()
