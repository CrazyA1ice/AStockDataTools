"""H5-only minute reconstruction tests; no licensed data, no Parquet I/O."""
import importlib.util
import unittest
from datetime import date
from pathlib import Path

SOURCE=(Path(__file__).resolve().parents[1]/"tools"/
        "inspect-h5-1min-top3-no-parquet.py")
SPEC=importlib.util.spec_from_file_location("h5_1min_top3_only",SOURCE)
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def baseline():
    ticker="SH688629"
    return {
        "format":"AStockDataTools x100 focused 5min residual session forensic v1",
        "date":"2026-09-28","selected_symbols":[ticker],
        "source_files_modified":False,"no_raw_ohlcv_exported":True,
        "unit_mapping_certified":False,"safe_to_automatically_union":False,
        "h5_five_minute_volume_factor_candidate":100,
        "symbol_results":{ticker:{
            "status":"hypothesis_diagnostic_only",
            "h5_5min_bars":48,"parquet_5min_bars":48,
            "h5_only_bars":0,"parquet_only_bars":0,
            "candidate_volume_factor_h5":100,"matched_only":True,
            "exact_residual_masks":{"none":15,"volume":1,
                                    "volume_amount":4,
                                    "volume_amount_price":28}
        }}
    }


def source_rows():
    symbol="SH688629"
    day=20260928
    # 24 end-stamped regular-session windows per half-day.
    times=([935+5*i for i in range(12)]
           + [1035+5*i for i in range(12)]
           + [1305+5*i for i in range(12)]
           + [1405+5*i for i in range(12)])
    # The first two portions must cover 09:35...11:30 and 13:05...15:00.
    from datetime import datetime, timedelta
    ends=[]
    for hour, minute in ((9,35),(13,5)):
        current=datetime(2026,9,28,hour,minute)
        for _ in range(24):
            ends.append(int(current.strftime("%Y%m%d%H%M")))
            current+=timedelta(minutes=5)
    five={}
    one={}
    for stamp in ends:
        five[(symbol,stamp)]=(10,11,9,10,10,1000)
        for minute_stamp in M.one.one_minute_times(stamp,"minute_end_label"):
            one[(symbol,minute_stamp)]=(10,11,9,10,2,200)
    return symbol,five,one


class H5OnlyTop3MinuteTests(unittest.TestCase):
    def test_select_prior_three_stock_report_fail_closed(self):
        report=baseline()
        self.assertEqual(M.select_existing_symbols(report,date(2026,9,28)),
                         ("SH688629",))
        report["date"]="2026-09-29"
        with self.assertRaisesRegex(ValueError,"matching"):
            M.select_existing_symbols(report,date(2026,9,28))
        report=baseline()
        report["symbol_results"]["SH688629"]["exact_residual_masks"]["volume"]+=1
        with self.assertRaisesRegex(ValueError,"non-comparable"):
            M.select_existing_symbols(report,date(2026,9,28))

    def test_full_48_end_label_windows_match_normalized_h5_5min_volume(self):
        sym,five,minute=source_rows()
        self.assertEqual(len(five),48)
        self.assertEqual(len(minute),240)
        result=M.complete_window_result(
            five,minute,sym,"minute_end_label")
        total=result["whole_day"]
        self.assertEqual(total["complete_windows"],48)
        self.assertEqual(total["incomplete_windows"],0)
        self.assertEqual(total["all_ohlc_agree"],48)
        self.assertEqual(total["amount_agree"],48)
        self.assertEqual(total["volume_match_minute_multiplier"]["100"],48)
        self.assertEqual(total["volume_match_minute_multiplier"]["1"],0)
        self.assertEqual(total["nonzero_volume_windows"],48)
        self.assertEqual(result["sessions"]["morning"]["complete_windows"],24)
        self.assertEqual(result["sessions"]["afternoon"]["complete_windows"],24)

    def test_start_label_hypothesis_reports_partial_windows(self):
        sym,five,minute=source_rows()
        other=M.complete_window_result(
            five,minute,sym,"minute_start_label")
        self.assertEqual(other["whole_day"]["complete_windows"],46)
        self.assertEqual(other["whole_day"]["incomplete_windows"],2)
        self.assertEqual(other["sessions"]["morning"]["complete_windows"],23)
        self.assertEqual(other["sessions"]["afternoon"]["complete_windows"],23)
        self.assertFalse(other["minute_time_convention_certified"])

    def test_missing_minute_data_is_not_a_false_crosscheck_pass(self):
        sym,five,minute=source_rows()
        missing={sym:{"availability":"missing_file",
                      "one_minute_rows":0,
                      "duplicate_minute_keys":0}}
        result=M.build_report_from_sources((sym,),five,{},missing)[sym]
        self.assertEqual(result["availability"],
                         "not_verifiable_no_one_minute_data")
        self.assertEqual(result["minute_convention_candidates"],{})
        duplicate={sym:{"availability":"has_records",
                        "one_minute_rows":240,
                        "duplicate_minute_keys":1}}
        result=M.build_report_from_sources((sym,),five,minute,duplicate)[sym]
        self.assertEqual(result["availability"],
                         "not_verifiable_duplicate_one_minute_keys")

    def test_incomplete_minute_window_never_compared_as_price_conflict(self):
        sym,five,minute=source_rows()
        del minute[(sym,202609280931)]
        result=M.complete_window_result(
            five,minute,sym,"minute_end_label")
        self.assertEqual(result["whole_day"]["complete_windows"],47)
        self.assertEqual(result["whole_day"]["incomplete_windows"],1)
        self.assertEqual(result["whole_day"]["all_ohlc_agree"],47)
        self.assertEqual(result["whole_day"][
            "volume_match_nonzero_minute_multiplier"]["100"],47)
        self.assertIn("202609280935",
                      result["missing_minute_window_end_labels_examples"])

    def test_source_count_drift_rejected(self):
        sym,five,minute=source_rows()
        five.pop((sym,202609280935))
        with self.assertRaisesRegex(ValueError,"count changed"):
            M.complete_window_result(five,minute,sym,"minute_end_label")


if __name__=="__main__":
    unittest.main()
