"""Synthetic private H5 VWAP outlier attribution contracts; all temporary only."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "synthetic_private_h5_1990_vwap_outlier_attribution",
    HERE.parent/"tools"/"attribute-pre2011-private-h5-day-vwap-outliers-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Pre2011PrivateH5VWAPAttributionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.folder=self.root/"private"/"1990-research-aaaaaaaaaaaaaaaa"
        self.folder.mkdir(parents=True)
        self.parquet=self.folder/"day.parquet"
        t=int(datetime(1990,12,20,tzinfo=M.UTC8).timestamp()*1000)
        self.rows=[
            {"ts":t,"symbol":"600000.XSHG","open":10.0,"high":11.0,
             "low":9.0,"close":10.0,"volume":100.0,"amount":1000.0,
             "source":"hikyuu_h5_1990_uncertified_private_candidate"},
            {"ts":t,"symbol":"600001.XSHG","open":10.0,"high":11.0,
             "low":9.0,"close":10.0,"volume":100.0,"amount":100.0,
             "source":"hikyuu_h5_1990_uncertified_private_candidate"},
            {"ts":t,"symbol":"600002.XSHG","open":10.0,"high":11.0,
             "low":9.0,"close":10.0,"volume":100.0,"amount":10000.0,
             "source":"hikyuu_h5_1990_uncertified_private_candidate"},
            {"ts":t,"symbol":"600003.XSHG","open":10.0,"high":11.0,
             "low":9.0,"close":10.0,"volume":0.0,"amount":0.0,
             "source":"hikyuu_h5_1990_uncertified_private_candidate"},
        ]
        self.private=Path(tmp.name)/"private"
        self.write()
        self.patches=[]
        for p in (
            patch.object(M.FULL,"_source_gate",
                         return_value=("a"*64,"b"*64)),
            patch.object(M.FULL,"_private_paths",
                         return_value={1990:self.folder}),
            patch.object(M.FULL,"_expected",
                         side_effect=lambda year:(len(self.rows),0,4,1)),
        ):
            p.start();self.patches.append(p)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def write(self):
        pq.write_table(pa.Table.from_pylist(
            self.rows,schema=M.FULL.ANNUAL._candidate_schema()),
            self.parquet,compression="snappy")
        self.sha=M.FULL.P90._digest(self.parquet)

    def audit(self):
        with patch.object(M.FULL,"_check_manifest",
                          side_effect=lambda year,folder,*source:(
                              self.parquet,{"private_parquet_sha256":self.sha})):
            with redirect_stdout(StringIO()) as log:
                result=M.analyze(self.root,1990,1990)
        return result,log.getvalue()

    def test_one_inside_one_below_one_above_one_bothzero(self):
        before=(self.parquet.stat().st_mtime_ns,self.parquet.stat().st_size)
        out,logs=self.audit()
        self.assertEqual(out["aggregate"]["candidate_stockdays_checked"],4)
        self.assertEqual(out["aggregate"]["positive_volume_and_amount"],3)
        self.assertEqual(out["aggregate"]["vwap_inside_bar"],1)
        self.assertEqual(out["aggregate"]["vwap_below_low"],1)
        self.assertEqual(out["aggregate"]["vwap_above_high"],1)
        self.assertEqual(out["aggregate"]["outliers_total"],2)
        self.assertFalse(out["h5_volume_amount_price_units_certified"])
        self.assertFalse(out["production_activated"])
        self.assertTrue(out["factors_are_competing_hypotheses_not_auto_repair"])
        self.assertEqual(out["candidate_multipliers_fitting_outliers"]["10"],1)
        self.assertEqual(out["candidate_multipliers_fitting_outliers"]["0.1"],1)
        self.assertEqual(logs.count("PRIVATE_H5_VWAP_ATTRIBUTION_YEAR="),1)
        self.assertNotIn("600001.XSHG",logs)
        self.assertNotIn("10000.0",logs)
        self.assertEqual(before,(self.parquet.stat().st_mtime_ns,self.parquet.stat().st_size))

    def test_year_month_prefix_and_hashed_symbol_attribution(self):
        with patch.object(M.FULL,"_check_manifest",
                return_value=(self.parquet,{"private_parquet_sha256":self.sha})):
            result=M._yearly(1990,self.folder,("a"*64,"b"*64))
        self.assertEqual(result["outliers_by_month"]["1990-12"]["below_low"],1)
        self.assertEqual(result["outliers_by_month"]["1990-12"]["above_high"],1)
        self.assertEqual(result["outliers_by_code_prefix"]["SH600"]["below_low"],1)
        self.assertEqual(result["outliers_by_code_prefix"]["SH600"]["above_high"],1)
        self.assertEqual(result["unique_symbols_with_outliers"],2)
        self.assertEqual(len(result["top_anomalous_symbols"]),2)
        self.assertTrue(all(len(item["symbol_sha256_prefix12"])==12
                            for item in result["top_anomalous_symbols"]))

    def test_no_alternative_factor_fit_is_not_suppressed(self):
        self.rows[1]["amount"]=300.0  # 3.0: x10 overshoots, x0.1 too low
        self.write()
        out,_=self.audit()
        self.assertEqual(out["candidate_multipliers_fitting_outliers"]["none_fit"],1)
        self.assertEqual(out["aggregate"]["outliers_total"],2)

    def test_modified_private_sha_rejected(self):
        self.rows[0]["amount"]=300.0
        self.write()
        self.sha="f"*64
        with self.assertRaisesRegex(ValueError,"full annual count/SHA"):
            self.audit()

    def test_negative_volume_rejected(self):
        self.rows[0]["volume"]=-1.0
        self.write()
        with self.assertRaisesRegex(ValueError,"invalid daily OHLCVA"):
            self.audit()

    def test_invalid_schema_rejected(self):
        pq.write_table(pa.table({"ts":[1]}),self.parquet)
        self.sha=M.FULL.P90._digest(self.parquet)
        with self.assertRaisesRegex(ValueError,"schema/count"):
            self.audit()

    def test_nonmidnight_timestamp_rejected(self):
        self.rows[0]["ts"]+=1000
        self.write()
        with self.assertRaisesRegex(ValueError,"invalid daily OHLCVA/key"):
            self.audit()

    def test_invalid_symbol_on_outlier_rejected(self):
        self.rows[1]["symbol"]="noncanonical"
        self.write()
        with self.assertRaisesRegex(ValueError,"source code invalid"):
            self.audit()

    def test_source_change_detected_after_scan(self):
        with patch.object(M.FULL,"_source_gate",side_effect=[
            ("a"*64,"b"*64),("c"*64,"b"*64)]):
            with self.assertRaisesRegex(ValueError,"source changed"):
                self.audit()

    def test_too_many_years_or_out_of_range_rejected_before_sources(self):
        with patch.object(M.FULL,"_source_gate",
                          side_effect=AssertionError("Sources accessed")):
            for start,end in ((1989,1990),(1990,2011),(1990,1997),(1995,1990)):
                with self.subTest(years=(start,end)):
                    with self.assertRaisesRegex(ValueError,"at most 7"):
                        M.analyze(self.root,start,end)


if __name__=="__main__":
    unittest.main(verbosity=2)
