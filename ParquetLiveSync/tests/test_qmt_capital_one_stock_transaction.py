"""P69 fail-closed pilot tests: synthetic Parquet, ledger and policy only.

No QMT download, no canonical stock root, no Windows scheduled task mutation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I
import qmt_capital_one_stock_transaction as T
import qmt_capital_scoped_policy_reader as POL


OLD = {"_index": "0", "m_timetag": 20260930, "m_quarter": 0.0,
       "total_capital": 100.0, "circulating_capital": 80.0,
       "m_anntime": 20261028}
NEW = dict(OLD, m_quarter=6750319.0)


class OneStockTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.extra = root / "AllCycleAStockData" / "qmt_extra"
        self.work = root / "work" / "qmt_extra"
        self.work.mkdir(parents=True)
        self.asof = datetime.now(E.L.UTC8).date().isoformat()
        self.old_asof = (datetime.now(E.L.UTC8).date() -
                         timedelta(days=1)).isoformat()
        self.old = E.snapshot_table(self.old_asof, T.SYMBOL, "Capital", [OLD])
        E._snapshot_write(
            self.extra, "financial/Capital/" + T.SYMBOL, self.old_asof,
            self.old, workspace=self.work)
        self.baseline = E._financial_snapshot_file(
            self.extra, T.SYMBOL, "Capital", self.old_asof)
        self.baseline_hash = T.sha(self.baseline)
        self.state = I._state(self.extra, self.work)
        self.state["pending"][T.SYMBOL] = {
            "reason": "SOURCE_HISTORY_CONFLICT",
            "detail": "SOURCE_HISTORY_CONFLICT " + T.SYMBOL + " table=Capital",
            "attempts": 1, "asof": self.asof}
        I._save_state(self.work, self.state)
        self.source = {table: [] for table in E.FIN_TABLES}
        self.source["Capital"] = [dict(NEW)]

    def preview(self, source=None):
        return T._run_locked(
            self.extra, self.work, self.source if source is None else source,
            self.asof)

    def authorize(self, source=None, ledger=None, proof=None, token=T.APPROVAL):
        state = T._preflight(
            self.extra, self.work, self.source if source is None else source,
            self.asof)
        return T._run_locked(
            self.extra, self.work, self.source if source is None else source,
            self.asof, approval=token,
            expected_ledger=state["ledger_sha256"] if ledger is None else ledger,
            expected_proof=state["nine_table_preflight_sha256"] if proof is None else proof)

    def test_read_only_has_no_ledger_snapshot_or_policy_writes(self):
        before = T.sha(T.paths(self.work)[0])
        p = self.preview()
        self.assertEqual(p["status"], "READY_FOR_EXPLICIT_ONE_STOCK_APPROVAL")
        self.assertEqual(p["mode"], "READ_ONLY")
        self.assertEqual(p["allowed_report_dates"], 1)
        self.assertEqual(p["changed_historical_rows"], 1)
        self.assertEqual(before, T.sha(T.paths(self.work)[0]))
        self.assertFalse(T.paths(self.work)[1].exists())
        self.assertFalse(T.paths(self.work)[2].exists())
        self.assertIsNone(E._financial_snapshot_file(
            self.extra, T.SYMBOL, "Capital", self.asof))

    def test_bad_approval_refused_before_journal_or_write(self):
        with self.assertRaisesRegex(ValueError, "P69_EXPLICIT_APPROVAL"):
            self.authorize(token="yes")
        self.assertFalse(T.paths(self.work)[1].exists())

    def test_bad_ledger_hash_refused_before_write(self):
        with self.assertRaisesRegex(ValueError, "P69_EXPLICIT_APPROVAL"):
            self.authorize(ledger="0" * 64)
        self.assertFalse(T.paths(self.work)[1].exists())

    def test_bad_preflight_hash_refused_before_write(self):
        with self.assertRaisesRegex(ValueError, "P69_EXPLICIT_APPROVAL"):
            self.authorize(proof="0" * 64)
        self.assertFalse(T.paths(self.work)[1].exists())

    def test_exact_approval_commits_one_capital_only_and_releases_one_pending(self):
        old = deepcopy(self.state)
        receipt = self.authorize()
        self.assertEqual(receipt["status"], "ONE_STOCK_APPLIED_PENDING_RELEASED")
        self.assertTrue(receipt["pending_released"])
        self.assertFalse(receipt["scheduled_finance_unblocked"])
        self.assertFalse(receipt["global_mass_conflict_guard_modified"])
        self.assertEqual(T.sha(self.baseline), self.baseline_hash)
        self.assertNotIn(T.SYMBOL, I._state(self.extra, self.work)["pending"])
        self.assertEqual(len(old["pending"]), 1)
        journal = T.paths(self.work)[1]
        self.assertEqual(__import__("json").loads(journal.read_text())["phase"], "COMPLETE")
        current = E._financial_snapshot_file(
            self.extra, T.SYMBOL, "Capital", self.asof)
        self.assertIsNotNone(current)
        policy = POL.read_policy(self.extra, T.SYMBOL, self.work)
        self.assertEqual(policy["candidate_snapshot"], current.name)
        _, saved = I._prior_rows(self.extra, T.SYMBOL, "Capital")
        verified = POL.validate_policy(
            self.extra, T.SYMBOL, self.asof, policy, saved, [dict(NEW)])
        self.assertEqual(verified["allowed_report_dates"], 1)
        with self.assertRaisesRegex(ValueError, "P69_EXISTING_JOURNAL"):
            self.authorize()

    def test_extra_table_delta_is_never_waived(self):
        earlier = E.snapshot_table(self.old_asof, T.SYMBOL, "Income",
                                   [{"_index": "0", "m_timetag": 20260930,
                                     "revenue": 100.0}])
        E._snapshot_write(
            self.extra, "financial/Income/" + T.SYMBOL,
            self.old_asof, earlier, workspace=self.work)
        with self.assertRaisesRegex(ValueError, "P69_NINE_TABLE_PREVIEW_REFUSED"):
            self.preview()

    def test_real_business_change_requires_review(self):
        changed = deepcopy(self.source)
        changed["Capital"][0]["total_capital"] = 111.0
        with self.assertRaisesRegex(ValueError, "P69_NINE_TABLE_PREVIEW_REFUSED"):
            self.preview(changed)

    def test_new_report_date_requires_separate_approval(self):
        changed = deepcopy(self.source)
        changed["Capital"].append(dict(NEW, _index="1", m_timetag=20261231))
        with self.assertRaisesRegex(ValueError, "P69_NINE_TABLE_PREVIEW_REFUSED"):
            self.preview(changed)

    def test_existing_same_day_snapshot_blocks_second_import(self):
        E._snapshot_write(self.extra, "financial/Capital/" + T.SYMBOL,
                          self.asof, E.snapshot_table(
                              self.asof, T.SYMBOL, "Capital", [OLD]),
                          workspace=self.work)
        with self.assertRaisesRegex(ValueError, "P69_CURRENT_DAY_CAPITAL"):
            self.preview()

    def test_bad_pending_reason_fails_closed(self):
        state = I._state(self.extra, self.work)
        state["pending"][T.SYMBOL]["reason"] = "CACHE_DECODE_ERROR"
        I._save_state(self.work, state)
        with self.assertRaisesRegex(ValueError, "P69_TARGET_MUST_REMAIN"):
            self.preview()

    def test_crash_after_prepared_stays_quarantined_until_explicit_compensation(self):
        normal = T._save
        def fail_once(path, doc):
            normal(path, doc)
            if path == T.paths(self.work)[1] and doc.get("phase") == "PREPARED":
                raise RuntimeError("INJECTED_AFTER_PREPARED")
        with patch.object(T, "_save", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "INJECTED_AFTER_PREPARED"):
                self.authorize()
        self.assertIn(T.SYMBOL, I._state(self.extra, self.work)["pending"])
        with self.assertRaisesRegex(ValueError, "P69_EXISTING_JOURNAL"):
            self.preview()
        result = T._quarantine_compensate_locked(self.extra, self.work)
        self.assertEqual(result["status"], "COMPENSATED_QUARANTINED_NO_PHYSICAL_ROLLBACK")
        self.assertIn(T.SYMBOL, I._state(self.extra, self.work)["pending"])

    def test_crash_after_candidate_revokes_policy_and_restores_pending(self):
        normal = T._save
        def fail_once(path, doc):
            normal(path, doc)
            if path == T.paths(self.work)[1] and doc.get("phase") == "POLICY_RECORDED":
                raise RuntimeError("INJECTED_AFTER_POLICY")
        with patch.object(T, "_save", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "INJECTED_AFTER_POLICY"):
                self.authorize()
        self.assertIn(T.SYMBOL, I._state(self.extra, self.work)["pending"])
        self.assertEqual(POL.read_policy(self.extra, T.SYMBOL, self.work)["status"], "ACTIVE")
        result = T._quarantine_compensate_locked(self.extra, self.work)
        self.assertTrue(result["pending_restored"])
        self.assertEqual(POL.read_policy(self.extra, T.SYMBOL, self.work)["status"], "REVOKED")
        self.assertEqual(T.sha(self.baseline), self.baseline_hash)

    def test_default_scheduled_runner_cannot_load_approval(self):
        import inspect
        self.assertNotIn("capital_policy", inspect.signature(I.run).parameters)
        self.assertNotIn("capital_policy", inspect.signature(I.main).parameters)
        self.assertFalse(hasattr(I, 'APPROVAL'))


if __name__ == "__main__":
    unittest.main()
