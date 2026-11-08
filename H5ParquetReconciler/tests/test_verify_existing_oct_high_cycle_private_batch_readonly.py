"""End-to-end synthetic read-only recovery of an already-written Oct private batch."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "test_readonly_existing_oct_stage_recovery",
    HERE.parent/"tools"/"verify-existing-oct-high-cycle-private-batch-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
DAY=date(2026,10,13)

def fake5(day,sym):
    stamps=M.S.C.grid_timestamps(day)
    return [{
        "symbol":sym,"period":"5min","trading_date":day.isoformat(),
        "source_timestamp_ms":t,"value_source":"h5_only_complete_stockday",
        "open":10.0+i/100,"high":10.3+i/100,
        "low":9.8+i/100,"close":10.1+i/100,
        "volume":100.0,"amount":1000.0,
    } for i,t in enumerate(stamps)]

class ReadonlyExistingOctHighcycleBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module=Path(self.tmp.name)/"repo"/"H5ParquetReconciler"
        self.module.mkdir(parents=True)
        self.stage_root=self.module/"work"/"unified_parquet"/"oct_high_cycle_staging"
        self.source=self.module/"work"/"unified_parquet"/"minute_complete_day"/"source.parquet"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"mocked complete safe 5-minute source")
        self.source_sha=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.market=Path(self.tmp.name)/"market"
        self.market.mkdir()
        self.stocks=[f"SH600{i:03d}" for i in range(16,32)]
        self.purchased_cycle=None
        self.calls=[]
        patches=[
            patch.object(M.S,"MODULE",self.module),
            patch.object(M.S,"STAGE_ROOT",self.stage_root),
            patch.object(M.S,"source_receipt",side_effect=self.receipt),
            patch.object(M.S.C,"_query",side_effect=self.query),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.original=M.S.stage(self.market,[DAY.isoformat()],self.stocks,"bbbbbbbbbbbb")
        self.hashes=[self.original["outputs"][p]["sha256"] for p in M.S.PERIODS]
        self.before=sorted(str(p.relative_to(self.stage_root)) for p in
                           self.stage_root.rglob("*") if p.is_file())

    def receipt(self,day):
        self.assertEqual(day,DAY)
        return self.source,self.source_sha

    def query(self,root,symbol,period,day,*,private=False):
        self.calls.append((symbol,period,private))
        if period=="5min":
            self.assertTrue(private)
            return fake5(day,symbol)
        self.assertFalse(private)
        return [{"dummy":"already purchased"}] if self.purchased_cycle==period else []

    def verify(self,**kw):
        return M.verify(self.market,*self.hashes,**kw)

    def test_recovered_previous_448_rows_exact_and_no_new_files(self):
        result=self.verify()
        self.assertEqual(result["status"],
                         "verified_existing_oct_13_private_high_cycle_batch_readonly")
        self.assertEqual(result["total_rows"],448)
        self.assertEqual(result["verified_source_stockdays"],16)
        self.assertEqual(result["period_rows"],
                         {"15min":256,"30min":128,"60min":64})
        self.assertEqual(result["run_id"],"bbbbbbbbbbbb")
        self.assertTrue(result["full_row_by_row_rederived_readback"])
        self.assertFalse(result["new_private_or_production_files_written"])
        self.assertFalse(result["production_activated"])
        self.assertFalse(result["ready_for_production_merge"])
        self.assertFalse(result["independent_vendor_units_certified"])
        self.assertEqual(self.before,sorted(str(p.relative_to(self.stage_root))
                         for p in self.stage_root.rglob("*") if p.is_file()))

    def test_missing_or_wrong_hash_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"exact 15min SHA"):
            M.find_existing("0"*64)
        with self.assertRaisesRegex(ValueError,"SHA"):
            M.verify(self.market,self.hashes[0],"f"*64,self.hashes[2])
        with self.assertRaisesRegex(ValueError,"precise lowercase SHA"):
            M.find_existing("invalid")
        self.assertEqual(self.before,sorted(str(p.relative_to(self.stage_root))
                         for p in self.stage_root.rglob("*") if p.is_file()))

    def test_source_mutation_fails_without_writing(self):
        self.source.write_bytes(b"changed source contents")
        with self.assertRaisesRegex(ValueError,"changed"):
            self.verify()

    def test_highcycle_now_purchased_refuses_revalidation(self):
        self.purchased_cycle="30min"
        with self.assertRaisesRegex(ValueError,"Purchased high-cycle"):
            self.verify()

    def test_changed_receipt_flags_rejected(self):
        path=self.stage_root/"bbbbbbbbbbbb"/"receipt.json"
        doc=json.loads(path.read_text("utf-8"))
        doc["ready_for_production_merge"]=True
        path.write_text(json.dumps(doc),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"safety flags"):
            self.verify()

    def test_tampered_private_parquet_rejected(self):
        file=self.stage_root/"bbbbbbbbbbbb"/"15min.parquet"
        with file.open("ab") as f:
            f.write(b"altered")
        with self.assertRaisesRegex(ValueError,"source file/receipt SHA"):
            self.verify()

if __name__=="__main__":
    unittest.main()
