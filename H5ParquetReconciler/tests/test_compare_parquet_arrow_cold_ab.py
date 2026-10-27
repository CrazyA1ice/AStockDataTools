"""Purely synthetic reversal audit tests; never access paid H5/Parquet or SQLite."""
import copy
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

SCRIPT = (Path(__file__).resolve().parents[1] / "tools" /
          "compare-parquet-arrow-cold-ab.py")
SPEC = importlib.util.spec_from_file_location("cold_query_ab_reversed_audit", SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def report(order="rowgroup-first", old=3.5, arrow=2.0):
    return {
        "format": M.FORMAT,
        "symbol": "SH600000", "period": "5min",
        "from_date": "2026-09-30", "to_date": "2026-09-30",
        "requested_execution_order": order,
        "source_stat_manifest_sha256": "a" * 64,
        "source_stat_manifest_file_count": 9,
        "matching_bar_count": 48,
        "candidate_row_groups": 47,
        "candidate_source_rows_upper_bound": 5685792,
        "baseline_existing_rowgroup": {
            "elapsed_seconds": old,
            "source_rows_delivered_to_python_before_filter": 5685792,
            "source_file_footers_opened": 9,
        },
        "experimental_arrow_filtered": {
            "elapsed_seconds": arrow,
            "arrow_rows_emitted_after_predicate": 48,
            "row_groups_that_emitted_filtered_rows": 47,
            "row_group_upper_bound_still": 5685792,
            "actual_parquet_rows_decoded_unknown": True,
            "actual_disk_bytes_read_unknown": True,
        },
        **{k: True for k in M.TRUE_FLAGS},
        **{k: False for k in M.FALSE_FLAGS},
    }


class ReversedOrderAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module = Path(self.tmp.name) / "H5ParquetReconciler"
        self.reports = self.module / "reports"
        self.reports.mkdir(parents=True)
        p1 = mock.patch.object(M, "MODULE", self.module)
        p2 = mock.patch.object(M, "REPORTS", self.reports.resolve())
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def write(self, name, value):
        path = self.reports / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_arrow_faster_both_orders_and_important_caveats(self):
        outcome = M.compare(report(), report("arrow-first", old=3.7, arrow=2.3))
        self.assertEqual(outcome["preliminary_timing_observation"],
                         "arrow_faster_in_both_orders")
        self.assertEqual(outcome["matching_bar_count"], 48)
        self.assertTrue(outcome["source_content_identity_between_runs_not_proven"])
        self.assertTrue(outcome["same_source_stat_manifest_in_both_runs_verified"])
        self.assertTrue(outcome["two_single_runs_insufficient_to_enable_arrow_in_production"])
        self.assertFalse(outcome["cache_or_paid_market_data_exported"])
        self.assertGreater(outcome["weakest_observed_baseline_over_arrow_ratio"], 1)

    def test_baseline_wins_both_orders(self):
        outcome = M.compare(report(old=1.0, arrow=2.0),
                            report("arrow-first", old=1.5, arrow=2.5))
        self.assertEqual(outcome["preliminary_timing_observation"],
                         "baseline_faster_in_both_orders")

    def test_order_sensitive_or_equal_is_not_misreported(self):
        outcome = M.compare(report(old=1.0, arrow=2.0),
                            report("arrow-first", old=2.0, arrow=1.0))
        self.assertEqual(outcome["preliminary_timing_observation"],
                         "mixed_or_equal_order_sensitive")
        outcome = M.compare(report(old=1.0, arrow=1.0),
                            report("arrow-first", old=2.0, arrow=1.0))
        self.assertEqual(outcome["preliminary_timing_observation"],
                         "mixed_or_equal_order_sensitive")

    def test_wrong_order_rejected(self):
        with self.assertRaisesRegex(ValueError, "exactly one report"):
            M.compare(report(), report())

    def test_cross_run_query_identity_mismatch_rejected(self):
        other = report("arrow-first")
        other["from_date"] = "2026-09-29"
        with self.assertRaisesRegex(ValueError, "Mismatched query"):
            M.compare(report(), other)

    def test_cross_run_source_and_arrow_census_mismatch_rejected(self):
        other = report("arrow-first")
        other["baseline_existing_rowgroup"]["source_rows_delivered_to_python_before_filter"] -= 1
        with self.assertRaisesRegex(ValueError, "Different baseline source census"):
            M.compare(report(), other)
        other = report("arrow-first")
        other["experimental_arrow_filtered"]["arrow_rows_emitted_after_predicate"] += 1
        with self.assertRaisesRegex(ValueError, "Different Arrow output census"):
            M.compare(report(), other)

    def test_changed_source_stat_fingerprint_rejected(self):
        other = report("arrow-first")
        other["source_stat_manifest_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "Source stat manifest differs"):
            M.compare(report(), other)
        other = report("arrow-first")
        other["source_stat_manifest_sha256"] = "unverified"
        with self.assertRaisesRegex(ValueError, "Malformed|malformed"):
            M.compare(report(), other)

    def test_missing_equality_or_privacy_assertion_rejected(self):
        other = report("arrow-first")
        other["query_output_all_values_times_and_source_provenance_identical"] = False
        with self.assertRaisesRegex(ValueError, "safe benchmark assertion"):
            M.compare(report(), other)
        other = report("arrow-first")
        other["local_private_ohlcva_cache_not_used"] = False
        with self.assertRaisesRegex(ValueError, "safe benchmark assertion"):
            M.compare(report(), other)
        other = report("arrow-first")
        other["raw_ohlcva_exported"] = True
        with self.assertRaisesRegex(ValueError, "Unsafe or incomplete"):
            M.compare(report(), other)

    def test_nonfinite_zero_or_boolean_timing_rejected(self):
        for bad in (0.0, -1.0, float("nan"), float("inf"), True, "0.2"):
            other = report("arrow-first", arrow=bad)
            with self.subTest(value=str(bad)), self.assertRaisesRegex(
                    ValueError, "positive finite duration"):
                M.compare(report(), other)

    def test_malformed_counts_and_physical_decode_claims_rejected(self):
        other = report("arrow-first")
        other["matching_bar_count"] = 47
        with self.assertRaisesRegex(ValueError, "Mismatched query"):
            M.compare(report(), other)
        other = report("arrow-first")
        other["experimental_arrow_filtered"]["actual_disk_bytes_read_unknown"] = False
        with self.assertRaisesRegex(ValueError, "disk bytes"):
            M.compare(report(), other)
        other = report("arrow-first")
        other["candidate_row_groups"] = True
        with self.assertRaisesRegex(ValueError, "nonnegative integer"):
            M.compare(report(), other)
        other = report("arrow-first")
        other["candidate_source_rows_upper_bound"] = 2
        # The first guard catches inconsistent bounds between the two engines.
        with self.assertRaisesRegex(ValueError, "Candidate RowGroup bound differs"):
            M.compare(report(), other)
        # With engine bounds internally consistent, the next guard catches
        # any scan that exceeds the reported preflight upper bound.
        other["experimental_arrow_filtered"]["row_group_upper_bound_still"] = 2
        with self.assertRaisesRegex(ValueError, "preflight bound"):
            M.compare(report(), other)

    def test_only_module_reports_json_allowed_no_overwrite(self):
        self.write("a.json", report())
        self.assertEqual(M.guarded_path("reports/a.json"), self.reports / "a.json")
        with self.assertRaisesRegex(ValueError, "inside"):
            M.guarded_path(self.module.parent / "secret.json")
        with self.assertRaisesRegex(ValueError, "already exists"):
            M.guarded_path("reports/a.json", is_output=True)
        with self.assertRaisesRegex(ValueError, "end in .json"):
            M.guarded_path("reports/a.txt", is_output=True)
        try:
            (self.reports / "link.json").symlink_to(self.reports / "a.json")
        except (OSError, NotImplementedError):
            pass  # Windows account may not have symlink privilege
        else:
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                M.guarded_path("reports/link.json")

    def test_report_json_size_limit(self):
        path = self.reports / "huge.json"
        path.write_text(" " * 131073, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "128 KiB"):
            M.read_summary(path)

    def test_cli_produces_safe_aggregate_summary_without_licensed_bar_values(self):
        left = report()
        right = report("arrow-first")
        # Untrusted/unrelated extra fields must NOT be copied into output.
        left["paid_bar_close"] = 12345.987654
        self.write("first.json", left)
        self.write("reverse.json", right)
        with redirect_stdout(StringIO()):
            M.main([
                "--rowgroup-first", "reports/first.json",
                "--arrow-first", "reports/reverse.json",
                "--out", "reports/audit.json", "--read-only",
            ])
        output = json.loads((self.reports / "audit.json").read_text(encoding="utf-8"))
        self.assertEqual(output["preliminary_timing_observation"],
                         "arrow_faster_in_both_orders")
        self.assertNotIn("paid_bar_close", json.dumps(output))
        self.assertNotIn("12345.987654", json.dumps(output))
        with self.assertRaises(SystemExit):
            with redirect_stderr(StringIO()):
                M.main([
                    "--rowgroup-first", "reports/first.json",
                    "--arrow-first", "reports/reverse.json",
                    "--out", "reports/audit.json", "--read-only",
                ])


if __name__ == "__main__":
    unittest.main()
