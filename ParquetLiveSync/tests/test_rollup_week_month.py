"""Real synthetic Arrow paid DAY/WEEK/MONTH sample, offline and fail-closed."""
from __future__ import annotations

from datetime import date,datetime,timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import rollup_week_month as R
import local_layout as L
import live_sync as S

def week_days(start,end):
    day=start
    while day<=end:
        if day.weekday()<5:
            yield day
        day+=timedelta(days=1)

def stamp(day):
    return S.source_day_ts(day)+34200000

def frame(rows):
    return pa.Table.from_pylist(rows,schema=S.parquet_schema())

def fields(day,sym,p):
    return {"ts":stamp(day),"symbol":sym,
            "open":p,"high":p+1.,"low":p-.5,"close":p+.3,
            "volume":1000.,"amount":10000.}

class WeekMonthStrictPurchasedCalibration(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)/"stock"
        self.work=Path(folder.name)/"work"
        self.work.mkdir()
        self.data=self.root/"AllCycleAStockData"
        for period in L.PERIODS:
            (self.data/period).mkdir(parents=True)
        self.symbols=[f"SH{600000+i:06}" for i in range(80)]
        self.legacy_daily=[]
        for month in range(5,10):
            rows=[]
            for day in week_days(date(2026,month,1),
                                  (date(2026,month+1,1) if month<12
                                   else date(2027,1,1))-timedelta(days=1)):
                for i,sym in enumerate(self.symbols):
                    rows.append(fields(day,sym,10.+i*.2+(day.day*.01)))
            self.legacy_daily.extend(rows)
            pq.write_table(frame(rows),self.data/"day"/f"2026-{month:02}.parquet")
        for period in R.PERIODS:
            aggregated=R.aggregate_day(frame(self.legacy_daily),period)
            grouped={}
            for (sym,key),item in aggregated.items():
                # Original source timestamp convention: all complete
                # weekly data use Friday, monthly use the LAST TRADED DAY.
                day=(R.start_of(key,period)+timedelta(days=4)
                     if period=="week" else item["last_traded"])
                row={"ts":stamp(day),"symbol":sym,
                     **{k:item[k] for k in
                        ("open","high","low","close","volume","amount")}}
                grouped.setdefault((day.year,day.month),[]).append(row)
            for (year,month),items in grouped.items():
                if year==2026 and 5<=month<=9:
                    pq.write_table(frame(items),
                        self.data/period/f"{year}-{month:02}.parquet")
        self.work_state=S.initial_state()
        self.work_state["calibration"]={
            "anchor_day":"2026-09-30","baseline_sha256":S.BASE_SHA,
            "tdx_shares_to_local_volume":1,
            "tdx_yuan_to_local_amount":1,
            "local_day_ts_offset_ms":34200000}
        self.patch=[]
        for name,val in (("WORK",self.work),("STATE",self.work/"state.json")):
            p=patch.object(S,name,val)
            p.start()
            self.addCleanup(p.stop)
        # Rollup module imports immutable same live WORK value at import;
        # patch it independently for synthetic artifact creation.
        p=patch.object(R,"WORK",self.work)
        p.start()
        self.addCleanup(p.stop)

    def create_recent(self,*,all_days=True):
        recent=[]
        overlay={}
        days=list(week_days(date(2026,10,12),date(2026,10,30)))+list(
            week_days(date(2026,11,2),date(2026,11,11)))
        for day in days:
            if not all_days and day==date(2026,10,21):
                continue
            for i,sym in enumerate(self.symbols):
                recent.append(fields(day,sym,20.+i*.2+day.day*.01))
            if day>S.BASE_DAY:
                overlay[str(day)]={"file":"fake","rows":80}
        for month in (10,11):
            rows=[x for x in recent
                  if L.market_ts_day(x["ts"]).month==month]
            pq.write_table(frame(rows),self.data/"day"/f"2026-{month:02}.parquet")
        return overlay

    def test_price_volume_amount_and_timestamp_labels_calibrate_exactly(self):
        weeks=R.audit_one(self.root,"week")
        months=R.audit_one(self.root,"month")
        self.assertEqual(weeks["rule"],"friday")
        self.assertEqual(months["rule"],"last_traded")
        self.assertEqual(weeks["intraday_offset_ms"],34200000)
        self.assertEqual(months["intraday_offset_ms"],34200000)
        self.assertEqual(weeks["full_ohlcva_match_fraction"],1)
        self.assertEqual(months["full_ohlcva_match_fraction"],1)
        self.assertGreaterEqual(months["matched_purchased_rows"],300)

    def test_real_purchased_period_amount_drift_aborts_all_updates(self):
        source=self.data/"month"/"2026-08.parquet"
        frame0=pq.read_table(source)
        broken=frame0.set_column(
            frame0.schema.get_field_index("amount"),"amount",
            pa.array([float(x)*100 for x in frame0["amount"].to_pylist()]))
        pq.write_table(broken,source)
        with self.assertRaisesRegex(ValueError,"NONMATCHED_MONTH_PURCHASED_OHLCVA"):
            R.audit_one(self.root,"month")

    def test_closed_week_and_month_only_not_current_incomplete_week(self):
        overlay=self.create_recent()
        self.work_state["days"]=overlay
        audit={"week":{"rule":"friday","intraday_offset_ms":34200000},
               "month":{"rule":"last_traded","intraday_offset_ms":34200000}}
        built=R.build_candidates(
            self.root,self.work_state,audit,asof=date(2026,11,12))
        weekly=built["week"]
        monthly=built["month"]
        self.assertEqual(weekly.num_rows,80*4)
        self.assertEqual(monthly.num_rows,80)
        weekly_days={str(L.market_ts_day(ts)) for ts in weekly["ts"].to_pylist()}
        self.assertEqual(weekly_days,{
            "2026-10-16","2026-10-23","2026-10-30","2026-11-06"})
        self.assertEqual(
            {str(L.market_ts_day(ts)) for ts in monthly["ts"].to_pylist()},
            {"2026-10-30"})

    def test_missing_midweek_official_zip_prevents_deriving_closed_week(self):
        overlay=self.create_recent(all_days=False)
        self.work_state["days"]=overlay
        audit={"week":{"rule":"friday","intraday_offset_ms":34200000},
               "month":{"rule":"last_traded","intraday_offset_ms":34200000}}
        with self.assertRaisesRegex(ValueError,"UNVERIFIED_WEEK_SOURCE_DAY=2026-10-21"):
            R.build_candidates(self.root,self.work_state,audit,
                               asof=date(2026,11,12))

    def test_derived_price_open_first_high_max_low_min_close_last_and_sums(self):
        sample=frame([
            fields(date(2026,10,14),"SH600000",10.),
            fields(date(2026,10,15),"SH600000",20.),
            fields(date(2026,10,16),"SH600000",15.),
        ])
        out=R.aggregate_day(sample,"week")
        item=next(iter(out.values()))
        self.assertEqual(item["open"],10.)
        self.assertEqual(item["high"],21.)
        self.assertEqual(item["low"],9.5)
        self.assertEqual(item["close"],15.3)
        self.assertEqual(item["volume"],3000.)
        self.assertEqual(item["amount"],30000.)

    def test_explicit_apply_creates_same_monthly_shards_without_rewriting_day(self):
        overlay=self.create_recent()
        state=self.work_state
        # The source state itself is verified/returned in this synthetic
        # test, whereas production always verifies private SHA receipts.
        audits={"week":{"rule":"friday","intraday_offset_ms":34200000},
                "month":{"rule":"last_traded","intraday_offset_ms":34200000}}
        with patch.object(R,"read_state",return_value=state):
            with patch.object(R,"audit_one",side_effect=lambda root,p:audits[p]):
                with patch.object(R,"exclusive_writer",S.exclusive_writer):
                    result=R.run(self.root,apply=True,asof=date(2026,11,12),
                                 log=lambda _:None)
        self.assertEqual(len(result["commits"]),3)
        self.assertEqual(
            pq.read_table(self.data/"week"/"2026-10.parquet").num_rows,240)
        self.assertEqual(
            pq.read_table(self.data/"week"/"2026-11.parquet").num_rows,80)
        self.assertEqual(
            pq.read_table(self.data/"month"/"2026-10.parquet").num_rows,80)
        self.assertFalse((self.data/"month"/"2026-11.parquet").exists())
        self.assertEqual(
            pq.read_table(self.data/"day"/"2026-11.parquet").num_rows,
            80*8)

if __name__=="__main__":
    unittest.main()
