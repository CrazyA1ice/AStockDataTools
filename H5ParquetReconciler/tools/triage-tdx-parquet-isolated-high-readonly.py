#!/usr/bin/env python3
"""Diagnose whether an isolated cross-source 1-minute High discrepancy affects 5-minute High.

This script reads real bounded market sources strictly read-only, reuses the
existing 241->240 in-memory candidate rule and TDX full-content SHA checks,
and emits SAFE AGGREGATE COUNTS ONLY. It does not export OHLCVA, individual
minute/interval keys or paths, and never authorizes staging or production union.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "isolated_high_existing_preview",
    HERE/"preview-tdx-parquet-1min-normalization-readonly.py")
P=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
native=P.native
probe=P.probe
opening=P.opening
FIELDS=P.FIELDS
FORMAT="AStockDataTools read-only cross-vendor isolated minute High mechanism v1"
RULE_ID="experimental_tdx_end240_from_pq241_opening_fold_v1"


def _aligned_5m(native_5m,purchased_5m):
    ends=probe.time_profiles("5min")["5min_end_48"]
    P._check_rows(native_5m,ends,"Native TDX five-minute")
    starts=tuple(t-5 for t in ends)
    P._check_rows(purchased_5m,starts,"Purchased Parquet five-minute")
    return [(t+5,bar) for t,bar in purchased_5m]


def _grouped(minute):
    ends=probe.time_profiles("5min")["5min_end_48"]
    result=[]
    for i,end in enumerate(ends):
        subset=minute[i*5:(i+1)*5]
        if (len(subset)!=5 or
                tuple(t for t,_ in subset)!=tuple(range(end-4,end+1))):
            raise ValueError("Incomplete or nonaligned 5-minute source grid")
        result.append((end,native._aggregate(subset)))
    return result


def _is_match(reference,actual,field):
    return math.isclose(reference,actual,rel_tol=1e-5,
                        abs_tol=0.0002 if field in FIELDS[:4] else 0.02)


def diagnose_in_memory(tdx_one,purchased_one,tdx_five,purchased_five):
    """Never return market OHLCVA or individual time positions."""
    keys=probe.time_profiles("1min")["1min_end_240"]
    pq_keys=probe.time_profiles("1min")["1min_opening_plus_end_241"]
    P._check_rows(tdx_one,keys,"Native TDX one-minute")
    P._check_rows(purchased_one,pq_keys,"Purchased Parquet one-minute")
    pq_five_end=_aligned_5m(tdx_five,purchased_five)
    candidate=[(keys[0],native._aggregate(purchased_one[:2]))]+list(purchased_one[2:])
    P._check_rows(candidate,keys,"In-memory candidate one-minute")
    native_agg=_grouped(tdx_one)
    purchased_agg=_grouped(candidate)

    discrepancies={field:[] for field in FIELDS}
    for idx,((left_t,left),(right_t,right)) in enumerate(zip(tdx_one,candidate)):
        if left_t!=right_t:
            raise ValueError("Minute keys diverged")
        for index,field in enumerate(FIELDS):
            if not _is_match(left[index],right[index],field):
                discrepancies[field].append(idx)

    high_indices=discrepancies["high"]
    affected_groups={i//5 for i in high_indices}
    native_controls=0
    purchased_controls=0
    neither_controls=0
    both_control=0
    interval_high_cross_source_mismatches=0
    for idx in high_indices:
        start=(idx//5)*5
        native_peers=[bar[1][1] for bar in tdx_one[start:start+5]]
        purchase_peers=[bar[1][1] for bar in candidate[start:start+5]]
        n=tdx_one[idx][1][1]==max(native_peers)
        p=candidate[idx][1][1]==max(purchase_peers)
        native_controls+=int(n)
        purchased_controls+=int(p)
        both_control+=int(n and p)
        neither_controls+=int(not n and not p)
        interval_high_cross_source_mismatches+=int(
            not _is_match(native_agg[idx//5][1][1],
                          purchased_agg[idx//5][1][1],"high"))

    native_internal=native._compare(native_agg,tdx_five)
    purchased_internal=native._compare(purchased_agg,pq_five_end)
    cross_five=native._compare(tdx_five,pq_five_end)
    source_consistent=P._matched(native_internal,48)
    purchased_consistent=P._matched(purchased_internal,48)
    cross_five_consistent=P._matched(cross_five,48)
    all_minute_match=all(not v for v in discrepancies.values())
    isolated_high_only=(len(high_indices)==1 and all(
        not discrepancies[f] for f in FIELDS if f!="high"))
    high_five_all_match=(cross_five["high"]["within_diagnostic_tolerance"]==48)
    if isolated_high_only and source_consistent and purchased_consistent and high_five_all_match:
        verdict="isolated_minute_high_disagreement_not_visible_at_5min_tolerance"
    elif all_minute_match and source_consistent and purchased_consistent and cross_five_consistent:
        verdict="all_checked_minute_and_five_minute_fields_match"
    else:
        verdict="other_or_cross_period_disagreement_do_not_materialize"
    return {
        "candidate_rule_id":RULE_ID,
        "candidate_rule_is_experimental":True,
        "minute_comparisons":240,
        "mismatch_counts_by_field":{f:len(discrepancies[f]) for f in FIELDS},
        "first_minute_any_field_disagreement":any(
            0 in discrepancies[f] for f in FIELDS),
        "isolated_high_only":isolated_high_only,
        "high_mismatch_records":len(high_indices),
        "affected_five_minute_intervals_count":len(affected_groups),
        "high_mismatch_source_minute_was_native_interval_max_count":native_controls,
        "high_mismatch_source_minute_was_purchased_interval_max_count":purchased_controls,
        "high_mismatch_source_minute_was_both_interval_max_count":both_control,
        "high_mismatch_source_minute_was_neither_interval_max_count":neither_controls,
        "high_mismatch_containing_interval_aggregated_high_disagrees_count":
            interval_high_cross_source_mismatches,
        "native_1min_aggregated_vs_native_5min":native_internal,
        "purchased_candidate_1min_aggregated_vs_purchased_5min":purchased_internal,
        "native_5min_vs_purchased_5min":cross_five,
        "native_1min_internal_5min_all_fields_match":source_consistent,
        "purchased_candidate_1min_internal_5min_all_fields_match":purchased_consistent,
        "cross_source_5min_all_fields_match":cross_five_consistent,
        "verdict":verdict,
        "eligible_for_automatic_production_union":False,
        "candidate_ohlcva_exported":False,
        "individual_mismatch_minute_or_interval_positions_exported":False,
    }


def diagnose(root,tdx_minute1_file,tdx_minute5_file,symbol,day_text,
             max_source_bytes=probe.MAX_SOURCE_BYTES,
             max_candidate_rows=35000000):
    if (type(symbol) is not str or
            not (len(symbol)==8 and symbol[:2] in ("SH","SZ") and
                 symbol[2:].isascii() and symbol[2:].isdigit())):
        raise ValueError("Canonical SH/SZ six-digit symbol required")
    if type(max_source_bytes) is not int or not 32<=max_source_bytes<=probe.MAX_SOURCE_BYTES:
        raise ValueError("TDX source byte budget out of bounds")
    if type(max_candidate_rows) is not int or not 1<=max_candidate_rows<=100000000:
        raise ValueError("Parquet candidate row budget out of bounds")
    if Path(tdx_minute1_file).resolve()==Path(tdx_minute5_file).resolve():
        raise ValueError("Distinct native source paths required")
    day=probe._date(day_text,"1min")
    native_rows={}
    meta={}
    for period,file,profile in (
            ("1min",tdx_minute1_file,"1min_end_240"),
            ("5min",tdx_minute5_file,"5min_end_48")):
        checked=probe.inspect(file,symbol,day_text,max_source_bytes)
        if checked["period"]!=period or checked["time_grid_classification"]!=profile:
            raise ValueError("Native minute source grid unsupported")
        native_rows[period]=native._read_day_values(
            file,period,day,checked,max_source_bytes)
        meta[period]=checked
    src,provenance=opening._purchased(root,symbol,day_text,max_candidate_rows)
    purchased_one=opening._validated_rows(
        src["1min"],"1min",day_text,
        probe.time_profiles("1min")["1min_opening_plus_end_241"])
    five_starts=tuple(t-5 for t in probe.time_profiles("5min")["5min_end_48"])
    purchased_five=opening._validated_rows(
        src["5min"],"5min",day_text,five_starts)
    stats=diagnose_in_memory(
        native_rows["1min"],purchased_one,native_rows["5min"],purchased_five)
    return {
        "format":FORMAT,
        "symbol":symbol,"date":day_text,
        "tdx_source_content_sha256":{
            period:meta[period]["source_content_sha256"]
            for period in ("1min","5min")},
        "purchased_source_stat_only_provenance":provenance,
        **stats,
        "purchased_source_manifests_not_content_authenticated":True,
        "native_source_hash_verified_against_second_read":True,
        "sources_modified":False,
        "private_cache_enabled":False,
        "h5_accessed":False,
        "market_ohlcva_or_private_paths_exported":False,
        "production_mapping_certified":False,
        "candidate_materialized":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet-root",type=Path,required=True)
    parser.add_argument("--tdx-1min-file",type=Path,required=True)
    parser.add_argument("--tdx-5min-file",type=Path,required=True)
    parser.add_argument("--symbol",required=True)
    parser.add_argument("--date",required=True)
    parser.add_argument("--max-tdx-file-bytes",type=int,default=probe.MAX_SOURCE_BYTES)
    parser.add_argument("--max-candidate-rows",type=int,default=35000000)
    parser.add_argument("--read-only",required=True,action="store_true")
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        out=probe.safe_out(args.out)
        report=diagnose(args.parquet_root,args.tdx_1min_file,args.tdx_5min_file,
                        args.symbol,args.date,args.max_tdx_file_bytes,args.max_candidate_rows)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as fd:
            json.dump(report,fd,ensure_ascii=False,indent=2,allow_nan=False)
            fd.write("\n")
        print("Saved SAFE isolated minute High mechanism audit:",out)
        print("Verdict:",report["verdict"],"High mismatches:",report["high_mismatch_records"])
        print("Raw market bars, private paths and individual minute keys not exported.")
    except (OSError,ValueError,TypeError,KeyError,OverflowError,ModuleNotFoundError,
            ZeroDivisionError) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
