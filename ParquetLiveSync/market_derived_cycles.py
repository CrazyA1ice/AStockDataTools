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
    """Stock-day source inventory; paid 241 admission checked later."""
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
    if (type(one_minute_offset_ms) is not int
            or one_minute_offset_ms not in [m*60000 for m in P.OFFSET_MINUTES]):
        raise ValueError("Invalid purchased 1minute grid offset")
    if len(rows) == 241:
        # The purchased physical 09:30 bar stays intact in 1m storage.
        # Use its turnover once in the first higher-period interval only.
        ordered_source = sorted(rows, key=lambda row: row["ts"])
        day = L.market_ts_day(int(ordered_source[0]["ts"]) -
                              one_minute_offset_ms)
        rows, _ = S._fold_241_day(
            ordered_source, one_minute_offset_ms, day.strftime("%Y-%m"))
    if len(rows) != 240:
        raise ValueError("INCOMPLETE_1MIN_STOCK_DAY: " + str(len(rows)))
    if (type(period_label_shift_ms) is not int
            or period_label_shift_ms%60000):
        raise ValueError("Invalid purchased higher-period timestamp shift")
    ordered = sorted(rows, key=lambda r: r["ts"])
    if any(type(r["ts"]) is not int for r in ordered):
        raise ValueError("Non-integer original 1minute timestamp")
    if any(ordered[i]["ts"] >= ordered[i+1]["ts"] for i in range(239)):
        raise ValueError("Duplicate/unsorted original 1minute timestamps")
    # Integer-minute binning alone can silently accept :00:45 and :00:59.
    # Require *exact* calibrated exchange-local whole-minute labels before
    # deriving any higher-period bar. Never floor off-grid source timestamps.
    shifted_ms = [r["ts"]+CN_MS-one_minute_offset_ms for r in ordered]
    if any(stamp%60000 for stamp in shifted_ms):
        raise ValueError("Purchased original 240-minute trading grid has off-minute timestamps")
    slots = [(stamp//60000)%1440 for stamp in shifted_ms]
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
    """Keep actual purchased 238-241 bars without inventing any minute.

    The real 2026-09-30 paid anchors are 241: 09:30 through 15:00,
    including a separate auction label. In contrast, canonical updated
    QMT stock-days are exactly 240 after the auction is safely folded.
    Incomplete purchased anchors are used for *calibration only* and only
    through their fully observed aggregation buckets.
    """
    grouped = grouped_source(pa.Table.from_pylist(
        list(original.values()),schema=S.SCHEMA))
    return {
        sym: sorted(rows,key=lambda r:r["ts"])
        for (sym,d),rows in grouped.items() if d==REFERENCE
        and 238<=len(rows)<=241
    }


def _anchor_complete_buckets(rows,period,*,one_minute_offset_ms):
    """Calibrate from ONLY genuinely observed entire 5/15/30/60m windows.

    During production, aggregate_stock_day() still requires 240/240 source
    minute bars. This helper is for purchased-source overlap only.
    """
    n=BARS[period]
    if (type(one_minute_offset_ms) is not int
            or one_minute_offset_ms not in [m*60000 for m in P.OFFSET_MINUTES]):
        raise ValueError("Unverified purchased source minute offset")
    if len(rows)<238 or len(rows)>241:
        raise ValueError("Purchased anchor needs 238-241 genuine minute bars")
    # 09:30 is a real source label, NOT an extra 09:31 interval. Where the
    # purchase has all 241 labels, apply the same proved auction folding
    # rule as the QMT physical 1m writer. Never silently discard traded
    # volume/amount or substitute a synthetic minute.
    if len(rows)==241:
        ordered=sorted(rows,key=lambda r:r["ts"])
        for raw in ordered:
            if type(raw["ts"]) is not int or (
                    raw["ts"]+CN_MS-one_minute_offset_ms)%60000:
                raise ValueError("Purchased minute anchor sub-minute timestamp drift")
        rows,_=S._fold_241_day(
            ordered,one_minute_offset_ms,REFERENCE.strftime("%Y-%m"))
    canonical={}
    stamp_seen=set()
    label_seen=set()
    expect=set(BASE_CLOCK)
    symbol=None
    for raw in rows:
        stamp=raw["ts"]
        if type(stamp) is not int or stamp in stamp_seen:
            raise ValueError("Purchased minute anchor duplicate/invalid timestamp")
        stamp_seen.add(stamp)
        shifted=stamp+CN_MS-one_minute_offset_ms
        if shifted%60000:
            raise ValueError("Purchased minute anchor sub-minute timestamp drift")
        label=(shifted//60000)%1440
        if label not in expect or label in label_seen:
            raise ValueError("Purchased minute anchor outside exact exchange time grid")
        label_seen.add(label)
        sym=L.normal_symbol(raw["symbol"])
        if symbol is None:
            symbol=sym
        elif sym!=symbol:
            raise ValueError("Purchased minute anchor mixes equities")
        if any(raw[k] is None or not math.isfinite(float(raw[k]))
               for k in FIELDS):
            raise ValueError("Purchased minute anchor non-finite OHLCVA")
        if not (float(raw["low"])>0 and
                float(raw["low"])<=min(float(raw["open"]),float(raw["close"])) and
                float(raw["high"])>=max(float(raw["open"]),float(raw["close"])) and
                float(raw["volume"])>=0 and float(raw["amount"])>=0):
            raise ValueError("Purchased minute anchor OHLCVA invalid")
        canonical[label]=raw
    out=[]
    for session in (BASE_CLOCK[:120],BASE_CLOCK[120:]):
        for start in range(0,120,n):
            slots=session[start:start+n]
            if any(slot not in canonical for slot in slots):
                continue
            group=[canonical[slot] for slot in slots]
            out.append({
                "ts":int(group[-1]["ts"]),"symbol":symbol,
                "open":float(group[0]["open"]),
                "high":max(float(x["high"]) for x in group),
                "low":min(float(x["low"]) for x in group),
                "close":float(group[-1]["close"]),
                "volume":math.fsum(float(x["volume"]) for x in group),
                "amount":math.fsum(float(x["amount"]) for x in group),
            })
    if len(out)<(240//n)-2:
        raise ValueError("Purchased anchor has too few complete higher-minute buckets")
    return out


def _infer_one(period, original, anchor_1m, sealed):
    n=BARS[period]
    base={}
    valid_symbols=[]
    skipped={}
    for sym, one in sorted(anchor_1m.items()):
        try:
            code=sym[2:]+"."+sym[:2]
            gate=B._calibration(sealed,code)
            base[sym]=_anchor_complete_buckets(
                one,period,one_minute_offset_ms=gate["offset_ms"])
            valid_symbols.append(sym)
        except (ValueError,KeyError) as exc:
            skipped[sym]=type(exc).__name__+": "+str(exc)[:250]
    if len(valid_symbols)<2:
        raise ValueError("Too few real purchased 1minute anchors prove "+period+
                         " complete windows: valid="+str(valid_symbols)+
                         " excluded="+json.dumps(skipped,sort_keys=True))
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
    all_days=grouped_source(pa.Table.from_pylist(
        list(one.values()),schema=S.SCHEMA))
    inventory={sym:{"rows":len(rows),
                    "first_cn":datetime.fromtimestamp(
                        min(x["ts"] for x in rows)/1000,L.UTC8).strftime("%H:%M:%S"),
                    "last_cn":datetime.fromtimestamp(
                        max(x["ts"] for x in rows)/1000,L.UTC8).strftime("%H:%M:%S")}
               for (sym,day),rows in sorted(all_days.items())
               if day==REFERENCE}
    progress("MARKET_PURCHASED_1MIN_ANCHOR_INVENTORY="+json.dumps(
        {"day":REFERENCE.isoformat(),"symbols":inventory,
         "real_rows_only":True,"missing_minutes_never_filled":True},
        sort_keys=True))
    old_minutes=_collect_anchor_minutes(one,sealed)
    if len(old_minutes)<2:
        raise ValueError("Purchased 2026-09-30 1minute anchors unavailable for "
                         "238-241 real minutes: "+
                         json.dumps({sym:len(rows) for
                                    (sym,day),rows in grouped_source(
                                        pa.Table.from_pylist(
                                            list(one.values()),schema=S.SCHEMA)).items()
                                    if day==REFERENCE},sort_keys=True))
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
    pending={}
    scratch={}
    for period in PERIODS:
        target=work/(period+"-"+month+".parquet.part")
        if target.is_symlink():
            raise ValueError("Linked private cycle candidate scratch: "+str(target))
        if target.exists():
            # Only this exact disposable private .part candidate is
            # restarted; accepted source Parquet and receipts are untouched.
            target.unlink()
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
                key=(sym,day)
                if day < date(2026,10,14) and len(single)!=241:
                    # The four pre-cutoff H5 fragments have no guaranteed
                    # Purchased 241 per stock-day. Never invent missing minutes.
                    errors["pre_cutoff_incomplete_stockday_fragment"]+=1
                    continue
                if key in pending:
                    single=pending.pop(key)+single
                if len(single)<241:
                    pending[key]=single
                    if len(pending)>40:
                        raise ValueError("Too many discontiguous QMT stock-days; original source ordering changed")
                    continue
                if len(single)!=241:
                    raise ValueError("Duplicate or malformed paid 241 QMT stock-day "+
                                     sym+" "+str(day)+" bars="+str(len(single)))
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
        if pending:
            raise ValueError("Accepted QMT minute stock-days remain incomplete after streaming: "+
                             str([(x[0],str(x[1]),len(v)) for x,v in
                                  list(pending.items())[:5]]))
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
    for period in PERIODS:
        for month,receipt in period_state["months"][period].items():
            target=L.storage_root(root)/period/(month+".parquet")
            if (not target.is_file() or target.is_symlink()
                    or L.hash_file(target)!=receipt["sha256"]):
                raise ValueError("Higher-minute Parquet changed after recorded commit "+
                                 period+" "+month)
    rules=paid_rules(root,progress=progress,workspace=workspace)
    sealed=_sealed_calibration(root)
    report=[]
    selected={}
    for month,meta in sorted(market["periods"]["1min"].items()):
        # 2026-10-08..13 are the immutable purchased/H5 eight-period
        # baseline, not QMT-backed new stock-days. Some real 1m files
        # have 239 bars. Never regenerate or credit that historical slice
        # as a successfully completed 241-source derived period.
        dates={d for d in meta["days"]
               if date.fromisoformat(d)>=date(2026,10,14)}
        pending={period:sorted(dates-set(
            period_state["months"][period].get(month,{}).get("processed_days",[])))
                 for period in PERIODS}
        # A failed period is retried on the next invocation. For current
        # version, stage common candidate source once, but write only days
        # not already credited to each period.
        union=set().union(*(set(d) for d in pending.values()))
        if not union:
            continue
        if meta.get("minute_grid_contract") != S.PAID_241_CONTRACT:
            raise ValueError("EXISTING_240_MONTH_REQUIRES_EXPLICIT_241_MIGRATION")
        target=S.target_path(root,month)
        if not target.is_file() or L.hash_file(target)!=meta["sha256"]:
            raise ValueError("Physical 1minute source differs from accepted ledger "+month)
        selected[month]={"file":target,"days":union,"source_sha":meta["sha256"],
                         "pending":pending}
    if not apply:
        preview=[{"period":period,"month":month,
                  "status":"CALIBRATION_PASSED_SOURCE_SHA_VERIFIED",
                  "pending_dates":job["pending"][period],
                  "source_1min_sha256":job["source_sha"]}
                 for month,job in sorted(selected.items())
                 for period in PERIODS if job["pending"][period]]
        progress("MARKET_FOUR_CYCLE_READONLY_PLAN="+json.dumps(
            {"candidate_period_months":len(preview),
             "one_minute_original_market_files_read_in_full":False,
             "physical_market_files_modified":False},sort_keys=True))
        return preview
    for month,job in sorted(selected.items()):
        source,missing=_derive_from_source(
            job["file"],job["days"],rules,sealed,
            workspace=workspace,month=month,progress=progress)
        progress("MARKET_FOUR_CYCLE_MONTH_PREVIEW="+json.dumps({
            "month":month,"eligible_days":sorted(job["days"]),
            "staged_rows":{k:v["rows"] for k,v in source.items()},
            "partial_stockday_groups":missing.get("incomplete_stockday",0),
            "apply":apply},sort_keys=True))
        if missing.get("incomplete_stockday",0):
            raise ValueError("Cannot credit incomplete QMT stock-days as complete "+
                             month+" count="+str(missing["incomplete_stockday"]))
        for period in PERIODS:
            observed=set(source.get(period,{}).get("days",[]))
            if observed!=set(job["days"]):
                raise ValueError("Derived "+period+" coverage does not include "+
                                 "all eligible QMT dates in "+month+" missing="+
                                 str(sorted(set(job["days"])-observed)[:8]))
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
