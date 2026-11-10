"""Synthetic real PyArrow footers, private SHA drift, cutoff and row conservation."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "synthetic_eight_cycle_full_market_physical_footer_census",
    HERE.parent/"tools"/"audit-asof20261013-eight-cycle-parquet-physical-rows-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
UTC8=timezone(timedelta(hours=8))

def fake_parquet(path,day="2026-10-13",symbol="SH600000",count=2):
    path.parent.mkdir(parents=True,exist_ok=True)
    stamp=int(datetime.fromisoformat(day).replace(tzinfo=UTC8).timestamp()*1000)
    values={
        "ts":pa.array([stamp+i*60000 for i in range(count)],type=pa.int64()),
        "symbol":pa.array([symbol]*count),
        **{name:pa.array([1.0]*count,type=pa.float64())
           for name in ("open","high","low","close","volume","amount")}
    }
    pq.write_table(pa.table(values),path,write_statistics=True)
    return path

class EightCyclePhysicalParquetFooterCensus(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base=Path(tmp.name)
        self.market=base/"market"
        self.market.mkdir()
        self.module=base/"H5ParquetReconciler"
        self.module.mkdir()
        self.old_module=M.D.MODULE
        M.D.MODULE=self.module
        self.addCleanup(setattr,M.D,"MODULE",self.old_module)
        self.first=fake_parquet(self.market/"AllCycleAStockData"/"1min"/"2026.parquet")
        st=self.first.stat()
        self.ref=M.D._item(
            "purchased_root",self.first.relative_to(self.market).as_posix(),
            "purchased_original",stat={
                "size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns})
        self.payload={
            "format":M.D.MANIFEST_VERSION,
            "asof_inclusive":"2026-10-13",
            "strict_cutoff_next_day":"2026-10-14",
            "no_purchased_parquet_copy":True,
            "ready_for_production_query":False,
            "period_physical_files":{"1min":[self.ref]},
            "period_purchased_footer_rows_except_day":{"1min":2},
        }

    def test_real_purchased_footer_counts_exact_without_ohlcva_read(self):
        result=M.audit(self.payload,self.market,periods=("1min",))
        entry=result["periods"]["1min"]
        self.assertEqual(entry["physical_rows"],2)
        self.assertEqual(entry["physical_files"],1)
        self.assertEqual(entry["rows_by_registered_source"],
                         {"purchased_original":2})
        self.assertEqual(entry["row_groups"],1)
        self.assertFalse(result["exact_stockday_time_key_coverage_certified"])
        self.assertFalse(result["new_market_or_source_files_written"])

    def test_purchased_original_metadata_change_fails_before_report(self):
        self.first.write_bytes(self.first.read_bytes()+b"tamper")
        with self.assertRaisesRegex(ValueError,"file stat changed"):
            M.audit(self.payload,self.market,periods=("1min",))

    def test_wrong_total_from_original_footer_rejected(self):
        self.payload["period_purchased_footer_rows_except_day"]["1min"]=3
        with self.assertRaisesRegex(ValueError,"purchased source footer"):
            M.audit(self.payload,self.market,periods=("1min",))

    def test_future_2026_oct15_original_fragment_rejected(self):
        self.first.unlink()
        self.first=fake_parquet(self.first,day="2026-10-15")
        st=self.first.stat()
        self.ref["source_stat"]={
            "size_bytes":st.st_size,"mtime_ns":st.st_mtime_ns}
        with self.assertRaisesRegex(ValueError,"extends beyond"):
            M.audit(self.payload,self.market,periods=("1min",))

    def test_private_physical_parquet_source_sha_checked(self):
        private=fake_parquet(
            self.module/"work"/"unified_parquet"/"oct"/"1min.parquet",
            count=3)
        item=M.D._item(
            "private_module",private.relative_to(self.module).as_posix(),
            "h5_only_verified_complete_stockday",sha256=M.D.sha(private),
            rows=3)
        self.payload["period_physical_files"]["1min"].append(item)
        result=M.audit(self.payload,self.market,periods=("1min",))
        self.assertEqual(result["periods"]["1min"]["physical_rows"],5)
        self.assertEqual(result["periods"]["1min"]["rows_by_registered_source"],{
            "purchased_original":2,
            "h5_only_verified_complete_stockday":3})
        private.write_bytes(private.read_bytes()+b"changed")
        with self.assertRaisesRegex(ValueError,"SHA mismatch"):
            M.audit(self.payload,self.market,periods=("1min",))

    def test_research_sources_cannot_join_standard_day_from_1990(self):
        self.ref["source_class"]="historical_1990_2010_h5_uncertified_candidate"
        with self.assertRaisesRegex(ValueError,"Unregistered research-only"):
            M.audit(self.payload,self.market,periods=("1min",))

    def test_future_month_request_is_unnecessary_and_rejected(self):
        self.payload["asof_inclusive"]="2026-10-31"
        with self.assertRaisesRegex(ValueError,"bounded research-only"):
            M.audit(self.payload,self.market,periods=("1min",))

    def test_duplicate_physical_input_fragment_rejected(self):
        self.payload["period_physical_files"]["1min"].append(dict(self.ref))
        with self.assertRaisesRegex(ValueError,"Duplicate physical"):
            M.audit(self.payload,self.market,periods=("1min",))

    def test_full_eight_cycle_missing_historical_tier_refuses_before_market_reads(self):
        # A bounded period may omit 21-year history, but the full eight-period
        # published census MUST fail before scanning any source fragment.
        with patch.object(M,"physical_file_stats",
                          side_effect=AssertionError("unexpected market read")):
            with self.assertRaisesRegex(ValueError,"historical research source registry"):
                M.audit(self.payload,self.market,periods=M.D.PERIODS)

    def test_full_eight_cycle_invalid_historical_source_list_refused(self):
        self.payload["historical_1990_2010_day"]={"historical_files":[]}
        with self.assertRaisesRegex(ValueError,"21-year research layer absent"):
            M.audit(self.payload,self.market,periods=M.D.PERIODS)

    def test_partial_period_ignores_unneeded_historical_source_registry(self):
        self.payload["historical_1990_2010_day"]={"historical_files":"not a list"}
        result=M.audit(self.payload,self.market,periods=("1min",))
        self.assertEqual(result["period_count"],1)
        self.assertEqual(result["separate_historical_1990_2010_unverified_rows"],0)
        self.assertFalse(result["exact_stockday_time_key_coverage_certified"])

    def test_no_unsupported_missing_timestamp_statistics_accepted(self):
        path=self.market/"AllCycleAStockData"/"5min"/"2026.parquet"
        path.parent.mkdir(parents=True,exist_ok=True)
        table=pq.read_table(self.first)
        pq.write_table(table,path,write_statistics=False)
        with self.assertRaisesRegex(ValueError,"Missing exact ts bounds"):
            M.physical_file_stats(path)

if __name__=="__main__":
    unittest.main()
