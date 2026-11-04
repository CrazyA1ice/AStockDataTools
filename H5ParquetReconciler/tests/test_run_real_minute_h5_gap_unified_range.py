"""Two small synthetic integration tests: one real day through both minute
writes and resumable no-rewrite restart; incomplete output fail closed.
"""
import contextlib
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(tag,path):
    spec=importlib.util.spec_from_file_location(tag,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


B=load("synthetic_real_minute_range_runner",
       TOOLS/"run-real-minute-h5-gap-unified-range.py")
F=load("synthetic_real_minute_range_fixture",
       HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")


class RealMinuteRangePhysicalWrites(unittest.TestCase):
    def setUp(self):
        self.f=F.RealMinuteGapWrites(
            "test_two_real_private_minute_parquet_files_created_and_read_back")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.base=self.f.base
        self.reports=self.base/"reports"
        self.reports.mkdir(exist_ok=True)
        self.stage_dir=self.base/"work"/"unified_parquet"/"minute_gap_staging"
        self.unified_dir=self.base/"work"/"unified_parquet"/"minute_complete_day"
        self.parent="a"*12
        self.out=self.reports/"range-final.json"

    def patched(self):
        ctx=contextlib.ExitStack()
        for obj,name,value in (
            (B,"MODULE",self.base),
            (B,"REPORTS",self.reports),
            (B.ST,"MODULE",self.base),
            (B.ST,"WORK",self.stage_dir),
            (B.ST,"REPORTS",self.reports),
            (B.UN,"MODULE",self.base),
            (B.UN,"OUT",self.unified_dir),
            (B.UN,"REPORTS",self.reports),
            (B.UN.G,"MODULE",self.base),
            (B.UN.G,"REPORTS",self.reports),
        ):
            ctx.enter_context(patch.object(obj,name,value))
        return ctx

    def test_real_synthetic_range_writes_two_periods_and_resumes_by_sha(self):
        with self.patched():
            result=B.process(
                self.base,self.f.day,self.f.day,self.parent,self.out,
                max_days=1,max_purchased_rows=10000,
                max_h5_rows=10000,max_unified_rows=10000)
        self.assertEqual(result["batch_days"],1)
        self.assertEqual(result["candidate_weekdays_no_market_source_rows"],[])
        self.assertEqual(result["candidate_weekdays_partial_periods"],{})
        self.assertEqual(result["days"][0]["periods_without_source_rows"],[])
        self.assertEqual(result["days"][0]["status"],
                         "new_physical_day_written_and_verified")
        self.assertEqual(result["aggregated_source_rows"]["1min"],{
            "physical_unified_rows":241,
            "purchased_rows":1,
            "h5_gap_rows":240,
            "h5_quarantined_stockdays":0,
        })
        self.assertEqual(result["aggregated_source_rows"]["5min"],{
            "physical_unified_rows":49,
            "purchased_rows":1,
            "h5_gap_rows":48,
            "h5_quarantined_stockdays":0,
        })
        original_shas={
            p:p.read_bytes() for p in (
                self.base/"AllCycleAStockData"/"1min"/"2026"/"sample.parquet",
                self.base/"AllCycleAStockData"/"5min"/"2026"/"sample.parquet",
            )
        }
        with self.patched():
            again=B.process(
                self.base,self.f.day,self.f.day,self.parent,
                self.reports/"range-restart.json",max_days=1,
                max_purchased_rows=10000,max_h5_rows=10000,
                max_unified_rows=10000)
        self.assertEqual(again["days"][0]["status"],
                         "reused_sha_verified_completed_day")
        self.assertEqual(again["aggregated_source_rows"],
                         result["aggregated_source_rows"])
        self.assertTrue(all(p.read_bytes()==data
                            for p,data in original_shas.items()))

    def test_workday_limit_fails_before_writing_any_market_file(self):
        from datetime import date
        monday=date(2026,10,12)
        friday=date(2026,10,16)
        completed=date(2026,10,13)
        chosen=B.days_between(monday,friday,4,exclude_dates=(completed,))
        self.assertEqual([d.isoformat() for d in chosen],[
            "2026-10-12","2026-10-14","2026-10-15","2026-10-16"])
        with self.assertRaisesRegex(ValueError,"Excluded days must be unique"):
            B.days_between(monday,friday,5,exclude_dates=(completed,completed))
        with self.patched(),self.assertRaisesRegex(ValueError,"Too many"):
            B.process(self.base,monday,friday,self.parent,self.out,
                      max_days=3,exclude_dates=(completed,))
        self.assertFalse(self.out.exists())
        self.assertFalse(self.stage_dir.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
