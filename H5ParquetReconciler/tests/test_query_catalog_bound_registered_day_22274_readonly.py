"""Synthetic paired-version eight-cycle + 22274 daily provenance tests.

All bars and SHAs are FICTITIOUS. No original purchased/H5 market IO.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "test_paired_catalog_and_registered_22274",
    HERE.parent/"tools"/"query-catalog-bound-registered-day-22274-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

CAT="a"*64
DAY="b"*64
FROM="2026-10-09"
UTC8=timezone(timedelta(hours=8))
SOURCES=M.DAY_SOURCES
EVIDENCE={
    "version_sha256":DAY,
    "live_safe":"fictional-live-safe.json",
    "private_keys":"fictional-keys.json",
    "history_ledger":"fictional-ledger.json",
    "source_2016":"fictional-2016-report.json",
    "source_2026":"fictional-2026-report.json",
    "mixed_plan":"fictional-88-plan.json",
}

def make_bar(period,source):
    return {
        "symbol":"SH600000", "period":period,
        "trading_date":FROM, "value_source":source,
        "source_timestamp_ms":int(
            datetime(2026,10,9,9,30,tzinfo=UTC8).timestamp()*1000),
        "open":10.0,"high":11.0,"low":9.0,
        "close":10.5,"volume":100.0,"amount":1000.0,
    }

def day_result(source="private_h5_whole_date_candidate"):
    return {
        "bars":[make_bar("day",source)],
        "safe_summary":{
            "period":"day","symbol":"SH600000",
            "routing":"explicit_immutable_22274_day_live_verified_purchased_first",
            "registered_private_day_version_sha256":DAY,
            "registered_private_22274_day_overlay_explicitly_enabled":True,
            "verified_private_h5_fallback_enabled":False,
            "purchased_source_priority":True,
            "original_market_files_modified":False,
            "new_market_or_index_files_written":False,
            "production_query_activated":False,
            "vendor_physical_units_certified":False,
            "no_raw_ohlcva_in_safe_summary":True,
            "bars_by_source":{
                "purchased_parquet":1 if source=="purchased_parquet" else 0,
                "private_h5_whole_date_candidate":
                    1 if source=="private_h5_whole_date_candidate" else 0,
                "private_h5_mixed_stockday_candidate":
                    1 if source=="private_h5_mixed_stockday_candidate" else 0,
            },
            "matching_bar_count":1,
        },
    }

def base_result(periods):
    rows={p:[make_bar(p,"purchased_parquet")] for p in periods}
    return {
        "bars_by_period":rows,
        "safe_summary":{
            "status":M.BOUND.STATUS,
            "catalog_sha256":CAT,
            "production_query_activated":False,
            "vendor_physical_units_certified":False,
            "private_candidate_source_and_file_shas_revalidated":True,
            "matching_bars_across_requested_cycles":len(periods),
            "periods":[{
                "period":p,"matching_bar_count":1,
                "bars_by_source":{"purchased_parquet":1}
            } for p in periods],
        }
    }

class PairedCatalogRegisteredDailyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"original"
        self.root.mkdir()
        self.path=Path(self.temp.name)/"immutable_catalog.json"
        self.path.write_bytes(b"original content")
        self.events=[]
        self.daily=day_result()
        self.version=DAY
        self.patches=[
            patch.object(M.RESOLVE.REG,"load_version",side_effect=self.registered),
            patch.object(M.RESOLVE,"resolve",side_effect=self.evidence),
            patch.object(M.BOUND,"query_bundle",side_effect=self.original),
            patch.object(M.BOUND,"validate_version",side_effect=self.catalog),
            patch.object(M.BOUND,"catalog_path",return_value=self.path),
            patch.object(M.ALL,"query_bars",side_effect=self.day_query),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.stale_catalog=False
        self.changed_day_evidence=False
        self.base_is_unsafe=False
        self.end_changes=False

    def registered(self,version_sha):
        self.events.append("REGISTERED")
        self.assertEqual(version_sha,DAY)
        return {"version_sha256":DAY,"candidate_total_new_stockday_rows":22274}

    def evidence(self,version_sha):
        self.events.append("OFFLINE_RESOLVER")
        self.assertEqual(version_sha,DAY)
        result=dict(EVIDENCE)
        if self.changed_day_evidence:
            result["version_sha256"]="f"*64
        return result

    def catalog(self,root,catalog_sha):
        self.events.append("CATALOG_CHECK")
        self.assertEqual((root,catalog_sha),(self.root,CAT))
        if self.stale_catalog or (
                self.end_changes and self.events.count("CATALOG_CHECK")>1):
            raise ValueError("Source catalog changed/stale")

    def original(self,root,symbol,periods,first,last,catalog_sha,**kwargs):
        self.events.append("BASE_QUERY")
        self.assertEqual((root,symbol,first,last,catalog_sha),
                         (self.root,"SH600000",FROM,FROM,CAT))
        self.assertEqual(kwargs["allow_private_gap"],True)
        result=base_result(periods)
        if self.base_is_unsafe:
            result["safe_summary"]["production_query_activated"]=True
        return result

    def day_query(self,root,symbol,period,first,last,**kwargs):
        self.events.append("LIVE_DAY_QUERY")
        self.assertEqual((root,symbol,period,first,last),
                         (self.root,"SH600000","day",FROM,FROM))
        self.assertEqual(kwargs["private_day_evidence"],EVIDENCE)
        return copy.deepcopy(self.daily)

    def run_query(self,periods=("1min","5min","15min","30min","60min","day","week","month")):
        return M.query_bundle(
            self.root,"SH600000",periods,FROM,FROM,CAT,DAY,
            allow_registered_private_day=True,
            allow_private_minute_highcycle=True)

    def test_eight_cycle_pair_with_registered_day_reuses_existing_queries(self):
        result=self.run_query()
        s=result["safe_summary"]
        self.assertEqual(s["status"],M.STATUS)
        self.assertEqual(s["paired_research_version_sha256"],M.paired_version(CAT,DAY))
        self.assertEqual(s["registered_private_day_candidates"],22274)
        self.assertEqual(s["registered_whole_day_candidates"],22191)
        self.assertEqual(s["registered_mixed_stockday_candidates"],83)
        self.assertEqual(s["matching_bars_across_requested_cycles"],8)
        self.assertEqual(len(s["periods"]),8)
        self.assertEqual(list(result["bars_by_period"]),list(M.BOUND.CYCLE_ORDER))
        self.assertEqual(self.events[:3],
                         ["REGISTERED","OFFLINE_RESOLVER","BASE_QUERY"])
        self.assertEqual(self.events[-2:],
                         ["LIVE_DAY_QUERY","CATALOG_CHECK"])
        self.assertTrue(s["registered_day_live_original_source_reverified"])
        self.assertFalse(s["ready_for_production_query"])
        self.assertTrue(s["no_raw_ohlcva_in_safe_summary"])

    def test_day_only_validates_base_catalog_twice(self):
        result=self.run_query(("day",))
        self.assertEqual(result["safe_summary"]["matching_bars_across_requested_cycles"],1)
        self.assertEqual(self.events.count("CATALOG_CHECK"),2)
        self.assertNotIn("BASE_QUERY",self.events)

    def test_deterministic_pair_sha_and_order(self):
        a=M.paired_version(CAT,DAY)
        b=M.paired_version(CAT,DAY)
        self.assertEqual(a,b)
        self.assertEqual(len(a),64)
        self.assertNotEqual(a,M.paired_version("c"*64,DAY))

    def test_explicit_private_day_opt_in_is_required(self):
        with self.assertRaisesRegex(ValueError,"Explicit"):
            M.query_bundle(self.root,"SH600000",("day",),FROM,FROM,CAT,DAY,
                           allow_registered_private_day=False)
        self.assertEqual(self.events,[])

    def test_missing_day_period_or_duplicate_periods_refused(self):
        for periods in (("1min",),("day","day"),("day","not_cycle"),()):
            with self.subTest(periods=periods),self.assertRaisesRegex(
                    ValueError,"unique periods including day"):
                self.run_query(periods)
        self.assertEqual(self.events,[])

    def test_2017_and_cross_year_queries_rejected_before_source_io(self):
        for first,last in (("2017-01-01","2017-01-01"),
                           ("2016-12-31","2017-01-01")):
            with self.subTest(first=first),self.assertRaisesRegex(
                    ValueError,"only covers 2016 or 2026"):
                M.query_bundle(
                    self.root,"SH600000",("day",),first,last,CAT,DAY,
                    allow_registered_private_day=True)
        self.assertEqual(self.events,[])

    def test_invalid_pair_sha_format_rejected(self):
        with self.assertRaisesRegex(ValueError,"original catalog"):
            M.paired_version("bad",DAY)
        with self.assertRaisesRegex(ValueError,"registered day"):
            M.paired_version(CAT,"latest")

    def test_resolved_source_evidence_version_mismatch_refused(self):
        self.changed_day_evidence=True
        with self.assertRaisesRegex(ValueError,"another registered version"):
            self.run_query(("day",))
        self.assertNotIn("LIVE_DAY_QUERY",self.events)

    def test_base_catalog_failure_stops_before_live_day_market_scan(self):
        self.stale_catalog=True
        with self.assertRaisesRegex(ValueError,"stale"):
            self.run_query(("day",))
        self.assertNotIn("LIVE_DAY_QUERY",self.events)

    def test_non_day_source_activated_or_unsafe_blocks_daily_query(self):
        self.base_is_unsafe=True
        with self.assertRaisesRegex(ValueError,"not verified"):
            self.run_query(("1min","day"))
        self.assertNotIn("LIVE_DAY_QUERY",self.events)

    def test_daily_live_source_not_purchased_primary_rejected(self):
        self.daily["safe_summary"]["purchased_source_priority"]=False
        with self.assertRaisesRegex(ValueError,"unsafe"):
            self.run_query(("day",))

    def test_daily_provenance_counter_mismatch_rejected(self):
        self.daily["safe_summary"]["bars_by_source"]["purchased_parquet"]=1
        with self.assertRaisesRegex(ValueError,"unsafe"):
            self.run_query(("day",))

    def test_changed_daily_source_version_rejected(self):
        self.daily["safe_summary"]["registered_private_day_version_sha256"]="e"*64
        with self.assertRaisesRegex(ValueError,"unsafe"):
            self.run_query(("day",))

    def test_catalog_change_during_day_live_verification_detected(self):
        self.end_changes=True
        with self.assertRaisesRegex(ValueError,"Source catalog changed"):
            self.run_query(("day",))
        self.assertEqual(self.events.count("CATALOG_CHECK"),2)

    def test_daily_query_may_return_purchased_or_mixed_candidate_provenance(self):
        for category in ("purchased_parquet","private_h5_mixed_stockday_candidate"):
            with self.subTest(category=category):
                self.daily=day_result(category)
                output=self.run_query(("day",))
                self.assertEqual(
                    output["safe_summary"]["periods"][0]["bars_by_source"][category],1)
                self.events.clear()

    def test_no_new_source_market_file_or_auto_activation_flags(self):
        output=self.run_query(("day",))
        summary=output["safe_summary"]
        self.assertFalse(summary["original_market_files_modified"])
        self.assertFalse(summary["new_market_or_index_files_written"])
        self.assertTrue(summary["only_research_SAFE_reports_may_be_created"])
        self.assertFalse(summary["production_query_activated"])
        self.assertFalse(summary["ready_for_h5_mirror"])
        self.assertFalse(summary["physical_units_certified"])
        self.assertTrue(self.path.exists())

if __name__=="__main__":
    unittest.main()
