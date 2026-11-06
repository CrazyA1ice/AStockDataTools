"""Synthetic, exact read-only original H5 vs private Parquet 1990 annual checks.

All H5 and Parquet bytes are fictional and reside in TemporaryDirectory;
never invokes licensed original sources or user's private market artifacts.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

import h5py
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "original_h5_exact_annual_private_ohlcva_synthetic_contracts",
    HERE.parent/"tools"/"compare-original-h5-pre2011-private-day-ohlcva-exact-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

H5_DTYPE=np.dtype([
    ("datetime","<i8"),("openPrice","<i8"),("highPrice","<i8"),
    ("lowPrice","<i8"),("closePrice","<i8"),("transCount","<i8"),
    ("transAmount","<i8")
])


class ExactRawH5VsPrivateDayContracts(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.root=self.base/"orig"
        self.market=self.root/"HikyuuData"
        self.market.mkdir(parents=True)
        self.module=self.base/"repo"
        self.folder=self.module/"work"/"unified_parquet"/"historical_pre2011_daily_pilots"/("1990-research-"+"a"*16)
        self.folder.mkdir(parents=True)
        self.patches=[]
        for m in M.P90.MARKETS:
            with h5py.File(self.market/(m+"_day.h5"),"w") as f:
                f.create_group("data")
        self.write_native("SH600000",199012200000,10_000,11_000,9_000,10_500,200,3000)
        self.write_native("SH600001",199012200000,20_000,21_000,19_000,20_500,400,6000)
        self.write_native("SH900901",199012200000,10000,11000,9000,10500,200,3000)
        self.prepare()
        for p in (
            patch.object(M.FULL,"MODULE",self.module),
            patch.object(M.FULL,"_private_paths",return_value={1990:self.folder}),
            patch.object(M.FULL,"_expected",return_value=(2,1,2,1)),
            patch.object(M.FULL,"_source_gate",side_effect=lambda root:(
                M.P90.h5_state(root),"b"*64)),
        ):
            p.start()
            self.patches.append(p)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def write_native(self,symbol,stamp,op,hi,lo,cl,volume,amount):
        market=symbol[:2].lower()
        record=np.array([(stamp,op,hi,lo,cl,volume,amount)],dtype=H5_DTYPE)
        with h5py.File(self.market/(market+"_day.h5"),"a") as f:
            f["data"].create_dataset(symbol,data=record)

    def prepare(self):
        native=199012200000
        stamp=int(datetime(1990,12,20,tzinfo=M.CORE.UTC8).timestamp()*1000)
        rows=[
            {
                "ts":stamp,"symbol":"600000.XSHG",
                "open":10.0,"high":11.0,"low":9.0,"close":10.5,
                "volume":20000.0,"amount":3000000.0,
                "source":M.FULL.SOURCES[1990],
            },
            {
                "ts":stamp,"symbol":"600001.XSHG",
                "open":20.0,"high":21.0,"low":19.0,"close":20.5,
                "volume":40000.0,"amount":6000000.0,
                "source":M.FULL.SOURCES[1990],
            },
        ]
        pq.write_table(pa.Table.from_pylist(rows,schema=M.FULL.ANNUAL._candidate_schema()),
                       self.folder/"day.parquet",compression="snappy")
        self.write_manifest()

    def write_manifest(self):
        proof={
            "format":"AStockDataTools isolated uncertified 1990 H5 candidate day private v1",
            "state":"verified_private_candidate_not_promoted",
            "year":1990,"period":"day",
            "candidate_stockday_rows":2,"private_parquet_row_count":2,
            "other_code_source_rows_not_staged":1,"distinct_source_dates":1,
            "market_candidate_rows":{"SH":2},
            "h5_original_state_sha256":M.P90.h5_state(self.root),
            "purchased_original_state_sha256":"b"*64,
            "private_parquet_written":True,
            "candidate_price_factor":0.001,"candidate_volume_factor":100,
            "candidate_amount_factor":1000,
            "private_stage_relative_dir":self.folder.relative_to(self.module).as_posix(),
            "private_parquet_sha256":M.P90._digest(self.folder/"day.parquet"),
            "purchased_pre2011_absent_in_all_24_original_day_files":True,
            "h5_1990_source_exact_key_and_OHLCVA_geometry_passed":True,
            **{key:False for key in M.FULL.ALWAYS_FALSE},
        }
        (self.folder/"manifest.json").write_text(
            json.dumps(proof,ensure_ascii=False,sort_keys=True),encoding="utf-8")

    def tamper_parquet_and_rehash(self,change):
        path=self.folder/"day.parquet"
        data=pq.read_table(path).to_pylist()
        change(data)
        pq.write_table(pa.Table.from_pylist(
            data,schema=M.FULL.ANNUAL._candidate_schema()),path,compression="snappy")
        self.write_manifest()

    def execute(self):
        with redirect_stdout(StringIO()) as out:
            result=M.compare(self.root,1990,1990)
        return result,out.getvalue()

    def test_two_exact_original_h5_compound_rows_match_all_fields(self):
        before={p.name:(p.stat().st_size,p.stat().st_mtime_ns)
                for p in self.market.iterdir()}
        result,output=self.execute()
        self.assertEqual(result["exact_h5_source_stockdays_compared"],2)
        self.assertEqual(result["excluded_other_source_day_keys"],1)
        self.assertTrue(result["all_selected_h5_candidate_keys_and_six_fields_exact_equal"])
        self.assertFalse(result["full_1990_2010_coverage_compared"])
        self.assertFalse(result["h5_price_volume_amount_units_certified"])
        self.assertFalse(result["ready_for_production_merge"])
        self.assertIn("EXACT_H5_PRIVATE_YEAR_PASS=1990 STOCKDAYS=2",output)
        self.assertNotIn("600000.XSHG",output)
        self.assertNotIn("20000.0",output)
        self.assertEqual(before,{p.name:(p.stat().st_size,p.stat().st_mtime_ns)
                                 for p in self.market.iterdir()})

    def test_changed_open_price_with_rehashed_private_manifest_rejected(self):
        self.tamper_parquet_and_rehash(lambda rows:rows[0].update(open=10.25))
        with self.assertRaisesRegex(ValueError,"field open mismatch"):
            self.execute()

    def test_changed_volume_scale_with_rehashed_private_manifest_rejected(self):
        self.tamper_parquet_and_rehash(lambda rows:rows[0].update(volume=2000.0))
        with self.assertRaisesRegex(ValueError,"field volume mismatch"):
            self.execute()

    def test_changed_amount_scale_with_rehashed_private_manifest_rejected(self):
        self.tamper_parquet_and_rehash(lambda rows:rows[0].update(amount=3000.0))
        with self.assertRaisesRegex(ValueError,"field amount mismatch"):
            self.execute()

    def test_changed_symbol_with_rehashed_private_manifest_rejected(self):
        self.tamper_parquet_and_rehash(lambda rows:rows[0].update(symbol="600002.XSHG"))
        with self.assertRaisesRegex(ValueError,"security set mismatch"):
            self.execute()

    def test_changed_native_day_with_rehashed_private_manifest_rejected(self):
        changed=int(datetime(1990,12,21,tzinfo=M.CORE.UTC8).timestamp()*1000)
        self.tamper_parquet_and_rehash(lambda rows:rows[0].update(ts=changed))
        with self.assertRaisesRegex(ValueError,"exact stockday keys mismatch"):
            self.execute()

    def test_duplicate_stockday_in_private_candidate_rejected(self):
        self.tamper_parquet_and_rehash(lambda rows:rows[1].update(symbol=rows[0]["symbol"]))
        with self.assertRaisesRegex(ValueError,"Duplicated original-private stockday key"):
            self.execute()

    def test_rewritten_parquet_without_manifest_sha_update_rejected(self):
        path=self.folder/"day.parquet"
        path.write_bytes(path.read_bytes()+b"tampered")
        with self.assertRaisesRegex(ValueError,"content SHA256 mismatch"):
            self.execute()

    def test_other_code_is_excluded_without_reading_other_ohlcva(self):
        result,_=self.execute()
        self.assertEqual(result["excluded_other_source_day_keys"],1)

    def test_missing_original_h5_candidate_refused(self):
        # Alter original source while preserving private candidate immutable.
        with h5py.File(self.market/"sh_day.h5","a") as f:
            del f["data/SH600001"]
        self.write_manifest()
        with self.assertRaisesRegex(ValueError,"security set mismatch|count conservation failed"):
            self.execute()

    def test_negative_original_source_price_refused(self):
        with h5py.File(self.market/"sh_day.h5","a") as f:
            f["data/SH600000"][0]=np.array(
                [(199012200000,-1,11000,9000,10500,200,3000)],dtype=H5_DTYPE)[0]
        self.write_manifest()
        with self.assertRaisesRegex(ValueError,"negative native OHLCVA"):
            self.execute()

    def test_purchased_source_gate_failure_never_loads_parquet(self):
        with patch.object(M.FULL,"_source_gate",side_effect=ValueError("source PQ drift")),patch.object(
                M,"_stage_array",side_effect=AssertionError("Do not load")):
            with self.assertRaisesRegex(ValueError,"source PQ drift"):
                self.execute()

    def test_years_outside_source_audit_rejected_before_open(self):
        for begin,end in ((1989,1990),(1990,2011),(2001,2000)):
            with self.subTest(begin=begin,end=end):
                with patch.object(M.FULL,"_source_gate",side_effect=AssertionError("no source")):
                    with self.assertRaisesRegex(ValueError,"bounded"):
                        M.compare(self.root,begin,end)

    def test_wrong_manifest_source_state_rejected_before_H5_decode(self):
        p=self.folder/"manifest.json"
        data=json.loads(p.read_text(encoding="utf-8"))
        data["h5_original_state_sha256"]="c"*64
        p.write_text(json.dumps(data),encoding="utf-8")
        with patch.object(M,"_stage_array",side_effect=AssertionError("no Parquet loads")):
            with self.assertRaisesRegex(ValueError,"uncertified gate"):
                self.execute()

    def test_source_file_stat_drift_after_comparison_refused(self):
        correct=M.P90.h5_state(self.root)
        with patch.object(M.P90,"h5_state",side_effect=[
            correct,"c"*64]):
            with self.assertRaisesRegex(ValueError,"changed mid-comparison"):
                self.execute()


if __name__=="__main__":
    unittest.main(verbosity=2)
