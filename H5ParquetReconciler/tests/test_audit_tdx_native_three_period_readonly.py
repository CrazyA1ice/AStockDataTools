"""Synthetic OHLCVA only; no real TDX data or paid bar artifacts."""
import importlib.util
import json
import struct
import tempfile
import unittest
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
from io import StringIO
from unittest import mock

TOOLS=Path(__file__).resolve().parents[1]/"tools"
SPEC=importlib.util.spec_from_file_location(
    "tdx_threep",TOOLS/"audit-tdx-native-three-period-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def minute(t,period="1min",volume=2,amount=20.0,
           open_price=10.,high=11.,low=9.,close=10.):
    packed=(2026-2004)*2048+9*100+30
    return struct.pack("<HHfffffII",packed,t,open_price,high,
                       low,close,amount,volume,0)


def day(volume=480,amount=4800.0,
        open_price=10.,high=11.,low=9.,close=10.):
    return struct.pack("<IIIIIfII",20260930,round(open_price*100),
                       round(high*100),round(low*100),round(close*100),
                       amount,volume,0)


class ThreePeriodTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.mod=Path(temp.name)/"H5ParquetReconciler"
        self.mod.mkdir()
        self.reports=self.mod/"reports"
        self.reports.mkdir()
        for target,key,value in (
                (M,"MODULE",self.mod),(M.probe,"MODULE",self.mod),
                (M.probe,"REPORTS",self.reports.resolve())):
            patch=mock.patch.object(target,key,value)
            patch.start()
            self.addCleanup(patch.stop)
        one_times=M.probe.time_profiles("1min")["1min_end_240"]
        five_times=M.probe.time_profiles("5min")["5min_end_48"]
        self.day_file=self.mod/"sh600000.day"
        self.m1_file=self.mod/"sh600000.lc1"
        self.m5_file=self.mod/"sh600000.lc5"
        self.day_file.write_bytes(day())
        self.m1_file.write_bytes(b"".join(minute(t) for t in one_times))
        self.m5_file.write_bytes(b"".join(
            minute(t,"5min",volume=10,amount=100.) for t in five_times))

    def run_audit(self):
        return M.audit(self.day_file,self.m5_file,self.m1_file,
                       "SH600000","2026-09-30")

    def test_three_period_exact_conservation_and_no_raw_values(self):
        result=self.run_audit()
        self.assertEqual(result["requested_source_records"],
                         {"day":1,"1min":240,"5min":48})
        for comparison in result["comparisons"].values():
            for metrics in comparison.values():
                self.assertEqual(metrics["max_relative_error"],0)
                self.assertEqual(metrics["n"],
                                 metrics["within_diagnostic_tolerance"])
        self.assertFalse(result["eligible_for_automatic_production_union"])
        serialized=json.dumps(result)
        for term in ('"bars"','"individual_intraday_times"',
                     '"source_absolute_path"','"open_price"'):
            self.assertNotIn(term,serialized)

    def test_volume_unit_ratio_diagnostics_do_not_auto_fix(self):
        times=M.probe.time_profiles("5min")["5min_end_48"]
        self.m5_file.write_bytes(b"".join(
            minute(t,"5min",volume=1000,amount=100.) for t in times))
        result=self.run_audit()
        metrics=result["comparisons"][
            "one_minute_aggregate_vs_five_minute_native"]
        self.assertEqual(
            metrics["volume"]["ratio_actual_over_reference_median"],100)
        self.assertEqual(metrics["volume"]["within_diagnostic_tolerance"],0)
        self.assertEqual(metrics["amount"]["within_diagnostic_tolerance"],48)
        self.assertTrue(result["amount_and_volume_units_not_assumed_identical"])

    def test_single_five_minute_close_price_drift_is_detected_not_modified(self):
        times=M.probe.time_profiles("5min")["5min_end_48"]
        self.m5_file.write_bytes(b"".join(
            minute(t,"5min",volume=10,amount=100.,
                   close=10.25 if i==0 else 10.)
            for i,t in enumerate(times)))
        result=self.run_audit()
        metrics=result["comparisons"][
            "one_minute_aggregate_vs_five_minute_native"]["close"]
        self.assertEqual(metrics["within_diagnostic_tolerance"],47)
        self.assertGreater(metrics["max_relative_error"],0)
        self.assertTrue(
            result["numeric_tolerances_are_diagnostic_not_source_certification"])

    def test_bad_241_minute_grid_fails_closed(self):
        self.m1_file.write_bytes(minute(570)+self.m1_file.read_bytes())
        with self.assertRaisesRegex(ValueError,"complete 1min_end_240"):
            self.run_audit()

    def test_reject_missing_date_bad_period_or_modified_byte(self):
        self.m1_file.write_bytes(self.m1_file.read_bytes()[:-32])
        with self.assertRaisesRegex(ValueError,"complete 1min_end_240"):
            self.run_audit()
        self.m1_file.write_bytes(b"".join(
            minute(t) for t in M.probe.time_profiles("1min")["1min_end_240"]))
        with self.assertRaisesRegex(ValueError,"Wrong native source period"):
            M.audit(self.day_file,self.m1_file,self.m5_file,
                    "SH600000","2026-09-30")

    def test_detect_source_hash_changed_between_probe_and_read(self):
        previous=M.probe.inspect(
            self.m5_file,"SH600000","2026-09-30")
        raw=self.m5_file.read_bytes()
        self.m5_file.write_bytes(raw[:-32]+minute(
            900,"5min",volume=100,amount=100))
        with self.assertRaisesRegex(ValueError,"source hash mismatch"):
            M._read_day_values(
                self.m5_file,"5min",M.probe._date("2026-09-30","5min"),
                previous,M.probe.MAX_SOURCE_BYTES)

    def test_cli_summary_is_local_only_and_no_overwrite(self):
        args=["--day-file",str(self.day_file),
              "--minute5-file",str(self.m5_file),
              "--minute1-file",str(self.m1_file),
              "--symbol","SH600000","--date","2026-09-30",
              "--read-only","--out","reports/tdx-cross-period-safe.json"]
        with redirect_stdout(StringIO()):
            M.main(args)
        report=self.reports/"tdx-cross-period-safe.json"
        self.assertTrue(report.exists())
        self.assertFalse((self.mod/"work").exists())
        output=report.read_text()
        self.assertIn("eligible_for_automatic_production_union",output)
        self.assertNotIn('"amount": 4800',output)
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
            M.main(args)


if __name__=="__main__":
    unittest.main()
