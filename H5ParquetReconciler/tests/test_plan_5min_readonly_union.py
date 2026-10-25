"""Synthetic-only regression for conservative five-minute H5/Parquet union preflight."""
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "tools" / "plan-5min-readonly-union.py"
SPEC = importlib.util.spec_from_file_location("plan_5min_readonly_union", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class UnionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.sym = "SH600000"
        self.same = (10, 12, 9, 11, 100, 1000)

    def test_matching_conflict_and_each_unique_source_are_distinct(self):
        h = {
            (self.sym, 202509300935): self.same,
            (self.sym, 202509300940): self.same,
            (self.sym, 202509300945): self.same
        }
        p = {
            (self.sym, 202509300930): self.same,
            (self.sym, 202509300935): (10.02, 12, 9, 11, 100, 1000),
            (self.sym, 202509300945): self.same
        }
        per, totals = M.classify_pairs(h, p, (self.sym,))
        self.assertEqual(totals, {
            "h5_only": 1, "parquet_only": 1, "identical_values": 1,
            "within_unverified_tolerance": 0, "value_conflict": 1
        })
        self.assertEqual(per[self.sym]["intersection_keys"], 2)
        self.assertEqual(per[self.sym]["value_conflict_fields"]["open"], 1)
        self.assertEqual(per[self.sym]["examples"]["parquet_only"][0]["bar_end"], "202509300950")

    def test_near_equal_is_separate_from_exact_and_conflict(self):
        h = {(self.sym, 202509300935): self.same}
        p = {(self.sym, 202509300930): (10.003, 12, 9, 11, 100, 1000)}
        _, totals = M.classify_pairs(h, p, (self.sym,))
        self.assertEqual(totals["within_unverified_tolerance"], 1)
        self.assertEqual(totals["identical_values"], 0)
        self.assertEqual(totals["value_conflict"], 0)

    def test_missing_h5_dataset_does_not_greenlight_auto_merge(self):
        bj = "BJ920680"
        pq = {(bj, 202509300930): self.same}
        report = M.build_plan(
            {}, pq, (bj,), {bj: "missing_symbol_dataset"},
            {bj: {"h5_file_present": True}}, {"files": 1, "source_rows_in_scanned_groups": 2},
            date(2025, 9, 30))
        self.assertEqual(report["keys"]["union_candidate_unique"], 1)
        self.assertEqual(report["totals"]["parquet_only"], 1)
        self.assertFalse(report["preflight_passed_for_automatic_union"])
        self.assertFalse(report["output_database_generated"])
        self.assertEqual(report["by_symbol"][bj]["h5_dataset_inventory"], "missing_symbol_dataset")
        self.assertIn("SECURITY_MASTER_NOT_CERTIFIED", report["quality_barriers"])

    def test_metadata_missing_and_duplicate_flags_block_planning(self):
        h = {(self.sym, 202509300935): self.same}
        report = M.build_plan(
            h, {}, (self.sym,), {self.sym: "missing_market_file"},
            {self.sym: {"h5_file_present": False, "h5_duplicate_keys": 1}},
            {"files": 0, "duplicate_keys": 3, "nonfinite_rows": 2},
            date(2025, 9, 30))
        barriers = report["quality_barriers"]
        self.assertIn("MISSING_H5_MARKET_FILE", barriers)
        self.assertIn("PARQUET_YEAR_FILE_NOT_FOUND", barriers)
        self.assertIn("PARQUET_DUPLICATE_KEYS", barriers)
        self.assertIn("PARQUET_NONFINITE_ROWS", barriers)
        self.assertIn("H5_DUPLICATE_KEYS", barriers)
        self.assertEqual(report["totals"]["h5_only"], 1)
        self.assertFalse(report["preflight_passed_for_automatic_union"])

    def test_invalid_source_geometry_is_quarantined(self):
        h = {(self.sym, 202509300935): (12, 11, 10, 12, 1, 2)}
        pq = {(self.sym, 202509300930): self.same}
        report = M.build_plan(
            h, pq, (self.sym,), {self.sym: "dataset_present"},
            {self.sym: {"h5_file_present": True}}, {"files": 1, "source_rows_in_scanned_groups": 1},
            date(2025, 9, 30))
        self.assertEqual(report["by_symbol"][self.sym]["invalid_or_nonfinite_ohlcv_records"]["h5"], 1)
        self.assertIn("OHLCV_GEOMETRY_OR_NONFINITE_ANOMALY", report["quality_barriers"])

    def test_no_actual_ohlcv_exported_to_json_report(self):
        h = {(self.sym, 202509300935): self.same}
        pq = {(self.sym, 202509300930): (10.03, 12, 9, 11, 100, 1000)}
        report = M.build_plan(
            h, pq, (self.sym,), {self.sym: "dataset_present"},
            {self.sym: {"h5_file_present": True}}, {"files": 1, "source_rows_in_scanned_groups": 1},
            date(2025, 9, 30))
        sample = report["by_symbol"][self.sym]["examples"]["value_conflict"][0]
        self.assertEqual(set(sample), {"symbol", "bar_end", "differing_fields"})
        self.assertEqual(sample["differing_fields"], ["open"])
        self.assertFalse(report["raw_source_values_exported"])
        self.assertFalse(report["original_files_modified"])
        self.assertNotIn('"open": 10', json.dumps(report))

    def test_h5_dataset_inventory_differentiates_file_dataset_and_missing(self):
        import h5py
        with tempfile.TemporaryDirectory() as d:
            stock = Path(d) / "HikyuuData"
            stock.mkdir()
            with h5py.File(stock / "sh_5min.h5", "w") as file:
                file.create_group("data").create_dataset("SH600000", data=[1])
            results = M.h5_dataset_inventory(
                Path(d), ("SH600000", "SH600001", "SZ000636"))
            self.assertEqual(results["SH600000"], "dataset_present")
            self.assertEqual(results["SH600001"], "missing_symbol_dataset")
            self.assertEqual(results["SZ000636"], "missing_market_file")

    def test_union_identity_holds_on_multiple_symbols(self):
        h = {
            ("SH600000", 202509300935): self.same,
            ("SH600000", 202509300940): self.same
        }
        p = {
            ("SH600000", 202509300930): self.same,
            ("SZ000636", 202509300930): self.same
        }
        per, totals = M.classify_pairs(h, p, ("SH600000", "SZ000636"))
        self.assertEqual(sum(totals.values()), 3)
        self.assertEqual(per["SH600000"]["h5_keys"], 2)
        self.assertEqual(per["SZ000636"]["candidate_parquet_to_h5_keys"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
