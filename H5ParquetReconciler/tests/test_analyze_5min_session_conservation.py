"""Synthetic regression for per-session 5min redistribution and price continuity tests."""
import importlib.util
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "tools" / "analyze-5min-session-conservation.py"
SPEC = importlib.util.spec_from_file_location("session_conservation", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class SessionConservationTests(unittest.TestCase):
    def setUp(self):
        self.symbol = "SH600000"
        self.good = (10, 12, 9, 11, 100, 1000)

    def test_opposite_bar_deltas_have_near_zero_net_and_nonzero_gross(self):
        h5 = [(202509300935, (10, 12, 9, 11, 100, 1000),
               (10, 12, 9, 11, 110, 1100)),
              (202509300940, (10, 12, 9, 11, 100, 1000),
               (10, 12, 9, 11, 90, 900))]
        v = M.field_conservation(h5, 4, "volume")
        self.assertEqual(v["matched_bars"], 2)
        self.assertEqual(v["different_bars"], 2)
        self.assertEqual(v["source_total_ratio_parquet_over_h5"], 1)
        self.assertEqual(v["net_difference_pct_of_h5_total"], 0)
        self.assertEqual(v["gross_bar_difference_pct_of_h5_total"], 10)
        self.assertEqual(v["cancellation_fraction"], 1)
        self.assertEqual(v["max_cumulative_imbalance_pct"], 5)
        self.assertEqual(v["adjacent_nonzero_difference_pairs"], 1)
        self.assertEqual(v["adjacent_opposite_sign_pairs"], 1)

    def test_same_sign_bar_deltas_are_not_misdiagnosed_as_redistribution(self):
        pairs = [(202509300935, (10, 12, 9, 11, 100, 1000),
                  (10, 12, 9, 11, 110, 1200)),
                 (202509300940, (10, 12, 9, 11, 100, 1000),
                  (10, 12, 9, 11, 120, 1100))]
        vol = M.field_conservation(pairs, 4, "volume")
        self.assertEqual(vol["cancellation_fraction"], 0)
        self.assertEqual(vol["adjacent_opposite_sign_pairs"], 0)
        self.assertEqual(vol["net_difference_pct_of_h5_total"], 15)
        self.assertEqual(vol["gross_bar_difference_pct_of_h5_total"], 15)

    def test_price_geometry_flags_internal_ohlc_violations(self):
        self.assertFalse(M.invalid_ohlc((10, 11, 9, 10, 100, 1000)))
        self.assertTrue(M.invalid_ohlc((10, 9.9, 9, 10, 100, 1000)))
        self.assertTrue(M.invalid_ohlc((10, 11, 10.1, 10, 100, 1000)))
        self.assertTrue(M.invalid_ohlc((10, 9, 11, 10, 100, 1000)))

    def test_lunch_gap_is_not_treated_as_adjacent(self):
        pairs = [(202509301130, (10, 11, 9, 10, 100, 1000),
                  (10, 11, 9, 10, 110, 1100)),
                 (202509301305, (10, 11, 9, 10, 100, 1000),
                  (10, 11, 9, 10, 90, 900))]
        summary = M.field_conservation(pairs, 4, "volume")
        self.assertEqual(summary["adjacent_pairs"], 0)
        self.assertEqual(summary["adjacent_opposite_sign_pairs"], 0)
        self.assertEqual(M.session_name(202509301130), "morning")
        self.assertEqual(M.session_name(202509301305), "afternoon")

    def test_price_boundary_match_uses_only_adjacent_bars(self):
        # Diff at second bar: H5 new open equals previous PQ close, while
        # the PQ current close equals next H5 open at third bar.
        pairs = [
            (202509300935, (9, 11, 8, 10, 100, 1000),
             (9, 11, 8, 10, 100, 1000)),
            (202509300940, (10, 12, 9, 11, 100, 1000),
             (10.01, 12, 9, 10.01, 100, 1000)),
            (202509300945, (10.01, 12, 9, 11, 100, 1000),
             (10.01, 12, 9, 11, 100, 1000))]
        result = M.boundary_price_stats(pairs)
        self.assertEqual(result["open_different_bars"], 1)
        self.assertEqual(result["open_diff_with_previous_contiguous_bar"], 1)
        self.assertEqual(result["h5_open_equals_previous_parquet_close"], 1)
        self.assertEqual(result["close_different_bars"], 1)
        self.assertEqual(result["close_diff_with_next_contiguous_bar"], 1)
        self.assertEqual(result["parquet_close_equals_next_h5_open"], 1)

    def test_missing_h5_symbol_does_not_create_price_difference(self):
        symbol = "BJ920680"
        p = {(symbol, 202509300930): (10, 11, 9, 10, 100, 1000)}
        result = M.analyze({}, p, (symbol,))[symbol]
        self.assertEqual(result["h5_5min_bars"], 0)
        self.assertEqual(result["parquet_only_bars"], 1)
        self.assertEqual(result["status"], "no_comparable_bars")
        self.assertEqual(result["conservation_on_matched_keys_only"]["matched_bars"], 0)
        self.assertIsNone(
            result["conservation_on_matched_keys_only"]["volume"]["source_total_ratio_parquet_over_h5"])

    def test_h5_and_parquet_reallocated_morning_afternoon_separately(self):
        sym = "SH600000"
        ends = (202509300935, 202509300940, 202509301305, 202509301310)
        h = {(sym, t): self.good for t in ends}
        amounts = (110, 90, 120, 80)
        p = {(sym, M.diagnostic.shift_bar_stamp(t, -5)):
             (10, 12, 9, 11, value, value * 10)
             for t, value in zip(ends, amounts)}
        got = M.analyze(h, p, (sym,))[sym]
        self.assertEqual(got["conservation_on_matched_keys_only"]["matched_bars"], 4)
        self.assertEqual(got["sessions"]["morning"]["volume"]["cancellation_fraction"], 1)
        self.assertEqual(got["sessions"]["afternoon"]["volume"]["cancellation_fraction"], 1)
        self.assertEqual(got["conservation_on_matched_keys_only"]["amount"]["net_difference_pct_of_h5_total"], 0)
        self.assertEqual(got["h5_ohlc_geometry_violations"], 0)
        self.assertEqual(got["parquet_ohlc_geometry_violations"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
