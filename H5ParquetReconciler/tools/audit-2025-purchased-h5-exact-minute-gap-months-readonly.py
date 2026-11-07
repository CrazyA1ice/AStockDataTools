#!/usr/bin/env python3
"""Bounded 2025 purchased-first minute H5 exact-key monthly gap audit.

Requires already SHA/metadata-checked source-grid month receipts and completed
private SQLite membership indexes. Reuses the existing exact H5-vs-purchased
key comparator; never builds an index, stages a market bar, repairs a key,
copies purchased OHLCVA or changes a production pointer. Source fingerprints
are metadata-only, NOT full source-content SHA.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
PERIODS=("1min","5min")
GAP_FIELDS=(
    "h5_only_keys_on_full_purchased_absence_days",
    "h5_only_candidate_keys_on_partial_purchased_stockdays",
    "purchased_only_0930_keys_on_complete_H5_stockdays",
    "purchased_only_other_time_keys_on_complete_H5_stockdays",
    "overlapping_exact_keys",
    "purchased_a_share_date_key_count",
    "h5_date_native_rows_examined",
)


def _load(tag,name):
    spec=importlib.util.spec_from_file_location(tag,HERE/name)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK=_load("verified_2025_source_only_checkpoint",
            "run-purchased-2025-minute-grid-checkpoint-batch.py")
EXACT=_load("verified_2025_indexed_h5_exact_comparator",
            "audit-minute-index-window-readonly.py")


def audit(root,from_month="2025-01",through_month="2025-02",*,max_months=2):
    labels=CHECK.months(from_month,through_month)
    if (type(max_months) is not int or not 1<=max_months<=2
            or not 1<=len(labels)<=max_months):
        raise ValueError("Limit H5 source-key monthly audit to 1..2 contiguous 2025 months")
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Require existing non-symlink source market root")
    before=CHECK.A.I.N.source_snapshot(root,2025)
    totals={p:Counter() for p in PERIODS}
    quarantines={p:Counter() for p in PERIODS}
    month_results=[]
    for month in labels:
        bought=CHECK.verified_receipt(month,root,before)
        if bought is None:
            raise ValueError("Missing accepted purchased source-grid receipt: "+month)
        first,last=CHECK.A._month(month)
        windows=CHECK.A.G.plan(
            root,first.isoformat(),last.isoformat(),
            allow_build=False,mode="minute")
        if (not windows or any(w["mode"]!="reuse_existing_index" or
                not w.get("existing_index") for w in windows)):
            raise ValueError("H5 exact-key audit must reuse every existing private index")
        per_period={p:Counter() for p in PERIODS}
        quarantine={p:Counter() for p in PERIODS}
        audited_days=0
        no_source_dates=0
        for w in windows:
            report=EXACT.audit(
                root,Path(w["existing_index"]),w["first"],w["last"])
            if (report.get("status")!=
                    "read_only_existing_index_multi_day_candidate_diff_not_activated"
                    or report.get("existing_purchased_key_index_reused") is not True
                    or report.get("original_purchased_parquet_opened_for_bars") is not False
                    or report.get("purchased_ohlcva_rows_rematerialized")!=0
                    or report.get("new_parquet_or_h5_market_files_written") is not False
                    or report.get("new_market_gap_keys_accepted")!=0
                    or report.get("ready_for_production_query") is not False):
                raise ValueError("H5 exact-key comparator violated no-market-write policy")
            if (report["from_day"]!=w["first"] or
                    report["through_day"]!=w["last"] or
                    set(report["summaries"])!=set(PERIODS)):
                raise ValueError("H5 exact-key report window/period drift")
            audited_days+=report["audited_calendar_dates"]
            no_source_dates+=sum(
                d["source_coverage_status"]=="NO_SOURCE_EVIDENCE_NOT_EXCHANGE_CLOSED"
                for d in report["days"])
            for period in PERIODS:
                p=report["summaries"][period]
                per_period[period].update(
                    {k:p[k] for k in GAP_FIELDS})
                quarantine[period].update(
                    p["quarantined_h5_stockdays_by_reason"])
        for period in PERIODS:
            keys=bought["periods"][period]["keys"]
            if per_period[period]["purchased_a_share_date_key_count"]!=keys:
                raise ValueError(
                    "Indexed purchased keys disagree with accepted month receipt: "+month+
                    " "+period)
            totals[period].update(per_period[period])
            quarantines[period].update(quarantine[period])
        entry={
            "month":month,
            "audited_weekday_dates":audited_days,
            "dates_without_either_purchased_or_native_h5_evidence":no_source_dates,
            "periods":{
                period:{
                    **{k:int(per_period[period][k]) for k in GAP_FIELDS},
                    "quarantined_h5_stockdays_by_reason":
                        dict(sorted(quarantine[period].items())),
                } for period in PERIODS
            },
            "accepted_purchased_month_receipt_reused":True,
            "h5_native_source_evidence_by_period":{
                period:{
                    "native_rows_examined":int(per_period[period][
                        "h5_date_native_rows_examined"]),
                    "any_native_rows_observed":bool(per_period[period][
                        "h5_date_native_rows_examined"]),
                    "zero_candidate_keys_proves_full_h5_coverage":False,
                } for period in PERIODS
            },
            "existing_source_key_index_windows_reused":len(windows),
            "purchased_ohlcva_copied":0,
            "new_market_gap_keys_accepted":0,
        }
        month_results.append(entry)
        print("H5_2025_MONTH_READONLY="+json.dumps(
            entry,sort_keys=True,separators=(",",":")),flush=True)
    if CHECK.A.I.N.source_snapshot(root,2025)!=before:
        raise RuntimeError("2025 source market metadata changed during H5 gap audit")
    result={
        "status":"2025_purchased_first_h5_exact_minute_gaps_candidate_readonly_not_activated",
        "from_month":labels[0],
        "through_month":labels[-1],
        "months_audited":len(labels),
        "summaries":{
            period:{
                **{k:int(totals[period][k]) for k in GAP_FIELDS},
                "quarantined_h5_stockdays_by_reason":
                    dict(sorted(quarantines[period].items()))
            } for period in PERIODS
        },
        "h5_native_source_observed_during_audit_by_period":{
            period:bool(totals[period]["h5_date_native_rows_examined"])
            for period in PERIODS
        },
        "zero_h5_candidate_keys_without_native_source_evidence_is_not_cross_validation":True,
        "all_purchased_month_grid_receipts_preverified_and_reused":True,
        "all_source_key_indexes_existing_and_reused":True,
        "new_source_key_indexes_created":0,
        "purchased_ohlcva_read_or_copied":False,
        "original_purchased_parquet_or_h5_modified":False,
        "h5_candidate_keys_automatically_accepted":0,
        "new_market_parquet_or_h5_written":False,
        "official_exchange_calendar_certified":False,
        "h5_price_volume_amount_units_certified":False,
        "source_fingerprint_is_content_sha":False,
        "production_activated":False,
        "ready_for_production_query":False,
    }
    print("H5_2025_EXACT_MONTH_GAP_SUMMARY="+json.dumps(
        result,sort_keys=True,separators=(",",":")),flush=True)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--from-month",default="2025-01")
    p.add_argument("--through-month",default="2025-02")
    a=p.parse_args(argv)
    audit(a.root,a.from_month,a.through_month)


if __name__=="__main__":
    main()
