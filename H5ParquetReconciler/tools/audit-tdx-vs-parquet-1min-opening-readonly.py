#!/usr/bin/env python3
"""Read-only TDX 240 vs purchased Parquet 241 minute opening-key diagnosis.

This never invents a 09:30 TDX bar, drops a purchased bar for production, or
changes original files. Compare the 240 *shared* native END labels, then test
both first-five-minute aggregation hypotheses against purchased 5min START
labels. Only ratio/error/boolean evidence is written, never actual OHLCVA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

# Reuse all strict local native source, Parquet reader, manifest and comparison
# contracts. These imports do not read source files or create a cache.
import importlib.util

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "tdx_parquet_minute_parent",HERE/"audit-tdx-vs-parquet-day5min-readonly.py")
cross=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cross)
native=cross.native
parquet=cross.parquet
probe=native.probe
FIELDS=native.FIELDS
FORMAT="AStockDataTools TDX 240 vs purchased Parquet 241 minute opening audit v1"


def _minute_label(row,day_text,period):
    if row.get("trading_date")!=day_text or row.get("period")!=period:
        raise ValueError("Purchased bar date or period differs from request")
    stamp=row.get("source_beijing_time")
    if type(stamp) is not str:
        raise ValueError("Missing purchased Beijing minute label")
    try:
        parsed=datetime.strptime(stamp,"%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Malformed purchased Beijing minute label") from exc
    if parsed.date().isoformat()!=day_text:
        raise ValueError("Purchased timestamp spills outside requested day")
    return parsed.hour*60+parsed.minute


def _validated_rows(rows,period,day_text,expected):
    if len(rows)!=len(expected):
        raise ValueError(f"Parquet {period} requires exactly {len(expected)} "
                         "bars for this explicit opening-label hypothesis")
    result=[]
    for bar,minute in zip(rows,expected):
        actual=_minute_label(bar,day_text,period)
        if actual!=minute:
            raise ValueError(
                f"Parquet {period} incomplete, duplicate or unexpected time "
                "grid; no synthetic opening bars or timestamp correction")
        values=[]
        for key in FIELDS:
            value=bar.get(key)
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError("Malformed/nonfinite purchased OHLCVA")
            values.append(float(value))
        o,h,l,c,volume,amount=values
        if (o<=0 or h<=0 or l<=0 or c<=0 or
                h<max(o,l,c)-1e-7 or l>min(o,h,c)+1e-7 or
                volume<0 or amount<0):
            raise ValueError("Invalid purchased OHLCVA bar")
        result.append((minute,tuple(values)))
    return result


def _source_manifest(root,summary,period,date_text,symbol):
    if (summary.get("period")!=period or summary.get("symbol")!=symbol
            or summary.get("from_date")!=date_text
            or summary.get("to_date")!=date_text
            or summary.get("local_cache_used") is not False
            or summary.get("no_h5_read") is not True):
        raise ValueError("Unexpected Parquet bounded query provenance")
    manifest=summary.get("source_file_stat_provenance")
    cross._verify_stat_manifest(root,manifest)
    fingerprint=hashlib.sha256(json.dumps(
        sorted(manifest,key=lambda item:item["relative_path"]),
        sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()
    return manifest,{
        "source_manifest_stat_only_sha256":fingerprint,
        "source_file_count":len(manifest),
        "candidate_source_rows_upper_bound":
            summary["candidate_source_rows_upper_bound"],
        "matching_bar_count":summary["matching_bar_count"],
        "source_manifest_is_stat_only_not_content_authenticated":True,
    }


def _purchased(root,symbol,day_text,budget):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Purchased root must be a non-symlink directory")
    if not (root/"AllCycleAStockData").is_dir():
        raise ValueError("Purchased Parquet folder is missing")
    values={}
    source={}
    manifests=[]
    for period,max_result in (("1min",242),("5min",49)):
        query=parquet.query_bars(
            root,symbol,period,day_text,day_text,
            max_candidate_rows=budget,max_result_bars=max_result,
            local_cache=False)
        bars=query["bars"]
        manifest,source_metadata=_source_manifest(
            root,query["safe_summary"],period,day_text,symbol)
        if query["safe_summary"]["matching_bar_count"]!=len(bars):
            raise ValueError("Parquet summary row-count disagrees with result")
        values[period]=bars
        source[period]=source_metadata
        manifests.append(manifest)
    # A previously read 1min file cannot change while we query 5min.
    for manifest in manifests:
        cross._verify_stat_manifest(root,manifest)
    return values,source


def _within_all(comparison):
    return all(x["within_diagnostic_tolerance"]==x["n"]
               for x in comparison.values())


def _compare_first(aggregate,first_five):
    return native._compare([(None,aggregate)],[(None,first_five)])


def audit(root,tdx_minute1_file,symbol,day_text,
          max_source_bytes=probe.MAX_SOURCE_BYTES,
          max_candidate_rows=35000000):
    if type(symbol) is not str or symbol!=symbol.upper():
        raise ValueError("Canonical uppercase symbol required")
    if (type(max_candidate_rows) is not int or
            not 1<=max_candidate_rows<=100000000):
        raise ValueError("Candidate rows outside safe 1..100000000 bound")
    if (type(max_source_bytes) is not int or
            not 32<=max_source_bytes<=probe.MAX_SOURCE_BYTES):
        raise ValueError("Native source exceeds bounded file limit")
    source_meta=probe.inspect(
        tdx_minute1_file,symbol,day_text,max_source_bytes)
    if (source_meta["period"]!="1min" or
            source_meta["time_grid_classification"]!="1min_end_240"):
        raise ValueError("TDX requires verified 240 ending-minute keys")
    day=probe._date(day_text,"1min")
    tdx=native._read_day_values(
        tdx_minute1_file,"1min",day,source_meta,max_source_bytes)
    native_keys=probe.time_profiles("1min")["1min_end_240"]
    if tuple(t for t,_ in tdx)!=native_keys:
        raise ValueError("Native minute grid changed between reads")

    src,provenance=_purchased(root,symbol,day_text,max_candidate_rows)
    expected=probe.time_profiles("1min")["1min_opening_plus_end_241"]
    pq_one=_validated_rows(src["1min"],"1min",day_text,expected)
    five_start=tuple(t-5 for t in probe.time_profiles("5min")["5min_end_48"])
    pq_five=_validated_rows(src["5min"],"5min",day_text,five_start)
    if tuple(t for t,_ in pq_one[1:])!=native_keys:
        raise ValueError("240 common ending-minute labels not aligned")
    common=native._compare(tdx,pq_one[1:])

    # Distinguish a *separate* Parquet 09:30 observation from an
    # independently testable hypothesis: native TDX may encode both
    # Parquet 09:30 and 09:31 observations inside its first 09:31 bar.
    # This is a read-only diagnostic, not a policy to discard either
    # original purchased record or to rewrite a TDX first minute.
    pq_first_two_aggregate=native._aggregate(pq_one[:2])
    first_unmerged=native._compare(tdx[:1],pq_one[1:2])
    first_merged=native._compare(
        tdx[:1],[(tdx[0][0],pq_first_two_aggregate)])
    remaining=native._compare(tdx[1:],pq_one[2:])
    reconstructed=[(tdx[0][0],pq_first_two_aggregate)]+pq_one[2:]
    all_240_merged=native._compare(tdx,reconstructed)

    regular=[]
    with_open=[]
    for i,(start,five_bar) in enumerate(pq_five):
        # 240 ending-minute observations, every group ends at START+5m.
        minute_group=pq_one[1+i*5:1+(i+1)*5]
        if (len(minute_group)!=5 or
                tuple(x[0] for x in minute_group)!=tuple(
                    range(start+1,start+6))):
            raise ValueError("Unable to associate five regular minute labels")
        base=native._aggregate(minute_group)
        regular.append((start+5,base))
        extra=(pq_one[0],)+tuple(minute_group) if i==0 else minute_group
        with_open.append((start+5,native._aggregate(extra)))
    five_pq_end=[(t+5,v) for t,v in pq_five]
    without=native._compare(regular,five_pq_end)
    including=native._compare(with_open,five_pq_end)

    first_regular=_compare_first(regular[0][1],five_pq_end[0][1])
    first_with_open=_compare_first(with_open[0][1],five_pq_end[0][1])
    no_extra=_within_all(without)
    yes_extra=_within_all(including)
    if no_extra and yes_extra:
        interpretation="both_hypotheses_match_within_tolerance"
    elif no_extra:
        interpretation="regular_240_better_matches_5min"
    elif yes_extra:
        interpretation="opening_inclusion_better_matches_5min"
    else:
        interpretation="neither_hypothesis_fully_matches_5min"
    opening=pq_one[0][1]
    first_regular_open=pq_one[1][1][0]
    return {
        "format":FORMAT,"symbol":symbol,"date":day_text,
        "tdx_source_basename":source_meta["native_source_basename"],
        "tdx_full_source_sha256":source_meta["source_content_sha256"],
        "tdx_verified_minute_count":240,
        "parquet_verified_minute_count":241,
        "parquet_verified_five_minute_count":48,
        "parquet_stat_only_provenance":provenance,
        "common_240_minutes_tdx_vs_parquet":common,
        "first_minute_opening_merge_hypothesis":{
            "native_0931_vs_parquet_0931_without_opening":first_unmerged,
            "native_0931_vs_aggregation_of_parquet_0930_and_0931":
                first_merged,
            "remaining_239_native_vs_parquet":remaining,
            "all_240_native_vs_first_merged_plus_remaining_239":
                all_240_merged,
            "first_minute_all_six_fields_match_after_merge":
                _within_all(first_merged),
            "remaining_239_all_six_fields_match":
                _within_all(remaining),
            "all_240_all_six_fields_match_after_merge":
                _within_all(all_240_merged),
            "opening_merge_is_only_a_hypothesis_not_a_mapping_rule":True,
        },
        "parquet_regular_240_minutes_vs_five_minute":without,
        "parquet_opening_241_in_first_five_minute_vs_five_minute":including,
        "parquet_first_five_minute_without_opening":first_regular,
        "parquet_first_five_minute_with_opening":first_with_open,
        "opening_bar_diagnostics":{
            "observed_separate_0930_opening_key":True,
            "opening_zero_volume":opening[4]==0,
            "opening_zero_amount":opening[5]==0,
            "opening_open_price_matches_first_regular_open":math.isclose(
                opening[0],first_regular_open,rel_tol=1e-5,abs_tol=0.0002),
            "opening_changes_first_5min_by_field":{
                key:not math.isclose(regular[0][1][i],
                                     with_open[0][1][i],
                                     rel_tol=1e-5,
                                     abs_tol=0.0002 if i<4 else 0.02)
                for i,key in enumerate(FIELDS)},
            "aggregation_hypothesis_outcome":interpretation,
            "opening_source_semantics_not_certified":True,
        },
        "minute_alignment":"TDX END == Parquet END for 240 shared keys",
        "first_0930_key_never_synthesized_or_dropped_for_production":True,
        "amount_and_volume_unit_conversion_not_applied":True,
        "source_timestamp_label_semantics_not_certified":True,
        "no_raw_ohlcva_or_individual_times_in_report":True,
        "private_cache_enabled":False,
        "h5_accessed":False,
        "sources_modified":False,
        "staging_or_production_union_performed":False,
        "eligible_for_automatic_production_union":False,
    }


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet-root",type=Path,required=True)
    ap.add_argument("--tdx-1min-file",type=Path,required=True)
    ap.add_argument("--symbol",required=True)
    ap.add_argument("--date",required=True)
    ap.add_argument("--max-tdx-file-bytes",type=int,default=probe.MAX_SOURCE_BYTES)
    ap.add_argument("--max-candidate-rows",type=int,default=35000000)
    ap.add_argument("--read-only",action="store_true",required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        output=probe.safe_out(args.out)
        report=audit(args.parquet_root,args.tdx_1min_file,args.symbol,args.date,
                     args.max_tdx_file_bytes,args.max_candidate_rows)
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open("x",encoding="utf-8") as fd:
            json.dump(report,fd,indent=2,ensure_ascii=False,allow_nan=False)
            fd.write("\n")
        print("Saved TDX/Parquet minute opening-key safe audit:",output)
        print("No market bars, prices or absolute source paths exported.")
    except (ValueError,TypeError,OSError,OverflowError,KeyError,
            ModuleNotFoundError,ZeroDivisionError) as exc:
        ap.error(str(exc))


if __name__=="__main__":
    main()
