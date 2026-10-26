"""Offline synthetic checks for strict V3 matched A/B report comparison."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from contextlib import closing
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = load("index_v3_ab_comparator_test", "compare-v3-write-order-ab.py")
I = C.indexer


class MatchedReadOnlyABTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.module = Path(temp.name)
        self.base = self.module / "work" / "indexes" / "base.sqlite"
        self.source = self.module / "work" / "indexes" / "source.sqlite"
        self.sorted = self.module / "work" / "indexes" / "sorted.sqlite"
        self.manifest = {
            "version": I.VERSION, "year": 2025, "period": "5min",
            "universe": "a-share-candidate",
            "files": [{"relative_path": "AllCycleAStockData/5min/2025.parquet",
                       "bytes": 1234, "mtime_ns": 5678}]
        }
        db = I.open_index(self.base, self.manifest, False)
        try:
            I.insert_group(
                db, 0, 0, {("SH600000", 20250930): [1, 1]},
                Counter(source_rows=1, candidate_rows=1))
        finally:
            db.close()
        I.clone_partial_index(self.base, self.source, self.manifest)
        I.clone_partial_index(self.base, self.sorted, self.manifest)
        self.reports = []
        for path, order, elapsed, commit in (
                (self.source, "source", 20.0, 12.0),
                (self.sorted, "pk-sorted", 18.0, 10.0)):
            db = I.open_index(path, self.manifest, True, journal_mode="wal")
            try:
                # The duplicate slot is intentional: comparing progress reports
                # must re-compute duplicate=1, not mistake null for zero.
                I.insert_group(db, 0, 1, {("SH600000", 20250930): [1, 1]},
                               Counter(source_rows=1, candidate_rows=1),
                               write_order=order)
                result = I.index_summary(db, self.manifest, 3, detail="progress")
                self.assertIsNone(result["duplicate_regular_session_keys"])
            finally:
                db.close()
            result.update({
                "saved_index": path.relative_to(self.module).as_posix(),
                "clone_source_index": self.base.relative_to(self.module).as_posix(),
                "source_fingerprint": I.manifest_signature(self.manifest),
                "sqlite_write_order": order, "sqlite_journal_mode": "wal",
                "new_row_groups_this_run": 1,
                "stopped_for": "max_new_groups", "soft_budget_reached": False,
                "soft_wall_budget_reached": False, "elapsed_seconds_this_run": elapsed,
                "stage_profile_this_run": {
                    "phases_seconds": {
                        "sqlite_group_commit": commit,
                        "parquet_read_and_key_aggregation": 4.0},
                    "slowest_row_group_wall_groups": [
                        {"file_id": 0, "row_group": 1,
                         "row_group_wall_seconds": elapsed / 2}]}
            })
            self.reports.append(result)

    def compare(self):
        # subTest() traps exceptions and records a subtest ERROR instead of
        # propagating it to assertRaisesRegex() in the calling negative test.
        # patch.object restores MODULE_DIR while preserving exception semantics.
        with mock.patch.object(C.core, "MODULE_DIR", self.module):
            return C.compare_matched_ab(self.source, self.sorted,
                                        self.manifest, [3], *self.reports)

    def test_comparison_helper_propagates_error_and_restores_module_dir(self):
        # A regression test for Windows' observed 5 FAIL + 5 subtest ERROR:
        # negative tests must receive their expected exception normally.
        original_dir = C.core.MODULE_DIR
        original_report = self.reports[1]
        self.reports[1] = dict(original_report, source_fingerprint="mismatch")
        try:
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                self.compare()
            self.assertEqual(C.core.MODULE_DIR, original_dir)
        finally:
            self.reports[1] = original_report

    def test_matched_indexes_equal_even_when_progress_did_not_count_duplicates(self):
        result = self.compare()
        self.assertTrue(result["logical_tables_equal"])
        self.assertTrue(result["full_key_audit_both"])
        self.assertEqual(result["unique_regular_session_keys"], 1)
        self.assertEqual(result["duplicate_regular_session_keys"], 1)
        self.assertEqual(result["logical_rows_compared"]["groups_done"], 2)
        self.assertEqual(result["logical_rows_compared"]["daily_coverage"], 1)
        self.assertEqual(result["total_speedup_pct_sorted_vs_source"], 10.0)
        self.assertFalse(result["automatically_change_write_order"])
        self.assertTrue(result["incomplete_year_cannot_certify_union"])
        # Read-only comparator must not mark either incomplete index as complete.
        # sqlite3.Connection.__exit__ commits/rolls back but DOES NOT close.
        # On Windows the open handle prevents TemporaryDirectory cleanup.
        with closing(sqlite3.connect(self.source)) as db:
            self.assertEqual(dict(db.execute("SELECT key,value FROM meta"))
                             ["completed"], "false")

    def test_reject_different_source_fingerprint_and_clone_origin(self):
        original = self.reports[1]
        self.reports[1] = dict(original, source_fingerprint="wrong")
        try:
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                self.compare()
        finally:
            self.reports[1] = original
        self.reports[1] = dict(original, clone_source_index="other.sqlite")
        try:
            with self.assertRaisesRegex(ValueError, "starting snapshots"):
                self.compare()
        finally:
            self.reports[1] = original

    def test_reject_report_range_or_premature_budget_stop(self):
        original = self.reports[1]
        self.reports[1] = dict(original, row_groups_complete=3)
        try:
            with self.assertRaisesRegex(ValueError, "read-only full audit"):
                self.compare()
        finally:
            self.reports[1] = original
        self.reports[1] = dict(original, stopped_for="max_run_seconds_after_group")
        try:
            with self.assertRaisesRegex(ValueError, "group cap"):
                self.compare()
        finally:
            self.reports[1] = original

    def test_reject_logical_key_differences_even_when_aggregates_match(self):
        # Swap a time slot bit. The unique and source row totals still match;
        # therefore full summary alone is not sufficient for A/B correctness.
        with closing(sqlite3.connect(self.sorted)) as db:
            with db:
                db.execute("UPDATE daily_coverage SET slot_mask=2")
        with self.assertRaisesRegex(ValueError, "logical mismatch"):
            self.compare()

    def test_equal_final_index_but_different_claimed_input_groups_rejected(self):
        original = self.reports[1]
        changed = dict(original)
        changed["stage_profile_this_run"] = dict(
            original["stage_profile_this_run"],
            slowest_row_group_wall_groups=[
                {"file_id": 0, "row_group": 2, "row_group_wall_seconds": 1.0}])
        self.reports[1] = changed
        try:
            with self.assertRaisesRegex(ValueError, "different RowGroups"):
                self.compare()
        finally:
            self.reports[1] = original

    def test_stream_table_comparison_rejects_different_db_paths(self):
        with self.assertRaisesRegex(ValueError, "distinct"):
            C.compare_logical_tables(self.source, self.source)

    def test_bad_timing_is_not_treated_as_performance_improvement(self):
        original = self.reports[1]
        invalid = dict(original)
        invalid["stage_profile_this_run"] = {
            "phases_seconds": {"sqlite_group_commit": float("nan"),
                               "parquet_read_and_key_aggregation": 4.0},
            "slowest_row_group_wall_groups": [
                {"file_id": 0, "row_group": 1, "row_group_wall_seconds": 1.0}]}
        self.reports[1] = invalid
        try:
            with self.assertRaisesRegex(ValueError, "Invalid A/B timing"):
                self.compare()
        finally:
            self.reports[1] = original


    def test_cli_refuses_to_write_report_as_existing_sqlite_wal_sidecar(self):
        import contextlib
        import io
        from unittest import mock
        options = [
            str(self.module / "fake_source"), "--year", "2025",
            "--source-index", "work/indexes/source.sqlite",
            "--sorted-index", "work/indexes/sorted.sqlite",
            "--source-report", "reports/source.json",
            "--sorted-report", "reports/sorted.json",
            "--out", "work/indexes/source.sqlite-wal", "--read-only"
        ]
        with mock.patch.object(C.core, "MODULE_DIR", self.module):
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as exc:
                    C.main(options)
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("journal path", errors.getvalue())



if __name__ == "__main__":
    unittest.main(verbosity=2)
