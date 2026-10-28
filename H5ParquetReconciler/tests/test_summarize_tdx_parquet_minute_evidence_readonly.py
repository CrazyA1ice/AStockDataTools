"""Strict synthetic-only stock-day SAFE-evidence cohort gate tests."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stderr,redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

TOOLS=Path(__file__).resolve().parents[1]/"tools"
SPEC=importlib.util.spec_from_file_location(
    "tdx_pq_opening_evidence_cohort_test",
    TOOLS/"summarize-tdx-parquet-minute-evidence-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def group(n,good=True):
    return {key:{"n":n,"within_diagnostic_tolerance":
                 n if good else n-1,
                 "max_relative_error":0 if good else .1,
                 "mean_relative_error":0 if good else .001}
            for key in M.FIELDS}


def example(symbol="SH600000",day="2026-09-30",good=True):
    return {
        "format":M.SOURCE_FORMAT,"symbol":symbol,"date":day,
        "tdx_verified_minute_count":240,
        "parquet_verified_minute_count":241,
        "parquet_verified_five_minute_count":48,
        "tdx_full_source_sha256":"a"*64,
        "parquet_stat_only_provenance":{
            period:{
                "source_manifest_stat_only_sha256":letter*64,
                "matching_bar_count":count,
                "source_manifest_is_stat_only_not_content_authenticated":True,
            } for period,letter,count in (("1min","b",241),("5min","c",48))},
        "first_minute_opening_merge_hypothesis":{
            "native_0931_vs_aggregation_of_parquet_0930_and_0931":group(1,good),
            "remaining_239_native_vs_parquet":group(239),
            "all_240_native_vs_first_merged_plus_remaining_239":group(240,good),
            "first_minute_all_six_fields_match_after_merge":good,
            "remaining_239_all_six_fields_match":True,
            "all_240_all_six_fields_match_after_merge":good,
            "opening_merge_is_only_a_hypothesis_not_a_mapping_rule":True,
        },
        "parquet_opening_241_in_first_five_minute_vs_five_minute":group(48),
        "opening_bar_diagnostics":{
            "observed_separate_0930_opening_key":True,
            "opening_source_semantics_not_certified":True,
            "opening_zero_volume":False,
            "opening_zero_amount":False,
        },
        "first_0930_key_never_synthesized_or_dropped_for_production":True,
        "amount_and_volume_unit_conversion_not_applied":True,
        "no_raw_ohlcva_or_individual_times_in_report":True,
        "private_cache_enabled":False,"h5_accessed":False,
        "sources_modified":False,
        "staging_or_production_union_performed":False,
        "eligible_for_automatic_production_union":False,
    }


class SafeCohortTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.mod=Path(temp.name)/"H5ParquetReconciler"
        self.mod.mkdir()
        self.reports=self.mod/"reports"
        self.reports.mkdir()
        for key,value in (("MODULE",self.mod),("REPORTS",self.reports)):
            patch=mock.patch.object(M,key,value)
            patch.start()
            self.addCleanup(patch.stop)

    def write(self,name,doc):
        path=self.reports/name
        path.write_text(json.dumps(doc),encoding="utf-8")
        return path

    def test_one_realistic_safe_report_is_insufficient_not_certified(self):
        report=self.write("one.json",example())
        result=M.summarize([report])
        self.assertEqual(result["unique_stock_days"],1)
        self.assertTrue(result["all_supplied_stock_days_match"])
        self.assertEqual(result["verdict"],
                         "matched_but_exploratory_cohort_too_small")
        self.assertFalse(result["production_mapping_certified"])
        self.assertFalse(result["eligible_for_automatic_production_union"])
        self.assertEqual(len(result["samples"]),1)

    def test_exploratory_sample_target_reached_still_not_certified(self):
        files=[]
        for day in ("2026-09-28","2026-09-29","2026-09-30"):
            for symbol in ("SH600000","SZ000001"):
                files.append(self.write(f"{symbol}-{day}.json",
                                        example(symbol,day)))
        result=M.summarize(files)
        self.assertEqual(result["unique_stock_days"],6)
        self.assertEqual(result["distinct_symbols"],2)
        self.assertEqual(result["distinct_dates"],3)
        self.assertTrue(result["exploratory_target_met"])
        self.assertEqual(result["verdict"],
                         "exploratory_sample_target_met_not_certified")
        self.assertFalse(result["production_mapping_certified"])

    def test_any_true_mismatch_reports_disagreement(self):
        files=[self.write("one.json",example()),
               self.write("two.json",example("SZ000001","2026-09-29",False))]
        # summarize() sorts samples by (date,symbol), NOT input-file order.
        # Always locate the actual disagreeing stock-day by identity.
        for inputs in (files,list(reversed(files))):
            with self.subTest(input_order=[p.name for p in inputs]):
                result=M.summarize(inputs)
                self.assertEqual(result["verdict"],
                                 "disagreement_observed_do_not_apply_mapping")
                self.assertFalse(result["all_supplied_stock_days_match"])
                by_stock_day={
                    (sample["symbol"],sample["date"]):
                        sample["all_required_diagnostics_match"]
                    for sample in result["samples"]
                }
                self.assertEqual(by_stock_day,{
                    ("SH600000","2026-09-30"):True,
                    ("SZ000001","2026-09-29"):False,
                })
                self.assertEqual(sum(not ok for ok in by_stock_day.values()),1)

    def test_mismatch_is_not_assumed_to_be_at_first_or_last_index(self):
        # Deliberately place a bad sample in the middle of the deterministic
        # date/symbol sort, independent of the order in which reports arrive.
        inputs=[
            self.write("later.json",example("SH600000","2026-09-30")),
            self.write("middle.json",example("SZ000001","2026-09-29",False)),
            self.write("earlier.json",example("SH600000","2026-09-28")),
        ]
        result=M.summarize(inputs)
        self.assertEqual(result["verdict"],
                         "disagreement_observed_do_not_apply_mapping")
        self.assertEqual([x["date"] for x in result["samples"]],
                         ["2026-09-28","2026-09-29","2026-09-30"])
        self.assertEqual(
            [x["all_required_diagnostics_match"] for x in result["samples"]],
            [True,False,True])

    def test_reject_duplicate_stock_day_or_wrong_format(self):
        a=self.write("one.json",example())
        b=self.write("two.json",example())
        with self.assertRaisesRegex(ValueError,"Duplicate symbol-day"):
            M.summarize([a,b])
        bad=example()
        bad["format"]="untrusted-adversarial"
        self.write("bad.json",bad)
        with self.assertRaisesRegex(ValueError,"Unsupported evidence-report"):
            M.summarize([self.reports/"bad.json"])

    def test_reject_contradictory_fields_and_unsafe_flags(self):
        bad=example()
        bad["first_minute_opening_merge_hypothesis"][
            "first_minute_all_six_fields_match_after_merge"]=False
        a=self.write("bad.json",bad)
        with self.assertRaisesRegex(ValueError,"Contradictory merge diagnostic"):
            M.summarize([a])
        bad=example()
        bad["eligible_for_automatic_production_union"]=True
        a.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError,"Unsafe or incomplete"):
            M.summarize([a])
        bad=example()
        bad["first_minute_opening_merge_hypothesis"][
            "remaining_239_native_vs_parquet"]["volume"]["n"]=999
        a.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError,"Malformed or inconsistent"):
            M.summarize([a])

    def test_only_existing_safe_reports_and_new_output_file_allowed(self):
        src=self.write("valid.json",example())
        with self.assertRaisesRegex(ValueError,"existing input"):
            M.summarize([self.mod/"outside.json"])
        args=["--report",str(src),"--read-only",
              "--out","reports/cohort-result.json"]
        with redirect_stdout(StringIO()):
            M.main(args)
        target=self.reports/"cohort-result.json"
        doc=json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(doc["unique_stock_days"],1)
        self.assertTrue(doc["no_raw_ohlcva_or_intraday_times_in_report"])
        self.assertFalse((self.mod/"work").exists())
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
            M.main(args)


if __name__=="__main__":
    unittest.main()
