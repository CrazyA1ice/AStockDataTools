"""Offline QMT-primary financial import tests; no live QMT/download/scheduler."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I


CODE = "000010.SZ"
PREV = "2026-11-18"
TODAY = "2026-11-23"


def record(day, shares, *, index="0"):
    return {"_index": index, "m_timetag": day, "m_quarter": 3.0,
            "freeFloatCapital": shares, "m_anntime": day}


class QMTPrimaryImmutableVersionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.extra = self.root / "qmt_extra"
        self.workspace = self.root / "work"
        self.workspace.mkdir()
        self.old_capital = record(20260930, 100)
        self.old_holder = {"_index": "0", "m_timetag": 20260930,
                           "holderName": "before", "shares": 100}
        self.old_files = {}
        for table, row in (("Capital", self.old_capital),
                           ("Top10Holder", self.old_holder)):
            path = E._snapshot_path(
                self.extra, "financial/" + table + "/" + CODE, PREV,
                E.snapshot_table(PREV, CODE, table, [row]))
            E._snapshot_write(
                self.extra, "financial/" + table + "/" + CODE, PREV,
                E.snapshot_table(PREV, CODE, table, [row]),
                workspace=self.workspace)
            E._pin_financial_snapshot(self.extra, CODE, table, PREV, path)
            self.old_files[table] = (path, E.L.hash_file(path))
        state = I._state(self.extra, self.workspace)
        state["pending"][CODE] = {
            "reason": "SOURCE_HISTORY_CONFLICT", "asof": PREV,
            "attempts": 2, "detail":
                "SOURCE_HISTORY_CONFLICT " + CODE + " table=Capital"}
        I._save_state(self.workspace, state)

    def source(self):
        values = {name: [] for name in E.FIN_TABLES}
        values["Capital"] = [
            record(20260930, 101),
            record(20261231, 101, index="1")]
        values["Top10Holder"] = [
            dict(self.old_holder, holderName="after")]
        return values

    def call(self, *, source=None, primary=False, apply=True):
        source = self.source() if source is None else source
        with patch.object(I.E, "_storage", return_value=self.extra), \
             patch.object(I, "_stock_universe",
                          side_effect=AssertionError("no full-universe scan")), \
             patch.object(I, "_recover_utf8_group",
                          return_value=[(CODE, source, None)]) as worker:
            result = I.run(
                self.root, xt=object(), mode="cache", apply=apply,
                retry_pending=True, max_symbols=1, batch_size=1,
                workspace=self.workspace, qmt_primary_versioned=primary,
                clock=lambda: datetime(2026, 11, 23, 16, 30,
                                       tzinfo=E.L.UTC8),
                progress=lambda msg: None)
        if apply:
            worker.assert_called_once()
        else:
            worker.assert_not_called()
        return result

    def test_strict_default_still_quarantines_history_revisions(self):
        report = self.call(primary=False)
        self.assertEqual(report["processed"], 0)
        self.assertEqual(report["pending_total"], 1)
        self.assertEqual(report["new_snapshots"], 0)
        self.assertFalse(report["qmt_primary_versioned"])
        for table, (path, digest) in self.old_files.items():
            self.assertEqual(E.L.hash_file(path), digest)

    def test_explicit_qmt_primary_commits_two_revised_tables_and_keeps_old(self):
        report = self.call(primary=True)
        self.assertEqual(report["processed"], 1)
        self.assertEqual(report["pending_total"], 0)
        self.assertEqual(report["new_snapshots"], 2)
        self.assertTrue(report["qmt_primary_versioned"])
        self.assertEqual(I._state(self.extra, self.workspace)["pending"], {})
        for table, (path, digest) in self.old_files.items():
            self.assertEqual(E.L.hash_file(path), digest)
            self.assertEqual(
                E._financial_snapshot_file(self.extra, CODE, table, PREV),
                path)
            fresh = E._financial_snapshot_rows(self.extra, CODE, table, TODAY)
            self.assertIsNotNone(fresh)
            self.assertEqual(fresh, self.source()[table])
        coverage = (self.workspace / "financial-coverage.jsonl").read_text(
            encoding="utf-8")
        self.assertIn('"qmt_primary_versioned":true', coverage)
        self.assertIn('"historical_records_not_in_current":1', coverage)
        self.assertIn('"provider_source_certified":false', coverage)

    def test_latest_selected_version_is_idempotent(self):
        self.call(primary=True)
        report, staged = I._plan_symbol(
            self.extra, CODE, TODAY, self.source(),
            qmt_primary_versioned=True)
        self.assertEqual(staged, {})
        self.assertEqual(report["Capital"]["action"], "UNCHANGED")
        self.assertEqual(report["Top10Holder"]["action"], "UNCHANGED")
        self.assertGreater(report["Capital"]["historical_records_not_in_current"],
                           0)

    def test_missing_current_table_keeps_previously_selected_data(self):
        fresh = self.source()
        fresh["Top10Holder"] = []
        result = self.call(source=fresh, primary=True)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["new_snapshots"], 1)
        self.assertIsNone(E._financial_snapshot_file(
            self.extra, CODE, "Top10Holder", TODAY))
        self.assertEqual(E._financial_snapshot_rows(
            self.extra, CODE, "Top10Holder", PREV), [self.old_holder])
        coverage = (self.workspace / "financial-coverage.jsonl").read_text(
            encoding="utf-8")
        self.assertIn("SOURCE_EMPTY_OLD_RETAINED", coverage)

    def test_preview_has_no_writes_or_qmt_worker(self):
        state_before = (self.workspace / I.STATE_FILE).read_bytes()
        result = self.call(primary=True, apply=False)
        self.assertEqual(result["status"], "PREVIEW")
        self.assertTrue(result["qmt_primary_versioned"])
        self.assertEqual(state_before,
                         (self.workspace / I.STATE_FILE).read_bytes())
        self.assertIsNone(E._financial_snapshot_file(
            self.extra, CODE, "Capital", TODAY))

    def test_corrupt_source_shape_blocks_before_any_snapshot(self):
        bad = self.source()
        bad["Capital"][0].pop("_index")
        with self.assertRaisesRegex(ValueError, "Invalid QMT cache response"):
            self.call(source=bad, primary=True)
        self.assertIsNone(E._financial_snapshot_file(
            self.extra, CODE, "Capital", TODAY))
        self.assertIn(CODE, I._state(self.extra, self.workspace)["pending"])

    def test_policies_cannot_be_combined(self):
        with self.assertRaisesRegex(ValueError, "exclusive"):
            I.run(self.root, xt=object(), qmt_primary_versioned=True,
                  capital_mquarter_nonbusiness=True)


if __name__ == "__main__":
    unittest.main()
