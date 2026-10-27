"""Synthetic, source-independent Parquet-only aggregation tests.

No paid H5 or Parquet data are needed.
"""
import importlib.util
import json
import math
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

SOURCE=(Path(__file__).resolve().parents[1]/"tools"/
        "validate-parquet-1min-to-5min.py")
SPEC=importlib.util.spec_from_file_location(
    "parquet_only_minute_to_five_validation",SOURCE)
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SYMBOL="SH688629"
DAY=date(2026,9,28)


def synthetic_pair(symbol=SYMBOL, day=DAY):
    one,five={},{}
    for hour,minute in ((9,30),(13,0)):
        current=datetime(day.year,day.month,day.day,hour,minute)
        for group in range(24):
            start=current+timedelta(minutes=5*group)
            raw=[]
            for m in range(5):
                dt=start+timedelta(minutes=m)
                t=int(dt.strftime("%Y%m%d%H%M"))
                price=10.0+group*.03+m*.001
                raw.append((price,price+.01,price-.01,price+.003,
                            5.0+m, (5.0+m)*price*100))
                one[(symbol,t)]=raw[-1]
            stamp=int(start.strftime("%Y%m%d%H%M"))
            five[(symbol,stamp)]=(
                raw[0][0],max(r[1] for r in raw),
                min(r[2] for r in raw),raw[-1][3],
                math.fsum(r[4] for r in raw),
                math.fsum(r[5] for r in raw))
    return one,five


def scanned(duplicates=0,nonfinite=0):
    return {"duplicate_keys":duplicates,"nonfinite_source_rows":nonfinite,
            "availability":"source_files_present"}


class ParquetOnlyMinuteAggregationTests(unittest.TestCase):
    def test_four_timestamp_hypotheses_consider_both_period_labels(self):
        start=202609280930
        self.assertEqual(M.observed_one_minute_stamps(
            start,"five_start_minute_start"),
            (202609280930,202609280931,202609280932,
             202609280933,202609280934))
        self.assertEqual(M.observed_one_minute_stamps(
            start,"five_start_minute_end"),
            (202609280931,202609280932,202609280933,
             202609280934,202609280935))
        end=202609280935
        self.assertEqual(M.observed_one_minute_stamps(
            end,"five_end_minute_start"),
            (202609280930,202609280931,202609280932,
             202609280933,202609280934))
        self.assertEqual(M.observed_one_minute_stamps(
            end,"five_end_minute_end"),
            (202609280931,202609280932,202609280933,
             202609280934,202609280935))
        with self.assertRaises(ValueError):
            M.observed_one_minute_stamps(start,"no_such_hypothesis")

    def test_full_48_start_labeled_parquet_matches_strict_and_tolerant(self):
        one,five=synthetic_pair()
        self.assertEqual(len(one),240)
        self.assertEqual(len(five),48)
        report=M.compare_symbols(one,five,scanned(),scanned(),(SYMBOL,),DAY)[SYMBOL]
        self.assertEqual(report["availability"],
                         "testable_parquet_both_periods_available")
        self.assertEqual(report["best_internal_convention_candidate"],
                         "five_start_minute_start")
        self.assertTrue(report["internal_5min_all_bars_tolerance_match"])
        exact=report["hypotheses"]["five_start_minute_start"]
        d=exact["whole_day"]
        self.assertEqual(d["complete_one_minute_windows"],48)
        self.assertEqual(d["incomplete_one_minute_windows"],0)
        self.assertEqual(d["ohlc_strict_all_agree"],48)
        self.assertEqual(d["strict_all_six_fields_agree"],48)
        self.assertEqual(d["existing_tolerance_all_six_fields_agree"],48)
        self.assertEqual(d["volume_factor_existing_tolerance_nonzero"]["1"],48)
        self.assertEqual(d["volume_factor_existing_tolerance_nonzero"]["100"],0)
        self.assertEqual(exact["morning"]["complete_one_minute_windows"],24)
        self.assertEqual(exact["afternoon"]["complete_one_minute_windows"],24)
        self.assertFalse(report["one_minute_quality"]["issue_counts"])

    def test_wrong_time_convention_does_not_fake_full_match(self):
        one,five=synthetic_pair()
        winner=M.compare_one_hypothesis(
            one,five,SYMBOL,"five_start_minute_start")["whole_day"]
        wrong=M.compare_one_hypothesis(
            one,five,SYMBOL,"five_start_minute_end")["whole_day"]
        self.assertEqual(winner["strict_all_six_fields_agree"],48)
        self.assertLess(wrong["strict_all_six_fields_agree"],48)
        self.assertLess(wrong["complete_one_minute_windows"],48)
        self.assertEqual(M.quality_checks(five,SYMBOL,"5min",DAY)[
            "unique_keys"],48)

    def test_minute_missing_never_counts_as_value_mismatch(self):
        one,five=synthetic_pair()
        del one[(SYMBOL,202609280931)]
        result=M.compare_one_hypothesis(
            one,five,SYMBOL,"five_start_minute_start")
        self.assertEqual(result["whole_day"]["complete_one_minute_windows"],47)
        self.assertEqual(result["whole_day"]["incomplete_one_minute_windows"],1)
        self.assertEqual(result["whole_day"]["strict_all_six_fields_agree"],47)
        self.assertEqual(result["missing_five_minute_source_stamps_examples"],
                         ["202609280930"])
        report=M.compare_symbols(
            one,five,scanned(),scanned(),(SYMBOL,),DAY)[SYMBOL]
        self.assertFalse(report["internal_5min_all_bars_tolerance_match"])

    def test_large_ohlc_disagreement_blocks_internal_approval(self):
        one,five=synthetic_pair()
        b=five[(SYMBOL,202609280930)]
        five[(SYMBOL,202609280930)]=(b[0]+.05,*b[1:])
        result=M.compare_symbols(
            one,five,scanned(),scanned(),(SYMBOL,),DAY)[SYMBOL]
        self.assertFalse(result["internal_5min_all_bars_tolerance_match"])
        best=result["hypotheses"]["five_start_minute_start"]["whole_day"]
        self.assertEqual(best["strict_field_agree"]["open"],47)
        self.assertEqual(best["existing_tolerance_field_agree"]["open"],47)
        self.assertEqual(best["strict_all_six_fields_agree"],47)

    def test_volume_hundredfold_error_exposed_as_candidate_not_passed(self):
        one,five=synthetic_pair()
        for key,b in list(five.items()):
            five[key]=(*b[:4],b[4]*100,b[5])
        result=M.compare_symbols(
            one,five,scanned(),scanned(),(SYMBOL,),DAY)[SYMBOL]
        self.assertFalse(result["internal_5min_all_bars_tolerance_match"])
        best=result["hypotheses"]["five_start_minute_start"]["whole_day"]
        self.assertEqual(best["volume_factor_existing_tolerance_nonzero"]["1"],0)
        self.assertEqual(best["volume_factor_existing_tolerance_nonzero"]["100"],48)
        self.assertEqual(best["strict_all_six_fields_agree"],0)

    def test_missing_source_and_duplicate_keys_are_not_approved(self):
        one,five=synthetic_pair()
        missing=M.compare_symbols({},five,scanned(),scanned(),(SYMBOL,),DAY)[SYMBOL]
        self.assertEqual(missing["availability"],
                         "not_verifiable_no_parquet_1min_rows")
        self.assertIsNone(missing["best_internal_convention_candidate"])
        duplicate=M.compare_symbols(
            one,five,scanned(duplicates=1),scanned(),(SYMBOL,),DAY)[SYMBOL]
        self.assertEqual(duplicate["availability"],
                         "not_verifiable_duplicate_parquet_keys")
        self.assertEqual(duplicate["hypotheses"],{})
        corrupt=M.compare_symbols(
            one,five,scanned(),scanned(nonfinite=1),(SYMBOL,),DAY)[SYMBOL]
        self.assertFalse(corrupt["internal_5min_all_bars_tolerance_match"])

    def test_boundary_and_negative_ohlc_quality_flags(self):
        one,five=synthetic_pair()
        bad=five[(SYMBOL,202609280930)]
        five[(SYMBOL,202609280930)]=(
            bad[0],bad[1]-1,bad[2],bad[3],-1,bad[5])
        out=M.quality_checks(five,SYMBOL,"5min",DAY)
        self.assertEqual(out["issue_counts"]["bad_ohlc_geometry"],1)
        self.assertEqual(out["issue_counts"]["negative_volume_or_amount"],1)

    def test_shareable_json_has_aggregate_counters_not_prices(self):
        one,five=synthetic_pair()
        out=M.compare_symbols(
            one,five,scanned(),scanned(),(SYMBOL,),DAY)
        serialized=json.dumps(out,ensure_ascii=False)
        self.assertNotIn('"h_normalized"',serialized)
        self.assertNotIn('"openPrice"',serialized)
        self.assertNotIn('"raw_ohlcv"',serialized)
        self.assertIn('"strict_all_six_fields_agree": 48',serialized)


if __name__=="__main__":
    unittest.main()
