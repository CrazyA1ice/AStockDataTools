"""Synthetic-only tests of bounded, source-read-only common TDX binary probe."""
import hashlib
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
    "native_tdx_readonly_probe_test",TOOLS/"probe-tdx-native-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def day_bar(day=20261027,open_cents=1000,high_cents=1100,
            low_cents=900,close_cents=1050):
    return struct.pack("<IIIIIfII",day,open_cents,high_cents,
                       low_cents,close_cents,1025.0,100,0)


def minute_bar(day="2026-10-27",minute=570,open_value=10.0,
               high_value=11.0,low_value=9.0,close_value=10.5):
    y,m,d=(int(v) for v in day.split("-"))
    packed=(y-2004)*2048+m*100+d
    return struct.pack("<HHfffffII",packed,minute,open_value,
                       high_value,low_value,close_value,1025.0,100,0)


class NativeTdxReadOnlyTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home=Path(temp.name)/"H5ParquetReconciler"
        self.home.mkdir()
        self.reports=self.home/"reports"
        self.reports.mkdir()
        for key,value in (("MODULE",self.home),("REPORTS",self.reports.resolve())):
            p=mock.patch.object(M,key,value)
            p.start()
            self.addCleanup(p.stop)

    def put(self,name,blob):
        file=self.home/name
        file.write_bytes(blob)
        return file

    def test_day_layout_decoding_order_and_real_content_checksum(self):
        data=day_bar(20261026)+day_bar(20261027)
        src=self.put("sh600000.day",data)
        audit=M.inspect(src,"SH600000","2026-10-27")
        self.assertEqual(audit["source_total_records"],2)
        self.assertEqual(audit["requested_date_source_records"],1)
        self.assertEqual(audit["source_content_sha256"],
                         hashlib.sha256(data).hexdigest())
        self.assertEqual(audit["source_first_date"],"2026-10-26")
        self.assertEqual(audit["source_last_date"],"2026-10-27")
        self.assertEqual(audit["time_grid_classification"],"single_daily_record")
        self.assertEqual(audit["time_grid_verdict"],"recognized_native_time_grid")
        self.assertFalse(audit["raw_ohlcva_or_intraday_time_keys_in_report"])
        self.assertFalse(audit["source_market_file_modified"])
        self.assertFalse(audit["automatic_normalization_or_staging_performed"])
        self.assertEqual(src.read_bytes(),data)

    def test_classify_5min_start_and_end_profiles_without_rescaling(self):
        for label in ("5min_start_48","5min_end_48"):
            with self.subTest(label=label):
                values=M.time_profiles("5min")[label]
                blob=b"".join(minute_bar(minute=v) for v in values)
                src=self.put("sz000001.lc5",blob)
                meta=M.inspect(src,"SZ000001","2026-10-27")
                self.assertEqual(meta["requested_date_source_records"],48)
                self.assertEqual(meta["time_grid_classification"],label)
                self.assertEqual(src.read_bytes(),blob)

    def test_classify_three_1min_time_conventions(self):
        for label,count in (("1min_start_240",240),("1min_end_240",240),
                            ("1min_opening_plus_end_241",241)):
            with self.subTest(label=label):
                values=M.time_profiles("1min")[label]
                blob=b"".join(minute_bar(minute=v) for v in values)
                src=self.put("sz300750.lc1",blob)
                meta=M.inspect(src,"SZ300750","2026-10-27")
                self.assertEqual(meta["requested_date_source_records"],count)
                self.assertEqual(meta["time_grid_classification"],label)

    def test_partial_grid_is_reported_not_treated_as_complete(self):
        times=M.time_profiles("5min")["5min_start_48"][:-1]
        src=self.put("sh600000.lc5",
                     b"".join(minute_bar(minute=x) for x in times))
        result=M.inspect(src,"SH600000","2026-10-27")
        self.assertEqual(result["requested_date_source_records"],47)
        self.assertEqual(result["time_grid_verdict"],
                         "unrecognized_or_partial_time_grid")
        self.assertIsNone(result["time_grid_classification"])
        self.assertTrue(result["minute_label_convention_not_assumed_for_staging"])

    def test_zero_keys_do_not_imply_missing_market_data(self):
        src=self.put("sh600000.day",day_bar(20261026))
        result=M.inspect(src,"SH600000","2026-10-27")
        self.assertEqual(result["time_grid_verdict"],
                         "no_records_on_requested_date")
        self.assertEqual(result["requested_date_source_records"],0)

    def test_reject_truncated_duplicate_out_of_order_invalid_ohlc(self):
        sources=(
            ("sh600000.day",day_bar()+b"\x00"),
            ("sh600000.day",day_bar()+day_bar()),
            ("sh600000.day",day_bar(20261027)+day_bar(20261026)),
            ("sh600000.day",day_bar(high_cents=500)),
            ("sh600000.day",day_bar(day=20261339)),
            ("sh600000.lc1",minute_bar(minute=1500)),
            ("sh600000.lc1",minute_bar(high_value=1.0)),
            ("sh600000.lc1",minute_bar(minute=570)+minute_bar(minute=570)),
            ("sh600000.lc5",minute_bar(minute=575)+minute_bar(minute=570)),
        )
        for idx,(name,blob) in enumerate(sources):
            with self.subTest(case=idx):
                src=self.put(name,blob)
                with self.assertRaises(ValueError):
                    M.inspect(src,"SH600000","2026-10-27")

    def test_reject_wrong_name_symbol_bad_date_and_byte_budget(self):
        source=self.put("sh600000.day",day_bar())
        for args in (("SZ600000","2026-10-27",64),
                     ("SH600000","2026-10-30x",64),
                     ("SH600000","2026-10-27",31),
                     ("SH600000","2026-10-27",0),
                     ("SH600000","2026-10-27",M.MAX_SOURCE_BYTES+1)):
            with self.subTest(args=args),self.assertRaises(ValueError):
                M.inspect(source,*args)
        self.put("sh600000.csv",day_bar())
        with self.assertRaisesRegex(ValueError,".day"):
            M.inspect(self.home/"sh600000.csv","SH600000","2026-10-27")
        src=self.put("sh600000.day",b"")
        with self.assertRaisesRegex(ValueError,"Source empty"):
            M.inspect(src,"SH600000","2026-10-27")

    def test_symlink_sources_and_report_escapes_refused(self):
        target=self.put("sh600000.day",day_bar())
        link=self.home/"sz000001.day"
        try:
            link.symlink_to(target)
        except (OSError,NotImplementedError):
            pass
        else:
            with self.assertRaisesRegex(ValueError,"symlink"):
                M.inspect(link,"SZ000001","2026-10-27")
        with self.assertRaisesRegex(ValueError,"NEW JSON"):
            M.safe_out(self.home/"outside.json")
        with self.assertRaisesRegex(ValueError,"NEW JSON"):
            M.safe_out(self.reports/"example.txt")

    def test_cli_report_no_licensed_values_no_overwrite(self):
        source=self.put("sh600000.day",day_bar())
        args=["--source",str(source),"--symbol","SH600000",
              "--date","2026-10-27","--read-only",
              "--out","reports/safe-native-tdx-test.json"]
        with redirect_stdout(StringIO()):
            M.main(args)
        report=self.reports/"safe-native-tdx-test.json"
        content=report.read_text(encoding="utf-8")
        audit=json.loads(content)
        self.assertTrue(audit["source_stable_during_read"])
        self.assertFalse(audit["production_query_modified"])
        self.assertFalse(audit["raw_ohlcva_or_intraday_time_keys_in_report"])
        for key in ("open","close","high","low","volume","amount","bars",
                    "intraday_minutes","raw_timestamp"):
            self.assertNotIn(f'"{key}"',content)
        self.assertFalse((self.home/"work").exists())
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
            M.main(args)
        self.assertEqual(source.read_bytes(),day_bar())


if __name__=="__main__":
    unittest.main()
