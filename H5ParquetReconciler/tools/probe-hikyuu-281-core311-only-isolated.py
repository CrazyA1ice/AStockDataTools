#!/usr/bin/env python3
"""Probe Hikyuu 2.8.1 *core311* bindings without importing hikyuu/__init__.py.

Strictly one-shot / synthetic-only. This probes native binding availability,
not real KData reading or Parquet/H5 field mapping. Never initializes
StockManager and never opens the user's live H5/stock.db configuration.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
FORMAT="AStockDataTools Hikyuu 2.8.1 isolated core311-only import preflight v1"
MARKER="ASTOCKTOOLS_HIKYUU_CORE311_SAFE:"
PHASE_MARKER="ASTOCKTOOLS_HIKYUU_CORE311_PHASE:"
PHASES=frozenset(("before_lookup","package_located","before_core_import",
                  "core_imported","finished"))
REQUIRED_APIS=("StockManager","Stock","Query","Parameter",
               "KDataDriver","DataDriverFactory","KRecord")
SPEC=importlib.util.spec_from_file_location(
    "hikyuu_canary_verifier",
    Path(__file__).resolve().parent/"probe-hikyuu-native-driver-runtime-isolated.py")
CHECK=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

# The installed Hikyuu 2.8.1 package normally imports its entire UI/plot stack
# from hikyuu/__init__.py. Our one-shot read-only binding probe must not import
# that initializer. Instead, locate the installed distribution, validate its
# package directory, register a Python-only namespace stub in sys.modules,
# then import ONLY the actual hikyuu.core and its cpp.core311 native extension.
# No on-disk package changes, no sys.path changes, no default user data/config.
WORKER=r'''
import importlib
import importlib.metadata
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

PREFIX="ASTOCKTOOLS_HIKYUU_CORE311_SAFE:"
PHASE="ASTOCKTOOLS_HIKYUU_CORE311_PHASE:"
API=("StockManager","Stock","Query","Parameter",
     "KDataDriver","DataDriverFactory","KRecord")
r={
 "status":"not_started",
 "distribution_version":None,
 "python311_confirmed":False,
 "package_location_verified":False,
 "core_loaded":False,
 "public_core_apis":{},
 "top_level_hikyuu_initializer_executed":False,
 "stock_manager_initialized":False,
 "native_h5_driver_called":False
}
phase="before_lookup"
print(PHASE+phase,flush=True)
try:
    v=importlib.metadata.version("hikyuu")
    if v!="2.8.1" or sys.version_info[:2]!=(3,11):
        r["status"]="unsupported_core311_environment"
    else:
        r["distribution_version"]=v
        r["python311_confirmed"]=True
        spec=importlib.util.find_spec("hikyuu")
        dist=importlib.metadata.distribution("hikyuu")
        installed=Path(dist.locate_file("hikyuu")).resolve()
        if (spec is None or spec.submodule_search_locations is None
                or len(spec.submodule_search_locations)!=1):
            raise RuntimeError("installed package spec not a normal package")
        found=Path(next(iter(spec.submodule_search_locations))).resolve()
        if (found!=installed or not found.is_dir() or found.is_symlink()
                or not (found/"__init__.py").is_file()
                or not (found/"core.py").is_file()
                or not (found/"cpp").is_dir()
                or (found/"cpp").is_symlink()):
            raise RuntimeError("core311 package root validation failed")
        phase="package_located"
        print(PHASE+phase,flush=True)
        r["package_location_verified"]=True
        # Prevent importlib from executing the heavyweight top-level
        # hikyuu/__init__.py. No attribute from Hikyuu's user configuration
        # or StockManager is evaluated before this native-only import.
        package=types.ModuleType("hikyuu")
        package.__path__=[str(found)]
        package.__package__="hikyuu"
        package.__spec__=spec
        sys.modules["hikyuu"]=package
        cpp=found/"cpp"
        if sys.platform=="win32":
            _hikyuu_dll=os.add_dll_directory(str(cpp))
            os.environ["PATH"]=str(cpp)+os.pathsep+os.environ.get("PATH","")
        phase="before_core_import"
        print(PHASE+phase,flush=True)
        core=importlib.import_module("hikyuu.core")
        r["core_loaded"]=True
        phase="core_imported"
        print(PHASE+phase,flush=True)
        r["public_core_apis"]={name:bool(hasattr(core,name)) for name in API}
        r["status"]=(
            "core311_bindings_ready"
            if all(r["public_core_apis"].values())
            else "core311_bindings_incomplete")
except ModuleNotFoundError:
    r["status"]="core311_package_missing_or_dependency_error"
except BaseException:
    r["status"]="core311_import_failed_at_"+phase
finally:
    print(PHASE+"finished",flush=True)
    print(PREFIX+json.dumps(r,sort_keys=True),flush=True)
    # This short-lived process may have loaded native bindings with atexit
    # callbacks. Flush the single result, then bypass Python atexit hooks.
    os._exit(0)
'''


def parse_core_worker(stdout,returncode):
    if returncode!=0 or not isinstance(stdout,str):
        return None
    lines=[line[len(MARKER):] for line in stdout.splitlines()
           if line.startswith(MARKER)]
    if len(lines)!=1:
        return None
    try:
        r=json.loads(lines[0])
    except (ValueError,TypeError):
        return None
    fields={"status","distribution_version","python311_confirmed",
            "package_location_verified","core_loaded","public_core_apis",
            "top_level_hikyuu_initializer_executed","stock_manager_initialized",
            "native_h5_driver_called"}
    if not isinstance(r,dict) or set(r)!=fields:
        return None
    if (type(r["status"]) is not str or len(r["status"])>90
            or r["distribution_version"] not in (None,"2.8.1")
            or any(type(r[k]) is not bool for k in (
                "python311_confirmed","package_location_verified","core_loaded",
                "top_level_hikyuu_initializer_executed",
                "stock_manager_initialized","native_h5_driver_called"))
            or r["top_level_hikyuu_initializer_executed"]
            or r["stock_manager_initialized"] or r["native_h5_driver_called"]
            or type(r["public_core_apis"]) is not dict
            or not set(r["public_core_apis"]).issubset(REQUIRED_APIS)
            or any(type(v) is not bool for v in r["public_core_apis"].values())):
        return None
    ready=r["status"]=="core311_bindings_ready"
    if ready != bool(
            r["distribution_version"]=="2.8.1"
            and r["python311_confirmed"]
            and r["package_location_verified"]
            and r["core_loaded"]
            and set(r["public_core_apis"])==set(REQUIRED_APIS)
            and all(r["public_core_apis"].values())):
        return None
    return r


def last_phase(stdout):
    if isinstance(stdout,bytes):
        stdout=stdout.decode("utf-8",errors="replace")
    if not isinstance(stdout,str):
        return None
    found=None
    for line in stdout.splitlines():
        if line.startswith(PHASE_MARKER):
            phase=line[len(PHASE_MARKER):]
            if phase in PHASES:
                found=phase
    return found


def probe_core(canary_report,out,python_exe,runner=subprocess.run,timeout=35):
    if type(timeout) is not int or not 10<=timeout<=90:
        raise ValueError("Core-only timeout must be an integer 10..90")
    if python_exe is None:
        raise ValueError("Core-only preflight requires an existing --python-exe")
    interpreter=CHECK._explicit_python(python_exe)
    canary=CHECK.verify_canary(canary_report)
    output=CHECK._module_output(out)
    sandbox=canary["isolated_canary_dir"]/"_core311_only_probe"
    if sandbox.is_symlink() or CHECK.WORK.is_symlink() or CHECK.MIRRORS.is_symlink():
        raise ValueError("Unsafe core-only sandbox")
    sandbox.mkdir(exist_ok=True)
    before=canary["source_file_details"]
    status="core311_subprocess_failed"
    phase=None
    worker=None
    try:
        proc=runner([str(interpreter),"-I","-c",WORKER],cwd=sandbox,
                    capture_output=True,text=True,timeout=timeout,check=False,
                    env=CHECK._sandbox_env(sandbox,interpreter))
        phase=last_phase(proc.stdout)
        worker=parse_core_worker(proc.stdout,proc.returncode)
        if worker is not None:
            status=worker["status"]
    except subprocess.TimeoutExpired as exc:
        status="core311_import_timeout"
        phase=last_phase(exc.stdout)
    except (OSError,ValueError,TypeError):
        status="core311_subprocess_failed"
    try:
        after=CHECK.verify_canary(canary_report)["source_file_details"]
    except (ValueError,OSError) as exc:
        raise ValueError("Synthetic H5 changed during core311 preflight") from exc
    if before!=after:
        raise ValueError("Synthetic H5 changed during core311 preflight")
    ready=worker is not None and status=="core311_bindings_ready"
    safe={
        "format":FORMAT,
        "canary_safe_summary_sha256":canary["report_sha256"],
        "canary_file_hashes_reverified":True,
        "isolated_core311_only":True,
        "explicit_python_executable_used":True,
        "hikyuu_core311_status":status,
        "last_core311_phase":phase,
        "hikyuu_distribution_version":(
            worker["distribution_version"] if worker else None),
        "public_core_api_presence":worker["public_core_apis"] if worker else {},
        "core311_bindings_ready":bool(ready),
        "hikyuu_full_package_imported":False,
        "stock_manager_initialized":False,
        "native_h5_driver_read_executed":False,
        "hikyuu_h5_compatibility_certified":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "full_market_mirror_allowed":False,
        "no_licensed_market_data_read":True,
        "original_market_files_modified":False,
        "original_hikyuu_config_modified":False,
        "private_overlay_activated":False,
        "no_raw_ohlcva_or_worker_logs_in_safe_summary":True,
    }
    with output.open("x",encoding="utf-8") as stream:
        json.dump(safe,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--canary-report",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--python-exe",type=Path,required=True)
    p.add_argument("--timeout-seconds",type=int,default=35)
    p.add_argument("--core-only-preflight",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        safe=probe_core(args.canary_report,args.out,args.python_exe,
                        timeout=args.timeout_seconds)
        print("SAFE Hikyuu 2.8.1 core-only probe:",args.out)
        print("Core311 status:",safe["hikyuu_core311_status"])
        print("Last core phase:",safe["last_core311_phase"])
        print("Native H5 driver executed: NO")
    except (ValueError,OSError,KeyError,TypeError) as exc:
        p.error(str(exc))


if __name__=="__main__":
    main()
