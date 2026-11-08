"""Pure synthetic resume-safe October multi-batch private high-cycle scheduler."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "test_oct_bounded_private_rollout",
    HERE.parent/"tools"/"rollout-2026-oct-high-cycle-private-batches.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
DAY=date(2026,10,13)
SOURCE_SHA="b"*64

class BoundedHighcycleRolloutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.market=Path(self.temp.name)/"market"
        self.market.mkdir()
        self.stage=Path(self.temp.name)/"stage"
        self.stage.mkdir()
        self.events=[]
        self._patch=patch.object(M.S,"_safe_stage_root",return_value=self.stage)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def plan(self,*,previous=24,uncovered=5,size=3,
             source=SOURCE_SHA,eligible=87):
        assert eligible>=uncovered
        chosen=min(uncovered,size)
        return {
            "status":M.PLAN_STATUS,"day":DAY.isoformat(),
            "batch_size":size,"source_5min_private_SHA_checked":True,
            "source_sha256":source,
            "original_market_files_modified":False,
            "new_private_or_production_files_written":False,
            "production_activated":False,
            "vendor_physical_units_certified":False,
            "h5_5min_complete_eligible_stockdays":eligible,
            "already_staged_complete_eligible_this_day":eligible-uncovered,
            "uncovered_complete_eligible_this_day":uncovered,
            "chosen_stockdays":chosen,
            "remaining_uncovered_stockdays_after_selection":uncovered-chosen,
            "selected_symbols":[f"SH601{i:03d}" for i in range(previous,previous+chosen)],
            "previous_private_stockdays_sha_rechecked":previous,
        }

    def checked(self,plan,runid):
        n=plan["chosen_stockdays"]
        return {
            "run_id":runid,"new_stockdays":n,
            "new_rows":28*n,
            "rows_by_period":{"15min":16*n,"30min":8*n,"60min":4*n},
            "sha256_by_period":{p:"a"*64 for p in M.PERIODS},
            "receipt_relative_file":"work/unified_parquet/test/receipt.json",
        }

    def test_preview_uses_inventory_without_staging_or_creating_files(self):
        with (patch.object(M.N,"plan",return_value=self.plan()),
              patch.object(M.N,"stage_next") as write):
            r=M.rollout(self.market,DAY,batch_size=3,max_batches=2,
                        preview_only=True,emit=self.events.append)
        self.assertEqual(r["planned_first_batch"],3)
        self.assertEqual(r["new_rows"],0)
        self.assertEqual(r["batches_completed"],0)
        self.assertEqual(r["uncovered_before"],5)
        self.assertTrue(r["preview_only"])
        write.assert_not_called()
        self.assertEqual(list(self.stage.iterdir()),[])

    def test_two_batches_pick_three_then_two_and_leave_no_duplicate_keys(self):
        initial=self.plan(previous=24,uncovered=5)
        next_plan=self.plan(previous=27,uncovered=2)
        observed=[]
        with (patch.object(M.N,"plan",side_effect=[initial,next_plan]) as query,
              patch.object(M.N,"stage_next",side_effect=lambda root,day,runid,**kw:
                  observed.append(runid) or {"status":"synthetic"}),
              patch.object(M,"_verify_written",side_effect=lambda result,plan,day,rid:
                  self.checked(plan,rid))):
            ids=iter(("111111111111","222222222222"))
            r=M.rollout(self.market,DAY,batch_size=3,max_batches=2,
                        emit=self.events.append,id_factory=lambda:next(ids))
        self.assertEqual(r["batches_completed"],2)
        self.assertEqual(r["new_private_stockdays"],5)
        self.assertEqual(r["new_rows"],140)
        self.assertEqual(r["uncovered_after"],0)
        self.assertEqual(r["run_ids"],["111111111111","222222222222"])
        self.assertEqual(observed,r["run_ids"])
        self.assertEqual(query.call_count,2)
        self.assertEqual(sum("OCT_BOUNDED_BATCH_PASS " in msg for msg in self.events),2)
        self.assertEqual(list(self.stage.iterdir()),[])

    def test_hard_ceiling_preserves_unprocessed_remainder(self):
        with (patch.object(M.N,"plan",return_value=self.plan(previous=24,uncovered=5)),
              patch.object(M.N,"stage_next",return_value={}),
              patch.object(M,"_verify_written",side_effect=lambda res,plan,day,rid:
                  self.checked(plan,rid))):
            r=M.rollout(self.market,DAY,batch_size=3,max_batches=1,
                        emit=self.events.append,id_factory=lambda:"333333333333")
        self.assertEqual(r["new_private_stockdays"],3)
        self.assertEqual(r["uncovered_after"],2)
        self.assertEqual(r["batches_completed"],1)

    def test_staging_failure_fails_closed_without_synthetic_success(self):
        with (patch.object(M.N,"plan",return_value=self.plan()),
              patch.object(M.N,"stage_next",
                           side_effect=ValueError("Purchased high-cycle owns stockday")),
              patch.object(M,"_verify_written") as verify):
            with self.assertRaisesRegex(ValueError,"Purchased high-cycle"):
                M.rollout(self.market,DAY,batch_size=3,max_batches=2,
                          emit=self.events.append,id_factory=lambda:"444444444444")
        verify.assert_not_called()
        self.assertFalse(any("BATCH_PASS" in x for x in self.events))

    def test_changed_source_sha_after_first_batch_stops_second_write(self):
        initial=self.plan(previous=24,uncovered=5)
        changed=self.plan(previous=27,uncovered=2,source="c"*64)
        with (patch.object(M.N,"plan",side_effect=[initial,changed]),
              patch.object(M.N,"stage_next",return_value={}) as stage,
              patch.object(M,"_verify_written",side_effect=lambda res,plan,day,rid:
                  self.checked(plan,rid))):
            with self.assertRaisesRegex(ValueError,"Source inventory/receipt ledger changed"):
                M.rollout(self.market,DAY,batch_size=3,max_batches=2,
                          emit=self.events.append,id_factory=lambda:"555555555555")
        self.assertEqual(stage.call_count,1)
        self.assertEqual(sum("BATCH_PASS " in x for x in self.events),1)

    def test_reject_duplicate_generated_run_id_before_stage(self):
        (self.stage/"666666666666").mkdir()
        with (patch.object(M.N,"plan",return_value=self.plan()),
              patch.object(M.N,"stage_next") as stage):
            with self.assertRaisesRegex(ValueError,"run ID already exists"):
                M.rollout(self.market,DAY,batch_size=3,max_batches=1,
                          emit=self.events.append,id_factory=lambda:"666666666666")
        stage.assert_not_called()

    def test_bad_bounds_and_date_rejected_before_io(self):
        cases=[(0,8),(101,8),(True,8),(100,0),(100,61),(100,True)]
        for size,number in cases:
            with self.subTest(size=size,max_batches=number):
                with self.assertRaisesRegex(ValueError,"Batch size|Max batches"):
                    M.rollout(self.market,DAY,batch_size=size,max_batches=number)
        with self.assertRaisesRegex(ValueError,"October 2026"):
            M.rollout(self.market,date(2026,9,30))

    def test_no_available_stockdays_is_clean_noop(self):
        with (patch.object(M.N,"plan",return_value=self.plan(uncovered=0)),
              patch.object(M.N,"stage_next") as stage):
            r=M.rollout(self.market,DAY,batch_size=3,max_batches=8,
                        emit=self.events.append)
        self.assertEqual(r["batches_completed"],0)
        self.assertEqual(r["new_rows"],0)
        self.assertEqual(r["uncovered_after"],0)
        stage.assert_not_called()

if __name__=="__main__":
    unittest.main()
