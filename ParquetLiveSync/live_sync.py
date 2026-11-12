#!/usr/bin/env python3
"""A-share DAY Parquet extension using a-stock-data v3.10.4 TDX recipe.

The 2026-10-13 eight-period physical dataset is immutable. This tool
appends a SHA-audited DAY-only overlay AFTER its cutoff; a read-only Arrow
view combines the verified legacy day fragments and new physical daily
Parquet files without modifying the original purchased source or H5.

No claim that Tencent minute bars are full OHLCVA: that endpoint has NO
amount. Non-day periods remain unchanged until a complete source exists.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date,datetime,timedelta,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
from typing import Callable

from tdx_source import MissingPackage,download_daily,parse_daily_zip,sha256
import local_layout as LOCAL

HERE=Path(__file__).resolve().parent
REPO=HERE.parent
BASE_MODULE=REPO/"H5ParquetReconciler"
BASE_SHA="a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01"
BASE_DAY=date(2026,10,13)
BASE=BASE_MODULE/"work"/"unified_parquet"/"datasets"/("eight_cycle_asof_20261013_"+BASE_SHA[:16])/"manifest.json"
PERIODS=("1min","5min","15min","30min","60min","day","week","month")
FIELDS=("ts","symbol","open","high","low","close","volume","amount")
WORK=HERE/"work"
STATE=WORK/"state.json"
FORMAT="a_stock_data_tdx_day_live_parquet_overlay_v1"
CN=timezone(timedelta(hours=8))
LATEST_SOURCE="simonlin1212/a-stock-data v3.10.4 §1.3 (Apache-2.0)"
CALIBRATION_DAYS=(date(2026,9,30),date(2026,9,24),date(2026,10,13))

def canonical(obj):
    return (json.dumps(obj,ensure_ascii=False,sort_keys=True,
                       separators=(",",":"),allow_nan=False)+"\n").encode("utf-8")

def file_sha(p):
    digest=hashlib.sha256()
    with Path(p).open("rb") as file:
        for block in iter(lambda:file.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()

def checked_path(base,relative):
    if (type(relative) is not str or not relative
            or "\\" in relative or relative.startswith("/")
            or any(t in ("",".","..") for t in relative.split("/"))):
        raise ValueError("Untrusted relative Parquet file path")
    base=Path(base).resolve()
    path=base.joinpath(*relative.split("/"))
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base):
        raise ValueError("Missing or redirected physical Parquet source")
    return path

def baseline():
    if BASE.is_symlink() or not BASE.is_file() or BASE.stat().st_size>16_000_000:
        raise FileNotFoundError("Accepted 2026-10-13 original 8-period Parquet manifest missing")
    doc=json.loads(BASE.read_bytes())
    payload=doc.get("payload")
    if (not isinstance(payload,dict)
            or payload.get("asof_inclusive")!=BASE_DAY.isoformat()
            or doc.get("dataset_sha256")!=BASE_SHA
            or sha256(canonical(payload))!=BASE_SHA
            or payload.get("periods")!=list(PERIODS)
            or not payload.get("period_physical_files",{}).get("day")):
        raise ValueError("Original eight-period physical dataset SHA changed")
    return payload

def parquet_schema():
    import pyarrow as pa
    return pa.schema([pa.field("ts",pa.int64()),
                      pa.field("symbol",pa.string()),
                      *(pa.field(name,pa.float64()) for name in FIELDS[2:])])

def baseline_day_files(doc):
    result=[]
    for entry in doc["period_physical_files"]["day"]:
        if (entry.get("root_kind")!="private_module"
                or entry.get("source_class")!="modern_16yr_purchased_first_day"):
            raise ValueError("Original day source not approved modern purchased-first")
        result.append(checked_path(BASE_MODULE,entry["relative_file"]))
    return result

def source_day_ts(day):
    d=datetime(day.year,day.month,day.day,tzinfo=CN)
    return int(d.timestamp()*1000)

def baseline_overlap(doc,day):
    """Read only one 2026 date from accepted physical daily Parquet; no rewrites."""
    import pyarrow.dataset as ds
    wanted=source_day_ts(day)
    dataset=ds.dataset([str(p) for p in baseline_day_files(doc)],
                       format="parquet",schema=parquet_schema())
    table=dataset.to_table(
        columns=list(FIELDS),
        filter=(ds.field("ts")>=wanted)&(ds.field("ts")<wanted+86400000),
        use_threads=False)
    if table.num_rows<1000 or table.num_rows>30000:
        raise ValueError("Original complete daily purchased source date missing")
    seen={}
    for item in table.to_pylist():
        sym=item["symbol"]
        if (type(sym) is not str
                or re.fullmatch(r"(SH|SZ|BJ)\d{6}",sym) is None):
            continue
        if sym in seen:
            raise ValueError("Original verified day contains duplicate symbol/day")
        seen[sym]=item
    if len(seen)<1000:
        raise ValueError("Not enough original day A-share symbols for source calibration")
    return seen

def infer_factor(pairs,candidates,*,absolute):
    """Select a *single* defensible source-unit multiplier; never guess zero."""
    pool=[(float(old),float(src)) for old,src in pairs
          if src is not None and old is not None and
          math.isfinite(float(old)) and math.isfinite(float(src))
          and float(old)>absolute*10 and float(src)>absolute*10]
    if len(pool)<30:
        raise ValueError("Insufficient nonzero exchange turnovers for unit calibration")
    ranked=[]
    for factor in candidates:
        hits=sum(abs(left-right*factor)<=max(absolute,abs(left)*0.02)
                 for left,right in pool)
        ranked.append((hits/len(pool),factor))
    ranked.sort(reverse=True)
    if ranked[0][0]<0.90 or (
            len(ranked)>1 and ranked[0][0]-ranked[1][0]<0.20):
        raise ValueError("Local vendor Parquet and TDX units have no unique stable 90% match")
    return ranked[0][1],round(ranked[0][0],4),len(pool)

def compare_units(original,external):
    paired=[(original[r["symbol"]],r) for r in external
            if r["symbol"] in original]
    if len(paired)<120:
        raise ValueError("TDX and original private Parquet have too few common stock codes")
    checked=0
    price_good=0
    for older,newer in paired:
        p=float(older["close"])
        q=float(newer["close"])
        if p>0 and q>0 and math.isfinite(p) and math.isfinite(q):
            checked+=1
            if abs(p-q)<=max(.04,.0075*abs(p)):
                price_good+=1
    if checked<100 or price_good/checked<0.88:
        raise ValueError("Close prices disagree: possible adjusted/unadjusted or wrong trading date")
    # Compare turnover quantities only on matching close prices so that
    # migrated securities/reused codes and stale bars cannot bias the unit.
    good=[(a,b) for a,b in paired if a["close"]>0 and
          abs(float(a["close"])-float(b["close"]))<=
             max(.04,.0075*abs(float(a["close"])))]
    # Preserve the existing supplier's DAY timestamp convention (00:00,
    # 09:30, etc.) instead of assuming all daily source timestamps are
    # always midnight. Validate an exact common local-day offset.
    offsets={int(older["ts"])-source_day_ts(
        date.fromisoformat(newer["date"])) for older,newer in good}
    if (len(offsets)!=1 or not 0<=next(iter(offsets))<86400000):
        raise ValueError("Existing day Parquet timestamp convention inconsistent")
    stamp_offset=next(iter(offsets))
    volume= [(x["volume"],y["volume_shares"]) for x,y in good]
    amount= [(x["amount"],y["amount_yuan"]) for x,y in good]
    vf,vs,vn=infer_factor(volume,[.0001,.001,.01,.1,1,10,100,1000,10000],
                          absolute=100)
    af,aas,an=infer_factor(amount,[.0001,.001,.01,.1,1,10,100,1000,10000],
                           absolute=1000)
    return {"tdx_shares_to_local_volume":vf,
            "tdx_yuan_to_local_amount":af,
            "local_day_ts_offset_ms":stamp_offset,
            "price_match_fraction":round(price_good/checked,4),
            "matched_prices":checked,"volume_fit":vs,"amount_fit":aas,
            "volume_samples":vn,"amount_samples":an,
            "source_raw_volume":"shares","source_raw_amount":"CNY_yuan",
            "local_vendor_units_proven_by_overlap_only":True,
            "global_historical_or_vendor_2011_2026_units_certified":False}

def initial_state():
    return {"format":FORMAT,"base_dataset_sha256":BASE_SHA,
            "base_day":BASE_DAY.isoformat(),
            "adapter":LATEST_SOURCE,"calibration":None,
            "days":{},"unavailable_404_last_attempt":{},
            "local_month_materializations":{},
            "original_purchased_parquet_or_H5_modified":False,
            "production_activated":False,
            "updated_periods":["day"],
            "unsupported_full_OHLCVA_from_Tencent":["1min","5min","15min",
                                                   "30min","60min","week","month"]}

def read_state():
    if STATE.is_symlink():
        raise ValueError("Linked persistent state")
    if not STATE.exists():
        return initial_state()
    if STATE.stat().st_size>10_000_000:
        raise ValueError("Persistent live Parquet state too large")
    doc=json.loads(STATE.read_bytes())
    if (doc.get("format")!=FORMAT or doc.get("base_dataset_sha256")!=BASE_SHA
            or doc.get("base_day")!=BASE_DAY.isoformat()
            or type(doc.get("days")) is not dict
            or doc.get("production_activated") is not False):
        raise ValueError("Persistent live Parquet state not accepted")
    materialized=doc.get("local_month_materializations",{})
    if type(materialized) is not dict:
        raise ValueError("Local Parquet monthly physical receipts must be a mapping")
    for key,info in materialized.items():
        if (type(key) is not str or re.fullmatch(
                r"day/[0-9]{4}-(0[1-9]|1[0-2])\.parquet",key) is None
                or type(info) is not dict):
            raise ValueError("Invalid local monthly Parquet target entry")
        target=Path(info["target"])
        if target.is_symlink():
            raise ValueError("Committed local monthly Parquet target redirected")
        if not target.is_file():
            # After explicit 12-month -> annual archival, the original
            # monthly file is safely stored under a SHA-backed private
            # archive. Validate BOTH the immutable month backup identity
            # and annual physical output instead of rejecting rollover.
            period,filename=key.split("/")
            year=int(filename[:4])
            plan=WORK/"rollover"/str(year)/(period+"-annual-commit.json")
            annual=target.with_name(str(year)+".parquet")
            if (plan.is_symlink() or not plan.is_file()
                    or annual.is_symlink() or not annual.is_file()):
                raise ValueError("Committed month missing without accepted yearly archive")
            receipt=json.loads(plan.read_bytes())
            old=next((x for x in receipt.get("original_months",[])
                      if x.get("name")==filename),None)
            if (receipt.get("year")!=year or receipt.get("period")!=period
                    or old is None or old.get("sha256")!=info.get("sha256")
                    or LOCAL.hash_file(annual)!=receipt.get("annual_sha256")
                    or not Path(old.get("backup_path","")).is_file()
                    or LOCAL.hash_file(old["backup_path"])!=info.get("sha256")):
                raise ValueError("Year-end archive lost original month or annual SHA")
            continue
        current=LOCAL.hash_file(target)
        if current!=info.get("sha256"):
            parts=key.removeprefix("day/").removesuffix(".parquet")
            journal=WORK/"transactions"/"day"/(parts+".json")
            if journal.is_symlink() or not journal.is_file():
                raise ValueError("Physical monthly Parquet has changed outside updater")
            trans=json.loads(journal.read_bytes())
            if (trans.get("old_sha256")!=info.get("sha256")
                    or trans.get("new_sha256")!=current):
                raise ValueError("Changed physical monthly Parquet has no valid interrupted transaction")
    for label,entry in doc["days"].items():
        candidate=date.fromisoformat(label)
        if candidate<=BASE_DAY or not isinstance(entry,dict):
            raise ValueError("Live overlay contains date colliding with original pinned dataset")
        path=checked_path(WORK,entry["file"])
        receipt=path.with_suffix(".json")
        if (receipt.is_symlink() or not receipt.is_file()
                or type(entry.get("receipt_sha256")) is not str
                or file_sha(receipt)!=entry["receipt_sha256"]):
            raise ValueError("Already accepted incremental day receipt checksum changed")
        proof=json.loads(receipt.read_bytes())
        if (proof.get("date")!=label or
                proof.get("file")!=entry["file"] or
                proof.get("raw_zip_sha256")!=entry.get("source_zip_sha256")):
            raise ValueError("Incremental source receipt identity differs")
        if (entry.get("sha256")!=file_sha(path)
                or type(entry.get("rows")) is not int
                or entry["rows"]<1 or entry["rows"]>15000
                or proof.get("rows")!=entry["rows"]
                or proof.get("sha256")!=entry["sha256"]):
            raise ValueError("Already accepted incremental day Parquet checksum changed")
    return doc

def save_state(doc):
    WORK.mkdir(parents=True,exist_ok=True)
    temp=STATE.with_name("state.json.part")
    if temp.is_symlink():
        raise ValueError("Linked temporary state")
    temp.write_bytes(canonical(doc))
    temp.replace(STATE)

def get_calibration(doc,source_root,log):
    if doc["calibration"]:
        out=doc["calibration"]
        if (out.get("baseline_sha256")!=BASE_SHA or
                out.get("anchor_day") not in [x.isoformat() for x in CALIBRATION_DAYS]):
            raise ValueError("Persistent source-vendor unit calibration identity changed")
        return out
    cache=WORK/"downloads"
    rejected_anchors=[]
    for day in CALIBRATION_DAYS:
        try:
            raw,provenance=download_daily(day,cache,logger=log)
            external,source_meta=parse_daily_zip(raw,day)
        except MissingPackage:
            log("校准基准日未发布："+str(day)+"；改试另一已验收交易日")
            continue
        except ValueError as exc:
            # One sampled baseline source ZIP can contain exceptional
            # records; reject that whole anchor, keep its evidence, and
            # try a DIFFERENT already purchased/accepted trading day.
            # Do not weaken downstream real-day data validation.
            rejected_anchors.append({"date":str(day),"reason":str(exc)[:600]})
            log("TDX_CALIBRATION_ANCHOR_REJECTED "+str(day)+" "+str(exc))
            continue
        log("TDX_CALIBRATION_SOURCE_TRADING_COUNT "+str(day)+" "+
            json.dumps(source_meta["a_share_by_market"],sort_keys=True)+
            " suspended_zero_turnover="+
            json.dumps(source_meta.get(
                "zero_turnover_nontrading_a_shares_by_market",{}),
                sort_keys=True))
        existing=baseline_overlap(source_root,day)
        try:
            factors=compare_units(existing,external)
        except ValueError as exc:
            rejected_anchors.append({"date":str(day),"reason":str(exc)[:600]})
            log("TDX_CALIBRATION_UNIT_OR_PRICE_REJECTED "+str(day)+" "+str(exc))
            continue
        doc["calibration"]={
            **factors,"baseline_sha256":BASE_SHA,
            "anchor_day":day.isoformat(),
            "anchor_raw_zip_sha256":source_meta["raw_zip_sha256"],
            "anchor_source":source_meta["origin_url"],
            "rejected_calibration_anchor_days":rejected_anchors,
            "source_adapter_version":LATEST_SOURCE}
        save_state(doc)
        log("自动量纲对照通过："+day.isoformat()+
            " volume×"+str(factors["tdx_shares_to_local_volume"])+
            " amount×"+str(factors["tdx_yuan_to_local_amount"]))
        return doc["calibration"]
    raise ValueError("所有已验收重叠日校准均未通过，拒绝猜测价格或量纲；"
                     "候选失败："+json.dumps(rejected_anchors,ensure_ascii=False))

def prepare_day(external,day,units):
    import pyarrow as pa
    values={
        "ts":[],"symbol":[],"open":[],"high":[],
        "low":[],"close":[],"volume":[],"amount":[]}
    factor_v=units["tdx_shares_to_local_volume"]
    factor_a=units["tdx_yuan_to_local_amount"]
    seen=set()
    for bar in external:
        symbol=bar["symbol"]
        if symbol in seen:
            raise ValueError("Duplicate TDX A-share symbol on one trading date")
        seen.add(symbol)
        offset=int(units.get("local_day_ts_offset_ms",0))
        if not 0<=offset<86400000:
            raise ValueError("Unproven local Parquet DAY timestamp alignment")
        values["ts"].append(source_day_ts(day)+offset)
        values["symbol"].append(symbol)
        for field in ("open","high","low","close"):
            values[field].append(float(bar[field]))
        values["volume"].append(float(bar["volume_shares"])*factor_v)
        values["amount"].append(float(bar["amount_yuan"])*factor_a)
    schema=parquet_schema()
    table=pa.table(values,schema=schema)
    if table.num_rows!=len(external):
        raise ValueError("Source-to-Arrow day row conservation failed")
    return table

def put_day(day,table,source_meta,doc):
    import pyarrow.parquet as pq
    rel="incremental/day/year="+str(day.year)+"/"+day.isoformat()+".parquet"
    folder=WORK/"incremental"/"day"/("year="+str(day.year))
    folder.mkdir(parents=True,exist_ok=True)
    output=checked_path(WORK,rel) if (WORK/rel).exists() else WORK/rel
    receipt=output.with_suffix(".json")
    if output.is_symlink() or receipt.is_symlink():
        raise ValueError("Linked incremental day output is refused")
    # An OS/process crash can occur AFTER new Parquet was renamed but
    # BEFORE the receipt/state is published. If the existing physical file
    # is byte-valid and exactly equal to the current source + calibrated
    # Arrow columns, recover it in-place instead of overwriting.
    if output.exists():
        existing=pq.read_table(output,columns=list(FIELDS))
        if existing.schema!=parquet_schema() or not existing.equals(table):
            raise ValueError("Conflicting/orphan DAY physical data differs from the official source")
    else:
        if receipt.exists():
            raise ValueError("Orphan receipt exists without corresponding DAY Parquet")
        temp=output.with_suffix(".parquet.part")
        if temp.is_symlink():
            raise ValueError("Linked incremental temporary Parquet path refused")
        if temp.exists():
            temp.unlink()
        pq.write_table(table,temp,compression="zstd",row_group_size=16384)
        # ParquetFile owns an open local file handle. Windows refuses
        # os.replace() while that reader still holds the temp file (WinError 32).
        # Always close it BEFORE the atomic rename, including on validation
        # failure. Do not rely on CPython garbage collection or Linux semantics.
        check=pq.ParquetFile(temp)
        try:
            if (check.schema_arrow!=parquet_schema()
                    or check.metadata.num_rows!=table.num_rows):
                raise ValueError("New Parquet footer schema/row count incorrect")
        finally:
            check.close()
        temp.replace(output)
    digest=file_sha(output)
    proof={"date":day.isoformat(),"file":rel,
           "sha256":digest,"rows":table.num_rows,
           "raw_zip_sha256":source_meta["raw_zip_sha256"],
           "origin":source_meta["origin_url"],
           "a_share_counts_by_market":source_meta["a_share_by_market"],
           "nontrading_a_share_zero_turnover_by_market":
               source_meta.get("zero_turnover_nontrading_a_shares_by_market",{}),
           "calibration":doc["calibration"],"base_dataset_sha256":BASE_SHA,
           "original_Parquet_files_unchanged":True,"source_values_adj":"none"}
    if receipt.exists():
        old_proof=json.loads(receipt.read_bytes())
        if old_proof!=proof:
            raise ValueError("Previously written DAY Parquet receipt differs from source")
    else:
        temp_receipt=receipt.with_suffix(".json.part")
        if temp_receipt.is_symlink():
            raise ValueError("Linked temporary source receipt refused")
        temp_receipt.write_bytes(canonical(proof))
        temp_receipt.replace(receipt)
    doc["days"][day.isoformat()]={"file":rel,"sha256":digest,"rows":table.num_rows,
                                  "receipt_sha256":file_sha(receipt),
                                  "source_zip_sha256":source_meta["raw_zip_sha256"]}
    doc["unavailable_404_last_attempt"].pop(day.isoformat(),None)
    save_state(doc)
    return proof

def trusted_october_pre_cutoff(payload):
    """Seed the new 2026-10 monthly physical Parquet using ACCEPTED private
    purchased-first DAY values through 2026-10-13. This is essential when
    local stock/AllCycleAStockData/day ends at 2026-09.parquet.
    """
    import pyarrow.dataset as ds
    from datetime import date as D
    source=ds.dataset([str(p) for p in baseline_day_files(payload)],
                      format="parquet",schema=parquet_schema())
    begin=source_day_ts(D(2026,10,1))
    after=source_day_ts(D(2026,10,14))
    rows=source.to_table(
        columns=list(FIELDS),
        filter=(ds.field("ts")>=begin)&(ds.field("ts")<after),
        use_threads=False)
    if not 1000<=rows.num_rows<=150000:
        raise ValueError("Missing accepted original 2026-10-01..13 DAY physical rows")
    LOCAL.checked_records(rows,target_year=2026,target_month=10)
    return rows

def materialize_day_in_original_layout(root,day,doc,baseline_payload,logger):
    """Post-SHA single-day upsert into actual AllCycleAStockData/day/YYYY-MM.

    Never called by the legacy overlay-only CLI. Explicit GUI / CLI opt-in
    only. Fully backed up, staged, readback verified, atomic replacement.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    if day<=BASE_DAY:
        raise ValueError("Cannot rewrite pinned purchased source cutoff day")
    key=day.isoformat()
    entry=doc.get("days",{}).get(key)
    if entry is None:
        raise ValueError("No already SHA-verified daily official overlay")
    physical=checked_path(WORK,entry["file"])
    supplied=pq.read_table(physical,columns=list(FIELDS))
    if supplied.num_rows!=entry["rows"] or supplied.schema!=parquet_schema():
        raise ValueError("Cannot materialize a wrong-schema or partial official source")
    LOCAL.checked_records(supplied,target_year=day.year,target_month=day.month)
    store=LOCAL.storage_root(root)
    current=datetime.now(CN).year
    commits=doc.setdefault("local_month_materializations",{})
    target=store/"day"/f"{day.year}-{day.month:02}.parquet"
    state_key=target.relative_to(store).as_posix()
    annual=store/"day"/f"{day.year}.parquet"
    if day.year>current or day.year<current-1:
        raise ValueError("Direct local day update supports active or immediately previous year only")
    if day.year<current:
        if annual.exists():
            # The canonical month has already been consolidated. Preserve
            # the accepted historical annual SHA and never overwrite it
            # from a late external package. Previously committed month
            # overlays are included by the SHA-validated archive receipt.
            if state_key not in commits:
                raise ValueError("Late historical DAY not present in accepted yearly archive")
            import pyarrow.dataset as ds
            low=source_day_ts(day)
            high=source_day_ts(day+timedelta(days=1))
            archived=ds.dataset(str(annual),format="parquet").to_table(
                columns=["ts","symbol"],
                filter=(ds.field("ts")>=low)&(ds.field("ts")<high),
                use_threads=False)
            existing_keys={(t,LOCAL.normal_symbol(symbol))
                           for t,symbol in zip(archived["ts"].to_pylist(),
                                               archived["symbol"].to_pylist())}
            new_keys={(t,LOCAL.normal_symbol(symbol))
                      for t,symbol in zip(supplied["ts"].to_pylist(),
                                          supplied["symbol"].to_pylist())}
            if not new_keys.issubset(existing_keys):
                raise ValueError("Archived annual day is missing late official-source keys; cannot silently skip")
            logger("SKIP_ALREADY_ARCHIVED_LOCAL_DAY "+key+
                   " VERIFIED_ANNUAL="+str(annual))
            return {"target":str(annual),"added":0,
                    "archived_year":True}
        has_months=any((store/"day").glob(f"{day.year}-??.parquet"))
        if not has_months:
            raise ValueError("Previous year DAY cannot be updated: no pending monthly files")
        logger("PREVIOUS_YEAR_MONTHLY_PENDING_ROLLOVER "+key)
    if day.year==2026 and day.month==10 and state_key not in commits:
        # Seed original purchased-first Oct1..13 exactly ONCE. Later Oct
        # source days merge into this already persistent month; do not
        # rescan all accepted 2011-2026 historical daily fragments each day.
        earlier=trusted_october_pre_cutoff(baseline_payload)
        supplied=pa.concat_tables([earlier,supplied])
        LOCAL.checked_records(supplied,target_year=2026,target_month=10)
    previous=commits.get(state_key)
    if previous:
        digest=LOCAL.hash_file(target) if target.is_file() else None
        if digest!=previous.get("sha256"):
            # Permit recovery after atomic physical replace but before
            # state.json was updated: the private journal proves what
            # should now be installed in the named physical target.
            journal=WORK/"transactions"/"day"/f"{day.year}-{day.month:02}.json"
            if not journal.is_file() or journal.is_symlink():
                raise ValueError("Local market Parquet changed outside accepted month transaction")
            proof=json.loads(journal.read_bytes())
            if (proof.get("new_sha256")!=digest
                    or proof.get("old_sha256")!=previous["sha256"]):
                raise ValueError("Live Parquet month differs from old committed SHA")
    receipt=LOCAL.write_month(
        root,"day",day.year,day.month,supplied,WORK,current_year=day.year)
    commits[state_key]={"sha256":receipt["sha256"],
                        "target":str(target),
                        "row_count":receipt["total_rows"],
                        "calendar_month":f"{day.year}-{day.month:02}",
                        "source":"accepted TDX DAY overlay plus trusted old October subset",
                        "last_materialized_source_day":key}
    doc["original_purchased_parquet_or_H5_modified"]=True
    doc["original_H5_modified"]=False
    doc["actual_local_AllCycleAStockData_day_updated"]=True
    save_state(doc)
    logger("PASS_LOCAL_DAY_MONTH_PARQUET "+key+
           " TARGET="+str(target)+
           " NEW_KEYS="+str(receipt["added"])+
           " KEPT_LOCAL_KEYS="+str(receipt["same_key"])+
           " MONTH_ROWS="+str(receipt["total_rows"]))
    return receipt

def latest_yesterday():
    """Today's package is only eligible after 20:00 China time.

    A 404 remains unpublished/absent, NOT a market-calendar conclusion.
    """
    current=datetime.now(CN)
    return current.date() if current.hour>=20 else current.date()-timedelta(days=1)

def safe_window(start,end,max_days=60):
    if start<=BASE_DAY or start>end or end>latest_yesterday():
        raise ValueError("New day-only overlay window must be after 2026-10-13 and no later than yesterday CN")
    if (end-start).days+1>max_days or max_days>180 or max_days<1:
        raise ValueError("Date range exceeds bounded window limit")

def _sync_unlocked(root,start,end,*,logger=print,stop=None,
                   max_days=60,materialize_local=False):
    payload=baseline()
    safe_window(start,end,max_days)
    doc=read_state()
    cal=get_calibration(doc,payload,logger)
    counters=Counter()
    day=start
    while day<=end:
        if stop is not None and stop():
            logger("STOPPED_AFTER_COMMITTED_DAY; safe to resume")
            break
        key=day.isoformat()
        if key in doc["days"]:
            logger("SKIP_ALREADY_SHA_VERIFIED "+key)
            counters["already_verified"]+=1
            if materialize_local:
                materialize_day_in_original_layout(
                    root,day,doc,payload,logger)
                counters["local_month_materializations_checked"]+=1
            day+=timedelta(days=1)
            continue
        logger("FETCH_TDX_DAY "+key)
        try:
            raw,_=download_daily(day,WORK/"downloads",logger=logger)
        except MissingPackage:
            logger("RETRYABLE_404_NOT_A_HOLIDAY_PROOF "+key)
            counters["not_yet_available"]+=1
            doc["unavailable_404_last_attempt"][key]=datetime.now(CN).isoformat()
            save_state(doc)
            day+=timedelta(days=1)
            continue
        external,meta=parse_daily_zip(raw,day)
        nontrading=meta.get("zero_turnover_nontrading_a_shares_by_market",{})
        if sum(nontrading.values()):
            logger("TDX_ZERO_TURNOVER_NOT_A_TRADED_BAR "+key+" "+
                   json.dumps(nontrading,ensure_ascii=False,sort_keys=True))
        table=prepare_day(external,day,cal)
        proof=put_day(day,table,meta,doc)
        if materialize_local:
            materialize_day_in_original_layout(
                root,day,doc,payload,logger)
            counters["local_month_materializations_checked"]+=1
        counters["new_days"]+=1
        counters["new_daily_rows"]+=proof["rows"]
        logger("PASS_NEW_DAY_PARQUET "+key+" ROWS="+str(proof["rows"])+
               " SOURCE_SHA="+meta["raw_zip_sha256"][:16])
        day+=timedelta(days=1)
    result={"status":"day_overlay_commits_or_skips_complete",
            "window":[start.isoformat(),end.isoformat()],
            "new_days":counters["new_days"],
            "new_daily_rows":counters["new_daily_rows"],
            "already_verified":counters["already_verified"],
            "source_not_yet_available_404":counters["not_yet_available"],
            "latest_overlaid_day":max(doc["days"]) if doc["days"] else None,
            "total_day_overlay_rows":sum(x["rows"] for x in doc["days"].values()),
            "all_eight_periods_up_to_date":False,
            "only_day_period_extended":True,
            "physical_local_AllCycleAStockData_day_written":bool(materialize_local),
            "local_day_months_checked":counters["local_month_materializations_checked"],
            "original_H5_unchanged":True,
            "original_purchased_parquet_historic_file_units_preserved":True}
    logger("PARQUET_LIVE_SYNC_RESULT="+json.dumps(result,ensure_ascii=False,sort_keys=True))
    return result

@contextmanager
def exclusive_writer():
    """Hold a 1-byte OS lock so GUI, CLI, and future scheduled jobs cannot race."""
    WORK.mkdir(parents=True,exist_ok=True)
    lock=WORK/"exclusive_writer.lock"
    if WORK.is_symlink() or lock.is_symlink():
        raise ValueError("Linked Parquet updater workspace/lock refused")
    with lock.open("a+b") as file:
        file.seek(0,2)
        if file.tell()==0:
            file.write(b"0")
            file.flush()
        file.seek(0)
        try:
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another Parquet GUI/CLI update is already running") from exc
        try:
            yield
        finally:
            if os.name=="nt":
                msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(file.fileno(),fcntl.LOCK_UN)

def sync(root,start,end,*,logger=print,stop=None,max_days=60,
         materialize_local=False):
    with exclusive_writer():
        return _sync_unlocked(root,start,end,logger=logger,stop=stop,
                              max_days=max_days,
                              materialize_local=materialize_local)

def open_live_dataset(period,root=None):
    """Read-only union: 8 known physical periods, plus new DAY Parquet only.

    No duplication with 2026-10-13 old files: each overlay is strictly after
    the pinned source cutoff. Caller must choose explicit period and handle
    uncalibrated old purchased schema/stock-code vendor semantics as before.
    """
    import pyarrow.dataset as ds
    if period not in PERIODS:
        raise ValueError("Unknown A-share Parquet period")
    payload=baseline()
    state=read_state()
    root=Path(root or "D:/stock").resolve()
    files=[]
    for x in payload["period_physical_files"][period]:
        base=BASE_MODULE if x["root_kind"]=="private_module" else root
        files.append(str(checked_path(base,x["relative_file"])))
    if period=="day":
        files.extend(str(checked_path(WORK,x["file"]))
                     for _,x in sorted(state["days"].items()))
    return ds.dataset(files,format="parquet",schema=parquet_schema())

def summarize():
    baseline()
    doc=read_state()
    return {"source":LATEST_SOURCE,"baseline_day":BASE_DAY.isoformat(),
            "latest_overlaid_day":max(doc["days"]) if doc["days"] else None,
            "new_day_dates":len(doc["days"]),
            "new_day_rows":sum(x["rows"] for x in doc["days"].values()),
            "missing_package_attempts":len(doc["unavailable_404_last_attempt"]),
            "calibration":doc["calibration"],
            "periods":{"day":"baseline + independently SHA-verified increment",
                       **{x:"asof 2026-10-13; not updated by this source"
                          for x in PERIODS if x!="day"}},
            "original_H5_modified":False,
            "local_day_month_materialized":bool(doc.get("local_month_materializations")),
            "local_month_targets":doc.get("local_month_materializations",{}),
            "storage_convention":"previous years yearly; active year monthly; all eight periods"}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("D:/stock"))
    parser.add_argument("--from-day",default="2026-10-14")
    parser.add_argument("--through-day",default=None)
    parser.add_argument("--max-days",type=int,default=60)
    parser.add_argument("--status",action="store_true")
    parser.add_argument("--preview",action="store_true")
    parser.add_argument("--sync-day-overlay",action="store_true")
    parser.add_argument("--auto-recent-90-days",action="store_true")
    parser.add_argument("--materialize-local-day",action="store_true",
                        help="Also transactionally merge into AllCycleAStockData/day/YYYY-MM.parquet")
    parser.add_argument("--inspect-local-layout",action="store_true",
                        help="Read-only eight-period year/month file and Parquet footer report")
    args=parser.parse_args()
    if args.inspect_local_layout:
        print(json.dumps(LOCAL.inventory(args.root),ensure_ascii=False,indent=2))
        return
    if args.status:
        print(json.dumps(summarize(),ensure_ascii=False,indent=2))
        return
    start=date.fromisoformat(args.from_day)
    end=date.fromisoformat(args.through_day) if args.through_day else latest_yesterday()
    # Long-term scheduled updates intentionally keep a rolling 90-day
    # retry window so HTTP 404/missed trading days remain retryable, without
    # rescanning 2011..2026 historical vendor Parquet or years of weekends.
    if args.auto_recent_90_days:
        start=max(BASE_DAY+timedelta(days=1),end-timedelta(days=89))
        args.max_days=90
    safe_window(start,end,args.max_days)
    if args.preview:
        print(json.dumps({"from":str(start),"to":str(end),
                          "candidate_calendar_days":(end-start).days+1,
                          "source":"Official TDX daily packages from a-stock-data §1.3",
                          "404":"unknown/holiday/not published; never mark closed",
                          "output":"separate DAY overlay, original all-eight source not overwritten",
                          "unsupported":"Tencent minute data lacks amount"},
                         ensure_ascii=False,indent=2))
        return
    if not args.sync_day_overlay and not args.auto_recent_90_days:
        parser.error("Specify --preview, --status, --sync-day-overlay, or --auto-recent-90-days")
    sync(args.root,start,end,max_days=args.max_days,
         materialize_local=args.materialize_local_day)

if __name__=="__main__":
    main()
