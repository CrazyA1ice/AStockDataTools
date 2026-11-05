"""Synthetic purchased 2025 5min unselected-code source-key census tests.

Uses real synthetic Parquet ts/symbol columns only, no licensed market OHLCVA,
H5 values, source writes, or external securities-master assumptions.
"""
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "purchased_2025_5min_excluded_prefix_tests",
    HERE.parent / "tools" /
    "audit-purchased-2025-unselected-5min-code-prefixes-readonly.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class ExcludedFiveMinuteCodePrefixes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        folder = self.root / "AllCycleAStockData" / "5min"
        folder.mkdir(parents=True)
        self.file = folder / "2025.parquet"
        self.day = date(2025, 1, 2)
        self.regular = sorted(
            M.D.normalized_native_keys(self.day, "5min").values())
        self.assertEqual(len(self.regular), 48)
        self.rows = [
            (stamp, raw)
            for raw in ("SH600000", "SH510300", "SH900901", "OTHER_INVALID")
            for stamp in self.regular
        ]
        self.save()

    def save(self):
        pq.write_table(pa.table({
            "ts": pa.array([x[0] for x in self.rows], type=pa.int64()),
            "symbol": [x[1] for x in self.rows],
        }), self.file, row_group_size=80)

    def audit(self, selected=48):
        return M.scan_5min_sources(
            self.root, [self.file], expected_total=len(self.rows),
            expected_selected=selected, max_source_rows=10000,
            max_stockdays=100)

    def test_exact_unselected_code_prefixes_not_certified_asset_types(self):
        data = self.audit()
        self.assertEqual(data["scanned_source_rows"], 192)
        self.assertEqual(data["selected_ashare_code_candidate_rows"], 48)
        self.assertEqual(data["unselected_source_rows"], 144)
        self.assertEqual(set(data["unselected_code_groups"]),
                         {"SH510", "SH900", "UNRECOGNIZED"})
        self.assertEqual(data["unselected_recognized_or_unknown_code_categories"],
                         {"recognized_code_but_not_selected_ashare": 96,
                          "unrecognized_raw_symbol": 48})
        self.assertEqual(data["unselected_observed_stockdays"], 3)
        self.assertEqual(data["unselected_complete_48_key_stockdays"], 3)
        self.assertTrue(data["unselected_all_observed_stockdays_match_48_key_grid"])
        self.assertTrue(data["prefix_groups_are_not_certified_security_classes"])
        self.assertFalse("SH510300" in str(data))
        self.assertTrue(data["no_ohlcva_columns_opened"])

    def test_absent_unrecognized_category_reported_as_zero(self):
        self.rows = [
            (stamp, raw)
            for raw in ("SH600000", "SH510300")
            for stamp in self.regular
        ]
        self.save()
        result = self.audit(selected=48)
        self.assertEqual(result["unselected_source_rows"], 48)
        self.assertEqual(result[
            "unselected_recognized_or_unknown_code_categories"
        ], {
            "recognized_code_but_not_selected_ashare": 48,
            "unrecognized_raw_symbol": 0,
        })

    def test_both_unselected_categories_zero_when_none_exist(self):
        self.rows = [(stamp, "SH600000") for stamp in self.regular]
        self.save()
        result = self.audit(selected=48)
        self.assertEqual(result["unselected_source_rows"], 0)
        self.assertEqual(result[
            "unselected_recognized_or_unknown_code_categories"
        ], {
            "recognized_code_but_not_selected_ashare": 0,
            "unrecognized_raw_symbol": 0,
        })

    def test_windows_report_uses_safe_optional_property_access(self):
        ps = (HERE.parent /
              "run-purchased-2025-unselected-5min-code-prefixes-audit.ps1")
        script = ps.read_text(encoding="utf-8")
        self.assertIn("PSObject.Properties['unrecognized_raw_symbol']", script)
        self.assertIn("PSObject.Properties['recognized_code_but_not_selected_ashare']", script)
        self.assertNotIn(
            "unselected_recognized_or_unknown_code_categories.unrecognized_raw_symbol",
            script)

    def test_source_read_never_requests_ohlcva(self):
        original = pq.ParquetFile.iter_batches
        seen = []
        def restricted(self, *args, **kwargs):
            self_cols = kwargs.get("columns")
            seen.append(self_cols)
            if self_cols != ["ts", "symbol"]:
                raise AssertionError("Purchased OHLCVA column access forbidden")
            yield from original(self, *args, **kwargs)
        with patch.object(pq.ParquetFile, "iter_batches", restricted):
            self.audit()
        self.assertGreater(len(seen), 0)
        self.assertTrue(all(cols == ["ts", "symbol"] for cols in seen))

    def test_incomplete_nonselected_stockday_reported_not_filled(self):
        self.rows.remove((self.regular[-1], "SH510300"))
        self.save()
        result = self.audit()
        self.assertFalse(result["unselected_all_observed_stockdays_match_48_key_grid"])
        self.assertEqual(result["unselected_complete_48_key_stockdays"], 2)
        self.assertEqual(result["unselected_nonstandard_key_stockdays"][
            "missing_expected_keys"], 1)

    def test_duplicate_excluded_symbol_minute_key_rejected(self):
        self.rows.append((self.regular[-1], "SH900901"))
        self.save()
        with self.assertRaisesRegex(ValueError, "Duplicate unselected"):
            self.audit()

    def test_selected_key_count_wrong_rejected(self):
        with self.assertRaisesRegex(ValueError, "disagree"):
            self.audit(selected=47)

    def test_selected_symbol_canonical_alias_is_recognised(self):
        self.rows = [(stamp, "SHSE.600000") for stamp in self.regular]
        self.save()
        result = self.audit(selected=48)
        self.assertEqual(result["unselected_source_rows"], 0)
        self.assertEqual(result["unselected_observed_stockdays"], 0)

    def test_bounded_scan_budget_and_missing_file_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            M.scan_5min_sources(
                self.root, [self.file], expected_total=len(self.rows),
                expected_selected=48, max_source_rows=150)
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            M.scan_5min_sources(
                self.root, [self.file.parent / "missing.parquet"],
                expected_total=0, expected_selected=0,
                max_source_rows=200)

    def test_purchased_source_is_never_rewritten(self):
        before = (self.file.stat().st_size, self.file.stat().st_mtime_ns)
        self.audit()
        self.assertEqual(before, (self.file.stat().st_size,
                                  self.file.stat().st_mtime_ns))


if __name__ == "__main__":
    unittest.main(verbosity=2)
