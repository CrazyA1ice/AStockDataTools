"""Synthetic policy tests. Never call QMT, WeCom, or mutate market data."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import market_daily_verification as V
import market_update_push as PUSH


def tagged(marker, obj):
    return marker + json.dumps(obj, ensure_ascii=False) + "\n"


def market_log(*, quarantine=0, disagree=False):
    lines = tagged("MARKET_EIGHT_PERIOD_SUMMARY=", {
        "status": "ALL_EIGHT_PERIOD_PHASES_COMPLETE",
        "applied": True, "phases_blocked": {},
    })
    lines += tagged("MARKET_DAILY_STAGED=", {
        "date": "2026-11-24", "accepted": 5100, "quarantine": quarantine,
    })
    lines += "MARKET_SOURCE_SAMPLE=eltdx status=AGREE agreed=8/8 attempted=8\n"
    lines += ("MARKET_SOURCE_SAMPLE=tencent status=PRICE_DISAGREES agreed=3/8 attempted=8\n"
              if disagree else
              "MARKET_SOURCE_SAMPLE=tencent status=AGREE agreed=8/8 attempted=8\n")
    return lines


def finance_log(*, pending=54, remaining=4726, processed=71,
                scanned=False, complete=False):
    return tagged("QMT_FINANCIAL_CACHE_IMPORT_SUMMARY=", {
        "mode": "daily", "apply": True,
        "status": "PAUSED_SYMBOL_LIMIT" if remaining else "SOURCE_UNIVERSE_EXHAUSTED",
        "source_completeness_verified": complete, "processed": processed,
        "pending_total": pending, "daily_remaining_unvisited": remaining,
        "daily_sweep_reached_end": scanned,
    })


def sectors_log():
    return tagged("MARKET_QMT_EXTRA_SUMMARY=", {
        "sections": {"sectors": {"status": "UPDATED", "memberships": 650}},
    })


def adjustments_log(*, processed=80, more=True):
    return tagged("MARKET_QMT_EXTRA_SUMMARY=", {
        "sections": {"adjustments": {
            "symbols_processed": processed, "next_batch_required": more}},
    })


def report_for(*, logs=None, exit_codes=None, completed=None, errors=None):
    data = {
        "EIGHT_PERIODS": market_log(),
        "SECTORS": sectors_log(),
        "ADJUSTMENTS_ROTATING": adjustments_log(),
        "FINANCIAL_DAILY": finance_log(),
    }
    data.update(logs or {})
    codes = dict.fromkeys(V.STAGES, 0)
    codes.update(exit_codes or {})
    with tempfile.TemporaryDirectory() as d:
        records = {}
        for stage in V.STAGES:
            log = Path(d) / (stage + ".log")
            log.write_text(data[stage], encoding="utf-8")
            records[stage] = {"exit_code": codes[stage], "log_path": str(log)}
        run = {
            "format": "qmt_daily_single_trigger_v3", "status": "SUCCESS",
            "steps_completed": list(V.STAGES) if completed is None else completed,
            "stage_records": records, "errors": [] if errors is None else errors,
            "china_start": "2026-11-24T23:10:47+08:00",
        }
        verification = V.report(run, expected_sources={"eltdx", "tencent"})
        return run, verification


class RoutineFinanceExitPolicyTests(unittest.TestCase):
    def test_actual_nov24_shape_is_normal_execution_not_complete_history(self):
        run, v = report_for()
        self.assertEqual(v["execution"], "PASS")
        self.assertEqual(v["data_validation"], "PARTIAL")
        self.assertEqual(v["cross_validation"], "UNVERIFIED")
        self.assertEqual(v["sections"]["FINANCIAL_DAILY"]["pending_total"], 54)
        self.assertEqual(v["sections"]["FINANCIAL_DAILY"]["remaining_unvisited"], 4726)
        self.assertEqual(v["sections"]["FINANCIAL_DAILY"]["processed"], 71)
        self.assertTrue(v["routine_continuation"])
        self.assertIn("本轮更新执行完成", v["notification_text"])
        self.assertIn("历史完整性未验证", v["notification_text"])

        # Sender title must not claim the historic finance backlog was validated.
        run["validation"] = v
        run["operational_classification"] = "ROUTINE_CONTINUATION"
        text = PUSH._report_text(run)
        self.assertIn("本轮执行完成（财务/除权正常轮换，仍有待审）", text)
        self.assertIn("质量：PARTIAL", text)
        self.assertIn("跨源：UNVERIFIED", text)

    def test_real_finance_exit_failure_must_not_be_routine(self):
        _, v = report_for(exit_codes={"FINANCIAL_DAILY": 86})
        self.assertFalse(v["routine_continuation"])
        self.assertEqual(v["sections"]["FINANCIAL_DAILY"]["data_validation"], "FAIL")

    def test_cross_source_disagreement_must_not_be_routine(self):
        _, v = report_for(logs={"EIGHT_PERIODS": market_log(disagree=True)})
        self.assertFalse(v["routine_continuation"])
        self.assertEqual(v["cross_validation"], "FAIL")

    def test_market_quarantine_must_not_be_routine(self):
        _, v = report_for(logs={"EIGHT_PERIODS": market_log(quarantine=2)})
        self.assertFalse(v["routine_continuation"])
        self.assertEqual(v["sections"]["EIGHT_PERIODS"]["data_validation"], "PARTIAL")

    def test_missing_finance_receipt_must_not_be_routine(self):
        _, v = report_for(logs={"FINANCIAL_DAILY": ""})
        self.assertFalse(v["routine_continuation"])
        self.assertEqual(v["sections"]["FINANCIAL_DAILY"]["data_validation"], "UNVERIFIED")

    def test_malformed_finance_sweep_evidence_must_not_be_routine(self):
        _, v = report_for(logs={"FINANCIAL_DAILY":
            finance_log(scanned=None)})
        self.assertFalse(v["routine_continuation"])
        self.assertEqual(v["sections"]["FINANCIAL_DAILY"]["data_validation"], "UNVERIFIED")

    def test_adjustment_receipt_without_processed_batch_must_not_be_routine(self):
        _, v = report_for(logs={"ADJUSTMENTS_ROTATING":
            adjustments_log(processed=0)})
        self.assertFalse(v["routine_continuation"])
        self.assertEqual(v["sections"]["ADJUSTMENTS_ROTATING"]["data_validation"], "UNVERIFIED")

    def test_runner_error_and_incomplete_stage_set_must_not_be_routine(self):
        _, with_error = report_for(errors=["RUNNER: unexpected failure"])
        self.assertFalse(with_error["routine_continuation"])
        _, incomplete = report_for(completed=["EIGHT_PERIODS"])
        self.assertFalse(incomplete["routine_continuation"])

    def test_no_source_completeness_proof_is_not_false_pass(self):
        _, v = report_for(logs={"FINANCIAL_DAILY":
            finance_log(pending=0, remaining=0, scanned=True)})
        self.assertFalse(v["routine_continuation"])
        self.assertEqual(v["sections"]["FINANCIAL_DAILY"]["data_validation"], "UNVERIFIED")

    def test_sender_requires_both_policy_marker_and_success_status(self):
        run, v = report_for()
        run["validation"] = v
        run["operational_classification"] = "ROUTINE_CONTINUATION"
        run["status"] = "PARTIAL"
        self.assertNotIn("正常轮换，仍有待审", PUSH._report_text(run).splitlines()[1])
        run["status"] = "SUCCESS"
        run["operational_classification"] = "UNKNOWN"
        self.assertNotIn("正常轮换，仍有待审", PUSH._report_text(run).splitlines()[1])


if __name__ == "__main__":
    unittest.main()
