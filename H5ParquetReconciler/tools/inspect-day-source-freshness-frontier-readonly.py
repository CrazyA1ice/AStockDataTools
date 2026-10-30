#!/usr/bin/env python3
"""Find observed day-data frontier: exact selected H5 tails + Parquet footer bounds.

A bounded, source-only, read-only diagnosis AFTER no post-snapshot stock-days.
H5 tail dates are the actual LAST positional record of each selected stock
(only bounded tail-order tested); Parquet footer max is an ALL-STOCK row-group
upper envelope, NOT proof of a specific stock's latest observed daily bar.
Neither operation opens licensed Parquet OHLCVA, changes production routes,
or makes an H5 monetary unit/mirror certification.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import date, datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools bounded original H5 and purchased day source frontier read-only v1"
MAX_FILES=128
MAX_ROW_GROUPS=20000
MAX_SYMBOLS=10
TAIL_LIMIT=8


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H5=load("day_source_frontier_h5_structural",
        "probe-hikyuu-native-day-h5-readonly.py")
META=load("day_source_frontier_parquet_footer",
          "inspect-h5-parquet-coverage-bounds.py")
CORE=H5.core


def report_path(out):
    p=Path(out)
    if (REPORTS.is_symlink() or p.is_symlink() or p.exists()
            or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve()):
        raise ValueError("New source-frontier SAFE must be in module reports/")
    return p.resolve()


def h5_datetime(key):
    if type(key) is not int or key<=0 or key%10000:
        raise ValueError("Invalid native H5 daily timestamp key")
    try:
        day=datetime.strptime(str(key//10000),"%Y%m%d").date()
    except ValueError:
        raise ValueError("Invalid H5 daily calendar label") from None
    return day.isoformat()


def pq_datetime(ms):
    if type(ms) is not int or ms<=0:
        raise ValueError("Invalid purchased daily timestamp footer")
    try:
        return datetime.fromtimestamp(ms/1000,tz=CORE.UTC8).date().isoformat()
    except (OverflowError,ValueError,OSError):
        raise ValueError("Invalid purchased daily timestamp footer") from None


def file_state(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or linked original data source")
    info=path.stat()
    return (int(info.st_size),int(info.st_mtime_ns))


def inspect_h5(root,symbols,year):
    import h5py
    paths=H5._market_sources(root,symbols)
    before={venue:file_state(path) for venue,path in paths.items()}
    info=[]
    for sym in symbols:
        market=sym[:2].lower()
        path=paths[market]
        with h5py.File(path,"r") as source:
            table=source.get("data")
            if not isinstance(table,h5py.Group):
                raise ValueError("Native day H5 /data group missing")
            ds=table.get(sym)
            if not isinstance(ds,h5py.Dataset) or ds.ndim!=1:
                raise ValueError("Selected H5 day stock dataset missing/invalid")
            layout=H5._schema(ds)
            if (not layout["expected_field_set"]
                    or not layout["integer_width_sign_compatible_with_h5record"]
                    or not layout["one_dimensional_compound_dataset"]):
                raise ValueError("Untrusted H5 day layout")
            count=len(ds)
            if count:
                start=max(0,count-TAIL_LIMIT)
                tail=[int(x) for x in ds[start:count]["datetime"]]
                dates=[h5_datetime(key) for key in tail]
                if dates!=sorted(set(dates)):
                    raise ValueError("H5 bounded tail day keys not strictly increasing")
                last=dates[-1]
            else:
                last=None
            info.append({
                "requested_stock_slot":len(info)+1,
                "market":market.upper(),
                "native_h5_dataset_rows":count,
                "h5_last_positional_record_day":last,
                "last_positional_record_in_requested_year":bool(
                    last is not None and last.startswith(str(year)+"-")),
                "bounded_tail_keys_increasing":True,
                "full_h5_history_sortedness_certified":False,
                "native_driver_compatibility_certified":False,
            })
    if {venue:file_state(path) for venue,path in paths.items()}!=before:
        raise ValueError("H5 source stat changed during frontier inspection")
    return info, before


def purchased_year_files(root,year):
    root=Path(root).resolve()
    purchased=root/"AllCycleAStockData"/"day"
    if (not purchased.is_dir() or purchased.is_symlink()
            or not (root/"AllCycleAStockData").is_dir()):
        raise ValueError("Purchased daily Parquet source folder missing")
    sources=CORE.year_files(root,"day",year)
    if not sources or len(sources)>MAX_FILES:
        raise ValueError("No matching purchased day year files or file budget exceeded")
    for source in sources:
        if (source.is_symlink() or not source.is_file()
                or not source.resolve().is_relative_to(purchased.resolve())):
            raise ValueError("Unsafe purchased daily Parquet source")
    return sources


def inspect_purchased(root,year):
    import pyarrow.parquet as pq
    paths=purchased_year_files(root,year)
    before={p:file_state(p) for p in paths}
    total=0
    usable=0
    unknown=0
    max_day=None
    min_day=None
    for source in paths:
        pf=pq.ParquetFile(source,memory_map=False,pre_buffer=False)
        try:
            if "ts" not in pf.schema_arrow.names:
                raise ValueError("Purchased daily source missing ts column")
            for index in range(pf.metadata.num_row_groups):
                total+=1
                if total>MAX_ROW_GROUPS:
                    raise ValueError("Purchased year footer group budget exceeded")
                group=pf.metadata.row_group(index)
                if group.num_rows==0:
                    continue
                bounds=META.parquet_rg_ts_range(group)
                if bounds is None:
                    unknown+=1
                    continue
                lo,hi=(pq_datetime(x) for x in bounds)
                if lo>hi:
                    raise ValueError("Inverted purchased footer calendar")
                usable+=1
                min_day=lo if min_day is None else min(min_day,lo)
                max_day=hi if max_day is None else max(max_day,hi)
        finally:
            pf.close()
    if {p:file_state(p) for p in paths}!=before:
        raise ValueError("Purchased source stat changed during footer inspection")
    return {
        "matching_year_source_files":len(paths),
        "row_group_footers_examined":total,
        "nonempty_row_groups_with_usable_ts_minmax":usable,
        "nonempty_row_groups_without_usable_ts_minmax":unknown,
        "purchased_footer_earliest_candidate_date":min_day,
        "purchased_footer_latest_candidate_date":max_day,
        "latest_is_row_group_all_stock_envelope_not_selected_stock_key":True,
        "latest_source_date_certified":False if unknown else bool(usable),
        "raw_purchased_parquet_ohlcva_rows_opened":False,
    },before


def state_digest(files, purchased_root):
    # Metadata-only digest across relative paths AND stat tuples: different
    # directories may have identical filenames. Still NOT a file-content hash.
    base=Path(purchased_root).resolve()
    rows=sorted((p.resolve().relative_to(base).as_posix(),*stat)
                for p,stat in files.items())
    return hashlib.sha256(json.dumps(rows,separators=(",",":")).encode()).hexdigest()


def inspect(root,symbols,year,out):
    safe=report_path(out)
    root=Path(root)
    if (type(year) is not int or not 2011<=year<=2100
            or type(symbols) not in (list,tuple)
            or not 1<=len(symbols)<=MAX_SYMBOLS
            or len(set(symbols))!=len(symbols)
            or any(type(sym) is not str or
                   CORE.symbol_id(sym)!=sym or
                   not CORE.is_a_share_candidate(sym,year)
                   for sym in symbols)):
        raise ValueError("Select 1..10 canonical A-share candidate stocks and 2011..2100 year")
    h5,hs=inspect_h5(root,symbols,year)
    purchased,ps=inspect_purchased(root,year)
    h5paths=H5._market_sources(root,symbols)
    pqpaths=purchased_year_files(root,year)
    if ({p:file_state(p) for p in h5paths.values()}!=
            {h5paths[m]:hs[m] for m in h5paths}
            or {p:file_state(p) for p in pqpaths}!=ps):
        raise ValueError("Original H5/PQ source metadata changed before publication")
    summary={
        "format":FORMAT,"status":"day_source_date_frontier_metadata_only",
        "source_year_requested":year,
        "selected_stock_count":len(symbols),
        "selected_original_h5_last_positional_days":h5,
        "purchased_day_year_footer":purchased,
        "observed_latest_selected_h5_tail_day":max(
            (item["h5_last_positional_record_day"] for item in h5
             if item["h5_last_positional_record_day"] is not None),default=None),
        "original_h5_market_files":len(hs),
        "original_h5_source_stat_only_sha256":hashlib.sha256(
            json.dumps(sorted((m,*v) for m,v in hs.items()),
                       separators=(",",":")).encode()).hexdigest(),
        "purchased_source_stat_only_sha256":state_digest(
            ps,Path(root).resolve()/"AllCycleAStockData"),
        "stat_checks_not_content_hashes":True,
        "selected_h5_tails_not_proof_of_full_history_sortedness":True,
        "purchased_footer_global_bound_not_stock_specific":True,
        "suppliers_last_successful_update_not_verified":True,
        "other_data_paths_or_newer_updater_outputs_not_searched":True,
        "no_full_market_coverage_or_trading_calendar_certified":True,
        "no_raw_ohlcva_or_stock_codes_in_safe":True,
        "original_market_files_modified":False,
        "private_active_pointers_read_or_modified":False,
        "production_query_route_modified":False,
        "ready_for_full_h5_mirror_or_automatic_backfill":False,
    }
    with safe.open("x",encoding="utf-8") as stream:
        json.dump(summary,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--symbols",nargs="+",required=True)
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-source-frontier",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=inspect(a.source_root,a.symbols,a.year,a.out)
        print("SAFE original market day frontier:",a.out)
        print("Selected H5 last tail day:",result[
            "observed_latest_selected_h5_tail_day"])
        print("Purchased year global footer latest candidate:",result[
            "purchased_day_year_footer"]["purchased_footer_latest_candidate_date"])
        print("Original H5 keys / purchased Parquet footers read: YES (read-only)")
        print("Original market files modified, production/private pointers touched: NO")
        print("No newer alternate supplier paths discovered by this inspection.")
    except (ValueError,TypeError,KeyError,OSError,OverflowError,
            ImportError,ModuleNotFoundError):
        p.error("Original day data source frontier refused; no market writes")


if __name__=="__main__":
    main()
