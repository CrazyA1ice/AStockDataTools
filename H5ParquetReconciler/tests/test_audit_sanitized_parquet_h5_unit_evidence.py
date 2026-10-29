"""No real market IO: sanitized JSON schema/aggregate intake regression."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "sanitized_unit_evidence_test",
    HERE.parent/"tools"/"audit-sanitized-parquet-h5-unit-evidence.py")
A=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def fictional_evidence():
    schema={
        "date_type":"timestamp_ns",
        "price_type":"decimal128",
        "amount_type":"decimal128",
        "volume_type":"int64",
        "timezone":"Asia/Shanghai",
        "amount_unit_declared":"unknown",
        "volume_unit_declared":"unknown",
    }
    windows=[]
    for symbol in ("SH600000","SZ000001"):
        for d in ("2026-08-17","2026-09-30"):
            windows.append({
                "symbol":symbol,
                "date":d,
                "day_rows":1,
                "min5_rows":48,
                "min1_rows":239,
                "closed_session":True,
                "time_grid_checked":True,
                "same_adjustment_basis":True,
                "day_vs_5min_amount_relative_gap":"0.000001",
                "day_vs_1min_amount_relative_gap":"0.000002",
                "day_vs_5min_volume_relative_gap":"0",
                "day_vs_1min_volume_relative_gap":"0",
            })
    return {
        "format":A.FORMAT,
        "sanitized_aggregates_only":True,
        "no_raw_market_rows":True,
        "schemas":{p:dict(schema) for p in A.PERIODS},
        "windows":windows,
        "independent_unit_reference":"none",
    }


class UnitEvidenceInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)/"H5ParquetReconciler"
        root.mkdir()
        self.reports=root/"reports"
        self.reports.mkdir()
        self.input=self.reports/"manually_sanitized.json"
        self.output=self.reports/"safe_assessment.json"
        self.patch=patch.object(A,"REPORTS",self.reports)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self,doc):
        self.input.write_text(json.dumps(doc),encoding="utf-8")

    def test_complete_sanitized_aggregate_is_readiness_not_units_certification(self):
        doc=fictional_evidence()
        result=A.check_evidence(doc)
        self.assertTrue(result["ready_to_plan_independent_unit_check"])
        self.assertEqual(result["observed_window_count"],4)
        self.assertEqual(result["unique_stock_count"],2)
        self.assertEqual(result["unique_date_count"],2)
        self.assertEqual(result["fully_aligned_window_count"],4)
        self.assertEqual(result["low_cross_period_gap_window_count"],4)
        self.assertIn("no_independent_physical_unit_documentation",
                      result["evidence_blockers"])
        for key in ("amount_physical_unit_certified",
                    "volume_physical_unit_certified",
                    "price_precision_mapping_certified",
                    "licensed_parquet_to_h5_mapping_certified",
                    "ready_for_full_market_mirror"):
            self.assertFalse(result[key])

    def test_run_outputs_only_aggregated_safe_and_does_not_open_data(self):
        doc=fictional_evidence()
        self.write(doc)
        with patch.object(A,"open",create=True) as faux:
            faux.side_effect=AssertionError("no generic open for market files")
            result=A.assess(self.input,self.output)
        out=json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(out,result)
        self.assertTrue(out["no_licensed_parquet_or_market_h5_opened"])
        self.assertNotIn("2026-08-17",
                         self.output.read_text(encoding="utf-8"))
        self.assertNotIn("SH600000",
                         self.output.read_text(encoding="utf-8"))
        self.assertNotIn("day_vs_5min_amount_relative_gap",
                         self.output.read_text(encoding="utf-8"))

    def test_raw_ohlcva_and_source_paths_are_forbidden(self):
        original=fictional_evidence()
        changes=[
            dict(original,source_file=r"D:\\market\\paid.parquet"),
            dict(original,raw_rows=[{"close":9.123}]),
            dict(original,schemas=dict(original["schemas"],
                    day=dict(original["schemas"]["day"],open="5.00"))),
            dict(original,windows=[dict(original["windows"][0],
                                       amount_value="123")] + original["windows"][1:]),
            dict(original,format="unknown"),
        ]
        for changed in changes:
            with self.subTest(changed_keys=set(changed)):
                with self.assertRaises(ValueError):
                    A.check_evidence(changed)

    def test_reject_partial_window_coverage_without_claiming_ready(self):
        doc=fictional_evidence()
        doc["windows"]=doc["windows"][:3]
        out=A.check_evidence(doc)
        self.assertFalse(out["ready_to_plan_independent_unit_check"])
        self.assertIn("insufficient_distinct_stock_date_windows",
                      out["evidence_blockers"])

    def test_missing_schema_and_unknown_timestamps_block_readiness(self):
        doc=fictional_evidence()
        del doc["schemas"]["5min"]
        with self.assertRaisesRegex(ValueError,"day, 5min and 1min"):
            A.check_evidence(doc)
        doc=fictional_evidence()
        doc["schemas"]["1min"]["timezone"]="unknown"
        out=A.check_evidence(doc)
        self.assertFalse(out["ready_to_plan_independent_unit_check"])
        self.assertIn("missing_parquet_schema_type_or_timezone",
                      out["evidence_blockers"])

    def test_closed_sessions_and_matching_adjustment_are_required(self):
        doc=fictional_evidence()
        doc["windows"][0]["time_grid_checked"]=False
        doc["windows"][1]["same_adjustment_basis"]=False
        out=A.check_evidence(doc)
        self.assertEqual(out["fully_aligned_window_count"],2)
        self.assertFalse(out["ready_to_plan_independent_unit_check"])
        self.assertIn("closed_session_time_grid_or_adjustment_unproven",
                      out["evidence_blockers"])

    def test_relative_gap_is_exact_decimal_no_float_or_exponent(self):
        for v in (-1,0.01,"-0.1","1e-6","NaN","Infinity","1.000000001",
                  "0.0000000000001",None,True):
            with self.subTest(value=v):
                with self.assertRaises(ValueError):
                    A._gap(v)
        self.assertEqual(A._gap("0.0001"),A.CANDIDATE_GAP_LIMIT)
        self.assertEqual(A._gap("0"),0)
        doc=fictional_evidence()
        doc["windows"][2]["day_vs_1min_amount_relative_gap"]="0.5"
        out=A.check_evidence(doc)
        self.assertEqual(out["low_cross_period_gap_window_count"],3)
        self.assertFalse(out["ready_to_plan_independent_unit_check"])

    def test_invalid_dates_duplicate_stock_windows_and_counts_rejected(self):
        for bad in ("2026-02-30","2026-13-01","2026-08-17T16:00","2026/08/17"):
            doc=fictional_evidence()
            doc["windows"][0]["date"]=bad
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    A.check_evidence(doc)
        doc=fictional_evidence()
        doc["windows"].append(dict(doc["windows"][0]))
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            A.check_evidence(doc)
        for name,bad in (("day_rows",0),("min5_rows",61),
                         ("min1_rows",-1),("min1_rows",True)):
            doc=fictional_evidence()
            doc["windows"][0][name]=bad
            with self.subTest(name=name,bad=bad):
                with self.assertRaisesRegex(ValueError,"Invalid counts"):
                    A.check_evidence(doc)

    def test_explicit_documentation_still_does_not_certify_physical_units(self):
        doc=fictional_evidence()
        doc["independent_unit_reference"]="documented_external"
        for v in doc["schemas"].values():
            v["amount_unit_declared"]="unit_claim_from_source_documentation"
            v["volume_unit_declared"]="unit_claim_from_source_documentation"
        out=A.check_evidence(doc)
        self.assertTrue(out["ready_to_plan_independent_unit_check"])
        self.assertEqual(
            out["evidence_blockers"],
            ["aggregate_evidence_cannot_prove_row_level_unit_mapping"])
        self.assertFalse(out["licensed_parquet_to_h5_mapping_certified"])

    def test_existing_report_or_external_input_cannot_be_used(self):
        doc=fictional_evidence()
        self.write(doc)
        self.output.write_text("protected",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            A.assess(self.input,self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"),"protected")
        outer=Path(self.tmp.name)/"external.json"
        outer.write_text(json.dumps(doc),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"direct non-symlink"):
            A.assess(outer,self.reports/"new.json")

    def test_untrusted_evidence_claims_rejected(self):
        for key,value in (
            ("sanitized_aggregates_only",False),
            ("no_raw_market_rows",False),
            ("independent_unit_reference","certified")):
            doc=fictional_evidence()
            doc[key]=value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    A.check_evidence(doc)


if __name__=="__main__":
    unittest.main(verbosity=2)
