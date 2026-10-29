"""Isolated synthetic Hikyuu H5 canary tests; no licensed market data."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import h5py

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "test_hikyuu_synthetic_canary",
    HERE.parent/"tools"/"build-hikyuu-native-h5-synthetic-canary.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

try:
    import tables
except ImportError:
    tables=None


def survey():
    fields=[{"field":name,"kind":kind,"itemsize_bytes":width,
             "offset_bytes":offset}
            for name,kind,width,offset in M.LAYOUT]
    by={}
    for name in ("SH600000","SZ000001"):
        by[name]={
            "dataset_present":True,"pytables_table_class_marker_present":True,
            "one_dimensional_compound_dataset":True,
            "expected_field_set":True,
            "integer_width_sign_compatible_with_h5record":True,
            "structural_h5record_candidate":True,
            "hikyuu_native_driver_verified":False,
            "dtype_itemsize_bytes":40,
            "rows_in_dataset":6404 if name=="SH600000" else 8468,
            "field_layout":[dict(item) for item in fields]}
    return {
        "format":M.SURVEY_FORMAT,"period":"day",
        "symbols":["SH600000","SZ000001"],
        "hikyuu_native_driver_load_tested":False,
        "ready_for_full_h5_mirror_write":False,
        "mirror_files_created":False,
        "source_h5_files_modified":False,
        "no_raw_ohlcva_in_safe_summary":True,
        "source_file_stat_provenance":[
            {"relative_path":"HikyuuData/sh_day.h5"},
            {"relative_path":"HikyuuData/sz_day.h5"}],
        "per_symbol_native_h5_contract":by}


class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.module=root/"H5ParquetReconciler"
        self.reports=self.module/"reports"
        self.work=self.module/"work"
        self.mirrors=self.work/"h5_mirror"
        self.reports.mkdir(parents=True)
        self.source=self.reports/"native-survey.json"
        self.source.write_text(json.dumps(survey()),encoding="utf-8")
        self.target=self.mirrors/"canary1"
        self.output=self.reports/"canary1-safe.json"
        patches=[
            patch.object(M,"MODULE",self.module),
            patch.object(M,"REPORTS",self.reports),
            patch.object(M,"WORK",self.work),
            patch.object(M,"MIRRORS",self.mirrors)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def produce(self):
        if tables is None:
            self.skipTest("PyTables required: python -m pip install tables")
        return M.build_canary(self.source,self.target,self.output)

    def test_real_pytables_writer_roundtrips_three_synthetic_rows_per_stock(self):
        result=self.produce()
        self.assertTrue(result["synthetic_only"])
        self.assertEqual(result["synthetic_record_count"],6)
        self.assertEqual(len(result["generated_files"]),2)
        self.assertFalse(result["hikyuu_native_driver_tested"])
        self.assertFalse(result["safe_for_full_market_h5_mirror"])
        self.assertTrue(self.output.is_file())
        for market,code in (("sh","SH600000"),("sz","SZ000001")):
            path=self.target/(market+"_day.h5")
            with h5py.File(path,"r") as f:
                ds=f["data"][code]
                self.assertEqual(len(ds),3)
                self.assertEqual(ds.dtype.names,M.ORDER)
                self.assertEqual(ds.dtype.itemsize,40)
                self.assertEqual(int(ds[1]["datetime"]),202610080000)
                self.assertEqual(ds.attrs["CLASS"],b"TABLE")
                self.assertEqual(ds.compression,"gzip")
            with tables.open_file(str(path)) as f:
                self.assertEqual(f.get_node("/data/"+code).nrows,3)
        safe=json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(safe["source_survey_sha256"],result["source_survey_sha256"])
        self.assertNotIn('"openPrice":',json.dumps(safe))
        self.assertNotIn("10050",json.dumps(safe))

    def test_no_recreate_or_overwrite_existing_mirror_or_report(self):
        self.produce()
        with self.assertRaisesRegex(ValueError,"NEW"):
            M.build_canary(self.source,self.target,self.reports/"another.json")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            M.build_canary(self.source,self.mirrors/"canary2",self.output)
        self.assertFalse((self.mirrors/"canary2").exists())

    def test_refuse_bad_source_structure_even_when_field_names_match(self):
        for change in ("signed_ohlc","out_of_order","wrong_offset"):
            with self.subTest(change=change):
                doc=survey()
                fields=doc["per_symbol_native_h5_contract"]["SH600000"]["field_layout"]
                if change=="signed_ohlc":
                    fields[0]["kind"]="i"
                elif change=="out_of_order":
                    fields.reverse()
                else:
                    fields[1]["offset_bytes"]=8
                self.source.write_text(json.dumps(doc),encoding="utf-8")
                with self.assertRaisesRegex(ValueError,"layout"):
                    M.build_canary(self.source,self.target,self.output)
                self.assertFalse(self.target.exists())

    def test_refuse_unproven_or_activated_survey_flags(self):
        for key,bad in (
                ("hikyuu_native_driver_load_tested",True),
                ("ready_for_full_h5_mirror_write",True),
                ("no_raw_ohlcva_in_safe_summary",False)):
            with self.subTest(key=key):
                doc=survey()
                doc[key]=bad
                self.source.write_text(json.dumps(doc),encoding="utf-8")
                with self.assertRaisesRegex(ValueError,"Untrusted"):
                    M.build_canary(self.source,self.target,self.output)
                self.assertFalse(self.target.exists())

    def test_refuse_missing_or_external_survey_and_unsafe_output(self):
        external=self.module/"other.json"
        external.write_text(self.source.read_text(encoding="utf-8"),
                            encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"directly under"):
            M.build_canary(external,self.target,self.output)
        self.assertFalse(self.target.exists())
        with self.assertRaisesRegex(ValueError,"NEW direct child"):
            M.build_canary(self.source,self.work/"other_canary",self.output)
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            M.build_canary(self.source,self.target,self.work/"report.json")
        self.assertFalse(self.target.exists())

    def test_failed_writer_does_not_leave_partial_canary(self):
        if tables is None:
            self.skipTest("PyTables required")
        with patch.object(M,"_synthetic_rows",
                          side_effect=ValueError("forced synthetic failure")):
            with self.assertRaisesRegex(ValueError,"forced synthetic"):
                M.build_canary(self.source,self.target,self.output)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.output.exists())

    def test_canary_build_requires_two_canonical_audited_symbols(self):
        for bad_symbols in (
                ["SH600000"],["SH600000","SH600000"],
                ["sh600000","SZ000001"]):
            with self.subTest(bad_symbols=bad_symbols):
                doc=survey()
                doc["symbols"]=bad_symbols
                with self.assertRaisesRegex(ValueError,"two-stock"):
                    M.validate_survey(doc)


if __name__=="__main__":
    unittest.main(verbosity=2)
