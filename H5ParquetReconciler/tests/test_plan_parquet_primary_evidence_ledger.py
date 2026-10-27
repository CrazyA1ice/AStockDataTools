"""Synthetic tests for non-ingesting Parquet primary evidence ledger."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "tools"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEDGER = load("parquet_sampled_evidence_ledger",
              "plan-parquet-primary-evidence-ledger.py")

FIELDS = ("open", "high", "low", "close", "volume", "amount")


def raw_report(day="2026-09-30", symbol="SH600000", amount=.999999995):
    def comparison():
        strict_fields={x: True for x in FIELDS}
        strict_fields["amount"]=False
        return {
            "comparable":True,
            "strict_ohlc_agree":True,
            "strict_all_six_raw_agree":False,
            "existing_tolerance_all_six_raw_agree":True,
            "strict_field_agree":strict_fields,
            "existing_tolerance_field_agree":{x:True for x in FIELDS},
            "relative_ratio_day_over_intraday":{
                "volume":1.0,"amount":amount},
            "volume_factor_tolerance_match":{"1":True},
            "amount_factor_tolerance_match":{"1":True},
        }
    return {
        "format":LEDGER.RAW,
        "date":day,
        "selected_symbols":[symbol],
        "stock_day_results":{
            symbol:{
                "day_bar_present":True,
                "day_quality":{"day_bar_found":True, "quality_issues":[]},
                "parquet_1min_rows":241, "parquet_5min_rows":48,
                "one_minute_missing_expected_stamps":0,
                "one_minute_outside_expected_grid":0,
                "five_minute_missing_expected_stamps":0,
                "five_minute_outside_expected_grid":0,
                "one_to_five_opening_rule_strict_48_of_48":True,
                "raw_all_three_periods_strict_agree":False,
                "day_vs_1min":comparison(),
                "day_vs_5min":comparison(),
            }
        },
        "read_cost_by_period":{
            p:{"duplicate_keys":0,"nonfinite_source_rows":0,
               "invalid_timestamp_rows":0}
            for p in ("day","1min","5min")
        },
        "source_daily_adjustment_or_quantity_units_certified":False,
        "raw_market_ohlcva_exported":False,
        "h5_source_accessed":False,
        "source_market_files_modified":False,
        "safe_to_automatically_union":False,
    }


def offline_report():
    from_raw=raw_report("2026-08-24", "SZ300750", .999999982)
    for per in ("day_vs_1min","day_vs_5min"):
        c=from_raw["stock_day_results"]["SZ300750"][per]
        c["strict_field_agree"]["volume"]=False
        c["relative_ratio_day_over_intraday"]["volume"]=.999992843
    review=LEDGER.OFFLINE.summarize(from_raw)
    review["source_report_filename"]="pq-day-vs-minute-2026-08-24.json"
    return review


class ParquetEvidenceLedgerTests(unittest.TestCase):
    def test_raw_and_offline_can_stage_two_realistic_dates(self):
        result=LEDGER.plan_reports([
            ("aug-assessment.json",offline_report()),
            ("sep-raw.json",raw_report())])
        self.assertEqual(result["sampled_date_count"],2)
        self.assertEqual(result["sampled_stock_day_count"],2)
        self.assertEqual(result["summary_by_status"],{
            "candidate_parquet_primary_in_this_sample_only":2})
        first=result["selected_sampled_stock_days"][0]
        self.assertEqual(first["date"],"2026-08-24")
        self.assertEqual(first["symbol"],"SZ300750")
        self.assertEqual(first["max_reported_relative_quantity_gap_ppm"],7.157)
        self.assertEqual(first["underlying_raw_report_filename_if_known"],
                         "pq-day-vs-minute-2026-08-24.json")
        self.assertFalse(first["eligible_for_unattended_import"])
        self.assertFalse(result["eligible_for_automatic_source_merge"])
        self.assertFalse(result["data_import_performed"])

    def test_strict_raw_day_can_be_sampled_without_global_approval(self):
        raw=raw_report()
        entry=raw["stock_day_results"]["SH600000"]
        for per in ("day_vs_1min","day_vs_5min"):
            e=entry[per]
            e["strict_field_agree"]["amount"]=True
            e["strict_all_six_raw_agree"]=True
        entry["raw_all_three_periods_strict_agree"]=True
        ledger=LEDGER.plan_reports([("day.json",raw)])
        row=ledger["selected_sampled_stock_days"][0]
        self.assertEqual(row["sample_level_review"],
            "all_three_raw_strict_consistent_in_this_sample")
        self.assertFalse(row["verified_full_history_coverage"])
        self.assertFalse(row["eligible_for_unattended_import"])

    def test_duplicate_stock_day_across_reports_fails_closed(self):
        raw=raw_report()
        other=offline_report()
        other["source_report_date"]="2026-09-30"
        other["selected_symbols"]=["SH600000"]
        other["stock_day_reviews"]={
            "SH600000":next(iter(other["stock_day_reviews"].values()))}
        with self.assertRaisesRegex(ValueError,"Duplicate sampled stock-day"):
            LEDGER.plan_reports([("raw.json",raw),("offline.json",other)])

    def test_tighter_ppm_only_demotes_old_offline_evidence(self):
        row=LEDGER.plan_reports([
            ("offline.json",offline_report())],review_ppm=5)[
                "selected_sampled_stock_days"][0]
        self.assertEqual(row["status"],
            "not_a_qualified_sample_investigate")
        self.assertEqual(row["sample_level_review"],
            "quantity_or_price_difference_requires_investigation")

    def test_corrupt_offline_safety_attestation_rejected(self):
        doc=offline_report()
        doc["safe_to_automatically_union"]=True
        with self.assertRaisesRegex(ValueError,"safety flags"):
            LEDGER.plan_reports([("offline.json",doc)])

    def test_offline_summary_mismatch_rejected(self):
        doc=offline_report()
        doc["summary_by_grade"]={"made_up":1}
        with self.assertRaisesRegex(ValueError,"summary contradicts"):
            LEDGER.plan_reports([("offline.json",doc)])

    def test_raw_source_anomaly_rejected(self):
        doc=raw_report()
        doc["read_cost_by_period"]["day"]["duplicate_keys"]=1
        with self.assertRaisesRegex(ValueError,"Source anomalies"):
            LEDGER.plan_reports([("raw.json",doc)])

    def test_incomplete_stock_is_a_nonqualified_sample(self):
        doc=raw_report()
        doc["stock_day_results"]["SH600000"][
            "one_minute_missing_expected_stamps"]=1
        row=LEDGER.plan_reports([("raw.json",doc)])[
            "selected_sampled_stock_days"][0]
        self.assertEqual(row["status"],"not_a_qualified_sample_investigate")

    def test_no_raw_ohlcva_in_shareable_manifest(self):
        wire=json.dumps(LEDGER.plan_reports([
            ("raw.json",raw_report())]))
        self.assertNotIn('"open": 10',wire)
        self.assertNotIn('"volume": 10000',wire)
        self.assertIn('"raw_market_ohlcva_exported": false',wire)
        self.assertIn('"historical_raw_market_files_read": false',wire)


if __name__=="__main__":
    unittest.main()
