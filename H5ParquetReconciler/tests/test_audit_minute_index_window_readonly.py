"""Synthetic purchased-minute index batch auditing without touching licensed data."""
import contextlib
import importlib.util
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"


def load(tag,path):
    spec=importlib.util.spec_from_file_location(tag,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


B=load("synthetic_multi_day_index_key_audit",
       TOOLS/"audit-minute-index-window-readonly.py")
Q=B.Q
I=B.I
F=load("synthetic_index_batch_original_fixture",
       HERE/"test_write_h5_only_complete_minute_stockdays_to_private_parquet.py")


class IndexedBatchMinuteKeysTests(unittest.TestCase):
    def setUp(self):
        self.fixture=F.RealMinuteGapWrites(
            "test_two_real_private_minute_parquet_files_created_and_read_back")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.base
        self.before=date(2026,10,12)
        self.today=date(2026,10,13)
        self.store=self.root/"work"/"unified_parquet"/"minute_key_index"

    def patched(self):
        stack=contextlib.ExitStack()
        for mod,key,value in (
                (B.N.ST,"MODULE",self.root),
                (B.N.ST,"WORK",self.root/"work"/"unified_parquet"/"minute_gap_staging"),
                (B.N.ST,"REPORTS",self.root/"reports"),
                (I,"STORE",self.store),
                (I.N.ST,"MODULE",self.root),
                (I.N.ST,"WORK",self.root/"work"/"unified_parquet"/"minute_gap_staging"),
                (I.N.ST,"REPORTS",self.root/"reports"),
        ):
            stack.enter_context(patch.object(mod,key,value))
        return stack

    def index(self):
        return I.build(self.root,self.before,self.today,"feed1234abcd")["index_path"]

    def test_two_day_source_index_reused_and_no_vendor_parquet_rescan(self):
        with self.patched():
            path=self.index()
            with patch.object(Q.ST,"purchased_stockdays",
                              side_effect=AssertionError("vendor Parquet rescan")):
                report=B.audit(self.root,path,self.before,self.today)
        self.assertEqual(report["audited_calendar_dates"],2)
        self.assertEqual(report["days"][0]["source_coverage_status"],
                         "NO_SOURCE_EVIDENCE_NOT_EXCHANGE_CLOSED")
        self.assertEqual(report["days"][1]["source_coverage_status"],
                         "SOME_SOURCE_EVIDENCE_NOT_FULLY_CERTIFIED")
        self.assertEqual(report["summaries"]["1min"][
            "h5_only_keys_on_full_purchased_absence_days"],240)
        self.assertEqual(report["summaries"]["1min"][
            "h5_only_candidate_keys_on_partial_purchased_stockdays"],240)
        self.assertEqual(report["summaries"]["5min"][
            "h5_only_keys_on_full_purchased_absence_days"],48)
        self.assertEqual(report["summaries"]["5min"][
            "h5_only_candidate_keys_on_partial_purchased_stockdays"],47)
        self.assertFalse(report["new_parquet_or_h5_market_files_written"])
        self.assertEqual(report["new_market_gap_keys_accepted"],0)

    def test_audit_requires_date_covered_by_completed_index(self):
        with self.patched():
            path=self.index()
            with self.assertRaisesRegex(ValueError,"Index metadata/date/period/root mismatch"):
                B.audit(self.root,path,date(2026,10,9),date(2026,10,12))

    def test_audit_rejects_mutated_input_after_index_build(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with self.patched():
            path=self.index()
            pq.write_table(pa.table({"ts":[1],"symbol":["SH600000"]}),
                self.root/"AllCycleAStockData"/"1min"/"2026"/"added_after_index.parquet")
            with self.assertRaisesRegex(ValueError,"source metadata changed"):
                B.audit(self.root,path,self.before,self.today)

    def test_single_day_audit_matches_original_single_day_preview(self):
        with self.patched():
            path=self.index()
            expected=Q.preview(self.root,self.today,key_index=path)
            actual=B.audit(self.root,path,self.today,self.today)
        for period in ("1min","5min"):
            for k in B.FIELDS:
                self.assertEqual(actual["summaries"][period][k],
                                 expected["periods"][period][k])
        self.assertTrue(actual["existing_purchased_key_index_reused"])
        self.assertFalse(actual["ready_for_production_query"])


if __name__=="__main__":
    unittest.main(verbosity=2)
