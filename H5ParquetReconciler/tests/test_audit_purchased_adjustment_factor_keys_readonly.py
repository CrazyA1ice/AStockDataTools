"""Synthetic HFQ factor original-only key audit: no Kline read or writes."""
from __future__ import annotations
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "synthetic_hfq_factor_key_only_audit",
    HERE.parent/"tools"/"audit-purchased-adjustment-factor-keys-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class OriginalHfqFactorKeyAuditTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.pa,self.pq=pa,pq
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.folder=self.root/"AllCycleAStockData"/M.SOURCE.LABEL
        self.folder.mkdir(parents=True)
        self.source=self.folder/"unnamed.factor.parquet"
        self.write([
            ("SH600000",date(2025,1,2),1.0),
            ("SH600000",date(2025,1,3),1.5),
            ("SZ000001",date(2026,1,6),2.0),
        ])

    def write(self,rows):
        a=self.pa
        self.pq.write_table(a.table({
            "symbol":a.array([x[0] for x in rows],type=a.string()),
            "d":a.array([x[1] for x in rows],type=a.date32()),
            "hfq_factor":a.array([x[2] for x in rows],type=a.float64()),
        }),self.source)

    def test_real_arrow_three_column_factor_date_profile(self):
        stat=(self.source.stat().st_size,self.source.stat().st_mtime_ns)
        result=M.audit(self.root)
        self.assertEqual(result["rows_from_footer"],3)
        self.assertEqual(result["factor_rows_examined"],3)
        self.assertEqual(result["distinct_raw_source_symbols"],2)
        self.assertEqual(result["distinct_raw_symbol_date_keys"],3)
        self.assertEqual(result["earliest_valid_original_factor_date"],"2025-01-02")
        self.assertEqual(result["latest_valid_original_factor_date"],"2026-01-06")
        self.assertEqual(result["observed_rows_by_year"],{"2025":2,"2026":1})
        self.assertEqual(result["counts"]["positive_factor_equal_one_rows"],1)
        self.assertEqual(result["counts"]["positive_factor_not_one_rows"],2)
        self.assertFalse(result["purchased_ohlcva_files_or_rows_opened"])
        self.assertFalse(result["individual_security_identifiers_or_factor_values_exported"])
        self.assertFalse(result["factor_direction_base_date_and_adjustment_semantics_certified"])
        self.assertFalse(result["production_activated"])
        self.assertEqual(stat,(self.source.stat().st_size,self.source.stat().st_mtime_ns))
        self.assertNotIn("SH600000",str(result))
        self.assertNotIn("1.5",str(result))

    def test_duplicates_and_invalid_values_flagged_without_kline_mutation(self):
        self.write([
            ("SH600000",date(2025,1,2),1.0),
            ("SH600000",date(2025,1,2),0.0),
            ("SZ000001",date(2025,1,3),float("nan")),
            ("SZ000001",date(2025,1,4),-2.0),
            ("SZ000001",date(2025,1,5),None),
        ])
        result=M.audit(self.root)
        self.assertEqual(result["counts"]["duplicate_exact_symbol_day_keys"],1)
        self.assertEqual(result["counts"]["nonpositive_factors"],2)
        self.assertEqual(result["counts"]["nonfinite_factors"],1)
        self.assertEqual(result["counts"]["null_or_nonnumeric_factors"],1)
        self.assertFalse(result["new_market_or_index_files_written"])

    def test_invalid_source_symbol_date_fails_open_only_as_diagnostic_not_certification(self):
        self.write([
            ("",date(2025,1,2),1.0),
            ("SH600000",None,1.1),
        ])
        r=M.audit(self.root)
        self.assertEqual(r["counts"]["null_or_invalid_symbols"],1)
        self.assertEqual(r["counts"]["null_or_invalid_dates"],1)
        self.assertEqual(r["distinct_raw_symbol_date_keys"],0)
        self.assertEqual(r["factor_health_rows_classified"],2)
        self.assertEqual(r["counts"]["null_date_rows"],1)
        self.assertEqual(r["distinct_symbols_with_any_valid_symbol_field"],1)
        self.assertFalse(r["factor_row_day_keys_verified_against_official_actions"])

    def test_null_date_record_one_per_stock_is_only_an_uninterpreted_candidate(self):
        self.write([
            ("SH600000",None,1.0),
            ("SH600000",date(2025,1,2),1.2),
            ("SZ000001",None,float("nan")),
            ("SZ000001",date(2025,1,3),2.0),
            ("BJ920000",None,0.0),
        ])
        r=M.audit(self.root)
        self.assertEqual(r["factor_rows_examined"],5)
        self.assertEqual(r["factor_health_rows_classified"],5)
        self.assertEqual(r["counts"]["null_date_rows"],3)
        self.assertEqual(r["counts"]["non_null_invalid_date_rows"],0)
        self.assertEqual(r["distinct_symbols_with_any_valid_symbol_field"],3)
        self.assertEqual(r["distinct_raw_source_symbols"],2)
        self.assertEqual(r["distinct_symbols_with_null_date_rows"],3)
        self.assertEqual(r["symbols_with_multiple_null_date_rows"],0)
        self.assertEqual(r["symbols_with_both_null_and_valid_dates"],2)
        self.assertEqual(r["symbols_with_only_null_dates"],1)
        self.assertEqual(r["counts"]["nonfinite_factors"],1)
        self.assertEqual(r["counts"]["nonpositive_factors"],1)
        self.assertTrue(r["invalid_date_rows_preserved_as_uninterpreted_source"])
        self.assertFalse(r["null_date_rows_treated_as_initial_factor"])
        self.assertFalse(r["factor_direction_base_date_and_adjustment_semantics_certified"])

    def test_multiple_null_dates_and_out_of_range_day_separately_counted(self):
        self.write([
            ("SH600000",None,1.0),
            ("SH600000",None,2.0),
            ("SH600000",date(1800,1,1),3.0),
            ("SH600000",date(2025,1,2),4.0),
        ])
        r=M.audit(self.root)
        self.assertEqual(r["counts"]["null_date_rows"],2)
        self.assertEqual(r["counts"]["non_null_invalid_date_rows"],1)
        self.assertEqual(r["counts"]["null_or_invalid_dates"],3)
        self.assertEqual(r["symbols_with_multiple_null_date_rows"],1)
        self.assertEqual(r["distinct_symbols_with_other_invalid_date_rows"],1)
        self.assertEqual(r["factor_health_rows_classified"],4)
        self.assertEqual(r["distinct_raw_symbol_date_keys"],1)
        self.assertEqual(r["counts"]["duplicate_exact_symbol_day_keys"],0)

    def test_wrong_vendor_factor_field_type_fails_closed(self):
        self.pq.write_table(self.pa.table({
            "symbol":["SH600000"],
            "d":self.pa.array([date(2025,1,2)],type=self.pa.date32()),
            "hfq_factor":["untrusted"],
        }),self.source)
        with self.assertRaisesRegex(ValueError,"Unexpected original factor column type"):
            M.audit(self.root)

    def test_missing_required_factor_column_fails_closed(self):
        self.pq.write_table(self.pa.table({
            "symbol":["SH600000"],
            "d":self.pa.array([date(2025,1,2)],type=self.pa.date32()),
        }),self.source)
        with self.assertRaisesRegex(ValueError,"Missing required original factor column"):
            M.audit(self.root)

    def test_strict_scan_budget_stops_before_factor_source_scan(self):
        with self.assertRaisesRegex(ValueError,"bounded read budget"):
            M.audit(self.root,max_rows=2)
        for value in (0,True, M.MAX_ROWS+1):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,"bounded row budget"):
                    M.audit(self.root,max_rows=value)

    def test_no_purchased_kline_folder_needed_to_read_factor_keys(self):
        r=M.audit(self.root)
        self.assertFalse((self.root/"AllCycleAStockData"/"day").exists())
        self.assertTrue(r["factor_row_scan_only_not_Kline"])


if __name__=="__main__":
    unittest.main(verbosity=2)
