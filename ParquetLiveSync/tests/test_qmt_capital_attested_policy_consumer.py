"""P70: detached synthetic Parquet-only attestation regression, zero live QMT."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import json
import tempfile
import unittest

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I
import qmt_capital_one_stock_transaction as TX
import qmt_capital_attested_policy_consumer as C
import qmt_capital_scoped_policy_reader as POL


OLD = {"_index": "0", "m_timetag": 20260930, "m_quarter": 0.0,
       "total_capital": 100.0, "circulating_capital": 80.0,
       "m_anntime": 20261028}
NEW = dict(OLD, m_quarter=6750319.0)


class AttestedPolicyConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.extra = root / "stock" / "AllCycleAStockData" / "qmt_extra"
        self.work = root / "work" / "qmt_extra"
        self.work.mkdir(parents=True)
        today = datetime.now(E.L.UTC8).date()
        self.asof = today.isoformat()
        self.old_asof = (today - timedelta(days=1)).isoformat()
        self.next_asof = (today + timedelta(days=1)).isoformat()
        E._snapshot_write(
            self.extra, "financial/Capital/" + TX.SYMBOL, self.old_asof,
            E.snapshot_table(self.old_asof, TX.SYMBOL, "Capital", [OLD]),
            workspace=self.work)
        state = I._state(self.extra, self.work)
        state["pending"][TX.SYMBOL] = {
            "reason": "SOURCE_HISTORY_CONFLICT",
            "detail": "SOURCE_HISTORY_CONFLICT " + TX.SYMBOL + " table=Capital",
            "attempts": 1, "asof": self.asof}
        I._save_state(self.work, state)
        self.source = {table: [] for table in E.FIN_TABLES}
        self.source["Capital"] = [dict(NEW)]

    def apply_synthetic(self):
        pre = TX._preflight(self.extra, self.work, self.source, self.asof)
        return TX._run_locked(
            self.extra, self.work, self.source, self.asof,
            approval=TX.APPROVAL,
            expected_ledger=pre["ledger_sha256"],
            expected_proof=pre["nine_table_preflight_sha256"])

    def checked(self, values=None):
        return C.verify_next_day_without_writes(
            self.extra, self.work, TX.SYMBOL, self.next_asof,
            self.source if values is None else values)

    def test_no_journal_and_no_policy_means_no_attestation(self):
        self.assertIsNone(C.read_completed_policy(
            self.extra, self.work, TX.SYMBOL))
        with self.assertRaisesRegex(ValueError, "NO_COMPLETED_APPROVAL"):
            self.checked()

    def test_non_pilot_stock_never_receives_pilot_policy(self):
        self.apply_synthetic()
        self.assertIsNone(C.read_completed_policy(
            self.extra, self.work, "688006.SH"))

    def test_completed_transaction_attests_exact_policy(self):
        self.apply_synthetic()
        expected = POL.read_policy(self.extra, TX.SYMBOL, self.work)
        self.assertEqual(C.read_completed_policy(
            self.extra, self.work, TX.SYMBOL), expected)

    def test_following_day_identical_cache_does_not_repeat_snapshot(self):
        self.apply_synthetic()
        saved_ledger_sha = TX.sha(TX.paths(self.work)[0])
        saved_candidate = E._financial_snapshot_file(
            self.extra, TX.SYMBOL, "Capital", self.asof)
        result = self.checked()
        self.assertEqual(result["capital_action"], "UNCHANGED")
        self.assertEqual(result["staged_tables"], [])
        self.assertTrue(result["capital_exception"]["persistent_policy_checked"])
        self.assertEqual(result["capital_exception"]["allowed_report_dates"], 1)
        self.assertFalse(result["applied"])
        self.assertFalse(result["unattended_waiver_enabled"])
        self.assertEqual(TX.sha(TX.paths(self.work)[0]), saved_ledger_sha)
        self.assertEqual(E._financial_snapshot_file(
            self.extra, TX.SYMBOL, "Capital", self.asof), saved_candidate)

    def test_changed_economic_capital_field_still_refused(self):
        self.apply_synthetic()
        drift = {k: [dict(r) for r in v] for k, v in self.source.items()}
        drift["Capital"][0]["total_capital"] = 101.0
        with self.assertRaisesRegex(ValueError, "APPROVED_BUSINESS_OR_QUARTER_DRIFT"):
            self.checked(drift)

    def test_new_report_date_requires_review_and_no_automatic_waiver(self):
        self.apply_synthetic()
        drift = {k: [dict(r) for r in v] for k, v in self.source.items()}
        drift["Capital"].append(dict(NEW, _index="1", m_timetag=20261231))
        with self.assertRaisesRegex(ValueError, "ADDED_OR_REMOVED_REPORT_DATE_REQUIRES_REVIEW"):
            self.checked(drift)

    def test_other_table_change_never_waived(self):
        E._snapshot_write(
            self.extra, "financial/Income/" + TX.SYMBOL, self.asof,
            E.snapshot_table(self.asof, TX.SYMBOL, "Income", [
                {"_index": "0", "m_timetag": 20260930, "revenue": 100.}]),
            workspace=self.work)
        self.apply_synthetic()
        drift = {k: [dict(r) for r in v] for k, v in self.source.items()}
        drift["Income"] = [
            {"_index": "0", "m_timetag": 20260930, "revenue": 101.}]
        with self.assertRaisesRegex(ValueError, "SOURCE_HISTORY_CONFLICT"):
            self.checked(drift)

    def test_active_policy_file_without_complete_journal_fails(self):
        self.apply_synthetic()
        _, journal, _ = TX.paths(self.work)
        journal.unlink()
        with self.assertRaisesRegex(ValueError, "MISSING_OR_UNSAFE_FILE"):
            C.read_completed_policy(self.extra, self.work, TX.SYMBOL)

    def test_journal_without_policy_fails(self):
        self.apply_synthetic()
        _, _, policy_path = TX.paths(self.work)
        policy_path.unlink()
        with self.assertRaisesRegex(ValueError, "MISSING_OR_UNSAFE_FILE"):
            C.read_completed_policy(self.extra, self.work, TX.SYMBOL)

    def test_changed_policy_sha_fails_closed(self):
        self.apply_synthetic()
        _, _, path = TX.paths(self.work)
        document = json.loads(path.read_text())
        document["status"] = "REVOKED"
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "POLICY_SHA_MISMATCH"):
            C.read_completed_policy(self.extra, self.work, TX.SYMBOL)

    def test_incomplete_journal_not_an_authorization(self):
        self.apply_synthetic()
        _, path, _ = TX.paths(self.work)
        document = json.loads(path.read_text())
        document["phase"] = "LEDGER_RELEASED"
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "NOT_A_COMPLETED"):
            C.read_completed_policy(self.extra, self.work, TX.SYMBOL)

    def test_original_ledger_backup_tampering_fails_closed(self):
        self.apply_synthetic()
        _, path, _ = TX.paths(self.work)
        document = json.loads(path.read_text())
        Path(document["ledger_backup_path"]).write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "ORIGINAL_LEDGER_BACKUP_NOT_ANCHORED"):
            C.read_completed_policy(self.extra, self.work, TX.SYMBOL)

    def test_baseline_snapshot_sha_tampering_fails_closed(self):
        self.apply_synthetic()
        old = E._financial_snapshot_file(
            self.extra, TX.SYMBOL, "Capital", self.old_asof)
        old.write_bytes(old.read_bytes() + b"broken")
        with self.assertRaisesRegex(ValueError, "IMMUTABLE_SNAPSHOT_SHA_MISMATCH"):
            C.read_completed_policy(self.extra, self.work, TX.SYMBOL)

    def test_pending_reappearing_revokes_attestation_eligibility(self):
        self.apply_synthetic()
        state = I._state(self.extra, self.work)
        state["pending"][TX.SYMBOL] = {
            "reason": "SOURCE_HISTORY_CONFLICT", "attempts": 1}
        I._save_state(self.work, state)
        with self.assertRaisesRegex(ValueError, "STOCK_STILL_QUARANTINED"):
            C.read_completed_policy(self.extra, self.work, TX.SYMBOL)

    def test_root_mismatch_fails(self):
        self.apply_synthetic()
        other = self.extra.parent / "foreign" / "qmt_extra"
        with self.assertRaises(Exception):
            C.read_completed_policy(other, self.work, TX.SYMBOL)


if __name__ == "__main__":
    unittest.main()
