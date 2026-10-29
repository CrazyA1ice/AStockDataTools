"""All offline synthetic JSON summaries. Do not open Parquet, TDX or H5."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "offline_real_precision_crosssource_gate",
    HERE.parent/"tools"/"audit-real-precision-crosssource-evidence-offline.py")
A=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def precision():
    columns={}
    for f in A.FIELDS:
        columns[f]={
            "sampled_values":2,
            "shortest_decimal_tick_exact_count":2,
            "binary_float_tick_exact_count":0 if f in
                ("open","high","low","close") else 2,
            "would_require_rounding_count":0,
            "half_tick_boundary_count":0,
            "range_overflow_count":0,
        }
    return {
        "format":A.PRECISION_FORMAT,"sample_trading_day":"2026-09-30",
        "sample_security_count":2,
        "scanned_source_rows_bounded":118208,
        "no_native_h5_integer_records_encoded_or_written":True,
        "source_parquet_read_only":True,
        "raw_ohlcva_or_timestamp_values_in_safe":False,
        "licensed_parquet_physical_units_certified":False,
        "real_float64_to_h5_precision_mapping_certified":False,
        "ready_for_full_market_mirror":False,
        "field_hypotheses":columns,
    }


def tdx():
    def group(n):
        record={}
        for f in A.FIELDS:
            item={
                "n":n,"within_diagnostic_tolerance":n,
                "max_relative_error":1e-7,
            }
            if f in ("volume","amount"):
                item["ratio_actual_over_reference_median"]=1.0
            record[f]=item
        return record
    return {
        "format":A.TDX_FORMAT,"date":"2026-09-30",
        "symbol":"SH600000",
        "tdx_internal_three_period_all_fields_within_tolerance":True,
        "only_tdx_and_purchased_parquet_read":True,
        "h5_accessed":False,
        "cross_vendor_volume_and_amount_unit_convention_unverified":True,
        "source_market_files_modified":False,
        "eligible_for_automatic_production_union":False,
        "five_minute_alignment":
            "TDX ending label == Parquet starting label + 5 minutes",
        "tdx_source_counts":{"day":1,"1min":240,"5min":48},
        "parquet_source_counts":{"day":1,"5min":48},
        "comparisons":{
            "tdx_5min_vs_parquet_5min_by_interval":group(48),
            "tdx_daily_vs_parquet_daily":group(1),
        },
    }


def h5():
    result={}
    for symbol,none in (("SH688629",15),("SH688017",16),
                        ("SH688172",18)):
        masks={k:0 for k in A.MASKS}
        masks["none"]=none
        masks["volume_amount_price"]=48-none
        result[symbol]={
            "h5_5min_bars":48,"parquet_5min_bars":48,
            "h5_only_bars":0,"parquet_only_bars":0,
            "exact_residual_masks":masks,
        }
    return {
        "format":A.H5_FORMAT,"date":"2026-09-28",
        "h5_five_minute_volume_factor_candidate":100,
        "unit_mapping_certified":False,
        "safe_to_automatically_union":False,
        "no_raw_ohlcv_exported":True,
        "source_files_modified":False,
        "symbol_results":result,
    }


class OfflineEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.reports=Path(self.temp.name)/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        self.precision=self.reports/"precision.json"
        self.tdx=self.reports/"tdx.json"
        self.h5=self.reports/"h5.json"
        self.out=self.reports/"decision-v1.json"
        self.precision.write_text(json.dumps(precision()),encoding="utf-8")
        self.tdx.write_text(json.dumps(tdx()),encoding="utf-8")
        self.h5.write_text(json.dumps(h5()),encoding="utf-8")
        p=patch.object(A,"REPORTS",self.reports)
        p.start();self.addCleanup(p.stop)

    def run_it(self):
        return A.run(self.precision,self.tdx,self.h5,self.out)

    def test_joins_three_existing_safe_reports_without_market_files(self):
        result=self.run_it()
        self.assertEqual(result["precision"]["two_real_stock_days_sampled"],2)
        self.assertEqual(result["precision"]["price_shortest_decimal_tick_fit"],
                         {"open":2,"high":2,"low":2,"close":2})
        self.assertEqual(result["precision"]["price_binary_float_tick_exact"],
                         {"open":0,"high":0,"low":0,"close":0})
        self.assertEqual(result["tdx_vs_purchased_parquet"]
                         ["five_minute_all_six_fields_within_report_tolerance"],48)
        self.assertFalse(result["tdx_vs_purchased_parquet"]["tdx_is_hikyuu_h5"])
        self.assertEqual(result["hikyuu_h5_vs_purchased_parquet"]
                         ["five_minute_bars_compared"],144)
        self.assertEqual(result["hikyuu_h5_vs_purchased_parquet"]
                         ["any_field_candidate_conflict_bars"],95)
        for key in ("physical_amount_unit_certified",
                    "physical_volume_unit_certified",
                    "real_float64_to_native_h5_precision_mapping_certified",
                    "h5_parquet_universal_volume_factor_100_certified",
                    "licensed_parquet_to_h5_mapping_certified",
                    "ready_for_full_market_mirror"):
            self.assertFalse(result[key])
        self.assertEqual(len(result["input_report_sha256"]),3)
        output=self.out.read_text(encoding="utf-8")
        for secret in ("C:\\Users","2026-09.parquet","10.125",
                       "private_absolute_source_path","source_row_group"):
            self.assertNotIn(secret,output)

    def test_no_input_modified_only_new_safe_file_created(self):
        before=[p.read_bytes() for p in
                (self.precision,self.tdx,self.h5)]
        self.run_it()
        self.assertEqual(before,[p.read_bytes() for p in
                         (self.precision,self.tdx,self.h5)])
        self.assertEqual(len(list(self.reports.glob("*.json"))),4)

    def test_second_run_cannot_overwrite(self):
        self.run_it()
        original=self.out.read_bytes()
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            self.run_it()
        self.assertEqual(self.out.read_bytes(),original)

    def test_precision_counts_are_consistent_or_rejected(self):
        doc=precision()
        doc["field_hypotheses"]["open"][
            "shortest_decimal_tick_exact_count"]=1
        with self.assertRaisesRegex(ValueError,"Inconsistent"):
            A.build(doc,tdx(),h5())
        doc=precision()
        doc["field_hypotheses"]["amount"]["raw_amount"]=123
        with self.assertRaisesRegex(ValueError,"Unexpected precision"):
            A.build(doc,tdx(),h5())
        doc=precision()
        doc["field_hypotheses"]["volume"][
            "binary_float_tick_exact_count"]=3
        with self.assertRaises(ValueError):
            A.build(doc,tdx(),h5())

    def test_unsafe_precision_claims_and_wrong_day_rejected(self):
        doc=precision()
        doc["licensed_parquet_physical_units_certified"]=True
        with self.assertRaisesRegex(ValueError,"Precision SAFE"):
            A.build(doc,tdx(),h5())
        doc=precision()
        doc["sample_trading_day"]="2026-09-28"
        with self.assertRaisesRegex(ValueError,"Precision SAFE"):
            A.build(doc,tdx(),h5())

    def test_wrong_tdx_source_or_date_fails_closed(self):
        doc=tdx();doc["h5_accessed"]=True
        with self.assertRaisesRegex(ValueError,"TDX cross-source"):
            A.build(precision(),doc,h5())
        doc=tdx();doc["date"]="2026-09-28"
        with self.assertRaisesRegex(ValueError,"TDX cross-source"):
            A.build(precision(),doc,h5())
        doc=tdx();doc["comparisons"]["tdx_daily_vs_parquet_daily"][
            "volume"]["within_diagnostic_tolerance"]=0
        with self.assertRaisesRegex(ValueError,"TDX field"):
            A.build(precision(),doc,h5())

    def test_h5_residual_masks_cannot_be_hid_by_aggregate_total(self):
        doc=h5()
        symbol="SH688629"
        doc["symbol_results"][symbol]["exact_residual_masks"][
            "volume_amount_price"]=0
        with self.assertRaisesRegex(ValueError,"do not sum"):
            A.build(precision(),tdx(),doc)
        doc=h5()
        doc["unit_mapping_certified"]=True
        with self.assertRaisesRegex(ValueError,"H5 residual SAFE"):
            A.build(precision(),tdx(),doc)

    def test_report_path_restrictions_and_duplicate_sources(self):
        outsider=Path(self.temp.name)/"outside.json"
        outsider.write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"direct report"):
            A.run(outsider,self.tdx,self.h5,self.out)
        with self.assertRaisesRegex(ValueError,"Four distinct"):
            A.run(self.precision,self.precision,self.h5,self.out)
        with self.assertRaisesRegex(ValueError,"direct report"):
            A.run(self.precision,self.tdx,self.h5,outsider)

    def test_corrupted_json_and_raw_data_fields_rejected(self):
        self.precision.write_text("{invalid",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Malformed"):
            self.run_it()
        self.assertFalse(self.out.exists())
        self.precision.write_text(json.dumps(precision()),encoding="utf-8")
        doc=precision()
        doc["field_hypotheses"]["volume"]["price"]=120.0
        self.precision.write_text(json.dumps(doc),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Unexpected precision"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_crossdate_compared_sources_remain_distinct_and_uncertified(self):
        out=A.build(precision(),tdx(),h5())
        self.assertEqual(out["tdx_vs_purchased_parquet"]["trading_day"],
                         "2026-09-30")
        self.assertEqual(out["hikyuu_h5_vs_purchased_parquet"]["trading_day"],
                         "2026-09-28")
        self.assertTrue(out[
            "crosssource_daily_precision_and_h5_residual_are_different_stock_dates"])
        self.assertFalse(out[
            "h5_parquet_universal_volume_factor_100_certified"])
        self.assertIn("independent_hikyuu_h5_decoded_unit_baseline",
                      out["required_before_real_h5_encoding"])


if __name__=="__main__":
    unittest.main(verbosity=2)
