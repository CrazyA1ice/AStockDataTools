"""V2G2 synthetic market audit review model: no QMT and no data writes."""
from __future__ import annotations

import inspect
import unittest

import market_center_v2g2_audit_review as R


def example_row(code="RECORDS_PRESENT_NOT_CERTIFIED"):
    return {
        "symbol": "000001.SZ", "period": "day",
        "label_day": "2026-11-19",
        "rows": 1 if code == "RECORDS_PRESENT_NOT_CERTIFIED" else 0,
        "interpretation": code, "physical_status": "NO_ROWS_OBSERVED",
        "anomalies": {},
    }


def report(*rows):
    return {
        "market_file_writes": False,
        "qmt_calls": 0,
        "scope": {"start": "2026-11-19", "end": "2026-11-19",
                  "stocks": ["000001.SZ"], "periods": ["day"]},
        "evidence_interpretation": {
            "status": "V2B2_EVIDENCE_GATED_CANDIDATES_NOT_CERTIFIED",
            "allowed_repair_or_backfill": False,
            "source_authenticity_certified": False,
            "confirmed_missing_count": 0,
            "observations": list(rows),
        },
    }


class V2G2ReadOnlyReviewModelTests(unittest.TestCase):
    def test_all_actual_b2_interpretations_have_specific_guidance(self):
        self.assertEqual(len(R.MARKET_INTERPRETATIONS), 12)
        for code in R.MARKET_INTERPRETATIONS:
            with self.subTest(code=code):
                item = R.explain_observation(example_row(code))
                self.assertTrue(item["next_step"])
                self.assertTrue(item["required_evidence"])
                self.assertFalse(item["can_repair"])
                self.assertFalse(item["can_download"])
                self.assertFalse(item["finance_fault_link_certified"])

    def test_records_present_never_means_full_history_coverage(self):
        item = R.explain_observation(example_row())
        self.assertIn("未认证", item["title"])
        self.assertFalse(item["can_repair"])

    def test_missing_candidates_are_never_confirmed(self):
        for code in R.CANDIDATES:
            with self.subTest(code=code):
                item = R.explain_observation(example_row(code))
                self.assertEqual(item["confirmed_missing_count"], 0)
                self.assertFalse(item["can_download"])

    def test_week_month_label_does_not_claim_trading_day(self):
        row = example_row("LONG_CYCLE_LABEL_NEEDS_CLOSURE_PROOF")
        row["period"] = "week"
        item = R.explain_observation(row)
        self.assertIn("起止范围", item["next_step"])
        self.assertFalse(item["can_repair"])

    def test_market_physical_anomaly_cannot_be_labeled_finance_qmt_fault(self):
        item = R.explain_observation(example_row(
            "PHYSICAL_ANOMALY_NEEDS_REVIEW"))
        self.assertNotIn("QMT_FINANCE_CONNECTION_LOST", item["title"])
        self.assertFalse(item["finance_fault_link_certified"])
        checklist = R.format_review_text(item)
        self.assertIn("财务任务故障日志不能", checklist)

    def test_summary_counts_observations_without_conferring_write(self):
        value = R.summarize_readonly_report(report(
            example_row(), example_row("PHYSICAL_ANOMALY_NEEDS_REVIEW"),
            example_row("MISSING_CANDIDATE_SOURCE_AUTHENTICITY_UNVERIFIED"),
            example_row("NO_ROWS_CALENDAR_AND_ELIGIBILITY_UNKNOWN")))
        self.assertEqual(value["observation_count"], 4)
        self.assertEqual(value["alert_count"], 1)
        self.assertEqual(value["candidate_count"], 1)
        self.assertEqual(value["unknown_count"], 1)
        self.assertEqual(value["confirmed_missing_count"], 0)
        self.assertFalse(value["can_repair"])

    def test_no_observations_cannot_claim_full_completeness(self):
        value = R.summarize_readonly_report(report())
        self.assertIn("没有可供复核", value["title"])
        self.assertFalse(value["can_download"])

    def test_bad_or_nonreadonly_report_fails_closed(self):
        for mutation in (
            {"market_file_writes": True}, {"qmt_calls": 1},
            {"evidence_interpretation": {"allowed_repair_or_backfill": True}},
            {"evidence_interpretation": {"status": "CERTIFIED"}},
        ):
            data = report(example_row())
            data.update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaises(R.AuditFlowBlocked):
                    R.summarize_readonly_report(data)

    def test_unknown_row_interpretation_blocked_without_guessing(self):
        with self.assertRaisesRegex(
                R.AuditFlowBlocked, "unknown_interpretation"):
            R.explain_observation(example_row("CERTIFIED_MISSING_DOWNLOAD"))

    def test_bad_row_identity_or_negative_count_rejected(self):
        for key, value in (("symbol", None), ("period", 1),
                           ("label_day", None), ("rows", -1)):
            with self.subTest(key=key):
                item = example_row()
                item[key] = value
                with self.assertRaises(R.AuditFlowBlocked):
                    R.explain_observation(item)

    def test_checklist_is_readonly_and_does_not_offer_an_apply_command(self):
        value = R.format_review_text(R.explain_observation(example_row()))
        self.assertIn("禁止自动下载", value)
        for term in ("--apply", "覆盖写入", "xtdata.download", "resume --online"):
            self.assertNotIn(term, value)
        with self.assertRaises(R.AuditFlowBlocked):
            R.format_review_text({"can_download": True, "can_repair": False,
                                  "market_file_writes": False})

    def test_review_model_is_pure_and_has_no_execution_or_network_api(self):
        source = inspect.getsource(R)
        for term in ("import xtquant", "import requests",
                     "subprocess.Popen", "os.system(",
                     "write_bytes(", "write_text(", "market_root.mkdir("):
            self.assertNotIn(term, source)


if __name__ == "__main__":
    unittest.main()
