#!/usr/bin/env python3
"""Fixed cross-regime original Parquet/raw H5 DAY overlap factor diagnostics.

Exactly 2 previously used liquid symbols, 2 held-out dates in each of 2016,
2020, 2024, 2026 (16 stockdays). Read only purchased DAY row groups and raw
original H5 stockday records; no licensed OHLCVA, stock IDs, timestamps of
individual records or source paths leave local RAM. No unit certification,
market write, pointer change, gap merge or mirror.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from datetime import date
from decimal import Decimal
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools fixed stratified 2016 2020 2024 2026 day factor diagnostic SAFE v1"
# Precommitted fixed calendar dates; never select the dates AFTER seeing
# source values. Already-investigated 2025-09-30 and 2026-08-24/09-28..30
# are explicitly excluded from new statistical evidence.
SAMPLES={
    2016:("2016-08-17","2016-08-18"),
    2020:("2020-08-17","2020-08-18"),
    2024:("2024-08-19","2024-08-20"),
    2026:("2026-08-17","2026-08-18"),
}
SYMBOLS=("SH600000","SZ000001")
FIELDS=("open","high","low","close","volume","amount")
PRICE_FIELDS=FIELDS[:4]
PRICE_H5={"open":"openPrice","high":"highPrice","low":"lowPrice","close":"closePrice"}
QUANTITY_H5={"volume":"transCount","amount":"transAmount"}
PRICE_TOL=Decimal("0.005")
QUANTITY_REL_TOL=Decimal("0.00001")
CANDIDATES={"volume":Decimal(100),"amount":Decimal(1000)}
PARQUET_COLUMNS=("ts","symbol",*FIELDS)
MAX_FILES_PER_YEAR=24
MAX_GROUPS_PER_YEAR=512
MAX_SCANNED_ROWS_PER_YEAR=5000000
MAX_SOURCE_SAFE=1000000


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


KEYS=load("stratified_fixed_day_keys","verify-live-mixed-h5-day-keys-readonly.py")
PAIR=load("stratified_original_h5_raw","probe-real-parquet-h5-day-unit-factors-readonly.py")
REG=load("stratified_22274_immutable_registration","register-private-combined-day-22274-version.py")
CORE=KEYS.CORE


def new_safe(path):
    p=Path(path)
    if (REPORTS.is_symlink() or p.is_symlink() or p.suffix.lower()!=".json"
            or p.resolve().parent!=REPORTS.resolve() or p.exists()):
        raise ValueError("Require NEW non-symlink module reports JSON")
    return p.resolve()


def checked_calendar():
    if (set(SAMPLES)!={2016,2020,2024,2026}
            or len(SYMBOLS)!=2 or set(SYMBOLS)!={"SH600000","SZ000001"}):
        raise ValueError("Fixed cross-regime sample dimensions have drifted")
    used=set()
    for year, days in SAMPLES.items():
        if type(days) is not tuple or len(days)!=2:
            raise ValueError("Fixed year must have exactly two dates")
        for d in days:
            day=date.fromisoformat(d)
            if day.isoformat()!=d or day.year!=year or d in used:
                raise ValueError("Invalid/duplicate cross-regime calendar")
            if d in {"2025-09-30","2026-08-24","2026-09-28",
                     "2026-09-29","2026-09-30"}:
                raise ValueError("Prior discovery/holdout used as new evidence")
            used.add(d)
    return used


def source_snapshot(root):
    """Stat signatures are a drift alarm, NOT a purchased source content hash."""
    items=[]
    for year in SAMPLES:
        paths=CORE.year_files(root,"day",year)
        if not 1<=len(paths)<=MAX_FILES_PER_YEAR:
            raise ValueError("Missing or excessive purchased year DAY files")
        for p in paths:
            if p.is_symlink() or not p.is_file():
                raise ValueError("Original purchased Parquet source is symlink/missing")
            s=p.stat()
            items.append((str(p.resolve()),s.st_size,s.st_mtime_ns))
    for market in ("sh","sz"):
        p=root/"HikyuuData"/(market+"_day.h5")
        if p.is_symlink() or not p.is_file():
            raise ValueError("Original Hikyuu daily source is symlink/missing")
        s=p.stat()
        items.append((str(p.resolve()),s.st_size,s.st_mtime_ns))
    return tuple(sorted(items))


def scan_purchased_year(root,year):
    """Read all day samples of a year in one pass; exact (symbol,date) join."""
    import pyarrow.parquet as pq

    selected=SAMPLES[year]
    times={int(d.replace("-",""))*10000:d for d in selected}
    _,_,low_ms,high_ms=CORE.parse_day_range(year,selected[0],selected[-1])
    files=CORE.year_files(root,"day",year)
    if not 1<=len(files)<=MAX_FILES_PER_YEAR:
        raise ValueError("Year source file budget/missing source")
    found={}
    scanned=0
    groups=0
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Purchased daily source symlink")
        pf=pq.ParquetFile(path)
        if not set(PARQUET_COLUMNS).issubset(pf.schema_arrow.names):
            raise ValueError("Purchased original day OHLCVA schema missing")
        for index in range(pf.metadata.num_row_groups):
            if not CORE.row_group_overlaps_timestamp(
                    pf.metadata.row_group(index),low_ms,high_ms):
                continue
            groups+=1
            if groups>MAX_GROUPS_PER_YEAR:
                raise ValueError("Selected purchased Parquet row group budget exceeded")
            for batch in pf.iter_batches(row_groups=[index],batch_size=32768,
                                         columns=list(PARQUET_COLUMNS),use_threads=True):
                scanned+=batch.num_rows
                if scanned>MAX_SCANNED_ROWS_PER_YEAR:
                    raise ValueError("Selected purchased Parquet source row budget exceeded")
                columns=[batch.column(j).to_pylist() for j in range(len(PARQUET_COLUMNS))]
                for values in zip(*columns):
                    ts,original_symbol,*ohlcva=values
                    if type(ts) is not int or not low_ms<=ts<high_ms:
                        continue
                    stamp=CORE.pq_stamp(ts,"day")
                    if stamp not in times:
                        continue
                    symbol=CORE.symbol_id(original_symbol)
                    if symbol is None:
                        raise ValueError("Unknown purchased symbol in a selected day")
                    if symbol not in SYMBOLS:
                        continue
                    if (len(ohlcva)!=len(FIELDS)
                            or any(type(v) is not float or not math.isfinite(v)
                                   or v<0 for v in ohlcva)):
                        raise ValueError("Invalid source float64 OHLCVA in selected key")
                    key=(symbol,times[stamp])
                    if key in found:
                        raise ValueError("Duplicate original purchased stockday key")
                    found[key]=dict(zip(FIELDS,ohlcva))
    if set(found)!={(s,d) for s in SYMBOLS for d in selected}:
        raise ValueError("Selected exact stockday missing in original purchased DAY")
    return found,scanned,groups


def evaluate_stockday(purchased,raw):
    """Return only aggregate-eligible diagnostics, never real source numbers."""
    if type(purchased) is not dict or set(purchased)!=set(FIELDS):
        raise ValueError("Missing six original float64 purchased fields")
    if type(raw) is not dict or not set(PAIR.RAW).issubset(raw):
        raise ValueError("Missing original H5 compound integer fields")
    if (any(type(purchased[f]) is not float or
            not math.isfinite(purchased[f]) or purchased[f]<0 for f in FIELDS)
            or any(type(raw[f]) is not int or raw[f]<0 for f in PAIR.RAW)):
        raise ValueError("Nonfinite/noncanonical original numeric fields")
    if min(purchased[f] for f in PRICE_FIELDS)<=0:
        raise ValueError("Purchased day price geometry invalid")
    if (purchased["high"] < max(purchased["open"],purchased["low"],purchased["close"])
            or purchased["low"] > min(purchased["open"],purchased["high"],purchased["close"])):
        raise ValueError("Purchased daily OHLC geometry mismatch")
    hit={}
    for f in PRICE_FIELDS:
        diff=abs(Decimal(str(purchased[f]))-Decimal(raw[PRICE_H5[f]])/1000)
        hit[f]=bool(diff<=PRICE_TOL)
    nonzero={}
    quantity_hit={}
    for f in ("volume","amount"):
        original=Decimal(str(purchased[f]))
        candidate=Decimal(raw[QUANTITY_H5[f]])*CANDIDATES[f]
        nonzero[f]=original>0 and candidate>0
        quantity_hit[f]=(nonzero[f] and
                         abs(original-candidate)/max(original,candidate)<=QUANTITY_REL_TOL)
    return {"price_tolerance_hits":hit,
            "quantity_positive_pairs":nonzero,
            "quantity_factor_hits":quantity_hit}


def summarize(year_stocks):
    """Always surface mismatches as evidence; never promote on silent coercion."""
    if type(year_stocks) is not dict or set(year_stocks)!=set(SAMPLES):
        raise ValueError("Must provide all four independent calendar years")
    by_year={}
    for year in sorted(SAMPLES):
        rows=year_stocks[year]
        if type(rows) is not list or len(rows)!=4:
            raise ValueError("Year needs both stocks on both precommitted dates")
        summary={
            "paired_stockdays":4,
            "price_field_within_0p005":{f:0 for f in PRICE_FIELDS},
            "positive_nonzero_pairs":{f:0 for f in ("volume","amount")},
            "candidate_factor_hit_pairs":{f:0 for f in ("volume","amount")},
        }
        for result in rows:
            if (type(result) is not dict or set(result)!={
                    "price_tolerance_hits","quantity_positive_pairs",
                    "quantity_factor_hits"}):
                raise ValueError("Malformed per-stockday factor evidence")
            for f in PRICE_FIELDS:
                if type(result["price_tolerance_hits"].get(f)) is not bool:
                    raise ValueError("Missing price factor outcome")
                summary["price_field_within_0p005"][f]+=int(result["price_tolerance_hits"][f])
            for f in ("volume","amount"):
                positive=result["quantity_positive_pairs"].get(f)
                matched=result["quantity_factor_hits"].get(f)
                if type(positive) is not bool or type(matched) is not bool or matched and not positive:
                    raise ValueError("Missing/contradictory quantity factor outcome")
                summary["positive_nonzero_pairs"][f]+=int(positive)
                summary["candidate_factor_hit_pairs"][f]+=int(matched)
        summary["all_sampled_numeric_candidates_match"]=(
            all(x==4 for x in summary["price_field_within_0p005"].values())
            and all(x==4 for x in summary["positive_nonzero_pairs"].values())
            and all(x==4 for x in summary["candidate_factor_hit_pairs"].values()))
        by_year[str(year)]=summary
    return by_year


def run(source_root,version_sha256,out):
    checked_calendar()
    dest=new_safe(out)
    if (type(version_sha256) is not str or len(version_sha256)!=64
            or any(x not in "0123456789abcdef" for x in version_sha256)):
        raise ValueError("Require explicit immutable version SHA256")
    source_root=Path(source_root)
    if (not source_root.is_absolute() or source_root.is_symlink()
            or not source_root.is_dir()):
        raise ValueError("Original source root must be an absolute nonsymlink directory")
    if REG.LOCK.exists() or REG.LOCK.is_symlink():
        raise ValueError("Private version registration is in progress")
    version=REG.load_version(version_sha256)
    if (version.get("ready_for_production_query") is not False
            or version.get("candidate_total_new_stockday_rows")!=22274
            or version.get("whole_day_candidate_rows")!=22191
            or version.get("mixed_stockday_candidate_rows")!=83):
        raise ValueError("Invalid/quarantined private version state")
    before=source_snapshot(source_root)
    per_year={}
    row_count={}
    group_count={}
    import h5py
    import numpy as np
    for year,days in SAMPLES.items():
        matched, scanned, groups = scan_purchased_year(source_root,year)
        row_count[str(year)]=scanned
        group_count[str(year)]=groups
        outcome=[]
        for day in days:
            for symbol in SYMBOLS:
                native=PAIR._read_single_h5(
                    source_root/"HikyuuData",symbol,day,h5py,np)
                outcome.append(evaluate_stockday(matched[(symbol,day)],native))
        per_year[year]=outcome
    report_year=summarize(per_year)
    if (source_snapshot(source_root)!=before
            or REG.load_version(version_sha256)!=version
            or REG.LOCK.exists() or REG.LOCK.is_symlink()):
        raise ValueError("Original sources/immutable private version changed during diagnostic")
    matched=all(v["all_sampled_numeric_candidates_match"] for v in report_year.values())
    result={
        "format":FORMAT,
        "state":"fixed_historical_original_overlap_diagnostic_not_unit_certification",
        "registered_private_version_sha256":version_sha256,
        "samples_per_year":2,
        "symbols_per_date":2,
        "total_distinct_stockdays_compared":16,
        "sample_years":sorted(SAMPLES),
        "per_year_factor_counts":report_year,
        "per_year_purchased_source_rows_scanned":row_count,
        "per_year_purchased_source_rowgroups_scanned":group_count,
        "hypothesis_raw_h5_price_divisor":1000,
        "hypothesis_raw_h5_volume_multiplier":100,
        "hypothesis_raw_h5_amount_multiplier":1000,
        "all_16_samples_numerically_within_candidate_tolerances":matched,
        "numeric_mismatch_or_zero_requires_quarantine":not matched,
        "source_file_stat_before_after_unchanged":True,
        "source_file_stat_is_not_cryptographic_content_proof":True,
        "original_h5_and_purchased_parquet_read_only":True,
        "stock_ids_ohlcva_raw_integers_paths_not_exported":True,
        "candidate_source_units_certified":False,
        "source_adjustment_and_timestamp_semantics_certified":False,
        "universal_conversion_rules_across_all_stockdays_certified":False,
        "ready_for_production_query":False,
        "ready_for_automatic_market_merge":False,
        "h5_mirror_created":False,
        "source_market_files_written":False,
        "purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "quarantined_2026_07_16_stockday_bars_not_included":5,
    }
    with dest.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(result,stream,indent=2,sort_keys=True,ensure_ascii=False)
        stream.write("\n")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--version-sha256",required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--read-only-stratified",action="store_true",required=True)
    a=p.parse_args(argv)
    try:
        result=run(a.source_root,a.version_sha256,a.out)
        print("Read-only overlapping stock-days:",result["total_distinct_stockdays_compared"])
        print("Candidate factor numeric match across fixed years:",
              result["all_16_samples_numerically_within_candidate_tolerances"])
        print("Aggregate SAFE:",a.out)
        print("No original stock/bar, H5 mirror, candidate promotion or market writes")
    except (OSError,ValueError,TypeError,KeyError,ImportError,OverflowError):
        p.error("Fixed historical overlap factor diagnostic failed closed")


if __name__=="__main__":
    main()
