#!/usr/bin/env python3
"""Bounded local read-only queries from purchased A-share Parquet history.

Directly reads existing Parquet row groups: NO database import, no H5 fallback,
no unit conversion, no implicit 5m timestamp shift and no purchased bar export
unless the local user explicitly opts in to printing a few bars to the terminal.

Programmatic API query_bars() RETURNS original OHLCVA values locally. These
must never be pasted into repository reports or committed to Git.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "parquet_primary_query_validator",HERE/
    "validate-parquet-1min-to-5min.py")
validator=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)
CACHE_SPEC=importlib.util.spec_from_file_location(
    "parquet_primary_private_cache",HERE/"private-parquet-query-cache.py")
private_cache=importlib.util.module_from_spec(CACHE_SPEC)
CACHE_SPEC.loader.exec_module(private_cache)
core=validator.core
diagnose=validator.diagnose
PERIODS=("day","1min","5min")
NEEDED=tuple(core.NEEDED)
MAX_RANGE_DAYS=31


def request_dates(symbol, period, first, last, max_candidate_rows,
                  max_result_bars):
    if period not in PERIODS:
        raise ValueError("period must be one of day, 1min, 5min")
    start=date.fromisoformat(str(first))
    end=date.fromisoformat(str(last))
    if start>end or (end-start).days+1>MAX_RANGE_DAYS:
        raise ValueError("Query must be an inclusive window of 1..31 days")
    canonical=core.symbol_id(symbol)
    if canonical is None or canonical != symbol.upper():
        raise ValueError("Supply a canonical symbol like SH600000 or SZ000001")
    if any(not core.is_a_share_candidate(canonical, y)
           for y in range(start.year,end.year+1)):
        raise ValueError("This first-stage interface supports A-share candidate "
                         "symbols only; no B-shares or unverified BJ transitions")
    if (type(max_candidate_rows) is not int or
            not 1<=max_candidate_rows<=100000000):
        raise ValueError("max_candidate_rows must be in [1,100000000]")
    if (type(max_result_bars) is not int or
            not 1<=max_result_bars<=100000):
        raise ValueError("max_result_bars must be in [1,100000]")
    return canonical,start,end


def day_bounds(start,end):
    left=datetime(start.year,start.month,start.day,tzinfo=core.UTC8)
    after=end+timedelta(days=1)
    right=datetime(after.year,after.month,after.day,tzinfo=core.UTC8)
    return int(left.timestamp()*1000),int(right.timestamp()*1000)


def monthly_filename_overlaps_query(path, period_directory, first, last):
    """Identify root-level YYYY-MM.parquet filenames as month candidates.

    The caller MUST confirm nonoverlap from all actual Parquet RowGroup footer
    timestamps before skipping. Filename alone is NEVER sufficient evidence.
    This only shortens the per-file metadata plan, not within-month K-line IO.
    """
    if path.parent != period_directory or path.suffix.lower() != ".parquet":
        return True
    name = path.stem
    if len(name) != 7 or name[4] != "-" or not (
            name[:4].isascii() and name[:4].isdigit() and
            name[5:].isascii() and name[5:].isdigit()):
        return True
    year, month = int(name[:4]), int(name[5:])
    if not (1900 <= year <= 9998 and 1 <= month <= 12):
        return True
    month_first = date(year, month, 1)
    month_last = (date(year+1, 1, 1) if month == 12
                  else date(year, month+1, 1)) - timedelta(days=1)
    return month_first <= last and month_last >= first


def prepare_query(root,symbol,period,start,end,max_candidate_rows=30000000,
                  max_result_bars=25000):
    """Preflight ALL source rowgroup costs before any licensed bar value read."""
    import pyarrow.parquet as pq
    symbol,start,end=request_dates(
        symbol,period,start,end,max_candidate_rows,max_result_bars)
    root=Path(root).resolve()
    purchased=root/"AllCycleAStockData"
    if not root.is_dir() or not purchased.is_dir():
        raise ValueError("Purchased Parquet root not found under data root")
    aliases=set(diagnose.source_spellings(symbol))
    low_ms,high_ms=day_bounds(start,end)
    pending=[]
    metadata=Counter()
    sources=[]
    period_directory=purchased/period
    for year in range(start.year,end.year+1):
        for path in core.year_files(root,period,year):
            metadata["source_files_discovered_for_year"]+=1
            if path.is_symlink() or not path.is_file() or not (
                    path.resolve().is_relative_to(purchased.resolve())):
                raise ValueError("Unsafe Parquet source path: "+str(path.name))
            pf=pq.ParquetFile(str(path))
            metadata["source_file_footers_opened"]+=1
            if not set(NEEDED).issubset(pf.schema_arrow.names):
                raise ValueError("Missing Parquet OHLCVA keys: "+path.name)
            if not monthly_filename_overlaps_query(
                    path, period_directory, start, end):
                # File names alone MUST NOT hide mislabeled data. Inspect
                # ALL RowGroup timestamp envelopes in the footer first;
                # unknown/malformed statistics fail OPEN for scanning.
                can_skip=all(not core.row_group_overlaps_timestamp(
                    pf.metadata.row_group(i), low_ms, high_ms)
                    for i in range(pf.metadata.num_row_groups))
                if can_skip:
                    metadata["source_files_skipped_nonoverlapping_named_month"]+=1
                    continue
                metadata["month_filename_disagrees_with_footer_query_range"]+=1
            metadata["source_files_examined"]+=1
            st=path.stat()
            sources.append({"relative_path":path.relative_to(root).as_posix(),
                            "size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns})
            for rg_id in range(pf.metadata.num_row_groups):
                metadata["row_groups_examined"]+=1
                rg=pf.metadata.row_group(rg_id)
                if not core.row_group_overlaps_timestamp(
                        rg,low_ms,high_ms):
                    metadata["row_groups_pruned_by_time"]+=1
                    continue
                if not diagnose.might_contain_symbols(rg,aliases):
                    metadata["row_groups_pruned_by_symbol"]+=1
                    continue
                metadata["candidate_source_rows_upper_bound"]+=rg.num_rows
                pending.append((path,pf,rg_id))
    if metadata["candidate_source_rows_upper_bound"]>max_candidate_rows:
        raise ValueError(
            "Query candidate RowGroups need "+
            f"{metadata['candidate_source_rows_upper_bound']:,} rows; "
            f"exceeds --max-candidate-rows {max_candidate_rows:,}. "
            "No paid OHLCVA bars were read.")
    return {
        "root":root,"symbol":symbol,"period":period,"start":start,
        "end":end,"aliases":aliases,"low_ms":low_ms,"high_ms":high_ms,
        "pending":pending,"metadata":metadata,"sources":sources,
        "max_result_bars":max_result_bars,
        "time_policy":("daily_source_day_with_raw_intraday_clock"
                       if period=="day" else
                       "one_minute_end_label_with_separate_0930_opening_key"
                       if period=="1min" else
                       "five_minute_start_label"),
    }


def query_bars(root,symbol,period,start,end,max_candidate_rows=30000000,
               max_result_bars=25000,local_cache=False):
    """Return locally requested actual bars plus safe metadata.

    All bar data stay in Python memory and are never written to a file by this
    function. Empty result only means no matching keys found in named sources.
    Duplicate requested symbol+source timestamp and bad rows fail closed.
    """
    # Explicit opt-in: storing paid OHLCVA has a local privacy/storage
    # cost, and is OFF by default. Warm repeats avoid Parquet bar reads.
    signature_before=None
    cache_file=None
    if local_cache:
        canonical,first,last=request_dates(
            symbol,period,start,end,max_candidate_rows,max_result_bars)
        private_cache.ensure_private_dir()
        cache_file=private_cache.cache_target(
            root,canonical,period,first,last,
            max_candidate_rows,max_result_bars)
        signature_before=private_cache.source_signature(
            root,period,first,last,core)
        hit=private_cache.read_cache(
            cache_file,signature_before,canonical,period,first,last,
            max_result_bars)
        if hit is not None:
            return hit
    context=prepare_query(
        root,symbol,period,start,end,max_candidate_rows,max_result_bars)
    import pyarrow as pa
    import pyarrow.compute as pc
    aliases_pa=pa.array(sorted(context["aliases"]),type=pa.string())
    values={}
    meta=context["metadata"]
    provenance={}
    for path,pf,group in context["pending"]:
        for batch in pf.iter_batches(
                row_groups=[group],batch_size=65536,
                columns=list(NEEDED),use_threads=True):
            meta["source_rows_scanned"]+=batch.num_rows
            mask=pc.and_(pc.is_in(batch.column(1),value_set=aliases_pa),
                        pc.and_(
                            pc.greater_equal(batch.column(0),context["low_ms"]),
                            pc.less(batch.column(0),context["high_ms"])))
            for item in batch.filter(mask).to_pylist():
                if core.symbol_id(item["symbol"]) != context["symbol"]:
                    continue
                ts=item["ts"]
                if type(ts) is not int or ts%60000:
                    raise ValueError("Non-integer/unaligned source timestamp")
                raw=datetime.fromtimestamp(ts/1000,tz=core.UTC8)
                if raw.date()<context["start"] or raw.date()>context["end"]:
                    continue
                row=tuple(float(item[f]) for f in validator.FIELDS)
                if not all(math.isfinite(v) for v in row):
                    raise ValueError("Non-finite OHLCVA source value")
                if row[1]<max(row[0],row[2],row[3])-1e-7 or (
                        row[2]>min(row[0],row[1],row[3])+1e-7) or (
                        row[4]<0 or row[5]<0):
                    raise ValueError("Invalid source OHLCVA geometry")
                if ts in values:
                    raise ValueError("Duplicate source timestamp for selected stock")
                if len(values)>=context["max_result_bars"]:
                    raise ValueError(
                        "Selected rows exceed --max-result-bars: "
                        +str(context["max_result_bars"]))
                values[ts]=row
                provenance[ts]=(path.relative_to(context["root"]).as_posix(),
                                group)
                meta["matching_bars"]+=1
    bars=[]
    for ts in sorted(values):
        dt=datetime.fromtimestamp(ts/1000,tz=core.UTC8)
        values6=values[ts]
        src,rg_id=provenance[ts]
        bars.append({
            "symbol":context["symbol"],"period":context["period"],
            "trading_date":dt.date().isoformat(),
            "source_timestamp_ms":ts,
            "source_beijing_time":dt.strftime("%Y-%m-%d %H:%M"),
            "normalized_query_label":(
                dt.date().isoformat() if context["period"]=="day"
                else dt.strftime("%Y-%m-%d %H:%M")),
            "source_file_relative_path":src,"source_row_group":rg_id,
            **dict(zip(validator.FIELDS,values6))
        })
    # Summaries contain metadata only; no raw market price/volume values.
    safe_summary={
        "format":"AStockDataTools purchased Parquet bounded query summary v1",
        "symbol":context["symbol"],"period":context["period"],
        "from_date":context["start"].isoformat(),
        "to_date":context["end"].isoformat(),
        "source_files_examined":meta["source_files_examined"],
        "source_file_footers_opened":meta["source_file_footers_opened"],
        "source_files_discovered_for_year":meta[
            "source_files_discovered_for_year"],
        "source_files_skipped_nonoverlapping_named_month":meta[
            "source_files_skipped_nonoverlapping_named_month"],
        "month_filename_disagrees_with_footer_query_range":meta[
            "month_filename_disagrees_with_footer_query_range"],
        "file_month_filter_requires_footer_proof_of_nonoverlap":True,
        "candidate_row_groups":len(context["pending"]),
        "candidate_source_rows_upper_bound":meta[
            "candidate_source_rows_upper_bound"],
        "source_rows_scanned":meta["source_rows_scanned"],
        "matching_bar_count":len(bars),
        "source_rows_read_per_returned_bar": (
            round(meta["source_rows_scanned"]/len(bars),3) if bars else None),
        "record_level_scan_amplification_is_observed_not_a_speedup":True,
        "first_matching_raw_beijing_label": (
            bars[0]["source_beijing_time"] if bars else None),
        "last_matching_raw_beijing_label": (
            bars[-1]["source_beijing_time"] if bars else None),
        "source_file_stat_provenance":context["sources"],
        "time_label_policy":context["time_policy"],
        "source_quantity_unit_rescaling_applied":False,
        "no_h5_read":True,"source_market_files_modified":False,
        "no_automatic_gaps_fill":True,"no_source_market_truth_certification":True,
        "no_raw_ohlcva_in_safe_summary":True,
        "query_delivery":"parquet_source_scan",
        "source_rows_scanned_this_invocation":meta["source_rows_scanned"],
        "source_file_footers_opened_this_invocation":meta[
            "source_file_footers_opened"],
        "local_cache_used":False,
    }
    result={"bars":bars,"safe_summary":safe_summary}
    if local_cache:
        signature_after=private_cache.source_signature(
            root,context["period"],context["start"],context["end"],core)
        if signature_after!=signature_before:
            raise ValueError("Source files changed during query; will not cache")
        private_cache.write_cache(cache_file,signature_before,result)
        safe_summary["private_cache_contains_licensed_ohlcva"]=True
        safe_summary["local_private_cache_written"]=True
        safe_summary[
            "local_cache_validated_by_source_stat_only_not_content_hash"]=True
        safe_summary["local_cache_source_file_count"]=signature_before[
            "manifest_file_count"]
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root",type=Path)
    ap.add_argument("--symbol",required=True)
    ap.add_argument("--period",choices=PERIODS,required=True)
    ap.add_argument("--from-date",required=True)
    ap.add_argument("--to-date",required=True)
    ap.add_argument("--max-candidate-rows",type=int,default=30000000)
    ap.add_argument("--max-result-bars",type=int,default=25000)
    ap.add_argument("--local-cache",action="store_true",
                    help="EXPLICIT opt-in: store selected licensed OHLCVA "
                         "locally under module work/ (gitignored), and reuse "
                         "when source-file sizes/mtimes match; off by default")
    ap.add_argument("--show-first-bars",type=int,default=0,
                    help="Explicitly show at most 10 licensed OHLCVA bars "
                         "in LOCAL terminal ONLY; default prints no prices")
    ap.add_argument("--out",type=Path,required=True,
                    help="Only the SAFE summary JSON is saved under module reports")
    ap.add_argument("--read-only",action="store_true",required=True)
    args=ap.parse_args(argv)
    try:
        if not 0<=args.show_first_bars<=10:
            raise ValueError("--show-first-bars must be 0..10")
        out,scratch=core.resolve_module_artifact_paths(args.out)
        root,_,_=core.resolve_safe_paths(args.root,out,scratch)
        if (out.suffix.lower()!=".json" or out.exists()
                or not out.is_relative_to((HERE.parent/"reports").resolve())):
            raise ValueError("Use NEW summary JSON inside module reports/")
        result=query_bars(root,args.symbol,args.period,args.from_date,
                          args.to_date,args.max_candidate_rows,
                          args.max_result_bars,local_cache=args.local_cache)
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as fh:
            json.dump(result["safe_summary"],fh,indent=2,
                      ensure_ascii=False)
            fh.write("\n")
        print("Saved bounded Parquet query SAFE summary:",out)
        print("Matching bars:",len(result["bars"]))
        if args.show_first_bars:
            print("LOCAL OHLCVA OUTPUT: Do not commit or share licensed data")
            for bar in result["bars"][:args.show_first_bars]:
                print(json.dumps(bar,ensure_ascii=False))
    except (ValueError,TypeError,OSError,OverflowError,
            ModuleNotFoundError) as e:
        ap.error(str(e))


if __name__=="__main__":
    main()
