"""Pure JSON synthetic tests for 5min exact/focused/H5 1min report provenance."""
import copy
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location(
    "offline_five_minute_source_chain",
    HERE / "audit-5min-source-evidence-chain-offline.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SYMBOL = "SH688629"
DATE = "2026-09-28"


def minute_bucket(count, missing, *, agree):
    return {
        "complete_windows": count,
        "incomplete_windows": missing,
        "all_ohlc_agree": count if agree else 0,
        "price_field_agree": {k: count if agree else 0
                              for k in M.PRICE_FIELDS},
        "amount_agree": count if agree else 0,
        "volume_both_zero_windows": 0,
        "nonzero_volume_windows": count,
        "volume_match_minute_multiplier":
            {"1": 0, "100": count if agree else 0},
        "volume_match_nonzero_minute_multiplier":
            {"1": 0, "100": count if agree else 0},
    }


def minute_result(*, end):
    n = 24 if end else 23
    morning = minute_bucket(n, 24-n, agree=end)
    afternoon = copy.deepcopy(morning)
    all_day = minute_bucket(2*n, 48-2*n, agree=end)
    return {"five_minute_bars": 48, "whole_day": all_day,
            "sessions": {"morning": morning, "afternoon": afternoon}}


def fixture():
    masks = {
        "none": 40, "volume": 1, "amount": 1, "price": 2,
        "volume_amount": 1, "volume_price": 1,
        "amount_price": 0, "volume_amount_price": 2,
    }
    sparse = {k: v for k, v in masks.items() if k != "none" and v}
    exact = {
        "format": "AStockDataTools H5-Parquet local coverage/difference report v1",
        "status": "complete", "eligible_for_automatic_union": False,
        "sources_modified": False, "requested_periods": ["5min"],
        "universe_mode": "a-share-candidate", "requested_years": [2026],
        "requested_from_date": DATE, "requested_to_date": DATE,
        "results": {
            "5min/2026": {
                "scan_complete": True, "issues": [],
                "safe_to_automatically_union": False,
                "source_units_certified": False,
                "matched_keys": 48, "price_mismatch_rows": 5,
                "quantity_scale_diagnostics": {
                    "fields": {"amount": {
                        "different_by_existing_tolerance": 4
                    }},
                    "h5_volume_times_100_candidate": {
                        "factor_certified": False,
                        "exact_masks_are_mutually_exclusive": True,
                        "exact_residual_field_mask_counts": masks,
                        "candidate_volume_mismatch": 5,
                        "candidate_value_mismatch_with_original_price_and_amount_rules": 8,
                        "exact_residual_top_stock_days": [{
                            "symbol": SYMBOL,
                            "day": "20260928",
                            "candidate_conflicting_bars": 8,
                            "field_mask_counts": sparse,
                        }],
                    },
                },
            },
        },
    }
    morning_mask = {
        "none":20, "volume":1, "amount":1, "price":1,
        "volume_amount":1, "volume_price":0, "amount_price":0,
        "volume_amount_price":0,
    }
    afternoon_mask = {
        "none":20, "volume":0, "amount":0, "price":1,
        "volume_amount":0, "volume_price":1, "amount_price":0,
        "volume_amount_price":2,
    }
    def session(m):
        return {
            "matched_bars": 24,
            "exact_residual_masks": m,
            "volume": {
                "matched_bars":24,
                "source_total_ratio_parquet_over_h5":1.0,
                "net_difference_pct_of_h5_total":0.0,
            },
            "amount": {"matched_bars":24},
        }
    focus = {
        "format":"AStockDataTools x100 focused 5min residual session forensic v1",
        "date":DATE, "source_files_modified":False,
        "no_raw_ohlcv_exported":True, "unit_mapping_certified":False,
        "safe_to_automatically_union":False,
        "h5_five_minute_volume_factor_candidate":100,
        "selected_symbols":[SYMBOL],
        "symbol_results":{
            SYMBOL:{
                "status":"hypothesis_diagnostic_only",
                "candidate_volume_factor_h5":100,
                "h5_5min_bars":48, "parquet_5min_bars":48,
                "h5_only_bars":0, "parquet_only_bars":0,
                "exact_residual_masks": masks,
                "conservation_on_matched_keys_only":{
                    "volume":{
                        "source_total_ratio_parquet_over_h5":1.0,
                        "net_difference_pct_of_h5_total":0.0,
                    },
                },
                "sessions":{
                    "morning":session(morning_mask),
                    "afternoon":session(afternoon_mask),
                },
            },
        },
    }
    minute = {
        "format":"AStockDataTools H5 one-minute top3 no-Parquet check v1",
        "date":DATE, "h5_source_values_modified":False,
        "original_report_modified":False, "raw_ohlcv_exported":False,
        "parquet_source_read":False,
        "safe_to_automatically_union":False,
        "minute_unit_certified":False,
        "source_timestamp_mapping_certified":False,
        "h5_five_minute_volume_times_100_candidate":True,
        "one_minute_volume_factor_candidate_values":[1,100],
        "minute_start_vs_end_label_hypotheses":[
            "minute_end_label","minute_start_label"],
        "selected_symbols":[SYMBOL],
        "symbol_results":{
            SYMBOL:{
                "availability":"candidate_windows_available",
                "one_minute_source":{
                    "one_minute_rows":240, "file_present":True,
                    "dataset_present":True,"duplicate_minute_keys":0,
                },
                "minute_convention_candidates":{
                    "minute_end_label":minute_result(end=True),
                    "minute_start_label":minute_result(end=False),
                },
            },
        },
    }
    return exact, focus, minute


class OfflineSourceChainTests(unittest.TestCase):
    def test_full_chain_conditional_agreement_and_zero_market_read(self):
        args = fixture()
        result = M.audit_chain(*args)
        summary=result["selected_three_stock_days"]
        self.assertEqual(summary["five_minute_bars"],48)
        self.assertEqual(summary["five_minute_candidate_conflicts"],8)
        self.assertEqual(summary["three_field_conflict_bars"],2)
        self.assertEqual(summary["h5_end_label_complete_windows"],48)
        self.assertEqual(summary["h5_end_label_ohlc_agreements"],48)
        self.assertEqual(summary["h5_end_label_nonzero_volume_x100_agreements"],48)
        self.assertEqual(summary["h5_start_label_complete_windows"],46)
        self.assertEqual(summary["h5_start_label_ohlc_agreements"],0)
        self.assertTrue(summary[
            "all_selected_h5_end_label_reaggregations_reproduced"])
        self.assertTrue(result["symbol_evidence"][0][
            "parquet_vs_h5_5min_volume_net_zero_at_report_precision"])
        self.assertFalse(result["interpretation"][
            "h5_1min_is_independent_vendor_ground_truth"])
        self.assertFalse(result["source_market_files_read"])
        self.assertFalse(result["safe_to_automatically_union"])

    def test_input_date_and_source_safety_fail_closed(self):
        exact,focus,minute=fixture()
        exact["requested_from_date"]="2026-09-29"
        with self.assertRaisesRegex(ValueError, "must cover one day"):
            M.audit_chain(exact,focus,minute)
        exact,focus,minute=fixture()
        minute["parquet_source_read"]=True
        with self.assertRaisesRegex(ValueError, "flags"):
            M.audit_chain(exact,focus,minute)
        exact,focus,minute=fixture()
        focus["safe_to_automatically_union"]=True
        with self.assertRaisesRegex(ValueError, "flags"):
            M.audit_chain(exact,focus,minute)

    def test_tampered_global_marginal_is_rejected(self):
        exact,focus,minute=fixture()
        exact["results"]["5min/2026"]["quantity_scale_diagnostics"][
            "h5_volume_times_100_candidate"]["candidate_volume_mismatch"] = 6
        with self.assertRaisesRegex(ValueError, "volume marginal"):
            M.audit_chain(exact,focus,minute)

    def test_focus_must_agree_with_top_exact_baseline(self):
        exact,focus,minute=fixture()
        focus["symbol_results"][SYMBOL]["exact_residual_masks"]["volume"]+=1
        with self.assertRaisesRegex(ValueError, "focus/exact masks"):
            M.audit_chain(exact,focus,minute)

    def test_session_masks_must_sum_back_to_same_stock_day(self):
        exact,focus,minute=fixture()
        focus["symbol_results"][SYMBOL]["sessions"]["morning"][
            "exact_residual_masks"]["volume"] = 0
        with self.assertRaisesRegex(ValueError, "session mask"):
            M.audit_chain(exact,focus,minute)

    def test_minute_incomplete_evidence_never_certifies_units(self):
        exact,focus,minute=fixture()
        record=minute["symbol_results"][SYMBOL]
        record["one_minute_source"]["one_minute_rows"]=0
        record["availability"]="not_verifiable_no_one_minute_data"
        record["minute_convention_candidates"]={}
        result=M.audit_chain(exact,focus,minute)
        self.assertFalse(result["selected_three_stock_days"][
            "all_selected_h5_end_label_reaggregations_reproduced"])
        self.assertEqual(result["symbol_evidence"][0]["evidence_level"],
                         "insufficient_h5_one_minute_evidence")
        self.assertFalse(result["interpretation"]["volume_unit_certified"])

    def test_minute_bucket_totals_do_not_silently_inflate_matches(self):
        exact,focus,minute=fixture()
        minute["symbol_results"][SYMBOL][
            "minute_convention_candidates"]["minute_end_label"]["sessions"][
            "afternoon"]["amount_agree"] = 23
        with self.assertRaisesRegex(ValueError, "session conservation"):
            M.audit_chain(exact,focus,minute)
        exact,focus,minute=fixture()
        minute["symbol_results"][SYMBOL][
            "minute_convention_candidates"]["minute_end_label"]["whole_day"][
            "volume_match_nonzero_minute_multiplier"]["100"] = 49
        with self.assertRaisesRegex(ValueError, "exceeds denominator"):
            M.audit_chain(exact,focus,minute)

    def test_rounded_volume_conservation_not_claimed_when_not_reported(self):
        exact,focus,minute=fixture()
        focus["symbol_results"][SYMBOL]["sessions"]["morning"]["volume"][
            "net_difference_pct_of_h5_total"]=0.01
        r=M.audit_chain(exact,focus,minute)
        self.assertFalse(r["symbol_evidence"][0][
            "parquet_vs_h5_5min_volume_net_zero_at_report_precision"])
        self.assertTrue(r["symbol_evidence"][0][
            "h5_end_labeled_ohlcv_amount_48_of_48_reaggregates"])


if __name__ == "__main__":
    unittest.main()
