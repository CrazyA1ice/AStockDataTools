#!/usr/bin/env python3
"""Actual eight-cycle PyArrow Parquet DATASET over existing physical files.

Materializes a content-addressed FILE MANIFEST, not another copy of billions
of purchased rows. All eight periods open as pyarrow.dataset.Dataset from
existing purchased Parquet / SHA-verified private H5-only Parquet files.
2011-2026 DAY uses an already materialized, independently audited 16-year
purchased+22,274 H5-only physical Parquet version (14,137,981 rows).
1990-2010 historical H5 candidate is separate, UNQUALIFIED source schema;
never mix it into standardized A-share day or pretend units are certified.
Hard cutoff 2026-10-13. 2026-10-14 onwards is out of scope, NOT a gap.
No raw market source, private source, or production pointer is mutated.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
WORK=MODULE/"work"/"unified_parquet"
DATASETS=WORK/"datasets"
PERIODS=("1min","5min","15min","30min","60min","day","week","month")
PRIVATE=("1min","5min","15min","30min","60min")
ASOF=date(2026,10,13)
DATE_CUTOFF="2026-10-13"
SHA_RE=re.compile(r"[a-f0-9]{64}\Z")
MANIFEST_VERSION="purchased_primary_asof_20261013_eight_cycle_physical_parquet_file_dataset_v1"
RAW_COLS=("ts","symbol","open","high","low","close","volume","amount")
MODERN_ROWS=14137981
PURCHASED_DAY_ROWS=14115707
PRIVATE_DAY_ROWS=22274
SOURCE_DAY_VERSION_SHA="bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05"
SOURCE_DAY_VERSION_SAFE=MODULE/"reports"/"private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json"

def _load(alias,filename):
    spec=importlib.util.spec_from_file_location(alias,HERE/filename)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

CAT=_load("asof_eight_cycle_sha_bound_catalog",
          "query-catalog-bound-purchased-primary-eight-cycles-readonly.py")
DAY=_load("asof_modern_physical_16_year_day_sha_version",
          "query-private-2011-2026-all16-coverage-readonly.py")
HIST=_load("asof_historical_21_year_source_and_sha_verifier",
           "audit-original-h5-pre2011-private-21-year-day-readonly.py")

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,
                       separators=(",",":"),allow_nan=False)+"\n").encode("utf-8")

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def checked(root_kind,rel,root,mod,expected=None,*,purchased_stat=None):
    if (type(root_kind) is not str or root_kind not in ("purchased_root","private_module")
            or type(rel) is not str or
            not rel.endswith(".parquet") or "\\" in rel or
            rel.startswith("/") or
            any(s in (".","..","") for s in rel.split("/"))):
        raise ValueError("Unsafe physical Parquet reference")
    base=Path(root) if root_kind=="purchased_root" else Path(mod)
    if not base.is_absolute() or base.is_symlink() or not base.is_dir():
        raise ValueError("Invalid physical root")
    path=base.joinpath(*rel.split("/"))
    if (not path.is_file() or path.is_symlink()
            or not path.resolve().is_relative_to(base.resolve())
            or any(p.is_symlink() for p in path.parents if p!=base
                   and p.is_relative_to(base))):
        raise ValueError("Missing, redirected or outside physical Parquet")
    stat=path.stat()
    if stat.st_size<=0:
        raise ValueError("Empty source Parquet")
    if purchased_stat is not None:
        if (purchased_stat.get("size_bytes")!=stat.st_size
                or purchased_stat.get("mtime_ns")!=stat.st_mtime_ns):
            raise ValueError("Original purchased Parquet file stat changed")
    if expected is not None:
        if type(expected) is not str or SHA_RE.fullmatch(expected) is None:
            raise ValueError("Untrusted private Parquet content SHA")
        if sha(path)!=expected:
            raise ValueError("Private physical Parquet content SHA mismatch")
    return path

def _item(kind,relative,source,*,sha256=None,rows=None,stat=None):
    if source not in ("purchased_original", "modern_16yr_purchased_first_day",
                      "h5_only_verified_complete_stockday",
                      "h5_5min_derived_unverified_units",
                      "historical_1990_2010_h5_uncertified_candidate"):
        raise ValueError("Unknown source class")
    item={"root_kind":kind,"relative_file":relative,"source_class":source}
    if sha256 is not None:
        item["content_sha256"]=sha256
    if rows is not None:
        item["source_rows"]=rows
    if stat is not None:
        item["source_stat"]=stat
    return item

def modern_day_files(version_safe=SOURCE_DAY_VERSION_SAFE,
                     version_sha=SOURCE_DAY_VERSION_SHA):
    """Use ALREADY physical 16-year 14,137,981-row snapshot; no new DAY bars."""
    doc=DAY.version(version_safe,version_sha)
    entries=[]
    for year in range(2011,2027):
        node=doc["annual"][str(year)]
        rel=node["private_relative_directory"]
        match=DAY.YEAR_DIR.fullmatch(rel)
        if (match is None or int(match.group(1))!=year
                or node.get("total_rows",0)<=0):
            raise ValueError("Invalid SHA-pinned annual day physical entry")
        folder=MODULE/rel
        manifest=folder/"manifest.json"
        index=folder/"stockday-unique.sqlite3"
        if (manifest.is_symlink() or index.is_symlink()
                or sha(manifest)!=node["physical_manifest_sha256"]
                or sha(index)!=node["private_stockday_index_sha256"]):
            raise ValueError("Annual day manifest/stockday-key index SHA changed")
        body=json.loads(manifest.read_bytes())
        if (body.get("year")!=year or
                body.get("total_private_physical_rows")!=node["total_rows"]):
            raise ValueError("Annual daily original/private row count changed")
        count=0
        for key,path,part in DAY.entries(year,folder,body):
            relative=path.relative_to(MODULE).as_posix()
            checked("private_module",relative,Path("D:/unused"),MODULE,
                    part["sha256"])
            entries.append(_item("private_module",relative,
                                 "modern_16yr_purchased_first_day",
                                 sha256=part["sha256"],rows=part["rows"]))
            count+=part["rows"]
        if count!=node["total_rows"]:
            raise ValueError("Annual daily physical row totals do not conserve")
    if sum(x["source_rows"] for x in entries)!=MODERN_ROWS:
        raise ValueError("2011-2026 purchased-first physical day row count wrong")
    return entries

def historical_day_files(root):
    """Full independent 21-year real physical/keys/OHLC geometry audit."""
    report=HIST.audit(root)
    if (report.get("state")!=
            "full_1990_2010_private_h5_day_21_year_files_shas_schema_keys_quality_verified_readonly_not_promoted"
            or report.get("years_verified")!=21
            or report.get("private_a_code_stockday_rows_verified")!=3682327
            or report.get("h5_price_volume_amount_units_certified") is not False
            or report.get("historical_security_master_certified") is not False
            or report.get("original_market_sources_modified") is not False
            or report.get("ready_for_production_merge") is not False):
        raise ValueError("Uncertified historical 1990-2010 private day audit failed")
    annual=HIST._private_paths()
    rows=[]
    for year in range(1990,2011):
        folder=annual[year]
        manifest=json.loads((folder/"manifest.json").read_bytes())
        rel=(folder/"day.parquet").relative_to(MODULE).as_posix()
        digest=manifest["private_parquet_sha256"]
        checked("private_module",rel,root,MODULE,digest)
        rows.append(_item(
            "private_module",rel,
            "historical_1990_2010_h5_uncertified_candidate",
            sha256=digest,rows=manifest["candidate_stockday_rows"]))
    if (len(rows)!=21 or
            sum(x["source_rows"] for x in rows)!=3682327):
        raise ValueError("Missing historical private H5-only Parquet candidates")
    return rows

def assemble(root,catalog_sha,*,day_version_sha=SOURCE_DAY_VERSION_SHA,
             day_version_safe=SOURCE_DAY_VERSION_SAFE,
             with_historical_1990_2010=True):
    root=Path(root).resolve()
    if type(catalog_sha) is not str or SHA_RE.fullmatch(catalog_sha) is None:
        raise ValueError("Expected explicit previously accepted catalog SHA")
    if day_version_sha!=SOURCE_DAY_VERSION_SHA:
        raise ValueError("Require accepted immutable 2011-2026 physical DAY SHA")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Source root not found")
    # Validates every purchased source footer and file-stat, every H5 private
    # 1/5min and highcycle SHA, and exact immutable catalog payload.
    CAT.validate_version(root,catalog_sha)
    catalog=json.loads(CAT.catalog_path(catalog_sha).read_bytes())["payload"]
    paid=catalog["purchased"]
    others=catalog["private_research_candidates"]
    parts={p:[] for p in PERIODS}
    for period in PERIODS:
        if period=="day":
            continue # full physical purchased+H5 16-year day replaces source originals
        for year in range(2011,2027):
            for entry in paid["original_source_files_by_period_year"][
                    period+"|"+str(year)]:
                rel=entry["relative_path"]
                checked("purchased_root",rel,root,MODULE,purchased_stat=entry)
                parts[period].append(_item(
                    "purchased_root",rel,"purchased_original",
                    stat={"size_bytes":entry["size_bytes"],
                          "mtime_ns":entry["mtime_ns"]}))
    for item in others["minute_h5_gap_private_references"]:
        p=item["period"]
        if p not in ("1min","5min") or item["day"] not in (
                "2026-10-08","2026-10-09","2026-10-12","2026-10-13"):
            raise ValueError("Unregistered private minute gap date or period")
        rel=item["relative_file"]
        checked("private_module",rel,root,MODULE,item["content_sha256"])
        parts[p].append(_item("private_module",rel,
                             "h5_only_verified_complete_stockday",
                             sha256=item["content_sha256"],
                             rows=item["h5_only_complete_stockday_rows"]))
    for run in others["stage_runs"]:
        if not set(run["source_days"]).issubset(
                {"2026-10-08","2026-10-09","2026-10-12","2026-10-13"}):
            raise ValueError("Unexpected highcycle source date outside cutoff")
        for period in ("15min","30min","60min"):
            item=run["outputs"][period]
            rel=item["relative_file"]
            checked("private_module",rel,root,MODULE,item["content_sha256"])
            parts[period].append(_item(
                "private_module",rel,
                "h5_5min_derived_unverified_units",
                sha256=item["content_sha256"],rows=item["rows"]))
    parts["day"]=modern_day_files(day_version_safe,day_version_sha)
    historic=(historical_day_files(root)
              if with_historical_1990_2010 else [])
    # This is a DATASET, not merely a filename manifest. Verify EVERY
    # physical Parquet fragment exposes the same eight raw Arrow fields.
    # Exclude vendor extra columns in the exposed common projection, retain
    # originals untouched, and check typed footer counts where known.
    import pyarrow as pa
    import pyarrow.parquet as pq
    expected={"ts":pa.int64(),"symbol":pa.string(),
              **{name:pa.float64() for name in RAW_COLS[2:]}}
    seen_files=set()
    for period in PERIODS:
        for item in parts[period]:
            pair=(item["root_kind"],item["relative_file"])
            if pair in seen_files:
                raise ValueError("Duplicated physical Parquet fragment in dataset")
            seen_files.add(pair)
            file=checked(item["root_kind"],item["relative_file"],root,MODULE,
                         item.get("content_sha256"),
                         purchased_stat=item.get("source_stat"))
            with pq.ParquetFile(file,memory_map=False) as pf:
                schema=pf.schema_arrow
                if (any(name not in schema.names or
                        schema.field(name).type!=dtype
                        for name,dtype in expected.items())
                        or pf.metadata.num_rows<=0):
                    raise ValueError("Parquet dataset fragment schema invalid")
                if ("source_rows" in item and
                        item["source_rows"]!=pf.metadata.num_rows):
                    raise ValueError("Dataset source fragment row counts differ")
    # Historical records are a separate Arrow dataset, NOT a silent
    # append to purchase-normalized modern DAY.
    for item in historic:
        file=checked(item["root_kind"],item["relative_file"],root,MODULE,
                     item["content_sha256"])
        with pq.ParquetFile(file,memory_map=False) as pf:
            if (pf.metadata.num_rows!=item["source_rows"]
                    or any(name not in pf.schema_arrow.names or
                            pf.schema_arrow.field(name).type!=dtype
                            for name,dtype in expected.items())):
                raise ValueError("Historical uncertified candidate is not a valid Parquet fragment")
    if (sum(x["source_rows"] for p in ("15min","30min","60min")
            for x in parts[p] if x["source_class"]==
            "h5_5min_derived_unverified_units")!=621348
            or len([x for p in ("1min","5min") for x in parts[p]
                    if x["source_class"]=="h5_only_verified_complete_stockday"])!=8
            or not all(parts[p] for p in PERIODS)):
        raise ValueError("Missing H5 gap shards or purchased periods")
    # Existing 1990..2010 private H5 candidate is a DIFFERENT, unverified
    # physical interpretation. It cannot be merged as a normalized daily
    # period without independent historical units/security validation.
    payload={
        "format":MANIFEST_VERSION,
        "asof_inclusive":DATE_CUTOFF,
        "strict_cutoff_next_day":"2026-10-14",
        "periods":list(PERIODS),
        "original_market_root_is_external":True,
        "physical_source_path_resolution":{
            "purchased_root":"Original D:/stock root chosen on local machine",
            "private_module":"Git-ignored H5ParquetReconciler workspace"},
        "source_catalog_sha256":catalog_sha,
        "modern_16year_day_physical_version_sha256":day_version_sha,
        "modern_16year_day_physical_version_safe_sha256":sha(day_version_safe),
        "modern_16year_day_physical_rows":MODERN_ROWS,
        "modern_day_purchased_source_rows":PURCHASED_DAY_ROWS,
        "modern_day_h5_gap_rows":PRIVATE_DAY_ROWS,
        "period_physical_files":parts,
        "period_purchased_footer_rows_except_day":{
            p:paid["footer_row_totals_not_exact_unique_keys"][p]
            for p in PERIODS if p!="day"},
        "highcycle_candidate_rows":621348,
        "known_oct_h5_1min_5min_candidate_files":8,
        "historical_1990_2010_day":{
            "physical_legacy_raw_candidate_rows":3682327,
            "historical_files":historic,
            "historical_source_staged_and_sha_validated":len(historic)==21,
            "status":"separate_1990_2010_H5_unit_hypothesis_not_vendor_or_security_master_certified",
            "included_as_standard_day":False,
            "original_raw_native_h5_records_retained_in_source_archive":True},
        "other_missing_stockdays_and_partial_minute_keys_certified":False,
        "purchased_stockday_priority_in_source_staging":True,
        "source_symbol_spellings_may_differ_in_original_purchased":True,
        "all_selected_files_share_common_ts_symbol_ohlcva_projection":True,
        "no_purchased_parquet_copy":True,
        "source_vendor_units_certified":False,
        "full_market_completeness_certified":False,
        "ready_for_production_query":False,
        "ready_for_h5_mirror":False,
        "original_market_files_modified":False,
        "new_market_ohlcva_files_materialized":False,
        "active_pointer_modified":False,
    }
    return payload

def fingerprint(payload):
    return hashlib.sha256(canonical(payload)).hexdigest()

def write_manifest(payload):
    version=fingerprint(payload)
    if any(p.is_symlink() for p in (MODULE,MODULE/"work",WORK,DATASETS)):
        raise ValueError("Unsafe private dataset directory")
    folder=DATASETS/("eight_cycle_asof_20261013_"+version[:16])
    output=folder/"manifest.json"
    data=canonical({"dataset_sha256":version,"payload":payload})
    if output.is_symlink() or folder.is_symlink():
        raise ValueError("Unsafe dataset path")
    if output.exists():
        if output.read_bytes()!=data:
            raise ValueError("Immutable Parquet dataset file manifest changed")
        return output,False
    if folder.exists():
        raise ValueError("Incomplete or conflicting private dataset output")
    folder.mkdir(parents=True,exist_ok=False)
    with output.open("xb") as f:
        f.write(data)
    if output.read_bytes()!=data:
        raise ValueError("Immutable dataset manifest readback failed")
    return output,True

def load_manifest(path,root,*,expected_sha=None,verify_sources=True):
    """Open explicit version, fail closed on stale/altered private references."""
    path=Path(path)
    if (path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(DATASETS.resolve())
            or not re.fullmatch("eight_cycle_asof_20261013_[a-f0-9]{16}",
                                path.parent.name)
            or path.name!="manifest.json"):
        raise ValueError("Not an explicit private unified dataset version")
    raw=path.read_bytes()
    if not 0<len(raw)<=16_000_000:
        raise ValueError("Oversized dataset manifest")
    doc=json.loads(raw)
    if (type(doc) is not dict or set(doc)!={"dataset_sha256","payload"}
            or doc["payload"].get("format")!=MANIFEST_VERSION):
        raise ValueError("Wrong dataset manifest")
    version=fingerprint(doc["payload"])
    if (version!=doc["dataset_sha256"]
            or path.parent.name!="eight_cycle_asof_20261013_"+version[:16]
            or (expected_sha is not None and expected_sha!=version)
            or raw!=canonical(doc)):
        raise ValueError("Dataset SHA or canonical bytes changed")
    if verify_sources:
        actual=assemble(root,doc["payload"]["source_catalog_sha256"],
                        day_version_sha=doc["payload"][
                            "modern_16year_day_physical_version_sha256"],
                        with_historical_1990_2010=bool(doc["payload"][
                            "historical_1990_2010_day"]["historical_files"]))
        if actual!=doc["payload"]:
            raise ValueError("Parquet dataset references stale underlying source")
    return doc["payload"],version

def validate_eight_arrow_dataset_metadata(payload,root):
    """All 8 PyArrow DATASET instances, no K-line batches, no new bar files.

    assemble() has already checked physical SHA and every field/row footer;
    this only makes the actual eight Arrow multi-file datasets from that
    validated list and proves the fragment enumeration is identical.
    """
    import pyarrow as pa
    import pyarrow.dataset as ds
    schema=pa.schema([pa.field("ts",pa.int64()),
                      pa.field("symbol",pa.string()),
                      *(pa.field(k,pa.float64()) for k in RAW_COLS[2:])])
    counts={}
    for period in PERIODS:
        records=payload["period_physical_files"][period]
        paths=[]
        for row in records:
            base=Path(root).resolve() if row["root_kind"]=="purchased_root" else MODULE
            paths.append(str(base.joinpath(*row["relative_file"].split("/"))))
        dataset=ds.dataset(paths,format="parquet",schema=schema)
        if (dataset.schema!=schema or len(dataset.files)!=len(paths)):
            raise ValueError("Physical Arrow dataset missing a Parquet fragment")
        counts[period]=len(paths)
    return counts

def open_period_dataset(manifest_path,root,period,*,expected_sha,
                        allow_research_unverified_units=False):
    """A real pyarrow.dataset.Dataset, zero bar duplication, no new index.

    The schema projects a common raw column set. Original purchased symbol
    spellings/time-label policies are PRESERVED, not falsely normalized.
    """
    if period not in PERIODS:
        raise ValueError("Unknown K-line period")
    if allow_research_unverified_units is not True:
        raise ValueError("Research source-unit opt-in required")
    payload,version=load_manifest(
        manifest_path,root,expected_sha=expected_sha,verify_sources=True)
    import pyarrow as pa
    import pyarrow.dataset as ds
    schema=pa.schema([pa.field("ts",pa.int64()),
                      pa.field("symbol",pa.string()),
                      *(pa.field(p,pa.float64()) for p in RAW_COLS[2:])])
    files=[
        checked(item["root_kind"],item["relative_file"],Path(root).resolve(),
                MODULE,item.get("content_sha256"),
                purchased_stat=item.get("source_stat"))
        for item in payload["period_physical_files"][period]]
    for path in files:
        import pyarrow.parquet as pq
        with pq.ParquetFile(path) as reader:
            observed=reader.schema_arrow
            if any(p not in observed.names for p in RAW_COLS):
                raise ValueError("Selected source lacks common eight K-line columns")
            for field in schema:
                if observed.field(field.name).type!=field.type:
                    raise ValueError("Uncoercible original purchased/H5 schema")
    return ds.dataset([str(p) for p in files],format="parquet",schema=schema)

def open_eight_cycle_dataset_bundle(manifest_path,root,*,expected_sha,
                                    allow_research_unverified_units=False):
    """One SHA/source verification, return eight actual physical Arrow Datasets.

    Period file lists + provenance remain in the immutable payload; the
    PyArrow datasets expose the common raw eight-column schema. Consumers
    MUST apply their own key policy and cutoff, or use scan_period_asof.
    """
    if allow_research_unverified_units is not True:
        raise ValueError("Explicit research-only source-unit opt-in required")
    payload,_=load_manifest(
        manifest_path,root,expected_sha=expected_sha,verify_sources=True)
    import pyarrow as pa
    import pyarrow.dataset as ds
    schema=pa.schema([pa.field("ts",pa.int64()),
                      pa.field("symbol",pa.string()),
                      *(pa.field(k,pa.float64()) for k in RAW_COLS[2:])])
    datasets={}
    for period in PERIODS:
        files=[
            checked(item["root_kind"],item["relative_file"],
                    Path(root).resolve(),MODULE,
                    item.get("content_sha256"),
                    purchased_stat=item.get("source_stat"))
            for item in payload["period_physical_files"][period]]
        datasets[period]=ds.dataset(
            [str(f) for f in files],format="parquet",schema=schema)
    return datasets,payload

def open_historical_1990_2010_research_day_dataset(manifest_path,root,*,
                         expected_sha,allow_historical_unverified=False):
    """Standalone historical H5-candidate Parquet dataset, NEVER modern DAY."""
    if allow_historical_unverified is not True:
        raise ValueError("Explicit UNVERIFIED historical H5 unit-hypothesis opt-in required")
    payload,_=load_manifest(
        manifest_path,root,expected_sha=expected_sha,verify_sources=True)
    records=payload.get("historical_1990_2010_day",{}).get(
        "historical_files",[])
    if not isinstance(records,list) or len(records)!=21:
        raise ValueError("No 21-year physically verified historical research layer")
    import pyarrow.dataset as ds
    import pyarrow as pa
    schema=pa.schema([pa.field("ts",pa.int64()),
                      pa.field("symbol",pa.string()),
                      *(pa.field(name,pa.float64()) for name in RAW_COLS[2:])])
    paths=[checked(x["root_kind"],x["relative_file"],Path(root).resolve(),
                   MODULE,x["content_sha256"]) for x in records]
    return ds.dataset([str(p) for p in paths],format="parquet",schema=schema)

def scan_period_asof(manifest_path,root,period,*,expected_sha,
                     allow_research_unverified_units=False,batch_size=32768):
    """Return a bounded streaming Arrow Scanner, with an enforced end cutoff."""
    import pyarrow.dataset as ds
    if type(batch_size) is not int or not 1<=batch_size<=32768:
        raise ValueError("Unsafe Arrow scan batch size")
    dataset=open_period_dataset(
        manifest_path,root,period,expected_sha=expected_sha,
        allow_research_unverified_units=allow_research_unverified_units)
    after=ASOF+timedelta(days=1)
    high=int(datetime(after.year,after.month,after.day,
                      tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)
    return dataset.scanner(
        columns=list(RAW_COLS),filter=ds.field("ts")<high,
        batch_size=batch_size,use_threads=False)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--source-catalog-sha256",required=True)
    p.add_argument("--skip-historical-research-layer",action="store_true",
                   help="Create 2011-2026 core first; 1990-2010 remains excluded until a separate audited version")
    p.add_argument("--modern-day-version-sha256",default=SOURCE_DAY_VERSION_SHA)
    p.add_argument("--modern-day-version-safe",type=Path,
                   default=SOURCE_DAY_VERSION_SAFE)
    a=p.parse_args(argv)
    try:
        payload=assemble(a.root,a.source_catalog_sha256,
                         day_version_sha=a.modern_day_version_sha256,
                         day_version_safe=a.modern_day_version_safe,
                         with_historical_1990_2010=not a.skip_historical_research_layer)
        file,created=write_manifest(payload)
        opened=validate_eight_arrow_dataset_metadata(payload,a.root)
        print("UNIFIED_20261013_EIGHT_CYCLE_PARQUET_DATASET="+json.dumps({
            "status":MANIFEST_VERSION,
            "dataset_sha256":fingerprint(payload),
            "manifest_relative_file":file.relative_to(MODULE).as_posix(),
            "file_count_by_period":{p:len(payload["period_physical_files"][p])
                                    for p in PERIODS},
            "all_eight_cycles_physically_addressable":True,
            "actual_pyarrow_datasets_opened":len(opened),
            "arrow_fragment_counts":opened,
            "market_bar_batches_read_during_arrow_open":False,
            "modern_day_physical_rows":MODERN_ROWS,
            "h5_gap_day_rows":PRIVATE_DAY_ROWS,
            "h5_derived_highcycle_candidate_rows":621348,
            "historical_1990_2010_raw_day_cannot_be_silently_normalized":True,
            "historical_research_files":len(payload["historical_1990_2010_day"]["historical_files"]),
            "historical_research_rows_not_in_modern_standard_day":3682327
                if payload["historical_1990_2010_day"]["historical_files"] else 0,
            "market_data_copied":False,
            "new_metadata_only_manifest_created":created,
            "original_market_files_modified":False,
            "ready_for_production_query":False,
        },ensure_ascii=False,sort_keys=True,separators=(",",":")),flush=True)
    except (ValueError,TypeError,KeyError,OSError) as exc:
        p.error("Eight-cycle physical Parquet dataset NOT ACCEPTED: "+
                type(exc).__name__+": "+str(exc))

if __name__=="__main__":
    main()
