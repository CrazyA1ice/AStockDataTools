#!/usr/bin/env python3
"""Re-read the TWO NEW, FICTIONAL Decimal-bridge H5 files with Hikyuu 2.8.1.

The previous gate proved synthetic Parquet->H5 integer equality. This second
stage runs the actual core311 C++ KData driver on those generated H5 files.
Never accepts arbitrary H5 paths, production market data, or licensed Parquet.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
from pathlib import Path

TOOL_DIR=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "hikyuu_isolated_native_reader",TOOL_DIR/"read-hikyuu-281-synthetic-h5-native-isolated.py")
NATIVE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)
SPEC2=importlib.util.spec_from_file_location(
    "hikyuu_synthetic_decimal_bridge",TOOL_DIR/"synthetic-parquet-to-hikyuu-h5-numeric-gate.py")
BRIDGE=importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(BRIDGE)
CHECK=NATIVE.CHECK
FORMAT="AStockDataTools core311 native re-read of synthetic Decimal-generated H5 v1"
STOCKS={"SH600000":"sh_day.h5","SZ000001":"sz_day.h5"}


def _guard_synthetic_dir(folder):
    path=Path(folder)
    if (NATIVE.WORK.is_symlink() or NATIVE.MIRRORS.is_symlink()
            or path.is_symlink() or not path.is_dir()
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,79}",path.name)
            or path.resolve().parent!=NATIVE.MIRRORS.resolve()):
        raise ValueError("Only an existing direct synthetic H5 mirror child is allowed")
    return path.resolve()


def verify_decimal_bridge(proof,canary,synthetic_dir):
    """Require exact original SHA provenance, fictional records and file SHA."""
    proof_path=CHECK._module_input(proof)
    doc=json.loads(proof_path.read_text(encoding="utf-8"))
    required_true=(
        "verified_previous_native_h5_six_rows","synthetic_parquet_generation_only",
        "prices_in_hikyuu_driver_units_only",
        "amounts_in_hikyuu_driver_units_only",
        "volumes_in_hikyuu_driver_units_only","exact_decimal_no_rounding",
        "all_six_synthetic_records_exactly_matched_native_baseline",
        "no_raw_ohlcva_in_safe_summary")
    required_false=(
        "new_h5_files_tested_by_native_driver",
        "actual_purchased_parquet_units_verified",
        "licensed_parquet_to_h5_mapping_certified",
        "ready_for_full_market_mirror","licensed_market_data_read",
        "original_market_files_modified","production_query_route_modified")
    if (type(doc) is not dict or doc.get("format")!=BRIDGE.FORMAT
            or doc.get("canary_safe_summary_sha256")!=canary["report_sha256"]
            or doc.get("native_h5_unsigned_price_width_bits")!=32
            or doc.get("native_h5_unsigned_amount_volume_width_bits")!=64
            or doc.get("per_symbol_records")!={"SH600000":3,"SZ000001":3}
            or any(doc.get(key) is not True for key in required_true)
            or any(doc.get(key) is not False for key in required_false)):
        raise ValueError("Matching successful fictional Decimal bridge proof required")
    entries=doc.get("generated_synthetic_files")
    if type(entries) is not list or len(entries)!=2:
        raise ValueError("Decimal bridge must have precisely two fictional sources")
    by_symbol={}
    for item in entries:
        if (type(item) is not dict
                or set(item)!={"kind","symbol","parquet_sha256","h5_sha256",
                               "verified_integer_records"}
                or item["kind"]!="fictional_parquet_and_h5"
                or item["symbol"] not in STOCKS
                or item["symbol"] in by_symbol
                or type(item["verified_integer_records"]) is not int
                or item["verified_integer_records"]!=3
                or any(type(item.get(key)) is not str
                       or not re.fullmatch(r"[0-9a-f]{64}",item[key])
                       for key in ("parquet_sha256","h5_sha256"))):
            raise ValueError("Invalid synthetic file manifest")
        by_symbol[item["symbol"]]=item
    if set(by_symbol)!=set(STOCKS):
        raise ValueError("Synthetic symbol pair mismatch")
    for symbol,filename in STOCKS.items():
        h5=synthetic_dir/filename
        pq=synthetic_dir/(symbol.lower()+"_synthetic.parquet")
        for path,hashfield in ((h5,"h5_sha256"),(pq,"parquet_sha256")):
            if (path.is_symlink() or not path.is_file()
                    or path.stat().st_size>20*1024*1024
                    or BRIDGE.sha256(path)!=by_symbol[symbol][hashfield]):
                raise ValueError("Synthetic Decimal bridge file hash changed")
    return by_symbol


def native_recheck(canary_report,decimal_report,core_proof,synthetic_dir,
                   python_exe,output,run_id="run001",runner=subprocess.run,
                   timeout=45):
    """Run only a fresh fictional native reader, with no real source paths."""
    if type(timeout) is not int or not (10<=timeout<=120):
        raise ValueError("Native read timeout must be 10..120 seconds")
    if type(run_id) is not str or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{2,39}",run_id):
        raise ValueError("Use a NEW safe --run-id")
    interpreter=CHECK._explicit_python(python_exe)
    canary=CHECK.verify_canary(canary_report)
    NATIVE.verify_core_proof(core_proof,canary)
    path=_guard_synthetic_dir(synthetic_dir)
    verify_decimal_bridge(decimal_report,canary,path)
    dest=CHECK._module_output(output)
    root=path/"_native_h5_281"
    stage=root/run_id
    if (root.is_symlink() or (root.exists() and not root.is_dir())
            or stage.exists() or stage.is_symlink()):
        raise ValueError("Native reread scratch run already exists; use NEW run ID")
    root.mkdir(exist_ok=True)
    stage.mkdir(exist_ok=False)
    status="native_subprocess_unavailable"
    phase=None
    result=None
    try:
        try:
            # Reuse the 6-row C++ worker whose stock/registry/H5 logic has
            # already passed the Windows synthetic native smoke test. Its
            # folder invariant is satisfied ONLY by stage under source/_native_h5_281.
            proc=runner([str(interpreter),"-I","-c",NATIVE.WORKER,
                         str(stage),str(path/"sh_day.h5"),str(path/"sz_day.h5")],
                        cwd=stage,capture_output=True,text=False,
                        check=False,timeout=timeout,
                        env=CHECK._sandbox_env(stage,interpreter))
            phase=NATIVE.last_native_phase(proc.stdout)
            result=NATIVE.parse_native(proc.stdout,proc.returncode)
            status=result["state"] if result else "native_subprocess_invalid_or_crashed"
        except subprocess.TimeoutExpired as exc:
            phase=NATIVE.last_native_phase(exc.stdout)
            status="native_subprocess_timeout"
        except (OSError,ValueError,TypeError):
            status="native_subprocess_spawn_failed"
        # Crucial: re-verify both NEW generated files *and* the original
        # synthetic native-read canary before certifying results.
        verify_decimal_bridge(decimal_report,canary,path)
        updated=CHECK.verify_canary(canary_report)
        if updated["source_file_details"]!=canary["source_file_details"]:
            raise ValueError("Original synthetic canary changed during native reread")
        matched=(result is not None and phase=="finished"
                 and result["state"]=="native_h5_six_synthetic_rows_matched")
        safe={
            "format":FORMAT,
            "original_canary_safe_summary_sha256":canary["report_sha256"],
            "synthetic_decimal_report_sha256":BRIDGE.sha256(
                CHECK._module_input(decimal_report)),
            "core311_only_native_worker_used":True,
            "original_and_decimal_h5_hashes_reverified":True,
            "new_native_h5_read_status":status,
            "last_native_phase":phase,
            "core311_loaded_in_native_worker":bool(
                result["core311_loaded"] if result else False),
            "native_h5_get_kdata_called":bool(
                result["native_h5_kdata_method_called"] if result else False),
            "per_symbol_matching_rows":(
                result["per_symbol_matching_rows"] if result else
                {"SH600000":0,"SZ000001":0}),
            "new_generated_h5_six_native_records_matched":bool(matched),
            "new_generated_h5_native_driver_certified":bool(matched),
            "synthetic_bridge_only":True,
            "licensed_parquet_units_verified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
            "original_market_files_modified":False,
            "production_query_route_modified":False,
            "licensed_market_data_read":False,
            "native_stdout_stderr_excluded_from_safe":True,
            "no_raw_ohlcva_in_safe_summary":True,
        }
        with dest.open("x",encoding="utf-8") as stream:
            json.dump(safe,stream,ensure_ascii=False,indent=2)
            stream.write("\n")
        return safe
    finally:
        # No deletion: both the generated H5 and all isolated runtime
        # scratch remain available for later debugging.
        pass


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canary-report",type=Path,required=True)
    parser.add_argument("--decimal-report",type=Path,required=True)
    parser.add_argument("--core-proof",type=Path,required=True)
    parser.add_argument("--synthetic-dir",type=Path,required=True)
    parser.add_argument("--python-exe",type=Path,required=True)
    parser.add_argument("--run-id",default="run001")
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--synthetic-native-reread",action="store_true",
                        required=True)
    args=parser.parse_args(argv)
    try:
        safe=native_recheck(args.canary_report,args.decimal_report,
                            args.core_proof,args.synthetic_dir,
                            args.python_exe,args.out,run_id=args.run_id)
        print("SAFE synthetic Decimal H5 native reread:",args.out)
        print("Native status:",safe["new_native_h5_read_status"])
        print("Last native phase:",safe["last_native_phase"])
        print("Matched fictional records:",safe["per_symbol_matching_rows"])
        print("Purchased Parquet source inspected: NO")
    except (ValueError,KeyError,TypeError,ImportError,OSError) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
