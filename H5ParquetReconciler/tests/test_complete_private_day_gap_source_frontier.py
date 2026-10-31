"""Synthetic-only source-observation frontier in private all-market day gap plans.

An audit with an end date after the last observed source trading day is NOT
evidence that the source provider had no later trading or updated market data.
"""
import importlib.util
import json
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BASE=load("private_day_gap_existing_fixture",
          HERE/"test_complete_private_parquet_primary_day_gap_set.py")
M=BASE.C


def report(begin="2026-09-01",end="2026-10-28",
           days=("20260930","20261008","20261009","20261012","20261013")):
    return {
        "audited_window":{"from_date":begin,"to_date":end},
        "daily_coverage":[{"date":day,"category":"parquet_primary_existing_overlap"}
                          for day in days],
    }


class SourceFrontierPureTests(unittest.TestCase):
    def test_realistic_oct_13_frontier_does_not_claim_oct_28_freshness(self):
        result=M.observed_source_frontier(report())
        self.assertEqual(result["last_source_stockday_observed_date"],"2026-10-13")
        self.assertEqual(result["audit_requested_end_date"],"2026-10-28")
        self.assertEqual(result["calendar_days_after_last_source_observation"],15)
        self.assertFalse(result["source_observations_reach_audit_window_end"])
        self.assertTrue(result["day_gap_staging_does_not_prove_later_market_freshness"])
        self.assertFalse(result["post_frontier_market_data_fabricated"])

    def test_exact_audit_end_has_observation_but_is_not_global_freshness_proof(self):
        result=M.observed_source_frontier(
            report(end="2026-10-13"))
        self.assertTrue(result["source_observations_reach_audit_window_end"])
        self.assertEqual(result["calendar_days_after_last_source_observation"],0)
        self.assertTrue(result["day_gap_staging_does_not_prove_later_market_freshness"])

    def test_calendar_days_not_claimed_as_trading_day_count(self):
        result=M.observed_source_frontier(
            report(end="2026-10-19",days=("20261013",)))
        self.assertEqual(result["calendar_days_after_last_source_observation"],6)
        self.assertNotIn("missing_trading_days",result)

    def test_duplicate_or_out_of_range_dates_refused(self):
        for days in (("20261008","20261008"),("20261101",),
                     ("20260831",)):
            with self.subTest(days=days):
                with self.assertRaisesRegex(ValueError,"Out-of-window or duplicate"):
                    M.observed_source_frontier(report(days=days))

    def test_invalid_source_calendar_key_refused(self):
        for days in (("20260230",),("2026-10-13",),("garbage!",),
                     ("2026101",)):
            with self.subTest(days=days):
                with self.assertRaisesRegex(ValueError,"Invalid observed"):
                    M.observed_source_frontier(report(days=days))

    def test_missing_or_bad_audit_window_refused(self):
        for data in ({"audited_window":{},"daily_coverage":[]},
                     report(begin="2026-10-31",end="2026-10-01"),
                     report(begin="2026-10-01",end="2026-10-1"),
                     report(end="2026-02-30")):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    M.observed_source_frontier(data)

    def test_empty_source_observation_never_claims_freshness(self):
        with self.assertRaises(ValueError):
            M.observed_source_frontier(report(days=()))


class ExistingFullDayPipelineIntegrationTests(unittest.TestCase):
    def test_real_synthetic_existing_plan_contains_source_frontier(self):
        with BASE.ready() as (root,module,gate,source,purchased,stage,safe):
            original=purchased.read_bytes()
            result=M.run(root,gate,source,safe,"plan")
            frontier=result["source_observation_frontier"]
            self.assertEqual(frontier["last_source_stockday_observed_date"],
                             "2026-10-08")
            self.assertFalse(frontier["post_frontier_market_data_fabricated"])
            self.assertTrue(frontier[
                "day_gap_staging_does_not_prove_later_market_freshness"])
            self.assertEqual(original,purchased.read_bytes())
            self.assertFalse(BASE.F.M.ACTIVE.exists())

    def test_tampered_gate_audited_window_refused_before_new_safe(self):
        with BASE.ready() as (root,module,gate,source,purchased,stage,safe):
            doc=json.loads(gate.read_text(encoding="utf-8"))
            doc["audited_window"]["to_date"]="2026-10-28"
            gate.write_text(json.dumps(doc),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"not SHA-linked"):
                M.run(root,gate,source,safe,"plan")
            self.assertFalse(safe.exists())
            self.assertFalse(BASE.F.M.ACTIVE.exists())

    def test_complete_private_preparation_does_not_change_source_frontier(self):
        with BASE.ready() as (root,module,gate,source,purchased,stage,safe):
            original=purchased.read_bytes()
            result=M.run(root,gate,source,safe,"complete",True)
            frontier=result["source_observation_frontier"]
            self.assertEqual(frontier["last_source_stockday_observed_date"],
                             "2026-10-08")
            self.assertEqual(result["audited_complete_h5_only_day_rows"],1)
            self.assertFalse(result["private_active_pointer_changed"])
            self.assertEqual(original,purchased.read_bytes())
            self.assertFalse(BASE.F.M.ACTIVE.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
