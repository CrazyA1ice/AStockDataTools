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
import sqlite3
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
    transactions=Path(workspace)/"transactions"/period
    transactions.mkdir(parents=True,exist_ok=True)
    journal=transactions/(f"{year}-{month:02}.json")
    prior_digest=backup["sha256"] if backup is not None else None
    if journal.is_symlink():
        raise ValueError("Linked local physical market Parquet transaction journal")
    if journal.exists():
        previous=json.loads(journal.read_bytes())
        if (previous.get("period")!=period or
                previous.get("year")!=year or
                previous.get("month")!=month or
                prior_digest not in (previous.get("new_sha256"),
                                     previous.get("old_sha256"))):
            # Either the prior atomic swap completed (new_sha) or it was
            # interrupted before the swap (old_sha), allowing replay.
            # Any unrelated external modification must fail closed.
            raise ValueError("Physical month differs from previous protected transaction")
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
    journal_doc={"format":"market_parquet_derived_month_physical_swap_v1",
                 "period":period,"year":year,"month":month,
                 "old_sha256":prior_digest,"new_sha256":expected_digest,
                 "original_backup":backup,"expected_rows":merged.num_rows}
    temporary_journal=journal.with_suffix(".json.part")
    if temporary_journal.is_symlink():
        raise ValueError("Linked month journal temporary path")
    temporary_journal.write_text(
        json.dumps(journal_doc,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    os.replace(temporary_journal,journal)
    os.replace(scratch,target)
    if hash_file(target)!=expected_digest:
        raise ValueError("Atomic final monthly Parquet output SHA drift")
    return {"target":str(target),"year":year,"month":month,
            "period":period,"added":counts["added"],"same_key":counts["same_key"],
            "total_rows":merged.num_rows,"unchanged":False,
            "sha256":expected_digest,"original_backup":backup}

def archive_year(root,period,year,workspace,*,current_year=None,apply=False):
    """12 verified monthly shards -> one annual; original months SHA-backed.

    Strictly prior year. Supports crash recovery after annual rename and
    between month removals. Never modifies H5 or historical Parquet dates.
    Uses disk-based SQLite uniqueness index to bound memory on 1min data.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    current_year=current_year or datetime.now(UTC8).year
    if period not in PERIODS or not 2011<=year<current_year:
        raise ValueError("Only complete past years can be archived")
    folder=storage_root(root)/period
    files=[folder/(f"{year}-{m:02}.parquet") for m in range(1,13)]
    yearfile=folder/(f"{year}.parquet")
    record_dir=Path(workspace)/"rollover"/str(year)
    record_dir.mkdir(parents=True,exist_ok=True)
    plan=record_dir/(period+"-annual-commit.json")
    if yearfile.is_symlink() or plan.is_symlink():
        raise ValueError("Linked annual market Parquet or receipt not supported")
    if plan.exists():
        receipt=json.loads(plan.read_bytes())
        if (receipt.get("period")!=period or receipt.get("year")!=year
                or not yearfile.is_file()
                or hash_file(yearfile)!=receipt.get("annual_sha256")):
            raise ValueError("Interrupted yearly archive annual bytes differ from receipt")
        if apply:
            for month_file,item in zip(files,receipt["original_months"]):
                backup=Path(item["backup_path"])
                if (not backup.is_file() or backup.is_symlink()
                        or hash_file(backup)!=item["sha256"]):
                    raise ValueError("Archive backup lost or corrupted; cannot remove original month")
                if month_file.exists():
                    if (month_file.is_symlink()
                            or hash_file(month_file)!=item["sha256"]):
                        raise ValueError("Original month has changed since yearly archive")
                    month_file.unlink()
        return {"period":period,"year":year,"annual_file":str(yearfile),
                "rows":receipt["rows"],"sha256":receipt["annual_sha256"],
                "action":"VERIFIED_PREVIOUS_ARCHIVE" if apply else "ALREADY_ARCHIVED"}

    if yearfile.exists():
        if any(path.exists() or path.is_symlink() for path in files):
            raise ValueError("Annual and monthly Parquet of the same year coexist")
        if yearfile.is_symlink() or not yearfile.is_file():
            raise ValueError("Untrusted physical annual Parquet path")
        _,count=parquet_reader(yearfile)
        return {"period":period,"year":year,"annual_file":str(yearfile),
                "rows":count,"sha256":hash_file(yearfile),
                "action":"ALREADY_ANNUAL_NO_CHANGES"}
    if not all(path.is_file() and not path.is_symlink() for path in files):
        raise ValueError("Yearly rollover requires twelve complete original months")
    metas=[parquet_reader(p) for p in files]
    schema=metas[0][0]
    if any(info[0]!=schema for info in metas):
        raise ValueError("Monthly physical source schemas differ; cannot archive")
    expected=sum(n for _,n in metas)
    if expected<=0:
        raise ValueError("Cannot archive empty year")
    if not apply:
        return {"period":period,"year":year,"month_files":12,
                "expected_rows":expected,"action":"PREVIEW_ONLY"}
    original_bytes=sum(p.stat().st_size for p in files)
    if shutil.disk_usage(folder).free<original_bytes*1.20+100000000:
        raise ValueError("Not enough disk for one new annual physical Parquet")
    if shutil.disk_usage(record_dir).free<original_bytes*1.10+100000000:
        raise ValueError("Not enough disk for twelve SHA-pinned original month backups")
    scratch=yearfile.with_suffix(".parquet.annual-part")
    if scratch.exists() or scratch.is_symlink():
        raise ValueError("Existing annual temp file needs manual inspection")
    index=record_dir/(period+"-unique-keys.sqlite3")
    if index.exists() or index.is_symlink():
        raise ValueError("Existing archive key-index scratch needs inspection")
    db=sqlite3.connect(str(index))
    writer=None
    observed=0
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("CREATE TABLE seen (ts INTEGER NOT NULL, sym TEXT NOT NULL,"
                   "PRIMARY KEY(ts,sym)) WITHOUT ROWID")
        writer=pq.ParquetWriter(str(scratch),schema,compression="zstd")
        for month,file in enumerate(files,1):
            reader=pq.ParquetFile(file)
            try:
                for batch in reader.iter_batches(batch_size=32768):
                    chunk=pa.Table.from_batches([batch],schema=schema)
                    checked_records(chunk,target_year=year,target_month=month)
                    keys=[(ts,normal_symbol(sym)) for ts,sym in zip(
                        chunk["ts"].to_pylist(),chunk["symbol"].to_pylist())]
                    try:
                        db.executemany("INSERT INTO seen(ts,sym) VALUES(?,?)",keys)
                    except sqlite3.IntegrityError as exc:
                        raise ValueError("Duplicated original annual stock-time key") from exc
                    observed+=len(keys)
                    writer.write_table(chunk)
            finally:
                reader.close()
        db.commit()
    finally:
        if writer is not None:
            writer.close()
        db.close()
        index.unlink(missing_ok=True)
    result_schema,result_rows=parquet_reader(scratch)
    if (result_schema!=schema or result_rows!=expected
            or observed!=expected):
        raise ValueError("Annual staged Parquet footer/key conservation failed")
    backups=[safe_private_backup(p,record_dir) for p in files]
    receipt={
        "format":"annual_native_parquet_monthly_12_to_year_v1",
        "period":period,"year":year,"rows":expected,
        "annual_sha256":hash_file(scratch),
        "original_months":[{"name":p.name,"sha256":item["sha256"],
                            "backup_path":item["path"]}
                           for p,item in zip(files,backups)],
        "old_8cycle_manifest_references_not_rewritten":True,
    }
    tmp=plan.with_suffix(".json.part")
    if tmp.is_symlink():
        raise ValueError("Annual plan temporary path is linked")
    tmp.write_text(json.dumps(receipt,ensure_ascii=False,
                              sort_keys=True,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp,plan)
    os.replace(scratch,yearfile)
    if hash_file(yearfile)!=receipt["annual_sha256"]:
        raise ValueError("Annual physical file SHA drift")
    # Plan has been durably written; any interruption can now be resumed
    # from the same source/receipt (no annual rebuild and no data loss).
    return archive_year(root,period,year,workspace,
                        current_year=current_year,apply=True)

def rollover_all_periods(root,year,workspace,*,current_year=None,apply=False):
    """Perform archive of ALL EIGHT periods only when all are ready.

    A period that was already archived with an accepted receipt can be
    skipped on retry. Never consolidate a partial/incomplete year into an
    annual shard. A separate opt-in command should invoke apply=True.
    """
    current_year=current_year or datetime.now(UTC8).year
    checks={}
    for period in PERIODS:
        checks[period]=archive_year(root,period,year,workspace,
                                    current_year=current_year,apply=False)
    if not apply:
        return {"year":year,"ready_periods":len(checks),
                "action":"PREVIEW_ALL_EIGHT","periods":checks}
    outcomes={}
    for period in PERIODS:
        outcomes[period]=archive_year(root,period,year,workspace,
                                      current_year=current_year,apply=True)
    return {"year":year,"archived_periods":len(outcomes),
            "action":"COMMITTED_ALL_EIGHT","periods":outcomes}

def open_local_layout_dataset(root,period):
    """Real native AllCycleAStockData physical files, independent of old SHA
    snapshot references, returning a typed Arrow Dataset of the eight columns.
    """
    import pyarrow as pa
    import pyarrow.dataset as ds
    if period not in PERIODS:
        raise ValueError("Unsupported Parquet K-line period")
    base=storage_root(root)/period
    files=sorted(path for path in base.glob("*.parquet")
                 if classify_filename(path.name) is not None)
    if not files:
        raise ValueError("No native physical Parquet files in local period")
    years=Counter()
    for path in files:
        yr,mo=classify_filename(path.name)
        years[(yr,"annual" if mo is None else "monthly")]+=1
        if path.is_symlink() or not path.is_file():
            raise ValueError("Linked or missing native stock Parquet source")
    if any(years.get((y,"annual"),0) and years.get((y,"monthly"),0)
           for y,_ in years):
        raise ValueError("Annual and monthly physical Parquet for same year coexist")
    schema=pa.schema([pa.field("ts",pa.int64()),
                      pa.field("symbol",pa.string()),
                      *(pa.field(k,pa.float64()) for k in COLS[2:])])
    for path in files:
        original,_=parquet_reader(path)
        validate_schema(original)
    return ds.dataset([str(p) for p in files],format="parquet",schema=schema)
