"""Synthetic-only A/B tests; never read or save licensed OHLCVA."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

HERE=Path(__file__).resolve().parents[1]/"tools"

def local_module(filename,name):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

M=local_module("benchmark-parquet-exact-rowgroup-reuse.py","parquet_rg_reuse_test")
PLANNER=local_module("plan-parquet-5min-exact-rowgroups.py","parquet_rg_planner_test")
TZ=timezone(timedelta(hours=8))


def stamp(st):
    return int(datetime.strptime(st,"%Y-%m-%d %H:%M").replace(
        tzinfo=TZ).timestamp()*1000)


class ExactRowGroupReuseABTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home=Path(tmp.name)
        self.root=self.home/"purchased synthetic with spaces"
        (self.root/"AllCycleAStockData").mkdir(parents=True)

    def bar(self,stamp_text,sym="600000.XSHG",close=10.5):
        return {
            "ts":stamp(stamp_text),"symbol":sym,
            "open":10.0,"high":11.0,"low":9.0,"close":close,
            "volume":10.0,"amount":100.0,
        }

    def write(self,rows,group_size=2):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
            import pyarrow.dataset
        except ImportError:
            self.skipTest("pyarrow unavailable")
        dest=self.root/"AllCycleAStockData"/"5min"/"2026-09.parquet"
        dest.parent.mkdir(parents=True,exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows),str(dest),
                       row_group_size=group_size)
        return dest

    def fixture(self):
        self.write([
            # Footer symbol min/max includes 600000 in this group, although
            # no real SH600000 record is present for the selected day.
            self.bar("2026-09-30 09:30","000001.XSHE"),
            self.bar("2026-09-30 09:35","688999.XSHG"),
            self.bar("2026-09-30 09:30"),
            self.bar("2026-09-30 09:35","000001.XSHE"),
            self.bar("2026-09-30 09:40","000001.XSHE"),
            self.bar("2026-09-30 09:45",close=10.6),
        ],group_size=2)
        return PLANNER.plan(self.root,"SH600000","2026-09-30")

    def run_ab(self,loc,order="full-first",verify=False):
        return M.run(self.root,"SH600000","2026-09-30",
                     loc,order=order,verify_rowgroup=verify)

    def test_real_arrow_two_orders_strict_parity_and_scan_reduction(self):
        locator=self.fixture()
        self.assertEqual(locator["exact_groups_without_target_keys"],1)
        self.assertEqual(locator["exact_groups_containing_target_keys"],2)
        for order in M.ORDERS:
            with self.subTest(order=order):
                report=self.run_ab(locator,order=order,verify=True)
                self.assertEqual(report["matching_bar_count"],2)
                self.assertEqual(report["full_footer_candidate_row_groups"],3)
                self.assertEqual(report["restricted_row_groups_actually_scanned"],2)
                self.assertEqual(report["row_groups_not_read_in_restricted_scan"],1)
                self.assertTrue(report["all_output_ohlcva_time_and_provenance_identical"])
                self.assertTrue(report["legacy_rowgroup_exact_equality_verified_this_run"])
                self.assertTrue(report["net_end_to_end_speedup_including_locator_creation_not_proven"])
                self.assertFalse(report["paid_ohlcva_exported"])
                self.assertEqual(len(report["source_stat_manifest_sha256"]),64)
                blob=json.dumps(report)
                for key in ('"open":','"close":','"volume":','"amount":'):
                    self.assertNotIn(key,blob)

    def test_wrong_or_missing_locator_identity_and_census_rejected(self):
        locator=self.fixture()
        altered=dict(locator,symbol="SZ000001")
        with self.assertRaisesRegex(ValueError,"identity"):
            self.run_ab(altered)
        altered=dict(locator,candidate_row_groups=2)
        with self.assertRaisesRegex(ValueError,"census"):
            self.run_ab(altered)
        altered=dict(locator,two_key_columns_source_rows_examined=1)
        with self.assertRaisesRegex(ValueError,"census"):
            self.run_ab(altered)
        altered=dict(locator,ALL_footer_candidate_groups_key_columns_scanned=False)
        with self.assertRaisesRegex(ValueError,"full-scan"):
            self.run_ab(altered)

    def test_bad_counts_foreign_groups_and_modified_manifest_rejected(self):
        locator=self.fixture()
        altered=dict(locator,source_stat_manifest_sha256="0"*64)
        with self.assertRaisesRegex(ValueError,"stale or mismatched"):
            self.run_ab(altered)
        altered=dict(locator,matching_source_keys=500)
        with self.assertRaisesRegex(ValueError,"conserve"):
            self.run_ab(altered)
        altered=dict(locator,nonempty_source_row_group_locators=[
            dict(locator["nonempty_source_row_group_locators"][0],
                 row_group=999),
            locator["nonempty_source_row_group_locators"][1],
        ])
        with self.assertRaisesRegex(ValueError,"foreign"):
            self.run_ab(altered)

    def test_tampered_membership_that_keeps_total_counts_fails_full_parity(self):
        locator=self.fixture()
        # Fabricated second locator with the same total count and plausible
        # foreign-free RowGroup membership, but a true source group omitted.
        entries=locator["nonempty_source_row_group_locators"]
        altered=dict(locator,nonempty_source_row_group_locators=[
            dict(entries[0],matching_key_count=2)])
        altered["exact_groups_containing_target_keys"]=1
        altered["exact_groups_without_target_keys"]=2
        altered["possible_row_groups_to_omit_if_sources_unchanged"]=2
        with self.assertRaisesRegex(ValueError,"differs in OHLCVA"):
            self.run_ab(altered)

    def test_source_stat_changes_during_ab_rejected(self):
        locator=self.fixture()
        original=M.query.private_cache.source_signature
        calls=[0]
        def source_changed(*args,**kwargs):
            result=original(*args,**kwargs)
            calls[0]+=1
            if calls[0]==2:
                result=dict(result)
                result["manifest_sha256_stat_only"]="0"*64
            return result
        with mock.patch.object(M.query.private_cache,"source_signature",
                               side_effect=source_changed):
            with self.assertRaisesRegex(ValueError,"manifest changed"):
                self.run_ab(locator)

    def test_original_candidate_budget_enforced_even_after_restriction(self):
        locator=self.fixture()
        with self.assertRaisesRegex(ValueError,"--max-candidate-rows"):
            M.run(self.root,"SH600000","2026-09-30",locator,
                  max_candidate_rows=1)

    def test_cli_safe_report_and_no_overwrite_or_path_escape(self):
        locator=self.fixture()
        module=self.home/"H5ParquetReconciler"
        reports=module/"reports"
        reports.mkdir(parents=True)
        input_file=reports/"locator.json"
        input_file.write_text(json.dumps(locator),encoding="utf-8")
        with (mock.patch.object(M,"MODULE",module),
              mock.patch.object(M,"REPORTS",reports.resolve()),
              mock.patch.object(M.query.core,"resolve_module_artifact_paths",
                                side_effect=lambda out:(
                                    (module/"reports"/"out.json").resolve(),
                                    (module/"work"/"_union_scratch").resolve())),
              mock.patch.object(M.query.core,"resolve_safe_paths",
                                side_effect=lambda root,out,scratch:(
                                    self.root.resolve(),out,scratch))):
            with redirect_stdout(StringIO()):
                M.main([str(self.root),"--symbol","SH600000",
                        "--date","2026-09-30",
                        "--locator-report","reports/locator.json",
                        "--read-only","--out","reports/out.json",
                        "--verify-rowgroup"])
            summary=json.loads((reports/"out.json").read_text())
            self.assertEqual(summary["matching_bar_count"],2)
            self.assertTrue(summary["legacy_rowgroup_exact_equality_verified_this_run"])
            self.assertNotIn('"open":',json.dumps(summary))
            with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
                M.main([str(self.root),"--symbol","SH600000",
                        "--date","2026-09-30",
                        "--locator-report","reports/locator.json",
                        "--read-only","--out","reports/out.json"])
            with self.assertRaisesRegex(ValueError,"Only JSON"):
                M.report_path(self.home/"escape.json")


if __name__=="__main__":
    unittest.main()
