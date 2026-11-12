"""Real temporary four-period Parquet month apply is ALL-MARKET gated."""
from datetime import date,datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import minute_market_sync as M
import minute_5m_rollup as R
import local_layout as L

CN=timezone(timedelta(hours=8))

def exact_bars(symbol,day=date(2026,11,2)):
    out=[]
    i=0
    for grid in R.GRID:
        for label in grid:
            hh,mm=map(int,label.split(":"))
            ts=int(datetime(day.year,day.month,day.day,hh,mm,
                            tzinfo=CN).timestamp()*1000)
            p=10.+.01*i
            out.append({
                "ts":ts,"symbol":symbol,"date":str(day),
                "local_time":label,
                "open":p,"high":p+.02,"low":p-.01,"close":p+.01,
                "provider_volume":100+i,"amount_yuan":100000+100*i})
            i+=1
    return out

def daily(stock):
    bars=exact_bars(stock)
    return {
        "symbol":stock,"ts":M.source_day_ts(date(2026,11,2)),
        "open":bars[0]["open"],"close":bars[-1]["close"],
        "high":max(x["high"] for x in bars),
        "low":min(x["low"] for x in bars),
        "volume":sum(x["provider_volume"]*100 for x in bars),
        "amount":sum(x["amount_yuan"] for x in bars)}

class MonthMarketMerge(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)/"stock"
        self.work=Path(tmp.name)/"work"
        self.work.mkdir()
        for period in L.PERIODS:
            (self.root/"AllCycleAStockData"/period).mkdir(parents=True)
        self.symbols=["SH600000","SZ000001"]
        self.days={date(2026,11,2):{s:daily(s) for s in self.symbols}}
        self.snapshot="a"*64
        self.gates={
            p:{"source_volume_to_purchased_factor":100.,
               "source_amount_to_purchased_factor":1.,
               "timestamp_offset_source_to_purchased_ms":0}
            for p in R.PERIODS}
        self.dates=dict(start=date(2026,11,2),end=date(2026,11,2))
        (self.work/"purchased_sep30_source_calibration.json").write_text(
            "{}",encoding="utf-8")
        self.cal_patch=patch.object(
            M,"check_calibration",return_value={"calibrations":self.gates})
        self.cal_patch.start()
        self.addCleanup(self.cal_patch.stop)
        self.real_official_days=M.official_days
        self.day_patch=patch.object(
            M,"official_days",return_value=(self.days,self.snapshot))
        self.day_patch.start()
        self.addCleanup(self.day_patch.stop)

    def collector(self,period,symbol,start,end,**kwargs):
        self.assertEqual(period,"5min")
        return {"pages":[{"raw_sha256":"b"*64}]},exact_bars(symbol)

    def test_daily_shares_vs_purchased_minute_lots_distinct_factors(self):
        bars=exact_bars("SH600000")
        source_day=daily("SH600000")
        # Old paid minute Kline may preserve lots, while official TDX
        # daily physical file independently stores shares.
        purchased_vendor_gate={
            "source_volume_to_purchased_factor":1.,
            "source_amount_to_purchased_factor":1.}
        M.compare_day("5min",date(2026,11,2),bars,
                      source_day,purchased_vendor_gate)
        self.assertEqual(sum(x["provider_volume"] for x in bars)*100,
                         source_day["volume"])

    def test_source_only_first_partial_stock_prevents_any_month_write(self):
        result=M.execute(self.root,work=self.work,limit=1,
                         collector=self.collector,
                         apply=True,logger=lambda _:None,**self.dates)
        self.assertEqual(result["status"],
                         "FOUR_MINUTE_PERIOD_STAGE_IN_PROGRESS_NOT_MERGED")
        self.assertEqual(result["stock_receipts_present"],1)
        for p in R.PERIODS:
            self.assertFalse(
                (self.root/"AllCycleAStockData"/p/"2026-11.parquet").exists())

    def test_resumable_full_market_commit_all_four_real_physical_month_files(self):
        first=M.execute(self.root,work=self.work,limit=1,
                        collector=self.collector,apply=True,
                        logger=lambda _:None,**self.dates)
        second=M.execute(self.root,work=self.work,limit=1,
                         collector=self.collector,apply=True,
                         logger=lambda _:None,**self.dates)
        self.assertEqual(first["stock_receipts_present"],1)
        self.assertEqual(second["status"],
                         "FOUR_MINUTE_PERIOD_MONTH_ATOMIC_SWAPS_COMPLETED")
        self.assertEqual(
            {x["period"]:x["added"] for x in second["commits"]},
            {"5min":96,"15min":32,"30min":16,"60min":8})
        for p,n in (("5min",96),("15min",32),("30min",16),("60min",8)):
            file=self.root/"AllCycleAStockData"/p/"2026-11.parquet"
            self.assertEqual(pq.read_table(file).num_rows,n)
            self.assertTrue(any(x["period"]==p for x in second["commits"]))

    def test_reapply_existing_rows_verifies_ohlcva_and_adds_zero(self):
        M.execute(self.root,work=self.work,limit=0,
                  collector=self.collector,apply=True,
                  logger=lambda _:None,**self.dates)
        def no_network(*a,**k):
            raise AssertionError("Source already cached; never redownload")
        done=M.execute(self.root,work=self.work,limit=0,
                       collector=no_network,apply=True,
                       logger=lambda _:None,**self.dates)
        self.assertEqual(done["status"],
                         "FOUR_MINUTE_PERIOD_MONTH_ATOMIC_SWAPS_COMPLETED")
        self.assertTrue(all(x["unchanged"] for x in done["commits"]))
        self.assertTrue(all(x["added"]==0 for x in done["commits"]))

    def test_day_turnover_inconsistency_blocks_stock_stage_and_month(self):
        self.days[date(2026,11,2)]["SH600000"]["amount"]*=2
        result=M.execute(self.root,work=self.work,limit=0,
                         collector=self.collector,apply=True,
                         logger=lambda _:None,**self.dates)
        self.assertEqual(result["stock_receipts_present"],1)
        self.assertEqual(result["status"],
                         "FOUR_MINUTE_PERIOD_STAGE_IN_PROGRESS_NOT_MERGED")
        self.assertIn("SH600000",result["source_or_coverage_failures"])

    def test_missing_5min_bar_blocks_stock_without_partial_derived_rows(self):
        def deficient(period,symbol,start,end,**kwargs):
            return {"pages":[]},exact_bars(symbol)[:-1]
        result=M.execute(self.root,work=self.work,limit=0,
                         collector=deficient,apply=True,
                         logger=lambda _:None,**self.dates)
        self.assertEqual(result["stock_receipts_present"],0)
        self.assertEqual(len(result["source_or_coverage_failures"]),2)
        self.assertFalse(
            (self.root/"AllCycleAStockData"/"5min"/"2026-11.parquet").exists())

    def test_original_purchased_october_source_baseline_protected(self):
        with self.assertRaisesRegex(ValueError,"OCTOBER_MINUTE_BASELINE_UNVERIFIED"):
            # Call saved REAL implementation; patching a mocked function
            # with wraps merely wraps the mock and hides the safety gate.
            self.real_official_days(self.root,date(2026,10,14),
                                    date(2026,10,14))

if __name__=="__main__":
    unittest.main()
