"""Targeted minute-alignment diagnostic synthetic tests. No paid OHLCV data."""
import importlib.util
import types
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/"tools"/"diagnose-5min-alignment.py"
SPEC=importlib.util.spec_from_file_location("diagnose_5min_alignment",SOURCE)
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class AlignmentDiagnosticTests(unittest.TestCase):
    def test_source_aliases_include_vendor_and_market_label(self):
        self.assertIn("600000.XSHG",M.source_spellings("SH600000"))
        self.assertIn("SH600000",M.source_spellings("SH600000"))
        self.assertIn("000636.XSHE",M.source_spellings("SZ000636"))
        self.assertIn("920680.XBSE",M.source_spellings("BJ920680"))
        with self.assertRaises(ValueError):
            M.source_spellings("SZ399000x")

    def test_symbol_row_group_pruning_safe_when_stats_missing(self):
        def rg(typ,low=None,high=None):
            stats=None if typ=="missing" else types.SimpleNamespace(
                has_min_max=True,min=low,max=high)
            return types.SimpleNamespace(
                num_columns=1,
                column=lambda i:types.SimpleNamespace(
                    path_in_schema="symbol",statistics=stats))
        targets=M.source_spellings("SH600000")
        self.assertTrue(M.might_contain_symbols(rg("missing"),targets))
        self.assertTrue(M.might_contain_symbols(rg("present","600000.XSHG","600001.XSHG"),targets))
        self.assertFalse(M.might_contain_symbols(rg("present","601000.XSHG","601999.XSHG"),targets))
        self.assertTrue(M.might_contain_symbols(rg("present","XX", "AA"),targets))
        self.assertTrue(M.might_contain_symbols(rg("present",123,456),targets))

    def test_shift_5_fits_ohlc_while_zero_does_not(self):
        sym="SH600000"
        h5={(sym,202509300935):(10,11,9,10,100,1000),
            (sym,202509300940):(12,13,11,12,200,2000)}
        parquet={(sym,202509300930):(10,11,9,10,100,1000),
                 (sym,202509300935):(12,13,11,12,200,2000)}
        d=M.evaluate(h5,parquet)
        self.assertEqual(d["5"]["matched_bars"],2)
        self.assertEqual(d["5"]["all_ohlc_equal_bars"],2)
        self.assertEqual(d["0"]["matched_bars"],1)
        self.assertEqual(d["0"]["all_ohlc_equal_bars"],0)
        self.assertEqual(d["5"]["volume_agreement_by_h5_multiplier"]["1"],2)

    def test_unit_multiplier_diagnosis(self):
        sym="SZ000636"
        h5={(sym,202509300935):(10,10,10,10,100,1000)}
        parquet={(sym,202509300930):(10,10,10,10,10000,1000000)}
        d=M.evaluate(h5,parquet)
        self.assertEqual(d["5"]["matched_bars"],1)
        self.assertEqual(d["5"]["volume_agreement_by_h5_multiplier"]["100"],1)
        self.assertEqual(d["5"]["amount_agreement_by_h5_multiplier"]["1000"],1)
        self.assertEqual(d["5"]["volume_agreement_by_h5_multiplier"]["1"],0)

    def test_output_does_not_export_ohlcv_values(self):
        h5={("SH600000",202509300935):(10,11,9,10,100,1000)}
        parquet={("SH600000",202509300930):(10,11,9,10,100,1000)}
        d=M.evaluate(h5,parquet)
        self.assertEqual(set(d.keys()),{"-5","0","5","10"})
        self.assertNotIn("open",d["5"])
        self.assertEqual(d["5"]["different_price_field_counts"],{})
        self.assertEqual(d["5"]["matched_bars_by_symbol"]["SH600000"],1)

    def test_attribution_per_symbol_price_boundary_and_quantity_ratio(self):
        sym="SH600000"
        h={
            (sym,202509300935):(10,11,9,10.0,100,1000),
            (sym,202509300940):(12,13,11,12.0,200,2000)
        }
        p={
            (sym,202509300930):(10.02,11,9,10.02,200,3000),
            (sym,202509300935):(12,13,11,12,400,6000)
        }
        report=M.attribute_differences(h,p)[sym]
        self.assertEqual(report["h5_bars"],2)
        self.assertEqual(report["parquet_bars"],2)
        self.assertEqual(report["matched_bars"],2)
        self.assertEqual(report["high_low_equal_bars"],2)
        self.assertEqual(report["high_low_equal_but_open_or_close_diff"],1)
        self.assertEqual(report["both_ohlc_equal_bars"],1)
        self.assertEqual(report["price_abs_difference_quantiles"]["open"]["count"],1)
        self.assertEqual(report["price_abs_difference_quantiles"]["open"]["median"],0.02)
        self.assertEqual(report["price_abs_difference_quantiles"]["close"]["median"],0.02)
        self.assertEqual(report["parquet_over_h5_volume_ratio"]["median"],2)
        self.assertEqual(report["parquet_over_h5_amount_ratio"]["median"],3)
        self.assertEqual(report["intraday_segments"]["morning"]["matched"],2)

    def test_attribution_zero_denominator_is_not_misleading(self):
        sym="SZ000636"
        h={(sym,202509300935):(10,10,10,10,0,0)}
        p={(sym,202509300930):(10,10,10,10,1,20)}
        report=M.attribute_differences(h,p)[sym]
        self.assertEqual(report["volume_zero_counts"]["h5_zero"],1)
        self.assertEqual(report["amount_zero_counts"]["h5_zero"],1)
        self.assertEqual(report["parquet_over_h5_volume_ratio"]["count"],0)
        self.assertIsNone(report["parquet_over_h5_amount_ratio"]["median"])
        self.assertEqual(report["both_ohlc_equal_bars"],1)

    def test_attribution_reports_parquet_only_without_fake_missing_ohlc(self):
        sym="BJ920680"
        p={(sym,202509300930):(10,10,10,10,100,1000)}
        report=M.attribute_differences({},p)[sym]
        self.assertEqual(report["h5_bars"],0)
        self.assertEqual(report["parquet_bars"],1)
        self.assertEqual(report["matched_bars"],0)
        self.assertEqual(report["price_abs_difference_quantiles"]["open"]["count"],0)
        self.assertIsNone(report["parquet_over_h5_volume_ratio"]["median"])

    def test_attribution_cross_boundary_exploratory_counts(self):
        sym="SH600000"
        # Previous parquet bar closes at 10, current H5 opens at 10.
        # Previous H5 closes at 11, current parquet opens at 11.
        h={(sym,202509300935):(9,12,8,11,10,100),
           (sym,202509300940):(10,13,9,12,20,200)}
        p={(sym,202509300930):(9,12,8,10,10,100),
           (sym,202509300935):(11,13,9,12,20,200)}
        r=M.attribute_differences(h,p)[sym]
        self.assertEqual(r["open_cross_boundary_checks"]["comparisons"],1)
        self.assertEqual(r["open_cross_boundary_checks"]["matches_previous_h5_close"],1)
        self.assertEqual(r["open_cross_boundary_checks"]["matches_previous_parquet_close"],1)

    def test_null_match_has_no_percentage(self):
        d=M.evaluate({}, {("SH600000",202509300930):(10,11,9,10,100,1000)})
        self.assertEqual(d["5"]["matched_bars"],0)
        self.assertIsNone(d["5"]["all_ohlc_equal_pct_of_matched"])


if __name__=="__main__":
    unittest.main(verbosity=2)
