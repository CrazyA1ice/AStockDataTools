"""Synthetic original OHLCVA equality/provenance contracts for purchased day priority."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "real_daily_original_purchased_primary_gate_tests",
    HERE.parent / "tools" /
    "query-registered-private-day-purchased-first-live-pilot-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
DAY="2026-04-08"
SOURCE="SH600000"
VERSION=M.VERSION
EVIDENCE={
    "version_sha256":VERSION,
    "live_safe":"fictional-safe", "private_keys":"fictional-keys",
    "history_ledger":"fictional-ledger", "source_2016":"fictional-2016",
    "source_2026":"fictional-2026","mixed_plan":"fictional-plan",
}
STAMP=202604080000
PRIVATE={("SH600099", STAMP)}
RAW={
    "symbol":SOURCE,"period":"day","trading_date":DAY,
    "source_timestamp_ms":1775563200000,
    "source_file_relative_path":"AllCycleAStockData/day/2026.parquet",
    "source_row_group":0,
    "open":10.0,"high":12.0,"low":9.0,"close":11.0,
    "volume":100.0,"amount":1200.0,
}


def live_row():
    return {**RAW,"value_source":"purchased_parquet"}


def live_reply():
    return {
        "bars":[live_row()],
        "safe_summary":{
            "matching_bar_count":1,
            "bars_by_source":{
                "purchased_parquet":1,
                "private_h5_whole_date_candidate":0,
                "private_h5_mixed_stockday_candidate":0,
            },
            "period":"day","symbol":SOURCE,
            "from_day":DAY,"through_day":DAY,
            "registered_private_day_version_sha256":VERSION,
            "registered_private_22274_day_overlay_explicitly_enabled":True,
            "routing":"explicit_immutable_22274_day_live_verified_purchased_first",
            "purchased_source_priority":True,
            "production_query_activated":False,
            "original_market_files_modified":False,
            "new_market_or_index_files_written":False,
            "no_raw_ohlcva_in_safe_summary":True,
        },
    }


class LiveOriginalPurchasedPrimaryTests(unittest.TestCase):
    def setUp(self):
        self.root=Path("D:/stock")
        self.conf=Path("private.json")

    def _run(self, *,purchased=None,unified=None):
        if purchased is None:
            purchased={"bars":[dict(RAW)]}
        if unified is None:
            unified=live_reply()
        with patch.object(M,"offline_context",
                          return_value=(EVIDENCE,DAY,PRIVATE)), \
             patch.object(M.ALL.PURCHASED,"query_bars",
                          return_value=purchased) as rawq, \
             patch.object(M.ALL,"query_bars",
                          return_value=unified) as unifiedq:
            result=M.query_one(self.root,VERSION,self.conf)
        return result,rawq,unifiedq

    def test_original_purchased_day_matches_unified_all_six_values_exactly(self):
        safe,orig,full=self._run()
        self.assertEqual(safe["bars_by_source"]["purchased_parquet"],1)
        self.assertFalse(safe["H5_value_override"])
        self.assertTrue(safe["all_six_OHLCVA_values_and_source_timestamp_equal_purchased_original"])
        self.assertTrue(safe["purchased_source_file_and_rowgroup_preserved"])
        self.assertTrue(safe["source_security_identifier_redacted"])
        self.assertFalse(safe["original_market_files_modified"])
        self.assertFalse(safe["production_query_activated"])
        self.assertNotIn(SOURCE,str(safe))
        self.assertNotIn("10.0",str(safe))
        self.assertFalse(orig.call_args.kwargs["local_cache"])
        self.assertEqual(full.call_args.kwargs["private_day_evidence"],EVIDENCE)
        self.assertEqual(full.call_args.kwargs["max_result_bars"],3)

    def test_probed_purchased_stockday_missing_is_not_invented(self):
        with patch.object(M.ALL.PURCHASED,"query_bars",
                          return_value={"bars":[]}) as raw:
            with self.assertRaisesRegex(ValueError,"No suitable purchased"):
                M.original_purchased_day(self.root,DAY,PRIVATE)
        self.assertEqual(raw.call_count,len(M.CANDIDATE_SYMBOLS))

    def test_exact_h5_mixed_candidate_must_not_be_used_as_purchased(self):
        candidate={(SOURCE,STAMP)}
        def bought(root,symbol,*a,**kw):
            if symbol!=M.CANDIDATE_SYMBOLS[1]:
                raise AssertionError("Should skip known private H5-only key")
            return {"bars":[{**RAW,"symbol":symbol}]}
        with patch.object(M.ALL.PURCHASED,"query_bars",side_effect=bought) as raw:
            symbol,result=M.original_purchased_day(self.root,DAY,candidate)
        self.assertEqual(symbol,M.CANDIDATE_SYMBOLS[1])
        self.assertEqual(raw.call_count,1)
        self.assertNotEqual((symbol,STAMP),candidate.pop())

    def test_no_real_ohlcva_can_be_replaced_with_private_h5_values(self):
        changed=live_reply()
        changed["bars"][0]["close"]=11.5
        with self.assertRaisesRegex(ValueError,"OHLCVA/time/source identity changed"):
            self._run(unified=changed)

    def test_timestamp_mismatch_rejected(self):
        changed=live_reply()
        changed["bars"][0]["source_timestamp_ms"]+=1000
        with self.assertRaisesRegex(ValueError,"OHLCVA/time/source identity changed"):
            self._run(unified=changed)

    def test_source_file_and_rowgroup_mismatch_rejected(self):
        for name, value in (
            ("source_file_relative_path","another.parquet"),("source_row_group",99)
        ):
            with self.subTest(name=name):
                changed=live_reply()
                changed["bars"][0][name]=value
                with self.assertRaisesRegex(ValueError,"OHLCVA/time/source identity changed"):
                    self._run(unified=changed)

    def test_unified_h5_bar_must_not_shadow_purchased_stockday(self):
        changed=live_reply()
        changed["bars"][0]["value_source"]="private_h5_mixed_stockday_candidate"
        with self.assertRaisesRegex(ValueError,"OHLCVA/time/source identity changed"):
            self._run(unified=changed)

    def test_provenance_counter_h5_override_rejected(self):
        changed=live_reply()
        changed["safe_summary"]["bars_by_source"]["purchased_parquet"]=0
        changed["safe_summary"]["bars_by_source"]["private_h5_mixed_stockday_candidate"]=1
        with self.assertRaisesRegex(ValueError,"wrong provenance"):
            self._run(unified=changed)

    def test_production_route_rejected(self):
        changed=live_reply()
        changed["safe_summary"]["production_query_activated"]=True
        with self.assertRaisesRegex(ValueError,"wrong provenance"):
            self._run(unified=changed)

    def test_direct_purchased_duplicate_rows_rejected_before_live(self):
        with patch.object(M.ALL.PURCHASED,"query_bars",
                          return_value={"bars":[dict(RAW),dict(RAW)]}):
            with self.assertRaisesRegex(ValueError,"duplicate daily records"):
                M.original_purchased_day(self.root,DAY,PRIVATE)

    def test_wrong_immutable_version_rejected_before_any_market_read(self):
        with self.assertRaisesRegex(ValueError,"Wrong registered"):
            M.offline_context("b"*64,self.conf)

    def test_malformed_original_purchased_price_rejected(self):
        bad={**RAW,"close":float("nan")}
        with patch.object(M.ALL.PURCHASED,"query_bars",
                          return_value={"bars":[bad]}):
            with self.assertRaisesRegex(ValueError,"source invalid"):
                M.original_purchased_day(self.root,DAY,PRIVATE)


if __name__=="__main__":
    unittest.main(verbosity=2)
