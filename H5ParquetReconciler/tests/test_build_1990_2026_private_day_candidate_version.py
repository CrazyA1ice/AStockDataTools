"""Two synthetic no-market-I/O checks of SHA-resumable full historical DAY
candidate version orchestration. Existing real 21-year H5 RAW and 16 modern
private Parquet parts are never touched by these tests.
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location("full_history_daily_candidate_coordinator",
    HERE.parent/"tools"/"build-1990-2026-private-day-candidate-version.py")
C=importlib.util.module_from_spec(s)
s.loader.exec_module(C)

class FullHistoryDayCandidateVersionTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="historical-day-version-")
        self.addCleanup(t.cleanup)
        self.home=Path(t.name)
        self.reports=self.home/"reports"
        self.reports.mkdir()
        self.candidates=self.home/"work"/"unified_parquet"/"pre2011_day_candidates"
        self.old_counts={year:1 for year in C.YEARS}
        self.old_counts[2010]=C.OLD_ROWS-20
        self.sources=[(year,self.home/f"source-{year}.parquet",
                       self.old_counts[year],"a"*64)
                      for year in C.YEARS]
        self.calls=[]

    def fake_annual(self,year,full21,run_id,safe,**kwargs):
        self.calls.append((year,run_id))
        folder=self.candidates/f"historical_{year}_{run_id}"
        folder.mkdir(parents=True)
        native=self.old_counts[year]
        obj={"format":C.W.FORMAT,
             "status":"historical_day_candidate_and_raw_quarantine_materialized_not_merged",
             "year":year,"total_raw_h5_rows":native,
             "purchased_schema_candidate_rows_not_vendor_certified":native-1,
             "lossless_native_quarantine_rows":1,
             "candidate_parquet_relative_path":str((folder/"candidate.parquet").relative_to(self.home)).replace("\\","/"),
             "candidate_parquet_sha256":"b"*64,
             "quarantine_parquet_relative_path":str((folder/"quarantine.parquet").relative_to(self.home)).replace("\\","/"),
             "quarantine_parquet_sha256":"c"*64}
        safe.write_text(json.dumps(obj),encoding="utf-8")
        return obj

    def test_full_21_source_years_are_classified_and_modern_version_is_not_rebuilt(self):
        runid="0123456789ab"
        target=self.reports/"full-day-version.json"
        with patch.object(C,"MODULE",self.home),patch.object(
                C,"REPORTS",self.reports),patch.object(
                C.W,"WORK",self.candidates),patch.object(
                C.W.PROFILE,"source_safe",return_value=({},"f"*64)),patch.object(
                C.W.PROFILE,"verified_private_files",return_value=self.sources),patch.object(
                C.Q,"version",return_value={
                    "private_total_stockday_records":C.MODERN_ROWS}),patch.object(
                C.W,"annual",side_effect=self.fake_annual):
            r=C.assemble(self.home/"prior.json",self.home/"modern.json",
                         "d"*64,runid,target)
        self.assertEqual(len(self.calls),21)
        self.assertEqual(r["all_1990_2026_source_rows_without_overlap"],
                         C.OLD_ROWS+C.MODERN_ROWS)
        self.assertEqual(r["purchase_schema_historical_hypothesis_rows"],
                         C.OLD_ROWS-21)
        self.assertEqual(r["historical_native_raw_quarantined_rows"],21)
        self.assertFalse(r["historical_candidate_rows_active_in_production_query"])
        self.assertTrue(r["modern_2011_2026_shards_are_referenced_not_rewritten"])
        self.assertEqual(len(r["historical_years"]),21)

    def test_interrupted_year_folder_is_preserved_and_new_child_id_used(self):
        runid="fedcba987654"
        year=1995
        prior_child=hashlib.sha256((runid+":"+str(year)+":0")
                                   .encode("ascii")).hexdigest()[:12]
        abandoned=self.candidates/f"historical_{year}_{prior_child}"
        abandoned.mkdir(parents=True)
        (abandoned/"incomplete").write_text("MUST STAY")
        with patch.object(C,"MODULE",self.home),patch.object(
                C,"REPORTS",self.reports),patch.object(
                C.W,"WORK",self.candidates),patch.object(
                C.W.PROFILE,"source_safe",return_value=({},"f"*64)),patch.object(
                C.W.PROFILE,"verified_private_files",return_value=self.sources),patch.object(
                C.Q,"version",return_value={
                    "private_total_stockday_records":C.MODERN_ROWS}),patch.object(
                C.W,"annual",side_effect=self.fake_annual):
            C.assemble(self.home/"prior.json",self.home/"modern.json",
                       "d"*64,runid,self.reports/"restart.json")
        self.assertEqual((abandoned/"incomplete").read_text(),"MUST STAY")
        actual=[child for y,child in self.calls if y==year]
        self.assertEqual(len(actual),1)
        self.assertNotEqual(actual[0],prior_child)

if __name__=="__main__":
    unittest.main(verbosity=2)
