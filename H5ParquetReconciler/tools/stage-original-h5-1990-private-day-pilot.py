#!/usr/bin/env python3
"""1990 historical H5 A-code DAILY pilot: immutable-source gated PRIVATE staging.

Only 1990, only the existing conservative A-share code filter. The full
purchased day Parquet physical footer/key scan must certify zero pre-2011
physical stockdays; original H5 source stat must match the independently
observed 1990-2010 inventory fingerprint. Never writes purchased or H5 files,
production indexes, active pointers or reports containing market OHLCVA.

--stage-private is explicit opt-in: writes an isolated local ignored Parquet
candidate and manifest. OHLCVA normalizations are *research candidates*, NOT
certified units, dates/IPO listings, adjustments or release readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import uuid
from collections import Counter
from datetime import date, datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
PARENT=MODULE/"work"/"unified_parquet"/"historical_pre2011_daily_pilots"
EXPECTED_H5_STATE="8abbe4be67525adec7f6e6802aab705f6f79296f7197e66b5e5301827dd3a55a"
EXPECTED_PQ_STATE="feca0e42b369106cc32560908d9aa82a472f18cc9a8e846600a5b7b20edc4883"
EXPECT_YEAR=1990
EXPECT_A_STOCKDAYS=24
EXPECT_OTHER_STOCKDAYS=16
EXPECT_A_SYMBOLS=4
EXPECT_A_DATES=8
FIELDS=("open","high","low","close","volume","amount")
MARKETS=("sh","sz","bj")
SUFFIX={"SH":"XSHG","SZ":"XSHE","BJ":"XBSE"}


def _load(tag,name):
    spec=importlib.util.spec_from_file_location(tag,HERE/name)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HIST=_load("pre2011_1990_h5_history_inventory_module",
           "inventory-original-h5-1990-2010-day-keys-readonly.py")
PQ=_load("pre2011_1990_purchased_day_audit_module",
         "audit-purchased-parquet-day-pre2011-source-keys-readonly.py")
CORE=HIST.CORE


def h5_state(root):
    base=Path(root)/"HikyuuData"
    if base.is_symlink() or not base.is_dir():
        raise ValueError("Untrusted original daily H5 market root")
    files={m:base/(m+"_day.h5") for m in MARKETS}
    if any(p.is_symlink() or not p.is_file() for p in files.values()):
        raise ValueError("Missing or symlinked native daily H5 market source")
    raw={m:list(HIST._file_state(files[m])) for m in MARKETS}
    return hashlib.sha256(json.dumps(
        raw,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def purchased_gate(root):
    proof=PQ.audit(root,max_projected_rows=10000000,max_stockdays=6000000)
    if (proof.get("state")!="pre2011_purchased_parquet_original_day_keys_audited_readonly"
            or proof.get("source_file_size_mtime_state_sha256")!=EXPECTED_PQ_STATE
            or proof.get("source_files")!=24
            or proof.get("rowgroups_total")!=139
            or proof.get("rowgroups_pruned_proven_by_min_ts_ge_2011")!=139
            or proof.get("rowgroups_key_projected")!=0
            or proof.get("no_1990_2010_purchased_keys_in_audited_files") is not True
            or proof.get("all_rowgroups_have_trusted_min_ts_ge_2011") is not True
            or proof.get("pre1990_physical_rows_detected")!=0
            or proof.get("source_key_only_no_ohlcva_read") is not True
            or proof.get("market_files_written") is not False
            or proof.get("purchased_original_source_stat_unchanged") is not True):
        raise ValueError("Purchased pre-2011 physical absence/source SHA gate failed")
    return proof


def _valid_native(stamps):
    """No missing/duplicate/non-midnight or invalid Gregorian daily keys."""
    if not stamps:
        return
    if any(type(n) is not int or not 199001010000<=n<199101010000
           or n%10000 for n in stamps):
        raise ValueError("1990 original H5 timestamps not canonical daily keys")
    if any(a>=b for a,b in zip(stamps,stamps[1:])):
        raise ValueError("Original 1990 H5 source dates duplicate/not sorted")
    for n in stamps:
        text=str(n//10000)
        try:
            d=date.fromisoformat(text)
        except ValueError:
            raise ValueError("Original 1990 H5 calendar date invalid") from None
        if d.strftime("%Y%m%d")!=text or d.year!=EXPECT_YEAR:
            raise ValueError("Original 1990 H5 native date not in audit year")


def source_1990(root,max_rows=1000):
    """Bounded original daily records; NO unbounded/full historical H5 decode."""
    import h5py
    import numpy as np
    if type(max_rows) is not int or not 24<=max_rows<=1000:
        raise ValueError("Invalid 1990 H5 candidate decode budget")
    base=Path(root)/"HikyuuData"
    seen=set()
    bars=[]
    counts=Counter()
    source_days=set()
    source_symbols=set()
    other=0
    for market in MARKETS:
        p=base/(market+"_day.h5")
        if p.is_symlink() or not p.is_file():
            raise ValueError("Untrusted H5 1990 source")
        with h5py.File(p,"r") as f:
            group=f.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("Original 1990 H5 group missing")
            for symbol in group:
                if (type(symbol) is not str or not symbol.startswith(market.upper())
                        or CORE.symbol_id(symbol)!=symbol):
                    raise ValueError("Noncanonical H5 original symbol identifier")
                ds=group.get(symbol)
                if (not isinstance(ds,h5py.Dataset) or ds.ndim!=1
                        or not set(CORE.H5_FIELDS).issubset(ds.dtype.names or ())
                        or not np.issubdtype(ds.dtype.fields["datetime"][0],np.integer)):
                    raise ValueError("Original H5 1990 source dataset schema mismatch")
                lo,hi=CORE.h5_key_slice(ds,199001010000,199101010000)
                if not 0<=lo<=hi<=len(ds) or hi-lo>366:
                    raise ValueError("Unbounded/corrupt 1990 original H5 day-key slice")
                if lo==hi:
                    continue
                stamps=[int(x) for x in ds.fields("datetime")[lo:hi]]
                _valid_native(stamps)
                if not CORE.is_a_share_candidate(symbol,EXPECT_YEAR):
                    other+=len(stamps)
                    continue
                source_symbols.add(symbol)
                for pos,n in enumerate(stamps):
                    # Read one bounded source compound OHLCVA record at the
                    # exact original physical key. Price units are candidates.
                    key=(symbol,n)
                    if key in seen:
                        raise ValueError("Duplicate original H5 1990 stockday")
                    seen.add(key)
                    raw=ds[lo+pos]
                    if int(raw["datetime"])!=n:
                        raise ValueError("Original H5 native key changed mid-probe")
                    native=[int(raw[x]) for x in (
                        "openPrice","highPrice","lowPrice","closePrice",
                        "transCount","transAmount")]
                    if any(v<0 for v in native):
                        raise ValueError("Negative 1990 original H5 source value")
                    op,high,low,close=(x/1000.0 for x in native[:4])
                    volume=native[4]*100.0
                    amount=native[5]*1000.0
                    if (min(op,high,low,close)<=0
                            or high+1e-8<max(op,low,close)
                            or low-1e-8>min(op,high,close)
                            or not all(math.isfinite(v) for v in
                                        (op,high,low,close,volume,amount))):
                        raise ValueError("1990 source OHLCVA geometric sanity failed")
                    day=date.fromisoformat(str(n//10000))
                    ts=int(datetime(day.year,day.month,day.day,
                                    tzinfo=CORE.UTC8).timestamp()*1000)
                    bars.append({
                        "ts":ts,"symbol":symbol[2:]+"."+SUFFIX[market.upper()],
                        "open":op,"high":high,"low":low,"close":close,
                        "volume":volume,"amount":amount,
                        "source":"hikyuu_h5_1990_uncertified_private_candidate",
                    })
                    counts[market.upper()]+=1
                    source_days.add(day.isoformat())
                    if len(bars)>max_rows:
                        raise ValueError("1990 H5 source candidate decode budget exceeded")
    if (len(bars)!=EXPECT_A_STOCKDAYS or other!=EXPECT_OTHER_STOCKDAYS
            or len(source_symbols)!=EXPECT_A_SYMBOLS
            or len(source_days)!=EXPECT_A_DATES
            or sum(counts.values())!=EXPECT_A_STOCKDAYS):
        raise ValueError("1990 original H5 yearly 24/16 candidate evidence changed")
    bars.sort(key=lambda row:(row["ts"],row["symbol"]))
    return bars,dict(sorted(counts.items())),other


def _digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda:f.read(1024*1024),b""):
            h.update(part)
    return h.hexdigest()


def stage(root,*,write=False):
    """Plan by default. Only --stage-private may create an ignored 1990 stage."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    if type(write) is not bool:
        raise ValueError("1990 private staging requires explicit boolean consent")
    root=Path(root).resolve()
    if (not root.is_dir() or root==MODULE
            or root.is_relative_to(MODULE)
            or PARENT.resolve().is_relative_to(root)):
        raise ValueError("Original root overlaps private staging location")
    before=h5_state(root)
    if before!=EXPECTED_H5_STATE:
        raise ValueError("Original 1990-2010 H5 stat SHA changed since audited inventory")
    pq_proof=purchased_gate(root)
    bars,market_counts,others=source_1990(root)
    if h5_state(root)!=before or purchased_gate(root)[
            "source_file_size_mtime_state_sha256"]!=pq_proof[
                "source_file_size_mtime_state_sha256"]:
        raise ValueError("Original H5/PQ state drift during 1990 private read")
    manifest={
        "format":"AStockDataTools isolated uncertified 1990 H5 candidate day private v1",
        "state":"verified_private_candidate_not_promoted" if write else
                 "read_only_1990_private_candidate_preflight_passed_not_staged",
        "year":EXPECT_YEAR,"period":"day",
        "candidate_stockday_rows":len(bars),
        "other_code_source_rows_not_staged":others,
        "market_candidate_rows":market_counts,
        "distinct_source_dates":EXPECT_A_DATES,
        "h5_original_state_sha256":before,
        "purchased_original_state_sha256":
            pq_proof["source_file_size_mtime_state_sha256"],
        "purchased_pre2011_absent_in_all_24_original_day_files":True,
        "h5_1990_source_exact_key_and_OHLCVA_geometry_passed":True,
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
        "private_parquet_written":write,
    }
    if write:
        if (PARENT.is_symlink() or not PARENT.parent.is_dir()
                or PARENT.parent.is_symlink()):
            raise ValueError("Private history output root missing or symlinked")
        if PARENT.exists() and not PARENT.is_dir():
            raise ValueError("Private 1990 stage output root not a directory")
        PARENT.mkdir(exist_ok=True)
        token=uuid.uuid4().hex[:16]
        target=PARENT/("1990-research-"+token)
        if target.exists() or target.is_symlink():
            raise ValueError("1990 private stage target already exists")
        target.mkdir(exist_ok=False)
        parquet=target/"day.parquet"
        schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(n,pa.float64()) for n in FIELDS),
            pa.field("source",pa.string()),
        ])
        table=pa.Table.from_pylist(bars,schema=schema)
        pq.write_table(table,parquet,compression="snappy",row_group_size=8192)
        check=pq.read_table(parquet)
        if not table.equals(check,check_metadata=True):
            raise ValueError("1990 private stage full row/field roundtrip failed")
        manifest["private_parquet_sha256"]=_digest(parquet)
        manifest["private_parquet_row_count"]=check.num_rows
        if (h5_state(root)!=before or purchased_gate(root)[
                "source_file_size_mtime_state_sha256"]!=
                pq_proof["source_file_size_mtime_state_sha256"]):
            raise ValueError("Market source drift after private historical candidate write")
        (target/"manifest.json").write_text(
            json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
            encoding="utf-8")
    return manifest


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--stage-private",action="store_true",
                   help="Explicitly write one new ignored 1990 candidate Parquet + manifest")
    a=p.parse_args(argv)
    result=stage(a.source_root,write=a.stage_private)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
