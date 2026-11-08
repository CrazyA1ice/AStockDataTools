"""Synthetic isolated Oct H5 5m->15/30/60m private candidate materialization tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "test_oct_highcycle_private_stage",
    HERE.parent/"tools"/"stage-2026-oct-verified-h5-high-cycle-private-parquet.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

def fake5(day,symbol,*,rows=48):
    result=[]
    for idx,stamp in enumerate(M.C.grid_timestamps(day)[:rows]):
        value=10.0+idx/100
        result.append({
            "symbol":symbol,"period":"5min",
            "source_timestamp_ms":stamp,
            "trading_date":day.isoformat(),
            "value_source":"h5_only_complete_stockday",
            "open":value,"high":value+0.3,
            "low":value-0.2,"close":value+0.1,
            "volume":100.0,"amount":1000.0,
        })
    return result

class PrivateOctHighCycleStagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module=Path(self.tmp.name)/"repo"/"H5ParquetReconciler"
        self.module.mkdir(parents=True)
        self.root=Path(self.tmp.name)/"market"
        self.root.mkdir()
        self.stage_root=(self.module/"work"/"unified_parquet"/"oct_high_cycle_staging")
        self.input=(self.module/"work"/"unified_parquet"/"minute_complete_day"/"source.parquet")
        self.input.parent.mkdir(parents=True)
        self.input.write_bytes(b"fake SHA-verified minute source fixture")
        self.input_sha=hashlib.sha256(self.input.read_bytes()).hexdigest()
        self.days=list(M.DEFAULT_DAYS)
        self.symbols=list(M.DEFAULT_SYMBOLS)
        self.patches=[
            patch.object(M,"MODULE",self.module),
            patch.object(M,"STAGE_ROOT",self.stage_root),
            patch.object(M.C.ALL.MINUTE,"_safe_private_file",
                         side_effect=lambda d,p:(self.input,{
                             "unified_parquet_sha256":self.input_sha})),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.queries=[]
        self.return_purchased=False
        self.partial=False
        self.bad_grid=False
        self.query_patch=patch.object(M.C,"_query",side_effect=self.query)
        self.query_patch.start()
        self.addCleanup(self.query_patch.stop)

    def query(self,root,symbol,period,day,*,private=False):
        self.queries.append((symbol,period,day.isoformat(),private))
        if period=="5min":
            self.assertTrue(private)
            bars=fake5(day,symbol,rows=(47 if self.partial else 48))
            if self.bad_grid:
                bars[0]["source_timestamp_ms"]+=60000
            return bars
        self.assertIn(period,M.PERIODS)
        self.assertFalse(private)
        return [{"source_timestamp_ms":123}] if self.return_purchased else []

    def stage(self,run_id="111111111111",days=None,symbols=None):
        return M.stage(self.root,
                       self.days if days is None else days,
                       self.symbols if symbols is None else symbols,
                       run_id)

    def test_eight_verified_stockdays_write_exact_224_rows_and_immutable_receipt(self):
        result=self.stage()
        self.assertEqual(result["verified_source_stockdays"],8)
        self.assertEqual(result["purchased_high_cycle_source_blocks"],0)
        self.assertEqual(result["source_5min_original_SHA_receipts_verified"],True)
        self.assertFalse(result["ready_for_production_merge"])
        self.assertFalse(result["ready_for_h5_mirror"])
        self.assertFalse(result["timestamp_conversion_certified"])
        self.assertFalse(result["vendor_physical_units_certified"])
        self.assertTrue(result["no_day_week_month_materialized"])
        self.assertEqual(len(self.queries),32) # 8 stockdays times 5m + 3 higher cycles
        for period,expected in (("15min",128),("30min",64),("60min",32)):
            meta=result["outputs"][period]
            self.assertEqual(meta["rows"],expected)
            path=self.module/meta["private_file"]
            self.assertEqual(M._sha(path),meta["sha256"])
            with pq.ParquetFile(path) as pf:
                self.assertEqual(pf.metadata.num_rows,expected)
                rows=pf.read().to_pylist()
            self.assertEqual(len(rows),expected)
            self.assertEqual(set(x["period"] for x in rows),{period})
            self.assertEqual(set(x["source_period"] for x in rows),{"5min"})
            self.assertEqual(set(x["source_5min_private_sha256"] for x in rows),
                             {self.input_sha})
            self.assertFalse(any(x["time_label_and_vendor_units_certified"] for x in rows))
        receipt=self.stage_root/"111111111111"/"receipt.json"
        self.assertEqual(json.loads(receipt.read_text("utf-8")),result)
        self.assertEqual([x.name for x in receipt.parent.iterdir()
                          if x.suffix==".parquet"],
                         ["15min.parquet","30min.parquet","60min.parquet"])

    def test_any_purchased_15_30_60min_block_refuses_entire_batch_before_disk(self):
        self.return_purchased=True
        with self.assertRaisesRegex(ValueError,"Purchased high-cycle"):
            self.stage()
        self.assertFalse(self.stage_root.exists())

    def test_partial_source_47_bars_refuses_entire_batch(self):
        self.partial=True
        with self.assertRaisesRegex(ValueError,"incomplete"):
            self.stage()
        self.assertFalse(self.stage_root.exists())

    def test_bad_start_grid_refuses_entire_batch(self):
        self.bad_grid=True
        with self.assertRaisesRegex(ValueError,"grid"):
            self.stage()
        self.assertFalse(self.stage_root.exists())

    def test_source_sha_receipt_disagreement_refuses_before_market_query(self):
        self.input.write_bytes(b"changed untrusted source")
        with self.assertRaisesRegex(ValueError,"changed H5|changed H5 5min|changed"):
            self.stage()
        self.assertEqual(self.queries,[])
        self.assertFalse(self.stage_root.exists())

    def test_existing_run_and_invalid_dates_or_symbols_rejected(self):
        self.stage(days=["2026-10-13"],symbols=["SH600000"])
        with self.assertRaisesRegex(ValueError,"overwrite"):
            self.stage(days=["2026-10-13"],symbols=["SH600000"])
        for d in (["2026-09-30"],["2026-10-13","2026-10-13"]):
            with self.subTest(days=d):
                with self.assertRaises(ValueError):
                    self.stage(run_id="222222222222",days=d)
        for symbols in (["SH600000","SH600000"],["bad-symbol"]):
            with self.subTest(symbols=symbols):
                with self.assertRaises(ValueError):
                    self.stage(run_id="222222222222",symbols=symbols)
        with self.assertRaisesRegex(ValueError,"hex"):
            self.stage(run_id="bad-runid")

    def test_stage_root_symlink_escape_rejected(self):
        outside=Path(self.tmp.name)/"outside"
        outside.mkdir()
        self.stage_root.parent.mkdir(parents=True,exist_ok=True)
        try:
            self.stage_root.symlink_to(outside,target_is_directory=True)
        except OSError:
            self.skipTest("Windows test user cannot create a symlink")
        with self.assertRaisesRegex(ValueError,"symlink"):
            self.stage()
        self.assertFalse((outside/"111111111111").exists())

    def test_source_5min_receipt_provenance_not_optional(self):
        with patch.object(M.C.ALL.MINUTE,"_safe_private_file",return_value=None):
            with self.assertRaisesRegex(ValueError,"Missing previously SAFE"):
                self.stage()
        self.assertFalse(self.stage_root.exists())

if __name__=="__main__":
    unittest.main()
