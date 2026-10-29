"""Purely fictional H5 and Parquet: privacy-safe staged crossyear diagnosis."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest import TestCase,main
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

SRC=load("existing_crossyear_synthetic_fixture",
         ROOT/"test_probe_real_h5_parquet_crossyear_day_readonly.py")
D=load("new_crossyear_safe_diagnostic",
       ROOT.parent/"tools"/"diagnose-real-h5-parquet-crossyear-readonly.py")


class CrossyearDiagnosticSyntheticTests(TestCase):
    def setUp(self):
        self.fixture=SRC.CrossyearSyntheticStockDayTests(
            "test_four_crossyear_out_of_sample_stock_days_all_match")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.report=self.fixture.reports/"crossyear-diagnostic-v1.json"
        context=patch.object(D.AUDIT,"REPORTS",self.fixture.reports)
        context.start()
        self.addCleanup(context.stop)

    def diagnose(self):
        obj=self.fixture
        return D.diagnose(obj.pqroot,obj.h5root,
                          obj.raw,obj.native,obj.heldout,self.report)

    def test_valid_fictional_sources_reach_ready_without_exporting_values(self):
        result=self.diagnose()
        self.assertEqual(result["status"],"ready_to_rerun_original_proof")
        self.assertEqual(result["last_stage"],"completed")
        self.assertEqual(result["annual_2025_candidate_rowgroups"],1)
        self.assertEqual(result["annual_2025_footer_rowgroup_count"],12)
        self.assertEqual(result["annual_2025_footer_total_rows"],24)
        self.assertEqual(result["annual_2025_candidate_rows"],2)
        self.assertTrue(result["source_files_stat_or_footer_unchanged"])
        self.assertFalse(result["ready_for_full_market_mirror"])
        txt=self.report.read_text(encoding="utf-8")
        for secret in ("SH600000","SZ000001","HikyuuData",
                       "AllCycleAStockData","202509300000","600000.XSHG"):
            self.assertNotIn(secret,txt)

    def test_missing_year_source_returns_selection_phase_not_false_mutation(self):
        (self.fixture.pqroot/"day"/"2025.parquet").unlink()
        obj=self.diagnose()
        self.assertEqual(obj["status"],"blocked")
        self.assertEqual(obj["last_stage"],"source_file_selection")
        self.assertFalse(obj["source_files_stat_or_footer_unchanged"])

    def test_preceding_hmac_safe_tamper_stops_before_any_source_reads(self):
        original=json.loads(self.fixture.native.read_text(encoding="utf-8"))
        original["all_two_native_h5_real_daily_records_match"]=False
        self.fixture.native.write_text(json.dumps(original),encoding="utf-8")
        obj=self.diagnose()
        self.assertEqual(obj["status"],"blocked")
        self.assertEqual(obj["last_stage"],"prior_safe_chain")
        self.assertEqual(obj["stages_completed"],[])
        self.assertIsNone(obj["annual_2025_footer_total_rows"])

    def test_annual_missing_ts_footer_stats_is_classified_without_row_reads(self):
        file=self.fixture.pqroot/"day"/"2025.parquet"
        table=self.fixture.pq.read_table(file)
        self.fixture.pq.write_table(
            table,file,row_group_size=2,write_statistics=False)
        obj=self.diagnose()
        self.assertEqual(obj["status"],"blocked")
        self.assertEqual(obj["last_stage"],"annual_footer_timestamp_statistics")
        self.assertIsNone(obj["annual_2025_candidate_rowgroups"])
        self.assertTrue(obj["source_files_stat_or_footer_unchanged"])

    def test_target_row_budget_is_distinct_from_rowgroup_count(self):
        with patch.object(D.T,"MAX_YEAR_READ_ROWS",1):
            obj=self.diagnose()
        self.assertEqual(obj["status"],"blocked")
        self.assertEqual(obj["last_stage"],"annual_target_row_budget")
        self.assertEqual(obj["annual_2025_candidate_rowgroups"],1)
        self.assertEqual(obj["annual_2025_candidate_rows"],2)

    def test_annual_selected_day_duplicate_fails_read_stage(self):
        file=self.fixture.pqroot/"day"/"2025.parquet"
        table=self.fixture.pq.read_table(file)
        target_index=next(i for i,ts in enumerate(
            table["ts"].to_pylist())
            if ts==int(__import__("datetime").datetime(
                2025,9,30,tzinfo=__import__("datetime").timezone(
                    __import__("datetime").timedelta(hours=8))
            ).timestamp()*1000))
        self.fixture.pq.write_table(
            self.fixture.pa.concat_tables([
                table,table.slice(target_index,1)]),
            file,row_group_size=2)
        obj=self.diagnose()
        self.assertEqual(obj["status"],"blocked")
        self.assertEqual(obj["last_stage"],"annual_bounded_day_read")
        self.assertEqual(obj["annual_2025_candidate_rowgroups"],2)

    def test_report_is_exclusive_and_within_module(self):
        self.report.write_text("must stay",encoding="utf-8")
        with self.assertRaises(ValueError):
            self.diagnose()
        self.assertEqual(self.report.read_text(encoding="utf-8"),"must stay")
        x=self.fixture.root/"outside.json"
        with self.assertRaises(ValueError):
            D.diagnose(
                self.fixture.pqroot,self.fixture.h5root,
                self.fixture.raw,self.fixture.native,self.fixture.heldout,x)
        self.assertFalse(x.exists())


if __name__=="__main__":
    main(verbosity=2)
