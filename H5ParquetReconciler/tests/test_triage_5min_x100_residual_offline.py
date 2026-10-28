"""No purchased data: tests for mathematically honest 5min x100 residual bounds."""
import copy
import importlib.util
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "tools" /
          "triage-5min-x100-residual-offline.py")
SPEC = importlib.util.spec_from_file_location("residual_offline_triage", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture():
    # Synthetic partition: 10 overlap keys, 5 volume residual, 4 amount,
    # 3 price, 6 any-residual. Joint membership is intentionally UNKNOWN.
    groups = {
        "SH_other_prefix": {
            "matched": 6, "candidate_h5_volume_x100_mismatch": 4,
            "amount_mismatch": 3, "price_mismatch": 2
        },
        "BJ_prefix": {
            "matched": 4, "candidate_h5_volume_x100_mismatch": 1,
            "amount_mismatch": 1, "price_mismatch": 1
        }
    }
    days = {
        "20260928": {
            "matched": 6, "candidate_h5_volume_x100_mismatch": 4,
            "amount_mismatch": 3, "price_mismatch": 2
        },
        "20260929": {
            "matched": 4, "candidate_h5_volume_x100_mismatch": 1,
            "amount_mismatch": 1, "price_mismatch": 1
        }
    }
    return {
        "format": "AStockDataTools H5-Parquet local coverage/difference report v1",
        "status": "complete",
        "eligible_for_automatic_union": False,
        "results": {
            "5min/2026": {
                "period": "5min", "year": 2026, "from_date": "2026-09-28",
                "to_date": "2026-09-29", "scan_complete": True,
                "issues": [], "safe_to_automatically_union": False,
                "matched_keys": 10, "price_mismatch_rows": 3,
                "quantity_mismatch_rows": 9,
                "by_code_prefix_group": groups, "by_day": days,
                "quantity_scale_diagnostics": {
                    "fields": {"amount": {"different_by_existing_tolerance": 4}},
                    "h5_volume_times_100_candidate": {
                        "source_values_modified": False,
                        "factor_certified": False,
                        "compared_overlap_keys": 10,
                        "legacy_volume_mismatch": 9,
                        "candidate_volume_mismatch": 5,
                        "legacy_mismatch_resolved_by_candidate": 4,
                        "legacy_match_broken_by_candidate": 0,
                        "candidate_value_mismatch_with_original_price_and_amount_rules": 6,
                        "candidate_volume_mismatch_by_day": {
                            "20260928": 4, "20260929": 1
                        }
                    }
                }
            }
        }
    }


class OfflineFiveMinuteResidualTests(unittest.TestCase):
    def test_no_full_venn_claim_from_marginal_counts(self):
        r = M.analyze(fixture())
        self.assertEqual(r["matched_overlap_keys"], 10)
        self.assertEqual(r["candidate_no_field_mismatch"], 4)
        self.assertEqual(r["nonvolume_only_with_price_or_amount_exact"], 1)
        self.assertEqual(r["pairwise_overlap_lower_bounds"], {
            "volume_and_amount": 3, "volume_and_price": 2,
            "amount_and_price": 1
        })
        self.assertEqual(r["three_field_overlap_lower_bound"], 0)
        self.assertTrue(r["all_field_overlap_bounds_not_exact_intersections"])
        self.assertEqual(r["by_code_prefix_group_bounds"][
            "SH_other_prefix"]["candidate_any_mismatch_upper_bound"], 5)
        self.assertEqual(r["by_code_prefix_group_bounds"][
            "BJ_prefix"]["candidate_any_mismatch_lower_bound"], 1)
        self.assertEqual(r["groups_ranked_by_candidate_volume_residual"][0],
                         "SH_other_prefix")
        self.assertFalse(r["underlying_ohlcv_read"])
        self.assertFalse(r["safe_to_automatically_union"])
        self.assertNotIn("symbol", r)

    def test_regression_3440_real_report_marginal_arithmetic(self):
        # These are aggregate-only totals from the user report, not stock bars.
        v, a, p, u = 3097, 2812, 1893, 3440
        self.assertEqual(u-v, 343)
        self.assertEqual(M.intersect_min(v, a, u), 2469)
        self.assertEqual(M.intersect_min(v, p, u), 1550)
        self.assertEqual(M.intersect_min(a, p, u), 1265)
        self.assertEqual(max(0, v+a+p-2*u), 922)
        self.assertEqual(min(v, u-max(a,p)), 628)

    def test_invalid_candidate_conservation_fails_closed(self):
        src = fixture()
        item = src["results"]["5min/2026"]["quantity_scale_diagnostics"][
            "h5_volume_times_100_candidate"]
        item["legacy_mismatch_resolved_by_candidate"] += 1
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            M.analyze(src)

    def test_missing_price_or_amount_daily_partition_refused(self):
        for place, field in [
            ("by_code_prefix_group", "price_mismatch"),
            ("by_day", "amount_mismatch")
        ]:
            src = fixture()
            src["results"]["5min/2026"][place]["SH_other_prefix" if place.startswith("by_code") else "20260928"][field] += 1
            with self.subTest(place=place), self.assertRaisesRegex(
                    ValueError, "Nonconserving"):
                M.analyze(src)

    def test_duplicate_or_malformed_year_window_does_not_pass(self):
        src = fixture()
        src["results"]["5min/2026"]["scan_complete"] = False
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            M.analyze(src)
        src = fixture()
        src["results"]["5min/2026"]["from_date"] = None
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            M.analyze(src)
        src = fixture()
        src["results"]["5min/2026"]["by_day"]["20260928"]["matched"] = True
        with self.assertRaisesRegex(ValueError, "integer"):
            M.analyze(src)
        src = fixture()
        # An entry named day/2026 that still claims period=5min is
        # a duplicate 5min section, not a malformed day companion.
        src["results"]["day/2026"] = copy.deepcopy(src["results"]["5min/2026"])
        with self.assertRaisesRegex(ValueError, "exactly one bounded 5min"):
            M.analyze(src)

        # Once labeled as day, an inconsistent date window must instead
        # fail the distinct day-companion provenance check.
        src["results"]["day/2026"]["period"] = "day"
        src["results"]["day/2026"]["to_date"] = "2026-09-30"
        with self.assertRaisesRegex(ValueError, "Companion day"):
            M.analyze(src)

    def test_disjoint_group_mandatory_nonvolume_bounds(self):
        groups = {
            "g1": {"matched": 10, "volume": 3, "amount": 5, "price": 1},
            "g2": {"matched": 10, "volume": 1, "amount": 1, "price": 1}
        }
        # g1 needs at least 2 nonvolume rows; g2 at least 0.
        bound = M.bounds_for_group(groups, 3)
        self.assertEqual(bound["g1"]["nonvolume_only_lower_bound"], 2)
        self.assertEqual(bound["g1"]["nonvolume_only_upper_bound"], 3)
        self.assertLessEqual(
            bound["g2"]["nonvolume_only_upper_bound"], 1)
        with self.assertRaisesRegex(ValueError, "more non-volume-only"):
            M.bounds_for_group(groups, 1)

    def test_zero_extra_forces_exact_group_unions(self):
        b = M.bounds_for_group({
            "g": {"matched": 8, "volume": 5, "amount": 4, "price": 2}
        }, 0)
        self.assertEqual(b["g"]["candidate_any_mismatch_lower_bound"], 5)
        self.assertEqual(b["g"]["candidate_any_mismatch_upper_bound"], 5)
        self.assertFalse(b["g"]["breakdown_is_exact"])


    def test_bounded_day_and_five_minute_report_is_accepted(self):
        src = fixture()
        base = src["results"]["5min/2026"]
        src["requested_years"] = [2026]
        src["requested_periods"] = ["day", "5min"]
        src["results"]["day/2026"] = {
            "period": "day", "year": 2026,
            "scan_complete": True, "issues": [],
            "safe_to_automatically_union": False,
            "from_date": base["from_date"], "to_date": base["to_date"],
            "universe_mode": base.get("universe_mode"),
        }
        result = M.analyze(src)
        self.assertTrue(result["separate_day_section_consistency_checked"])
        self.assertEqual(result["candidate_any_field_mismatch"], 6)
        self.assertFalse(result["exact_mask_evidence_present"])

    def test_exact_disjoint_field_masks_reconcile_all_marginals(self):
        src = fixture()
        cand = src["results"]["5min/2026"][
            "quantity_scale_diagnostics"]["h5_volume_times_100_candidate"]
        names = M.MASK_NAMES
        def group(**kwargs):
            return {key: kwargs.get(key, 0) for key in names}
        sh = group(none=2, volume=1, volume_amount=1,
                   volume_amount_price=2)
        bj = group(none=2, volume=1, amount_price=1)
        global_mask = {k: sh[k] + bj[k] for k in names}
        cand["exact_residual_field_mask_counts"] = global_mask
        cand["exact_field_mask_by_prefix"] = {
            "SH_other_prefix": sh, "BJ_prefix": bj}
        cand["exact_field_mask_by_day"] = {
            "20260928": sh, "20260929": bj}
        cand["exact_masks_are_mutually_exclusive"] = True
        result = M.analyze(src)
        self.assertTrue(result["exact_mask_evidence_present"])
        self.assertEqual(result["verified_exact_disjoint_field_masks"][
            "global_disjoint_field_mask_counts"], global_mask)
        self.assertTrue(result["verified_exact_disjoint_field_masks"][
            "all_field_overlap_counts_are_exact_not_estimated"])
        self.assertFalse(result["underlying_ohlcv_read"])
        self.assertFalse(result["safe_to_automatically_union"])

        tamper = copy.deepcopy(src)
        tamper["results"]["5min/2026"]["quantity_scale_diagnostics"][
            "h5_volume_times_100_candidate"][
            "exact_field_mask_by_day"]["20260928"]["volume"] += 1
        with self.assertRaisesRegex(ValueError, "conserve|marginal"):
            M.analyze(tamper)

    def test_partial_masks_or_wrong_day_companion_fail_closed(self):
        src = fixture()
        cand = src["results"]["5min/2026"][
            "quantity_scale_diagnostics"]["h5_volume_times_100_candidate"]
        cand["exact_residual_field_mask_counts"] = {"none": 10}
        with self.assertRaisesRegex(ValueError, "Partial exact residual"):
            M.analyze(src)

        src = fixture()
        five = src["results"]["5min/2026"]
        src["results"]["day/2026"] = {
            "period": "day", "year": 2026,
            "scan_complete": True, "issues": [],
            "safe_to_automatically_union": False,
            "from_date": five["from_date"], "to_date": "2026-09-30",
            "universe_mode": five.get("universe_mode")
        }
        with self.assertRaisesRegex(ValueError, "Companion day"):
            M.analyze(src)



if __name__ == "__main__":
    unittest.main()
