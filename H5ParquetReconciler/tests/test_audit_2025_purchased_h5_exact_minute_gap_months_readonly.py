"""Synthetic 2025 H5-vs-purchased minute exact-key monthly batch no-write gates."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from contextlib import ExitStack,redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "synthetic_2025_exact_h5_monthly_reuse_audit",
    HERE.parent/"tools"/"audit-2025-purchased-h5-exact-minute-gap-months-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Existing2025MinuteGapMonthlyReadOnlyTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.before=("source-stat-fingerprint",1)
        self.calls=[]
        self.receipts={m:{"periods":{
            "1min":{"keys":241,"stockdays":1},
            "5min":{"keys":48,"stockdays":1}}}
            for m in ("2025-01","2025-02")}
        self.fail_market=False

    def fake_receipt(self,month,root,sha):
        self.assertEqual(sha,self.before)
        self.assertEqual(Path(root),self.root)
        return self.receipts.get(month)

    def fake_plan(self,root,first,last,*,allow_build,mode):
        self.assertFalse(allow_build,"No missing indexes may be created")
        self.assertEqual(mode,"minute")
        self.assertEqual(Path(root),self.root)
        return [{
            "mode":"reuse_existing_index",
            "existing_index":str(self.root/"fictional-existing-index.sqlite"),
            "first":first,"last":last,
        }]

    def fake_exact_audit(self,root,index,first,last):
        self.calls.append((first,last))
        self.assertEqual(Path(root),self.root)
        self.assertEqual(Path(index).name,"fictional-existing-index.sqlite")
        summary={p:{
            **{k:0 for k in M.GAP_FIELDS},
            "purchased_a_share_date_key_count":241 if p=="1min" else 48,
            "quarantined_h5_stockdays_by_reason":{}} for p in M.PERIODS}
        summary["1min"]["overlapping_exact_keys"]=240
        summary["5min"]["overlapping_exact_keys"]=48
        summary["1min"]["purchased_only_0930_keys_on_complete_H5_stockdays"]=1
        summary["1min"]["h5_date_native_rows_examined"]=240
        summary["5min"]["h5_date_native_rows_examined"]=48
        return {
            "status":"read_only_existing_index_multi_day_candidate_diff_not_activated",
            "from_day":first,"through_day":last,
            "existing_purchased_key_index_reused":True,
            "original_purchased_parquet_opened_for_bars":False,
            "purchased_ohlcva_rows_rematerialized":0,
            "new_parquet_or_h5_market_files_written":self.fail_market,
            "new_market_gap_keys_accepted":0,
            "ready_for_production_query":False,
            "audited_calendar_dates":20,
            "days":[],
            "summaries":summary,
        }

    def audited(self,from_month="2025-01",through_month="2025-01",*,extra=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(
                M.CHECK.A.I.N,"source_snapshot",return_value=self.before))
            stack.enter_context(patch.object(
                M.CHECK,"verified_receipt",side_effect=self.fake_receipt))
            stack.enter_context(patch.object(
                M.CHECK.A.G,"plan",side_effect=self.fake_plan))
            stack.enter_context(patch.object(
                M.EXACT,"audit",side_effect=self.fake_exact_audit))
            if extra:
                stack.enter_context(extra)
            with redirect_stdout(StringIO()) as log:
                result=M.audit(self.root,from_month,through_month)
        return result,log.getvalue()

    def test_one_month_reuses_accepted_month_and_index_without_writes(self):
        before=set(self.root.iterdir())
        result,log=self.audited()
        self.assertEqual(result["months_audited"],1)
        self.assertEqual(result["new_source_key_indexes_created"],0)
        self.assertEqual(result["summaries"]["1min"][
            "purchased_a_share_date_key_count"],241)
        self.assertEqual(result["summaries"]["5min"][
            "purchased_a_share_date_key_count"],48)
        self.assertEqual(result["summaries"]["1min"]["overlapping_exact_keys"],240)
        self.assertFalse(result["new_market_parquet_or_h5_written"])
        self.assertFalse(result["production_activated"])
        self.assertFalse(result["h5_price_volume_amount_units_certified"])
        self.assertIn("H5_2025_EXACT_MONTH_GAP_SUMMARY=",log)
        self.assertEqual(before,set(self.root.iterdir()))

    def test_two_months_conserve_purchased_membership(self):
        result,_=self.audited("2025-01","2025-02")
        self.assertEqual(result["months_audited"],2)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(result["summaries"]["1min"][
            "purchased_a_share_date_key_count"],482)
        self.assertEqual(result["summaries"]["5min"][
            "purchased_a_share_date_key_count"],96)

    def test_missing_accepted_month_receipt_fails_closed(self):
        self.receipts.pop("2025-01")
        with self.assertRaisesRegex(ValueError,"Missing accepted"):
            self.audited()
        self.assertFalse(self.calls)

    def test_purchased_key_count_disagreement_fails_closed(self):
        self.receipts["2025-01"]["periods"]["1min"]["keys"]=242
        with self.assertRaisesRegex(ValueError,"Indexed purchased keys disagree"):
            self.audited()

    def test_no_private_index_creation_flag_reached(self):
        def wrong_plan(*args,**kwargs):
            self.assertFalse(kwargs["allow_build"])
            raise ValueError("Unindexed date range")
        with self.assertRaisesRegex(ValueError,"Unindexed date range"):
            self.audited(extra=patch.object(M.CHECK.A.G,"plan",side_effect=wrong_plan))
        self.assertFalse(self.calls)

    def test_write_contract_violation_from_comparator_rejected(self):
        self.fail_market=True
        with self.assertRaisesRegex(ValueError,"no-market-write policy"):
            self.audited()

    def test_source_stat_drift_after_scan_rejected(self):
        with self.assertRaisesRegex(RuntimeError,"metadata changed"):
            self.audited(extra=patch.object(
                M.CHECK.A.I.N,"source_snapshot",side_effect=[
                    self.before,("different",99)]))

    def test_three_months_rejected_before_source_access(self):
        with patch.object(M.CHECK.A.I.N,"source_snapshot",
                          side_effect=AssertionError("Source scan wrongly started")):
            with self.assertRaisesRegex(ValueError,"1..2"):
                M.audit(self.root,"2025-01","2025-03")
        self.assertFalse(self.calls)

    def test_non_2025_or_reversed_months_rejected(self):
        for a,b in (("2024-12","2025-01"),("2026-01","2026-02"),
                    ("2025-02","2025-01")):
            with self.subTest(a=a,b=b):
                with self.assertRaises(ValueError):
                    M.audit(self.root,a,b)
        self.assertFalse(self.calls)

    def test_original_market_source_symlink_root_rejected(self):
        fake=self.root/"source-link"
        fake.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,"non-symlink"):
            M.audit(fake,"2025-01","2025-01")


if __name__=="__main__":
    unittest.main(verbosity=2)
