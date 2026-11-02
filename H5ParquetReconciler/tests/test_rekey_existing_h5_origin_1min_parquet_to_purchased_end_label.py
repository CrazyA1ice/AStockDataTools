"""Two focused real Parquet tests for OLD -1min H5-only minute gap rekey.
Only synthetic scratch data, original purchased/H5 not touched.
"""
from __future__ import annotations
import contextlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"

def load(tag,p):
    spec=importlib.util.spec_from_file_location(tag,p)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

R=load("minute_legacy_rekey_synthetic",
       TOOLS/"rekey-existing-h5-origin-1min-parquet-to-purchased-end-label.py")
F=load("minute_legacy_rekey_fixture",
       HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")


class LegacyH5MinuteRekeyTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
        self.f=F.RealMinuteGapWrites(
            "test_two_real_private_minute_parquet_files_created_and_read_back")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.base=self.f.base
        self.report=self.base/"reports"
        self.report.mkdir(exist_ok=True)
        self.work=self.base/"work"/"unified_parquet"/"minute_gap_staging"
        self.legacy_id="123456789abc"
        self.output=self.report/"rekey-new-safe.json"
        self.old=self.report/"legacy-original-safe.json"
        with self.f.patched():
            periods={period:F.M.write_private_day(
                self.base,self.f.day,period,self.legacy_id,
                max_purchased_rows=10000,max_h5_rows=10000)
                for period in ("1min","5min")}
        legacy=self.base/periods["1min"]["private_parquet_relative_file"]
        table=pq.read_table(legacy)
        shifted=pc.subtract(table.column("ts"),pa.scalar(60000,pa.int64()))
        # This synthesizes an OLD-version data value, not an OLD-version
        # schema. Keep the original required (nullable=False) ts field.
        # Passing just the string "ts" silently replaces it with a
        # nullable=True Field, making the migration's strict schema
        # preflight reject this synthetic fixture before any real work.
        original_schema=table.schema
        table=table.set_column(table.schema.get_field_index("ts"),
                               table.schema.field("ts"),shifted)
        self.assertEqual(table.schema,original_schema)
        pq.write_table(table,legacy,compression="zstd")
        periods["1min"]["private_parquet_sha256"]=R.sha(legacy)
        periods["1min"]["h5_time_convention_source_end_to_candidate_parquet_start_minutes"]=1
        periods["1min"].pop("standardized_minute_key_contract",None)
        periods["5min"].pop("standardized_minute_key_contract",None)
        self.old.write_text(json.dumps({
            "format":F.M.FORMAT,
            "source_day":str(self.f.day),
            "period_results":periods,
            "original_market_files_modified":False,
            "production_or_private_pointer_modified":False,
            "all_private_outputs_written_not_merged":True,
        }),encoding="utf-8")
        self.prior_sha=R.sha(legacy)

    def patched(self):
        c=contextlib.ExitStack()
        for module,field,value in (
            (R,"MODULE",self.base),
            (R,"REPORTS",self.report),
            (R,"WORK",self.work),
            (R.M,"MODULE",self.base),
            (R.M,"REPORTS",self.report),
        ):
            c.enter_context(patch.object(module,field,value))
        return c

    def test_versioned_rekey_uses_staged_h5_integers_no_original_h5_access(self):
        import pyarrow.parquet as pq
        with self.patched():
            result=R.rekey(self.old,"aaaaaaaaaaaa",self.output)
        self.assertEqual(result["period_results"]["1min"]["private_parquet_rows"],240)
        self.assertEqual(result["period_results"]["5min"]["private_parquet_rows"],48)
        self.assertEqual(result["period_results"]["1min"][
            "h5_time_convention_source_end_to_candidate_parquet_start_minutes"],0)
        path=self.base/result["period_results"]["1min"]["private_parquet_relative_file"]
        table=pq.read_table(path)
        self.assertEqual(table.num_rows,240)
        first=table.to_pylist()[0]
        self.assertEqual(first["h5_native_datetime"],202610130931)
        self.assertEqual(first["ts"],int(
            __import__("datetime").datetime(
                2026,10,13,9,31,
                tzinfo=F.M.CORE.UTC8).timestamp()*1000))
        self.assertEqual(result["period_results"]["5min"]["private_parquet_sha256"],
                         json.loads(self.old.read_text())["period_results"]["5min"][
                             "private_parquet_sha256"])
        self.assertEqual(R.sha(self.base/json.loads(self.old.read_text())[
            "period_results"]["1min"]["private_parquet_relative_file"]),self.prior_sha)
        self.assertFalse(result["original_market_files_modified"])

    def test_nonlegacy_candidate_shift_is_rejected_before_new_files(self):
        content=json.loads(self.old.read_text())
        content["period_results"]["1min"][
            "h5_time_convention_source_end_to_candidate_parquet_start_minutes"]=0
        self.old.write_text(json.dumps(content),encoding="utf-8")
        with self.patched(),self.assertRaisesRegex(ValueError,"Only old unaligned"):
            R.rekey(self.old,"aaaaaaaaaaaa",self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.work/"aaaaaaaaaaaa").exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
