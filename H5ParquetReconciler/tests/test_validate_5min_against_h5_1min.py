"""Synthetic regression tests for read-only H5 1min reaggregation crosscheck."""
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]/"tools"
SPEC=importlib.util.spec_from_file_location(
    "validate_5min_from_h5_1min", HERE/"validate-5min-against-h5-1min.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class MinuteIndependentCrosscheckTests(unittest.TestCase):
    def setUp(self):
        self.symbol="SH600000"
        self.end=202509300935
        self.minute={
            (self.symbol,202509300931):(10,10.5,9.5,10.25,1,100),
            (self.symbol,202509300932):(10.25,11,10,10.5,2,200),
            (self.symbol,202509300933):(10.5,12,10.5,11.5,3,300),
            (self.symbol,202509300934):(11.5,11.5,9,10,4,400),
            (self.symbol,202509300935):(10,11,10,11,5,500)
        }
        self.expected=(10,12,9,11,15,1500)
        self.h5={(self.symbol,self.end):self.expected}
        self.pq={(self.symbol,202509300930):self.expected}

    def test_minute_label_hypotheses_are_distinct(self):
        self.assertEqual(M.one_minute_times(self.end,"minute_end_label"),
                         (202509300931,202509300932,202509300933,
                          202509300934,202509300935))
        self.assertEqual(M.one_minute_times(self.end,"minute_start_label"),
                         (202509300930,202509300931,202509300932,
                          202509300933,202509300934))
        with self.assertRaises(ValueError):
            M.one_minute_times(self.end,"magic")

    def test_five_complete_minutes_reproduce_ohlcv(self):
        self.assertEqual(M.aggregate_minute_window(
            self.minute,self.symbol,self.end,"minute_end_label"),self.expected)
        v=M.compare_to_reaggregation(self.minute,self.h5,self.symbol,"minute_end_label")
        self.assertEqual(v["complete_minute_windows"],1)
        self.assertEqual(v["all_ohlc_agree"],1)
        self.assertEqual(v["volume_agree"],1)
        self.assertEqual(v["amount_agree"],1)
        self.assertEqual(v["bar_over_one_minute_sum_volume_ratio"]["median"],1.0)
        self.assertEqual(v["price_field_agree"]["high"],1)

    def test_incomplete_minute_window_is_not_reported_as_price_conflict(self):
        partial=dict(self.minute)
        del partial[(self.symbol,202509300933)]
        self.assertIsNone(M.aggregate_minute_window(
            partial,self.symbol,self.end,"minute_end_label"))
        r=M.compare_to_reaggregation(partial,self.h5,self.symbol,"minute_end_label")
        self.assertEqual(r["complete_minute_windows"],0)
        self.assertEqual(r["incomplete_minute_windows"],1)
        self.assertEqual(r["all_ohlc_agree"],0)
        self.assertEqual(r["incomplete_window_end_labels_examples"],["202509300935"])

    def test_parquet_5min_close_conflict_is_attributed_against_1min(self):
        conflicting=(10,12,9,11.01,15,1500)
        h=self.h5
        pq={(self.symbol,202509300930):conflicting}
        cover={self.symbol:{"availability":"has_records","one_minute_rows":5,
                            "duplicate_minute_keys":0}}
        r=M.build_crosscheck(h,pq,self.minute,cover,(self.symbol,))[self.symbol]
        self.assertEqual(r["validation_status"],"conditional_evidence")
        end=r["one_minute_reaggregation"]["minute_end_label"]
        self.assertEqual(end["H5_5min"]["all_ohlc_agree"],1)
        self.assertEqual(end["Parquet_5min"]["all_ohlc_agree"],0)
        self.assertEqual(end["Parquet_5min"]["price_field_agree"]["high"],1)
        self.assertEqual(end["Parquet_5min"]["price_field_agree"]["close"],0)
        self.assertEqual(r["five_minute_day_total_comparison"]["matched_five_minute_bars"],1)

    def test_different_minute_time_convention_has_no_complete_window(self):
        cover={self.symbol:{"availability":"has_records","one_minute_rows":5,
                            "duplicate_minute_keys":0}}
        r=M.build_crosscheck(self.h5,self.pq,self.minute,cover,(self.symbol,))[self.symbol]
        self.assertEqual(
            r["one_minute_reaggregation"]["minute_start_label"]["H5_5min"]["complete_minute_windows"],0)
        self.assertEqual(
            r["one_minute_reaggregation"]["minute_end_label"]["Parquet_5min"]["complete_minute_windows"],1)

    def test_missing_minute_source_is_explicitly_unverifiable(self):
        coverage={self.symbol:{"availability":"missing_file","one_minute_rows":0,
                               "duplicate_minute_keys":0}}
        r=M.build_crosscheck(self.h5,self.pq,{},coverage,(self.symbol,))[self.symbol]
        self.assertEqual(r["validation_status"],"not_verifiable_no_one_minute_data")
        self.assertEqual(r["one_minute_reaggregation"],{})
        self.assertEqual(r["five_minute_day_total_comparison"]["matched_five_minute_bars"],1)

    def test_pq_only_ticker_does_not_have_fake_h5_matches(self):
        symbol="BJ920680"
        record={(symbol,202509300930):self.expected}
        coverage={symbol:{"availability":"no_records_on_date","one_minute_rows":0,
                          "duplicate_minute_keys":0}}
        r=M.build_crosscheck({},record,{},coverage,(symbol,))[symbol]
        self.assertEqual(r["five_minute_day_total_comparison"]["matched_five_minute_bars"],0)
        self.assertIsNone(
            r["five_minute_day_total_comparison"]["parquet_over_h5_total_amount_ratio_on_matched_bars"])

    def test_load_h5_minute_file_is_read_only_and_bounded(self):
        import h5py
        import numpy as np
        dtype=np.dtype([
            ("datetime","<u8"),("openPrice","<i4"),("highPrice","<i4"),
            ("lowPrice","<i4"),("closePrice","<i4"),
            ("transCount","<u8"),("transAmount","<u8")])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            stock=root/"HikyuuData"
            stock.mkdir()
            rows=np.zeros(6,dtype=dtype)
            for i,t in enumerate((202509290931,202509300931,202509300932,
                                  202509300933,202509300934,202509300935)):
                rows["datetime"][i]=t
                for field in ("openPrice","highPrice","lowPrice","closePrice"):
                    rows[field][i]=10000
                rows["transCount"][i]=5
                rows["transAmount"][i]=2
            with h5py.File(stock/"sh_1min.h5","w") as file:
                file.create_group("data").create_dataset(self.symbol,data=rows)
            got,status=M.load_h5_minute_day(root,(self.symbol,"SZ000636"),
                                            date(2025,9,30))
            self.assertEqual(len(got),5)
            self.assertEqual(status[self.symbol]["one_minute_rows"],5)
            self.assertEqual(status[self.symbol]["availability"],"has_records")
            self.assertEqual(status["SZ000636"]["availability"],"missing_file")
            self.assertEqual(got[(self.symbol,202509300931)][5],2000)


if __name__=="__main__":
    unittest.main(verbosity=2)
