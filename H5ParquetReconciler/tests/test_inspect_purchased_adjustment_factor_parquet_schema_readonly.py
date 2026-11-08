"""Synthetic original adjustment factor Parquet footer-only inspection."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "synthetic_purchased_factor_footer_schema_gate",
    HERE.parent/"tools"/"inspect-purchased-adjustment-factor-parquet-schema-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class PurchasedFactorOnlyFooterTests(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.pa,self.pq=pa,pq
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.folder=self.root/"AllCycleAStockData"/M.LABEL
        self.folder.mkdir(parents=True)
        self.file=self.folder/"nonannual-adjustments.parquet"
        self.make_file()

    def make_file(self):
        self.pq.write_table(self.pa.table({
            "ts":self.pa.array([1,2],type=self.pa.int64()),
            "symbol":self.pa.array(["SH600000","SZ000001"]),
            "adj_factor":self.pa.array([1.0,1.1]),
        }),self.file,row_group_size=1)

    def test_one_unnamed_year_factor_file_schema_and_footer_rows_only(self):
        before=(self.file.stat().st_size,self.file.stat().st_mtime_ns)
        result=M.inspect(self.root)
        self.assertEqual(result["source_files"],1)
        self.assertEqual(result["source_footer_rows"],2)
        self.assertEqual(result["source_rowgroups"],2)
        self.assertEqual(
            [x["name"] for x in result["file_schemas"][0]["arrow_fields"]],
            ["ts","symbol","adj_factor"])
        self.assertTrue(result["file_schemas"][0][
            "filename_year_assignment_not_verified"])
        self.assertFalse(result["original_parquet_ohlcva_or_factor_values_read"])
        self.assertFalse(result["factor_value_semantics_and_adjustment_direction_certified"])
        self.assertFalse(result["production_activated"])
        self.assertEqual(before,(self.file.stat().st_size,self.file.stat().st_mtime_ns))
        self.assertNotIn("SH600000",str(result))
        self.assertNotIn("1.1",str(result))

    def test_unknown_factor_column_names_are_reported_not_relabelled(self):
        self.file.unlink()
        self.pq.write_table(self.pa.table({"my_vendor_ratio":[1.0],
                                            "vendor_day":["2025-01-02"]}),self.file)
        result=M.inspect(self.root)
        self.assertEqual(result["file_schemas"][0]["arrow_fields"][0]["name"],
                         "my_vendor_ratio")
        self.assertFalse(result["corporate_action_adjusted_kline_materialized"])

    def test_missing_factor_source_fails(self):
        self.file.unlink()
        with self.assertRaisesRegex(ValueError,"bounded nonempty"):
            M.inspect(self.root)

    def test_missing_factor_folder_fails(self):
        self.file.unlink()
        self.folder.rmdir()
        with self.assertRaisesRegex(ValueError,"missing/unsafe"):
            M.inspect(self.root)

    def test_file_budget_fails_before_any_data_read(self):
        with self.assertRaisesRegex(ValueError,"bounded nonempty"):
            M.inspect(self.root,max_files=0)
        with self.assertRaisesRegex(ValueError,"resource budgets"):
            M.inspect(self.root,max_rowgroups=0)
        with self.assertRaisesRegex(ValueError,"rowgroup budget"):
            M.inspect(self.root,max_rowgroups=1)

    def test_multiple_factor_files_are_preserved_without_filename_year_assumption(self):
        other=self.folder/"not-YYYY.parquet"
        other.write_bytes(self.file.read_bytes())
        r=M.inspect(self.root,max_files=2)
        self.assertEqual(r["source_files"],2)
        self.assertEqual(r["source_footer_rows"],4)
        self.assertFalse(r["source_file_years_and_exact_trade_date_coverage_certified"])


if __name__=="__main__":
    unittest.main(verbosity=2)
