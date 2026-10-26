"""Offline synthetic checks: durable and exact 48-slot 5min Parquet key index."""
import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "index-parquet-5min-coverage.py"
SPEC = importlib.util.spec_from_file_location("parquet_5min_index_test", SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
TZ8 = timezone(timedelta(hours=8))


def ms(value):
    return int(datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=TZ8).timestamp()*1000)


class FakeColumn:
    def __init__(self, rows):
        self.rows = rows
    def to_pylist(self):
        return self.rows


class FakeBatch:
    def __init__(self, stamps, symbols):
        self.stamps, self.symbols = stamps, symbols
    def column(self, index):
        return FakeColumn(self.stamps if index == 0 else self.symbols)


class ParquetKeyCoverageIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.index = Path(self.temp.name) / "work" / "indexes" / "2025.sqlite"
        self.manifest = {"version": M.VERSION, "year": 2025,
                         "period": "5min", "universe": "a-share-candidate",
                         "files": [{"relative_path":"AllCycleAStockData/5min/2025.parquet",
                                    "bytes":1234,"mtime_ns":5678}]}

    def test_session_start_slots_and_invalid_midday(self):
        self.assertEqual(M.minute_slot(ms("202509300930"),2025)[0],(20250930,0))
        self.assertEqual(M.minute_slot(ms("202509301125"),2025)[0],(20250930,23))
        self.assertEqual(M.minute_slot(ms("202509301300"),2025)[0],(20250930,24))
        self.assertEqual(M.minute_slot(ms("202509301455"),2025)[0],(20250930,47))
        self.assertEqual(M.minute_slot(ms("202509301130"),2025)[1],
                         "unexpected_session_stamp")
        self.assertEqual(M.minute_slot(ms("202601020930"),2025)[1],"outside_year")
        self.assertEqual(M.minute_slot(ms("202509300931"),2025)[1],
                         "unexpected_session_stamp")
        self.assertEqual(M.minute_slot(None,2025)[1],"bad_timestamp")

    def test_aggregation_symbol_universe_and_cross_batch_duplicate(self):
        a = FakeBatch([ms("202509300930"),ms("202509300935"),
                       ms("202509300930"),ms("202509300930")],
                      ["600000.XSHG","600000.XSHG","000001.XSHG","200001.XSHE"])
        b = FakeBatch([ms("202509300930"),ms("202509301300")],
                      ["SH600000","SH600000"])
        packed,counts = M.aggregate_batches((a,b),2025,"a-share-candidate")
        self.assertEqual(counts["source_rows"],6)
        self.assertEqual(counts["candidate_rows"],4)
        self.assertEqual(counts["excluded_security_type"],2)
        self.assertEqual(packed[("SH600000",20250930)][1],4)
        self.assertEqual(packed[("SH600000",20250930)][0].bit_count(),3)

    def test_exact_duplicate_count_across_row_groups_and_resume(self):
        a,st = M.aggregate_batches([FakeBatch(
            [ms("202509300930"),ms("202509300935")],
            ["600000.XSHG","600000.XSHG"])],2025,"a-share-candidate")
        b,sb = M.aggregate_batches([FakeBatch(
            [ms("202509300935"),ms("202509301300")],
            ["600000.XSHG","600000.XSHG"])],2025,"a-share-candidate")
        db=M.open_index(self.index,self.manifest,False)
        try:
            M.insert_group(db,0,0,a,st)
            M.insert_group(db,0,1,b,sb)
            result=M.index_summary(db,self.manifest,2)
            self.assertTrue(result["index_complete"])
            self.assertEqual(result["candidate_source_rows"],4)
            self.assertEqual(result["unique_regular_session_keys"],3)
            self.assertEqual(result["duplicate_regular_session_keys"],1)
            self.assertEqual(result["row_group_locator_entries"],2)
            self.assertEqual(result["row_group_locator_compact_rows"],1)
            self.assertEqual(M.index_matches_and_groups(
                db,("SH600000",),20250930),{0:[0,1]})
        finally:
            db.close()
        reopened=M.open_index(self.index,self.manifest,True)
        try:
            self.assertEqual(reopened.execute(
                "SELECT COUNT(*) FROM groups_done").fetchone()[0],2)
            self.assertEqual(M.index_summary(reopened,self.manifest,2)
                             ["duplicate_regular_session_keys"],1)
        finally:
            reopened.close()

    def test_resume_rejects_new_source_manifest_and_unrequested_rebuild(self):
        db=M.open_index(self.index,self.manifest,False)
        db.close()
        with self.assertRaisesRegex(ValueError,"Index exists"):
            M.open_index(self.index,self.manifest,False)
        changed=dict(self.manifest)
        changed["files"]=[dict(self.manifest["files"][0], bytes=999)]
        with self.assertRaisesRegex(ValueError,"fingerprint"):
            M.open_index(self.index,changed,True)

    def test_resume_requires_existing_index(self):
        with self.assertRaisesRegex(ValueError,"does not exist"):
            M.open_index(self.index,self.manifest,True)

    def test_row_group_transaction_failure_does_not_mark_complete(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,counts)
            with self.assertRaises(sqlite3.IntegrityError):
                M.insert_group(db,0,0,data,counts)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM groups_done").fetchone()[0],1)
            self.assertEqual(M.index_summary(db,self.manifest,1)
                             ["candidate_source_rows"],1)
        finally:
            db.close()

    def test_partial_group_index_not_certified_complete(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,counts)
            report=M.index_summary(db,self.manifest,522)
            self.assertEqual(report["row_groups_total"],522)
            self.assertEqual(report["row_groups_complete"],1)
            self.assertFalse(report["index_complete"])
            self.assertEqual(report["unique_regular_session_keys"],1)
        finally:
            db.close()

    def test_cross_file_same_key_is_duplicate(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,counts)
            M.insert_group(db,1,0,data,counts)
            report=M.index_summary(db,self.manifest,2)
            self.assertEqual(report["duplicate_regular_session_keys"],1)
            self.assertEqual(report["row_group_locator_entries"],2)
            self.assertEqual(report["row_group_locator_compact_rows"],2)
            self.assertEqual(M.index_matches_and_groups(
                db,("SH600000",),20250930),{0:[0],1:[0]})
        finally:
            db.close()

    def test_sparse_groupids_handles_large_and_cross_byte_group_ids(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            for rg in (0,7,8,255,521):
                M.insert_group(db,0,rg,data,counts)
            summary=M.index_summary(db,self.manifest,5)
            self.assertEqual(summary["row_group_locator_compact_rows"],1)
            self.assertEqual(summary["row_group_locator_entries"],5)
            self.assertEqual(summary["row_group_locator_payload_bytes"],7)
            self.assertEqual(summary["duplicate_regular_session_keys"],4)
            self.assertEqual(M.index_matches_and_groups(
                db,("SH600000",),20250930),{0:[0,7,8,255,521]})
        finally:
            db.close()

    def test_sparse_varint_union_does_not_pad_high_row_group(self):
        self.assertEqual(len(M.encode_group_ids([521])),2)
        self.assertEqual(M.decode_group_ids(M.encode_group_ids([0,8,521])),
                         [0,8,521])
        self.assertEqual(M.decode_group_ids(M.merge_group_ids(
            M.encode_group_ids([521,8]), M.encode_group_ids([0,8]))),
            [0,8,521])
        self.assertEqual(M.merge_group_ids(b"",M.encode_group_ids([521])),
                         M.encode_group_ids([521]))

    def test_corrupted_varint_fails_closed(self):
        for encoded in (b"\x00",b"\x80",b"\x01\x01",b"\x81\x00"):
            with self.assertRaises(ValueError):
                M.decode_group_ids(encoded)
        with self.assertRaises(ValueError):
            M.encode_group_ids([-1])


    def test_storage_budget_includes_sqlite_main_or_wal_allocation(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,counts)
            usage=M.index_storage_usage(db,self.index)
            self.assertGreater(usage["sqlite_logical_allocated_bytes"],0)
            self.assertEqual(usage["sqlite_budget_measure_bytes"],max(
                usage["sqlite_logical_allocated_bytes"],
                usage["sqlite_main_and_wal_on_disk_bytes"]))
            self.assertTrue(usage["sqlite_wal_file_included_if_present"])
        finally:
            db.close()

    def test_soft_budget_boundary_and_no_budget(self):
        usage={"sqlite_budget_measure_bytes":2*1024*1024}
        self.assertFalse(M.budget_exceeded(usage,None))
        self.assertFalse(M.budget_exceeded(usage,2.01))
        self.assertTrue(M.budget_exceeded(usage,2))
        self.assertTrue(M.budget_exceeded(usage,1.99))

    def test_invalid_budget_fails_before_index_open(self):
        import contextlib
        import io
        for invalid in ("0","-1","nan","inf"):
            with self.subTest(value=invalid):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as err:
                        M.main([".", "--year", "2025", "--max-index-mib",
                                invalid, "--read-only"])
                self.assertEqual(err.exception.code,2)
        self.assertFalse(self.index.exists())

    def test_wall_time_budget_boundary_and_disabled_default(self):
        self.assertFalse(M.wall_budget_exceeded(100.0,None,now=10_000.0))
        self.assertFalse(M.wall_budget_exceeded(100.0,90.0,now=189.999))
        self.assertTrue(M.wall_budget_exceeded(100.0,90.0,now=190.0))
        self.assertTrue(M.wall_budget_exceeded(100.0,90.0,now=191.0))
        with self.assertRaisesRegex(ValueError,"max-run-seconds"):
            M.wall_budget_exceeded(100.0,0.0,now=100.0)

    def test_invalid_wall_time_budget_fails_before_index_open(self):
        import contextlib
        import io
        for invalid in ("0","-1","nan","inf"):
            with self.subTest(value=invalid):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as exc:
                        M.main([".", "--year", "2025", "--max-run-seconds",
                                invalid, "--read-only"])
                self.assertEqual(exc.exception.code,2)
        self.assertFalse(self.index.exists())

    def test_wall_budget_stops_after_committed_group_and_resumes(self):
        """Fake Parquet batches; no paid files and no pyarrow dependency."""
        import json
        import sys
        import types
        from unittest import mock

        module_dir = Path(self.temp.name)
        root = module_dir / "fake_source"
        file = root / "AllCycleAStockData" / "5min" / "2025.parquet"
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(b"fake-schema-only")

        class FakeParquetFile:
            def __init__(self, path):
                self.schema_arrow=types.SimpleNamespace(names=["ts","symbol"])
                self.metadata=types.SimpleNamespace(num_row_groups=3)

            def iter_batches(self, row_groups, columns, batch_size, use_threads):
                self_row = row_groups[0]
                yield FakeBatch([ms("202509300930")+self_row*300000],
                                ["600000.XSHG"])

        pq=types.ModuleType("pyarrow.parquet")
        pq.ParquetFile=FakeParquetFile
        pyarrow=types.ModuleType("pyarrow")
        pyarrow.__path__=[]
        pyarrow.parquet=pq
        with (mock.patch.object(M.core,"MODULE_DIR",module_dir),
              mock.patch.dict(sys.modules,{"pyarrow":pyarrow,"pyarrow.parquet":pq})):
            with mock.patch.object(M,"wall_budget_exceeded",
                                   side_effect=[False,True]) as elapsed_check:
                M.main([str(root),"--year","2025","--max-new-groups","3",
                        "--max-run-seconds","1","--report-detail","progress",
                        "--read-only","--report","reports/soft-wall-1.json"])
                self.assertEqual(elapsed_check.call_count,2)
            first=json.loads((module_dir/"reports"/"soft-wall-1.json").read_text(
                encoding="utf-8"))
            self.assertEqual(first["row_groups_complete"],1)
            self.assertEqual(first["new_row_groups_this_run"],1)
            self.assertTrue(first["soft_wall_budget_reached"])
            self.assertEqual(first["stopped_for"],"max_run_seconds_after_group")
            self.assertTrue(first["run_limited_before_complete"])
            self.assertEqual(first["max_run_seconds_soft_budget"],1.0)
            self.assertIsNone(first["duplicate_regular_session_keys"])
            M.main([str(root),"--year","2025","--resume","--max-new-groups","3",
                    "--report-detail","progress","--read-only",
                    "--report","reports/soft-wall-resume.json"])
        second=json.loads((module_dir/"reports"/"soft-wall-resume.json").read_text(
            encoding="utf-8"))
        self.assertTrue(second["index_complete"])
        self.assertTrue(second["full_key_audit_performed"])
        self.assertEqual(second["row_groups_complete"],3)
        self.assertEqual(second["new_row_groups_this_run"],2)
        self.assertFalse(second["soft_wall_budget_reached"])
        self.assertIsNone(second["max_run_seconds_soft_budget"])

    def test_budget_checkpoint_reclaims_unnecessary_wal_and_can_continue(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            # Build a real transaction log without changing source-data records.
            # Keep below SQLite's default automatic 1000-page checkpoint.
            for n in range(40):
                with db:
                    db.execute(
                        "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                        ("synthetic_wal_pressure", "A"*4096 + str(n)))
            before=M.index_storage_usage(db,self.index)
            self.assertGreater(
                before["sqlite_main_and_wal_on_disk_bytes"],
                before["sqlite_logical_allocated_bytes"])
            cap=(before["sqlite_main_and_wal_on_disk_bytes"] +
                 before["sqlite_logical_allocated_bytes"])/2/1048576
            blocked,after,event=M.budget_check_after_wal_recovery(
                db,self.index,cap)
            self.assertFalse(blocked)
            self.assertIsNotNone(event)
            self.assertFalse(event["checkpoint_busy"])
            self.assertGreater(event["reclaimed_disk_bytes"],0)
            self.assertLess(after["sqlite_budget_measure_bytes"],
                            before["sqlite_budget_measure_bytes"])
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute(
                "SELECT value FROM meta WHERE key='synthetic_wal_pressure'"
                ).fetchone()[0][-2:],"39")
        finally:
            db.close()

    def test_budget_checkpoint_keeps_real_over_budget_state(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            with db:
                db.execute("INSERT INTO meta(key,value) VALUES(?,?)",
                           ("extra", "B"*4096))
            blocked,after,event=M.budget_check_after_wal_recovery(
                db,self.index,0.001)
            self.assertTrue(blocked)
            self.assertIsNotNone(event)
            self.assertFalse(event["checkpoint_busy"])
            self.assertGreater(after["sqlite_logical_allocated_bytes"],1024)
        finally:
            db.close()

    def test_budget_checkpoint_skips_wal_work_under_limit(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            blocked,usage,event=M.budget_check_after_wal_recovery(
                db,self.index,1024)
            self.assertFalse(blocked)
            self.assertIsNone(event)
            self.assertGreater(usage["sqlite_budget_measure_bytes"],0)
        finally:
            db.close()

    def test_budget_checkpoint_refuses_uncommitted_transactions(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            db.execute("INSERT INTO meta(key,value) VALUES(?,?)",
                       ("uncommitted","test"))
            with self.assertRaisesRegex(ValueError,"inside a transaction"):
                M.budget_check_after_wal_recovery(db,self.index,0.001)
            db.rollback()
        finally:
            db.close()

    def test_clone_from_incomplete_v3_index_keeps_original_intact(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,counts)
        finally:
            db.close()
        clone=Path(self.temp.name)/"other"/"pilot.sqlite"
        M.clone_partial_index(self.index,clone,self.manifest)
        self.assertTrue(clone.exists())
        copy=M.open_index(clone,self.manifest,True,journal_mode="delete")
        try:
            self.assertEqual(copy.execute("PRAGMA journal_mode").fetchone()[0],"delete")
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300935")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(copy,0,1,data,counts)
            self.assertEqual(M.index_summary(copy,self.manifest,2)
                             ["unique_regular_session_keys"],2)
        finally:
            copy.close()
        original=M.open_index(self.index,self.manifest,True)
        try:
            self.assertEqual(M.index_summary(original,self.manifest,2)
                             ["row_groups_complete"],1)
            self.assertEqual(M.index_summary(original,self.manifest,2)
                             ["unique_regular_session_keys"],1)
            self.assertEqual(original.execute("PRAGMA journal_mode").fetchone()[0],"wal")
        finally:
            original.close()

    def test_snapshot_clone_in_wal_mode_has_same_checkpoint_count(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,stats=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,stats)
        finally:
            db.close()
        cloned=Path(self.temp.name)/"pilot-wal.sqlite"
        M.clone_partial_index(self.index,cloned,self.manifest)
        copied=M.open_index(cloned,self.manifest,True,journal_mode="wal")
        try:
            self.assertEqual(copied.execute("PRAGMA journal_mode").fetchone()[0],"wal")
            self.assertEqual(copied.execute("SELECT COUNT(*) FROM groups_done")
                             .fetchone()[0],1)
        finally:
            copied.close()

    def test_clone_rejects_fingerprint_mismatch_and_existing_destination(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,stats=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,stats)
        finally:
            db.close()
        target=Path(self.temp.name)/"pilots"/"trial.sqlite"
        changed=dict(self.manifest)
        changed["year"]=2024
        with self.assertRaisesRegex(ValueError,"fingerprint"):
            M.clone_partial_index(self.index,target,changed)
        self.assertFalse(target.exists())
        M.clone_partial_index(self.index,target,self.manifest)
        with self.assertRaisesRegex(ValueError,"Refusing to overwrite"):
            M.clone_partial_index(self.index,target,self.manifest)
        self.assertTrue(target.exists())

    def test_clone_rejects_empty_or_completed_sources(self):
        db=M.open_index(self.index,self.manifest,False)
        db.close()
        target=Path(self.temp.name)/"empty-pilot.sqlite"
        with self.assertRaisesRegex(ValueError,"no completed"):
            M.clone_partial_index(self.index,target,self.manifest)
        self.assertFalse(target.exists())
        db=M.open_index(self.index,self.manifest,True)
        try:
            data,stats=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,stats)
            with db:
                db.execute("UPDATE meta SET value='true' WHERE key='completed'")
        finally:
            db.close()
        with self.assertRaisesRegex(ValueError,"incomplete checkpoint"):
            M.clone_partial_index(self.index,target,self.manifest)
        self.assertFalse(target.exists())

    def test_unsupported_journal_mode_does_not_create_silent_database(self):
        with self.assertRaisesRegex(ValueError,"Unsupported SQLite journal mode"):
            M.open_index(self.index,self.manifest,False,journal_mode="memory")
        # SQLite may have created an empty file before mode validation; no
        # source data or checkpoint should have been written to that file.
        if self.index.exists():
            self.assertEqual(self.index.stat().st_size,0)

    def test_processing_profile_accounts_for_each_stage_without_double_wal_count(self):
        rows=[
            {"file_id":0,"row_group":34,"read_and_aggregate_seconds":4.5,
             "commit_seconds":2.0},
            {"file_id":0,"row_group":35,"read_and_aggregate_seconds":2.0,
             "commit_seconds":8.0}
        ]
        times={
            "parquet_read_and_key_aggregation":6.5,
            "sqlite_group_commit":10.0,
            "budget_guard_and_checkpoint":3.0,
            "wal_checkpoint_inside_budget":2.75
        }
        profile=M.processing_profile(times,rows,20.0)
        self.assertEqual(profile["profiled_new_groups"],2)
        self.assertEqual(profile["unattributed_seconds"],0.5)
        self.assertEqual(profile["wal_checkpoint_inside_budget_seconds"],2.75)
        self.assertEqual(profile["slowest_parquet_read_and_aggregate_groups"][0]["row_group"],34)
        self.assertEqual(profile["slowest_sqlite_commit_groups"][0]["row_group"],35)
        self.assertEqual(profile["phases_seconds"]["budget_guard_and_checkpoint"],3.0)

    def test_processing_profile_empty_stage_set_reports_no_fake_ohlcv(self):
        result=M.processing_profile({},[],2.0)
        self.assertEqual(result["profiled_new_groups"],0)
        self.assertEqual(result["unattributed_seconds"],2.0)
        self.assertEqual(result["slowest_sqlite_commit_groups"],[])
        self.assertEqual(result["wal_checkpoint_inside_budget_seconds"],0)
        self.assertNotIn("open",str(result))
        self.assertNotIn("close",str(result))

    def test_processing_profile_slowest_group_examples_are_bounded(self):
        rows=[{"file_id":0, "row_group":i, "read_and_aggregate_seconds":float(i),
               "commit_seconds":float(100-i)} for i in range(10)]
        result=M.processing_profile({},rows,0.0)
        self.assertEqual(len(result["slowest_sqlite_commit_groups"]),5)
        self.assertEqual(len(result["slowest_parquet_read_and_aggregate_groups"]),5)
        self.assertEqual(result["slowest_parquet_read_and_aggregate_groups"][0]["row_group"],9)
        self.assertEqual(result["slowest_sqlite_commit_groups"][0]["row_group"],0)

    def test_sqlite_nested_timing_breakdown_preserves_index_state(self):
        """Instrumenting each UPSERT must not change committed V3 coverage."""
        db=M.open_index(self.index,self.manifest,False)
        try:
            parts={
                ("SH600000",20250930):[1,1],
                ("SZ000636",20250930):[2,1]
            }
            counts=M.Counter({"source_rows":2,"candidate_rows":2})
            timings={}
            M.insert_group(db,0,0,parts,counts,timing_out=timings)
            expected={
                "prepare_seconds", "daily_coverage_upsert_seconds",
                "row_group_locator_upsert_seconds", "groups_done_insert_seconds",
                "commit_and_other_seconds",
                "transaction_context_enter_seconds",
                "transaction_context_exit_seconds"
            }
            self.assertEqual(set(timings),expected)
            self.assertLessEqual(
                timings["transaction_context_enter_seconds"] +
                timings["transaction_context_exit_seconds"],
                timings["commit_and_other_seconds"] + 0.02)
            self.assertTrue(all(isinstance(value,float) and value>=0
                                for value in timings.values()))
            self.assertEqual(
                M.index_summary(db,self.manifest,1)["unique_regular_session_keys"],2)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM groups_done").fetchone()[0],1)
        finally:
            db.close()

    def test_nested_sqlite_timing_is_published_only_after_commit(self):
        """A failed duplicate-group transaction must never publish partial timing."""
        db=M.open_index(self.index,self.manifest,False)
        try:
            data={("SH600000",20250930):[1,1]}
            counts=M.Counter({"source_rows":1,"candidate_rows":1})
            M.insert_group(db,0,0,data,counts)
            output={"keep_existing":1}
            with self.assertRaises(sqlite3.IntegrityError):
                M.insert_group(db,0,0,data,counts,timing_out=output)
            self.assertEqual(output,{"keep_existing":1})
            self.assertEqual(
                db.execute("SELECT SUM(source_rows) FROM daily_coverage").fetchone()[0],1)
        finally:
            db.close()

    def test_nested_sqlite_profile_is_non_additive_and_old_input_compatible(self):
        """Nested phases subdivide commit, not inflate profiled wall time."""
        nested={
            "prepare_seconds":0.2,
            "daily_coverage_upsert_seconds":0.8,
            "row_group_locator_upsert_seconds":1.2,
            "groups_done_insert_seconds":0.1,
            "commit_and_other_seconds":0.2
        }
        measured={
            "file_id":0,"row_group":57,
            "read_and_aggregate_seconds":1.0,
            "commit_seconds":2.7,
            "sqlite_write_breakdown_seconds":nested
        }
        report=M.processing_profile({
            "parquet_read_and_key_aggregation":1.0,
            "sqlite_group_commit":2.7},[measured],3.7)
        self.assertEqual(report["sqlite_write_breakdown_profiled_groups"],1)
        self.assertEqual(report["sqlite_write_breakdown_seconds"]
                         ["daily_coverage_upsert_seconds"],0.8)
        self.assertAlmostEqual(
            sum(report["sqlite_write_breakdown_seconds"].values()),2.7,places=4)
        self.assertEqual(report["unattributed_seconds"],0.0)
        self.assertEqual(report["phases_seconds"]["sqlite_group_commit"],2.7)
        self.assertEqual(report["sqlite_transaction_boundary_seconds"]
                         ["context_exit_seconds"],0.0)
        old=M.processing_profile({},[],1.0)
        self.assertEqual(old["sqlite_write_breakdown_profiled_groups"],0)
        self.assertTrue(all(v==0.0 for v in
                            old["sqlite_write_breakdown_seconds"].values()))

    def test_observed_sqlite_transaction_exit_is_nested_not_additive(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            output={}
            M.insert_group(db,0,0,{("SH600000",20250930):[1,1]},
                           M.Counter({"source_rows":1,"candidate_rows":1}),
                           timing_out=output)
            enter=output["transaction_context_enter_seconds"]
            exit=output["transaction_context_exit_seconds"]
            self.assertGreaterEqual(enter,0.0)
            self.assertGreaterEqual(exit,0.0)
            self.assertLessEqual(enter+exit,output["commit_and_other_seconds"]+0.02)
            total=sum(output[k] for k in (
                "prepare_seconds","daily_coverage_upsert_seconds",
                "row_group_locator_upsert_seconds","groups_done_insert_seconds",
                "commit_and_other_seconds"))
            result=M.processing_profile(
                {"sqlite_group_commit":total},
                [{"file_id":0,"row_group":0,"read_and_aggregate_seconds":0.0,
                  "commit_seconds":total,"sqlite_write_breakdown_seconds":output}],
                elapsed=total)
            nested=result["sqlite_transaction_boundary_seconds"]
            self.assertAlmostEqual(nested["context_exit_seconds"],exit,places=2)
            self.assertAlmostEqual(
                nested["context_enter_seconds"]+nested["context_exit_seconds"]+
                nested["other_within_commit_and_other_seconds"],
                output["commit_and_other_seconds"],places=2)
            self.assertEqual(result["unattributed_seconds"],0.0)
        finally:
            db.close()

    def test_observed_sqlite_transaction_preserves_rollback_on_error(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            transaction=M._ObservedSQLiteTransaction(db)
            with self.assertRaises(sqlite3.IntegrityError):
                with transaction:
                    db.execute(
                        "INSERT INTO daily_coverage VALUES(?,?,?,?)",
                        ("SH600000",20250930,1,1))
                    db.execute(
                        "INSERT INTO daily_coverage VALUES(?,?,?,?)",
                        ("SH600000",20250930,1,1))
            self.assertGreaterEqual(transaction.exit_seconds,0.0)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM daily_coverage").fetchone()[0],0)
        finally:
            db.close()

    def test_pk_sorted_write_yields_identical_daily_and_locator_state(self):
        """Reordered input and overlapping groups must yield identical V3 state."""
        rows1 = [
            (("SZ000636",20250930),[3,2]),
            (("SH600000",20250930),[5,2]),
            (("SH600000",20250929),[1,1])
        ]
        rows2 = [
            (("SH600000",20250930),[8,1]),
            (("SZ000636",20250930),[16,1]),
            (("SH600000",20250929),[2,1])
        ]
        created=[]
        try:
            for order in ("source","pk-sorted"):
                path=Path(self.temp.name)/("compare-"+order+".sqlite")
                db=M.open_index(path,self.manifest,False)
                created.append(db)
                first=dict(rows1)
                second=dict(rows2)
                # Match source row counts to the compressed group counters.
                c1=sum(value[1] for value in first.values())
                c2=sum(value[1] for value in second.values())
                M.insert_group(db,0,31,first,
                               M.Counter({"source_rows":c1,"candidate_rows":c1}),
                               write_order=order)
                M.insert_group(db,0,32,second,
                               M.Counter({"source_rows":c2,"candidate_rows":c2}),
                               write_order=order)
            results=[]
            for db in created:
                summary=M.index_summary(db,self.manifest,2)
                # Different write orders can legitimately allocate different
                # SQLite page counts; compare logical coverage, not B-tree
                # physical byte layout.
                summary.pop("sqlite_main_estimated_allocated_bytes")
                daily=list(db.execute("SELECT * FROM daily_coverage ORDER BY symbol,trade_day"))
                loc=[(row[0],row[1],row[2],M.decode_group_ids(row[3]))
                     for row in db.execute(
                         "SELECT * FROM row_group_locator ORDER BY symbol,trade_day,file_id")]
                results.append((summary,daily,loc))
            self.assertEqual(results[0],results[1])
            self.assertEqual(results[0][0]["row_groups_complete"],2)
            self.assertEqual(results[0][0]["row_group_locator_entries"],6)
            self.assertEqual(results[0][0]["duplicate_regular_session_keys"],0)
        finally:
            for db in created:
                db.close()

    def test_sorted_write_preserves_atomic_rollback(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            packed={("SH600000",20250930):[1,1],
                    ("SZ000636",20250930):[2,1]}
            counts=M.Counter({"source_rows":2,"candidate_rows":2})
            M.insert_group(db,0,0,packed,counts,write_order="pk-sorted")
            with self.assertRaises(sqlite3.IntegrityError):
                M.insert_group(db,0,0,packed,counts,write_order="pk-sorted")
            self.assertEqual(db.execute("SELECT SUM(source_rows) FROM daily_coverage")
                             .fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM groups_done").fetchone()[0],1)
        finally:
            db.close()

    def test_unsupported_write_order_fails_before_sqlite_mutation(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            with self.assertRaisesRegex(ValueError,"Unsupported SQLite write ordering"):
                M.insert_group(db,0,0,{("SH600000",20250930):[1,1]},
                               M.Counter({"source_rows":1,"candidate_rows":1}),
                               write_order="random")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM daily_coverage")
                             .fetchone()[0],0)
        finally:
            db.close()

    def test_processing_profile_separates_full_summary_from_unattributed(self):
        timings = {
            "parquet_read_and_key_aggregation": 3.0,
            "sqlite_group_commit": 5.0,
            "budget_guard_and_checkpoint": 1.0,
            "wal_checkpoint_inside_budget": 0.5,
            "final_index_summary": 7.0
        }
        profile = M.processing_profile(timings, [], 16.5)
        self.assertEqual(profile["phases_seconds"]["final_index_summary"], 7.0)
        self.assertEqual(profile["unattributed_seconds"], 0.5)
        self.assertEqual(profile["wal_checkpoint_inside_budget_seconds"], 0.5)

    def test_loop_residual_excludes_nested_stages_and_wal_substage(self):
        phase = {
            "checkpoint_lookup": 1.0,
            "parquet_read_and_key_aggregation": 4.0,
            "sqlite_group_commit": 5.0,
            "budget_guard_and_checkpoint": 3.0,
            "wal_checkpoint_inside_budget": 2.0,
            "progress_output": 0.5
        }
        self.assertEqual(M.row_group_loop_residual(20.0,phase),6.5)
        self.assertEqual(M.row_group_loop_residual(10.0,phase),0.0)

    def test_extended_phase_profile_explains_long_wall_gap_without_false_speedup(self):
        # Mimics the 45/522 report: most wall time was not covered by the
        # old phase counters. Residual is NOT assigned to SQLite write time.
        phases = {
            "parquet_footer_metadata": 0.10,
            "checkpoint_lookup": 0.05,
            "parquet_read_and_key_aggregation": 33.077,
            "sqlite_group_commit": 140.517,
            "budget_guard_and_checkpoint": 0.109,
            "wal_checkpoint_inside_budget": 0.0,
            "progress_output": 0.01,
            "final_index_summary": 0.047
        }
        loop_wall = 1318.813 - phases["parquet_footer_metadata"] - phases["final_index_summary"]
        phases["row_group_loop_other"] = M.row_group_loop_residual(loop_wall,phases)
        report = M.processing_profile(phases,[],1318.813)
        self.assertAlmostEqual(report["unattributed_seconds"],0.0,places=2)
        self.assertGreater(report["phases_seconds"]["row_group_loop_other"],1100)
        self.assertEqual(report["phases_seconds"]["sqlite_group_commit"],140.517)
        self.assertEqual(report["wal_checkpoint_inside_budget_seconds"],0.0)

    def test_longest_whole_group_spans_are_bounded_and_keep_original_fields(self):
        groups = [
            {"file_id":0, "row_group":i,
             "read_and_aggregate_seconds":2.0, "commit_seconds":5.0,
             "row_group_wall_seconds":float(i * 10)}
            for i in range(10)
        ]
        groups.append({"file_id":0, "row_group":999,
                       "read_and_aggregate_seconds":0.1, "commit_seconds":0.2})
        report = M.processing_profile({},groups,0.0)
        slow = report["slowest_row_group_wall_groups"]
        self.assertEqual(len(slow),5)
        self.assertEqual([v["row_group"] for v in slow],[9,8,7,6,5])
        self.assertEqual(slow[0]["row_group_wall_seconds"],90.0)
        self.assertNotIn("open",str(report))
        self.assertNotIn("close",str(report))

    def test_progress_report_marks_unknown_duplicates_null_not_zero(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,counts)
            progress=M.index_summary(db,self.manifest,522,detail="progress")
            self.assertEqual(progress["row_groups_complete"],1)
            self.assertEqual(progress["candidate_source_rows"],1)
            self.assertIsNone(progress["unique_regular_session_keys"])
            self.assertIsNone(progress["duplicate_regular_session_keys"])
            self.assertIsNone(progress["stock_day_partitions"])
            self.assertIsNone(progress["row_group_locator_entries"])
            self.assertFalse(progress["full_key_audit_performed"])
            self.assertFalse(progress["index_complete"])
            self.assertFalse(progress["safe_to_automatically_union"])
        finally:
            db.close()

    def test_quick_progress_skips_expensive_daily_and_locator_table_scans(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,counts)
            selects=[]
            db.set_trace_callback(selects.append)
            try:
                M.index_summary(db,self.manifest,522,detail="progress")
            finally:
                db.set_trace_callback(None)
            query=" ".join(selects).lower()
            self.assertIn("groups_done",query)
            self.assertNotIn("from daily_coverage",query)
            self.assertNotIn("from row_group_locator",query)
        finally:
            db.close()

    def test_final_row_group_forces_full_audit_even_if_progress_requested(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300930"),ms("202509300935")],
                           ["600000.XSHG","600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,counts)
            report=M.index_summary(db,self.manifest,1,detail="progress")
            self.assertEqual(report["report_detail_effective"],"full")
            self.assertTrue(report["index_complete"])
            self.assertTrue(report["full_key_audit_performed"])
            self.assertEqual(report["unique_regular_session_keys"],2)
            self.assertEqual(report["duplicate_regular_session_keys"],0)
            M.persist_report_certification(db,report)
            stored=dict(db.execute("SELECT key,value FROM meta"))
            self.assertEqual(stored["completed"],"true")
            self.assertEqual(stored["duplicate_regular_session_keys"],"0")
        finally:
            db.close()

    def test_resumed_progress_invalidates_previous_exact_duplicate_cache(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            data,counts=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,0,data,counts)
            full=M.index_summary(db,self.manifest,522,detail="full")
            M.persist_report_certification(db,full)
            self.assertEqual(dict(db.execute("SELECT key,value FROM meta"))
                             ["duplicate_regular_session_keys"],"0")
            duplicate,stats=M.aggregate_batches(
                [FakeBatch([ms("202509300930")],["600000.XSHG"])],
                2025,"a-share-candidate")
            M.insert_group(db,0,1,duplicate,stats)
            quick=M.index_summary(db,self.manifest,522,detail="progress")
            M.persist_report_certification(db,quick)
            stored=dict(db.execute("SELECT key,value FROM meta"))
            self.assertNotIn("duplicate_regular_session_keys",stored)
            self.assertEqual(stored["full_key_audit_performed"],"false")
            self.assertEqual(stored["completed"],"false")
            verified=M.index_summary(db,self.manifest,522,detail="full")
            self.assertEqual(verified["duplicate_regular_session_keys"],1)
        finally:
            db.close()

    def test_unknown_report_detail_refused(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            with self.assertRaisesRegex(ValueError,"Unsupported report detail"):
                M.index_summary(db,self.manifest,522,detail="fast-but-certified")
        finally:
            db.close()

    def test_index_has_no_ohlcv_columns(self):
        db=M.open_index(self.index,self.manifest,False)
        try:
            cols=[row[1] for row in db.execute("PRAGMA table_info(daily_coverage)")]
            self.assertEqual(cols,["symbol","trade_day","slot_mask","source_rows"])
            cols=[row[1] for row in db.execute("PRAGMA table_info(row_group_locator)")]
            self.assertEqual(cols,["symbol","trade_day","file_id","group_ids"])
            self.assertFalse(any(field in cols for field in (
                "open","high","low","close","volume","amount")))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
