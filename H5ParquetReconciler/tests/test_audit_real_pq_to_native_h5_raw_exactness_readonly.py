"""Fully fictional Parquet/H5 fixtures for real-source read-only integer feasibility."""
import hashlib
import importlib.util
import json
import math
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "native_h5_raw_integer_feasibility_under_test",
    HERE.parent/"tools"/"audit-real-pq-to-native-h5-raw-exactness-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def sample_pairs():
    floats={}
    raw={}
    for symbol,price,amount,volume in (
        ("SH600000",10.1,150000.0,1300.0),
        ("SZ000001",20.2,320000.0,2200.0)):
        floats[symbol]={
            "open":price,"high":round(price+0.1,3),
            "low":round(price-0.1,3),"close":round(price+0.05,3),
            "amount":amount,"volume":volume}
        raw[symbol]={
            "datetime":202609300000,
            "openPrice":int(round(price*1000)),
            "highPrice":int(round((price+0.1)*1000)),
            "lowPrice":int(round((price-0.1)*1000)),
            "closePrice":int(round((price+0.05)*1000)),
            "transAmount":int(amount/1000),
            "transCount":int(volume/100)}
    return floats,raw


class IntegerCandidateContracts(unittest.TestCase):
    def test_matching_positive_candidate_integer_ticks(self):
        f,h=sample_pairs()
        counts=M.summarize(f,h)
        self.assertEqual(set(counts),set(M.FIELDS))
        for field in M.FIELDS:
            with self.subTest(field=field):
                self.assertEqual(counts[field]["sample_pairs"],2)
                self.assertEqual(counts[field]["positive_nonzero_pairs"],2)
                self.assertEqual(counts[field]["shortest_decimal_tick_exact_count"],2)
                self.assertEqual(counts[field]["positive_exact_raw_integer_matches_count"],2)
                self.assertEqual(counts[field]["shortest_decimal_requires_rounding_count"],0)
                self.assertEqual(counts[field]["native_integer_range_overflow_count"],0)
        self.assertLess(counts["open"]["binary64_tick_exact_count"],2)

    def test_decimal_printed_float_and_binary64_are_not_same(self):
        result=M.classify_pair(10.1,10100,"open")
        self.assertTrue(result["decimal_tick_exact"])
        self.assertFalse(result["binary64_tick_exact"])
        self.assertTrue(result["exact_raw_match"])

    def test_fractional_ticks_and_mismatch_reported_not_silently_rounded(self):
        price=M.classify_pair(10.1234,10123,"open")
        amount=M.classify_pair(150000.5,150,"amount")
        volume=M.classify_pair(1301.0,13,"volume")
        self.assertTrue(price["decimal_requires_rounding"])
        self.assertTrue(amount["decimal_requires_rounding"])
        self.assertTrue(volume["decimal_requires_rounding"])
        self.assertFalse(price["exact_raw_match"])
        self.assertFalse(amount["exact_raw_match"])
        self.assertFalse(volume["exact_raw_match"])
        # Tick exact does not imply exact cross-source equality.
        no_match=M.classify_pair(10.1,10101,"open")
        self.assertTrue(no_match["decimal_tick_exact"])
        self.assertFalse(no_match["exact_raw_match"])

    def test_both_zero_not_positive_factor_evidence_and_one_zero_is_separate(self):
        zero=M.classify_pair(0.0,0,"amount")
        one=M.classify_pair(0.0,120,"amount")
        self.assertTrue(zero["both_zero"])
        self.assertFalse(zero["exact_raw_match"])
        self.assertTrue(one["one_zero"])
        self.assertFalse(one["exact_raw_match"])

    def test_invalid_float_integer_or_date_fails_closed(self):
        for value in (float("nan"),float("inf"),-1.0,1,False,None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    M.classify_pair(value,3,"volume")
        for value in (1.1,-1,True,1<<65):
            with self.subTest(raw=value):
                with self.assertRaises(ValueError):
                    M.classify_pair(1.0,value,"amount")
        f,h=sample_pairs()
        h["SH600000"]["datetime"]=202609290000
        with self.assertRaisesRegex(ValueError,"date key"):
            M.summarize(f,h)

    def test_native_integer_limit_breaches_are_reported(self):
        c=M.classify_pair(1000000000.0,100,"open")
        self.assertTrue(c["range_overflow"])
        self.assertFalse(c["exact_raw_match"])
        d=M.classify_pair(1e308,1,"amount")
        self.assertTrue(d["range_overflow"])


class FictitiousRealSourceReadTests(unittest.TestCase):
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
        self.safe=self.reports/"ten-safe.json"
        self.out=self.reports/"integer-preview-safe.json"
        prior={
            "format":M.PRIOR_FORMAT,
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
        }
        for key,value in (
            ("sample_numeric_factor_candidate_supported",True),
            ("raw_ohlcva_h5_integer_or_source_paths_exported",False),
            ("market_source_opened_or_modified_by_this_audit",False),
            ("native_cpp_tested_on_crossyear_holdouts",False),
            ("vendor_amount_physical_units_certified",False),
            ("vendor_volume_physical_units_certified",False),
            ("adjustment_and_timestamps_certified",False),
            ("universal_period_factor_certified",False),
            ("licensed_parquet_to_native_h5_mapping_certified",False),
            ("ready_for_full_market_mirror",False),
            ("ready_to_modify_parquet_primary_source",False)):
            prior[key]=value
        self.safe.write_text(json.dumps(prior),encoding="utf-8")
        p=patch.object(M.PAIR.AUDIT,"REPORTS",self.reports)
        p.start();self.addCleanup(p.stop)
        self._create_sources()

    def _create_sources(self):
        pa,pq,h5py,np=self.pa,self.pq,self.h5py,self.np
        f,h=sample_pairs()
        tick=int(datetime(2026,9,30,tzinfo=timezone(
            timedelta(hours=8))).timestamp()*1000)
        rows=[{"ts":tick,
               "symbol":("600000.XSHG" if sym=="SH600000" else "000001.XSHE"),
               **f[sym]} for sym in M.PAIR.SYMBOLS]
        table=pa.Table.from_pylist(rows)
        pq.write_table(table,self.pqfile)
        native_dtype=np.dtype([
            ("closePrice","<u4"),("datetime","<u8"),("highPrice","<u4"),
            ("lowPrice","<u4"),("openPrice","<u4"),
            ("transAmount","<u8"),("transCount","<u8")])
        self.assertEqual(native_dtype.itemsize,40)
        for sym in M.PAIR.SYMBOLS:
            array=np.zeros(1,dtype=native_dtype)
            for field,value in h[sym].items():
                array[0][field]=value
            with h5py.File(self.h5root/(sym[:2].lower()+"_day.h5"),"w") as handle:
                handle.create_group("data").create_dataset(sym,data=array)

    def run_it(self):
        return M.run(self.purchased,self.h5root,"2026-09-30",
                     self.safe,self.out)

    def test_real_reader_on_fictional_parquet_h5_reports_counts_only(self):
        source_files=[self.pqfile,*self.h5root.glob("*.h5")]
        before={file:hashlib.sha256(file.read_bytes()).hexdigest()
                for file in source_files}
        report=self.run_it()
        self.assertEqual(report["sample_stock_days"],2)
        self.assertEqual(report["parquet_source_rows_scanned"],2)
        self.assertEqual(report["original_hikyuu_h5_records_read"],2)
        self.assertTrue(all(report["candidate_raw_integer_field_counts"][f][
            "positive_exact_raw_integer_matches_count"]==2 for f in M.FIELDS))
        self.assertFalse(report["real_float64_to_native_h5_mapping_certified"])
        self.assertFalse(report["ready_for_full_market_mirror"])
        self.assertEqual(
            before,{file:hashlib.sha256(file.read_bytes()).hexdigest()
                    for file in source_files})
        payload=self.out.read_text(encoding="utf-8")
        for forbidden in (
            "SH600000","SZ000001","150000.0","320000.0",
            str(int(datetime(2026,9,30,tzinfo=timezone(
                timedelta(hours=8))).timestamp()*1000)),
            "HikyuuData","AllCycleAStockData","10100"):
            self.assertNotIn(forbidden,payload)

    def test_unverified_prior_or_existing_report_fails_before_market_read(self):
        prior=json.loads(self.safe.read_text())
        prior["candidate_raw_h5_volume_multiply"]=10
        self.safe.write_text(json.dumps(prior))
        with patch.object(M.PAIR.DAY,"_read_bounded_daily",
                          side_effect=AssertionError("must not scan")):
            with self.assertRaisesRegex(ValueError,"not qualified"):
                self.run_it()
        self.assertFalse(self.out.exists())
        prior["candidate_raw_h5_volume_multiply"]=100
        self.safe.write_text(json.dumps(prior))
        self.out.write_text("protected")
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertEqual(self.out.read_text(),"protected")

    def test_source_changes_during_read_are_rejected_without_safe(self):
        original=M.PAIR._read_single_h5
        def change_after_read(root,sym,day,h5py,np):
            ret=original(root,sym,day,h5py,np)
            self.pqfile.touch()
            # Force mtime drift independent of filesystem clock granularity.
            st=self.pqfile.stat()
            import os
            os.utime(self.pqfile,ns=(st.st_atime_ns,st.st_mtime_ns+2000000000))
            return ret
        with patch.object(M.PAIR,"_read_single_h5",side_effect=change_after_read):
            with self.assertRaisesRegex(ValueError,"stat changed"):
                self.run_it()
        self.assertFalse(self.out.exists())

    def test_unselected_date_and_output_outside_module_rejected(self):
        with self.assertRaisesRegex(ValueError,"fixed day"):
            M.run(self.purchased,self.h5root,"2026-09-29",self.safe,self.out)
        with self.assertRaises(ValueError):
            M.run(self.purchased,self.h5root,"2026-09-30",
                  self.safe,self.root/"outside.json")
        self.assertFalse(self.out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
