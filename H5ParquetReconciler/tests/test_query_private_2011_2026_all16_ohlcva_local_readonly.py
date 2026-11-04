"""Synthetic local-memory SHA-bounded real OHLCVA API safety tests.

No licensed market data. All synthetic scratch under H5ParquetReconciler/work.
"""
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
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

API=load("synthetic_private_local_ohlcva_api",
         TOOLS/"query-private-2011-2026-all16-ohlcva-local-readonly.py")
FIXTURE=load("synthetic_private_local_ohlcva_fixtures",
             HERE/"test_query_private_2011_2026_all16_coverage_readonly.py")


class All16LocalRealOHLCVATests(unittest.TestCase):
    def setUp(self):
        self.f=FIXTURE.All16PrivateCoverageTests(
            "test_2016_mixed_h5_purchased_query_only_returns_aggregate_counts")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def patched(self):
        stack=contextlib.ExitStack()
        for key,value in (
            ("MODULE",self.f.root),
            ("REPORTS",self.f.reports),
            ("WORK",self.f.work),
            ("ROOT",self.f.years),
        ):
            stack.enter_context(patch.object(API.Q.M,key,value))
        return stack

    def get(self,start,end,**kwargs):
        opts={
            "allow_private_values":True,
            "max_candidate_rows":1200000,
            "max_result_bars":31,
        }
        opts.update(kwargs)
        with self.patched():
            return API.read_local_bars(
                self.f.verpath,self.f.saved_sha,"SH600000",
                start,end,**opts)

    def test_purchased_and_h5_local_float64_values_exact_with_provenance(self):
        response=self.get("2016-08-17","2016-08-18")
        bars=response["bars"]
        safe=response["safe_summary"]
        self.assertEqual(len(bars),2)
        self.assertEqual([r["trading_date"] for r in bars],
                         ["2016-08-17","2016-08-18"])
        self.assertEqual([r["value_source"] for r in bars],
                         ["purchased_parquet",
                          "private_h5_mixed_stockday_candidate"])
        self.assertTrue(all(r["open"]==10.0 and r["amount"]==1000.0
                            for r in bars))
        self.assertEqual(safe["local_bars_count"],2)
        self.assertTrue(safe["all_original_licensed_OHLCVA_values_read"])
        self.assertFalse(safe["local_licensed_OHLCVA_values_exported_to_safe"])
        self.assertFalse(safe["h5_only_value_units_certified"])
        self.assertFalse(safe["ready_for_h5_mirror"])
        sanitized=json.dumps(safe)
        self.assertNotIn("SH600000",sanitized)
        self.assertNotIn("1000.0",sanitized)
        self.assertNotIn("2016-08-17",sanitized)
        self.assertNotIn('"bars"',sanitized)

    def test_cross_year_local_bars_match_coverage_and_sqlite(self):
        response=self.get("2025-12-31","2026-01-06")
        bars=response["bars"]
        safe=response["safe_summary"]
        self.assertEqual(len(bars),3)
        self.assertEqual([r["trading_date"] for r in bars],
                         ["2025-12-31","2026-01-02","2026-01-05"])
        self.assertEqual(safe["sqlite_rows_matched"],3)
        self.assertEqual(safe["matched_key_rows_vectorized_by_arrow"],3)
        self.assertEqual(safe["sha_checked_private_partitions"],11)
        self.assertEqual(safe["by_source_counts"]["purchased_parquet"],2)
        self.assertEqual(safe["by_source_counts"]["private_h5_whole_date_candidate"],1)

    def test_no_optin_rejected_before_loading_private_source(self):
        with self.patched(),patch.object(API.Q,"version",
                                         side_effect=AssertionError("read forbidden")):
            with self.assertRaisesRegex(ValueError,"explicit opt-in"):
                API.read_local_bars(self.f.verpath,self.f.saved_sha,
                                    "SH600000","2016-08-17","2016-08-18")

    def test_bar_count_limit_refuses_partial_caller_result(self):
        with self.assertRaisesRegex(ValueError,"bounded bar limit"):
            self.get("2016-08-17","2016-08-18",max_result_bars=1)

    def test_wrong_source_version_sha_refuses_before_value_loading(self):
        with self.patched():
            with self.assertRaisesRegex(ValueError,"version SAFE SHA differs"):
                API.read_local_bars(self.f.verpath,"f"*64,
                                    "SH600000","2016-08-17","2016-08-18",
                                    allow_private_values=True)

    def test_modified_private_parquet_sha_refuses_all_local_values(self):
        folder,mf,db=self.f.data[2016]
        parquet=folder/"purchased"/"day.parquet"
        parquet.write_bytes(parquet.read_bytes()+b"changed")
        with self.assertRaisesRegex(ValueError,"partition bytes differ"):
            self.get("2016-08-17","2016-08-18")

    def test_local_cli_only_writes_aggregate_safe_not_real_bars(self):
        report=self.f.reports/"local-value-check.json"
        args=["--version-safe",str(self.f.verpath),
              "--version-sha256",self.f.saved_sha,
              "--symbol","SH600000",
              "--start","2016-08-17",
              "--end","2016-08-18",
              "--max-candidate-rows","1200000",
              "--max-result-bars","31",
              "--out",str(report),"--verify-local-values-only"]
        printed=io.StringIO()
        with self.patched(),contextlib.redirect_stdout(printed):
            API.main(args)
        safe=json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(safe["local_bars_count"],2)
        for prohibited in ("SH600000","2016-08-17",'"bars"','1000.0'):
            self.assertNotIn(prohibited,report.read_text(encoding="utf-8"))
            self.assertNotIn(prohibited,printed.getvalue())
        self.assertFalse(safe["local_licensed_OHLCVA_values_exported_to_safe"])

    def test_local_values_return_in_memory_only_and_no_production_flags(self):
        before=set(self.f.reports.iterdir())
        result=self.get("2016-08-17","2016-08-18")
        self.assertEqual(set(self.f.reports.iterdir()),before)
        self.assertTrue(all(isinstance(r[f],float)
                            for r in result["bars"]
                            for f in API.Q.PHYS.F))
        self.assertFalse(result["safe_summary"]["ready_for_production_query"])
        self.assertFalse(result["safe_summary"]["ready_for_automatic_market_merge"])


if __name__=="__main__":
    unittest.main(verbosity=2)
