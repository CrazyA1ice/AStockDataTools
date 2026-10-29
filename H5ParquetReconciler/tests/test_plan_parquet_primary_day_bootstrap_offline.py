"""Synthetic tests for the no-market-I/O Parquet-first daily bootstrap gate."""
import copy
import importlib.util
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "tools" /
          "plan-parquet-primary-day-bootstrap-offline.py")
SPEC = importlib.util.spec_from_file_location("day_primary_gate", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture():
    return {
        "format": M.SOURCE_FORMAT,
        "status": "complete",
        "requested_years": [2026],
        "requested_periods": ["day"],
        "universe_mode": "a-share-candidate",
        "requested_from_date": "2026-09-30",
        "requested_to_date": "2026-10-01",
        "sources_modified": False,
        "eligible_for_automatic_union": False,
        "results": {
            "day/2026": {
                "period": "day", "year": 2026,
                "from_date": "2026-09-30", "to_date": "2026-10-01",
                "universe_mode": "a-share-candidate",
                "scan_complete": True, "issues": [],
                "pq_year_metadata_only_no_h5_rows": False,
                "h5_duplicate_keys": 0,
                "pq_duplicate_keys_within_batch": 0,
                "pq_duplicate_keys_across_batches": 0,
                "h5_rows": 5, "pq_rows": 4, "matched_keys": 3,
                "h5_only_rows": 2, "pq_only_rows": 1,
                "value_mismatch_rows": 2, "price_mismatch_rows": 0,
                "quantity_mismatch_rows": 2,
                "by_day": {
                    "20260930": {
                        "h5_unique": 3, "parquet_unique": 4,
                        "matched": 3, "h5_only": 0, "pq_only": 1,
                        "value_mismatch": 2, "intersection_unique": 3,
                        "union_candidate_unique": 4,
                    },
                    "20261001": {
                        "h5_unique": 2, "parquet_unique": 0,
                        "matched": 0, "h5_only": 2, "pq_only": 0,
                        "value_mismatch": 0, "intersection_unique": 0,
                        "union_candidate_unique": 2,
                    },
                },
            },
        },
    }


class ParquetPrimaryBootstrapGateTests(unittest.TestCase):
    def test_complete_overlap_keeps_parquet_and_marks_h5_only_date_candidate(self):
        result = M.analyze(fixture())
        self.assertTrue(result["source_key_conservation_verified"])
        self.assertTrue(result["existing_tolerance_ohlc_overlap_pass"])
        self.assertEqual(result["h5_only_rows_on_wholly_parquet_absent_dates"], 2)
        self.assertEqual(result["h5_only_rows_on_mixed_dates_need_symbol_day_manifest"], 0)
        self.assertEqual(
            result["daily_coverage"][0]["category"],
            "parquet_primary_existing_overlap_plus_pq_only")
        self.assertEqual(
            result["daily_coverage"][1]["category"],
            "entire_date_h5_only_candidate")
        self.assertFalse(result["market_source_files_read"])
        self.assertFalse(result["safe_to_automatically_union"])
        self.assertFalse(result["ready_for_unattended_data_fill"])

    def test_price_mismatch_cannot_pass_overlap_gate(self):
        source = fixture()
        source["results"]["day/2026"]["price_mismatch_rows"] = 1
        out = M.analyze(source)
        self.assertFalse(out["existing_tolerance_ohlc_overlap_pass"])
        self.assertEqual(out["overlap_price_mismatch_rows"], 1)
        self.assertFalse(out["ready_for_unattended_data_fill"])

    def test_quantity_mismatch_is_recorded_not_silently_called_equal(self):
        out = M.analyze(fixture())
        self.assertEqual(out["quantity_or_amount_difference_rows"], 2)
        self.assertTrue(
            out["source_price_comparison_is_existing_tolerance_not_strict_equality"])

    def test_mixed_date_h5_only_requires_exact_symbol_day_manifest(self):
        report = fixture()
        section = report["results"]["day/2026"]
        # H5 has one extra record on September 30, but both sources have data.
        sep = section["by_day"]["20260930"]
        sep["h5_unique"] += 1
        sep["h5_only"] = 1
        sep["union_candidate_unique"] += 1
        section["h5_rows"] += 1
        section["h5_only_rows"] += 1
        result = M.analyze(report)
        self.assertEqual(
            result["daily_coverage"][0]["category"],
            "mixed_date_requires_exact_symbol_day_manifest")
        self.assertEqual(
            result["h5_only_rows_on_mixed_dates_need_symbol_day_manifest"], 1)
        self.assertEqual(
            result["h5_only_rows_on_wholly_parquet_absent_dates"], 2)

    def test_incomplete_bad_provenance_or_extra_period_fails_closed(self):
        edits = (
            lambda r: r.update(status="partial"),
            lambda r: r.update(eligible_for_automatic_union=True),
            lambda r: r.update(sources_modified=True),
            lambda r: r.update(requested_periods=["day", "5min"]),
            lambda r: r["results"].update({"5min/2026": {}}),
            lambda r: r["results"]["day/2026"].update(scan_complete=False),
            lambda r: r["results"]["day/2026"].update(issues=["read_error"]),
            lambda r: r["results"]["day/2026"].update(
                pq_year_metadata_only_no_h5_rows=True),
            lambda r: r["results"]["day/2026"].update(
                pq_duplicate_keys_across_batches=1),
        )
        for edit in edits:
            bad = fixture()
            edit(bad)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                M.analyze(bad)

    def test_outside_bound_or_invalid_day_is_rejected(self):
        for badkey in ("20261101", "20260931", "2026-09-30"):
            bad = fixture()
            sec = bad["results"]["day/2026"]
            sec["by_day"][badkey] = sec["by_day"].pop("20260930")
            with self.subTest(key=badkey), self.assertRaises(ValueError):
                M.analyze(bad)

    def test_corrupted_partition_counts_fail_closed(self):
        changes = (
            ("matched_keys", 4),
            ("h5_rows", 6),
            ("value_mismatch_rows", 3),
        )
        for field, value in changes:
            bad = fixture()
            bad["results"]["day/2026"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                M.analyze(bad)
        bad = fixture()
        bad["results"]["day/2026"]["by_day"]["20260930"]["h5_unique"] += 1
        with self.assertRaisesRegex(ValueError, "conservation"):
            M.analyze(bad)

    def test_no_overlap_cannot_be_called_ohlc_identical(self):
        bad = fixture()
        sec = bad["results"]["day/2026"]
        sec["h5_rows"] = 2
        sec["pq_rows"] = 0
        sec["matched_keys"] = 0
        sec["h5_only_rows"] = 2
        sec["pq_only_rows"] = 0
        sec["value_mismatch_rows"] = 0
        sec["quantity_mismatch_rows"] = 0
        sec["by_day"] = {"20261001": fixture()["results"]["day/2026"]["by_day"]["20261001"]}
        result = M.analyze(bad)
        self.assertFalse(result["existing_tolerance_ohlc_overlap_pass"])
        self.assertEqual(result["overlap_ohlc_keys_tested"], 0)

    def test_noninteger_false_negative_counters_rejected(self):
        for value in (True, -1, 0.5, "1"):
            bad = fixture()
            bad["results"]["day/2026"]["h5_only_rows"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                M.analyze(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
