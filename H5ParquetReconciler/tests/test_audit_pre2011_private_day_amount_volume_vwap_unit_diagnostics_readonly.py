"""Synthetic private historical day candidate amount/volume VWAP diagnostics.

All fictional Parquet inputs are in TemporaryDirectory. Source H5/PQ checks
are mocked. These tests never open any user H5, licensed Parquet or market DB.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "historical_1990_private_vwap_candidate_diagnostic_contract",
    HERE.parent/"tools"/"audit-pre2011-private-day-amount-volume-vwap-unit-diagnostics-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class HistoricalPrivateVWAPDiagnosticTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.base=Path(t.name)
        self.root=self.base/"market-root"
        self.root.mkdir()
        self.annual=self.base/"ignored-annual-stage"
        self.annual.mkdir()
        self.file=self.annual/"day.parquet"
        self.rows=[
            {"ts":0,"symbol":"600000.XSHG","open":10.0,"high":11.0,"low":9.0,
             "close":10.0,"volume":100.0,"amount":1000.0,
             "source":"hikyuu_h5_1990_uncertified_private_candidate"},
            {"ts":0,"symbol":"600001.XSHG","open":10.0,"high":11.0,"low":9.0,
             "close":10.0,"volume":200.0,"amount":2000.0,
             "source":"hikyuu_h5_1990_uncertified_private_candidate"},
            {"ts":0,"symbol":"600002.XSHG","open":10.0,"high":11.0,"low":9.0,
             "close":10.0,"volume":0.0,"amount":0.0,
             "source":"hikyuu_h5_1990_uncertified_private_candidate"},
            {"ts":0,"symbol":"600003.XSHG","open":10.0,"high":11.0,"low":9.0,
             "close":10.0,"volume":0.0,"amount":10.0,
             "source":"hikyuu_h5_1990_uncertified_private_candidate"},
        ]
        self.patches=[]
        for p in (
            patch.object(M.FULL,"_source_gate",return_value=("a"*64,"b"*64)),
            patch.object(M.FULL,"_private_paths",return_value={1990:self.annual}),
            patch.object(M.FULL,"_expected",return_value=(4,0,4,1)),
        ):
            p.start()
            self.patches.append(p)
        self.write()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def write(self):
        pq.write_table(pa.Table.from_pylist(
            self.rows,schema=M.FULL.ANNUAL._candidate_schema()),
            self.file,compression="snappy")
        self.sha=M.FULL.P90._digest(self.file)

    def run(self):
        with patch.object(M.FULL,"_check_manifest",
                          return_value=(self.file,{"private_parquet_sha256":self.sha})):
            with redirect_stdout(StringIO()) as report:
                result=M.analyze(self.root,1990,1990)
        return result,report.getvalue()

    def test_exact_four_rows_one_zero_two_inside_one_missing_volume(self):
        before=(self.file.stat().st_size,self.file.stat().st_mtime_ns)
        output,log=self.run()
        totals=output["aggregate"]
        self.assertEqual(output["candidate_stockdays_checked"],4)
        self.assertEqual(output["years_checked"],1)
        self.assertEqual(totals["positive_volume_and_amount"],2)
        self.assertEqual(totals["vwap_inside_bar"],2)
        self.assertEqual(totals["both_zero"],1)
        self.assertEqual(totals["only_volume_zero"],1)
        self.assertEqual(totals["only_amount_zero"],0)
        self.assertEqual(totals["ratio_near_factors_within_5pct"]["1"],2)
        self.assertFalse(output["h5_physical_amount_and_volume_units_certified"])
        self.assertFalse(output["production_merge_authorized"])
        self.assertFalse(output["historical_private_candidate_files_modified"])
        self.assertIn("PRIVATE_H5_UNIT_DIAGNOSTIC_SUMMARY=",log)
        self.assertNotIn("600000.XSHG",log)
        self.assertEqual(before,(self.file.stat().st_size,self.file.stat().st_mtime_ns))

    def test_ratio_ten_and_above_bar_is_evidence_not_exception(self):
        self.rows[0]["amount"]=10000.0
        self.write()
        data,_=self.run()
        self.assertEqual(data["aggregate"]["vwap_above_high"],1)
        self.assertEqual(data["aggregate"]["ratio_near_factors_within_5pct"]["10"],1)
        self.assertFalse(data["production_merge_authorized"])

    def test_ratio_below_price_range_is_anomaly_not_conversion(self):
        self.rows[0]["amount"]=100.0
        self.write()
        data,_=self.run()
        self.assertEqual(data["aggregate"]["vwap_below_low"],1)
        self.assertEqual(data["aggregate"]["ratio_near_factors_within_5pct"]["0.1"],1)
        self.assertEqual(data["aggregate"]["vwap_inside_bar"],1)

    def test_only_amount_zero_is_independent_missingness_category(self):
        self.rows[1]["amount"]=0.0
        self.write()
        data,_=self.run()
        self.assertEqual(data["aggregate"]["only_amount_zero"],1)
        self.assertEqual(data["aggregate"]["positive_volume_and_amount"],1)

    def test_negative_volume_is_rejected_before_ratio(self):
        self.rows[0]["volume"]=-100.0
        self.write()
        with self.assertRaisesRegex(ValueError,"Unsafe OHLCVA"):
            self.run()

    def test_nonfinite_amount_is_rejected(self):
        self.rows[0]["amount"]=float("nan")
        self.write()
        with self.assertRaisesRegex(ValueError,"Unsafe OHLCVA"):
            self.run()

    def test_bad_close_outside_high_low_rejected(self):
        self.rows[0]["close"]=20.0
        self.write()
        with self.assertRaisesRegex(ValueError,"Unsafe OHLCVA"):
            self.run()

    def test_private_byte_sha_tamper_rejected(self):
        self.file.write_bytes(self.file.read_bytes()+b"bad")
        with self.assertRaisesRegex(ValueError,"manifest drift"):
            self.run()

    def test_source_state_drift_before_market_scan_fails(self):
        with patch.object(M.FULL,"_source_gate",side_effect=ValueError("source-state drift")):
            with self.assertRaisesRegex(ValueError,"source-state drift"):
                self.run()

    def test_source_state_drift_after_scan_fails(self):
        with patch.object(M.FULL,"_source_gate",side_effect=[
            ("a"*64,"b"*64),("z"*64,"b"*64)]):
            with self.assertRaisesRegex(ValueError,"states drifted"):
                self.run()

    def test_wrong_requested_range_fails_before_market_read(self):
        with patch.object(M.FULL,"_source_gate",side_effect=AssertionError("source opened")):
            for start,stop in ((1989,1990),(2010,2011),(2000,1999)):
                with self.subTest(start=start,stop=stop):
                    with self.assertRaisesRegex(ValueError,"year bounds"):
                        M.analyze(self.root,start,stop)

    def test_schema_mismatch_or_inconsistent_row_count_rejected(self):
        pq.write_table(pa.table({"close":[10.0]}),self.file)
        self.sha=M.FULL.P90._digest(self.file)
        with self.assertRaisesRegex(ValueError,"schema/rows"):
            self.run()


if __name__=="__main__":
    unittest.main(verbosity=2)
