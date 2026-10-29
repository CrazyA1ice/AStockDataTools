"""Synthetic PyArrow day + synthetic H5: no licensed sources and no H5 writes in SUT."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "real_day_h5_two_source_candidate_gate",
    HERE.parent/"tools"/"probe-real-parquet-h5-day-unit-factors-readonly.py")
G=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


def fake_ms():
    return int(datetime(2026,9,30,8,0,
                        tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)


class TwoSourceSyntheticGateTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        import h5py
        import numpy as np
        self.pa,self.pq,self.h5py,self.np=pa,pq,h5py,np
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"synthetic_source"
        self.parquet=self.root/"AllCycleAStockData"/"day"/"2026-09.parquet"
        self.h5root=self.root/"HikyuuData"
        self.parquet.parent.mkdir(parents=True)
        self.h5root.mkdir()
        self.reports=Path(self.tmp.name)/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        self.bridge=self.reports/"previous-bridge-v1.json"
        self.output=self.reports/"factors-safe-v1.json"
        patcher=patch.object(G.AUDIT,"REPORTS",self.reports)
        patcher.start();self.addCleanup(patcher.stop)
        self.write_sources()
        self.bridge.write_text(json.dumps({
            "format":G.BRIDGE_FORMAT,
            "source_stock_files_or_market_db_opened":False,
            "real_ohlcva_or_individual_timestamps_emitted":False,
            "physical_amount_unit_certified":False,
            "physical_volume_unit_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
            "precision":{
                "two_real_stock_days_sampled":2,
                "trading_day":"2026-09-30"},
            "tdx_vs_purchased_parquet":{"tdx_is_hikyuu_h5":False},
            "hikyuu_h5_vs_purchased_parquet":{
                "any_field_candidate_conflict_bars":95}
        }),encoding="utf-8")

    def write_sources(self,wrong_h5_type=False,missing_h5=False):
        pa,pq,h5py,np=self.pa,self.pq,self.h5py,self.np
        t=pa.table({
            "ts":pa.array([fake_ms(),fake_ms()],type=pa.int64()),
            "symbol":pa.array(["600000.XSHG","000001.XSHE"]),
            "open":pa.array([10.1,20.2]),
            "high":pa.array([10.2,20.3]),
            "low":pa.array([10.0,20.1]),
            "close":pa.array([10.15,20.25]),
            "volume":pa.array([1300.,2200.]),
            "amount":pa.array([150000.,320000.]),
        })
        pq.write_table(t,self.parquet)
        dt=np.dtype([
            ("datetime","<u8"),("openPrice","<u4"),
            ("highPrice","<u4"),("lowPrice","<u4"),
            ("closePrice","<u4"),("transCount","<u8"),
            ("transAmount","<f8" if wrong_h5_type else "<u8"),
        ])
        for sym,raw in (("SH600000",(10100,10200,10000,10150,13,150)),
                        ("SZ000001",(20200,20300,20100,20250,22,320))):
            path=self.h5root/(sym[:2].lower()+"_day.h5")
            if missing_h5 and sym=="SZ000001":
                if path.exists():
                    path.unlink()
                continue
            rec=np.zeros(2,dtype=dt)
            rec[0]["datetime"]=202609290000
            rec[1]["datetime"]=202609300000
            for field,v in zip(G.RAW[1:],raw):
                rec[1][field]=v
            with h5py.File(path,"w") as f:
                f.create_group("data").create_dataset(sym,data=rec)

    def run_it(self):
        return G.run(self.root/"AllCycleAStockData",self.h5root,
                     "2026-09-30",self.bridge,self.output)

    def test_two_source_actual_synthetic_file_read_and_safe_factor_counts(self):
        before={p:hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (self.parquet,*self.h5root.glob("*.h5"))}
        result=self.run_it()
        ratio=result["comparison"][
            "candidate_factor_multiply_raw_h5_record_to_parquet_value"]
        self.assertEqual(ratio["volume"]["100"],2)
        self.assertEqual(ratio["amount"]["1000"],2)
        self.assertEqual(ratio["volume"]["1"],0)
        self.assertEqual(ratio["amount"]["1"],0)
        self.assertEqual(result["comparison"]["nonzero_positive_pair_count"],
                         {"volume":2,"amount":2})
        self.assertTrue(all(x==2 for x in result["comparison"][
            "raw_h5_price_divided_1000_within_0p005_count"].values()))
        self.assertFalse(result["licensed_parquet_to_h5_mapping_certified"])
        self.assertFalse(result["native_hikyuu_driver_unit_mapping_certified"])
        self.assertFalse(result["ready_for_full_market_mirror"])
        self.assertEqual(result["h5_raw_day_records_read"],2)
        after={p:hashlib.sha256(p.read_bytes()).hexdigest()
               for p in before}
        self.assertEqual(before,after)
        payload=self.output.read_text(encoding="utf-8")
        for forbidden in ("600000.XSHG","000001.XSHE","150000.",
                          "320000.","202609300000",str(fake_ms()),
                          "AllCycleAStockData","HikyuuData",
                          "SH600000","SZ000001"):
            self.assertNotIn(forbidden,payload)

    def test_prior_bridge_missing_or_claiming_certification_rejected(self):
        source=json.loads(self.bridge.read_text(encoding="utf-8"))
        for modifier in (
            lambda d:d.update({"physical_volume_unit_certified":True}),
            lambda d:d["precision"].update({"two_real_stock_days_sampled":3}),
            lambda d:d["hikyuu_h5_vs_purchased_parquet"].update(
                {"any_field_candidate_conflict_bars":0}),
        ):
            with self.subTest(modifier=modifier):
                x=json.loads(json.dumps(source))
                modifier(x)
                self.bridge.write_text(json.dumps(x),encoding="utf-8")
                with self.assertRaisesRegex(ValueError,"SAFE evidence"):
                    self.run_it()
                self.assertFalse(self.output.exists())

    def test_incorrect_h5_raw_numeric_dtype_rejected(self):
        self.write_sources(wrong_h5_type=True)
        with self.assertRaisesRegex(ValueError,"Unable to read"):
            self.run_it()
        self.assertFalse(self.output.exists())

    def test_missing_h5_source_does_not_create_new_file(self):
        self.write_sources(missing_h5=True)
        with self.assertRaisesRegex(ValueError,"original direct"):
            self.run_it()
        self.assertFalse(self.output.exists())
        self.assertFalse((self.h5root/"sz_day.h5").exists())

    def test_invalid_date_or_extra_period_rejected(self):
        with self.assertRaisesRegex(ValueError,"reviewed"):
            G.run(self.root/"AllCycleAStockData",self.h5root,
                  "2026-09-29",self.bridge,self.output)
        with self.assertRaisesRegex(ValueError,"reviewed"):
            G.run(self.root/"AllCycleAStockData",self.h5root,
                  "2026-09-31",self.bridge,self.output)

    def test_nonpositive_or_invalid_float_rejected(self):
        pq={"SH600000":{field:1.0 for field in G.FIELDS},
            "SZ000001":{field:1.0 for field in G.FIELDS}}
        h5={symbol:{field:1 for field in G.RAW}
            for symbol in G.SYMBOLS}
        for value in (float("nan"),float("inf"),-1.,True,1):
            local={symbol:dict(row) for symbol,row in pq.items()}
            local["SH600000"]["amount"]=value
            with self.subTest(v=value):
                with self.assertRaisesRegex(ValueError,"Parquet float64"):
                    G.evaluate(local,h5)

    def test_zero_pair_not_candidate_factor_evidence(self):
        p={symbol:{field:1. for field in G.FIELDS}
           for symbol in G.SYMBOLS}
        h={symbol:{field:1 for field in G.RAW}
           for symbol in G.SYMBOLS}
        for symbol in G.SYMBOLS:
            p[symbol]["amount"]=0.
            h[symbol]["transAmount"]=0
        result=G.evaluate(p,h)
        self.assertEqual(result["both_zero_pair_count"]["amount"],2)
        self.assertEqual(result["nonzero_positive_pair_count"]["amount"],0)
        self.assertTrue(all(v==0 for v in result[
            "candidate_factor_multiply_raw_h5_record_to_parquet_value"][
            "amount"].values()))

    def test_two_stock_day_duplicate_rejected_before_safe_output(self):
        # Recreate Parquet with duplicate matching security/date key.
        x=self.pq.read_table(self.parquet)
        joined=self.pa.concat_tables([x,x.slice(0,1)])
        self.pq.write_table(joined,self.parquet)
        with self.assertRaisesRegex(ValueError,"Cannot safely inspect"):
            self.run_it()
        self.assertFalse(self.output.exists())

    def test_output_only_in_module_reports_and_never_overwrites(self):
        self.output.write_text("original",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            self.run_it()
        self.assertEqual(self.output.read_text(encoding="utf-8"),"original")
        external=Path(self.tmp.name)/"out.json"
        with self.assertRaisesRegex(ValueError,"direct non-symlink"):
            G.run(self.root/"AllCycleAStockData",self.h5root,
                  "2026-09-30",self.bridge,external)

    def test_ratio_tolerance_and_no_false_universal_factor(self):
        self.assertTrue(G._ratio_hit(G.Decimal("1000"),10,"100"))
        self.assertFalse(G._ratio_hit(G.Decimal("1000"),10,"1"))
        self.assertFalse(G._ratio_hit(G.Decimal("0"),0,"100"))
        report=self.run_it()
        self.assertTrue(report["crosssource_factor_not_universal_outside_two_stock_days"])
        self.assertTrue(report["raw_h5_record_used_not_native_cpp_driver_decoding"])
        self.assertFalse(report["parquet_vendor_physical_volume_unit_certified"])

    def test_read_only_source_scope_does_not_create_market_h5(self):
        import inspect
        src=inspect.getsource(G._read_single_h5)
        self.assertIn('h5py.File(path,"r")',src)
        self.assertIn('ds[left]',src)
        self.assertNotIn('h5py.File(path,"w")',src)
        self.assertNotIn("create_dataset(",src)
        self.assertNotIn("iter_batches(",src)
        self.assertIn("MAX_H5_DATASET_ROWS",src)


if __name__=="__main__":
    unittest.main(verbosity=2)
