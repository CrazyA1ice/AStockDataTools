"""Fictional Parquet-only checks for int64 footer-stat timebase hypotheses."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "parquet_date_timebase_under_test",
    HERE.parent/"tools"/"audit-parquet-int64-footer-timebase-readonly.py")
T=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T)


def fake_stamp(day,hour=9,minute=30):
    return int(datetime(2026,9,day,hour,minute,
                        tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)


class DateFooterTimebaseTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.pa=pa
        self.pq=pq
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"fake_purchased_source"
        self.root.mkdir()
        self.files={}
        for period in T.PERIODS:
            folder=self.root/period
            folder.mkdir()
            self.files[period]=folder/"2026-09.parquet"
        self.reports=Path(self.tmp.name)/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        self.previous=self.reports/"3period-footer-v2.json"
        self.output=self.reports/"date-timebase-v1.json"
        p=patch.object(T.AUDIT,"REPORTS",self.reports)
        p.start();self.addCleanup(p.stop)

    def write_fictional_source(self,mode="epoch_ms",statistics=True):
        if mode=="epoch_ms":
            values=[fake_stamp(d) for d in (1,2,29,30)]
        elif mode=="epoch_s":
            values=[fake_stamp(d)//1000 for d in (1,2,29,30)]
        elif mode=="calendar":
            values=[int(f"202609{d:02d}0930") for d in (1,2,29,30)]
        else:
            raise AssertionError("unsupported fake mode")
        t=self.pa.table({
            "datetime":self.pa.array(values,type=self.pa.int64()),
            "open":self.pa.array([1.,2.,3.,4.]),
            "high":self.pa.array([2.,3.,4.,5.]),
            "low":self.pa.array([1.,1.,2.,3.]),
            "close":self.pa.array([1.,2.,3.,4.]),
            "volume":self.pa.array([10.,20.,30.,40.]),
            "amount":self.pa.array([12.,20.,30.,40.]),
        })
        for filename in self.files.values():
            self.pq.write_table(t,filename,row_group_size=2,
                                write_statistics=statistics)
        self.make_prior()

    def make_prior(self):
        details={}
        for period,filename in self.files.items():
            x=T.PREVIOUS.inspect_footer(filename,period,self.pq,self.pa)
            self.assertEqual(x["date_arrow_storage_family"],"int64")
            details[period]=x
        self.previous.write_text(json.dumps({
            "format":T.PREVIOUS.FORMAT,
            "periods":details,
            "footer_only_no_row_data_loaded":True,
            "sources_read_only":True,
            "ready_for_full_market_mirror":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "amount_physical_unit_certified":False,
            "volume_physical_unit_certified":False,
        }),encoding="utf-8")

    def run_it(self):
        return T.run(self.root,"day/2026-09.parquet",
                     "5min/2026-09.parquet","1min/2026-09.parquet",
                     self.previous,self.output)

    def test_native_synthetic_epoch_ms_footer_evidence_all_three_periods(self):
        self.write_fictional_source()
        with patch.object(self.pq,"read_table",
                          side_effect=AssertionError("no reading rows")):
            safe=self.run_it()
        self.assertTrue(safe["all_three_periods_unique_epoch_ms_footer_candidate"])
        self.assertFalse(safe["date_raw_calendar_encoding_certified"])
        self.assertFalse(safe["date_time_label_semantics_certified"])
        self.assertFalse(safe["licensed_parquet_to_h5_mapping_certified"])
        self.assertFalse(safe["ready_for_full_market_mirror"])
        self.assertTrue(safe["footer_only_no_market_rows_loaded"])
        for record in safe["periods"].values():
            self.assertEqual(record["nonempty_row_groups_with_valid_int64_minmax"],2)
            self.assertEqual(record["nonempty_row_groups_without_valid_minmax"],0)
            self.assertEqual(record["candidate_timebases_matching_all_observed_bounds"],
                             ["epoch_ms"])
            self.assertEqual(record["candidate_matching_row_groups"]["epoch_ms"],2)
            self.assertEqual(record["candidate_matching_row_groups"]["epoch_s"],0)
        out=self.output.read_text(encoding="utf-8")
        for private in ("fake_purchased_source","2026-09.parquet",
                        str(fake_stamp(1)),"D:/","stock.db"):
            self.assertNotIn(private,out)

    def test_epoch_seconds_is_not_misclassified_as_epoch_ms(self):
        self.write_fictional_source(mode="epoch_s")
        safe=self.run_it()
        self.assertFalse(safe["all_three_periods_unique_epoch_ms_footer_candidate"])
        for record in safe["periods"].values():
            self.assertEqual(record["candidate_timebases_matching_all_observed_bounds"],
                             ["epoch_s"])
            self.assertFalse(record["date_raw_calendar_encoding_certified"])

    def test_integer_calendar_yyyymmddhhmm_is_only_a_candidate(self):
        self.write_fictional_source(mode="calendar")
        safe=self.run_it()
        for record in safe["periods"].values():
            self.assertEqual(record["candidate_timebases_matching_all_observed_bounds"],
                             ["calendar_yyyymmddhhmm"])
        self.assertFalse(safe["all_three_periods_unique_epoch_ms_footer_candidate"])
        self.assertFalse(safe["date_raw_calendar_encoding_certified"])

    def test_stats_absent_cannot_be_certified(self):
        self.write_fictional_source(statistics=False)
        safe=self.run_it()
        self.assertFalse(safe["all_three_periods_unique_epoch_ms_footer_candidate"])
        for record in safe["periods"].values():
            self.assertEqual(record["nonempty_row_groups_with_valid_int64_minmax"],0)
            self.assertEqual(record["nonempty_row_groups_without_valid_minmax"],2)
            self.assertFalse(record["full_nonempty_row_group_minmax_coverage"])

    def test_changed_file_size_or_footer_is_rejected(self):
        self.write_fictional_source()
        file=self.files["day"]
        original=file.read_bytes()
        # Preserve PAR1 trailer but make the source length differ from v2.
        file.write_bytes(original[:-8]+b"stat-changed"+original[-8:])
        with self.assertRaisesRegex(ValueError,"differs"):
            self.run_it()
        self.assertFalse(self.output.exists())

    def test_tampered_prior_date_family_and_false_status_rejected(self):
        self.write_fictional_source()
        doc=json.loads(self.previous.read_text(encoding="utf-8"))
        scenarios=[
            lambda r:r["periods"]["day"].update(
                {"date_arrow_storage_family":"unknown"}),
            lambda r:r.update({"ready_for_full_market_mirror":True}),
            lambda r:r["periods"]["1min"].update(
                {"date_raw_calendar_encoding_certified":True}),
            lambda r:r.update({"format":"unsupported"}),
        ]
        for edit in scenarios:
            fake=json.loads(json.dumps(doc))
            edit(fake)
            self.previous.write_text(json.dumps(fake),encoding="utf-8")
            with self.subTest(change=edit):
                with self.assertRaisesRegex(ValueError,"existing|Requires"):
                    self.run_it()
                self.assertFalse(self.output.exists())

    def test_output_must_be_new_and_in_module_reports_only(self):
        self.write_fictional_source()
        self.output.write_text("protected",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            self.run_it()
        self.assertEqual(self.output.read_text(encoding="utf-8"),"protected")
        self.output.unlink()
        external=Path(self.tmp.name)/"outside.json"
        with self.assertRaisesRegex(ValueError,"direct non-symlink"):
            T.run(self.root,"day/2026-09.parquet","5min/2026-09.parquet",
                  "1min/2026-09.parquet",self.previous,external)
        self.assertFalse(external.exists())

    def test_month_mismatch_is_rejected_before_footer_read(self):
        self.write_fictional_source()
        folder=self.root/"5min"
        (folder/"2026-08.parquet").write_bytes(
            (folder/"2026-09.parquet").read_bytes())
        with self.assertRaisesRegex(ValueError,"same named month"):
            T.run(self.root,"day/2026-09.parquet","5min/2026-08.parquet",
                  "1min/2026-09.parquet",self.previous,self.output)
        self.assertFalse(self.output.exists())

    def test_candidate_bounds_invalid_or_unsupported_do_not_crash(self):
        for candidate in T.CANDIDATES:
            with self.subTest(candidate=candidate):
                self.assertIsNone(T._date_candidate_month(-1,candidate))
                self.assertIsNone(T._date_candidate_month(True,candidate))
        self.assertEqual(T._date_candidate_month(fake_stamp(30),"epoch_ms"),
                         "2026-09")
        self.assertNotEqual(T._date_candidate_month(202609300930,"epoch_ms"),"2026-09")
        self.assertEqual(
            T._date_candidate_month(202609300930,
                                    "calendar_yyyymmddhhmm"),"2026-09")

    def test_no_row_read_calls_in_inspector(self):
        import inspect
        source=inspect.getsource(T.inspect_stats)
        call_lines=[line for line in source.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
        self.assertIn("ParquetFile",source)
        self.assertIn("reader.metadata",source)
        self.assertIn("reader.close()",source)
        for name in ("read_row_group(","iter_batches(","read_table(",
                     "read_column(","scanner("):
            self.assertFalse(any(name in line for line in call_lines),
                             "Found forbidden row-read call "+name)


if __name__=="__main__":
    unittest.main(verbosity=2)
