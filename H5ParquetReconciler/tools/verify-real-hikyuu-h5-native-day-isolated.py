#!/usr/bin/env python3
"""Bounded read-only native Hikyuu 2.8.1 real H5 day verification.

Parent reads TWO exact original H5 records, computes random-key HMACs.
Isolated native C++ core311 child loads an ephemeral *fictional registry*
and reads at most 64 recent native KRecords from each original H5 source.
Only MACs cross the process boundary; no OHLCVA, raw H5 integers or source
paths are ever written to reports or passed as command line value arguments.
No official Parquet physical units or production data mapping is certified.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
FORMAT="AStockDataTools isolated real Hikyuu 2.8.1 two-stock-day native H5 HMAC v1"
MARKER=b"ASTOCK_NATIVE_REAL_DAY_HMAC:"
STAGE_MARKER=b"ASTOCK_NATIVE_REAL_DAY_PHASE:"
PHASES=frozenset(("before_core","core_ready","registry_ready",
                   "stock_manager_ready","before_native",
                   "before_stock_lookup","before_count","count_ready",
                   "before_query","query_ready","before_get_kdata",
                   "kdata_returned","target_found","before_hmac",
                   "native_complete","finished"))
FAIL_STAGES=frozenset(("before_core","before_registry","before_stock_manager",
                       "before_stock_lookup","before_count",
                       "before_query","before_get_kdata","kdata_returned",
                       "target_found","before_hmac"))
SAFE_NATIVE_FAILS=frozenset(("native_no_day_rows","native_day_count_exceeds_budget",
                            "native_kdata_count_invalid","native_target_day_not_found",
                            "native_target_day_duplicate"))
WORK=MODULE/"work"/"h5_mirror"/"real_day_native"
SYMBOLS=("SH600000","SZ000001")
DAY="2026-09-30"
RAW=("datetime","openPrice","highPrice","lowPrice","closePrice",
     "transCount","transAmount")
FIELD_TYPES={"openPrice":(0,1<<32),"highPrice":(0,1<<32),
             "lowPrice":(0,1<<32),"closePrice":(0,1<<32),
             "transCount":(0,1<<53),"transAmount":(0,1<<53)}
MAX_STOCK_ROWS=25000
MAX_NATIVE_TAIL=64

def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

RAW_GATE=load("real_h5_raw_factor_proof","probe-real-parquet-h5-day-unit-factors-readonly.py")
NATIVE=load("prior_isolated_native_synthetic","read-hikyuu-281-synthetic-h5-native-isolated.py")
AUDIT=RAW_GATE.AUDIT

# Exact amount and volume scaling here is the native H5 C++ decoder contract:
# price raw*0.001, transAmount raw*0.1, transCount raw*1.
# These are *H5 source* decoded units, NOT purchased Parquet units.
def signed_record(mac_key,symbol,values):
    if symbol not in SYMBOLS or type(values) is not dict or set(values)!=set(RAW):
        raise ValueError("Invalid fixed H5 source record shape")
    if type(mac_key) is not bytes or len(mac_key)!=32:
        raise ValueError("Unusable HMAC key")
    parts=[symbol,str(values["datetime"])]
    for field in RAW[1:]:
        v=values[field]
        if type(v) is not int:
            raise ValueError("H5 raw fields require strict integers")
        limit=FIELD_TYPES[field]
        if not limit[0]<=v<limit[1]:
            raise ValueError("H5 source integer precision/range gate failed")
        parts.append(str(v))
    return hmac.new(mac_key,"|".join(parts).encode("ascii"),
                    hashlib.sha256).hexdigest()


def verify_previous(path):
    d=json.loads(AUDIT._path(path,True).read_text(encoding="utf-8"))
    if (type(d) is not dict or d.get("format")!=RAW_GATE.FORMAT
            or d.get("sample_day")!=DAY
            or d.get("two_selected_stock_days_compared")!=2
            or d.get("h5_raw_day_records_read")!=2
            or d.get("raw_h5_record_used_not_native_cpp_driver_decoding") is not True
            or d.get("sources_read_only_no_h5_or_parquet_writes") is not True
            or d.get("no_real_ohlcva_or_raw_timestamp_values_in_report") is not True
            or d.get("parquet_vendor_physical_amount_unit_certified") is not False
            or d.get("parquet_vendor_physical_volume_unit_certified") is not False
            or d.get("native_hikyuu_driver_unit_mapping_certified") is not False
            or d.get("licensed_parquet_to_h5_mapping_certified") is not False
            or d.get("ready_for_full_market_mirror") is not False
            or type(d.get("comparison")) is not dict):
        raise ValueError("Requires prior successful two-source original-H5 SAFE")
    cand=d["comparison"].get(
        "candidate_factor_multiply_raw_h5_record_to_parquet_value")
    if (type(cand) is not dict or set(cand)!=set(("volume","amount"))
            or cand["volume"].get("100")!=2
            or cand["amount"].get("1000")!=2):
        raise ValueError("Prior raw H5 numerical factor candidates changed")
    return d


def paths(root):
    p=Path(root)
    if (not p.is_absolute() or p.is_symlink() or not p.is_dir()
            or p.resolve()!=p):
        raise ValueError("H5 source root must be a canonical direct absolute folder")
    files={symbol:RAW_GATE._plain_h5_path(p,symbol) for symbol in SYMBOLS}
    return files


def raw_expected(files,key,h5py,np):
    vals={}
    before={name:(path.stat().st_size,path.stat().st_mtime_ns)
            for name,path in files.items()}
    for symbol,path in files.items():
        values=RAW_GATE._read_single_h5(
            path.parent,symbol,DAY,h5py,np)
        vals[symbol]=signed_record(key,symbol,values)
    return vals,before


def unchanged(files,before):
    return all((path.stat().st_size,path.stat().st_mtime_ns)==before[symbol]
               for symbol,path in files.items())


def lines(stdout,prefix):
    if not isinstance(stdout,(bytes,bytearray)):
        return []
    return [item[len(prefix):] for item in bytes(stdout).splitlines()
            if item.startswith(prefix)]


def decode_status(stdout,code):
    if code!=0:
        return None
    msgs=lines(stdout,MARKER)
    if len(msgs)!=1 or len(msgs[0])>1000:
        return None
    try:
        doc=json.loads(msgs[0].decode("ascii"))
    except (ValueError,UnicodeError):
        return None
    expected={"state","core311","registry_only_temp",
              "stock_manager_initialized","native_get_kdata_called",
              "h5_file_read_only","records_examined_per_stock",
              "hmac_by_stock"}
    if type(doc) is not dict or set(doc)!=expected:
        return None
    if any(type(doc[x]) is not bool for x in ("core311","registry_only_temp",
            "stock_manager_initialized","native_get_kdata_called",
            "h5_file_read_only")):
        return None
    if (type(doc["state"]) is not str or
            doc["state"] not in (
                {"native_complete","runtime_unavailable"}
                | SAFE_NATIVE_FAILS
                | {"failed_at_"+step for step in FAIL_STAGES}) or
            type(doc["records_examined_per_stock"]) is not dict or
            set(doc["records_examined_per_stock"])!=set(SYMBOLS) or
            any(type(v) is not int or not 0<=v<=MAX_NATIVE_TAIL
                for v in doc["records_examined_per_stock"].values()) or
            type(doc["hmac_by_stock"]) is not dict or
            set(doc["hmac_by_stock"])!=set(SYMBOLS) or
            any(type(v) is not str or (v and not re.fullmatch(r"[0-9a-f]{64}",v))
                for v in doc["hmac_by_stock"].values())):
        return None
    return doc


# The child imports *only* the compiled core311, as the successful synthetic
# test does. Parent passes only stage/H5 PATHS as argv, and HMAC key as a
# transient environment variable. No raw OHLCVA/int64/price values in argv.
WORKER=r'''
import hashlib,hmac,importlib,importlib.metadata,importlib.util,json,os,sqlite3,sys,types
from pathlib import Path
PREFIX="ASTOCK_NATIVE_REAL_DAY_HMAC:"
PHASE="ASTOCK_NATIVE_REAL_DAY_PHASE:"
NAMES=("SH600000","SZ000001")
out={"state":"runtime_unavailable","core311":False,"registry_only_temp":False,
     "stock_manager_initialized":False,"native_get_kdata_called":False,
     "h5_file_read_only":True,
     "records_examined_per_stock":{s:0 for s in NAMES},
     "hmac_by_stock":{s:"" for s in NAMES}}
def mark(phase):
    print(PHASE+phase,flush=True)
mark("before_core")
failure_step="before_core"
try:
    stage=Path(sys.argv[1]).resolve()
    sh=Path(sys.argv[2]).resolve()
    sz=Path(sys.argv[3]).resolve()
    if (stage!=Path.cwd().resolve() or stage.name.startswith(".")
            or stage.parent.name!="real_day_native"
            or sh.name!="sh_day.h5" or sz.name!="sz_day.h5"
            or not sh.is_file() or not sz.is_file()
            or sh.is_symlink() or sz.is_symlink()):
        raise RuntimeError("unsafe isolated native paths")
    key=bytes.fromhex(os.environ.pop("ASTOCK_NATIVE_REAL_HMAC_SECRET"))
    if len(key)!=32:
        raise RuntimeError("invalid transient key")
    if (sys.version_info[:2]!=(3,11) or
            importlib.metadata.version("hikyuu")!="2.8.1"):
        raise RuntimeError("Only Python311/Hikyuu2.8.1 validated")
    spec=importlib.util.find_spec("hikyuu")
    dist=importlib.metadata.distribution("hikyuu")
    installed=Path(dist.locate_file("hikyuu")).resolve()
    found=Path(next(iter(spec.submodule_search_locations))).resolve()
    if (found!=installed or not (found/"core.py").is_file()
            or not (found/"cpp").is_dir() or (found/"cpp").is_symlink()):
        raise RuntimeError("native package not safely resolved")
    fake=types.ModuleType("hikyuu")
    fake.__path__=[str(found)]
    fake.__package__="hikyuu"
    fake.__spec__=spec
    sys.modules["hikyuu"]=fake
    cpp=found/"cpp"
    if sys.platform=="win32":
        holder=os.add_dll_directory(str(cpp))
        os.environ["PATH"]=str(cpp)+os.pathsep+os.environ.get("PATH","")
    hk=importlib.import_module("hikyuu.core")
    native=sys.modules.get("hikyuu.cpp.core311")
    path=Path(getattr(native,"__file__","")).resolve()
    if (path.suffix.lower() not in (".pyd",".so") or
            not path.is_relative_to(cpp.resolve())):
        raise RuntimeError("compiled native core311 missing")
    out["core311"]=True
    mark("core_ready")
    failure_step="before_registry"
    db=stage/"isolated_fictional_registry.sqlite3"
    if db.exists():
        raise RuntimeError("existing registry forbidden")
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE Market (marketid INTEGER PRIMARY KEY,market TEXT,name TEXT,
          description TEXT,code TEXT,lastDate INTEGER,openTime1 INTEGER,
          closeTime1 INTEGER,openTime2 INTEGER,closeTime2 INTEGER);
        CREATE TABLE StockTypeInfo (id INTEGER PRIMARY KEY,type INTEGER,
          precision INTEGER,tick REAL,tickValue REAL,minTradeNumber INTEGER,
          maxTradeNumber INTEGER,description TEXT);
        CREATE TABLE Stock (stockid INTEGER PRIMARY KEY,marketid INTEGER,
          code TEXT,name TEXT,type INTEGER,valid INTEGER,startDate INTEGER,endDate INTEGER);
        CREATE TABLE stkWeight (id INTEGER PRIMARY KEY,stockid INTEGER,date INTEGER,
          countAsGift INTEGER,countForSell INTEGER,priceForSell INTEGER,
          bonus INTEGER,countOfIncreasement INTEGER,totalCount INTEGER,
          freeCount INTEGER,suogu INTEGER);
        CREATE TABLE Block (id INTEGER PRIMARY KEY,category TEXT,name TEXT,market_code TEXT);
        CREATE TABLE BlockIndex (category TEXT,name TEXT,market_code TEXT);
        CREATE TABLE Holiday (date INTEGER);
        CREATE TABLE ZhBond10 (date INTEGER,value INTEGER);
        CREATE TABLE HistoryFinanceField (id INTEGER,name TEXT);
        """)
        conn.executemany("INSERT INTO Market VALUES (?,?,?,?,?,?,?,?,?,?)",
          [(1,"SH","Isolated SH","two-source proof only","000001",20261029,0,0,0,0),
           (2,"SZ","Isolated SZ","two-source proof only","399001",20261029,0,0,0,0)])
        conn.execute("INSERT INTO StockTypeInfo VALUES (1,1,2,0.01,0.01,100,1000000,'isolated')")
        conn.executemany("INSERT INTO Stock VALUES (?,?,?,?,?,?,?,?)",
          [(1,1,"600000","Isolated stock SH",1,1,20260901,20991231),
           (2,2,"000001","Isolated stock SZ",1,1,20260901,20991231)])
        conn.commit()
    out["registry_only_temp"]=True
    mark("registry_ready")
    failure_step="before_stock_manager"
    def p(**kw):
        obj=hk.Parameter()
        for k,v in kw.items(): obj[k]=v
        return obj
    # C++ HDF5 driver source opening mode is not independently asserted here.
    # Original src stat is checked in parent before/after; driver data writes
    # are neither requested nor authorized.
    sm=hk.StockManager.instance()
    plugin=stage/"empty_plugins"
    plugin.mkdir(exist_ok=False)
    sm.set_plugin_path(str(plugin))
    sm.init(p(type="sqlite3",db=str(db)),
            p(type="sqlite3",db=str(db)),
            p(type="hdf5",sh_day=str(sh),sz_day=str(sz)),
            p(day=False,week=False,month=False,min=False,min5=False),
            p(tmpdir=str(stage),datadir=str(stage),
              load_history_finance=False,lazy_preload=False,
              use_shm_server=False,load_stock_weight=False))
    sm.wait_data_ready()
    out["stock_manager_initialized"]=True
    mark("stock_manager_ready")
    mark("before_native")
    for symbol in NAMES:
        failure_step="before_stock_lookup"
        mark(failure_step)
        stock=sm.get_stock(symbol)
        if stock.is_null():
            raise RuntimeError("real stock registration unavailable")
        # An older synthetic native trial passed Query(0,3,Query.DAY).
        # Query(-64,Query.DAY) can bind the second positional argument as
        # the END INDEX, not the KType. Use exactly that successful
        # three-positional-argument overload and a strict <=64 tail window.
        failure_step="before_count"
        mark(failure_step)
        n=int(stock.get_count(hk.Query.DAY))
        if n<1:
            out["state"]="native_no_day_rows"
            raise RuntimeError("No native day record")
        if n>25000:
            out["state"]="native_day_count_exceeds_budget"
            raise RuntimeError("Unexpected native day count")
        mark("count_ready")
        failure_step="before_query"
        mark(failure_step)
        first=max(0,n-64)
        query=hk.Query(first,n,hk.Query.DAY)
        mark("query_ready")
        failure_step="before_get_kdata"
        mark(failure_step)
        out["native_get_kdata_called"]=True
        recs=stock.get_kdata(query)
        mark("kdata_returned")
        failure_step="kdata_returned"
        returned=len(recs)
        out["records_examined_per_stock"][symbol]=returned
        if returned!=n-first or not 1<=returned<=64:
            out["state"]="native_kdata_count_invalid"
            raise RuntimeError("Native count/window mismatch")
        matches=[r for r in recs if int(r.datetime.ymd)==20260930]
        if len(matches)==0:
            out["state"]="native_target_day_not_found"
            raise RuntimeError("Target day missing in bounded tail")
        if len(matches)>1:
            out["state"]="native_target_day_duplicate"
            raise RuntimeError("Duplicate target day")
        mark("target_found")
        r=matches[0]
        failure_step="before_hmac"
        mark(failure_step)
        # Reverse only the well-known native H5 driver numeric scales.
        # No user OHLCVA, decoded values or raw H5 integers leave the worker.
        raw=[202609300000,int(round(float(r.open)*1000)),
             int(round(float(r.high)*1000)),
             int(round(float(r.low)*1000)),
             int(round(float(r.close)*1000)),
             int(round(float(r.volume))),
             int(round(float(r.amount)*10))]
        msg="|".join([symbol,*map(str,raw)]).encode("ascii")
        out["hmac_by_stock"][symbol]=hmac.new(key,msg,hashlib.sha256).hexdigest()
    out["state"]="native_complete"
    mark("native_complete")
except BaseException:
    # Never print an arbitrary exception type/message/traceback: C++ logs may
    # include the private original H5 path or source values. SAFE reason codes
    # are hardcoded stage names, not user or native-exception strings.
    if out["state"]=="runtime_unavailable":
        out["state"]="failed_at_"+failure_step
finally:
    mark("finished")
    print(PREFIX+json.dumps(out,sort_keys=True),flush=True)
    os._exit(0)
'''


def run(h5_root,proof,output,python_exe,run_id="run001",timeout=60,
        runner=subprocess.run):
    if type(timeout) is not int or not 10<=timeout<=120:
        raise ValueError("Native timeout must be 10..120 seconds")
    if type(run_id) is not str or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{2,39}",run_id):
        raise ValueError("Invalid isolated run ID")
    dest=AUDIT._path(output,False)
    verify_previous(proof)
    interpreter=NATIVE.CHECK._explicit_python(python_exe)
    source=paths(h5_root)
    import h5py
    import numpy as np
    key=secrets.token_bytes(32)
    expected,before=raw_expected(source,key,h5py,np)
    if WORK.parent.is_symlink() or WORK.is_symlink():
        raise ValueError("Unsafe native work destination")
    WORK.mkdir(parents=True,exist_ok=True)
    stage=WORK/run_id
    if stage.exists() or stage.is_symlink():
        raise ValueError("Native run id already exists; use a new ID")
    stage.mkdir(exist_ok=False)
    phase=None
    work_phase=None
    parsed=None
    state="native_unavailable"
    try:
        env=NATIVE.CHECK._sandbox_env(stage,interpreter)
        env["ASTOCK_NATIVE_REAL_HMAC_SECRET"]=key.hex()
        try:
            proc=runner(
                [str(interpreter),"-I","-c",WORKER,
                 str(stage),str(source["SH600000"]),
                 str(source["SZ000001"])],
                cwd=stage,env=env,timeout=timeout,
                capture_output=True,text=False,check=False)
            phases=lines(proc.stdout,STAGE_MARKER)
            if phases:
                valid=[p.decode("ascii") for p in phases
                       if p in {a.encode("ascii") for a in PHASES}]
                phase=valid[-1] if valid else None
                work_phase=next((item for item in reversed(valid)
                                 if item!="finished"),None)
            parsed=decode_status(proc.stdout,proc.returncode)
            state=parsed["state"] if parsed else "native_invalid_or_crashed"
        except subprocess.TimeoutExpired as exc:
            phases=lines(exc.stdout,STAGE_MARKER)
            if phases:
                valid=[p.decode("ascii") for p in phases
                       if p in {a.encode("ascii") for a in PHASES}]
                phase=valid[-1] if valid else None
                work_phase=next((item for item in reversed(valid)
                                 if item!="finished"),None)
            state="native_timeout"
        except (ValueError,OSError,TypeError):
            state="native_spawn_error"
        if not unchanged(source,before):
            raise ValueError("Original H5 source changed during native probe")
        matched={symbol:(parsed is not None and
                         parsed["state"]=="native_complete" and
                         parsed["core311"] and parsed["registry_only_temp"]
                         and parsed["stock_manager_initialized"] and
                         parsed["native_get_kdata_called"] and
                         parsed["h5_file_read_only"] and
                         parsed["hmac_by_stock"][symbol]==expected[symbol])
                 for symbol in SYMBOLS}
        passed=(all(matched.values()) and phase=="finished")
        result={
            "format":FORMAT,
            "target_day":DAY,
            "native_hikyuu_expected_version":"2.8.1",
            "native_python_expected_minor":"3.11",
            "native_status":state,
            "native_final_phase":phase,
            "native_last_work_phase":work_phase,
            "original_raw_h5_stock_days_compared":2,
            "native_matching_stock_day_count":sum(matched.values()),
            "all_two_native_h5_real_daily_records_match":bool(passed),
            "native_get_kdata_called":bool(parsed and
                                           parsed["native_get_kdata_called"]),
            "native_source_original_h5_read":True,
            "isolated_registry_created_inside_module":True,
            "original_h5_stat_before_after_unchanged":True,
            "original_h5_full_content_sha256_checked":False,
            "original_parquet_or_market_sqlite_accessed":False,
            "source_h5_or_parquet_modified":False,
            "native_worker_stdout_stderr_not_saved":True,
            "hmac_key_or_digest_recorded_in_safe":False,
            "raw_market_ohlcva_or_timestamp_recorded_in_safe":False,
            "successful_native_h5_decode_is_not_vendor_unit_certificate":True,
            "native_h5_raw_record_decode_evidence_for_two_stock_days":bool(passed),
            "parquet_vendor_amount_physical_unit_certified":False,
            "parquet_vendor_volume_physical_unit_certified":False,
            "parquet_to_hikyuu_native_units_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
        }
        with dest.open("x",encoding="utf-8") as f:
            json.dump(result,f,ensure_ascii=False,indent=2)
            f.write("\n")
        return result
    finally:
        # Do not write/delete any user's market data. New scratch directory
        # only holds a fictional SQLite register and native module settings.
        key=b"\x00"*32


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--h5-root",type=Path,required=True)
    p.add_argument("--prior-two-source-safe",type=Path,required=True)
    p.add_argument("--python-exe",type=Path,required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--timeout",type=int,default=60)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--native-read-only-two-stock-day",required=True,action="store_true")
    a=p.parse_args(argv)
    try:
        safe=run(a.h5_root,a.prior_two_source_safe,a.out,a.python_exe,
                 run_id=a.run_id,timeout=a.timeout)
        print("Native real H5 safe evidence:",a.out)
        print("Status:",safe["native_status"])
        print("Both stock-day native values match:",
              safe["all_two_native_h5_real_daily_records_match"])
        print("Market files modified: NO")
        print("Licensed units / production H5 mapping certified: NO")
    except (ValueError,OSError,TypeError,ImportError,json.JSONDecodeError):
        p.error("Isolated native H5 read refused: invalid previous proof, source, or runtime")


if __name__=="__main__":
    main()
