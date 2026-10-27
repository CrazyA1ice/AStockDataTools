"""Synthetic, license-free actual-bar selection for manual THS validation."""
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "tools" /
          "prepare-5min-tonghuashun-spotcheck.py")
SPEC = importlib.util.spec_from_file_location("safe_ths_spotchecks", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class THSManualSpotcheckTests(unittest.TestCase):
    def setUp(self):
        self.symbol = "SH688629"
        ends = (202609280935, 202609281030, 202609281120,
                202609281305, 202609281425)
        self.h = {
            (self.symbol, t): (10, 11, 9, 10, 10, 1000)
            for t in ends
        }
        # Every row differs from H5 volume×100. Two have changed OHLC.
        p = [
            (10.01, 11, 9, 10, 1100, 2005000),
            (10.11, 11, 9, 10, 1000, 1000),
            (10, 11, 9, 10, 1100, 1000),
            (10.03, 11, 9, 10, 1200, 1000),
            (10, 11, 9, 10, 1100, 1000),
        ]
        self.p = {
            (self.symbol, M.diagnose.shift_bar_stamp(t, -5)): row
            for t, row in zip(ends, p)
        }

    def test_selects_true_diff_and_prioritizes_morning_afternoon(self):
        selected = M.select_verification_rows(
            self.h, self.p, (self.symbol,), 3)
        self.assertEqual(len(selected), 3)
        ends = [r["bar_end"] for r in selected]
        self.assertIn(202609281030, ends)
        self.assertIn(202609281305, ends)
        self.assertIn(202609280935, ends)
        self.assertTrue(all(r["different_fields"] for r in selected))
        self.assertTrue(any("open" in r["different_fields"] for r in selected))
        self.assertEqual(selected[0]["interval_start"],
                         "2026-09-28 09:30")

    def test_identical_bars_are_never_selected(self):
        self.p = {
            (sym, t): (10, 11, 9, 10, 1000, 1000)
            for (sym, t) in self.p
        }
        self.assertEqual(M.select_verification_rows(
            self.h, self.p, (self.symbol,), 3), [])

    def test_h5_lot_to_share_candidate_is_applied_before_comparison(self):
        h = (10, 11, 9, 10, 1000, 1000)
        p = (10, 11, 9, 10, 1000, 1000)
        self.assertEqual(M.discrepancy_fields(h, p), [])
        self.assertEqual(M.discrepancy_fields(
            (10, 11, 9, 10, 100, 1000), p), ["volume"])
        with self.assertRaises(ValueError):
            M.discrepancy_fields(
                (10, 11, 9, 10, float("nan"), 1000), p)

    def test_safe_report_never_serializes_paid_ohlcv(self):
        samples = M.select_verification_rows(
            self.h, self.p, (self.symbol,), 3)
        report = M.safe_report(
            samples, (self.symbol,), date(2026, 9, 28),
            "exact.json", {"parquet_row_groups_read": 47})
        wire = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("h_normalized", wire)
        self.assertNotIn('"p":', wire)
        self.assertNotIn("2005000", wire)
        self.assertEqual(report["selected_points"], 3)
        self.assertFalse(report["raw_source_ohlcv_exported"])
        self.assertFalse(report["safe_to_automatically_union"])
        self.assertTrue(report["manual_ths_comparison_not_yet_performed"])
        self.assertTrue(all("bar_interval_end_beijing" in bar
                            for bar in report[
                                "verification_points_by_symbol"][self.symbol]))

    def test_opt_in_terminal_prints_values_without_modifying_report(self):
        sample = M.select_verification_rows(
            self.h, self.p, (self.symbol,), 3)
        with io.StringIO() as buf, redirect_stdout(buf):
            M.show_values_only_locally(sample)
            printed = buf.getvalue()
        self.assertIn("LOCAL DISPLAY ONLY", printed)
        self.assertIn("2005000", printed)
        self.assertIn("H5=", printed)
        self.assertIn("Parquet=", printed)
        self.assertIn("2026-09-28", printed)

    def test_reject_overlarge_or_zero_manual_sample(self):
        with self.assertRaisesRegex(ValueError, "1..8"):
            M.select_verification_rows(self.h, self.p, (self.symbol,), 0)
        with self.assertRaisesRegex(ValueError, "1..8"):
            M.select_verification_rows(self.h, self.p, (self.symbol,), 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
