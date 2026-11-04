#!/usr/bin/env python3
"""Stage real, ISOLATED Hikyuu-layout day H5 from SHA-pinned private Parquet.

This first real mirror WRITE probe handles 1 canonical stock and <=31 daily
rows. It creates a NEW H5 under module work/h5_mirror/canaries/ only.
It does NOT modify original purchased Parquet, original Hikyuu H5 or an
active pointer. The source is the already independently certified 16-year
private parquet version via the existing opt-in local-only OHLCVA API.

Hikyuu H5 stores integer prices/volume/amount; conversion can be lossy.
Always report *both* key equality and whether all OHLCVA were exactly
representable. A H5 built by this tool is NOT production/native-C++-
certified until a separate native Hikyuu reader actually opens it.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
OUT=MODULE/"work"/"h5_mirror"/"canaries"
REPORTS=MODULE/"reports"
SUFFIX=re.compile(r"[a-f0-9]{12}\Z")
FIELDS=("open","high","low","close","volume","amount")
UNITS={"open":1000,"high":1000,"low":1000,"close":1000,
       "volume":1/100,"amount":1/1000}
LIMITS={"open":2**32-1,"high":2**32-1,"low":2**32-1,
        "close":2**32-1,"volume":2**64-1,"amount":2**64-1}
H5_COLS=("datetime","openPrice","highPrice","lowPrice","closePrice",
         "transCount","transAmount")
FORMAT="AStockDataTools private DAY Parquet-to-Hikyuu H5 isolated real write probe v1"


def tool():
    spec=importlib.util.spec_from_file_location(
        "hikyuu_day_mirror_private_source_reader",
        HERE/"query-private-2011-2026-all16-ohlcva-local-readonly.py")
    x=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(x)
    return x


def raw_row(source):
    """Explicit Hikyuu daily fixed-point candidate and loss report."""
    from datetime import timezone,timedelta
    if type(source)!=dict or type(source.get("ts")) is not int:
        raise ValueError("Invalid normalized private DAY row")
    try:
        d=datetime.fromtimestamp(source["ts"]/1000,
             tz=timezone(timedelta(hours=8)))
    except (OverflowError,OSError,ValueError):
        raise ValueError("Invalid private DAY timestamp") from None
    # The independently audited unified Parquet builder intentionally
    # allows purchased DAY source timestamps at any Beijing-local time:
    # its canonical trading_date is dt.date(), not necessarily 00:00.
    # H5-only additions are separately constrained to midnight by the
    # existing source materializer; preserve that contract here too.
    if d.date().isoformat()!=source.get("trading_date"):
        raise ValueError("Private DAY source timestamp differs from trading date")
    if (source.get("value_source")!="purchased_parquet"
            and (d.hour,d.minute,d.second,d.microsecond)!=(0,0,0,0)):
        raise ValueError("Private H5 candidate DAY timestamp must be midnight CST")
    stamp=int(d.strftime("%Y%m%d"))*10000
    raw=[stamp]
    errors={}
    for f in FIELDS:
        v=source.get(f)
        if type(v) is not float or not math.isfinite(v) or v<0:
            raise ValueError("Invalid private Float64 value")
        scaled=v*UNITS[f]
        integer=round(scaled)
        if integer<0 or integer>LIMITS[f]:
            raise ValueError("Original float exceeds Hikyuu native integer range")
        roundtrip=integer/UNITS[f]
        # Float64 comparison is intentionally exact (no tolerance):
        # if changed, this mirror is not bitwise-equivalent to Parquet.
        errors[f]=abs(v-roundtrip)
        raw.append(integer)
    return raw,errors


def stage(reader,symbol,version_safe,sha,start,end,
          run_id,out_safe,max_candidate_rows=3000000,phase_callback=None):
    def mark(phase):
        if phase_callback is not None:
            phase_callback(phase)
    mark("preflight")
    import h5py
    import numpy as np
    import tables
    if not SUFFIX.fullmatch(run_id):
        raise ValueError("Require fresh 12-hex run id")
    if symbol[:2] not in ("SH","SZ","BJ") or not re.fullmatch(
            "(?:SH|SZ|BJ)[0-9]{6}",symbol):
        raise ValueError("Canonical market code required")
    dest=OUT/f"day_canary_{run_id}.h5"
    safe=Path(out_safe)
    if (any(p.is_symlink() for p in
            (MODULE/"work",MODULE/"work"/"h5_mirror",OUT,REPORTS,dest,safe))
            or dest.exists() or safe.exists() or safe.suffix!=".json"
            or safe.resolve().parent!=REPORTS.resolve()
            or dest.resolve().parent!=OUT.resolve()):
        raise ValueError("Only new private H5 canary and module reports SAFE")
    mark("read_private_parquet")
    response=reader.read_local_bars(
        version_safe,sha,symbol,start,end,allow_private_values=True,
        max_candidate_rows=max_candidate_rows,max_result_bars=31)
    rows=response["bars"]
    stats=response["safe_summary"]
    if (len(rows)<1 or len(rows)>31 or
            stats.get("local_bars_count")!=len(rows)
            or stats.get("source_all16_private_version_sha256")!=sha
            or stats.get("ready_for_h5_mirror") is not False
            or stats.get("local_licensed_OHLCVA_values_exported_to_safe") is not False):
        raise ValueError("Private DAY row provenance or count invalid")
    mark("convert_float64_to_h5_integer")
    kinds=Counter()
    original=[]
    maxima={k:0.0 for k in FIELDS}
    changed=Counter()
    for row in rows:
        if row.get("symbol")!=symbol:
            raise ValueError("Cross-stock DAY mirror is not permitted")
        record,errors=raw_row(row)
        original.append(record)
        kinds[row["value_source"]]+=1
        for k,error in errors.items():
            maxima[k]=max(maxima[k],error)
            if error!=0:
                changed[k]+=1
    if len({row[0] for row in original})!=len(rows):
        raise ValueError("Duplicate Hikyuu stockday in one-symbol sample")
    original.sort(key=lambda row:row[0])
    # The audited native 2.8.1 H5 format is a packed 40-byte PyTables
    # TABLE, not a generic HDF5 compound dataset. Reuse the proven exact
    # order/offsets from build-hikyuu-native-h5-synthetic-canary.py.
    dt=np.dtype([("closePrice","<u4"),("datetime","<u8"),
                 ("highPrice","<u4"),("lowPrice","<u4"),
                 ("openPrice","<u4"),("transAmount","<u8"),
                 ("transCount","<u8")])
    order=("closePrice","datetime","highPrice","lowPrice",
           "openPrice","transAmount","transCount")
    if dt.itemsize!=40 or dt.names!=order:
        raise ValueError("Hikyuu native 40-byte TABLE dtype unavailable")
    raw=np.empty(len(original),dtype=dt)
    for i,record in enumerate(original):
        raw[i]["datetime"]=record[0]
        raw[i]["openPrice"]=record[1]
        raw[i]["highPrice"]=record[2]
        raw[i]["lowPrice"]=record[3]
        raw[i]["closePrice"]=record[4]
        raw[i]["transCount"]=record[5]
        raw[i]["transAmount"]=record[6]
    mark("create_isolated_h5")
    OUT.mkdir(parents=True,exist_ok=True)
    with tables.open_file(str(dest),mode="w") as h5:
        group=h5.create_group("/","data")
        table=h5.create_table(
            group,symbol,description=dt,title=symbol,
            filters=tables.Filters(complevel=5,complib="zlib",shuffle=True),
            expectedrows=len(raw))
        table.append(raw)
        table.flush()
    mark("verify_h5_integer_readback")
    with h5py.File(dest,"r") as h5:
        if (not isinstance(h5.get("data"),h5py.Group)
                or not isinstance(h5["data"].get(symbol),h5py.Dataset)):
            raise ValueError("Native Hikyuu layout /data/symbol missing")
        ds=h5["data"][symbol]
        marker=ds.attrs.get("CLASS")
        if isinstance(marker,bytes):
            marker=marker.decode("ascii")
        if (marker!="TABLE" or ds.dtype!=dt or len(ds)!=len(original)
                or ds.dtype.itemsize!=40 or ds.ndim!=1
                or ds.dtype.names!=order):
            raise ValueError("Hikyuu-layout H5 fixed-width compound dtype incorrect")
        for got,want in zip(ds,original):
            if [int(got[f]) for f in H5_COLS]!=want:
                raise ValueError("Hikyuu-layout H5 full integer roundtrip changed")
    with tables.open_file(str(dest),"r") as h5:
        if h5.get_node("/data/"+symbol).nrows!=len(original):
            raise ValueError("Hikyuu PyTables TABLE native row count differs")
    mark("hash_written_h5")
    sha_h5=hashlib.sha256(dest.read_bytes()).hexdigest()
    doc={
        "format":FORMAT,
        "status":"isolated_native_layout_day_h5_written_and_h5py_readback_verified_not_activated",
        "source_private_all16_version_sha256":sha,
        "private_h5_relative_file":dest.relative_to(MODULE).as_posix(),
        "private_h5_file_sha256":sha_h5,
        "source_day_rows":len(rows),"written_h5_integer_rows":len(rows),
        "source_rows_by_class":dict(kinds),
        "h5_fixedpoint_source_value_changed_field_counts":dict(changed),
        "h5_fixedpoint_max_abs_source_value_errors":maxima,
        "all_six_fields_exactly_representable_in_h5":not bool(changed),
        "h5py_compound_integer_full_row_readback_verified":True,
        "pytables_table_class_marker_and_40byte_layout_verified":True,
        "native_hikyuu_amount_value_in_purchased_units_requires_multiplier":10000,
        "native_hikyuu_volume_value_in_purchased_units_requires_multiplier":100,
        "hikyuu_cpp_native_reader_verified":False,
        "ready_for_full_market_mirror":False,
        "ready_for_production_query":False,
        "ready_for_h5_mirror":False,
        "ready_for_automatic_market_merge":False,
        "original_market_files_written":False,
        "purchased_parquet_source_rewritten":False,
        "original_hikyuu_h5_rewritten":False,
        "source_symbol_and_exact_dates_exported_to_safe":False,
        "source_ohlcva_exported_to_safe":False,
    }
    mark("write_aggregate_report")
    with safe.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(doc,f,sort_keys=True,indent=2)
        f.write("\n")
    return doc


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version-safe",type=Path,required=True)
    p.add_argument("--version-sha256",required=True)
    p.add_argument("--symbol",required=True)
    p.add_argument("--start",required=True)
    p.add_argument("--end",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--write-isolated-h5-canary",action="store_true",required=True)
    args=p.parse_args(argv)
    phase=["import_and_args"]
    try:
        r=stage(tool(),args.symbol,args.version_safe,args.version_sha256,
                args.start,args.end,args.run_id,args.out,
                phase_callback=lambda value: phase.__setitem__(0,value))
        print("PASS: isolated Hikyuu-layout DAY H5 actually written/read back")
        print("H5 rows:",r["written_h5_integer_rows"])
        print("Exact Float64 representability:",r["all_six_fields_exactly_representable_in_h5"])
        print("Changed field counts:",r["h5_fixedpoint_source_value_changed_field_counts"])
        print("H5 SAFE:",args.out)
        print("Real Hikyuu native C++ reader not yet verified; no production source touched")
    except Exception as exc:
        # Never reveal private values, source row dictionaries or full
        # exceptions that may contain source file paths. Phase + exception
        # class is enough for a focused code repair after real-world failure.
        reasons={
            "Private DAY row provenance or count invalid",
            "Cross-stock DAY mirror is not permitted",
            "Invalid normalized private DAY row",
            "Invalid private DAY timestamp",
            "Private DAY source timestamp differs from trading date",
            "Private H5 candidate DAY timestamp must be midnight CST",
            "Invalid private Float64 value",
            "Original float exceeds Hikyuu native integer range",
            "Hikyuu-layout H5 fixed-width compound dtype incorrect",
            "Hikyuu native 40-byte TABLE dtype unavailable",
            "Hikyuu PyTables TABLE native row count differs",
            "Hikyuu-layout H5 full integer roundtrip changed",
            "Only new private H5 canary and module reports SAFE",
        }
        detail=(str(exc) if type(exc) is ValueError and str(exc) in reasons
                else "details_redacted")
        last=traceback.extract_tb(exc.__traceback__)[-1]
        site=(last.name + ":" + str(last.lineno))
        p.error("Isolated DAY H5 write refused [" + phase[0] + "/" +
                type(exc).__name__ + "/" + site + "/" + detail +
                "]; no original sources changed")


if __name__=="__main__":
    main()
