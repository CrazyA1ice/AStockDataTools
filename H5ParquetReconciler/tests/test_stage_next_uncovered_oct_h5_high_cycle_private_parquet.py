"""Synthetic next-uncovered Oct 5m private highcycle stage with SHA receipt registry."""
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
    "test_next_unstaged_oct_highcycle",
    HERE.parent/"tools"/"stage-next-uncovered-oct-h5-high-cycle-private-parquet.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
DAY=date(2026,10,13)

def fake5(day,symbol):
    return [{
        "source_timestamp_ms":t,
        "symbol":symbol,"period":"5min","trading_date":day.isoformat(),
        "value_source":"h5_only_complete_stockday",
        "open":10+i/100.0,"high":10.3+i/100.0,
        "low":9.8+i/100.0,"close":10.1+i/100.0,
        "volume":100.0,"amount":1000.0,
    } for i,t in enumerate(M.S.C.grid_timestamps(day))]

class NextUnstagedOctPrivateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module=Path(self.tmp.name)/"repo"/"H5ParquetReconciler"
        self.module.mkdir(parents=True)
        self.market=Path(self.tmp.name)/"market"
        self.market.mkdir()
        self.source=self.module/"work"/"unified_parquet"/"minute_complete_day"/"mock.parquet"
        self.source.parent.mkdir(parents=True)
        self.stage_root=self.module/"work"/"unified_parquet"/"oct_high_cycle_staging"
        self.canary=("SH600000","SZ000001")
        self.all_new=tuple(f"SH601{i:03d}" for i in range(86))
        self.source_symbols=self.canary+self.all_new
        self.purchased_cycle=None
        self.queries=[]
        self.create_inventory()
        self.receipt_sha=hashlib.sha256(self.source.read_bytes()).hexdigest()
        patches=[
            patch.object(M.S,"MODULE",self.module),
            patch.object(M.S,"STAGE_ROOT",self.stage_root),
            patch.object(M.S,"source_receipt",side_effect=self.receipt),
            patch.object(M.S.C,"_query",side_effect=self.query),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # Stage BOTH real shape/previous receipts, not artificially simulated:
        # canary 2 x 4 days = 8 stockdays (224 bars), first auto-batch
        # 16 x Oct 13 = 16 stockdays (448 bars).
        canary_dates=["2026-10-08","2026-10-09","2026-10-12","2026-10-13"]
        self.canary_receipt=M.S.stage(self.market,canary_dates,self.canary,"aaaaaaaaaaaa")
        self.old_receipt=M.S.stage(
            self.market,["2026-10-13"],self.all_new[:16],"bbbbbbbbbbbb")

    def create_inventory(self):
        rows=[]
        stamps=M.S.C.grid_timestamps(DAY)
        for sym in self.source_symbols:
            rows.extend({
                "ts":stamp,"symbol":sym,
                "value_source":"h5_only_complete_stockday",
                "period":"5min",
            } for stamp in stamps)
        rows.extend({
            "ts":stamp,"symbol":"SH600099",
            "value_source":"h5_only_complete_stockday",
            "period":"5min",
        } for stamp in stamps[:-1])
        schema=pa.schema([
            pa.field("ts",pa.int64()),
            pa.field("symbol",pa.string()),
            pa.field("value_source",pa.string()),
            pa.field("period",pa.string()),
        ])
        pq.write_table(pa.Table.from_pylist(rows,schema=schema),
                       self.source,compression="zstd")

    def receipt(self,day):
        self.assertEqual(day.year,2026)
        self.assertEqual(day.month,10)
        return self.source,self.receipt_sha

    def query(self,root,symbol,period,day,*,private=False):
        self.queries.append((day.isoformat(),symbol,period,private))
        if period=="5min":
            self.assertTrue(private)
            return fake5(day,symbol)
        self.assertFalse(private)
        return [{"source_timestamp_ms":1}] if self.purchased_cycle==period else []

    def inventory_paths(self):
        return sorted(str(p.relative_to(self.stage_root)) for p in
                      self.stage_root.rglob("*") if p.is_file())

    def test_inventory_skips_exact_24_previous_stockdays(self):
        before=self.inventory_paths()
        report=M.plan(DAY,batch_size=64)
        self.assertEqual(report["previous_private_runs_sha_rechecked"],2)
        self.assertEqual(report["previous_private_stockdays_sha_rechecked"],24)
        self.assertEqual(report["h5_5min_complete_eligible_stockdays"],88)
        self.assertEqual(report["already_staged_complete_eligible_this_day"],18)
        self.assertEqual(report["uncovered_complete_eligible_this_day"],70)
        self.assertEqual(report["chosen_stockdays"],64)
        self.assertEqual(report["remaining_uncovered_stockdays_after_selection"],6)
        self.assertEqual(report["selected_symbols"],list(self.all_new[16:80]))
        self.assertFalse(report["new_private_or_production_files_written"])
        self.assertEqual(before,self.inventory_paths())

    def test_next_64_stockdays_create_1792_private_highcycle_rows(self):
        report=M.stage_next(self.market,DAY,"cccccccccccc")
        self.assertTrue(report["only_unstaged_candidates_selected"])
        self.assertEqual(report["plan"]["chosen_stockdays"],64)
        self.assertNotIn("selected_symbols",report["plan"])
        written=report["stage"]
        self.assertEqual(written["symbols"],list(self.all_new[16:80]))
        self.assertEqual(written["verified_source_stockdays"],64)
        self.assertEqual({p:written["outputs"][p]["rows"] for p in M.S.PERIODS},
                         {"15min":1024,"30min":512,"60min":256})
        self.assertEqual(sum(written["outputs"][p]["rows"] for p in M.S.PERIODS),
                         1792)
        self.assertFalse(written["ready_for_production_merge"])
        self.assertEqual(M.existing_stockdays()[1],3)
        for p in M.S.PERIODS:
            target=self.module/written["outputs"][p]["private_file"]
            self.assertEqual(M.S._sha(target),written["outputs"][p]["sha256"])
        with self.assertRaisesRegex(ValueError,"Already|No previously unstaged"):
            # A newly created, different run ID may NOT overlap any of
            # the just-staged symbols if selection is repeated.
            M.S.stage(self.market,[DAY.isoformat()],
                      list(self.all_new[16:80]),"dddddddddddd")
        # Old base stager has NO receipt-overlap blocking by design: only the
        # next-uncovered selector protects against repeated selection.

    def test_repeated_plan_moves_forward_without_duplicates(self):
        first=M.stage_next(self.market,DAY,"cccccccccccc")
        self.assertEqual(first["stage"]["verified_source_stockdays"],64)
        second=M.plan(DAY)
        self.assertEqual(second["chosen_stockdays"],6)
        self.assertEqual(second["selected_symbols"],list(self.all_new[80:]))
        following=M.stage_next(self.market,DAY,"dddddddddddd")
        self.assertEqual(following["stage"]["verified_source_stockdays"],6)
        self.assertEqual(following["stage"]["outputs"]["15min"]["rows"],96)
        before=self.inventory_paths()
        with self.assertRaisesRegex(ValueError,"No previously unstaged"):
            M.stage_next(self.market,DAY,"eeeeeeeeeeee")
        self.assertEqual(before,self.inventory_paths())

    def test_tampered_existing_parquet_sha_fails_before_new_write(self):
        file=self.stage_root/"bbbbbbbbbbbb"/"15min.parquet"
        with file.open("ab") as f:
            f.write(b"corrupted")
        before=self.inventory_paths()
        with self.assertRaisesRegex(ValueError,"candidate Parquet changed"):
            M.stage_next(self.market,DAY,"cccccccccccc")
        self.assertEqual(before,self.inventory_paths())

    def test_malformed_existing_receipt_fails_closed(self):
        receipt=self.stage_root/"bbbbbbbbbbbb"/"receipt.json"
        doc=json.loads(receipt.read_text("utf-8"))
        doc["ready_for_production_merge"]=True
        receipt.write_text(json.dumps(doc),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"identity/safety"):
            M.plan(DAY)
        self.assertFalse((self.stage_root/"cccccccccccc").exists())

    def test_partial_stage_directory_without_receipt_blocks_selection(self):
        partial=self.stage_root/"cccccccccccc"
        partial.mkdir()
        with self.assertRaisesRegex(ValueError,"Incomplete existing private stage"):
            M.plan(DAY)
        self.assertFalse((partial/"15min.parquet").exists())

    def test_purchased_highcycle_detected_before_any_new_stage(self):
        self.purchased_cycle="30min"
        with self.assertRaisesRegex(ValueError,"Purchased high-cycle"):
            M.stage_next(self.market,DAY,"cccccccccccc")
        self.assertFalse((self.stage_root/"cccccccccccc").exists())

    def test_invalid_bounds_and_non_oct_date_rejected(self):
        for bad in (0,101,-1,1.2,True):
            with self.subTest(batch_size=bad):
                with self.assertRaisesRegex(ValueError,"Bounded batch size"):
                    M.plan(DAY,batch_size=bad)
        with self.assertRaisesRegex(ValueError,"October 2026"):
            M.plan(date(2026,9,30))
        self.assertFalse((self.stage_root/"cccccccccccc").exists())

if __name__=="__main__":
    unittest.main()
