"""No-market-write catalog SHA-binding, source drift, eight-cycle routing tests."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "test_catalog_version_bound_eightcycle_query",
    HERE.parent/"tools"/"query-catalog-bound-purchased-primary-eight-cycles-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
START="2026-09-30"
END="2026-10-13"
SYMBOL="SH600000"
UTC8=timezone(timedelta(hours=8))
HIGH=frozenset(("15min","30min","60min"))
MINUTE=frozenset(("1min","5min"))

def row(period,source):
    return {
        "symbol":SYMBOL,"period":period,
        "trading_date":START,
        "source_timestamp_ms":int(
            datetime(2026,9,30,9,30,tzinfo=UTC8).timestamp()*1000),
        "value_source":source,
        "open":1.0,"high":1.2,"low":0.8,"close":1.1,
        "volume":100.0,"amount":100.0,
    }

class VersionBoundEightCycleQueryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/"market"
        self.root.mkdir()
        self.module=Path(temp.name)/"H5ParquetReconciler"
        directory=self.module/"work"/"unified_parquet"/"source_catalog"
        directory.mkdir(parents=True)
        self.payload={
            "status":M.CATALOG.STATUS,
            "periods":list(M.CYCLE_ORDER),
            "purchased_reference_mode":"original_parquet_file_refs_not_copied",
            "research_query_explicit_opt_in_required":True,
            "original_market_files_modified":False,
            "market_OHLCVA_read_or_copied_for_catalog":False,
            "new_market_index_or_parquet_materialized":False,
            "production_or_private_active_pointer_modified":False,
            "ready_for_production_merge":False,
            "ready_for_h5_mirror":False,
            "vendor_units_certified":False,
            "timestamp_semantics_certified":False,
            "corporate_actions_certified":False,
            "full_historical_stockday_key_coverage_certified":False,
            "purchased":{
                "purchased_source_files_copied":False,
                "original_purchased_file_identity_is_stat_not_full_content_sha256":True,
                "original_source_files_by_period_year":{
                    "15min|2026":[{"relative_path":"AllCycleAStockData/15min/2026.parquet"}],
                    "1min|2026":[{"relative_path":"AllCycleAStockData/1min/2026.parquet"}]
                },
            },
            "private_research_candidates":{
                "all_private_candidates_research_only":True,
                "stockdays_by_date":{"2026-10-13":2},
                "highcycle_total_candidate_rows":56,
                "minute_h5_gap_private_references":[
                    {"day":"2026-10-13","period":"1min"},
                    {"day":"2026-10-13","period":"5min"}
                ],
            },
        }
        self.sealed=M.CATALOG.seal(self.payload)
        self.file=directory/("catalog_"+self.sealed["catalog_sha256"]+".json")
        self.file.write_bytes(M.CATALOG._json(self.sealed))
        self.live=copy.deepcopy(self.payload)
        self.calls=[]
        self._patches=[
            patch.object(M.CATALOG,"MODULE",self.module),
            patch.object(M.CATALOG,"assemble",side_effect=lambda root:self.live),
            patch.object(M.ALL,"query_bars",side_effect=self.normal_query),
            patch.object(M.HIGHQUERY,"query_bars",side_effect=self.high_query),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        self.unsafe_router=None
        self.alter_catalog_during=None
        self.extra_day_private=False

    def normal_query(self,root,symbol,period,first,last,**kw):
        self.calls.append(("normal",period,kw.get("allow_verified_private_h5")))
        self.assertEqual((symbol,first,last),(SYMBOL,START,END))
        rows=[row(period,"purchased_parquet")]
        self.assertEqual(root,self.root)
        self.assertIn(period,M.CYCLE_ORDER)
        if period in MINUTE and kw.get("allow_verified_private_h5"):
            candidate=row(period,"private_h5_only_complete_stockday")
            candidate["source_timestamp_ms"]+=86400000
            rows.append(candidate)
        if self.extra_day_private and period=="day":
            rows[0]["value_source"]="private_h5_only_complete_stockday"
        safe={
            "period":period,"symbol":symbol,
            "matching_bar_count":len(rows),
            "bars_by_source":{
                "purchased_parquet":sum(r["value_source"]=="purchased_parquet" for r in rows),
                "private_h5_only_complete_stockday":sum(
                    r["value_source"]!="purchased_parquet" for r in rows),
            },
            "production_query_activated":False,
            "original_market_files_modified":False,
            "new_market_or_index_files_written":False,
            "vendor_physical_units_certified":False,
        }
        if self.unsafe_router=="normal":
            safe["production_query_activated"]=True
        if self.alter_catalog_during==period:
            self.file.write_text("changed",encoding="utf-8")
        return {"bars":rows,"safe_summary":safe}

    def high_query(self,root,symbol,period,first,last,**kw):
        self.calls.append(("high",period,kw.get("allow_private_highcycle")))
        self.assertEqual((symbol,first,last),(SYMBOL,START,END))
        self.assertEqual(root,self.root)
        rows=[row(period,"purchased_parquet")]
        if kw.get("allow_private_highcycle"):
            candidate=row(period,"research_derived_candidate_from_sha_verified_h5_5min")
            candidate["source_timestamp_ms"]+=86400000
            rows.append(candidate)
        safe={
            "status":M.HIGHQUERY.OUTPUT_STATUS,
            "period":period,"symbol":symbol,
            "matching_bar_count":len(rows),
            "bars_by_source":{
                "purchased_parquet":1,
                "research_derived_candidate_from_sha_verified_h5_5min":
                    len(rows)-1,
            },
            "ready_for_production_query":False,
            "original_market_files_modified":False,
            "new_market_or_index_files_written":False,
            "private_or_production_active_pointer_modified":False,
            "vendor_physical_units_certified":False,
        }
        if self.unsafe_router=="high":
            safe["ready_for_production_query"]=True
        return {"bars":rows,"safe_summary":safe}

    def go(self,periods=None,opt_in=True):
        return M.query_bundle(
            self.root,SYMBOL,list(M.CYCLE_ORDER) if periods is None else periods,
            START,END,self.sealed["catalog_sha256"],allow_private_gap=opt_in)

    def test_all_eight_cycle_source_bound_opt_in_query_in_memory_only(self):
        result=self.go()
        safe=result["safe_summary"]
        self.assertEqual(len(safe["periods"]),8)
        self.assertEqual(safe["catalog_sha256"],self.sealed["catalog_sha256"])
        self.assertEqual(safe["purchased_original_file_refs"],2)
        self.assertEqual(safe["highcycle_private_candidate_rows"],56)
        self.assertEqual(safe["h5_private_minute_refs"],2)
        self.assertEqual(safe["matching_bars_across_requested_cycles"],13)
        self.assertEqual(len(result["bars_by_period"]),8)
        self.assertEqual(
            [x[1] for x in self.calls],list(M.CYCLE_ORDER))
        self.assertEqual(
            [x for x in self.calls if x[2] is True],
            [("normal","1min",True),("normal","5min",True),
             ("high","15min",True),("high","30min",True),("high","60min",True)])
        self.assertFalse(safe["ready_for_production_query"])
        self.assertTrue(safe["catalog_all_purchased_and_private_sources_revalidated_at_start"])
        self.assertTrue(safe["no_raw_ohlcva_in_safe_summary"])
        self.assertEqual(list(self.file.parent.iterdir()),[self.file])

    def test_all_eight_default_source_only_without_any_h5_return(self):
        result=self.go(opt_in=False)
        self.assertEqual(result["safe_summary"]["matching_bars_across_requested_cycles"],8)
        self.assertEqual(len(self.calls),8)
        self.assertFalse(any(call[2] for call in self.calls))

    def test_duplicate_period_refused_before_source_audit_or_query(self):
        with patch.object(M.CATALOG,"assemble") as live:
            with self.assertRaisesRegex(ValueError,"unique"):
                self.go(periods=["1min","1min"])
        live.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_invalid_explicit_catalog_sha_or_missing_version_rejected(self):
        with self.assertRaisesRegex(ValueError,"64-hex"):
            M.query_bundle(self.root,SYMBOL,["15min"],START,END,"bad")
        with self.assertRaisesRegex(ValueError,"missing"):
            M.query_bundle(self.root,SYMBOL,["15min"],START,END,"a"*64)
        self.assertEqual(self.calls,[])

    def test_catalog_file_bytes_tampered_prevents_any_market_read(self):
        self.file.write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"envelope malformed"):
            self.go()
        self.assertEqual(self.calls,[])

    def test_purchased_original_file_stat_drift_detected_before_query(self):
        self.live["purchased"]["original_source_files_by_period_year"][
            "1min|2026"][0]["relative_path"]="AllCycleAStockData/1min/changed.parquet"
        with self.assertRaisesRegex(ValueError,"stale"):
            self.go()
        self.assertEqual(self.calls,[])

    def test_private_h5_content_sha_drift_detected_before_query(self):
        self.live["private_research_candidates"]["minute_h5_gap_private_references"][
            0]["content_sha256"]="f"*64
        with self.assertRaisesRegex(ValueError,"stale"):
            self.go()
        self.assertEqual(self.calls,[])

    def test_highcycle_production_flag_refuses_results(self):
        self.unsafe_router="high"
        with self.assertRaisesRegex(ValueError,"Highcycle router"):
            self.go(periods=["15min"])
        self.assertEqual(len(self.calls),1)

    def test_minute_production_flag_refuses_results(self):
        self.unsafe_router="normal"
        with self.assertRaisesRegex(ValueError,"router unsafe"):
            self.go(periods=["1min"])
        self.assertEqual(len(self.calls),1)

    def test_day_unregistered_private_overlay_refused_even_if_opted_in(self):
        self.extra_day_private=True
        with self.assertRaisesRegex(ValueError,"NOT included"):
            self.go(periods=["day"])

    def test_catalog_mutation_during_query_fails_closed(self):
        self.alter_catalog_during="1min"
        with self.assertRaisesRegex(ValueError,"modified during"):
            self.go(periods=["1min"])
        self.assertEqual(len(self.calls),1)

    def test_non_boolean_opt_in_refuses_request(self):
        with self.assertRaisesRegex(ValueError,"must be boolean"):
            M.query_bundle(self.root,SYMBOL,["1min"],START,END,
                           self.sealed["catalog_sha256"],allow_private_gap=1)
        self.assertEqual(self.calls,[])

if __name__=="__main__":
    unittest.main()
