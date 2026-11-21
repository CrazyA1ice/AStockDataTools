"""S6 finance transaction fault-injection tests, fixture-only Parquet writes."""
from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import io
import os
import tempfile
import unittest

import market_scoped_finance_transaction_sandbox as S
import market_scoped_finance_transaction_intent as T
import qmt_extra_data as E


class FinanceSandboxTransactionTests(unittest.TestCase):
    def test_success_uses_real_snapshot_writer_and_verified_pin(self):
        with patch.object(E, "_snapshot_write", wraps=E._snapshot_write) as w, \
             patch.object(E, "_pin_financial_snapshot",
                          wraps=E._pin_financial_snapshot) as p:
            r = S.run_sandbox()
        self.assertEqual(r["status"], "SANDBOX_TRANSACTION_COMPLETE")
        self.assertEqual(r["at"], "COMPLETE")
        self.assertTrue(r["candidate_exists"])
        self.assertTrue(r["active_pin_is_candidate"])
        self.assertTrue(r["original_snapshot_sha256_unchanged"])
        self.assertTrue(r["backup_ledger_sha256_valid"])
        self.assertTrue(r["backup_pin_sha256_valid"])
        self.assertTrue(r["ledger_pending_unchanged"])
        self.assertTrue(r["ledger_cursor_unchanged"])
        self.assertFalse(r["auto_replay_allowed"])
        self.assertFalse(r["physical_rollback_attempted"])
        self.assertEqual(r["real_market_writes"], 0)
        self.assertEqual(r["real_qmt_calls"], 0)
        self.assertGreaterEqual(w.call_count, 2)
        self.assertGreaterEqual(p.call_count, 2)

    def test_fault_at_every_phase_never_replays_or_destroys_baseline(self):
        for phase in S.FAIL_POINTS:
            with self.subTest(phase=phase):
                r = S.run_sandbox(failure_at=phase)
                self.assertTrue(r["sandbox_only"])
                self.assertFalse(r["auto_replay_allowed"])
                self.assertFalse(r["physical_rollback_attempted"])
                self.assertTrue(r["original_snapshot_sha256_unchanged"])
                self.assertTrue(r["backup_ledger_sha256_valid"])
                self.assertTrue(r["backup_pin_sha256_valid"])
                self.assertTrue(r["ledger_pending_unchanged"])
                self.assertTrue(r["ledger_cursor_unchanged"])
                self.assertEqual(r["real_market_writes"], 0)
                self.assertEqual(r["real_qmt_calls"], 0)
                if phase == "COMPLETE":
                    self.assertEqual(
                        r["recovery_decision"], "AUDIT_COMPLETED_TRANSACTION")
                else:
                    self.assertEqual(r["status"],
                                     "SANDBOX_INTERRUPTED_QUARANTINE_REQUIRED")
                    self.assertEqual(
                        r["recovery_decision"],
                        "QUARANTINE_PENDING_MANUAL_RECOVERY")

    def test_prepared_crash_has_no_candidate_and_pin_still_original(self):
        r = S.run_sandbox(failure_at="PREPARED")
        self.assertEqual(r["at"], "PREPARED")
        self.assertFalse(r["candidate_exists"])
        self.assertFalse(r["active_pin_is_candidate"])

    def test_snapshot_unjournaled_crash_retains_file_but_old_pin(self):
        r = S.run_sandbox(failure_at="AFTER_SNAPSHOT_BEFORE_JOURNAL")
        self.assertEqual(r["at"], "PREPARED")
        self.assertTrue(r["candidate_exists"])
        self.assertFalse(r["active_pin_is_candidate"])
        self.assertEqual(r["recovery_decision"],
                         "QUARANTINE_PENDING_MANUAL_RECOVERY")

    def test_pin_unjournaled_crash_requires_manual_recovery(self):
        r = S.run_sandbox(failure_at="AFTER_PIN_BEFORE_JOURNAL")
        self.assertEqual(r["at"], "SNAPSHOT_WRITTEN")
        self.assertTrue(r["candidate_exists"])
        self.assertTrue(r["active_pin_is_candidate"])
        self.assertEqual(r["recovery_decision"],
                         "QUARANTINE_PENDING_MANUAL_RECOVERY")

    def test_ledger_unjournaled_crash_never_silently_releases_pending(self):
        r = S.run_sandbox(failure_at="AFTER_LEDGER_BEFORE_JOURNAL")
        self.assertEqual(r["at"], "PINS_UPDATED")
        self.assertTrue(r["ledger_pending_unchanged"])
        self.assertTrue(r["ledger_cursor_unchanged"])
        self.assertFalse(r["auto_replay_allowed"])

    def test_synthetic_scope_cannot_be_live_stock_root(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(S.SandboxRefused):
                S._sandbox_case(root, failure_at=None)

    def test_synthetic_marker_must_be_exact(self):
        with tempfile.TemporaryDirectory(prefix="astock-finance-s6-") as d:
            root = Path(d)
            (root / "marker.txt").write_text("NO", encoding="utf-8")
            with self.assertRaisesRegex(
                    S.SandboxRefused, "S6_ONLY_INTERNAL"):
                S._sandbox_case(root, failure_at=None)

    def test_unknown_synthetic_fault_point_refused(self):
        with self.assertRaisesRegex(S.SandboxRefused, "UNKNOWN_SYNTHETIC"):
            S.run_sandbox(failure_at="OVERRIDE_PRODUCTION_LEDGER")

    def test_temp_private_root_is_not_persisted(self):
        roots = []
        def witness(home, extra, workspace, result):
            roots.append(home)
            self.assertTrue(
                home.name.startswith("astock-finance-s6-"))
            self.assertEqual(home.resolve().parent,
                             Path(tempfile.gettempdir()).resolve())
            self.assertIn("AllCycleAStockData", str(extra))
            self.assertTrue(workspace.is_relative_to(home))
            self.assertTrue(result["original_snapshot_sha256_unchanged"])
        S.run_sandbox(observer=witness)
        self.assertEqual(len(roots), 1)
        self.assertFalse(roots[0].exists())

    def test_cli_without_synthetic_optin_does_not_launch_sandbox(self):
        buf = io.StringIO()
        with patch.object(S, "run_sandbox") as run:
            with redirect_stdout(buf):
                rc = S.main([])
        self.assertEqual(rc, 2)
        run.assert_not_called()
        self.assertIn("S6_SYNTHETIC_ONLY_REQUIRED", buf.getvalue())

    def test_cli_does_not_accept_live_root_or_apply_switch(self):
        with self.assertRaises(SystemExit):
            S.main(["--apply", "--root", "D:/stock/AllCycleAStockData"])

    def test_synthetic_sha_is_not_approval_token(self):
        observed = []
        def witness(home, extra, workspace, report):
            import json
            journal = json.loads((
                workspace / "scoped-finance-transaction-journals" /
                (S.STOCK + ".json")).read_text(encoding="utf-8"))
            self.assertEqual(journal["format"], T.FORMAT)
            self.assertRegex(journal["intent_sha256"], "^[a-f0-9]{64}$")
            self.assertTrue(journal["sandbox_only"])
            self.assertEqual(journal["phase_history"][0], "PREPARED")
            self.assertEqual(journal["phase_history"][-1], "COMPLETE")
            observed.append(report["status"])
        S.run_sandbox(observer=witness)
        self.assertEqual(observed, ["SANDBOX_TRANSACTION_COMPLETE"])

    def test_no_live_root_parameter_or_download_api(self):
        import inspect
        s = inspect.getsource(S)
        self.assertNotIn("xtquant", s)
        self.assertNotIn("download_financial_data", s)
        self.assertNotIn("._commit_symbol(", s)
        self.assertNotIn('"--apply"', s)
        self.assertNotIn('"--root"', s)
        self.assertIn("TemporaryDirectory(prefix=", s)
        self.assertIn('journal_workspace=workspace', s)

    def test_real_finance_ledger_outside_fixture_unchanged(self):
        # This test itself doesn't even locate the official user tree.
        before = (Path(__file__).resolve().parents[1] /
                  "market_scoped_finance_transaction_sandbox.py")
        self.assertTrue(before.is_file())
        result = S.run_sandbox(failure_at="PINS_UPDATED")
        self.assertTrue(result["sandbox_only"])
        self.assertFalse(result["auto_replay_allowed"])


if __name__ == "__main__":
    unittest.main()
