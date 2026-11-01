"""Two essential synthetic tests of REAL purchased-first 1min/5min Parquet writes.

Inputs and outputs exist only under H5ParquetReconciler/work scratch.
Tests preserve an actual purchased-specific vendor extra column.
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

M=local("synthetic_purchased_first_physical_minute_union",
        TOOLS/"write-purchased-first-unified-minute-day-parquet.py")
FIX=local("synthetic_minute_h5_stager_fixture_for_union",
          HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")


class PurchasedFirstPhysicalMinuteDayTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.f=FIX.RealMinuteGapWrites(
            "test_two_real_private_minute_parquet_files_created_and_read_back")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.base=self.f.base
        self.work=self.base/"work"/"unified_parquet"/"minute_complete_day"
        self.reports=self.base/"reports"
        self.reports.mkdir(exist_ok=True)
        self.runid="123456789abc"
        # Vendor-specific field MUST be retained. Do not silently lose it
        # when an H5-origin row has a different source schema.
        for period in ("1min","5min"):
            purchased=self.base/"AllCycleAStockData"/period/"2026"/"sample.parquet"
            old=pq.read_table(purchased)
            expanded=old.append_column("vendor_marker",
                                       pa.array(["vendor-original-only"]))
            pq.write_table(expanded,purchased)
        self.stage=self.reports/"minute-stage-source-safe.json"
        with self.f.patched():
            pairs={
                p:FIX.M.write_private_day(
                    self.base,self.f.day,p,self.runid,
                    max_purchased_rows=10000,max_h5_rows=10000)
                for p in ("1min","5min")
            }
        self.stage.write_text(json.dumps({
            "format":FIX.M.FORMAT,
            "source_day":self.f.day.isoformat(),
            "period_results":pairs,
            "original_market_files_modified":False,
            "production_or_private_pointer_modified":False,
            "all_private_outputs_written_not_merged":True,
        }),encoding="utf-8")

    def patched(self):
        ctx=contextlib.ExitStack()
        for module,attribute,value in (
            (M,"MODULE",self.base),
            (M,"REPORTS",self.reports),
            (M,"OUT",self.work),
            (M.G,"MODULE",self.base),
            (M.G,"REPORTS",self.reports),
        ):
            ctx.enter_context(patch.object(module,attribute,value))
        return ctx

    def test_purchased_first_physical_two_periods_preserve_vendor_and_h5_raw(self):
        import pyarrow.parquet as pq
        with self.patched():
            result=M.stage_unified(
                self.base,self.stage,self.runid,
                self.reports/"physical-unified.json",max_rows=10000)
        for period,h5_num in (("1min",240),("5min",48)):
            r=result["periods"][period]
            self.assertEqual(r["unified_rows"],h5_num+1)
            self.assertEqual(r["source_rows"],{
                "purchased_parquet":1,
                "h5_only_complete_stockday":h5_num,
            })
            self.assertEqual(r["purchased_vendor_extra_columns_retained"],1)
            table=pq.read_table(self.base/r["unified_parquet_relative_file"])
            self.assertEqual(table.num_rows,h5_num+1)
            self.assertIn("purchased__vendor_marker",table.schema.names)
            selected=table.to_pylist()
            purchased=[r for r in selected if r["value_source"]=="purchased_parquet"]
            self.assertEqual(len(purchased),1)
            self.assertEqual(purchased[0]["symbol"],"SZ000001")
            self.assertEqual(purchased[0]["source_symbol"],"000001.XSHE")
            self.assertEqual(purchased[0]["purchased__vendor_marker"],
                             "vendor-original-only")
            self.assertIsNone(purchased[0]["h5_native_datetime"])
            h5=[r for r in selected if r["value_source"]=="h5_only_complete_stockday"]
            self.assertEqual(len(h5),h5_num)
            self.assertEqual({r["symbol"] for r in h5},{"SH600000"})
            self.assertTrue(all(r["purchased__vendor_marker"] is None for r in h5))
            self.assertEqual(h5[0]["h5_native_openPrice"],10500)
            self.assertTrue(r["full_merged_source_rows_and_vendor_extra_columns_readback_verified"])
        self.assertFalse(result["full_minute_history_unified"])
        self.assertFalse(result["original_purchased_parquet_or_hikyuu_h5_modified"])

    def test_modified_staged_h5_parquet_sha_refuses_physical_union(self):
        staged=(self.base/"work"/"unified_parquet"/"minute_gap_staging"/
                self.runid/"5min"/"2026-10-13.parquet")
        staged.write_bytes(staged.read_bytes()+b"synthetic-only-data-change")
        with self.patched():
            with self.assertRaisesRegex(ValueError,"SHA changed"):
                M.stage_unified(self.base,self.stage,self.runid,
                                self.reports/"physical-unified.json",
                                max_rows=10000)
        self.assertFalse((self.work/f"minute_{self.runid}").exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
