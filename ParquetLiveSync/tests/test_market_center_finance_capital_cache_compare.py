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
        self.assertNotIn("a", json.dumps(report))
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
        self.assertNotIn("m_totalShare", json.dumps(result))
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
