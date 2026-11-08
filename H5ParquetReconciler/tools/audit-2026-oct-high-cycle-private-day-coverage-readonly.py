#!/usr/bin/env python3
"""Final read-only Oct 2026 15/30/60m candidate stockday coverage audit.

All receipts+source+physical Parquet SHA are rechecked using the successful
next-uncovered registry; the current single-day source inventory is also
rechecked independently. Only receipts for SHA-verified complete H5-only
5min stockdays count. This checks *candidate staging coverage*, NOT vendor
unit certification, corporate actions, production merge or H5 mirroring.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent

def _load():
    spec=importlib.util.spec_from_file_location(
        "oct_2026_private_day_coverage_registry",
        HERE/"stage-next-uncovered-oct-h5-high-cycle-private-parquet.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

N=_load()
DAY_STATUS="oct_2026_single_day_sha_verified_private_15_30_60min_candidate_coverage_readonly"

def audit(day):
    if type(day) is not date or day.year!=2026 or day.month!=10:
        raise ValueError("Only a single explicit October 2026 date")
    # Read-only registry validates all known receipt source SHA, 15/30/60m
    # Parquet SHA, stockday identities, and rejects incomplete run folders.
    existing,runs=N.existing_stockdays()
    source=N.A.discover(day,exclude=frozenset())
    if (source.get("day")!=day.isoformat()
            or source.get("status")!=N.A.STATUS
            or source.get("strict_receipt_sha_verified") is not True
            or source.get("original_market_files_modified") is not False
            or source.get("production_activated") is not False
            or source.get("vendor_physical_units_certified") is not False
            or N.S.SHA256.fullmatch(str(source.get("source_5min_sha256"))) is None):
        raise ValueError("Source inventory provenance/SHA gate not accepted")
    eligible=source["eligible_symbols"]
    if (not isinstance(eligible,list) or len(set(eligible))!=len(eligible)
            or any(type(x) is not str or N.S.SYMBOL.fullmatch(x) is None
                   for x in eligible)
            or source.get("candidate_complete_stockdays")!=len(eligible)):
        raise ValueError("Source inventory unique stockday count mismatch")
    daystr=day.isoformat()
    on_day={sym for d,sym in existing if d==daystr}
    missing=sorted(set(eligible)-on_day)
    stale=sorted(on_day-set(eligible))
    if stale:
        # Previously SHA-backed source no longer considered eligible by
        # current H5-only grid/purchased-priority inventory: reject, not count.
        raise ValueError("Previously staged private stockdays are not eligible in latest source")
    staged=len(on_day)
    total=len(eligible)
    if staged+len(missing)!=total or len(existing)<staged:
        raise ValueError("Private high-cycle stockday coverage conservation failed")
    historical_rows=len(existing)*28
    return {
        "status":DAY_STATUS,
        "day":daystr,
        "stage_runs_all_october_sha_verified":runs,
        "stage_stockdays_all_october_sha_verified":len(existing),
        "other_dates_staged_stockdays":len(existing)-staged,
        "eligible_full_h5_5min_source_stockdays":total,
        "this_date_staged_complete_stockdays":staged,
        "this_date_unstaged_complete_stockdays":len(missing),
        "this_date_coverage_complete":len(missing)==0,
        "private_candidate_15min_rows_for_this_date":staged*16,
        "private_candidate_30min_rows_for_this_date":staged*8,
        "private_candidate_60min_rows_for_this_date":staged*4,
        "all_october_private_candidate_rows":historical_rows,
        "existing_private_h5_source_sha256":source["source_5min_sha256"],
        "full_existing_receipt_and_parquet_sha_reverified":True,
        "full_original_market_or_h5_files_modified":False,
        "new_market_private_or_production_files_written":False,
        "production_activated":False,
        "vendor_physical_units_certified":False,
        "unadjusted_time_label_semantics_certified":False,
        "not_official_day_week_or_month_data":True,
        "private_only_research_candidate_coverage":True,
        "no_market_OHLCVA_or_symbol_list_exported":True,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--day",default="2026-10-13")
    p.add_argument("--audit-readonly",action="store_true",required=True)
    p.add_argument("--require-complete",action="store_true")
    args=p.parse_args(argv)
    try:
        report=audit(date.fromisoformat(args.day))
        if args.require_complete and not report["this_date_coverage_complete"]:
            raise ValueError("Private H5-only high-cycle stockday coverage incomplete: "+
                             str(report["this_date_unstaged_complete_stockdays"])+" remain")
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
        p.error("Oct private candidate final coverage NOT accepted: "+
                type(exc).__name__+": "+str(exc)+"; readonly, no writes")
    print("PRIVATE_OCT_HIGH_CYCLE_DAY_COVERAGE="+json.dumps(
        report,ensure_ascii=False,sort_keys=True,separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
