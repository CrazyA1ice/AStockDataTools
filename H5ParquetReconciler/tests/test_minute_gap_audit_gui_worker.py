"""Synthetic safe dashboard worker tests: never touch real market data."""
import contextlib
import hashlib
import importlib.util
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(tag,path):
    spec=importlib.util.spec_from_file_location(tag,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


W=load("synthetic_minute_gap_audit_gui_worker",
       TOOLS/"minute-gap-audit-gui-worker.py")
F=load("synthetic_minute_gap_gui_fixture",
       HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")


class MinuteAuditDashboardWorkerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=F.RealMinuteGapWrites(
            "test_two_real_private_minute_parquet_files_created_and_read_back")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.base
        self.day1=date(2026,10,12)
        self.day2=date(2026,10,13)
        self.store=self.root/"work"/"unified_parquet"/"minute_key_index"
        self.base=self.root/"work"/"minute_audit_gui"

    def patched(self):
        c=contextlib.ExitStack()
        for mod,key,val in (
            (W,"BASE",self.base),
            (W,"JOBS",self.base/"jobs"),
            (W,"LOCK",self.base/"audit.lock"),
            (W.I,"STORE",self.store),
            (W.I.N.ST,"MODULE",self.root),
            (W.I.N.ST,"WORK",self.root/"work"/"unified_parquet"/"minute_gap_staging"),
            (W.I.N.ST,"REPORTS",self.root/"reports"),
            (W.B.I,"STORE",self.store),
            (W.B.I.N.ST,"MODULE",self.root),
            (W.B.I.N.ST,"WORK",self.root/"work"/"unified_parquet"/"minute_gap_staging"),
            (W.B.I.N.ST,"REPORTS",self.root/"reports"),
        ):
            c.enter_context(patch.object(mod,key,val))
        return c

    def sources(self):
        return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest()
                for dirname in ("AllCycleAStockData","HikyuuData")
                for p in (self.root/dirname).rglob("*") if p.is_file()}

    def test_powershell_launcher_is_ascii_for_windows_powershell_51(self):
        # Windows PowerShell 5.1 interprets UTF-8 without BOM as the active
        # ANSI code page; non-ASCII single-quoted text can break parsing.
        launcher=HERE.parent/"start-minute-gap-audit-gui.ps1"
        data=launcher.read_bytes()
        self.assertTrue(data.isascii(), "PowerShell launcher must stay ASCII")
        text=data.decode("ascii")
        self.assertIn("Start-Process",text)
        self.assertIn("minute-gap-audit-gui.py",text)
        self.assertIn("preflight-minute-gap-audit-gui.py",text)
        self.assertNotIn("& $py -B -c",text)
        self.assertNotIn("minute-private-parquet-worker.py",text)

    def test_python_gui_module_is_syntax_valid_before_pythonw_launch(self):
        import ast
        path=TOOLS/"minute-gap-audit-gui.py"
        ast.parse(path.read_text(encoding="utf-8"),filename=str(path))

    def test_separate_gui_preflight_succeeds_without_powershell_c_quoting(self):
        import subprocess
        import sys
        preflight=TOOLS/"preflight-minute-gap-audit-gui.py"
        gui=TOOLS/"minute-gap-audit-gui.py"
        result=subprocess.run(
            [sys.executable,"-B",str(preflight),"--gui",str(gui)],
            cwd=str(HERE.parent),capture_output=True,text=True,
            encoding="utf-8",timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+"\n"+result.stderr)
        self.assertIn("GUI_PREFLIGHT_OK",result.stdout)

    def test_preflight_rejects_unrelated_python_file(self):
        import subprocess
        import sys
        preflight=TOOLS/"preflight-minute-gap-audit-gui.py"
        wrong=TOOLS/"minute-gap-audit-gui-worker.py"
        result=subprocess.run(
            [sys.executable,"-B",str(preflight),"--gui",str(wrong)],
            cwd=str(HERE.parent),capture_output=True,text=True,
            encoding="utf-8",timeout=30)
        self.assertNotEqual(result.returncode,0)
        self.assertIn("safe source-key audit GUI",result.stderr)

    def test_only_uncovered_dates_get_new_index_shard(self):
        before=self.sources()
        with self.patched():
            W.E.ensure(self.root,self.day1,self.day1,run_id="aabbccddeeff")
            windows=W.plan(self.root,self.day1,self.day2,allow_build=True)
            self.assertEqual([x["mode"] for x in windows],[
                "reuse_existing_index","build_missing_private_index"])
            job=W.start_job(self.root,self.day1,self.day2,True,"123456789abc")
            W.run("123456789abc")
            state=W._job("123456789abc")/"state.json"
            summary=W.json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"],"completed")
            self.assertEqual(summary["windows_done"],2)
            self.assertEqual(summary["days_done"],2)
            self.assertEqual(summary["new_market_gap_keys_accepted"],0)
            self.assertEqual(len(list(self.store.glob("*.sqlite"))),2)
            self.assertEqual(len(list(job.glob("audit-*.json"))),2)
            self.assertEqual(summary["summary_by_period"]["1min"][
                "h5_only_keys_on_full_purchased_absence_days"],240)
        self.assertEqual(self.sources(),before)

    def test_existing_indexes_reused_without_purchased_key_source_rescan(self):
        with self.patched():
            W.E.ensure(self.root,self.day1,self.day2,run_id="aabbccddeeff")
            job=W.start_job(self.root,self.day1,self.day2,False,"123456789abc")
            with patch.object(W.I,"purchased_masks",
                              side_effect=AssertionError("original vendor scan blocked")):
                W.run("123456789abc")
            state=W.json.loads((job/"state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"],"completed")
            self.assertEqual(state["windows_done"],1)
            self.assertEqual(state["days_done"],2)

    def test_no_private_build_permission_is_fail_closed(self):
        with self.patched():
            with self.assertRaisesRegex(ValueError,"Unindexed date range"):
                W.plan(self.root,self.day1,self.day2,allow_build=False)
            self.assertFalse((self.base/"jobs").exists())

    def test_safe_pause_waits_for_current_completed_window(self):
        with self.patched():
            W.E.ensure(self.root,self.day1,self.day1,run_id="aabbccddeeff")
            job=W.start_job(self.root,self.day1,self.day2,True,"123456789abc")
            (job/"pause_after_window.flag").touch()
            W.run("123456789abc")
            state=W.json.loads((job/"state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"],"paused")
            self.assertEqual(state["windows_done"],1)
            self.assertEqual(state["days_done"],1)
            self.assertEqual(len(list(self.store.glob("*.sqlite"))),1)
            self.assertEqual(len(list(job.glob("audit-*.json"))),1)

    def test_multiple_overlapping_indexes_refuse_silent_choice(self):
        with self.patched():
            W.E.ensure(self.root,self.day1,self.day2,run_id="aabbccddeeff")
            W.E.ensure(self.root,self.day2,self.day2,run_id="ffeeddccbbaa")
            with self.assertRaisesRegex(ValueError,"Overlapping existing"):
                W.plan(self.root,self.day1,self.day2,allow_build=True)

    def test_stale_existing_index_refused_before_audit(self):
        with self.patched():
            W.E.ensure(self.root,self.day1,self.day2,run_id="aabbccddeeff")
            job=W.start_job(self.root,self.day1,self.day2,False,"123456789abc")
            import h5py
            with h5py.File(self.root/"HikyuuData"/"bj_1min.h5","r+") as h5:
                h5.attrs["new_source_revision"]="different"
            with self.assertRaisesRegex(ValueError,"source metadata changed"):
                W.run("123456789abc")
            self.assertFalse(list(job.glob("audit-*.json")))


if __name__=="__main__":
    unittest.main(verbosity=2)
