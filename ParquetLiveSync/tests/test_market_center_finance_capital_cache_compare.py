"""Synthetic P5 Capital cache-read fingerprints and historical comparison tests."""
from __future__ import annotations

from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import sys
import unittest

import market_center_finance_capital_cache_compare as P


def fp(key, quarter, *, shares=100):
    return P._fingerprint({"m_timetag": key, "m_quarter": quarter,
                           "m_totalShare": shares})


class CapitalCompareTests(unittest.TestCase):
    def test_report_key_removed_and_added_are_counted_without_values(self):
        report = P._compare([fp("a", 1), fp("b", 2)],
                            [fp("a", 1), fp("c", 3)])
        self.assertEqual(report["observed_class"],
                         "REPORT_KEYS_ADDED_OR_REMOVED")
        self.assertEqual(report["previous_keys_missing_from_cache"], 1)
        self.assertEqual(report["cached_keys_absent_from_previous"], 1)
        self.assertNotIn('"a"', json.dumps(report))
        self.assertNotIn("m_totalShare", json.dumps(report))

    def test_economic_field_difference_not_marked_as_quarter_noise(self):
        report = P._compare([fp("a", 1, shares=100)],
                            [fp("a", 2, shares=101)])
        self.assertEqual(report["observed_class"],
                         "BUSINESS_OR_DATE_FIELD_CHANGED")
        self.assertEqual(report["changed_non_quarter_field_counts"],
                         [{"field": "m_totalShare", "report_keys": 1}])

    def test_m_quarter_only_still_not_repair_approval(self):
        report = P._compare([fp("a", 1)], [fp("a", 2)])
        self.assertEqual(report["observed_class"],
                         "M_QUARTER_ONLY_CANDIDATE_NOT_APPROVED")
        self.assertEqual(report["changed_non_quarter_field_counts"], [])

    def test_historical_business_revision_precedes_fresh_difference(self):
        report = P._compare([fp("a", 1, shares=100),
                             fp("a", 2, shares=101)],
                            [fp("a", 3, shares=102)])
        self.assertEqual(report["observed_class"],
                         "HISTORICAL_BUSINESS_FIELD_REVISION")
        self.assertEqual(report["historical_business_conflicting_keys"], 1)

    def test_duplicate_fresh_report_key_blocks(self):
        with self.assertRaisesRegex(P.CacheCompareBlocked, "duplicate_cached"):
            P._compare([fp("a", 1)], [fp("a", 1), fp("a", 2)])

    def test_two_proof_classes_have_two_distinct_pending_identities(self):
        items = {}
        for code, kind in (("000001.SZ", "REPORT_KEYS_ADDED_OR_REMOVED"),
                           ("000002.SZ", "BUSINESS_OR_DATE_FIELD_CHANGED")):
            items[code] = {
                "reason": "SOURCE_HISTORY_CONFLICT", "asof": "2026-11-21",
                "attempts": 1, "detail": "SOURCE_HISTORY_CONFLICT " + code +
                " table=Capital scoped_m_quarter_proof=" + kind,
            }
        chosen = P._pick_two({"pending": items}, {"000001.SZ"})
        self.assertEqual([x["stock"] for x in chosen],
                         ["000001.SZ", "000002.SZ"])

    def test_cache_read_internal_worker_only_get_financial_data(self):
        class Frame:
            index = ["row0"]
            def to_dict(self, orient):
                return [{"m_timetag": "20240930", "m_quarter": "Q3",
                         "m_totalShare": 100}]
        class API:
            def get_financial_data(self, stocks, tables, **kwargs):
                self.args = (stocks, tables, kwargs)
                return {"000001.SZ": {"Capital": Frame()}}
        xt = ModuleType("xtquant")
        xt.xtdata = API()
        with patch.dict(sys.modules, {"xtquant": xt}):
            result = P._child_cache_fingerprints("000001.SZ")
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(xt.xtdata.args[1], ["Capital"])
        self.assertEqual(len(result["records"][0]["field_sha256"]["m_totalShare"]), 64)
        self.assertNotIn('"m_totalShare":100', json.dumps(result))
        self.assertEqual(result["table"], "Capital")

    def test_child_fingerprint_receipt_rejects_unsafe_data(self):
        bad = SimpleNamespace(returncode=0,
                              stdout=b"FINANCE_P5_CACHED_FINGERPRINTS={}\n")
        with self.assertRaisesRegex(P.CacheCompareBlocked, "envelope"):
            P._run_child("000001.SZ", runner=lambda *a, **k: bad)

    def test_cache_worker_timeout_is_fail_closed(self):
        import subprocess
        def late(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 5)
        with self.assertRaisesRegex(P.CacheCompareBlocked, "timed_out"):
            P._run_child("000001.SZ", runner=late)

    def test_offline_preflight_selects_two_classes_without_cache_or_values(self):
        from datetime import datetime, timedelta, timezone
        sha = "a" * 64
        stocks = ("000001.SZ", "000002.SZ")
        kinds = P.PROOF_TYPES
        ledger = {"pending": {
            code: {"reason": "SOURCE_HISTORY_CONFLICT",
                   "asof": "2026-11-22", "attempts": 1,
                   "detail": "SOURCE_HISTORY_CONFLICT " + code +
                   " table=Capital scoped_m_quarter_proof=" + kind}
            for code, kind in zip(stocks, kinds)}}
        details = {"snapshot_candidates_verified": 1,
                   "historical_selected_dates": 1,
                   "selected_history_variants": 3,
                   "active_pins_structurally_present": 1,
                   "history_fingerprint_locally_verified": True}
        now = datetime(2026, 11, 22, 21, 0,
                       tzinfo=timezone(timedelta(hours=8)))
        with TemporaryDirectory() as tmp:
            state = Path(tmp) / "ParquetLiveSync"
            market = Path(tmp) / "AllCycleAStockData"
            with (patch.object(P.P3, "review", return_value={
                        "progress_sha256": sha,
                        "samples": [{"stock": stocks[0]}]}),
                  patch.object(P.P2, "_trusted_path",
                               return_value=state / "financial-progress.json"),
                  patch.object(P.P2, "_read_ledger",
                               return_value=(ledger, sha)),
                  patch.object(P.P3, "_root", return_value=market / "qmt_extra" /
                               "financial"),
                  patch.object(P, "_old_verified_fingerprints",
                               return_value=([fp("old", 1)], details)) as history,
                  patch.object(P.P2, "summarize_pending",
                               return_value={"progress_sha256": sha}),
                  patch.object(P, "_run_child",
                               side_effect=AssertionError("NO_QMT_READ")) as cache):
                report = P.preflight(state, market, sha, now=now)
        cache.assert_not_called()
        self.assertEqual(history.call_count, 2)
        self.assertEqual(report["sample_count"], 2)
        self.assertEqual([x["stock"] for x in report["samples"]],
                         list(stocks))
        self.assertEqual([x["pending_proof_class"] for x in report["samples"]],
                         list(kinds))
        self.assertEqual(report["qmt_cache_calls"], 0)
        self.assertEqual(report["download_calls"], 0)
        self.assertFalse(report["current_qmt_cache_compared"])
        self.assertFalse(report["actual_conflict_report_dates_located"])
        self.assertFalse(report["can_execute"])
        self.assertFalse(report["can_repair"])
        self.assertFalse(report["market_file_writes"])
        self.assertNotIn("field_sha256", json.dumps(report))

    def test_preflight_requires_explicit_readonly_and_rejects_cache_flag(self):
        sha = "a" * 64
        args = ["--state-module", "/synthetic",
                "--market-root", "/synthetic",
                "--expected-progress-sha256", sha,
                "--preflight-only"]
        report = {"status":
                  "FINANCE_P5_CAPITAL_TWO_STOCK_OFFLINE_PREFLIGHT_NOT_CERTIFIED",
                  "qmt_cache_calls": 0, "can_execute": False}
        with (patch.object(P, "preflight", return_value=report) as offline,
              patch.object(P, "compare") as online):
            for flags in (args, args + ["--explicit-readonly",
                                       "--explicit-qmt-cache-read"]):
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(P.main(flags), 2)
                self.assertIn("OFFLINE_PREFLIGHT_ONLY_READONLY_REQUIRED",
                              output.getvalue())
            offline.assert_not_called()
            online.assert_not_called()
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(
                    P.main(args + ["--explicit-readonly"]), 0)
            self.assertIn(report["status"], output.getvalue())
            offline.assert_called_once()
            online.assert_not_called()

    def test_offline_preflight_cannot_enter_internal_qmt_child(self):
        with patch.object(P, "_child_cache_fingerprints") as qmt, \
             redirect_stdout(io.StringIO()):
            result = P.main([
                "--preflight-only", "--internal-cache-fingerprints",
                "--stock", "000001.SZ"])
        self.assertEqual(result, 2)
        qmt.assert_not_called()

    def test_preflight_missing_proof_class_never_reads_current_cache(self):
        sha = "b" * 64
        stock = "000001.SZ"
        ledger = {"pending": {
            stock: {"reason": "SOURCE_HISTORY_CONFLICT",
                    "asof": "2026-11-22", "attempts": 1,
                    "detail": "SOURCE_HISTORY_CONFLICT " + stock +
                              " table=Capital scoped_m_quarter_proof=" +
                              P.PROOF_TYPES[0]}}}
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 11, 22, 21, 0,
                       tzinfo=timezone(timedelta(hours=8)))
        with (patch.object(P.P3, "review", return_value={
                  "progress_sha256": sha, "samples": []}),
              patch.object(P.P2, "_trusted_path", return_value=Path("/synthetic")),
              patch.object(P.P2, "_read_ledger", return_value=(ledger, sha)),
              patch.object(P, "_old_verified_fingerprints") as old,
              patch.object(P, "_run_child") as cache):
            with self.assertRaisesRegex(P.CacheCompareBlocked,
                                        "missing_required_capital_proof_class"):
                P.preflight("/synthetic", "/synthetic", sha, now=now)
            old.assert_not_called()
            cache.assert_not_called()

    def test_p5_opt_in_date_labels_keep_unchanged_sha_key_identity(self):
        row = {"m_timetag": "20240930", "m_quarter": "Q3",
               "freeFloatCapital": 123456.78}
        old = P._fingerprint(row)
        decorated = P._fingerprint(row, date_details=True)
        self.assertEqual(decorated["key_sha256"], old["key_sha256"])
        self.assertEqual(decorated["field_sha256"], old["field_sha256"])
        self.assertEqual(decorated["report_key_date"], "2024-09-30")
        self.assertNotIn("report_key_date", old)
        self.assertNotIn("123456.78", json.dumps(decorated))
        self.assertEqual(P._report_key_date(1609459200000), "2021-01-01")
        self.assertEqual(P._report_key_date("20240930120000"), "2024-09-30")
        for untrusted in ("20260230", "20240930 extra", "X", "0"):
            with self.assertRaises(P.CacheCompareBlocked):
                P._report_key_date(untrusted)

    def test_opt_in_locates_thirteen_cache_only_key_dates_not_quarter_noise(self):
        def row(key, quarter="Q3", cap=100):
            return P._fingerprint(
                {"m_timetag": key, "m_quarter": quarter,
                 "freeFloatCapital": cap}, date_details=True)
        old = [row("20200930")]
        added = [f"{year}0630" for year in range(2000, 2013)]
        fresh = [row("20200930", quarter="Q4")] + [row(day) for day in added]
        before = P._compare(old, fresh)
        report = P._compare(old, fresh, date_details=True)
        self.assertEqual(report["cached_keys_absent_from_previous"], 13)
        self.assertEqual(report["m_quarter_changed_matching_report_keys"], 1)
        self.assertEqual(report["observed_class"], before["observed_class"])
        self.assertEqual(report["changed_non_quarter_field_counts"],
                         before["changed_non_quarter_field_counts"])
        self.assertNotIn("report_key_date_details", before)
        evidence = report["report_key_date_details"]
        self.assertEqual(evidence["current_only_key_dates"],
                         [f"{year}-06-30" for year in range(2000, 2013)])
        self.assertEqual(evidence["previous_only_key_dates"], [])
        self.assertEqual(evidence["changed_business_field_key_dates"], [])
        self.assertTrue(evidence["m_quarter_date_labels_omitted"])
        self.assertFalse(evidence["official_report_periods_or_filing_dates_certified"])
        self.assertNotIn("freeFloatCapital", json.dumps(evidence))

    def test_opt_in_locates_two_business_key_dates_without_financial_values(self):
        def row(day, cap, quarter="Q3"):
            return P._fingerprint({
                "m_timetag": day, "m_quarter": quarter,
                "freeFloatCapital": cap}, date_details=True)
        old = [row("20230930", 100), row("20231231", 200),
               row("20240331", 300)]
        fresh = [row("20230930", 101, "Q4"), row("20231231", 202),
                 row("20240331", 300)]
        report = P._compare(old, fresh, date_details=True)
        self.assertEqual(report["observed_class"],
                         "BUSINESS_OR_DATE_FIELD_CHANGED")
        self.assertEqual(report["changed_non_quarter_field_counts"],
                         [{"field": "freeFloatCapital", "report_keys": 2}])
        dates = report["report_key_date_details"]
        self.assertEqual(dates["changed_business_field_key_dates"], [
            {"report_key_date": "2023-09-30", "fields": ["freeFloatCapital"]},
            {"report_key_date": "2023-12-31", "fields": ["freeFloatCapital"]},
        ])
        self.assertNotIn("101", json.dumps(dates))
        self.assertNotIn("202", json.dumps(dates))
        self.assertTrue(dates["historical_pending_remains_blocked"])

    def test_date_details_fail_closed_for_ambiguous_or_unbounded_mapping(self):
        def row(day):
            return P._fingerprint({
                "m_timetag": day, "m_quarter": "Q1",
                "freeFloatCapital": 1}, date_details=True)
        with self.assertRaisesRegex(
                P.CacheCompareBlocked, "ambiguous_qmt_key_date_mapping"):
            P._compare([row("20240930"), row("2024-09-30")],
                       [row("20240930")], date_details=True)
        too_many = [row(f"{year}0630") for year in range(1980, 2013)]
        with self.assertRaisesRegex(
                P.CacheCompareBlocked, "report_key_date_detail_budget_exceeded"):
            P._compare([], too_many, date_details=True)
        tampered = row("20240930")
        del tampered["report_key_date"]
        with self.assertRaisesRegex(
                P.CacheCompareBlocked, "missing_verified_qmt_key_date"):
            P._compare([], [tampered], date_details=True)

    def test_internal_date_receipt_validates_dates_and_never_reads_source(self):
        record = P._fingerprint({
            "m_timetag": "20240930", "m_quarter": "Q3",
            "freeFloatCapital": 987654}, date_details=True)
        payload = {"format": "qmt_capital_cache_fingerprints_v1",
                   "stock": "000001.SZ", "table": "Capital", "row_count": 1,
                   "records": [record]}
        def simulate(*args, **kwargs):
            self.assertIn("--report-key-date-details", args[0])
            return SimpleNamespace(
                returncode=0,
                stdout=(P.SENTINEL + json.dumps(payload)).encode("utf-8"))
        res = P._run_child("000001.SZ", runner=simulate, date_details=True)
        self.assertEqual(res["records"][0]["report_key_date"], "2024-09-30")
        record["report_key_date"] = "2024-02-30"
        with self.assertRaises(P.CacheCompareBlocked):
            P._run_child("000001.SZ", runner=simulate, date_details=True)

    def test_cli_date_details_require_separate_explicit_cache_read(self):
        sha = "a" * 64
        args = ["--state-module", "/synthetic",
                "--market-root", "/synthetic",
                "--expected-progress-sha256", sha,
                "--report-key-date-details"]
        mock = {"status": "SYNTHETIC_ONLY", "can_repair": False}
        with patch.object(P, "preflight") as offline, \
             patch.object(P, "compare", return_value=mock) as online:
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(P.main(args), 2)
            self.assertIn("TWO_EXPLICIT_OPTINS_REQUIRED", output.getvalue())
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(P.main(args + [
                    "--preflight-only", "--explicit-readonly"]), 2)
            self.assertIn("OFFLINE_PREFLIGHT_ONLY_READONLY_REQUIRED",
                          output.getvalue())
            offline.assert_not_called()
            online.assert_not_called()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(P.main(args + [
                    "--explicit-readonly", "--explicit-qmt-cache-read"]), 0)
            self.assertTrue(online.call_args.kwargs["date_details"])

    def test_default_cli_never_imports_or_calls_qmt(self):
        with patch.object(P, "compare") as compare:
            with redirect_stdout(io.StringIO()) as capture:
                result = P.main(["--state-module", "/bad",
                                 "--market-root", "/bad",
                                 "--expected-progress-sha256", "a"*64])
        self.assertEqual(result, 2)
        compare.assert_not_called()
        self.assertIn("TWO_EXPLICIT_OPTINS_REQUIRED", capture.getvalue())

    def test_bad_sha_rejected_before_any_audit(self):
        with patch.object(P.P3, "review") as review:
            with self.assertRaisesRegex(P.CacheCompareBlocked, "sha_required"):
                P.compare("/bad", "/bad", "INVALID")
            review.assert_not_called()


if __name__ == "__main__":
    unittest.main()
