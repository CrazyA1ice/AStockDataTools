"""Pure synthetic daily autopilot health checks. Does not run QMT or update."""
from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
from unittest.mock import patch
import unittest

import market_daily_autopilot_shadow as S


def inputs(*, status="PARTIAL", financial_exit=0,
           finance_qa="PARTIAL", adjustments_qa="PARTIAL", pending=85,
           reached_end=False):
    receipt = {
        "format": "qmt_daily_single_trigger_v3",
        "mode": "UNIFIED_SINGLE_RUN", "status": status,
        "china_start": "2026-11-21T20:05:02.7044379",
        "qmt_preflight_status": "CONNECTED", "errors": [],
        "stage_records": {name: {"exit_code": 0} for name in S.STAGES},
        "validation": {
            "data_validation": "PARTIAL",
            "cross_validation": "UNVERIFIED",
            "sections": {
                "EIGHT_PERIODS": {"data_validation": "UNVERIFIED",
                                  "cross_validation": "UNVERIFIED"},
                "SECTORS": {"data_validation": "PASS",
                            "cross_validation": "UNVERIFIED"},
                "ADJUSTMENTS_ROTATING": {"data_validation": adjustments_qa,
                                         "cross_validation": "UNVERIFIED"},
                "FINANCIAL_DAILY": {"data_validation": finance_qa,
                                    "cross_validation": "UNVERIFIED",
                                    "remaining_unvisited": 5201,
                                    "processed": 159},
            },
        },
    }
    receipt["stage_records"]["FINANCIAL_DAILY"]["exit_code"] = financial_exit
    ledger = {
        "format": "qmt_financial_cache_import_v1",
        "daily_date": "2026-11-21", "daily_cursor": "001266.SZ",
        "daily_sweep_start": "2026-11-19",
        "daily_sweep_finished": "2026-11-18",
        "daily_sweep_reached_end": reached_end,
        "pending": {},
    }
    for n in range(pending):
        code = f"{n:06d}.SZ"
        ledger["pending"][code] = {
            "reason": "SOURCE_HISTORY_CONFLICT",
            "asof": "2026-11-21", "attempts": 1,
            "detail": "synthetic conflict",
        }
    return receipt, ledger


class HealthTests(unittest.TestCase):
    def test_ordinary_partial_is_not_a_daily_failure(self):
        a, b = inputs()
        h = S.classify(a, b)
        self.assertEqual(h["execution_health"], "ROUTINE_CONTINUATION")
        self.assertEqual(h["alert_policy_preview"], "NONE")
        self.assertEqual(h["coverage"]["financial_remaining_unvisited"], 5201)
        self.assertEqual(h["coverage"]["pending_total"], 85)
        self.assertEqual(h["normal_partial_stages"],
                         ["ADJUSTMENTS_ROTATING", "FINANCIAL_DAILY"])
        self.assertIn("EIGHT_PERIODS", h["unverified_stage_labels"])
        self.assertFalse(h["can_download"])

    def test_finance_nonzero_exit_requires_attention(self):
        a, b = inputs(financial_exit=86)
        h = S.classify(a, b)
        self.assertEqual(h["alert_policy_preview"], "ACTION")
        self.assertIn("FINANCIAL_DAILY_NONZERO_EXIT",
                      h["stage_execution_errors"])

    def test_quality_fail_is_not_hidden_as_normal_rotation(self):
        a, b = inputs(finance_qa="FAIL")
        h = S.classify(a, b)
        self.assertEqual(h["alert_policy_preview"], "ACTION")
        self.assertEqual(h["stage_quality_failures"], ["FINANCIAL_DAILY"])

    def test_cross_source_failure_requires_attention(self):
        a, b = inputs()
        a["validation"]["sections"]["SECTORS"]["cross_validation"] = "FAIL"
        h = S.classify(a, b)
        self.assertEqual(h["alert_policy_preview"], "ACTION")

    def test_missing_verification_never_claims_data_certified(self):
        a, b = inputs()
        a["validation"] = None
        h = S.classify(a, b)
        self.assertEqual(h["execution_health"], "EXECUTED_NEEDS_REVIEW")
        self.assertEqual(h["alert_policy_preview"], "REVIEW")

    def test_mass_conflict_requires_safety_review(self):
        a, b = inputs(pending=500)
        h = S.classify(a, b)
        self.assertEqual(h["alert_policy_preview"], "ACTION")
        self.assertIn("FINANCE_MASS_CONFLICT_SAFETY_REVIEW",
                      h["stage_execution_errors"])

    def test_ledger_run_day_mismatch_is_attention(self):
        a, b = inputs()
        b["daily_date"] = "2026-11-20"
        h = S.classify(a, b)
        self.assertEqual(h["alert_policy_preview"], "ACTION")

    def test_reached_end_does_not_discard_pending(self):
        a, b = inputs(reached_end=True)
        h = S.classify(a, b)
        self.assertEqual(h["coverage"]["financial_sweep"],
                         "SWEEP_REACHED_END_PENDING_SEPARATE")
        self.assertEqual(h["coverage"]["pending_total"], 85)

    def test_invalid_pending_stock_fails_closed(self):
        a, b = inputs(pending=0)
        b["pending"] = {"bad": {"reason": "SOURCE_HISTORY_CONFLICT",
                                "attempts": 1}}
        with self.assertRaises(S.HealthBlocked):
            S.classify(a, b)

    def test_cli_requires_explicit_readonly_without_disk(self):
        with patch.object(S, "inspect") as read:
            with redirect_stdout(io.StringIO()) as out:
                rc = S.main(["--state-module", "/invalid"])
        self.assertEqual(rc, 2)
        read.assert_not_called()
        self.assertIn("EXPLICIT_READONLY_REQUIRED", out.getvalue())

    def test_canonical_fixture_files_are_read_only(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "ParquetLiveSync"
            work = root / "work"
            (work / "qmt_extra").mkdir(parents=True)
            a, b = inputs()
            receipt = work / "last-afternoon-unified.json"
            ledger = work / "qmt_extra" / "financial-cache-progress.json"
            receipt.write_text(json.dumps(a), encoding="utf-8")
            ledger.write_text(json.dumps(b), encoding="utf-8")
            first = receipt.read_bytes(), ledger.read_bytes()
            report = S.inspect(root)
            self.assertEqual(report["alert_policy_preview"], "NONE")
            self.assertEqual(first, (receipt.read_bytes(), ledger.read_bytes()))
            self.assertEqual(report["writes"], 0)


    def test_nonplanned_kline_partial_requires_review_not_green(self):
        a, b = inputs()
        a["validation"]["sections"]["EIGHT_PERIODS"]["data_validation"] = "PARTIAL"
        h = S.classify(a, b)
        self.assertEqual(h["alert_policy_preview"], "REVIEW")
        self.assertEqual(h["other_partial_stages_require_review"],
                         ["EIGHT_PERIODS"])

    def test_run_global_fail_is_never_hidden_by_stage_pass(self):
        a, b = inputs()
        a["validation"]["data_validation"] = "FAIL"
        h = S.classify(a, b)
        self.assertEqual(h["alert_policy_preview"], "ACTION")
        self.assertIn("RUN_GLOBAL_VALIDATION", h["stage_quality_failures"])

    def test_failed_run_receipt_never_green_even_with_all_stage_exit_zero(self):
        a, b = inputs(status="FAILED")
        h = S.classify(a, b)
        self.assertEqual(h["alert_policy_preview"], "ACTION")
        self.assertIn("RUN_RECEIPT_FAILED", h["stage_execution_errors"])

    def test_unknown_receipt_format_never_green(self):
        a, b = inputs()
        a["format"] = "unexpected_format"
        with self.assertRaises(S.HealthBlocked):
            S.classify(a, b)


if __name__ == "__main__":
    unittest.main()
