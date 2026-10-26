"""Synthetic, offline read-only checks for periodic V3 SQLite full audits."""
import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


I = load_script("key_index_for_read_only_tests", "index-parquet-5min-coverage.py")
A = load_script("read_only_audit_tests", "audit-parquet-5min-coverage.py")
TZ8 = timezone(timedelta(hours=8))


class Column:
    def __init__(self, rows):
        self.rows = rows

    def to_pylist(self):
        return self.rows


class Batch:
    def __init__(self, timestamps, symbols):
        self.values = (Column(timestamps), Column(symbols))

    def column(self, i):
        return self.values[i]


def epoch_ms(stamp):
    return int(datetime.strptime(stamp, "%Y%m%d%H%M").replace(
        tzinfo=TZ8).timestamp() * 1000)


class ReadOnlyCoverageAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.index_path = Path(temp.name) / "work" / "indexes" / "coverage.sqlite"
        self.manifest = {
            "version": I.VERSION, "year": 2025,
            "period": "5min", "universe": "a-share-candidate",
            "files": [{"relative_path": "AllCycleAStockData/5min/2025.parquet",
                       "bytes": 1234, "mtime_ns": 5678}],
        }

    def add_group(self, db, group_id, stamps):
        packed, counts = I.aggregate_batches([
            Batch([epoch_ms(stamp) for stamp in stamps],
                  ["600000.XSHG"] * len(stamps))
        ], 2025, "a-share-candidate")
        I.insert_group(db, 0, group_id, packed, counts)

    def test_partial_full_audit_recounts_after_quick_progress_without_mutation(self):
        db = I.open_index(self.index_path, self.manifest, False)
        try:
            self.add_group(db, 0, ["202509300930", "202509300935"])
            self.add_group(db, 1, ["202509300935", "202509301300"])
            quick = I.index_summary(db, self.manifest, 522, detail="progress")
            I.persist_report_certification(db, quick)
            before = dict(db.execute("SELECT key,value FROM meta"))
            self.assertNotIn("duplicate_regular_session_keys", before)
        finally:
            db.close()
        audit = A.audit_existing_index(self.index_path, self.manifest, [522])
        self.assertEqual(audit["row_groups_complete"], 2)
        self.assertEqual(audit["unique_regular_session_keys"], 3)
        self.assertEqual(audit["duplicate_regular_session_keys"], 1)
        self.assertTrue(audit["full_key_audit_performed"])
        self.assertFalse(audit["index_complete"])
        self.assertFalse(audit["saved_meta_completed"])
        self.assertFalse(audit["usable_for_automatic_union_from_this_audit"])
        self.assertTrue(audit["no_parquet_data_rows_read_this_run"])
        self.assertEqual(audit["new_row_groups_this_run"], 0)
        db = sqlite3.connect(self.index_path)
        try:
            self.assertEqual(dict(db.execute("SELECT key,value FROM meta")), before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM groups_done").fetchone()[0], 2)
        finally:
            db.close()

    def test_fingerprint_change_fails_before_reporting_counts(self):
        db = I.open_index(self.index_path, self.manifest, False)
        try:
            self.add_group(db, 0, ["202509300930"])
        finally:
            db.close()
        changed = dict(self.manifest)
        changed["files"] = [dict(self.manifest["files"][0], bytes=4567)]
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            A.audit_existing_index(self.index_path, changed, [522])

    def test_out_of_range_row_group_checkpoint_is_rejected(self):
        db = I.open_index(self.index_path, self.manifest, False)
        try:
            self.add_group(db, 9, ["202509300930"])
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError, "Out-of-range"):
            A.audit_existing_index(self.index_path, self.manifest, [2])

    def test_corrupted_daily_candidate_count_is_rejected(self):
        db = I.open_index(self.index_path, self.manifest, False)
        try:
            self.add_group(db, 0, ["202509300930"])
            db.execute("UPDATE daily_coverage SET source_rows=source_rows+1")
            db.commit()
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError, "disagree"):
            A.audit_existing_index(self.index_path, self.manifest, [522])

    def test_completed_flag_with_missing_checkpoints_is_rejected(self):
        db = I.open_index(self.index_path, self.manifest, False)
        try:
            self.add_group(db, 0, ["202509300930"])
            db.execute("UPDATE meta SET value='true' WHERE key='completed'")
            db.commit()
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError, "Completed flag"):
            A.audit_existing_index(self.index_path, self.manifest, [522])

    def test_exact_full_audit_is_not_a_write_time_certification(self):
        db = I.open_index(self.index_path, self.manifest, False)
        try:
            self.add_group(db, 0, ["202509300930"])
        finally:
            db.close()
        audit = A.audit_existing_index(self.index_path, self.manifest, [1])
        self.assertTrue(audit["index_complete"])
        self.assertFalse(audit["saved_meta_completed"])
        self.assertFalse(audit["usable_for_automatic_union_from_this_audit"])
        self.assertEqual(audit["unique_regular_session_keys"], 1)

    def test_invalid_footer_counts_and_empty_index_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "footer counts"):
            A.audit_existing_index(self.index_path, self.manifest, [])
        with self.assertRaisesRegex(ValueError, "does not exist"):
            A.audit_existing_index(self.index_path, self.manifest, [522])
        db = I.open_index(self.index_path, self.manifest, False)
        db.close()
        with self.assertRaisesRegex(ValueError, "no committed row groups"):
            A.audit_existing_index(self.index_path, self.manifest, [522])


if __name__ == "__main__":
    unittest.main(verbosity=2)
