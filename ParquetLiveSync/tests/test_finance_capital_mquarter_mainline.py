"""Small synthetic smoke test for opt-in Capital.m_quarter mainline recovery.

No QMT network access, real data modifications, or scheduled task execution.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I


CODE = "002237.SZ"
OLD = {"_index": "0", "m_timetag": 20260930, "m_anntime": 20261028,
       "m_quarter": 0.0, "total_capital": 100.0,
       "circulating_capital": 80.0}
FRESH = dict(OLD, m_quarter=6750319.0)


class MainlineCapitalMetadataSmoke(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.extra = self.root / "qmt_extra"
        self.work = self.root / "work"
        self.work.mkdir()
        E._snapshot_write(
            self.extra, "financial/Capital/" + CODE, "2026-11-17",
            E.snapshot_table("2026-11-17", CODE, "Capital", [OLD]),
            workspace=self.work)
        state = I._state(self.extra, self.work)
        state["pending"][CODE] = {
            "reason": "SOURCE_HISTORY_CONFLICT", "attempts": 1,
            "asof": "2026-11-18",
            "detail": "SOURCE_HISTORY_CONFLICT " + CODE + " table=Capital"}
        I._save_state(self.work, state)

    def run_cache(self, row, *, opt_in):
        nine = {table: [] for table in E.FIN_TABLES}
        nine["Capital"] = [row]
        with patch.object(I.E, "_storage", return_value=self.extra), patch.object(
                I, "_stock_universe", return_value=([CODE], {})), patch.object(
                    I, "_recover_utf8_group", return_value=[(CODE, nine, None)]):
            return I.run(
                self.root, xt=object(), mode="cache", apply=True,
                max_symbols=1, batch_size=1,
                retry_pending=True, workspace=self.work,
                capital_mquarter_nonbusiness=opt_in,
                clock=lambda: datetime(2026, 11, 18, 18, 30, tzinfo=E.L.UTC8),
                progress=lambda _: None)

    def test_opt_in_recovers_only_mquarter_drift_and_preserves_old_parquet(self):
        prior = E._financial_snapshot_file(
            self.extra, CODE, "Capital", "2026-11-17")
        old_hash = E.L.hash_file(prior)
        result = self.run_cache(dict(FRESH), opt_in=True)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["new_snapshots"], 1)
        self.assertEqual(result["pending_total"], 0)
        self.assertEqual(E.L.hash_file(prior), old_hash)
        self.assertIsNotNone(E._financial_snapshot_file(
            self.extra, CODE, "Capital", "2026-11-18"))

    def test_default_strict_mode_does_not_waive_historical_difference(self):
        result = self.run_cache(dict(FRESH), opt_in=False)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["pending_total"], 1)

    def test_changed_real_total_capital_stays_quarantined(self):
        result = self.run_cache(dict(FRESH, total_capital=101.0), opt_in=True)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["pending_total"], 1)

    def test_added_report_date_stays_quarantined(self):
        nine = {table: [] for table in E.FIN_TABLES}
        nine["Capital"] = [dict(FRESH),
                           dict(FRESH, _index="1", m_timetag=20261231)]
        with patch.object(I.E, "_storage", return_value=self.extra), patch.object(
                I, "_stock_universe", return_value=([CODE], {})), patch.object(
                    I, "_recover_utf8_group", return_value=[(CODE, nine, None)]):
            result = I.run(
                self.root, xt=object(), mode="cache", apply=True,
                max_symbols=1, batch_size=1, retry_pending=True,
                workspace=self.work, capital_mquarter_nonbusiness=True,
                clock=lambda: datetime(2026, 11, 18, 18, 30, tzinfo=E.L.UTC8),
                progress=lambda _: None)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["pending_total"], 1)


if __name__ == "__main__":
    unittest.main()
