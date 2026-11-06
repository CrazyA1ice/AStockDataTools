"""1991-2010 yearly H5 -> PRIVATE Parquet contract tests, fictional data only."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "annual_pre2011_h5_private_candidate_synthetic_contract",
    HERE.parent/"tools"/"stage-original-h5-pre2011-annual-private-day.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
TYPE=np.dtype([
    ("datetime","<i8"),("openPrice","<i8"),("highPrice","<i8"),
    ("lowPrice","<i8"),("closePrice","<i8"),("transCount","<i8"),
    ("transAmount","<i8"),
])


class AnnualPre2011PrivateStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.root=self.base/"original"
        self.h5=self.root/"HikyuuData"
        self.h5.mkdir(parents=True)
        for exchange in M.P90.MARKETS:
            with h5py.File(self.h5/(exchange+"_day.h5"),"w") as f:
                f.create_group("data")
        self.module=self.base/"fake-module"
        self.parent=self.module/"work"/"unified_parquet"/"historical_pre2011_daily_pilots"
        self.parent.parent.mkdir(parents=True)
        self.patches=[]

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def fixture(self):
        for p in (
            patch.object(M,"MODULE",self.module),
            patch.object(M,"PARENT",self.parent),
            patch.dict(M.EXPECTED,{1991:(2,1,1,2)}),
            patch.object(M.P90,"EXPECTED_H5_STATE",M.P90.h5_state(self.root)),
            patch.object(M.P90,"purchased_gate",
                         return_value={"source_file_size_mtime_state_sha256":"a"*64}),
        ):
            p.start()
            self.patches.append(p)

    def put(self,market,symbol,stamps,**override):
        rows=np.zeros(len(stamps),dtype=TYPE)
        rows["datetime"]=stamps
        values={
            "openPrice":10000,"highPrice":11000,"lowPrice":9000,
            "closePrice":10200,"transCount":100,"transAmount":2000,
            **override,
        }
        for k,value in values.items():
            rows[k]=value
        with h5py.File(self.h5/(market+"_day.h5"),"a") as h5:
            h5["data"].create_dataset(symbol,data=rows)

    def prepare(self):
        self.put("sh","SH600000",[199101020000,199101030000])
        self.put("sh","SH900901",[199101020000])

    def test_1991_readonly_preflight_no_private_file(self):
        self.prepare();self.fixture()
        result=M.annual(self.root,1991)
        self.assertEqual(result["candidate_stockday_rows"],2)
        self.assertEqual(result["other_code_source_rows_not_staged"],1)
        self.assertEqual(result["market_candidate_rows"],{"SH":2})
        self.assertFalse(result["private_parquet_written"])
        self.assertFalse(result["ready_for_production_merge"])
        self.assertFalse(result["h5_volume_amount_price_units_certified"])
        self.assertFalse(self.parent.exists())

    def test_stage_and_exact_h5_roundtrip_idempotent_resume(self):
        self.prepare();self.fixture()
        before={p.name:(p.stat().st_size,p.stat().st_mtime_ns)
                for p in self.h5.iterdir()}
        first=M.annual(self.root,1991,write=True)
        self.assertTrue(first["private_parquet_written"])
        self.assertEqual(first["state"],"verified_private_candidate_not_promoted")
        directory=self.module/first["private_stage_relative_dir"]
        manifest=json.loads((directory/"manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["candidate_stockday_rows"],2)
        self.assertEqual(manifest["private_parquet_sha256"],first["private_parquet_sha256"])
        table=pq.read_table(directory/"day.parquet")
        self.assertEqual(table.num_rows,2)
        self.assertEqual(table.column("source").to_pylist(),[
            "hikyuu_h5_historical_uncertified_private_candidate"]*2)
        again=M.annual(self.root,1991,write=True)
        self.assertEqual(again["state"],"already_verified_private_candidate_not_promoted")
        self.assertFalse(again["private_parquet_written"])
        self.assertEqual(again["private_parquet_sha256"],first["private_parquet_sha256"])
        self.assertEqual(len(list(self.parent.iterdir())),1)
        self.assertEqual(before,{p.name:(p.stat().st_size,p.stat().st_mtime_ns)
                                 for p in self.h5.iterdir()})

    def test_different_h5_state_before_any_year_source_read_fails(self):
        self.prepare();self.fixture()
        with patch.object(M.P90,"EXPECTED_H5_STATE","0"*64), patch.object(
                M,"_source_rows",side_effect=AssertionError("No H5 prices")):
            with self.assertRaisesRegex(ValueError,"H5 source state differs"):
                M.annual(self.root,1991,write=True)

    def test_failed_purchase_source_gate_never_reads_h5_prices(self):
        self.prepare();self.fixture()
        with patch.object(M.P90,"purchased_gate",side_effect=ValueError("purchase changed")),patch.object(
                M,"_source_rows",side_effect=AssertionError("No H5 prices")):
            with self.assertRaisesRegex(ValueError,"purchase changed"):
                M.annual(self.root,1991,write=True)

    def test_wrong_year_rejected(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,"Only individually audited"):
            M.annual(self.root,1990)
        with self.assertRaisesRegex(ValueError,"Only individually audited"):
            M.annual(self.root,2011)

    def test_duplicate_native_day_rejected(self):
        self.put("sh","SH600000",[199101020000,199101020000])
        with self.assertRaisesRegex(ValueError,"Duplicate or unsorted"):
            M._source_rows(self.root,1991,2)

    def test_nonmidnight_day_rejected(self):
        self.put("sh","SH600000",[199101020930])
        with self.assertRaisesRegex(ValueError,"Non-midnight"):
            M._source_rows(self.root,1991,2)

    def test_invalid_calendar_date_rejected(self):
        self.put("sh","SH600000",[199102300000])
        with self.assertRaisesRegex(ValueError,"Noncalendar"):
            M._source_rows(self.root,1991,2)

    def test_negative_original_h5_amount_rejected(self):
        self.put("sh","SH600000",[199101020000],transAmount=-1)
        with self.assertRaisesRegex(ValueError,"Negative"):
            M._source_rows(self.root,1991,2)

    def test_bad_high_low_geometry_rejected(self):
        self.put("sh","SH600000",[199101020000],highPrice=8000)
        with self.assertRaisesRegex(ValueError,"geometry"):
            M._source_rows(self.root,1991,2)

    def test_historical_other_code_is_never_staged(self):
        self.prepare();self.fixture()
        result=M.annual(self.root,1991,write=True)
        path=self.module/result["private_stage_relative_dir"]/"day.parquet"
        rows=pq.read_table(path).to_pylist()
        self.assertEqual(len(rows),2)
        self.assertTrue(all(row["symbol"]=="600000.XSHG" for row in rows))

    def test_source_inventory_changed_count_rejected(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,"source counts differ"):
            M._source_rows(self.root,1991,2043)

    def test_untrusted_private_output_root_rejected_before_creation(self):
        self.prepare();self.fixture()
        outside=self.base/"other"/"annual"
        outside.parent.mkdir()
        with patch.object(M,"PARENT",outside):
            with self.assertRaisesRegex(ValueError,"inside ignored module work"):
                M.annual(self.root,1991,write=True)
        self.assertFalse(outside.exists())

    def test_existing_candidate_sha_drift_refused(self):
        self.prepare();self.fixture()
        summary=M.annual(self.root,1991,write=True)
        path=self.module/summary["private_stage_relative_dir"]/"day.parquet"
        path.write_bytes(path.read_bytes()+b"tamper")
        with self.assertRaisesRegex(ValueError,"SHA/provenance changed"):
            M.annual(self.root,1991,write=True)

    def test_existing_candidate_missing_manifest_is_not_overwritten(self):
        self.prepare();self.fixture()
        summary=M.annual(self.root,1991,write=True)
        (self.module/summary["private_stage_relative_dir"]/"manifest.json").unlink()
        with self.assertRaisesRegex(ValueError,"Incomplete existing"):
            M.annual(self.root,1991,write=True)
        self.assertEqual(len(list(self.parent.iterdir())),1)

    def test_duplicate_private_stage_dirs_need_manual_review_not_duplicate_write(self):
        self.prepare();self.fixture()
        M.annual(self.root,1991,write=True)
        (self.parent/"1991-research-0000000000000000").mkdir()
        with self.assertRaisesRegex(ValueError,"Multiple existing"):
            M.annual(self.root,1991,write=True)


if __name__=="__main__":
    unittest.main(verbosity=2)
