#!/usr/bin/env python3
"""Independent private historical physical year audit; never opens purchased/H5 originals.

Validates a completed 2011..2025 private physical annual SAFE, its immutable
manifest, every row of purchased plus the optional 2016 single H5 candidate,
float64 source digest and exact SQLite stockday index mapping. It cannot
certify supplier currency/rounding or authorize a production database.
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
def load():
    spec=importlib.util.spec_from_file_location(
        "independent_historical_private_physical_builder",
        HERE/"materialize-private-2011-2025-purchased-year.py")
    o=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(o)
    return o

M=load()
PHYS=M.PHYS
FORMAT="AStockDataTools independent private historical physical DAY year audit v1"


def source(safe):
    p=Path(safe)
    if (M.REPORTS.is_symlink() or p.is_symlink()
            or p.suffix.lower()!=".json"
            or p.resolve().parent!=M.REPORTS.resolve()
            or not p.is_file() or not 0<p.stat().st_size<=1000000):
        raise ValueError("Only existing module historical physical SAFE accepted")
    raw=p.read_bytes()
    doc=json.loads(raw)
    year=doc.get("year")
    if (type(doc) is not dict or type(year) is not int
            or not 2011<=year<=2025
            or doc.get("format")!=M.FORMAT
            or doc.get("status")!=
               "private_purchased_historical_day_physical_year_not_activated"
            or type(doc.get("purchased_original_rows")) is not int
            or not 0<doc["purchased_original_rows"]<=M.PHYS.MAX_ROWS
            or doc.get("h5_mixed_candidate_rows")!=(1 if year==2016 else 0)
            or doc.get("total_private_physical_rows")!=(
                doc["purchased_original_rows"]+(year==2016))
            or doc.get("original_float64_roundtrip_exact") is not True
            or doc.get("no_market_ohlcva_or_symbols_in_safe") is not True
            or any(doc.get(k) is not False for k in (
                "original_market_files_written","original_purchased_parquet_replaced",
                "private_or_production_active_pointer_modified",
                "candidate_source_units_certified","ready_for_production_query",
                "ready_for_automatic_market_merge","ready_for_h5_mirror"))):
        raise ValueError("Incomplete or production-authorized historical SAFE")
    for k in ("private_manifest_sha256","private_sqlite_sha256",
              "source_purchased_original_parquet_sha256",
              "source_candidate_safe_sha256","source_candidate_version_sha256"):
        if not re.fullmatch("[0-9a-f]{64}",str(doc.get(k))):
            raise ValueError("Invalid purchased/H5 historical source pin")
    if doc["source_candidate_version_sha256"]!=M.SOURCE_VERSION:
        raise ValueError("Historic private candidate source version changed")
    rel=doc.get("private_relative_directory")
    if (type(rel) is not str or not re.fullmatch(
            f"work/unified_parquet/physical_years/physical_{year}_[0-9a-f]{{12,32}}",rel)):
        raise ValueError("Historical physical year escaped module work")
    folder=M.MODULE/rel
    mf=folder/"manifest.json"
    db=folder/"stockday-unique.sqlite3"
    if (any(x.is_symlink() for x in (M.MODULE/"work",M.WORK,M.ROOT,
                                     folder,mf,db))
            or not folder.is_dir() or not mf.is_file() or not db.is_file()
            or folder.resolve().parent!=M.ROOT.resolve()
            or M.ST.sha(mf)!=doc["private_manifest_sha256"]
            or M.ST.sha(db)!=doc["private_sqlite_sha256"]):
        raise ValueError("Historical private manifest or unique SQLite bytes drifted")
    manifest=json.loads(mf.read_bytes())
    if (manifest.get("format")!=M.FORMAT or manifest.get("year")!=year
            or manifest.get("status")!=doc["status"]
            or manifest.get("stockday_unique_sqlite_sha256")!=doc["private_sqlite_sha256"]
            or manifest.get("source_purchased_original_parquet_sha256")!=
                    doc["source_purchased_original_parquet_sha256"]
            or manifest.get("source_candidate_safe_sha256")!=doc["source_candidate_safe_sha256"]
            or manifest.get("source_candidate_version_sha256")!=M.SOURCE_VERSION
            or manifest.get("original_purchased_rows")!=doc["purchased_original_rows"]
            or manifest.get("h5_mixed_candidate_rows")!=doc["h5_mixed_candidate_rows"]
            or manifest.get("total_private_physical_rows")!=doc["total_private_physical_rows"]
            or any(manifest.get(k) is not False for k in (
                "original_market_files_written","original_purchased_parquet_replaced",
                "private_or_production_active_pointer_modified",
                "candidate_source_units_certified","ready_for_production_query",
                "ready_for_automatic_market_merge","ready_for_h5_mirror"))):
        raise ValueError("Historic manifest/source SAFE provenance mismatch")
    return doc,hashlib.sha256(raw).hexdigest(),folder,mf,db,manifest


def verify(safe,out):
    target=Path(out)
    if (M.REPORTS.is_symlink() or target.is_symlink()
            or target.suffix.lower()!=".json" or target.exists()
            or target.resolve().parent!=M.REPORTS.resolve()):
        raise ValueError("Require NEW direct reports/ historical independent audit SAFE")
    doc,safe_sha,folder,mf,db,manifest=source(safe)
    year=doc["year"]
    names={"purchased"}|({"h5_gap_2016"} if year==2016 else set())
    parts=manifest.get("partition_files")
    receipts=doc.get("physical_partition_sha256")
    if (type(parts) is not dict or set(parts)!=names
            or type(receipts) is not dict or set(receipts)!=names):
        raise ValueError("Unexpected historical private physical partition set")
    import pyarrow as pa
    import pyarrow.parquet as pq
    expected_schema=PHYS.schema(pa)
    con=sqlite3.connect(db.resolve().as_uri()+"?mode=ro&immutable=1",uri=True)
    counts=Counter()
    try:
        if (con.execute("PRAGMA integrity_check").fetchone()[0]!="ok"
                or con.execute("SELECT COUNT(*) FROM stockday").fetchone()[0]!=
                   doc["total_private_physical_rows"]):
            raise ValueError("Historical private SQLite uniqueness integrity failed")
        for label in sorted(names):
            item=parts[label]
            expected_rel=("purchased/day.parquet" if label=="purchased"
                          else "candidate/h5-gap-2016.parquet")
            expected_kind=("purchased_parquet" if label=="purchased"
                           else "private_h5_mixed_stockday_candidate")
            file=folder/expected_rel
            if (type(item) is not dict
                    or set(item)!={"relative_file","rows","sha256","source_kind",
                                   "original_rows_float64_digest_sha256"}
                    or item["relative_file"]!=expected_rel
                    or item["source_kind"]!=expected_kind
                    or type(item["rows"]) is not int
                    or item["rows"]!=(doc["purchased_original_rows"] if label=="purchased" else 1)
                    or receipts[label]!={"rows":item["rows"],"sha256":item["sha256"]}
                    or any(not re.fullmatch("[0-9a-f]{64}",str(item[k]))
                           for k in ("sha256","original_rows_float64_digest_sha256"))
                    or file.is_symlink() or file.parent.is_symlink()
                    or not file.is_file() or not 0<file.stat().st_size<=M.MAX_PART_BYTES
                    or M.ST.sha(file)!=item["sha256"]):
                raise ValueError("Historical physical partition SHA/path/count mismatch")
            pf=pq.ParquetFile(file,memory_map=False,pre_buffer=False)
            digest=hashlib.sha256()
            seen=0
            try:
                if pf.schema_arrow!=expected_schema or pf.metadata.num_rows!=item["rows"]:
                    raise ValueError("Historical private physical Arrow schema/footer differs")
                for rg in range(pf.metadata.num_row_groups):
                    table=pf.read_row_group(rg,use_threads=False)
                    if (table.schema!=expected_schema
                            or any(col.null_count for col in table.columns)):
                        raise ValueError("Historic private physical Arrow values null/invalid")
                    for row in table.to_pylist():
                        if row["value_source"]!=expected_kind:
                            raise ValueError("Purchased/H5 historic provenance was changed")
                        restored=dict(row)
                        restored["symbol"]=row["source_symbol"]
                        if PHYS.normalise(restored,expected_kind,year,None)!=row:
                            raise ValueError("Historic original vendor values/symbol timestamp changed")
                        sql=con.execute("SELECT kind FROM stockday WHERE "
                              "year=? AND symbol=? AND trading_date=?",
                              (year,row["symbol"],row["trading_date"])).fetchone()
                        if sql!=(expected_kind,):
                            raise ValueError("Historical private unique stockday index wrong")
                        digest.update(PHYS.row_bytes(row))
                        counts[expected_kind]+=1
                        seen+=1
            finally:
                pf.close()
            if (seen!=item["rows"] or
                    digest.hexdigest()!=item["original_rows_float64_digest_sha256"]
                    or M.ST.sha(file)!=item["sha256"]):
                raise ValueError("Historical private original float64/partition SHA drift")
    finally:
        con.close()
    if (counts["purchased_parquet"]!=doc["purchased_original_rows"]
            or counts["private_h5_mixed_stockday_candidate"]!=(year==2016)
            or sum(counts.values())!=doc["total_private_physical_rows"]
            or M.ST.sha(db)!=doc["private_sqlite_sha256"]
            or M.ST.sha(mf)!=doc["private_manifest_sha256"]
            or source(safe)[1]!=safe_sha):
        raise ValueError("Historical full year original data/key/manifest inconsistent")
    result={
        "format":FORMAT,"status":"independent_historical_private_physical_year_all_rows_sha_and_keys_verified",
        "year":year,
        "private_purchased_rows_verified":counts["purchased_parquet"],
        "private_h5_mixed_candidate_rows_verified":
            counts["private_h5_mixed_stockday_candidate"],
        "private_total_rows_verified":sum(counts.values()),
        "private_partition_files_verified":len(names),
        "source_materialization_safe_sha256":safe_sha,
        "source_private_manifest_sha256":doc["private_manifest_sha256"],
        "original_purchased_parquet_reopened":False,
        "original_h5_source_reopened":False,
        "original_market_source_freshness_rechecked":False,
        "original_float64_roundtrip_fingerprint_verified":True,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "original_market_files_written":False,
        "private_or_production_active_pointer_modified":False,
        "no_market_ohlcva_or_stock_symbols_in_safe":True,
    }
    with target.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(result,stream,indent=2,sort_keys=True)
        stream.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--materialization-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--verify-private-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=verify(a.materialization_safe,a.out)
        print("Historical private physical year:",result["year"])
        print("Purchased rows:",result["private_purchased_rows_verified"])
        print("H5 candidate:",result["private_h5_mixed_candidate_rows_verified"])
        print("Total verified:",result["private_total_rows_verified"])
        print("SAFE:",a.out)
    except (OSError,ValueError,TypeError,KeyError,ImportError,
            OverflowError,sqlite3.Error):
        p.error("Historical private full year independently verified SAFE denied")


if __name__=="__main__":
    main()
