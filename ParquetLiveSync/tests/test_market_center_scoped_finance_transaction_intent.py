"""S5 intent + immutable-version sandbox checks. No QMT or production writes."""
from __future__ import annotations

from contextlib import redirect_stdout
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import io
import os
import re
import subprocess
import unittest

import market_scoped_finance_transaction_intent as T
import qmt_extra_data as E
import qmt_extra_financial_cache_import as I


STOCK = "000001.SZ"
ASOF = "2026-11-21"


def old_row():
    return {"_index": "1", "m_timetag": "20260930",
            "m_quarter": "2026Q3", "total": 123}


def new_row():
    return {"_index": "2", "m_timetag": "20261231",
            "m_quarter": "2026Q4", "total": 456}


def payload(*, with_new=True, codes=None):
    codes = codes or [STOCK]
    return {
        "symbols": codes,
        "records": {
            code: {name: ([old_row(), new_row()] if name == "Capital"
                           and with_new else []) for name in E.FIN_TABLES}
            for code in codes
        },
    }


def proof(codes=None, *, status="CANDIDATE_NEW_VERSION_NOT_COMMITTED",
          pending=False):
    codes = codes or [STOCK]
    return {
        "status": "SCOPED_FINANCE_NINE_TABLE_PRECOMMIT_READONLY",
        "can_commit": False,
        "official_market_writes": 0,
        "financial_ledger_writes": 0,
        "multisource_verified": False,
        "source_authenticity_certified": False,
        "stock_results": [
            {"symbol": code, "status": status,
             "pending_previously_recorded": pending} for code in codes
        ],
    }


def digest(value="a"):
    return value * 64


class IntentPureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="transaction-preview-")
        self.addCleanup(self.temp.cleanup)
        self.extra = Path(self.temp.name) / "qmt_extra"
        self.extra.mkdir(parents=True)

    def build(self, source=None, reviewed=None, **options):
        src = source or payload()
        evidence = reviewed or proof()
        return T.build_intent(
            src, evidence, extra=self.extra, asof=ASOF,
            cache_sha=digest(), progress_sha=digest("b"), **options)

    def test_new_parquet_candidate_is_only_intent_not_commit(self):
        with patch.object(I, "_prior_rows", return_value=(None, None)):
            outcome = self.build()
        self.assertEqual(outcome["candidate_immutable_files"], 1)
        target = outcome["intent"]["candidate_stocks"][0][
            "immutable_targets"][0]
        self.assertEqual(target["table"], "Capital")
        self.assertRegex(target["target_filename"],
                         r"^2026-11-21-[a-f0-9]{16}\.parquet$")
        self.assertTrue(target["target_absent_verified"])
        self.assertFalse(outcome["can_commit"])
        self.assertFalse(outcome["can_apply"])
        self.assertEqual(outcome["official_market_writes"], 0)
        self.assertFalse(outcome["journal_written"])
        self.assertFalse(any(self.extra.rglob("*.parquet")))

    def test_same_source_same_manifest_fingerprint(self):
        with patch.object(I, "_prior_rows", return_value=(None, None)):
            first = self.build()
            second = self.build()
        self.assertEqual(first["intent_sha256"], second["intent_sha256"])

    def test_pending_ledger_entry_blocks_batch_even_if_cache_looks_new(self):
        with patch.object(I, "_plan_symbol") as planner:
            result = self.build(reviewed=proof(pending=True))
        planner.assert_not_called()
        self.assertTrue(result["batch_has_unresolved_blockers"])
        self.assertEqual(result["candidate_immutable_files"], 0)

    def test_historical_conflict_never_gets_reclassified(self):
        result = self.build(reviewed=proof(status="BLOCKED_HISTORY_CONFLICT"))
        self.assertTrue(result["batch_has_unresolved_blockers"])
        self.assertEqual(result["intent"]["blocked_stocks"][0]["reason"],
                         "BLOCKED_HISTORY_CONFLICT")
        self.assertFalse(result["can_apply"])

    def test_missing_cached_stock_is_blocker(self):
        result = self.build(reviewed=proof(status="SOURCE_CACHE_MISSING"))
        self.assertEqual(result["candidate_immutable_files"], 0)
        self.assertTrue(result["batch_has_unresolved_blockers"])

    def test_no_source_changes_is_not_commit_permission(self):
        result = self.build(
            reviewed=proof(status="LOCAL_HISTORY_UNCHANGED_NOT_CERTIFIED"))
        self.assertEqual(result["candidate_immutable_files"], 0)
        self.assertFalse(result["batch_fully_eligible_for_future_manual_review"])

    def test_mixed_batch_preserves_blocking_stock(self):
        codes = ["000001.SZ", "000002.SZ"]
        reviewed = proof(codes)
        reviewed["stock_results"][1]["status"] = "BLOCKED_HISTORY_CONFLICT"
        with patch.object(I, "_prior_rows", return_value=(None, None)):
            result = self.build(source=payload(codes=codes),
                                reviewed=reviewed)
        self.assertEqual(len(result["intent"]["candidate_stocks"]), 1)
        self.assertEqual(len(result["intent"]["blocked_stocks"]), 1)
        self.assertFalse(result["batch_fully_eligible_for_future_manual_review"])

    def test_untrusted_review_or_unknown_status_fail_closed(self):
        sample = proof()
        sample["can_commit"] = True
        with self.assertRaisesRegex(T.IntentBlocked, "STRICT_NINE_TABLE"):
            self.build(reviewed=sample)
        with self.assertRaisesRegex(T.IntentBlocked, "UNKNOWN_STRICT"):
            self.build(reviewed=proof(status="SURPRISE"))

    def test_stock_order_change_after_review_rejected(self):
        source = payload(codes=["000002.SZ", "000001.SZ"])
        with self.assertRaisesRegex(T.IntentBlocked, "SORTED"):
            self.build(source=source,
                       reviewed=proof(source["symbols"]))

    def test_strict_planner_cannot_return_empty_actions(self):
        with self.assertRaisesRegex(T.IntentBlocked, "NEW_VERSION_ACTIONS"):
            self.build(planner=lambda *_: (
                {t: {"action": "UNCHANGED"} for t in E.FIN_TABLES}, {}))

    def test_existing_candidate_path_requires_reanalysis(self):
        source = payload()
        new_arrow = E.snapshot_table(
            ASOF, STOCK, "Capital", source["records"][STOCK]["Capital"])
        path = E._snapshot_path(
            self.extra, "financial/Capital/" + STOCK, ASOF, new_arrow)
        E._snapshot_write(
            self.extra, "financial/Capital/" + STOCK,
            ASOF, new_arrow, workspace=self.extra)
        with patch.object(I, "_prior_rows", return_value=(None, None)):
            with self.assertRaisesRegex(T.IntentBlocked, "TARGET_ALREADY"):
                self.build()
        self.assertTrue(path.exists())

    def _install_same_day_old(self, *, pin):
        old = E.snapshot_table(ASOF, STOCK, "Capital", [old_row()])
        name = "financial/Capital/" + STOCK
        saved = E._snapshot_path(self.extra, name, ASOF, old)
        E._snapshot_write(self.extra, name, ASOF, old, workspace=self.extra)
        if pin:
            E._pin_financial_snapshot(self.extra, STOCK, "Capital",
                                      ASOF, saved)
        return saved

    def test_unpinned_legacy_same_day_version_refuses_intent(self):
        old = self._install_same_day_old(pin=False)
        with self.assertRaisesRegex(T.IntentBlocked, "SAME_DAY_UNPINNED"):
            self.build()
        self.assertTrue(old.exists())

    def test_pinned_same_day_version_is_retained_and_sha_bound(self):
        old = self._install_same_day_old(pin=True)
        before = E.L.hash_file(old)
        result = self.build()
        candidate = result["intent"]["candidate_stocks"][0][
            "immutable_targets"][0]
        self.assertEqual(candidate["prior_snapshot_sha256"], before)
        self.assertEqual(candidate["prior_same_day_filename"], old.name)
        self.assertRegex(candidate["active_pin_sha256"], r"^[a-f0-9]{64}$")
        self.assertTrue(candidate["target_absent_verified"])
        self.assertEqual(E.L.hash_file(old), before)

    def test_complete_and_incomplete_journals_never_auto_replay(self):
        for phase in T.PHASES:
            result = T.recovery_decision({
                "format": T.FORMAT, "phase": phase,
                "intent_sha256": digest()})
            self.assertFalse(result["automated_replay_allowed"])
            self.assertFalse(result["financial_ledger_release_allowed"])
            if phase == "COMPLETE":
                self.assertEqual(result["decision"],
                                 "AUDIT_COMPLETED_TRANSACTION")
            else:
                self.assertEqual(result["decision"],
                                 "QUARANTINE_PENDING_MANUAL_RECOVERY")

    def test_existing_transaction_journal_blocks_repreparation(self):
        journals = Path(self.temp.name) / "private" / (
            "scoped-finance-transaction-journals")
        journals.mkdir(parents=True)
        (journals / (STOCK + ".json")).write_text(
            '{"phase":"PREPARED"}', encoding="utf-8")
        with patch.object(I, "_prior_rows", return_value=(None, None)):
            with self.assertRaisesRegex(
                    T.IntentBlocked, "EXISTING_TRANSACTION_JOURNAL"):
                self.build(journal_workspace=journals.parent)

    def test_clean_no_change_is_not_an_error_or_new_commit(self):
        result = self.build(
            reviewed=proof(status="LOCAL_HISTORY_UNCHANGED_NOT_CERTIFIED"))
        self.assertEqual(result["stocks_without_source_changes"], 1)
        self.assertFalse(result["batch_has_unresolved_blockers"])
        self.assertFalse(result["can_apply"])

    def test_only_exact_hex_fingerprints_are_accepted(self):
        with self.assertRaisesRegex(T.IntentBlocked, "STRICT_NINE_TABLE"):
            T.build_intent(payload(), proof(), extra=self.extra,
                           asof=ASOF, cache_sha=None,
                           progress_sha=digest("b"))
        with self.assertRaisesRegex(T.IntentBlocked, "STRICT_NINE_TABLE"):
            T.build_intent(payload(), proof(), extra=self.extra,
                           asof=ASOF, cache_sha=digest(),
                           progress_sha="z" * 64)

    def test_unknown_journal_refused(self):
        with self.assertRaisesRegex(T.IntentBlocked, "UNKNOWN_TRANSACTION"):
            T.recovery_decision({
                "format": T.FORMAT, "phase": "MAYBE",
                "intent_sha256": digest()})

    def test_cli_explicit_readonly_is_required(self):
        with patch.object(T, "preview") as preview:
            capture = io.StringIO()
            with redirect_stdout(capture):
                code = T.main([
                    "--root", "X", "--workspace", "X",
                    "--cache-file", "X/cache.json",
                    "--expected-cache-sha256", digest(),
                    "--expected-progress-sha256", digest("b"),
                    "--symbols", STOCK, "--start", "20261120",
                    "--end", "20261120"])
        self.assertEqual(code, 2)
        preview.assert_not_called()
        self.assertIn("S5_EXPLICIT_READONLY_REQUIRED", capture.getvalue())

    def test_no_qmt_or_actual_commit_call_in_intent_code(self):
        import inspect
        code = inspect.getsource(T)
        self.assertNotIn("xtquant", code)
        self.assertNotIn("._commit_symbol(", code)
        self.assertNotIn("._save_state(", code)
        self.assertNotIn("._pin_financial_snapshot(", code)
        self.assertNotIn("._snapshot_write(", code)
        self.assertNotIn("pq.write_table(", code)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell parser only")
    def test_scoped_worker_script_has_no_powershell_syntax_errors(self):
        script = Path(__file__).resolve().parents[1] / (
            "run-scoped-qmt-finance-cache.ps1")
        escaped = str(script).replace("'", "''")
        statement = (
            "$t=$null;$e=$null;"
            "[System.Management.Automation.Language.Parser]::"
            "ParseFile('" + escaped + "',[ref]$t,[ref]$e)|Out-Null;"
            "if($e.Count -ne 0){$e | ForEach-Object {Write-Error $_};exit 2};exit 0")
        executed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             statement], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=15, check=False)
        self.assertEqual(executed.returncode, 0,
                         executed.stderr.decode("utf-8", errors="replace")[:800])

    def test_repaired_script_has_single_cleanup_and_complete_reason_regex(self):
        code = (Path(__file__).resolve().parents[1] /
                "run-scoped-qmt-finance-cache.ps1").read_text(
                    encoding="utf-8-sig")
        self.assertEqual(code.count("$mutex.Dispose()"), 1)
        self.assertEqual(code.count("SCOPED_FINANCE_PRECOMMIT="), 1)
        self.assertIn("$candidate -cmatch '^[A-Z0-9_]{1,90}$'", code)


if __name__ == "__main__":
    unittest.main()
