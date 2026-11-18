"""Guard against repeating a systemic QMT Capital source history revision."""
from __future__ import annotations

import unittest

import qmt_extra_financial_cache_import as I


class MassFinancialConflictGuardTests(unittest.TestCase):
    def test_few_pending_stock_errors_dont_block_incremental(self):
        data = {"pending": {str(i): {"reason": "SOURCE_HISTORY_CONFLICT"}
                            for i in range(17)}}
        I._guard_mass_history_conflicts(data, 5655)
        self.assertEqual(len(data["pending"]), 17)

    def test_systemic_capital_revision_stops_without_state_changes(self):
        data = {"pending": {str(i): {"reason": "SOURCE_HISTORY_CONFLICT"}
                            for i in range(4300)},
                "daily_cursor": "688258.SH",
                "daily_date": "2026-11-18"}
        import copy
        before = copy.deepcopy(data)
        with self.assertRaisesRegex(RuntimeError,
                                    "MASS_FINANCIAL_SOURCE_HISTORY_CONFLICT_GUARD"):
            I._guard_mass_history_conflicts(data, 5655)
        self.assertEqual(data, before)

    def test_real_daily_runner_aborts_before_worker_and_any_cursor_write(self):
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch
        import copy
        import tempfile
        from pathlib import Path
        saved = {"pending": {str(i): {"reason": "SOURCE_HISTORY_CONFLICT"}
                             for i in range(4300)},
                 "import_cursor": "ZZZZZZ", "daily_cursor": "688258.SH",
                 "daily_date": "2026-11-18"}
        baseline = copy.deepcopy(saved)
        calls = []
        catalog = [f"{i:06d}.SH" for i in range(5655)]
        def forbidden_worker(*args, **kwargs):
            calls.append("worker")
            raise AssertionError("Financial worker must not run under mass guard")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(I, "_state", return_value=saved), patch.object(
                    I, "_stock_universe", return_value=(catalog, {})), patch.object(
                    I.E, "_storage", return_value=root):
                with self.assertRaisesRegex(RuntimeError, "MASS_FINANCIAL"):
                    I.run(root, xt=object(), mode="daily", apply=True,
                          worker=forbidden_worker,
                          clock=lambda: datetime(2026, 11, 18, 16, 30,
                                                 tzinfo=timezone(timedelta(hours=8))),
                          progress=lambda _: None)
        self.assertEqual(calls, [])
        self.assertEqual(saved, baseline)

    def test_unrelated_pending_errors_dont_trip_history_revision_guard(self):
        data = {"pending": {str(i): {"reason": "CACHE_DECODE_ERROR"}
                            for i in range(4300)}}
        I._guard_mass_history_conflicts(data, 5655)

    def test_not_a_global_quarantine_if_relatively_small_portion(self):
        data = {"pending": {str(i): {"reason": "SOURCE_HISTORY_CONFLICT"}
                            for i in range(500)}}
        I._guard_mass_history_conflicts(data, 6000)

    def test_mass_past_threshold_rejects_unknown_catalog_or_corrupt_pending(self):
        I._guard_mass_history_conflicts({"pending": {}}, 0)
        with self.assertRaisesRegex(ValueError, "Malformed"):
            I._guard_mass_history_conflicts({"pending": []}, 6000)


if __name__ == "__main__":
    unittest.main()
