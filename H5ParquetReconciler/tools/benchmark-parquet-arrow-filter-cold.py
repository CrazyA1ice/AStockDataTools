#!/usr/bin/env python3
"""Cold-query A/B: existing ParquetFile batches vs Arrow Dataset predicates.

ALWAYS a read-only, no-cache experimental benchmark. Project exactly the same
source RowGroups and OHLCVA fields under the same upper-bound budget. Compare
all actual bars including their RowGroup provenance in memory, but emit only
aggregate diagnostics to reports/. Filtered Arrow output row count does NOT
measure decoded Parquet records or disk read bytes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import time
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
Q_SPEC=importlib.util.spec_from_file_location(
    "parquet_ab_benchmark_query",HERE/"query-parquet-primary-readonly.py")
query=importlib.util.module_from_spec(Q_SPEC)
Q_SPEC.loader.exec_module(query)
FIELDS=query.validator.FIELDS
MODULE=HERE.parent
ORDER=("rowgroup-first","arrow-first")


def arrow_filtered_query(root,symbol,period,start,end,
                         max_candidate_rows=30000000,max_result_bars=25000):
    """Dataset fragment per RowGroup retains exact file+RowGroup provenance."""
    import pyarrow.dataset as ds

    started=time.perf_counter()
    context=query.prepare_query(
        root,symbol,period,start,end,max_candidate_rows,max_result_bars)
    fmt=ds.ParquetFileFormat()
    criterion=(
        (ds.field("ts")>=context["low_ms"])
        & (ds.field("ts")<context["high_ms"])
        & ds.field("symbol").isin(sorted(context["aliases"]))
    )
    observed={}
    arrow_emitted=0
    nonempty_fragments=0
    for path,pf,group in context["pending"]:
        fragment=fmt.make_fragment(str(path),row_groups=[group])
        fragment_count=0
        for batch in fragment.to_batches(
                columns=list(query.NEEDED),filter=criterion,
                batch_size=65536,use_threads=True):
            arrow_emitted+=batch.num_rows
            fragment_count+=batch.num_rows
            for item in batch.to_pylist():
                if query.core.symbol_id(item["symbol"])!=context["symbol"]:
                    continue
                stamp=item["ts"]
                if type(stamp) is not int or stamp%60000:
                    raise ValueError("Non-integer or non-minute source timestamp")
                raw=datetime.fromtimestamp(stamp/1000,tz=query.core.UTC8)
                if not context["start"]<=raw.date()<=context["end"]:
                    continue
                numbers=tuple(float(item[f]) for f in FIELDS)
                if not all(math.isfinite(n) for n in numbers):
                    raise ValueError("Nonfinite source OHLCVA encountered")
                if (numbers[1]<max(numbers[0],numbers[2],numbers[3])-1e-7
                        or numbers[2]>min(
                            numbers[0],numbers[1],numbers[3])+1e-7
                        or numbers[4]<0 or numbers[5]<0):
                    raise ValueError("Invalid source OHLCVA geometry")
                if stamp in observed:
                    raise ValueError("Duplicate selected source timestamp")
                if len(observed)>=context["max_result_bars"]:
                    raise ValueError("Selected bar limit exceeded")
                observed[stamp]={
                    "symbol":context["symbol"],"period":period,
                    "trading_date":raw.date().isoformat(),
                    "source_timestamp_ms":stamp,
                    "source_beijing_time":raw.strftime("%Y-%m-%d %H:%M"),
                    "normalized_query_label":(
                        raw.date().isoformat() if period=="day"
                        else raw.strftime("%Y-%m-%d %H:%M")),
                    "source_file_relative_path":path.relative_to(
                        context["root"]).as_posix(),
                    "source_row_group":group,
                    **dict(zip(FIELDS,numbers)),
                }
        if fragment_count:
            nonempty_fragments+=1
    return {
        "bars":[observed[key] for key in sorted(observed)],
        "safe_measurement":{
            "engine":"arrow_dataset_rowgroup_fragment_filter",
            "candidate_source_rows_upper_bound":context["metadata"][
                "candidate_source_rows_upper_bound"],
            "candidate_row_groups":len(context["pending"]),
            "row_groups_that_emitted_filtered_rows":nonempty_fragments,
            "source_file_footers_opened":context["metadata"][
                "source_file_footers_opened"],
            "arrow_rows_emitted_after_predicate":arrow_emitted,
            "selected_matching_bars":len(observed),
            "actual_parquet_rows_decoded_unknown":True,
            "actual_disk_bytes_read_unknown":True,
            "source_files_modified":False,
            "query_elapsed_seconds_this_invocation":round(
                time.perf_counter()-started,6),
        },
    }


def benchmark(root,symbol,period,start,end,max_candidate_rows=30000000,
              max_result_bars=25000,order="rowgroup-first"):
    if order not in ORDER:
        raise ValueError("Invalid order")
    # Metadata-only source census before either engine. No licensed values
    # read, and no cache records created. This is NOT a content checksum.
    _,first_day,last_day=query.request_dates(
        symbol,period,start,end,max_candidate_rows,max_result_bars)
    source_before=query.private_cache.source_signature(
        root,period,first_day,last_day,query.core)
    first={}
    if order=="rowgroup-first":
        old=query.query_bars(
            root,symbol,period,start,end,
            max_candidate_rows,max_result_bars,local_cache=False)
        first["rowgroup"]=old
        arrow=arrow_filtered_query(
            root,symbol,period,start,end,max_candidate_rows,max_result_bars)
        first["arrow"]=arrow
    else:
        arrow=arrow_filtered_query(
            root,symbol,period,start,end,max_candidate_rows,max_result_bars)
        first["arrow"]=arrow
        old=query.query_bars(
            root,symbol,period,start,end,
            max_candidate_rows,max_result_bars,local_cache=False)
        first["rowgroup"]=old
    source_after=query.private_cache.source_signature(
        root,period,first_day,last_day,query.core)
    if source_before!=source_after:
        raise ValueError(
            "Source Parquet stat manifest changed between A/B engines; "
            "refusing timing report")
    # Includes OHLCVA exact Python float values, time labels, rowgroup and path.
    # No raw purchased values leave this function or go into report JSON.
    if old["bars"]!=arrow["bars"]:
        raise ValueError(
            "Arrow filter differs in bars, OHLCVA or provenance; "
            "refusing benchmark report (investigate locally)")
    base=old["safe_summary"]
    other=arrow["safe_measurement"]
    old_secs=base["query_elapsed_seconds_this_invocation"]
    arrow_secs=other["query_elapsed_seconds_this_invocation"]
    return {
        "format":"AStockDataTools Parquet cold-read A/B comparison v1",
        "source_stat_manifest_sha256":
            source_before["manifest_sha256_stat_only"],
        "source_stat_manifest_file_count":
            source_before["manifest_file_count"],
        "source_manifest_stat_only_not_content_sha256":True,
        "source_stat_manifest_stable_across_both_engines":True,
        "symbol":base["symbol"],"period":base["period"],
        "from_date":base["from_date"],"to_date":base["to_date"],
        "requested_execution_order":order,
        "query_output_all_values_times_and_source_provenance_identical":True,
        "matching_bar_count":len(old["bars"]),
        "candidate_row_groups":base["candidate_row_groups"],
        "candidate_source_rows_upper_bound":base[
            "candidate_source_rows_upper_bound"],
        "baseline_existing_rowgroup":{
            "elapsed_seconds":old_secs,
            "source_rows_delivered_to_python_before_filter":
                base["source_rows_scanned_this_invocation"],
            "source_file_footers_opened":
                base["source_file_footers_opened_this_invocation"],
        },
        "experimental_arrow_filtered":{
            "elapsed_seconds":arrow_secs,
            "arrow_rows_emitted_after_predicate":
                other["arrow_rows_emitted_after_predicate"],
            "row_groups_that_emitted_filtered_rows":
                other["row_groups_that_emitted_filtered_rows"],
            "actual_parquet_rows_decoded_unknown":True,
            "actual_disk_bytes_read_unknown":True,
            "row_group_upper_bound_still":
                other["candidate_source_rows_upper_bound"],
        },
        "observed_baseline_seconds_divided_by_arrow_seconds":(
            round(old_secs/arrow_secs,5) if arrow_secs else None),
        "execution_order_and_os_cache_could_bias_timings":True,
        "arrow_output_rows_are_not_number_of_physical_rows_read":True,
        "fast_cold_engine_not_automatically_enabled":True,
        "local_private_ohlcva_cache_not_used":True,
        "only_safe_aggregate_metadata_exported":True,
        "raw_ohlcva_exported":False,
        "h5_source_accessed":False,
        "source_market_files_modified":False,
        "automatic_source_union_or_import_performed":False,
    }


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root",type=Path)
    ap.add_argument("--symbol",required=True)
    ap.add_argument("--period",choices=query.PERIODS,required=True)
    ap.add_argument("--from-date",required=True)
    ap.add_argument("--to-date",required=True)
    ap.add_argument("--max-candidate-rows",type=int,default=30000000)
    ap.add_argument("--max-result-bars",type=int,default=25000)
    ap.add_argument("--order",choices=ORDER,default="rowgroup-first")
    ap.add_argument("--read-only",action="store_true",required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        out,scratch=query.core.resolve_module_artifact_paths(args.out)
        root,_,_=query.core.resolve_safe_paths(args.root,out,scratch)
        if (out.suffix.lower()!=".json" or out.exists()
                or not out.is_relative_to((MODULE/"reports").resolve())):
            raise ValueError("Use NEW JSON under H5ParquetReconciler/reports/")
        report=benchmark(root,args.symbol,args.period,args.from_date,
                         args.to_date,args.max_candidate_rows,
                         args.max_result_bars,args.order)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as fd:
            json.dump(report,fd,ensure_ascii=False,indent=2)
            fd.write("\n")
        print("Saved NO-OHLCVA Arrow-vs-RowGroup cold query A/B:",out)
        print("same bars:",report[
            "query_output_all_values_times_and_source_provenance_identical"])
        print("times (s): rowgroup",
              report["baseline_existing_rowgroup"]["elapsed_seconds"],
              "arrow",report["experimental_arrow_filtered"]["elapsed_seconds"])
    except (ValueError,TypeError,OSError,OverflowError,
            ModuleNotFoundError) as e:
        ap.error(str(e))


if __name__=="__main__":
    main()
