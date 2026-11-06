#!/usr/bin/env python3
"""Independent READ-ONLY 21-year original-H5 historical private day audit.

Checks exactly one private Parquet and manifest for every year 1990..2010.
No original H5 OHLCVA read, no source/Parquet writes, no private candidate
mutation, no production pointer, no implicit unit/security/calendar approval.
Prior annual converters are not called: this reads the MATERIALIZED candidates.
Original-source size/mtime fingerprints are rechecked (NOT full-byte hashes).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
FIRST_YEAR=1990
LAST_YEAR=2010
EXPECTED_ALL_STOCKDAYS=3682327
EXPECTED_ALL_OTHER=631281
MAX_BATCH_ROWS=32768
MARKET_BY_SUFFIX={"XSHG":"SH","XSHE":"SZ","XBSE":"BJ"}
LOWER_DATE=date(1970,1,1)


def _load(name,path):
    spec=importlib.util.spec_from_file_location(name,HERE/path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


P90=_load("independent_pre2011_private_1990_contract",
          "stage-original-h5-1990-private-day-pilot.py")
ANNUAL=_load("independent_pre2011_private_1991_2010_contract",
             "stage-original-h5-pre2011-annual-private-day.py")

PARENT=MODULE/"work"/"unified_parquet"/"historical_pre2011_daily_pilots"
SOURCES={
    1990:"hikyuu_h5_1990_uncertified_private_candidate",
    **{y:"hikyuu_h5_historical_uncertified_private_candidate"
       for y in range(1991,2011)},
}
ALWAYS_FALSE=(
    "historical_security_master_certified",
    "official_historical_trading_calendar_certified",
    "h5_volume_amount_price_units_certified",
    "corporate_action_adjustment_certified",
    "raw_OHLCVA_in_manifest",
    "original_market_files_written",
    "purchased_parquet_replaced",
    "h5_mirror_created",
    "production_pointer_modified",
    "ready_for_production_merge",
)
FLOATS=P90.FIELDS
SUFFIX_TO_PREFIX={"XSHG":"SH","XSHE":"SZ","XBSE":"BJ"}


def _source_gate(root):
    root=Path(root).resolve()
    if (not root.is_dir() or root==MODULE or root.is_relative_to(MODULE)
            or MODULE.is_relative_to(root)
            or PARENT.resolve().is_relative_to(root)):
        raise ValueError("Original source overlaps audit repository/private work")
    h5=P90.h5_state(root)
    if h5!=P90.EXPECTED_H5_STATE:
        raise ValueError("Original H5 size/mtime SHA differs from source inventory")
    bought=P90.purchased_gate(root)
    if bought["source_file_size_mtime_state_sha256"]!=P90.EXPECTED_PQ_STATE:
        raise ValueError("Purchased Parquet daily source differs from original footer audit")
    return h5,bought["source_file_size_mtime_state_sha256"]


def _private_paths():
    if (PARENT!=MODULE/"work"/"unified_parquet"/"historical_pre2011_daily_pilots"
            or not PARENT.is_dir() or not PARENT.parent.is_dir()
            or any(p.is_symlink() for p in (
                MODULE/"work",MODULE/"work"/"unified_parquet",PARENT))
            or not PARENT.resolve().is_relative_to(MODULE.resolve())):
        raise ValueError("Unsafe or missing local gitignored historical private candidate root")
    found={}
    entries=list(PARENT.iterdir())
    if len(entries)!=LAST_YEAR-FIRST_YEAR+1:
        raise ValueError("Not exactly 21 annual private candidate directories")
    for p in entries:
        if p.is_symlink() or not p.is_dir():
            raise ValueError("Non-directory/symlink in private annual candidate root")
        match=re.fullmatch(r"(199\d|200\d|2010)-research-[a-f0-9]{16}",p.name)
        if not match:
            raise ValueError("Unexpected private annual candidate directory")
        year=int(match.group(1))
        if year in found:
            raise ValueError("More than one private annual candidate for same year")
        found[year]=p
    if set(found)!=set(range(FIRST_YEAR,LAST_YEAR+1)):
        raise ValueError("Missing annual private candidate year")
    return found


def _expected(year):
    if year==1990:
        return (P90.EXPECT_A_STOCKDAYS,P90.EXPECT_OTHER_STOCKDAYS,
                P90.EXPECT_A_SYMBOLS,P90.EXPECT_A_DATES)
    return ANNUAL.EXPECTED[year]


def _check_manifest(year,folder,h5_sha,pq_sha):
    manifest=folder/"manifest.json"
    parquet=folder/"day.parquet"
    if (set(p.name for p in folder.iterdir())!={"day.parquet","manifest.json"}
            or any(p.is_symlink() or not p.is_file() for p in (manifest,parquet))
            or not 0<manifest.stat().st_size<=8192):
        raise ValueError("Private annual files missing, unexpected or symlinked")
    info=json.loads(manifest.read_text(encoding="utf-8"))
    stockdays,other,symbols,days=_expected(year)
    expected_format=(P90.FORMAT if year==1990 and hasattr(P90,"FORMAT")
                     else ("AStockDataTools isolated uncertified 1990 H5 candidate day private v1"
                           if year==1990 else ANNUAL.FORMAT))
    if (info.get("format")!=expected_format
            or info.get("state")!="verified_private_candidate_not_promoted"
            or info.get("year")!=year or info.get("period")!="day"
            or info.get("candidate_stockday_rows")!=stockdays
            or info.get("private_parquet_row_count")!=stockdays
            or info.get("other_code_source_rows_not_staged")!=other
            or info.get("distinct_source_dates")!=days
            or info.get("h5_original_state_sha256")!=h5_sha
            or info.get("purchased_original_state_sha256")!=pq_sha
            or info.get("private_parquet_written") is not True
            or info.get("candidate_price_factor")!=0.001
            or info.get("candidate_volume_factor")!=100
            or info.get("candidate_amount_factor")!=1000
            or any(info.get(k) is not False for k in ALWAYS_FALSE)):
        raise ValueError(f"Historical private manifest year {year} failed source/uncertified gate")
    if year==1990:
        if (info.get("purchased_pre2011_absent_in_all_24_original_day_files") is not True
                or info.get("h5_1990_source_exact_key_and_OHLCVA_geometry_passed") is not True):
            raise ValueError("1990 original H5/PQ exact day source validation proof missing")
    elif (info.get("purchased_pre2011_all_day_files_confirmed_absent") is not True
          or info.get("native_day_keys_and_OHLCVA_geometry_checked") is not True):
        raise ValueError(f"Annual year {year} exact source proof missing")
    if info.get("private_stage_relative_dir")!=folder.relative_to(MODULE).as_posix():
        raise ValueError("Private candidate relative stage manifest mismatch")
    sha=info.get("private_parquet_sha256")
    if type(sha) is not str or not re.fullmatch("[a-f0-9]{64}",sha):
        raise ValueError("Invalid independent private Parquet SHA256 manifest")
    # Content SHA, not the weaker H5 source size/mtime SHA.
    actual=P90._digest(parquet)
    if sha!=actual:
        raise ValueError(f"Private year {year} Parquet content SHA256 mismatch")
    return parquet,info


def _check_parquet(year,parquet,info):
    """Stream exact private typed OHLCVA, symbol/day keys, and annual totals."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    import numpy as np

    expected,other,number_symbols,number_days=_expected(year)
    schema=ANNUAL._candidate_schema()
    reader=pq.ParquetFile(str(parquet))
    if (reader.schema_arrow!=schema
            or reader.metadata.num_rows!=expected
            or reader.metadata.num_row_groups<1
            or reader.metadata.num_row_groups>10000):
        raise ValueError(f"Private {year} Parquet physical schema/count/rowgroups wrong")
    unique=set()
    symbols=set()
    days=set()
    market=Counter()
    checked=0
    seen_source=SOURCES[year]
    valid_symbol={}
    date_cache={}
    for batch in reader.iter_batches(batch_size=MAX_BATCH_ROWS,use_threads=False):
        if (batch.schema!=schema or
                any(batch.column(i).null_count for i in range(len(schema)))):
            raise ValueError(f"Private {year} Parquet null/typed-batch schema invalid")
        count=batch.num_rows
        if count<1 or checked+count>expected:
            raise ValueError(f"Private {year} Parquet streamed rows exceed budget")
        ts=batch.column(0).to_numpy(zero_copy_only=False)
        values=[batch.column(j).to_numpy(zero_copy_only=False)
                for j in range(2,8)]
        if (np.any((ts+28800000)%86400000!=0)
                or not all(np.all(np.isfinite(col)) for col in values)
                or not all(np.all(col>=0) for col in values)
                or np.any(values[0]<=0) or np.any(values[1]<=0)
                or np.any(values[2]<=0) or np.any(values[3]<=0)
                or np.any(values[1]+1e-8<np.maximum.reduce((
                    values[0],values[2],values[3])))
                or np.any(values[2]-1e-8>np.minimum.reduce((
                    values[0],values[1],values[3])))):
            raise ValueError(f"Private {year} native daily key/OHLCVA geometric sanity failed")
        for x in np.unique(ts):
            stamp=int(x)
            if stamp not in date_cache:
                d=LOWER_DATE+timedelta(days=(stamp+28800000)//86400000)
                if d.year!=year or d.strftime("%Y%m%d")!=str(d.year).zfill(4)+d.strftime("%m%d"):
                    raise ValueError(f"Private {year} timestamp outside original native day year")
                date_cache[stamp]=d
                days.add(stamp)
        sym_list=batch.column(1).to_pylist()
        sources=batch.column(8).to_pylist()
        if any(value!=seen_source for value in sources):
            raise ValueError(f"Private {year} provenance source label changed")
        for stamp,symbol in zip(ts,sym_list):
            if symbol not in valid_symbol:
                m=re.fullmatch(r"(\d{6})\.(XSHG|XSHE|XBSE)",symbol or "")
                if m is None:
                    raise ValueError(f"Private {year} noncanonical stock code")
                prefix=SUFFIX_TO_PREFIX[m.group(2)]
                original=prefix+m.group(1)
                if (P90.CORE.symbol_id(original)!=original
                        or not P90.CORE.is_a_share_candidate(original,year)):
                    raise ValueError(f"Private {year} non-A-code original security candidate")
                valid_symbol[symbol]=prefix
            key=(int(stamp),symbol)
            if key in unique:
                raise ValueError(f"Private {year} duplicate exact stockday key")
            unique.add(key)
            symbols.add(symbol)
            market[valid_symbol[symbol]]+=1
        checked+=count
    if (checked!=expected or len(unique)!=expected
            or len(symbols)!=number_symbols or len(days)!=number_days
            or dict(sorted(market.items()))!=info.get("market_candidate_rows")):
        raise ValueError(f"Private {year} stockdays/symbols/dates/markets do not conserve")
    return {
        "year":year,
        "stockdays":checked,
        "other_code_rows_excluded":other,
        "candidate_symbols":len(symbols),
        "candidate_dates":len(days),
        "private_parquet_sha256":info["private_parquet_sha256"],
        "validated":True,
    }


def audit(root):
    """Full 21-year read-only scan, no new candidate/report written anywhere."""
    before=_source_gate(root)
    all_year_paths=_private_paths()
    annual=[]
    for year in range(FIRST_YEAR,LAST_YEAR+1):
        print(f"READONLY_PRIVATE_H5_YEAR_VERIFYING={year} EXPECTED={_expected(year)[0]}",flush=True)
        path,info=_check_manifest(year,all_year_paths[year],*before)
        result=_check_parquet(year,path,info)
        # A year has its own exclusive calendar range; uniqueness within year
        # plus exact in-year midnight timestamp proves cross-year uniqueness.
        annual.append(result)
        print(f"READONLY_PRIVATE_H5_YEAR_PASS={year} STOCKDAYS={result['stockdays']} OTHER_EXCLUDED={result['other_code_rows_excluded']} SHA256={result['private_parquet_sha256']}",flush=True)
    if _source_gate(root)!=before:
        raise ValueError("Original H5 or purchased Parquet stat changed during 21-year audit")
    total=sum(row["stockdays"] for row in annual)
    other=sum(row["other_code_rows_excluded"] for row in annual)
    if total!=EXPECTED_ALL_STOCKDAYS or other!=EXPECTED_ALL_OTHER:
        raise ValueError("21-year historical H5 candidate/other code native inventory mismatch")
    result={
        "state":"full_1990_2010_private_h5_day_21_year_files_shas_schema_keys_quality_verified_readonly_not_promoted",
        "years_verified":len(annual),
        "years_first_last":[FIRST_YEAR,LAST_YEAR],
        "private_a_code_stockday_rows_verified":total,
        "other_code_source_rows_excluded":other,
        "all_annual_private_parquet_sha256_valid":True,
        "all_annual_manifest_source_state_checked":True,
        "all_annual_candidate_keys_unique_and_year_bound":True,
        "all_annual_OHLCVA_geometry_finite_nonnegative":True,
        "original_h5_stat_sha256":before[0],
        "purchased_day_original_stat_sha256":before[1],
        "original_h5_ohlcva_redecoded_by_full_audit":False,
        "source_stat_SHA_is_not_full_byte_SHA":True,
        "historical_security_master_certified":False,
        "official_trading_calendar_certified":False,
        "h5_price_volume_amount_units_certified":False,
        "corporate_action_adjustment_certified":False,
        "original_market_sources_modified":False,
        "private_candidate_files_modified":False,
        "production_activated":False,
        "ready_for_production_merge":False,
    }
    print("READONLY_PRIVATE_H5_21_YEAR_AUDIT_SUMMARY="+json.dumps(
        result,ensure_ascii=False,sort_keys=True,separators=(",",":")),flush=True)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    a=p.parse_args(argv)
    audit(a.source_root)


if __name__=="__main__":
    main()
