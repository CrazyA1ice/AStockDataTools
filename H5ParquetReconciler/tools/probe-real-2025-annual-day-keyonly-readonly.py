#!/usr/bin/env python3
"""Bounded 2025 annual Parquet key-only probe, no OHLCVA or real H5 reads.

The 2025 annual file has rowgroup timestamp ranges that all overlap one day;
metadata-only pruning cannot find target stock-days. This scans exclusively
int64 "ts" and string "symbol" in <=16384-row batches, with a 1.6m key-row
budget. It does NOT read a single price, amount or volume column.

The older 150k OHLCVA rowgroup budget remains INTACT. A key-only scan is
different and explicitly accounted for in the SAFE report. No source writes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

T=load("read_only_crossyear_prior_gate",
       "probe-real-h5-parquet-crossyear-day-readonly.py")
AUDIT=T.AUDIT
FORMAT="AStockDataTools 2025 annual daily two-column key-only rowgroup probe v1"
DAY="2025-09-30"
REL="day/2025.parquet"
MAX_KEY_ROWS=1600000
MAX_GROUPS=16
MAX_BATCH=16384
MAX_PRICE_GROUPS=2
MAX_PRICE_ROWS=150000
PHASES=frozenset((
    "prior_safe_chain","source_file_selection","source_parquet_footer",
    "annual_key_schema","annual_key_footer_budget","annual_key_scan",
    "target_key_uniqueness","target_price_rowgroup_budget",
    "source_file_unchanged","finished",
))
STATUSES=frozenset((
    "blocked","key_source_invalid","key_scan_invalid","no_target_keys",
    "duplicate_target_keys","selected_price_group_count_exceeds_budget",
    "selected_price_rows_exceed_budget",
    "ready_for_bounded_price_group_read",
))


def keyprobe(root,raw_safe,native_safe,heldout_safe,out):
    target=AUDIT._path(out,False)
    report={
        "format":FORMAT,
        "target_day":DAY,
        "source_period":"day",
        "status":"blocked",
        "last_phase":"prior_safe_chain",
        "source_year_footer_rowgroups":None,
        "source_year_footer_rows":None,
        "key_only_rows_scanned":0,
        "key_only_batches_scanned":0,
        "matching_target_key_count":0,
        "selected_target_rowgroups":0,
        "selected_target_rowgroup_total_rows":0,
        "key_scan_budget_rows":MAX_KEY_ROWS,
        "possible_ohlcva_rowgroup_budget":MAX_PRICE_GROUPS,
        "possible_ohlcva_row_budget":MAX_PRICE_ROWS,
        "ohlcva_rows_scanned":0,
        "ohlcva_columns_opened":False,
        "raw_h5_or_market_sqlite_opened":False,
        "real_native_cpp_invoked":False,
        "original_parquet_modified":False,
        "original_source_footer_unchanged":False,
        "raw_symbols_timestamps_ohlcva_or_paths_emitted":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "vendor_physical_units_certified":False,
        "ready_for_full_market_mirror":False,
    }
    path=None
    stamp=None
    try:
        T.check_calendar()
        T.verified_sources(raw_safe,native_safe,heldout_safe)
        report["last_phase"]="source_file_selection"
        path=T.DAY.FOOTER.selected_file(root,REL,"day")
        report["last_phase"]="source_parquet_footer"
        stamp=T.DAY.FOOTER.footer_guard(path)
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
        pf=None
        try:
            pf=pq.ParquetFile(str(path),memory_map=False,pre_buffer=False)
            report["last_phase"]="annual_key_schema"
            schema=pf.schema_arrow
            if (len(schema.names)>512
                    or "ts" not in schema.names or "symbol" not in schema.names
                    or not pa.types.is_int64(schema.field("ts").type)
                    or not pa.types.is_string(schema.field("symbol").type)):
                report["status"]="key_source_invalid"
                raise ValueError("invalid key-only schema")
            report["last_phase"]="annual_key_footer_budget"
            count=pf.metadata.num_row_groups
            if not 1<=count<=MAX_GROUPS:
                report["status"]="key_source_invalid"
                raise ValueError("annual group budget")
            numrows=sum(pf.metadata.row_group(i).num_rows for i in range(count))
            if (not 1<=numrows<=MAX_KEY_ROWS
                    or any(pf.metadata.row_group(i).num_rows<=0
                           for i in range(count))):
                report["status"]="key_source_invalid"
                raise ValueError("annual key-row budget")
            report["source_year_footer_rowgroups"]=count
            report["source_year_footer_rows"]=numrows
            low,high=T.DAY._range_ms(DAY)
            aliases={spelling for spellings in T.DAY.ALIASES.values()
                     for spelling in spellings}
            to_canonical={name:symbol
                          for symbol,spellings in T.DAY.ALIASES.items()
                          for name in spellings}
            needle=pa.array(sorted(aliases),type=pa.string())
            matched={symbol:0 for symbol in T.DAY.SYMBOLS}
            chosen=set()
            report["last_phase"]="annual_key_scan"
            for group in range(count):
                for batch in pf.iter_batches(row_groups=[group],
                        columns=["ts","symbol"],batch_size=MAX_BATCH,
                        use_threads=False):
                    report["key_only_rows_scanned"]+=batch.num_rows
                    report["key_only_batches_scanned"]+=1
                    if (report["key_only_rows_scanned"]>MAX_KEY_ROWS
                            or batch.num_rows>MAX_BATCH
                            or batch.column(0).null_count
                            or batch.column(1).null_count):
                        report["status"]="key_scan_invalid"
                        raise ValueError("invalid bounded key-only scan")
                    ts=batch.column(0)
                    names=batch.column(1)
                    wanted=pc.and_(
                        pc.and_(pc.greater_equal(ts,low),pc.less(ts,high)),
                        pc.is_in(names,value_set=needle))
                    for item in batch.filter(wanted).to_pylist():
                        symbol=to_canonical.get(item["symbol"])
                        if symbol is None:
                            report["status"]="key_scan_invalid"
                            raise ValueError("unexpected alias in key scan")
                        matched[symbol]+=1
                        chosen.add(group)
            if report["key_only_rows_scanned"]!=numrows:
                report["status"]="key_scan_invalid"
                raise ValueError("key-only row count differs from footer")
            report["matching_target_key_count"]=sum(matched.values())
            report["selected_target_rowgroups"]=len(chosen)
            report["selected_target_rowgroup_total_rows"]=sum(
                pf.metadata.row_group(i).num_rows for i in chosen)
            report["last_phase"]="target_key_uniqueness"
            if any(val>1 for val in matched.values()):
                report["status"]="duplicate_target_keys"
            elif any(val!=1 for val in matched.values()):
                report["status"]="no_target_keys"
            else:
                report["last_phase"]="target_price_rowgroup_budget"
                if len(chosen)>MAX_PRICE_GROUPS:
                    report["status"]="selected_price_group_count_exceeds_budget"
                elif report["selected_target_rowgroup_total_rows"]>MAX_PRICE_ROWS:
                    report["status"]="selected_price_rows_exceed_budget"
                else:
                    report["status"]="ready_for_bounded_price_group_read"
            report["last_phase"]="finished"
        finally:
            if pf is not None:
                pf.close()
    except Exception:
        # Never echo vendor/HDF5/PyArrow errors: they can include local paths.
        # The stage and pre-approved status are the only observable detail.
        if report["status"] not in STATUSES:
            report["status"]="blocked"
    finally:
        if path is not None and stamp is not None:
            try:
                report["original_source_footer_unchanged"]=(
                    T.DAY.FOOTER.footer_guard(path)==stamp)
            except Exception:
                report["original_source_footer_unchanged"]=False
            if not report["original_source_footer_unchanged"]:
                report["status"]="blocked"
                report["last_phase"]="source_file_unchanged"
        with target.open("x",encoding="utf-8") as f:
            json.dump(report,f,ensure_ascii=False,indent=2,sort_keys=True)
            f.write("\n")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parquet-root",required=True,type=Path)
    p.add_argument("--prior-raw-safe",required=True,type=Path)
    p.add_argument("--prior-native-safe",required=True,type=Path)
    p.add_argument("--prior-heldout-safe",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--key-only-read-2025-annual",required=True,action="store_true")
    a=p.parse_args(argv)
    try:
        report=keyprobe(a.parquet_root,a.prior_raw_safe,a.prior_native_safe,
                        a.prior_heldout_safe,a.out)
    except Exception:
        p.error("Cannot create privacy-safe annual Parquet key-only evidence")
    print("SAFE 2025 annual key-only evidence:",a.out)
    print("Status:",report["status"])
    print("Key-only rows scanned:",report["key_only_rows_scanned"])
    print("Selected rowgroups:",report["selected_target_rowgroups"])
    print("Potential OHLCVA rowgroup rows:",report["selected_target_rowgroup_total_rows"])
    print("No OHLCVA/H5 read, no user market file written.")


if __name__=="__main__":
    main()
