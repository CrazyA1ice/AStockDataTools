"""Offline synthetic gate tests: no licensed market access."""
import importlib.util
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("factor_26_bridge_test",
    HERE.parent/"tools"/"audit-private-day-26-factor-evidence-offline.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def prior():
    o={"format":M.OLD.FORMAT,
       "total_distinct_daily_stock_days_with_candidate_factor_matches":10,
       "source_discovery_stock_days":2,"same_month_holdout_stock_days":4,
       "crossyear_holdout_stock_days":4,
       "positive_volume_factor100_sample_count":10,
       "positive_amount_factor1000_sample_count":10,
       "all_four_ohlc_raw_div1000_sample_count_per_field":10,
       "native_hikyuu_281_cpp_verified_real_stock_days":2,
       "native_cpp_tested_on_crossyear_holdouts":False,
       "sample_numeric_factor_candidate_supported":True,
       "candidate_raw_h5_volume_multiply":100,
       "candidate_raw_h5_amount_multiply":1000,
       "candidate_raw_h5_price_divide":1000,
       "raw_ohlcva_h5_integer_or_source_paths_exported":False,
       "market_source_opened_or_modified_by_this_audit":False,
       "five_safe_sha256":{str(x):format(x,"064x") for x in range(1,5)}
           | {"crossyear_holdout":"e"*64}}
    o.update(dict.fromkeys((
        "vendor_amount_physical_units_certified",
        "vendor_volume_physical_units_certified",
        "adjustment_and_timestamps_certified","universal_period_factor_certified",
        "licensed_parquet_to_native_h5_mapping_certified",
        "ready_for_full_market_mirror",
        "ready_to_modify_parquet_primary_source"),False))
    return o


def newer():
    o={"format":M.NEW.FORMAT,
       "state":"fixed_historical_original_overlap_diagnostic_not_unit_certification",
       "registered_private_version_sha256":M.VERSION,
       "samples_per_year":2,"symbols_per_date":2,
       "total_distinct_stockdays_compared":16,
       "sample_years":[2016,2020,2024,2026],
       "hypothesis_raw_h5_price_divisor":1000,
       "hypothesis_raw_h5_volume_multiplier":100,
       "hypothesis_raw_h5_amount_multiplier":1000,
       "original_h5_and_purchased_parquet_read_only":True,
       "stock_ids_ohlcva_raw_integers_paths_not_exported":True,
       "source_file_stat_before_after_unchanged":True,
       "source_file_stat_is_not_cryptographic_content_proof":True,
       "quarantined_2026_07_16_stockday_bars_not_included":5,
       "all_16_samples_numerically_within_candidate_tolerances":True,
       "numeric_mismatch_or_zero_requires_quarantine":False,
       "per_year_factor_counts":{k:{
           "paired_stockdays":4,"price_field_within_0p005":dict.fromkeys(M.PRICE,4),
           "positive_nonzero_pairs":dict.fromkeys(M.QUANTITY,4),
           "candidate_factor_hit_pairs":dict.fromkeys(M.QUANTITY,4),
           "all_sampled_numeric_candidates_match":True} for k in M.YEARS},
       "per_year_purchased_source_rows_scanned":dict.fromkeys(M.YEARS,100),
       "per_year_purchased_source_rowgroups_scanned":dict.fromkeys(M.YEARS,1)}
    o.update(dict.fromkeys((
        "candidate_source_units_certified",
        "source_adjustment_and_timestamp_semantics_certified",
        "universal_conversion_rules_across_all_stockdays_certified",
        "ready_for_production_query","ready_for_automatic_market_merge",
        "h5_mirror_created","source_market_files_written",
        "purchased_parquet_replaced",
        "private_or_production_active_pointer_modified"),False))
    return o


class EvidenceBridgeTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.reports=Path(self.dir.name)/"reports"
        self.reports.mkdir()
        patcher=patch.object(M,"REPORTS",self.reports)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.p=self.reports/"previous.json"
        self.n=self.reports/"new.json"
        self.out=self.reports/"aggregate.json"
        self.store(self.p,prior())
        self.store(self.n,newer())

    def store(self,path,obj):
        path.write_bytes((json.dumps(obj,sort_keys=True)+"\n").encode())

    def mutate(self,path,fn):
        obj=json.loads(path.read_bytes())
        fn(obj)
        self.store(path,obj)

    def test_all_26_matching_samples_and_sha(self):
        r=M.audit(self.p,self.n,self.out)
        self.assertTrue(r["all_26_candidate_factors_matched"])
        self.assertEqual(r["total_distinct_daily_stockday_factor_observations"],26)
        self.assertEqual(r["source_aggregate_safe_sha256"]["new_fixed_16_stockdays"],
                         hashlib.sha256(self.n.read_bytes()).hexdigest())
        self.assertFalse(r["candidate_source_units_certified"])
        self.assertFalse(r["ready_for_automatic_market_merge"])
        self.assertFalse(r["ready_for_full_market_mirror"])
        self.assertEqual(len(r["unresolved_independent_certification_blockers"]),6)

    def test_one_mismatch_keeps_source_unapproved(self):
        def change(o):
            q=o["per_year_factor_counts"]["2016"]
            q["candidate_factor_hit_pairs"]["amount"]=3
            q["all_sampled_numeric_candidates_match"]=False
            o["all_16_samples_numerically_within_candidate_tolerances"]=False
            o["numeric_mismatch_or_zero_requires_quarantine"]=True
        self.mutate(self.n,change)
        r=M.audit(self.p,self.n,self.out)
        self.assertFalse(r["all_26_candidate_factors_matched"])
        self.assertFalse(r["ready_for_production_query"])

    def test_inconsistent_total_rejected(self):
        self.mutate(self.n,lambda o:o.update(
            {"all_16_samples_numerically_within_candidate_tolerances":False}))
        with self.assertRaises(ValueError):
            M.audit(self.p,self.n,self.out)

    def test_missing_year_rejected(self):
        self.mutate(self.n,lambda o:o["per_year_factor_counts"].pop("2016"))
        with self.assertRaises(ValueError):
            M.audit(self.p,self.n,self.out)

    def test_bad_sample_factor_rejected(self):
        self.mutate(self.n,lambda o:o["per_year_factor_counts"]["2024"][
            "candidate_factor_hit_pairs"].update({"volume":5}))
        with self.assertRaises(ValueError):
            M.audit(self.p,self.n,self.out)

    def test_old_chain_requires_all_sha_refs(self):
        self.mutate(self.p,lambda o:o["five_safe_sha256"].pop("crossyear_holdout"))
        with self.assertRaises(ValueError):
            M.audit(self.p,self.n,self.out)

    def test_missing_vendor_evidence_does_not_become_certified(self):
        self.mutate(self.n,lambda o:o.update({"candidate_source_units_certified":True}))
        with self.assertRaises(ValueError):
            M.audit(self.p,self.n,self.out)

    def test_existing_safe_cannot_overwrite(self):
        self.out.write_bytes(b"original")
        with self.assertRaises(ValueError):
            M.audit(self.p,self.n,self.out)
        self.assertEqual(self.out.read_bytes(),b"original")

    def test_paths_cannot_leave_reports(self):
        outside=Path(self.dir.name)/"outside.json"
        outside.write_bytes(self.p.read_bytes())
        with self.assertRaises(ValueError):
            M.audit(outside,self.n,self.out)

    def test_individual_symbol_and_ohlcva_not_saved(self):
        M.audit(self.p,self.n,self.out)
        text=self.out.read_text()
        self.assertNotIn("SH600000",text)
        self.assertNotIn("SZ000001",text)
        self.assertNotIn(str(self.dir.name),text)

if __name__=="__main__":
    unittest.main(verbosity=2)
