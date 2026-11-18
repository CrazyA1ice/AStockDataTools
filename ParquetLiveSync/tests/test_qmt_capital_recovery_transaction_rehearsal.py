"""P66 fault-injection tests use ONLY OS TEMP synthetic financial snapshots.

Do not import QMT, call provider downloads, alter production pending or task.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I
import qmt_capital_recovery_transaction_rehearsal as R


CODE = R.TARGET
OLD = {"_index": "0", "m_timetag": 20260930,
       "m_quarter": 0., "total_capital": 100.,
       "circulating_capital": 80., "m_anntime": 20261028}
FRESH = dict(OLD, m_quarter=6750319.)
ASOF = "2026-11-18"


def fixture():
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    extra = root / "qmt_extra"
    work = root / "finance-work"
    work.mkdir()
    (work / "synthetic-only.marker").write_text(R.MARKER, encoding="utf-8")
    pending = {"reason": "SOURCE_HISTORY_CONFLICT", "attempts": 1,
               "asof": ASOF,
               "detail": "SOURCE_HISTORY_CONFLICT 002237.SZ table=Capital removed_or_revised=1"}
    state = {"format": I.FORMAT, "root": str(extra.resolve()),
             "import_cursor": CODE, "daily_date": ASOF,
             "daily_cursor": CODE, "pending": {CODE: pending},
             "daily_sweep_start": ASOF,
             "daily_sweep_reached_end": False, "daily_sweep_finished": ""}
    I._save_state(work, state)
    E._snapshot_write(
        extra, "financial/Capital/" + CODE, "2026-11-17",
        E.snapshot_table("2026-11-17", CODE, "Capital", [OLD]),
        workspace=work)
    source = {name: [] for name in E.FIN_TABLES}
    source["Capital"] = [dict(FRESH)]
    return temp, extra, work, state, source


class SyntheticCapitalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp, self.extra, self.work, self.state, self.source = fixture()
        self.addCleanup(self.temp.cleanup)

    def run_pilot(self, fault=None):
        return R.synthetic_run(self.extra, self.work, code=CODE,
                               asof=ASOF, source=self.source, fault=fault)

    def state_now(self):
        return I._state(self.extra, self.work)

    def test_full_synthetic_transaction_is_not_live_approval(self):
        outcome = self.run_pilot()
        self.assertEqual(outcome["status"],
                         "SYNTHETIC_COMPLETED_NOT_LIVE_AUTHORIZED")
        self.assertFalse(outcome["applies_to_production_importer"])
        self.assertNotIn(CODE, self.state_now()["pending"])
        self.assertTrue((self.work / "capital-recovery-journal" /
                         (CODE + ".json")).is_file())
        self.assertEqual(json.loads(
            (self.work / "capital-recovery-policy" /
             (CODE + ".json")).read_text(encoding="utf-8"))["status"],
            "SYNTHETIC_APPROVAL_EVIDENCE_ONLY")
        self.assertEqual(E._financial_snapshot_rows(
            self.extra, CODE, "Capital", "2026-11-17"), [OLD])
        self.assertEqual(E._financial_snapshot_rows(
            self.extra, CODE, "Capital", ASOF), [FRESH])
        with self.assertRaisesRegex(ValueError, "SOURCE_HISTORY_CONFLICT"):
            I._plan_symbol(self.extra, CODE, "2026-11-19", self.source)

    def test_recovery_journal_prevents_second_unreviewed_transaction(self):
        self.run_pilot()
        with self.assertRaisesRegex(ValueError, "Existing transaction"):
            self.run_pilot()

    def test_successful_synthetic_commit_can_be_compensated(self):
        self.run_pilot()
        result = R.synthetic_compensate(self.extra, self.work)
        self.assertEqual(result["status"], "COMPENSATED_PENDING_QUARANTINED")
        self.assertTrue(result["pending_restored"])
        self.assertEqual(self.state_now()["pending"][CODE],
                         self.state["pending"][CODE])
        self.assertFalse(result["physical_rollback_claimed"])
        self.assertTrue(result["candidate_immutable_file_retained"])
        self.assertEqual(E._financial_snapshot_rows(
            self.extra, CODE, "Capital", "2026-11-17"), [OLD])
        policy = json.loads((self.work / "capital-recovery-policy" /
                             (CODE + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(policy["status"], "SYNTHETIC_REVOKED")
        self.assertEqual(R.synthetic_compensate(self.extra, self.work)["status"],
                         "ALREADY_COMPENSATED")

    def test_faults_compensate_at_every_durable_boundary(self):
        for fault in R.FAULTS:
            with self.subTest(fault=fault):
                temp, extra, work, state, source = fixture()
                try:
                    with self.assertRaisesRegex(RuntimeError, "INJECTED_"):
                        R.synthetic_run(extra, work, code=CODE, asof=ASOF,
                                        source=source, fault=fault)
                    result = R.synthetic_compensate(extra, work)
                    self.assertTrue(result["pending_restored"])
                    self.assertEqual(
                        I._state(extra, work)["pending"][CODE],
                        state["pending"][CODE])
                    journal = json.loads((work / "capital-recovery-journal" /
                                          (CODE + ".json")).read_text(encoding="utf-8"))
                    self.assertEqual(journal["phase"], "COMPENSATED")
                finally:
                    temp.cleanup()

    def test_existing_same_asof_pin_reinstated_after_compensation(self):
        original_file = E._snapshot_path(
            self.extra, "financial/Capital/" + CODE, ASOF,
            E.snapshot_table(ASOF, CODE, "Capital", [OLD]))
        E._snapshot_write(
            self.extra, "financial/Capital/" + CODE, ASOF,
            E.snapshot_table(ASOF, CODE, "Capital", [OLD]),
            workspace=self.work)
        original_hash = E.L.hash_file(original_file)
        with self.assertRaisesRegex(RuntimeError, "INJECTED_AFTER_SNAPSHOT"):
            self.run_pilot(fault="AFTER_SNAPSHOT")
        selected = E._financial_snapshot_file(
            self.extra, CODE, "Capital", ASOF)
        self.assertNotEqual(selected, original_file)
        result = R.synthetic_compensate(self.extra, self.work)
        self.assertTrue(result["old_same_day_pin_restored"])
        self.assertEqual(E._financial_snapshot_file(
            self.extra, CODE, "Capital", ASOF), original_file)
        self.assertEqual(E.L.hash_file(original_file), original_hash)
        self.assertEqual(len(list(original_file.parent.glob(
            "2026-11-18-*.parquet"))), 2)

    def test_real_business_field_change_fails_before_journal(self):
        self.source["Capital"][0]["total_capital"] += 1.
        with self.assertRaisesRegex(ValueError, "NINE_TABLE_SOURCE_PROOF_REJECTED"):
            self.run_pilot()
        self.assertIn(CODE, self.state_now()["pending"])
        self.assertFalse((self.work / "capital-recovery-journal").exists())

    def test_other_financial_table_change_fails_before_journal(self):
        E._snapshot_write(
            self.extra, "financial/Income/" + CODE, "2026-11-17",
            E.snapshot_table("2026-11-17", CODE, "Income", [
                {"_index": "0", "m_timetag": 20260930, "income": 12.}]),
            workspace=self.work)
        self.source["Income"] = [
            {"_index": "0", "m_timetag": 20260930, "income": 13.}]
        with self.assertRaisesRegex(ValueError, "NINE_TABLE_SOURCE_PROOF_REJECTED"):
            self.run_pilot()
        self.assertFalse((self.work / "capital-recovery-journal").exists())

    def test_missing_test_marker_never_writes(self):
        (self.work / "synthetic-only.marker").unlink()
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_TEMP_ROOT"):
            self.run_pilot()
        self.assertIn(CODE, self.state_now()["pending"])

    def test_real_production_tree_is_rejected_before_any_reads(self):
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_TEMP_ROOT"):
            R.synthetic_run(Path("D:/stock/qmt_extra"),
                            Path("D:/ChatGPT/AStockDataTools/ParquetLiveSync/work/qmt_extra"),
                            code=CODE, asof=ASOF, source=self.source)

    def test_noncapital_pending_never_starts(self):
        state = self.state_now()
        state["pending"][CODE]["detail"] = (
            "SOURCE_HISTORY_CONFLICT 002237.SZ table=Income removed_or_revised=1")
        I._save_state(self.work, state)
        with self.assertRaisesRegex(ValueError, "not quarantined for Capital"):
            self.run_pilot()
        self.assertFalse((self.work / "capital-recovery-journal").exists())

    def test_other_symbol_not_permitted(self):
        with self.assertRaisesRegex(ValueError, "only 002237"):
            R.synthetic_run(self.extra, self.work, code="688367.SH",
                            asof=ASOF, source=self.source)

    def test_existing_pending_entry_drift_refuses_to_overwrite(self):
        with self.assertRaisesRegex(RuntimeError, "INJECTED_AFTER_POLICY"):
            self.run_pilot(fault="AFTER_POLICY")
        latest = self.state_now()
        latest["pending"][CODE]["attempts"] = 2
        I._save_state(self.work, latest)
        with self.assertRaisesRegex(ValueError, "PENDING_ENTRY_DRIFT"):
            R.synthetic_compensate(self.extra, self.work)
        self.assertEqual(self.state_now()["pending"][CODE]["attempts"], 2)

    def test_snapshot_phase_failure_does_not_clear_pending(self):
        with self.assertRaisesRegex(RuntimeError, "INJECTED_AFTER_SNAPSHOT"):
            self.run_pilot(fault="AFTER_SNAPSHOT")
        self.assertIn(CODE, self.state_now()["pending"])
        self.assertFalse((self.work / "capital-recovery-policy").exists())

    def test_after_ledger_fault_detectable_and_compensatable(self):
        with self.assertRaisesRegex(RuntimeError, "INJECTED_AFTER_LEDGER"):
            self.run_pilot(fault="AFTER_LEDGER")
        self.assertNotIn(CODE, self.state_now()["pending"])
        journal = json.loads((self.work / "capital-recovery-journal" /
                              (CODE + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(journal["phase"], "POLICY_RECORDED")
        compensated = R.synthetic_compensate(self.extra, self.work)
        self.assertTrue(compensated["pending_restored"])

    def test_no_external_provider_calls_in_synthetic_rehearsal(self):
        from unittest.mock import patch
        with patch.object(I, "_worker_batch", side_effect=AssertionError("QMT called")), \
             patch.object(I, "_recover_utf8_group", side_effect=AssertionError("QMT called")):
            self.run_pilot()


if __name__ == "__main__":
    unittest.main()
