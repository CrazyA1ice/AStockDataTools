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

    def test_default_scratch_is_sibling_of_outside_report_not_inside_source(self):
        expected = self.out.parent / "_union_scratch"
        root, out, scratch = M.resolve_safe_paths(self.root, self.out, None)
        self.assertEqual(root, self.root.resolve())
        self.assertEqual(out, self.out.resolve())
        self.assertEqual(scratch, expected.resolve())
        self.assertFalse(scratch.is_relative_to(self.root.resolve()))
        self.write_h5("day", "sh", "SH600000", [(202610250000, 10, 10)])
        self.other_markets("day")
        with self.fake_arrow():
            result = M.run(self.root, self.out, None, [2026], ["day"], 512, False)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(expected.is_dir())
        self.assertEqual(result["results"]["day/2026"]["h5_only_rows"], 1)

    def test_unsafe_report_or_explicit_scratch_shows_resolved_paths(self):
        with self.assertRaisesRegex(ValueError, r"Report path is inside source data root"):
            M.resolve_safe_paths(self.root, self.root/"reports"/"audit.json", None)
        with self.assertRaisesRegex(ValueError, r"Scratch path is inside source data root"):
            M.resolve_safe_paths(self.root, self.out, self.root/"scratch")
        safe_root, safe_out, safe_scratch = M.resolve_safe_paths(
            self.root, self.out, self.dir/"scratch_explicit")
        self.assertEqual(safe_scratch, (self.dir/"scratch_explicit").resolve())
        self.assertNotEqual(safe_root, safe_out)

    def test_equity_candidate_mode_does_not_mix_indexes_and_b_shares(self):
        self.write_h5("day", "sh", "SH600000", [(202609080000, 12, 20)])
        file = self.root/"HikyuuData"/"sh_day.h5"
        with h5py.File(file, "a") as group:
            old=group["data"]["SH600000"][:]
            group["data"].create_dataset("SH000001",data=old)
        self.fake_parquet("day", 2026, [
            (self.epoch_ms("202609080000"), "600000.XSHG", 10, 10, 10, 10, 1200, 20000),
            (self.epoch_ms("202609080000"), "000001.XSHG", 10, 10, 10, 10, 100, 20000),
            (self.epoch_ms("202609080000"), "200025.XSHE", 10, 10, 10, 10, 100, 20000)
        ])
        self.other_markets("day")
        with self.fake_arrow():
            all_result=M.reconcile_section(self.root,self.scratch,"day",2026,512)
            equities=M.reconcile_section(self.root,self.scratch,"day",2026,512,
                                         universe="a-share-candidate")
        self.assertEqual(all_result["h5_rows"],2)
        self.assertEqual(all_result["pq_rows"],3)
        self.assertEqual(equities["h5_rows"],1)
        self.assertEqual(equities["pq_rows"],1)
        self.assertEqual(equities["matched_keys"],1)
        self.assertEqual(equities["h5_only_rows"],0)
        self.assertEqual(equities["pq_only_rows"],0)
        self.assertEqual(equities["h5_excluded_non_equity_rows"],1)
        self.assertEqual(equities["pq_excluded_non_equity_rows"],2)
        self.assertFalse(equities["security_master_certified"])

    def test_historical_bj_is_excluded_until_2022_but_not_erased_from_all_mode(self):
        self.assertFalse(M.is_a_share_candidate("BJ920961",2015))
        self.assertFalse(M.is_a_share_candidate("BJ920510",2021))
        self.assertTrue(M.is_a_share_candidate("BJ920510",2022))
        self.assertTrue(M.is_a_share_candidate("BJ830000",2026))
        self.assertFalse(M.is_a_share_candidate("SH000001",2026))
        self.assertFalse(M.is_a_share_candidate("SZ399001",2026))
        self.assertFalse(M.is_a_share_candidate("SZ200025",2026))
        self.assertTrue(M.is_a_share_candidate("SH688981",2026))
        self.assertFalse(M.is_a_share_candidate("SH688981",2018))
        self.assertTrue(M.is_a_share_candidate("SZ300750",2026))

    def test_resume_rejects_mixed_universe_reports(self):
        self.write_h5("day","sh","SH600000",[(202610250000,20,30)])
        self.other_markets("day")
        with self.fake_arrow():
            report=M.run(self.root,self.out,self.scratch,[2026],["day"],512,False,
                         universe="a-share-candidate")
        self.assertEqual(report["universe_mode"],"a-share-candidate")
        with self.assertRaisesRegex(ValueError,"Resume universe mode must match"):
            M.run(self.root,self.out,self.scratch,[2026],["day"],512,True,
                  universe="all")

    def test_universe_metadata_only_cannot_claim_equity_filtered_keys(self):
        self.fake_parquet("day",2015,[
            (self.epoch_ms("201503170000"),"920961.XBSE",10,10,10,10,100,1000)
        ])
        with self.fake_arrow():
            result=M.reconcile_section(self.root,self.scratch,"day",2015,512,
                                       universe="a-share-candidate")
        self.assertEqual(result["pq_rows"],1)
        self.assertEqual(result["pq_only_rows"],0)
        self.assertTrue(result["pq_year_metadata_only_no_h5_rows"])
        self.assertTrue(result["pq_footer_row_count_not_equity_filtered"])
        self.assertFalse(result["safe_to_automatically_union"])

    def test_cli_module_paths_are_independent_of_cwd_and_reject_external(self):
        module=self.dir/"AStockDataTools"/"H5ParquetReconciler"
        module.mkdir(parents=True)
        output, scratch=M.resolve_module_artifact_paths(None,None,module)
        self.assertEqual(output,module/"reports"/"h5-parquet-audit.json")
        self.assertEqual(scratch,module/"work"/"_union_scratch")
        self.assertTrue(output.is_relative_to(module))
        self.assertTrue(scratch.is_relative_to(module))
        rel_output,rel_scratch=M.resolve_module_artifact_paths(
            "h5-private-candidates/h5-parquet-day-audit.json",
            "scratch/sqlite",module)
        self.assertEqual(rel_output,module/"h5-private-candidates"/"h5-parquet-day-audit.json")
        self.assertEqual(rel_scratch,module/"scratch"/"sqlite")
        with self.assertRaisesRegex(ValueError,"must stay inside"):
            M.resolve_module_artifact_paths(self.dir/"other"/"audit.json",None,module)
        with self.assertRaisesRegex(ValueError,"must stay inside"):
            M.resolve_module_artifact_paths(None,self.dir/"external_tmp",module)
        with self.assertRaisesRegex(ValueError,"must stay inside"):
            M.resolve_module_artifact_paths("../audit.json",None,module)

    def test_moved_legacy_report_remains_resumable_in_module_root(self):
        module=self.dir/"AStockDataTools"/"H5ParquetReconciler"
        module.mkdir(parents=True)
        name="h5-parquet-day-equity-2025-2026.json"
        out, temp=M.resolve_module_artifact_paths(name,None,module)
        self.assertEqual(out,module/name)
        self.write_h5("day","sh","SH600000",[(202610250000,20,30)])
        self.other_markets("day")
        with self.fake_arrow():
            original=M.run(self.root,out,temp,[2026],["day"],512,False,
                           universe="a-share-candidate")
            with patch.object(M,"MODULE_DIR",module):
                M.main([str(self.root),"--years","2026","--periods","day",
                        "--universe","a-share-candidate","--read-only",
                        "--out",name,"--resume"])
        self.assertEqual(json.loads(out.read_text(encoding="utf-8")),original)
        self.assertTrue(out.with_suffix(".md").is_file())

    def test_default_cli_writes_only_inside_reconciler(self):
        module=self.dir/"AStockDataTools"/"H5ParquetReconciler"
        module.mkdir(parents=True)
        self.write_h5("day","sh","SH600000",[(202610250000,20,30)])
        self.other_markets("day")
        with self.fake_arrow(), patch.object(M,"MODULE_DIR",module):
            M.main([str(self.root),"--years","2026","--periods","day",
                    "--read-only"])
        result=module/"reports"/"h5-parquet-audit.json"
        self.assertTrue(result.exists())
        self.assertTrue(result.with_suffix(".md").exists())
        self.assertTrue((module/"work"/"_union_scratch").is_dir())
        self.assertFalse(self.out.exists())
        with patch.object(M,"MODULE_DIR",module):
            with self.assertRaises(SystemExit):
                M.main([str(self.root),"--years","2026","--periods","day",
                        "--read-only","--out",str(self.dir/"stray"/"out.json")])

    def test_5min_start_time_and_bj_aliases(self):
        self.assertEqual(M.pq_stamp(self.epoch_ms("202607161410"), "5min"), 202607161415)
        self.assertEqual(M.symbol_id("920000.XBSE"), "BJ920000")
        self.assertIsNone(M.symbol_id("not_a_ticker"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
