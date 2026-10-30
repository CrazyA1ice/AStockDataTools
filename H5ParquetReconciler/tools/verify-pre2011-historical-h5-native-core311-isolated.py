#!/usr/bin/env python3
"""Bounded real 1992-95 Hikyuu native DAY decode, by qualified H5 row index.

Preflight verifies 21-year immutable private RAW SHA chain, previous 7-target
SAFE and private H5 index manifest digest, and all seven original H5 integer
rows against immutable private RAW. A separate CPython 3.11 / Hikyuu 2.8.1
core311 process reads at most ONE DAY KRecord at each of the seven exact
H5 indices via a wholly fictional isolated SQLite registry.

Only ephemeral keyed HMAC digests cross the process boundary. No raw H5
prices/amounts/volumes or market symbols/dates leave in SAFE, and no source,
production pointer, purchased Parquet or existing H5 file is written.
H5 native decoded values do not certify purchased vendor physical units.
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
WORK=MODULE/"work"/"h5_mirror"/"historical_native_isolated"
FORMAT="AStockDataTools seven verified original H5 historical DAY native core311 HMAC v1"
PREFIX=b"ASTOCK_HISTORICAL_NATIVE_HMAC:"
PHASE=b"ASTOCK_HISTORICAL_NATIVE_PHASE:"
PHASES=frozenset(("before_core","core_ready","registry_ready",
                  "stock_manager_ready","before_native","before_stock_lookup",
                  "before_count","count_ready","before_query","query_ready",
                  "before_get_kdata","kdata_returned","before_hmac",
                  "native_complete","finished"))
FAIL_STEPS=frozenset(("before_core","before_registry","before_stock_manager",
                     "before_stock_lookup","before_count","before_query",
                     "before_get_kdata","kdata_returned","before_hmac"))
SAFE_FAIL_STATES=frozenset((
    "native_stock_not_found","native_count_mismatch",
    "native_query_count_invalid","native_target_day_mismatch",
    "native_manifest_refused",
))
MAX_SOURCE_STOCK_DAYS=25000
EXPECTED_COUNT=7


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    x=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(x)
    return x


Q=load("historical_h5_qualified_source_seven_targets",
       "qualify-pre2011-historical-native-h5-targets-readonly.py")
G=load("historical_h5_real_native_core_previous_runtime",
       "verify-real-hikyuu-h5-native-day-isolated.py")
P=Q.P
SINGLE=Q.SINGLE


def safe_previous(path):
    """Verify exact SHA-bound SAFE, never accept an arbitrary manifest path."""
    p=Path(path)
    if (P.REPORTS.is_symlink() or p.is_symlink() or not p.is_file()
            or p.resolve().parent!=P.REPORTS.resolve()
            or not 0<p.stat().st_size<=200000):
        raise ValueError("Prior original H5 target qualification SAFE invalid")
    raw=p.read_bytes()
    d=json.loads(raw)
    if (type(d) is not dict or d.get("format")!=Q.FORMAT
            or d.get("status")!="historical_native_h5_target_qualification_only_no_driver_called"
            or d.get("sample_count")!=EXPECTED_COUNT
            or d.get("required_cohorts")!=[
                {"year":y,"market":m,"quarter":q,"candidate_factor":f}
                for y,m,q,f in Q.COHORTS]
            or d.get("private_raw_original_h5_integer_rows_identical") is not True
            or d.get("full21_private_raw_sha_chain_checked") is not True
            or d.get("original_h5_file_stat_unchanged") is not True
            or d.get("original_h5_full_content_sha256_rechecked") is not False
            or d.get("current_all_original_sources_requalified") is not False
            or d.get("original_h5_read_only") is not True
            or d.get("purchased_parquet_opened") is not False
            or d.get("hikyuu_native_driver_called") is not False
            or d.get("historical_native_units_or_securities_certified") is not False
            or d.get("production_or_private_active_pointer_modified") is not False
            or d.get("standardized_parquet_or_h5_mirror_created") is not False
            or d.get("raw_symbol_day_ohlcva_excluded_from_safe") is not True
            or not isinstance(d.get("private_selection_manifest_sha256"),str)
            or not re.fullmatch(r"[0-9a-f]{64}",d["private_selection_manifest_sha256"])):
        raise ValueError("Prior seven historical H5 source target SAFE is not qualified")
    raw_rel=d.get("private_selection_relative_path")
    if (type(raw_rel) is not str or not re.fullmatch(
            r"work/h5_mirror/historical_native_qualification/"
            r"native_targets_[a-f0-9]{12,32}/selected-original-h5-native-targets\.json",
            raw_rel)):
        raise ValueError("Unsafe or noncanonical private target manifest selector")
    target=MODULE/raw_rel
    if (any(n.is_symlink() for n in (
            MODULE/"work",MODULE/"work"/"h5_mirror",Q.WORK,
            target.parent,target))
            or not target.is_file()
            or target.resolve()!=target
            or target.resolve().parent!=Q.WORK.resolve()
               /target.parent.name
            or SINGLE.hash_file(target)!=d["private_selection_manifest_sha256"]):
        raise ValueError("Private historical H5 target manifest SHA or path changed")
    return d,target,hashlib.sha256(raw).hexdigest()


def bind_coordinates(full21_safe,qualification_safe,root):
    """No trust in private selectors until fresh integer-equality H5 recheck."""
    full,full_sha=P.source_safe(full21_safe)
    prior,manifest,prior_sha=safe_previous(qualification_safe)
    if prior["source_full21_safe_sha256"]!=full_sha:
        raise ValueError("Historical original RAW safe SHA not bound to target SAFE")
    raw=json.loads(manifest.read_text(encoding="utf-8"))
    if (type(raw) is not dict or raw.get("format")!=Q.PRIVATE_FORMAT
            or raw.get("source_full21_safe_sha256")!=full_sha
            or raw.get("sample_count")!=EXPECTED_COUNT
            or raw.get("source_original_h5_files_read_only") is not True
            or raw.get("physical_units_certified") is not False
            or raw.get("authorized_for_market_data_write") is not False
            or type(raw.get("sample_selections")) is not list
            or len(raw["sample_selections"])!=EXPECTED_COUNT):
        raise ValueError("Private historical original H5 coordinate record invalid")
    chosen=raw["sample_selections"]
    for cohort,row in zip(Q.COHORTS,chosen):
        y,market,quarter,factor=cohort
        if (type(row) is not dict
                or row.get("year")!=y or row.get("market")!=market
                or row.get("quarter")!=quarter
                or row.get("candidate_factor")!=factor
                or type(row.get("symbol")) is not str
                or not re.fullmatch(market+r"[0-9]{6}",row["symbol"])
                or not SINGLE.AUDIT.CORE.is_a_share_candidate(row["symbol"],y)
                or type(row.get("datetime")) is not int
                or SINGLE.AUDIT.date_key(row["datetime"]).year!=y
                or (SINGLE.AUDIT.date_key(row["datetime"]).month-1)//3+1!=quarter
                or type(row.get("source_native_stock_index")) is not int
                or type(row.get("source_stock_total_day_count")) is not int
                or not 0<=row["source_native_stock_index"]<
                    row["source_stock_total_day_count"]<=MAX_SOURCE_STOCK_DAYS):
            raise ValueError("Historical H5 native coordinate malformed")
    # Manifest file is not a proof of original raw values: source+RAW
    # are independently rechecked before ANY native child is spawned.
    entries=P.verified_private_files(full)
    lookup={year:(path,count,sha) for year,path,count,sha in entries}
    selected={}
    for year in sorted({c[0] for c in Q.COHORTS}):
        file,count,sha=lookup[year]
        before=(file.stat().st_size,file.stat().st_mtime_ns)
        selected.update(Q.pick_from_private(file,year,count))
        if ((file.stat().st_size,file.stat().st_mtime_ns)!=before
                or SINGLE.hash_file(file)!=sha):
            raise ValueError("Private historical H5 RAW changed during source recheck")
    files=Q.real_h5_files(root)
    verified=Q.real_h5_read_match(files,selected)
    expected=[]
    for cohort,row in zip(Q.COHORTS,chosen):
        if verified[cohort]!=row:
            raise ValueError("Private target selector differs from currently proven H5 source")
        current=selected[cohort]
        if any(type(current[name]) is not int or not 0<=current[name]<2**53
               for name in SINGLE.REQUIRED_NUMERIC):
            raise ValueError("Historical H5 RAW exceeds exact signed native numeric budget")
        expected.append(current)
    return chosen,expected,files,manifest,prior_sha,full_sha


def hmac_row(key,row):
    if type(key) is not bytes or len(key)!=32:
        raise ValueError("Invalid ephemeral original H5 comparison HMAC key")
    if type(row) is not dict or set(row)!=set(SINGLE.FIELDS):
        raise ValueError("Invalid original H5 source HMAC record")
    symbol=row["symbol"]
    if not re.fullmatch(r"(SH|SZ)[0-9]{6}",symbol):
        raise ValueError("Invalid original H5 HMAC symbol")
    for name in SINGLE.REQUIRED_NUMERIC:
        if type(row[name]) is not int or not 0<=row[name]<2**53:
            raise ValueError("Native H5 HMAC integer not losslessly representable")
    raw="|".join([symbol,*[str(row[k]) for k in SINGLE.REQUIRED_NUMERIC]])
    return hmac.new(key,raw.encode("ascii"),hashlib.sha256).hexdigest()


def encoded_lines(stdout,prefix):
    if type(stdout) not in (bytes,bytearray) or len(stdout)>60000:
        return []
    return [line[len(prefix):] for line in bytes(stdout).splitlines()
            if line.startswith(prefix)]


def decode_worker(stdout,return_code):
    if return_code!=0:
        return None
    lines=encoded_lines(stdout,PREFIX)
    if len(lines)!=1 or len(lines[0])>1400:
        return None
    try:
        parsed=json.loads(lines[0].decode("ascii"))
    except (UnicodeError,ValueError):
        return None
    if (type(parsed) is not dict
            or set(parsed)!={"state","core311","registry_only_temp",
                              "stock_manager_initialized","native_get_kdata_called",
                              "h5_files_no_write_requested","records_examined",
                              "digest_by_target"}
            or parsed["state"] not in ({"native_complete","runtime_unavailable"}
              | SAFE_FAIL_STATES | {"failed_at_"+step for step in FAIL_STEPS})
            or any(type(parsed[name]) is not bool for name in (
                "core311","registry_only_temp","stock_manager_initialized",
                "native_get_kdata_called","h5_files_no_write_requested"))
            or type(parsed["records_examined"]) is not int
            or not 0<=parsed["records_examined"]<=EXPECTED_COUNT
            or type(parsed["digest_by_target"]) is not list
            or len(parsed["digest_by_target"])!=EXPECTED_COUNT
            or any(type(v) is not str
                   or (v!="" and not re.fullmatch(r"[0-9a-f]{64}",v))
                   for v in parsed["digest_by_target"])):
        return None
    return parsed


WORKER=r'''
import hashlib,hmac,importlib,importlib.metadata,importlib.util,json,os,sqlite3,sys,types
from pathlib import Path
PREFIX="ASTOCK_HISTORICAL_NATIVE_HMAC:"
PHASE="ASTOCK_HISTORICAL_NATIVE_PHASE:"
out={"state":"runtime_unavailable","core311":False,"registry_only_temp":False,
     "stock_manager_initialized":False,"native_get_kdata_called":False,
     "h5_files_no_write_requested":True,"records_examined":0,
     "digest_by_target":[""]*7}
def mark(p): print(PHASE+p,flush=True)
mark("before_core")
failure="before_core"
try:
    stage=Path(sys.argv[1]).resolve()
    manifest=Path(sys.argv[2]).resolve()
    sh=Path(sys.argv[3]).resolve()
    sz=Path(sys.argv[4]).resolve()
    if (stage!=Path.cwd().resolve() or stage.parent.name!="historical_native_isolated"
            or not manifest.is_file() or manifest.is_symlink()
            or manifest.name!="selected-original-h5-native-targets.json"
            or manifest.parent.parent.name!="historical_native_qualification"
            or sh.name!="sh_day.h5" or sz.name!="sz_day.h5"
            or not sh.is_file() or not sz.is_file()
            or sh.is_symlink() or sz.is_symlink()):
        out["state"]="native_manifest_refused"
        raise RuntimeError("invalid bounded historical native paths")
    sha=os.environ.pop("ASTOCK_HISTORICAL_H5_MANIFEST_SHA")
    if hashlib.sha256(manifest.read_bytes()).hexdigest()!=sha:
        out["state"]="native_manifest_refused"
        raise RuntimeError("historical manifest source digest changed")
    selections=json.loads(manifest.read_text(encoding="utf-8"))["sample_selections"]
    if type(selections) is not list or len(selections)!=7:
        out["state"]="native_manifest_refused"
        raise RuntimeError("unexpected selected raw source count")
    for r in selections:
        if (type(r) is not dict
                or r.get("market") not in ("SH","SZ")
                or type(r.get("symbol")) is not str
                or not r["symbol"].startswith(r["market"])
                or len(r["symbol"])!=8 or not r["symbol"][2:].isdigit()
                or type(r.get("datetime")) is not int
                or type(r.get("source_native_stock_index")) is not int
                or type(r.get("source_stock_total_day_count")) is not int
                or not 0<=r["source_native_stock_index"]<
                       r["source_stock_total_day_count"]<=25000):
            out["state"]="native_manifest_refused"
            raise RuntimeError("invalid historical native stock selector")
    key=bytes.fromhex(os.environ.pop("ASTOCK_HISTORICAL_NATIVE_HMAC_SECRET"))
    if len(key)!=32 or sys.version_info[:2]!=(3,11):
        raise RuntimeError("unexpected isolated native interpreter")
    if importlib.metadata.version("hikyuu")!="2.8.1":
        raise RuntimeError("Native Hikyuu expected 2.8.1")
    spec=importlib.util.find_spec("hikyuu")
    dist=importlib.metadata.distribution("hikyuu")
    installed=Path(dist.locate_file("hikyuu")).resolve()
    found=Path(next(iter(spec.submodule_search_locations))).resolve()
    if found!=installed or not (found/"core.py").is_file():
        raise RuntimeError("Unverified installed native Hikyuu package")
    fake=types.ModuleType("hikyuu")
    fake.__path__=[str(found)]
    fake.__package__="hikyuu"
    fake.__spec__=spec
    sys.modules["hikyuu"]=fake
    cpp=found/"cpp"
    if not cpp.is_dir() or cpp.is_symlink():
        raise RuntimeError("Unverified native Hikyuu compiled package")
    if sys.platform=="win32":
        holder=os.add_dll_directory(str(cpp))
        os.environ["PATH"]=str(cpp)+os.pathsep+os.environ.get("PATH","")
    hk=importlib.import_module("hikyuu.core")
    native=sys.modules.get("hikyuu.cpp.core311")
    loc=Path(getattr(native,"__file__","")).resolve()
    if loc.suffix.lower() not in (".pyd",".so") or not loc.is_relative_to(cpp.resolve()):
        raise RuntimeError("Native core311 module absent")
    out["core311"]=True
    mark("core_ready")
    failure="before_registry"
    db=stage/"fictional_historical_registry.sqlite3"
    if db.exists():
        raise RuntimeError("Unexpected existing isolated registry")
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
          [(1,"SH","Isolated SH","native history sample","000001",20261031,0,0,0,0),
           (2,"SZ","Isolated SZ","native history sample","399001",20261031,0,0,0,0)])
        conn.execute("INSERT INTO StockTypeInfo VALUES (1,1,2,0.01,0.01,100,1000000,'fictional')")
        stocks=sorted({r["symbol"] for r in selections})
        conn.executemany("INSERT INTO Stock VALUES (?,?,?,?,?,?,?,?)",
          [(i+1,1 if s.startswith("SH") else 2,s[2:],"Fictional historical",1,1,
            19900101,20991231) for i,s in enumerate(stocks)])
        conn.commit()
    out["registry_only_temp"]=True
    mark("registry_ready")
    failure="before_stock_manager"
    def p(**kw):
        t=hk.Parameter()
        for k,v in kw.items():t[k]=v
        return t
    sm=hk.StockManager.instance()
    plugin=stage/"empty_plugins"
    plugin.mkdir(exist_ok=False)
    sm.set_plugin_path(str(plugin))
    sm.init(p(type="sqlite3",db=str(db)),p(type="sqlite3",db=str(db)),
            p(type="hdf5",sh_day=str(sh),sz_day=str(sz)),
            p(day=False,week=False,month=False,min=False,min5=False),
            p(tmpdir=str(stage),datadir=str(stage),
              load_history_finance=False,lazy_preload=False,
              use_shm_server=False,load_stock_weight=False))
    sm.wait_data_ready()
    out["stock_manager_initialized"]=True
    mark("stock_manager_ready")
    mark("before_native")
    for i,r in enumerate(selections):
        failure="before_stock_lookup"
        mark("before_stock_lookup")
        stock=sm.get_stock(r["symbol"])
        if stock.is_null():
            out["state"]="native_stock_not_found"
            raise RuntimeError("Historical H5 native stock missing")
        failure="before_count"
        mark("before_count")
        n=int(stock.get_count(hk.Query.DAY))
        if n!=r["source_stock_total_day_count"]:
            out["state"]="native_count_mismatch"
            raise RuntimeError("Historical H5 count not identical to original raw source")
        mark("count_ready")
        index=r["source_native_stock_index"]
        failure="before_query"
        mark("before_query")
        query=hk.Query(index,index+1,hk.Query.DAY)
        mark("query_ready")
        failure="before_get_kdata"
        mark("before_get_kdata")
        out["native_get_kdata_called"]=True
        records=stock.get_kdata(query)
        mark("kdata_returned")
        failure="kdata_returned"
        if len(records)!=1:
            out["state"]="native_query_count_invalid"
            raise RuntimeError("Expected precisely one historical H5 DAY KRecord")
        value=records[0]
        if int(value.datetime.ymd)!=r["datetime"]//10000:
            out["state"]="native_target_day_mismatch"
            raise RuntimeError("Historical native date differs from original H5 integer key")
        failure="before_hmac"
        mark("before_hmac")
        raw=[r["datetime"],
             int(round(float(value.open)*1000)),
             int(round(float(value.high)*1000)),
             int(round(float(value.low)*1000)),
             int(round(float(value.close)*1000)),
             int(round(float(value.volume))),
             int(round(float(value.amount)*10))]
        msg="|".join([r["symbol"],*map(str,raw)]).encode("ascii")
        out["digest_by_target"][i]=hmac.new(key,msg,hashlib.sha256).hexdigest()
        out["records_examined"]+=1
    out["state"]="native_complete"
    mark("native_complete")
except BaseException:
    # Never echo exceptions, stack traces, original source paths or values.
    if out["state"]=="runtime_unavailable":
        out["state"]="failed_at_"+failure
finally:
    mark("finished")
    print(PREFIX+json.dumps(out,sort_keys=True),flush=True)
    os._exit(0)
'''


def phase_from_stdout(stdout):
    valid=[]
    for line in encoded_lines(stdout,PHASE):
        if line in {p.encode("ascii") for p in PHASES}:
            valid.append(line.decode("ascii"))
    return (valid[-1] if valid else None,
            next((x for x in reversed(valid) if x!="finished"),None))


def run(root,full21_safe,qualification_safe,python_exe,run_id,out,timeout=60,
        runner=subprocess.run):
    if type(timeout) is not int or not 10<=timeout<=120:
        raise ValueError("Native Hikyuu bounded timeout must be 10..120s")
    if type(run_id) is not str or not re.fullmatch(r"[a-f0-9]{12,32}",run_id):
        raise ValueError("Historical native run id invalid")
    dest=P.target_safe(out)
    interpreter=G.NATIVE.CHECK._explicit_python(python_exe)
    coordinates,source_rows,files,manifest,prior_sha,full_sha=bind_coordinates(
        full21_safe,qualification_safe,root)
    before={market:SINGLE.AUDIT.state(path) for market,path in files.items()}
    manifest_sha=SINGLE.hash_file(manifest)
    key=secrets.token_bytes(32)
    expected=[hmac_row(key,row) for row in source_rows]
    if any(path.is_symlink() for path in (
            MODULE/"work",MODULE/"work"/"h5_mirror",WORK)):
        raise ValueError("Historical isolated native work hierarchy linked")
    WORK.mkdir(parents=True,exist_ok=True)
    stage=WORK/("run_"+run_id)
    if stage.exists() or stage.is_symlink():
        raise ValueError("Historical native run id already exists")
    stage.mkdir(exist_ok=False)
    state="native_invalid_or_crashed"
    final_phase=None
    last_work_phase=None
    parsed=None
    try:
        env=G.NATIVE.CHECK._sandbox_env(stage,interpreter)
        env["ASTOCK_HISTORICAL_NATIVE_HMAC_SECRET"]=key.hex()
        env["ASTOCK_HISTORICAL_H5_MANIFEST_SHA"]=manifest_sha
        try:
            proc=runner([
                str(interpreter),"-I","-c",WORKER,
                str(stage),str(manifest),str(files["SH"]),str(files["SZ"])
            ],cwd=stage,env=env,timeout=timeout,
                capture_output=True,text=False,check=False)
            final_phase,last_work_phase=phase_from_stdout(proc.stdout)
            parsed=decode_worker(proc.stdout,proc.returncode)
            state=parsed["state"] if parsed else "native_invalid_or_crashed"
        except subprocess.TimeoutExpired as exc:
            final_phase,last_work_phase=phase_from_stdout(exc.stdout)
            state="native_timeout"
        except (ValueError,TypeError,OSError):
            state="native_spawn_error"
        if SINGLE.hash_file(manifest)!=manifest_sha:
            raise ValueError("Historical private H5 selector modified during native test")
        if any(SINGLE.AUDIT.state(path)!=before[market]
               for market,path in files.items()):
            raise ValueError("Original H5 source file mutated during native HMAC read")
        matched=[
            bool(parsed and parsed["state"]=="native_complete"
                 and parsed["core311"]
                 and parsed["registry_only_temp"]
                 and parsed["stock_manager_initialized"]
                 and parsed["native_get_kdata_called"]
                 and parsed["h5_files_no_write_requested"]
                 and parsed["records_examined"]==EXPECTED_COUNT
                 and parsed["digest_by_target"][i]==expected[i])
            for i in range(EXPECTED_COUNT)
        ]
        done=(all(matched) and state=="native_complete"
              and final_phase=="finished")
        result={
            "format":FORMAT,
            "status":"native_historical_seven_h5_source_hmac_checked_not_vendor_units",
            "previous_historical_qualification_safe_sha256":prior_sha,
            "previous_full21_original_h5_snapshot_safe_sha256":full_sha,
            "private_selection_manifest_sha256":manifest_sha,
            "native_hikyuu_expected_version":"2.8.1",
            "native_python_expected_minor":"3.11",
            "native_status":state,
            "native_final_phase":final_phase,
            "native_last_work_phase":last_work_phase,
            "seven_historical_original_h5_rows_qualified":EXPECTED_COUNT,
            "native_matching_h5_historical_stock_days":sum(matched),
            "all_seven_native_h5_historical_records_match":done,
            "native_get_kdata_called":bool(parsed and parsed[
                "native_get_kdata_called"]),
            "native_query_expected_day_rows_per_target":1,
            "isolated_fictional_registry_only":bool(parsed and parsed["registry_only_temp"]),
            "original_h5_source_stat_unchanged":True,
            "original_h5_full_file_sha256_rechecked":False,
            "purchased_parquet_or_production_market_sqlite_accessed":False,
            "source_h5_or_purchased_parquet_modified":False,
            "private_raw_or_target_manifest_modified":False,
            "production_or_private_active_pointer_modified":False,
            "hmac_key_or_digests_saved_in_safe":False,
            "actual_symbols_dates_and_market_ohlcva_saved_in_safe":False,
            "historical_vendor_physical_units_or_adjustments_certified":False,
            "historical_security_master_certified":False,
            "historical_normalized_parquet_or_h5_mirror_created":False,
            "ready_for_production_data_integration":False,
        }
        with dest.open("x",encoding="utf-8") as handle:
            json.dump(result,handle,ensure_ascii=False,sort_keys=True,indent=2)
            handle.write("\n")
        return result
    finally:
        # Only the key in memory is scrubbed. Never delete unowned/source data.
        key=b"\x00"*32


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--full21-safe",type=Path,required=True)
    p.add_argument("--historical-qualification-safe",type=Path,required=True)
    p.add_argument("--python-exe",type=Path,required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--timeout",type=int,default=60)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--isolated-historical-native-seven",required=True,
                   action="store_true")
    args=p.parse_args(argv)
    try:
        report=run(args.root,args.full21_safe,args.historical_qualification_safe,
                   args.python_exe,args.run_id,args.out,timeout=args.timeout)
        print("Historical Hikyuu 2.8.1 native HMAC SAFE:",args.out)
        print("Native status:",report["native_status"])
        print("All seven qualified original H5 rows match native:",
              report["all_seven_native_h5_historical_records_match"])
        print("Original market source writes: NO; physical units certified: NO")
    except (ValueError,KeyError,TypeError,OSError,OverflowError,ImportError,
            ModuleNotFoundError,json.JSONDecodeError):
        p.error("Isolated historical H5 native qualification/read refused; no source write")


if __name__=="__main__":
    main()
