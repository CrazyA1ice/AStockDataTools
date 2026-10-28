"""Synthetic paid-data-free tests for explicit indexed 5min query preview."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

TOOLS=Path(__file__).resolve().parents[1]/"tools"


def load(filename,name):
    spec=importlib.util.spec_from_file_location(name,TOOLS/filename)
    o=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(o)
    return o


M=load("query-parquet-exact-locator-preview.py","idx_preview_test")
PLAN=load("plan-parquet-5min-exact-rowgroups.py","idx_preview_planner")
TZ=timezone(timedelta(hours=8))


def ts(stamp):
    return int(datetime.strptime(stamp,"%Y-%m-%d %H:%M").replace(
        tzinfo=TZ).timestamp()*1000)


class ExactLocatorPreviewTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home=Path(temp.name)
        self.root=self.home/"synthetic stock with spaces"
        (self.root/"AllCycleAStockData").mkdir(parents=True)

    def row(self,stamp,symbol="600000.XSHG"):
        return {"ts":ts(stamp),"symbol":symbol,
                "open":10.0,"high":11.0,"low":9.0,"close":10.5,
                "volume":10.0,"amount":100.0}

    def fixture(self):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
            import pyarrow.dataset
        except ImportError:
            self.skipTest("pyarrow unavailable")
        path=self.root/"AllCycleAStockData"/"5min"/"2026-09.parquet"
        path.parent.mkdir(parents=True,exist_ok=True)
        rows=[
            self.row("2026-09-30 09:30","000001.XSHE"),
            self.row("2026-09-30 09:35","688999.XSHG"),
            self.row("2026-09-30 09:30"),
            self.row("2026-09-30 09:35","000001.XSHE"),
            self.row("2026-09-30 09:40","000001.XSHE"),
            self.row("2026-09-30 09:45"),
        ]
        pq.write_table(pa.Table.from_pylist(rows),str(path),row_group_size=2)
        return PLAN.plan(self.root,"SH600000","2026-09-30")

    def test_default_preview_parity_and_safe_summary(self):
        loc=self.fixture()
        result=M.query_bars(self.root,"SH600000","2026-09-30",loc)
        self.assertEqual(len(result["bars"]),2)
        self.assertEqual(result["safe_summary"][
            "full_preflight_candidate_row_groups"],3)
        self.assertEqual(result["safe_summary"][
            "restricted_row_groups_actually_scanned"],2)
        self.assertTrue(result["safe_summary"][
            "full_arrow_equality_checked_this_invocation"])
        self.assertFalse(result["safe_summary"][
            "fast_path_can_silently_omit_bars_if_locator_is_tampered"])
        self.assertFalse(result["safe_summary"]["raw_ohlcva_in_safe_summary"])
        wire=json.dumps(result["safe_summary"])
        self.assertNotIn('"open":',wire)
        self.assertNotIn('"close":',wire)
        self.assertNotIn('"amount":',wire)

    def test_explicit_fast_path_skips_full_query_but_counts_check(self):
        loc=self.fixture()
        original=M.benchmark.arrow_filtered_query
        calls=[]
        def counted(*args,**kwargs):
            calls.append(kwargs.get("allowed_rowgroups"))
            return original(*args,**kwargs)
        with mock.patch.object(M.benchmark,"arrow_filtered_query",
                               side_effect=counted):
            out=M.query_bars(self.root,"SH600000","2026-09-30",
                             loc,fast_stat_only=True)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(calls[0]),2)
        self.assertEqual(out["safe_summary"]["matching_bar_count"],2)
        self.assertFalse(out["safe_summary"][
            "full_arrow_equality_checked_this_invocation"])
        self.assertTrue(out["safe_summary"][
            "fast_path_can_silently_omit_bars_if_locator_is_tampered"])
        self.assertTrue(out["safe_summary"][
            "not_certified_for_unattended_production_pruning"])

    def test_preflight_invoked_only_once_per_query_even_with_full_parity(self):
        loc=self.fixture()
        original=M.query.prepare_query
        for fast in (False,True):
            with self.subTest(fast_stat_only=fast),mock.patch.object(
                    M.query,"prepare_query",wraps=original) as plan:
                result=M.query_bars(
                    self.root,"SH600000","2026-09-30",loc,
                    fast_stat_only=fast)
                self.assertEqual(plan.call_count,1)
                safe=result["safe_summary"]
                self.assertEqual(
                    safe["full_footer_preflight_executions_this_invocation"],1)
                self.assertTrue(
                    safe["prepared_preflight_context_reused_for_arrow_scans"])
                self.assertTrue(
                    safe["arrow_engine_seconds_are_scan_only_in_prepared_mode"])
                self.assertGreaterEqual(safe["full_footer_preflight_seconds"],0)
                self.assertGreaterEqual(safe["source_manifest_before_seconds"],0)
                self.assertGreaterEqual(safe["locator_validation_seconds"],0)
                self.assertEqual(safe["matching_bar_count"],2)
                self.assertEqual(safe["full_arrow_equality_checked_this_invocation"],
                                 not fast)

    def test_prepared_context_rejects_wrong_query_and_budget(self):
        loc=self.fixture()
        ctx=M.query.prepare_query(
            self.root,"SH600000","5min","2026-09-30","2026-09-30")
        original=M.benchmark.arrow_filtered_query
        with self.assertRaisesRegex(ValueError,"context does not match"):
            original(self.root,"SH600000","5min","2026-09-29",
                     "2026-09-29",prepared_context=ctx)
        with self.assertRaisesRegex(ValueError,"budget is invalid"):
            original(self.root,"SH600000","5min","2026-09-30",
                     "2026-09-30",max_candidate_rows=1,
                     prepared_context=ctx)
        with self.assertRaisesRegex(ValueError,"context does not match"):
            original(self.root,"SH600000","5min","2026-09-30",
                     "2026-09-30",max_result_bars=1,prepared_context=ctx)
        # A source-specific cached context must not be mistaken for another
        # file root even if relative file names and group IDs coincide.
        with self.assertRaisesRegex(ValueError,"context does not match"):
            original(self.home,"SH600000","5min","2026-09-30",
                     "2026-09-30",prepared_context=ctx)

    def test_tampered_locator_rejected_in_parity_mode(self):
        loc=self.fixture()
        entries=loc["nonempty_source_row_group_locators"]
        changed=dict(loc,nonempty_source_row_group_locators=[
            dict(entries[0],matching_key_count=2)])
        changed["exact_groups_containing_target_keys"]=1
        changed["exact_groups_without_target_keys"]=2
        changed["possible_row_groups_to_omit_if_sources_unchanged"]=2
        with self.assertRaisesRegex(ValueError,"Locator selected key count"):
            M.query_bars(self.root,"SH600000","2026-09-30",changed)
        # Same result count forged by pointing to a different group fails count
        # or full parity, not a silent successful result.

    def test_stale_manifest_and_smaller_budget_refused(self):
        loc=self.fixture()
        with self.assertRaisesRegex(ValueError,"stale or mismatched"):
            M.query_bars(self.root,"SH600000","2026-09-30",
                         dict(loc,source_stat_manifest_sha256="0"*64))
        with self.assertRaisesRegex(ValueError,"--max-candidate-rows"):
            M.query_bars(self.root,"SH600000","2026-09-30",
                         loc,max_candidate_rows=1)
        with self.assertRaises(ValueError):
            M.query_bars(self.root,"SH600000","2026-09-30",
                         loc,fast_stat_only=1)

    def test_source_stat_mutation_mid_query_refuses_report(self):
        loc=self.fixture()
        original=M.query.private_cache.source_signature
        calls=[0]
        def moved(*args,**kwargs):
            output=original(*args,**kwargs)
            calls[0]+=1
            if calls[0]==2:
                output=dict(output)
                output["manifest_sha256_stat_only"]="0"*64
            return output
        with mock.patch.object(M.query.private_cache,"source_signature",
                               side_effect=moved):
            with self.assertRaisesRegex(ValueError,"manifest changed"):
                M.query_bars(self.root,"SH600000","2026-09-30",loc)

    def test_cli_outputs_safe_only_and_no_overwrite(self):
        loc=self.fixture()
        fake_module=self.home/"H5ParquetReconciler"
        reports=fake_module/"reports"
        reports.mkdir(parents=True)
        (reports/"locator.json").write_text(
            json.dumps(loc),encoding="utf-8")
        with (mock.patch.object(M.gate,"MODULE",fake_module),
              mock.patch.object(M.gate,"REPORTS",reports.resolve()),
              mock.patch.object(M.query.core,"resolve_module_artifact_paths",
                                side_effect=lambda out:(
                                    (fake_module/"reports"/"result.json").resolve(),
                                    (fake_module/"work"/"_union_scratch").resolve())),
              mock.patch.object(M.query.core,"resolve_safe_paths",
                                side_effect=lambda root,out,scratch:(
                                    self.root.resolve(),out,scratch))):
            with redirect_stdout(StringIO()):
                M.main([str(self.root),"--symbol","SH600000",
                        "--date","2026-09-30",
                        "--locator-report","reports/locator.json",
                        "--fast-stat-only","--out","reports/result.json",
                        "--read-only"])
            record=json.loads((reports/"result.json").read_text())
            self.assertTrue(record["fast_path_can_silently_omit_bars_if_locator_is_tampered"])
            self.assertNotIn('"volume":',json.dumps(record))
            with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
                M.main([str(self.root),"--symbol","SH600000",
                        "--date","2026-09-30",
                        "--locator-report","reports/locator.json",
                        "--out","reports/result.json","--read-only"])


if __name__=="__main__":
    unittest.main()
