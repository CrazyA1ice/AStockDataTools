"""Synthetic Arrow predicate vs existing ParquetFile scan; no paid market bars."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest import mock

SCRIPT=(Path(__file__).resolve().parents[1]/"tools"/
        "benchmark-parquet-arrow-filter-cold.py")
SPEC=importlib.util.spec_from_file_location(
    "parquet_cold_arrow_benchmark_test_module",SCRIPT)
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
TZ=timezone(timedelta(hours=8))


def epoch(stamp):
    return int(datetime.strptime(stamp,"%Y-%m-%d %H:%M").replace(
        tzinfo=TZ).timestamp()*1000)


class ParquetArrowColdQueryBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"stock"
        (self.root/"AllCycleAStockData").mkdir(parents=True)

    def write(self,period,name,rows,group=2):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
            import pyarrow.dataset
        except ImportError:
            self.skipTest("pyarrow.dataset unavailable")
        path=self.root/"AllCycleAStockData"/period/name
        path.parent.mkdir(parents=True,exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows),
                       str(path),row_group_size=group)
        return path

    def bar(self,stamp,sym="600000.XSHG",p=10):
        return {
            "ts":epoch(stamp),"symbol":sym,"open":float(p),
            "high":float(p)+1,"low":float(p)-1,"close":float(p)+.5,
            "volume":float(p)*2,"amount":float(p)*20,
        }

    def test_two_engines_exact_six_fields_and_rowgroup_provenance(self):
        self.write("5min","2026-09.parquet",[
            self.bar("2026-09-29 09:30"),
            self.bar("2026-09-30 09:30"),
            self.bar("2026-09-30 09:30","000001.XSHE"),
            self.bar("2026-09-30 09:35",p=11),
            self.bar("2026-09-30 14:55",p=12),
        ],group=2)
        report=M.benchmark(self.root,"SH600000","5min",
                           "2026-09-30","2026-09-30")
        self.assertEqual(report["matching_bar_count"],3)
        self.assertTrue(report[
            "query_output_all_values_times_and_source_provenance_identical"])
        self.assertEqual(report["baseline_existing_rowgroup"][
            "source_rows_delivered_to_python_before_filter"],5)
        self.assertEqual(report["experimental_arrow_filtered"][
            "arrow_rows_emitted_after_predicate"],3)
        self.assertEqual(report["candidate_row_groups"],3)
        self.assertTrue(report["arrow_output_rows_are_not_number_of_physical_rows_read"])
        self.assertTrue(report["experimental_arrow_filtered"][
            "actual_parquet_rows_decoded_unknown"])
        self.assertFalse(report["raw_ohlcva_exported"])

    def test_arrow_first_order_does_not_change_source_results(self):
        self.write("1min","2026-09.parquet",[
            self.bar("2026-09-30 09:30"),
            self.bar("2026-09-30 09:31",p=11)])
        report=M.benchmark(self.root,"SH600000","1min",
                           "2026-09-30","2026-09-30",
                           order="arrow-first")
        self.assertEqual(report["matching_bar_count"],2)
        self.assertEqual(report["requested_execution_order"],"arrow-first")
        self.assertGreaterEqual(report["baseline_existing_rowgroup"][
            "elapsed_seconds"],0)
        self.assertGreaterEqual(report["experimental_arrow_filtered"][
            "elapsed_seconds"],0)

    def test_data_empty_returns_matching_empty_and_no_ohlcva(self):
        self.write("day","2026-09.parquet",[
            self.bar("2026-09-30 08:00",sym="000001.XSHE")])
        report=M.benchmark(self.root,"SH600000","day",
                           "2026-09-30","2026-09-30")
        self.assertEqual(report["matching_bar_count"],0)
        self.assertTrue(report[
            "query_output_all_values_times_and_source_provenance_identical"])
        self.assertEqual(report["experimental_arrow_filtered"][
            "arrow_rows_emitted_after_predicate"],0)
        self.assertEqual(report["candidate_source_rows_upper_bound"],1)
        wire=json.dumps(report)
        for text in ('"open": 10', '"volume": 20', '"amount": 200'):
            self.assertNotIn(text,wire)
        self.assertTrue(report["only_safe_aggregate_metadata_exported"])

    def test_two_engines_reject_duplicate_target_time_key(self):
        self.write("day","2026-09.parquet",[
            self.bar("2026-09-30 08:00"),
            self.bar("2026-09-30 08:00",p=11)],group=1)
        with self.assertRaisesRegex(ValueError,"Duplicate selected"):
            M.arrow_filtered_query(self.root,"SH600000","day",
                                   "2026-09-30","2026-09-30")
        with self.assertRaisesRegex(ValueError,"Duplicate source timestamp"):
            M.query.query_bars(self.root,"SH600000","day",
                                "2026-09-30","2026-09-30")

    def test_budget_refuses_both_engines_before_paid_values(self):
        self.write("5min","2026-09.parquet",[
            self.bar("2026-09-30 09:30"),
            self.bar("2026-09-30 09:35")],group=2)
        with self.assertRaisesRegex(ValueError,
                                    "exceeds --max-candidate-rows"):
            M.arrow_filtered_query(self.root,"SH600000","5min",
                                   "2026-09-30","2026-09-30",
                                   max_candidate_rows=1)
        with self.assertRaisesRegex(ValueError,
                                    "exceeds --max-candidate-rows"):
            M.benchmark(self.root,"SH600000","5min",
                        "2026-09-30","2026-09-30",
                        max_candidate_rows=1)
        with self.assertRaisesRegex(ValueError,"Selected bar limit exceeded"):
            M.arrow_filtered_query(self.root,"SH600000","5min",
                                   "2026-09-30","2026-09-30",
                                   max_result_bars=1)

    def test_refuse_report_when_any_price_or_provenance_differs(self):
        self.write("day","2026-09.parquet",[
            self.bar("2026-09-30 08:00")])
        original=M.query.query_bars
        def corruption(*args,**kwargs):
            result=original(*args,**kwargs)
            result["bars"][0]["close"]+=1
            return result
        with mock.patch.object(M.query,"query_bars",side_effect=corruption):
            with self.assertRaisesRegex(ValueError,
                                        "Arrow filter differs"):
                M.benchmark(self.root,"SH600000","day",
                            "2026-09-30","2026-09-30")

    def test_invalid_execution_order_fails(self):
        with self.assertRaisesRegex(ValueError,"Invalid order"):
            M.benchmark(self.root,"SH600000","day",
                        "2026-09-30","2026-09-30",order="unknown")


if __name__=="__main__":
    unittest.main()
