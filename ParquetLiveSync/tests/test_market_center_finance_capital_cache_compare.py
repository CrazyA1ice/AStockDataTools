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
        for untrusted in ("20260230", "20240930 extra", "X", "0",
                          "2024093000000", "2026093000"):
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
        self.assertNotIn('"freeFloatCapital": 101', json.dumps(dates))
        self.assertNotIn('"freeFloatCapital": 202', json.dumps(dates))
        self.assertTrue(dates["historical_pending_remains_blocked"])

    def test_capital_change_dates_may_be_off_quarter_end(self):
        """Capital m_timetag is a change date; off-quarter is not an error."""
        days = ["2025-08-13", "2025-09-30", "2025-10-23",
                "2025-12-13", "2025-12-17", "2025-12-31",
                "2026-03-31", "2026-04-15", "2026-06-12",
                "2026-06-30", "2026-08-05", "2026-09-18",
                "2026-09-30"]
        old = [P._fingerprint({"m_timetag": "2023-09-30",
                              "m_quarter": "Q3"}, date_details=True)]
        now = old + [P._fingerprint({"m_timetag": item,
                                    "m_quarter": "Q3"}, date_details=True)
                     for item in days]
        evidence = P._compare(old, now, date_details=True)[
            "report_key_date_details"]
        self.assertEqual(evidence["capital_date_role"],
                         "SHARE_CAPITAL_CHANGE_DATE")
        self.assertEqual(evidence["capital_announcement_date_field"],
                         "m_anntime")
        self.assertFalse(evidence["capital_announcement_dates_verified"])
        self.assertFalse(evidence["calendar_quarter_ends_required"])
        self.assertFalse(evidence["change_event_sources_verified"])
        self.assertFalse(evidence["free_float_capital_alias_normalized"])
        self.assertEqual(evidence["calendar_only_date_counts"]["current_only"],
                         {"calendar_quarter_end": 5,
                          "other_calendar_dates": 8})
        self.assertFalse(evidence[
            "official_report_periods_or_filing_dates_certified"])

    def test_capital_free_float_changes_can_have_adjacent_event_dates(self):
        def item(day, value):
            return P._fingerprint({"m_timetag": day,
                                   "m_quarter": "Q4",
                                   "freeFloatCapital": value},
                                  date_details=True)
        old = [item("20261112", 10), item("20261113", 20)]
        new = [item("20261112", 11), item("20261113", 21)]
        result = P._compare(old, new, date_details=True)
        self.assertEqual(result["observed_class"],
                         "BUSINESS_OR_DATE_FIELD_CHANGED")
        evidence = result["report_key_date_details"]
        self.assertEqual(evidence["calendar_only_date_counts"][
                             "changed_business_fields"],
                         {"calendar_quarter_end": 0,
                          "other_calendar_dates": 2})
        self.assertEqual(
            [d["report_key_date"] for d in
             evidence["changed_business_field_key_dates"]],
            ["2026-11-12", "2026-11-13"])
        self.assertFalse(evidence["change_event_sources_verified"])
        self.assertTrue(evidence["historical_pending_remains_blocked"])

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
            self.assertIn("--explicit-readonly", args[0])
            self.assertIn("--explicit-qmt-cache-read", args[0])
            return SimpleNamespace(
                returncode=0,
                stdout=(P.SENTINEL + json.dumps(payload)).encode("utf-8"))
        res = P._run_child("000001.SZ", runner=simulate, date_details=True)
        self.assertEqual(res["records"][0]["report_key_date"], "2024-09-30")
        record["report_key_date"] = "2024-02-30"
        with self.assertRaises(P.CacheCompareBlocked):
            P._run_child("000001.SZ", runner=simulate, date_details=True)

    def test_internal_date_mode_requires_same_two_opt_ins(self):
        for extra in ([], ["--explicit-readonly"],
                      ["--explicit-qmt-cache-read"]):
            with patch.object(P, "_child_cache_fingerprints") as source, \
                 redirect_stdout(io.StringIO()):
                code = P.main([
                    "--internal-cache-fingerprints",
                    "--report-key-date-details", "--stock", "000001.SZ"
                ] + extra)
            self.assertEqual(code, 2)
            source.assert_not_called()

    def test_parent_compares_two_opt_in_date_samples_once_each(self):
        sha = "a" * 64
        def row(day, cap):
            return P._fingerprint({
                "m_timetag": day, "m_quarter": "Q3",
                "freeFloatCapital": cap}, date_details=True)
        details = {"snapshot_candidates_verified": 1,
                   "historical_selected_dates": 1,
                   "selected_history_variants": 1,
                   "active_pins_structurally_present": 1,
                   "history_fingerprint_locally_verified": True}
        histories = [
            ({"stock": "000010.SZ", "proof_class": P.PROOF_TYPES[0],
              "pending_asof": "2026-11-19", "attempts": 6},
             [row("20230930", 100)], details),
            ({"stock": "000055.SZ", "proof_class": P.PROOF_TYPES[1],
              "pending_asof": "2026-11-19", "attempts": 4},
             [row("20231231", 200)], details)]
        fresh = {
            "000010.SZ": [row("20230930", 100), row("20240331", 100)],
            "000055.SZ": [row("20231231", 201)]}
        called = []
        def local_cache_only(code, *, date_details=False):
            called.append((code, date_details))
            return {"records": fresh[code]}
        with patch.object(P, "_prepare_verified_histories",
                          return_value=(sha, histories)) as prepared, \
             patch.object(P.P2, "summarize_pending",
                          return_value={"progress_sha256": sha}):
            result = P.compare("/synthetic", "/synthetic", sha,
                               read_cache=local_cache_only, date_details=True)
        self.assertEqual(prepared.call_args.kwargs["date_details"], True)
        self.assertEqual(called, [("000010.SZ", True), ("000055.SZ", True)])
        self.assertEqual(result["qmt_cache_calls"], 2)
        self.assertEqual(result["download_calls"], 0)
        self.assertFalse(result["can_execute"])
        self.assertFalse(result["can_repair"])
        self.assertFalse(result["market_file_writes"])
        self.assertEqual(
            result["samples"][0]["report_key_date_details"][
                "current_only_key_dates"], ["2024-03-31"])
        self.assertEqual(
            result["samples"][1]["report_key_date_details"][
                "changed_business_field_key_dates"],
            [{"report_key_date": "2023-12-31",
              "fields": ["freeFloatCapital"]}])

    def test_date_details_discarded_if_ledger_changes_after_qmt_read(self):
        sha = "a" * 64
        rows = [P._fingerprint(
            {"m_timetag": "20240930", "m_quarter": "Q3",
             "freeFloatCapital": 10}, date_details=True)]
        histories = [
            ({"stock": "000010.SZ", "proof_class": P.PROOF_TYPES[0],
              "pending_asof": "2026-11-19", "attempts": 1},
             rows, {"history_fingerprint_locally_verified": True})]
        with patch.object(P, "_prepare_verified_histories",
                          return_value=(sha, histories)), \
             patch.object(P.P2, "summarize_pending",
                          return_value={"progress_sha256": "b" * 64}):
            with self.assertRaisesRegex(
                    P.CacheCompareBlocked, "financial_progress_changed_during_qmt"):
                P.compare("/synthetic", "/synthetic", sha,
                          read_cache=lambda code, *, date_details: {
                              "records": rows}, date_details=True)

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

    def test_capital_announcement_labels_never_disclose_original_amounts(self):
        base = {"m_timetag": "20261112", "m_quarter": "Q4",
                "freeFloatCapital": 123456789}
        for value, expected in (
                ("20261111120000", {"status": "PARSED_DATE",
                                    "date": "2026-11-11"}),
                (None, {"status": "EMPTY_OR_ZERO"}),
                (0, {"status": "EMPTY_OR_ZERO"}),
                ("not-a-date", {"status": "UNPARSEABLE"})):
            row = {**base, "m_anntime": value}
            original = P._fingerprint(row, date_details=True)
            found = P._fingerprint(
                row, date_details=True, announcement_evidence=True)
            self.assertEqual(found["key_sha256"], original["key_sha256"])
            self.assertEqual(found["field_sha256"], original["field_sha256"])
            self.assertEqual(found["announcement_label"], expected)
            self.assertNotIn("123456789", json.dumps(found))
            self.assertNotIn("20261111120000", json.dumps(found))
        no_field = P._fingerprint(
            base, date_details=True, announcement_evidence=True)
        self.assertEqual(no_field["announcement_label"],
                         {"status": "FIELD_ABSENT"})
        with self.assertRaises(P.CacheCompareBlocked):
            P._fingerprint(base, announcement_evidence=True)

    def test_announcement_evidence_only_selected_key_differences(self):
        def dated(day, capital, announcement):
            return P._fingerprint({
                "m_timetag": day, "m_quarter": "Q4",
                "freeFloatCapital": capital, "m_anntime": announcement},
                date_details=True, announcement_evidence=True)
        old = [dated("20240101", 100, "20231231"),
               dated("20261112", 200, "20261111"),
               dated("20261113", 300, "20261113")]
        cache = [dated("20240101", 100, "20231231"),
                 dated("20261112", 201, "20261111"),
                 dated("20261113", 301, "20261113"),
                 dated("20261114", 400, "20261114")]
        report = P._compare(
            old, cache, date_details=True, announcement_evidence=True)
        evidence = report["report_key_date_details"][
            "capital_announcement_evidence"]
        self.assertEqual(report["observed_class"],
                         "REPORT_KEYS_ADDED_OR_REMOVED")
        self.assertFalse(evidence["official_announcements_checked"])
        self.assertFalse(evidence["can_certify_or_repair"])
        self.assertEqual(len(evidence["entries"]), 3)
        self.assertEqual(
            [e["capital_change_date"] for e in evidence["entries"]],
            ["2026-11-12", "2026-11-13", "2026-11-14"])
        self.assertEqual(evidence["entries"][0]["difference_reason"],
                         "BUSINESS_FIELD_DIFF")
        self.assertEqual(evidence["entries"][0]["historical_m_anntime"],
                         {"status": "PARSED_DATE", "date": "2026-11-11"})
        self.assertEqual(evidence["entries"][-1]["difference_reason"],
                         "CACHE_ONLY_KEY")
        self.assertEqual(evidence["entries"][-1]["historical_m_anntime"],
                         {"status": "RECORD_NOT_IN_THIS_VERSION"})
        self.assertNotIn("2024-01-01", json.dumps(evidence))
        self.assertNotIn("freeFloatCapital", json.dumps(evidence))
        self.assertNotIn("400", json.dumps(evidence))
        original = P._compare(old, cache, date_details=True)
        self.assertNotIn("capital_announcement_evidence",
                         original["report_key_date_details"])
        self.assertEqual(report["changed_non_quarter_field_counts"],
                         original["changed_non_quarter_field_counts"])

    def test_announcement_receipt_validation_blocks_forged_status_or_date(self):
        record = P._fingerprint({
            "m_timetag": "20261112", "m_anntime": "20261111",
            "m_quarter": "Q4", "freeFloatCapital": 12},
            date_details=True, announcement_evidence=True)
        payload = {"format": "qmt_capital_cache_fingerprints_v1",
                   "stock": "000010.SZ", "table": "Capital",
                   "row_count": 1, "records": [record]}
        def runner(*args, **kwargs):
            self.assertIn("--capital-announcement-evidence", args[0])
            self.assertIn("--report-key-date-details", args[0])
            self.assertIn("--explicit-readonly", args[0])
            self.assertIn("--explicit-qmt-cache-read", args[0])
            return SimpleNamespace(
                returncode=0,
                stdout=(P.SENTINEL + json.dumps(payload)).encode("utf-8"))
        self.assertEqual(P._run_child(
            "000010.SZ", runner=runner, date_details=True,
            announcement_evidence=True)["records"][0]["announcement_label"],
            {"status": "PARSED_DATE", "date": "2026-11-11"})
        record["announcement_label"] = {
            "status": "PARSED_DATE", "date": "2026-02-30"}
        with self.assertRaises(P.CacheCompareBlocked):
            P._run_child("000010.SZ", runner=runner, date_details=True,
                         announcement_evidence=True)
        record["announcement_label"] = {"status": "FIELD_ABSENT"}
        with self.assertRaises(P.CacheCompareBlocked):
            P._run_child("000010.SZ", runner=runner, date_details=True,
                         announcement_evidence=True)

    def test_parent_announcement_opt_in_only_two_cache_reads(self):
        sha = "a" * 64
        def fp(day, capital, notice):
            return P._fingerprint({
                "m_timetag": day, "m_quarter": "Q4",
                "freeFloatCapital": capital, "m_anntime": notice},
                date_details=True, announcement_evidence=True)
        old = [
            ({"stock": "000010.SZ", "proof_class": P.PROOF_TYPES[0],
              "pending_asof": "2026-11-19", "attempts": 6},
             [fp("20251112", 10, "20251111")], {}),
            ({"stock": "000055.SZ", "proof_class": P.PROOF_TYPES[1],
              "pending_asof": "2026-11-19", "attempts": 4},
             [fp("20261112", 20, "20261111")], {})]
        cache = {
            "000010.SZ": [fp("20251112", 10, "20251111"),
                          fp("20251212", 12, "20251211")],
            "000055.SZ": [fp("20261112", 21, "20261111")]}
        calls = []
        def reader(code, *, date_details, announcement_evidence):
            calls.append((code, date_details, announcement_evidence))
            return {"records": cache[code]}
        with patch.object(P, "_prepare_verified_histories",
                          return_value=(sha, old)) as prepare, \
             patch.object(P.P2, "summarize_pending",
                          return_value={"progress_sha256": sha}):
            result = P.compare("/synthetic", "/synthetic", sha,
                               read_cache=reader, date_details=True,
                               announcement_evidence=True)
        self.assertEqual(prepare.call_args.kwargs["announcement_evidence"],
                         True)
        self.assertEqual(calls, [
            ("000010.SZ", True, True), ("000055.SZ", True, True)])
        self.assertEqual(result["qmt_cache_calls"], 2)
        self.assertEqual(result["download_calls"], 0)
        self.assertFalse(result["market_file_writes"])
        self.assertFalse(result["official_announcements_checked"])
        self.assertFalse(result["can_repair"])
        for sample in result["samples"]:
            self.assertEqual(len(sample["report_key_date_details"][
                "capital_announcement_evidence"]["entries"]), 1)

    def test_announcement_cli_opt_ins_and_preflight_incompatibility(self):
        sha = "a" * 64
        opts = ["--state-module", "/synthetic",
                "--market-root", "/synthetic",
                "--expected-progress-sha256", sha,
                "--capital-announcement-evidence"]
        with patch.object(P, "compare") as compare, \
             patch.object(P, "preflight") as preflight:
            for args in (opts, opts + ["--explicit-readonly",
                                       "--explicit-qmt-cache-read"],
                         opts + ["--report-key-date-details",
                                 "--preflight-only", "--explicit-readonly"]):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(P.main(args), 2)
            compare.assert_not_called()
            preflight.assert_not_called()
        with patch.object(P, "compare",
                          return_value={"status": "MOCK_ONLY"}) as compare, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(P.main(opts + [
                "--report-key-date-details",
                "--explicit-readonly", "--explicit-qmt-cache-read"]), 0)
        self.assertTrue(compare.call_args.kwargs["announcement_evidence"])

    def test_internal_announcement_mode_requires_all_readonly_opt_ins(self):
        for args in ([], ["--explicit-readonly"],
                     ["--explicit-qmt-cache-read"],
                     ["--explicit-readonly", "--explicit-qmt-cache-read"]):
            with patch.object(P, "_child_cache_fingerprints") as child, \
                 redirect_stdout(io.StringIO()):
                rc = P.main(["--internal-cache-fingerprints",
                             "--capital-announcement-evidence",
                             "--stock", "000010.SZ"] + args)
            self.assertEqual(rc, 2)
            child.assert_not_called()

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
