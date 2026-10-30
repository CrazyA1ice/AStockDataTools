"""Offline safe count/lineage-only fixtures; never import or read market data."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "offline_ten_day_candidate_gate",
    HERE.parent/"tools"/"audit-parquet-primary-day-crossyear-factor-evidence-offline.py")
D=importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)
T=D.T


class TenStockdayCrossyearOfflineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reports=Path(self.tmp.name)/"H5ParquetReconciler"/"reports"
        self.reports.mkdir(parents=True)
        p=patch.object(T.AUDIT,"REPORTS",self.reports)
        p.start();self.addCleanup(p.stop)
        self.raw=self.reports/"raw.json"
        self.native=self.reports/"native.json"
        self.heldout=self.reports/"heldout.json"
        self.key=self.reports/"key.json"
        self.cross=self.reports/"crossyear.json"
        self.out=self.reports/"ten-stockdays.json"
        self.create_priors()

    @staticmethod
    def write(path,object):
        path.write_text(json.dumps(object),encoding="utf-8")

    @staticmethod
    def day_two():
        return {
            "stock_days_compared":2,
            "candidate_volume_raw_h5_times100_matched":2,
            "candidate_amount_raw_h5_times1000_matched":2,
            "price_h5_raw_div1000_within_0p005":{
                field:2 for field in D.FIELDS},
            "quantity_positive_nonzero_pairs":{"volume":2,"amount":2},
            "quantity_both_zero_pairs":{"volume":0,"amount":0},
            "quantity_one_zero_pairs":{"volume":0,"amount":0},
            "factor_grid_counts":{
                field:{factor:(2 if factor==winner else 0)
                       for factor in D.FACTORS}
                for field,winner in (("volume","100"),("amount","1000"))},
        }

    def create_priors(self):
        self.write(self.raw,{
            "format":T.PAIR.FORMAT,
            "sample_day":"2026-09-30",
            "two_selected_stock_days_compared":2,
            "h5_raw_day_records_read":2,
            "sources_read_only_no_h5_or_parquet_writes":True,
            "original_market_files_modified":False,
            "ready_for_full_market_mirror":False,
            "parquet_vendor_physical_amount_unit_certified":False,
            "parquet_vendor_physical_volume_unit_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "comparison":{
                "candidate_factor_multiply_raw_h5_record_to_parquet_value":{
                    "volume":{"100":2},"amount":{"1000":2}},
                "raw_h5_price_divided_1000_within_0p005_count":{
                    field:2 for field in D.FIELDS}},
        })
        self.write(self.native,{
            "format":T.HELD.NATIVE.FORMAT,
            "target_day":"2026-09-30",
            "native_status":"native_complete",
            "native_final_phase":"finished",
            "native_last_work_phase":"native_complete",
            "native_matching_stock_day_count":2,
            "all_two_native_h5_real_daily_records_match":True,
            "native_h5_raw_record_decode_evidence_for_two_stock_days":True,
            "native_get_kdata_called":True,
            "original_h5_stat_before_after_unchanged":True,
            "source_h5_or_parquet_modified":False,
            "original_parquet_or_market_sqlite_accessed":False,
            "raw_market_ohlcva_or_timestamp_recorded_in_safe":False,
            "hmac_key_or_digest_recorded_in_safe":False,
            "parquet_vendor_amount_physical_unit_certified":False,
            "parquet_vendor_volume_physical_unit_certified":False,
            "parquet_to_hikyuu_native_units_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
        })
        self.write(self.heldout,{
            "format":T.HELD.FORMAT,
            "holdout_days":list(T.HELD.DAYS),
            "prior_discovery_date_excluded":"2026-09-30",
            "observations_independent_of_discovery_date":True,
            "previous_SAFE_sha256":T.HELD.verify_chain(self.raw,self.native),
            "h5_raw_day_records_read":4,
            "original_parquet_or_h5_modified":False,
            "raw_ohlcva_or_h5_integer_values_exported":False,
            "native_decoder_consistency_not_retested_on_heldout_dates":True,
            "holdout_native_cpp_kdata_executed":False,
            "vendor_volume_physical_unit_certified":False,
            "vendor_amount_physical_unit_certified":False,
            "sample_factor_generalization_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
            "aggregate":{
                "heldout_stock_days_compared":4,
                "volume_candidate_factor100_matched":4,
                "amount_candidate_factor1000_matched":4,
                "nonzero_positive_pairs":{"volume":4,"amount":4},
                "zero_pairs":{"volume":0,"amount":0},
                "price_fields_within_tolerance":dict.fromkeys(D.FIELDS,4)},
            "per_holdout_date_diagnostic":{
                day:{
                    "stock_days_compared":2,
                    "candidate_volume_raw_h5_times100_matched":2,
                    "candidate_amount_raw_h5_times1000_matched":2,
                    "quantity_positive_nonzero_pairs":{"volume":2,"amount":2}}
                for day in T.HELD.DAYS},
        })
        self.write(self.key,{
            "format":D.KEY_ONLY_FORMAT if hasattr(D,"KEY_ONLY_FORMAT") else T.KEY_ONLY_FORMAT,
            "target_day":"2025-09-30",
            "source_period":"day",
            "status":"ready_for_bounded_price_group_read",
            "last_phase":"finished",
            "matching_target_key_count":2,
            "possible_ohlcva_rowgroup_budget":2,
            "possible_ohlcva_row_budget":150000,
            "key_scan_budget_rows":1600000,
            "source_year_footer_rowgroups":12,
            "source_year_footer_rows":24,
            "key_only_rows_scanned":24,
            "key_only_batches_scanned":12,
            "selected_target_rowgroups":1,
            "selected_target_rowgroup_total_rows":2,
            "ohlcva_rows_scanned":0,
            "ohlcva_columns_opened":False,
            "raw_h5_or_market_sqlite_opened":False,
            "real_native_cpp_invoked":False,
            "original_parquet_modified":False,
            "original_source_footer_unchanged":True,
            "raw_symbols_timestamps_ohlcva_or_paths_emitted":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "vendor_physical_units_certified":False,
            "ready_for_full_market_mirror":False,
        })
        links={**T.verified_sources(self.raw,self.native,self.heldout),
               "annual_2025_key_only":hashlib.sha256(
                   self.key.read_bytes()).hexdigest()}
        self.write(self.cross,{
            "format":T.FORMAT,
            "fixed_crossyear_samples":list(D.DAYS),
            "independent_of_prior_2026_09_discovery_and_heldout_days":True,
            "source_period":"day",
            "symbols_sampled_count":2,
            "source_parquet_files_read":2,
            "source_parquet_layouts":{
                "2025":"annual_two_column_key_revalidated",
                "2026":"monthly"},
            "previous_safe_sha256":links,
            "annual_2025_prior_key_only_safe_revalidated":True,
            "annual_2025_key_only_rows_rechecked":24,
            "annual_2025_key_only_batches_rechecked":12,
            "annual_2025_source_total_rows_from_footer":24,
            "annual_2025_source_rowgroups_from_footer":12,
            "annual_2025_selected_rowgroups_scanned":1,
            "annual_2025_ohlcva_rows_scanned":2,
            "source_parquet_total_rows_scanned":4,
            "source_parquet_row_groups_scanned":2,
            "raw_h5_day_records_read":4,
            "native_cpp_h5_decoding_on_crossyear_samples_executed":False,
            "previous_native_real_decode_was_only_2026_09_30":True,
            "source_files_stat_or_footer_before_after_unchanged":True,
            "entire_market_source_files_sha256_checked":False,
            "source_files_modified":False,
            "market_sqlite_or_h5_writes_performed":False,
            "raw_ohlcva_or_native_integer_values_in_report":False,
            "raw_market_paths_or_individual_source_timestamps_in_report":False,
            "vendor_amount_physical_units_certified":False,
            "vendor_volume_physical_units_certified":False,
            "source_timestamp_semantics_certified":False,
            "universal_factor_across_time_or_periods_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "ready_for_full_market_mirror":False,
            "per_sample_day":{day:self.day_two() for day in D.DAYS},
            "crossyear_aggregate":{
                "stock_days_compared":4,
                "volume_candidate_raw_h5_times100_matched":4,
                "amount_candidate_raw_h5_times1000_matched":4,
                "per_field_price_tolerance_matches":dict.fromkeys(D.FIELDS,4),
                "nonzero_positive_pairs":{"volume":4,"amount":4},
                "both_zero_pairs":{"volume":0,"amount":0},
                "one_zero_pairs":{"volume":0,"amount":0}},
        })

    def run_it(self):
        return D.audit(self.raw,self.native,self.heldout,
                       self.key,self.cross,self.out)

    def edit_cross(self,transform):
        obj=json.loads(self.cross.read_text(encoding="utf-8"))
        transform(obj)
        self.write(self.cross,obj)

    def test_five_safe_valid_chain_produces_only_ten_count_candidate_evidence(self):
        report=self.run_it()
        self.assertEqual(report["total_distinct_daily_stock_days_with_candidate_factor_matches"],10)
        self.assertEqual(report["positive_amount_factor1000_sample_count"],10)
        self.assertEqual(report["positive_volume_factor100_sample_count"],10)
        self.assertEqual(report["all_four_ohlc_raw_div1000_sample_count_per_field"],10)
        self.assertEqual(report["native_hikyuu_281_cpp_verified_real_stock_days"],2)
        self.assertEqual(report["annual_2025_ohlcva_rows_verified"],2)
        self.assertEqual(len(report["five_safe_sha256"]),5)
        self.assertFalse(report["ready_for_full_market_mirror"])
        self.assertFalse(report["licensed_parquet_to_native_h5_mapping_certified"])
        data=self.out.read_text(encoding="utf-8")
        for forbidden in ("SH600000","SZ000001","HikyuuData",
                          "AllCycleAStockData","600000.XSHG","202509300000"):
            self.assertNotIn(forbidden,data)

    def test_crossyear_amount_count_cannot_be_three_without_fail_closed(self):
        self.edit_cross(lambda x:x["crossyear_aggregate"].update(
            {"amount_candidate_raw_h5_times1000_matched":3}))
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_one_day_zero_value_is_not_factor_support(self):
        self.edit_cross(lambda x:x["per_sample_day"]["2025-09-30"].update(
            {"quantity_positive_nonzero_pairs":{"volume":1,"amount":2}}))
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_wrong_proof_chain_fails_without_any_source_access(self):
        self.edit_cross(lambda x:x["previous_safe_sha256"].update(
            {"annual_2025_key_only":"0"*64}))
        with self.assertRaisesRegex(ValueError,"Crossyear real numeric"):
            self.run_it()

    def test_vendor_unit_flag_cannot_be_promoted_by_source(self):
        self.edit_cross(lambda x:x.update({"vendor_amount_physical_units_certified":True}))
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_annual_target_group_count_drift_rejected(self):
        self.edit_cross(lambda x:x.update({"annual_2025_ohlcva_rows_scanned":3}))
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertFalse(self.out.exists())

    def test_wrong_2025_key_only_proof_status_rejected(self):
        key=json.loads(self.key.read_text(encoding="utf-8"))
        key["status"]="duplicate_target_keys"
        self.write(self.key,key)
        with self.assertRaises(ValueError):
            self.run_it()

    def test_output_is_exclusive_and_inside_module_reports(self):
        self.out.write_text("protected",encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_it()
        self.assertEqual(self.out.read_text(encoding="utf-8"),"protected")
        other=Path(self.tmp.name)/"outside.json"
        with self.assertRaises(ValueError):
            D.audit(self.raw,self.native,self.heldout,self.key,self.cross,other)


if __name__=="__main__":
    unittest.main(verbosity=2)
