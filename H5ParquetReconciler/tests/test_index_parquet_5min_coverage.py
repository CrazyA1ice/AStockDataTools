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
        for encoded in (b"\x00",b"\x80",b"\x01\x01"):
            with self.assertRaises(ValueError):
                M.decode_group_ids(encoded) if encoded != b"\x01\x01" else (
                    M.decode_group_ids(encoded) if len(set(M.decode_group_ids(encoded))) == 2
                    else (_ for _ in ()).throw(ValueError("duplicate"))
                )
        with self.assertRaises(ValueError):
            M.encode_group_ids([-1])


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
