"""Synthetic original H5 native 2025 monthly 1min coverage: never read OHLCVA."""
from __future__ import annotations
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "test_bounded_native_one_minute_2025_source_months",
    HERE.parent/"tools"/"inventory-2025-h5-native-1min-month-coverage-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class Native2025OneMinuteCoverageReadOnlyTests(unittest.TestCase):
    def setUp(self):
        import h5py
        import numpy as np
        self.tmp=tempfile.TemporaryDirectory(prefix="native-month-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        folder=self.root/"HikyuuData"
        folder.mkdir()
        self.paths={}
        rows={
            "sh":{
                "SH600001":[202105170931,202508070931,202508070932,202512310930],
                "SH600002":[202409300931,202601080931],
                "SH000001":[202501020931,202502030931],
                "SH600003":[],
            },
            "sz":{
                "SZ000001":[202508070931,202508080931,202511030931],
                "SZ399001":[202501020931],
            },
            "bj":{
                "BJ920000":[202601080931,202610131500],
            },
        }
        for market in ("sh","sz","bj"):
            p=folder/(market+"_1min.h5")
            self.paths[market]=p
            with h5py.File(p,"w") as h:
                group=h.create_group("data")
                for code,stamps in rows[market].items():
                    dtype=np.dtype([("datetime","<u8"),("closePrice","<u4")])
                    arr=np.zeros(len(stamps),dtype=dtype)
                    if stamps:
                        arr["datetime"]=stamps
                        arr["closePrice"]=range(1,len(stamps)+1)
                    group.create_dataset(code,data=arr)

    def hashes(self):
        return {market:hashlib.sha256(p.read_bytes()).hexdigest()
                for market,p in self.paths.items()}

    def test_january_february_empty_even_though_first_sh_table_in_2021(self):
        old=self.hashes()
        result=M.inspect(self.root)
        self.assertEqual(result["markets"]["sh"]["first_candidate_2025_native_stamp"],
                         202508070931)
        self.assertEqual(result["months"]["2025-01"]["native_rows"],0)
        self.assertEqual(result["months"]["2025-02"]["native_rows"],0)
        self.assertEqual(result["months"]["2025-08"]["markets_with_rows"],
                         ["sh","sz"])
        self.assertEqual(result["months"]["2025-08"]["native_rows"],4)
        self.assertEqual(result["months"]["2025-11"]["native_rows"],1)
        self.assertEqual(result["months"]["2025-12"]["native_rows"],1)
        self.assertEqual(result["months"]["2025-10"]["native_rows"],0)
        self.assertEqual(result["markets"]["bj"]["total_2025_native_rows"],0)
        self.assertEqual(result["markets"]["sh"]["total_2025_native_rows"],3)
        self.assertEqual(result["markets"]["sz"]["total_2025_native_rows"],3)
        self.assertEqual(result["markets"]["sh"][
            "candidate_datasets_with_2025_rows"],1)
        self.assertEqual(result["months"]["2025-08"]["dataset_month_observations"],2)
        self.assertTrue(result["source_row_count_sum_conserved"])
        self.assertFalse(result["ready_for_production_query"])
        self.assertTrue(result["no_native_h5_ohlcva_decoded"])
        self.assertTrue(result["no_purchased_parquet_opened"])
        self.assertEqual(old,self.hashes())
        self.assertNotIn("SH600001",str(result))
        self.assertNotIn("SZ000001",str(result))

    def test_existing_source_date_coverage_not_guaranteed_contiguous(self):
        result=M.inspect(self.root)
        self.assertEqual(result["months"]["2025-08"]["native_rows"],4)
        self.assertEqual(result["months"]["2025-09"]["native_rows"],0)
        self.assertEqual(result["months"]["2025-11"]["native_rows"],1)
        self.assertFalse(result["source_2025_full_session_completeness_certified"])
        self.assertFalse(result["independent_exchange_calendar_certified"])

    def test_non_share_index_rows_excluded(self):
        result=M.inspect(self.root)
        self.assertEqual(result["markets"]["sh"][
            "candidate_a_share_datasets_examined"],3)
        self.assertEqual(result["markets"]["sz"][
            "candidate_a_share_datasets_examined"],1)
        self.assertEqual(result["candidate_a_share_datasets_checked"],5)

    def test_missing_source_market_fails_closed(self):
        self.paths["sz"].unlink()
        with self.assertRaisesRegex(ValueError,"Missing/unsafe"):
            M.inspect(self.root)

    def test_invalid_budget_rejected_before_original_sources(self):
        for n in (0,-1,True,M.MAX_DATASETS+1):
            with self.subTest(n=n):
                with self.assertRaises(ValueError):
                    M.inspect(self.root,max_datasets=n)
        with self.assertRaisesRegex(ValueError,"bounded positive"):
            M.inspect(self.root,max_probes=0)

    def test_small_probe_budget_stops_before_unbounded_history(self):
        with self.assertRaisesRegex(ValueError,"probe budget exceeded"):
            M.inspect(self.root,max_probes=4)

    def test_small_candidate_budget_stops_without_market_changes(self):
        before=self.hashes()
        with self.assertRaisesRegex(ValueError,"Excessive"):
            M.inspect(self.root,max_datasets=1)
        self.assertEqual(before,self.hashes())

    def test_unsorted_original_h5_first_last_fails_closed(self):
        import h5py
        p=self.paths["sz"]
        with h5py.File(p,"r+") as h:
            ds=h["data/SZ000001"]
            row0=ds[0]
            row0["datetime"]=202612010931
            ds[0]=row0
        with self.assertRaisesRegex(ValueError,"Unsorted"):
            M.inspect(self.root)

    def test_year_month_boundaries_are_exact_native_keys(self):
        ends=M.native_month_keys()
        self.assertEqual(len(ends),12)
        self.assertEqual(ends[0],202502010000)
        self.assertEqual(ends[11],202601010000)
        self.assertEqual(ends,sorted(ends))


if __name__=="__main__":
    unittest.main(verbosity=2)
