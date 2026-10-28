"""TDX/Parquet 240+1-minute read-only diagnosis with synthetic market bars."""
import importlib.util
import json
import struct
import tempfile
import unittest
from contextlib import redirect_stderr,redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

TOOLS=Path(__file__).resolve().parents[1]/"tools"
SPEC=importlib.util.spec_from_file_location(
    "tdx_parquet_opening_test",
    TOOLS/"audit-tdx-vs-parquet-1min-opening-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
DAY="2026-09-30"
SYMBOL="SH600000"
OHLC={"open":10.,"high":11.,"low":9.,"close":10.}


def minute_bytes(t,volume=2,amount=20.,opening=10.):
    packed=(2026-2004)*2048+9*100+30
    return struct.pack("<HHfffffII",
                       packed,t,opening,11.,9.,10.,amount,volume,0)


def synthetic_pq(opening_volume=0.,opening_amount=0.,shared_volume=2.):
    one=[]
    five=[]
    keys=M.probe.time_profiles("1min")["1min_opening_plus_end_241"]
    for i,t in enumerate(keys):
        is_open=(i==0)
        volume=opening_volume if is_open else shared_volume
        amount=opening_amount if is_open else 20.
        row={**OHLC,"volume":volume,"amount":amount,
             "period":"1min","trading_date":DAY,
             "source_beijing_time":
             DAY+f" {t//60:02d}:{t%60:02d}"}
        if is_open:
            row.update({"high":10.,"low":10.})
        one.append(row)
    starts=[t-5 for t in M.probe.time_profiles("5min")["5min_end_48"]]
    for i,t in enumerate(starts):
        row={**OHLC,"volume":5*shared_volume+
             (opening_volume if i==0 else 0),
             "amount":100.+(opening_amount if i==0 else 0),
             "period":"5min","trading_date":DAY,
             "source_beijing_time":DAY+f" {t//60:02d}:{t%60:02d}"}
        five.append(row)
    return {"1min":one,"5min":five}


class OpeningMinuteAuditTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.mod=Path(temp.name)/"H5ParquetReconciler"
        self.mod.mkdir()
        self.reports=self.mod/"reports"
        self.reports.mkdir()
        self.root=self.mod/"market"
        (self.root/"AllCycleAStockData"/"1min").mkdir(parents=True)
        self.tdx=self.mod/"sh600000.lc1"
        self.tdx.write_bytes(b"".join(
            minute_bytes(t) for t in
            M.probe.time_profiles("1min")["1min_end_240"]))
        for module,name,value in (
            (M.probe,"MODULE",self.mod),
            (M.probe,"REPORTS",self.reports.resolve())):
            patch=mock.patch.object(module,name,value)
            patch.start()
            self.addCleanup(patch.stop)

    def examine(self,fixture=None):
        if fixture is None:
            fixture=synthetic_pq()
        provenance={"1min":{"matching_bar_count":241},
                    "5min":{"matching_bar_count":48}}
        with mock.patch.object(M,"_purchased",
                               return_value=(fixture,provenance)):
            return M.audit(self.root,self.tdx,SYMBOL,DAY)

    def test_240_common_keys_and_zero_opening_ambiguity(self):
        report=self.examine()
        self.assertEqual(report["tdx_verified_minute_count"],240)
        self.assertEqual(report["parquet_verified_minute_count"],241)
        self.assertEqual(report["parquet_verified_five_minute_count"],48)
        for metrics in report["common_240_minutes_tdx_vs_parquet"].values():
            self.assertEqual(metrics["n"],240)
            self.assertEqual(metrics["within_diagnostic_tolerance"],240)
        extra=report["opening_bar_diagnostics"]
        self.assertTrue(extra["opening_zero_amount"])
        self.assertTrue(extra["opening_zero_volume"])
        self.assertEqual(extra["aggregation_hypothesis_outcome"],
                         "both_hypotheses_match_within_tolerance")
        merge=report["first_minute_opening_merge_hypothesis"]
        self.assertTrue(merge["all_240_all_six_fields_match_after_merge"])
        self.assertFalse(report["eligible_for_automatic_production_union"])

    def test_nonzero_opening_contributes_only_if_included(self):
        report=self.examine(synthetic_pq(opening_volume=7.,opening_amount=70.))
        e=report["opening_bar_diagnostics"]
        self.assertEqual(e["aggregation_hypothesis_outcome"],
                         "opening_inclusion_better_matches_5min")
        self.assertTrue(e["opening_changes_first_5min_by_field"]["volume"])
        self.assertTrue(e["opening_changes_first_5min_by_field"]["amount"])
        self.assertEqual(report["parquet_first_five_minute_without_opening"][
            "volume"]["within_diagnostic_tolerance"],0)
        self.assertEqual(report["parquet_first_five_minute_with_opening"][
            "volume"]["within_diagnostic_tolerance"],1)
        self.assertTrue(report[
            "first_0930_key_never_synthesized_or_dropped_for_production"])

    def test_realistic_0930_and_0931_merge_matches_native_first_bar(self):
        # Synthetic opening observation contains real nonzero turnover and
        # different opening price. Native's FIRST 09:31 record represents
        # the aggregation of this opening observation with regular 09:31.
        rows=synthetic_pq(opening_volume=7.,opening_amount=70.)
        rows["1min"][0].update({
            "open":9.9,"high":9.9,"low":9.9,"close":9.9})
        rows["5min"][0]["open"]=9.9
        minutes=M.probe.time_profiles("1min")["1min_end_240"]
        self.tdx.write_bytes(b"".join(
            minute_bytes(t,volume=9,amount=90.,opening=9.9)
            if index==0 else minute_bytes(t)
            for index,t in enumerate(minutes)))
        report=self.examine(rows)
        diagnostic=report["first_minute_opening_merge_hypothesis"]
        self.assertFalse(
            M._within_all(diagnostic[
                "native_0931_vs_parquet_0931_without_opening"]))
        self.assertTrue(
            diagnostic["first_minute_all_six_fields_match_after_merge"])
        self.assertTrue(diagnostic["remaining_239_all_six_fields_match"])
        self.assertTrue(diagnostic["all_240_all_six_fields_match_after_merge"])
        for metrics in diagnostic[
                "all_240_native_vs_first_merged_plus_remaining_239"].values():
            self.assertEqual(metrics["n"],240)
            self.assertEqual(metrics["within_diagnostic_tolerance"],240)
        self.assertTrue(diagnostic[
            "opening_merge_is_only_a_hypothesis_not_a_mapping_rule"])
        self.assertFalse(report["eligible_for_automatic_production_union"])

    def test_opening_merge_is_rejected_when_first_native_bar_does_not_contain_it(self):
        # Opening Parquet record is nonzero but synthetic native 09:31
        # still only contains the regular minute: flag, never auto-merge.
        report=self.examine(
            synthetic_pq(opening_volume=7.,opening_amount=70.))
        diagnostic=report["first_minute_opening_merge_hypothesis"]
        self.assertFalse(
            diagnostic["first_minute_all_six_fields_match_after_merge"])
        self.assertTrue(diagnostic["remaining_239_all_six_fields_match"])
        self.assertFalse(diagnostic[
            "all_240_all_six_fields_match_after_merge"])
        first=diagnostic[
            "native_0931_vs_aggregation_of_parquet_0930_and_0931"]
        self.assertEqual(first["volume"]["within_diagnostic_tolerance"],0)
        self.assertEqual(first["amount"]["within_diagnostic_tolerance"],0)

    def test_100x_shared_minute_volume_surfaces_as_ratio(self):
        report=self.examine(synthetic_pq(shared_volume=200.))
        result=report["common_240_minutes_tdx_vs_parquet"]["volume"]
        self.assertEqual(result["within_diagnostic_tolerance"],0)
        self.assertEqual(result["ratio_actual_over_reference_median"],100.)

    def test_incomplete_missing_opening_or_duplicate_minute_fails(self):
        one=synthetic_pq()
        one["1min"].pop(0)
        with self.assertRaisesRegex(ValueError,"exactly 241"):
            self.examine(one)
        duplicate=synthetic_pq()
        duplicate["1min"][2]["source_beijing_time"]=duplicate[
            "1min"][1]["source_beijing_time"]
        with self.assertRaisesRegex(ValueError,"unexpected time grid"):
            self.examine(duplicate)

    def test_bad_five_minute_grid_fails_without_backfill(self):
        wrong=synthetic_pq()
        wrong["5min"].pop()
        with self.assertRaisesRegex(ValueError,"exactly 48"):
            self.examine(wrong)
        wrong2=synthetic_pq()
        wrong2["5min"][0]["source_beijing_time"]=DAY+" 09:35"
        with self.assertRaisesRegex(ValueError,"unexpected time grid"):
            self.examine(wrong2)

    def test_source_missing_minute_or_bad_price_fails_closed(self):
        self.tdx.write_bytes(self.tdx.read_bytes()[:-32])
        with self.assertRaisesRegex(ValueError,"240 ending-minute keys"):
            self.examine()
        self.tdx.write_bytes(b"".join(
            minute_bytes(t) for t in
            M.probe.time_profiles("1min")["1min_end_240"]))
        malformed=synthetic_pq()
        malformed["1min"][1]["high"]=1.
        with self.assertRaisesRegex(ValueError,"Invalid purchased OHLCVA"):
            self.examine(malformed)

    def test_bounded_parquet_query_no_cache_and_manifest_guard(self):
        file=self.root/"AllCycleAStockData"/"1min"/"2026-09.parquet"
        file.write_bytes(b"synthetic fake source")
        stat=file.stat()
        manifest=[{"relative_path":"AllCycleAStockData/1min/2026-09.parquet",
                   "size_bytes":stat.st_size,"mtime_ns":stat.st_mtime_ns}]
        rows=synthetic_pq()
        def stub(_root,_symbol,period,_from,_to,**kwargs):
            self.assertFalse(kwargs["local_cache"])
            self.assertEqual(kwargs["max_result_bars"],
                             242 if period=="1min" else 49)
            return {
                "bars":rows[period],
                "safe_summary":{
                    "symbol":SYMBOL,"period":period,"from_date":DAY,
                    "to_date":DAY,"local_cache_used":False,
                    "no_h5_read":True,
                    "source_file_stat_provenance":manifest,
                    "candidate_source_rows_upper_bound":500,
                    "matching_bar_count":len(rows[period]),
                }}
        with mock.patch.object(M.parquet,"query_bars",side_effect=stub):
            data,src=M._purchased(self.root,SYMBOL,DAY,1000)
        self.assertEqual(len(data["1min"]),241)
        self.assertTrue(src["1min"][
            "source_manifest_is_stat_only_not_content_authenticated"])
        file.write_bytes(b"changed!")
        with mock.patch.object(M.parquet,"query_bars",side_effect=stub),self.assertRaisesRegex(
                ValueError,"source stat changed"):
            M._purchased(self.root,SYMBOL,DAY,1000)

    def test_cli_writes_safe_json_and_refuses_overwrite(self):
        evidence=synthetic_pq()
        args=["--parquet-root",str(self.root),
              "--tdx-1min-file",str(self.tdx),
              "--symbol",SYMBOL,"--date",DAY,"--read-only",
              "--out","reports/tdx-pq-minute-opening-synthetic.json"]
        with mock.patch.object(M,"_purchased",
                return_value=(evidence,{"1min":{},"5min":{}})):
            with redirect_stdout(StringIO()):
                M.main(args)
            saved=self.reports/"tdx-pq-minute-opening-synthetic.json"
            report=json.loads(saved.read_text())
            self.assertTrue(report["no_raw_ohlcva_or_individual_times_in_report"])
            self.assertFalse(report["private_cache_enabled"])
            payload=saved.read_text()
            for marker in ('"bars"','"open": 10.0',
                           '"volume": 2.0','"source_beijing_time"'):
                self.assertNotIn(marker,payload)
            with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
                M.main(args)
        self.assertFalse((self.mod/"work").exists())


if __name__=="__main__":
    unittest.main()
