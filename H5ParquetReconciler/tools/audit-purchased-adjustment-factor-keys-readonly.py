#!/usr/bin/env python3
"""Bounded original purchased HFQ factor *key and value health* audit.

Reads only original (symbol,d,hfq_factor) factor columns, NEVER price/volume
OHLCVA K-lines or other purchased periods. Reports aggregate dates/counts only,
never ticker identities or individual factor values. 'hfq' is a source column
name, NOT certification of factor direction/base date/corporate actions.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
MAX_ROWS=2000000
MAX_YEARS=160


def _load():
    spec=importlib.util.spec_from_file_location(
        "existing_original_factor_parquet_metadata_gate",
        HERE/"inspect-purchased-adjustment-factor-parquet-schema-readonly.py")
    x=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(x)
    return x


SOURCE=_load()
COLUMNS=("symbol","d","hfq_factor")


def audit(root,*,max_rows=MAX_ROWS):
    import pyarrow as pa
    import pyarrow.parquet as pq

    if type(max_rows) is not int or not 1<=max_rows<=MAX_ROWS:
        raise ValueError("Original adjustment factor scan requires bounded row budget")
    root=Path(root)
    metadata=SOURCE.inspect(root)
    if metadata["source_footer_rows"]>max_rows:
        raise ValueError("Factor original source footer rows exceed bounded read budget")
    folder=root/"AllCycleAStockData"/SOURCE.LABEL
    files=sorted(folder.rglob("*.parquet"))
    if len(files)!=metadata["source_files"]:
        raise RuntimeError("Factor source file inventory changed before key scan")
    before={str(p):(p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ino)
            for p in files}
    counts=Counter()
    by_year=Counter()
    symbols=set()
    all_valid_raw_symbols=set()
    null_date_symbols=set()
    other_invalid_date_symbols=set()
    null_date_count_by_symbol=Counter()
    keys=set()
    dates=[]
    decoded=0
    for source in files:
        with pq.ParquetFile(source,memory_map=False,pre_buffer=False) as parquet:
            schema=parquet.schema_arrow
            for name in COLUMNS:
                if name not in schema.names:
                    raise ValueError("Missing required original factor column: "+name)
            if (not pa.types.is_string(schema.field("symbol").type)
                    or not pa.types.is_date32(schema.field("d").type)
                    or not pa.types.is_float64(schema.field("hfq_factor").type)):
                raise ValueError("Unexpected original factor column type; no factor interpretation")
            for batch in parquet.iter_batches(
                    batch_size=32768,columns=list(COLUMNS),use_threads=False):
                decoded+=batch.num_rows
                if decoded>max_rows:
                    raise ValueError("Original factor source scan exceeded row budget")
                names,days,factors=(
                    batch.column(i).to_pylist() for i in range(3))
                for symbol,day,factor in zip(names,days,factors):
                    counts["rows"]+=1
                    # Classify ALL factors before filtering invalid symbol/date.
                    # The original reader skipped 5499 invalid-date rows;
                    # a zero anomaly count therefore only applied to 62939.
                    if factor is None or not isinstance(factor,(int,float)):
                        counts["null_or_nonnumeric_factors"]+=1
                    elif not math.isfinite(float(factor)):
                        counts["nonfinite_factors"]+=1
                    elif float(factor)<=0:
                        counts["nonpositive_factors"]+=1
                    elif float(factor)==1:
                        counts["positive_factor_equal_one_rows"]+=1
                    else:
                        counts["positive_factor_not_one_rows"]+=1
                    if (not isinstance(symbol,str) or not symbol.strip()
                            or len(symbol)>128):
                        counts["null_or_invalid_symbols"]+=1
                        continue
                    all_valid_raw_symbols.add(symbol)
                    if day is None:
                        counts["null_or_invalid_dates"]+=1
                        counts["null_date_rows"]+=1
                        null_date_symbols.add(symbol)
                        null_date_count_by_symbol[symbol]+=1
                        continue
                    if type(day) is not date or not 1990<=day.year<=2100:
                        counts["null_or_invalid_dates"]+=1
                        counts["non_null_invalid_date_rows"]+=1
                        other_invalid_date_symbols.add(symbol)
                        continue
                    symbols.add(symbol)
                    key=(symbol,day)
                    if key in keys:
                        counts["duplicate_exact_symbol_day_keys"]+=1
                    keys.add(key)
                    by_year[str(day.year)]+=1
                    dates.append(day)
    if (decoded!=metadata["source_footer_rows"]
            or counts["rows"]!=metadata["source_footer_rows"]):
        raise ValueError("Factor footer vs bounded key/value rows mismatch")
    factor_health_buckets=(
        "null_or_nonnumeric_factors","nonfinite_factors",
        "nonpositive_factors","positive_factor_equal_one_rows",
        "positive_factor_not_one_rows")
    if (sum(counts[name] for name in factor_health_buckets)!=decoded
            or counts["null_or_invalid_dates"]!=
            counts["null_date_rows"]+counts["non_null_invalid_date_rows"]
            or len(keys)+counts["duplicate_exact_symbol_day_keys"]!=len(dates)):
        raise ValueError("Factor complete-source health/date/key conservation failed")
    after={str(p):(p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ino)
           for p in files}
    if before!=after:
        raise RuntimeError("Original factor parquet source stat changed during scan")
    if len(by_year)>MAX_YEARS:
        raise ValueError("Factor original calendar exceeds bounded year count")
    return {
        "status":"original_purchased_hfq_factor_key_coverage_and_value_health_readonly_not_certified",
        "original_factor_file_count":len(files),
        "rows_from_footer":metadata["source_footer_rows"],
        "factor_rows_examined":decoded,
        "distinct_raw_source_symbols":len(symbols),
        "distinct_symbols_with_any_valid_symbol_field":len(all_valid_raw_symbols),
        "distinct_symbols_with_null_date_rows":len(null_date_symbols),
        "symbols_with_multiple_null_date_rows":sum(
            1 for n in null_date_count_by_symbol.values() if n>1),
        "symbols_with_both_null_and_valid_dates":len(
            null_date_symbols & symbols),
        "symbols_with_only_null_dates":len(null_date_symbols-symbols),
        "symbols_with_valid_dates_no_null_dates":len(
            symbols-null_date_symbols),
        "distinct_symbols_with_other_invalid_date_rows":len(
            other_invalid_date_symbols),
        "distinct_raw_symbol_date_keys":len(keys),
        "earliest_valid_original_factor_date":min(dates).isoformat() if dates else None,
        "latest_valid_original_factor_date":max(dates).isoformat() if dates else None,
        "observed_rows_by_year":dict(sorted(by_year.items())),
        "counts":{
            name:int(counts[name]) for name in (
                "null_or_invalid_symbols","null_or_invalid_dates",
                "null_date_rows","non_null_invalid_date_rows",
                "duplicate_exact_symbol_day_keys",
                "null_or_nonnumeric_factors","nonfinite_factors",
                "nonpositive_factors","positive_factor_equal_one_rows",
                "positive_factor_not_one_rows")},
        "factor_health_rows_classified":sum(
            counts[name] for name in factor_health_buckets),
        "invalid_date_rows_preserved_as_uninterpreted_source":True,
        "null_date_rows_treated_as_initial_factor":False,
        "factor_row_scan_only_not_Kline":True,
        "only_original_factor_columns_read":list(COLUMNS),
        "purchased_ohlcva_files_or_rows_opened":False,
        "original_factor_parquet_stat_unchanged":True,
        "original_market_files_modified":False,
        "new_market_or_index_files_written":False,
        "individual_security_identifiers_or_factor_values_exported":False,
        "factor_row_day_keys_verified_against_official_actions":False,
        "factor_direction_base_date_and_adjustment_semantics_certified":False,
        "source_fingerprint_is_content_sha":False,
        "production_activated":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",required=True,type=Path)
    args=parser.parse_args(argv)
    print("FACTOR_KEY_AUDIT_READONLY="+json.dumps(
        audit(args.root),ensure_ascii=False,sort_keys=True,separators=(",",":")),
        flush=True)


if __name__=="__main__":
    main()
