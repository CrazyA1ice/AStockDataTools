"""Synthetic-only contract tests for memory-only TDX/Parquet 241->240 preview."""
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
    "tdx_pq_241_candidate_preview_tests",
    TOOLS/"preview-tdx-parquet-1min-normalization-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
DAY="2026-09-30"
SYMBOL="SH600000"
FIELDS=M.FIELDS


def fixtures(open_volume=7.,open_amount=70.):
    keys=M.probe.time_profiles("1min")["1min_opening_plus_end_241"]
    raw=[(time,(9.9,9.9,9.9,9.9,open_volume,open_amount))
         if n==0 else (time,(10.,11.,9.,10.,2.,20.))
         for n,time in enumerate(keys)]
    candidate=[(keys[1],M.native._aggregate(raw[:2]))]+raw[2:]
    five_start=tuple(
        t-5 for t in M.probe.time_profiles("5min")["5min_end_48"])
    five=[(start,M.native._aggregate(candidate[i*5:(i+1)*5]))
          for i,start in enumerate(five_start)]
    return candidate,raw,five


class PreviewTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.mod=Path(tmp.name)/"H5ParquetReconciler"
        self.mod.mkdir()
        self.reports=self.mod/"reports"
        self.reports.mkdir()
        for name,obj in (("MODULE",self.mod),("REPORTS",self.reports.resolve())):
            patch=mock.patch.object(M.probe,name,obj)
            patch.start()
            self.addCleanup(patch.stop)

    def test_complete_241_to_240_candidate_and_five_minute_matches(self):
        tdx,pq,five=fixtures()
        result=M.preview_in_memory(tdx,pq,five)
        self.assertEqual(result["preview_verdict"],
                         "diagnostic_candidate_matches_both_sources_not_production_certified")
        self.assertTrue(result["gates"]["diagnostic_preview_consistent"])
        self.assertEqual(
            result["mapping_lineage_summary"]["source_minute_records_accounted_for_once"],241)
        self.assertEqual(result["mapping_lineage_summary"]["original_minutes_discarded"],0)
        self.assertEqual(result["mapping_lineage_summary"]["original_rows_used_by_first_candidate"],2)
        self.assertEqual(result["mapping_lineage_summary"]["original_rows_used_by_remaining_candidates"],239)
        self.assertFalse(result["eligible_for_staging_or_automatic_production_union"])
        self.assertFalse(result["candidate_ohlcva_exported"])
        for label,n in (("candidate_vs_native_first_minute",1),
                        ("candidate_vs_native_remaining_239",239),
                        ("candidate_vs_native_full_240",240),
                        ("candidate_240_to_purchased_48_five_minute",48)):
            for metric in result[label].values():
                self.assertEqual(metric["n"],n)
                self.assertEqual(metric["within_diagnostic_tolerance"],n)

    def test_nonzero_opening_is_not_discarded_as_padding(self):
        tdx,pq,five=fixtures(open_volume=700.,open_amount=7000.)
        result=M.preview_in_memory(tdx,pq,five)
        self.assertTrue(result["gates"]["diagnostic_preview_consistent"])
        self.assertEqual(result["candidate_vs_native_first_minute"][
            "volume"]["max_relative_error"],0.)
        self.assertEqual(result["mapping_lineage_summary"][
            "source_minute_records_accounted_for_once"],241)

    def test_native_first_bar_disagreement_blocks_preview(self):
        tdx,pq,five=fixtures()
        native_bad=list(tdx)
        old=native_bad[0][1]
        native_bad[0]=(native_bad[0][0],old[:4]+(old[4]+10.,old[5]+100.))
        result=M.preview_in_memory(native_bad,pq,five)
        self.assertFalse(result["gates"]["first_candidate_matches_native"])
        self.assertTrue(result["gates"]["candidate_5min_matches_purchased_5min"])
        self.assertEqual(result["preview_verdict"],
                         "diagnostic_candidate_mismatch_do_not_materialize")
        self.assertFalse(result["eligible_for_staging_or_automatic_production_union"])

    def test_purchased_five_minute_disagreement_blocks_preview(self):
        tdx,pq,five=fixtures()
        wrong=list(five)
        t,bar=wrong[3]
        wrong[3]=(t,bar[:4]+(bar[4]+100.,bar[5]+1000.))
        result=M.preview_in_memory(tdx,pq,wrong)
        self.assertTrue(result["gates"]["candidate_240_matches_native"])
        self.assertFalse(result["gates"]["candidate_5min_matches_purchased_5min"])
        self.assertFalse(result["gates"]["diagnostic_preview_consistent"])

    def test_missing_or_duplicate_minute_fail_closed(self):
        tdx,pq,five=fixtures()
        with self.assertRaisesRegex(ValueError,"exactly 241"):
            M.preview_in_memory(tdx,pq[:-1],five)
        wrong=list(pq)
        wrong[2]=(wrong[1][0],wrong[2][1])
        with self.assertRaisesRegex(ValueError,"minute grid"):
            M.preview_in_memory(tdx,wrong,five)
        wrong=list(five)
        wrong.pop()
        with self.assertRaisesRegex(ValueError,"exactly 48"):
            M.preview_in_memory(tdx,pq,wrong)

    def test_invalid_source_price_or_turnover_fails_closed(self):
        tdx,pq,five=fixtures()
        wrong=list(pq)
        wrong[1]=(wrong[1][0],(10.,9.,9.,10.,2.,20.))
        with self.assertRaisesRegex(ValueError,"impossible OHLCVA geometry"):
            M.preview_in_memory(tdx,wrong,five)
        wrong=list(pq)
        wrong[1]=(wrong[1][0],(10.,11.,9.,10.,float("nan"),20.))
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            M.preview_in_memory(tdx,wrong,five)
        wrong=list(pq)
        wrong[1]=(wrong[1][0],(10.,11.,9.,10.,-2.,20.))
        with self.assertRaisesRegex(ValueError,"impossible OHLCVA geometry"):
            M.preview_in_memory(tdx,wrong,five)

    def test_source_pin_and_safe_json_never_exports_market_bars(self):
        tdx,pq,five=fixtures()
        def rows(period,data):
            return [{
                **dict(zip(FIELDS,values)),
                "period":period,"trading_date":DAY,
                "source_beijing_time":DAY+f" {t//60:02}:{t%60:02}",
            } for t,values in data]
        src={"1min":rows("1min",pq),"5min":rows("5min",five)}
        stat={
            p:{"source_manifest_stat_only_sha256":letter*64,
               "matching_bar_count":n,
               "source_manifest_is_stat_only_not_content_authenticated":True}
            for p,letter,n in (("1min","a",241),("5min","b",48))}
        meta={"period":"1min","time_grid_classification":"1min_end_240",
              "source_content_sha256":"c"*64,"native_source_basename":"sh600000.lc1"}
        with mock.patch.object(M.probe,"inspect",return_value=meta),\
             mock.patch.object(M.native,"_read_day_values",return_value=tdx),\
             mock.patch.object(M.opening,"_purchased",return_value=(src,stat)):
            report=M.preview(Path("ignored"),Path("sh600000.lc1"),SYMBOL,DAY)
        self.assertEqual(report["native_source_content_sha256"],"c"*64)
        self.assertTrue(report["gates"]["diagnostic_preview_consistent"])
        self.assertTrue(report["no_raw_ohlcva_or_individual_times_in_report"])
        self.assertFalse(report["eligible_for_automatic_production_union"])
        serialized=json.dumps(report)
        for raw in ("9.9", "11.0", "70.0", "7000.0"):
            self.assertNotIn(raw,serialized)
        self.assertNotIn("09:30",serialized)

    def test_cli_safe_output_only_and_refuses_overwrite(self):
        tdx,pq,five=fixtures()
        sample={"format":M.FORMAT,"symbol":SYMBOL,"date":DAY,
                **M.preview_in_memory(tdx,pq,five),
                "eligible_for_automatic_production_union":False,
                "no_raw_ohlcva_or_individual_times_in_report":True}
        argv=["--parquet-root","ignored","--tdx-1min-file","ignored",
              "--symbol",SYMBOL,"--date",DAY,"--read-only",
              "--out","reports/candidate-preview.json"]
        with mock.patch.object(M,"preview",return_value=sample):
            with redirect_stdout(StringIO()):
                M.main(argv)
        doc=json.loads((self.reports/"candidate-preview.json").read_text("utf-8"))
        self.assertFalse(doc["candidate_ohlcva_exported"])
        self.assertEqual(doc["mapping_lineage_summary"][
            "original_minutes_discarded"],0)
        with mock.patch.object(M,"preview",return_value=sample):
            with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
                M.main(argv)


if __name__=="__main__":
    unittest.main()
