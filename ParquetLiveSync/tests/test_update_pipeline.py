"""Offline one-click DAY -> purchased-calibrated WEEK/MONTH update contract."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import update_pipeline as P
import local_layout as L

class FullThreePeriodAutopilot(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root=Path(td.name)/"stock"
        for p in L.PERIODS:
            (self.root/"AllCycleAStockData"/p).mkdir(parents=True)
        self.start=date(2026,10,14)
        self.end=date(2026,11,11)
        self.day={"status":"day_overlay_commits_or_skips_complete",
                  "latest_overlaid_day":"2026-11-11",
                  "physical_local_AllCycleAStockData_day_written":True}
        self.derived={"mode":"APPLY","candidate_rows":{
            "week":22285,"month":5576},"commits":[
            {"period":"week","added":16712},
            {"period":"week","added":5573},
            {"period":"month","added":5576}]}

    def test_no_apply_dry_run_never_downloads_or_writes(self):
        with patch.object(P,"sync",side_effect=AssertionError("network/write")):
            with patch.object(P.R,"run",side_effect=AssertionError("rollup/write")):
                result=P.run(self.root,start=self.start,end=self.end,
                             apply=False,logger=lambda _:None)
        self.assertEqual(result["status"],"READONLY_UPDATE_PLAN")
        self.assertEqual(result["candidate_calendar_dates"],29)

    def test_update_checks_both_steps_and_requires_local_day_materialization(self):
        invocations=[]
        def sync(*args,**kwargs):
            self.assertTrue(kwargs["materialize_local"])
            self.assertEqual(kwargs["max_days"],180)
            invocations.append("day")
            return self.day
        def derive(root,**kwargs):
            self.assertTrue(kwargs["apply"])
            self.assertEqual(invocations,["day"])
            invocations.append("week-month")
            return self.derived
        with patch.object(P,"sync",side_effect=sync):
            with patch.object(P.R,"run",side_effect=derive):
                result=P.run(self.root,start=self.start,end=self.end,
                             apply=True,logger=lambda _:None)
        self.assertEqual(invocations,["day","week-month"])
        self.assertEqual(result["status"],"DAY_WEEK_MONTH_COMPLETED_AND_SHA_BACKED")
        self.assertEqual(result["week_month"]["candidate_rows"]["week"],22285)
        self.assertFalse(result["all_eight_periods_up_to_date"])

    def test_stop_before_any_market_write(self):
        with patch.object(P,"sync",side_effect=AssertionError("Do not sync")):
            result=P.run(self.root,start=self.start,end=self.end,
                         apply=True,stop=lambda:True,logger=lambda _:None)
        self.assertEqual(result["status"],"STOPPED_BEFORE_ANY_WRITE")

    def test_stop_after_daily_checkpoint_keeps_commits_no_partial_derivation(self):
        calls=iter([False,True])
        with patch.object(P,"sync",return_value=self.day):
            with patch.object(P.R,"run",side_effect=AssertionError("No rollup")):
                result=P.run(self.root,start=self.start,end=self.end,
                             apply=True,stop=lambda:next(calls),
                             logger=lambda _:None)
        self.assertEqual(result["status"],"STOPPED_AFTER_DAILY_COMMITS")
        self.assertTrue(result["daily_commits_preserved"])
        self.assertIsNone(result["week_month"])

    def test_period_failure_is_not_reported_as_success(self):
        with patch.object(P,"sync",return_value=self.day):
            with patch.object(P.R,"run",side_effect=ValueError(
                    "UNVERIFIED_WEEK_SOURCE_DAY=2026-11-10")):
                with self.assertRaisesRegex(ValueError,"UNVERIFIED_WEEK_SOURCE"):
                    P.run(self.root,start=self.start,end=self.end,apply=True,
                          logger=lambda _:None)

    def test_rolling_recent_window_caps_at_2026_oct14_cutoff(self):
        begin,end=P.window(end=self.end,retry_days=90)
        self.assertEqual(begin,date(2026,10,14))
        self.assertEqual(end,self.end)
        with self.assertRaises(ValueError):
            P.window(end=self.end,retry_days=181)

    def test_day_only_workflow_still_supported_explicitly(self):
        with patch.object(P,"sync",return_value=self.day):
            with patch.object(P.R,"run",
                              side_effect=AssertionError("No derived writes")):
                result=P.run(self.root,start=self.start,end=self.end,
                             apply=True,verify_week_month=False,logger=lambda _:None)
        self.assertEqual(result["status"],"DAY_ONLY_SUCCESS")

if __name__=="__main__":
    unittest.main()
