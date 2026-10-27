"""Synthetic, source-independent Parquet-only aggregation tests.

No paid H5 or Parquet data are needed.
"""
import importlib.util
import json
import math
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

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


def with_0930_opening_extra():
    """Make an internally consistent 241×1min and 48×5min synthetic day.

    Parquet 1min is END-labelled (09:31..11:30, 13:01..15:00)
    plus a separate 09:30 auction record. Five-minute labels are START.
    """
    minute_start, five_start = synthetic_pair()
    minute_end = {
        (sym, M.diagnose.shift_bar_stamp(stamp, 1)): tuple(values)
        for (sym, stamp), values in minute_start.items()
    }
    auction = (9.7, 10.0, 9.5, 9.75, 17.0, 1670.0)
    minute_end[(SYMBOL, 202609280930)] = auction
    first = five_start[(SYMBOL, 202609280930)]
    five_start[(SYMBOL, 202609280930)] = (
        auction[0], max(auction[1], first[1]),
        min(auction[2], first[2]), first[3],
        first[4] + auction[4], first[5] + auction[5]
    )
    return minute_end, five_start


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

    def test_0930_opening_sixth_minute_only_in_first_5min_window(self):
        opening = "five_start_minute_end_plus_opening_0930"
        self.assertEqual(
            M.observed_one_minute_stamps(202609280930, opening),
            (202609280930, 202609280931, 202609280932,
             202609280933, 202609280934, 202609280935))
        self.assertEqual(
            M.observed_one_minute_stamps(202609280935, opening),
            (202609280936, 202609280937, 202609280938,
             202609280939, 202609280940))
        self.assertEqual(
            M.observed_one_minute_stamps(202609281300, opening),
            (202609281301, 202609281302, 202609281303,
             202609281304, 202609281305))

    def test_opening_0930_explains_47_of_48_and_is_counted_once(self):
        one, five = with_0930_opening_extra()
        self.assertEqual(len(one), 241)
        self.assertEqual(len(five), 48)
        base = M.compare_one_hypothesis(
            one, five, SYMBOL, "five_start_minute_end")
        self.assertEqual(base["whole_day"]["complete_one_minute_windows"], 48)
        self.assertEqual(base["whole_day"]["strict_all_six_fields_agree"], 47)
        self.assertEqual(
            base["mismatched_five_minute_source_stamps_examples"][0][
                "five_minute_source_stamp"], "202609280930")
        self.assertEqual(set(base[
            "mismatched_five_minute_source_stamps_examples"][0][
                "strict_mismatched_fields"]),
                {"open", "low", "volume", "amount"})
        report=M.compare_symbols(
            one, five, scanned(), scanned(), (SYMBOL,), DAY)[SYMBOL]
        self.assertEqual(report["best_internal_convention_candidate"],
                         "five_start_minute_end_plus_opening_0930")
        self.assertTrue(report["opening_0930_one_minute_key_present"])
        self.assertTrue(report["first_0930_five_minute_key_present"])
        self.assertTrue(report["opening_0930_included_once_by_candidate"])
        self.assertTrue(report["internal_5min_all_bars_tolerance_match"])
        best = report["hypotheses"][
            "five_start_minute_end_plus_opening_0930"]
        self.assertEqual(best["whole_day"]["strict_all_six_fields_agree"], 48)
        self.assertEqual(best["whole_day"][
            "volume_factor_existing_tolerance_nonzero"]["1"], 48)
        self.assertEqual(best["morning"]["strict_all_six_fields_agree"], 24)
        self.assertEqual(best["afternoon"]["strict_all_six_fields_agree"], 24)
        self.assertEqual(best[
            "mismatched_five_minute_source_stamps_examples"], [])

    def test_opening_0930_missing_fails_closed_while_base_may_pass(self):
        one, five=with_0930_opening_extra()
        del one[(SYMBOL, 202609280930)]
        # Standard five-start/minute-end still has five data records, but
        # the six-record opening hypothesis cannot silently use only five.
        special = M.compare_one_hypothesis(
            one, five, SYMBOL, "five_start_minute_end_plus_opening_0930")
        self.assertEqual(special["whole_day"]["complete_one_minute_windows"], 47)
        self.assertEqual(
            special["missing_five_minute_source_stamps_examples"],
            ["202609280930"])
        overall=M.compare_symbols(
            one, five, scanned(), scanned(), (SYMBOL,), DAY)[SYMBOL]
        self.assertFalse(overall["internal_5min_all_bars_tolerance_match"])
        self.assertFalse(overall["opening_0930_one_minute_key_present"])

    def test_five_end_minute_start_can_be_internal_match_too(self):
        one, five_start=synthetic_pair()
        five_end={
            (symbol, M.diagnose.shift_bar_stamp(stamp, 5)): row
            for (symbol, stamp), row in five_start.items()
        }
        report=M.compare_symbols(
            one,five_end,scanned(),scanned(),(SYMBOL,),DAY)[SYMBOL]
        self.assertEqual(report["best_internal_convention_candidate"],
                         "five_end_minute_start")
        self.assertTrue(report["internal_5min_all_bars_tolerance_match"])
        self.assertEqual(report["hypotheses"]["five_end_minute_start"][
            "whole_day"]["strict_all_six_fields_agree"],48)
        self.assertFalse(report["five_minute_quality"]["issue_counts"])

    def test_all_zero_volume_does_not_certify_volume_factor(self):
        one,five=synthetic_pair()
        one={key:(*bar[:4],0,bar[5]) for key,bar in one.items()}
        five={key:(*bar[:4],0,bar[5]) for key,bar in five.items()}
        report=M.compare_symbols(
            one,five,scanned(),scanned(),(SYMBOL,),DAY)[SYMBOL]
        best=report["hypotheses"]["five_start_minute_start"]["whole_day"]
        self.assertEqual(best["strict_all_six_fields_agree"],48)
        self.assertEqual(best["nonzero_volume_windows"],0)
        self.assertFalse(report["internal_5min_all_bars_tolerance_match"])

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

    def test_small_generated_parquet_1min_and_5min_scan_matches_without_h5(self):
        # An actual Arrow Parquet file is used to catch schema/column-order and
        # epoch-millisecond reading issues without licensed market data.
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow not installed in test interpreter")
        def ms(ts):
            dt=datetime.strptime(str(ts), "%Y%m%d%H%M").replace(
                tzinfo=timezone(timedelta(hours=8)))
            return int(dt.timestamp()*1000)
        with TemporaryDirectory() as d:
            root=Path(d)
            for period, minutes in (("1min",10), ("5min",2)):
                folder=root/"AllCycleAStockData"/period
                folder.mkdir(parents=True)
                rows=[]
                for i in range(minutes):
                    if period=="1min":
                        stamp=202609280930+i
                    else:
                        stamp=202609280930+i*5
                    rows.append({
                        "ts":ms(stamp),"symbol":"688629.XSHG",
                        "open":10.0,"high":11.0,"low":9.0,
                        "close":10.0,"volume":100.0,"amount":1000.0
                    })
                pq.write_table(pa.Table.from_pylist(rows),
                               folder/"2026-09.parquet",row_group_size=6)
            one,one_meta=M.read_parquet_period(
                root,"1min",DAY,(SYMBOL,),100)
            five,five_meta=M.read_parquet_period(
                root,"5min",DAY,(SYMBOL,),100)
            self.assertEqual(len(one),10)
            self.assertEqual(len(five),2)
            self.assertIn((SYMBOL,202609280930),one)
            self.assertIn((SYMBOL,202609280930),five)
            self.assertEqual(one_meta["source_rows_examined"],10)
            self.assertEqual(five_meta["source_rows_examined"],2)
            self.assertEqual(one_meta["duplicate_keys"],0)
            self.assertEqual(five_meta["duplicate_keys"],0)

    def test_generated_parquet_read_cap_aborts_before_decoding(self):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("pyarrow not installed in test interpreter")
        dt=datetime(2026,9,28,9,30,
                    tzinfo=timezone(timedelta(hours=8)))
        ts=int(dt.timestamp()*1000)
        with TemporaryDirectory() as d:
            root=Path(d)
            folder=root/"AllCycleAStockData"/"5min"
            folder.mkdir(parents=True)
            rows=[{
                "ts":ts,"symbol":"688629.XSHG",
                "open":10.0,"high":11.0,"low":9.0,"close":10.0,
                "volume":100.0,"amount":1000.0
            } for _ in range(3)]
            pq.write_table(pa.Table.from_pylist(rows),
                           folder/"2026-09.parquet",row_group_size=3)
            with self.assertRaisesRegex(ValueError,"exceeds --max-candidate-rows"):
                M.read_parquet_period(
                    root,"5min",DAY,(SYMBOL,),2)

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
