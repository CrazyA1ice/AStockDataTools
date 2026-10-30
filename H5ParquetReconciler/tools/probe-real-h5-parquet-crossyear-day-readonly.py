#!/usr/bin/env python3
"""Conservative independent-month real daily Parquet/raw Hikyuu H5 hypotheses.

Only SH600000/SZ000001 on 2025-09-30 and 2026-08-24: 4 stock-days.
Reuses bounded per-month/day real Parquet reader, original raw H5 day reader,
and the same fixed candidate factor grid. NO production writes or native
C++ recheck on the two new dates. Missing data fail closed, never substituted.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

HELD=load("prior_real_daily_holdout_gate",
          "probe-real-h5-parquet-heldout-day-factors-readonly.py")
PAIR=HELD.PAIR
DAY=HELD.DAY
AUDIT=HELD.AUDIT

FORMAT="AStockDataTools real H5 Parquet two-month cross-year daily candidate factors v1"
SAMPLES=(("2025-09-30","day/2025.parquet"),
         ("2026-08-24","day/2026-08.parquet"))
MAX_YEAR_FOOTER_ROWS=1600000
MAX_YEAR_ROW_GROUPS=16
MAX_YEAR_SELECTED_ROW_GROUPS=2
MAX_YEAR_READ_ROWS=150000
MAX_SCANNED_TOTAL=300000
MAX_GROUPS_TOTAL=64
MIN_DISCOVERY_REFERENCE=6


def verified_sources(raw_safe,native_safe,heldout_safe):
    chain=HELD.verify_chain(raw_safe,native_safe)
    path=AUDIT._path(heldout_safe,True)
    data=path.read_bytes()
    if not 0<len(data)<=200000:
        raise ValueError("Cross-month prerequisite heldout SAFE too large or empty")
    try:
        previous=json.loads(data)
    except (ValueError,UnicodeError):
        raise ValueError("Cross-month prerequisite heldout SAFE invalid JSON") from None
    agg=previous.get("aggregate") if type(previous) is dict else None
    days=previous.get("per_holdout_date_diagnostic") if type(previous) is dict else None
    if (type(previous) is not dict or previous.get("format")!=HELD.FORMAT
            or previous.get("holdout_days")!=list(HELD.DAYS)
            or previous.get("prior_discovery_date_excluded")!="2026-09-30"
            or previous.get("observations_independent_of_discovery_date") is not True
            or previous.get("previous_SAFE_sha256")!=chain
            or previous.get("h5_raw_day_records_read")!=4
            or previous.get("original_parquet_or_h5_modified") is not False
            or previous.get("raw_ohlcva_or_h5_integer_values_exported") is not False
            or previous.get("native_decoder_consistency_not_retested_on_heldout_dates") is not True
            or previous.get("holdout_native_cpp_kdata_executed") is not False
            or previous.get("vendor_volume_physical_unit_certified") is not False
            or previous.get("vendor_amount_physical_unit_certified") is not False
            or previous.get("sample_factor_generalization_certified") is not False
            or previous.get("licensed_parquet_to_h5_mapping_certified") is not False
            or previous.get("ready_for_full_market_mirror") is not False
            or type(agg) is not dict
            or agg.get("heldout_stock_days_compared")!=4
            or agg.get("volume_candidate_factor100_matched")!=4
            or agg.get("amount_candidate_factor1000_matched")!=4
            or agg.get("nonzero_positive_pairs")!={"volume":4,"amount":4}
            or agg.get("zero_pairs")!={"volume":0,"amount":0}
            or agg.get("price_fields_within_tolerance")!={
                "open":4,"high":4,"low":4,"close":4}
            or type(days) is not dict
            or set(days)!=set(HELD.DAYS)
            or any(type(days[d]) is not dict
                   or days[d].get("stock_days_compared")!=2
                   or days[d].get("candidate_volume_raw_h5_times100_matched")!=2
                   or days[d].get("candidate_amount_raw_h5_times1000_matched")!=2
                   or days[d].get("quantity_positive_nonzero_pairs")!={
                       "volume":2,"amount":2}
                   for d in HELD.DAYS)):
        raise ValueError("Cross-month prerequisite heldout SAFE not qualified")
    return {**chain,"same_month_heldout":hashlib.sha256(data).hexdigest()}


def check_calendar():
    if (len(SAMPLES)!=2
            or SAMPLES!=(("2025-09-30","day/2025.parquet"),
                          ("2026-08-24","day/2026-08.parquet"))
            or any(day in HELD.DAYS or day==PAIR.DAY_DATE
                   for day,_ in SAMPLES)):
        raise ValueError("Cross-year selected sample dates or months changed")


def compare(days):
    if type(days) is not dict or set(days)!={d for d,_ in SAMPLES}:
        raise ValueError("Cross-year sample identities cannot change")
    results={}
    for name,_ in SAMPLES:
        entry=days[name]
        if type(entry) is not dict or set(entry)!={"parquet","h5"}:
            raise ValueError("Cross-year paired source fields invalid")
        results[name]=HELD.aggregated_day(entry["parquet"],entry["h5"])
    factor_names=("volume","amount")
    total={
        "stock_days_compared":4,
        "per_field_price_tolerance_matches":{
            field:sum(results[day]["price_h5_raw_div1000_within_0p005"][field]
                      for day,_ in SAMPLES)
            for field in ("open","high","low","close")},
        "volume_candidate_raw_h5_times100_matched":sum(
            results[day]["candidate_volume_raw_h5_times100_matched"]
            for day,_ in SAMPLES),
        "amount_candidate_raw_h5_times1000_matched":sum(
            results[day]["candidate_amount_raw_h5_times1000_matched"]
            for day,_ in SAMPLES),
        "nonzero_positive_pairs":{
            field:sum(results[day]["quantity_positive_nonzero_pairs"][field]
                      for day,_ in SAMPLES)
            for field in factor_names},
        "both_zero_pairs":{
            field:sum(results[day]["quantity_both_zero_pairs"][field]
                      for day,_ in SAMPLES)
            for field in factor_names},
        "one_zero_pairs":{
            field:sum(results[day]["quantity_one_zero_pairs"][field]
                      for day,_ in SAMPLES)
            for field in factor_names},
    }
    if any(sum(total[k][field] for k in (
            "nonzero_positive_pairs","both_zero_pairs","one_zero_pairs"))!=4
            for field in factor_names):
        raise ValueError("Cross-year quantity counts fail conservation")
    return results,total


def read_annual_2025_selected_day(path,day,pa,pq,pc):
    """Read ONLY rowgroups whose verified int64 ts bounds overlap 2025-09-30.

    A paid annual 2025 day file has >1.3 million total rows and must NOT be
    scanned by the old 150k monthly reader. The 12-group historical footer
    inventory motivated this explicit annual + per-group bounded adapter.
    Missing/unsafe stats, broad groups or duplicate keys fail closed.
    """
    if day!="2025-09-30" or path.name!="2025.parquet":
        raise ValueError("Only fixed 2025 annual Parquet day sample allowed")
    stamp=DAY.FOOTER.footer_guard(path)
    pf=None
    try:
        pf=pq.ParquetFile(str(path),memory_map=False,pre_buffer=False)
        schema=pf.schema_arrow
        if (not set(DAY.NEEDED).issubset(schema.names)
                or len(schema.names)>512
                or not pa.types.is_int64(schema.field("ts").type)
                or not pa.types.is_string(schema.field("symbol").type)
                or any(not pa.types.is_float64(schema.field(f).type)
                       for f in DAY.FIELDS)):
            raise ValueError("Annual Parquet day schema invalid")
        groups=pf.metadata.num_row_groups
        if not 1<=groups<=MAX_YEAR_ROW_GROUPS:
            raise ValueError("Annual rowgroup total exceeds budget")
        total=sum(pf.metadata.row_group(i).num_rows for i in range(groups))
        if not 1<=total<=MAX_YEAR_FOOTER_ROWS:
            raise ValueError("Annual source footer row count exceeds budget")
        low,high=DAY._range_ms(day)
        year_low=DAY._range_ms("2025-01-01")[0]
        year_high=DAY._range_ms("2025-12-31")[1]
        ts_index=schema.names.index("ts")
        selected=[]
        for i in range(groups):
            rg=pf.metadata.row_group(i)
            if rg.num_rows<1:
                raise ValueError("Annual empty rowgroup cannot be pruned safely")
            stats=rg.column(ts_index).statistics
            if (stats is None or not stats.has_min_max
                    or type(stats.min) is not int or type(stats.max) is not int
                    or stats.min>stats.max
                    or not year_low<=stats.min<year_high
                    or not year_low<=stats.max<year_high):
                raise ValueError("Missing or untrusted annual ts footer bounds")
            if stats.max>=low and stats.min<high:
                selected.append(i)
        if not 1<=len(selected)<=MAX_YEAR_SELECTED_ROW_GROUPS:
            raise ValueError("Annual source day has no bounded rowgroups")
        selected_rows=sum(pf.metadata.row_group(i).num_rows for i in selected)
        if not 1<=selected_rows<=MAX_YEAR_READ_ROWS:
            raise ValueError("Annual selected rowgroups exceed 150k scan budget")
        aliases={name:sym for sym,spellings in DAY.ALIASES.items()
                 for name in spellings}
        alias_values=pa.array(sorted(aliases),type=pa.string())
        found={}
        scanned=0
        for batch in pf.iter_batches(
                row_groups=selected,batch_size=16384,
                columns=list(DAY.NEEDED),use_threads=False):
            scanned+=batch.num_rows
            if scanned>MAX_YEAR_READ_ROWS:
                raise ValueError("Actual annual day scan exceeds 150k budget")
            columns={name:batch.column(i)
                     for i,name in enumerate(DAY.NEEDED)}
            mask=pc.and_(
                pc.is_in(columns["symbol"],value_set=alias_values),
                pc.and_(pc.greater_equal(columns["ts"],low),
                        pc.less(columns["ts"],high)))
            for item in batch.filter(mask).to_pylist():
                symbol=aliases.get(item["symbol"])
                if symbol is None or symbol in found:
                    raise ValueError("Annual selected stock-day missing identity/duplicated")
                if type(item["ts"]) is not int:
                    raise ValueError("Annual source timestamp invalid")
                record={field:item[field] for field in DAY.FIELDS}
                import math
                if any(type(v) is not float or not math.isfinite(v)
                       for v in record.values()):
                    raise ValueError("Annual source float64 invalid")
                found[symbol]=record
        if set(found)!=set(DAY.SYMBOLS):
            raise ValueError("Fixed annual target stock-days absent")
        return found,scanned,len(selected),total,groups
    except Exception:
        # No PyArrow errors or paid source paths are exposed in SAFE diagnostics.
        raise ValueError("Cannot safely inspect bounded annual 2025 day rowgroups") from None
    finally:
        if pf is not None:
            pf.close()
        if DAY.FOOTER.footer_guard(path)!=stamp:
            raise ValueError("Source annual Parquet file changed during read")


KEY_ONLY_FORMAT="AStockDataTools 2025 annual daily two-column key-only rowgroup probe v1"
MAX_YEAR_KEY_ROWS=1600000
MAX_YEAR_KEY_BATCH=16384


def qualified_annual_key_only_safe(path):
    """Prior SAFE is a *gate*, never a rowgroup locator or source authority.

    The last evidence intentionally did not store raw source bytes or group
    indexes. Always re-read all 2025 keys before opening any OHLCVA columns.
    """
    input_path=AUDIT._path(path,True)
    blob=input_path.read_bytes()
    if not 0<len(blob)<=200000:
        raise ValueError("2025 key-only SAFE missing/excessive")
    try:
        doc=json.loads(blob)
    except (ValueError,UnicodeError):
        raise ValueError("2025 key-only SAFE malformed") from None
    if (type(doc) is not dict or doc.get("format")!=KEY_ONLY_FORMAT
            or doc.get("target_day")!="2025-09-30"
            or doc.get("source_period")!="day"
            or doc.get("status")!="ready_for_bounded_price_group_read"
            or doc.get("last_phase")!="finished"
            or doc.get("matching_target_key_count")!=2
            or doc.get("possible_ohlcva_rowgroup_budget")!=2
            or doc.get("possible_ohlcva_row_budget")!=150000
            or doc.get("key_scan_budget_rows")!=MAX_YEAR_KEY_ROWS
            or type(doc.get("source_year_footer_rowgroups")) is not int
            or not 1<=doc["source_year_footer_rowgroups"]<=MAX_YEAR_ROW_GROUPS
            or type(doc.get("source_year_footer_rows")) is not int
            or not 1<=doc["source_year_footer_rows"]<=MAX_YEAR_KEY_ROWS
            or type(doc.get("key_only_rows_scanned")) is not int
            or doc["key_only_rows_scanned"]!=doc["source_year_footer_rows"]
            or type(doc.get("key_only_batches_scanned")) is not int
            or doc["key_only_batches_scanned"]<1
            or type(doc.get("selected_target_rowgroups")) is not int
            or not 1<=doc["selected_target_rowgroups"]<=MAX_YEAR_SELECTED_ROW_GROUPS
            or type(doc.get("selected_target_rowgroup_total_rows")) is not int
            or not 1<=doc["selected_target_rowgroup_total_rows"]<=MAX_YEAR_READ_ROWS
            or doc.get("ohlcva_rows_scanned")!=0
            or doc.get("ohlcva_columns_opened") is not False
            or doc.get("raw_h5_or_market_sqlite_opened") is not False
            or doc.get("real_native_cpp_invoked") is not False
            or doc.get("original_parquet_modified") is not False
            or doc.get("original_source_footer_unchanged") is not True
            or doc.get("raw_symbols_timestamps_ohlcva_or_paths_emitted") is not False
            or doc.get("licensed_parquet_to_h5_mapping_certified") is not False
            or doc.get("vendor_physical_units_certified") is not False
            or doc.get("ready_for_full_market_mirror") is not False):
        raise ValueError("2025 annual key-only prior SAFE not qualified")
    return doc,hashlib.sha256(blob).hexdigest()


def read_annual_2025_keylocated_day(path,day,pa,pq,pc,prior_key_safe):
    """Re-scan ONLY the annual ts/symbol keys before any 8-column K-line read.

    First scan <=1.6m two-column keys across <=16 groups, prove both fixed
    stock-day keys unique and reconstruct the exact selected group indexes.
    After independent comparison to the earlier SAFE, read <=2 selected
    groups / <=150k OHLCVA rows. Never trust rowgroup ids from prior output.
    """
    if day!="2025-09-30" or path.name!="2025.parquet":
        raise ValueError("Unexpected fixed annual stock-day")
    stamp=DAY.FOOTER.footer_guard(path)
    pf=None
    try:
        pf=pq.ParquetFile(str(path),memory_map=False,pre_buffer=False)
        schema=pf.schema_arrow
        if (len(schema.names)>512
                or not set(DAY.NEEDED).issubset(schema.names)
                or not pa.types.is_int64(schema.field("ts").type)
                or not pa.types.is_string(schema.field("symbol").type)
                or any(not pa.types.is_float64(schema.field(x).type)
                       for x in DAY.FIELDS)):
            raise ValueError("Unsupported exact annual OHLCVA schema")
        group_count=pf.metadata.num_row_groups
        if not 1<=group_count<=MAX_YEAR_ROW_GROUPS:
            raise ValueError("Annual group budget exceeded")
        footer_rows=sum(pf.metadata.row_group(i).num_rows
                        for i in range(group_count))
        if (not 1<=footer_rows<=MAX_YEAR_KEY_ROWS
                or any(pf.metadata.row_group(i).num_rows<=0
                       for i in range(group_count))):
            raise ValueError("Annual key-only row count budget exceeded")
        if (group_count!=prior_key_safe["source_year_footer_rowgroups"]
                or footer_rows!=prior_key_safe["source_year_footer_rows"]):
            raise ValueError("Annual key-only prior footer changed")
        low,high=DAY._range_ms(day)
        aliases={alias:symbol
                 for symbol,names in DAY.ALIASES.items()
                 for alias in names}
        needle=pa.array(sorted(aliases),type=pa.string())
        seen={symbol:0 for symbol in DAY.SYMBOLS}
        selected=set()
        key_rows=0
        key_batches=0
        for group in range(group_count):
            for batch in pf.iter_batches(
                    row_groups=[group],columns=["ts","symbol"],
                    batch_size=MAX_YEAR_KEY_BATCH,use_threads=False):
                key_rows+=batch.num_rows
                key_batches+=1
                if (not 0<batch.num_rows<=MAX_YEAR_KEY_BATCH
                        or key_rows>MAX_YEAR_KEY_ROWS
                        or batch.column(0).null_count
                        or batch.column(1).null_count):
                    raise ValueError("Annual key-only batch invalid")
                ts=batch.column(0)
                names=batch.column(1)
                wanted=pc.and_(
                    pc.and_(pc.greater_equal(ts,low),pc.less(ts,high)),
                    pc.is_in(names,value_set=needle))
                for item in batch.filter(wanted).to_pylist():
                    symbol=aliases.get(item["symbol"])
                    if symbol not in seen:
                        raise ValueError("Unexpected annual stock-day alias")
                    seen[symbol]+=1
                    selected.add(group)
        if (key_rows!=footer_rows
                or key_rows!=prior_key_safe["key_only_rows_scanned"]
                or key_batches!=prior_key_safe["key_only_batches_scanned"]
                or any(seen[s]!=1 for s in DAY.SYMBOLS)):
            raise ValueError("Annual key-only source or unique keys changed")
        selected=sorted(selected)
        selected_rows=sum(pf.metadata.row_group(i).num_rows
                          for i in selected)
        if (not 1<=len(selected)<=MAX_YEAR_SELECTED_ROW_GROUPS
                or not 1<=selected_rows<=MAX_YEAR_READ_ROWS
                or len(selected)!=prior_key_safe["selected_target_rowgroups"]
                or selected_rows!=prior_key_safe["selected_target_rowgroup_total_rows"]):
            raise ValueError("Annual selected price groups exceed or differ from prior SAFE")

        found={}
        price_rows=0
        for batch in pf.iter_batches(
                row_groups=selected,columns=list(DAY.NEEDED),
                batch_size=MAX_YEAR_KEY_BATCH,use_threads=False):
            price_rows+=batch.num_rows
            if price_rows>MAX_YEAR_READ_ROWS:
                raise ValueError("Actual OHLCVA scan exceeded 150k budget")
            fields={name:batch.column(i)
                    for i,name in enumerate(DAY.NEEDED)}
            wanted=pc.and_(
                pc.and_(pc.greater_equal(fields["ts"],low),
                        pc.less(fields["ts"],high)),
                pc.is_in(fields["symbol"],value_set=needle))
            for row in batch.filter(wanted).to_pylist():
                symbol=aliases.get(row["symbol"])
                if (symbol is None or symbol in found
                        or type(row["ts"]) is not int):
                    raise ValueError("Annual selected OHLCVA key mismatch")
                values={field:row[field] for field in DAY.FIELDS}
                import math
                if any(type(v) is not float or not math.isfinite(v)
                       for v in values.values()):
                    raise ValueError("Annual selected OHLCVA non-finite/invalid")
                found[symbol]=values
        if set(found)!=set(DAY.SYMBOLS) or price_rows!=selected_rows:
            raise ValueError("Annual OHLCVA keys or selected rows inconsistent")
        return found,price_rows,len(selected),footer_rows,group_count,key_rows,key_batches
    except Exception:
        # PyArrow exceptions can disclose paid-source paths or values.
        raise ValueError("Cannot safely inspect key-located annual daily rows") from None
    finally:
        if pf is not None:
            pf.close()
        if DAY.FOOTER.footer_guard(path)!=stamp:
            raise ValueError("Annual source file changed during key/price verification")


def run(parquet_root,h5_root,raw_safe,native_safe,heldout_safe,out,
        annual_key_only_safe=None):
    target=AUDIT._path(out,False)
    check_calendar()
    prior=verified_sources(raw_safe,native_safe,heldout_safe)
    previous_annual_key=None
    if annual_key_only_safe is not None:
        previous_annual_key,prior_key_sha=qualified_annual_key_only_safe(
            annual_key_only_safe)
        prior["annual_2025_key_only"]=prior_key_sha
    month_files={day:DAY.FOOTER.selected_file(
        parquet_root,path,"day") for day,path in SAMPLES}
    if len({p.resolve() for p in month_files.values()})!=len(SAMPLES):
        raise ValueError("Cross-year samples must be different Parquet monthly sources")
    file_stamps={day:DAY.FOOTER.footer_guard(p)
                 for day,p in month_files.items()}
    h5paths={symbol:PAIR._plain_h5_path(h5_root,symbol)
             for symbol in PAIR.SYMBOLS}
    h5stamps={symbol:(p.stat().st_size,p.stat().st_mtime_ns)
              for symbol,p in h5paths.items()}
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    import h5py
    import numpy as np
    scanned=0
    groups=0
    annual_source_total_rows_from_footer=0
    annual_source_rowgroups_from_footer=0
    annual_selected_rowgroups=0
    rechecked_annual_key_rows=0
    rechecked_annual_key_batches=0
    annual_2025_ohlcva_rows_scanned=0
    paired={}
    try:
        for day,path in month_files.items():
            if day=="2025-09-30":
                if previous_annual_key is not None:
                    (vals,n,g,annual_source_total_rows_from_footer,
                     annual_source_rowgroups_from_footer,
                     rechecked_annual_key_rows,rechecked_annual_key_batches)=(
                        read_annual_2025_keylocated_day(
                            path,day,pa,pq,pc,previous_annual_key))
                else:
                    vals,n,g,annual_source_total_rows_from_footer,annual_source_rowgroups_from_footer=(
                        read_annual_2025_selected_day(path,day,pa,pq,pc))
                annual_selected_rowgroups=g
                annual_2025_ohlcva_rows_scanned=n
            else:
                vals,n,g=DAY._read_bounded_daily(path,day,pa,pq,pc)
            scanned+=n
            groups+=g
            if scanned>MAX_SCANNED_TOTAL or groups>MAX_GROUPS_TOTAL:
                raise ValueError("Cross-year fixed source scan budget exceeded")
            h5={symbol:PAIR._read_single_h5(h5_root,symbol,day,h5py,np)
                for symbol in PAIR.SYMBOLS}
            paired[day]={"parquet":vals,"h5":h5}
        breakdown,aggregate=compare(paired)
    finally:
        if any(DAY.FOOTER.footer_guard(p)!=file_stamps[day]
               for day,p in month_files.items()):
            raise ValueError("Real Parquet file changed during cross-year analysis")
        if any((p.stat().st_size,p.stat().st_mtime_ns)!=h5stamps[s]
               for s,p in h5paths.items()):
            raise ValueError("Real H5 file changed during cross-year analysis")
    safe={
        "format":FORMAT,
        "fixed_crossyear_samples":[day for day,_ in SAMPLES],
        "independent_of_prior_2026_09_discovery_and_heldout_days":True,
        "symbols_sampled_count":2,
        "source_period":"day",
        "source_parquet_files_read":2,
        "source_parquet_layouts":{
            "2025":("annual_two_column_key_revalidated"
                    if previous_annual_key is not None
                    else "annual_footer_pruned"),
            "2026":"monthly"},
        "annual_2025_prior_key_only_safe_revalidated":previous_annual_key is not None,
        "annual_2025_key_only_rows_rechecked":rechecked_annual_key_rows,
        "annual_2025_key_only_batches_rechecked":rechecked_annual_key_batches,
        "annual_2025_ohlcva_rows_scanned":annual_2025_ohlcva_rows_scanned,
        "annual_2025_source_total_rows_from_footer":annual_source_total_rows_from_footer,
        "annual_2025_source_rowgroups_from_footer":annual_source_rowgroups_from_footer,
        "annual_2025_selected_rowgroups_scanned":annual_selected_rowgroups,
        "source_parquet_total_rows_scanned":scanned,
        "source_parquet_row_groups_scanned":groups,
        "raw_h5_day_records_read":4,
        "native_cpp_h5_decoding_on_crossyear_samples_executed":False,
        "previous_native_real_decode_was_only_2026_09_30":True,
        "tolerance_amount_volume_ratio_relative":"0.00001",
        "tolerance_price_absolute":"0.005",
        "parquet_float_approximately_equals_raw_h5_integer_times_factor":True,
        "per_sample_day":breakdown,
        "crossyear_aggregate":aggregate,
        "previous_safe_sha256":prior,
        "source_files_stat_or_footer_before_after_unchanged":True,
        "entire_market_source_files_sha256_checked":False,
        "source_files_modified":False,
        "market_sqlite_or_h5_writes_performed":False,
        "raw_ohlcva_or_native_integer_values_in_report":False,
        "raw_market_paths_or_individual_source_timestamps_in_report":False,
        "vendor_amount_physical_units_certified":False,
        "vendor_volume_physical_units_certified":False,
        "source_timestamp_semantics_certified":False,
        "universal_factor_across_time_or_periods_certified":False,
        "licensed_parquet_to_h5_mapping_certified":False,
        "ready_for_full_market_mirror":False,
    }
    with target.open("x",encoding="utf-8") as stream:
        json.dump(safe,stream,indent=2,sort_keys=True,ensure_ascii=False)
        stream.write("\n")
    return safe


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parquet-root",type=Path,required=True)
    p.add_argument("--h5-root",type=Path,required=True)
    p.add_argument("--prior-raw-safe",type=Path,required=True)
    p.add_argument("--prior-native-safe",type=Path,required=True)
    p.add_argument("--prior-heldout-safe",type=Path,required=True)
    p.add_argument("--prior-annual-key-only-safe",type=Path,
                   help="Pre-verified 2025 annual key-only SAFE; independently re-scan keys")
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-crossyear-days",required=True,action="store_true")
    args=p.parse_args(argv)
    try:
        result=run(args.parquet_root,args.h5_root,args.prior_raw_safe,
                   args.prior_native_safe,args.prior_heldout_safe,args.out,
                   annual_key_only_safe=args.prior_annual_key_only_safe)
    except (ValueError,TypeError,KeyError,OSError,ImportError,
            OverflowError,json.JSONDecodeError):
        p.error("Cross-year sampled real H5/Parquet verification refused; sources or SAFE incomplete")
    stats=result["crossyear_aggregate"]
    print("SAFE cross-year daily evidence:",args.out)
    print("Cross-year stock-days:",stats["stock_days_compared"])
    print("Volume raw H5 x100 matches:",stats["volume_candidate_raw_h5_times100_matched"])
    print("Amount raw H5 x1000 matches:",stats["amount_candidate_raw_h5_times1000_matched"])
    print("Original sources modified: NO")
    print("Vendor units or production conversion certified: NO")


if __name__=="__main__":
    main()
