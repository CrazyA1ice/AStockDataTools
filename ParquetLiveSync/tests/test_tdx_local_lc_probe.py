"""Zero-dependency, strictly offline .lc1/.lc5 local TDX file format regression tests."""
import importlib.util
from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest
import struct
import json

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "tdx_local_lc_probe",HERE/"tdx_local_lc_probe.py")
T=importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)


def record(day,minute,*,open_=10.0,high=10.2,low=9.9,close=10.1,
           amount=123456.75,volume=1200,reserved=0):
    packed=(day.year-2004)*2048+day.month*100+day.day
    return T.BAR.pack(packed,minute,open_,high,low,close,amount,volume,reserved)


def put(vipdoc,code,period,data):
    path=T.path_for(vipdoc,code,period)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)
    return path


class Tests(unittest.TestCase):
    def test_32_byte_wire_endian_date_price_amount_and_raw_shares(self):
        day=date(2026,10,16)
        raw=record(day,571,volume=10000,amount=880000.5)
        self.assertEqual(len(raw),32)
        d,m,fields=T.decode_record(raw)
        self.assertEqual(d,day)
        self.assertEqual(m,571)
        self.assertAlmostEqual(fields["high"],10.2,places=5)
        self.assertEqual(fields["volume_raw"],10000)
        self.assertAlmostEqual(fields["amount"],880000.5,places=2)
        self.assertEqual(fields["reserved"],0)
        self.assertEqual(T.BAR.format,"<HHfffffII")

    def test_sh_sz_fzline_minline_paths_and_index(self):
        root=Path("D:/software/TDX/vipdoc")
        self.assertEqual(T.path_for(root,"600000.SH",1),
            root/"sh"/"minline"/"sh600000.lc1")
        self.assertEqual(T.path_for(root,"SZ000001",5),
            root/"sz"/"fzline"/"sz000001.lc5")
        self.assertEqual(T.path_for(root,"000001.SH",5),
            root/"sh"/"fzline"/"sh000001.lc5")
        self.assertEqual(T.path_for(root,"688001.SH",1),
            root/"sh"/"minline"/"sh688001.lc1")
        with self.assertRaises(ValueError):
            T.path_for(root,"../../evil",1)

    def test_240_regular_1min_vs_48_regular_5min_label_grid(self):
        day=date(2026,10,16)
        minutes=(list(range(571,691))+list(range(781,901)))
        self.assertEqual(len(minutes),240)
        minutes5=(list(range(575,691,5))+list(range(785,901,5)))
        self.assertEqual(len(minutes5),48)
        with tempfile.TemporaryDirectory() as tmp:
            one=put(tmp,"688001.SH",1,b"".join(
                record(day,m,volume=10000) for m in minutes))
            five=put(tmp,"688001.SH",5,b"".join(
                record(day,m,volume=10000) for m in minutes5))
            s1=T.scan_file(one,period=1)
            s5=T.scan_file(five,period=5)
            self.assertEqual(s1["status"],"VALID")
            self.assertEqual(s1["trading_days"],1)
            self.assertEqual(s1["day_bar_count_distribution"],{"240":1})
            self.assertEqual(s1["requested_days"][str(day)]["first"],"09:31")
            self.assertEqual(s1["requested_days"][str(day)]["last"],"15:00")
            self.assertEqual(s1["requested_days"][str(day)]["bars"],240)
            self.assertTrue(s1["requested_days"][str(day)]["opening_slot_presence"]["09:31"]["record_present"])
            self.assertEqual(s5["day_bar_count_distribution"],{"48":1})
            self.assertEqual(s5["requested_days"][str(day)]["first"],"09:35")
            self.assertEqual(s5["requested_days"][str(day)]["last"],"15:00")
            self.assertNotIn("09:31",s5["requested_days"][str(day)]["opening_slot_presence"])
            self.assertNotEqual(s1["sha256"],s5["sha256"])

    def test_damaged_file_rejected_read_only_no_output(self):
        d=date(2026,10,15)
        with tempfile.TemporaryDirectory() as tmp:
            bad=put(tmp,"600000.SH",1,record(d,571)+b"broken")
            self.assertEqual(T.scan_file(bad,period=1)["status"],"INVALID_32BYTE_LENGTH")
            bad.write_bytes(record(d,571)+record(d,571))
            duplicate=T.scan_file(bad,period=1)
            self.assertEqual(duplicate["status"],"REVIEW_CORRUPT_OR_NONMONOTONIC")
            self.assertEqual(duplicate["duplicate_stamps"],1)
            bad.write_bytes(record(d,571)+record(d,570))
            self.assertEqual(T.scan_file(bad,period=1)["decreasing_timestamp_pairs"],1)
            bad.write_bytes(record(d,571,high=9.0,low=10.0))
            self.assertEqual(T.scan_file(bad,period=1)["invalid_records"],1)
            self.assertEqual(T.scan_file(bad,period=1)["status"],
                             "REVIEW_CORRUPT_OR_NONMONOTONIC")

    def test_empty_missing_and_symlink_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=T.path_for(tmp,"000001.SZ",5)
            self.assertEqual(T.scan_file(p,period=5)["status"],"NOT_FOUND")
            p.parent.mkdir(parents=True)
            p.touch()
            self.assertEqual(T.scan_file(p,period=5)["status"],"INVALID_32BYTE_LENGTH")
            target=p.with_name("other.lc5")
            target.write_bytes(record(date(2026,10,14),575))
            p.unlink()
            try:
                p.symlink_to(target)
            except (OSError,NotImplementedError):
                return
            self.assertEqual(T.scan_file(p,period=5)["status"],"REJECT_SYMLINK")

    def test_inventory_handles_missing_lc1_and_only_lc5_without_failure(self):
        day=date(2026,10,16)
        with tempfile.TemporaryDirectory() as tmp:
            put(tmp,"000001.SH",5,record(day,575))
            logs=[]
            summary=T.run(vipdoc=tmp,logger=logs.append)
            self.assertEqual(summary["period_file_present_counts"],
                             {"1min":0,"5min":1})
            self.assertTrue(summary["no_network_requests"])
            self.assertTrue(summary["no_output_files_written"])
            parsed=[json.loads(line.split("=",1)[1]) for line in logs if
                    line.startswith("TDX_LOCAL_BAR_FILE=")]
            self.assertEqual(len(parsed),8)
            self.assertEqual(sum(1 for x in parsed if x["status"]=="VALID"),1)
            self.assertFalse(list(Path(tmp).rglob("*.json")))

    def test_no_volume_unit_normalization_for_index_or_stock(self):
        day=date(2026,10,16)
        for code in ("000001.SH","600000.SH"):
            with self.subTest(code=code),tempfile.TemporaryDirectory() as tmp:
                f=put(tmp,code,5,record(day,575,volume=10000))
                s=T.scan_file(f,period=5)
                self.assertEqual(s["raw_volume_unit"],"stock_shares_likely_index_differs")
                self.assertTrue(s["source_values_modified"] is False)
                self.assertEqual(s["records"],1)

if __name__=="__main__":
    unittest.main()
