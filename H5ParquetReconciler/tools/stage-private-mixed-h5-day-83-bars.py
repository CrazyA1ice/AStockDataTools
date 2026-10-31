#!/usr/bin/env python3
"""Privately stage exactly 83 verified H5-only MIXED-date daily bars, never originals.

Do not use the whole-date stager: purchased Parquet already has many records
for each selected day. Require SHA-bound 2011..2026 evidence, the offline
83+5/quarantine plan, the new source-key-only private manifest and its SAFE,
then RECHECK H5/PQ key sets against live originals. H5 daily unit factors
remain explicitly unverified conversion CANDIDATES. No pointers or production.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from collections import Counter
from datetime import date,datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent.resolve()
WORK=MODULE/"work"
UNIFIED=WORK/"unified_parquet"
STAGES=UNIFIED/"mixed_day_stages"
REPORTS=MODULE/"reports"
FORMAT="AStockDataTools mixed-date 83 H5-only private daily Parquet candidate stage v1"
STAGE_FORMAT="AStockDataTools mixed-date 83 private Parquet stage manifest v1"
PRICE_FACTOR=0.001
DAY_VOLUME_FACTOR=100
AMOUNT_FACTOR=1000
LIMIT=83


def load(label,name):
    spec=importlib.util.spec_from_file_location(label,HERE/name)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KEYS=load("stage_mixed_live_verified_keys","verify-live-mixed-h5-day-keys-readonly.py")
STAGE=KEYS.STAGE
CORE=STAGE.core


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def stage_dir(path):
    p=Path(path)
    if (not re.fullmatch(r"mixed_[0-9a-f]{12,32}",p.name)
            or p.exists()
            or any(x.is_symlink() for x in (WORK,UNIFIED,STAGES,p))
            or p.resolve().parent!=STAGES.resolve()):
        raise ValueError("Require NEW private mixed_<hex> stage directory")
    return p.resolve()


def read_verified_key_manifest(live_safe,manifest_path,originals,year_dates):
    """Manifest symbols are private; NEVER copy them to reports/ or Git."""
    safe_path=KEYS.safe_file(live_safe,read=True,max_bytes=1000000)
    raw_safe=safe_path.read_bytes()
    evidence=json.loads(raw_safe)
    if (evidence.get("format")!=KEYS.FORMAT
            or evidence.get("live_verified_nonquarantined_h5_only_stockdays")!=LIMIT
            or evidence.get("quarantined_stockdays_excluded_from_exact_live_keyset")!=5
            or evidence.get("original_market_files_written") is not False
            or evidence.get("private_parquet_market_rows_staged") is not False
            or evidence.get("private_or_production_active_pointer_modified") is not False
            or evidence.get("ready_for_automatic_merge") is not False
            or evidence.get("original_historical_ledger_sha256")!=sha256(originals["ledger"][1])
            or evidence.get("offline_mixed_plan_sha256")!=sha256(originals["plan"][1])):
        raise ValueError("Untrusted original live exact key proof")
    relative=evidence.get("private_key_manifest_relative_path")
    if (type(relative) is not str or ".." in Path(relative).parts
            or Path(relative).is_absolute()):
        raise ValueError("Private key manifest reference outside module")
    target=Path(manifest_path).resolve()
    expected=(MODULE/relative).resolve()
    if (target!=expected
            or target.name!="keys.json"
            or target.parent.parent.resolve()!=KEYS.PRIVATE.resolve()
            or target.is_symlink() or target.parent.is_symlink()
            or KEYS.PRIVATE.is_symlink()
            or not target.is_file()
            or not 0<target.stat().st_size<80000):
        raise ValueError("Only original module-private exact key manifest permitted")
    raw=target.read_bytes()
    if sha256(raw)!=evidence.get("private_key_manifest_sha256"):
        raise ValueError("Private key manifest SHA differs from live SAFE")
    doc=json.loads(raw)
    if (doc.get("format")!=KEYS.PRIVATE_FORMAT
            or doc.get("period")!="day"
            or doc.get("candidate_key_count")!=LIMIT
            or doc.get("h5_values_or_ohlcva_exported") is not False
            or doc.get("ready_for_unattended_staging") is not False
            or doc.get("source_purchased_parquet_priority_required") is not True
            or doc.get("source_state_stat_sha256")!=
                evidence.get("original_source_stat_sha256")
            or doc.get("offline_mixed_plan_sha256")!=sha256(originals["plan"][1])
            or doc.get("original_historical_ledger_sha256")!=
                sha256(originals["ledger"][1])):
        raise ValueError("Private exact key manifest schema/evidence inconsistent")
    rows=doc.get("candidate_symbol_day_keys")
    if type(rows) is not list or len(rows)!=LIMIT:
        raise ValueError("Expected precisely 83 private exact symbol/day keys")
    selected=[]
    seen=set()
    approved_days={y:{x["date"] for x in daylist}
                   for y,daylist in year_dates.items()}
    for item in rows:
        if type(item) is not dict or set(item)!={"date","symbol"}:
            raise ValueError("Private key entry must contain date and symbol only")
        d,s=item["date"],item["symbol"]
        if type(d) is not str or type(s) is not str:
            raise ValueError("Invalid source symbol/day types")
        try:
            dt=date.fromisoformat(d)
        except ValueError:
            raise ValueError("Invalid private source trading date") from None
        if (dt.isoformat()!=d or dt.year not in (2016,2026)
                or d not in approved_days.get(dt.year,set())
                or d=="2026-07-16"
                or not CORE.is_a_share_candidate(s,dt.year)
                or (d,s) in seen):
            raise ValueError("Duplicate or outside-quarantine exact stockday")
        seen.add((d,s))
        selected.append((s,int(d.replace("-",""))*10000))
    if sorted((d,s) for s,stamp in selected
              for d in [f"{stamp//10000:08d}"])!=[
                  (d.replace("-",""),s) for d,s in sorted(seen)]:
        raise ValueError("Inconsistent private key/date encoding")
    if {s[:2] for s,_ in selected}-{"SH","SZ","BJ"}:
        raise ValueError("Unexpected exchange prefix")
    return safe_path,raw_safe,target,raw,evidence,set(selected)


def normalize_private_h5_rows(source_root,keys):
    """Read only 83 original H5 records. Output stays private, candidate scale."""
    import h5py

    by_market={}
    for symbol,stamp in keys:
        by_market.setdefault(symbol[:2].lower(),[]).append((symbol,stamp))
    out=[]
    for market in ("sh","sz","bj"):
        path=Path(source_root)/"HikyuuData"/(market+"_day.h5")
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing or symlinked native H5 daily source")
        if not by_market.get(market):
            continue
        with h5py.File(path,"r") as f:
            group=f.get("data")
            if not isinstance(group,h5py.Group):
                raise ValueError("H5 daily group invalid")
            for symbol,stamp in sorted(by_market[market]):
                ds=group.get(symbol)
                if (not isinstance(ds,h5py.Dataset) or not set(CORE.H5_FIELDS).
                        issubset(ds.dtype.names or ())):
                    raise ValueError("Missing or malformed selected native H5 stock")
                left,right=CORE.h5_key_slice(ds,stamp,stamp+1)
                if right-left!=1 or int(ds[left]["datetime"])!=stamp:
                    raise ValueError("Selected source stockday missing/duplicate/stale")
                row=ds[left]
                raw=[int(row[field]) for field in
                     ("openPrice","highPrice","lowPrice","closePrice",
                      "transCount","transAmount")]
                if any(v<0 for v in raw):
                    raise ValueError("Negative native daily OHLCVA candidate")
                # Match the already-verified whole-day H5 staging float
                # normalization exactly; these remain candidate factors.
                op,hi,lo,cl=(v/1000.0 for v in raw[:4])
                vol=raw[4]*100.0
                amt=raw[5]*1000.0
                if (not all(math.isfinite(v) for v in (op,hi,lo,cl,vol,amt))
                        or min(op,hi,lo,cl)<=0
                        or hi+1e-8<max(op,lo,cl)
                        or lo-1e-8>min(op,hi,cl)):
                    raise ValueError("Invalid native H5 daily candidate geometry")
                d=date(stamp//100000000,(stamp//1000000)%100,(stamp//10000)%100)
                out.append({
                    "ts":int(datetime(d.year,d.month,d.day,
                                      tzinfo=CORE.UTC8).timestamp()*1000),
                    "symbol":symbol[2:]+"."+STAGE.MARKET_SUFFIX[market.upper()],
                    "open":op,"high":hi,"low":lo,"close":cl,
                    "volume":float(vol),"amount":float(amt),
                    "source":"hikyuu_h5_mixed_day_candidate",
                })
    if len(out)!=LIMIT or len({(x["ts"],x["symbol"]) for x in out})!=LIMIT:
        raise ValueError("Not precisely 83 unique candidate H5 bars")
    out.sort(key=lambda x:(x["ts"],x["symbol"]))
    return out


def verify_all_live_absence(root,year_dates,expected,h5_scanner=None):
    if h5_scanner is None:
        h5_scanner=KEYS.scan_h5_keys
    elif h5_scanner is not KEYS.scan_h5_keys_bounded:
        raise ValueError("Unknown private H5 bounded scanner mode")
    # Exact H5/PQ source sets are re-read NOW, not trusted only from the
    # private manifest or stat fingerprint. This never writes market data.
    keys=[]
    total_pq_projection=0
    for year in (2016,2026):
        active=year_dates[year]
        h=h5_scanner(root,year,active)
        p,scanned=KEYS.scan_parquet_keys(root,year,active)
        total_pq_projection+=scanned
        _summary,missing=KEYS.classify_exact_days(year,active,h,p)
        keys.extend(missing)
    if len(keys)!=LIMIT or set(keys)!=expected:
        raise ValueError("Live H5/PQ source keyset differs from SHA-bound private 83 keys")
    return total_pq_projection


def run(root,ledger,source2016,source2026,mixed_plan,
        live_safe,private_keys,output_dir,report,action,allow_stage):
    if action not in ("plan","stage") or (action=="stage")!=bool(allow_stage):
        raise ValueError("Explicit stage action and private-write flag must match")
    root=Path(root).resolve()
    output_dir=stage_dir(output_dir)
    report=KEYS.safe_file(report)
    if (root==MODULE or MODULE.is_relative_to(root)
            or root.is_relative_to(MODULE)
            or output_dir.is_relative_to(root) or report.is_relative_to(root)
            or not (root/"HikyuuData").is_dir()
            or not (root/"AllCycleAStockData"/"day").is_dir()):
        raise ValueError("Invalid original source root or unsafe private output overlap")
    originals,year_dates=KEYS.verified_existing_plan(
        ledger,source2016,source2026,mixed_plan)
    safe_path,safe_raw,private_path,keys_raw,evidence,selected=read_verified_key_manifest(
        live_safe,private_keys,originals,year_dates)
    before=KEYS.state_digest(root,(2016,2026))
    if before!=evidence["original_source_stat_sha256"]:
        raise ValueError("Original market source state changed since live 83-key proof")
    pq_scanned=verify_all_live_absence(root,year_dates,selected)
    candidate=normalize_private_h5_rows(root,selected)
    if (KEYS.state_digest(root,(2016,2026))!=before
            or safe_path.read_bytes()!=safe_raw
            or private_path.read_bytes()!=keys_raw
            or any(p.read_bytes()!=raw for p,raw in originals.values())):
        raise ValueError("Market/source SAFE/private manifest changed during verification")
    result={
        "format":FORMAT,
        "action":action,
        "state":"private_stage_prepared_not_promoted" if action=="stage" else "plan_passed_no_stage",
        "verified_mixed_h5_only_stockday_bars":LIMIT,
        "verified_year_counts":{"2016":1,"2026":82},
        "quarantined_2026_07_16_stockday_bars_not_included":5,
        "purchased_source_ts_symbol_rows_projected":pq_scanned,
        "source_stat_sha256":before,
        "private_key_manifest_sha256":sha256(keys_raw),
        "source_live_key_safe_sha256":sha256(safe_raw),
        "offline_mixed_plan_sha256":sha256(originals["plan"][1]),
        "source_conversion_price_factor_candidate":PRICE_FACTOR,
        "source_conversion_daily_volume_factor_candidate":DAY_VOLUME_FACTOR,
        "source_conversion_amount_factor_candidate":AMOUNT_FACTOR,
        "candidate_source_units_certified":False,
        "stage_parquet_created":action=="stage",
        "h5_mirror_created":False,
        "source_market_files_written":False,
        "purchased_parquet_replaced":False,
        "private_or_production_active_pointer_modified":False,
        "ready_for_automatic_market_merge":False,
        "private_stage_relative_dir":
            output_dir.relative_to(MODULE).as_posix() if action=="stage" else None,
    }
    if action=="stage":
        import pyarrow as pa
        import pyarrow.parquet as pq

        if output_dir.exists():
            raise ValueError("Stage directory appeared while source scan ran")
        fields=STAGE.SCHEMA_FIELDS
        schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(n,pa.float64()) for n in
              ("open","high","low","close","volume","amount")),
            pa.field("source",pa.string())])
        if tuple(schema.names)!=fields:
            raise ValueError("Native candidate Parquet schema mismatch")
        table=pa.Table.from_pylist(candidate,schema=schema)
        output_dir.parent.mkdir(parents=True,exist_ok=True)
        output_dir.mkdir(exist_ok=False)
        pq_path=output_dir/"day.parquet"
        pq.write_table(table,pq_path,compression="snappy")
        roundtrip=pq.read_table(pq_path)
        if not table.equals(roundtrip,check_metadata=True):
            raise ValueError("Private candidate Parquet write/read mismatch")
        if KEYS.state_digest(root,(2016,2026))!=before:
            raise ValueError("Source changed during private candidate Parquet write")
        if (safe_path.read_bytes()!=safe_raw or private_path.read_bytes()!=keys_raw
                or any(p.read_bytes()!=raw for p,raw in originals.values())):
            raise ValueError("Trusted evidence changed during private write")
        result["private_staged_parquet_sha256"]=STAGE.file_digest(pq_path)
        result["stage_row_count"]=table.num_rows
        stage_meta={
            "format":STAGE_FORMAT,
            "status":"private_candidate_not_active",
            "period":"day",
            "source_time_schema":"H5 Beijing midnight candidate (original purchased raw UTC midnight preserved)",
            "private_stage_sha256":result["private_staged_parquet_sha256"],
            "source_live_key_safe_sha256":sha256(safe_raw),
            "private_key_manifest_sha256":sha256(keys_raw),
            "source_market_stat_sha256":before,
            "staged_bar_count":LIMIT,
            "candidate_units_certified":False,
            "source_market_files_written":False,
            "purchased_parquet_replaced":False,
            "active_pointer_changed":False,
            "not_ready_for_production":True,
        }
        (output_dir/"manifest.json").write_text(
            json.dumps(stage_meta,ensure_ascii=False,indent=2,sort_keys=True)+"\n",
            encoding="utf-8")
    with report.open("x",encoding="utf-8") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,sort_keys=True)
        stream.write("\n")
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-root",type=Path,required=True)
    ap.add_argument("--history-ledger",type=Path,required=True)
    ap.add_argument("--source-2016",type=Path,required=True)
    ap.add_argument("--source-2026",type=Path,required=True)
    ap.add_argument("--mixed-plan",type=Path,required=True)
    ap.add_argument("--live-safe",type=Path,required=True)
    ap.add_argument("--private-keys",type=Path,required=True)
    ap.add_argument("--stage-dir",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--action",choices=("plan","stage"),required=True)
    ap.add_argument("--allow-new-private-parquet-stage",action="store_true")
    ap.add_argument("--read-only-original-market-sources",action="store_true",required=True)
    args=ap.parse_args(argv)
    try:
        result=run(
            args.source_root,args.history_ledger,args.source_2016,
            args.source_2026,args.mixed_plan,args.live_safe,
            args.private_keys,args.stage_dir,args.out,
            args.action,args.allow_new_private_parquet_stage)
        print("Mixed day candidate:",result["action"],
              "verified bars:",result["verified_mixed_h5_only_stockday_bars"])
        print("Private source-only stage created:",result["stage_parquet_created"])
        print("SAFE:",args.out)
        print("Original H5/Parquet, production routes, private pointers unchanged.")
    except (ValueError,OSError,TypeError,KeyError,ImportError,
            ModuleNotFoundError,OverflowError):
        ap.error("83-key mixed private candidate stage fail-closed; no original market writes")


if __name__=="__main__":
    main()
