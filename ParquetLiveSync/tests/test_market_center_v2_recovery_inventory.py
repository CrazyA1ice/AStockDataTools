"""V2-D2B bounded file fingerprints and backup-scope planning; synthetic only.

Never start or connect QMT, never write/copy production data, never acquire the
20:05 mutex. Test fixtures use fresh TemporaryDirectory roots exclusively.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import inspect
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import market_center_v2_recovery_inventory as I
import market_center_v2_recovery_inventory_cli as CLI
import market_center_v2_qmt_live as Q
import market_center_v2_preview as UI

CN = timezone(timedelta(hours=8))
TIME = datetime(2026, 11, 20, 23, 15, tzinfo=CN)
DAY = "2026-11-20"
GROUP = ["000756.SZ", "000757.SZ", "000758.SZ",
         "000759.SZ", "000761.SZ"]


def fixture(base: Path):
    module = base / "ParquetLiveSync"
    market = base / "AllCycleAStockData"
    module.mkdir()
    market.mkdir()
    for name in I.CODE_FILES:
        (module / name).write_text("synthetic:" + name, encoding="utf-8")
    finance = market / "qmt_extra" / "financial"
    finance.mkdir(parents=True)
    data = {
        "status": "V2D_READONLY_FAULT_DIAGNOSIS_NOT_EXECUTABLE",
        "receipt_sha256": "a" * 64,
        "finance_progress_sha256": "b" * 64,
        "run_day": DAY,
        "finance_resume_preview": {
            "status": "PREVIEW_CHECKS_PASSED_EXECUTION_STILL_DISABLED",
            "saved_daily_cursor": "000755.SZ",
            "failed_batch": GROUP,
            "allowed_to_execute": False,
            "blockers": [],
        },
    }
    return module, market, data


class ReadOnlyFinanceInventoryTests(unittest.TestCase):
    def read(self, module, market, report, **options):
        with patch.object(I, "diagnose_latest", return_value=report) as diag:
            outcome = I.inspect_recovery_prerequisites(
                state_module=module, market_root=market,
                now=options.pop("now", TIME))
            diag.assert_called_once()
            return outcome

    def test_valid_scope_fingerprints_five_code_files_not_approved(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            result = self.read(module, market, report)
            self.assertEqual(len(result["code_fingerprints"]), 5)
            self.assertTrue(all(x["status"] ==
                                "FINGERPRINT_OBSERVED_NOT_APPROVED"
                                for x in result["code_fingerprints"]))
            self.assertEqual(result["finance_scope_count"], 45)
            self.assertTrue(result["finance_storage_found"])
            self.assertFalse(result["canonical_code_hash_approved"])
            self.assertFalse(result["can_execute"])
            self.assertFalse(result["can_download"])
            self.assertFalse(result["can_modify_finance_progress"])
            self.assertEqual(result["qmt_calls"], 0)
            self.assertEqual(result["files_created"], 0)

    def test_code_digest_is_raw_sha256_observation_only(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            source = module / I.CODE_FILES[0]
            expected = sha256(source.read_bytes()).hexdigest()
            result = self.read(module, market, report)
            first = result["code_fingerprints"][0]
            self.assertEqual(first["sha256"], expected)
            self.assertFalse(first["approved"])
            source.write_text("new synthetic version", encoding="utf-8")
            changed = self.read(module, market, report)
            self.assertNotEqual(changed["code_fingerprints"][0]["sha256"], expected)
            self.assertFalse(changed["can_execute"])

    def test_failure_scope_pins_and_snapshot_candidates_stat_only(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            root = market / "qmt_extra" / "financial" / "Capital" / GROUP[0]
            (root / "snapshots").mkdir(parents=True)
            (root / "active").mkdir()
            (root / "snapshots" / (DAY + "-0123456789abcdef.parquet")).write_bytes(b"ABC")
            (root / "active" / (DAY + ".json")).write_text(
                '{"format":"synthetic"}', encoding="utf-8")
            before = [(p, p.read_bytes(), p.stat().st_mtime_ns)
                      for p in root.rglob("*") if p.is_file()]
            result = self.read(module, market, report)
            matching = [x for x in result["finance_scope_inventory"]
                        if x["table"] == "Capital" and x["symbol"] == GROUP[0]]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["candidate_count"], 1)
            self.assertFalse(matching[0]["backup_created"])
            self.assertFalse(matching[0]["pin_references_verified"])
            self.assertEqual(matching[0]["same_day_snapshot_candidates"][0]["bytes"], 3)
            self.assertGreater(result["backup_plan"]["estimated_candidate_bytes"], 3)
            after = [(p, p.read_bytes(), p.stat().st_mtime_ns)
                     for p in root.rglob("*") if p.is_file()]
            self.assertEqual(before, after)

    def test_absence_of_failed_stock_snapshot_not_labeled_corruption(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            result = self.read(module, market, report)
            self.assertTrue(all(x["candidate_count"] == 0
                                for x in result["finance_scope_inventory"]))
            self.assertFalse(result["backup_plan"]["backup_created"])
            self.assertFalse(result["can_execute"])

    def test_missing_storage_root_is_reported_not_created(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            (market / "qmt_extra" / "financial").rmdir()
            result = self.read(module, market, report)
            self.assertFalse(result["finance_storage_found"])
            self.assertEqual(result["finance_scope_count"], 0)
            self.assertIn("finance_storage_root_not_found", result["blockers"])
            self.assertFalse((market / "qmt_extra" / "financial").exists())

    def test_unapproved_code_missing_never_approved(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            (module / I.CODE_FILES[0]).unlink()
            result = self.read(module, market, report)
            self.assertIn("canonical_code_files_missing", result["blockers"])
            self.assertFalse(result["canonical_code_hash_approved"])
            self.assertFalse(result["can_execute"])

    def test_oversized_code_file_rejected_before_hash(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            (module / I.CODE_FILES[0]).write_bytes(b"x" * (I.MAX_CODE_BYTES + 1))
            with patch.object(I, "diagnose_latest", return_value=report):
                with self.assertRaisesRegex(I.PreflightBlocked, "oversized"):
                    I.inspect_recovery_prerequisites(
                        state_module=module, market_root=market, now=TIME)

    def test_invalid_failed_symbol_or_unsorted_group_rejected(self):
        for scope in (["000756.SZ", "bad"], ["000757.SZ", "000756.SZ"],
                      ["000756.SZ"] * 2):
            with self.subTest(scope=scope), TemporaryDirectory() as tmp:
                module, market, report = fixture(Path(tmp))
                report["finance_resume_preview"]["failed_batch"] = scope
                with patch.object(I, "diagnose_latest", return_value=report):
                    with self.assertRaisesRegex(
                            I.PreflightBlocked, "untrusted_failed_batch_scope"):
                        I.inspect_recovery_prerequisites(
                            state_module=module, market_root=market, now=TIME)

    def test_inventory_candidate_count_cap_is_fail_closed(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            snapshots = (market / "qmt_extra" / "financial" / "Capital"
                         / GROUP[0] / "snapshots")
            snapshots.mkdir(parents=True)
            for i in range(I.MAX_SNAPSHOTS_PER_SCOPE + 1):
                (snapshots / (DAY + f"-{i:016x}.parquet")).write_bytes(b"x")
            with patch.object(I, "diagnose_latest", return_value=report):
                with self.assertRaisesRegex(I.PreflightBlocked, "too_many"):
                    I.inspect_recovery_prerequisites(
                        state_module=module, market_root=market, now=TIME)

    def test_redirected_snapshot_file_cannot_be_followed(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            outside = Path(tmp) / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            snapshots = (market / "qmt_extra" / "financial" / "Capital"
                         / GROUP[0] / "snapshots")
            snapshots.mkdir(parents=True)
            path = snapshots / (DAY + "-0123456789abcdef.parquet")
            try:
                path.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink privileges unavailable")
            with patch.object(I, "diagnose_latest", return_value=report):
                with self.assertRaisesRegex(I.PreflightBlocked, "redirected"):
                    I.inspect_recovery_prerequisites(
                        state_module=module, market_root=market, now=TIME)

    def test_noncanonical_paths_rejected_before_any_inventory(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            with patch.object(I, "diagnose_latest") as diag:
                with self.assertRaisesRegex(I.PreflightBlocked, "untrusted"):
                    I.inspect_recovery_prerequisites(
                        state_module=module.parent, market_root=market,
                        now=TIME)
                diag.assert_not_called()

    def test_near_2005_window_refuses_inventory_before_file_scan(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            for hour, minute in ((19, 50), (20, 5), (20, 24)):
                with self.subTest(clock=(hour, minute)):
                    with patch.object(I, "diagnose_latest") as read:
                        with self.assertRaisesRegex(
                                I.PreflightBlocked, "reserved_2005"):
                            I.inspect_recovery_prerequisites(
                                state_module=module, market_root=market,
                                now=TIME.replace(hour=hour, minute=minute))
                        read.assert_not_called()

    def test_cross_day_does_not_pretend_yesterday_is_today(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            report["finance_resume_preview"]["status"] = "PREVIEW_BLOCKED"
            tomorrow = TIME + timedelta(days=1)
            result = self.read(module, market, report, now=tomorrow)
            self.assertIn("CROSS_DAY_NO_OLD_DAILY_REPLAY",
                          result["resume_policy"])
            self.assertIn("previous_run_day_requires_daily_sweep_carry_forward_review",
                          result["blockers"])
            self.assertFalse(result["can_execute"])

    def test_zero_symbols_never_approves_unknown_failure(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            report["finance_resume_preview"]["failed_batch"] = []
            result = self.read(module, market, report)
            self.assertIn("no_verified_failed_batch", result["blockers"])
            self.assertFalse(result["can_execute"])

    def test_static_gate_ok_still_all_unapproved_even_with_qmt_success(self):
        with TemporaryDirectory() as tmp:
            module, market, report = fixture(Path(tmp))
            result = self.read(module, market, report)
            gate_rows = Q.outstanding_resume_gates(
                report["finance_resume_preview"],
                qmt_observation={
                    "status": "QMT_CONNECTION_OBSERVED_ONLY",
                    "connected_now": True,
                },
                inventory_observation=result)
            self.assertEqual([row["ok"] for row in gate_rows],
                             [True, True, False, False, False])
            self.assertIn("指纹", gate_rows[3]["detail"])
            self.assertIn("未复制备份", gate_rows[4]["detail"])

    def test_cli_requires_explicit_readonly_and_does_not_inventory(self):
        with patch.object(CLI, "inspect_recovery_prerequisites") as inspect_mock:
            with patch("sys.stdout", io.StringIO()) as output:
                status = CLI.main([
                    "--state-module", "D:/test/ParquetLiveSync",
                    "--market-root", "D:/test/AllCycleAStockData"])
            self.assertEqual(status, 2)
            inspect_mock.assert_not_called()
            self.assertIn("EXPLICIT_READONLY_OPTIN_REQUIRED", output.getvalue())

    def test_cli_makes_nonexecutable_json_only(self):
        with patch.object(CLI, "inspect_recovery_prerequisites",
                          return_value={
                              "status": "V2D2B_READONLY_RECOVERY_INVENTORY_NOT_EXECUTABLE",
                              "can_execute": False, "qmt_calls": 0,
                              "market_file_writes": False,
                          }):
            with patch("sys.stdout", io.StringIO()) as output:
                status = CLI.main([
                    "--state-module", "D:/test/ParquetLiveSync",
                    "--market-root", "D:/test/AllCycleAStockData",
                    "--explicit-readonly"])
        self.assertEqual(status, 0)
        data = json.loads(output.getvalue())
        self.assertFalse(data["can_execute"])
        self.assertEqual(data["qmt_calls"], 0)

    def test_gui_click_gates_inventory_and_never_starts_apply(self):
        view = inspect.getsource(UI.MarketCenterV2)
        method = inspect.getsource(UI.MarketCenterV2.start_finance_inventory)
        self.assertIn("command=self.start_finance_inventory", view)
        self.assertIn("inspect_recovery_prerequisites(", method)
        self.assertIn("threading.Thread(", method)
        self.assertIn('text="一键重试（尚未开放）", state="disabled"', view)
        self.assertNotIn("subprocess.Popen", view)
        self.assertNotIn("--apply", view)

    def test_current_finance_importer_carries_unfinished_sweep_across_days(self):
        from qmt_extra_financial_cache_import import _prepare_daily_sweep
        carry = {
            "daily_date": "2026-11-20", "daily_cursor": "000755.SZ",
            "daily_sweep_start": "2026-11-20",
            "daily_sweep_reached_end": False, "daily_sweep_finished": "",
        }
        _prepare_daily_sweep(
            carry, "2026-11-21", ["000001.SZ", "000755.SZ", "000756.SZ"])
        self.assertEqual(carry["daily_date"], "2026-11-21")
        self.assertEqual(carry["daily_cursor"], "000755.SZ")
        self.assertFalse(carry["daily_sweep_reached_end"])
        self.assertEqual(carry["daily_sweep_start"], "2026-11-20")


if __name__ == "__main__":
    unittest.main()
