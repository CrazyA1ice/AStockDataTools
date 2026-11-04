"""Focused, offline worker tests. No real market files touched, no GUI display.
Real writing and full source hashing remain in the existing batch test suite.
"""
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
    "minute_private_gui_worker_test",
    HERE.parent/"tools"/"minute-private-parquet-worker.py")
W=importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

class MinuteBackgroundGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.reports=self.root/"reports"
        self.reports.mkdir()
        self.jobs=self.root/"work"/"minute_gui"/"jobs"
        self.fake_market=self.root/"market"
        self.fake_market.mkdir()

    def test_frontend_job_precreated_log_dir_and_no_overwrite(self):
        with patch.object(W,"JOBS",self.jobs):
            folder=self.jobs/"abababababab"
            folder.mkdir(parents=True)
            (folder/"worker-stdout.log").write_text("new worker\n")
            job=W.new_job("abababababab",self.fake_market,
                          "2026-08-10","2026-08-12")
            self.assertEqual(job,folder)
            config=json.loads((job/"config.json").read_text())
            self.assertEqual(config["weekdays"],[
                "2026-08-10","2026-08-11","2026-08-12"])
            self.assertTrue((job/"worker-stdout.log").is_file())
            with self.assertRaisesRegex(ValueError,"already allocated"):
                W.new_job("abababababab",self.fake_market,
                          "2026-08-10","2026-08-12")
            with self.assertRaisesRegex(ValueError,"Choose a date"):
                W.weekdays("2026-10-13","2026-10-08")

    def test_sha_verified_prior_complete_day_is_skipped(self):
        day="2026-08-24"
        child="aaaaaaaaaaaa"
        report=self.reports/f"minute-batch-unified-20260824-{child}.json"
        stage={
            "period_results":{
                p:{"private_parquet_rows":1,
                   "standardized_minute_key_contract":W.CONTRACT[p]}
                for p in ("1min","5min")
            }}
        union={"periods":{p:{"unified_rows":240 if p=="1min" else 48,
                            "unified_parquet_sha256":"x"*64,
                            "standardized_minute_key_contract":W.CONTRACT[p]}
                          for p in ("1min","5min")}}
        report.write_text("{}")
        with patch.object(W,"REPORTS",self.reports),patch.object(
                W.B,"verified_completed",return_value=(stage,union)) as f:
            found=W.verified_existing_batch(day)
        self.assertEqual(found["status"],"sha_reused_existing_verified_day")
        self.assertEqual(found["1min"],240)
        self.assertEqual(found["5min"],48)
        self.assertEqual(f.call_count,1)
        self.assertEqual(report.read_text(),"{}")

    def test_interrupted_attempt_is_preserved_and_new_child_is_used(self):
        day="2026-08-25"
        jobid="abcdef012345"
        child0=W.run_id(jobid,day,0)
        nested0=hashlib.sha256((child0+":"+day).encode("ascii")).hexdigest()[:12]
        old=self.root/"work"/"unified_parquet"/"minute_gap_staging"/nested0
        old.mkdir(parents=True)
        (old/"incomplete.txt").write_text("DO NOT MODIFY")
        def fake_paths(d,child):
            name=d.strftime("%Y%m%d")
            return (self.reports/f"minute-batch-stage-{name}-{child}.json",
                    self.reports/f"minute-batch-unified-{name}-{child}.json")
        def fake_real_process(root,a,b,run_id,out,*,max_days):
            child=hashlib.sha256((run_id+":"+day).encode("ascii")).hexdigest()[:12]
            stage,unified=fake_paths(a,child)
            stage.write_text(json.dumps({
                "period_results":{p:{
                    "private_parquet_rows":1,
                    "standardized_minute_key_contract":W.CONTRACT[p]}
                    for p in ("1min","5min")}}))
            unified.write_text(json.dumps({"source_day":day,
                "periods":{p:{
                    "unified_rows":240 if p=="1min" else 48,
                    "standardized_minute_key_contract":W.CONTRACT[p]}
                    for p in ("1min","5min")}}))
            Path(out).write_text('{"status":"mock_written"}')
            return {"status":"mock_written"}
        journal=self.root/"work"/"minute_gui"/"jobs"/jobid
        journal.mkdir(parents=True)
        with patch.object(W,"REPORTS",self.reports),patch.object(
                W,"MODULE",self.root),patch.object(
                W.B,"receipt_paths",side_effect=fake_paths),patch.object(
                W.B,"process",side_effect=fake_real_process):
            result=W.process_one(day,jobid,0,self.fake_market,journal)
        self.assertEqual(result["status"],"finished_verified")
        self.assertEqual(result["attempt"],1)
        self.assertEqual(result["1min"],240)
        self.assertEqual(result["5min"],48)
        self.assertEqual((old/"incomplete.txt").read_text(),"DO NOT MODIFY")

if __name__=="__main__":
    unittest.main(verbosity=2)
