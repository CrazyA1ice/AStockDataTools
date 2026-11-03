"""Mock-only launcher tests: never spawn worker or touch licensed market data."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE=Path(__file__).resolve().parent.parent/"tools"
s=importlib.util.spec_from_file_location("backfill_launcher_test",
    HERE/"launch-minute-year-backfill.py")
L=importlib.util.module_from_spec(s)
s.loader.exec_module(L)

class BackfillLaunchTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="minute-backfill-launch-")
        self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name)
        self.root=self.base/"market"
        (self.root/"HikyuuData").mkdir(parents=True)
        self.jobs=self.base/"work"/"minute_gui"/"jobs"
        self.lock=self.base/"work"/"minute_gui"/"active.lock"
        for obj,attr,value in (
            (L,"JOBS",self.jobs),
            (L.GUI,"JOBS",self.jobs),
            (L.W,"JOBS",self.jobs),
            (L.W,"LOCK",self.lock),
        ):
            p=patch.object(obj,attr,value)
            p.start()
            self.addCleanup(p.stop)

    def prior(self,status):
        folder=self.jobs/"123456789abc"
        folder.mkdir(parents=True,exist_ok=True)
        config={"job_id":folder.name,"root":str(self.root.resolve()),
                "start":"2026-01-01","end":"2026-10-13",
                "mode":"REAL_PRIVATE_PURCHASED_FIRST_1MIN_5MIN_PARQUET_ONLY"}
        (folder/"config.json").write_text(json.dumps(config),encoding="utf-8")
        (folder/"state.json").write_text(json.dumps({
            "job_id":folder.name,"status":status}),encoding="utf-8")
        return folder

    def test_new_year_run_launches_one_detached_process(self):
        with patch.object(L.GUI,"launch",return_value=SimpleNamespace(pid=12345)) as spawn,patch.object(
            L.secrets,"token_hex",return_value="abcdef123456"):
            r=L.launch(self.root,"2026-01-01","2026-10-13")
        self.assertEqual(r["status"],"new_real_backfill_requested_detached")
        self.assertTrue(r["launched"])
        self.assertEqual(r["job_id"],"abcdef123456")
        self.assertEqual(r["worker_pid"],12345)
        self.assertEqual(spawn.call_count,1)
        self.assertFalse(spawn.call_args.kwargs["resume"])

    def test_existing_failed_job_resumes_not_duplicate(self):
        self.prior("failed")
        with patch.object(L.GUI,"launch",return_value=SimpleNamespace(pid=12345)) as spawn:
            r=L.launch(self.root,"2026-01-01","2026-10-13")
        self.assertEqual(r["job_id"],"123456789abc")
        self.assertEqual(r["status"],"resume_requested_detached")
        self.assertTrue(spawn.call_args.kwargs["resume"])

    def test_completed_job_not_rewritten(self):
        self.prior("completed")
        with patch.object(L.GUI,"launch") as spawn:
            r=L.launch(self.root,"2026-01-01","2026-10-13")
        self.assertEqual(r["status"],"already_completed_no_new_market_writes")
        spawn.assert_not_called()

    def test_active_writer_lock_does_not_spawn(self):
        with L.W.exclusive_lock(self.lock), patch.object(L.GUI,"launch") as spawn:
            r=L.launch(self.root,"2026-01-01","2026-10-13")
        self.assertEqual(r["status"],"another_minute_writer_active_no_new_job")
        spawn.assert_not_called()

    def test_source_window_and_dry_run(self):
        with self.assertRaisesRegex(ValueError,"beyond last verified"):
            L.validate(self.root,"2026-01-01","2026-11-03")
        with self.assertRaisesRegex(ValueError,"One calendar-year"):
            L.validate(self.root,"2025-12-01","2026-01-02")
        with patch.object(L.GUI,"launch") as spawn:
            r=L.launch(self.root,"2026-01-01","2026-10-13",dry_run=True)
        self.assertEqual(r["status"],"dry_run_no_child_process")
        spawn.assert_not_called()

if __name__=="__main__":
    unittest.main(verbosity=2)
