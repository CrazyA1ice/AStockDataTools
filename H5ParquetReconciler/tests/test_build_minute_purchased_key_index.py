"""Synthetic purchased minute membership-index integration, no real sources."""
import contextlib
import importlib.util
import tempfile
import unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(tag,path):
    spec=importlib.util.spec_from_file_location(tag,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


Q=load("tested_exact_minutes_with_index",
       TOOLS/"preview-minute-exact-key-diff-readonly.py")
I=Q.I
F=load("tested_index_original_synthetic_h5_parquet",
       HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")


class SourceMinuteMembershipIndexTests(unittest.TestCase):
    def setUp(self):
        self.fixture=F.RealMinuteGapWrites(
            "test_two_real_private_minute_parquet_files_created_and_read_back")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.base
        self.day=self.fixture.day
        self.store=self.root/"work"/"unified_parquet"/"minute_key_index"
        self.rid="bbaaccdd1234"

    def patched(self):
        stack=contextlib.ExitStack()
        for module,key,value in (
            (Q.N.ST,"MODULE",self.root),
            (Q.N.ST,"WORK",self.root/"work"/"unified_parquet"/"minute_gap_staging"),
            (Q.N.ST,"REPORTS",self.root/"reports"),
            (Q.N,"REPORTS",self.root/"reports"),
            (I,"STORE",self.store),
            (I.N.ST,"MODULE",self.root),
            (I.N.ST,"WORK",self.root/"work"/"unified_parquet"/"minute_gap_staging"),
            (I.N.ST,"REPORTS",self.root/"reports"),
            (I.N,"REPORTS",self.root/"reports"),
        ):
            stack.enter_context(patch.object(module,key,value))
        return stack

    def one(self):
        return I.build(self.root,self.day,self.day,self.rid)

    def test_real_small_index_reuses_bought_keys_without_vendor_parquet_rescan(self):
        with self.patched():
            before=Q.preview(self.root,self.day)
            info=self.one()
            self.assertEqual(info["periods"]["1min"]["a_share_unique_keys"],1)
            self.assertEqual(info["periods"]["5min"]["a_share_unique_keys"],1)
            self.assertEqual(info["purchased_ohlcva_rows_copied"],0)
            self.assertFalse(info["new_market_parquet_or_h5_files_written"])
            with patch.object(
                    Q.ST,"purchased_stockdays",
                    side_effect=AssertionError("rescan original purchased rows")):
                reused=Q.preview(self.root,self.day,key_index=info["index_path"])
            for period in ("1min","5min"):
                expected=before["periods"][period]
                actual=reused["periods"][period]
                for field in (
                    "purchased_a_share_date_key_count",
                    "overlapping_exact_keys",
                    "h5_only_keys_on_full_purchased_absence_days",
                    "h5_only_candidate_keys_on_partial_purchased_stockdays",
                    "purchased_only_keys_on_native_complete_H5_stockdays",
                ):
                    self.assertEqual(actual[field],expected[field])
                self.assertTrue(actual["purchased_date_key_scan"]["index_used"])
                self.assertTrue(actual["purchased_date_key_scan"][
                    "no_purchased_parquet_scanned_during_lookup"])
            self.assertTrue(reused["reusable_key_index_used"])
            self.assertFalse(reused["new_market_parquet_or_h5_files_written"])

    def test_build_window_with_unrelated_dates_stays_precise(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        before_day=date(2026,10,12)
        before_epoch=int(datetime(2026,10,12,9,31,tzinfo=timezone(
            timedelta(hours=8))).timestamp()*1000)
        folder=self.root/"AllCycleAStockData"/"1min"/"2026"
        pq.write_table(pa.table({
            "ts":pa.array([before_epoch]*4,type=pa.int64()),
            "symbol":["SH600000"]*4,
        }),folder/"outside_day_source.parquet")
        # Four identical keys in prior day are duplicates and should be
        # rejected only when that day is inside the index window.
        with self.patched():
            result=self.one()
            self.assertEqual(result["periods"]["1min"]["a_share_unique_keys"],1)
            with self.assertRaisesRegex(ValueError,"Duplicate purchased minute key"):
                I.build(self.root,before_day,self.day,"eeeeffff1234")

    def test_changed_source_rejects_prior_index_read(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with self.patched():
            info=self.one()
            pq.write_table(pa.table({
                "ts":pa.array([1],type=pa.int64()),
                "symbol":["SH600000"],
            }),self.root/"AllCycleAStockData"/"1min"/"2026"/"extra.parquet")
            with self.assertRaisesRegex(ValueError,"source metadata changed"):
                I.query_index(info["index_path"],self.root,"1min",self.day)

    def test_rejects_wrong_window_and_duplicate_index_destination(self):
        with self.patched():
            info=self.one()
            with self.assertRaisesRegex(ValueError,"outside|mismatch"):
                I.query_index(info["index_path"],self.root,
                              "1min",date(2026,10,12))
            with self.assertRaisesRegex(ValueError,"output exists"):
                self.one()
            with self.assertRaisesRegex(ValueError,"1..31 days"):
                I.make_days(date(2026,1,1),date(2026,2,15))

    def test_index_keeps_the_vendor_extra_0930_minute_slot(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        epoch=int(datetime(2026,10,13,9,30,tzinfo=timezone(
            timedelta(hours=8))).timestamp()*1000)
        folder=self.root/"AllCycleAStockData"/"1min"/"2026"
        pq.write_table(pa.table({
            "ts":pa.array([epoch],type=pa.int64()),
            "symbol":["SH600000"],
        }),folder/"extra_sh_0931.parquet")
        with self.patched():
            info=self.one()
            values,meta=I.query_index(
                info["index_path"],self.root,"1min",self.day)
            self.assertIn(epoch,values["SH600000"])
            self.assertEqual(meta["purchased_a_share_date_key_count"],2)
            self.assertFalse(info["source_content_sha_certified"])

if __name__=="__main__":
    unittest.main(verbosity=2)
