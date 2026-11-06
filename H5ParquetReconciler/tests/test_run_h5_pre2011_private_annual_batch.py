"""Fictional 1992-2010 max-three-year private historical H5 batch contracts.

All small Parquet artifacts live in TemporaryDirectory; all annual-source
calls are mocks, so no licensed/user H5/Parquet file is opened by tests.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "pre2011_annual_private_h5_batch_synthetic_tests",
    HERE.parent/"tools"/"run-h5-pre2011-private-annual-batch.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Pre2011PrivateYearBatchTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.base=Path(t.name)
        self.module=self.base/"fake-module"
        self.module.mkdir()
        self.root=self.base/"original-market"
        self.root.mkdir()
        self.patches=[]
        for p in (
            patch.object(M.ANNUAL,"MODULE",self.module),
            patch.object(M.ANNUAL.P90,"EXPECTED_H5_STATE","a"*64),
            patch.object(M.ANNUAL.P90,"EXPECTED_PQ_STATE","b"*64),
            patch.dict(M.ANNUAL.EXPECTED,{
                1992:(2,1,1,2),1993:(3,2,2,2),1994:(4,3,3,3)
            }),
        ):
            p.start()
            self.patches.append(p)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def make(self,year,*,reused=False):
        amount=M.ANNUAL.EXPECTED[year][0]
        relative=f"work/unified_parquet/historical_pre2011_daily_pilots/{year}-research-{'c'*16}"
        folder=self.module/relative
        folder.mkdir(parents=True)
        parquet=folder/"day.parquet"
        data=pa.Table.from_pylist([
            {"ts":int(year)*100000000+i,"symbol":"600000.XSHG",
             "open":10.0,"high":11.0,"low":9.0,"close":10.0,
             "volume":100.0,"amount":1000.0,
             "source":"hikyuu_h5_historical_uncertified_private_candidate"}
            for i in range(amount)
        ],schema=M.ANNUAL._candidate_schema())
        pq.write_table(data,parquet,compression="snappy")
        common={
            "format":M.FORMAT,
            "state":"verified_private_candidate_not_promoted",
            "year":year,
            "period":"day",
            "candidate_stockday_rows":amount,
            "other_code_source_rows_not_staged":M.ANNUAL.EXPECTED[year][1],
            "distinct_source_dates":M.ANNUAL.EXPECTED[year][3],
            "h5_original_state_sha256":"a"*64,
            "purchased_original_state_sha256":"b"*64,
            "purchased_pre2011_all_day_files_confirmed_absent":True,
            "native_day_keys_and_OHLCVA_geometry_checked":True,
            "private_stage_relative_dir":relative,
            "private_parquet_sha256":M.ANNUAL.P90._digest(parquet),
            "private_parquet_row_count":amount,
            "private_parquet_written":True,
            **{k:False for k in M.FLAGS},
        }
        (folder/"manifest.json").write_text(
            json.dumps(common,sort_keys=True),encoding="utf-8")
        return {**common,
                "private_parquet_written":not reused,
                "state":("already_verified_private_candidate_not_promoted"
                          if reused else "verified_private_candidate_not_promoted")}

    def test_exact_two_years_verify_individual_manifest_and_sha(self):
        x=self.make(1992)
        y=self.make(1993,reused=True)
        with patch.object(M.ANNUAL,"annual",side_effect=[x,y]) as mock_annual:
            with redirect_stdout(StringIO()) as out:
                summary=M.batch(self.root,1992,1993,write=True)
        self.assertEqual(summary["years_completed"],[1992,1993])
        self.assertEqual(summary["new_or_revalidated_private_stockdays"],5)
        self.assertTrue(summary["all_private_year_checkpoints_verified"])
        self.assertFalse(summary["production_activated"])
        self.assertFalse(summary["h5_price_volume_amount_units_certified"])
        self.assertIn("CHECKPOINT=new",out.getvalue())
        self.assertIn("CHECKPOINT=verified_existing",out.getvalue())
        self.assertNotIn("600000.XSHG",out.getvalue())
        self.assertEqual(mock_annual.call_count,2)
        self.assertEqual(mock_annual.call_args_list[0].args[1],1992)
        self.assertTrue(mock_annual.call_args_list[1].kwargs["write"])

    def test_three_year_cap_is_enforced_before_source_calls(self):
        with patch.object(M.ANNUAL,"annual",side_effect=AssertionError("source read")):
            with self.assertRaisesRegex(ValueError,"At most three"):
                M.batch(self.root,1992,1995,write=True)

    def test_1991_or_2011_out_of_batch_scope_rejected(self):
        for begin,end in ((1991,1992),(2010,2011),(1994,1993)):
            with self.subTest(begin=begin,end=end),patch.object(
                    M.ANNUAL,"annual",side_effect=AssertionError("source read")):
                with self.assertRaisesRegex(ValueError,"Only a selected"):
                    M.batch(self.root,begin,end,write=True)

    def test_private_flag_is_explicit_and_false_by_default(self):
        with patch.object(M.ANNUAL,"annual",side_effect=AssertionError("source read")):
            with self.assertRaisesRegex(ValueError,"explicit --stage-private"):
                M.batch(self.root,1992,1992)

    def test_corrupt_private_day_sha_stops_before_next_year(self):
        result=self.make(1992)
        f=self.module/result["private_stage_relative_dir"]/"day.parquet"
        f.write_bytes(f.read_bytes()+b"tampered")
        with patch.object(M.ANNUAL,"annual",return_value=result) as mock_annual:
            with redirect_stdout(StringIO()) as out:
                with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                    M.batch(self.root,1992,1993,write=True)
        self.assertEqual(mock_annual.call_count,1)
        self.assertIn("PRIVATE_H5_BATCH_STOPPED_AT_YEAR=1992",out.getvalue())

    def test_wrong_year_candidate_count_rejected(self):
        result=self.make(1992)
        result["candidate_stockday_rows"]=99
        with patch.object(M.ANNUAL,"annual",return_value=result):
            with redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError,"exact audited year"):
                    M.batch(self.root,1992,1992,write=True)

    def test_incomplete_manifest_is_not_published_as_checkpoint(self):
        result=self.make(1992)
        (self.module/result["private_stage_relative_dir"]/"manifest.json").unlink()
        with patch.object(M.ANNUAL,"annual",return_value=result):
            with redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError,"incomplete"):
                    M.batch(self.root,1992,1992,write=True)

    def test_existing_immutable_manifest_with_wrong_h5_sha_fails(self):
        result=self.make(1992,reused=True)
        result["h5_original_state_sha256"]="d"*64
        with patch.object(M.ANNUAL,"annual",return_value=result):
            with redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError,"source safety gates"):
                    M.batch(self.root,1992,1992,write=True)

    def test_promotion_or_unit_certification_not_claimed(self):
        for key in ("ready_for_production_merge","h5_volume_amount_price_units_certified",
                    "historical_security_master_certified"):
            with self.subTest(key=key):
                result=self.make(1992)
                result[key]=True
                with patch.object(M.ANNUAL,"annual",return_value=result):
                    with redirect_stdout(StringIO()):
                        with self.assertRaisesRegex(ValueError,"source safety gates"):
                            M.batch(self.root,1992,1992,write=True)
                # Reuse directory after this subtest without rewriting it.
                (self.module/result["private_stage_relative_dir"]/"manifest.json").unlink()
                (self.module/result["private_stage_relative_dir"]/"day.parquet").unlink()
                (self.module/result["private_stage_relative_dir"]).rmdir()

    def test_annual_middle_year_failure_preserves_previous_checkpoint(self):
        x=self.make(1992)
        with patch.object(M.ANNUAL,"annual",side_effect=[
                x,ValueError("fictional 1993 source drift")]) as mock_annual:
            with redirect_stdout(StringIO()) as out:
                with self.assertRaisesRegex(ValueError,"fictional 1993 source drift"):
                    M.batch(self.root,1992,1994,write=True)
        self.assertEqual(mock_annual.call_count,2)
        self.assertIn("PRIVATE_H5_YEAR_PASS=1992",out.getvalue())
        self.assertIn("PRIVATE_H5_BATCH_STOPPED_AT_YEAR=1993",out.getvalue())
        self.assertTrue((self.module/x["private_stage_relative_dir"]/"manifest.json").is_file())

    def test_manifest_source_identity_alteration_rejected(self):
        result=self.make(1992)
        f=self.module/result["private_stage_relative_dir"]/"manifest.json"
        proof=json.loads(f.read_text("utf-8"))
        proof["purchased_original_state_sha256"]="e"*64
        f.write_text(json.dumps(proof),encoding="utf-8")
        with patch.object(M.ANNUAL,"annual",return_value=result):
            with redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError,"metadata drift"):
                    M.batch(self.root,1992,1992,write=True)


if __name__=="__main__":
    unittest.main(verbosity=2)
