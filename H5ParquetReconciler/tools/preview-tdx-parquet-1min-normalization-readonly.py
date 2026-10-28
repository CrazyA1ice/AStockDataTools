#!/usr/bin/env python3
"""Read-only in-memory Parquet 241 -> candidate TDX-END 240 minute preview.

Never exports candidate OHLCVA. Never changes sources, private caches,
staging, production pointers or source timestamp policies. This is an
experimental, source-pinned candidate view ONLY for one explicitly selected
symbol-day with a verified 241 opening-plus-END grid.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "tdx_parquet_241_preview_existing_audit",
    HERE/"audit-tdx-vs-parquet-1min-opening-readonly.py")
opening=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(opening)
native=opening.native
probe=opening.probe
FIELDS=native.FIELDS
FORMAT="AStockDataTools read-only TDX-aligned Parquet 241-to-240 minute candidate preview v1"


def _check_rows(rows,keys,label):
    if type(rows) not in (tuple,list) or len(rows)!=len(keys):
        raise ValueError(label+" expected exactly "+str(len(keys))+" records")
    if tuple(t for t,_ in rows)!=keys:
        raise ValueError(label+" incorrect, duplicated or missing minute grid")
    for _minute,values in rows:
        if (type(values) not in (tuple,list) or len(values)!=6
                or any(type(v) not in (int,float) or
                       not math.isfinite(v) for v in values)):
            raise ValueError(label+" malformed or nonfinite OHLCVA")
        o,h,l,c,vol,amt=values
        if (min(o,h,l,c)<=0 or h<max(o,l,c)-1e-7
                or l>min(o,h,c)+1e-7 or vol<0 or amt<0):
            raise ValueError(label+" impossible OHLCVA geometry")
    return rows


def _matched(stat,expected_n):
    if set(stat)!=set(FIELDS):
        raise ValueError("Unexpected metric field contract")
    for key in FIELDS:
        item=stat[key]
        if type(item.get("n")) is not int or item["n"]!=expected_n:
            raise ValueError("Wrong comparison cardinality")
        if type(item.get("within_diagnostic_tolerance")) is not int:
            raise ValueError("Malformed comparison count")
    return all(stat[k]["within_diagnostic_tolerance"]==expected_n
               for k in FIELDS)


def preview_in_memory(tdx,purchased_one,purchased_five):
    """Build and check candidate bars in RAM; return only SAFE diagnostics.

    source input 0 and 1 are folded into candidate 0, with first input open,
    max high, min low, last close and summation of volume+amount. Every other
    input is assigned exactly once and NO raw source bar is removed/mutated.
    """
    tdx_keys=probe.time_profiles("1min")["1min_end_240"]
    pq_keys=probe.time_profiles("1min")["1min_opening_plus_end_241"]
    five_keys=tuple(t-5 for t in probe.time_profiles("5min")["5min_end_48"])
    _check_rows(tdx,tdx_keys,"Native TDX one-minute")
    _check_rows(purchased_one,pq_keys,"Purchased Parquet one-minute")
    _check_rows(purchased_five,five_keys,"Purchased Parquet five-minute")

    first=native._aggregate(purchased_one[:2])
    candidate=[(tdx_keys[0],first)]+list(purchased_one[2:])
    _check_rows(candidate,tdx_keys,"Candidate END one-minute")
    # No slicing/discarding raw input: the first two rows contribute to
    # candidate 0, the remaining 239 source rows map one-to-one, in order.
    groups=[]
    for group_index,(five_start,_five_values) in enumerate(purchased_five):
        minute_group=candidate[group_index*5:(group_index+1)*5]
        if (len(minute_group)!=5 or
                tuple(t for t,_ in minute_group)!=
                tuple(range(five_start+1,five_start+6))):
            raise ValueError("Candidate cannot form a lossless 5-minute interval")
        groups.append((five_start,native._aggregate(minute_group)))

    first_metrics=native._compare(tdx[:1],candidate[:1])
    rest_metrics=native._compare(tdx[1:],candidate[1:])
    full_metrics=native._compare(tdx,candidate)
    five_metrics=native._compare(purchased_five,groups)
    first_ok=_matched(first_metrics,1)
    rest_ok=_matched(rest_metrics,239)
    full_ok=_matched(full_metrics,240)
    five_ok=_matched(five_metrics,48)
    consistent=first_ok and rest_ok and full_ok and five_ok
    return {
        "source_and_candidate_grid":{
            "purchased_original_1min": "1min_opening_plus_end_241",
            "native_1min": "1min_end_240",
            "candidate_preview_1min": "1min_end_240",
            "purchased_original_5min": "5min_start_48",
        },
        "mapping_lineage_summary":{
            "original_purchased_minute_records":241,
            "candidate_minute_records_in_memory":240,
            "original_rows_used_by_first_candidate":2,
            "original_rows_used_by_remaining_candidates":239,
            "source_minute_records_accounted_for_once":241,
            "original_minutes_discarded":0,
            "synthetic_source_minutes_inserted":0,
            "first_candidate_source_rows_folded_not_deleted":True,
            "all_source_records_preserved_in_original_files":True,
            "candidate_end_minute_labels_are_hypothetical":True,
        },
        "candidate_vs_native_first_minute":first_metrics,
        "candidate_vs_native_remaining_239":rest_metrics,
        "candidate_vs_native_full_240":full_metrics,
        "candidate_240_to_purchased_48_five_minute":five_metrics,
        "gates":{
            "first_candidate_matches_native":first_ok,
            "remaining_239_match_native":rest_ok,
            "candidate_240_matches_native":full_ok,
            "candidate_5min_matches_purchased_5min":five_ok,
            "diagnostic_preview_consistent":consistent,
        },
        "preview_verdict":(
            "diagnostic_candidate_matches_both_sources_not_production_certified"
            if consistent else
            "diagnostic_candidate_mismatch_do_not_materialize"),
        "eligible_for_staging_or_automatic_production_union":False,
        "candidate_ohlcva_exported":False,
    }


def preview(root,tdx_1min_file,symbol,day_text,
            max_source_bytes=probe.MAX_SOURCE_BYTES,
            max_candidate_rows=35000000):
    if type(symbol) is not str or symbol!=symbol.upper():
        raise ValueError("Canonical uppercase requested symbol required")
    if (type(max_source_bytes) is not int or
            not 32<=max_source_bytes<=probe.MAX_SOURCE_BYTES):
        raise ValueError("Unsafe TDX source-file budget")
    if (type(max_candidate_rows) is not int or
            not 1<=max_candidate_rows<=100000000):
        raise ValueError("Unsafe purchased Parquet candidate-row budget")

    native_meta=probe.inspect(
        tdx_1min_file,symbol,day_text,max_source_bytes)
    if (native_meta["period"]!="1min" or
            native_meta["time_grid_classification"]!="1min_end_240"):
        raise ValueError("Strict native 240 END-minute profile required")
    day=probe._date(day_text,"1min")
    native_rows=native._read_day_values(
        tdx_1min_file,"1min",day,native_meta,max_source_bytes)
    src,provenance=opening._purchased(
        root,symbol,day_text,max_candidate_rows)
    pq_one=opening._validated_rows(
        src["1min"],"1min",day_text,
        probe.time_profiles("1min")["1min_opening_plus_end_241"])
    pq_five=opening._validated_rows(
        src["5min"],"5min",day_text,
        tuple(t-5 for t in probe.time_profiles("5min")["5min_end_48"]))
    result=preview_in_memory(native_rows,pq_one,pq_five)
    # All actual per-minute OHLCVA, the candidate and individual time
    # labels live only in private process memory, never in the JSON report.
    return {
        "format":FORMAT,
        "symbol":symbol,"date":day_text,
        "native_source_content_sha256":native_meta["source_content_sha256"],
        "native_source_basename":native_meta["native_source_basename"],
        "purchased_source_stat_only_provenance":provenance,
        **result,
        "source_timestamp_label_semantics_not_certified":True,
        "purchased_source_manifest_not_content_authenticated":True,
        "native_source_hash_pinned_across_both_native_reads":True,
        "private_cache_enabled":False,"h5_accessed":False,
        "original_sources_modified":False,
        "private_staging_or_production_union_performed":False,
        "eligible_for_automatic_production_union":False,
        "no_raw_ohlcva_or_individual_times_in_report":True,
    }


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet-root",required=True,type=Path)
    ap.add_argument("--tdx-1min-file",required=True,type=Path)
    ap.add_argument("--symbol",required=True)
    ap.add_argument("--date",required=True)
    ap.add_argument("--max-tdx-file-bytes",type=int,default=probe.MAX_SOURCE_BYTES)
    ap.add_argument("--max-candidate-rows",type=int,default=35000000)
    ap.add_argument("--read-only",action="store_true",required=True)
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args(argv)
    try:
        out=probe.safe_out(args.out)
        result=preview(args.parquet_root,args.tdx_1min_file,args.symbol,
                       args.date,args.max_tdx_file_bytes,args.max_candidate_rows)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as fd:
            json.dump(result,fd,indent=2,ensure_ascii=False,allow_nan=False)
            fd.write("\n")
        print("Saved read-only 241-to-240 diagnostic preview:",out)
        print("Preview verdict:",result["preview_verdict"])
        print("All source OHLCVA remained local, unchanged and unexported.")
    except (ValueError,TypeError,OSError,OverflowError,KeyError,
            ModuleNotFoundError,ZeroDivisionError) as exc:
        ap.error(str(exc))


if __name__=="__main__":
    main()
