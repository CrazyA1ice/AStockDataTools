"""Synthetic-only, bounded and privacy-preserving anomaly survey tests."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stderr,redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

TOOLS=Path(__file__).resolve().parents[1]/"tools"
SPEC=importlib.util.spec_from_file_location(
    "tdx_pq_boundary_survey_tests",
    TOOLS/"survey-tdx-parquet-minute-rule-boundaries-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def success(matched=True):
    return {
        "preview_verdict":(
            M.SUCCESS if matched else M.MISMATCH),
        "gates":{
            "first_candidate_matches_native":matched,
            "remaining_239_match_native":True,
            "candidate_240_matches_native":matched,
            "candidate_5min_matches_purchased_5min":True,
            "diagnostic_preview_consistent":matched,
        },
        "eligible_for_automatic_production_union":False,
        "original_sources_modified":False,
        "candidate_ohlcva_exported":False,
        "native_source_content_sha256":"a"*64,
        "purchased_source_stat_only_provenance":{
            "1min":{"source_manifest_stat_only_sha256":"b"*64},
            "5min":{"source_manifest_stat_only_sha256":"c"*64},
        },
    }


class BoundarySurveyTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.module=self.root/"H5ParquetReconciler"
        self.module.mkdir()
        (self.module/"reports").mkdir()
        self.purchased=self.root/"purchased"
        self.purchased.mkdir()
        self.vipdoc=self.root/"vipdoc"
        self.vipdoc.mkdir()
        for path,sym in (("sh","sh600000"),("sz","sz300750")):
            folder=self.vipdoc/path/"minline"
            folder.mkdir(parents=True)
            (folder/(sym+".lc1")).write_bytes(b"fake-source-not-read")
        for k,v in (("MODULE",self.module),("REPORTS",self.module/"reports")):
            patch=mock.patch.object(M.probe,k,v)
            patch.start()
            self.addCleanup(patch.stop)

    def test_matching_two_days_uses_version_and_safe_source_hashes(self):
        cases=[("SH600000","2026-09-30"),("SZ300750","2026-08-17")]
        with mock.patch.object(M.preview_mod,"preview",return_value=success()) as called:
            r=M.survey(self.purchased,self.vipdoc,cases,64*1024*1024,10000)
        self.assertEqual(called.call_count,2)
        self.assertEqual(r["candidate_rule_id"],M.RULE_ID)
        self.assertEqual(r["diagnostic_matches"],2)
        self.assertTrue(r["all_requested_samples_match"])
        self.assertFalse(r["production_mapping_certified"])
        self.assertFalse(r["eligible_for_automatic_production_union"])
        self.assertEqual(r["verdict"],
                         "all_requested_cases_diagnostic_match_not_certified")
        self.assertEqual(r["samples"][0]["native_source_content_sha256"],"a"*64)
        self.assertNotIn(str(self.root),json.dumps(r))
        self.assertNotIn("fake-source",json.dumps(r))

    def test_real_disagreement_is_not_silently_marked_success(self):
        with mock.patch.object(M.preview_mod,"preview",return_value=success(False)):
            r=M.survey(self.purchased,self.vipdoc,[("SH600000","2026-09-30")],
                       64*1024*1024,10000)
        self.assertEqual(r["mismatches"],1)
        self.assertEqual(r["diagnostic_matches"],0)
        self.assertEqual(r["samples"][0]["status"],"mismatch")
        self.assertIn("first_candidate_matches_native",r["samples"][0]["failed_gates"])
        self.assertEqual(r["verdict"],"anomaly_observed_do_not_apply_mapping")

    def test_missing_native_source_is_safe_rejection(self):
        with mock.patch.object(M.preview_mod,"preview") as never:
            r=M.survey(self.purchased,self.vipdoc,[("SH600001","2026-09-30")],
                       64*1024*1024,10000)
        never.assert_not_called()
        self.assertEqual(r["unsupported_source_profiles"],1)
        self.assertEqual(r["samples"][0]["reason_category"],"native_source_not_found")

    def test_native_path_symlink_rejected_before_opening(self):
        f=self.vipdoc/"sh"/"minline"/"sh600000.lc1"
        f.unlink()
        try:
            f.symlink_to(self.root/"secret-outside-vipdoc")
        except (OSError,NotImplementedError):
            self.skipTest("File symlinks unavailable on this host")
        with mock.patch.object(M.preview_mod,"preview") as never:
            r=M.survey(self.purchased,self.vipdoc,[("SH600000","2026-09-30")],
                       64*1024*1024,10000)
        never.assert_not_called()
        self.assertEqual(r["samples"][0]["reason_category"],"native_source_path_unsafe")

    def test_incomplete_grid_classified_without_raw_exception_text(self):
        def broken(*args,**kwargs):
            raise ValueError("Parquet 1min requires exactly 241 bars for this explicit opening-label hypothesis at D:\\secret\\licensed")
        with mock.patch.object(M.preview_mod,"preview",side_effect=broken):
            r=M.survey(self.purchased,self.vipdoc,[("SH600000","2026-09-30")],
                       64*1024*1024,10000)
        self.assertEqual(r["samples"][0]["reason_category"],
                         "purchased_minute_grid_unsupported")
        self.assertNotIn("licensed",json.dumps(r))
        self.assertNotIn("secret",json.dumps(r))

    def test_unknown_failure_remains_unclassified_not_auto_pass(self):
        with mock.patch.object(M.preview_mod,"preview",side_effect=ValueError(
                "Unexpected vendor time convention D:\\private\\source")):
            r=M.survey(self.purchased,self.vipdoc,[("SH600000","2026-09-30")],
                       64*1024*1024,10000)
        self.assertEqual(r["samples"][0]["reason_category"],
                         "source_or_validation_error_unclassified")
        # The safe report legitimately contains a key named
        # "no_private_source_paths_in_report". Check the actual simulated
        # sensitive path and exception text, not the generic word "private".
        payload=json.dumps(r)
        self.assertNotIn(json.dumps("D:\\private\\source")[1:-1],payload)
        self.assertNotIn("Unexpected vendor time convention",payload)
        self.assertTrue(r["no_private_source_paths_in_report"])
        self.assertFalse(r["all_requested_samples_match"])

    def test_invalid_cases_duplicate_or_limits_rejected_before_any_read(self):
        cases=[
            [("sh600000","2026-09-30")],
            [("SH600000","2026-09-30"),("SH600000","2026-09-30")],
            [("SH600000","2026-2-3")],
            [("SH600000","2026-02-30")],
            [("SH600000", "2026-09-30")]*13,
        ]
        with mock.patch.object(M.preview_mod,"preview") as never:
            for batch in cases:
                with self.subTest(batch=batch),self.assertRaises(ValueError):
                    M.survey(self.purchased,self.vipdoc,batch,64*1024*1024,10000)
        never.assert_not_called()

    def test_unsafe_budget_fails_before_reading_market(self):
        with mock.patch.object(M.preview_mod,"preview") as never:
            with self.assertRaisesRegex(ValueError,"source byte budget"):
                M.survey(self.purchased,self.vipdoc,[("SH600000","2026-09-30")],999999999,10)
            with self.assertRaisesRegex(ValueError,"scan row budget"):
                M.survey(self.purchased,self.vipdoc,[("SH600000","2026-09-30")],64*1024*1024,0)
        never.assert_not_called()

    def test_cli_writes_new_safe_json_under_reports_only(self):
        cases=["--case","SH600000","2026-09-30"]
        command=["--parquet-root",str(self.purchased),
                 "--tdx-vipdoc",str(self.vipdoc),
                 *cases,"--read-only",
                 "--out","reports/boundary-survey-new.json"]
        with mock.patch.object(M.preview_mod,"preview",return_value=success()):
            with redirect_stdout(StringIO()):
                M.main(command)
        actual=self.module/"reports"/"boundary-survey-new.json"
        d=json.loads(actual.read_text(encoding="utf-8"))
        self.assertEqual(d["diagnostic_matches"],1)
        self.assertFalse(d["production_mapping_certified"])
        self.assertFalse((self.module/"work").exists())
        with mock.patch.object(M.preview_mod,"preview",return_value=success()):
            with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
                M.main(command)


if __name__=="__main__":
    unittest.main()
