"""Offline fake-Parquet tests; licensed bars never accessed."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "real_day_float64_precision_pilot_under_test",
    HERE.parent/"tools"/"audit-real-parquet-day-float64-h5-tick-candidates.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def stamp(d=30):
    return int(datetime(2026,9,d,8,0,
                        tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)


class BoundedRealDayFloatTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.pa=pa
        self.pq=pq
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"fictional_source"
        self.file=self.root/"day"/"2026-09.parquet"
        self.file.parent.mkdir(parents=True)
        self.reports=Path(self.tmp.name)/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        self.proof=self.reports/"prior-candidate-v1.json"
        self.out=self.reports/"float-pilot-v1.json"
        p=patch.object(M.AUDIT,"REPORTS",self.reports)
        p.start()
        self.addCleanup(p.stop)
        self.write_source()

    def write_source(self,wrong_schema=False,missing=False):
        import pyarrow as pa
        dataset={
            "ts":pa.array([stamp(30),stamp(30)],type=pa.int64()),
            "symbol":pa.array(["600000.XSHG","000001.XSHE"]),
            "open":pa.array([10.125,11.1234]),
            "high":pa.array([10.129,11.1267]),
            "low":pa.array([10.122,11.1200]),
            "close":pa.array([10.124,11.1249]),
            "amount":pa.array([1234.5,999.99]),
            "volume":pa.array([1000.0,99.5]),
        }
        if wrong_schema:
            dataset["volume"]=pa.array([1000,99],type=pa.int64())
        if missing:
            dataset={k:v.slice(0,1) for k,v in dataset.items()}
        table=pa.table(dataset)
        self.pq.write_table(table,self.file)
        rows={period:{
            "period":period,"date_arrow_storage_family":"int64",
            "unique_epoch_ms_candidate_from_footer_only":True,
            "full_nonempty_row_group_minmax_coverage":True,
            "date_raw_calendar_encoding_certified":False,
        } for period in ("day","5min","1min")}
        self.proof.write_text(json.dumps({
            "format":M.PREVIOUS_FORMAT,
            "sample_month":"2026-09",
            "three_periods_int64_date_footer_checked":True,
            "all_three_periods_unique_epoch_ms_footer_candidate":True,
            "date_raw_calendar_encoding_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
            "footer_only_no_market_rows_loaded":True,
            "periods":rows,
        }),encoding="utf-8")

    def run_it(self):
        return M.run(self.root,"day/2026-09.parquet","2026-09-30",
                     self.proof,self.out)

    def test_fictional_real_arrow_day_values_bounded_no_h5_output(self):
        report=self.run_it()
        self.assertEqual(report["sample_security_count"],2)
        self.assertEqual(report["scanned_source_rows_bounded"],2)
        self.assertEqual(report["scanned_row_group_count"],1)
        self.assertEqual(report["field_hypotheses"]["open"]
                         ["shortest_decimal_tick_exact_count"],1)
        self.assertEqual(report["field_hypotheses"]["amount"]
                         ["shortest_decimal_tick_exact_count"],1)
        self.assertEqual(report["field_hypotheses"]["volume"]
                         ["shortest_decimal_tick_exact_count"],1)
        self.assertFalse(report["real_float64_to_h5_precision_mapping_certified"])
        self.assertFalse(report["licensed_parquet_to_h5_mapping_certified"])
        self.assertFalse(report["ready_for_full_market_mirror"])
        self.assertTrue(report["no_native_h5_integer_records_encoded_or_written"])
        output=self.out.read_text(encoding="utf-8")
        for private in ("600000.XSHG","000001.XSHE","10.125","1234.5",
                        "999.99",str(stamp(30)),"fictional_source",
                        "2026-09.parquet"):
            self.assertNotIn(private,output)
        self.assertEqual(sorted(self.file.parent.iterdir()),[self.file])

    def test_native_tick_shortest_decimal_vs_binary_exact_not_same_claim(self):
        x=M.tick_hypothesis(10.1,"open")
        self.assertTrue(x["shortest_decimal_tick_exact"])
        self.assertFalse(x["binary_float_tick_exact"])
        self.assertFalse(x["would_require_rounding"])
        self.assertTrue(M.tick_hypothesis(10.125,"open")
                        ["binary_float_tick_exact"])
        self.assertTrue(M.tick_hypothesis(10.1234,"open")
                        ["would_require_rounding"])

    def test_nonfinite_negative_bool_and_wrong_numeric_type_fail_closed(self):
        for x in (float("nan"),float("inf"),-1.0,True,1,
                  "1.00",None):
            with self.subTest(x=x):
                with self.assertRaises(ValueError):
                    M.tick_hypothesis(x,"open")

    def test_overflow_and_half_tick_indicated_never_written(self):
        self.assertFalse(
            M.tick_hypothesis(float(2**33),"open")["range_ok"])
        result=M.tick_hypothesis(1.0005,"open")
        self.assertTrue(result["half_tick_boundary"])
        self.assertTrue(result["would_require_rounding"])

    def test_missing_symbol_or_duplicate_stock_day_rejected(self):
        self.write_source(missing=True)
        with self.assertRaisesRegex(ValueError,"Cannot safely inspect"):
            self.run_it()
        self.assertFalse(self.out.exists())
        self.write_source()
        table=self.pq.read_table(self.file)
        appended=self.pa.concat_tables([table,table.slice(0,1)])
        self.pq.write_table(appended,self.file)
        with self.assertRaisesRegex(ValueError,"Cannot safely inspect"):
            self.run_it()

    def test_wrong_schema_for_volume_fails_before_summary(self):
        self.write_source(wrong_schema=True)
        with self.assertRaisesRegex(ValueError,"Cannot safely inspect"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_input_prior_timebase_false_fails_closed(self):
        doc=json.loads(self.proof.read_text(encoding="utf-8"))
        doc["all_three_periods_unique_epoch_ms_footer_candidate"]=False
        self.proof.write_text(json.dumps(doc),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Existing epoch_ms"):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_no_output_overwrite_or_export_outside_module(self):
        self.out.write_text("protected",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            self.run_it()
        self.assertEqual(self.out.read_text(encoding="utf-8"),"protected")
        self.out.unlink()
        outside=Path(self.tmp.name)/"unsafe.json"
        with self.assertRaisesRegex(ValueError,"direct non-symlink"):
            M.run(self.root,"day/2026-09.parquet","2026-09-30",
                  self.proof,outside)

    def test_other_month_date_and_file_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"requested month"):
            M.run(self.root,"day/2026-09.parquet","2026-08-24",
                  self.proof,self.out)
        self.assertFalse(self.out.exists())
        for invalid in ("2026-09-31","2026/09/30","2026-09-30T08:00"):
            with self.subTest(date=invalid):
                with self.assertRaises(ValueError):
                    M.run(self.root,"day/2026-09.parquet",invalid,
                          self.proof,self.out)

    def test_fixed_h5_driver_scales_are_hypotheses_without_unit_claim(self):
        self.assertEqual(M.SCALINGS["open"],1000)
        self.assertEqual(M.SCALINGS["amount"],10)
        self.assertEqual(M.SCALINGS["volume"],1)
        report=self.run_it()
        self.assertTrue(report["units_assumed_hikyuu_decoded_not_parquet_verified"])
        self.assertFalse(report["licensed_parquet_physical_units_certified"])
        self.assertFalse(report["source_time_label_semantics_certified"])

    def test_max_day_rows_bounded_before_data_read(self):
        self.write_source()
        with patch.object(M,"MAX_ROWS",1):
            with self.assertRaisesRegex(ValueError,"Cannot safely inspect"):
                self.run_it()
        self.assertFalse(self.out.exists())

    def test_no_h5_writer_imports_and_only_selected_projected_columns(self):
        import inspect
        source=inspect.getsource(M._read_bounded_daily)
        self.assertIn("iter_batches",source)
        self.assertIn("columns=list(NEEDED)",source)
        self.assertIn("batch.filter(mask)",source)
        self.assertIn("pf.close()",source)
        for prohibited in ("h5py","tables.open_file","create_h5",
                           "write_table(","open_file(","read_table("):
            self.assertNotIn(prohibited,source)


if __name__=="__main__":
    unittest.main(verbosity=2)
