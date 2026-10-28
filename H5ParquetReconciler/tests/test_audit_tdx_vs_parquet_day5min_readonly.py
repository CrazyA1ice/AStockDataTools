"""Synthetic, offline cross-vendor 5min START/END parity regression tests."""
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
    "tdx_pq_cross_vendor_readonly_test",
    TOOLS/"audit-tdx-vs-parquet-day5min-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SYMBOL="SH600000"
DAY="2026-09-30"
TDX_VALUE=(10.0,11.0,9.0,10.0,10.0,100.0)
DAY_VALUE=(10.0,11.0,9.0,10.0,480.0,4800.0)


def fixture():
    ends=M.native.probe.time_profiles("5min")["5min_end_48"]
    tdxbars={"5min":[(end,TDX_VALUE) for end in ends],
             "day":[(None,DAY_VALUE)]}
    out5=[]
    for end in ends:
        start=end-5
        fields=dict(zip(M.FIELDS,TDX_VALUE))
        out5.append({
            "symbol":SYMBOL,"period":"5min","trading_date":DAY,
            "source_beijing_time":DAY+f" {start//60:02d}:{start%60:02d}",
            **fields,
        })
    outday=[{
        "symbol":SYMBOL,"period":"day","trading_date":DAY,
        "source_beijing_time":DAY+" 00:00",**dict(zip(M.FIELDS,DAY_VALUE)),
    }]
    evidence={
        "input":{period:{"source_content_sha256":period[0]*64}
                 for period in ("day","5min","1min")},
        "comparisons":{"one_minute_aggregate_vs_five_minute_native":{
            name:{"n":48,"within_diagnostic_tolerance":48}
            for name in M.FIELDS}},
    }
    parquet_src={p:{"source_files_examined":1,
         "candidate_source_rows_upper_bound":100,
         "matching_bar_count":n,
         "source_manifest_stat_only_sha256":"a"*64,
         "source_manifest_is_stat_only_not_content_authenticated":True}
        for p,n in (("day",1),("5min",48))}
    return evidence,tdxbars,{"day":outday,"5min":out5},parquet_src


class TdxVsParquetAuditTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.module=Path(temp.name)/"H5ParquetReconciler"
        self.module.mkdir()
        self.reports=self.module/"reports"
        self.reports.mkdir()
        root=self.module/"market"
        (root/"AllCycleAStockData"/"5min").mkdir(parents=True)
        self.root=root
        for target,name,value in ((M,"MODULE",self.module),
                                  (M.native.probe,"MODULE",self.module),
                                  (M.native.probe,"REPORTS",self.reports.resolve())):
            p=mock.patch.object(target,name,value)
            p.start()
            self.addCleanup(p.stop)

    def run_synthetic(self,modify=None):
        proof,tdx,purchased,metadata=fixture()
        if modify:
            modify(proof,tdx,purchased,metadata)
        with mock.patch.object(M,"_native_bars",return_value=(proof,tdx)),mock.patch.object(
                M,"_purchase_bars",return_value=(purchased,metadata)):
            return M.audit(self.root,"day","5","1",SYMBOL,DAY)

    def test_strict_start_to_end_alignment_and_identical_values(self):
        report=self.run_synthetic()
        self.assertEqual(report["parquet_source_counts"],{"day":1,"5min":48})
        self.assertEqual(report["tdx_source_counts"],{"day":1,"1min":240,"5min":48})
        for data in report["comparisons"].values():
            for metric in data.values():
                self.assertEqual(metric["n"],metric["within_diagnostic_tolerance"])
                self.assertEqual(metric["max_relative_error"],0)
        self.assertTrue(report["parquet_one_minute_241_special_opening_not_compared"])
        self.assertTrue(report["tdx_internal_three_period_all_fields_within_tolerance"])
        self.assertIn("parquet_5min_aggregate_vs_parquet_daily",report["comparisons"])
        self.assertFalse(report["eligible_for_automatic_production_union"])
        self.assertFalse(report["staging_or_production_union_performed"])

    def test_out_of_profile_start_labels_fail_closed(self):
        def shift(_proof,_tdx,bar,_meta):
            bar["5min"][0]["source_beijing_time"]=DAY+" 09:35"
        with self.assertRaisesRegex(ValueError,"48 START labels"):
            self.run_synthetic(shift)

    def test_partial_five_minute_source_and_duplicate_label_fail_closed(self):
        def remove(_proof,_tdx,bar,_meta):
            bar["5min"].pop()
        with self.assertRaisesRegex(ValueError,"exactly 48"):
            self.run_synthetic(remove)
        def repeat(_proof,_tdx,bar,_meta):
            bar["5min"][1]["source_beijing_time"]=bar["5min"][0][
                "source_beijing_time"]
        with self.assertRaisesRegex(ValueError,"48 START labels"):
            self.run_synthetic(repeat)

    def test_real_numeric_disagreement_is_reported_not_normalized(self):
        def volume_x100(_proof,_tdx,bar,_meta):
            for row in bar["5min"]:
                row["volume"]*=100
        report=self.run_synthetic(volume_x100)
        volume=report["comparisons"]["tdx_5min_vs_parquet_5min_by_interval"][
            "volume"]
        self.assertEqual(volume["ratio_actual_over_reference_median"],100.)
        self.assertEqual(volume["within_diagnostic_tolerance"],0)
        self.assertTrue(report["cross_vendor_volume_and_amount_unit_convention_unverified"])

    def test_one_price_drift_fails_matching_but_not_hidden(self):
        def edit(_proof,_tdx,bar,_meta):
            bar["5min"][0]["close"]=10.25
        report=self.run_synthetic(edit)
        res=report["comparisons"]["tdx_5min_vs_parquet_5min_by_interval"]["close"]
        self.assertEqual(res["within_diagnostic_tolerance"],47)
        self.assertGreater(res["max_relative_error"],0)

    def test_parquet_stat_manifest_stable_and_mutation_guard(self):
        src=self.root/"AllCycleAStockData"/"5min"/"2026-09.parquet"
        src.write_bytes(b"pretend parquet contents")
        st=src.stat()
        manifest=[{"relative_path":"AllCycleAStockData/5min/2026-09.parquet",
                   "size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns}]
        M._verify_stat_manifest(self.root,manifest)
        src.write_bytes(src.read_bytes()+b"x")
        with self.assertRaisesRegex(ValueError,"source stat changed"):
            M._verify_stat_manifest(self.root,manifest)
        with self.assertRaisesRegex(ValueError,"Unsafe"):
            M._verify_stat_manifest(self.root,[{
                **manifest[0],"relative_path":"AllCycleAStockData/../evil.parquet"}])

    def test_parquet_query_cached_values_are_disabled(self):
        file=self.root/"AllCycleAStockData"/"5min"/"2026-09.parquet"
        file.write_bytes(b"test only")
        st=file.stat()
        manifest=[{"relative_path":"AllCycleAStockData/5min/2026-09.parquet",
                   "size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns}]
        _,_,bars,_=fixture()
        def stub(_root,_symbol,period,_date1,_date2,**kwargs):
            self.assertFalse(kwargs["local_cache"])
            return {"bars":bars[period],"safe_summary":{
                "symbol":SYMBOL,"period":period,"from_date":DAY,"to_date":DAY,
                "local_cache_used":False,"no_h5_read":True,
                "source_file_stat_provenance":manifest,
                "source_files_examined":1,
                "candidate_source_rows_upper_bound":100,
                "matching_bar_count":len(bars[period])}}
        with mock.patch.object(M.parquet,"query_bars",side_effect=stub):
            got,provenance=M._purchase_bars(self.root,SYMBOL,DAY,500)
        self.assertEqual(len(got["5min"]),48)
        self.assertTrue(provenance["day"][
            "source_manifest_is_stat_only_not_content_authenticated"])

    def test_cli_writes_metadata_only_and_refuses_overwrite(self):
        f,tdx,bars,metadata=fixture()
        args=["--parquet-root",str(self.root),
              "--tdx-day-file","day","--tdx-5min-file","five",
              "--tdx-1min-file","one","--symbol",SYMBOL,
              "--date",DAY,"--read-only",
              "--out","reports/tdx-parquet-safe-test.json"]
        with mock.patch.object(M,"_native_bars",return_value=(f,tdx)),mock.patch.object(
                M,"_purchase_bars",return_value=(bars,metadata)):
            with redirect_stdout(StringIO()):
                M.main(args)
            path=self.reports/"tdx-parquet-safe-test.json"
            blob=path.read_text()
            doc=json.loads(blob)
            self.assertTrue(doc["no_raw_ohlcva_or_individual_times_in_report"])
            self.assertEqual(doc["symbol"],SYMBOL)
            for raw in ('"open": 10','"volume": 480','"amount": 4800',
                        '"source_beijing_time"','"bars"'):
                self.assertNotIn(raw,blob)
            with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
                M.main(args)
        self.assertFalse((self.module/"work").exists())


if __name__=="__main__":
    unittest.main()
