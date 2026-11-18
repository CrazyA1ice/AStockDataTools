"""Small targeted tests for cached pending retries, without QMT/network use."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I

CODES = ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ")


class CachedPendingRotationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.extra = self.root / "qmt_extra"
        self.work = self.root / "work"
        self.work.mkdir()
        state = I._state(self.extra, self.work)
        state["pending"] = {code: {
            "reason": "SOURCE_HISTORY_CONFLICT",
            "detail": "SOURCE_HISTORY_CONFLICT " + code + " table=Capital",
            "attempts": 1, "asof": "2026-11-18"}
            for code in CODES}
        I._save_state(self.work, state)

    def run_retry(self, visited, size=2, groups=None):
        def retry_worker(_worker, group, _mode, _asof, _lookback, _work,
                         _timeout, _progress):
            if group != sorted(set(group)):
                raise AssertionError("Worker group crosses the retry wrap")
            if groups is not None:
                groups.append(list(group))
            visited.extend(group)
            return [(code, None, "NO_CACHE") for code in group]
        with patch.object(I.E, "_storage", return_value=self.extra), patch.object(
                I, "_stock_universe",
                side_effect=AssertionError("cached pending retries need no universe")), patch.object(
                    I, "_recover_utf8_group", side_effect=retry_worker):
            return I.run(
                self.root, xt=object(), mode="cache", apply=True,
                max_symbols=size, batch_size=2, retry_pending=True,
                workspace=self.work, capital_mquarter_nonbusiness=True,
                clock=lambda: datetime(2026, 11, 18, 18, 30, tzinfo=E.L.UTC8),
                progress=lambda _: None)

    def test_first_pending_batch_skips_expensive_full_universe_scan(self):
        visited = []
        report = self.run_retry(visited)
        self.assertEqual(visited, list(CODES[:2]))
        self.assertEqual(
            report["universe_metadata"]["source_scope"],
            "VERIFIED_PRIVATE_PENDING_LEDGER_ONLY")
        self.assertFalse(report["universe_metadata"]["finance_directory_scanned"])
        self.assertEqual(report["pending_total"], 4)
        self.assertEqual(report["pending_retry_cursor_end"], "000002.SZ")
        self.assertEqual(I._state(self.extra, self.work)["import_cursor"], "")

    def test_unresolved_first_stock_cannot_starve_later_pending(self):
        visited = []
        self.run_retry(visited)
        self.run_retry(visited)
        self.run_retry(visited)
        self.assertEqual(visited, list(CODES[:2]) + list(CODES[2:]) +
                         list(CODES[:2]))
        self.assertEqual(I._state(self.extra, self.work)["daily_cursor"], "")
        self.assertEqual(I._state(self.extra, self.work)["import_cursor"], "")

    def test_rotated_pending_wrap_never_produces_unsorted_worker_batch(self):
        # The last BJ stock followed by the first lower-code pending stock
        # must be two QMT requests, never one non-monotonic worker group.
        state = I._state(self.extra, self.work)
        state["pending_retry_cursor"] = CODES[2]
        I._save_state(self.work, state)
        visited, groups = [], []
        report = self.run_retry(visited, size=4, groups=groups)
        self.assertEqual(groups, [[CODES[3]], list(CODES[:2]), [CODES[2]]])
        self.assertEqual(visited, [CODES[3], CODES[0], CODES[1], CODES[2]])
        self.assertEqual(report["pending_total"], 4)
        self.assertEqual(report["pending_retry_cursor_end"], CODES[2])

    def test_empty_pending_skips_worker_and_universe_without_writes(self):
        state = I._state(self.extra, self.work)
        state["pending"] = {}
        I._save_state(self.work, state)
        before = I._state(self.extra, self.work)
        with patch.object(I.E, "_storage", return_value=self.extra), patch.object(
                I, "_stock_universe", side_effect=AssertionError("no universe")), patch.object(
                    I, "_recover_utf8_group", side_effect=AssertionError("no worker")):
            report = I.run(
                self.root, xt=object(), mode="cache", apply=True,
                retry_pending=True, workspace=self.work,
                clock=lambda: datetime(2026, 11, 18, 18, 30, tzinfo=E.L.UTC8),
                progress=lambda _: None)
        self.assertEqual(report["status"], "NO_PENDING")
        self.assertEqual(I._state(self.extra, self.work), before)

    def test_regular_non_pending_preview_still_queries_market_universe(self):
        seen = []
        def catalog(*_args):
            seen.append(True)
            return list(CODES), {"source_scope": "NORMAL_MARKET"}
        with patch.object(I.E, "_storage", return_value=self.extra), patch.object(
                I, "_stock_universe", side_effect=catalog):
            report = I.run(
                self.root, xt=object(), mode="cache", apply=False,
                retry_pending=False, workspace=self.work,
                clock=lambda: datetime(2026, 11, 18, 18, 30, tzinfo=E.L.UTC8),
                progress=lambda _: None)
        self.assertEqual(seen, [True])
        self.assertEqual(report["universe_symbols"], 4)


if __name__ == "__main__":
    unittest.main()
