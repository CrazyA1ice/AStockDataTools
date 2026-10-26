"""Synthetic Parquet day-vs-5min volume hypothesis tests; no paid data."""
import importlib.util
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "tools" / "inspect-parquet-day-vs-5min-volume.py"
SPEC = importlib.util.spec_from_file_location("pq_cycle_probe", SRC)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
BEIJING = timezone(timedelta(hours=8))


class FakeArray:
    def __init__(self, v):
        self.v = v

    def to_pylist(self):
        return self.v


class FakeBatch:
    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows

    def column(self, i):
        return FakeArray([r[self.columns[i]] for r in self.rows])


class FakeParquetFile:
    data = {}

    def __init__(self, path):
        self.all_rows = self.data[str(path)]
        self.groups = [self.all_rows[i:i+15]
                       for i in range(0, len(self.all_rows), 15)]
        self.schema_arrow = types.SimpleNamespace(
            names=("ts", "symbol", "volume"))
        self.metadata = types.SimpleNamespace(
            num_row_groups=len(self.groups), row_group=self.row_group)

    def row_group(self, i):
        lo = min(r["ts"] for r in self.groups[i])
        hi = max(r["ts"] for r in self.groups[i])
        stat = types.SimpleNamespace(has_min_max=True, min=lo, max=hi)
        return types.SimpleNamespace(
            num_columns=1,
            column=lambda j: types.SimpleNamespace(
                path_in_schema="ts", statistics=stat))

    def iter_batches(self, *, row_groups, batch_size, columns, use_threads):
        for i in row_groups:
            rows = self.groups[i]
            for off in range(0,len(rows),batch_size):
                yield FakeBatch(columns, rows[off:off+batch_size])


class ParquetCycleAuditTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name) / "stock"
        for period in ("day", "5min"):
            (self.root/"AllCycleAStockData"/period).mkdir(parents=True)
        FakeParquetFile.data = {}

    def stamp(self, year_day, hhmm):
        ds = f"{year_day}{hhmm:04d}"
        return int(datetime.strptime(ds,"%Y%m%d%H%M")
                   .replace(tzinfo=BEIJING).timestamp()*1000)

    def srcrow(self, day, hhmm, symbol, volume):
        return {"ts": self.stamp(day,hhmm), "symbol": symbol,
                "volume": float(volume)}

    def minute_rows(self, day, symbol, volume=100):
        rows = []
        for label in sorted(M.EXPECTED_ENDS):
            end = datetime.strptime(f"{day}{label:04d}","%Y%m%d%H%M")
            begin = end - timedelta(minutes=5)
            rows.append(self.srcrow(
                int(begin.strftime("%Y%m%d")),
                int(begin.strftime("%H%M")),symbol,volume))
        return rows

    def put(self, day_records, minute_records):
        for period, rows in (("day", day_records),("5min", minute_records)):
            path=self.root/"AllCycleAStockData"/period/"2026.parquet"
            path.write_bytes(b"FAKE")
            FakeParquetFile.data[str(path)] = rows

    def fake_arrow(self):
        root=types.ModuleType("pyarrow")
        root.__path__ = []
        pq=types.ModuleType("pyarrow.parquet")
        pq.ParquetFile=FakeParquetFile
        root.parquet=pq
        return mock.patch.dict(sys.modules,{"pyarrow":root,"pyarrow.parquet":pq})

    def test_parquet_day_and_five_minute_match_one_times_scale(self):
        day = self.srcrow(20260929,0,"600000.XSHG",4800)
        bars = self.minute_rows(20260929,"600000.XSHG",100)
        # Other dates must be skipped without materializing within this window.
        self.put([self.srcrow(20260924,0,"600000.XSHG",300),day],
                 self.minute_rows(20260924,"600000.XSHG",100) + bars)
        with self.fake_arrow():
            report=M.make_report(self.root,2026,"2026-09-29","2026-09-29",512)
        totals=report["totals"]
        self.assertEqual(totals["complete_48_bar_stock_days_compared"],1)
        self.assertEqual(totals["raw_day_equals_sum_five_minute_0_1pct"],1)
        self.assertEqual(
            totals.get("day_times_100_equals_sum_five_minute_0_1pct",0),0)
        self.assertEqual(
            totals.get("day_equals_sum_five_minute_times_100_0_1pct",0),0)
        self.assertGreater(
            report["five_minute_source"]["row_groups_skipped_by_footer"],0)
        self.assertTrue(report["scan_complete"])
        self.assertFalse(report["safe_to_automatically_union"])
        self.assertFalse(report["unit_mapping_certified"])
        self.assertNotIn("4800", str(report))

    def test_parquet_day_hundreds_candidate_may_beat_identity(self):
        day=self.srcrow(20260929,0,"600000.XSHG",48)
        bars=self.minute_rows(20260929,"600000.XSHG",100)
        self.put([day], bars)
        with self.fake_arrow():
            report=M.make_report(self.root,2026,"2026-09-29","2026-09-29",512)
        t=report["totals"]
        self.assertEqual(t.get("raw_day_equals_sum_five_minute_0_1pct",0),0)
        self.assertEqual(t["day_times_100_equals_sum_five_minute_0_1pct"],1)
        self.assertEqual(t["complete_48_bar_stock_days_compared"],1)

    def test_missing_stock_day_and_session_label_never_false_pass(self):
        self.put([
            self.srcrow(20260929,0,"600000.XSHG",4800),
            self.srcrow(20260929,0,"600001.XSHG",100)],
            self.minute_rows(20260929,"600000.XSHG",100)[:-1] +
            self.minute_rows(20260929,"000001.XSHE",100))
        with self.fake_arrow():
            report=M.make_report(self.root,2026,"2026-09-29","2026-09-29",512)
        t=report["totals"]
        self.assertEqual(t["stock_days_with_both_cycles"],1)
        self.assertEqual(t["stock_days_only_day"],1)
        self.assertEqual(t["stock_days_only_five_minute"],1)
        self.assertEqual(t["five_minute_session_not_48_exact"],1)
        self.assertEqual(t.get("complete_48_bar_stock_days_compared",0),0)

    def test_duplicate_source_keys_incomplete(self):
        day=self.srcrow(20260929,0,"600000.XSHG",4800)
        bars=self.minute_rows(20260929,"600000.XSHG",100)
        self.put([day,day],bars)
        with self.fake_arrow():
            report=M.make_report(self.root,2026,"2026-09-29","2026-09-29",512)
        self.assertFalse(report["scan_complete"])
        self.assertEqual(report["day_source"]["duplicate_source_keys"],1)

    def test_7day_limit_and_invalid_dates(self):
        with self.assertRaisesRegex(ValueError,"limited to 7"):
            M.make_report(self.root,2026,"2026-09-01","2026-09-30",512)
        with self.assertRaises(ValueError):
            M.make_report(self.root,2026,"2025-09-01","2025-09-02",512)


if __name__=="__main__":
    unittest.main(verbosity=2)
