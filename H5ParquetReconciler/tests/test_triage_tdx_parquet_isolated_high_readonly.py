"""Synthetic regression for read-only isolated-minute-High mechanism."""
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
    "test_isolated_high_research",
    HERE/"triage-tdx-parquet-isolated-high-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture(mode="isolated"):
    pq_keys=M.probe.time_profiles("1min")["1min_opening_plus_end_241"]
    pq=[(pq_keys[0],(9.9,9.9,9.9,9.9,7.,70.))]+[
        (t,(10.,11.,9.,10.,2.,20.)) for t in pq_keys[1:]]
    keys=M.probe.time_profiles("1min")["1min_end_240"]
    candidate=[(keys[0],M.native._aggregate(pq[:2]))]+pq[2:]
    tdx=list(candidate)
    if mode in ("isolated","visible","many"):
        index=7
        time,bar=tdx[index]
        high=10.5 if mode in ("isolated","many") else 12.
        tdx[index]=(time,(bar[0],high,bar[2],bar[3],bar[4],bar[5]))
        if mode=="many":
            index=13
            time,bar=tdx[index]
            tdx[index]=(time,(bar[0],10.5,bar[2],bar[3],bar[4],bar[5]))
    elif mode=="volume":
        index=7
        t,bar=tdx[index]
        tdx[index]=(t,bar[:4]+(5.,bar[5]))
    elif mode=="first":
        t,bar=tdx[0]
        tdx[0]=(t,(bar[0],10.5,bar[2],bar[3],bar[4],bar[5]))
    native_five=M._grouped(tdx)
    pq_end=M._grouped(candidate)
    pq_five=[(t-5,v) for t,v in pq_end]
    return tdx,pq,native_five,pq_five


class IsolatedHighTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.mod=Path(tmp.name)/"H5ParquetReconciler"
        self.mod.mkdir()
        self.reports=self.mod/"reports"
        self.reports.mkdir()
        for k,value in (("MODULE",self.mod),("REPORTS",self.reports)):
            patch=mock.patch.object(M.probe,k,value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_one_high_disagreement_masked_by_other_five_minute_peak(self):
        r=M.diagnose_in_memory(*fixture("isolated"))
        self.assertEqual(r["mismatch_counts_by_field"],
                         {"open":0,"high":1,"low":0,"close":0,"volume":0,"amount":0})
        self.assertTrue(r["isolated_high_only"])
        self.assertFalse(r["first_minute_any_field_disagreement"])
        self.assertEqual(r["affected_five_minute_intervals_count"],1)
        self.assertEqual(r["high_mismatch_source_minute_was_native_interval_max_count"],0)
        self.assertEqual(r["high_mismatch_source_minute_was_purchased_interval_max_count"],1)
        self.assertEqual(r["high_mismatch_source_minute_was_both_interval_max_count"],0)
        self.assertEqual(r["high_mismatch_containing_interval_aggregated_high_disagrees_count"],0)
        self.assertTrue(r["native_1min_internal_5min_all_fields_match"])
        self.assertTrue(r["purchased_candidate_1min_internal_5min_all_fields_match"])
        self.assertTrue(r["cross_source_5min_all_fields_match"])
        self.assertEqual(r["verdict"],
                         "isolated_minute_high_disagreement_not_visible_at_5min_tolerance")
        self.assertFalse(r["eligible_for_automatic_production_union"])
        self.assertFalse(r["candidate_ohlcva_exported"])

    def test_high_disagreement_reaches_five_minute_high(self):
        r=M.diagnose_in_memory(*fixture("visible"))
        self.assertTrue(r["isolated_high_only"])
        self.assertEqual(r["high_mismatch_source_minute_was_native_interval_max_count"],1)
        self.assertEqual(r["high_mismatch_containing_interval_aggregated_high_disagrees_count"],1)
        self.assertFalse(r["cross_source_5min_all_fields_match"])
        self.assertEqual(r["native_5min_vs_purchased_5min"]["high"][
            "within_diagnostic_tolerance"],47)
        self.assertEqual(r["verdict"],"other_or_cross_period_disagreement_do_not_materialize")

    def test_two_high_differences_do_not_qualify_as_isolated(self):
        r=M.diagnose_in_memory(*fixture("many"))
        self.assertEqual(r["high_mismatch_records"],2)
        self.assertEqual(r["affected_five_minute_intervals_count"],2)
        self.assertFalse(r["isolated_high_only"])
        self.assertEqual(r["verdict"],"other_or_cross_period_disagreement_do_not_materialize")

    def test_volume_mismatch_prevents_high_only_verdict(self):
        r=M.diagnose_in_memory(*fixture("volume"))
        self.assertEqual(r["mismatch_counts_by_field"]["volume"],1)
        self.assertEqual(r["mismatch_counts_by_field"]["high"],0)
        self.assertFalse(r["isolated_high_only"])
        self.assertFalse(r["cross_source_5min_all_fields_match"])

    def test_no_anomaly_diagnostic_only_never_production(self):
        r=M.diagnose_in_memory(*fixture("clean"))
        self.assertEqual(r["high_mismatch_records"],0)
        self.assertTrue(r["cross_source_5min_all_fields_match"])
        self.assertEqual(r["verdict"],"all_checked_minute_and_five_minute_fields_match")
        self.assertFalse(r["eligible_for_automatic_production_union"])

    def test_first_minute_disagreement_not_hidden(self):
        r=M.diagnose_in_memory(*fixture("first"))
        self.assertTrue(r["first_minute_any_field_disagreement"])
        self.assertTrue(r["isolated_high_only"])
        self.assertEqual(r["high_mismatch_records"],1)

    def test_missing_or_duplicate_source_minute_rejected(self):
        tdx,pq,n5,p5=fixture("isolated")
        with self.assertRaisesRegex(ValueError,"exactly 241"):
            M.diagnose_in_memory(tdx,pq[:-1],n5,p5)
        wrong=list(tdx)
        wrong[3]=(wrong[2][0],wrong[3][1])
        with self.assertRaisesRegex(ValueError,"minute grid"):
            M.diagnose_in_memory(wrong,pq,n5,p5)

    def test_real_read_facade_source_pins_and_no_bar_export(self):
        tdx,pq,n5,p5=fixture("isolated")
        meta={
            "1min":{"period":"1min","time_grid_classification":"1min_end_240",
                    "source_content_sha256":"a"*64},
            "5min":{"period":"5min","time_grid_classification":"5min_end_48",
                    "source_content_sha256":"b"*64},
        }
        def native_probe(file,*_):
            return meta["1min"] if Path(file).suffix==".lc1" else meta["5min"]
        def read(_file,period,*_):
            return tdx if period=="1min" else n5
        def safe_rows(period,rows):
            return [{**dict(zip(M.FIELDS,values)),
                     "trading_date":"2026-07-16","period":period,
                     "source_beijing_time":
                         f"2026-07-16 {minute//60:02}:{minute%60:02}"}
                    for minute,values in rows]
        meta_pq={
            period:{"source_manifest_stat_only_sha256":mark*64,
                    "matching_bar_count":count,
                    "source_manifest_is_stat_only_not_content_authenticated":True}
            for period,mark,count in (("1min","c",241),("5min","d",48))}
        with mock.patch.object(M.probe,"inspect",side_effect=native_probe),\
             mock.patch.object(M.native,"_read_day_values",side_effect=read),\
             mock.patch.object(M.opening,"_purchased",return_value=(
                 {"1min":safe_rows("1min",pq),"5min":safe_rows("5min",p5)},
                 meta_pq)):
            r=M.diagnose(Path("fake_purchased"),Path("stock.lc1"),
                         Path("stock.lc5"),"SH600000","2026-07-16")
        self.assertEqual(r["tdx_source_content_sha256"]["1min"],"a"*64)
        self.assertEqual(r["tdx_source_content_sha256"]["5min"],"b"*64)
        self.assertTrue(r["native_source_hash_verified_against_second_read"])
        self.assertEqual(r["mismatch_counts_by_field"]["high"],1)
        self.assertFalse(r["candidate_materialized"])
        self.assertFalse(r["market_ohlcva_or_private_paths_exported"])
        payload=json.dumps(r)
        self.assertNotIn("source_beijing_time",payload)
        self.assertNotIn("09:30",payload)
        self.assertNotIn("fake_purchased",payload)

    def test_cli_safe_output_and_never_overwrites(self):
        r={"format":M.FORMAT,**M.diagnose_in_memory(*fixture("isolated")),
           "eligible_for_automatic_production_union":False}
        argv=["--parquet-root","ignored","--tdx-1min-file","a.lc1",
              "--tdx-5min-file","a.lc5","--symbol","SH600000",
              "--date","2026-07-16","--read-only",
              "--out","reports/isolated-high-safe-v1.json"]
        with mock.patch.object(M,"diagnose",return_value=r),redirect_stdout(StringIO()):
            M.main(argv)
        out=self.reports/"isolated-high-safe-v1.json"
        parsed=json.loads(out.read_text("utf-8"))
        self.assertEqual(parsed["mismatch_counts_by_field"]["high"],1)
        self.assertFalse(parsed["eligible_for_automatic_production_union"])
        with mock.patch.object(M,"diagnose",return_value=r),\
             redirect_stderr(StringIO()),self.assertRaises(SystemExit):
            M.main(argv)


if __name__=="__main__":
    unittest.main()
