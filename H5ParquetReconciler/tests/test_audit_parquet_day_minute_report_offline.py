"""Synthetic only: existing Parquet day-minute JSON offline interpretation."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / (
    "audit-parquet-day-minute-report-offline.py")
SPEC = importlib.util.spec_from_file_location("parquet_day_report_offline", SCRIPT)
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)
FIELDS = ("open", "high", "low", "close", "volume", "amount")


def make_report():
    def comparison():
        strict = {field: True for field in FIELDS}
        strict["amount"] = False
        loose = {field: True for field in FIELDS}
        return {
            "comparable": True,
            "strict_ohlc_agree": True,
            "strict_all_six_raw_agree": False,
            "existing_tolerance_all_six_raw_agree": True,
            "strict_field_agree": strict,
            "existing_tolerance_field_agree": loose,
            "volume_factor_tolerance_match": {
                "1": True, "100": False, "0.01": False},
            "amount_factor_tolerance_match": {
                "1": True, "100": False, "0.01": False},
            "relative_ratio_day_over_intraday": {
                "volume": 1.0, "amount": .999999975},
        }
    item = {
        "day_bar_present": True,
        "day_quality": {"day_bar_found": True, "quality_issues": []},
        "parquet_1min_rows": 241,
        "parquet_5min_rows": 48,
        "one_minute_missing_expected_stamps": 0,
        "one_minute_outside_expected_grid": 0,
        "five_minute_missing_expected_stamps": 0,
        "five_minute_outside_expected_grid": 0,
        "one_to_five_opening_rule_strict_48_of_48": True,
        "day_vs_1min": comparison(),
        "day_vs_5min": comparison(),
        "raw_all_three_periods_strict_agree": False,
    }
    return {
        "format": A.EXPECTED_FORMAT,
        "date": "2026-08-24",
        "selected_symbols": ["SH600000"],
        "stock_day_results": {"SH600000": item},
        "read_cost_by_period": {period: {
            "duplicate_keys": 0, "nonfinite_source_rows": 0,
            "invalid_timestamp_rows": 0} for period in ("day", "1min", "5min")},
        "source_daily_adjustment_or_quantity_units_certified": False,
        "raw_market_ohlcva_exported": False,
        "h5_source_accessed": False,
        "source_market_files_modified": False,
        "safe_to_automatically_union": False,
    }


class ParquetDailyOfflineEvidenceTests(unittest.TestCase):
    def test_tiny_amount_gap_is_a_review_not_strict_pass(self):
        report = A.summarize(make_report())
        row = report["stock_day_reviews"]["SH600000"]
        self.assertEqual(row["assessment"],
            "strict_OHLC_and_minute_aggregation_small_daily_quantity_gap_review")
        self.assertFalse(row["raw_three_periods_strict_flag_from_original"])
        self.assertEqual(row["max_abs_relative_quantity_gap_ppm"], .025)
        self.assertEqual(row["daily_vs_minute_evidence"]["1min"][
            "strict_mismatch_fields"], ["amount"])
        self.assertEqual(row["daily_vs_minute_evidence"]["1min"][
            "existing_tolerance_mismatch_fields"], [])
        self.assertFalse(report["safe_to_automatically_union"])
        self.assertTrue(report["ppm_from_nine_decimal_rounded_ratios"])

    def test_7_157_ppm_volume_gap_can_be_reported_but_not_certified(self):
        sample = make_report()
        item = sample["stock_day_results"]["SH600000"]
        for period in ("day_vs_1min", "day_vs_5min"):
            src = item[period]
            src["strict_field_agree"]["volume"] = False
            src["relative_ratio_day_over_intraday"]["volume"] = .999992843
        r=A.summarize(sample)
        row=r["stock_day_reviews"]["SH600000"]
        self.assertEqual(row["max_abs_relative_quantity_gap_ppm"], 7.157)
        self.assertIn("volume", row["daily_vs_minute_evidence"]["5min"][
            "strict_mismatch_fields"])
        self.assertTrue(row["assessment"].endswith("_review"))
        self.assertEqual(A.summarize(sample, max_ppm=5)["stock_day_reviews"][
            "SH600000"]["assessment"],
            "quantity_or_price_difference_requires_investigation")

    def test_all_six_strict_matches_must_remain_true_in_source(self):
        sample=make_report()
        item=sample["stock_day_results"]["SH600000"]
        for period in ("day_vs_1min", "day_vs_5min"):
            item[period]["strict_field_agree"]["amount"]=True
            item[period]["strict_all_six_raw_agree"]=True
        item["raw_all_three_periods_strict_agree"]=True
        out=A.summarize(sample)
        self.assertEqual(out["stock_day_reviews"]["SH600000"]["assessment"],
            "all_three_raw_strict_consistent_in_this_sample")

    def test_missing_minute_refuses_tolerated_classification(self):
        sample=make_report()
        item=sample["stock_day_results"]["SH600000"]
        item["one_minute_missing_expected_stamps"]=1
        self.assertEqual(A.summarize(sample)["stock_day_reviews"][
            "SH600000"]["assessment"],
            "cannot_certify_incomplete_or_quality_issue")

    def test_reject_inconsistent_strict_and_price_flags(self):
        sample=make_report()
        sample["stock_day_results"]["SH600000"]["day_vs_5min"][
            "strict_all_six_raw_agree"]=True
        with self.assertRaisesRegex(ValueError, "Contradictory strict"):
            A.summarize(sample)
        sample=make_report()
        sample["stock_day_results"]["SH600000"][
            "raw_all_three_periods_strict_agree"]=True
        with self.assertRaisesRegex(ValueError, "contradicts inputs"):
            A.summarize(sample)

    def test_reject_invalid_ratio_and_source_anomaly(self):
        sample=make_report()
        sample["stock_day_results"]["SH600000"]["day_vs_1min"][
            "relative_ratio_day_over_intraday"]["volume"]=float("nan")
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            A.summarize(sample)
        sample=make_report()
        sample["read_cost_by_period"]["day"]["duplicate_keys"]=1
        with self.assertRaisesRegex(ValueError, "Source anomalies"):
            A.summarize(sample)

    def test_reject_source_marked_modified_or_auto_join_allowed(self):
        for key in ("h5_source_accessed", "source_market_files_modified",
                    "safe_to_automatically_union",
                    "source_daily_adjustment_or_quantity_units_certified"):
            sample=make_report()
            sample[key]=True
            with self.subTest(key=key), self.assertRaisesRegex(
                    ValueError, "safety attestation"):
                A.summarize(sample)

    def test_shareable_review_has_no_raw_ohlcva_and_new_file_only(self):
        result=A.summarize(make_report())
        wire=json.dumps(result)
        self.assertNotIn('"open": 10',wire)
        self.assertNotIn('"amount": 24000',wire)
        self.assertFalse(result["raw_market_ohlcva_exported"])
        self.assertTrue(result["derived_only_from_existing_json_not_from_market_files"])
        with tempfile.TemporaryDirectory() as work:
            source=Path(work)/"source.json"
            source.write_text(json.dumps(make_report()),encoding="utf-8")
            report=A.summarize(json.loads(source.read_text(encoding="utf-8")))
            self.assertEqual(report["source_report_date"],"2026-08-24")


if __name__=="__main__":
    unittest.main()
