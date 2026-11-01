#!/usr/bin/env python3
"""Actually read an ISOLATED, REAL private Parquet-to-Hikyuu DAY canary via
the installed Hikyuu 2.8.1 core311 C++ HDF5 KDataDriver.

Does NOT open D:/stock, real market database, default Hikyuu config or
original purchased files. All comparison records stay in subprocess memory.
Reports only exact counts and pass/fail, never any licensed OHLCVA.

This reuses the previously tested core311-only sandbox worker + its isolated
fictional registry. Hikyuu native amount units = raw amount * 0.1 (Wan Yuan)
and native volume units = raw count (lots); Parquet candidate amount = raw
amount * 1000 (Yuan), volume = raw count * 100 (shares). These are *unit*
relationships, NOT bitwise numeric equality between differently scaled APIs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
CANARIES=MODULE/"work"/"h5_mirror"/"canaries"
FORMAT="AStockDataTools isolated real private daily H5 Hikyuu core311 native decode proof v1"
ALLOWED_ID=re.compile(r"[0-9a-f]{12}\Z")


def load(label,name):
    spec=importlib.util.spec_from_file_location(label,HERE/name)
    x=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(x)
    return x


SOURCE=load("hikyuu_private_day_real_writer","write-private-parquet-day-to-hikyuu-h5-canary.py")
NATIVE=load("hikyuu_sandbox_native_existing_worker","read-hikyuu-281-synthetic-h5-native-isolated.py")
CHECK=NATIVE.CHECK


def make_worker():
    """Reuse the real C++ library load and isolated stock.db setup unchanged."""
    original=NATIVE.WORKER
    start=original.index('    root=Path(sys.argv[1]).resolve()')
    end=original.index('    # Also require no preexisting registry:',start)
    new_root='''    import re
    root=Path(sys.argv[1]).resolve()
    sh=Path(sys.argv[2]).resolve()
    sz=Path(sys.argv[3]).resolve()
    if (root!=Path.cwd().resolve() or root.parent.name!="_native_h5_281"
            or root.parent.parent!=sh.parent or sh!=sz
            or not re.fullmatch(r"day_canary_[0-9a-f]{12}\\.h5",sh.name)
            or not sh.is_file() or sh.is_symlink()):
        raise RuntimeError("private-isolated-h5-source-invariant-failed")
'''
    worker=original[:start]+new_root+original[end:]
    # Widen only the *fictional* SH stock registry interval. No real stock.db.
    old='(1,1,"600000","Synthetic SH",1,1,20260930,20261014)'
    if worker.count(old)!=1:
        raise RuntimeError("Audited synthetic registry anchor changed")
    worker=worker.replace(old,'(1,1,"600000","Isolated SH",1,1,20110101,20271231)')
    a=worker.index('    days=[20260930,20261008,20261013]')
    b=worker.index('except BaseException as ex:',a)
    new_read='''    # The only market-shaped file is the SHA-pinned PRIVATE generated H5.
    # Independently read its raw integers and compare actual KRecords decoded
    # by the installed native HDF5 driver. Never log any values or dates.
    import h5py
    with h5py.File(sh,"r") as f:
        ds=f["data"]["SH600000"]
        rows=ds[:]
    if not 1<=len(rows)<=31:
        out["state"]="invalid_private_h5_sample_count"
        raise RuntimeError("out-of-budget")
    stock=sm.get_stock("SH600000")
    if stock.is_null():
        out["state"]="fictional_stock_registration_failed"
        raise RuntimeError("isolated-stock-missing")
    out["native_h5_kdata_method_called"]=True
    records=stock.get_kdata(hk.Query(0,len(rows),hk.Query.DAY))
    if len(records)!=len(rows):
        out["state"]="native_h5_row_count_mismatch"
        raise RuntimeError("KData row count mismatch")
    for source,rec in zip(rows,records):
        expected=(
            float(source["openPrice"])*0.001,
            float(source["highPrice"])*0.001,
            float(source["lowPrice"])*0.001,
            float(source["closePrice"])*0.001,
            float(source["transAmount"])*0.1,
            float(source["transCount"]))
        actual=(rec.open,rec.high,rec.low,rec.close,
                rec.amount,rec.volume)
        if (int(rec.datetime.ymd)!=int(source["datetime"])//10000
                or any(abs(float(got)-want)>max(1e-8,abs(want)*1e-12)
                       for got,want in zip(actual,expected))):
            out["state"]="native_private_h5_decode_mismatch"
            raise RuntimeError("native value mismatch")
        out["per_symbol_matching_rows"]["SH600000"]+=1
    out["native_h5_values_matched"]=True
    print(PHASE+"native_read_complete",flush=True)
    out["state"]="native_private_h5_all_rows_matched"
'''
    return worker[:a]+new_read+worker[b:]


WORKER=make_worker()


def hash_file(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def audited_source(prior):
    p=Path(prior)
    if (p.is_symlink() or p.suffix!=".json"
            or p.resolve().parent!=REPORTS.resolve()
            or not p.is_file() or p.stat().st_size>200000):
        raise ValueError("Real private H5 canary requires module reports SAFE")
    doc=json.loads(p.read_bytes())
    if (doc.get("format")!=SOURCE.FORMAT
            or doc.get("status")!=
              "isolated_native_layout_day_h5_written_and_h5py_readback_verified_not_activated"
            or doc.get("h5py_compound_integer_full_row_readback_verified") is not True
            or doc.get("pytables_table_class_marker_and_40byte_layout_verified") is not True
            or doc.get("hikyuu_cpp_native_reader_verified") is not False
            or doc.get("written_h5_integer_rows")!=doc.get("source_day_rows")
            or type(doc.get("written_h5_integer_rows")) is not int
            or not 1<=doc["written_h5_integer_rows"]<=31
            or any(doc.get(k) is not False for k in (
                "ready_for_full_market_mirror","ready_for_production_query",
                "ready_for_h5_mirror","ready_for_automatic_market_merge",
                "original_market_files_written","original_hikyuu_h5_rewritten",
                "purchased_parquet_source_rewritten"))):
        raise ValueError("Only previously verified REAL private TABLE H5 accepted")
    rel=doc.get("private_h5_relative_file")
    if (type(rel) is not str
            or not re.fullmatch(r"work/h5_mirror/canaries/day_canary_[0-9a-f]{12}\.h5",rel)):
        raise ValueError("Untrusted private H5 canary relative path")
    h5=MODULE/rel
    if (CANARIES.is_symlink() or h5.is_symlink()
            or not h5.is_file() or h5.resolve().parent!=CANARIES.resolve()
            or hash_file(h5)!=doc.get("private_h5_file_sha256")):
        raise ValueError("Real private H5 SHA changed since write/readback")
    return doc,h5


def verify(prior,python_exe,out,run_id,timeout=75,runner=subprocess.run):
    if type(run_id) is not str or ALLOWED_ID.fullmatch(run_id) is None:
        raise ValueError("New 12-hex isolated native verifier run ID required")
    if type(timeout) is not int or not 10<=timeout<=180:
        raise ValueError("Native subprocess timeout outside 10..180 seconds")
    dest=Path(out)
    if (REPORTS.is_symlink() or dest.is_symlink() or dest.exists()
            or dest.suffix!=".json"
            or dest.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Require a NEW module reports/ SAFE output")
    doc,h5=audited_source(prior)
    interpreter=CHECK._explicit_python(python_exe)
    parent=CANARIES/"_native_h5_281"
    stage=parent/run_id
    if (parent.is_symlink() or stage.is_symlink() or stage.exists()
            or not CANARIES.is_dir()):
        raise ValueError("Unsafe or existing isolated native H5 run directory")
    parent.mkdir(exist_ok=True)
    stage.mkdir(exist_ok=False)
    state="native_subprocess_unavailable"
    matched=0
    phase=None
    try:
        p=runner(
            [str(interpreter),"-I","-c",WORKER,str(stage),str(h5),str(h5)],
            cwd=stage,capture_output=True,text=False,
            timeout=timeout,check=False,env=CHECK._sandbox_env(stage,interpreter))
        phase=NATIVE.last_native_phase(p.stdout)
        if p.returncode==0:
            items=NATIVE._marker_payloads(p.stdout,NATIVE.MARKER)
            if len(items)==1:
                try:
                    raw=json.loads(items[0])
                except (ValueError,UnicodeError):
                    raw=None
                if (type(raw) is dict
                        and set(raw)=={
                            "state","core311_loaded",
                            "full_hikyuu_package_imported",
                            "hikyuu_281_version_confirmed",
                            "synthetic_registry_initialized",
                            "stock_manager_initialized",
                            "native_h5_kdata_method_called",
                            "native_h5_values_matched",
                            "per_symbol_matching_rows",
                            "source_market_files_accessed",
                            "production_query_switched"}
                        and raw.get("full_hikyuu_package_imported") is False
                        and raw.get("source_market_files_accessed") is False
                        and raw.get("production_query_switched") is False
                        and type(raw.get("per_symbol_matching_rows")) is dict
                        and set(raw["per_symbol_matching_rows"])=={
                            "SH600000","SZ000001"}
                        and type(raw["per_symbol_matching_rows"]["SH600000"]) is int
                        and raw["per_symbol_matching_rows"]["SZ000001"]==0
                        and raw["per_symbol_matching_rows"]["SH600000"]<=31):
                    state=raw["state"]
                    matched=raw["per_symbol_matching_rows"]["SH600000"]
                    good=(all(raw[k] is True for k in (
                        "core311_loaded","hikyuu_281_version_confirmed",
                        "synthetic_registry_initialized","stock_manager_initialized",
                        "native_h5_kdata_method_called","native_h5_values_matched"))
                        and state=="native_private_h5_all_rows_matched"
                        and matched==doc["written_h5_integer_rows"]
                        and phase=="finished")
                    if not good:
                        raise ValueError("Native private H5 KRecords not verified")
        if state!="native_private_h5_all_rows_matched":
            safe_state=(state if re.fullmatch(r"[a-z0-9_]{1,80}",state)
                        else "invalid_native_worker_state")
            safe_phase=(phase if phase in NATIVE.PHASES else "none")
            raise ValueError("Native core311 status="+safe_state+" phase="+safe_phase)
    except subprocess.TimeoutExpired:
        raise ValueError("Native isolated core311 read timed out") from None
    finally:
        if hash_file(h5)!=doc["private_h5_file_sha256"]:
            raise ValueError("Private H5 modified during isolated native read")
    result={
        "format":FORMAT,
        "status":"native_hikyuu_281_private_day_all_krecords_match",
        "source_real_private_h5_sha256":doc["private_h5_file_sha256"],
        "source_16year_unified_parquet_version_sha256":
            doc["source_private_all16_version_sha256"],
        "native_core311_version_expected":"2.8.1",
        "native_krecord_rows_matched":matched,
        "native_h5_get_kdata_called":True,
        "last_native_phase":phase,
        "private_h5_sha_rechecked_before_and_after":True,
        "hikyuu_driver_amount_reconstitution_to_purchased_units":10000,
        "hikyuu_driver_volume_reconstitution_to_purchased_units":100,
        "price_ohlc_driver_decode_all_rows_equal_to_integer_storage":True,
        "native_amount_vs_purchased_float64_exactly_equal":False,
        "native_krecord_amount_values_follow_fixedpoint_decode":True,
        "native_krecord_volume_values_follow_fixedpoint_decode":True,
        "no_raw_ohlcva_stock_codes_or_exact_dates_exported":True,
        "original_market_files_opened_or_modified":False,
        "original_purchased_parquet_modified":False,
        "private_or_production_active_pointer_modified":False,
        "full_market_h5_mirror_completed":False,
        "ready_for_production_query":False,
    }
    with dest.open("x",encoding="utf-8",newline="\n") as f:
        json.dump(result,f,sort_keys=True,indent=2)
        f.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--real-canary-safe",type=Path,required=True)
    p.add_argument("--python-exe",type=Path,required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--timeout",type=int,default=75)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--native-private-read-only",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=verify(a.real_canary_safe,a.python_exe,a.out,a.run_id,a.timeout)
        print("PASS: native Hikyuu 2.8.1 isolated real private DAY KRecords")
        print("Native matched rows:",result["native_krecord_rows_matched"])
        print("Full-market native mirror: NOT YET; original market sources untouched")
        print("SAFE:",a.out)
    except (ValueError,TypeError,OSError,ImportError) as exc:
        message=str(exc)
        if message.startswith("Native core311 status="):
            p.error(message+"; original files unchanged")
        p.error("Native private read refused ["+type(exc).__name__+
                "]: failed isolated core311/real H5 verification")


if __name__=="__main__":
    main()
