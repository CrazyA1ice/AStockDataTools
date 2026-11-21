"""V2G task routing model is pure and deliberately never executable."""
from __future__ import annotations

import inspect
import unittest

import market_center_v2g_workflow as W


class GuidedWorkflowModelTests(unittest.TestCase):
    def test_four_routes_are_unique_and_in_expected_order(self):
        self.assertEqual(W.allowed_ui_routes(),
                         ("update", "audit", "diagnose", "manage"))
        self.assertEqual(len(set(W.allowed_ui_routes())), 4)

    def test_each_route_has_clear_steps_and_honest_availability(self):
        for key in W.allowed_ui_routes():
            item = W.task_by_id(key)
            with self.subTest(task=key):
                self.assertGreaterEqual(len(item["steps"]), 3)
                self.assertTrue(item["availability"])
                self.assertIn(item["title"], W.workflow_guide(key))

    def test_unknown_route_fails_closed(self):
        for key in ("", "download", "repair", "sudo", "../update"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "unknown"):
                    W.task_by_id(key)

    def test_missing_receipt_never_suggests_download(self):
        report = W.recommended_task(None)
        self.assertEqual(report["task_id"], "audit")
        self.assertFalse(report["can_execute_repair"])
        self.assertIn("证据", report["reason"])

    def test_partial_execution_recommends_diagnostics_only(self):
        for value in ("PARTIAL", "FAIL", "FAILED", "ERROR"):
            with self.subTest(value=value):
                result = W.recommended_task({"execution_validation": value})
                self.assertEqual(result["task_id"], "diagnose")
                self.assertFalse(result["can_execute_repair"])

    def test_quality_issue_without_execution_issue_recommends_audit(self):
        r = W.recommended_task({
            "execution_validation": "PASS", "data_validation": "FAIL"})
        self.assertEqual(r["task_id"], "audit")
        self.assertFalse(r["can_execute_repair"])

    def test_pass_is_not_historical_coverage_certification(self):
        r = W.recommended_task({
            "execution_validation": "PASS", "data_validation": "PASS"})
        self.assertEqual(r["task_id"], "audit")
        self.assertIn("历史完整性", r["reason"])

    def test_historic_qmt_status_never_infers_repair_permission(self):
        r = W.recommended_task({
            "execution_validation": "PARTIAL", "qmt_recent_preflight": "CONNECTED"})
        self.assertEqual(r["task_id"], "diagnose")
        self.assertFalse(r["can_execute_repair"])

    def test_task_model_does_not_import_or_call_execution_stack(self):
        src = inspect.getsource(W)
        for forbidden in ("subprocess", "os.system", "xtquant",
                          "download_financial_data2(", "open(",
                          "write_bytes(", "write_text("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, src)
        self.assertTrue(W.execution_is_disabled())


if __name__ == "__main__":
    unittest.main()
