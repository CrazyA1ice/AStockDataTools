#!/usr/bin/env python3
"""Single owner of the eight-period market-update workflow.

QMT 1m + TDX official DAY are independently SHA verified first. Higher
minutes are constructed ONLY from accepted purchased-calibrated 1m.
Closed WEEK/MONTH reuse existing purchased DAY timestamp/amount
cross-calibration. Each period has its own resumable physical commit.
No duplicate scheduler, no second QMT ingestion, no vendor H5 mutation.
"""
from __future__ import annotations
from datetime import date
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
        asof=requested_day))
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
