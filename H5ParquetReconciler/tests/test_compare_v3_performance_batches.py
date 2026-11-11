"""Synthetic reports only: validation of non-invasive V3 main-index trends."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "compare-v3-performance-batches.py"
SPEC = importlib.util.spec_from_file_location("compare_v3_performance_batches", SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def sample_report(*, groups_complete, start_rg, total_time, sqlite_time,
                  read_time, context_exit=None):
    is_new = groups_complete == 62
    b = {
        "prepare_seconds": 0.328 if is_new else 0.312,
        "daily_coverage_upsert_seconds": 2.267 if is_new else 2.047,
        "row_group_locator_upsert_seconds": 12.685 if is_new else 8.376,
        "groups_done_insert_seconds": 0.0,
        "commit_and_other_seconds": 25.938 if is_new else 15.156,
        "outside_insert_group_seconds": 0.047 if is_new else 0.032,
    }
    assert abs(sum(b.values()) - sqlite_time) < 0.001
    stage = {
        "profiled_new_groups": 5,
        "sqlite_write_breakdown_profiled_groups": 5,
        "phases_seconds": {
            "parquet_read_and_key_aggregation": read_time,
            "sqlite_group_commit": sqlite_time,
        },
        "sqlite_write_breakdown_seconds": b,
        "slowest_row_group_wall_groups": [
            {"file_id": 0, "row_group": start_rg+i,
             "row_group_wall_seconds": 8.0}
            for i in range(5)
        ],
    }
    if context_exit is not None:
        stage["sqlite_transaction_boundary_seconds"] = {
            "context_enter_seconds": 0.0,
            "context_exit_seconds": context_exit,
            "other_within_commit_and_other_seconds": 0.0,
        }
    return {
        "format": "parquet-5min-coverage-index-v3",
        "year": 2025,
        "universe": "a-share-candidate",
        "files": 1,
        "row_groups_total": 522,
        "row_groups_complete": groups_complete,
        "index_complete": False,
        "report_detail_effective": "progress",
        "sqlite_journal_mode": "wal",
        "sqlite_write_order": "source",
        "clone_source_index": None,
        "saved_index": "work/indexes/pq-5min-2025-a-share-candidate-v3.sqlite",
        "source_fingerprint": "immutable-fake-metadata-signature",
        "source_files_modified": False,
        "max_index_mib_soft_budget": 192.0,
        "max_run_seconds_soft_budget": 90.0,
        "soft_budget_reached": False,
        "soft_wall_budget_reached": False,
        "stopped_for": "max_new_groups",
        "new_row_groups_this_run": 5,
        "source_rows_this_run": 614400,
        "candidate_source_rows": 7623474 if is_new else 7009197,
        "row_groups_stats": {
            "source_rows": 7624698 if is_new else 7010298,
            "candidate_rows": 7623474 if is_new else 7009197,
        },
        "sqlite_main_and_wal_on_disk_bytes": (
            145426584 if is_new else 143771264),
        "elapsed_seconds_this_run": total_time,
        "process_cpu_seconds_this_run": 31.203 if is_new else 28.828,
        "stage_profile_this_run": stage
    }


class V3BatchTrendTests(unittest.TestCase):
    def setUp(self):
        self.before = sample_report(
            groups_complete=57,start_rg=52,total_time=40.828,
            sqlite_time=25.923,read_time=14.874)
        self.after = sample_report(
            groups_complete=62,start_rg=57,total_time=57.297,
            sqlite_time=41.265,read_time=16.016,context_exit=25.938)

    def test_real_shape_matched_57_to_62_observation(self):
        result = M.compare_reports(self.before, self.after)
        self.assertEqual(result["main_index_groups_before"],57)
        self.assertEqual(result["main_index_groups_after"],62)
        self.assertEqual(result["time_seconds"]["delta_total"],16.469)
        self.assertEqual(result["time_seconds"]["stages_delta"]
                         ["sqlite_group_commit"],15.342)
        self.assertEqual(result["time_seconds"]["sql_breakdown_delta"]
                         ["commit_and_other_seconds"],10.782)
        self.assertIsNone(result["time_seconds"]["sqlite_transaction_previous"])
        self.assertEqual(result["time_seconds"]["sqlite_transaction_current"]
                         ["context_exit_seconds"],25.938)
        self.assertFalse(result["causal_sqlite_storage_or_fsync_conclusion_supported"])
        self.assertFalse(result["safe_to_automatically_union"])

    def test_mismatched_fingerprint_or_different_main_index_rejected(self):
        for key, value in (("source_fingerprint","different"),
                           ("saved_index","work/indexes/clone.sqlite")):
            with self.subTest(key=key):
                altered = dict(self.after, **{key:value})
                with self.assertRaisesRegex(ValueError,"identity"):
                    M.compare_reports(self.before,altered)

    def test_nonconsecutive_group_range_and_unequal_group_count_rejected(self):
        broken = json.loads(json.dumps(self.after))
        broken["stage_profile_this_run"]["slowest_row_group_wall_groups"][0][
            "row_group"] = 56
        with self.assertRaisesRegex(ValueError,"RowGroup"):
            M.compare_reports(self.before,broken)
        broken = dict(self.after,row_groups_complete=63)
        with self.assertRaisesRegex(ValueError,"cumulative group count"):
            M.compare_reports(self.before,broken)

    def test_cannot_infer_from_a_budget_stopped_or_cloned_run(self):
        for key, value in (("soft_budget_reached",True),
                           ("stopped_for","max_run_seconds_after_group"),
                           ("clone_source_index","work/indexes/other.sqlite"),
                           ("source_files_modified",True)):
            with self.subTest(key=key):
                altered=dict(self.after,**{key:value})
                with self.assertRaises(ValueError):
                    M.compare_reports(self.before,altered)

    def test_reject_forged_nested_timing_and_nan(self):
        broken = json.loads(json.dumps(self.after))
        broken["stage_profile_this_run"]["sqlite_transaction_boundary_seconds"][
            "context_exit_seconds"] = 99.0
        with self.assertRaisesRegex(ValueError,"nested"):
            M.compare_reports(self.before,broken)
        broken = json.loads(json.dumps(self.after))
        broken["elapsed_seconds_this_run"] = float("nan")
        with self.assertRaisesRegex(ValueError,"Invalid"):
            M.compare_reports(self.before,broken)

    def test_only_module_reports_path_and_no_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"reports").mkdir()
            with mock.patch.object(M,"MODULE_DIR",root):
                (root/"reports"/"a.json").write_text("{}",encoding="utf-8")
                self.assertEqual(M.report_path("reports/a.json"),
                                 root/"reports"/"a.json")
                with self.assertRaisesRegex(ValueError,"reports"):
                    M.report_path(root/"sensitive.json")
                with self.assertRaisesRegex(ValueError,"overwrite"):
                    M.report_path("reports/a.json",new=True)
                self.assertEqual(M.report_path("reports/new.json",new=True),
                                 root/"reports"/"new.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
