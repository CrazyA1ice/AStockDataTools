"""Synthetic October high-cycle private candidate completion read-only ledger tests."""
from __future__ import annotations

import importlib.util
import unittest
from datetime import date
from unittest.mock import patch
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "private_oct_day_coverage_synthetic",
    HERE.parent/"tools"/"audit-2026-oct-high-cycle-private-day-coverage-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
DAY=date(2026,10,13)

class OctPrivateDayCoverageTests(unittest.TestCase):
    def setUp(self):
        self.stocks=[f"SH601{i:03d}" for i in range(10)]
        self.records={
            (DAY.isoformat(),sym) for sym in self.stocks[:8]
        } | {("2026-10-08","SZ000001"),("2026-10-09","SZ000001")}
        self.discover={
            "day":DAY.isoformat(),
            "status":M.N.A.STATUS,
            "strict_receipt_sha_verified":True,
            "original_market_files_modified":False,
            "production_activated":False,
            "vendor_physical_units_certified":False,
            "source_5min_sha256":"a"*64,
            "candidate_complete_stockdays":len(self.stocks),
            "eligible_symbols":list(self.stocks),
        }
        self.patches=[
            patch.object(M.N,"existing_stockdays",side_effect=lambda:
                         (frozenset(self.records),3)),
            patch.object(M.N.A,"discover",side_effect=lambda d,**kwargs:self.discover),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_partial_day_8_of_10_exact_and_no_optimistic_claim(self):
        result=M.audit(DAY)
        self.assertEqual(result["stage_runs_all_october_sha_verified"],3)
        self.assertEqual(result["stage_stockdays_all_october_sha_verified"],10)
        self.assertEqual(result["other_dates_staged_stockdays"],2)
        self.assertEqual(result["eligible_full_h5_5min_source_stockdays"],10)
        self.assertEqual(result["this_date_staged_complete_stockdays"],8)
        self.assertEqual(result["this_date_unstaged_complete_stockdays"],2)
        self.assertFalse(result["this_date_coverage_complete"])
        self.assertEqual(result["private_candidate_15min_rows_for_this_date"],128)
        self.assertEqual(result["private_candidate_30min_rows_for_this_date"],64)
        self.assertEqual(result["private_candidate_60min_rows_for_this_date"],32)
        self.assertEqual(result["all_october_private_candidate_rows"],280)
        self.assertFalse(result["new_market_private_or_production_files_written"])
        self.assertFalse(result["production_activated"])
        self.assertFalse(result["vendor_physical_units_certified"])
        self.assertTrue(result["no_market_OHLCVA_or_symbol_list_exported"])

    def test_complete_only_when_all_current_source_stockdays_staged(self):
        self.records.update((DAY.isoformat(),sym) for sym in self.stocks)
        r=M.audit(DAY)
        self.assertTrue(r["this_date_coverage_complete"])
        self.assertEqual(r["this_date_unstaged_complete_stockdays"],0)
        self.assertEqual(r["this_date_staged_complete_stockdays"],10)
        self.assertEqual(r["all_october_private_candidate_rows"],336)

    def test_now_unavailable_previous_source_rejected_not_counted_as_finished(self):
        self.discover["eligible_symbols"]=self.stocks[:-3]
        self.discover["candidate_complete_stockdays"]=7
        with self.assertRaisesRegex(ValueError,"not eligible"):
            M.audit(DAY)

    def test_duplicate_and_wrong_inventory_source_sha_fails_closed(self):
        self.discover["eligible_symbols"]=[self.stocks[0]]*2
        self.discover["candidate_complete_stockdays"]=2
        with self.assertRaisesRegex(ValueError,"unique stockday"):
            M.audit(DAY)
        self.discover["eligible_symbols"]=list(self.stocks)
        self.discover["candidate_complete_stockdays"]=10
        self.discover["source_5min_sha256"]="bad"
        with self.assertRaisesRegex(ValueError,"provenance/SHA"):
            M.audit(DAY)

    def test_invalid_date_fails_before_reading_registry(self):
        for bad in (date(2026,9,30),date(2027,10,13)):
            with self.subTest(day=bad):
                with self.assertRaisesRegex(ValueError,"October 2026"):
                    M.audit(bad)

    def test_fail_closed_if_prior_stage_sha_registry_fails(self):
        with patch.object(M.N,"existing_stockdays",
                          side_effect=ValueError("private Parquet SHA changed")):
            with self.assertRaisesRegex(ValueError,"SHA changed"):
                M.audit(DAY)

if __name__=="__main__":
    unittest.main()
