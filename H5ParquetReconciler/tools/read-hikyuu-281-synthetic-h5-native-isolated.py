#!/usr/bin/env python3
"""Try REAL Hikyuu 2.8.1 C++ native KData reads, strictly SYNTHETIC + isolated.

Unlike h5py/PyTables smoke tests, this attempts StockManager().get_stock()
and Stock.get_kdata(Query(0,3,Query.DAY)) with an isolated synthetic SQLite
security registry and ONLY previously hash-verified synthetic H5 canaries.

No default hikyuu_init(), no live DB, no original H5/Parquet, no production
route change, no full-market mirror authorization. Subprocess failures do not
count as compatible. All outputs remain module work/ and reports/.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MODULE=Path(__file__).resolve().parent.parent
REPORTS=MODULE/"reports"
WORK=MODULE/"work"
MIRRORS=WORK/"h5_mirror"
FORMAT="AStockDataTools isolated synthetic Hikyuu 2.8.1 native H5 read verification v1"
MARKER="ASTOCKTOOLS_NATIVE_H5_281_RESULT:"

SPEC=importlib.util.spec_from_file_location(
    "synthetic_native_preflight_verifier",
    Path(__file__).resolve().parent/"probe-hikyuu-native-driver-runtime-isolated.py")
CHECK=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

# SECURITY CONTRACT: always run in an isolated child. Only synthetic H5 paths
# supplied after parent verified original report/file SHA. DB built from
# hard-coded fictional registry, never copied from user's stock.db.
WORKER=r'''
import importlib.metadata
import json
import os
import sqlite3
import sys
from pathlib import Path

PREFIX="ASTOCKTOOLS_NATIVE_H5_281_RESULT:"
out={
 "state":"not_started",
 "hikyuu_imported":False,
 "hikyuu_281_version_confirmed":False,
 "synthetic_registry_initialized":False,
 "stock_manager_initialized":False,
 "native_h5_kdata_method_called":False,
 "native_h5_values_matched":False,
 "per_symbol_matching_rows":{"SH600000":0,"SZ000001":0},
 "source_market_files_accessed":False,
 "production_query_switched":False
}
stage="import"
try:
    import hikyuu as hk
    out["hikyuu_imported"]=True
    version=importlib.metadata.version("hikyuu")
    if version!="2.8.1":
        out["state"]="unsupported_installed_hikyuu_version"
        raise RuntimeError("guard: different hikyuu wheel version")
    out["hikyuu_281_version_confirmed"]=True
    stage="registry"
    # argv is only: private run dir, verified synthetic sh_day, verified
    # synthetic sz_day. No paths to original market sources are supplied.
    root=Path(sys.argv[1]).resolve()
    sh=Path(sys.argv[2]).resolve()
    sz=Path(sys.argv[3]).resolve()
    if (root!=Path.cwd().resolve()
            or root.parent.name!="_native_h5_281"
            or sh.parent!=sz.parent
            or root.parent.parent!=sh.parent
            or sh.name!="sh_day.h5"
            or sz.name!="sz_day.h5"
            or not sh.is_file() or not sz.is_file()):
        raise RuntimeError("synthetic-only folder invariant failed")
    # Also require no preexisting registry: never open user stock.db.
    db=root/"fictional_registry.sqlite3"
    if db.exists() or db.is_symlink():
        raise RuntimeError("fictional registration database already exists")
    with sqlite3.connect(db) as cx:
        cx.executescript("""
        CREATE TABLE Market (
          marketid INTEGER PRIMARY KEY, market TEXT, name TEXT,
          description TEXT, code TEXT, lastDate INTEGER,
          openTime1 INTEGER, closeTime1 INTEGER, openTime2 INTEGER,
          closeTime2 INTEGER);
        CREATE TABLE StockTypeInfo (
          id INTEGER PRIMARY KEY, type INTEGER, precision INTEGER,
          tick REAL, tickValue REAL, minTradeNumber INTEGER,
          maxTradeNumber INTEGER, description TEXT);
        CREATE TABLE Stock (
          stockid INTEGER PRIMARY KEY, marketid INTEGER, code TEXT,
          name TEXT, type INTEGER, valid INTEGER,
          startDate INTEGER, endDate INTEGER);
        CREATE TABLE stkWeight (
          id INTEGER PRIMARY KEY, stockid INTEGER, date INTEGER,
          countAsGift INTEGER, countForSell INTEGER,
          priceForSell INTEGER, bonus INTEGER, countOfIncreasement INTEGER,
          totalCount INTEGER, freeCount INTEGER, suogu INTEGER);
        CREATE TABLE Block (
          id INTEGER PRIMARY KEY, category TEXT, name TEXT,
          market_code TEXT);
        CREATE TABLE BlockIndex (
          category TEXT, name TEXT, market_code TEXT);
        CREATE TABLE Holiday (date INTEGER);
        CREATE TABLE ZhBond10 (date INTEGER, value INTEGER);
        CREATE TABLE HistoryFinanceField (id INTEGER, name TEXT);
        """)
        cx.executemany(
          "INSERT INTO Market VALUES (?,?,?,?,?,?,?,?,?,?)",
          [(1,"SH","Fictional SH","synthetic only","000001",20261013,0,0,0,0),
           (2,"SZ","Fictional SZ","synthetic only","399001",20261013,0,0,0,0)])
        cx.execute("INSERT INTO StockTypeInfo VALUES (1,1,2,0.01,0.01,100,1000000,'synthetic')")
        cx.executemany(
          "INSERT INTO Stock VALUES (?,?,?,?,?,?,?,?)",
          [(1,1,"600000","Synthetic SH",1,1,20260930,20261014),
           (2,2,"000001","Synthetic SZ",1,1,20260930,20261014)])
        cx.commit()
    out["synthetic_registry_initialized"]=True
    stage="stock_manager"
    def p(**kwargs):
        obj=hk.Parameter()
        for name,value in kwargs.items():
            obj[name]=value
        return obj
    # NEVER call hk.hikyuu_init or import hikyuu.interactive, which might
    # pick up default user config or live commercial stock database.
    base=p(type="sqlite3",db=str(db))
    block=p(type="sqlite3",db=str(db))
    kdata=p(type="hdf5",sh_day=str(sh),sz_day=str(sz))
    preload=p(day=False,week=False,month=False,min=False,min5=False)
    extras=p(tmpdir=str(root),datadir=str(root),
             load_history_finance=False,lazy_preload=False,
             use_shm_server=False,load_stock_weight=False)
    sm=hk.StockManager.instance()
    # Package import can set a plugin directory globally. Explicitly replace
    # it BEFORE init to prevent installed/external plugin discovery.
    empty_plugin_dir=root/"empty_plugins"
    empty_plugin_dir.mkdir(exist_ok=False)
    sm.set_plugin_path(str(empty_plugin_dir))
    sm.init(base,block,kdata,preload,extras)
    sm.wait_data_ready()
    out["stock_manager_initialized"]=True
    stage="native_read"
    days=[20260930,20261008,20261013]
    for venue,code,seed in (("SH","600000",1),("SZ","000001",2)):
        symbol=venue+code
        stock=sm.get_stock(symbol)
        if stock.is_null():
            out["state"]="fictional_stock_registration_failed"
            raise RuntimeError("missing fictional security")
        # Native Stock.get_kdata invokes the Hikyuu C++ hdf5 driver.
        out["native_h5_kdata_method_called"]=True
        records=stock.get_kdata(hk.Query(0,3,hk.Query.DAY))
        if len(records)!=3:
            out["state"]="native_h5_row_count_mismatch"
            raise RuntimeError("wrong native KRecord count")
        for i,record in enumerate(records):
            base_value=10000+seed*50+i*100
            expected=(
              base_value*0.001,
              (base_value+200)*0.001,
              (base_value-200)*0.001,
              (base_value+50)*0.001,
              (100000+seed*1000+i*100)*0.1,
              float(1200+seed*10+i))
            actual=(
              record.open,record.high,record.low,record.close,
              record.amount,record.volume)
            if (int(record.datetime.ymd)!=days[i] or any(
                    abs(float(a)-float(b))>1e-8
                    for a,b in zip(actual,expected))):
                out["state"]="native_h5_value_mismatch"
                raise RuntimeError("Hikyuu decoded a synthetic field incorrectly")
            out["per_symbol_matching_rows"][symbol]+=1
    out["native_h5_values_matched"]=True
    out["state"]="native_h5_six_synthetic_rows_matched"
except BaseException as ex:
    if out["state"]=="not_started":
        out["state"]="native_runtime_failed_at_"+stage
finally:
    # hikyuu==2.8.1 registers an atexit hku_cleanup callback that can
    # wait indefinitely if StockManager never becomes data_ready. This
    # one-shot child owns ONLY newly-created fictional SQLite and read-only
    # synthetic H5: emit a complete SAFE result and bypass that callback.
    # A native crash or deadlock BEFORE this point remains a failure/timeout.
    print(PREFIX+json.dumps(out,sort_keys=True),flush=True)
    os._exit(0)
'''


def parse_native(stdout,returncode):
    lines=[line[len(MARKER):] for line in stdout.splitlines()
           if line.startswith(MARKER)]
    if returncode!=0 or len(lines)!=1:
        return None
    try:
        v=json.loads(lines[0])
    except (ValueError,TypeError):
        return None
    required={
        "state","hikyuu_imported","hikyuu_281_version_confirmed",
        "synthetic_registry_initialized","stock_manager_initialized",
        "native_h5_kdata_method_called","native_h5_values_matched",
        "per_symbol_matching_rows","source_market_files_accessed",
        "production_query_switched"}
    if (not isinstance(v,dict) or set(v)!=required
            or not isinstance(v["state"],str)
            or len(v["state"])>90
            or any(type(v[k]) is not bool for k in required-{
                "state","per_symbol_matching_rows"})
            or v["source_market_files_accessed"]
            or v["production_query_switched"]
            or type(v["per_symbol_matching_rows"]) is not dict
            or set(v["per_symbol_matching_rows"])!={"SH600000","SZ000001"}
            or any(type(n) is not int or n<0 or n>3
                   for n in v["per_symbol_matching_rows"].values())):
        return None
    passed=v["state"]=="native_h5_six_synthetic_rows_matched"
    if passed and not (
            all(v[k] for k in (
                "hikyuu_imported","hikyuu_281_version_confirmed",
                "synthetic_registry_initialized","stock_manager_initialized",
                "native_h5_kdata_method_called","native_h5_values_matched"))
            and list(v["per_symbol_matching_rows"].values())==[3,3]):
        return None
    if not passed and v["native_h5_values_matched"]:
        return None
    return v


def native_read(canary_report, output, python_exe, runner=subprocess.run,
                timeout=45, run_id="run001"):
    """Run isolated native read; only machine-state metadata leaves worker."""
    if python_exe is None:
        raise ValueError("--python-exe must select a pre-existing Hikyuu environment")
    interpreter=CHECK._explicit_python(python_exe)
    file_check=CHECK.verify_canary(canary_report)
    report_dest=CHECK._module_output(output)
    canary_dir=file_check["isolated_canary_dir"]
    if (WORK.is_symlink() or MIRRORS.is_symlink()
            or canary_dir.is_symlink()):
        raise ValueError("Unsafe mirror path")
    # Allow safe retries with a NEW run ID, never overwrite earlier scratch.
    if type(run_id) is not str or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,39}",run_id):
        raise ValueError("Use a safe --run-id such as run001")
    root=canary_dir/"_native_h5_281"
    stage=root/run_id
    if (root.is_symlink() or (root.exists() and not root.is_dir())
            or stage.exists() or stage.is_symlink()):
        raise ValueError("Native run ID already exists or unsafe; choose a NEW --run-id")
    root.mkdir(exist_ok=True)
    stage.mkdir(exist_ok=False)
    runtime_status="native_subprocess_unavailable"
    result=None
    try:
        try:
            proc=runner(
                [str(interpreter),"-I","-c",WORKER,
                 str(stage),str(canary_dir/"sh_day.h5"),
                 str(canary_dir/"sz_day.h5")],
                cwd=stage,capture_output=True,text=True,
                timeout=timeout,check=False,
                env=CHECK._sandbox_env(stage,interpreter))
            result=parse_native(proc.stdout,proc.returncode)
            runtime_status=(
                result["state"] if result else "native_subprocess_invalid_or_crashed")
        except subprocess.TimeoutExpired:
            runtime_status="native_subprocess_timeout"
        except (ValueError,OSError,TypeError):
            runtime_status="native_subprocess_spawn_failed"
        try:
            after=CHECK.verify_canary(canary_report)["source_file_details"]
        except (OSError,ValueError) as ex:
            raise ValueError("Synthetic source changed during native read") from ex
        if after!=file_check["source_file_details"]:
            raise ValueError("Synthetic source changed during native read")
        success=(result is not None and result["state"]==
                 "native_h5_six_synthetic_rows_matched")
        safe={
            "format":FORMAT,
            "canary_safe_summary_sha256":file_check["report_sha256"],
            "canary_h5_hashes_reverified":True,
            "synthetic_only":True,
            "native_hikyuu_runtime_version_expected":"2.8.1",
            "native_h5_read_status":runtime_status,
            "native_stock_manager_initialized":bool(
                result["stock_manager_initialized"] if result else False),
            "native_h5_get_kdata_called":bool(
                result["native_h5_kdata_method_called"] if result else False),
            "per_symbol_matching_rows":(
                result["per_symbol_matching_rows"] if result else
                {"SH600000":0,"SZ000001":0}),
            "native_h5_synthetic_six_records_matched":bool(success),
            "native_h5_compatibility_certified_for_synthetic_v1":bool(success),
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
            "no_licensed_market_data_read":True,
            "original_market_files_modified":False,
            "production_query_route_modified":False,
            "private_overlay_activated":False,
            "no_raw_ohlcva_in_safe_summary":True,
            "native_worker_stdout_stderr_not_saved":True,
        }
        # Keep logs from actual Hikyuu runtime entirely inside scratch
        # and do not leak path/user info into the SAFE summary.
        with report_dest.open("x",encoding="utf-8") as fp:
            json.dump(safe,fp,indent=2,ensure_ascii=False)
            fp.write("\n")
        return safe
    finally:
        # Never delete user's preexisting files: root was just created.
        # Deliberately retain only the isolated fictional registry and logs
        # in work/ for troubleshooting; no user market data here.
        pass


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--canary-report",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--python-exe",type=Path,required=True)
    p.add_argument("--run-id",default="run001",
                   help="NEW synthetic-only scratch name; use run002 for retry")
    p.add_argument("--synthetic-native-read",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        safe=native_read(args.canary_report,args.out,args.python_exe,
                         run_id=args.run_id)
        print("SAFE native Hikyuu 2.8.1 verification:",args.out)
        print("Status:",safe["native_h5_read_status"])
        print("Matched synthetic records:",
              safe["per_symbol_matching_rows"])
        print("Real market H5/Parquet read: NO")
    except (ValueError,TypeError,KeyError,OSError,ImportError) as e:
        p.error(str(e))


if __name__=="__main__":
    main()
