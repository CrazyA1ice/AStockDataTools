#!/usr/bin/env python3
"""Independently re-open all private physical 2026 purchased+H5 DAY partitions.

Full-content audit of the *new private outputs* and SQLite stockday index;
no original licensed Parquet/H5 reads, no source freshness claim and no
authorization to replace purchased market data, activate routing or mirror H5.
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
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

M=load("verify_new_2026_private_physical_day",
       "materialize-private-2026-purchased-plus-h5-year.py")
FORMAT="AStockDataTools independent private physical 2026 purchased+H5 DAY audit v1"


def source_report(path):
    p=Path(path)
    if (M.REPORTS.is_symlink() or p.is_symlink()
            or p.suffix.lower()!=".json"
            or p.resolve().parent!=M.REPORTS.resolve()
            or not p.is_file() or not 0<p.stat().st_size<=1000000):
        raise ValueError("Require genuine module reports/ physical 2026 SAFE")
    raw=p.read_bytes()
    doc=json.loads(raw)
    if (type(doc) is not dict or doc.get("format")!=M.FORMAT
            or doc.get("status")!=
                "private_full_2026_purchased_and_h5_candidate_physical_not_activated"
            or doc.get("year")!=2026
            or doc.get("purchased_original_2026_source_files")!=9
            or doc.get("h5_whole_candidate_rows")!=22191
            or doc.get("h5_mixed_candidate_rows")!=82
            or doc.get("candidate_source_units_certified") is not False
            or doc.get("ready_for_production_query") is not False
            or doc.get("ready_for_automatic_market_merge") is not False
            or doc.get("ready_for_h5_mirror") is not False
            or doc.get("historical_2011_2025_purchased_all_included") is not False
            or doc.get("original_market_files_written") is not False
            or doc.get("original_purchased_parquet_replaced") is not False
            or doc.get("private_or_production_active_pointer_modified") is not False
            or doc.get("quarantined_2026_07_16_stockday_bars_not_included")!=5
            or doc.get("no_market_ohlcva_or_stock_symbols_exported_in_safe") is not True):
        raise ValueError("Incomplete or production-authorized private 2026 SAFE")
    if (doc.get("total_private_physical_rows") !=
            doc.get("purchased_original_rows")+22273):
        raise ValueError("2026 purchased+H5 private source row totals inconsistent")
    sha_fields=("private_manifest_sha256",
                "private_stockday_unique_index_sha256",
                "source_private_candidate_safe_sha256",
                "source_private_version_sha256","source_qdc_manifest_sha256")
    if any(not re.fullmatch("[0-9a-f]{64}",str(doc.get(k))) for k in sha_fields):
        raise ValueError("2026 source SHA pins missing or malformed")
    rel=doc.get("private_relative_directory")
    if (type(rel) is not str or not re.fullmatch(
            "work/unified_parquet/physical_years/physical_2026_[0-9a-f]{12,32}",rel)):
        raise ValueError("Physical year private path escaped ignored module work")
    folder=M.MODULE/rel
    mf=folder/"manifest.json"
    idx=folder/"stockday-unique.sqlite3"
    if (any(x.is_symlink() for x in (M.MODULE/"work",M.WORK,M.ROOT,
                                     folder,mf,idx))
            or not folder.is_dir() or not mf.is_file() or not idx.is_file()
            or folder.resolve().parent!=M.ROOT.resolve()
            or M.ST.sha(mf)!=doc["private_manifest_sha256"]
            or M.ST.sha(idx)!=doc["private_stockday_unique_index_sha256"]):
        raise ValueError("Private 2026 manifest or SQLite index content SHA changed")
    manifest=json.loads(mf.read_bytes())
    for key in ("format","status","year","purchased_original_2026_source_files",
                "purchased_original_rows","h5_whole_candidate_rows",
                "h5_mixed_candidate_rows","total_private_physical_rows",
                "source_private_candidate_safe_sha256","source_private_version_sha256",
                "source_qdc_manifest_sha256",
                "quarantined_2026_07_16_stockday_bars_not_included"):
        if manifest.get(key)!=doc.get(key):
            raise ValueError("2026 private manifest and source SAFE disagree")
    if (manifest.get("global_stockday_unique_index_sha256")!=
            doc["private_stockday_unique_index_sha256"]
            or manifest.get("candidate_source_units_certified") is not False
            or manifest.get("ready_for_automatic_market_merge") is not False
            or manifest.get("ready_for_h5_mirror") is not False):
        raise ValueError("2026 physical manifest violates safety")
    return doc,hashlib.sha256(raw).hexdigest(),folder,mf,idx,manifest


def verify(materialization_safe,out):
    out=Path(out)
    if (M.REPORTS.is_symlink() or out.is_symlink()
            or out.exists() or out.suffix.lower()!=".json"
            or out.resolve().parent!=M.REPORTS.resolve()):
        raise ValueError("Independent physical year SAFE must be NEW module reports/ file")
    doc,source_sha,folder,mf,idx,manifest=source_report(materialization_safe)
    expected_names={f"2026-{m:02d}.parquet" for m in range(1,10)} | {"h5_gap_2026"}
    parts=manifest.get("partition_files")
    safe_parts=doc.get("physical_partition_sha256")
    if (type(parts) is not dict or set(parts)!=expected_names
            or type(safe_parts) is not dict or set(safe_parts)!=expected_names):
        raise ValueError("2026 physical output must have exactly 9 months plus one H5 gap")
    import pyarrow as pa
    import pyarrow.parquet as pq
    sch=M.schema(pa)
    con=sqlite3.connect(idx.resolve().as_uri()+"?mode=ro&immutable=1",uri=True)
    counters=Counter()
    files_checked=0
    try:
        if (con.execute("SELECT COUNT(*) FROM stockday").fetchone()[0]!=
                doc["total_private_physical_rows"]
                or con.execute("PRAGMA integrity_check").fetchone()[0]!="ok"):
            raise ValueError("Global 2026 stockday unique SQLite index is invalid")
        for key in sorted(expected_names):
            data=parts[key]
            path=folder/data["relative_file"]
            expected_source=("purchased_parquet" if key!="h5_gap_2026"
                             else "mixed_whole_h5_candidates")
            expected_path=(f"purchased/month={key[5:7]}/day.parquet"
                           if key!="h5_gap_2026"
                           else "candidate/h5-gap-2026.parquet")
            if (type(data) is not dict or
                    set(data)!={"relative_file","rows","sha256","source_kind",
                                "original_rows_float64_digest_sha256"}
                    or data["relative_file"]!=expected_path
                    or data["source_kind"]!=expected_source
                    or safe_parts[key]!={"sha256":data["sha256"],"rows":data["rows"]}
                    or type(data["rows"]) is not int or not 0<data["rows"]<=M.MAX_ROWS
                    or not re.fullmatch("[0-9a-f]{64}",str(data["sha256"]))
                    or not re.fullmatch("[0-9a-f]{64}",str(
                        data["original_rows_float64_digest_sha256"]))
                    or path.parent.is_symlink() or path.is_symlink()
                    or not path.is_file() or not 0<path.stat().st_size<=M.MAX_PART_BYTES
                    or M.ST.sha(path)!=data["sha256"]):
                raise ValueError("Private 2026 partition path/rows/hash invalid")
            pf=pq.ParquetFile(path,memory_map=False,pre_buffer=False)
            count=0
            roundtrip_sha=hashlib.sha256()
            try:
                if pf.schema_arrow!=sch or pf.metadata.num_rows!=data["rows"]:
                    raise ValueError("Private 2026 Arrow schema/footer changed")
                month=int(key[5:7]) if key!="h5_gap_2026" else None
                for rg in range(pf.metadata.num_row_groups):
                    table=pf.read_row_group(rg,use_threads=False)
                    if table.schema!=sch or table.null_count:
                        raise ValueError("Private 2026 partition corrupted Arrow data")
                    for row in table.to_pylist():
                        kind=row.get("value_source")
                        if (kind not in M.SOURCE_KINDS or
                                (month is not None and kind!="purchased_parquet") or
                                (month is None and kind=="purchased_parquet")):
                            raise ValueError("Private 2026 source category mislabelled")
                        # Re-derive canonical stock/day from retained original
                        # source_symbol and original timestamp; no value cast.
                        test=dict(row)
                        test["symbol"]=row["source_symbol"]
                        clean=M.normalise(test,kind,year=2026,month=month)
                        if clean!=row:
                            raise ValueError("Private 2026 physical values or raw symbol changed")
                        roundtrip_sha.update(M.row_bytes(row))
                        lookup=con.execute(
                            "SELECT kind FROM stockday WHERE year=? AND symbol=? "
                            "AND trading_date=?",
                            (2026,row["symbol"],row["trading_date"])).fetchone()
                        if lookup!=(kind,):
                            raise ValueError("Global private purchased/H5 key index mismatch")
                        counters[kind]+=1
                        count+=1
            finally:
                pf.close()
            if (count!=data["rows"] or M.ST.sha(path)!=data["sha256"]
                    or roundtrip_sha.hexdigest()!=
                        data["original_rows_float64_digest_sha256"]):
                raise ValueError("Private 2026 partition totals, original float64 or bytes changed")
            files_checked+=1
    finally:
        con.close()
    if (counters["purchased_parquet"]!=doc["purchased_original_rows"]
            or counters["private_h5_whole_date_candidate"]!=22191
            or counters["private_h5_mixed_stockday_candidate"]!=82
            or sum(counters.values())!=doc["total_private_physical_rows"]
            or M.ST.sha(mf)!=doc["private_manifest_sha256"]
            or M.ST.sha(idx)!=doc["private_stockday_unique_index_sha256"]
            or source_report(materialization_safe)[1]!=source_sha):
        raise ValueError("Private 2026 physical Arrow/key/SHA conservation failed")
    result={
        "format":FORMAT,
        "status":"independent_full_2026_private_physical_parquet_sha_values_keys_verified",
        "source_private_physical_manifest_sha256":doc["private_manifest_sha256"],
        "source_materialization_safe_sha256":source_sha,
        "source_private_version_sha256":doc["source_private_version_sha256"],
        "purchased_month_files_verified":9,
        "private_partition_files_verified":files_checked,
        "private_purchased_records_verified":counters["purchased_parquet"],
        "private_h5_whole_candidate_rows_verified":22191,
        "private_h5_mixed_candidate_rows_verified":82,
        "private_total_stockday_rows_verified":sum(counters.values()),
        "all_original_purchased_ohlcva_copied_unmodified_as_claimed_by_materializer":True,
        "original_purchased_source_2026_full_sha_rechecked_now":False,
        "original_market_source_freshness_rechecked_now":False,
        "historical_purchased_2011_2025_included":False,
        "candidate_source_units_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "ready_for_h5_mirror":False,
        "original_market_files_opened":False,
        "original_market_files_modified":False,
        "private_or_production_active_pointer_modified":False,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
        "no_licensed_ohlcva_or_stock_symbols_exported_in_safe":True,
    }
    with out.open("x",encoding="utf-8",newline="\n") as fp:
        json.dump(result,fp,indent=2,sort_keys=True,ensure_ascii=False)
        fp.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--materialization-safe",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--verify-private-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=verify(a.materialization_safe,a.out)
        print("Independent 2026 physical purchased+H5 daily rows:",
              result["private_total_stockday_rows_verified"])
        print("Nine purchased months and one H5 gap candidate SHA/value/key verification")
        print("SAFE:",a.out)
    except (OSError,ValueError,TypeError,KeyError,ImportError,sqlite3.Error):
        p.error("Independent physical 2026 purchased+H5 candidate year verification refused")


if __name__=="__main__":
    main()
