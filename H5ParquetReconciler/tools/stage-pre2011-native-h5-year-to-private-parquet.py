#!/usr/bin/env python3
"""1990..2010 H5 exact native integer day rows -> NEW isolated private Parquet.

This stage deliberately stores all ORIGINAL H5 integer columns losslessly.
They are NOT normalized to purchased OHLCVA scale: Hikyuu price/volume/amount
unit hypotheses and historic corporate actions remain uncertified.
No original purchased Parquet/H5 file, active pointer, production routing, or
previous immutable version is ever modified by this tool.

--action plan: recheck real all-market date-key inventory + all purchased
  day-file timestamp footers against previously verified SAFE; no market writes.
--action stage --allow-private-raw-parquet: repeat the same gate, stream one
  original H5 historical year to a NEW private Parquet file, fully read back
  and compare all scalar integers + row digest, and publish only SAFE counts.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
REPORTS=MODULE/"reports"
PRIVATE=MODULE/"work"/"unified_parquet"/"pre2011_native_h5_raw"
FORMAT="AStockDataTools verified source-native H5 historical daily Parquet stage v1"
PRIVATE_FORMAT="AStockDataTools private raw H5 pre2011 year Parquet manifest v1"
FIELDS=("symbol","datetime","openPrice","highPrice","lowPrice",
        "closePrice","transCount","transAmount")
REQUIRED_NUMERIC=FIELDS[1:]
MAX_YEAR_ROWS=500000
CHUNK=8192


def load_inventory():
    spec=importlib.util.spec_from_file_location(
        "pre2011_exact_source_evidence",
        HERE/"inventory-pre2011-h5-parquet-day-readonly.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AUDIT=load_inventory()


def audit_file(path):
    p=Path(path)
    if (p.is_symlink() or not p.is_file() or p.resolve().parent!=REPORTS.resolve()
            or p.suffix.lower()!=".json" or p.stat().st_size>1024*1024):
        raise ValueError("Must supply existing bounded 1990-2010 SAFE in module reports")
    raw=p.read_bytes()
    entry=json.loads(raw)
    if (not isinstance(entry,dict) or entry.get("format")!=AUDIT.FORMAT
            or entry.get("status")!="pre2011_full_source_day_timestamp_coverage_inventory_not_staged"
            or entry.get("historical_inclusive_start")!="1990-01-01"
            or entry.get("historical_inclusive_end")!="2010-12-31"
            or entry.get("original_market_files_modified") is not False
            or entry.get("pre2011_h5_to_new_private_parquet_authorized") is not False
            or entry.get("private_active_pointers_read_or_modified") is not False
            or entry.get("production_query_route_modified") is not False):
        raise ValueError("Only complete, unchanged-source pre2011 SAFE qualifies")
    return entry,hashlib.sha256(raw).hexdigest()


def new_safe(out):
    target=Path(out)
    if (REPORTS.is_symlink() or target.is_symlink() or target.exists()
            or target.suffix.lower()!=".json"
            or target.resolve().parent!=REPORTS.resolve()):
        raise ValueError("New SAFE must be directly inside module reports")
    return target.resolve()


def private_folder(path):
    p=Path(path)
    if (any(x.is_symlink() for x in
            (MODULE/"work",MODULE/"work"/"unified_parquet",PRIVATE))
            or p.is_symlink() or p.exists()
            or not re.fullmatch(r"native_pre2011_[0-9]{4}_[a-f0-9]{12,32}",p.name)
            or p.resolve().parent!=PRIVATE.resolve()):
        raise ValueError("Private output must be unused native_pre2011_<year>_<hex> direct child")
    return p.resolve()


def sources_unchanged(before_h5,before_pq):
    if (any(AUDIT.state(p)!=v for p,v in before_h5.items())
            or any(AUDIT.state(p)!=v for p,v in before_pq.items())):
        raise ValueError("Original H5/PQ changed during year stage")


def requalify(root,reference):
    h5,hfiles=AUDIT.inspect_h5(root)
    pq,pfiles=AUDIT.inspect_purchased(root)
    if (h5!=reference.get("original_h5")
            or pq!=reference.get("original_purchased_parquet")
            or pq["no_pre2011_parquet_rows_proven_by_complete_footer_bounds"] is not True
            or pq["nonempty_row_groups_without_ts_stats"]!=0):
        raise ValueError("Historical source report no longer matches real H5/PQ keys and footers")
    sources_unchanged(hfiles,pfiles)
    return h5,pq,hfiles,pfiles


def schema(pa):
    return pa.schema([pa.field("symbol",pa.string()),
                      *(pa.field(x,pa.uint64()) for x in REQUIRED_NUMERIC)])


def row_bytes(row):
    return (json.dumps([row[k] for k in FIELDS],ensure_ascii=True,
                       separators=(",",":"),allow_nan=False)+"\n").encode()


def iterate_native_year(root,year):
    """Yield original scalar uints; H5 source chronology prechecked by requalify."""
    import h5py
    low=year*100000000
    high=(year+1)*100000000
    for market in ("sh","sz","bj"):
        p=root/"HikyuuData"/(market+"_day.h5")
        if not p.is_file():
            continue
        with h5py.File(p,"r") as source:
            group=source["data"]
            for symbol in sorted(group):
                if (not re.fullmatch(market.upper()+r"[0-9]{6}",symbol)
                        or not AUDIT.CORE.is_a_share_candidate(symbol,2010)):
                    continue
                ds=group[symbol]
                if (not set(AUDIT.CORE.H5_FIELDS).issubset(ds.dtype.names or ())
                        or ds.ndim!=1):
                    raise ValueError("H5 source schema changed from full source audit")
                left,right=AUDIT.CORE.h5_key_slice(ds,low,high)
                last_key=None
                for begin in range(left,right,CHUNK):
                    block=ds[begin:min(right,begin+CHUNK)]
                    for original in block:
                        row={"symbol":symbol}
                        for field in REQUIRED_NUMERIC:
                            value=int(original[field])
                            if value<0 or value>2**64-1:
                                raise ValueError("H5 native unsigned integer field out of range")
                            row[field]=value
                        key=row["datetime"]
                        if not low<=key<high or key%10000:
                            raise ValueError("Wrong historical year or non-daily timestamp")
                        try:
                            dt=date(key//100000000,
                                (key//1000000)%100,(key//10000)%100)
                        except ValueError:
                            raise ValueError("Invalid original H5 day timestamp") from None
                        if dt.year!=year or (last_key is not None and key<=last_key):
                            raise ValueError("Original H5 day year keys out of order")
                        last_key=key
                        # Deliberate raw storage, no guessed price/volume/amount conversion.
                        yield row


def stage_year(root,year,target,expected):
    import pyarrow as pa
    import pyarrow.parquet as pq
    target.parent.mkdir(parents=True,exist_ok=True)
    target.mkdir(exist_ok=False)
    file=target/"h5-native-day.parquet"
    writer=None
    n=0
    initial=hashlib.sha256()
    markets=Counter()
    try:
        writer=pq.ParquetWriter(file,schema(pa),compression="zstd",
                                version="2.6")
        buffer=[]
        for row in iterate_native_year(root,year):
            initial.update(row_bytes(row))
            buffer.append(row)
            markets[row["symbol"][:2]]+=1
            n+=1
            if n>MAX_YEAR_ROWS or n>expected:
                raise ValueError("Historical year exceeds audited H5 native row budget")
            if len(buffer)>=CHUNK:
                writer.write_table(pa.Table.from_pylist(buffer,schema=schema(pa)),
                                   row_group_size=CHUNK)
                buffer.clear()
        if buffer:
            writer.write_table(pa.Table.from_pylist(buffer,schema=schema(pa)),
                               row_group_size=CHUNK)
        writer.close()
        writer=None
        if n!=expected:
            raise ValueError("Private native H5 year count differs from 1990-2010 audited keys")
        if n==0:
            raise ValueError("Historical private year staging needs nonempty audited H5 year")
        pf=pq.ParquetFile(file)
        try:
            if tuple(pf.schema_arrow.names)!=FIELDS or pf.metadata.num_rows!=n:
                raise ValueError("Private native Parquet schema/count changed")
            decoded=0
            readhash=hashlib.sha256()
            for batch in pf.iter_batches(batch_size=CHUNK,columns=list(FIELDS)):
                for row in batch.to_pylist():
                    if (not isinstance(row["symbol"],str)
                            or any(type(row[k]) is not int or row[k]<0
                                   for k in REQUIRED_NUMERIC)):
                        raise ValueError("Private raw Parquet row malformed")
                    readhash.update(row_bytes(row))
                    decoded+=1
            if decoded!=n or readhash.digest()!=initial.digest():
                raise ValueError("Full private Parquet field-by-field source roundtrip failed")
        finally:
            pf.close()
        return {"year":year,"raw_h5_stockday_rows":n,
                "per_market_rows":dict(sorted(markets.items())),
                "raw_row_stream_sha256":initial.hexdigest(),
                "full_private_parquet_sha256":AUDIT.hashlib.sha256(
                    file.read_bytes()).hexdigest(),
                "private_parquet_schema":"native_uint64_all_ohlcva_no_renormalization"}
    finally:
        if writer is not None:
            writer.close()


def run(root,inventory_report,year,out,action,folder=None,allow_stage=False):
    root=Path(root).resolve()
    safe=new_safe(out)
    if (not root.is_dir() or MODULE.is_relative_to(root)
            or type(year) is not int or not 1990<=year<=2010
            or action not in ("plan","stage")
            or (action=="stage" and not allow_stage)
            or (action=="plan" and (allow_stage or folder is not None))):
        raise ValueError("Historical year/safe source/action authorization rejected")
    private=private_folder(folder) if action=="stage" else None
    reference,sha=audit_file(inventory_report)
    h5,pq,hfiles,pfiles=requalify(root,reference)
    exp=h5["yearly_source_key_inventory"][str(year)]["H5_candidate_stockday_rows"]
    if not 0<=exp<=MAX_YEAR_ROWS:
        raise ValueError("Audited historical year exceeds private stage budget")
    result=None
    if action=="stage":
        if not exp:
            raise ValueError("Selected historical year contains zero native H5 rows")
        try:
            result=stage_year(root,year,private,exp)
            sources_unchanged(hfiles,pfiles)
            with (private/"manifest.json").open("x",encoding="utf-8") as stream:
                json.dump({"format":PRIVATE_FORMAT,**result,
                           "inventory_report_sha256":sha,
                           "purchased_parquet_footer_no_pre2011_rows":True,
                           "private_normalized_purchased_schema":False,
                           "H5_native_quantity_and_amount_units_certified":False,
                           "H5_original_source_modified":False,
                           "purchased_parquet_original_modified":False,
                           "production_or_private_active_pointer_changed":False},
                          stream,sort_keys=True,ensure_ascii=False,indent=2)
                stream.write("\n")
        except Exception:
            # Private target is a new, exclusively created folder. Remove only
            # our incomplete private output; never touch a market-source path.
            if private.exists():
                shutil.rmtree(private)
            raise
    sources_unchanged(hfiles,pfiles)
    summary={
        "format":FORMAT,"action":action,
        "status":("source_native_h5_year_parquet_staged_not_normalized_not_activated"
                  if result else "pre2011_original_sources_requalified_year_plan"),
        "audited_year":year,
        "audited_h5_native_stockday_rows":exp,
        "pre2011_h5_all_year_stockday_rows":
            h5["pre2011_candidate_h5_stockday_rows"],
        "historical_earliest_h5_day":h5["earliest_pre2011_candidate_h5_date"],
        "historical_latest_h5_day":h5["latest_pre2011_candidate_h5_date"],
        "purchased_day_file_count":pq["source_day_parquet_files_scanned"],
        "purchased_day_row_group_count":pq["source_day_row_groups_scanned"],
        "purchased_day_ts_earliest_footer":pq[
            "earliest_all_stock_footer_candidate_day"],
        "purchased_no_pre2011_day_keys_proven_by_all_footers":True,
        "inventory_report_sha256":sha,
        "new_raw_private_year_parquet_created":result is not None,
        "private_raw_source_row_digest":(
            result["raw_row_stream_sha256"] if result else None),
        "private_raw_parquet_sha256":(
            result["full_private_parquet_sha256"] if result else None),
        "private_normalized_purchased_schema":False,
        "H5_legacy_price_volume_amount_scale_not_certified":True,
        "historical_security_master_or_trading_calendar_not_certified":True,
        "raw_private_stage_is_not_a_usable_purchased_day_overlay":True,
        "original_h5_and_purchased_parquet_modified":False,
        "private_active_pointer_or_production_query_modified":False,
        "h5_native_mirror_created":False,
        "no_stock_codes_source_paths_or_raw_market_values_in_safe":True,
    }
    with safe.open("x",encoding="utf-8") as output:
        json.dump(summary,output,sort_keys=True,indent=2,ensure_ascii=False)
        output.write("\n")
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--inventory-report",type=Path,required=True)
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--action",choices=("plan","stage"),required=True)
    p.add_argument("--private-dir",type=Path)
    p.add_argument("--allow-private-raw-parquet",action="store_true")
    p.add_argument("--read-only-market-sources",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=run(a.root,a.inventory_report,a.year,a.out,a.action,
                   a.private_dir,a.allow_private_raw_parquet)
        print("Historical H5 native year SAFE:",a.out)
        print("Year:",a.year,"audited original H5 rows:",
              result["audited_h5_native_stockday_rows"])
        print("New private RAW H5 integer Parquet:",
              result["new_raw_private_year_parquet_created"])
        print("NO change to original PQ/H5, private active or production routes.")
        print("RAW native integer stage is NOT purchased normalized day schema.")
    except (ValueError,KeyError,TypeError,OSError,OverflowError,
            ImportError,ModuleNotFoundError) as exc:
        p.error(str(exc))


if __name__=="__main__":
    main()
