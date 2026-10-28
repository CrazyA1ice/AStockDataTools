"""Synthetic-only regression for case-level SAFE source-evidence disposition."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location(
    "tdx_pq_case_evidence_gate_tests",
    HERE / "evaluate-tdx-parquet-case-evidence-readonly.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def metrics(n, bad_field=None):
    return {field: {
        "n": n, "within_diagnostic_tolerance": n - int(field == bad_field),
        "max_relative_error": 0.0001 if field == bad_field else 0.0}
        for field in M.FIELDS}


def provenance(period, fingerprint):
    return {"source_manifest_stat_only_sha256": fingerprint * 64,
            "matching_bar_count": {"1min": 241, "5min": 48, "day": 1}[period],
            "source_manifest_is_stat_only_not_content_authenticated": True}


def fixture(parquet_daily_bad=True):
    p = {
        "format": M.PREVIEW_FORMAT, "symbol": "SH600519", "date": "2026-06-30",
        "native_source_content_sha256": "a" * 64,
        "purchased_source_stat_only_provenance": {
            "1min": provenance("1min", "d"), "5min": provenance("5min", "e")},
        "candidate_vs_native_first_minute": metrics(1),
        "candidate_vs_native_full_240": metrics(240, "high"),
        "candidate_vs_native_remaining_239": metrics(239, "high"),
        "candidate_240_to_purchased_48_five_minute": metrics(48),
        "preview_verdict": "diagnostic_candidate_mismatch_do_not_materialize",
        "gates": {"first_candidate_matches_native": True,
                  "remaining_239_match_native": False,
                  "candidate_240_matches_native": False,
                  "candidate_5min_matches_purchased_5min": True,
                  "diagnostic_preview_consistent": False},
        "eligible_for_automatic_production_union": False,
        "candidate_ohlcva_exported": False,
        "original_sources_modified": False,
        "no_raw_ohlcva_or_individual_times_in_report": True,
    }
    m = {
        "format": M.MECHANISM_FORMAT, "symbol": "SH600519", "date": "2026-06-30",
        "candidate_rule_id": M.RULE_ID, "candidate_rule_is_experimental": True,
        "tdx_source_content_sha256": {"1min": "a" * 64, "5min": "b" * 64},
        "purchased_source_stat_only_provenance": {
            "1min": provenance("1min", "d"), "5min": provenance("5min", "e")},
        "minute_comparisons": 240,
        "mismatch_counts_by_field": {
            "open": 0, "high": 1, "low": 0, "close": 0, "volume": 0, "amount": 0},
        "high_mismatch_records": 1, "isolated_high_only": True,
        "verdict": "isolated_minute_high_disagreement_not_visible_at_5min_tolerance",
        "first_minute_any_field_disagreement": False,
        "high_mismatch_source_minute_was_neither_interval_max_count": 1,
        "high_mismatch_containing_interval_aggregated_high_disagrees_count": 0,
        "native_1min_aggregated_vs_native_5min": metrics(48),
        "purchased_candidate_1min_aggregated_vs_purchased_5min": metrics(48),
        "native_5min_vs_purchased_5min": metrics(48),
        "native_1min_internal_5min_all_fields_match": True,
        "purchased_candidate_1min_internal_5min_all_fields_match": True,
        "cross_source_5min_all_fields_match": True,
        "eligible_for_automatic_production_union": False,
        "candidate_ohlcva_exported": False,
        "candidate_materialized": False, "sources_modified": False,
        "market_ohlcva_or_private_paths_exported": False,
        "individual_mismatch_minute_or_interval_positions_exported": False,
    }
    c = {
        "format": M.CROSSCYCLE_FORMAT, "symbol": "SH600519", "date": "2026-06-30",
        "tdx_source_sha256": {"1min": "a" * 64, "5min": "b" * 64, "day": "c" * 64},
        "parquet_stat_only_provenance": {
            "5min": provenance("5min", "e"), "day": provenance("day", "f")},
        "comparisons": {
            "tdx_5min_vs_parquet_5min_by_interval": metrics(48),
            "tdx_daily_vs_parquet_daily": metrics(1, "volume" if parquet_daily_bad else None),
            "parquet_5min_aggregate_vs_parquet_daily": metrics(
                1, "volume" if parquet_daily_bad else None)},
        "tdx_internal_three_period_checked_against_real_bytes": True,
        "eligible_for_automatic_production_union": False,
        "source_market_files_modified": False,
        "staging_or_production_union_performed": False,
        "no_raw_ohlcva_or_individual_times_in_report": True,
    }
    return p, m, c


class CaseGateTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name) / "H5ParquetReconciler"
        self.root.mkdir()
        self.reports = self.root / "reports"
        self.reports.mkdir()
        for attribute, val in (("MODULE", self.root), ("REPORTS", self.reports)):
            patch = mock.patch.object(M, attribute, val)
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, p, m, c):
        files = [self.reports / (name + ".json") for name in
                 ("minute-preview", "isolated-high", "crosscycle")]
        for file, d in zip(files, (p, m, c)):
            file.write_text(json.dumps(d), encoding="utf8")
        return files

    def test_isolated_high_minute_remains_failed_and_daily_volume_separate(self):
        r = M.evaluate(*self.write(*fixture()))
        self.assertEqual(r["minute_field_mismatch_counts"]["high"], 1)
        self.assertEqual(r["minute_disposition"],
                         "isolated_high_not_five_minute_max_minute_disagreement_remains")
        self.assertTrue(r["cross_source_5min_all_fields_match"])
        self.assertEqual(r["daily_volume_disposition"][
            "tdx_daily_vs_parquet_daily_volume"], "mismatch")
        self.assertEqual(r["daily_volume_disposition"][
            "parquet_five_minute_sum_vs_parquet_daily_volume"], "mismatch")
        self.assertFalse(r["eligible_for_automatic_production_union"])
        self.assertFalse(r["production_mapping_certified"])

    def test_daily_volume_ok_does_not_silence_minute_high(self):
        r = M.evaluate(*self.write(*fixture(False)))
        self.assertTrue(r["daily_volume_disposition"]["all_daily_fields_diagnostic_match"])
        self.assertEqual(r["minute_field_mismatch_counts"]["high"], 1)
        self.assertNotIn("all_minute_fields", r["minute_disposition"])

    def test_native_sha_conflict_rejected(self):
        p, m, c = fixture()
        m["tdx_source_content_sha256"]["1min"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "TDX content SHA"):
            M.evaluate(*self.write(p, m, c))

    def test_purchased_5min_manifest_conflict_rejected(self):
        p, m, c = fixture()
        c["parquet_stat_only_provenance"]["5min"]["source_manifest_stat_only_sha256"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "Parquet stat manifest conflicts"):
            M.evaluate(*self.write(p, m, c))

    def test_symbol_day_conflict_rejected(self):
        p, m, c = fixture()
        c["date"] = "2026-07-16"
        with self.assertRaisesRegex(ValueError, "identical stock-day"):
            M.evaluate(*self.write(p, m, c))

    def test_minute_metric_tampering_rejected(self):
        p, m, c = fixture()
        p["candidate_vs_native_full_240"]["high"]["within_diagnostic_tolerance"] = 240
        with self.assertRaisesRegex(ValueError, "Minute field counts conflict"):
            M.evaluate(*self.write(p, m, c))

    def test_safety_flag_tampering_rejected(self):
        p, m, c = fixture()
        p["candidate_ohlcva_exported"] = True
        with self.assertRaisesRegex(ValueError, "Unsafe/contradictory"):
            M.evaluate(*self.write(p, m, c))

    def test_report_paths_and_duplicate_keys_rejected(self):
        files = self.write(*fixture())
        external = self.root / "outside.json"
        external.write_text(files[0].read_text(encoding="utf8"), encoding="utf8")
        with self.assertRaisesRegex(ValueError, "SAFE input"):
            M.evaluate(external, files[1], files[2])
        files[0].write_text('{"format":"x","format":"y"}', encoding="utf8")
        with self.assertRaisesRegex(ValueError, "Duplicate JSON keys"):
            M.evaluate(*files)

    def test_mechanism_high_control_flag_does_not_authorize(self):
        p, m, c = fixture()
        m["high_mismatch_source_minute_was_neither_interval_max_count"] = 0
        r = M.evaluate(*self.write(p, m, c))
        self.assertEqual(r["minute_disposition"], "minute_fields_disagree_do_not_materialize")
        self.assertFalse(r["eligible_for_automatic_production_union"])

    def test_falsified_summary_verdict_rejected(self):
        p, m, c = fixture()
        m["verdict"] = "all_checked_minute_and_five_minute_fields_match"
        with self.assertRaisesRegex(ValueError, "High mechanism verdict contradicts"):
            M.evaluate(*self.write(p, m, c))

    def test_cli_exclusive_create_safe_json(self):
        files = self.write(*fixture())
        args = ["--preview", str(files[0]), "--mechanism", str(files[1]),
                "--crosscycle", str(files[2]), "--read-only",
                "--out", "reports/decision.json"]
        with redirect_stdout(StringIO()):
            M.main(args)
        result = json.loads((self.reports / "decision.json").read_text("utf8"))
        self.assertEqual(result["minute_field_mismatch_counts"]["high"], 1)
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertTrue(result["no_ohlcva_or_intraday_positions_exported"])
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            M.main(args)


if __name__ == "__main__":
    unittest.main()
