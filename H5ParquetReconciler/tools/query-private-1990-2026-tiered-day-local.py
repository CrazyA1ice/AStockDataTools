#!/usr/bin/env python3
"""Opt-in LOCAL historical DAY query on existing 1990-2026 physical Parquets.

2011-2026 uses the already tested SHA-pinned 16-year query, with purchased
bars distinguished from H5-only hypotheses. 1990-2010 reads separately SHA-
verified tentative (NOT VENDOR CERTIFIED) Parquet rows; quarantined ORIGINAL
native integers are a separately opt-in result, NEVER assigned fake floats.
No original H5, purchased supplier files, mutable active pointers or writes.
Licensed market values are returned ONLY to the caller in process memory;
the CLI prints/writes only aggregate safe counts, no symbols or date windows.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
REPORTS=MODULE/"reports"
PRIVATE=MODULE/"work"/"unified_parquet"/"pre2011_day_candidates"
HISTORICAL_RE=re.compile(
    r"work/unified_parquet/pre2011_day_candidates/historical_(19\d\d|200\d|2010)_([0-9a-f]{12})/(purchased_schema_day_candidates|source_native_quarantine)\.parquet\Z")
SHA_RE=re.compile(r"[0-9a-f]{64}\Z")
SYMBOL_RE=re.compile(r"(SH|SZ|BJ)[0-9]{6}\Z")
HIST_LABEL="h5_pre2011_numeric_hypothesis_not_vendor_certified"

def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

MODERN=load("tiered_day_modern_reader","query-private-2011-2026-all16-ohlcva-local-readonly.py")
STAGE=load("tiered_day_original_historical_schema","stage-pre2011-day-normalized-candidates-with-quarantine.py")

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def check_query(symbol,first,last,max_result_bars,
                allow_private_values,allow_unverified_historical,
                allow_native_quarantine):
    if allow_private_values is not True:
        raise ValueError("Private licensed bars require explicit local opt-in")
    if (type(symbol) is not str or not SYMBOL_RE.fullmatch(symbol)):
        raise ValueError("Only canonical SH/SZ/BJ six digit stock code")
    try:
        first=date.fromisoformat(first)
        last=date.fromisoformat(last)
    except (TypeError,ValueError):
        raise ValueError("Require exact ISO day dates") from None
    if (first>last or first.year<1990 or last.year>2026
            or not 1<=(last-first).days+1<=31):
        raise ValueError("Historical bounded query accepts 1..31 days in 1990..2026")
    if type(max_result_bars) is not int or not 1<=max_result_bars<=31:
        raise ValueError("Only 1..31 DAY values in a local read")
    for name,value in (("historical",allow_unverified_historical),
                       ("native quarantine",allow_native_quarantine)):
        if type(value) is not bool:
            raise ValueError(name+" option must be explicit boolean")
    if first<=date(2010,12,31) and not (
            allow_unverified_historical or allow_native_quarantine):
        raise ValueError("1990-2010 is NOT certified; opt into candidate/native layer")
    return first,last

def checked_manifest(path,expected_sha,modern_sha):
    if not SHA_RE.fullmatch(expected_sha) or not SHA_RE.fullmatch(modern_sha):
        raise ValueError("Full 64-hex SHA pins required")
    p=Path(path)
    if (REPORTS.is_symlink() or p.is_symlink() or not p.is_file()
            or p.resolve().parent!=REPORTS.resolve()
            or p.stat().st_size>500000 or sha(p)!=expected_sha):
        raise ValueError("Historical candidate manifest SHA/path not verified")
    obj=json.loads(p.read_text(encoding="utf-8"))
    years=obj.get("historical_years")
    if (obj.get("status")!="1990_2026_day_full_history_private_candidates_with_raw_quarantine_not_activated"
            or obj.get("raw_1990_2010_h5_rows_preserved")!=3682327
            or obj.get("purchase_schema_historical_hypothesis_rows")!=3673987
            or obj.get("historical_native_raw_quarantined_rows")!=8340
            or obj.get("modern_2011_2026_accepted_private_rows")!=14137981
            or obj.get("all_1990_2026_source_rows_without_overlap")!=17820308
            or obj.get("modern_all16_version_sha256")!=modern_sha
            or obj.get("historical_candidate_vendor_units_or_corporate_actions_certified") is not False
            or obj.get("historical_candidate_rows_active_in_production_query") is not False
            or obj.get("private_active_pointer_modified") is not False
            or not isinstance(years,dict)
            or set(years)!={str(y) for y in range(1990,2011)}):
        raise ValueError("Historical candidate manifest safety/counts changed")
    return obj

def historical_file(entry,year,kind):
    file_key=("candidate" if kind=="purchased_schema_day_candidates"
              else "quarantine")+"_parquet_relative_path"
    hash_key=("candidate" if kind=="purchased_schema_day_candidates"
              else "quarantine")+"_parquet_sha256"
    relative=entry.get(file_key)
    digest=entry.get(hash_key)
    if type(relative) is not str or type(digest) is not str:
        raise ValueError("Invalid historical candidate entry fields")
    matched=HISTORICAL_RE.fullmatch(relative)
    if not matched or int(matched[1])!=year or matched[3]!=kind or not SHA_RE.fullmatch(digest):
        raise ValueError("Invalid private historical year-relative path or SHA")
    path=MODULE/relative
    if (path.is_symlink() or path.parent.is_symlink()
            or not path.is_file() or not path.resolve().is_relative_to(PRIVATE.resolve())
            or sha(path)!=digest):
        raise ValueError("Original historical private Parquet SHA changed")
    return path

def read_history_part(file,kind,symbol,lo,hi,limit):
    import pyarrow as pa
    import pyarrow.parquet as pq
    raw=kind=="source_native_quarantine"
    schema=(pa.schema([*STAGE.SINGLE.schema(pa),
                      pa.field("quarantine_reason",pa.string())])
            if raw else STAGE.PHYS.schema(pa))
    with pq.ParquetFile(file) as p:
        if p.schema_arrow!=schema:
            raise ValueError("Historical private Parquet schema changed")
    if raw:
        stamp=lambda d: d.year*100000000+d.month*1000000+d.day*10000
        filters=[("symbol","==",symbol),
                 ("datetime",">=",stamp(lo)),
                 ("datetime","<=",stamp(hi))]
    else:
        filters=[("symbol","==",symbol),
                 ("trading_date",">=",lo.isoformat()),
                 ("trading_date","<=",hi.isoformat())]
    table=pq.read_table(file,filters=filters,use_threads=False)
    if len(table)>limit:
        raise ValueError("Private DAY result exceeds max bars; no partial values returned")
    rows=table.to_pylist()
    if len(rows)!=len({r["datetime"] if raw else r["trading_date"]
                        for r in rows}):
        raise ValueError("Duplicate stock/day in historical Parquet")
    for row in rows:
        if row.get("symbol")!=symbol:
            raise ValueError("Historical Arrow filter did not match symbol")
        if not raw and row.get("value_source")!=HIST_LABEL:
            raise ValueError("Unverified historical source tag changed")
        if raw and not isinstance(row.get("quarantine_reason"),str):
            raise ValueError("Unrecognized native quarantine reason")
    return rows

def read_local_bars(historical_version_safe,historical_version_sha256,
                    modern_version_safe,modern_version_sha256,
                    symbol,first,last,*,allow_private_values=False,
                    allow_unverified_historical=False,
                    allow_native_quarantine=False,max_result_bars=31):
    lo,hi=check_query(symbol,first,last,max_result_bars,
                      allow_private_values,allow_unverified_historical,
                      allow_native_quarantine)
    # The version includes every year; version pin checked before reading values.
    manifest=checked_manifest(historical_version_safe,historical_version_sha256,
                              modern_version_sha256)
    modern=[]
    historic=[]
    native=[]
    if hi>=date(2011,1,1):
        start=max(lo,date(2011,1,1))
        result=MODERN.read_local_bars(
            modern_version_safe,modern_version_sha256,symbol,
            start.isoformat(),hi.isoformat(),
            allow_private_values=True,max_result_bars=max_result_bars)
        modern=result["bars"]
    if lo<=date(2010,12,31):
        hhi=min(hi,date(2010,12,31))
        for year in range(lo.year,hhi.year+1):
            entry=manifest["historical_years"][str(year)]
            begin=max(lo,date(year,1,1))
            end=min(hhi,date(year,12,31))
            if allow_unverified_historical:
                file=historical_file(entry,year,"purchased_schema_day_candidates")
                historic.extend(read_history_part(
                    file,"purchased_schema_day_candidates",symbol,begin,end,
                    max_result_bars))
            if allow_native_quarantine:
                file=historical_file(entry,year,"source_native_quarantine")
                native.extend(read_history_part(
                    file,"source_native_quarantine",symbol,begin,end,
                    max_result_bars))
    if len(modern)+len(historic)+len(native)>max_result_bars:
        raise ValueError("Total private result exceeded explicitly bounded bars")
    if len({(r["symbol"],r["trading_date"]) for r in modern+historic})!=len(modern+historic):
        raise ValueError("Duplicate canonical DAY key across source tiers")
    history_counts={
        "purchased_2011_2026":sum(r.get("value_source")=="purchased_parquet" for r in modern),
        "h5_2011_2026_unverified_gap":sum(r.get("value_source")!="purchased_parquet" for r in modern),
        "h5_pre2011_unverified_hypothesis":len(historic),
        "h5_pre2011_native_quarantine":len(native),
    }
    safe={
        "status":"local_optin_sha_pinned_1990_2026_tiered_day_read_not_production",
        "local_result_count":sum(history_counts.values()),
        "counts_by_data_tier":history_counts,
        "historical_version_sha256":historical_version_sha256,
        "modern_version_sha256":modern_version_sha256,
        "historical_vendor_units_or_stock_identity_certified":False,
        "quarantined_raw_converted_to_purchase_schema":False,
        "native_quarantine_kept_separate":True,
        "original_market_files_opened":False,
        "private_or_production_pointer_modified":False,
        "ready_for_production_query":False,
        "safe_contains_private_licensed_bars_or_symbol":False,
    }
    return {"bars":modern+historic,"native_quarantine_rows":native,
            "safe_summary":safe}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-version-safe",type=Path,required=True)
    parser.add_argument("--historical-version-sha256",required=True)
    parser.add_argument("--modern-version-safe",type=Path,required=True)
    parser.add_argument("--modern-version-sha256",required=True)
    parser.add_argument("--symbol",required=True)
    parser.add_argument("--start",required=True)
    parser.add_argument("--end",required=True)
    parser.add_argument("--include-historical-hypothesis",action="store_true")
    parser.add_argument("--include-native-quarantine",action="store_true")
    parser.add_argument("--max-result-bars",type=int,default=31)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--verify-local-private-only",action="store_true",required=True)
    args=parser.parse_args(argv)
    out=args.out
    if (out.is_symlink() or out.exists() or out.suffix!=".json"
            or REPORTS.is_symlink() or out.resolve().parent!=REPORTS.resolve()):
        raise ValueError("Write only a fresh aggregate report under module reports")
    result=read_local_bars(args.historical_version_safe,args.historical_version_sha256,
                           args.modern_version_safe,args.modern_version_sha256,
                           args.symbol,args.start,args.end,
                           allow_private_values=True,
                           allow_unverified_historical=args.include_historical_hypothesis,
                           allow_native_quarantine=args.include_native_quarantine,
                           max_result_bars=args.max_result_bars)
    with out.open("x",encoding="utf-8") as f:
        json.dump(result["safe_summary"],f,indent=2,sort_keys=True)
        f.write("\n")
    print("SHA-verified local private read complete; result counts:",
          result["safe_summary"]["counts_by_data_tier"])
    print("NO private licensed values/symbol or dates exported. SAFE:",out)

if __name__=="__main__":
    main()
