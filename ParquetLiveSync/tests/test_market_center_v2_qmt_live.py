"""Synthetic V2-D2 explicit QMT availability probes and gate presentation.

No real QMT connections, history downloads, market writes, or user state edits.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import market_center_v2_qmt_live as Q
import market_center_v2_qmt_live_cli as CLI
import market_center_v2_preview as UI
import market_center_v2_faults as F

CN = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 20, 21, 35, tzinfo=CN)
STATIC = {
    "status": "PREVIEW_CHECKS_PASSED_EXECUTION_STILL_DISABLED",
    "allowed_to_execute": False,
    "blockers": [],
}


class ExplicitQMTObservationTests(unittest.TestCase):
    def test_explicit_probe_success_still_is_not_permission(self):
        fake = Mock(return_value=(True, "xtdata_get_client_connected"))
        result = Q.observe_qmt_connection(now=NOW, probe=fake)
        fake.assert_called_once_with(timeout_seconds=15)
        self.assertEqual(result["status"], "QMT_CONNECTION_OBSERVED_ONLY")
        self.assertTrue(result["connected_now"])
        self.assertFalse(result["connection_stability_certified"])
        self.assertFalse(result["allowed_to_execute"])
        self.assertFalse(result["allowed_to_download"])
        self.assertFalse(result["allowed_to_modify_finance_progress"])
        self.assertEqual(result["download_calls"], 0)
        self.assertEqual(result["qmt_connection_attempts"], 1)

    def test_connection_down_is_not_fabricated_success(self):
        result = Q.observe_qmt_connection(
            now=NOW, probe=lambda **kwargs: (False, "xtdata_exit_1"))
        self.assertEqual(result["status"], "QMT_CONNECTION_UNAVAILABLE")
        self.assertFalse(result["connected_now"])
        self.assertFalse(result["allowed_to_execute"])

    def test_scheduled_protection_blocks_without_qmt_import_or_probe(self):
        for hh, mm in ((19, 55), (20, 5), (20, 19)):
            with self.subTest(time=(hh, mm)):
                fake = Mock(side_effect=AssertionError("forbidden"))
                result = Q.observe_qmt_connection(
                    now=NOW.replace(hour=hh, minute=mm), probe=fake)
                fake.assert_not_called()
                self.assertEqual(
                    result["status"], "QMT_CONNECTION_PROBE_SCHEDULE_BLOCKED")
                self.assertEqual(result["qmt_connection_attempts"], 0)

    def test_outside_window_can_probe_but_never_download(self):
        for hh, mm in ((19, 54), (20, 20)):
            with self.subTest(time=(hh, mm)):
                fake = Mock(return_value=(True, "connected"))
                result = Q.observe_qmt_connection(
                    now=NOW.replace(hour=hh, minute=mm), probe=fake)
                fake.assert_called_once()
                self.assertEqual(result["download_calls"], 0)

    def test_probe_exception_fails_closed_and_hides_sensitive_detail(self):
        result = Q.observe_qmt_connection(
            now=NOW, probe=Mock(side_effect=OSError("private path here")))
        self.assertEqual(result["status"], "QMT_CONNECTION_PROBE_FAILED")
        self.assertEqual(result["detail"], "probe_exception_OSError")
        self.assertNotIn("private path", str(result))
        self.assertFalse(result["connected_now"])

    def test_provider_malformed_probe_response_fails_closed(self):
        for response in ((1, "connected"), (True, None), "connected"):
            with self.subTest(response=response):
                result = Q.observe_qmt_connection(
                    now=NOW, probe=lambda **kwargs: response)
                self.assertEqual(result["status"], "QMT_CONNECTION_PROBE_FAILED")
                self.assertFalse(result["connected_now"])

    def test_invalid_timeouts_rejected_before_any_connection(self):
        for timeout in (-1, 0, 4, 26, 30, 15.0, True):
            fake = Mock()
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    Q.observe_qmt_connection(
                        now=NOW, probe=fake, timeout_seconds=timeout)
                fake.assert_not_called()

    def test_naive_clock_is_refused_without_probe(self):
        fake = Mock()
        with self.assertRaisesRegex(ValueError, "timezone_aware"):
            Q.observe_qmt_connection(
                now=NOW.replace(tzinfo=None), probe=fake)
        fake.assert_not_called()

    def test_pure_helper_import_does_not_call_xtquant(self):
        source = inspect.getsource(Q)
        self.assertNotIn("download_financial_data2", source)
        self.assertNotIn("get_financial_data(", source)
        self.assertNotIn("xtdata.download", source)
        self.assertIn("probe_once", source)
        self.assertIn("allowed_to_execute", source)

    def test_static_no_blockers_must_show_four_unmet_execution_gates(self):
        gates = Q.outstanding_resume_gates(STATIC)
        self.assertEqual(len(gates), 5)
        self.assertEqual([x["ok"] for x in gates],
                         [True, False, False, False, False])

    def test_connected_probe_clears_only_qmt_observation_gate(self):
        observation = Q.observe_qmt_connection(
            now=NOW, probe=lambda **kwargs: (True, "connected"))
        gates = Q.outstanding_resume_gates(STATIC, qmt_observation=observation)
        self.assertEqual([x["ok"] for x in gates],
                         [True, True, False, False, False])
        self.assertIn("不能保证", gates[1]["detail"])

    def test_blocked_static_evidence_is_not_overridden_by_connection(self):
        p = {"status": "PREVIEW_BLOCKED", "allowed_to_execute": False}
        observation = {"status": "QMT_CONNECTION_OBSERVED_ONLY",
                       "connected_now": True}
        gates = Q.outstanding_resume_gates(p, qmt_observation=observation)
        self.assertFalse(gates[0]["ok"])
        self.assertFalse(gates[2]["ok"])
        self.assertFalse(gates[-1]["ok"])

    def test_gui_only_connects_on_click_never_refresh_or_startup(self):
        ui = inspect.getsource(UI.MarketCenterV2)
        start = inspect.getsource(UI.MarketCenterV2.start_qmt_live_probe)
        refresh = inspect.getsource(UI.MarketCenterV2.refresh_overview)
        self.assertIn("command=self.start_qmt_live_probe", ui)
        self.assertIn('state="disabled"', ui)
        self.assertIn("observe_qmt_connection(timeout_seconds=15)", start)
        self.assertNotIn("observe_qmt_connection(", refresh)
        self.assertNotIn("subprocess.Popen", ui)

    def test_gui_exposes_five_gates_and_compact_error_table(self):
        source = inspect.getsource(UI.MarketCenterV2.build_fault_page)
        self.assertIn("恢复门禁逐项核对", source)
        self.assertIn("height=5", source)
        details = inspect.getsource(UI.MarketCenterV2._update_qmt_gate_display)
        self.assertIn("outstanding_resume_gates(", details)

    def test_empty_static_blockers_are_never_full_execution_approval(self):
        case = {
            "category": "QMT_FINANCE_CONNECTION_LOST",
            "failed_stock_batch": ["000756.SZ"],
            "last_checkpoint_in_log": "000755.SZ",
            "same_run_log_verified": True,
        }
        progress = {"daily_date": "2026-11-20",
                    "daily_cursor": "000755.SZ"}
        preview = F._finance_preview(case, progress, "2026-11-20", NOW)
        self.assertEqual(preview["blockers"], [])
        self.assertEqual(preview["blockers_scope"],
                         "static_evidence_and_time_only_not_execution")
        self.assertEqual(len(preview["execution_prerequisites_unverified"]), 4)
        self.assertFalse(preview["allowed_to_execute"])
        self.assertFalse(preview["allowed_to_download"])

    def test_elapsed_day_keeps_static_checkpoint_evidence_but_denies_replay(self):
        case = {
            "category": "QMT_FINANCE_CONNECTION_LOST",
            "failed_stock_batch": ["000756.SZ"],
            "last_checkpoint_in_log": "000755.SZ",
            "same_run_log_verified": True,
        }
        progress = {"daily_date": "2026-11-20",
                    "daily_cursor": "000755.SZ"}
        preview = F._finance_preview(
            case, progress, "2026-11-20", NOW + timedelta(days=1))
        self.assertTrue(preview["checks"]["same_run_log_and_cursor_checked"])
        self.assertIn("run_day_elapsed_do_not_replay_old_daily_window",
                      preview["blockers"])
        self.assertEqual(preview["status"], "PREVIEW_BLOCKED")
        self.assertFalse(preview["allowed_to_execute"])

    def test_cli_needs_explicit_connection_only_optin(self):
        with patch.object(CLI, "diagnose_latest") as read:
            with patch.object(CLI, "observe_qmt_connection") as probe:
                with patch("sys.stdout", io.StringIO()) as output:
                    status = CLI.main([
                        "--state-module", "D:/test/ParquetLiveSync"])
        self.assertEqual(status, 2)
        read.assert_not_called()
        probe.assert_not_called()
        self.assertIn("EXPLICIT_OPTIN_REQUIRED", output.getvalue())

    def test_cli_reports_available_without_authorizing_resume(self):
        observation = Q.observe_qmt_connection(
            now=NOW, probe=lambda **kwargs: (True, "connected"))
        fixture = {
            "run_day": "2026-11-20",
            "receipt_sha256": "a" * 64,
            "finance_progress_sha256": "b" * 64,
            "finance_resume_preview": STATIC,
        }
        with patch.object(CLI, "diagnose_latest", return_value=fixture):
            with patch.object(CLI, "observe_qmt_connection",
                              return_value=observation):
                with patch("sys.stdout", io.StringIO()) as output:
                    code = CLI.main([
                        "--state-module", "D:/test/ParquetLiveSync",
                        "--explicit-connect-only"])
        self.assertEqual(code, 0)
        parsed = json.loads(output.getvalue())
        self.assertFalse(parsed["allowed_to_execute"])
        self.assertFalse(parsed["allowed_to_download"])
        self.assertEqual(parsed["download_calls"], 0)
        self.assertEqual(
            [gate["ok"] for gate in parsed["recovery_gates"]],
            [True, True, False, False, False])

    def test_cli_does_not_probe_if_receipt_is_unreadable(self):
        with patch.object(CLI, "diagnose_latest",
                          side_effect=CLI.FaultEvidenceBlocked("invalid_receipt")):
            with patch.object(CLI, "observe_qmt_connection") as probe:
                with patch("sys.stdout", io.StringIO()) as output:
                    code = CLI.main([
                        "--state-module", "D:/test/ParquetLiveSync",
                        "--explicit-connect-only"])
        self.assertEqual(code, 2)
        probe.assert_not_called()
        self.assertIn("QMT_CONNECTION_PROBE_BLOCKED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
