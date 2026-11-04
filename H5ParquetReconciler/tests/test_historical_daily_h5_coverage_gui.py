"""Historical DAY vs MINUTE GUI date modes: real synthetic H5 read-only.

Validates that 1990 H5 daily data is selectable while old minute exact-key
safety bounds are not silently interpreted as daily historical coverage.
No original purchased market files are accessed by these fixtures.
"""
import contextlib
import hashlib
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(tag,name):
    path=TOOLS/name
    spec=importlib.util.spec_from_file_location(tag,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D=load("test_h5_historical_daily_coverage",
       "inspect-daily-h5-coverage-readonly.py")
W=load("test_gui_mode_daily_v_minute",
       "minute-gap-audit-gui-worker.py")
F=importlib.util.spec_from_file_location(
    "test_daily_mode_existing_minute_fixture",
    HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")
T=importlib.util.module_from_spec(F)
F.loader.exec_module(T)


class HistoricalDailySourceCoverageGuiTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        import h5py
        self.fixture=T.RealMinuteGapWrites(
            "test_two_real_private_minute_parquet_files_created_and_read_back")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.base
        self.jobroot=self.root/"work"/"minute_audit_gui"
        folder=self.root/"HikyuuData"
        # One 1990 date, one 1991, plus a later record; illustrates why
        # minute index engine cannot impose its 2025 cutoff on daily.
        self.day_file=folder/"sh_day.h5"
        raw=np.zeros(3,dtype=self.fixture.raw_dtype)
        raw["datetime"]=[199012190000,199101040000,202610130000]
        with h5py.File(self.day_file,"w") as h5:
            h5.create_group("data").create_dataset("SH600000",data=raw)

    def patched(self):
        c=contextlib.ExitStack()
        for mod,key,val in (
            (W,"BASE",self.jobroot),
            (W,"JOBS",self.jobroot/"jobs"),
            (W,"LOCK",self.jobroot/"audit.lock"),
        ):
            c.enter_context(patch.object(mod,key,val))
        return c

    def hashes(self):
        return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest()
                for name in ("AllCycleAStockData","HikyuuData")
                for p in (self.root/name).rglob("*") if p.is_file()}

    def test_1990_historical_day_accepted_without_minute_index(self):
        plan=W.plan(self.root,"1990-12-01","1991-01-31",mode="day")
        self.assertEqual(len(plan),2)
        self.assertEqual(plan[0]["year"],1990)
        self.assertEqual(plan[1]["year"],1991)
        self.assertTrue(all(p["mode"]=="historical_h5_day_coverage_only"
                            for p in plan))
        old=D.inspect_year(self.root,"1990-12-01","1990-12-31")
        self.assertEqual(old["h5_a_share_candidate_daily_rows"],1)
        self.assertEqual(old["purchased_day_parquet_year_file_count"],0)
        self.assertFalse(old["daily_exact_parquet_key_diff_completed"])
        self.assertIsNone(old["h5_only_net_day_key_count"])

    def test_source_detects_actual_day_bounds_not_assumed_1990(self):
        before=self.hashes()
        d=D.detect_h5_day_bounds(self.root)
        self.assertEqual(d["h5_earliest_candidate_day"],"1990-12-19")
        self.assertEqual(d["h5_latest_candidate_day"],"2026-10-13")
        self.assertEqual(before,self.hashes())

    def test_year_sharded_day_worker_read_only_1990_to_1991(self):
        before=self.hashes()
        with self.patched():
            job=W.start_job(self.root,"1990-12-01","1991-01-31",
                            False,"abcdef012345",mode="day")
            W.run("abcdef012345")
            status=W.json.loads((job/"state.json").read_text(encoding="utf-8"))
        self.assertEqual(status["status"],"completed")
        self.assertEqual(status["days_total"],2)
        self.assertEqual(status["days_done"],2)
        self.assertEqual(status["summary_by_period"]["day"][
            "h5_a_share_candidate_daily_rows"],2)
        self.assertEqual(len(list(job.glob("audit-day-*.json"))),2)
        self.assertEqual(before,self.hashes())

    def test_minute_plan_no_global_367day_limit_but_bounded_shards(self):
        # Previous GUI rejected 2025-01-01 through 2026-10-13 because it
        # imposed an arbitrary <=367 day full-task limit.
        plan=W.plan(self.root,"2025-01-01","2026-10-13",
                    allow_build=True,mode="minute")
        self.assertGreater(len(plan),12)
        self.assertTrue(all((date.fromisoformat(p["last"])-
                             date.fromisoformat(p["first"])).days <31
                            for p in plan))

    def test_old_minute_algorithm_not_invoked_for_1990_daily_mode(self):
        with patch.object(W.I,"purchased_masks",
                          side_effect=AssertionError("minute scan forbidden")):
            with self.patched():
                W.start_job(self.root,"1990-12-01","1990-12-31",
                            False,"abcdef012345",mode="day")
                W.run("abcdef012345")
        self.assertEqual(len(list(self.jobroot.glob("jobs/*/audit-day-*.json"))),1)

    def test_minute_engine_rejects_1990_with_clear_mode_choice(self):
        with self.assertRaisesRegex(ValueError,"choose historical DAY coverage"):
            W.plan(self.root,"1990-01-01","1991-12-31",
                   allow_build=True,mode="minute")


if __name__=="__main__":
    unittest.main(verbosity=2)
