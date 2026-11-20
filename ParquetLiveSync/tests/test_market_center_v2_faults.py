"""V2-D synthetic same-run fault diagnosis and non-executable resume preview.

No real QMT service, downloads, market file writes, or scheduler interaction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import market_center_v2_faults as F
import market_center_v2_fault_cli as CLI

CN = timezone(timedelta(hours=8))
TODAY = datetime(2026, 11, 20, 21, 10, tzinfo=CN)
RUN = "2026-11-20T20:05:02+08:00"
STAMP = "20261120-200502"
WORKER_GROUP = [
    "000756.SZ", "000757.SZ", "000758.SZ", "000759.SZ", "000761.SZ",
]


def fixture(path: Path, *, failed_stage="FINANCIAL_DAILY",
            fail_code=1, connection=True, log_checkpoint="000755.SZ",
            ledger_cursor="000755.SZ", daily_date="2026-11-20",
            run_status="PARTIAL", no_stage_log=False):
    module = path / "ParquetLiveSync"
    work = module / "work"
    (work / "qmt_extra").mkdir(parents=True)
    stage_records = {}
    sections = {
        "EIGHT_PERIODS": {"data_validation": "PASS", "cross_validation": "PASS"},
        "SECTORS": {"data_validation": "PASS", "cross_validation": "UNVERIFIED"},
        "ADJUSTMENTS_ROTATING": {
            "data_validation": "PARTIAL", "cross_validation": "UNVERIFIED",
            "detail": "QMT除权本批处理80只；后续仍有批次"},
        "FINANCIAL_DAILY": {
            "data_validation": "FAIL", "cross_validation": "UNVERIFIED",
            "detail": "步骤执行失败，旧数据未据此判为损坏"},
    }
    for stage in F.STAGES:
        p = work / f"afternoon-{STAMP}-{stage}.log"
        if stage == "FINANCIAL_DAILY":
            details = (
                F.CHECKPOINT +
                json.dumps({"cursor": log_checkpoint, "symbol": log_checkpoint},
                           ensure_ascii=False) + "\n" +
                ("Exception: 无法连接xtquant服务，请检查QMT\n" if connection else
                 "RuntimeError: unspecified financial stage failed\n") +
                "RuntimeError: QMT cache batch worker nonzero exit=1 stocks=" +
                json.dumps(WORKER_GROUP, ensure_ascii=False) + "\n"
            )
        else:
            details = "STAGE_COMPLETED=TRUE\n"
        if not no_stage_log:
            p.write_text(details, encoding="utf-8")
        stage_records[stage] = {
            "exit_code": fail_code if stage == failed_stage else 0,
            "log_path": str(p),
        }
    payload = {
        "status": run_status, "china_start": RUN,
        "qmt_preflight_status": "CONNECTED",
        "stage_records": stage_records,
        "validation": {"sections": sections},
    }
    (work / "last-afternoon-unified.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (work / "qmt_extra" / "financial-cache-progress.json").write_text(
        json.dumps({
            "format": "qmt_financial_cache_import_v1",
            "daily_cursor": ledger_cursor,
            "daily_date": daily_date,
            "pending": {f"000001.SZ": {"reason": "SOURCE_HISTORY_CONFLICT"}},
        }, ensure_ascii=False), encoding="utf-8")
    return module


class FaultDiagnosisTests(unittest.TestCase):
    def test_realistic_same_run_qmt_connection_failure_and_rotating_notice(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            result = F.diagnose_latest(root, now=TODAY)
            self.assertEqual(result["status"], "V2D_READONLY_FAULT_DIAGNOSIS_NOT_EXECUTABLE")
            self.assertEqual(result["fault_count"], 1)
            self.assertEqual(result["notice_count"], 1)
            self.assertEqual(result["warning_count"], 0)
            self.assertEqual(result["cases"][0]["category"],
                             "QMT_FINANCE_CONNECTION_LOST")
            self.assertEqual(result["cases"][1]["category"],
                             "ADJUSTMENTS_ROTATION_PENDING")
            self.assertEqual(result["cases"][0]["failed_stock_batch"], WORKER_GROUP)
            self.assertEqual(result["cases"][0]["last_checkpoint_in_log"], "000755.SZ")
            self.assertTrue(result["cases"][0]["same_run_log_verified"])
            self.assertFalse(result["allowed_to_execute"])
            self.assertFalse(result["market_file_writes"])
            self.assertEqual(result["qmt_calls"], 0)

    def test_preview_can_pass_only_evidence_checks_never_execute(self):
        with TemporaryDirectory() as temp:
            report = F.diagnose_latest(fixture(Path(temp)), now=TODAY)
            p = report["finance_resume_preview"]
            self.assertEqual(p["status"],
                             "PREVIEW_CHECKS_PASSED_EXECUTION_STILL_DISABLED")
            self.assertEqual(p["saved_daily_cursor"], "000755.SZ")
            self.assertEqual(p["failed_batch"], WORKER_GROUP)
            self.assertEqual(p["blockers"], [])
            self.assertFalse(p["allowed_to_execute"])
            self.assertFalse(p["allowed_to_download"])
            self.assertFalse(p["allowed_to_modify_progress"])
            self.assertFalse(p["checks"]["qmt_connected_now_verified"])
            self.assertFalse(p["checks"]["writer_mutex_free_verified"])
            self.assertFalse(p["checks"]["canonical_deployed_worker_version_verified"])

    def test_resume_blocks_when_ledger_cursor_changed(self):
        with TemporaryDirectory() as temp:
            p = F.diagnose_latest(
                fixture(Path(temp), ledger_cursor="000756.SZ"), now=TODAY)
            self.assertIn("financial_cursor_changed_since_failure",
                          p["finance_resume_preview"]["blockers"])
            self.assertEqual(p["finance_resume_preview"]["status"], "PREVIEW_BLOCKED")

    def test_resume_blocks_when_date_changed(self):
        with TemporaryDirectory() as temp:
            p = F.diagnose_latest(fixture(Path(temp)), now=TODAY + timedelta(days=1))
            self.assertIn("run_day_elapsed_do_not_replay_old_daily_window",
                          p["finance_resume_preview"]["blockers"])
            self.assertFalse(p["finance_resume_preview"]["allowed_to_execute"])

    def test_resume_blocks_during_scheduled_window(self):
        with TemporaryDirectory() as temp:
            now = datetime(2026, 11, 20, 20, 6, tzinfo=CN)
            p = F.diagnose_latest(fixture(Path(temp)), now=now)
            self.assertIn("reserved_2005_automatic_schedule_window",
                          p["finance_resume_preview"]["blockers"])

    def test_missing_same_run_stage_log_never_uses_other_run_evidence(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp), no_stage_log=True)
            p = F.diagnose_latest(root, now=TODAY)
            self.assertEqual(p["cases"][0]["category"], "FAILED_LOG_UNVERIFIED")
            self.assertFalse(p["cases"][0]["same_run_log_verified"])
            self.assertIn("not_a_verified_finance_connect_outage",
                          p["finance_resume_preview"]["blockers"])

    def test_stale_log_filename_is_rejected_even_inside_work(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            receipt = root / "work" / "last-afternoon-unified.json"
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            oldlog = root / "work" / "afternoon-20261119-200502-FINANCIAL_DAILY.log"
            oldlog.write_text("无法连接xtquant服务\n", encoding="utf-8")
            payload["stage_records"]["FINANCIAL_DAILY"]["log_path"] = str(oldlog)
            receipt.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            p = F.diagnose_latest(root, now=TODAY)
            self.assertEqual(p["cases"][0]["category"], "FAILED_LOG_UNVERIFIED")

    def test_outside_work_path_is_rejected_even_with_correct_filename(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            receipt = root / "work" / "last-afternoon-unified.json"
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            outside = Path(temp) / f"afternoon-{STAMP}-FINANCIAL_DAILY.log"
            outside.write_text("无法连接xtquant服务\n", encoding="utf-8")
            payload["stage_records"]["FINANCIAL_DAILY"]["log_path"] = str(outside)
            receipt.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            p = F.diagnose_latest(root, now=TODAY)
            self.assertEqual(p["cases"][0]["category"], "FAILED_LOG_UNVERIFIED")

    def test_bad_financial_snapshot_blocks_without_guessing_cursor(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp), daily_date="2026-11-19")
            p = F.diagnose_latest(root, now=TODAY)
            self.assertIn("saved_daily_date_differs_from_failed_run",
                          p["finance_resume_preview"]["blockers"])

    def test_missing_failed_batch_blocks_resumption(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            finance_log = root / "work" / f"afternoon-{STAMP}-FINANCIAL_DAILY.log"
            finance_log.write_text(
                F.CHECKPOINT + '{"cursor":"000755.SZ"}\n' +
                "Exception: 无法连接xtquant服务\n",
                encoding="utf-8")
            p = F.diagnose_latest(root, now=TODAY)
            self.assertEqual(p["cases"][0]["category"], "QMT_FINANCE_CONNECTION_LOST")
            self.assertEqual(p["cases"][0]["failed_stock_batch"], [])
            self.assertIn("failed_batch_not_anchored",
                          p["finance_resume_preview"]["blockers"])

    def test_unknown_stage_error_does_not_masquerade_as_qmt_disconnect(self):
        with TemporaryDirectory() as temp:
            p = F.diagnose_latest(
                fixture(Path(temp), connection=False), now=TODAY)
            self.assertEqual(p["cases"][0]["category"], "STAGE_FAILURE_UNCLASSIFIED")
            self.assertFalse(p["cases"][0]["automatic_repair_allowed"])

    def test_healthy_finance_is_not_wrongly_reported_failed(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp), failed_stage="EIGHT_PERIODS")
            receipt = root / "work" / "last-afternoon-unified.json"
            p = json.loads(receipt.read_text(encoding="utf-8"))
            p["validation"]["sections"]["FINANCIAL_DAILY"]["data_validation"] = "PASS"
            receipt.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
            result = F.diagnose_latest(root, now=TODAY)
            self.assertFalse(any(x["stage"] == "FINANCIAL_DAILY" for x in result["cases"]))

    def test_progress_receipt_absent_keeps_fault_but_blocks_resume(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            (root / "work" / "qmt_extra" / "financial-cache-progress.json").unlink()
            p = F.diagnose_latest(root, now=TODAY)
            self.assertEqual(p["cases"][0]["category"], "QMT_FINANCE_CONNECTION_LOST")
            self.assertIn("financial_progress_missing_or_invalid",
                          p["finance_resume_preview"]["blockers"])

    def test_qmt_preflight_connection_failure_is_not_finance_corruption(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            receipt = root / "work" / "last-afternoon-unified.json"
            p = json.loads(receipt.read_text(encoding="utf-8"))
            p["qmt_preflight_status"] = "QMT_SERVICE_UNAVAILABLE"
            receipt.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
            result = F.diagnose_latest(root, now=TODAY)
            self.assertTrue(any(x["category"] == "QMT_PRECHECK_UNAVAILABLE"
                                for x in result["cases"]))

    def test_cross_source_sample_disagreement_is_separate_from_execution(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            receipt = root / "work" / "last-afternoon-unified.json"
            p = json.loads(receipt.read_text(encoding="utf-8"))
            p["validation"]["sections"]["EIGHT_PERIODS"]["cross_validation"] = "FAIL"
            receipt.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
            result = F.diagnose_latest(root, now=TODAY)
            self.assertTrue(any(x["category"] == "CROSS_SOURCE_SAMPLE_DISAGREEMENT"
                                for x in result["cases"]))

    def test_cli_requires_optin_before_accessing_private_state(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            result = CLI.main(["--state-module", str(root)])
            self.assertEqual(result, 2)

    def test_cli_emits_non_executable_report(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            stdout = io.StringIO()
            with patch.object(CLI, "diagnose_latest",
                              side_effect=lambda path: F.diagnose_latest(path, now=TODAY)):
                with patch("sys.stdout", stdout):
                    exit_code = CLI.main([
                        "--state-module", str(root), "--explicit-readonly"])
            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertFalse(data["allowed_to_execute"])
            self.assertFalse(data["finance_resume_preview"]["allowed_to_execute"])
            self.assertEqual(data["fault_count"], 1)
            self.assertFalse(data["market_file_writes"])

    def test_gui_error_panel_never_offers_process_launch(self):
        import inspect
        import market_center_v2_preview as UI
        view = inspect.getsource(UI.MarketCenterV2.build_home)
        self.assertIn("错误诊断与快速恢复建议", view)
        self.assertIn("command=self.open_fault_page", view)
        self.assertIn("command=self.copy_finance_resume_preview", view)
        details = inspect.getsource(UI.MarketCenterV2.build_fault_page)
        self.assertIn('state="disabled"', details)
        source = inspect.getsource(UI.MarketCenterV2)
        self.assertNotIn("subprocess.Popen", source)
        self.assertNotIn("download_financial_data2", source)

    def test_redirected_private_progress_is_refused_without_outside_read(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            original = root / "work" / "qmt_extra" / "financial-cache-progress.json"
            other = Path(temp) / "outside.json"
            other.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
            original.unlink()
            try:
                original.symlink_to(other)
            except (OSError, NotImplementedError):
                self.skipTest("Windows symlink privileges unavailable")
            report = F.diagnose_latest(root, now=TODAY)
            self.assertEqual(report["cases"][0]["category"],
                             "QMT_FINANCE_CONNECTION_LOST")
            self.assertIn("financial_progress_missing_or_invalid",
                          report["finance_resume_preview"]["blockers"])

    def test_small_dashboard_is_scrollable_with_diagnostic_cards(self):
        import inspect
        import market_center_v2_preview as UI
        content = inspect.getsource(UI.MarketCenterV2.build_home)
        self.assertIn("canvas = tk.Canvas(self.home", content)
        self.assertIn('orient="vertical", command=canvas.yview', content)
        self.assertIn("canvas.itemconfigure(slot, width=event.width)", content)
        self.assertIn("错误诊断与快速恢复建议", content)

    def test_short_latest_receipt_validation_none_keeps_diagnosis_readonly(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            receipt = root / "work" / "last-afternoon-unified.json"
            obj = json.loads(receipt.read_text(encoding="utf-8"))
            obj["validation"] = None
            receipt.write_text(json.dumps(obj), encoding="utf-8")
            result = F.diagnose_latest(root, now=TODAY)
            self.assertEqual(result["cases"][0]["category"],
                             "QMT_FINANCE_CONNECTION_LOST")
            self.assertFalse(result["allowed_to_execute"])

    def test_repeated_diagnosis_only_reads_inputs_no_state_mutation(self):
        with TemporaryDirectory() as temp:
            root = fixture(Path(temp))
            paths = [
                root / "work" / "last-afternoon-unified.json",
                root / "work" / "qmt_extra" / "financial-cache-progress.json",
            ]
            before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
            one = F.diagnose_latest(root, now=TODAY)
            two = F.diagnose_latest(root, now=TODAY)
            after = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
            self.assertEqual(before, after)
            self.assertEqual(one["receipt_sha256"], two["receipt_sha256"])
            self.assertFalse(one["allowed_to_execute"])


if __name__ == "__main__":
    unittest.main()
