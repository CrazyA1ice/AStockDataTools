"""Synthetic-only regression tests; no user's purchased Parquet or H5 is needed."""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

SOURCE = Path(__file__).resolve().parents[1] / "tools" / "reconcile-local-a-share-h5-parquet.py"
SPEC = importlib.util.spec_from_file_location("reconciliation", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
H5_DTYPE = np.dtype([
    ("datetime", "<u8"), ("openPrice", "<i4"), ("highPrice", "<i4"),
    ("lowPrice", "<i4"), ("closePrice", "<i4"),
    ("transCount", "<u8"), ("transAmount", "<u8")
])


class FakeColumn:
    def __init__(self, data):
        self.data = data
    def to_pylist(self):
        return self.data


class FakeBatch:
    def __init__(self, rows):
        self.rows = rows
    def column(self, index):
        return FakeColumn([row[index] for row in self.rows])


class FakeParquetFile:
    files = {}
    def __init__(self, name):
        self.records = self.files[Path(name).name]
        self.schema_arrow = types.SimpleNamespace(names=list(M.NEEDED))
        self.metadata = types.SimpleNamespace(num_rows=len(self.records), num_row_groups=0)
    def iter_batches(self, **kwargs):
        batch = kwargs.get("batch_size", 512)
        for start in range(0, len(self.records), batch):
            yield FakeBatch(self.records[start:start+batch])


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.root = self.dir/"stock"
        self.root.mkdir()
        (self.root/"HikyuuData").mkdir()
        (self.root/"AllCycleAStockData").mkdir()
        self.scratch = self.dir/"scratch"
        self.scratch.mkdir()
        self.out = self.dir/"result.json"
        self.zone = timezone(timedelta(hours=8))

    def write_h5(self, period, market, symbol, entries):
        filename = self.root/"HikyuuData"/f"{market}_{period}.h5"
        values = np.zeros(len(entries), dtype=H5_DTYPE)
        for i, (stamp, volume, amount) in enumerate(entries):
            values["datetime"][i] = stamp
            for name in ("openPrice", "highPrice", "lowPrice", "closePrice"):
                values[name][i] = 10000
            values["transCount"][i] = volume
            values["transAmount"][i] = amount
        with h5py.File(filename, "w") as f:
            f.create_group("data").create_dataset(symbol, data=values)

    def other_markets(self, period):
        for market in ("sh", "sz", "bj"):
            name = self.root/"HikyuuData"/f"{market}_{period}.h5"
            if not name.exists():
                with h5py.File(name, "w") as f:
                    f.create_group("data")

    def fake_parquet(self, period, year, rows):
        folder = self.root/"AllCycleAStockData"/period
        folder.mkdir(exist_ok=True)
        name = folder/f"{year}.parquet"
        name.write_bytes(b"PAR1")
        FakeParquetFile.files[name.name] = rows

    def epoch_ms(self, d):
        return int(datetime.strptime(d, "%Y%m%d%H%M").replace(tzinfo=self.zone).timestamp()*1000)

    def fake_arrow(self):
        fake = types.ModuleType("pyarrow")
        fake.__path__ = []
        parquet = types.ModuleType("pyarrow.parquet")
        parquet.ParquetFile = FakeParquetFile
        fake.parquet = parquet
        return patch.dict(sys.modules, {"pyarrow": fake, "pyarrow.parquet": parquet})

    def test_day_overlap_gaps_newer_h5_and_price_differences(self):
        self.write_h5("day", "sh", "SH600000", [
            (202609070000, 10, 10), (202609080000, 12, 20),
            (202610250000, 20, 30)
        ])
        self.fake_parquet("day", 2026, [
            (self.epoch_ms("202609070000"), "600000.XSHG", 10, 10, 10, 10, 1000, 10000),
            (self.epoch_ms("202609080000"), "600000.XSHG", 10, 10.02, 10, 10, 1200, 20000),
            (self.epoch_ms("202609090000"), "600000.XSHG", 10, 10, 10, 10, 10, 20000)
        ])
        self.other_markets("day")
        with self.fake_arrow():
            r = M.reconcile_section(self.root, self.scratch, "day", 2026, 512)
        self.assertTrue(r["scan_complete"])
        self.assertEqual((r["h5_rows"], r["pq_rows"]), (3, 3))
        self.assertEqual(r["matched_keys"], 2)
        self.assertEqual(r["h5_only_rows"], 1)
        self.assertEqual(r["pq_only_rows"], 1)
        self.assertEqual(r["value_mismatch_rows"], 1)
        self.assertEqual(r["price_mismatch_rows"], 1)
        self.assertEqual(r["h5_only_latest"], 202610250000)
        self.assertEqual(r["by_day"]["20261025"]["h5_only"], 1)
        self.assertEqual(r["value_mismatch_examples"][0]["different_fields"], ["high"])

    def test_0930_exception_and_0931_quantity_candidate(self):
        self.write_h5("1min", "sh", "SH600000", [(202607160931, 120, 100)])
        self.fake_parquet("1min", 2026, [
            (self.epoch_ms("202607160930"), "600000.SH", 10, 10, 10, 10, 20, 10000),
            (self.epoch_ms("202607160931"), "600000.SH", 10, 10, 10, 10, 100, 100000)
        ])
        with self.fake_arrow():
            r = M.reconcile_section(self.root, self.scratch, "1min", 2026, 512)
        self.assertEqual(r["pq_0930_extra_candidate_rows"], 1)
        self.assertEqual(r["matched_keys"], 1)
        self.assertEqual(r["opening_candidate_mismatch_rows"], 1)
        self.assertEqual(r["pq_only_rows"], 0)
        self.assertFalse(r["safe_to_automatically_union"])

    def test_resume_and_h5_only_with_no_parquet(self):
        self.write_h5("day", "sh", "SH600000", [(202610250000, 20, 30)])
        self.other_markets("day")
        with self.fake_arrow():
            one = M.run(self.root, self.out, self.scratch, [2026], ["day"], 512, False)
            two = M.run(self.root, self.out, self.scratch, [2026], ["day"], 512, True)
        self.assertEqual(one, two)
        self.assertEqual(one["status"], "complete")
        self.assertEqual(one["results"]["day/2026"]["h5_only_rows"], 1)
        self.assertTrue(self.out.with_suffix(".md").is_file())
        with self.assertRaises(ValueError):
            M.run(self.root, self.out, self.scratch, [2025], ["day"], 512, True)

    def test_h5_empty_year_parquet_footer_is_candidate_only(self):
        self.fake_parquet("day", 2011, [
            (self.epoch_ms("201101050000"), "600000.SH", 10, 10, 10, 10, 100, 1000)
        ])
        with self.fake_arrow():
            r = M.reconcile_section(self.root, self.scratch, "day", 2011, 512)
        self.assertTrue(r["pq_year_metadata_only_no_h5_rows"])
        self.assertTrue(r["pq_only_candidate_rows_from_year_file_metadata_are_not_exact_keys"])
        self.assertEqual(r["pq_only_candidate_rows_from_year_file_metadata"], 1)

    def test_refuse_writing_under_source_tree(self):
        with self.assertRaises(ValueError):
            M.run(self.root, self.root/"report.json", self.scratch, [2026], ["day"], 512, False)
        with self.assertRaises(ValueError):
            M.run(self.root, self.out, self.root/"scratch", [2026], ["day"], 512, False)

    def test_5min_start_time_and_bj_aliases(self):
        self.assertEqual(M.pq_stamp(self.epoch_ms("202607161410"), "5min"), 202607161415)
        self.assertEqual(M.symbol_id("920000.XBSE"), "BJ920000")
        self.assertIsNone(M.symbol_id("not_a_ticker"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
