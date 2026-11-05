#!/usr/bin/env python3
"""2026 registered daily fusion purchased-Parquet precedence: real-source pilot.

Selects a validated 2026 mixed-H5 trading day from SHA-bound 83-key manifest,
then selects one *different* liquid A-share with an actual purchased Parquet
day bar and no private mixed overlay. Independently compares all original
purchased OHLCVA fields and timestamp against the explicit 22,274-version
eight-cycle live H5+Parquet source rechecked result. No market writes,
no automatic source promotion, no raw bar or private security ID in output.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
VERSION="e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23"
FIELDS=("open","high","low","close","volume","amount")
CANDIDATE_SYMBOLS=(
    "SH600000","SH600519","SH601318","SZ000001","SZ000002",
    "SZ300750","SH600036","SZ000333","SH601166","SH600900",
)


def _load(tag, filename):
    spec=importlib.util.spec_from_file_location(tag,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIXED=_load("daily_purchase_priority_2026_mixed_source_key",
            "query-registered-private-day-83-mixed-live-pilot-readonly.py")
ALL=MIXED.ALL
RES=MIXED.EVIDENCE


def offline_context(version,config):
    if version!=VERSION:
        raise ValueError("Wrong registered daily candidate version")
    evidence, sample_symbol, day = MIXED.offline_sample(version,config)
    originals, years=RES.KEYS.verified_existing_plan(
        evidence["history_ledger"], evidence["source_2016"],
        evidence["source_2026"], evidence["mixed_plan"])
    _,_,_,_,_,approved=RES.MIXED.read_verified_key_manifest(
        evidence["live_safe"],evidence["private_keys"],originals,years)
    if (type(approved) is not set or len(approved)!=83
            or (sample_symbol,int(day.replace("-",""))*10000) not in approved):
        raise ValueError("Private 83 exact keyset changed during purchased-priority preflight")
    return evidence,day,approved


def original_purchased_day(root,day,private_keys,*,max_candidate_rows=30000000):
    """Find one real purchased stockday outside the SHA-bound missing keys.

    Unlike filename heuristics, a candidate only counts when the purchased
    Parquet query returns one actual correctly dated OHLCVA row.
    """
    timestamp=int(day.replace("-",""))*10000
    for symbol in CANDIDATE_SYMBOLS:
        if (symbol,timestamp) in private_keys:
            continue
        result=ALL.PURCHASED.query_bars(
            root,symbol,"day",day,day,
            max_candidate_rows=max_candidate_rows,max_result_bars=2,
            local_cache=False)
        if type(result) is not dict or type(result.get("bars")) is not list:
            raise ValueError("Purchased primary day query returned invalid result contract")
        rows=result["bars"]
        if not rows:
            continue
        if len(rows)!=1:
            raise ValueError("Actual purchased source has duplicate daily records")
        row=rows[0]
        if (row.get("symbol")!=symbol or row.get("period")!="day"
                or row.get("trading_date")!=day
                or type(row.get("source_timestamp_ms")) is not int
                or any(type(row.get(field)) not in (int,float)
                       or not math.isfinite(row[field]) for field in FIELDS)):
            raise ValueError("Purchased primary original daily OHLCVA source invalid")
        return symbol,row
    raise ValueError("No suitable purchased daily source found among bounded research candidates")


def query_one(root,version,config,*,max_candidate_rows=30000000):
    evidence,day,private_keys=offline_context(version,config)
    symbol,raw=original_purchased_day(
        root,day,private_keys,max_candidate_rows=max_candidate_rows)
    verified=ALL.query_bars(
        root,symbol,"day",day,day,private_day_evidence=evidence,
        max_candidate_rows=max_candidate_rows,max_result_bars=3)
    safe=verified["safe_summary"]
    bars=verified["bars"]
    expected_counts={
        "purchased_parquet":1,
        "private_h5_whole_date_candidate":0,
        "private_h5_mixed_stockday_candidate":0,
    }
    if (type(bars) is not list or len(bars)!=1
            or safe.get("bars_by_source")!=expected_counts
            or safe.get("matching_bar_count")!=1
            or safe.get("period")!="day"
            or safe.get("symbol")!=symbol
            or safe.get("from_day")!=day
            or safe.get("through_day")!=day
            or safe.get("registered_private_day_version_sha256")!=version
            or safe.get("registered_private_22274_day_overlay_explicitly_enabled") is not True
            or safe.get("routing")!="explicit_immutable_22274_day_live_verified_purchased_first"
            or safe.get("purchased_source_priority") is not True
            or safe.get("production_query_activated") is not False
            or safe.get("original_market_files_modified") is not False
            or safe.get("new_market_or_index_files_written") is not False
            or safe.get("no_raw_ohlcva_in_safe_summary") is not True):
        raise ValueError("Real purchased primary daily live gate wrong provenance/safety")
    row=bars[0]
    if (row.get("value_source")!="purchased_parquet"
            or row.get("symbol")!=symbol or row.get("period")!="day"
            or row.get("trading_date")!=day
            or row.get("source_timestamp_ms")!=raw["source_timestamp_ms"]
            or row.get("source_file_relative_path")!=raw.get("source_file_relative_path")
            or row.get("source_row_group")!=raw.get("source_row_group")
            or any(type(row.get(k)) not in (int,float)
                   or not math.isfinite(row[k]) or row[k]!=raw[k]
                   for k in FIELDS)):
        raise ValueError("Purchased primary OHLCVA/time/source identity changed in unified daily result")
    return {
        "status":"verified_registered_22274_purchased_parquet_primary_real_stockday",
        "source_day":day,
        "source_security_identifier_redacted":True,
        "registered_private_day_version_sha256":version,
        "candidate_83_mixed_day_context_verified":True,
        "matching_bars":1,
        "bars_by_source":expected_counts,
        "all_six_OHLCVA_values_and_source_timestamp_equal_purchased_original":True,
        "purchased_source_file_and_rowgroup_preserved":True,
        "H5_value_override":False,
        "full_h5_purchased_live_source_gate_passed":True,
        "original_market_files_modified":False,
        "production_query_activated":False,
        "raw_price_values_in_safe_summary":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--version-sha256",required=True)
    p.add_argument("--private-day-config",type=Path,required=True)
    p.add_argument("--max-candidate-rows",type=int,default=30000000)
    a=p.parse_args(argv)
    summary=query_one(a.root,a.version_sha256,a.private_day_config,
                      max_candidate_rows=a.max_candidate_rows)
    print(json.dumps(summary,sort_keys=True,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
