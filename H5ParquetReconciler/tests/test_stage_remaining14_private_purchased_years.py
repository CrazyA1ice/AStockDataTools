"""Offline synthetic 14-year purchased private staging and fail-closed gates."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"
spec=importlib.util.spec_from_file_location(
    "synthetic_14_year_private_purchased_staging",
    TOOLS/"stage-remaining14-private-purchased-years.py")
S=importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


class Remaining14SyntheticTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        scratch=HERE.parent/"work"/"_union_scratch"
        scratch.mkdir(parents=True,exist_ok=True)
        td=tempfile.TemporaryDirectory(prefix="remaining14-",dir=scratch)
        self.addCleanup(td.cleanup)
        self.base=Path(td.name)
        self.reports=self.base/"reports"
        self.reports.mkdir()
        self.work=self.base/"work"/"unified_parquet"
        self.root=self.work/"physical_years"
        self.vendor=self.base/"vendor"
        self.vendor.mkdir()
        self.source=self.vendor/"dummy-annual.parquet"
        self.extra=0
        self.write_source()
        self.anchors={
            "source_h5_candidate_safe_sha256":"c"*64,
            "accepted_2016_recovery_safe_sha256":"a"*64,
            "accepted_2026_materialization_safe_sha256":"b"*64,
        }
        self.pins=("a"*64,"b"*64)
        self.samples=("2016-safe","2016-audit","2026-safe","2026-audit")
        self.pre=self.reports/"preflight.json"
        self.output=self.reports/"batch.json"
        self.mocked_purchased_calls=[]
        self.made_years=[]
        self.audited_years=[]

    def write_source(self,extra=0,missing=False,int_volume=False):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.extra=extra
        fields=[
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            *(pa.field(f,pa.int64() if f=="volume" and int_volume
                       else pa.float64())
              for f in S.M.PHYS.F if not (f=="amount" and missing)),
            *(pa.field(f"vendor_private_unknown_{j}",pa.int32())
              for j in range(extra)),
        ]
        rows=[{"ts":1450000000000,"symbol":"600001.XSHG",
               "open":5.0,"high":6.0,"low":4.0,"close":5.5,
               "volume":400 if int_volume else 400.0,"amount":1000.0,
               **{f"vendor_private_unknown_{j}":j for j in range(extra)}}]
        pq.write_table(pa.Table.from_pylist(rows,schema=pa.schema(fields)),
                       self.source)
        self.record={"sha":S.M.ST.sha(self.source),
                     "rows":1,"size":self.source.stat().st_size}

    def source_reader(self,root,year,readme_sha,manifest_sha):
        self.assertEqual(Path(root),self.vendor)
        self.assertIn(year,S.YEARS)
        self.mocked_purchased_calls.append(year)
        return self.source,self.record,None,None

    def patched(self):
        from contextlib import ExitStack
        stack=ExitStack()
        for obj,name,value in [
            (S.M,"MODULE",self.base),
            (S.M,"WORK",self.work),
            (S.M,"ROOT",self.root),
            (S.M,"REPORTS",self.reports),
            (S.M,"purchased_input",self.source_reader),
            (S,"EXPECTED_OTHER14_ROWS",14),
            (S,"fixed_anchors",lambda *args:self.anchors),
        ]:
            stack.enter_context(patch.object(obj,name,value))
        return stack

    def call_preflight(self):
        return S.preflight(
            self.vendor,self.base/"candidate.json",*self.pins,
            *self.samples,self.pre)

    def test_14_year_preflight_sha_footer_and_anchor_receipts_only(self):
        with self.patched():
            doc=self.call_preflight()
        self.assertEqual(doc["historical_year_files_verified"],14)
        self.assertEqual(doc["purchased_original_rows"],14)
        self.assertEqual(doc["years"],list(S.YEARS))
        self.assertEqual(len(doc["annual"]),14)
        self.assertEqual(sorted(self.mocked_purchased_calls),list(S.YEARS))
        self.assertFalse(doc["physical_parquet_or_sqlite_created"])
        self.assertFalse(doc["ready_for_h5_mirror"])
        self.assertTrue(self.pre.is_file())
        self.assertFalse(self.root.exists())

    def test_14_year_preflight_preserves_one_unknown_original_field(self):
        self.write_source(extra=1)
        with self.patched():
            doc=self.call_preflight()
        self.assertTrue(all(x["unclassified_extra_field_count"]==1
                            for x in doc["annual"].values()))
        self.assertEqual(doc["minimum_extra_column_original_shadow_bytes"],
                         14*self.source.stat().st_size)

    def test_14_year_preflight_rejects_two_unknown_fields_before_safe(self):
        self.write_source(extra=2)
        with self.patched():
            with self.assertRaisesRegex(ValueError,"unsupported"):
                self.call_preflight()
        self.assertFalse(self.pre.exists())

    def test_14_year_preflight_rejects_missing_or_wrong_required_type(self):
        for missing,wrong in [(True,False),(False,True)]:
            with self.subTest(missing=missing,wrong=wrong):
                self.write_source(missing=missing,int_volume=wrong)
                with self.patched():
                    with self.assertRaisesRegex(ValueError,"unsupported"):
                        self.call_preflight()
                self.assertFalse(self.pre.exists())

    def test_14_year_preflight_fails_when_annual_bundle_count_drifted(self):
        with self.patched():
            with patch.object(S,"EXPECTED_OTHER14_ROWS",15):
                with self.assertRaisesRegex(ValueError,"24-file inventory"):
                    self.call_preflight()
        self.assertFalse(self.pre.exists())

    def mocked_build(self,year,root,candidate,readme,manifest,folder,gate,out):
        self.made_years.append(year)
        folder=Path(folder)
        folder.mkdir(parents=True,exist_ok=False)
        Path(gate).write_text('{"kind":"scope"}\n')
        doc={
            "status":"private_purchased_historical_day_physical_year_not_activated",
            "year":year,
            "purchased_original_rows":1,
            "total_private_physical_rows":1,
            "h5_mixed_candidate_rows":0,
            "unclassified_purchased_extra_field_count":self.extra,
            "source_purchased_original_parquet_sha256":self.record["sha"],
            "source_candidate_safe_sha256":"c"*64,
            "private_relative_directory":folder.relative_to(self.base).as_posix(),
            "private_manifest_sha256":"d"*64,
            "candidate_source_units_certified":False,
            "ready_for_production_query":False,
            "ready_for_automatic_market_merge":False,
            "ready_for_h5_mirror":False,
            "original_market_files_written":False,
            "private_or_production_active_pointer_modified":False,
        }
        Path(out).write_text(json.dumps(doc)+"\n",encoding="utf-8")
        return doc

    def mocked_audit(self,source,out):
        d=json.loads(Path(source).read_text(encoding="utf-8"))
        self.audited_years.append(d["year"])
        result={
            "status":"independent_historical_private_physical_year_all_rows_sha_and_keys_verified",
            "year":d["year"],
            "private_purchased_rows_verified":1,
            "private_h5_mixed_candidate_rows_verified":0,
            "private_total_rows_verified":1,
            "private_unclassified_purchased_extra_field_count_verified":self.extra,
            "source_materialization_safe_sha256":S.M.ST.sha(Path(source)),
            "source_private_manifest_sha256":"d"*64,
            "candidate_source_units_certified":False,
            "ready_for_production_query":False,
            "ready_for_automatic_market_merge":False,
            "ready_for_h5_mirror":False,
            "original_market_files_written":False,
            "private_or_production_active_pointer_modified":False,
        }
        Path(out).write_text(json.dumps(result)+"\n",encoding="utf-8")
        return result

    def call_stage(self,sha,run_id="123456789abc"):
        return S.stage(self.vendor,self.base/"candidate.json",*self.pins,
                       *self.samples,self.pre,sha,run_id,self.output)

    def test_14_year_stage_stops_only_after_all_independent_audits(self):
        with self.patched():
            self.call_preflight()
            sha=S.M.ST.sha(self.pre)
            with patch.object(S.M,"materialize",side_effect=self.mocked_build),\
                 patch.object(S.I,"verify",side_effect=self.mocked_audit):
                result=self.call_stage(sha)
        self.assertEqual(self.made_years,list(S.YEARS))
        self.assertEqual(self.audited_years,list(S.YEARS))
        self.assertNotIn(2016,self.made_years)
        self.assertNotIn(2026,self.made_years)
        self.assertEqual(result["year_count"],14)
        self.assertEqual(result["historical_purchased_rows_verified"],14)
        self.assertTrue(result["all_years_independent_full_row_sha_and_key_verified"])
        self.assertTrue(self.output.exists())
        self.assertFalse(result["ready_for_automatic_market_merge"])

    def test_14_year_stage_refuses_tampered_preflight_sha_before_writes(self):
        with self.patched():
            self.call_preflight()
            with self.assertRaisesRegex(ValueError,"not trusted"):
                self.call_stage("0"*64)
        self.assertEqual(self.made_years,[])
        self.assertFalse(self.output.exists())

    def test_14_year_stage_fails_closed_if_independent_year_audit_fails(self):
        with self.patched():
            self.call_preflight()
            sha=S.M.ST.sha(self.pre)
            def rejected_audit(source,out):
                if len(self.audited_years)==3:
                    raise ValueError("synthetic independent failure")
                return self.mocked_audit(source,out)
            with patch.object(S.M,"materialize",side_effect=self.mocked_build),\
                 patch.object(S.I,"verify",side_effect=rejected_audit):
                with self.assertRaisesRegex(ValueError,"synthetic independent failure"):
                    self.call_stage(sha)
        self.assertEqual(len(self.made_years),4)
        self.assertEqual(len(self.audited_years),3)
        self.assertFalse(self.output.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
