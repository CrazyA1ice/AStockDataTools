#!/usr/bin/env python3
"""Purchased-format, incremental 1m -> 5/15/30/60m local Parquet writer.

Only the already-accepted QMT-calibrated physical 1m bars are eligible.
A real September purchased-vendor overlap first proves EACH period's
timestamp offset and volume/amount scale. If not proven, do not publish.
Replays use the existing monthly 1m ledger, bounded Parquet row groups,
a per-period resume ledger, and local_layout.write_month's SHA backup +
atomic write. No QMT or external HTTP calls are made here.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import date, datetime
import json
import math
import os
from pathlib import Path
import statistics

import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
import live_sync as LIVE
import qmt_1m_pipeline as P
import qmt_1m_private_month_bridge as B
import market_month_storage as S
from minute_paid_calibration import source_day_rows

PERIODS = ("5min", "15min", "30min", "60min")
BARS = {"5min":5, "15min":15, "30min":30, "60min":60}
ANCHORS = ("SH600000", "SZ000001", "SH688001")
REFERENCE = date(2026, 9, 30)
FORMAT = "qmt_1m_to_purchased_four_minute_cycles_v1"
RULES_PATH = S.STATE_DIR / "four_cycle_paid_rules.json"
LEDGER_PATH = S.STATE_DIR / "four_cycle_commits.json"
FIELDS = ("open", "high", "low", "close", "volume", "amount")
BASE_CLOCK = [h*60+m for h,m in sorted(P.GRID - {(9, 30)})]
CN_MS = 28800000


def _source_stamp(ts):
    return L.market_ts_day(int(ts))


def grouped_source(table):
    """Stock-day source inventory; strict 240 trading bar and grid gate."""
    found = defaultdict(list)
    for row in table.to_pylist():
        stock = L.normal_symbol(row["symbol"])
        if stock[:2] not in ("SH", "SZ") or len(stock) != 8:
            continue
        found[(stock, _source_stamp(row["ts"]))].append(row)
    return found


def aggregate_stock_day(rows, period, *, one_minute_offset_ms,
                        period_label_shift_ms=0,
                        volume_factor=1.0, amount_factor=1.0):
    n = BARS[period]
    if len(rows) != 240:
        raise ValueError("INCOMPLETE_1MIN_STOCK_DAY: " + str(len(rows)))
    ordered = sorted(rows, key=lambda r: r["ts"])
    if any(ordered[i]["ts"] >= ordered[i+1]["ts"] for i in range(239)):
        raise ValueError("Duplicate/unsorted original 1minute timestamps")
    slots = [((int(r["ts"])+CN_MS-int(one_minute_offset_ms))//60000)%1440
             for r in ordered]
    if slots != BASE_CLOCK:
        raise ValueError("Purchased original 240-minute trading grid mismatch")
    for row in ordered:
        if any(row[field] is None or
               not math.isfinite(float(row[field])) for field in FIELDS):
            raise ValueError("Non-finite or empty 1minute OHLCVA")
    result = []
    for session in (ordered[:120], ordered[120:]):
        for pos in range(0, 120, n):
            bars = session[pos:pos+n]
            bar = {
                "ts": int(bars[-1]["ts"]) + int(period_label_shift_ms),
                "symbol": L.normal_symbol(bars[0]["symbol"]),
                "open": float(bars[0]["open"]),
                "high": max(float(x["high"]) for x in bars),
                "low": min(float(x["low"]) for x in bars),
                "close": float(bars[-1]["close"]),
                "volume": math.fsum(float(x["volume"]) for x in bars)*volume_factor,
                "amount": math.fsum(float(x["amount"]) for x in bars)*amount_factor,
            }
            if (bar["high"] < max(bar["open"], bar["close"]) or
                    bar["low"] > min(bar["open"], bar["close"])):
                raise ValueError("Derived minute OHLC inconsistent")
            result.append(bar)
    if len(result) != 240//n:
        raise ValueError("Derived higher-minute bar count not 240/period")
    for field in ("volume","amount"):
        original = math.fsum(float(row[field]) for row in ordered)
        derived = math.fsum(float(row[field]) for row in result)
        factor = volume_factor if field=="volume" else amount_factor
        if not math.isclose(derived, original*factor, rel_tol=1e-10,abs_tol=1e-5):
            raise ValueError("Higher-period minute amount/volume not conserved")
    return result


def _purchased_anchors(root, period, symbols=ANCHORS):
    source, path, sha = source_day_rows(root, period, REFERENCE, symbols)
    return source, {"path":str(path), "sha256":sha,
                    "size_bytes":path.stat().st_size,
                    "mtime_ns":path.stat().st_mtime_ns}


def _sealed_calibration(root):
    state = S.state_for(root)
    anchor = P.BASE / "calibration" / "latest.json"
    if anchor.is_symlink():
        raise ValueError("Linked QMT minute purchased calibration source")
    proof = S._json(anchor)
    if (not proof.get("calibration_passed")
            or P.sha_bytes(P.canonical(proof))!=state.get("qmt_calibration_sha256")):
        raise ValueError("Sealed purchased-QMT minute calibration changed")
    return proof


def _collect_anchor_minutes(original, sealed):
    grouped = grouped_source(pa.Table.from_pylist(
        list(original.values()),schema=S.SCHEMA))
    return {
        sym: sorted(rows,key=lambda r:r["ts"])
        for (sym,d),rows in grouped.items() if d==REFERENCE
        and len(rows)==240
    }


def _infer_one(period, original, anchor_1m, sealed):
    n=BARS[period]
    base={}
    valid_symbols=[]
    for sym, one in sorted(anchor_1m.items()):
        try:
            code=sym[2:]+"."+sym[:2]
            gate=B._calibration(sealed,code)
            base[sym]=aggregate_stock_day(
                one,period,one_minute_offset_ms=gate["offset_ms"])
            valid_symbols.append(sym)
        except (ValueError,KeyError):
            continue
    if len(valid_symbols)<2:
        raise ValueError("Only one purchased 1minute anchor matched 240-grid")
    scores=[]
    for minutes in range(-n,n+1):
        shift=minutes*60000
        pairs=[(original.get((sym, int(bar["ts"])+shift)), bar)
               for sym,series in base.items() for bar in series]
        pairs=[(a,b) for a,b in pairs if a is not None]
        if len(pairs)<max(6, int(sum(len(b) for b in base.values())*.6)):
            continue
        agree=sum(all(math.isclose(float(a[field]),float(b[field]),
                                   rel_tol=.005,abs_tol=.03)
                      for field in ("open","high","low","close"))
                  for a,b in pairs)/len(pairs)
        loss=statistics.median(
            sum(abs(float(a[field])-float(b[field]))
                for field in ("open","high","low","close"))
            /max(1.,abs(float(a["close"]))) for a,b in pairs)
        scores.append((loss,-agree,-len(pairs),abs(shift),shift,pairs))
    if not scores:
        raise ValueError("No purchased higher-cycle time-label matches: "+period)
    scores.sort(key=lambda x:x[:4])
    loss,negative_agree,neg_n,_,shift,pairs=scores[0]
    if -negative_agree <.85:
        raise ValueError("Purchased higher-cycle OHLC mismatch "+period+
                         " agreement="+str(round(-negative_agree,4)))
    if len(scores)>1 and (scores[1][0]<=max(loss*1.15,loss+1e-6)
                           and -scores[1][2]>=-neg_n*.9):
        raise ValueError("Purchased higher-cycle timestamp ambiguous "+period)
    scalars={}
    for field in ("volume","amount"):
        positive=[(float(a[field]),float(b[field])) for a,b in pairs
                  if float(a[field])>0 and float(b[field])>0]
        if len(positive)<6:
            raise ValueError("Too few positive purchased scale comparisons "+period)
        value=statistics.median(a/b for a,b in positive)
        if not math.isfinite(value) or not 1e-4<=value<=10000:
            raise ValueError("Higher-minute purchased unit scale invalid")
        fit=sum(math.isclose(a,b*value,rel_tol=.05,abs_tol=1e-6)
                for a,b in positive)/len(positive)
        if fit<.85:
            raise ValueError("Higher-minute purchased units not compatible "+period+
                             " "+field+" fit="+str(round(fit,4)))
        scalars[field]=value
    return {
        "period":period, "timestamp_shift_from_1min_last_ms":shift,
        "volume_factor":scalars["volume"],"amount_factor":scalars["amount"],
        "anchor_symbols":valid_symbols,"price_match":round(-negative_agree,6),
        "paired_ohlc_bars":len(pairs),"relative_residual":round(loss,8),
        "source_only_sample_not_all_symbols_certified":True,
    }


def paid_rules(root, *, progress=print, workspace=S.STATE_DIR):
    root=Path(root)
    destination=Path(workspace)/"four_cycle_paid_rules.json"
    base=str(L.storage_root(root).resolve())
    if destination.exists():
        stored=S._json(destination)
        if (stored.get("format")!=FORMAT or stored.get("root")!=base or
                set(stored.get("periods",{}))!=set(PERIODS)):
            raise ValueError("Stored minute period calibration unrecognized")
        for spec in stored["sources"].values():
            path=Path(spec["path"])
            if (path.is_symlink() or not path.is_file()
                    or path.stat().st_size!=spec["size_bytes"]
                    or path.stat().st_mtime_ns!=spec["mtime_ns"]):
                raise ValueError("Purchased higher-period calibration input changed")
        if stored["qmt_purchased_calibration"]!=S.state_for(root)["qmt_calibration_sha256"]:
            raise ValueError("QMT purchased 1m calibration differs from saved rules")
        return stored["periods"]
    sealed=_sealed_calibration(root)
    one,original_source=_purchased_anchors(root,"1min")
    old_minutes=_collect_anchor_minutes(one,sealed)
    if len(old_minutes)<2:
        raise ValueError("Purchased 2026-09-30 1minute anchor bars unavailable")
    rules={}
    sources={"1min":original_source}
    for period in PERIODS:
        original,stat=_purchased_anchors(root,period)
        sources[period]=stat
        rules[period]=_infer_one(period,original,old_minutes,sealed)
        progress("MARKET_PURCHASED_PERIOD_CALIBRATED="+json.dumps(
            rules[period],sort_keys=True))
    doc={"format":FORMAT,"root":base,"periods":rules,
         "qmt_purchased_calibration":S.state_for(root)["qmt_calibration_sha256"],
         "sources":sources}
    S._save(destination,doc)
    return rules


def _ledger(root,workspace):
    path=Path(workspace)/"four_cycle_commits.json"
    if not path.exists():
        return {"format":FORMAT,"root":str(L.storage_root(root).resolve()),
                "months":{p:{} for p in PERIODS}}
    state=S._json(path)
    if (state.get("format")!=FORMAT
            or state.get("root")!=str(L.storage_root(root).resolve())
            or set(state.get("months",{}))!=set(PERIODS)):
        raise ValueError("Higher-minute update ledger root or format changed")
    return state


def _derive_from_source(path, selected_days, rules, sealed, *, workspace, month, progress):
    """Read physical 1m row groups just once; stage four period candidates."""
    out={}
    work=Path(workspace)/"cycle_candidates"
    work.mkdir(parents=True,exist_ok=True)
    writers={}
    rows=Counter()
    errors=Counter()
    days=defaultdict(set)
    buffers={p:[] for p in PERIODS}
    scratch={}
    for period in PERIODS:
        target=work/(period+"-"+month+".parquet.part")
        if target.is_symlink() or target.exists():
            raise ValueError("Unresolved minute period candidate scratch: "+str(target))
        scratch[period]=target
    reader=pq.ParquetFile(path)
    try:
        if reader.schema_arrow!=S.SCHEMA:
            raise ValueError("Source physical 1minute format differs from sealed format")
        for period in PERIODS:
            writers[period]=pq.ParquetWriter(scratch[period],S.SCHEMA,compression="zstd")
        for group_id in range(reader.num_row_groups):
            batch=reader.read_row_group(group_id)
            for (sym,day),single in grouped_source(batch).items():
                if day.isoformat() not in selected_days:
                    continue
                if len(single)!=240:
                    errors["incomplete_stockday"]+=1
                    continue
                code=sym[2:]+"."+sym[:2]
                gate=B._calibration(sealed,code)
                for period in PERIODS:
                    spec=rules[period]
                    aggregate=aggregate_stock_day(
                        single,period,one_minute_offset_ms=gate["offset_ms"],
                        period_label_shift_ms=spec["timestamp_shift_from_1min_last_ms"],
                        volume_factor=spec["volume_factor"],
                        amount_factor=spec["amount_factor"])
                    buffers[period].extend(aggregate)
                    if len(buffers[period])>=32768:
                        writers[period].write_table(
                            pa.Table.from_pylist(buffers[period],schema=S.SCHEMA),
                            row_group_size=32768)
                        buffers[period].clear()
                    rows[period]+=len(aggregate)
                    days[period].add(day.isoformat())
            if (group_id+1)%1000==0:
                progress("MARKET_FOUR_CYCLE_PROGRESS="+month+" rowgroups="+str(group_id+1))
    finally:
        reader.close()
        for period,writer in writers.items():
            if buffers[period]:
                writer.write_table(
                    pa.Table.from_pylist(buffers[period],schema=S.SCHEMA),
                    row_group_size=32768)
            writer.close()
    for period in PERIODS:
        if rows[period]:
            out[period]={"path":str(scratch[period]),"rows":rows[period],
                         "days":sorted(days[period])}
        else:
            scratch[period].unlink(missing_ok=True)
    return out,dict(errors)


def _protect_existing(root,period,month,record,workspace):
    """Preserve original key-values and verify same-key price sanity."""
    target=L.storage_root(root)/period/(month+".parquet")
    if not target.exists():
        return
    if target.is_symlink():
        raise ValueError("Linked existing higher-minute market file")
    old=pq.read_table(target,columns=list(L.COLS))
    L.checked_records(old,target_year=int(month[:4]),target_month=int(month[5:]))
    old_by_key={(int(r["ts"]),L.normal_symbol(r["symbol"])):r
                for r in old.to_pylist()}
    collided=0
    for new in record["table"].to_pylist():
        key=(int(new["ts"]),L.normal_symbol(new["symbol"]))
        oldrow=old_by_key.get(key)
        if oldrow is None:
            continue
        collided+=1
        if not all(math.isclose(float(oldrow[f]),float(new[f]),
                                rel_tol=.012,abs_tol=.03)
                   for f in ("open","high","low","close")):
            raise ValueError("Existing purchased higher-minute price conflict "+
                             period+" "+month+" "+str(key))
    return collided


def _run_unlocked(root,*,apply=False,progress=print,workspace=S.STATE_DIR):
    """Incremental catchup under the caller's writer lock for apply."""
    root=Path(root)
    market=S.state_for(root)
    period_state=_ledger(root,workspace)
    rules=paid_rules(root,progress=progress,workspace=workspace)
    sealed=_sealed_calibration(root)
    report=[]
    selected={}
    for month,meta in sorted(market["periods"]["1min"].items()):
        dates=set(meta["days"])
        pending={period:sorted(dates-set(
            period_state["months"][period].get(month,{}).get("processed_days",[])))
                 for period in PERIODS}
        # A failed period is retried on the next invocation. For current
        # version, stage common candidate source once, but write only days
        # not already credited to each period.
        union=set().union(*(set(d) for d in pending.values()))
        if not union:
            continue
        target=S.target_path(root,month)
        if not target.is_file() or L.hash_file(target)!=meta["sha256"]:
            raise ValueError("Physical 1minute source differs from accepted ledger "+month)
        selected[month]={"file":target,"days":union,"source_sha":meta["sha256"],
                         "pending":pending}
    for month,job in sorted(selected.items()):
        source,missing=_derive_from_source(
            job["file"],job["days"],rules,sealed,
            workspace=workspace,month=month,progress=progress)
        progress("MARKET_FOUR_CYCLE_MONTH_PREVIEW="+json.dumps({
            "month":month,"eligible_days":sorted(job["days"]),
            "staged_rows":{k:v["rows"] for k,v in source.items()},
            "partial_stockday_groups":missing.get("incomplete_stockday",0),
            "apply":apply},sort_keys=True))
        try:
            for period in PERIODS:
                if period not in source:
                    continue
                pending=set(job["pending"][period])
                if not pending:
                    continue
                data=pq.read_table(source[period]["path"])
                L.checked_records(data,target_year=int(month[:4]),
                                  target_month=int(month[5:]))
                day_mask=pa.array([_source_stamp(t).isoformat() in pending
                                   for t in data["ts"].to_pylist()])
                filtered=data.filter(day_mask)
                if not filtered.num_rows:
                    continue
                collisions=_protect_existing(
                    root,period,month,{"table":filtered},workspace)
                if not apply:
                    report.append({"month":month,"period":period,
                                   "status":"PREVIEW","candidate_rows":filtered.num_rows,
                                   "old_key_matches":collisions})
                    continue
                result=L.write_month(root,period,int(month[:4]),int(month[5:]),
                                     filtered,workspace,current_year=int(month[:4]))
                path=L.storage_root(root)/period/(month+".parquet")
                period_state["months"][period][month]={
                    "sha256":L.hash_file(path),
                    "source_month_sha256":job["source_sha"],
                    "processed_days":sorted(
                        set(period_state["months"][period].get(month,{})
                            .get("processed_days",[]))|pending),
                    "source_full_stockdays_only":True,
                }
                S._save(Path(workspace)/"four_cycle_commits.json",period_state)
                report.append({"month":month,"period":period,
                               "status":"COMMITTED","added":result["added"],
                               "already_present":result["same_key"],
                               "rows":result["total_rows"]})
                progress("MARKET_DERIVED_PERIOD_COMMITTED="+json.dumps(
                    report[-1],sort_keys=True))
        finally:
            for item in source.values():
                Path(item["path"]).unlink(missing_ok=True)
    return report


def run(root,*,apply=False,progress=print,workspace=S.STATE_DIR):
    """Public cycle updater: retain the same OS single-writer lock as QMT."""
    if apply:
        with LIVE.exclusive_writer():
            return _run_unlocked(root,apply=True,progress=progress,workspace=workspace)
    return _run_unlocked(root,apply=False,progress=progress,workspace=workspace)
