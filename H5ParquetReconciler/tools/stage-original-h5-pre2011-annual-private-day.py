#!/usr/bin/env python3
"""Private-only H5 historical annual day candidates, 1991-2010.

One explicitly selected year per invocation. SHA/stat-bound original H5 and
purchased Parquet checks are mandatory. First deployment runs only 1991.
No market write, H5 mirror, active research route, or production activation.
The yearly counts are the independently observed 2026-11-06 native-key audit.
A-share code pattern is NOT historical security master certification.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import uuid
from collections import Counter
from datetime import date, datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
PARENT=MODULE/"work"/"unified_parquet"/"historical_pre2011_daily_pilots"

# year: (H5 A-code day rows, other-code day rows, A-code symbols, A-code dates).
# Never derive expected values from the same unverified scan being staged.
EXPECTED={
    1991:(2043,738,9,304),1992:(5892,1112,44,260),
    1993:(20366,1513,142,266),1994:(52414,1585,231,252),
    1995:(58848,2688,249,251),1996:(75651,3246,408,247),
    1997:(123419,10429,582,243),1998:(153762,12609,675,246),
    1999:(169612,12404,756,239),2000:(189731,13268,871,239),
    2001:(216305,14740,944,240),2002:(226875,16684,1009,237),
    2003:(246286,22056,1072,241),2004:(268903,32491,1166,243),
    2005:(272523,62341,1179,242),2006:(253988,68312,1240,241),
    2007:(289516,74372,1352,242),2008:(324630,79603,1418,246),
    2009:(339144,91214,1513,244),2010:(392395,109860,1832,242),
}
FORMAT="AStockDataTools private pre2011 annual H5 day research candidate v1"


def _load(tag, filename):
    spec=importlib.util.spec_from_file_location(tag,HERE/filename)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


P90=_load("annual_history_private_1990_source_gate",
          "stage-original-h5-1990-private-day-pilot.py")
CORE=P90.CORE
FIELDS=P90.FIELDS


def _valid_key(stamp,year):
    if type(stamp) is not int or stamp%10000:
        raise ValueError("Non-midnight H5 historical day key")
    try:
        d=date.fromisoformat(str(stamp//10000))
    except ValueError:
        raise ValueError("Noncalendar H5 historical day key") from None
    if d.year!=year or int(d.strftime("%Y%m%d"))*10000!=stamp:
        raise ValueError("H5 historical source day escaped selected audit year")
    return d


def _source_rows(root,year,max_rows):
    """Only date slices for one year; bounded one-stock/year H5 blocks."""
    import h5py
    import numpy as np
    if year not in EXPECTED or type(year) is not int:
        raise ValueError("Year outside verified 1991-2010 research inventory")
    expect=EXPECTED[year]
    if (type(max_rows) is not int or not expect[0]<=max_rows<=400000):
        raise ValueError("Invalid exact-year candidate row budget")
    bars=[]
    seen=set()
    dates=set()
    symbols=set()
    markets=Counter()
    other_count=0
    lo_key=year*100000000
    hi_key=(year+1)*100000000
    for market in P90.MARKETS:
        path=Path(root)/"HikyuuData"/(market+"_day.h5")
        if path.is_symlink() or not path.is_file():
            raise ValueError("Original historical daily H5 missing or symlinked")
        with h5py.File(path,"r") as fh:
            grp=fh.get("data")
            if not isinstance(grp,h5py.Group):
                raise ValueError("Missing historical source H5 data group")
            for symbol in grp:
                if (type(symbol) is not str or not symbol.startswith(market.upper())
                        or CORE.symbol_id(symbol)!=symbol):
                    raise ValueError("Untrusted historical H5 security code")
                ds=grp.get(symbol)
                if (not isinstance(ds,h5py.Dataset) or ds.ndim!=1
                        or not set(CORE.H5_FIELDS).issubset(ds.dtype.names or ())
                        or not np.issubdtype(ds.dtype.fields["datetime"][0],np.integer)):
                    raise ValueError("Malformed historical H5 daily dataset")
                left,right=CORE.h5_key_slice(ds,lo_key,hi_key)
                if not 0<=left<=right<=len(ds) or right-left>366:
                    raise ValueError("Historical H5 single security/year bound exceeded")
                if left==right:
                    continue
                native_stamps=[int(x) for x in ds.fields("datetime")[left:right]]
                decoded_days=[_valid_key(n,year) for n in native_stamps]
                if any(a>=b for a,b in zip(native_stamps,native_stamps[1:])):
                    raise ValueError("Duplicate or unsorted original H5 day key")
                if not CORE.is_a_share_candidate(symbol,year):
                    other_count+=len(native_stamps)
                    continue
                symbols.add(symbol)
                # Only approved A-code data is read with OHLCVA fields.
                # This ONE bounded compound slice (max 366 rows per symbol)
                # avoids tens of thousands of random H5 record requests.
                records=ds[left:right]
                if len(records)!=len(native_stamps):
                    raise ValueError("Incomplete bounded historical H5 annual OHLCVA slice")
                for offset,(stamp,d) in enumerate(zip(native_stamps,decoded_days)):
                    key=(symbol,stamp)
                    if key in seen:
                        raise ValueError("Duplicate historical H5 candidate stockday")
                    seen.add(key)
                    # Bounded record (one original OHLCVA record, no full-history import).
                    record=records[offset]
                    if int(record["datetime"])!=stamp:
                        raise ValueError("Historical original H5 record timestamp drift")
                    raw=[int(record[k]) for k in (
                        "openPrice","highPrice","lowPrice","closePrice",
                        "transCount","transAmount")]
                    if any(n<0 for n in raw):
                        raise ValueError("Negative historical source OHLCVA")
                    op,hi,low,close=(n/1000.0 for n in raw[:4])
                    vol,amt=raw[4]*100.0,raw[5]*1000.0
                    if (min(op,hi,low,close)<=0
                            or hi+1e-8<max(op,low,close)
                            or low-1e-8>min(op,hi,close)
                            or not all(math.isfinite(x) for x in
                                        (op,hi,low,close,vol,amt))):
                        raise ValueError("Historical H5 candidate price geometry invalid")
                    ts=int(datetime(d.year,d.month,d.day,
                                    tzinfo=CORE.UTC8).timestamp()*1000)
                    bars.append({
                        "ts":ts,"symbol":symbol[2:]+"."+P90.SUFFIX[market.upper()],
                        "open":op,"high":hi,"low":low,"close":close,
                        "volume":vol,"amount":amt,
                        "source":"hikyuu_h5_historical_uncertified_private_candidate",
                    })
                    dates.add(d.isoformat())
                    markets[market.upper()]+=1
                    if len(bars)>max_rows:
                        raise ValueError("Historical H5 per-year candidate source budget exceeded")
    if ((len(bars),other_count,len(symbols),len(dates))!=expect
            or sum(markets.values())!=expect[0] or len(seen)!=expect[0]):
        raise ValueError("Historical H5 exact-year source counts differ from audited 21-year inventory")
    bars.sort(key=lambda row:(row["ts"],row["symbol"]))
    return bars,dict(sorted(markets.items())),other_count


def _candidate_schema():
    import pyarrow as pa
    return pa.schema([
        pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
        *(pa.field(k,pa.float64()) for k in FIELDS),
        pa.field("source",pa.string()),
    ])


def _validate_private_root(root):
    if (PARENT!=MODULE/"work"/"unified_parquet"/"historical_pre2011_daily_pilots"
            or not PARENT.resolve().is_relative_to(MODULE.resolve())
            or PARENT.resolve().is_relative_to(root)
            or any(p.is_symlink() for p in (
                MODULE/"work",MODULE/"work"/"unified_parquet",PARENT))):
        raise ValueError("Private annual candidate path must remain in ignored module work")
    if not PARENT.parent.is_dir() or PARENT.parent.is_symlink():
        raise ValueError("Private annual candidate parent missing or symlinked")
    if PARENT.exists() and not PARENT.is_dir():
        raise ValueError("Private annual candidate root is not a directory")


def _check_existing(year, expected, table, h5_sha, pq_sha):
    """Fail closed on ambiguous/incomplete candidate, no duplicate rewriting."""
    import pyarrow.parquet as pq
    if not PARENT.is_dir():
        return None
    matching=sorted(PARENT.glob(str(year)+"-research-*"))
    if not matching:
        return None
    if len(matching)!=1:
        raise ValueError("Multiple existing private annual stages: review required")
    folder=matching[0]
    if (folder.is_symlink() or not folder.is_dir()
            or not re.fullmatch(rf"{year}-research-[a-f0-9]{{16}}",folder.name)):
        raise ValueError("Unsafe existing private annual research stage")
    manifest=folder/"manifest.json"
    parquet=folder/"day.parquet"
    if any(p.is_symlink() or not p.is_file() for p in (manifest,parquet)):
        raise ValueError("Incomplete existing private annual research stage")
    if not 0<manifest.stat().st_size<=8192:
        raise ValueError("Unsafe annual manifest size")
    proof=json.loads(manifest.read_text(encoding="utf-8"))
    if (proof.get("format")!=FORMAT or proof.get("state")!="verified_private_candidate_not_promoted"
            or proof.get("year")!=year or proof.get("candidate_stockday_rows")!=expected
            or proof.get("h5_original_state_sha256")!=h5_sha
            or proof.get("purchased_original_state_sha256")!=pq_sha
            or proof.get("ready_for_production_merge") is not False
            or proof.get("historical_security_master_certified") is not False
            or proof.get("h5_volume_amount_price_units_certified") is not False
            or proof.get("private_stage_relative_dir")!=folder.relative_to(MODULE).as_posix()
            or proof.get("private_parquet_sha256")!=P90._digest(parquet)):
        raise ValueError("Existing private annual stage SHA/provenance changed; no overwrite")
    actual=pq.read_table(parquet)
    if actual.num_rows!=expected or not table.equals(actual,check_metadata=True):
        raise ValueError("Existing annual private candidate differs from SHA-bound original H5")
    return proof


def annual(root,year,*,write=False):
    import pyarrow as pa
    import pyarrow.parquet as pq
    if type(year) is not int or year not in EXPECTED:
        raise ValueError("Only individually audited years 1991-2010 can be selected")
    if type(write) is not bool:
        raise ValueError("Explicit boolean private annual stage permission required")
    root=Path(root).resolve()
    if (not root.is_dir() or root==MODULE or root.is_relative_to(MODULE)
            or MODULE.is_relative_to(root)):
        raise ValueError("Original market source and research module roots must not overlap")
    # Only validated original physical source keys and state, not filename claims.
    source_before=P90.h5_state(root)
    if source_before!=P90.EXPECTED_H5_STATE:
        raise ValueError("Historical H5 source state differs from 1990-2010 audited original")
    bought=P90.purchased_gate(root)
    bars,markets,other=_source_rows(root,year,EXPECTED[year][0])
    if (P90.h5_state(root)!=source_before or
            P90.purchased_gate(root)["source_file_size_mtime_state_sha256"]!=
            bought["source_file_size_mtime_state_sha256"]):
        raise ValueError("Source H5/Parquet changed while checking private annual candidate")
    table=pa.Table.from_pylist(bars,schema=_candidate_schema())
    summary={
        "format":FORMAT,"state":"read_only_annual_preflight_passed",
        "year":year,"period":"day",
        "candidate_stockday_rows":len(bars),
        "other_code_source_rows_not_staged":other,
        "market_candidate_rows":markets,
        "distinct_source_dates":EXPECTED[year][3],
        "h5_original_state_sha256":source_before,
        "purchased_original_state_sha256":bought["source_file_size_mtime_state_sha256"],
        "purchased_pre2011_all_day_files_confirmed_absent":True,
        "native_day_keys_and_OHLCVA_geometry_checked":True,
        "historical_security_master_certified":False,
        "official_historical_trading_calendar_certified":False,
        "h5_volume_amount_price_units_certified":False,
        "corporate_action_adjustment_certified":False,
        "candidate_price_factor":0.001,
        "candidate_volume_factor":100,
        "candidate_amount_factor":1000,
        "raw_OHLCVA_in_manifest":False,
        "original_market_files_written":False,
        "purchased_parquet_replaced":False,
        "h5_mirror_created":False,
        "production_pointer_modified":False,
        "ready_for_production_merge":False,
        "private_parquet_written":False,
    }
    if not write:
        return summary
    _validate_private_root(root)
    existing=_check_existing(year,len(bars),table,source_before,
                             bought["source_file_size_mtime_state_sha256"])
    if existing is not None:
        summary.update({
            "state":"already_verified_private_candidate_not_promoted",
            "private_parquet_written":False,
            "private_stage_relative_dir":existing["private_stage_relative_dir"],
            "private_parquet_sha256":existing["private_parquet_sha256"],
            "private_parquet_row_count":existing["private_parquet_row_count"],
        })
        return summary
    PARENT.mkdir(exist_ok=True)
    target=PARENT/(str(year)+"-research-"+uuid.uuid4().hex[:16])
    if target.exists() or target.is_symlink():
        raise ValueError("Private annual stage target collision")
    target.mkdir(exist_ok=False)
    dest=target/"day.parquet"
    pq.write_table(table,dest,compression="snappy",row_group_size=8192)
    decoded=pq.read_table(dest)
    if decoded.num_rows!=EXPECTED[year][0] or not table.equals(
            decoded,check_metadata=True):
        raise ValueError("New annual private Parquet exact roundtrip mismatch")
    summary.update({
        "state":"verified_private_candidate_not_promoted",
        "private_parquet_written":True,
        "private_stage_relative_dir":target.relative_to(MODULE).as_posix(),
        "private_parquet_sha256":P90._digest(dest),
        "private_parquet_row_count":decoded.num_rows,
    })
    if (P90.h5_state(root)!=source_before or
            P90.purchased_gate(root)["source_file_size_mtime_state_sha256"]!=
            bought["source_file_size_mtime_state_sha256"]):
        raise ValueError("Original H5/Parquet source drift after private annual output")
    (target/"manifest.json").write_text(
        json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
        encoding="utf-8")
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--year",type=int,required=True)
    p.add_argument("--stage-private",action="store_true")
    a=p.parse_args(argv)
    print(json.dumps(annual(a.source_root,a.year,write=a.stage_private),
                     ensure_ascii=False,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
