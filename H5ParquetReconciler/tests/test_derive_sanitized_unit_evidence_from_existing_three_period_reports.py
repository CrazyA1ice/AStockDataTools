"""Pure offline tests: reuse existing conservation reports, never source markets."""
import importlib.util
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "three_period_existing_report_adapter",
    HERE.parent/"tools"/"derive-sanitized-unit-evidence-from-existing-three-period-reports.py")
D=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)


def existing(date,missing=False):
    def pair(v):
        return {
            "comparable":True,"strict_ohlc_agree":True,
            "relative_ratio_day_over_intraday":{
                "amount":v,"volume":Decimal("1.0")}}
    stocks={}
    for symbol in D.SYMBOLS:
        stocks[symbol]={
            "day_bar_present":True,
            "day_quality":{"day_bar_found":True,"quality_issues":[]},
            "parquet_1min_rows":241,"parquet_5min_rows":48,
            "one_minute_missing_expected_stamps":0,
            "one_minute_outside_expected_grid":0,
            "five_minute_missing_expected_stamps":0,
            "five_minute_outside_expected_grid":0,
            "one_to_five_opening_rule_strict_48_of_48":True,
            "day_vs_5min":pair(Decimal("1.000000049")),
            "day_vs_1min":pair(Decimal("0.999999975")),
        }
    if missing:
        stocks["SH600000"]["five_minute_missing_expected_stamps"]=1
    return {
        "format":D.SOURCE_FORMAT,
        "date":date,
        "selected_symbols":["SH600000","SZ000001","SZ300750"],
        "expected_regular_1min_count_with_opening_0930":241,
        "expected_regular_5min_count":48,
        "read_cost_by_period":{
            p:{"parquet_schema_checked":True,"duplicate_keys":0,
               "nonfinite_source_rows":0,"invalid_timestamp_rows":0}
            for p in D.PERIODS
        },
        "stock_day_results":stocks,
    }


def safe_json(obj):
    return json.dumps(obj,ensure_ascii=False,default=float)


class PriorReportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.reports=Path(self.temp.name)/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        self.first=self.reports/"pq-day-vs-minute-2026-08-24.json"
        self.second=self.reports/"pq-day-vs-minute-2026-09-30.json"
        self.output=self.reports/"sanitized-from-existing.json"
        self.assessment=self.reports/"assessment-from-existing.json"
        self.first.write_text(safe_json(existing("2026-08-24")),encoding="utf-8")
        self.second.write_text(safe_json(existing("2026-09-30")),encoding="utf-8")
        p=patch.object(D.AUDIT,"REPORTS",self.reports)
        p.start()
        self.addCleanup(p.stop)

    def test_existing_two_stock_two_date_reports_are_reused_not_market_read(self):
        assessment=D.derive(self.first,self.second,self.output,self.assessment)
        self.assertEqual(assessment["observed_window_count"],4)
        self.assertEqual(assessment["unique_date_count"],2)
        self.assertEqual(assessment["unique_stock_count"],2)
        self.assertEqual(assessment["low_cross_period_gap_window_count"],4)
        self.assertEqual(assessment["fully_aligned_window_count"],0)
        self.assertFalse(assessment["ready_to_plan_independent_unit_check"])
        self.assertFalse(assessment["licensed_parquet_to_h5_mapping_certified"])
        doc=json.loads(self.output.read_text(encoding="utf-8"))
        self.assertTrue(doc["sanitized_aggregates_only"])
        self.assertEqual(len(doc["windows"]),4)
        self.assertEqual({x["date"] for x in doc["windows"]},
                         {"2026-08-24","2026-09-30"})
        self.assertEqual({x["symbol"] for x in doc["windows"]},set(D.SYMBOLS))
        for w in doc["windows"]:
            self.assertEqual(w["day_rows"],1)
            self.assertEqual(w["min5_rows"],48)
            self.assertEqual(w["min1_rows"],241)
            self.assertTrue(w["time_grid_checked"])
            self.assertFalse(w["same_adjustment_basis"])
            self.assertFalse(w["closed_session"])
            self.assertEqual(w["day_vs_1min_amount_relative_gap"],"0.000000025")
            self.assertEqual(w["day_vs_5min_amount_relative_gap"],"0.000000049")
        for p in D.PERIODS:
            self.assertEqual(doc["schemas"][p]["amount_type"],"unknown")
            self.assertEqual(doc["schemas"][p]["timezone"],"unknown")
            self.assertEqual(doc["schemas"][p]["volume_unit_declared"],"unknown")
        out=self.assessment.read_text(encoding="utf-8")
        for token in ("source_files_examined","relative_ratio_day_over_intraday",
                      "SH600000","2026-09-30"):
            self.assertNotIn(token,out)

    def test_unknown_schema_and_adjustment_stay_unknown_even_when_all_gaps_small(self):
        doc1=existing("2026-08-24")
        doc2=existing("2026-09-30")
        sanitized,assessment=D.convert([doc1,doc2])
        self.assertTrue(all(w["time_grid_checked"] for w in sanitized["windows"]))
        self.assertEqual(assessment["low_cross_period_gap_window_count"],4)
        self.assertIn("closed_session_time_grid_or_adjustment_unproven",
                      assessment["evidence_blockers"])
        self.assertIn("missing_parquet_schema_type_or_timezone",
                      assessment["evidence_blockers"])
        self.assertNotIn("cross_period_aggregate_gap_not_small",
                         assessment["evidence_blockers"])

    def test_no_implicit_24_hour_session_completeness_inference(self):
        doc=existing("2026-08-24",missing=True)
        reduced=D._window("SH600000","2026-08-24",
                          doc["stock_day_results"]["SH600000"],
                          doc["read_cost_by_period"],doc)
        self.assertFalse(reduced["time_grid_checked"])
        self.assertFalse(reduced["closed_session"])

    def test_invalid_or_missing_ratio_fails_closed(self):
        for value in ("NaN",None,True,-1,Decimal("Infinity"),Decimal("3")):
            with self.subTest(v=value):
                with self.assertRaises(ValueError):
                    D._small_decimal(value)
        doc=existing("2026-08-24")
        del doc["stock_day_results"]["SH600000"]["day_vs_5min"][
            "relative_ratio_day_over_intraday"]["amount"]
        with self.assertRaisesRegex(ValueError,"Missing existing amount"):
            D.convert([doc,existing("2026-09-30")])

    def test_old_report_not_rewritten_and_new_destinations_required(self):
        first_before=self.first.read_bytes()
        second_before=self.second.read_bytes()
        D.derive(self.first,self.second,self.output,self.assessment)
        self.assertEqual(self.first.read_bytes(),first_before)
        self.assertEqual(self.second.read_bytes(),second_before)
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            D.derive(self.first,self.second,self.output,self.assessment)

    def test_reject_duplicate_date_wrong_format_or_missing_symbol(self):
        a=existing("2026-08-24")
        with self.assertRaisesRegex(ValueError,"distinct"):
            D.convert([a,existing("2026-08-24")])
        bad=existing("2026-09-30")
        bad["format"]="unsupported"
        with self.assertRaisesRegex(ValueError,"known"):
            D.convert([a,bad])
        bad=existing("2026-09-30")
        del bad["stock_day_results"]["SH600000"]
        with self.assertRaisesRegex(ValueError,"Missing existing stock"):
            D.convert([a,bad])
        with self.assertRaisesRegex(ValueError,"Exactly two"):
            D.convert([a])

    def test_external_source_file_not_allowed(self):
        outsider=Path(self.temp.name)/"private.parquet"
        outsider.write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"direct non-symlink"):
            D.derive(outsider,self.second,self.output,self.assessment)
        self.assertFalse(self.output.exists())

    def test_reject_unsupported_bar_count_or_missing_daily_data(self):
        doc=existing("2026-08-24")
        doc["stock_day_results"]["SH600000"]["parquet_1min_rows"]=False
        with self.assertRaisesRegex(ValueError,"bar count"):
            D.convert([doc,existing("2026-09-30")])
        doc=existing("2026-08-24")
        doc["stock_day_results"]["SH600000"]["day_bar_present"]=False
        with self.assertRaisesRegex(ValueError,"counts"):
            D.convert([doc,existing("2026-09-30")])


if __name__=="__main__":
    unittest.main(verbosity=2)
