"""Tiny real Arrow/H5 exact-minute-key comparisons, NO licensed source access."""
import contextlib
import importlib.util
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(tag,path):
    spec=importlib.util.spec_from_file_location(tag,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


Q=load("test_single_day_exact_key_preview",
       TOOLS/"preview-minute-exact-key-diff-readonly.py")
F=load("test_existing_synthetic_h5_minute_fixture_for_exact_keys",
       HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")


class ExactMinuteKeyReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=F.RealMinuteGapWrites(
            "test_two_real_private_minute_parquet_files_created_and_read_back")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.base
        self.day=self.fixture.day

    def patched(self):
        stack=contextlib.ExitStack()
        for module,key,value in (
            (Q.N.ST,"MODULE",self.root),
            (Q.N.ST,"WORK",self.root/"work"/"unified_parquet"/"minute_gap_staging"),
            (Q.N.ST,"REPORTS",self.root/"reports"),
            (Q.N,"REPORTS",self.root/"reports"),
        ):
            stack.enter_context(patch.object(module,key,value))
        return stack

    def put_purchased_keys(self,period,symbol,stamps,name):
        import pyarrow as pa
        import pyarrow.parquet as pq
        folder=self.root/"AllCycleAStockData"/period/"2026"
        folder.mkdir(parents=True,exist_ok=True)
        pq.write_table(pa.table({
            "ts":pa.array(stamps,type=pa.int64()),
            "symbol":[symbol]*len(stamps),
        }),folder/name)

    def normalized(self,period):
        return sorted(Q.normalized_native_keys(self.day,period).values())

    def test_one_day_key_preview_discriminates_full_gap_from_partial_gap(self):
        # The fixture has SZ bought 09:30 only, plus complete H5 SH/SZ.
        with self.patched():
            result=Q.preview(self.root,self.day)
        one=result["periods"]["1min"]
        five=result["periods"]["5min"]
        self.assertEqual(one["h5_only_keys_on_full_purchased_absence_days"],240)
        self.assertEqual(one["h5_only_candidate_keys_on_partial_purchased_stockdays"],240)
        self.assertEqual(one["purchased_only_keys_on_native_complete_H5_stockdays"],1)
        self.assertEqual(five["h5_only_keys_on_full_purchased_absence_days"],48)
        self.assertEqual(five["h5_only_candidate_keys_on_partial_purchased_stockdays"],47)
        self.assertEqual(five["overlapping_exact_keys"],1)
        self.assertFalse(result["new_market_parquet_or_h5_files_written"])
        self.assertFalse((self.root/"reports").exists())
        self.assertFalse((self.root/"work"/"unified_parquet").exists())

    def test_purchased_complete_full_days_have_no_h5_only_partial_candidates(self):
        # SZ already has a distinct vendor 09:30 1min row. It is NOT an H5
        # missing bar. Fill both H5 session grids with original buy keys.
        for period in ("1min","5min"):
            for sym in ("SH600000","SZ000001"):
                stamps=self.normalized(period)
                if period=="5min" and sym=="SZ000001":
                    stamps=stamps[1:] # original bought 09:30 already
                self.put_purchased_keys(
                    period,sym,stamps,
                    "full-"+period+"-"+sym+".parquet")
        with self.patched():
            result=Q.preview(self.root,self.day)
        for period in ("1min","5min"):
            p=result["periods"][period]
            self.assertEqual(p["h5_only_keys_on_full_purchased_absence_days"],0)
            self.assertEqual(p["h5_only_candidate_keys_on_partial_purchased_stockdays"],0)
            self.assertEqual(p["overlapping_stockdays_with_native_complete_H5"],2)
        self.assertEqual(result["periods"]["1min"][
            "purchased_only_keys_on_native_complete_H5_stockdays"],1)

    def test_true_single_missing_minute_is_candidate_not_automatically_accepted(self):
        # Buy all SZ H5 keys; buy SH H5 keys except one (missing minute).
        grid=self.normalized("1min")
        self.put_purchased_keys("1min","SZ000001",grid,"sz-complete.parquet")
        self.put_purchased_keys("1min","SH600000",grid[:-1],"sh-one-missing.parquet")
        with self.patched():
            p=Q.inspect_exact_period(self.root,self.day,"1min")
        self.assertEqual(p["h5_only_candidate_keys_on_partial_purchased_stockdays"],1)
        self.assertEqual(p["partial_purchased_stockdays_with_h5_only_candidate_keys"],1)
        self.assertEqual(p["h5_only_keys_on_full_purchased_absence_days"],0)
        self.assertEqual(p["candidate_keys_automatically_accepted"],0)
        self.assertEqual(p["purchased_bars_rematerialized"],0)

    def test_duplicate_purchased_key_is_fail_closed(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        original=self.root/"AllCycleAStockData"/"1min"/"2026"/"sample.parquet"
        table=pq.read_table(original)
        pq.write_table(table,original.with_name("duplicate.parquet"))
        with self.patched(),self.assertRaisesRegex(
                ValueError,"Duplicate purchased minute key"):
            Q.inspect_exact_period(self.root,self.day,"1min")

    def test_incomplete_h5_stockday_is_quarantined_not_candidate(self):
        import h5py
        file=self.root/"HikyuuData"/"sh_5min.h5"
        with h5py.File(file,"r+") as h5:
            data=h5["data"]["SH600000"][:]
            del h5["data"]["SH600000"]
            h5["data"].create_dataset("SH600000",data=data[:-1])
        with self.patched():
            p=Q.inspect_exact_period(self.root,self.day,"5min")
        self.assertEqual(p["quarantined_h5_stockdays_by_reason"],
                         {"incomplete_5min_session":1})
        self.assertEqual(p["h5_only_keys_on_full_purchased_absence_days"],0)
        self.assertEqual(p["h5_only_candidate_keys_on_partial_purchased_stockdays"],47)
        self.assertEqual(p["candidate_keys_automatically_accepted"],0)

    def test_source_metadata_change_during_read_rejects_preview(self):
        with self.patched(),patch.object(
                Q.N,"source_snapshot",side_effect=[{"sha":"a"},{"sha":"b"}]):
            with self.assertRaisesRegex(RuntimeError,"changed during exact-key"):
                Q.preview(self.root,self.day)


if __name__=="__main__":
    unittest.main(verbosity=2)
