"""Two essential file-backed synthetic proofs for purchased/H5 combined minute
Parquet -> REAL native PyTables six-H5 integer write & full readback.
All synthetic only under module work/_union_scratch, no D:/stock access.
"""
import contextlib
import importlib.util
import json
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(tag,path):
    spec=importlib.util.spec_from_file_location(tag,path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M=load("mixed_unified_minute_to_native_h5_synthetic",
       TOOLS/"mirror-real-purchased-first-minute-unified-parquet-to-native-h5.py")
F=load("real_minute_range_fixture_for_native_mirror",
       HERE/"test_run_real_minute_h5_gap_unified_range.py")


class PurchasedAndH5NativeMinuteMirrorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=F.RealMinuteRangePhysicalWrites(
            "test_real_synthetic_range_writes_two_periods_and_resumes_by_sha")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base=self.fixture.base
        self.reports=self.fixture.reports
        self.batch=self.fixture.out
        self.h5_root=self.base/"work"/"h5_mirror"
        self.native_safe=self.reports/"new-real-native-combined-summary.json"
        with self.fixture.patched():
            F.B.process(
                self.base,self.fixture.f.day,self.fixture.f.day,
                self.fixture.parent,self.batch,max_days=1,
                max_purchased_rows=10000,max_h5_rows=10000,
                max_unified_rows=10000)

    def patched(self):
        context=contextlib.ExitStack()
        for obj,field,value in (
            (M,"MODULE",self.base),
            (M,"REPORTS",self.reports),
            (M,"DEST_ROOT",self.h5_root),
        ):
            context.enter_context(patch.object(obj,field,value))
        return context

    def test_actual_purchased_and_h5_minute_parquet_both_mirrored(self):
        import tables
        with self.patched():
            result=M.stage(self.batch,None,"123456789abc",self.native_safe,
                           max_total_rows=10000)
        self.assertEqual(result["native_bar_counts"],{"1min":241,"5min":49})
        self.assertEqual(result["source_class_row_counts"],{
            "1min":{"purchased_parquet":1,"h5_only_complete_stockday":240},
            "5min":{"purchased_parquet":1,"h5_only_complete_stockday":48}})
        self.assertEqual(len(result["native_h5_files_sha256"]),6)
        self.assertTrue(result["native_40byte_pytables_integer_full_readback_verified"])
        self.assertFalse(result["complete_minute_history_mirrored"])
        self.assertFalse(result["original_purchased_parquet_or_original_h5_modified"])
        with tables.open_file(str(self.h5_root/"minute_union_123456789abc"/"sz_1min.h5"),"r") as source:
            table=source.get_node("/data/SZ000001")
            self.assertEqual(table.nrows,1)
            self.assertEqual(table.dtype.itemsize,40)
            rec=table.read()[0]
            # Purchased 1min 09:30 is an independent opening label,
            # not 09:31 (which might already hold a different bar).
            self.assertEqual(int(rec["datetime"]),202610130930)
            self.assertEqual(int(rec["transCount"]),1)
            self.assertEqual(int(rec["transAmount"]),2)
        with tables.open_file(str(self.h5_root/"minute_union_123456789abc"/"sz_5min.h5"),"r") as source:
            self.assertEqual(int(source.get_node("/data/SZ000001").read()[0]["datetime"]),
                             202610130935)
        # Test the independently documented 1min end/5min start convention,
        # including the extra 09:30 record and 13:00 boundary.
        day=self.fixture.f.day
        one=M.purchased_minute_map(day,"1min")
        five=M.purchased_minute_map(day,"5min")
        for hm in ("0930","0931","1300","1301","1500"):
            tm=datetime.strptime(str(day).replace("-","")+hm,"%Y%m%d%H%M"
                ).replace(tzinfo=M.ST.CORE.UTC8)
            self.assertEqual(one[int(tm.timestamp()*1000)],
                             int(tm.strftime("%Y%m%d%H%M")))
        self.assertEqual(len(set(one.values())),len(one))
        opening=datetime.strptime(str(day).replace("-","")+"0930","%Y%m%d%H%M"
            ).replace(tzinfo=M.ST.CORE.UTC8)
        self.assertEqual(five[int(opening.timestamp()*1000)],202610130935)
        self.assertEqual(len(five),48)
        with tables.open_file(str(self.h5_root/"minute_union_123456789abc"/"sh_1min.h5"),"r") as source:
            table=source.get_node("/data/SH600000")
            self.assertEqual(table.nrows,240)
            self.assertEqual(int(table.read(0,1)[0]["openPrice"]),10500)
        saved=self.native_safe.read_text("utf-8")
        for forbidden in ("SH600000","SZ000001","202610130931","10500"):
            self.assertNotIn(forbidden,saved)

    def test_modified_unified_minute_parquet_source_sha_blocks_write(self):
        summary=json.loads(self.batch.read_text())
        one=summary["days"][0]["by_period"]["1min"]["unified_parquet_sha256"]
        self.assertEqual(len(one),64)
        day=self.fixture.f.day
        child=__import__("hashlib").sha256(
            (self.fixture.parent+":"+str(day)).encode("ascii")).hexdigest()[:12]
        path=(self.base/"work"/"unified_parquet"/"minute_complete_day"/
              f"minute_{child}"/f"1min-{day}.parquet")
        path.write_bytes(path.read_bytes()+b"synthetic-test-only")
        with self.patched(),self.assertRaisesRegex(ValueError,"SHA mismatch"):
            M.stage(self.batch,None,"123456789abc",self.native_safe,
                    max_total_rows=10000)
        self.assertFalse(self.native_safe.exists())
        self.assertFalse((self.h5_root/"minute_union_123456789abc").exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
