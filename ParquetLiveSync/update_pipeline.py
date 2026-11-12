#!/usr/bin/env python3
"""One local Parquet update: official DAILY -> fully closed WEEK/MONTH.

Source: a-stock-data/TDX official g4day ZIP; NO H5 writes. Runs
the already-proven existing tools in chronological order, without
conflating a successful daily physical commit with weekly/monthly success.

- Explicit --apply only; no background task is installed by this script.
- Rolling 90-calendar-day retry window for skipped/unpublished TDX dates.
- Per-day source ZIP + Parquet SHA verification; original DAY month backed up.
- Historical paid week/month OHLCVA+timestamp calibration before each rollup.
- An incomplete/rejected weekday must STOP the dependent weekly/monthly
  rollup rather than minting partial bars. Daily commits are retained.
- Repeated runs keep existing (ts,symbol) period values unchanged.
"""
from __future__ import annotations

import argparse
from datetime import date,timedelta
import json
from pathlib import Path

from live_sync import BASE_DAY,latest_yesterday,safe_window,sync
import rollup_week_month as R
import local_layout as L

def window(*,end=None,start=None,retry_days=90):
    if type(retry_days) is not int or not 1<=retry_days<=180:
        raise ValueError("Recent-day retry horizon must be 1..180 calendar days")
    end=end or latest_yesterday()
    start=start or max(BASE_DAY+timedelta(days=1),
                       end-timedelta(days=retry_days-1))
    safe_window(start,end,max_days=180)
    return start,end

def run(root,*,start=None,end=None,retry_days=90,apply=False,
        logger=print,stop=None,verify_week_month=True):
    """Explicit physical update; return separate DAY + WEEK/MONTH receipts.

    In dry mode the only output is a planned date window and prior SHA
    readiness; no source downloads or market file writes.
    """
    root=Path(root)
    local=L.storage_root(root)
    start,end=window(end=end,start=start,retry_days=retry_days)
    if not apply:
        result={
            "status":"READONLY_UPDATE_PLAN",
            "stock_root":str(root),
            "physical_eight_period_root":str(local),
            "day_window":[start.isoformat(),end.isoformat()],
            "candidate_calendar_dates":(end-start).days+1,
            "future_behavior":"Official TDX DAY then strict purchased-calibrated completed WEEK/MONTH",
            "week_month_write_requires_explicit_apply":True,
            "other_five_periods_and_h5_unchanged":True,
        }
        logger("PARQUET_AUTOPILOT_PLAN="+json.dumps(result,ensure_ascii=False,sort_keys=True))
        return result
    if stop is not None and stop():
        return {"status":"STOPPED_BEFORE_ANY_WRITE","day":None,
                "week_month":None}
    logger("PARQUET_AUTOPILOT_STEP_1_OF_2=OFFICIAL_DAY_SHA_AND_LOCAL_MONTH")
    day_result=sync(root,start,end,max_days=180,logger=logger,
                    stop=stop,materialize_local=True)
    if stop is not None and stop():
        result={"status":"STOPPED_AFTER_DAILY_COMMITS",
                "day":day_result,"week_month":None,
                "daily_commits_preserved":True}
        logger("PARQUET_AUTOPILOT_PAUSED="+json.dumps(result,ensure_ascii=False,sort_keys=True))
        return result
    if not verify_week_month:
        result={"status":"DAY_ONLY_SUCCESS","day":day_result,
                "week_month":None,"original_H5_unchanged":True}
        logger("PARQUET_AUTOPILOT_DAY_ONLY="+json.dumps(result,ensure_ascii=False,sort_keys=True))
        return result
    logger("PARQUET_AUTOPILOT_STEP_2_OF_2=STRICT_CLOSED_WEEK_MONTH")
    # run() rechecks locally owned SHA receipts, entire source-market monthly
    # files, purchased 2026 May-Sep consistency and the complete weekday
    # envelope; it then acquires its own exclusive physical-writer lock.
    # Never hide a failed weekly/monthly validation as complete.
    derived_result=R.run(root,apply=True,log=logger)
    result={"status":"DAY_WEEK_MONTH_COMPLETED_AND_SHA_BACKED",
            "day":day_result,"week_month":derived_result,
            "original_H5_unchanged":True,
            "minute_and_other_periods_unchanged":True,
            "all_eight_periods_up_to_date":False}
    logger("PARQUET_AUTOPILOT_RESULT="+json.dumps(
        result,ensure_ascii=False,sort_keys=True))
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("D:/stock"))
    parser.add_argument("--from-day",type=date.fromisoformat,default=None)
    parser.add_argument("--through-day",type=date.fromisoformat,default=None)
    parser.add_argument("--recent-days",type=int,default=90)
    parser.add_argument("--apply",action="store_true",
                        help="Explicitly permit actual local DAY/WEEK/MONTH Parquet month writes")
    args=parser.parse_args()
    run(args.root,start=args.from_day,end=args.through_day,
        retry_days=args.recent_days,apply=args.apply)

if __name__=="__main__":
    main()
