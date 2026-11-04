"""Minimal synthetic integration: actual two-year private Parquet -> native H5
full-table writes, purchased precedence, all integer bytes read back.
"""
import contextlib
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"

def load(label,path):
    spec=importlib.util.spec_from_file_location(label,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

B=load("synthetic_full_day_h5_batch",
       TOOLS/"mirror-private-2011-2026-day-to-native-hikyuu-h5.py")
F=load("synthetic_full_day_h5_source_fixture",
       HERE/"test_query_private_2011_2026_all16_coverage_readonly.py")


class WholeDayNativeH5Test(unittest.TestCase):
    def setUp(self):
        self.f=F.All16PrivateCoverageTests(
            "test_2016_mixed_h5_purchased_query_only_returns_aggregate_counts")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.path=self.f.root/"work"/"h5_mirror"
        self.safe=self.f.reports/"real-write-synthetic-safe.json"

    def patched(self):
        ctx=contextlib.ExitStack()
        for obj,name,value in (
            (B,"MODULE",self.f.root),
            (B,"MIRRORS",self.path),
            (B,"REPORTS",self.f.reports),
            (B.Q.M,"MODULE",self.f.root),
            (B.Q.M,"WORK",self.f.work),
            (B.Q.M,"ROOT",self.f.years),
            (B.Q.M,"REPORTS",self.f.reports),
        ):
            ctx.enter_context(patch.object(obj,name,value))
        return ctx

    def test_actual_native_three_market_tables_for_2025_2026(self):
        import tables
        with self.patched():
            result=B.mirror(self.f.verpath,self.f.saved_sha,"123456789abc",
                            self.safe,first_year=2025,last_year=2026,
                            max_year_rows=1200000)
        self.assertEqual(result["total_private_parquet_rows"],11)
        self.assertEqual(result["total_h5_native_integer_records"],11)
        # Regression: tables.Table.nrows may be numpy.int64, but SAFE must
        # contain only JSON-native numbers and be published after serialization.
        self.assertIs(type(result["total_h5_native_integer_records"]),int)
        self.assertIs(type(result["annual_rows"]["2026"]),int)
        self.assertIs(type(result["venue_record_counts"]["SH"]),int)
        self.assertIs(type(result["stock_tables_count"]),int)
        report_data=json.loads(self.safe.read_text(encoding="utf-8"))
        self.assertEqual(report_data["total_h5_native_integer_records"],11)
        self.assertEqual(report_data["annual_rows"],{"2025":1,"2026":10})
        self.assertEqual(result["annual_rows"],{"2025":1,"2026":10})
        self.assertEqual(result["purchased_h5_candidate_source_counts"],{
            "purchased_parquet":10,"private_h5_whole_date_candidate":1})
        self.assertTrue(result["native_40byte_table_integer_sha_readback_verified"])
        self.assertFalse(result["original_hikyuu_h5_files_modified"])
        self.assertEqual(len(result["private_h5_files_sha256"]),3)
        with tables.open_file(str(self.path/"full_day_123456789abc"/"sh_day.h5"),"r") as f:
            t=f.get_node("/data/SH600000")
            self.assertEqual(t.nrows,11)
            self.assertEqual(t.dtype.itemsize,40)
            self.assertEqual(int(t.read(0,1)[0]["datetime"]),202512310000)
        report=self.safe.read_text()
        self.assertNotIn("SH600000",report)
        self.assertNotIn("2025-12-31",report)
        self.assertFalse(result["full_mirror_ready_for_production"])

    def test_changed_year_partition_sha_fails_before_success_safe(self):
        folder,_,_=self.f.data[2025]
        source=folder/"purchased"/"day.parquet"
        source.write_bytes(source.read_bytes()+b"changed-only-in-synthetic-test")
        with self.patched():
            with self.assertRaisesRegex(ValueError,"partition SHA mismatch"):
                B.mirror(self.f.verpath,self.f.saved_sha,"123456789abc",
                         self.safe,first_year=2025,last_year=2026,
                         max_year_rows=1200000)
        self.assertFalse(self.safe.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
