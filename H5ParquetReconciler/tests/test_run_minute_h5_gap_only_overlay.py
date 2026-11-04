"""Actual synthetic Parquet/H5 regression for the new source-first delta path.

All files are tiny synthetic examples under module/work/_union_scratch.
No real licensed market data or original Hikyuu files are touched.
"""
import contextlib
import hashlib
import importlib.util
import tempfile
import unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

N=load("tested_purchased_primary_gap_overlay",
       TOOLS/"run-minute-h5-gap-only-overlay.py")
F=load("tested_source_first_existing_synthetic_fixture",
       HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")


class PurchasedPrimaryGapOverlayTests(unittest.TestCase):
    def setUp(self):
        self.fixture=F.RealMinuteGapWrites(
            "test_two_real_private_minute_parquet_files_created_and_read_back")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.base
        self.day=date(2026,10,13)
        self.work=self.root/"work"/"unified_parquet"/"minute_gap_staging"
        self.reports=self.root/"reports"
        self.reports.mkdir(parents=True,exist_ok=True)
        self.runid="abcddcba1234"

    def patched(self):
        c=contextlib.ExitStack()
        for target,key,value in (
            (N.ST,"MODULE",self.root),
            (N.ST,"WORK",self.work),
            (N.ST,"REPORTS",self.reports),
            (N,"REPORTS",self.reports),
            (N.W,"LOCK",self.root/"work"/"minute_gui"/"active.lock"),
        ):
            c.enter_context(patch.object(target,key,value))
        return c

    def original_hashes(self):
        return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest()
                for name in ("AllCycleAStockData","HikyuuData")
                for p in (self.root/name).rglob("*") if p.is_file()}

    def purchase_sh_too(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        epoch=int(datetime(2026,10,13,9,31,tzinfo=timezone(
            timedelta(hours=8))).timestamp()*1000)
        for period in ("1min","5min"):
            # Original bought sample has SZ000001; add SH600000 too,
            # so BOTH H5 symbols are purchased. No H5 key is eligible.
            dt=epoch if period=="1min" else epoch-60000
            folder=self.root/"AllCycleAStockData"/period/"2026"
            pq.write_table(pa.table({
                "ts":pa.array([dt],type=pa.int64()),
                "symbol":["SH600000"],
                "open":[10.0],"high":[11.0],"low":[9.0],
                "close":[10.5],"volume":[100.0],"amount":[2000.0],
            }),folder/"bought_SH600000.parquet")

    def test_preview_is_read_only_and_counts_only_real_h5_gaps(self):
        originals=self.original_hashes()
        with self.patched():
            r=N.execute(self.root,self.day,self.runid,write=False)
        self.assertEqual(r["status"],"preview_no_market_files_written")
        self.assertEqual(r["accepted_new_h5_full_stockday_gap_rows"],0)
        self.assertEqual(r["purchased_bars_rematerialized"],0)
        self.assertEqual(r["periods"]["1min"]["eligible_h5_only_rows"],240)
        self.assertEqual(r["periods"]["5min"]["eligible_h5_only_rows"],48)
        self.assertFalse(self.work.exists())
        self.assertEqual(list(self.reports.glob("minute-h5-gap-only-*.json")),[])
        self.assertEqual(self.original_hashes(),originals)

    def test_all_purchased_days_create_zero_market_files(self):
        self.purchase_sh_too()
        originals=self.original_hashes()
        with self.patched():
            r=N.execute(self.root,self.day,self.runid,write=True)
        self.assertEqual(r["status"],
                         "zero_eligible_full_stockday_gap_no_market_files_written")
        self.assertEqual(r["accepted_new_h5_full_stockday_gap_rows"],0)
        self.assertEqual(r["purchased_bars_rematerialized"],0)
        self.assertTrue(Path(r["report_path"]).is_file())
        self.assertFalse(self.work.exists())
        self.assertEqual(r["outputs"]["1min"]["private_parquet_relative_file"],None)
        self.assertEqual(r["outputs"]["5min"]["private_parquet_relative_file"],None)
        self.assertFalse(r["periods"]["1min"]["partial_purchased_stockday_minute_keys_checked"])
        self.assertEqual(self.original_hashes(),originals)

    def test_true_full_stockday_gap_writes_only_h5_native_rows(self):
        import pyarrow.parquet as pq
        originals=self.original_hashes()
        with self.patched():
            r=N.execute(self.root,self.day,self.runid,write=True)
        self.assertEqual(r["accepted_new_h5_full_stockday_gap_rows"],288)
        self.assertEqual(r["purchased_bars_rematerialized"],0)
        for p,n in (("1min",240),("5min",48)):
            self.assertEqual(r["outputs"][p]["written_h5_gap_rows"],n)
            src=self.root/r["outputs"][p]["private_parquet_relative_file"]
            self.assertTrue(src.is_file())
            self.assertEqual(N.ST.pct_hash(src),r["outputs"][p]["private_parquet_sha256"])
            table=pq.read_table(src)
            self.assertEqual(table.num_rows,n)
            self.assertEqual(set(table["symbol"].to_pylist()),{"SH600000"})
            self.assertEqual(set(table["value_source"].to_pylist()),
                             {"h5_only_complete_stockday"})
        self.assertEqual(self.original_hashes(),originals)
        self.assertTrue(Path(r["report_path"]).is_file())
        self.assertFalse(r["ready_for_production_query"])

    def test_partial_h5_session_is_quarantined_without_empty_5min_file(self):
        import h5py
        h5path=self.root/"HikyuuData"/"sh_5min.h5"
        with h5py.File(h5path,"r+") as h5:
            data=h5["data"]["SH600000"][:]
            del h5["data"]["SH600000"]
            h5["data"].create_dataset("SH600000",data=data[:-1])
        with self.patched():
            r=N.execute(self.root,self.day,self.runid,write=True)
        self.assertEqual(r["accepted_new_h5_full_stockday_gap_rows"],240)
        self.assertEqual(r["periods"]["5min"]["eligible_h5_only_rows"],0)
        self.assertEqual(r["periods"]["5min"][
            "quarantined_h5_only_stockdays_by_reason"]["incomplete_5min_session"],1)
        self.assertIsNone(r["outputs"]["5min"]["private_parquet_relative_file"])
        self.assertFalse((self.work/self.runid/"5min").exists())
        self.assertTrue((self.work/self.runid/"1min").is_dir())

    def test_original_market_files_changed_mid_inspection_fails_closed(self):
        with self.patched(),patch.object(N,"source_snapshot",
                                          side_effect=[{"version":1},{"version":2}]):
            with self.assertRaisesRegex(RuntimeError,"changed while inspecting"):
                N.execute(self.root,self.day,self.runid,write=True)
        self.assertFalse(self.work.exists())
        self.assertEqual(list(self.reports.glob("minute-h5-gap-only-*.json")),[])

    def test_old_gap_receipt_blocks_double_counting_h5_market_keys(self):
        # October 13 already has an old validated H5 gap in real history.
        # A new run ID must not manufacture a second 'net new' gap receipt.
        receipt=self.reports/"minute-batch-stage-20261013-aaaaaaaaaaaa.json"
        receipt.write_text("{}",encoding="utf-8")
        with self.patched():
            preview=N.execute(self.root,self.day,self.runid,write=False)
            self.assertEqual(preview["previous_gap_receipt_count_for_date"],1)
            with self.assertRaisesRegex(RuntimeError,"PRIOR_GAP_RECEIPT_FOR_DATE"):
                N.execute(self.root,self.day,self.runid,write=True)
        self.assertFalse(self.work.exists())
        self.assertFalse(list(self.reports.glob("minute-h5-gap-only-*.json")))
        self.assertEqual(receipt.read_text(encoding="utf-8"),"{}")

    def test_readonly_day_without_market_data_has_no_write(self):
        with self.patched():
            r=N.execute(self.root,date(2026,1,1),self.runid,write=True)
        self.assertEqual(r["accepted_new_h5_full_stockday_gap_rows"],0)
        self.assertFalse(self.work.exists())
        self.assertEqual(r["status"],
            "zero_eligible_full_stockday_gap_no_market_files_written")

    def test_reuse_same_run_id_never_overwrites_accepted_output(self):
        with self.patched():
            first=N.execute(self.root,self.day,self.runid,write=True)
            with self.assertRaisesRegex(ValueError,"new isolated report"):
                N.execute(self.root,self.day,self.runid,write=True)
        self.assertEqual(first["accepted_new_h5_full_stockday_gap_rows"],288)

if __name__=="__main__":
    unittest.main(verbosity=2)
