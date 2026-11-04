#!/usr/bin/env python3
"""Local-only bounded real DAY OHLCVA API for the SHA-pinned 2011-2026 version.

PROGRAMMATIC API: read_local_bars(...) with explicit allow_private_values=True.
Returns exact source float64 OHLCVA values in Python process memory ONLY.
No file containing bar values or requested symbol/day is ever written.
Only an aggregate-only CLI SAFE may be written under module reports/.

This is not production authorization. 2016/2026 H5-only bars remain
uncertified units/source-semantic candidates, distinguish provenance.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load(label,path):
    spec=importlib.util.spec_from_file_location(label,HERE/path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


Q=load("private_all16_real_ohlcva_local_coverage",
       "query-private-2011-2026-all16-coverage-readonly.py")

LIMIT_BARS=31


def read_local_bars(version_safe,version_sha256,symbol,first,last,
                    *,allow_private_values=False,max_candidate_rows=3000000,
                    max_result_bars=31):
    """Return {"bars": [...], "safe_summary": {...}} in local process only.

    Bars are private licensed data. Keep them on this machine, not in
    JSON reports, terminal logs pasted online, GitHub, or other connectors.
    Cross-check against pinned physical partitions and year SQLite first;
    never expose even a partial result on a failed audit.
    """
    if allow_private_values is not True:
        raise ValueError("Local licensed OHLCVA read requires explicit opt-in")
    if type(max_result_bars) is not int or not 1<=max_result_bars<=LIMIT_BARS:
        raise ValueError("Only 1..31 local DAY bars are permitted")
    # Inputs validated by coverage query; pin version before any OHLCVA read.
    version=Q.version(version_safe,version_sha256)
    received=[]
    def sink(row):
        if len(received)>=max_result_bars:
            raise ValueError("Local result exceeded explicitly bounded bar limit")
        received.append(dict(row))

    safe=Q.query(version,version_sha256,symbol,first,last,
                 max_candidate_rows=max_candidate_rows,
                 private_row_callback=sink)
    if (safe.get("status")!=
            "private_all16_bounded_day_coverage_keys_and_provenance_verified_only"
            or safe.get("source_all16_private_version_sha256")!=version_sha256
            or safe.get("all_original_licensed_OHLCVA_values_read") is not True
            or safe.get("local_licensed_OHLCVA_values_exported_to_safe") is not False
            or safe.get("matched_stockday_rows")!=len(received)
            or safe.get("sqlite_rows_matched")!=len(received)
            or safe.get("matched_key_rows_vectorized_by_arrow")!=len(received)
            or any(safe.get(k) is not False for k in (
                "original_market_source_opened",
                "private_or_production_active_pointer_modified",
                "ready_for_production_query","ready_for_automatic_market_merge",
                "ready_for_h5_mirror"))):
        raise ValueError("Local value read was not fully private and SHA verified")
    kinds=Counter(r["value_source"] for r in received)
    if dict(sorted(kinds.items()))!=safe["by_source_counts"]:
        raise ValueError("Local source row classes changed during value audit")
    received.sort(key=lambda row:(row["ts"],row["trading_date"]))
    # Ensure explicit source sematics remain visible in local API result.
    # Never silently treat unverified H5 amounts as purchased-equivalent.
    safe=dict(safe)
    safe["private_values_returned_only_to_opted_in_local_python_caller"]=True
    safe["local_bars_count"]=len(received)
    safe["h5_only_value_units_certified"]=False
    safe["original_vendor_unknown_extra_field_semantics_certified"]=False
    return {"bars":received,"safe_summary":safe}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version-safe",type=Path,required=True)
    p.add_argument("--version-sha256",required=True)
    p.add_argument("--symbol",required=True)
    p.add_argument("--start",required=True)
    p.add_argument("--end",required=True)
    p.add_argument("--max-candidate-rows",type=int,default=3000000)
    p.add_argument("--max-result-bars",type=int,default=31)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--verify-local-values-only",action="store_true",required=True)
    args=p.parse_args(argv)
    try:
        dest=Path(args.out)
        if (Q.M.REPORTS.is_symlink() or dest.is_symlink() or dest.exists()
                or dest.suffix!=".json"
                or dest.resolve().parent!=Q.M.REPORTS.resolve()):
            raise ValueError("Only NEW module reports/ aggregate-only local-check receipt")
        result=read_local_bars(
            args.version_safe,args.version_sha256,
            args.symbol,args.start,args.end,
            allow_private_values=True,
            max_candidate_rows=args.max_candidate_rows,
            max_result_bars=args.max_result_bars)
        summary=result["safe_summary"]
        if "bars" in summary:
            raise ValueError("Licensed values cannot be included in aggregate SAFE")
        with dest.open("x",encoding="utf-8",newline="\n") as fp:
            json.dump(summary,fp,indent=2,sort_keys=True)
            fp.write("\n")
        # Never print the values, symbol or requested day keys to terminal.
        print("PASS: actual local OHLCVA float64 values validated in memory")
        print("Row count:",summary["local_bars_count"],
              "Purchased/H5:",summary["by_source_counts"])
        print("Aggregate-only SAFE:",args.out)
        print("No market values, symbol or exact query dates written to report")
    except Exception:
        p.error("Refused local OHLCVA read; version SHA, data or key validation incomplete")


if __name__=="__main__":
    main()
