"""Bounded deterministic October 2026 H5-only stockday discovery + private stage."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "test_oct_highcycle_autobatch",
    HERE.parent/"tools"/"auto-batch-2026-oct-h5-high-cycle-private-parquet.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

DAY=date(2026,10,13)

def native_five(day,symbol):
    return [{
        "source_timestamp_ms":t, "symbol":symbol,"period":"5min",
        "trading_date":day.isoformat(),"value_source":"h5_only_complete_stockday",
        "open":10.0,"high":10.3,"low":9.8,"close":10.1,
        "volume":100.0,"amount":1000.0,
    } for t in M.S.C.grid_timestamps(day)]

class AutobatchHighCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module=Path(self.tmp.name)/"repo"/"H5ParquetReconciler"
        self.module.mkdir(parents=True)
        self.source=(self.module/"work"/"unified_parquet"/"minute_complete_day"/"source.parquet")
        self.source.parent.mkdir(parents=True)
        self.market=Path(self.tmp.name)/"market"
        self.market.mkdir()
        self.days=[DAY]
        self.symbols=["SH600000"]+[f"SH600{k:03d}" for k in range(10,29)]
        self.native=tuple(M.S.C.grid_timestamps(DAY))
        self.create_source()
        self.stage_root=self.module/"work"/"unified_parquet"/"oct_high_cycle_staging"
        self.patches=[
            patch.object(M.S,"MODULE",self.module),
            patch.object(M.S,"STAGE_ROOT",self.stage_root),
            patch.object(M.S,"source_receipt",side_effect=self.receipt),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.queries=[]
        self.purchased_cycle=None
        self.query_patch=patch.object(M.S.C,"_query",side_effect=self.query)
        self.query_patch.start()
        self.addCleanup(self.query_patch.stop)

    def create_source(self):
        rows=[]
        for sym in self.symbols:
            rows.extend({
                "ts":stamp,"symbol":sym,
                "value_source":"h5_only_complete_stockday","period":"5min",
            } for stamp in self.native)
        rows.extend({
            "ts":stamp,"symbol":"SH600099",
            "value_source":"h5_only_complete_stockday","period":"5min",
        } for stamp in self.native[:-1])
        rows.extend({
            "ts":stamp,"symbol":"SH600098",
            "value_source":"h5_only_complete_stockday","period":"5min",
        } for stamp in (self.native[:-1]+(self.native[-2],)))
        # Purchased 5m conflicts with a seemingly complete H5 source.
        rows.append({"ts":self.native[0],"symbol":"SH600015",
                     "value_source":"purchased_parquet","period":"5min"})
        schema=pa.schema([
            pa.field("ts",pa.int64()),pa.field("symbol",pa.string()),
            pa.field("value_source",pa.string()),pa.field("period",pa.string()),
        ])
        pq.write_table(pa.Table.from_pylist(rows,schema=schema),self.source,
                       compression="zstd")
        self.expected_sha=hashlib.sha256(self.source.read_bytes()).hexdigest()

    def receipt(self,day):
        self.assertEqual(day,DAY)
        return self.source,self.expected_sha

    def query(self,root,symbol,period,day,*,private=False):
        self.queries.append((symbol,period,private))
        if period=="5min":
            self.assertTrue(private)
            return native_five(day,symbol)
        self.assertFalse(private)
        return [{"symbol":symbol}] if self.purchased_cycle==period else []

    def test_inventory_excludes_canary_purchased_partial_and_duplicate(self):
        inv=M.discover(DAY)
        self.assertEqual(inv["source_5min_sha256"],self.expected_sha)
        self.assertEqual(inv["h5_source_symbols_observed"],22)
        self.assertEqual(inv["candidate_complete_stockdays"],18)
        self.assertEqual(inv["excluded_by_reason"]["already_staged_canary_symbol"],1)
        self.assertEqual(inv["excluded_by_reason"]["purchased_five_minute_priority"],1)
        self.assertEqual(inv["excluded_by_reason"]["incomplete_or_invalid_h5_five_minute_grid"],2)
        self.assertEqual(len(inv["eligible_symbols"]),18)
        self.assertNotIn("SH600000",inv["eligible_symbols"])
        self.assertNotIn("SH600015",inv["eligible_symbols"])
        self.assertEqual(self.queries,[])
        self.assertFalse(self.stage_root.exists())

    def test_real_private_stage_16_new_symbols_448_rows_and_receipt(self):
        result=M.run(self.market,DAY,"111111111111",batch_size=16)
        self.assertEqual(result["selected_stockdays"],16)
        self.assertEqual(result["remaining_after_batch"],2)
        self.assertEqual(result["source_inventory"]["candidate_complete_stockdays"],18)
        self.assertNotIn("eligible_symbols",result["source_inventory"])
        stage=result["stage"]
        self.assertEqual(stage["verified_source_stockdays"],16)
        self.assertEqual({k:stage["outputs"][k]["rows"] for k in M.S.PERIODS},
                         {"15min":256,"30min":128,"60min":64})
        self.assertEqual(len(self.queries),64)
        self.assertFalse(stage["ready_for_production_merge"])
        self.assertFalse(stage["ready_for_h5_mirror"])
        for period in M.S.PERIODS:
            path=self.module/stage["outputs"][period]["private_file"]
            self.assertEqual(M.S._sha(path),stage["outputs"][period]["sha256"])
        r=self.stage_root/"111111111111"/"receipt.json"
        self.assertEqual(json.loads(r.read_text("utf-8")),stage)

    def test_second_deterministic_batch_and_exhaustion(self):
        result=M.run(self.market,DAY,"222222222222",batch_size=16,
                     batch_index=1)
        self.assertEqual(result["selected_stockdays"],2)
        self.assertEqual(result["remaining_after_batch"],0)
        self.assertEqual(result["stage"]["outputs"]["15min"]["rows"],32)
        with self.assertRaisesRegex(ValueError,"No complete"):
            M.run(self.market,DAY,"333333333333",batch_size=16,batch_index=2)
        self.assertFalse((self.stage_root/"333333333333").exists())

    def test_mutated_receipt_sha_and_invalid_period_fail_before_stage(self):
        self.source.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError,"SHA changed"):
            M.discover(DAY)
        self.assertEqual(self.queries,[])
        self.assertFalse(self.stage_root.exists())

    def test_purchased_high_cycle_blocks_selected_batch_before_write(self):
        self.purchased_cycle="30min"
        with self.assertRaisesRegex(ValueError,"Purchased high-cycle"):
            M.run(self.market,DAY,"222222222222",batch_size=16)
        self.assertFalse(self.stage_root.exists())

    def test_bad_dates_and_page_size_rejected(self):
        for day in (date(2026,9,30),date(2027,10,13)):
            with self.subTest(day=day):
                with self.assertRaisesRegex(ValueError,"October 2026"):
                    M.discover(day)
        for n,idx in ((0,0),(101,0),(16,-1),(16,10001)):
            with self.subTest(size=n,index=idx):
                with self.assertRaisesRegex(ValueError,"bounded batch"):
                    M.run(self.market,DAY,"444444444444",
                          batch_size=n,batch_index=idx)
        self.assertFalse(self.stage_root.exists())

    def test_symlink_source_refused_if_windows_supports_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            link=Path(root)/"symlink.parquet"
            try:
                link.symlink_to(self.source)
            except OSError:
                self.skipTest("Windows symlink unavailable")
            with patch.object(M.S,"source_receipt",
                              return_value=(link,self.expected_sha)):
                with self.assertRaisesRegex(ValueError,"Unsafe"):
                    M.discover(DAY)
            self.assertFalse(self.stage_root.exists())

if __name__=="__main__":
    unittest.main()
