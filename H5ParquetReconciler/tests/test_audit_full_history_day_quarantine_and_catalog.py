"""Synthetic SHA/Parquet tests for 21-year quarantined raw-reason audit."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

TOOL=Path(__file__).resolve().parent.parent/"tools"/"audit-full-history-day-quarantine-and-catalog.py"
spec=importlib.util.spec_from_file_location("full_history_safe_catalog_audit",TOOL)
A=importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

class FullHistoryQuarantineCatalogTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="safe-37year-catalog-")
        self.addCleanup(temp.cleanup)
        self.home=Path(temp.name)
        self.reports=self.home/"reports"
        self.reports.mkdir()
        self.old=self.reports/"raw21.json"
        self.modern=self.reports/"modern.json"
        self.candidate=self.reports/"candidate37.json"
        self.old.write_text("{}",encoding="utf-8")
        self.modern.write_text("{}",encoding="utf-8")
        self.modern_sha="c"*64
        self.annually={}
        self.sources=[]
        self.entries={}
        for year in A.YEARS:
            child=f"{year:04d}"+"abcdefab"
            # Twelve lowercase hex characters (4-year digits + 8 suffix).
            folder=self.home/"work"/"unified_parquet"/"pre2011_day_candidates"/f"historical_{year}_{child}"
            folder.mkdir(parents=True)
            data=folder/"source_native_quarantine.parquet"
            reason="alternative_historical_vwap_factor_100" if year==1991 else "native_volume_or_amount_zero"
            pq.write_table(pa.table({"quarantine_reason":[reason]}),data)
            cand=folder/"purchased_schema_day_candidates.parquet"
            pq.write_table(pa.table({"trading_date":pa.array([],type=pa.string())}),cand)
            n=1 if year!=2010 else A.C.OLD_ROWS-20
            annual_path=self.reports/f"pre2011-day-candidate-{year}-{child}.json"
            ann={"purchased_schema_candidate_rows_not_vendor_certified":n-1,
                 "lossless_native_quarantine_rows":1,
                 "quarantine_by_reason":{reason:1},
                 "candidate_parquet_sha256":A.sha(cand),
                 "quarantine_parquet_sha256":A.sha(data)}
            annual_path.write_text(json.dumps(ann),encoding="utf-8")
            self.annually[year]=ann
            self.sources.append((year,self.home/f"raw_{year}.parquet",n,"d"*64))
            self.entries[str(year)]={
                "raw_h5_rows":n,
                "candidate_rows_unverified_unit_hypothesis":n-1,
                "native_raw_quarantine_rows":1,
                "candidate_parquet_relative_path":cand.relative_to(self.home).as_posix(),
                "quarantine_parquet_relative_path":data.relative_to(self.home).as_posix(),
                "candidate_parquet_sha256":A.sha(cand),
                "quarantine_parquet_sha256":A.sha(data),
                "year_receipt_sha256":A.sha(annual_path)}
        self.obj={
            "status":A.FULL_FORMAT,
            "historical_native_start":"1990-12-20",
            "modern_purchase_first_start":"2011-01-04",
            "raw_1990_2010_h5_rows_preserved":A.C.OLD_ROWS,
            "modern_2011_2026_accepted_private_rows":A.C.MODERN_ROWS,
            "all_1990_2026_source_rows_without_overlap":A.C.OLD_ROWS+A.C.MODERN_ROWS,
            "historical_candidate_vendor_units_or_corporate_actions_certified":False,
            "historical_candidate_rows_active_in_production_query":False,
            "private_active_pointer_modified":False,
            "original_market_files_or_previous_private_shards_modified":False,
            "modern_all16_version_sha256":self.modern_sha,
            "historical_full21_safe_sha256":"a"*64,
            "historical_years":self.entries,
            "purchase_schema_historical_hypothesis_rows":A.C.OLD_ROWS-21,
            "historical_native_raw_quarantined_rows":21,
        }
        self.patches=[
            patch.object(A,"MODULE",self.home),
            patch.object(A,"REPORTS",self.reports),
            patch.object(A.C,"REPORTS",self.reports),
            patch.object(A.C.W.PROFILE,"source_safe",return_value=({},"a"*64)),
            patch.object(A.C.W.PROFILE,"verified_private_files",return_value=self.sources),
            patch.object(A.C.Q,"version",return_value={"private_total_stockday_records":A.C.MODERN_ROWS}),
            patch.object(A.C,"verified_existing",side_effect=lambda y,child,full_sha,source:self.annually[y]),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def run_audit(self):
        self.candidate.write_text(json.dumps(self.obj),encoding="utf-8")
        return A.audit(self.candidate,A.sha(self.candidate),self.old,
                       self.modern,self.modern_sha)

    def test_all_21_years_preserved_and_reason_counts_match(self):
        summary=self.run_audit()
        self.assertEqual(summary["all_history_source_rows_accounted"],17820308)
        self.assertEqual(summary["historical_native_quarantined_rows"],21)
        self.assertEqual(summary["historical_purchase_schema_unverified_candidate_rows"],A.C.OLD_ROWS-21)
        self.assertEqual(summary["all_historical_quarantine_reasons"],{
            "native_volume_or_amount_zero":20,
            "alternative_historical_vwap_factor_100":1})
        self.assertFalse(summary["ready_for_production_query"])
        self.assertFalse(summary["historical_purchase_schema_semantics_certified"])

    def test_changed_annual_receipt_sha_fails(self):
        self.entries["1991"]["year_receipt_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"annual SAFE SHA"):
            self.run_audit()

    def test_reason_distribution_must_match_annual_safe(self):
        self.annually[1992]["quarantine_by_reason"]={"unproven_source":1}
        with self.assertRaisesRegex(ValueError,"reason rows disagree"):
            self.run_audit()

    def test_unsafe_production_mark_cannot_pass(self):
        self.obj["historical_candidate_rows_active_in_production_query"]=True
        with self.assertRaisesRegex(ValueError,"unsafe certification"):
            self.run_audit()

if __name__=="__main__":
    unittest.main(verbosity=2)
