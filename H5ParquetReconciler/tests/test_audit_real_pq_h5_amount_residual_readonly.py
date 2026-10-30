"""Synthetic-only tests for bounded actual daily amount residual triage."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "real_market_amount_residual_contract",
    HERE.parent/"tools"/"audit-real-pq-h5-amount-residual-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def positive_rows(amounts=(150000.25,320000.75)):
    bars={}
    records={}
    for symbol,p,a,v in (
        ("SH600000",10.1,amounts[0],1300.0),
        ("SZ000001",20.2,amounts[1],2200.0)):
        bars[symbol]={
            "open":p,"high":round(p+.1,3),
            "low":round(p-.1,3),"close":round(p+.05,3),
            "amount":a,"volume":v}
        records[symbol]={
            "datetime":202609300000,
            "openPrice":int(round(p*1000)),
            "highPrice":int(round((p+.1)*1000)),
            "lowPrice":int(round((p-.1)*1000)),
            "closePrice":int(round((p+.05)*1000)),
            "transAmount":(150 if symbol=="SH600000" else 320),
            "transCount":int(v/100)}
    return bars,records


class AmountResidualPureTests(unittest.TestCase):
    def test_same_tolerance_but_not_lossless_amount(self):
        rows,raw=positive_rows()
        result=M.aggregate(rows,raw)
        self.assertEqual(result["sample_positive_pairs"],2)
        self.assertEqual(result["would_require_decimal_rounding"],2)
        self.assertEqual(result["candidate_exact_original_h5_integer_count"],0)
        self.assertEqual(result["within_previous_relative_tolerance_count"],2)
        self.assertEqual(result["nearest_half_even_matches_original_count"],2)
        self.assertEqual(result["floor_matches_original_count"],2)
        self.assertEqual(result["ceiling_matches_original_count"],0)
        self.assertEqual(result["absolute_integer_candidate_residual_buckets"]["le_0p01"],2)

    def test_candidate_nearest_not_always_existing_h5_integer(self):
        result=M.one_amount(150999.1,150)
        self.assertTrue(result["existing_relative_tolerance_1e_minus_5"] is False)
        self.assertFalse(result["nearest_half_even_matches_raw"])
        self.assertTrue(result["floor_matches_raw"])
        self.assertFalse(result["ceil_matches_raw"])

    def test_residual_partition_and_sign_do_not_export_values(self):
        for value,raw,bucket,above in (
            (100000.0,100,"zero",False),
            (100005.0,100,"le_0p01",True),
            (100060.0,100,"le_0p1",True),
            (100400.0,100,"le_0p5",True),
            (100800.0,100,"le_1",True),
            (102000.0,100,"gt_1",True),
            (99999.0,100,"le_0p01",False)):
            with self.subTest(value=value):
                d=M.one_amount(value,raw)
                self.assertEqual(d["abs_residual_bucket"],bucket)
                self.assertEqual(d["candidate_above_native_raw"],above)
                self.assertNotIn(str(value),str(d))

    def test_bad_float_or_unsigned_native_refused(self):
        for amount,raw in (
            (float("nan"),100),(float("inf"),100),(-1.,100),
            (True,100),(1,100),(None,100),
            (150000.1,-1),(150000.1,True),(150000.1,1<<65)):
            with self.subTest(amount=amount,raw=raw):
                with self.assertRaises(ValueError):
                    M.one_amount(amount,raw)

    def test_missing_source_or_changed_date_rejected(self):
        f,h=positive_rows()
        h["SH600000"]["datetime"]=202609290000
        with self.assertRaisesRegex(ValueError,"paired daily"):
            M.aggregate(f,h)
        f,h=positive_rows()
        del f["SH600000"]
        with self.assertRaises(ValueError):
            M.aggregate(f,h)

    def test_exactness_changed_not_misreported_as_reproduced_anomaly(self):
        f,h=positive_rows(amounts=(150000.0,320000.0))
        with self.assertRaisesRegex(ValueError,"contradicts"):
            M.aggregate(f,h)


class SyntheticRealReadersTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        import h5py
        import numpy as np
        self.pa,self.pq,self.h5py,self.np=pa,pq,h5py,np
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.purchased=self.root/"AllCycleAStockData"
        self.h5root=self.root/"HikyuuData"
        self.pqfile=self.purchased/"day"/"2026-09.parquet"
        self.pqfile.parent.mkdir(parents=True)
        self.h5root.mkdir()
        self.reports=self.root/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        self.ten=self.reports/"ten-safe.json"
        self.exact=self.reports/"exactness-safe.json"
        self.output=self.reports/"amount-residual-safe.json"
        patcher=patch.object(M.PAIR.AUDIT,"REPORTS",self.reports)
        patcher.start();self.addCleanup(patcher.stop)
        prior={
            "format":M.EXACT.PRIOR_FORMAT,
            "source_discovery_stock_days":2,
            "same_month_holdout_stock_days":4,
            "crossyear_holdout_stock_days":4,
            "total_distinct_daily_stock_days_with_candidate_factor_matches":10,
            "native_hikyuu_281_cpp_verified_real_stock_days":2,
            "positive_volume_factor100_sample_count":10,
            "positive_amount_factor1000_sample_count":10,
            "all_four_ohlc_raw_div1000_sample_count_per_field":10,
            "candidate_raw_h5_price_divide":1000,
            "candidate_raw_h5_amount_multiply":1000,
            "candidate_raw_h5_volume_multiply":100,
            "five_safe_sha256":{key:"a"*64 for key in (
                "real_raw_stock_day","real_native_stock_day","same_month_heldout",
                "annual_2025_key_only","crossyear_holdout")},
            "sample_numeric_factor_candidate_supported":True,
            "raw_ohlcva_h5_integer_or_source_paths_exported":False,
            "market_source_opened_or_modified_by_this_audit":False,
            "native_cpp_tested_on_crossyear_holdouts":False,
            "vendor_amount_physical_units_certified":False,
            "vendor_volume_physical_units_certified":False,
            "adjustment_and_timestamps_certified":False,
            "universal_period_factor_certified":False,
            "licensed_parquet_to_native_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
            "ready_to_modify_parquet_primary_source":False,
        }
        self.ten.write_text(json.dumps(prior),encoding="utf-8")
        self.rows,self.raw=positive_rows()
        self._write_synthetic_sources()
        report={
            "format":M.EXACT.FORMAT,"sample_day":"2026-09-30",
            "sample_period":"day","sample_stock_days":2,
            "original_hikyuu_h5_records_read":2,
            "prior_ten_stockday_evidence_sha256":M.EXACT.qualified_prior(self.ten),
            "source_stat_before_after_unchanged":True,
            "raw_real_prices_quantities_timestamps_or_paths_exported":False,
            "raw_native_h5_integer_values_exported":False,
            "no_h5_parquet_or_market_sqlite_writes":True,
            "ready_for_full_market_mirror":False,
            "ready_to_modify_purchased_parquet_or_original_h5":False,
            "real_float64_to_native_h5_mapping_certified":False,
            "licensed_parquet_physical_units_certified":False,
            "candidate_raw_integer_field_counts":M.EXACT.summarize(
                self.rows,self.raw),
        }
        self.exact.write_text(json.dumps(report),encoding="utf-8")

    def _write_synthetic_sources(self):
        pa,pq,h5py,np=self.pa,self.pq,self.h5py,self.np
        tick=int(datetime(2026,9,30,tzinfo=timezone(
            timedelta(hours=8))).timestamp()*1000)
        rows=[{"ts":tick,"symbol":(
            "600000.XSHG" if sym=="SH600000" else "000001.XSHE"),
            **self.rows[sym]} for sym in M.PAIR.SYMBOLS]
        pq.write_table(pa.Table.from_pylist(rows),self.pqfile)
        dt=np.dtype([
            ("closePrice","<u4"),("datetime","<u8"),
            ("highPrice","<u4"),("lowPrice","<u4"),("openPrice","<u4"),
            ("transAmount","<u8"),("transCount","<u8")])
        self.assertEqual(dt.itemsize,40)
        for sym in M.PAIR.SYMBOLS:
            arr=np.zeros(1,dtype=dt)
            for field,value in self.raw[sym].items():
                arr[0][field]=value
            with h5py.File(self.h5root/(sym[:2].lower()+"_day.h5"),"w") as fh:
                fh.create_group("data").create_dataset(sym,data=arr)

    def run_it(self):
        return M.run(self.purchased,self.h5root,"2026-09-30",
                     self.ten,self.exact,self.output)

    def test_synthetic_arrow_h5_roundtrip_only_safe_counts(self):
        files=[self.pqfile,*self.h5root.glob("*.h5")]
        before={x:hashlib.sha256(x.read_bytes()).hexdigest() for x in files}
        report=self.run_it()
        self.assertEqual(report["amount_residual_counts"]["sample_positive_pairs"],2)
        self.assertEqual(report["amount_residual_counts"][
            "within_previous_relative_tolerance_count"],2)
        self.assertEqual(report["parquet_scanned_source_rows_bounded"],2)
        self.assertTrue(report["prior_exactness_counts_reverified"])
        self.assertFalse(report["ready_for_full_market_mirror"])
        self.assertEqual(before,{
            x:hashlib.sha256(x.read_bytes()).hexdigest() for x in files})
        saved=self.output.read_text()
        for forbidden in (
            "SH600000","SZ000001","150000.25","320000.75",
            "AllCycleAStockData","HikyuuData",str(int(datetime(
                2026,9,30,tzinfo=timezone(timedelta(hours=8))).timestamp()*1000))):
            self.assertNotIn(forbidden,saved)

    def test_forged_prior_or_missing_exactness_rejected_before_source_scan(self):
        document=json.loads(self.exact.read_text())
        document["candidate_raw_integer_field_counts"]["amount"][
            "shortest_decimal_requires_rounding_count"]=0
        self.exact.write_text(json.dumps(document))
        with patch.object(M.PAIR.DAY,"_read_bounded_daily",
                          side_effect=AssertionError("must not read market")):
            with self.assertRaisesRegex(ValueError,"not reproduced"):
                self.run_it()
        self.assertFalse(self.output.exists())

    def test_existing_safe_no_overwrite_and_date_is_fixed(self):
        self.output.write_text("protected")
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertEqual(self.output.read_text(),"protected")
        self.output.unlink()
        with self.assertRaisesRegex(ValueError,"known same-day"):
            M.run(self.purchased,self.h5root,"2026-09-29",
                  self.ten,self.exact,self.output)
        self.assertFalse(self.output.exists())

    def test_amount_count_changes_between_runs_rejected(self):
        original=M.PAIR._read_single_h5
        def mutate_count(root,sym,day,h5py,np):
            result=original(root,sym,day,h5py,np)
            if sym=="SH600000":
                return dict(result,transAmount=result["transAmount"]+1)
            return result
        with patch.object(M.PAIR,"_read_single_h5",side_effect=mutate_count):
            with self.assertRaisesRegex(ValueError,"no longer match"):
                self.run_it()
        self.assertFalse(self.output.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
