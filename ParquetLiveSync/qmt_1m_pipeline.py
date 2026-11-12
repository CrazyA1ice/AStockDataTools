#!/usr/bin/env python3
"""QMT 1-minute market historical intake with paid-provider calibration.

ONE entry point: verify 2026-09-30 purchased overlap, discover source DAY
stocks, download/verify QMT 1m OHLCVA, stage SHA-pinned private Arrow files,
and resume without refetching accepted stocks. NEVER modifies market/H5.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

import pyarrow as pa
import pyarrow.parquet as pq

import local_layout as L
from live_sync import CN, WORK, source_day_ts
from minute_paid_calibration import source_day_rows
from qmt_1m_probe import FIELDS, normalize_code, normalize_frame, parse_time, probe

FORMAT = "qmt_paid_calibrated_private_1minute_market_stage_v1"
BASE = WORK / "qmt_1min_market"
ANCHORS = ("600000.SH", "000001.SZ", "688001.SH")
REFERENCE = date(2026, 9, 30)
OFFSET_MINUTES = (-3, -2, -1, 0, 1, 2, 3)
FACTORS = (.0001, .001, .01, .1, 1., 10., 100., 1000., 10000.)
GRID = frozenset(
    [(h, m) for h in (9, 10, 11, 13, 14, 15) for m in range(60)
     if (h == 9 and m >= 30) or h == 10 or (h == 11 and m <= 30)
     or (h == 13 and m >= 1) or h == 14 or (h == 15 and m == 0)]
)
# Exactly 241 labels: 09:30..11:30 (121) and 13:01..15:00 (120).
PRIVATE_SCHEMA = pa.schema([
    pa.field("ts", pa.int64()),
    pa.field("symbol", pa.string()),
    *[pa.field(field, pa.float64()) for field in FIELDS],
])


def sha_bytes(blob):
    return hashlib.sha256(blob).hexdigest()


def canonical(doc):
    return (json.dumps(doc, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def safe_save(path, blob):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Symlinked private output refused")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Symlinked private output directory")
    part = path.with_suffix(path.suffix + ".part")
    if part.is_symlink():
        raise ValueError("Symlinked private temporary output")
    with part.open("wb") as f:
        f.write(blob)
    os.replace(part, path)


def category(code):
    code = normalize_code(code)
    if code.endswith(".SZ"):
        return "SZ"
    if code.startswith(("688", "689")):
        return "STAR"
    return "SH_OTHER"


def stamp_ms(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def expected_minute_grid(day):
    # Never fabricate missing bars; this is an acceptance grid only.
    return frozenset(
        datetime(day.year, day.month, day.day, h, m, tzinfo=CN).isoformat()
        for h, m in GRID
    )


def validate_full_days(rows, wanted_days, code):
    by_day = defaultdict(list)
    for row in rows:
        by_day[date.fromisoformat(row["datetime_cn"][:10])].append(row)
    wanted_days = set(wanted_days)
    if set(by_day) != wanted_days:
        missing = sorted(d.isoformat() for d in wanted_days-set(by_day))
        unexpected = sorted(d.isoformat() for d in set(by_day)-wanted_days)
        raise ValueError(f"QMT_STOCK_DAY_MISMATCH {code} missing={missing[:6]} extra={unexpected[:6]}")
    for day, observed in by_day.items():
        slots = frozenset(row["datetime_cn"] for row in observed)
        expected = expected_minute_grid(day)
        if slots != expected:
            absent = sorted(expected-slots)
            extra = sorted(slots-expected)
            raise ValueError(f"QMT_NOT_EXACT_241_GRID {code} {day} "
                             f"rows={len(observed)} missing={absent[:3]} unexpected={extra[:3]}")
    return by_day


def factor_fit(pairs, field):
    pairs = [(float(original[field]),float(qmt[field]))
             for original,qmt in pairs
             if float(original[field]) > 0 and float(qmt[field]) > 0]
    if len(pairs) < 70:
        raise ValueError(f"QMT_PAID_{field}_INSUFFICIENT_POSITIVE_PAIR n={len(pairs)}")
    scores = []
    for factor in FACTORS:
        residuals = [abs(old - new*factor) / max(abs(old), 0.00001)
                     for old,new in pairs]
        fit = sum(r <= 0.04 for r in residuals)/len(residuals)
        scores.append((fit, -statistics.median(residuals), factor))
    scores.sort(reverse=True)
    best = scores[0]
    second = scores[1]
    if best[0] < .88 or best[0]-second[0] < .15:
        raise ValueError(f"QMT_PAID_{field}_UNRESOLVED best={best} runner_up={second}")
    return {"factor":best[2],"inlier_fraction":round(best[0],5),
            "positive_pairs":len(pairs)}


def overlap_calibrate(code, source, old):
    canonical_code = L.normal_symbol(code)
    stamp_rows=[{**row,"ts":stamp_ms(row["datetime_cn"])} for row in source]
    trials=[]
    for minute in OFFSET_MINUTES:
        delta=minute*60000
        pairs = []
        for bar in stamp_rows:
            prev=old.get((canonical_code,bar["ts"]+delta))
            if prev is not None:
                pairs.append((prev,bar))
        if len(pairs) < 150:
            continue
        errors=[
            sum(abs(float(a[key])-float(b[key])) for key in ("open","high","low","close"))
            / max(1.,abs(float(a["close"]))) for a,b in pairs
        ]
        price_fit=sum(all(math.isclose(float(a[k]),float(b[k]),rel_tol=.003,abs_tol=.02)
                          for k in ("open","high","low","close"))
                      for a,b in pairs)/len(pairs)
        trials.append((statistics.median(errors),-price_fit,-len(pairs),minute,pairs))
    if not trials:
        raise ValueError(f"QMT_PAID_NO_OVERLAP_FOR {code}")
    trials.sort(key=lambda t:t[:3])
    loss,negprice,negn,minute,pairs=trials[0]
    fit=-negprice
    if fit < .91:
        raise ValueError(f"QMT_PAID_PRICE_TIME_GATE {code} fit={fit:.4f} offset_min={minute}")
    if len(trials)>1:
        second=trials[1]
        if second[0] <= max(loss*1.1,loss+0.00001) and -second[2]>=-negn*.9:
            raise ValueError(f"QMT_PAID_AMBIGUOUS_TIME {code} offsets={minute},{second[3]}")
    price_pairs=[(a,b) for a,b in pairs if
                 all(math.isclose(float(a[k]),float(b[k]),rel_tol=.003,abs_tol=.02)
                     for k in ("open","high","low","close"))]
    if len(price_pairs)<140:
        raise ValueError(f"QMT_PAID_NOT_ENOUGH_EXACT_PRICE_PAIRS {code}")
    return {"category":category(code),"symbol":code,
            "offset_ms":minute*60000,"overlap_pairs":len(pairs),
            "price_fit":round(fit,5),"normalized_price_error":round(loss,8),
            "volume":factor_fit(price_pairs,"volume"),
            "amount":factor_fit(price_pairs,"amount")}


def fetch_qmt(xtdata, code, start, end):
    # QMT cache is user-owned: downloads may write only inside QMT's own data dir.
    xtdata.download_history_data(code, period="1m",
        start_time=start.strftime("%Y%m%d"), end_time=end.strftime("%Y%m%d"))
    payload=xtdata.get_market_data_ex(
        field_list=list(FIELDS),stock_list=[code],period="1m",
        start_time=start.strftime("%Y%m%d"),end_time=end.strftime("%Y%m%d"),
        count=-1,dividend_type="none",fill_data=False)
    if not isinstance(payload,dict) or code not in payload:
        raise ValueError("QMT returned no requested stock: "+code)
    rows=normalize_frame(payload[code],code,start,end)
    if not rows:
        raise ValueError("QMT returned no original OHLCVA 1m: "+code)
    return rows


def calibrate(root, xtdata, workspace=BASE, logger=print):
    """Three independent SH/SZ/STAR source contracts, not an assumed global factor."""
    folder=Path(workspace)/"calibration"
    folder.mkdir(parents=True,exist_ok=True)
    result={"format":FORMAT,"reference_day":REFERENCE.isoformat(),
            "providers":{},"failed":{},"market_modified":False}
    for code in ANCHORS:
        logger(f"QMT_PAID_OVERLAP_START {code} 2026-09-30")
        try:
            original,path,original_sha=source_day_rows(
                root,"1min",REFERENCE,[L.normal_symbol(code)])
            bars=fetch_qmt(xtdata,code,REFERENCE,REFERENCE)
            # Full QMT source day required for reference. Purchased bars may
            # have a different first-minute convention, evaluated by overlap.
            validate_full_days(bars,[REFERENCE],code)
            gate=overlap_calibrate(code,bars,original)
            gate["paid_source_sha256"]=original_sha
            gate["paid_source_path"]=str(path)
            gate["qmt_canonical_sha256"]=sha_bytes(canonical(bars))
            result["providers"][category(code)]=gate
            logger(f"QMT_CALIBRATION_PASS {code} offset_ms={gate['offset_ms']} "
                   f"price_fit={gate['price_fit']} "
                   f"volume_factor={gate['volume']['factor']} "
                   f"amount_factor={gate['amount']['factor']}")
        except Exception as exc:
            result["failed"][category(code)]=f"{type(exc).__name__}: {exc}"[:500]
            logger(f"QMT_CALIBRATION_BLOCK {code} {exc}")
    result["calibration_passed"]=len(result["providers"])==3 and not result["failed"]
    result["source_only_not_full_market_certified"]=True
    safe_save(folder/"latest.json",canonical(result))
    logger("QMT_CALIBRATION_SUMMARY="+json.dumps({
        "passed":result["calibration_passed"],
        "categories":sorted(result["providers"]),
        "failed":result["failed"],
        "market_modified":False
    },ensure_ascii=False,sort_keys=True))
    return result



def latest_certified_day(root, start, requested_end):
    """Conservatively trim trailing unpublished DAY dates, never invent calendar rows."""
    base=L.storage_root(root)
    current=requested_end
    while current>=start:
        if current.weekday() < 5:
            p=base/"day"/f"{current.year}-{current.month:02}.parquet"
            if p.exists() and not p.is_symlink():
                stamp=source_day_ts(current)
                view=pq.read_table(p,columns=["ts","symbol"],
                    filters=[("ts",">=",stamp),("ts","<",stamp+86400000)])
                if view.num_rows>=2500:
                    return current
        current-=timedelta(days=1)
    raise ValueError("No official 2500+-stock DAY reference on/after requested start")


def official_day_universe(root, start, end):
    """Read-only stocks from actual monthly DAY Parquet, no index-point expansion."""
    base=L.storage_root(root)
    monthly={}
    selected=defaultdict(dict)
    month=(start.year,start.month)
    while month<=(end.year,end.month):
        year,mm=month
        p=base/"day"/f"{year}-{mm:02d}.parquet"
        if p.is_symlink() or not p.is_file():
            raise ValueError("Required official DAY monthly file missing: "+str(p))
        digest=L.hash_file(p)
        monthly[p.name]=digest
        lo=source_day_ts(start)
        hi=source_day_ts(end)+86400000
        frame=pq.read_table(p,columns=list(L.COLS),
                            filters=[("ts",">=",lo),("ts","<",hi)])
        L.validate_schema(frame.schema)
        for bar in frame.to_pylist():
            day=L.market_ts_day(int(bar["ts"]))
            sym=L.normal_symbol(bar["symbol"])
            if not start<=day<=end or sym[:2] not in ("SH","SZ") or len(sym)!=8:
                continue
            if not sym[2:].isdigit() or float(bar["close"])<=0 or float(bar["volume"])<=0:
                continue
            code=normalize_code(sym)
            if code in selected[day]:
                raise ValueError("Duplicate official stock/day: "+code+" "+str(day))
            selected[day][code]=bar
        month=(year+1,1) if mm==12 else (year,mm+1)
    if not selected:
        raise ValueError("No official DAY traded securities over request")
    counts={str(day):len(day_symbols) for day,day_symbols in selected.items()}
    if any(n<2500 for n in counts.values()):
        raise ValueError("DAY_REFERENCE_NOT_FULL_MARKET "+str(counts))
    # If a weekday is absent, we cannot infer that it was a holiday.
    for n in range((end-start).days+1):
        day=start+timedelta(days=n)
        if day.weekday()<5 and day not in selected:
            raise ValueError("DAY_REFERENCE_TRADING_DATE_NOT_PROVEN "+str(day))
    universe=sorted(set().union(*(set(v) for v in selected.values())))
    proof=sha_bytes(canonical({"monthly_sha256":monthly,
                              "days":sorted((str(day),code)
                                  for day,codes in selected.items() for code in codes)}))
    return selected,universe,proof,monthly


def qmt_stage_stock(code, expected, start, end, calibration, workspace, xtdata):
    root=Path(workspace)
    meta=root/"receipts"/(code.replace(".","_")+".json")
    target=root/"source_parquet"/(code.replace(".","_")+".parquet")
    days=sorted(day for day,codes in expected.items() if code in codes)
    if not days:
        raise ValueError("Stock absent from approved official DAY universe")
    requested=[x.isoformat() for x in days]
    fingerprint=sha_bytes(canonical({
        "window":[start.isoformat(),end.isoformat()],
        "symbol":code,"days":requested,
        "calibration_sha256":sha_bytes(canonical(calibration))
    }))
    if meta.is_file() and not meta.is_symlink():
        old=json.loads(meta.read_bytes())
        if old.get("fingerprint")!=fingerprint:
            raise ValueError("Existing QMT receipt tied to changed calendar/calibration")
        if target.is_symlink() or not target.is_file() or L.hash_file(target)!=old.get("sha256"):
            raise ValueError("Cached QMT source Parquet SHA mismatch")
        if old.get("status")!="private_ohlcva_source_verified":
            raise ValueError("Unexpected QMT source cache status")
        return old,False
    rows=fetch_qmt(xtdata,code,start,end)
    groups=validate_full_days(rows,days,code)
    # Independent traded DAY OHLC check; do not assume time/volume units
    # because these are measured separately against purchased 1min.
    day_checks={}
    for day,bars in groups.items():
        daily=expected[day][code]
        ohlc={"open":bars[0]["open"],"close":bars[-1]["close"],
              "high":max(x["high"] for x in bars),
              "low":min(x["low"] for x in bars)}
        close_enough=all(math.isclose(float(daily[field]),float(value),
                                      rel_tol=.006,abs_tol=.04)
                         for field,value in ohlc.items())
        day_checks[day.isoformat()]={"ohlc_match":close_enough,
                                    "qmt_volume_total":round(sum(x["volume"] for x in bars),4),
                                    "qmt_amount_total":round(sum(x["amount"] for x in bars),4)}
        if not close_enough:
            raise ValueError("QMT_OFFICIAL_DAY_OHLC_MISMATCH "+code+" "+str(day))
    tab=pa.Table.from_pylist([
        {"ts":stamp_ms(r["datetime_cn"]),"symbol":L.normal_symbol(code),
         **{field:float(r[field]) for field in FIELDS}} for r in rows
    ],schema=PRIVATE_SCHEMA)
    L.checked_records(tab,target_year=start.year) if start.month==end.month else None
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_symlink():
        raise ValueError("Linked QMT Parquet candidate")
    scratch=target.with_suffix(".parquet.part")
    if scratch.is_symlink():
        raise ValueError("Linked QMT temp Parquet candidate")
    pq.write_table(tab,scratch,compression="zstd",row_group_size=8192)
    readback=pq.read_table(scratch)
    if not readback.equals(tab,check_metadata=False):
        raise ValueError("QMT Parquet roundtrip mismatch")
    os.replace(scratch,target)
    digest=L.hash_file(target)
    group=calibration.get(category(code))
    result={"status":"private_ohlcva_source_verified",
            "symbol":code,"rows":tab.num_rows,
            "first":rows[0]["datetime_cn"],"last":rows[-1]["datetime_cn"],
            "traded_days":requested,"sha256":digest,
            "source_canonical_sha256":sha_bytes(canonical(rows)),
            "fingerprint":fingerprint,
            "calibration_category":category(code),
            "calibrated_volume_factor":group["volume"]["factor"] if group else None,
            "calibrated_amount_factor":group["amount"]["factor"] if group else None,
            "calibrated_offset_ms":group["offset_ms"] if group else None,
            "paid_calibration_passed_for_category":group is not None,
            "daily_reference_checks":day_checks,
            "private_path":str(target),
            "market_modified":False}
    safe_save(meta,canonical(result))
    return result,True


def execute(root,start,end,limit=100,workspace=BASE,xtdata=None,logger=print):
    if start<date(2026,10,14) or end>datetime.now(CN).date() or start>end:
        raise ValueError("Only 2026-10-14 onward closed-session historical source windows")
    if (end-start).days>93:
        raise ValueError("Limit every resumable window to <=94 natural days")
    if type(limit) is not int or limit<0 or limit>10000:
        raise ValueError("Use --limit-stocks 0 for all, or 1..10000 for bounded batches")
    if xtdata is None:
        from xtquant import xtdata
    requested_end=end
    end=latest_certified_day(root,start,end)
    if end!=requested_end:
        logger(f"QMT_SOURCE_WINDOW_TRIMMED_TO_LAST_DAY_REFERENCE {requested_end} -> {end}; "
               "not claiming future/current unverified market-day completion")
    # Always calibrate first; do not silently accept a prior receipt after
    # local purchased Parquet bytes or server-side history have changed.
    calib=calibrate(root,xtdata,workspace,logger)
    if not calib["calibration_passed"]:
        logger("QMT_PAID_CALIBRATION_NOT_COMPLETE_STILL_SOURCE_ONLY_STAGING")
    expected,stocks,calendar_sha,files=official_day_universe(root,start,end)
    stage=Path(workspace)/f"{start:%Y%m%d}_{end:%Y%m%d}"
    stage.mkdir(parents=True,exist_ok=True)
    plan={"format":FORMAT,"window":[str(start),str(end)],
          "calendar_sha256":calendar_sha,"day_file_sha256":files,
          "stock_count":len(stocks),"trading_days":sorted(str(d) for d in expected),
          "calibration_sha256":sha_bytes(canonical(calib))}
    planpath=stage/"plan.json"
    if planpath.exists():
        if planpath.is_symlink() or planpath.read_bytes()!=canonical(plan):
            raise ValueError("Cached QMT stage bound to different DAY/calibration version")
    else:
        safe_save(planpath,canonical(plan))
    cached=0;accepted=0;failures={};attempted=0;stopped_early=False
    consecutive_failures=0
    for n,code in enumerate(stocks):
        receipt=stage/"receipts"/(code.replace(".","_")+".json")
        is_cached=receipt.exists()
        if not is_cached and limit and attempted>=limit:
            stopped_early=True
            continue
        if not is_cached:
            attempted+=1
        try:
            status,created=qmt_stage_stock(
                code,expected,start,end,calib["providers"],stage,xtdata)
            accepted+=1
            cached+=not created
            consecutive_failures=0
            if created:
                logger(f"QMT_PRIVATE_STAGED {accepted}/{len(stocks)} {code} "
                       f"rows={status['rows']} days={len(status['traded_days'])}")
            elif accepted%100==0:
                logger(f"QMT_PRIVATE_REUSE {accepted}/{len(stocks)}")
        except Exception as exc:
            failures[code]=f"{type(exc).__name__}: {exc}"[:270]
            consecutive_failures+=1
            logger(f"QMT_PRIVATE_QUARANTINE {code} {exc}")
            if consecutive_failures>=12:
                logger("QMT_CIRCUIT_BREAKER_12_CONSECUTIVE_FAILURES; safe partial stage retained")
                stopped_early=True
                break
        if not is_cached:
            time.sleep(.15)
    result={"format":FORMAT,"status":"PRIVATE_ONE_MINUTE_INTAKE",
            "range":[str(start),str(end)],"requested_end":str(requested_end),
            "expected_stocks":len(stocks),
            "accepted_stocks":accepted,"cached_stocks":cached,
            "download_attempts":attempted,"stopped_early":stopped_early,
            "pending_count":max(0,len(stocks)-accepted-len(failures)),
            "failure_count":len(failures),"failure_examples":list(failures.items())[:12],
            "total_rows_expected_for_241_day_stocks":sum(
                len([d for d in expected if code in expected[d]])*241 for code in stocks),
            "calibration_passed":calib["calibration_passed"],
            "calibration_failures":calib["failed"],"market_modified":False,
            "production_1min_merge_authorized":False,
            "stage_root":str(stage)}
    safe_save(stage/"last_report.json",canonical(result))
    logger("QMT_ONE_MINUTE_MARKET_RESULT="+json.dumps(result,ensure_ascii=False,sort_keys=True))
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,default=Path("D:/stock"))
    ap.add_argument("--start",type=date.fromisoformat,default=date(2026,10,14))
    ap.add_argument("--end",type=date.fromisoformat,default=date(2026,11,12))
    ap.add_argument("--limit-stocks",type=int,default=100,
                    help="0 all pending; default 100; resumable")
    args=ap.parse_args(argv)
    print("QMT_SINGLE_COMMAND_PAID_CALIBRATION_AND_FULL_MARKET_PRIVATE_STAGE")
    execute(args.root,args.start,args.end,args.limit_stocks)


if __name__=="__main__":
    main()
