"""Focused real PyTables write/readback of staged 1min+5min private Parquet.
Synthetic only: source data lives in module-local work scratch.
"""
import contextlib
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def local(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M=local("synthetic_minute_native_mirror",
        TOOLS/"mirror-h5-origin-private-minute-parquet-to-native-h5.py")
FIX=local("synthetic_minute_staged_parquet_fixture",
          HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")


class MinuteNativeMirrorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=FIX.RealMinuteGapWrites("test_two_real_private_minute_parquet_files_created_and_read_back")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base=self.fixture.base
        self.reports=self.base/"reports"
        self.reports.mkdir(exist_ok=True)
        self.runid="123456789abc"
        self.staged_safe=self.reports/"staged-synthetic.json"
        with self.fixture.patched():
            result={
                period:FIX.M.write_private_day(
                    self.base,self.fixture.day,period,self.runid,
                    max_purchased_rows=10000,max_h5_rows=10000)
                for period in ("1min","5min")
            }
        self.staged_safe.write_text(json.dumps({
            "format":FIX.M.FORMAT,
            "source_day":self.fixture.day.isoformat(),
            "period_results":result,
            "original_market_files_modified":False,
            "production_or_private_pointer_modified":False,
            "all_private_outputs_written_not_merged":True,
        }),encoding="utf-8")
        self.native_dir=self.base/"work"/"h5_mirror"
        self.safe=self.reports/"native-minute-aggregate.json"

    def patched(self):
        ctx=contextlib.ExitStack()
        for obj,name,value in (
            (M,"MODULE",self.base),
            (M,"REPORTS",self.reports),
            (M,"MIRRORS",self.native_dir),
        ):
            ctx.enter_context(patch.object(obj,name,value))
        return ctx

    def test_real_synthetic_minute_native_six_h5_files_write_and_readback(self):
        import h5py
        with self.patched():
            result=M.write_mirror(
                self.staged_safe,self.runid,self.safe,max_rows=10000)
        self.assertEqual(result["native_h5_bar_counts"],{
            "1min":240,"5min":48})
        self.assertEqual(result["native_h5_full_integer_readback_counts"],{
            "1min":240,"5min":48})
        self.assertEqual(result["native_h5_stock_tables"],{
            "1min":1,"5min":1})
        self.assertEqual(len(result["native_h5_six_files_sha256"]),6)
        self.assertTrue(result["staged_h5_source_raw_integer_values_preserved_exactly"])
        self.assertFalse(result["full_period_minute_mirror_completed"])
        self.assertFalse(result["original_vendor_parquet_or_hikyuu_h5_modified"])
        with h5py.File(self.native_dir/f"minute_gap_{self.runid}"/"sh_5min.h5","r") as f:
            row=f["data"]["SH600000"][0]
            self.assertEqual(int(row["datetime"]),202610130935)
            self.assertEqual(int(row["openPrice"]),10500)
            self.assertEqual(len(f["data"]["SH600000"]),48)
            self.assertEqual(f["data"]["SH600000"].dtype.itemsize,40)
        text=self.safe.read_text(encoding="utf-8")
        for private in ("SH600000","10500","202610130935"):
            self.assertNotIn(private,text)

    def test_staged_parquet_sha_tamper_rejected_without_native_output(self):
        staged=self.base/"work"/"unified_parquet"/"minute_gap_staging"/self.runid/"5min"/"2026-10-13.parquet"
        staged.write_bytes(staged.read_bytes()+b"synthetic-mutation")
        with self.patched():
            with self.assertRaisesRegex(ValueError,"SHA changed"):
                M.write_mirror(self.staged_safe,self.runid,self.safe,max_rows=10000)
        self.assertFalse(self.safe.exists())
        self.assertFalse((self.native_dir/f"minute_gap_{self.runid}").exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
