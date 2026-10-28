"""Pure in-memory synthetic test of month key evidence audit; zero market IO."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

TOOLS=Path(__file__).resolve().parents[1]/"tools"
SPEC=importlib.util.spec_from_file_location(
    "parquet_month_key_audit_tests",TOOLS/"audit-parquet-month-shared-key-report.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SOURCE="AllCycleAStockData/5min/2026-09.parquet"


def item(group,count):
    return {"source_file_relative_path":SOURCE,
            "row_group":group,"matching_key_count":count}


def fixture():
    return {
        "format":M.MONTH_FORMAT,
        "period":"5min","from_date":"2026-09-29","to_date":"2026-09-30",
        "requested_calendar_days":2,"requested_distinct_symbol_count":2,
        "requested_symbol_day_count":4,
        "per_symbol":[
            {"symbol":"SH600000",
             "independent_footer_candidate_row_groups":3,
             "independent_footer_candidate_source_rows_upper_bound":20,
             "matching_source_keys_all_days":4},
            {"symbol":"SZ000001",
             "independent_footer_candidate_row_groups":3,
             "independent_footer_candidate_source_rows_upper_bound":20,
             "matching_source_keys_all_days":1},
        ],
        "per_symbol_day":[
            {"symbol":"SH600000","date":"2026-09-29",
             "matching_source_keys":2,"exact_row_groups_containing_keys":1,
             "nonempty_row_group_locators":[item(0,2)]},
            {"symbol":"SH600000","date":"2026-09-30",
             "matching_source_keys":2,"exact_row_groups_containing_keys":1,
             "nonempty_row_group_locators":[item(1,2)]},
            {"symbol":"SZ000001","date":"2026-09-29",
             "matching_source_keys":0,"exact_row_groups_containing_keys":0,
             "nonempty_row_group_locators":[]},
            {"symbol":"SZ000001","date":"2026-09-30",
             "matching_source_keys":1,"exact_row_groups_containing_keys":1,
             "nonempty_row_group_locators":[item(2,1)]},
        ],
        "matching_keys_all_stock_days":5,
        "union_footer_candidate_row_groups":3,
        "union_footer_candidate_source_rows_upper_bound":20,
        "union_source_key_rows_examined_once":20,
        "sum_of_independent_symbol_footer_row_upper_bounds":40,
        "theoretical_rows_avoided_vs_independent_symbol_scans":20,
        "source_file_footers_opened_once":1,
        "source_stat_manifest_sha256":"a"*64,
        "source_stat_manifest_file_count":1,
        "source_stat_manifest_stable_during_scan":True,
        "source_manifest_stat_only_not_content_sha256":True,
        "all_union_footer_candidate_groups_key_columns_scanned":True,
        "only_ts_and_symbol_columns_read":True,
        "all_parquet_readers_explicitly_closed":True,
        "one_pass_key_scan_seconds":1.25,
        "whole_planning_seconds":2.5,
        "physical_disk_bytes_read_or_saved_unknown":True,
        "net_end_to_end_query_speedup_not_measured":True,
        "locator_unsigned_not_trusted_for_production":True,
        "production_default_engine_unchanged":True,
        "no_raw_ohlcva_or_individual_intraday_time_keys_exported":True,
        "no_h5_read":True,"source_market_files_modified":False,
        "automatic_source_union_or_import_performed":False,
    }


def day_ref():
    return {
        "format":M.DAY_FORMAT,"date":"2026-09-30","period":"5min",
        "source_stat_manifest_sha256":"a"*64,
        "source_stat_manifest_file_count":1,
        "per_symbol":[
            {"symbol":"SH600000","matching_source_keys":2,
             "exact_row_groups_containing_keys":1,
             "nonempty_row_group_locators":[item(1,2)]},
            {"symbol":"SZ000001","matching_source_keys":1,
             "exact_row_groups_containing_keys":1,
             "nonempty_row_group_locators":[item(2,1)]},
        ],
    }


class OfflineMonthlyKeyEvidenceTests(unittest.TestCase):
    def test_summarizes_coverage_without_source_data_or_original_times(self):
        result=M.audit(fixture(),day_ref())
        self.assertEqual(result["matching_keys_all_stock_days"],5)
        self.assertEqual(result["number_of_stock_days"],4)
        self.assertEqual(result["month_unique_row_groups_with_any_selected_keys"],3)
        self.assertEqual(result["total_row_group_locator_entries"],3)
        self.assertEqual(result["reference_day_if_verified"],"2026-09-30")
        self.assertTrue(result["single_day_reference_exact_membership_verified"])
        self.assertFalse(result["all_stocks_share_same_zero_key_dates"])
        stock=result["per_stock"][1]
        self.assertEqual(stock["zero_key_dates"],["2026-09-29"])
        self.assertEqual(stock["total_matching_keys"],1)
        self.assertEqual(stock["unique_row_groups_with_keys_across_month"],1)
        self.assertEqual(result["original_month_plan_wall_seconds"],2.5)
        blob=json.dumps(result)
        for sensitive in ('"open":','"close":','"amount":','"volume":',
                          '"source_timestamp_ms":','"nonempty_row_group_locators":'):
            self.assertNotIn(sensitive,blob)
        self.assertFalse(result["source_market_files_accessed_by_this_audit"])

    def test_reject_tampered_census_duplicate_and_data_leak_flags(self):
        for mutate in (
            lambda x:x.update(matching_keys_all_stock_days=999),
            lambda x:x.update(union_source_key_rows_examined_once=19),
            lambda x:x.update(requested_symbol_day_count=3),
            lambda x:x["per_symbol_day"].pop(),
            lambda x:x["per_symbol_day"][0].update(
                matching_source_keys=3),
            lambda x:x["per_symbol_day"][0].update(
                nonempty_row_group_locators=[item(0,1),item(0,1)],
                matching_source_keys=2,exact_row_groups_containing_keys=2),
            lambda x:x.update(only_ts_and_symbol_columns_read=False),
            lambda x:x.update(source_stat_manifest_sha256="x"*64),
            lambda x:x.update(one_pass_key_scan_seconds=float("nan")),
            lambda x:x["per_symbol_day"][0]["nonempty_row_group_locators"][0].update(
                source_file_relative_path="AllCycleAStockData/5min/../other.parquet"),
        ):
            # Deep copy isolates each intentional corruption.
            changed=json.loads(json.dumps(fixture()))
            mutate(changed)
            with self.subTest(mutate=repr(mutate)),self.assertRaises(ValueError):
                M.audit(changed)

    def test_real_producer_flag_polarities_and_negative_cases(self):
        # Match the actual plan-parquet-5min-multiday-shared-keys.py
        # producer: no_h5_read=True while actions performed=False.
        source=fixture()
        self.assertIs(source["no_h5_read"],True)
        self.assertIs(source["source_market_files_modified"],False)
        self.assertIs(source["automatic_source_union_or_import_performed"],False)
        self.assertEqual(M.audit(source)["matching_keys_all_stock_days"],5)
        # False/missing/1 must not be accepted as proof that H5 was untouched.
        for value in (False,None,1,"true"):
            altered=json.loads(json.dumps(source))
            if value is None:
                altered.pop("no_h5_read")
            else:
                altered["no_h5_read"]=value
            with self.subTest(value=value),self.assertRaisesRegex(
                    ValueError,"no_h5_read=true"):
                M.audit(altered)
        # Action flags have the inverse polarity: they must stay exactly False.
        for name in ("source_market_files_modified",
                     "automatic_source_union_or_import_performed"):
            for value in (True,None,0):
                altered=json.loads(json.dumps(source))
                if value is None:
                    altered.pop(name)
                else:
                    altered[name]=value
                with self.subTest(flag=name,value=value),self.assertRaisesRegex(
                        ValueError,"Unexpected source modification or import"):
                    M.audit(altered)

    def test_reference_catches_mismatched_group_membership_or_manifest(self):
        report=fixture()
        wrong=day_ref()
        wrong["per_symbol"][0]["nonempty_row_group_locators"][0]["row_group"]=0
        with self.assertRaisesRegex(ValueError,"locator mismatch"):
            M.audit(report,wrong)
        bad=day_ref()
        bad["source_stat_manifest_sha256"]="b"*64
        with self.assertRaisesRegex(ValueError,"stat mismatch"):
            M.audit(report,bad)
        bad=day_ref()
        bad["date"]="2026-08-30"
        with self.assertRaisesRegex(ValueError,"outside month"):
            M.audit(report,bad)

    def test_reject_invalid_window_or_stock_population(self):
        for key,value in (("from_date","2026-08-29"),
                          ("to_date","2026-10-01"),
                          ("period","1min"),
                          ("requested_calendar_days",3)):
            changed=fixture()
            changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                M.audit(changed)

    def test_cli_offline_json_and_refuses_overwrite_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            module=Path(temp)/"H5ParquetReconciler"
            reports=module/"reports"
            reports.mkdir(parents=True)
            (reports/"monthly.json").write_text(
                json.dumps(fixture()),encoding="utf-8")
            (reports/"day.json").write_text(
                json.dumps(day_ref()),encoding="utf-8")
            args=["--month-report","reports/monthly.json",
                  "--single-day-report","reports/day.json",
                  "--read-only","--out","reports/audit.json"]
            with mock.patch.object(M,"MODULE",module),mock.patch.object(
                    M,"REPORTS",reports.resolve()):
                with redirect_stdout(StringIO()):
                    M.main(args)
                audited=json.loads((reports/"audit.json").read_text())
                self.assertTrue(
                    audited["single_day_reference_exact_membership_verified"])
                with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
                    M.main(args)
                with self.assertRaisesRegex(ValueError,"Only JSON"):
                    M.located_report(Path(temp)/"escape.json")
                (reports/"nan.json").write_text(
                    '{"a": NaN}',encoding="utf-8")
                with self.assertRaisesRegex(ValueError,"Nonfinite"):
                    M.read_json("reports/nan.json")


if __name__=="__main__":
    unittest.main()
