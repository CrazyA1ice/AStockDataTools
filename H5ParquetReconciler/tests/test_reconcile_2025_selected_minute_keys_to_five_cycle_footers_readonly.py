"""Synthetic 2025 full-year verified-minute versus five footer reconciliation."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "2025_minute_footer_grid_reconciliation_tests",
    HERE.parent / "tools" /
    "reconcile-2025-selected-minute-keys-to-five-cycle-footers-readonly.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

ROWS = {
    "1min": 321744640, "5min": 64081920, "15min": 21360640,
    "30min": 10680320, "60min": 5340160,
}
STOCKDAYS = 1316686


class AnnualFiveCycleReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rows = dict(ROWS)
        self.source_stat = {"source_metadata_fingerprint_sha256": "synthetic"}

    def fake_receipt(self, month, root, fingerprint):
        n = STOCKDAYS if month == "2025-01" else 0
        return {
            "periods": {
                "1min": {"stockdays": n, "keys": 241 * n},
                "5min": {"stockdays": n, "keys": 48 * n},
            }
        }

    def fake_files(self, root, periods, first, last):
        self.assertEqual((first, last), (2025, 2025))
        return ({p: {2025: [self.root / "AllCycleAStockData" / p / "2025.parquet"]}
                 for p in periods}, {"some_unassigned_year_files": 0})

    def fake_footer(self, root, paths, year, period, maxgroups):
        self.assertEqual(year, 2025)
        self.assertEqual(len(paths), 1)
        return {
            "row_groups": 1,
            "nonempty_row_groups_without_usable_ts_bounds": 0,
            "row_groups_with_any_ts_bounds_outside_named_year": 0,
            "footer_envelope_complete_for_nonempty_row_groups": True,
            "source_rows_from_parquet_footers": self.rows[period],
        }

    def checks(self, receipt=None):
        import contextlib
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(
            M.B.A.I.N, "source_snapshot", return_value=self.source_stat))
        stack.enter_context(patch.object(
            M.B, "verified_receipt", side_effect=receipt or self.fake_receipt))
        stack.enter_context(patch.object(
            M.F, "source_files", side_effect=self.fake_files))
        stack.enter_context(patch.object(
            M.F, "year_period_footer", side_effect=self.fake_footer))
        return stack

    def test_2025_exact_source_total_and_unselected_grid_equivalent(self):
        with self.checks():
            out = M.reconcile(self.root)
        self.assertEqual(out["selected_ashare_stockdays"], 1316686)
        self.assertEqual(out["selected_ashare_minute_keys"]["1min"], 317321326)
        self.assertEqual(out["selected_ashare_minute_keys"]["5min"], 63200928)
        self.assertEqual(out["unselected_source_rows_unknown_security_class"],
                         {"1min": 4423314, "5min": 880992})
        self.assertEqual(out[
            "unselected_source_standard_grid_equivalents_not_certified_stockdays"
        ], 18354)
        self.assertEqual(set(out["whole_source_standard_stockday_equivalents_by_cycle"].values()),
                         {1335040})
        self.assertEqual(len(out["verified_2025_grid_months"]), 12)
        self.assertFalse(out["unselected_source_security_categories_classified"])
        self.assertFalse(out["production_source_activated"])
        self.assertFalse(out["purchased_ohlcva_bars_opened_or_copied"])

    def test_missing_month_receipt_rejected(self):
        def missing(month, root, fingerprint):
            return None if month == "2025-05" else self.fake_receipt(
                month, root, fingerprint)
        with self.checks(receipt=missing):
            with self.assertRaisesRegex(ValueError, "Missing completed"):
                M.reconcile(self.root)

    def test_five_cycle_source_stockday_equivalent_disagreement_rejected(self):
        self.rows["15min"] += 16
        with self.checks():
            with self.assertRaisesRegex(ValueError, "disagree"):
                M.reconcile(self.root)

    def test_nonmultiple_footer_rows_rejected(self):
        self.rows["5min"] -= 1
        with self.checks():
            with self.assertRaisesRegex(ValueError, "standard-grid multiples"):
                M.reconcile(self.root)

    def test_selected_keys_must_not_exceed_whole_source(self):
        self.rows["1min"] = STOCKDAYS * 241 - 241
        with self.checks():
            with self.assertRaisesRegex(ValueError, "disagree|exceed"):
                M.reconcile(self.root)

    def test_safe_file_budget_rejected(self):
        with self.checks():
            with self.assertRaisesRegex(ValueError, "overbudget"):
                M.reconcile(self.root, max_source_files=4)

    def test_reconciliation_produces_no_disk_reports(self):
        before = list(self.root.iterdir())
        with self.checks():
            M.reconcile(self.root)
        self.assertEqual(before, list(self.root.iterdir()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
