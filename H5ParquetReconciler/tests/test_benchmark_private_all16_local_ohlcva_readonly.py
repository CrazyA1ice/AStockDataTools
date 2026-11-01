"""Synthetic SHA-pinned repeated private OHLCVA performance and privacy gates."""
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(label,path):
    spec=importlib.util.spec_from_file_location(label,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BENCH=load("synthetic_all16_repeated_ohlcva_benchmark",
           TOOLS/"benchmark-private-all16-local-ohlcva-readonly.py")
FIXTURE=load("synthetic_all16_repeated_ohlcva_fixtures",
             HERE/"test_query_private_2011_2026_all16_coverage_readonly.py")


class PrivateAll16RepeatedOHLCVABenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.f=FIXTURE.All16PrivateCoverageTests(
            "test_2016_mixed_h5_purchased_query_only_returns_aggregate_counts")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def patched(self):
        stack=contextlib.ExitStack()
        for name,value in (
            ("MODULE",self.f.root),
            ("REPORTS",self.f.reports),
            ("WORK",self.f.work),
            ("ROOT",self.f.years),
        ):
            stack.enter_context(patch.object(BENCH.API.Q.M,name,value))
        return stack

    def run_bench(self,**kwargs):
        args={
            "repeats":3,
            "expected_bars":2,
            "max_candidate_rows":1200000,
            "max_result_bars":31,
        }
        args.update(kwargs)
        with self.patched():
            return BENCH.benchmark(
                self.f.verpath,self.f.saved_sha,"SH600000",
                "2016-08-17","2016-08-18",**args)

    def test_three_actual_synthetic_local_ohlcva_reads_have_same_float64(self):
        before=set(self.f.reports.iterdir())
        result=self.run_bench()
        self.assertEqual(result["sample_count"],3)
        self.assertEqual(result["matched_rows_per_run"],2)
        self.assertEqual(result["by_source_counts_per_run"],{
            "purchased_parquet":1,
            "private_h5_mixed_stockday_candidate":1,
        })
        self.assertTrue(result["full_float64_row_bytes_equal_across_runs_in_memory"])
        self.assertTrue(result["all_runs_reverified_full_selected_partition_sha_and_sqlite"])
        self.assertFalse(result["first_run_os_cache_cold_verified"])
        self.assertEqual(len(result["subsequent_observed_runs_seconds"]),2)
        self.assertEqual(set(self.f.reports.iterdir()),before)
        self.assertFalse(result["ready_for_automatic_market_merge"])
        serialized=json.dumps(result)
        for forbidden in ("SH600000","2016-08-17","1000.0",'"bars"'):
            self.assertNotIn(forbidden,serialized)

    def test_repeated_run_count_and_expected_bar_bounds_fail_before_read(self):
        with self.patched(),patch.object(
                BENCH.API,"read_local_bars",
                side_effect=AssertionError("private source was opened")):
            for n in (0,1,2,8,True):
                with self.subTest(n=n),self.assertRaises(ValueError):
                    BENCH.benchmark(
                        self.f.verpath,self.f.saved_sha,"SH600000",
                        "2016-08-17","2016-08-18",
                        repeats=n,expected_bars=2)
            with self.assertRaisesRegex(ValueError,"Invalid expected"):
                BENCH.benchmark(
                    self.f.verpath,self.f.saved_sha,"SH600000",
                    "2016-08-17","2016-08-18",
                    repeats=3,expected_bars=40)

    def test_mismatched_expected_count_refused_after_first_audited_read(self):
        with self.assertRaisesRegex(ValueError,"count gate"):
            self.run_bench(expected_bars=3)

    def test_one_ohlcva_float_changed_only_in_memory_refuses_repetitions(self):
        native=BENCH.API.read_local_bars
        calls=[0]
        def altering(*args,**kwargs):
            response=native(*args,**kwargs)
            calls[0]+=1
            if calls[0]==2:
                response["bars"][0]["close"]=11.0
            return response
        with patch.object(BENCH.API,"read_local_bars",side_effect=altering):
            with self.assertRaisesRegex(ValueError,"Float64/source"):
                self.run_bench()
        self.assertEqual(calls[0],2)

    def test_private_parquet_change_between_repetitions_refused(self):
        native=BENCH.API.read_local_bars
        calls=[0]
        folder,_,_=self.f.data[2016]
        parquet=folder/"purchased"/"day.parquet"
        def tampered_after_first(*args,**kwargs):
            response=native(*args,**kwargs)
            calls[0]+=1
            if calls[0]==1:
                parquet.write_bytes(parquet.read_bytes()+b"changed-synthetic")
            return response
        with patch.object(BENCH.API,"read_local_bars",
                          side_effect=tampered_after_first):
            with self.assertRaisesRegex(ValueError,"partition bytes differ"):
                self.run_bench()
        self.assertEqual(calls[0],1)

    def test_cli_creates_only_aggregate_safe_after_all_repetitions_pass(self):
        target=self.f.reports/"repeated-safe.json"
        args=[
            "--version-safe",str(self.f.verpath),
            "--version-sha256",self.f.saved_sha,
            "--symbol","SH600000","--start","2016-08-17",
            "--end","2016-08-18","--repeats","3",
            "--expected-bars","2","--max-candidate-rows","1200000",
            "--max-result-bars","31","--out",str(target),
            "--benchmark-local-only",
        ]
        printed=io.StringIO()
        with self.patched(),contextlib.redirect_stdout(printed):
            BENCH.main(args)
        result=json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(result["matched_rows_per_run"],2)
        self.assertEqual(result["sample_count"],3)
        self.assertFalse(result["market_values_or_float64_fingerprint_exported"])
        for prohibited in ("SH600000","2016-08-17",'"bars"', "1000.0"):
            self.assertNotIn(prohibited,target.read_text(encoding="utf-8"))
            self.assertNotIn(prohibited,printed.getvalue())


if __name__=="__main__":
    unittest.main(verbosity=2)
