"""Synthetic SAFE preview-cohort validation and source-lineage tests."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stderr,redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parents[1]/"tools"
SPEC=importlib.util.spec_from_file_location(
    "tdx_pq_safe_preview_cohort_test",
    HERE/"summarize-tdx-parquet-normalization-previews-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def metrics(n,good=True):
    result={}
    for field in M.FIELDS:
        p={"n":n,"within_diagnostic_tolerance":n if good else n-1,
           "max_relative_error":0 if good else 0.1,
           "mean_relative_error":0 if good else 0.01}
        if field in ("volume","amount"):
            p.update({"ratio_actual_over_reference_median":1.,
                      "positive_reference_count":n,"zero_reference_count":0})
        result[field]=p
    return result


def example(symbol="SH600000",day="2026-09-30",good=True):
    return {
        "format":M.SOURCE_FORMAT,"symbol":symbol,"date":day,
        "native_source_content_sha256":"a"*64,
        "native_source_basename":symbol.lower()+".lc1",
        "source_and_candidate_grid":dict(M.GRID),
        "purchased_source_stat_only_provenance":{
            period:{
                "source_manifest_stat_only_sha256":letter*64,
                "matching_bar_count":n,
                "source_manifest_is_stat_only_not_content_authenticated":True,
            }
            for period,letter,n in (("1min","b",241),("5min","c",48))
        },
        "mapping_lineage_summary":{
            **M.LINEAGE,
            "first_candidate_source_rows_folded_not_deleted":True,
            "all_source_records_preserved_in_original_files":True,
            "candidate_end_minute_labels_are_hypothetical":True,
        },
        "candidate_vs_native_first_minute":metrics(1,good),
        "candidate_vs_native_remaining_239":metrics(239),
        "candidate_vs_native_full_240":metrics(240,good),
        "candidate_240_to_purchased_48_five_minute":metrics(48),
        "gates":{
            "first_candidate_matches_native":good,
            "remaining_239_match_native":True,
            "candidate_240_matches_native":good,
            "candidate_5min_matches_purchased_5min":True,
            "diagnostic_preview_consistent":good,
        },
        "preview_verdict":(
            "diagnostic_candidate_matches_both_sources_not_production_certified"
            if good else "diagnostic_candidate_mismatch_do_not_materialize"),
        **M.SAFETY,
    }


def history(rows):
    samples=[]
    for source in rows:
        previews=source["purchased_source_stat_only_provenance"]
        samples.append({
            "symbol":source["symbol"],"date":source["date"],
            "native_full_source_sha256":source["native_source_content_sha256"],
            "parquet_manifest_fingerprints_stat_only":{
                k:previews[k]["source_manifest_stat_only_sha256"]
                for k in ("1min","5min")},
            "all_required_diagnostics_match":
                source["gates"]["diagnostic_preview_consistent"],
        })
    return {
        "format":M.cohort.FORMAT,
        "evidence_only_no_source_market_bars_read":True,
        "production_mapping_certified":False,
        "eligible_for_automatic_production_union":False,
        "parquet_source_manifests_are_stat_only":True,
        "no_raw_ohlcva_or_intraday_times_in_report":True,
        "unique_stock_days":len(samples),
        "distinct_symbols":len({x["symbol"] for x in samples}),
        "distinct_dates":len({x["date"] for x in samples}),
        "samples":samples,
    }


class SafePreviewCohortTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.module=Path(temp.name)/"H5ParquetReconciler"
        self.module.mkdir()
        self.reports=self.module/"reports"
        self.reports.mkdir()
        for name,value in (("MODULE",self.module),
                           ("REPORTS",self.reports)):
            patch=mock.patch.object(M.cohort,name,value)
            patch.start()
            self.addCleanup(patch.stop)

    def write(self,name,doc):
        file=self.reports/name
        file.write_text(json.dumps(doc),encoding="utf-8")
        return file

    def test_single_candidate_stays_not_certified(self):
        f=self.write("one.json",example())
        result=M.summarize([f])
        self.assertEqual(result["verdict"],"matched_but_preview_sample_too_small")
        self.assertTrue(result["all_supplied_previews_match"])
        self.assertFalse(result["production_mapping_certified"])
        self.assertFalse(result["eligible_for_automatic_production_union"])
        self.assertFalse(result["original_audit_cohort_crosschecked"])
        self.assertEqual(result["samples"][0][
            "full_240_max_relative_error_by_field"]["volume"],0)

    def test_six_stockdays_crosscheck_and_order_independence(self):
        docs=[example(symbol,day) for day in (
            "2026-09-28","2026-09-29","2026-09-30")
            for symbol in ("SH600000","SZ000001")]
        files=[self.write(f"{i}.json",r) for i,r in enumerate(docs)]
        baseline=self.write("baseline.json",history(docs))
        for items in (files,list(reversed(files))):
            with self.subTest(order=[f.name for f in items]):
                result=M.summarize(items,baseline)
                self.assertEqual(result["unique_stock_days"],6)
                self.assertEqual(result["distinct_symbols"],2)
                self.assertEqual(result["distinct_dates"],3)
                self.assertTrue(result["original_audit_cohort_crosschecked"])
                self.assertTrue(result["exploratory_target_met"])
                self.assertEqual(result["verdict"],
                                 "exploratory_preview_target_met_not_certified")
                self.assertFalse(result["production_mapping_certified"])

    def test_true_mismatch_is_reported_not_silenced(self):
        docs=[example(),example("SZ000001","2026-09-28",False)]
        files=[self.write(f"{i}.json",doc) for i,doc in enumerate(docs)]
        result=M.summarize(files)
        self.assertEqual(result["verdict"],"preview_disagreement_do_not_materialize")
        self.assertFalse(result["all_supplied_previews_match"])
        by_id={(x["symbol"],x["date"]):x for x in result["samples"]}
        self.assertFalse(by_id[("SZ000001","2026-09-28")][
            "all_preview_diagnostics_match"])

    def test_modified_or_unsafe_evidence_report_rejected(self):
        altered=example()
        altered["original_sources_modified"]=True
        path=self.write("unsafe.json",altered)
        with self.assertRaisesRegex(ValueError,"Unsafe preview"):
            M.summarize([path])
        altered=example()
        altered["mapping_lineage_summary"]["original_minutes_discarded"]=1
        self.write("unsafe.json",altered)
        with self.assertRaisesRegex(ValueError,"does not account"):
            M.summarize([path])
        altered=example()
        altered["source_and_candidate_grid"]["candidate_preview_1min"]="different"
        self.write("unsafe.json",altered)
        with self.assertRaisesRegex(ValueError,"timestamp grids"):
            M.summarize([path])

    def test_contradictory_metrics_and_verdict_rejected(self):
        bad=example()
        bad["candidate_vs_native_first_minute"]["open"][
            "within_diagnostic_tolerance"]=0
        src=self.write("bad.json",bad)
        with self.assertRaisesRegex(ValueError,"Contradictory"):
            M.summarize([src])
        bad=example()
        bad["preview_verdict"]="diagnostic_candidate_mismatch_do_not_materialize"
        self.write("bad.json",bad)
        with self.assertRaisesRegex(ValueError,"Contradictory"):
            M.summarize([src])
        bad=example()
        bad["candidate_vs_native_full_240"]["amount"][
            "max_relative_error"]=float("nan")
        self.write("bad.json",bad)
        with self.assertRaisesRegex(ValueError,"Nonfinite"):
            M.summarize([src])

    def test_crosscheck_rejects_source_mismatch_or_dates(self):
        docs=[example()]
        src=self.write("one.json",docs[0])
        base=history(docs)
        base["samples"][0]["native_full_source_sha256"]="e"*64
        history_file=self.write("baseline.json",base)
        with self.assertRaisesRegex(ValueError,"provenance/verdict mismatch"):
            M.summarize([src],history_file)
        base=history(docs)
        base["samples"][0]["date"]="2026-09-29"
        self.write("baseline.json",base)
        with self.assertRaisesRegex(ValueError,"stock-days differ"):
            M.summarize([src],history_file)
        base=history(docs)
        base["samples"][0]["parquet_manifest_fingerprints_stat_only"]["1min"]="f"*64
        self.write("baseline.json",base)
        with self.assertRaisesRegex(ValueError,"provenance/verdict mismatch"):
            M.summarize([src],history_file)

    def test_duplicate_stock_day_and_unsafe_source_path_rejected(self):
        a=self.write("one.json",example())
        b=self.write("two.json",example())
        with self.assertRaisesRegex(ValueError,"Duplicate candidate preview"):
            M.summarize([a,b])
        outside=self.module/"not-in-reports.json"
        outside.write_text(json.dumps(example()))
        with self.assertRaisesRegex(ValueError,"Use existing input"):
            M.summarize([outside])

    def test_cli_creates_once_and_never_overwrites(self):
        a=self.write("one.json",example())
        baseline=self.write("baseline.json",history([example()]))
        cmd=["--report",str(a),"--cohort",str(baseline),"--read-only",
             "--out","reports/preview-evidence-summary.json"]
        with redirect_stdout(StringIO()):
            M.main(cmd)
        result=json.loads((self.reports/"preview-evidence-summary.json").
                          read_text(encoding="utf-8"))
        self.assertEqual(result["unique_stock_days"],1)
        self.assertTrue(result["original_audit_cohort_crosschecked"])
        self.assertTrue(result["no_raw_ohlcva_or_intraday_times_in_report"])
        self.assertFalse((self.module/"work").exists())
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
            M.main(cmd)


if __name__=="__main__":
    unittest.main()
