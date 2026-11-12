#!/usr/bin/env python3
"""Eight-period physical Parquet layout and safe local materialization.

Accepted local convention (AStockDataTools): stock/AllCycleAStockData/
  1min|5min|15min|30min|60min|day|week|month/
    2011.parquet ... (all past years, one annual shard per period)
    <current year>-01.parquet ... <current year>-12.parquet

No H5 access. Existing market files are never truncated in-place:
- original bytes backed up privately and SHA-verified before replacement
- staged Parquet is fully read-back verified with all old normalized keys
- only one atomic os.replace occurs, after readers are explicitly closed
- source/target key overlaps keep original values (no silent overwrite)
- completed-year monthly-to-annual archival is a separate explicit action
"""
from __future__ import annotations

from datetime import date,datetime,timedelta,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
from collections import Counter

PERIODS=("1min","5min","15min","30min","60min","day","week","month")
COLS=("ts","symbol","open","high","low","close","volume","amount")
UTC8=timezone(timedelta(hours=8))
ANNUAL=re.compile(r"^(20\d{2}|19\d{2})\.parquet$")
MONTHLY=re.compile(r"^(20\d{2}|19\d{2})-(0[1-9]|1[0-2])\.parquet$")
FORMAT="eight_cycle_local_year_month_annual_convention_v1"

def hash_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for buffer in iter(lambda:f.read(1024*1024),b""):
            h.update(buffer)
    return h.hexdigest()

def storage_root(root,*,require_all=True):
    root=Path(root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Stock source root missing or redirected")
    folder=root if root.name.lower()=="allcycleastockdata" else root/"AllCycleAStockData"
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Expected stock/AllCycleAStockData directory")
    for period in PERIODS:
        child=folder/period
        if (require_all and not child.is_dir()) or child.is_symlink():
            raise ValueError("Missing or linked Parquet period directory: "+period)
    return folder

def classify_filename(filename):
    annual=ANNUAL.fullmatch(filename)
    if annual:
        return (int(annual.group(1)),None)
    monthly=MONTHLY.fullmatch(filename)
    if monthly:
        return (int(monthly.group(1)),int(monthly.group(2)))
    return None

def target_for_date(root,period,day,*,current_year=None):
    if period not in PERIODS or not isinstance(day,date):
        raise ValueError("Period or local trading date invalid")
    current_year=current_year or datetime.now(UTC8).year
    if day.year>current_year:
        raise ValueError("Future year cannot be archived")
    folder=storage_root(root)/period
    # Prior years are annual, current year monthly. A prior-year monthly
    # rollover requires explicit archive first; never create a second copy
    # of the same year's bars while the prior monthly series is present.
    if day.year<current_year:
        return folder/(f"{day.year}.parquet")
    return folder/(f"{day.year}-{day.month:02}.parquet")

def inventory(root,*,current_year=None):
    import pyarrow.parquet as pq
    current_year=current_year or datetime.now(UTC8).year
    base=storage_root(root)
    response={"root":str(base),"year":current_year,
              "schema":"ts:int64,symbol:string,OHLCVA:float64",
              "periods":{},"layout_valid":True}
    for period in PERIODS:
        annual=[]
        monthly=[]
        unknown=[]
        for path in sorted((base/period).iterdir()):
            if not path.is_file() or path.is_symlink() or path.suffix!=".parquet":
                continue
            classification=classify_filename(path.name)
            if classification is None:
                unknown.append(path.name)
                continue
            yr,month=classification
            f=pq.ParquetFile(path)
            try:
                count=f.metadata.num_rows
                schema=f.schema_arrow
                if not set(COLS).issubset(schema.names):
                    raise ValueError("Existing original Parquet lacks standard OHLCVA columns: "+str(path))
                info={"name":path.name,"rows":count,"bytes":path.stat().st_size}
            finally:
                f.close()
            if month is None:
                annual.append(info)
            else:
                monthly.append(info)
        current=sorted(x["name"] for x in monthly if x["name"].startswith(str(current_year)+"-"))
        archived_year_months=[x["name"] for x in monthly
                              if int(x["name"][:4])<current_year]
        past_year_names=[x["name"] for x in annual
                         if int(x["name"][:4])>=current_year]
        problems=[]
        if archived_year_months:
            problems.append("Previous year monthly files need archival: "+",".join(archived_year_months[:15]))
        if past_year_names:
            problems.append("Current/future year has annual file: "+",".join(past_year_names))
        if problems:
            response["layout_valid"]=False
        response["periods"][period]={
            "annual_files":len(annual),"monthly_files":len(monthly),
            "current_year_monthly_files":current,
            "prior_year_monthly_files":archived_year_months,
            "unknown_parquet_files":unknown,
            "issues":problems,
            "latest_filename":(sorted((x["name"] for x in annual+monthly))[-1]
                               if annual or monthly else None),
            "total_physical_rows_footer":sum(x["rows"] for x in annual+monthly),
        }
    return response

def validate_schema(schema):
    import pyarrow as pa
    expected={"ts":pa.int64(),"symbol":pa.string(),
              **{field:pa.float64() for field in COLS[2:]}}
    if (any(field not in schema.names or schema.field(field).type!=dtype
            for field,dtype in expected.items())
            or len(schema.names)!=len(set(schema.names))):
        raise ValueError("Local Parquet schema lacks compatible canonical eight Arrow fields")

def normal_symbol(value):
    if type(value) is not str:
        raise ValueError("Invalid physical security symbol type")
    v=value.strip().upper()
    m=re.fullmatch(r"(SH|SZ|BJ)(\d{6})",v)
    if m:
        return m.group(1)+m.group(2)
    m=re.fullmatch(r"(\d{6})[.:-](SH|SZ|BJ|XSHG|XSHE|BSE)",v)
    if m:
        return {"XSHG":"SH","XSHE":"SZ","BSE":"BJ"}.get(m.group(2),m.group(2))+m.group(1)
    # Other original symbols (indexes, special formats) must be preserved
    # unchanged. They never collide silently with a new normal A-share.
    if not v:
        raise ValueError("Empty original security identifier")
    return v

def symbol_style(table):
    # Existing monthly Parquet sometimes stores SH600000 and sometimes
    # vendor "600000.SH". Reject mixed conventions for an A-share new row
    # rather than writing a third incompatible symbol spelling.
    values=table["symbol"].to_pylist()
    samples=[v for v in values if isinstance(v,str)
             and (re.fullmatch(r"(SH|SZ|BJ)\d{6}",v.upper())
                  or re.fullmatch(r"\d{6}[.:-](SH|SZ|BJ)",v.upper()))]
    prefix=sum(bool(re.fullmatch(r"(SH|SZ|BJ)\d{6}",v.upper())) for v in samples)
    suffix=sum(bool(re.fullmatch(r"\d{6}[.:-](SH|SZ|BJ)",v.upper())) for v in samples)
    if prefix and suffix:
        raise ValueError("Existing purchased stock symbols use mixed suffix/prefix formats")
    if suffix:
        return "suffix"
    return "prefix"

def market_ts_day(stamp):
    if type(stamp) is not int:
        raise ValueError("Original Parquet milliseconds must be int")
    return datetime.fromtimestamp(stamp/1000,tz=UTC8).date()

def checked_records(table,*,target_year=None,target_month=None):
    validate_schema(table.schema)
    keys=set()
    for i,(ts,sym) in enumerate(zip(table["ts"].to_pylist(),
                                    table["symbol"].to_pylist())):
        day=market_ts_day(ts)
        if (target_year is not None and day.year!=target_year
                or target_month is not None and day.month!=target_month):
            raise ValueError("Original/incoming timestamp is outside target Parquet year-month")
        key=(ts,normal_symbol(sym))
        if key in keys:
            raise ValueError("Duplicate normalized (symbol,timestamp) in source Parquet")
        keys.add(key)
    return keys

def in_original_schema(incoming,original_schema,style):
    import pyarrow as pa
    standard=incoming
    if style=="suffix":
        converted=[]
        for sym in incoming["symbol"].to_pylist():
            v=normal_symbol(sym)
            if re.fullmatch(r"(SH|SZ|BJ)\d{6}",v) is None:
                raise ValueError("New symbol cannot be styled to local original format")
            converted.append(v[2:]+"."+v[:2])
        standard=incoming.set_column(
            incoming.schema.get_field_index("symbol"),"symbol",
            pa.array(converted,type=pa.string()))
    arrays=[]
    for field in original_schema:
        if field.name in standard.column_names:
            arrays.append(standard[field.name].cast(field.type))
        else:
            if not field.nullable:
                raise ValueError("Cannot invent nonnullable vendor extra field: "+field.name)
            arrays.append(pa.nulls(standard.num_rows,type=field.type))
    return pa.Table.from_arrays(arrays,schema=original_schema)

def merge_month_tables(existing,new_rows,*,period,year,month):
    import pyarrow as pa
    if period not in PERIODS:
        raise ValueError("Unknown K-line period")
    validate_schema(new_rows.schema)
    existing_keys=checked_records(existing,target_year=year,target_month=month)
    new_keys=checked_records(new_rows,target_year=year,target_month=month)
    if not len(new_keys):
        return existing,{"added":0,"same_key":0}
    style=symbol_style(existing) if existing.num_rows else "prefix"
    adapted=in_original_schema(new_rows,existing.schema if existing.num_rows else new_rows.schema,style)
    new_ts=adapted["ts"].to_pylist()
    new_sym=adapted["symbol"].to_pylist()
    insert_idx=[]
    overlaps=0
    for ix,(stamp,sym) in enumerate(zip(new_ts,new_sym)):
        if (stamp,normal_symbol(sym)) in existing_keys:
            overlaps+=1
        else:
            insert_idx.append(ix)
    if insert_idx:
        new_only=adapted.take(pa.array(insert_idx,type=pa.int64()))
        combined=pa.concat_tables([existing,new_only],promote_options="none")
        order=pa.compute.sort_indices(
            combined,sort_keys=[("ts","ascending"),("symbol","ascending")])
        merged=combined.take(order)
    else:
        merged=existing
    if len(checked_records(merged,target_year=year,target_month=month)) != (
            len(existing_keys)+len(insert_idx)):
        raise ValueError("Merging original/new Parquet key counts failed")
    return merged,{"added":len(insert_idx),"same_key":overlaps}

def parquet_reader(path):
    import pyarrow.parquet as pq
    reader=pq.ParquetFile(path)
    try:
        validate_schema(reader.schema_arrow)
        return reader.schema_arrow,reader.metadata.num_rows
    finally:
        reader.close()

def safe_private_backup(path,workspace):
    """Private SHA backup before modifying a prior market Parquet file."""
    path=Path(path)
    if not path.exists():
        return None
    if path.is_symlink():
        raise ValueError("Linked market Parquet cannot be backed up or replaced")
    digest=hash_file(path)
    parent=Path(workspace)/"backups"/path.parent.name
    parent.mkdir(parents=True,exist_ok=True)
    target=parent/(path.stem+"-"+digest[:16]+".parquet")
    if target.is_symlink():
        raise ValueError("Linked market backup refused")
    if target.exists():
        if hash_file(target)!=digest:
            raise ValueError("Previously created private market backup SHA differs")
    else:
        staging=target.with_suffix(".copying")
        if staging.is_symlink():
            raise ValueError("Linked temporary market backup refused")
        if staging.exists():
            staging.unlink()
        shutil.copyfile(path,staging)
        if hash_file(staging)!=digest:
            raise ValueError("Backup copied bytes differ from original market data")
        os.replace(staging,target)
    return {"path":str(target),"sha256":digest}

def write_month(root,period,year,month,new_rows,workspace,*,current_year=None):
    """Safe actual physical MONTH upsert, with fail-closed original precedence.

    Caller must hold the ParquetLiveSync OS single-writer lock. A month has
    manageable data size; for billion-row minutes use separate streamed
    monthly aggregation to avoid loading 1min whole-year into memory.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    current_year=current_year or datetime.now(UTC8).year
    if not 1<=month<=12 or year!=current_year:
        raise ValueError("Direct monthly update must target current year")
    if period not in PERIODS:
        raise ValueError("Unsupported source K-line period")
    storage=storage_root(root)
    target=storage/period/(f"{year}-{month:02}.parquet")
    annual=storage/period/(f"{year}.parquet")
    if annual.exists() or annual.is_symlink():
        raise ValueError("Current-year annual file exists; would double-count with month")
    if target.is_symlink():
        raise ValueError("Linked physical market Parquet output refused")
    if target.exists():
        schema,old_count=parquet_reader(target)
        existing=pq.read_table(target)
        validate_schema(existing.schema)
    else:
        existing=pa.Table.from_batches([],schema=new_rows.schema)
    merged,counts=merge_month_tables(
        existing,new_rows,period=period,year=year,month=month)
    # No new rows means no need to rewrite or hash the existing local file.
    if counts["added"]==0:
        return {"target":str(target),"added":0,"same_key":counts["same_key"],
                "total_rows":merged.num_rows,"unchanged":True,
                "sha256":hash_file(target) if target.exists() else None}
    backup=safe_private_backup(target,workspace)
    scratch=target.with_suffix(".parquet.live-sync-part")
    if scratch.is_symlink():
        raise ValueError("Linked Parquet staging file")
    if scratch.exists():
        scratch.unlink()
    pq.write_table(merged,scratch,compression="zstd",row_group_size=65536)
    schema,written=parquet_reader(scratch)  # closes reader before Windows rename
    if schema!=merged.schema or written!=merged.num_rows:
        raise ValueError("Staged monthly Parquet footer failed")
    readback=pq.read_table(scratch)
    if not readback.equals(merged,check_metadata=False):
        raise ValueError("Monthly Parquet full readback differs from merged Arrow table")
    expected_digest=hash_file(scratch)
    # Existing original must still have identical bytes to the protected
    # backup; a third-party writer may not race this transaction.
    if target.exists() and hash_file(target)!=backup["sha256"]:
        raise ValueError("Original market month changed while staging")
    os.replace(scratch,target)
    if hash_file(target)!=expected_digest:
        raise ValueError("Atomic final monthly Parquet output SHA drift")
    return {"target":str(target),"year":year,"month":month,
            "period":period,"added":counts["added"],"same_key":counts["same_key"],
            "total_rows":merged.num_rows,"unchanged":False,
            "sha256":expected_digest,"original_backup":backup}

def archive_year(root,period,year,workspace,*,current_year=None,apply=False):
    """One-time, streaming 12-month -> annual Parquet; explicit opt-in only.

    Monthly fragments are backed up and preserved in WORK before removal.
    Never silently archive active-year monthly files. All twelve original
    months must be present. Annual output is readback checked before cleanup.
    """
    import pyarrow.parquet as pq
    current_year=current_year or datetime.now(UTC8).year
    if period not in PERIODS or not 2011<=year<current_year:
        raise ValueError("Only complete past years can be archived")
    folder=storage_root(root)/period
    files=[folder/(f"{year}-{m:02}.parquet") for m in range(1,13)]
    if not all(p.is_file() and not p.is_symlink() for p in files):
        raise ValueError("Yearly archive requires twelve valid original month files")
    yearfile=folder/(f"{year}.parquet")
    if yearfile.exists() or yearfile.is_symlink():
        raise ValueError("Existing annual file already present; refuse overwrite/duplicate")
    metas=[parquet_reader(p) for p in files]
    schemas=[m[0] for m in metas]
    if len(set(schemas))!=1:
        raise ValueError("Inconsistent Parquet schema across year months")
    rows_expected=sum(n for _,n in metas)
    if not apply:
        return {"year":year,"period":period,"monthly_files":12,
                "expected_rows":rows_expected,"action":"PREVIEW_ONLY"}
    scratch=yearfile.with_suffix(".parquet.annual-part")
    if scratch.is_symlink() or scratch.exists():
        raise ValueError("Existing annual scratch file; prior rollover needs inspection")
    writer=None
    seen=set()
    try:
        writer=pq.ParquetWriter(str(scratch),schemas[0],compression="zstd")
        for idx,path in enumerate(files,1):
            p=pq.ParquetFile(path)
            try:
                for batch in p.iter_batches(batch_size=32768):
                    table=batch.to_table() if hasattr(batch,"to_table") else None
                    # pyarrow RecordBatch.to_table is available on modern Arrow;
                    # fallback is explicit Table.from_batches for portability.
                    if table is None:
                        import pyarrow as pa
                        table=pa.Table.from_batches([batch],schema=schemas[0])
                    checked_records(table,target_year=year,target_month=idx)
                    for ts,sym in zip(table["ts"].to_pylist(),table["symbol"].to_pylist()):
                        key=(ts,normal_symbol(sym))
                        if key in seen:
                            raise ValueError("Duplicate key across source months")
                        seen.add(key)
                    writer.write_table(table)
            finally:
                p.close()
    finally:
        if writer is not None:
            writer.close()
    schema,rows=parquet_reader(scratch)
    if schema!=schemas[0] or rows!=rows_expected or rows!=len(seen):
        raise ValueError("Yearly stitched Parquet footer/key total differs from 12 months")
    backups=[safe_private_backup(p,Path(workspace)/"rollover"/str(year))
             for p in files]
    annual_digest=hash_file(scratch)
    os.replace(scratch,yearfile)
    if hash_file(yearfile)!=annual_digest:
        raise ValueError("Verified yearly annual source file differs after commit")
    # Original months are retained in private SHA backups for rollback, but
    # moved out of the canonical AllCycleAStockData period folder so there
    # is ONLY one physical year file. This invalidates legacy manifests that
    # hard-reference original month files; old snapshots are not rewritten.
    for path,backup in zip(files,backups):
        if hash_file(path)!=backup["sha256"]:
            raise ValueError("Market month changed after annual output commit")
        path.unlink()
    return {"year":year,"period":period,"annual_file":str(yearfile),
            "rows":rows,"sha256":annual_digest,"monthly_backups":backups,
            "archive_note":"Legacy pinned external physical manifests pointing at these monthly paths must be rebased separately"}
