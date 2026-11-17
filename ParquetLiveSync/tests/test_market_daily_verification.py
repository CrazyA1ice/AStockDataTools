"""Never equate a zero exit code with validated data or cross-sources."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import market_daily_verification as V


def receipt(marker, obj):
    return marker + json.dumps(obj, ensure_ascii=False) + "\n"


def market_log(status="ALL_EIGHT_PERIOD_PHASES_COMPLETE", sources=True):
    result = receipt("MARKET_EIGHT_PERIOD_SUMMARY=", {
        "status": status, "applied": True, "phases_blocked": {}})
    result += receipt("MARKET_DAILY_STAGED=", {
        "date": "2026-11-17", "accepted": 5000, "quarantine": 0})
    if sources:
        result += "MARKET_SOURCE_SAMPLE=eltdx status=AGREE agreed=8/8 attempted=8\n"
        result += "MARKET_SOURCE_SAMPLE=tencent status=AGREE agreed=8/8 attempted=8\n"
    return result


def finance_log(pending=17, remaining=5000, processed=5):
    return receipt("QMT_FINANCIAL_CACHE_IMPORT_SUMMARY=", {
        "mode": "daily", "apply": True,
        "status": "PAUSED_DATE_ROLLOVER" if remaining else "SOURCE_UNIVERSE_EXHAUSTED",
        "source_completeness_verified": False,
        "processed": processed, "pending_total": pending,
        "daily_remaining_unvisited": remaining,
        "daily_sweep_reached_end": remaining == 0})


def sector_log():
    return receipt("MARKET_QMT_EXTRA_SUMMARY=", {
        "status": "BATCH_COMMITTED_MORE_BATCHES_MAY_REMAIN",
        "sections": {"sectors": {"status": "UPDATED", "sectors": 30, "memberships": 650}}})


def adj_log(more=True):
    return receipt("MARKET_QMT_EXTRA_SUMMARY=", {
        "status": "BATCH_COMMITTED_MORE_BATCHES_MAY_REMAIN",
        "sections": {"adjustments": {
            "symbols_processed": 80, "universe_symbols": 5224,
            "next_batch_required": more}}})


class DailyVerificationTests(unittest.TestCase):
    def test_eight_period_cross_source_is_explicitly_sample_only(self):
        result = V.assess(
            "EIGHT_PERIODS", 0, market_log(),
            expected_sources={"eltdx", "tencent"})
        self.assertEqual(result["execution"], "PASS")
        self.assertEqual(result["data_validation"], "PASS")
        self.assertEqual(result["cross_validation"], "PASS")
        self.assertIn("抽样", result["detail"])

    def test_eight_period_zero_exit_without_samples_does_not_pass_cross(self):
        result = V.assess(
            "EIGHT_PERIODS", 0, market_log(sources=False),
            expected_sources={"eltdx", "tencent"})
        self.assertEqual(result["data_validation"], "PASS")
        self.assertEqual(result["cross_validation"], "UNVERIFIED")

    def test_zero_exit_with_no_new_day_does_not_fake_validation(self):
        log = receipt("MARKET_EIGHT_PERIOD_SUMMARY=", {
            "status": "ALL_EIGHT_PERIOD_PHASES_COMPLETE",
            "applied": True, "phases_blocked": {}})
        result = V.assess(
            "EIGHT_PERIODS", 0, log, expected_sources={"eltdx", "tencent"})
        self.assertEqual(result["data_validation"], "UNVERIFIED")
        self.assertEqual(result["cross_validation"], "UNVERIFIED")

    def test_quarantined_stocks_are_partial_not_clean_pass(self):
        log = market_log() + receipt("MARKET_DAILY_STAGED=", {
            "date": "2026-11-17", "accepted": 4980, "quarantine": 20})
        result = V.assess(
            "EIGHT_PERIODS", 0, log, expected_sources={"eltdx", "tencent"})
        self.assertEqual(result["data_validation"], "PARTIAL")

    def test_missing_one_required_source_does_not_pass_cross(self):
        log = receipt("MARKET_EIGHT_PERIOD_SUMMARY=", {
            "status": "ALL_EIGHT_PERIOD_PHASES_COMPLETE",
            "applied": True, "phases_blocked": {}})
        log += receipt("MARKET_DAILY_STAGED=", {
            "date": "2026-11-17", "accepted": 5000, "quarantine": 0})
        log += "MARKET_SOURCE_SAMPLE=eltdx status=AGREE agreed=8/8 attempted=8\n"
        result = V.assess(
            "EIGHT_PERIODS", 0, log, expected_sources={"eltdx", "tencent"})
        self.assertEqual(result["cross_validation"], "UNVERIFIED")

    def test_tencent_price_disagreement_reported_even_if_nonblocking(self):
        log = market_log()
        log += "MARKET_SOURCE_SAMPLE=tencent status=PRICE_DISAGREES agreed=3/8 attempted=8\n"
        result = V.assess(
            "EIGHT_PERIODS", 0, log, expected_sources={"eltdx", "tencent"})
        self.assertEqual(result["cross_validation"], "FAIL")

    def test_financial_existing_17_pending_are_visible_as_partial(self):
        result = V.assess("FINANCIAL_DAILY", 0, finance_log())
        self.assertEqual(result["execution"], "PASS")
        self.assertEqual(result["data_validation"], "PARTIAL")
        self.assertEqual(result["cross_validation"], "UNVERIFIED")
        self.assertEqual(result["pending_total"], 17)
        self.assertIn("待审17只", result["detail"])

    def test_financial_completed_without_historical_proof_still_unverified(self):
        result = V.assess(
            "FINANCIAL_DAILY", 0, finance_log(pending=0, remaining=0))
        self.assertEqual(result["data_validation"], "UNVERIFIED")

    def test_qmt_sector_and_adjustments_lack_independent_source(self):
        sector = V.assess("SECTORS", 0, sector_log())
        adj = V.assess("ADJUSTMENTS_ROTATING", 0, adj_log())
        self.assertEqual(sector["data_validation"], "PASS")
        self.assertEqual(sector["cross_validation"], "UNVERIFIED")
        self.assertEqual(adj["data_validation"], "PARTIAL")
        self.assertEqual(adj["cross_validation"], "UNVERIFIED")

    def test_failed_or_missing_receipt_never_passes(self):
        self.assertEqual(
            V.assess("SECTORS", 4, sector_log())["data_validation"], "FAIL")
        self.assertEqual(
            V.assess("SECTORS", 0, "")["data_validation"], "UNVERIFIED")
        self.assertEqual(
            V.assess("SECTORS", None, "")["data_validation"], "NOT_RUN")

    def test_run_summary_mentions_failures_unknown_and_known_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {
                "EIGHT_PERIODS": market_log(),
                "FINANCIAL_DAILY": finance_log(),
                "SECTORS": sector_log(),
                "ADJUSTMENTS_ROTATING": adj_log(),
            }
            paths = {}
            for section, value in data.items():
                path = Path(tmp) / (section + ".log")
                path.write_text(value, encoding="utf-8")
                paths[section] = {"exit_code": 0, "log_path": str(path)}
            report = V.report({"stage_records": paths},
                              expected_sources={"eltdx", "tencent"})
            self.assertEqual(report["execution"], "PASS")
            self.assertEqual(report["data_validation"], "PARTIAL")
            self.assertEqual(report["cross_validation"], "UNVERIFIED")
            self.assertIn("数据校验部分通过", report["notification_text"])
            self.assertIn("跨源验证未验证", report["notification_text"])
            self.assertIn("财务：数据部分通过", report["notification_text"])
            paths["FINANCIAL_DAILY"]["exit_code"] = 1
            failed = V.report({"stage_records": paths},
                              expected_sources={"eltdx", "tencent"})
            self.assertEqual(failed["execution"], "PARTIAL")
            self.assertEqual(failed["data_validation"], "FAIL")
            self.assertIn("财务：数据失败", failed["notification_text"])


if __name__ == "__main__":
    unittest.main()
