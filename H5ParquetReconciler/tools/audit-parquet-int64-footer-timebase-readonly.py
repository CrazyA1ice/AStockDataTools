#!/usr/bin/env python3
"""Safely test int64 Parquet DATE footer-stat ranges against timebase candidates.

Exactly three specified Parquet files. Only ParquetFile.metadata and
schema_arrow are accessed. No K-line rows, raw timestamp extrema, price,
amount, volume, market H5, or SQLite are read or exported.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "parquet_footer_schema_prior_v2",
    HERE/"probe-parquet-arrow-footer-schema-readonly.py")
PREVIOUS=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREVIOUS)
AUDIT=PREVIOUS.AUDIT
FORMAT="AStockDataTools Parquet int64 footer date-timebase candidates v1"
PERIODS=("day","5min","1min")
CANDIDATES=("epoch_s","epoch_ms","epoch_us","epoch_ns",
            "calendar_yyyymmddhhmm")
UTC8=timezone(timedelta(hours=8))
MAX_ROWGROUPS=4096


def _date_candidate_month(value,candidate):
    """A date can only be a candidate if its timezone-adjusted month matches."""
    if type(value) is not int or value<0:
        return None
    try:
        if candidate=="calendar_yyyymmddhhmm":
            literal=str(value)
            if len(literal)!=12:
                return None
            d=datetime.strptime(literal,"%Y%m%d%H%M")
            if d.strftime("%Y%m%d%H%M")!=literal:
                return None
        else:
            scale={
                "epoch_s":1,"epoch_ms":1_000,"epoch_us":1_000_000,
                "epoch_ns":1_000_000_000}[candidate]
            # All raw integer bounds are converted to seconds and interpreted
            # as UTC instants, then displayed as Asia/Shanghai fixed UTC+8.
            # This establishes a plausible representation, NOT semantics.
            d=datetime.fromtimestamp(value/scale,tz=UTC8)
        return d.strftime("%Y-%m")
    except (KeyError,OverflowError,OSError,ValueError):
        return None


def _previous_safe(report):
    old=json.loads(AUDIT._path(report,True).read_text(encoding="utf-8"))
    if (type(old) is not dict or old.get("format")!=PREVIOUS.FORMAT
            or old.get("footer_only_no_row_data_loaded") is not True
            or old.get("sources_read_only") is not True
            or old.get("ready_for_full_market_mirror") is not False
            or old.get("licensed_parquet_to_h5_mapping_certified") is not False
            or old.get("amount_physical_unit_certified") is not False
            or old.get("volume_physical_unit_certified") is not False
            or type(old.get("periods")) is not dict
            or set(old["periods"])!=set(PERIODS)):
        raise ValueError("Requires existing successful 3-period v2 footer SAFE")
    for period in PERIODS:
        entry=old["periods"][period]
        if (type(entry) is not dict
                or entry.get("period")!=period
                or entry.get("parquet_metadata_only") is not True
                or entry.get("date_role_match_status")!="matched"
                or entry.get("date_arrow_storage_family")!="int64"
                or entry.get("date_raw_calendar_encoding_certified") is not False
                or entry.get("date_time_label_semantics_certified") is not False
                or type(entry.get("row_group_count")) is not int
                or not 1<=entry["row_group_count"]<=MAX_ROWGROUPS
                or type(entry.get("source_file_size_bytes")) is not int
                or type(entry.get("footer_bytes")) is not int
                or type(entry.get("total_source_rows_from_footer")) is not int):
            raise ValueError("Existing date int64 footer proof is missing")
    return old


def _file_month(relative):
    parts=Path(relative).parts
    if (len(parts)!=2
            or not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])\.parquet",parts[-1])):
        raise ValueError("Explicit monthly YYYY-MM.parquet filenames required")
    return parts[-1][:7]


def inspect_stats(path,period,month,previous,pq,pa):
    """Only metadata row group statistic minima/maxima, no column buffers."""
    before=PREVIOUS.footer_guard(path)
    if (before[0]!=previous["source_file_size_bytes"]
            or before[2]!=previous["footer_bytes"]):
        raise ValueError("Parquet source footer differs from v2 certified metadata")
    reader=None
    try:
        reader=pq.ParquetFile(str(path),memory_map=False,pre_buffer=False)
        names=[f.name for f in reader.schema_arrow
               if f.name.casefold() in PREVIOUS.ALIASES["date"]]
        if (len(names)!=1 or not pa.types.is_int64(
                reader.schema_arrow.field(names[0]).type)):
            raise ValueError("Unique int64 date field required")
        meta=reader.metadata
        if (meta is None or not 1<=meta.num_row_groups<=MAX_ROWGROUPS
                or meta.num_row_groups!=previous["row_group_count"]
                or meta.num_rows!=previous["total_source_rows_from_footer"]):
            raise ValueError("Parquet row group provenance changed")
        observed=0
        missing=0
        empty=0
        counter={name:0 for name in CANDIDATES}
        for idx in range(meta.num_row_groups):
            row_group=meta.row_group(idx)
            if row_group.num_rows==0:
                empty+=1
                continue
            columns=[row_group.column(i) for i in range(row_group.num_columns)
                     if row_group.column(i).path_in_schema==names[0]]
            if len(columns)!=1:
                raise ValueError("Date column absent or duplicated in row group")
            stats=columns[0].statistics
            if stats is None or not stats.has_min_max:
                missing+=1
                continue
            low,high=stats.min,stats.max
            if (type(low) is not int or type(high) is not int
                    or low>high):
                missing+=1
                continue
            observed+=1
            for candidate in CANDIDATES:
                if (_date_candidate_month(low,candidate)==month
                        and _date_candidate_month(high,candidate)==month):
                    counter[candidate]+=1
        plausible=[c for c in CANDIDATES if observed and counter[c]==observed]
        complete=(observed>0 and missing==0)
        # No candidate is certified from file footer alone: row group
        # boundaries are extrema, not per-bar timestamp / trading session.
        return {
            "period":period,
            "date_arrow_storage_family":"int64",
            "footer_only_no_date_rows_loaded":True,
            "nonempty_row_groups_with_valid_int64_minmax":observed,
            "nonempty_row_groups_without_valid_minmax":missing,
            "empty_row_groups":empty,
            "candidate_matching_row_groups":counter,
            "candidate_timebases_matching_all_observed_bounds":plausible,
            "full_nonempty_row_group_minmax_coverage":complete,
            "unique_epoch_ms_candidate_from_footer_only":(
                complete and plausible==["epoch_ms"]),
            "date_raw_calendar_encoding_certified":False,
            "date_time_label_semantics_certified":False,
            "independent_timezone_semantics_certified":False,
        }
    except Exception:
        # Do not disclose source absolute path or Arrow metadata strings.
        raise ValueError("Unable to evaluate approved Parquet date footer stats") from None
    finally:
        if reader is not None:
            reader.close()
        after=PREVIOUS.footer_guard(path)
        if before!=after:
            raise ValueError("Parquet source changed during date footer inspection")


def run(root,day_rel,min5_rel,min1_rel,previous_report,output,
        inspector=inspect_stats):
    dest=AUDIT._path(output,False)
    old=_previous_safe(previous_report)
    paths={
        "day":PREVIOUS.selected_file(root,day_rel,"day"),
        "5min":PREVIOUS.selected_file(root,min5_rel,"5min"),
        "1min":PREVIOUS.selected_file(root,min1_rel,"1min"),
    }
    rels={"day":day_rel,"5min":min5_rel,"1min":min1_rel}
    months={_file_month(rels[p]) for p in PERIODS}
    if len(months)!=1:
        raise ValueError("All three Parquet files must be from the same named month")
    month=next(iter(months))
    import pyarrow as pa
    import pyarrow.parquet as pq
    records={p:inspector(paths[p],p,month,old["periods"][p],pq,pa)
             for p in PERIODS}
    all_ms=all(records[p]["unique_epoch_ms_candidate_from_footer_only"]
               for p in PERIODS)
    safe={
        "format":FORMAT,
        "sample_month":month,
        "three_periods_int64_date_footer_checked":True,
        "periods":records,
        "all_three_periods_unique_epoch_ms_footer_candidate":bool(all_ms),
        "prior_query_code_epoch_ms_assumption_independently_proven":False,
        "date_raw_calendar_encoding_certified":False,
        "date_time_label_semantics_certified":False,
        "source_timezone_semantics_certified":False,
        "parquet_real_float64_to_h5_precision_certified":False,
        "physical_amount_unit_certified":False,
        "physical_volume_unit_certified":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
        "footer_only_no_market_rows_loaded":True,
        "original_market_files_modified":False,
        "h5_or_sqlite_opened":False,
        "source_filenames_or_paths_in_report":False,
        "no_raw_timestamp_extrema_in_report":True,
        "no_raw_ohlcva_in_report":True,
    }
    with dest.open("x",encoding="utf-8") as stream:
        json.dump(safe,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    return safe


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,required=True)
    parser.add_argument("--day-relative",type=Path,required=True)
    parser.add_argument("--min5-relative",type=Path,required=True)
    parser.add_argument("--min1-relative",type=Path,required=True)
    parser.add_argument("--previous-schema-safe",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--footer-date-stats-only",required=True,action="store_true")
    args=parser.parse_args(argv)
    try:
        safe=run(args.source_root,args.day_relative,
                 args.min5_relative,args.min1_relative,
                 args.previous_schema_safe,args.out)
        print("SAFE date int64 footer timebase:",args.out)
        print("Three period unique epoch_ms footer candidate:",
              safe["all_three_periods_unique_epoch_ms_footer_candidate"])
        print("Date encoding/time label certified: NO")
        print("Raw market bars read or changed: NO")
    except (ValueError,TypeError,OSError,ImportError,
            json.JSONDecodeError) as exc:
        parser.error(str(exc) if type(exc) is ValueError
                     else "Parquet footer timebase inspection failed")


if __name__=="__main__":
    main()
