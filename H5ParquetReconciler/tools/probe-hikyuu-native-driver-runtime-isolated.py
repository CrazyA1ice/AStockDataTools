#!/usr/bin/env python3
"""Isolated Hikyuu native Python API preflight for SYNTHETIC H5 canary only.

This is a capability probe, NOT a native driver read: it never initializes
StockManager, imports hikyuu.interactive, loads live market data, or modifies
the user's ~/.hikyuu configuration. A later native read needs verified
version-specific driver APIs and an isolated market registry.

Only an exact pre-verified 2-stock synthetic canary and a NEW SAFE report
inside this module are permitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
REPORTS=MODULE/"reports"
WORK=MODULE/"work"
MIRRORS=WORK/"h5_mirror"
CANARY_FORMAT="AStockDataTools synthetic Hikyuu native day H5 canary summary v1"
FORMAT="AStockDataTools isolated Hikyuu native runtime capability preflight v1"
STOCKS={"SH600000":"sh_day.h5","SZ000001":"sz_day.h5"}
DATES=[202609300000,202610080000,202610130000]
MARKER="ASTOCKTOOLS_SAFE_HIKYUU_RUNTIME:"
WORKER=r'''
import importlib.metadata
import json
import sys
r={"module_imported":False,"runtime_status":"unknown",
   "installed_distribution_version":None,"public_api_presence":{},
   "native_h5_driver_called":False,
   "stock_manager_initialized":False,"default_hikyuu_config_loaded":False}
try:
    import hikyuu
except ModuleNotFoundError as exc:
    if exc.name=="hikyuu":
        r["runtime_status"]="hikyuu_not_installed_in_this_interpreter"
    else:
        r["runtime_status"]="hikyuu_missing_dependency"
except BaseException:
    r["runtime_status"]="hikyuu_import_failed"
else:
    r["module_imported"]=True
    r["runtime_status"]="hikyuu_imported_without_initializing"
    try:
        ver=importlib.metadata.version("hikyuu")
        if type(ver) is str and len(ver)<64:
            r["installed_distribution_version"]=ver
    except BaseException:
        pass
    names=["StockManager","Stock","Query","Parameter","KDataDriver",
           "DataDriverFactory","H5KDataDriver","hikyuu_init","KRecord"]
    r["public_api_presence"]={
        n:bool(hasattr(hikyuu,n)) for n in names}
print("ASTOCKTOOLS_SAFE_HIKYUU_RUNTIME:"+json.dumps(r,sort_keys=True))
'''


def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def _module_input(path):
    p=Path(path)
    if (REPORTS.is_symlink() or WORK.is_symlink()
            or MIRRORS.is_symlink() or p.is_symlink()
            or not p.is_file() or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Synthetic canary summary must be an existing module reports/ JSON")
    return p.resolve()


def _module_output(path):
    p=Path(path)
    if (REPORTS.is_symlink() or WORK.is_symlink()
            or MIRRORS.is_symlink() or p.is_symlink() or p.exists()
            or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Output must be a NEW SAFE JSON directly in module reports/")
    return p.resolve()


def verify_canary(canary_report):
    """Check source report shape, byte hashes and HDF5 key layout and dates.

    This function never reads actual original market files or licensed values.
    """
    import h5py

    report_path=_module_input(canary_report)
    report=json.loads(report_path.read_text(encoding="utf-8"))
    if (type(report) is not dict or report.get("format")!=CANARY_FORMAT
            or report.get("synthetic_only") is not True
            or report.get("synthetic_record_count")!=6
            or report.get("source_market_files_read") is not False
            or report.get("original_hikyuu_h5_read") is not False
            or report.get("purchased_parquet_read") is not False
            or report.get("original_market_files_modified") is not False
            or report.get("hikyuu_native_driver_tested") is not False
            or report.get("safe_for_full_market_h5_mirror") is not False
            or set(report.get("symbols",[]))!=set(STOCKS)):
        raise ValueError("Cannot use untrusted or non-synthetic H5 report")
    files=report.get("generated_files")
    if type(files) is not list or len(files)!=2:
        raise ValueError("Expected two synthetic H5 source files")
    seen=set()
    found=[]
    parent=None
    for item in files:
        if not isinstance(item,dict) or item.get("stock") not in STOCKS:
            raise ValueError("Invalid synthetic H5 report stock")
        stock=item["stock"]
        if stock in seen or item.get("synthetic_rows")!=3 or (
                item.get("dtype_itemsize_bytes")!=40
                or item.get("pytables_table") is not True
                or item.get("h5py_and_pytables_roundtrip_values_equal") is not True):
            raise ValueError("Invalid synthetic H5 canary row/layout evidence")
        seen.add(stock)
        p=MIRRORS/item.get("relative_output","").removeprefix("work/h5_mirror/")
        if (p.name!=STOCKS[stock] or not p.is_file()
                or p.is_symlink()
                or not p.resolve().is_relative_to(MIRRORS.resolve())):
            raise ValueError("Unsafe/missing synthetic H5 canary file")
        if p.resolve().parent.parent!=MIRRORS.resolve():
            raise ValueError("Synthetic canary must be direct H5 mirror child directory")
        if parent is None:
            parent=p.resolve().parent
        elif parent!=p.resolve().parent:
            raise ValueError("Synthetic H5 files must have same isolated parent")
        if digest(p)!=item.get("sha256"):
            raise ValueError("Synthetic H5 file digest differs from SAFE report")
        with h5py.File(p,"r") as h:
            ds=h.get("data/"+stock)
            if not isinstance(ds,h5py.Dataset):
                raise ValueError("Missing native synthetic H5 dataset")
            if len(ds)!=3 or ds.dtype.itemsize!=40:
                raise ValueError("Synthetic native H5 dataset rows/dtype changed")
            if [int(x) for x in ds["datetime"][:]]!=DATES:
                raise ValueError("Synthetic date labels changed")
        found.append(p)
    if len(seen)!=2 or parent is None or parent.is_symlink():
        raise ValueError("Synthetic H5 canary incomplete")
    return {"report_sha256":digest(report_path),
            "isolated_canary_dir":parent,
            "source_file_details":{f.name:{
                "sha256":digest(f),"size_bytes":f.stat().st_size}
                for f in found}}


def _sandbox_env(target):
    env=dict(os.environ)
    for k in list(env):
        if k.upper().startswith(("HIKYUU_","HKU_")):
            del env[k]
    # The worker is a child process and uses a private config/home root.
    # No hikyuu_init / interactive import is called even in this sandbox.
    for name in ("HOME","USERPROFILE","APPDATA","LOCALAPPDATA",
                 "XDG_CONFIG_HOME","TMP","TEMP","TMPDIR"):
        env[name]=str(target)
    if os.name=="nt":
        drive,tail=os.path.splitdrive(str(target))
        env["HOMEDRIVE"]=drive
        env["HOMEPATH"]=tail
    env["PYTHONNOUSERSITE"]="1"
    return env


def parse_worker(stdout,returncode):
    lines=[s[len(MARKER):] for s in stdout.splitlines()
           if s.startswith(MARKER)]
    if returncode!=0 or len(lines)!=1:
        raise ValueError("Hikyuu child-process import failed or terminated")
    data=json.loads(lines[0])
    allowed={"module_imported","runtime_status",
             "installed_distribution_version","public_api_presence",
             "native_h5_driver_called","stock_manager_initialized",
             "default_hikyuu_config_loaded"}
    if (type(data) is not dict or set(data)!=allowed
            or data["native_h5_driver_called"] is not False
            or data["stock_manager_initialized"] is not False
            or data["default_hikyuu_config_loaded"] is not False
            or type(data["module_imported"]) is not bool
            or data["runtime_status"] not in (
                "hikyuu_not_installed_in_this_interpreter",
                "hikyuu_missing_dependency","hikyuu_import_failed",
                "hikyuu_imported_without_initializing")
            or type(data["public_api_presence"]) is not dict
            or not all(type(v) is bool for v in
                       data["public_api_presence"].values())):
        raise ValueError("Unsafe or invalid Hikyuu subprocess result")
    return data


def runtime_preflight(report,out,runner=subprocess.run,timeout=20):
    canary=verify_canary(report)
    output=_module_output(out)
    sandbox=canary["isolated_canary_dir"]/"_runtime_preflight"
    if sandbox.is_symlink() or WORK.is_symlink() or MIRRORS.is_symlink():
        raise ValueError("Runtime isolation sandbox must not be symlinked")
    sandbox.mkdir(exist_ok=True)
    sources_before=canary["source_file_details"]
    runtime_status="hikyuu_subprocess_unavailable"
    worker_result=None
    try:
        proc=runner([sys.executable,"-I","-c",WORKER],cwd=sandbox,
                    capture_output=True,text=True,timeout=timeout,
                    env=_sandbox_env(sandbox),check=False)
        worker_result=parse_worker(proc.stdout,proc.returncode)
        runtime_status=worker_result["runtime_status"]
    except subprocess.TimeoutExpired:
        runtime_status="hikyuu_import_timeout"
    except (ValueError,OSError,TypeError):
        runtime_status="hikyuu_subprocess_failed"
    try:
        sources_after=verify_canary(report)["source_file_details"]
    except (ValueError,OSError) as exc:
        raise ValueError(
            "Synthetic canary changed during native runtime preflight") from exc
    if sources_after!=sources_before:
        raise ValueError("Synthetic canary changed during native runtime preflight")
    safe={
        "format":FORMAT,
        "canary_safe_summary_sha256":canary["report_sha256"],
        "canary_file_hashes_reverified":True,
        "synthetic_canary_stocks":sorted(STOCKS),
        "isolation_environment_used":True,
        "worker_imports_hikyuu_but_never_initializes_stock_manager":True,
        "hikyuu_runtime_status":runtime_status,
        "installed_hikyuu_version":(
            worker_result["installed_distribution_version"]
            if worker_result else None),
        "hikyuu_api_presence":(
            worker_result["public_api_presence"] if worker_result else {}),
        "native_h5_driver_read_executed":False,
        "hikyuu_h5_compatibility_certified":False,
        "full_market_mirror_allowed":False,
        "no_licensed_market_data_read":True,
        "original_market_files_modified":False,
        "original_hikyuu_config_modified":False,
        "private_overlay_activated":False,
        "no_raw_ohlcva_in_safe_summary":True,
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x",encoding="utf-8") as f:
        json.dump(safe,f,indent=2,ensure_ascii=False)
        f.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--canary-report",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--isolated-preflight",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        safe=runtime_preflight(args.canary_report,args.out)
        print("SAFE Hikyuu runtime probe:",args.out)
        print("Runtime status:",safe["hikyuu_runtime_status"])
        print("Native HDF5 driver executed: NO")
    except (ValueError,TypeError,KeyError,OSError,ImportError) as exc:
        p.error(str(exc))


if __name__=="__main__":
    main()
