"""Fictional annual daily reports only; no H5 or commercial Parquet access."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def import_file(label,path):
    spec=importlib.util.spec_from_file_location(label,path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


M=import_file("full_history_day_ledger_under_test",
              HERE.parent/"tools"/"plan-parquet-primary-full-history-day-offline.py")
FIX=import_file("full_history_day_existing_exact_gate_fixture",
                HERE/"test_plan_parquet_primary_day_bootstrap_offline.py")


def annual(year=2026):
    source=copy.deepcopy(FIX.fixture())
    source=json.loads(json.dumps(source).replace("2026",str(year)))
    source["requested_from_date"]=f"{year}-01-01"
    source["requested_to_date"]=(
        "2026-10-31" if year==2026 else f"{year}-12-31")
    part=source["results"][f"day/{year}"]
    part["from_date"]=source["requested_from_date"]
    part["to_date"]=source["requested_to_date"]
    part["parquet_key_coverage_exact_when_scan_complete"]=True
    return source


def item(year):
    return (f"day-{year}-safe.json",
            json.dumps(annual(year),sort_keys=True).encode("utf-8"))


class ExactAnnualEvidenceLedgerTests(unittest.TestCase):
    def test_single_qualified_year_never_claims_full_2011_to_2026(self):
        result=M.plan_reports([item(2026)])
        self.assertEqual(result["annual_exact_day_audits_accepted"],1)
        self.assertEqual(result["missing_exact_annual_day_audit_years"],
                         list(range(2011,2026)))
        self.assertFalse(result["full_2011_to_2026_as_of_source_key_coverage_audited"])
        self.assertEqual(result["audited_totals_only_for_accepted_years"][
            "h5_only_complete_absent_date_candidates"],2)
        self.assertEqual(result["audited_totals_only_for_accepted_years"][
            "purchased_only_stockday_keys"],1)
        self.assertFalse(result["historical_unified_parquet_materialized"])
        self.assertFalse(result["ready_to_automatically_union_or_mirror"])

    def test_nonconsecutive_years_keep_each_year_sha_and_missing_status(self):
        result=M.plan_reports([item(2025),item(2011)])
        self.assertEqual([x["year"] for x in
                          result["yearly_exact_source_coverage"]],[2011,2025])
        self.assertEqual(result["audited_totals_only_for_accepted_years"][
            "overlapping_stockday_keys"],6)
        self.assertEqual(result["audited_totals_only_for_accepted_years"][
            "h5_only_complete_absent_date_candidates"],4)
        self.assertEqual(len(result["missing_exact_annual_day_audit_years"]),14)
        for entry in result["yearly_exact_source_coverage"]:
            self.assertRegex(entry["audit_source_report_sha256"],r"^[0-9a-f]{64}$")
            self.assertTrue(entry["source_key_coverage_exact_within_requested_window"])

    def test_all_16_qualified_sources_claim_coverage_only_not_union(self):
        result=M.plan_reports([item(y) for y in reversed(M.YEARS)])
        self.assertEqual(result["annual_exact_day_audits_accepted"],16)
        self.assertEqual(result["missing_exact_annual_day_audit_years"],[])
        self.assertTrue(result["full_2011_to_2026_as_of_source_key_coverage_audited"])
        self.assertIn("not_merged",result["status"])
        self.assertEqual(len(result["yearly_exact_source_coverage"]),16)
        self.assertEqual(result["audited_totals_only_for_accepted_years"][
            "purchased_unique_stockdays"],64)
        self.assertFalse(result["ready_to_automatically_union_or_mirror"])

    def test_footer_only_parquet_annual_fallback_is_never_exact(self):
        broken=annual(2011)
        part=broken["results"]["day/2011"]
        for k,v in (("pq_year_metadata_only_no_h5_rows",True),
                    ("parquet_key_coverage_exact_when_scan_complete",False),
                    ("parquet_key_coverage_exact_when_scan_complete",None)):
            with self.subTest(k=k,v=v):
                clone=copy.deepcopy(broken)
                clone["results"]["day/2011"][k]=v
                with self.assertRaisesRegex(ValueError,"footer-only|unverified"):
                    M.plan_reports([("day-2011.json",json.dumps(clone).encode())])

    def test_full_calendar_without_explicit_from_to_rejected(self):
        for field,bad in (("requested_from_date",None),
                          ("requested_to_date",None),
                          ("requested_to_date","2026-12-31"),
                          ("requested_from_date","2026-09-01")):
            with self.subTest(field=field):
                clone=annual(2026)
                clone[field]=bad
                with self.assertRaisesRegex(ValueError,"explicit year/as-of"):
                    M.plan_reports([("audited-2026.json",json.dumps(clone).encode())])

    def test_older_year_cannot_be_accepted_from_partial_window(self):
        clone=annual(2025)
        clone["requested_to_date"]="2025-11-30"
        with self.assertRaisesRegex(ValueError,"explicit year/as-of"):
            M.plan_reports([("old.json",json.dumps(clone).encode())])

    def test_tampered_conservation_rejected_not_only_counted(self):
        clone=annual(2025)
        clone["results"]["day/2025"]["h5_rows"]=999
        with self.assertRaises(ValueError):
            M.plan_reports([("bad.json",json.dumps(clone).encode())])

    def test_mixed_date_h5_gaps_are_explicit_blockers(self):
        source=annual(2026)
        sec=source["results"]["day/2026"]
        day=sec["by_day"]["20260930"]
        day["h5_unique"]+=1
        day["h5_only"]+=1
        day["union_candidate_unique"]+=1
        sec["h5_rows"]+=1
        sec["h5_only_rows"]+=1
        result=M.plan_reports([("mixed.json",json.dumps(source).encode())])
        self.assertEqual(result["audited_totals_only_for_accepted_years"][
            "h5_only_mixed_date_candidates"],1)
        self.assertEqual(result["blockers"][
            "years_with_mixed_date_h5_only_stockdays"],[2026])
        self.assertTrue(result["mixed_date_h5_gaps_cannot_use_whole_day_stager"])

    def test_price_mismatch_is_blocker_not_erased_by_volume_difference(self):
        clone=annual(2026)
        clone["results"]["day/2026"]["price_mismatch_rows"]=1
        result=M.plan_reports([("price.json",json.dumps(clone).encode())])
        self.assertEqual(result["blockers"][
            "years_with_existing_tolerance_price_disagreement"],[2026])
        self.assertFalse(result["yearly_exact_source_coverage"][0][
            "overlap_price_gate_passed_for_this_year_only"])

    def test_missing_overlap_is_not_false_ohlc_certification(self):
        clone=annual(2026)
        part=clone["results"]["day/2026"]
        part["h5_rows"]=2
        part["pq_rows"]=0
        part["matched_keys"]=0
        part["h5_only_rows"]=2
        part["pq_only_rows"]=0
        part["value_mismatch_rows"]=0
        part["quantity_mismatch_rows"]=0
        part["by_day"]={"20261001":part["by_day"]["20261001"]}
        with self.assertRaisesRegex(ValueError,"Missing purchased day source"):
            M.plan_reports([("no-purchased.json",json.dumps(clone).encode())])

    def test_duplicates_bad_format_and_unsafe_inputs_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"Duplicate source audit"):
            M.plan_reports([item(2011),("renamed-2011.json",item(2011)[1])])
        for filename,data in (("../outside.json",item(2011)[1]),
                              ("source.TXT",item(2011)[1]),
                              ("malformed.json",b"{nope"),
                              ("valid.json",b""),
                              ("bad.json",b"x"*(M.MAX_BYTES_PER_SOURCE_REPORT+1))):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    M.plan_reports([(filename,data)])

    def test_no_years_is_partial_not_empty_certification(self):
        result=M.plan_reports([])
        self.assertEqual(result["annual_exact_day_audits_accepted"],0)
        self.assertEqual(result["missing_exact_annual_day_audit_years"],
                         list(M.YEARS))
        self.assertFalse(result["full_2011_to_2026_as_of_source_key_coverage_audited"])

    def test_wrong_current_cutoff_and_year_range_rejected(self):
        for start,end,cutoff in ((2012,2026,"2026-10-31"),
                                 (2011,2025,"2026-10-31"),
                                 (2011,2026,"2025-10-31"),
                                 (2011,2026,"2026-10-1")):
            with self.subTest(cutoff=cutoff):
                with self.assertRaises(ValueError):
                    M.bounds(start,end,cutoff)

    def test_existing_report_file_and_no_market_io_in_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            reports=home/"H5ParquetReconciler"/"reports"
            reports.mkdir(parents=True)
            first=reports/"annual-2026.json"
            first.write_bytes(item(2026)[1])
            out=reports/"ledger.json"
            with patch.object(M,"REPORTS",reports):
                M.main(["--reports",str(first),"--as-of-date","2026-10-31",
                        "--out",str(out),"--offline-reports-only"])
                saved=json.loads(out.read_text(encoding="utf-8"))
                self.assertEqual(saved["annual_exact_day_audits_accepted"],1)
                self.assertTrue(saved["no_market_files_opened_by_this_offline_ledger"])
                self.assertFalse(saved["private_or_production_active_pointer_modified"])
                self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(),
                                 saved["yearly_exact_source_coverage"][0][
                                     "audit_source_report_sha256"])
                with self.assertRaises(SystemExit):
                    M.main(["--reports",str(first),"--as-of-date","2026-10-31",
                            "--out",str(out),"--offline-reports-only"])
            self.assertFalse((home/"stock").exists())

    def test_extra_risks_not_overstated_as_full_history(self):
        res=M.plan_reports([item(2026)])
        self.assertFalse(res["historical_unified_parquet_materialized"])
        self.assertTrue(res["candidate_h5_amount_volume_units_unverified"])
        self.assertTrue(res["annual_h5_private_staging_requires_separate_fresh_exact_gate"])
        self.assertFalse(res["h5_mirror_created"])
        self.assertFalse(res["original_market_parquet_or_h5_written"])


if __name__=="__main__":
    unittest.main(verbosity=2)
