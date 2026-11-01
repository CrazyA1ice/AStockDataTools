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
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
OUT=MODULE/"work"/"h5_mirror"/"canaries"
REPORTS=MODULE/"reports"
SUFFIX=re.compile("[a-f0-9]{12}\\Z")
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
    if (d.isoformat()[11:]!="00:00:00+08:00"
            or d.date().isoformat()!=source.get("trading_date")):
        raise ValueError("Private DAY timestamp not midnight CST")
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
          run_id,out_safe,max_candidate_rows=3000000):
    import h5py
    import numpy as np
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
    dt=np.dtype([("datetime","<u8"),("openPrice","<u4"),
                 ("highPrice","<u4"),("lowPrice","<u4"),
                 ("closePrice","<u4"),("transCount","<u8"),
                 ("transAmount","<u8")])
    OUT.mkdir(parents=True,exist_ok=True)
    with h5py.File(dest,"x") as h5:
        grp=h5.create_group("data")
        ds=grp.create_dataset(symbol,data=np.array([tuple(r) for r in original],
                                   dtype=dt),compression="gzip",
                              compression_opts=3,shuffle=True,chunks=True)
    # Independent on-disk H5 bytes and ALL integer value read-back:
    with h5py.File(dest,"r") as h5:
        if (not isinstance(h5.get("data"),h5py.Group)
                or not isinstance(h5["data"].get(symbol),h5py.Dataset)):
            raise ValueError("Native Hikyuu layout /data/symbol missing")
        ds=h5["data"][symbol]
        if (ds.dtype!=dt or len(ds)!=len(original)
                or list(ds.dtype.names)!=list(H5_COLS)):
            raise ValueError("Hikyuu-layout H5 fixed-width compound dtype incorrect")
        for got,want in zip(ds,original):
            if [int(got[f]) for f in H5_COLS]!=want:
                raise ValueError("Hikyuu-layout H5 full integer roundtrip changed")
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
    with safe.open("x",encoding="utf-8",newline="\\n") as f:
        json.dump(doc,f,sort_keys=True,indent=2)
        f.write("\\n")
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
    try:
        r=stage(tool(),args.symbol,args.version_safe,args.version_sha256,
                args.start,args.end,args.run_id,args.out)
        print("PASS: isolated Hikyuu-layout DAY H5 actually written/read back")
        print("H5 rows:",r["written_h5_integer_rows"])
        print("Exact Float64 representability:",r["all_six_fields_exactly_representable_in_h5"])
        print("Changed field counts:",r["h5_fixedpoint_source_value_changed_field_counts"])
        print("H5 SAFE:",args.out)
        print("Real Hikyuu native C++ reader not yet verified; no production source touched")
    except Exception:
        p.error("Isolated DAY H5 write refused; sources remain unchanged")


if __name__=="__main__":
    main()
