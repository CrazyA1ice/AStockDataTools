"""Focused ×100 5min session diagnostics: synthetic, no purchased rows."""
import copy
import importlib.util
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "tools" /
          "analyze-5min-x100-focused-sessions.py")
SPEC = importlib.util.spec_from_file_location("focused_sessions_x100", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def baseline():
    top = [
        ("SH688629", 33, {"volume_amount_price": 28, "volume_amount": 4,
                          "volume": 1}),
        ("SH688017", 32, {"volume_amount_price": 25, "volume_amount": 7}),
        ("SH688172", 30, {"volume_amount_price": 19, "volume_amount": 8,
                          "volume_price": 2, "volume": 1})
    ]
    return {
        "format": "AStockDataTools H5-Parquet local coverage/difference report v1",
        "status": "complete", "requested_years": [2026],
        "requested_periods": ["5min"], "requested_from_date": "2026-09-28",
        "requested_to_date": "2026-09-28", "universe_mode": "a-share-candidate",
        "eligible_for_automatic_union": False,
        "results": {"5min/2026": {
            "scan_complete": True, "issues": [],
            "safe_to_automatically_union": False,
            "quantity_scale_diagnostics": {
                "h5_volume_times_100_candidate": {
                    "exact_masks_are_mutually_exclusive": True,
                    "exact_residual_field_mask_counts": {
                        k: 0 for k in M.MASKS
                    },
                    "exact_residual_top_stock_days": [
                        {"symbol": s, "day": "20260928",
                         "candidate_conflicting_bars": n,
                         "field_mask_counts": masks}
                        for s, n, masks in top]
                }
            }
        }}
    }


class FocusedX100SessionTests(unittest.TestCase):
    def setUp(self):
        self.symbol = "SH688629"
        self.ts = (202609280935, 202609280940,
                   202609281305, 202609281310)
        self.h5 = {
            (self.symbol, t): (10, 11, 9, 10, 10, 1000)
            for t in self.ts
        }
        p = [
            (10.03, 11, 9, 10, 1200, 2005000),
            (10, 11, 9, 10, 800, 1000),
            (10.03, 11, 9, 10, 1000, 1000),
            (10, 11, 9, 10, 1000, 1000),
        ]
        self.parquet = {
            (self.symbol, M.diagnose.shift_bar_stamp(t, -5)): value
            for t, value in zip(self.ts, p)
        }
        self.selected = {self.symbol: {
            "volume_amount_price": 1, "volume": 1, "price": 1
        }}

    def test_baseline_selects_real_top_three_and_validates_hypotheses(self):
        got = M.load_baseline(baseline(), __import__("datetime").date(2026, 9, 28), 3)
        self.assertEqual(list(got), ["SH688629", "SH688017", "SH688172"])
        self.assertEqual(got["SH688629"]["volume_amount_price"], 28)
        self.assertFalse("none" in got["SH688629"])
        with self.assertRaisesRegex(ValueError, "top-symbols"):
            M.load_baseline(baseline(), __import__("datetime").date(2026, 9, 28), 9)

    def test_one_hundred_scale_exact_masks_and_session_conservation(self):
        before = copy.deepcopy(self.h5)
        got = M.summarized_pair_masks(self.h5, self.parquet, self.selected)
        item = got[self.symbol]
        self.assertEqual(self.h5, before)
        self.assertEqual(item["h5_5min_bars"], 4)
        self.assertEqual(item["exact_residual_masks"]["none"], 1)
        self.assertEqual(item["exact_residual_masks"]["volume"], 1)
        self.assertEqual(item["exact_residual_masks"]["volume_amount_price"], 1)
        self.assertEqual(item["exact_residual_masks"]["price"], 1)
        self.assertEqual(item["sessions"]["morning"]["exact_residual_masks"][
            "volume_amount_price"], 1)
        self.assertEqual(item["sessions"]["afternoon"]["exact_residual_masks"][
            "price"], 1)
        v = item["sessions"]["morning"]["volume"]
        self.assertEqual(v["matched_bars"], 2)
        self.assertEqual(v["different_bars"], 2)
        self.assertEqual(v["source_total_ratio_parquet_over_h5"], 1)
        self.assertEqual(v["net_difference_pct_of_h5_total"], 0)
        self.assertEqual(v["gross_bar_difference_pct_of_h5_total"], 20)
        self.assertEqual(v["cancellation_fraction"], 1)
        self.assertEqual(v["adjacent_opposite_sign_pairs"], 1)
        self.assertEqual(item["candidate_volume_factor_h5"], 100)
        self.assertTrue(item["not_proof_of_boundary_reallocation"])

    def test_existing_baseline_disagreement_fails_closed(self):
        self.selected[self.symbol]["volume_amount_price"] = 2
        with self.assertRaisesRegex(ValueError, "do not reproduce"):
            M.summarized_pair_masks(self.h5, self.parquet, self.selected)

    def test_selected_unmatched_keys_do_not_invent_conflicts(self):
        stamp = 202609281315
        self.h5[(self.symbol,stamp)] = (10,11,9,10,10,1000)
        got = M.summarized_pair_masks(self.h5, self.parquet, self.selected)
        item = got[self.symbol]
        self.assertEqual(item["h5_only_bars"], 1)
        self.assertEqual(item["conservation_on_matched_keys_only"][
            "matched_bars"], 4)
        self.assertEqual(sum(item["exact_residual_masks"].values()), 4)

    def test_reject_invalid_date_and_incomplete_baseline(self):
        d = __import__("datetime").date(2026,9,28)
        src=baseline()
        src["results"]["5min/2026"]["scan_complete"] = False
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            M.load_baseline(src,d,3)
        src=baseline()
        src["results"]["5min/2026"][
            "quantity_scale_diagnostics"]["h5_volume_times_100_candidate"][
            "exact_residual_top_stock_days"][0]["field_mask_counts"]["none"] = 1
        with self.assertRaisesRegex(ValueError, "Invalid top"):
            M.load_baseline(src,d,3)
        with self.assertRaisesRegex(ValueError, "matching completed"):
            M.load_baseline(baseline(), __import__("datetime").date(2026,9,29),3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
