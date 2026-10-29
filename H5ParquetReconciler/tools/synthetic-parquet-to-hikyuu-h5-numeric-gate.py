#!/usr/bin/env python3
"""Synthetic-only Parquet -> Hikyuu 2.8.1 H5 decimal numeric gate.

This is NOT a converter for licensed Parquet. It creates its own six fictional
decimal-valued Parquet rows and converts those to a NEW two-file PyTables H5
mirror, then checks every integer against the previously Hikyuu-native-read
synthetic baseline. It never opens any purchased source or production db.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
REPORTS=MODULE/"reports"
WORK=MODULE/"work"
MIRRORS=WORK/"h5_mirror"
FORMAT="AStockDataTools synthetic Parquet to Hikyuu 2.8.1 decimal H5 gate v1"
NATIVE_FORMAT="AStockDataTools isolated synthetic Hikyuu 2.8.1 native H5 read verification v2"
FIELDS=("datetime","open","high","low","close","amount","volume")
PRICE_FIELDS=("open","high","low","close")
PRICE_SCALE=Decimal(1000)
AMOUNT_SCALE=Decimal(10)
VOLUME_SCALE=Decimal(1)
U32_MAX=(1<<32)-1
U64_MAX=(1<<64)-1
DATES=(202609300000,202610080000,202610130000)
STOCKS={"SH600000":("sh_day.h5",1),"SZ000001":("sz_day.h5",2)}
LAYOUT=(
    ("closePrice","<u4"),("datetime","<u8"),("highPrice","<u4"),
    ("lowPrice","<u4"),("openPrice","<u4"),
    ("transAmount","<u8"),("transCount","<u8"),
)

SPEC=importlib.util.spec_from_file_location(
    "strict_synthetic_h5_verified",
    Path(__file__).resolve().parent/"probe-hikyuu-native-driver-runtime-isolated.py")
CHECK=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def sha256(path):
    hasher=hashlib.sha256()
    with open(path,"rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def as_decimal(value,field):
    """A source float is not acceptable proof of exact decimal units."""
    if isinstance(value,bool) or isinstance(value,float) or value is None:
        raise ValueError(field+": no float/bool/null implicit conversion")
    if not isinstance(value,(Decimal,int,str)):
        raise ValueError(field+": expected an explicit decimal value")
    try:
        val=Decimal(value)
    except (ValueError,InvalidOperation):
        raise ValueError(field+": malformed decimal") from None
    if not val.is_finite() or val<0:
        raise ValueError(field+": negative or nonfinite value")
    return val


def encode_exact(value,scale,maximum,field):
    decimal=as_decimal(value,field)
    scaled=decimal*scale
    if not scaled.is_finite() or scaled!=scaled.to_integral_value():
        raise ValueError(field+": cannot represent exactly at native H5 scale")
    if scaled>maximum:
        raise ValueError(field+": native H5 integer overflow")
    return int(scaled)


def encode_day_row(row):
    """Input units are *Hikyuu-decoded* units, not inferred Parquet units."""
    if type(row) is not dict or set(row)!=set(FIELDS):
        raise ValueError("Expected exactly 7 typed source fields")
    date=row["datetime"]
    if type(date) is not int or not 0<=date<=U64_MAX:
        raise ValueError("datetime must be integer YYYYMMDD0000")
    value=str(date)
    if len(value)!=12 or value[-4:]!="0000":
        raise ValueError("datetime must be canonical daily YYYYMMDD0000")
    try:
        day=datetime.strptime(value[:8],"%Y%m%d")
    except ValueError:
        raise ValueError("datetime is not a calendar date") from None
    if int(day.strftime("%Y%m%d"))!=int(value[:8]):
        raise ValueError("datetime date was normalized")
    encoded={
        "datetime":date,
        "openPrice":encode_exact(row["open"],PRICE_SCALE,U32_MAX,"open"),
        "highPrice":encode_exact(row["high"],PRICE_SCALE,U32_MAX,"high"),
        "lowPrice":encode_exact(row["low"],PRICE_SCALE,U32_MAX,"low"),
        "closePrice":encode_exact(row["close"],PRICE_SCALE,U32_MAX,"close"),
        "transAmount":encode_exact(row["amount"],AMOUNT_SCALE,U64_MAX,"amount"),
        "transCount":encode_exact(row["volume"],VOLUME_SCALE,U64_MAX,"volume"),
    }
    low,high=encoded["lowPrice"],encoded["highPrice"]
    if (low>high or not low<=encoded["openPrice"]<=high
            or not low<=encoded["closePrice"]<=high):
        raise ValueError("OHLC relationship invalid")
    return encoded


def native_h5_dtype(np):
    """Construct and validate Hikyuu's 40-byte compound disk record dtype.

    NumPy interprets a tuple as the special (base_dtype, shape) constructor
    form, not as a compound-field sequence. Feed the field descriptors as a
    LIST, and verify offsets so this cannot silently change across versions.
    """
    dtype=np.dtype(list(LAYOUT))
    expected={
        "closePrice":0,"datetime":4,"highPrice":12,"lowPrice":16,
        "openPrice":20,"transAmount":24,"transCount":32,
    }
    if (dtype.itemsize!=40 or dtype.names!=tuple(expected)
            or any(dtype.fields[name][1]!=offset
                   for name,offset in expected.items())):
        raise ValueError("NumPy compound dtype differs from native 40-byte H5 layout")
    return dtype


def synthetic_decoded_rows(seed):
    """Numbers are fictional, by construction, and declared in driver units."""
    rows=[]
    for i,date in enumerate(DATES):
        base=10000+seed*50+i*100
        dec=lambda x:Decimal(x)/PRICE_SCALE
        rows.append({
            "datetime":date,
            "open":dec(base),
            "high":dec(base+200),
            "low":dec(base-200),
            "close":dec(base+50),
            "amount":Decimal(100000+seed*1000+i*100)/AMOUNT_SCALE,
            "volume":Decimal(1200+seed*10+i),
        })
    return rows


def require_native_proof(path,canary):
    """Gate the run on the user's already-successful native read SAFE."""
    source=CHECK._module_input(path)
    report=json.loads(source.read_text(encoding="utf-8"))
    flags_true=(
        "canary_h5_hashes_reverified","synthetic_only",
        "verified_prior_core311_only_safe_proof","native_core311_loaded",
        "native_stock_manager_initialized","native_h5_get_kdata_called",
        "native_h5_synthetic_six_records_matched",
        "native_h5_compatibility_certified_for_synthetic_v1",
        "no_licensed_market_data_read","no_raw_ohlcva_in_safe_summary",
        "native_worker_stdout_stderr_not_saved")
    flags_false=(
        "full_hikyuu_package_imported",
        "licensed_parquet_to_h5_mapping_certified",
        "ready_for_full_market_mirror","original_market_files_modified",
        "production_query_route_modified","private_overlay_activated")
    if (not isinstance(report,dict)
            or report.get("format")!=NATIVE_FORMAT
            or report.get("canary_safe_summary_sha256")!=canary["report_sha256"]
            or report.get("native_hikyuu_runtime_version_expected")!="2.8.1"
            or report.get("native_h5_read_status")!="native_h5_six_synthetic_rows_matched"
            or report.get("last_native_phase")!="finished"
            or report.get("per_symbol_matching_rows")!={"SH600000":3,"SZ000001":3}
            or any(report.get(k) is not True for k in flags_true)
            or any(report.get(k) is not False for k in flags_false)):
        raise ValueError("Verified matching successful native synthetic H5 SAFE proof required")
    return True


def destinations(out_dir,safe_report):
    target=Path(out_dir)
    report=CHECK._module_output(safe_report)
    if (WORK.is_symlink() or MIRRORS.is_symlink()
            or target.is_symlink() or target.exists()
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,79}",target.name)
            or target.resolve().parent!=MIRRORS.resolve()):
        raise ValueError("Must use NEW isolated directory under module work/h5_mirror")
    return target.resolve(),report


def generate(canary_report,native_proof,out_dir,safe_report):
    """Create only a NEW fictional Parquet+H5 output, with strict equality."""
    canary=CHECK.verify_canary(canary_report)
    require_native_proof(native_proof,canary)
    target,report=destinations(out_dir,safe_report)
    # Import dependencies only after proof and path gates. No source paths are
    # accepted; Parquet inputs are generated internally from fictional rows.
    import numpy as np
    import h5py
    import tables
    import pyarrow as pa
    import pyarrow.parquet as pq

    dtype=native_h5_dtype(np)
    for key in STOCKS:
        baseline=canary["isolated_canary_dir"]/STOCKS[key][0]
        if not baseline.is_file() or baseline.is_symlink():
            raise ValueError("Synthetic baseline missing")
    target.mkdir(parents=False,exist_ok=False)
    new_files=[]
    matching=0
    schema=pa.schema([
        ("datetime",pa.int64()),
        ("open",pa.decimal128(16,3)),("high",pa.decimal128(16,3)),
        ("low",pa.decimal128(16,3)),("close",pa.decimal128(16,3)),
        ("amount",pa.decimal128(24,1)),("volume",pa.decimal128(24,0)),
    ])
    try:
        for symbol,(h5_name,seed) in STOCKS.items():
            rows=synthetic_decoded_rows(seed)
            arrays=[
                pa.array([row[field] for row in rows],type=schema.field(field).type)
                for field in FIELDS
            ]
            parquet_path=target/(symbol.lower()+"_synthetic.parquet")
            pq.write_table(pa.Table.from_arrays(arrays,schema=schema),
                           parquet_path,compression="zstd")
            typed=pq.read_table(parquet_path)
            if typed.schema!=schema or typed.num_rows!=3:
                raise ValueError("Synthetic Parquet schema/row count changed")
            cols={name:typed[name].to_pylist() for name in FIELDS}
            decoded=[{name:cols[name][i] for name in FIELDS} for i in range(3)]
            if decoded!=rows:
                raise ValueError("Synthetic decimal Parquet roundtrip changed")
            encoded=[encode_day_row(row) for row in decoded]
            if [row["datetime"] for row in encoded]!=list(DATES):
                raise ValueError("Synthetic date order or uniqueness changed")
            out_data=np.zeros(3,dtype=dtype)
            for i,row in enumerate(encoded):
                for field,value in row.items():
                    out_data[i][field]=value

            # This baseline was actually read via Hikyuu 2.8.1 native C++
            # and is unchanged. Compare EVERY integer; not just 6 counts.
            with h5py.File(canary["isolated_canary_dir"]/h5_name,"r") as src:
                canonical=src["data"][symbol][:]
            if (canonical.dtype.itemsize!=40
                    or canonical.dtype.names!=dtype.names
                    or not np.array_equal(out_data,canonical)):
                raise ValueError("Synthetic Parquet/H5 integers differ from native-read baseline")

            dest=target/h5_name
            with tables.open_file(str(dest),mode="w") as h5:
                group=h5.create_group("/","data")
                table=h5.create_table(
                    group,symbol,description=dtype,title=symbol,
                    filters=tables.Filters(complevel=5,complib="zlib",
                                          shuffle=True),expectedrows=3)
                table.append(out_data)
                table.flush()
            with h5py.File(dest,"r") as h5:
                node=h5["data"][symbol]
                if (node.shape!=(3,) or node.dtype!=dtype
                        or not np.array_equal(node[:],canonical)):
                    raise ValueError("Synthetic H5 PyTables output mismatch")
            new_files.append({
                "kind":"fictional_parquet_and_h5",
                "symbol":symbol,
                "parquet_sha256":sha256(parquet_path),
                "h5_sha256":sha256(dest),
                "verified_integer_records":3,
            })
            matching+=3
        after=CHECK.verify_canary(canary_report)["source_file_details"]
        if after!=canary["source_file_details"]:
            raise ValueError("Certified synthetic source mutated during experiment")
        safe={
            "format":FORMAT,
            "canary_safe_summary_sha256":canary["report_sha256"],
            "verified_previous_native_h5_six_rows":True,
            "synthetic_parquet_generation_only":True,
            "prices_in_hikyuu_driver_units_only":True,
            "amounts_in_hikyuu_driver_units_only":True,
            "volumes_in_hikyuu_driver_units_only":True,
            "exact_decimal_no_rounding":True,
            "native_h5_unsigned_price_width_bits":32,
            "native_h5_unsigned_amount_volume_width_bits":64,
            "all_six_synthetic_records_exactly_matched_native_baseline":matching==6,
            "per_symbol_records":{item["symbol"]:item["verified_integer_records"]
                                  for item in new_files},
            "generated_synthetic_files":new_files,
            "new_h5_files_tested_by_native_driver":False,
            "actual_purchased_parquet_units_verified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
            "licensed_market_data_read":False,
            "original_market_files_modified":False,
            "production_query_route_modified":False,
            "no_raw_ohlcva_in_safe_summary":True,
        }
        with report.open("x",encoding="utf-8") as output:
            json.dump(safe,output,ensure_ascii=False,indent=2)
            output.write("\n")
        return safe
    except BaseException:
        # Never overwrite/delete prior user files; leave NEW fictional
        # scratch artifacts for investigation and no success SAFE report.
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canary-report",type=Path,required=True)
    parser.add_argument("--native-proof",type=Path,required=True)
    parser.add_argument("--out-dir",type=Path,required=True)
    parser.add_argument("--safe-report",type=Path,required=True)
    parser.add_argument("--synthetic-only",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        result=generate(args.canary_report,args.native_proof,
                        args.out_dir,args.safe_report)
        print("SAFE synthetic Parquet/H5 numeric gate:",args.safe_report)
        print("Exact synthetic integer records:",
              result["per_symbol_records"])
        print("Purchased Parquet source units validated: NO")
        print("New H5 native-driver re-read performed: NO")
    except (ValueError,OSError,TypeError,KeyError,ImportError) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
