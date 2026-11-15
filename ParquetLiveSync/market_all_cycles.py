#!/usr/bin/env python3
"""Single owner of the eight-period market-update workflow.

QMT 1m + TDX official DAY are independently SHA verified first. Higher
minutes are constructed ONLY from accepted purchased-calibrated 1m.
Closed WEEK/MONTH reuse existing purchased DAY timestamp/amount
cross-calibration. Each period has its own resumable physical commit.
No duplicate scheduler, no second QMT ingestion, no vendor H5 mutation.
"""
from __future__ import annotations
from datetime import date,datetime,timedelta
import json
from pathlib import Path

import local_layout as L
import market_month_storage as S
import market_derived_cycles as D
import rollup_week_month as R
import update_market as U

FORMAT="eight_period_single_market_updater_v1"
WEEK_RULES=S.STATE_DIR/"week_month_paid_rules.json"
MONTHS=[(2026,m) for m in range(5,10)]


def _week_source_stats(root):
    base=L.storage_root(root)
    refs={}
    for period in ("day","week","month"):
        for year,mon in MONTHS:
            path=base/period/f"{year}-{mon:02}.parquet"
            if path.is_symlink() or not path.is_file():
                raise ValueError("Missing purchased week/month calibration anchor "+str(path))
            stat=path.stat()
            refs[str(path)]={"size_bytes":stat.st_size,"mtime_ns":stat.st_mtime_ns}
    return refs


def week_month_rules(root, *, logger=print, workspace=S.STATE_DIR):
    path=Path(workspace)/"week_month_paid_rules.json"
    base=str(L.storage_root(root).resolve())
    stats=_week_source_stats(root)
    if path.exists():
        cached=S._json(path)
        if (cached.get("format")!=FORMAT or cached.get("root")!=base
                or cached.get("purchased_source_stat")!=stats
                or set(cached.get("periods",{}))!=set(R.PERIODS)):
            raise ValueError("Pinned historic purchased WEEK/MONTH source changed")
        logger("MARKET_WEEK_MONTH_CALIBRATION_REUSED")
        return cached["periods"]
    rules={period:R.audit_one(root,period) for period in R.PERIODS}
    S._save(path,{"format":FORMAT,"root":base,
                  "purchased_source_stat":stats,"periods":rules})
    logger("MARKET_WEEK_MONTH_PAID_RULES_SEALED="+json.dumps(
        {p:{"rule":r["rule"],"intraday_offset_ms":r["intraday_offset_ms"]}
         for p,r in rules.items()},sort_keys=True))
    return rules


def verified_qmt_trading_calendar(asof=None):
    """Actual SH exchange trading days; no invented holiday shortcuts.

    QMT xtdata returns Unix-ms integers or 8-digit YYYYMMDD strings,
    depending on the installed SDK. Reject ambiguous/empty responses.
    """
    from xtquant import xtdata
    asof=asof or datetime.now(L.UTC8).date()
    since=date(2026,10,13)
    raw=xtdata.get_trading_dates(
        "SH",start_time=since.strftime("%Y%m%d"),
        end_time=asof.strftime("%Y%m%d"),count=-1)
    if not isinstance(raw,(list,tuple)) or not raw:
        raise ValueError("QMT exchange trading calendar is unavailable")
    accepted=set()
    for item in raw:
        if isinstance(item,str):
            if len(item)!=8 or not item.isdigit():
                raise ValueError("Unexpected QMT trading date string")
            parsed=date(int(item[:4]),int(item[4:6]),int(item[6:]))
        elif type(item) in (int,float):
            number=int(item)
            if 20000101<=number<=20991231:
                txt=str(number)
                parsed=date(int(txt[:4]),int(txt[4:6]),int(txt[6:]))
            elif number>10**12:
                parsed=datetime.fromtimestamp(number/1000,tz=L.UTC8).date()
            elif number>10**9:
                parsed=datetime.fromtimestamp(number,tz=L.UTC8).date()
            else:
                raise ValueError("Unknown QMT trading-date epoch")
        else:
            raise ValueError("Unsupported QMT exchange trading calendar entry")
        if not since<=parsed<=asof or parsed.weekday()>=5:
            raise ValueError("QMT trading calendar returned an invalid date "+str(parsed))
        accepted.add(parsed)
    if len(accepted)<12 and (asof-since).days>35:
        raise ValueError("QMT exchange calendar appears incomplete")
    return accepted


def run(root, *, mode="auto", apply=True, requested_day=None,
        max_days=30, config=U.CONFIG_PATH, logger=print):
    """Update eight periods in dependency order, reporting all phase failures.

    The supplied mode controls QMT ingest: 'cycles' does higher periods
    only, using already-committed 1m and official DAY. A failed phase
    cannot be reported as an eight-cycle success.
    """
    if mode not in ("auto","daily","bootstrap","cycles"):
        raise ValueError("Unsupported eight-period update mode "+str(mode))
    root=Path(root)
    L.storage_root(root)
    parts={}
    errors={}
    calendar_cache={}
    def calendar():
        if "value" not in calendar_cache:
            calendar_cache["value"]=verified_qmt_trading_calendar(requested_day)
        return calendar_cache["value"]
    def phase(name,callback):
        try:
            parts[name]=callback()
            logger("MARKET_EIGHT_PHASE_PASS="+name)
        except (ValueError,RuntimeError,FileNotFoundError,OSError,
                KeyError,ImportError,TypeError) as exc:
            errors[name]=type(exc).__name__+": "+str(exc)[:1200]
            logger("MARKET_EIGHT_PHASE_BLOCK="+name+" "+errors[name])
    if mode!="cycles":
        phase("QMT_1MIN_AND_TDX_DAY",lambda:U.update(
            root,mode=mode,apply=apply,requested_date=requested_day,
            config=config,max_days=max_days,progress=logger))
    phase("5_15_30_60MIN",lambda:D.run(root,apply=apply,progress=logger))
    phase("CLOSED_WEEK_MONTH",lambda:R.run(
        root,apply=apply,log=logger,
        audits=week_month_rules(root,logger=logger),
        trade_dates=calendar(),
        asof=requested_day))
    if apply and mode in ("auto","daily") and "QMT_1MIN_AND_TDX_DAY" in parts:
        try:
            accepted=S.state_for(root)["periods"]["1min"]
            current=max(date.fromisoformat(d) for info in accepted.values()
                        for d in info["days"])
            cutoff=requested_day or U.last_eligible_day()
            expected=max(d for d in calendar() if d<=cutoff)
            if current<expected:
                errors["LATEST_REQUIRED_TRADING_DAY"]=(
                    "Official DAY/QMT minute source has not yet committed "+
                    expected.isoformat()+"; accepted only through "+current.isoformat())
                logger("MARKET_EIGHT_SOURCE_LAG="+errors["LATEST_REQUIRED_TRADING_DAY"])
        except (ValueError,KeyError,TypeError) as exc:
            errors["LATEST_REQUIRED_TRADING_DAY"]=type(exc).__name__+": "+str(exc)[:250]
    status=("PREVIEW" if not apply and not errors
            else "ALL_EIGHT_PERIOD_PHASES_COMPLETE" if not errors
            else "INCOMPLETE_RETRY_SAFELY")
    summary={"format":FORMAT,"status":status,"mode":mode,
             "applied":bool(apply),
             "periods_covered":["1min","5min","15min","30min","60min",
                                "day","week","month"],
             "closed_week_month_only":True,
             "phases_completed":sorted(parts),
             "phases_blocked":errors,
             "h5_modified":False}
    logger("MARKET_EIGHT_PERIOD_SUMMARY="+json.dumps(
        summary,ensure_ascii=False,sort_keys=True))
    if errors:
        raise RuntimeError("Eight-period update has unfinished phases: "+
                           "; ".join(k+" => "+v[:280] for k,v in errors.items()))
    return summary
