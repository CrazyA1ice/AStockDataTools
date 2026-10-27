"""Synthetic Parquet daily-vs-minute conservation tests: no licensed bars."""
import importlib.util
import json
import unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory

FILE=(Path(__file__).resolve().parents[1]/"tools"/
      "validate-parquet-day-to-minute.py")
SPEC=importlib.util.spec_from_file_location("parquet_day_minute_audit",FILE)
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

DAY=date(2026,8,24)
SYMBOL="SH600000"
STAMP=int(DAY.strftime("%Y%m%d"))*10000


def fixtures(volume_factor=1):
    one={}
    grid=M.expected_keys(DAY)
    for stamp in grid["1min"]:
        one[(SYMBOL,stamp)]=(10.0,11.0,9.0,10.0,1.0,100.0)
    five={}
    for stamp in grid["5min"]:
        n=len(M.validator.observed_one_minute_stamps(
            stamp,"five_start_minute_end_plus_opening_0930"))
        five[(SYMBOL,stamp)]=(10.0,11.0,9.0,10.0,float(n),100.0*n)
    day={ (SYMBOL,STAMP):(
        10.0,11.0,9.0,10.0,241.0*volume_factor,24100.0)}
    scans={p:{"duplicate_keys":0,"nonfinite_source_rows":0,
               "invalid_timestamp_rows":0} for p in ("1min","5min","day")}
    return one,five,day,scans


class ParquetThreeCycleConservationTests(unittest.TestCase):
    def test_exact_regular_grid_is_241_plus_48_with_0930(self):
        grids=M.expected_keys(DAY)
        self.assertEqual(len(grids["1min"]),241)
        self.assertEqual(len(grids["5min"]),48)
        self.assertIn(202608240930,grids["1min"])
        self.assertIn(202608240931,grids["1min"])
        self.assertIn(202608241500,grids["1min"])
        self.assertNotIn(202608241300,grids["1min"])
        self.assertIn(202608241300,grids["5min"])

    def test_synthetic_three_periods_all_strict_agree(self):
        one,five,day,scans=fixtures()
        r=M.audit_stock_day(
            DAY,(SYMBOL,),one,five,day,scans)[SYMBOL]
        self.assertEqual(r["parquet_1min_rows"],241)
        self.assertEqual(r["parquet_5min_rows"],48)
        self.assertEqual(r["one_minute_missing_expected_stamps"],0)
        self.assertEqual(r["five_minute_outside_expected_grid"],0)
        self.assertTrue(r["one_to_five_opening_rule_strict_48_of_48"])
        self.assertTrue(r["raw_all_three_periods_strict_agree"])
        self.assertTrue(r["day_vs_1min"]["strict_all_six_raw_agree"])
        self.assertTrue(r["day_vs_5min"]["strict_all_six_raw_agree"])
        self.assertEqual(r["day_vs_1min"][
            "relative_ratio_day_over_intraday"],
            {"volume":1.0,"amount":1.0})

    def test_daily_volume_hundredfold_is_flagged_not_auto_accepted(self):
        one,five,day,scans=fixtures(volume_factor=100)
        r=M.audit_stock_day(
            DAY,(SYMBOL,),one,five,day,scans)[SYMBOL]
        self.assertTrue(r["day_vs_1min"]["strict_ohlc_agree"])
        self.assertFalse(r["raw_all_three_periods_strict_agree"])
        self.assertFalse(r["day_vs_5min"]["strict_all_six_raw_agree"])
        self.assertTrue(r["day_vs_1min"][
            "volume_factor_strict_match"]["100"])
        self.assertTrue(r["day_vs_5min"][
            "volume_factor_strict_match"]["100"])
        self.assertFalse(r["day_vs_1min"][
            "volume_factor_strict_match"]["1"])
        self.assertTrue(r["unit_factor_matches_are_hypotheses_only"])

    def test_missing_a_minute_fails_closed_even_if_daily_matches_5min(self):
        one,five,day,scans=fixtures()
        del one[(SYMBOL,202608240931)]
        r=M.audit_stock_day(
            DAY,(SYMBOL,),one,five,day,scans)[SYMBOL]
        self.assertEqual(r["one_minute_missing_expected_stamps"],1)
        self.assertFalse(r["one_to_five_opening_rule_strict_48_of_48"])
        self.assertFalse(r["day_vs_1min"]["comparable"])
        self.assertTrue(r["day_vs_5min"]["strict_all_six_raw_agree"])
        self.assertFalse(r["raw_all_three_periods_strict_agree"])

    def test_missing_day_and_duplicate_source_fails_closed(self):
        one,five,day,scans=fixtures()
        missing=M.audit_stock_day(
            DAY,(SYMBOL,),one,five,{},scans)[SYMBOL]
        self.assertFalse(missing["day_bar_present"])
        self.assertFalse(missing["raw_all_three_periods_strict_agree"])
        scans["5min"]["duplicate_keys"]=1
        duplicated=M.audit_stock_day(
            DAY,(SYMBOL,),one,five,day,scans)[SYMBOL]
        self.assertFalse(duplicated["raw_all_three_periods_strict_agree"])
        self.assertFalse(duplicated["one_to_five_opening_rule_strict_48_of_48"])

    def test_extra_minute_and_bad_daily_bar_cannot_be_certified(self):
        one,five,day,scans=fixtures()
        one[(SYMBOL,202608241300)]=(10,11,9,10,1,100)
        r=M.audit_stock_day(
            DAY,(SYMBOL,),one,five,day,scans)[SYMBOL]
        self.assertEqual(r["one_minute_outside_expected_grid"],1)
        self.assertFalse(r["raw_all_three_periods_strict_agree"])
        one.pop((SYMBOL,202608241300))
        day[(SYMBOL,STAMP)]=(10,9,11,10,241,24100)
        r=M.audit_stock_day(
            DAY,(SYMBOL,),one,five,day,scans)[SYMBOL]
        self.assertIn("invalid_daily_ohlc_geometry",r[
            "day_quality"]["quality_issues"])
        self.assertFalse(r["raw_all_three_periods_strict_agree"])

    def test_only_aggregate_flags_and_ratios_not_paid_bars(self):
        one,five,day,scans=fixtures()
        output=M.audit_stock_day(
            DAY,(SYMBOL,),one,five,day,scans)
        serial=json.dumps(output)
        self.assertIn('"raw_all_three_periods_strict_agree": true',serial)
        self.assertNotIn('"open": 10',serial)
        self.assertNotIn('"volume": 241',serial)
        self.assertNotIn('"amount": 24100',serial)

    def test_generated_arrow_daily_parquet_is_normalized_to_day_key(self):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow unavailable in test interpreter")
        with TemporaryDirectory() as directory:
            root=Path(directory)
            folder=root/"AllCycleAStockData"/"day"
            folder.mkdir(parents=True)
            dt=datetime(2026,8,24,15,0,
                        tzinfo=timezone(timedelta(hours=8)))
            row={"ts":int(dt.timestamp()*1000),
                 "symbol":"600000.XSHG",
                 "open":10.0,"high":11.0,"low":9.0,"close":10.0,
                 "volume":241.0,"amount":24100.0}
            pq.write_table(pa.Table.from_pylist([row]),
                           folder/"2026-08.parquet")
            source,meta=M.validator.read_parquet_period(
                root,"day",DAY,(SYMBOL,),100)
            self.assertEqual(source[(SYMBOL,STAMP)],
                             (10,11,9,10,241,24100))
            self.assertEqual(meta["source_rows_examined"],1)
            self.assertEqual(meta["duplicate_keys"],0)


if __name__=="__main__":
    unittest.main()
