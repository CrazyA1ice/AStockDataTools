"""Pure synthetic, no Parquet reads: reversed-order exact RG report audit."""
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

TOOLS=Path(__file__).resolve().parents[1]/"tools"
SPEC=importlib.util.spec_from_file_location(
    "offline_rg_audit_tests",TOOLS/"audit-parquet-exact-rowgroup-ab.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def report(order):
    full,restricted=((2.58,0.48) if order=="full-first" else (1.00,0.53))
    return {
        "format":"AStockDataTools exact 5min RowGroup reuse A/B v1",
        "symbol":"SH600000","date":"2026-09-30","period":"5min",
        "requested_execution_order":order,"matching_bar_count":48,
        "full_arrow_seconds":full,
        "restricted_arrow_seconds":restricted,
        "full_over_restricted_ratio":round(full/restricted,6),
        "full_footer_candidate_row_groups":47,
        "restricted_row_groups_actually_scanned":18,
        "row_groups_not_read_in_restricted_scan":29,
        "original_preflight_rows_upper_bound":5685792,
        "restricted_rowgroup_source_rows_upper_bound":2213909,
        "key_only_locator_build_seconds_from_prior_report":2.361006,
        "locator_build_cost_not_included_in_engine_comparison":True,
        "source_stat_manifest_sha256":"7"*64,
        "source_stat_manifest_file_count":9,
        "source_stat_only_not_content_hash":True,
        "source_stat_stable_during_comparison":True,
        "all_output_ohlcva_time_and_provenance_identical":True,
        "locator_key_count_and_group_membership_crosschecked_with_full_source":True,
        "legacy_rowgroup_exact_equality_verified_this_run":True,
        "legacy_rowgroup_seconds_if_verified":1.7,
        "total_wall_seconds_including_all_parity_scans":5.0,
        "net_end_to_end_speedup_including_locator_creation_not_proven":True,
        "physical_parquet_io_saved_unknown":True,
        "not_production_pruning":True,
        "local_private_cache_not_used":True,
        "paid_ohlcva_exported":False,
        "h5_source_accessed":False,
        "source_market_files_modified":False,
        "automatic_source_union_or_import_performed":False,
    }


class ExactRGOfflineABTests(unittest.TestCase):
    def test_equal_source_and_both_orders_infer_only_scenario_payback(self):
        result=M.compare(report("full-first"),report("restricted-first"))
        self.assertEqual(result["observation"],"restricted_faster_both_orders")
        self.assertEqual(result["simple_break_even_query_count_range_if_both_faster"],
                         [2,6])
        self.assertTrue(result["break_even_is_scenario_only_not_realized_savings"])
        self.assertFalse(result["paid_ohlcva_or_private_cache_exported"])
        data=json.dumps(result)
        self.assertNotIn('"open":',data)
        self.assertNotIn('"volume":',data)

    def test_stat_date_or_row_count_changes_rejected(self):
        first,other=report("full-first"),report("restricted-first")
        for field,value in (
            ("source_stat_manifest_sha256","a"*64),
            ("date","2026-08-30"),
            ("matching_bar_count",47),
            ("restricted_rowgroup_source_rows_upper_bound",12345),
        ):
            changed=dict(other,**{field:value})
            with self.subTest(field=field),self.assertRaisesRegex(
                    ValueError,"differ"):
                M.compare(first,changed)

    def test_tampered_identity_census_and_safety_flags_rejected(self):
        first,second=report("full-first"),report("restricted-first")
        for field,value in (
            ("requested_execution_order","full-first"),
            ("all_output_ohlcva_time_and_provenance_identical",False),
            ("legacy_rowgroup_exact_equality_verified_this_run",False),
            ("paid_ohlcva_exported",True),
            ("restricted_row_groups_actually_scanned",200),
            ("full_over_restricted_ratio",500.0),
        ):
            altered=dict(second,**{field:value})
            with self.subTest(field=field),self.assertRaises(ValueError):
                M.compare(first,altered)

    def test_not_faster_does_not_fabricate_payback(self):
        a,b=report("full-first"),report("restricted-first")
        b["restricted_arrow_seconds"]=1.3
        b["full_over_restricted_ratio"]=round(b["full_arrow_seconds"]/1.3,6)
        result=M.compare(a,b)
        self.assertEqual(result["observation"],"not_faster_both_orders")
        self.assertIsNone(result["simple_break_even_query_count_range_if_both_faster"])
        self.assertIsNone(result["per_order_measurements"][1][
            "simple_build_cost_break_even_query_count"])

    def test_invalid_float_bool_counts_are_not_accepted(self):
        a,b=report("full-first"),report("restricted-first")
        for field,value in (
            ("full_arrow_seconds",float("nan")),
            ("restricted_arrow_seconds",0),
            ("source_stat_manifest_file_count",True),
            ("key_only_locator_build_seconds_from_prior_report",float("inf")),
        ):
            altered=dict(a,**{field:value})
            with self.subTest(field=field),self.assertRaises(ValueError):
                M.compare(altered,b)

    def test_cli_safe_json_reports_only_and_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"H5ParquetReconciler"
            reports=root/"reports"
            reports.mkdir(parents=True)
            (reports/"full.json").write_text(
                json.dumps(report("full-first")),encoding="utf-8")
            (reports/"restricted.json").write_text(
                json.dumps(report("restricted-first")),encoding="utf-8")
            with (mock.patch.object(M.v,"MODULE",root),
                  mock.patch.object(M.v,"REPORTS",reports.resolve())):
                args=["--full-first","reports/full.json",
                      "--restricted-first","reports/restricted.json",
                      "--out","reports/audit.json","--read-only"]
                with redirect_stdout(StringIO()):
                    M.main(args)
                saved=json.loads((reports/"audit.json").read_text())
                self.assertEqual(saved["observation"],
                                 "restricted_faster_both_orders")
                with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
                    M.main(args)
                (reports/"corrupt.json").write_text(
                    json.dumps(report("full-first")).replace('"full_arrow_seconds": 2.58',
                                                              '"full_arrow_seconds": NaN'),
                    encoding="utf-8")
                with self.assertRaisesRegex(ValueError,"NaN"):
                    M.read_report("reports/corrupt.json")


if __name__=="__main__":
    unittest.main()
