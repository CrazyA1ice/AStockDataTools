#!/usr/bin/env python3
"""Build ISOLATED, SYNTHETIC Hikyuu HDF5 daily canaries from a SAFE survey.

Never reads or copies original H5 or purchased Parquet data. Requires PyTables,
h5py and NumPy. Writes only module/work/h5_mirror/<new-subdir>/ and a NEW
module/reports/<safe>.json. Compatibility with the real Hikyuu native driver
is NOT established here; test that separately before any real market mirror.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
REPORTS=MODULE/"reports"
WORK=MODULE/"work"
MIRRORS=WORK/"h5_mirror"
SURVEY_FORMAT="AStockDataTools Hikyuu native daily H5 structural read-only survey v1"
OUTPUT_FORMAT="AStockDataTools synthetic Hikyuu native day H5 canary summary v1"
ORDER=("closePrice","datetime","highPrice","lowPrice","openPrice",
       "transAmount","transCount")
LAYOUT=(("closePrice","u",4,0),("datetime","u",8,4),
        ("highPrice","u",4,12),("lowPrice","u",4,16),
        ("openPrice","u",4,20),("transAmount","u",8,24),
        ("transCount","u",8,32))
DATES=(202609300000,202610080000,202610130000)


def validate_survey(survey):
    """Require strict, observed 40-byte format; never infer from field names."""
    if (not isinstance(survey,dict) or survey.get("format")!=SURVEY_FORMAT
            or survey.get("period")!="day"
            or survey.get("hikyuu_native_driver_load_tested") is not False
            or survey.get("ready_for_full_h5_mirror_write") is not False
            or survey.get("mirror_files_created") is not False
            or survey.get("source_h5_files_modified") is not False
            or survey.get("no_raw_ohlcva_in_safe_summary") is not True):
        raise ValueError("Untrusted or incompatible native H5 SAFE survey")
    symbols=survey.get("symbols")
    if (type(symbols) is not list or len(symbols)!=2
            or len(set(symbols))!=2
            or set(symbols)!={"SH600000","SZ000001"}):
        raise ValueError("Canary only accepts the audited two-stock survey")
    by_symbol=survey.get("per_symbol_native_h5_contract")
    if not isinstance(by_symbol,dict) or set(by_symbol)!=set(symbols):
        raise ValueError("SAFE survey lacks exact per-stock H5 evidence")
    sources=survey.get("source_file_stat_provenance")
    if (type(sources) is not list or
            {e.get("relative_path") for e in sources if isinstance(e,dict)}
                != {"HikyuuData/sh_day.h5","HikyuuData/sz_day.h5"}):
        raise ValueError("SAFE survey source-file provenance differs")
    for sym in symbols:
        node=by_symbol[sym]
        if (not isinstance(node,dict)
                or node.get("dataset_present") is not True
                or node.get("pytables_table_class_marker_present") is not True
                or node.get("one_dimensional_compound_dataset") is not True
                or node.get("expected_field_set") is not True
                or node.get("integer_width_sign_compatible_with_h5record") is not True
                or node.get("structural_h5record_candidate") is not True
                or node.get("hikyuu_native_driver_verified") is not False
                or node.get("dtype_itemsize_bytes")!=40
                or type(node.get("rows_in_dataset")) is not int
                or node["rows_in_dataset"]<=0):
            raise ValueError("Native H5 candidate evidence missing for "+sym)
        layout=node.get("field_layout")
        if (type(layout) is not list or
                tuple((x.get("field"),x.get("kind"),x.get("itemsize_bytes"),
                       x.get("offset_bytes")) for x in layout
                      if isinstance(x,dict)) != LAYOUT):
            raise ValueError("Actual H5 byte offsets/order do not match surveyed layout")
    return symbols


def _input_report(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.suffix.lower()!=".json":
        raise ValueError("Supply an existing non-symlink SAFE survey JSON")
    if path.resolve().parent!=REPORTS.resolve():
        raise ValueError("SAFE survey must be directly under module reports/")
    raw=path.read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()


def _safe_destinations(target,safe_report):
    target=Path(target)
    safe_report=Path(safe_report)
    if (WORK.is_symlink() or MIRRORS.is_symlink() or REPORTS.is_symlink()):
        raise ValueError("Unsafe module output directory symlink")
    if (target.is_symlink() or target.exists()
            or target.resolve().parent!=MIRRORS.resolve()
            or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,79}",target.name)):
        raise ValueError("Use a NEW direct child under module work/h5_mirror/")
    if (safe_report.is_symlink() or safe_report.exists()
            or safe_report.suffix.lower()!=".json"
            or safe_report.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Use a NEW SAFE JSON under module reports/")
    return target.resolve(),safe_report.resolve()


def _synthetic_rows(dtype,seed):
    import numpy as np
    raw=np.empty(3,dtype=dtype)
    for i,key in enumerate(DATES):
        base=10000+seed*50+i*100
        raw[i]["datetime"]=key
        raw[i]["openPrice"]=base
        raw[i]["highPrice"]=base+200
        raw[i]["lowPrice"]=base-200
        raw[i]["closePrice"]=base+50
        raw[i]["transAmount"]=100000+seed*1000+i*100
        raw[i]["transCount"]=1200+seed*10+i
    return raw


def build_canary(survey_path,target,safe_report):
    """Create synthetic h5 files; output source proof and count metadata only."""
    import numpy as np
    import h5py
    try:
        import tables
    except ImportError as exc:
        raise RuntimeError(
            "PyTables required for native TABLE canary: pip install tables") from exc
    survey,digest=_input_report(survey_path)
    symbols=validate_survey(survey)
    target,safe_report=_safe_destinations(target,safe_report)
    dtype=np.dtype([(name, "<u8" if width==8 else "<u4")
                    for name,_,width,_ in LAYOUT])
    if (dtype.itemsize!=40 or dtype.names!=ORDER
            or tuple((name,dtype.fields[name][0].kind,
                      dtype.fields[name][0].itemsize,dtype.fields[name][1])
                     for name in ORDER)!=LAYOUT):
        raise ValueError("Local NumPy cannot reproduce surveyed native H5 offsets")
    MIRRORS.mkdir(parents=True,exist_ok=True)
    target.mkdir(exist_ok=False)
    completed=False
    report_created=False
    try:
        file_info=[]
        for venue,stock,seed in (("sh","SH600000",1),("sz","SZ000001",2)):
            output=target/(venue+"_day.h5")
            data=_synthetic_rows(dtype,seed)
            with tables.open_file(str(output),mode="w") as h5:
                group=h5.create_group("/","data")
                table=h5.create_table(group,stock,description=dtype,
                    title=stock,filters=tables.Filters(
                        complevel=5,complib="zlib",shuffle=True),
                    expectedrows=len(data))
                table.append(data)
                table.flush()
            # Verify the actual TABLE marker, 40-byte binary layout and every
            # synthetic integer value, not just the record count.
            with h5py.File(output,"r") as fh:
                ds=fh["data"][stock]
                actual=ds[:]
                node=survey["per_symbol_native_h5_contract"][stock]
                marker=ds.attrs.get("CLASS")
                if isinstance(marker,bytes):
                    marker=marker.decode("ascii")
                if (marker!="TABLE" or ds.ndim!=1
                        or ds.compression!="gzip" or ds.chunks is None
                        or actual.dtype.names!=ORDER
                        or actual.dtype.itemsize!=40
                        or tuple((name,actual.dtype.fields[name][0].kind,
                                  actual.dtype.fields[name][0].itemsize,
                                  actual.dtype.fields[name][1])
                                 for name in ORDER)!=LAYOUT
                        or not np.array_equal(actual,data)):
                    raise ValueError(
                        "Synthetic H5 PyTables roundtrip does not match SAFE survey")
                # Field set and its offsets are what matters; an old
                # legacy header's declaration ordering is not the stored order.
                if (node.get("rows_in_dataset",0)<=0 or
                        len(actual)!=len(DATES)):
                    raise ValueError("Canary count invalid")
            with tables.open_file(str(output),"r") as fh:
                if fh.get_node("/data/"+stock).nrows!=len(DATES):
                    raise ValueError("PyTables failed to reload synthetic table")
            file_info.append({
                "relative_output": "work/h5_mirror/"+target.name+"/"+output.name,
                "stock":stock,"synthetic_rows":len(DATES),
                "dtype_itemsize_bytes":int(dtype.itemsize),
                "pytables_table":True,
                "h5py_and_pytables_roundtrip_values_equal":True,
                "sha256":hashlib.sha256(output.read_bytes()).hexdigest()
            })
        summary={
            "format":OUTPUT_FORMAT,
            "source_survey_sha256":digest,
            "symbols":symbols,
            "synthetic_only":True,
            "synthetic_record_count":sum(x["synthetic_rows"] for x in file_info),
            "generated_files":file_info,
            "source_market_files_read":False,
            "purchased_parquet_read":False,
            "original_hikyuu_h5_read":False,
            "original_market_files_modified":False,
            "private_overlay_activated":False,
            "hikyuu_native_driver_tested":False,
            "hikyuu_driver_compatible_certified":False,
            "safe_for_full_market_h5_mirror":False,
            "no_raw_ohlcva_in_safe_summary":True,
            "production_query_route_modified":False,
        }
        REPORTS.mkdir(parents=True,exist_ok=True)
        with safe_report.open("x",encoding="utf-8") as fp:
            report_created=True
            json.dump(summary,fp,ensure_ascii=False,indent=2)
            fp.write("\n")
        completed=True
        return summary
    finally:
        if not completed:
            if report_created:
                safe_report.unlink(missing_ok=True)
            # The target was created by this invocation and did not exist
            # beforehand; safe to clean *this* failed temporary canary only.
            shutil.rmtree(target)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--survey",type=Path,required=True)
    p.add_argument("--out-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--synthetic-only",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        summary=build_canary(args.survey,args.out_dir,args.out)
        print("SAFE synthetic H5 canary summary:",args.out)
        print("Files:",len(summary["generated_files"]),
              "synthetic rows:",summary["synthetic_record_count"])
        print("Hikyuu native driver tested: NO; market mirror created: NO")
    except (ValueError,TypeError,OSError,RuntimeError,ImportError,KeyError) as e:
        p.error(str(e))


if __name__=="__main__":
    main()
