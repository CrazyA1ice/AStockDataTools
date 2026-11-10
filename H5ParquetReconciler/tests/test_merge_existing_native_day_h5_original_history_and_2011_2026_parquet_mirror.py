"""Synthetic full native H5 day source-preserving merge, real PyTables files."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import tables

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "hikyuu_original_history_plus_modern_mirror_test",
    HERE.parent/"tools"/"merge-existing-native-day-h5-original-history-and-2011-2026-parquet-mirror.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
DT=M.canonical_dtype(np)

def records(*items):
    rows=np.empty(len(items),dtype=DT)
    for i,(stamp,close) in enumerate(items):
        rows[i]["datetime"]=stamp
        for field in ("openPrice","highPrice","lowPrice","closePrice"):
            rows[i][field]=close
        rows[i]["transAmount"]=1000
        rows[i]["transCount"]=100
    return rows

def write_file(file,groups):
    file.parent.mkdir(parents=True,exist_ok=True)
    with tables.open_file(str(file),"w") as h5:
        h5.create_group("/","data")
        h5.create_group("/","metadata")
        h5.create_array("/metadata","sentinel",obj=np.array([73],dtype=np.int32))
        for sym,rows in groups.items():
            t=h5.create_table("/data",sym,description=DT,
                              expectedrows=max(1,len(rows)))
            t.append(rows)
            t.flush()

class FullNativeDayMirrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        self.module=base/"H5ParquetReconciler"
        self.reports=self.module/"reports"
        self.reports.mkdir(parents=True)
        self.mirrors=self.module/"work"/"h5_mirror"
        self.mirrors.mkdir(parents=True)
        self.modern=self.mirrors/M.MIRROR_NAME
        self.market=base/"stock"/"HikyuuData"
        self.market.mkdir(parents=True)
        self.old={
            "sh":{"SH600000":records(
                (201012300000,101),(201201040000,200),
                (201301040000,300)),
                  "SH000001":records((200601050000,120))},
            "sz":{"SZ000001":records((201012290000,111))},
            "bj":{"BJ430001":records((200901010000,100))},
        }
        self.new={
            "sh":{"SH600000":records(
                (201101040000,111),(201201040000,999),
                (202610130000,222))},
            "sz":{"SZ000001":records((201201040000,777))},
            "bj":{},
        }
        self.mirrorsha={}
        self.origsha={}
        for market in M.MARKETS:
            name=market+"_day.h5"
            original=self.market/name
            modern=self.modern/name
            write_file(original,self.old[market])
            write_file(modern,self.new[market])
            self.mirrorsha[name]=M.sha(modern)
            self.origsha[name]=M.sha(original)
        self.safe=self.reports/"full-2011-2026-native-h5-day-3dc5044a4122.json"
        self.doc={
            "status":"private_day_native_h5_40byte_tables_written_all_integer_rows_readback_not_activated",
            "source_16year_private_version_sha256":"bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05",
            "total_h5_native_integer_records":4,
            "total_private_parquet_rows":4,
            "year_range":[2011,2026],
            "native_40byte_table_integer_sha_readback_verified":True,
            "original_hikyuu_h5_files_modified":False,
            "full_mirror_ready_for_production":False,
            "private_h5_files_sha256":self.mirrorsha,
        }
        self.safe.write_text(json.dumps(self.doc),encoding="utf-8")
        patched=[
            patch.object(M,"MODULE",self.module),
            patch.object(M,"REPORTS",self.reports),
            patch.object(M,"MIRRORS",self.mirrors),
            patch.object(M,"MODERN_COUNT",4),
        ]
        for p in patched:
            p.start()
            self.addCleanup(p.stop)

    def run_merge(self):
        rid="c0ffee123456"
        output=self.reports/"complete-day-test.json"
        result=M.mirror(self.market.parent,self.safe,self.modern,rid,output)
        return result,self.mirrors/("complete_day_"+rid),output

    def test_full_native_merge_preserves_old_history_other_symbols_and_purchased_priority(self):
        report,dest,safe=self.run_merge()
        self.assertTrue(safe.is_file())
        self.assertEqual(report["modern_purchased_first_2011_2026_rows"],4)
        self.assertEqual(report["preserved_original_native_1990_2010_rows_in_overlapping_A_share_stocks"],2)
        self.assertEqual(report["original_h5_2011_plus_same_keys_overridden_from_parquet"],1)
        self.assertEqual(report["original_h5_2011_plus_only_native_keys_preserved"],1)
        self.assertEqual(report["other_original_H5_stock_tables_retained_unmodified"],2)
        with tables.open_file(str(dest/"sh_day.h5"),"r") as f:
            got=f.get_node("/data/SH600000").read()
            self.assertEqual(got["datetime"].tolist(),
                             [201012300000,201101040000,201201040000,
                              201301040000,202610130000])
            self.assertEqual(got["closePrice"].tolist(),
                             [101,111,999,300,222])
            self.assertEqual(int(f.get_node("/metadata/sentinel")[0]),73)
            self.assertEqual(f.get_node("/data/SH000001").read().tobytes(),
                             self.old["sh"]["SH000001"].tobytes())
        for name,digest in self.origsha.items():
            self.assertEqual(M.sha(self.market/name),digest)
        self.assertFalse(report["production_h5_active_replacement_performed"])
        self.assertFalse(report["original_hikyuu_h5_or_purchased_parquet_modified"])

    def test_same_native_day_key_purchased_wins(self):
        combined,count=M.merge_stock(
            records((201012310000,1),(201201010000,2)),
            records((201201010000,99),(201301010000,3)),np,DT)
        self.assertEqual(combined["datetime"].tolist(),
                         [201012310000,201201010000,201301010000])
        self.assertEqual(combined["closePrice"].tolist(),[1,99,3])
        self.assertEqual(count["original_post2010_replaced_by_purchased"],1)

    def test_duplicate_input_time_keys_rejected(self):
        with self.assertRaisesRegex(ValueError,"not strictly increasing"):
            M.merge_stock(records((201001010000,1),(201001010000,2)),
                          records((201201010000,1)),np,DT)
        with self.assertRaisesRegex(ValueError,"not strictly increasing"):
            M.merge_stock(records((201001010000,1)),
                          records((201201010000,1),(201201010000,2)),np,DT)

    def test_legacy_h5_after_cutoff_rejected_and_original_untouched(self):
        self.old["sh"]["SH600000"]=records((201012300000,10),(202610150000,20))
        write_file(self.market/"sh_day.h5",self.old["sh"])
        modified=M.sha(self.market/"sh_day.h5")
        with self.assertRaisesRegex(ValueError,"past authorized"):
            self.run_merge()
        self.assertEqual(M.sha(self.market/"sh_day.h5"),modified)
        self.assertFalse((self.reports/"complete-day-test.json").exists())

    def test_modern_native_h5_tamper_rejected_before_copy(self):
        self.modern.joinpath("sh_day.h5").write_bytes(
            self.modern.joinpath("sh_day.h5").read_bytes()+b"tamper")
        with self.assertRaisesRegex(ValueError,"mirror SHA differs"):
            self.run_merge()
        self.assertFalse((self.mirrors/"complete_day_c0ffee123456").exists())

    def test_invalid_uint_source_signedness_rejected(self):
        dt=np.dtype([(name,"<i8" if name=="datetime" else
                      ("<u8" if name in ("transAmount","transCount")
                       else "<u4")) for name in M.FIELDS])
        original=np.empty(1,dtype=dt)
        with self.assertRaisesRegex(ValueError,"signedness"):
            M.convert_records(original,DT,np)

if __name__=="__main__":
    unittest.main()
