"""Only locally supplied temp checkpoint receipts; no commercial market reads."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "explicit_sep_source_proven_minute_native_h5_waves",
    HERE.parent/"tools"/"run-real-2026-september-purchased-minute-h5-resumable-waves.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

class AcceptedSeptemberBatchOrchestrator(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir=Path(temp.name)
        self.dir.mkdir(exist_ok=True)
        patcher=patch.object(M.R,"LIVE",self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher=patch.object(M.R,"exclusive_working_h5_lock",nullcontext)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.completed=[]

    def write_done(self,first,last,n1=14,n5=4):
        folder=self.dir/"batches"/("batch_"+first+"_"+last)
        folder.mkdir(parents=True,exist_ok=True)
        receipt={
            "status":M.R.STATUS,"dataset_sha256":M.R.SOURCE_SHA,
            "window":[first,last],
            "purchased_parquet_rows_processed_by_period":
                {"1min":n1,"5min":n5},
            "all_stock_swaps_completed_and_journal_committed":True,
            "original_purchased_parquet_or_hikyuu_H5_modified":False,
            "original_markets_never_opened_in_write_mode":True,
            "production_H5_activated":False,
            "numeric_unit_mapping_vendor_certified":False,
            "complete_2011_2026_minute_history":False,
            "full_private_six_file_H5_sha256":{
                name:"a"*64 for name in M.R.H5_NAMES},
        }
        (folder/"done.json").write_text(json.dumps(receipt),encoding="utf-8")

    def set_state(self,already):
        (self.dir/"initialized.json").write_text(
            json.dumps({"completed_windows":already}),encoding="utf-8")

    def test_explicit_source_proven_four_weeks_no_weekends_or_already_mirrored(self):
        self.assertEqual(M.validate_windows(),16)
        self.assertEqual(len(M.WAVES),4)
        self.assertEqual(M.WAVES[0],("2026-09-21","2026-09-22"))
        self.assertEqual(M.WAVES[-1],("2026-09-01","2026-09-04"))

    def test_excess_window_limit_or_unverified_source_days_rejected(self):
        with self.assertRaisesRegex(ValueError,"one to four"):
            M.run_all("unused","unused",max_waves=5)
        with patch.object(M,"WAVES",(("2026-09-23","2026-09-24"),)):
            with self.assertRaisesRegex(ValueError,"Unexpected"):
                M.validate_windows()

    def test_two_accepted_windows_run_in_order_and_report_real_receipts(self):
        self.set_state([])
        called=[]
        def fake_run(_root,_manifest,first,last):
            called.append((first,last))
            self.write_done(first,last)
            self.completed.append([first,last])
            self.set_state(self.completed)
        with patch.object(M.R,"run",fake_run):
            report=M.run_all("unused","unused",max_waves=2)
        self.assertEqual(called,list(M.WAVES[:2]))
        self.assertEqual(report["purchased_source_rows_processed_in_these_windows"],
                         {"1min":28,"5min":8})
        self.assertFalse(report["production_h5_activated"])
        self.assertEqual(report["window_count"],2)

    def test_completed_window_skipped_even_if_next_window_is_partly_written(self):
        # A later interrupted H5 batch changes the workspace SHA, therefore
        # re-invoking the prior R.run would incorrectly reject continuation.
        first,second=M.WAVES[:2]
        self.write_done(*first)
        self.completed=[list(first)]
        self.set_state(self.completed)
        called=[]
        def fake_run(_root,_manifest,a,b):
            called.append((a,b))
            self.write_done(a,b,22,6)
            self.completed.append([a,b])
            self.set_state(self.completed)
        with patch.object(M.R,"run",fake_run):
            result=M.run_all("unused","unused",max_waves=2)
        self.assertEqual(called,[second])
        self.assertEqual(result["purchased_source_rows_processed_in_these_windows"],
                         {"1min":36,"5min":10})

    def test_interrupt_and_repeat_does_not_double_commit_prior_success(self):
        self.set_state([])
        first,second=M.WAVES[:2]
        def crash_after_first(_root,_manifest,a,b):
            if (a,b)==first:
                self.write_done(a,b)
                self.completed.append([a,b])
                self.set_state(self.completed)
            else:
                raise RuntimeError("synthetic interrupted H5")
        with patch.object(M.R,"run",crash_after_first):
            with self.assertRaisesRegex(RuntimeError,"interrupted H5"):
                M.run_all("unused","unused",max_waves=2)
        called=[]
        def next_run(_root,_manifest,a,b):
            called.append((a,b))
            self.write_done(a,b)
            self.completed.append([a,b])
            self.set_state(self.completed)
        with patch.object(M.R,"run",next_run):
            M.run_all("unused","unused",max_waves=2)
        self.assertEqual(called,[second])

    def test_missing_receipt_never_skips_allegedly_completed_window(self):
        self.set_state([list(M.WAVES[0])])
        with self.assertRaisesRegex(ValueError,"Missing committed"):
            M.run_all("unused","unused",max_waves=1)

    def test_malformed_or_future_safe_receipt_rejected(self):
        first,last=M.WAVES[0]
        self.write_done(first,last)
        file=self.dir/"batches"/("batch_"+first+"_"+last)/"done.json"
        doc=json.loads(file.read_text(encoding="utf-8"))
        doc["window"]=["2026-10-14","2026-10-14"]
        file.write_text(json.dumps(doc),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Unverified purchased-minute"):
            M.validate_done(first,last)

if __name__=="__main__":
    unittest.main()
