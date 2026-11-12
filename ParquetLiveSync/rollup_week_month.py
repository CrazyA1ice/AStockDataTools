#!/usr/bin/env python3
"""Strict, source-verified DAY -> WEEK/MONTH Parquet updater.

The official TDX daily ZIP has the full OHLCVA needed to derive longer
periods. Existing 2026-05..09 PURCHASED week/month/Day files are used to
infer actual target timestamp labels and verify the O/H/L/C/volume/amount
aggregation on many matching real stock/period keys. No guessing label
conventions or deriving full-OHLCVA minutes from Tencent's OHLCV source.

Only fully closed post-2026-10-13 weeks/months are considered. All ordinary
Monday-Friday dates after that historical cutoff MUST have a verified
official DAY overlay; 404 weekdays are not guessed to be holidays. Output
uses the existing AllCycleAStockData/<week|month>/YYYY-MM.parquet physical
files with SHA backups and atomic Parquet swaps. Default PREVIEW is read-only.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta
import json
from pathlib import Path
import statistics
import sys

import pyarrow as pa
import pyarrow.parquet as pq

from live_sync import (
    BASE_DAY,CN,WORK,parquet_schema,read_state,exclusive_writer,
    source_day_ts,
)
import local_layout as L

PERIODS=("week","month")
ANCHOR_MONTHS=((2026,m) for m in range(5,10))
MIN_CAL_SAMPLES=300
MIN_PRICE_MATCH=.94
MIN_OHLCVA_MATCH=.90
MIN_TIME_MATCH=.92
PRICE_EPS=.025
SUM_EPS=.04

def source_day(stamp):
    return L.market_ts_day(int(stamp))

def period_key(day,period):
    if period=="week":
        a=day.isocalendar()
        return (a.year,a.week)
    return (day.year,day.month)

def start_of(key,period):
    if period=="week":
        return date.fromisocalendar(key[0],key[1],1)
    return date(key[0],key[1],1)

def next_start(key,period):
    begin=start_of(key,period)
    if period=="week":
        return begin+timedelta(days=7)
    return date(begin.year+1,1,1) if begin.month==12 else date(begin.year,begin.month+1,1)

def monthly_path(stock_root,period,yr,mo):
    root=L.storage_root(stock_root)
    target=root/period/f"{yr}-{mo:02}.parquet"
    if target.is_symlink() or not target.is_file():
        raise ValueError("Missing trusted physical %s %04d-%02d Parquet"%(period,yr,mo))
    return target

def read_months(stock_root,period,months,*,required=True):
    paths=[]
    for y,m in months:
        try:
            paths.append(monthly_path(stock_root,period,y,m))
        except ValueError:
            if required:
                raise
    if not paths:
        return pa.Table.from_batches([],schema=parquet_schema())
    tables=[]
    for path in paths:
        frame=pq.read_table(path,columns=list(L.COLS))
        L.checked_records(frame)
        tables.append(frame)
    return pa.concat_tables(tables)

def aggregate_day(frame,period):
    if period not in PERIODS:
        raise ValueError("Unsupported bar rollup")
    records=frame.select(list(L.COLS)).to_pylist()
    grouped=defaultdict(list)
    used=set()
    for row in records:
        sym=L.normal_symbol(row["symbol"])
        ts=row["ts"]
        if (type(ts) is not int or any(
                row[field] is None for field in L.COLS[2:])):
            raise ValueError("Malformed purchased/TXD daily eight-column bar")
        key=(sym,ts)
        if key in used:
            raise ValueError("Duplicated normalized DAY stock/time during rollup")
        used.add(key)
        grouped[(sym,period_key(source_day(ts),period))].append(row)
    aggregate={}
    for (sym,key),raw in grouped.items():
        raw.sort(key=lambda x:x["ts"])
        aggregate[(sym,key)]={
            "symbol":sym,"key":key,
            "open":raw[0]["open"],"high":max(x["high"] for x in raw),
            "low":min(x["low"] for x in raw),"close":raw[-1]["close"],
            "volume":sum(x["volume"] for x in raw),
            "amount":sum(x["amount"] for x in raw),
            "first_traded":source_day(raw[0]["ts"]),
            "last_traded":source_day(raw[-1]["ts"]),
            "day_count":len(raw)}
    return aggregate

def timestamp_candidates(key,period,trading):
    begin=start_of(key,period)
    end=next_start(key,period)-timedelta(days=1)
    if period=="week":
        return {
            "first_calendar":begin,"last_calendar":end,
            "friday":begin+timedelta(days=4),
            "next_monday":begin+timedelta(days=7),
            "first_traded":trading["first_traded"],
            "last_traded":trading["last_traded"]}
    return {
        "first_calendar":begin,
        "last_calendar":end,
        "next_first":end+timedelta(days=1),
        "first_traded":trading["first_traded"],
        "last_traded":trading["last_traded"]}

def close_enough(a,b,*,relative,absolute):
    return (abs(float(a)-float(b)) <=
            max(absolute,relative*max(abs(float(a)),abs(float(b)))))

def price_match(aggregate,original):
    return all(close_enough(aggregate[name],original[name],
                            relative=.015,absolute=PRICE_EPS)
               for name in ("open","high","low","close"))

def all_match(aggregate,original):
    return price_match(aggregate,original) and all(
        close_enough(aggregate[name],original[name],
                     relative=SUM_EPS,absolute=100.0 if name=="amount" else 1.)
        for name in ("volume","amount"))

def audit_one(stock_root,period,*,calibration_months=None):
    """Conservatively infer time label from existing paid weekly/month data.

    Only interior weeks are compared to avoid a label crossing month/year;
    each source row must be from a complete purchased monthly set.
    """
    calibration_months=calibration_months or [(2026,m) for m in range(5,10)]
    source=read_months(stock_root,"day",calibration_months)
    existing=read_months(stock_root,period,calibration_months)
    day_groups=aggregate_day(source,period)
    matched=[]
    total_candidates=0
    price_pass=0
    all_pass=0
    for row in existing.to_pylist():
        stock=L.normal_symbol(row["symbol"])
        old_date=source_day(row["ts"])
        # Week timestamps are usually in their matching ISO week. A
        # next-Monday vendor convention is also supported as an option.
        candidates=[period_key(old_date,period)]
        if period=="week" and old_date.weekday()==0:
            # A vendor may date the completed week on NEXT Monday.
            # Do NOT treat a source row labeled Friday of an incomplete
            # edge-week as the previous FULL week's paid bar; that falsely
            # matched data and undermined the stamp-convention audit.
            candidates.append(period_key(old_date-timedelta(days=7),period))
        elif period=="month" and old_date.day==1:
            # Next-month-first labels are plausible only on the 1st.
            previous=old_date.replace(day=1)-timedelta(days=1)
            candidates.append(period_key(previous,period))
        for key in candidates:
            current=day_groups.get((stock,key))
            if not current:
                continue
            # Do not infer weekly labels using incomplete cross-month
            # groups at the edges of calibration months.
            begin=start_of(key,period)
            end=next_start(key,period)-timedelta(days=1)
            if period=="week":
                # Avoid end-of-month source windows with only 1-2 DAY
                # records (e.g. a week continuing outside our May-Sep
                # audit sample). They can coincidentally match a different
                # weekly vendor bar but cannot establish a weekly anchor.
                # 3+ actual trading-day observations per stock are
                # sufficient for calibration; legitimate short-holiday
                # weeks simply do not contribute calibration evidence.
                if current["day_count"]<3:
                    continue
                month_end=(
                    date(begin.year+1,1,1) if begin.month==12
                    else date(begin.year,begin.month+1,1))
                if not (begin>=date(begin.year,begin.month,1)
                        and end<month_end):
                    continue
            total_candidates+=1
            if price_match(current,row):
                price_pass+=1
            if all_match(current,row):
                all_pass+=1
                matched.append((row,current))
            break
    if total_candidates<MIN_CAL_SAMPLES:
        raise ValueError(
            f"INSUFFICIENT_{period.upper()}_PURCHASED_CALIBRATION_ROWS="
            f"{total_candidates} (needs {MIN_CAL_SAMPLES})")
    pf=price_pass/total_candidates
    af=all_pass/total_candidates
    if pf<MIN_PRICE_MATCH or af<MIN_OHLCVA_MATCH:
        raise ValueError(
            f"NONMATCHED_{period.upper()}_PURCHASED_OHLCVA"
            f" price_fit={pf:.4f} full_fit={af:.4f}"
            f" scanned={total_candidates}; original period convention not proven")
    patterns=Counter()
    offsets=Counter()
    for original,aggregate in matched:
        ts=int(original["ts"])
        day=source_day(ts)
        offset=ts-source_day_ts(day)
        offsets[offset]+=1
        for pattern,expected_day in timestamp_candidates(
                aggregate["key"],period,aggregate).items():
            if day==expected_day:
                patterns[pattern]+=1
    if not offsets:
        raise ValueError("No period label timestamp samples")
    offset,count=offsets.most_common(1)[0]
    if count/len(matched)<MIN_TIME_MATCH:
        raise ValueError("Purchased period timestamp time-of-day convention unstable")
    high=max(patterns.values(),default=0)
    best=[k for k,v in patterns.items()
          if v==high and v/len(matched)>=MIN_TIME_MATCH]
    # When the first/last trading day is also the calendar day in most
    # months, the candidates can tie. Prefer the explicit calendar rule
    # ONLY if that rule itself satisfies a strict threshold over holidays.
    preference=(
        ("friday","last_calendar","last_traded","first_calendar",
         "first_traded","next_monday")
        if period=="week" else
        ("last_calendar","last_traded","first_calendar","first_traded",
         "next_first"))
    choice=next((item for item in preference if item in best),None)
    if choice is None:
        raise ValueError(
            f"UNCERTAIN_{period.upper()}_PURCHASED_TIME_LABEL"
            f" coverage={high/len(matched):.4f}"
            f" matched={len(matched)} patterns={dict(patterns)}"
            f" offsets={dict(offsets.most_common(3))}; strict inference required")
    return {
        "period":period,"rule":choice,"intraday_offset_ms":offset,
        "source":"D:/stock/AllCycleAStockData historical purchased Day+"+period,
        "matched_purchased_rows":total_candidates,
        "price_match_fraction":round(pf,6),
        "full_ohlcva_match_fraction":round(af,6),
        "timestamp_fit":round(high/len(matched),6),
        "latest_allowed_day":"2026-10-13",
        "vendor_ohlcva_semantics_observed_only_not_global":True,
    }

def verified_recent_days(stock_root,state):
    # Current 2026 only, anchored on the accepted physical October + November.
    files=sorted((L.storage_root(stock_root)/"day").glob("2026-??.parquet"))
    dates=[]
    for path in files:
        item=L.classify_filename(path.name)
        if (item is not None and item[0]==2026 and item[1]>=10
                and not path.is_symlink()):
            dates.append((2026,item[1]))
    if not dates:
        raise ValueError("October/November day physical Parquet not yet available")
    return read_months(stock_root,"day",dates)

def ensure_weekday_complete(period,key,accepted_dates,state):
    begin=start_of(key,period)
    end=next_start(key,period)
    current=begin
    while current<end:
        if current>BASE_DAY and current.weekday()<5:
            if (str(current) not in accepted_dates
                    or str(current) not in state["days"]):
                raise ValueError(
                    f"UNVERIFIED_{period.upper()}_SOURCE_DAY={current};"
                    " weekday missing, not silently assuming holiday")
        current+=timedelta(days=1)

def build_candidates(stock_root,state,audits,*,asof=None):
    asof=asof or datetime.now(CN).date()
    daily=verified_recent_days(stock_root,state)
    aggregated={p:aggregate_day(daily,p) for p in PERIODS}
    accepted_dates={
        str(source_day(ts)) for ts in daily["ts"].to_pylist()
    }
    # The accepted old October slice was physically carried into the
    # 2026-10 month on first new TDX day. Require all four previously
    # SHA-pinned purchased trading days before deriving a week or month
    # containing the 2026-10-13 cutoff.
    required_legacy={"2026-10-08","2026-10-09",
                     "2026-10-12","2026-10-13"}
    if not required_legacy.issubset(accepted_dates):
        raise ValueError(
            "MISSING_PINNED_PRE_CUTOFF_OCTOBER_DAYS="+
            ",".join(sorted(required_legacy-accepted_dates))+
            "; no closed period can be safely derived")
    all_out={}
    for period in PERIODS:
        rows=[]
        audit=audits[period]
        for (sym,key),bar in aggregated[period].items():
            begin=start_of(key,period)
            end=next_start(key,period)
            if end>asof or end<=BASE_DAY:
                continue
            if period=="week" and begin<date(2026,10,12):
                continue
            if period=="month" and begin<date(2026,10,1):
                continue
            ensure_weekday_complete(period,key,accepted_dates,state)
            label_day=timestamp_candidates(key,period,bar)[audit["rule"]]
            offset=audit["intraday_offset_ms"]
            if not 0<=offset<86400000:
                raise ValueError("Unsafe inferred period timestamp offset")
            ts=source_day_ts(label_day)+offset
            rows.append({
                "ts":ts,"symbol":sym,
                **{v:float(bar[v]) for v in
                   ("open","high","low","close","volume","amount")}})
        all_out[period]=pa.Table.from_pylist(rows,schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(f,pa.float64()) for f in
              ("open","high","low","close","volume","amount"))]))
    return all_out

def run(root,*,apply=False,log=print,asof=None):
    root=Path(root)
    L.storage_root(root)
    state=read_state()
    if not state["calibration"]:
        raise ValueError("Official TDX DAY volume/amount unit calibration is absent")
    audits={p:audit_one(root,p) for p in PERIODS}
    for period,result in audits.items():
        log("PASSED_HISTORICAL_"+period.upper()+"_PURCHASED_ROLLUP_AUDIT="+
            json.dumps(result,sort_keys=True))
    built=build_candidates(root,state,audits,asof=asof)
    targets={}
    for period,table in built.items():
        targets[period]=dict(sorted(Counter(
            str(source_day(ts))[:7] for ts in table["ts"].to_pylist()
        ).items()))
    result={"mode":"APPLY" if apply else "READONLY_PREVIEW",
            "verified_purchased_calibration":audits,
            "candidate_rows":{period:table.num_rows for period,table in built.items()},
            "candidate_month_file_rows":targets,
            "original_h5_unchanged":True,
            "other_six_parquet_periods_unchanged":True,
            "weekly_monthly_write_only_if_explicit_apply":True,
            "all_eight_periods_up_to_date":False}
    if apply:
        with exclusive_writer():
            # Explicit lock; revalidate state under lock and prevent a
            # concurrent DAY writer from changing source between audit and
            # monthly materialization.
            reread=read_state()
            if reread["days"]!=state["days"]:
                raise ValueError("Official DAY source changed after audit, rerun")
            commits=[]
            for period in PERIODS:
                values=defaultdict(list)
                for row in built[period].to_pylist():
                    day=source_day(row["ts"])
                    if day.year!=datetime.now(CN).year:
                        raise ValueError("Only current-year week/month monthly files writable")
                    values[(day.year,day.month)].append(row)
                for (year,month),records in sorted(values.items()):
                    group=pa.Table.from_pylist(records,schema=built[period].schema)
                    done=L.write_month(root,period,year,month,group,WORK,
                                       current_year=year)
                    commits.append({"period":period,"year":year,
                                    "month":month,**done})
                    log("PASS_LOCAL_"+period.upper()+"_MONTH_PARQUET "+
                        f"{year}-{month:02} NEW_KEYS={done['added']}"+
                        f" TOTAL={done['total_rows']} TARGET={done['target']}")
            result["commits"]=commits
    log("DAY_DERIVED_WEEK_MONTH_RESULT="+json.dumps(
        result,sort_keys=True,ensure_ascii=False))
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path("D:/stock"))
    parser.add_argument("--apply-to-local-week-month",action="store_true")
    args=parser.parse_args()
    run(args.root,apply=args.apply_to_local_week_month)

if __name__=="__main__":
    main()
