"""Synthetic bounded orchestration of Oct 08,09,12 highcycle private days."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from datetime import date

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "test_three_oct_2026_highcycle_orchestrator",
    HERE.parent/"tools"/"finish-three-oct-2026-high-cycle-private-days.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
DAYS=M.TARGETS
BASE=M.BASELINE_DAY

class ThreeDatePrivateRolloutTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.eligible=dict(M.SOURCE_ELIGIBLE)
        self.staged={d:2 for d in DAYS}
        self.staged[BASE]=self.eligible[BASE]
        self.visited=[]
        self.calls=[]
        self.events=[]
        self.sha={d:chr(97+i)*64 for i,d in enumerate((*DAYS,BASE))}
        self.change_source_after=None
        self.break_flags=False
        self.fail_day=None
        self.bad_rows_day=None

    def audit(self,day):
        d=day.isoformat()
        self.visited.append(d)
        staged=self.staged[d]
        count=sum(self.staged.values())
        doc={
            "status":M.AUDIT_STATUS,
            "day":d,
            "eligible_full_h5_5min_source_stockdays":self.eligible[d],
            "this_date_staged_complete_stockdays":staged,
            "this_date_unstaged_complete_stockdays":self.eligible[d]-staged,
            "this_date_coverage_complete":self.eligible[d]==staged,
            "stage_stockdays_all_october_sha_verified":count,
            "all_october_private_candidate_rows":28*count,
            "private_candidate_15min_rows_for_this_date":16*staged,
            "private_candidate_30min_rows_for_this_date":8*staged,
            "private_candidate_60min_rows_for_this_date":4*staged,
            "full_existing_receipt_and_parquet_sha_reverified":not self.break_flags,
            "full_original_market_or_h5_files_modified":False,
            "new_market_private_or_production_files_written":False,
            "production_activated":False,
            "vendor_physical_units_certified":False,
            "unadjusted_time_label_semantics_certified":False,
            "private_only_research_candidate_coverage":True,
            "not_official_day_week_or_month_data":True,
            "existing_private_h5_source_sha256":self.sha[d],
        }
        return doc

    def rollout(self,root,day,*,batch_size,max_batches,preview_only,emit):
        d=day.isoformat()
        self.calls.append(d)
        if self.fail_day==d:
            raise ValueError("Purchased high-cycle data conflict")
        self.assertEqual(root,self.root)
        self.assertEqual(batch_size,100)
        self.assertFalse(preview_only)
        before=sum(self.staged.values())
        missing=self.eligible[d]-self.staged[d]
        self.assertEqual(max_batches,(missing+99)//100)
        self.staged[d]=self.eligible[d]
        if self.change_source_after==d:
            self.sha[d]="f"*64
        return {
            "status":M.ROLLOUT_STATUS,
            "day":d,"preview_only":False,
            "batch_size":100,
            "max_batches":max_batches,
            "batches_completed":max_batches,
            "preexisting_stockdays":before,
            "source_eligible":self.eligible[d],
            "uncovered_before":missing,
            "uncovered_after":0,
            "new_private_stockdays":missing,
            "new_rows":28*missing+(1 if self.bad_rows_day==d else 0),
            "original_market_files_modified":False,
            "production_activated":False,
            "ready_for_production_merge":False,
            "no_raw_ohlcva_printed":True,
            "run_ids":[f"{n:012x}" for n in range(max_batches)],
        }

    def go(self,preview=False):
        return M.finish(self.root,preview_only=preview,
                        audit=self.audit,rollout=self.rollout,
                        emit=self.events.append)

    def test_preview_only_three_dates_and_oct13_baseline_unchanged(self):
        baseline=dict(self.staged)
        out=self.go(preview=True)
        self.assertEqual(out["status"],M.FINAL_STATUS)
        self.assertTrue(out["preview_only"])
        self.assertEqual(out["new_candidate_rows"],0)
        self.assertEqual(out["original_verified_stockdays_all_oct"],5555)
        self.assertEqual(out["per_day"][DAYS[0]]["uncovered_at_start"],5544)
        self.assertEqual(out["per_day"][DAYS[1]]["uncovered_at_start"],5545)
        self.assertEqual(out["per_day"][DAYS[2]]["uncovered_at_start"],5547)
        self.assertEqual(out["per_day"][DAYS[0]]["needed_batches"],56)
        self.assertEqual(out["per_day"][DAYS[1]]["needed_batches"],56)
        self.assertEqual(out["per_day"][DAYS[2]]["needed_batches"],56)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.staged,baseline)

    def test_three_dates_in_order_and_final_full_four_day_coverage(self):
        out=self.go()
        self.assertEqual(self.calls,list(DAYS))
        self.assertEqual(out["new_stockdays"],16636)
        self.assertEqual(out["new_candidate_rows"],465808)
        self.assertEqual(out["final_verified_stockdays_all_oct"],22191)
        self.assertEqual(out["final_candidate_rows_all_oct"],621348)
        self.assertTrue(out["all_four_dates_source_complete"])
        self.assertFalse(out["ready_for_production_merge"])
        self.assertFalse(out["production_activated"])
        self.assertFalse(out["source_vendor_units_certified"])
        self.assertFalse(out["preview_only"])
        self.assertEqual(self.visited[:4],list((*DAYS,BASE)))
        self.assertEqual(len([s for s in self.events
                              if s.startswith("PASS_OCT_THREE_DAY_DATE")]),3)

    def test_resume_after_first_date_already_completed(self):
        self.staged[DAYS[0]]=self.eligible[DAYS[0]]
        out=self.go()
        self.assertEqual(self.calls,list(DAYS[1:]))
        self.assertEqual(out["per_day"][DAYS[0]]["new_stockdays"],0)
        self.assertEqual(out["new_stockdays"],5545+5547)
        self.assertTrue(out["all_four_dates_source_complete"])

    def test_stop_on_second_date_failure_without_running_third_date(self):
        self.fail_day=DAYS[1]
        with self.assertRaisesRegex(ValueError,"Purchased high-cycle"):
            self.go()
        self.assertEqual(self.calls,list(DAYS[:2]))
        self.assertEqual(self.staged[DAYS[0]],self.eligible[DAYS[0]])
        self.assertEqual(self.staged[DAYS[1]],2)
        self.assertEqual(self.staged[DAYS[2]],2)

    def test_oct13_baseline_incomplete_stops_all_writes(self):
        self.staged[BASE]-=1
        with self.assertRaisesRegex(ValueError,"Previously completed"):
            self.go()
        self.assertEqual(self.calls,[])

    def test_oct13_receipt_sha_invalidation_stops_before_writes(self):
        self.break_flags=True
        with self.assertRaisesRegex(ValueError,"source eligibility/SHA/safety"):
            self.go()
        self.assertEqual(self.calls,[])

    def test_modified_current_source_sha_after_write_fails_before_next_date(self):
        self.change_source_after=DAYS[0]
        with self.assertRaisesRegex(ValueError,"Independent full-date SHA"):
            self.go()
        self.assertEqual(self.calls,[DAYS[0]])
        self.assertEqual(self.staged[DAYS[1]],2)

    def test_wrong_bounded_writer_row_count_rejected(self):
        self.bad_rows_day=DAYS[0]
        with self.assertRaisesRegex(ValueError,"Unexpected bounded private rollout"):
            self.go()
        self.assertEqual(self.calls,[DAYS[0]])
        self.assertEqual(self.staged[DAYS[1]],2)

    def test_clean_noop_when_all_three_days_previously_completed(self):
        for d in DAYS:
            self.staged[d]=self.eligible[d]
        out=self.go()
        self.assertEqual(out["new_stockdays"],0)
        self.assertEqual(out["new_candidate_rows"],0)
        self.assertEqual(out["final_verified_stockdays_all_oct"],22191)
        self.assertEqual(self.calls,[])

    def test_invalid_source_inventory_rejected_during_preflight(self):
        self.eligible[DAYS[0]]=5547
        with self.assertRaisesRegex(ValueError,"source eligibility/SHA/safety"):
            self.go()
        self.assertEqual(self.calls,[])

if __name__=="__main__":
    unittest.main()
