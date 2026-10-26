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
        self.groups = [self.records[i:i+2] for i in range(0,len(self.records),2)]
        self.metadata = types.SimpleNamespace(
            num_rows=len(self.records),
            num_row_groups=len(self.groups),
            row_group=self.row_group
        )
    def row_group(self, group_i):
        stamps=[r[0] for r in self.groups[group_i]]
        stats=types.SimpleNamespace(has_min_max=True,min=min(stamps),max=max(stamps))
        return types.SimpleNamespace(
            num_columns=1,
            column=lambda i: types.SimpleNamespace(path_in_schema="ts",statistics=stats)
        )
    def iter_batches(self, **kwargs):
        batch = kwargs.get("batch_size", 512)
        rgids = kwargs.get("row_groups")
        all_rows = (self.records if rgids is None
                    else [r for group in rgids for r in self.groups[group]])
        for start in range(0, len(all_rows), batch):
            yield FakeBatch(all_rows[start:start+batch])


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
        self.assertFalse(r["pq_footer_contains_unfiltered_security_types"])
        self.assertFalse(r["pq_footer_row_count_not_equity_filtered"])
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

    def test_bounded_5min_date_window_skips_nonoverlap_groups(self):
        self.write_h5("5min","sh","SH600000",[
            (202501020935,100,100), (202501030935,120,200),
            (202501060935,130,300)
        ])
        self.other_markets("5min")
        self.fake_parquet("5min",2025,[
            (self.epoch_ms("202501020930"),"600000.XSHG",10,10,10,10,100,100000),
            (self.epoch_ms("202501030930"),"600000.XSHG",10,10,10,10,120,200000),
            (self.epoch_ms("202501060930"),"600000.XSHG",10,10,10,10,130,300000)
        ])
        with self.fake_arrow():
            r=M.reconcile_section(self.root,self.scratch,"5min",2025,512,
                                  "a-share-candidate","2025-01-06","2025-01-06")
        self.assertEqual(r["h5_rows"],1)
        self.assertEqual(r["pq_rows"],1)
        self.assertEqual(r["matched_keys"],1)
        self.assertEqual(r["h5_only_rows"],0)
        self.assertEqual(r["pq_only_rows"],0)
        self.assertEqual(r["pq_row_groups_total"],2)
        self.assertEqual(r["pq_row_groups_read"],1)
        self.assertEqual(r["pq_row_groups_skipped_by_time"],1)
        self.assertEqual(r["from_date"],"2025-01-06")
        self.assertTrue(r["scan_complete"])

    def test_bounded_window_empty_h5_scans_exact_parquet_keys_not_footer(self):
        self.write_h5("5min","sh","SH600000",[(202501020935,100,100)])
        self.other_markets("5min")
        self.fake_parquet("5min",2025,[
            (self.epoch_ms("202501020930"),"600000.XSHG",10,10,10,10,100,100000),
            (self.epoch_ms("202501030930"),"600000.XSHG",10,10,10,10,120,200000)
        ])
        with self.fake_arrow():
            r=M.reconcile_section(self.root,self.scratch,"5min",2025,512,
                                  "a-share-candidate","2025-01-03","2025-01-03")
        self.assertEqual(r["h5_rows"],0)
        self.assertEqual(r["pq_only_rows"],1)
        self.assertFalse(r["pq_year_metadata_only_no_h5_rows"])
        self.assertFalse(r["pq_footer_contains_unfiltered_security_types"])
        self.assertFalse(r["pq_footer_row_count_not_equity_filtered"])
        self.assertEqual(r["pq_only_examples"][0]["bar_end"],"202501030935")
        self.assertEqual(r["pq_rows"],1)

    def test_cross_arrow_batch_and_within_batch_parquet_duplicates_flagged(self):
        """One vendor time key can recur in later batches/RowGroups."""
        db=M.db_open(self.dir/"cross-batch-join.sqlite")
        try:
            db.execute(
                "INSERT INTO h(s,t,o,hi,lo,c,v,a) VALUES(?,?,?,?,?,?,?,?)",
                ("SH600000",202509300935,10,10,10,10,100,1000))
            stats=M.Counter({"period":"5min"})
            same=("SH600000",202509300935,10,10,10,10,100,1000)
            extra=("SZ000636",202509300940,10,10,10,10,100,1000)
            M.check_batch(db,[same,extra],stats,"5min")
            # One duplicate inside the next batch, another across batches;
            # neither increases matched/only counts.
            M.check_batch(db,[same,same,extra],stats,"5min")
            self.assertEqual(stats["pq_unique_keys"],2)
            self.assertEqual(stats["matched_keys"],1)
            self.assertEqual(stats["pq_only_rows"],1)
            self.assertEqual(stats["pq_duplicate_keys_within_batch"],1)
            self.assertEqual(stats["pq_duplicate_keys_across_batches"],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM pq_seen").fetchone()[0],2)
        finally:
            db.close()

    def test_bounded_multi_day_report_has_exact_daily_overlap_and_two_way_gaps(self):
        """One bounded scan returns per-day counts, not only mismatch days."""
        self.write_h5("5min","sh","SH600000",[
            (202509260935,100,100),
            (202509290935,100,100),
            (202509300935,100,100),
            (202509300940,100,100)])
        self.other_markets("5min")
        self.fake_parquet("5min",2025,[
            (self.epoch_ms("202509260930"),"600000.XSHG",10,10,10,10,100,100000),
            (self.epoch_ms("202509290930"),"600000.XSHG",10,10,10,10,100,100000),
            (self.epoch_ms("202509300930"),"600000.XSHG",10,10,10,10,100,100000),
            (self.epoch_ms("202509300945"),"600000.XSHG",10,10,10,10,100,100000)])
        with self.fake_arrow():
            report=M.reconcile_section(self.root,self.scratch,"5min",2025,512,
                                       "a-share-candidate","2025-09-26","2025-09-30")
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["pq_unique_keys"],4)
        self.assertEqual(report["h5_rows"],4)
        self.assertEqual(report["matched_keys"],3)
        self.assertEqual(report["h5_only_rows"],1)
        self.assertEqual(report["pq_only_rows"],1)
        self.assertEqual(report["by_day"]["20250926"]["matched"],1)
        self.assertEqual(report["by_day"]["20250929"]["h5_unique"],1)
        self.assertEqual(report["by_day"]["20250930"]["intersection_unique"],1)
        self.assertEqual(report["by_day"]["20250930"]["h5_only"],1)
        self.assertEqual(report["by_day"]["20250930"]["pq_only"],1)
        self.assertEqual(report["by_day"]["20250930"]["union_candidate_unique"],3)
        self.assertEqual(report["by_day"]["20250930"]["overlap_value_mismatch_pct"],0)
        self.assertTrue(report["parquet_key_coverage_exact_when_scan_complete"])
        self.assertFalse(report["duplicate_keys_across_batches_not_exhaustively_checked"])

    def test_stock_day_source_gaps_separate_full_absence_and_partial_bars(self):
        """A missing H5 stock-day is not the same as a missing intraday bar."""
        self.write_h5("5min","sh","SH600000",[
            (202509300935,100,100),
            (202509300940,100,100)])
        self.other_markets("5min")
        self.fake_parquet("5min",2025,[
            (self.epoch_ms("202509300930"),"600000.XSHG",10,10,10,10,100,100000),
            (self.epoch_ms("202509300940"),"600000.XSHG",10,10,10,10,100,100000),
            (self.epoch_ms("202509300930"),"300747.XSHE",10,10,10,10,100,100000),
            (self.epoch_ms("202509300935"),"300747.XSHE",10,10,10,10,100,100000)])
        with self.fake_arrow():
            report=M.reconcile_section(self.root,self.scratch,"5min",2025,512,
                                       "a-share-candidate","2025-09-30","2025-09-30")
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["matched_keys"],1)
        self.assertEqual(report["pq_only_rows"],3)
        self.assertEqual(report["h5_only_rows"],1)
        summary=report["stock_day_gap_summary"]
        self.assertEqual(summary["candidate_stock_days_in_either_source"],2)
        self.assertEqual(summary["pq_only_full_h5_absence_stock_days"],1)
        self.assertEqual(summary["pq_only_partial_h5_coverage_stock_days"],1)
        self.assertEqual(summary["pq_only_keys_on_full_h5_absence_days"],2)
        self.assertEqual(summary["pq_only_keys_on_partial_h5_coverage_days"],1)
        self.assertEqual(summary["h5_only_partial_pq_coverage_stock_days"],1)
        self.assertEqual(summary["h5_only_keys_on_partial_pq_coverage_days"],1)
        self.assertEqual(summary["examples_full_h5_absence"][0]["symbol"],"SZ300747")
        day=report["by_day"]["20250930"]
        self.assertEqual(day["pq_only_keys_on_full_h5_absence_days"],2)
        self.assertEqual(day["pq_only_keys_on_partial_h5_coverage_days"],1)
        self.assertEqual(report["by_code_prefix_group"]
                         ["SZ_300_301_prefix"]["pq_only"],2)
        self.assertEqual(report["by_code_prefix_group"]
                         ["SH_other_prefix"]["matched"],1)
        self.assertFalse(report["board_membership_certified"])
        self.assertTrue(summary["source_key_gap_does_not_certify_missing_trades"])

    def test_prefix_mismatch_rate_does_not_count_unique_as_matched(self):
        """Group percentages use ONLY source-overlap time keys."""
        db=M.db_open(self.dir/"prefix-aggregate.sqlite")
        try:
            db.executemany(
                "INSERT INTO h(s,t,o,hi,lo,c,v,a) VALUES(?,?,?,?,?,?,?,?)",
                [("SH688001",202509300935,10,10,10,10,100,1000),
                 ("SH688001",202509300940,10,10,10,10,100,1000)])
            counts=M.Counter({"period":"5min"})
            M.check_batch(db,[
                ("SH688001",202509300935,10.05,10,10,10,100,1000),
                ("SH688001",202509300945,10,10,10,10,100,1000)],
                counts,"5min")
            self.assertEqual(counts["matched_keys"],1)
            self.assertEqual(counts["value_mismatch_rows"],1)
            grp=counts["by_code_prefix_group"]["SH_688_689_prefix"]
            self.assertEqual(grp["matched"],1)
            self.assertEqual(grp["value_mismatch"],1)
            self.assertEqual(grp["pq_only"],1)
            self.assertEqual(grp["price_mismatch"],1)
            self.assertEqual(M.symbol_prefix_group("BJ920680"),"BJ_prefix")
        finally:
            db.close()

    def test_markdown_includes_daily_gaps_and_code_prefix_sections(self):
        section={
            "period":"5min","year":2025,"scan_complete":True,"issues":[],
            "h5_rows":1,"pq_rows":2,"matched_keys":1,
            "h5_only_rows":0,"pq_only_rows":1,"value_mismatch_rows":0,
            "by_day":{"20250930":{
                "h5_unique":1,"parquet_unique":2,"intersection_unique":1,
                "pq_only":1,"overlap_value_mismatch_pct":0.0}},
            "stock_day_gap_summary":{
                "pq_only_full_h5_absence_stock_days":1,
                "pq_only_keys_on_full_h5_absence_days":1,
                "pq_only_partial_h5_coverage_stock_days":0,
                "pq_only_keys_on_partial_h5_coverage_days":0,
                "h5_only_full_pq_absence_stock_days":0,
                "h5_only_keys_on_full_pq_absence_days":0,
                "h5_only_partial_pq_coverage_stock_days":0,
                "h5_only_keys_on_partial_pq_coverage_days":0,
                "examples_full_h5_absence":[
                    {"symbol":"SH603056","day":"20250930","parquet_only_keys":1}]},
            "by_code_prefix_group":{
                "SH_other_prefix":{"matched":1,"value_mismatch":0,
                                   "pq_only":1}}
        }
        markdown=M.render_markdown({
            "status":"complete","universe_mode":"a-share-candidate",
            "requested_periods":["5min"],"results":{"5min/2025":section}})
        self.assertIn("逐日双源交集与量价冲突",markdown)
        self.assertIn("证券—交易日缺口归因",markdown)
        self.assertIn("代码前缀分组量价差异",markdown)
        self.assertIn("SH603056@20250930(1根)",markdown)
        self.assertIn("H5整只证券该日无键",markdown)

    def test_5min_quantity_ratio_is_separate_for_volume_and_amount(self):
        """Synthetic 100x volume, 1000x amount and one-sided zeros."""
        stats = M.Counter({
            "period": "5min",
            "from_date": "2026-09-29",
            "to_date": "2026-09-29"
        })
        day = {}
        symbol = "SH600000"
        same = (10, 10, 10, 10, 100, 1000)
        cases = (
            # p, h, actual old-tolerance field names
            (same, same, []),
            ((10,10,10,10,10000,1000), same, ["volume"]),
            ((10,10,10,10,100,1000000), same, ["amount"]),
            ((10,10,10,10,0,0), same, ["volume","amount"]),
            ((10,10,10,10,10050,1000),
             (10,10,10,10,10000,1000), ["volume"]),
        )
        for i, (p,h,different) in enumerate(cases):
            M.record_bounded_5min_quantity_evidence(
                stats,symbol,202609290935+i*5,p,h,different,day)
        summary=stats["quantity_scale_diagnostics"]
        categories=summary["quantity_pair_categories"]
        self.assertEqual(categories, {
            "neither":1,"volume_only":2,"amount_only":1,"both":1})
        self.assertEqual(summary["fields"]["volume"]["compared"],5)
        self.assertEqual(summary["fields"]["volume"]["different_by_existing_tolerance"],3)
        self.assertEqual(summary["fields"]["volume"]["one_zero"],1)
        vratio=summary["fields"]["volume"][
            "parquet_divided_by_h5_near_factor_within_1pct"]
        self.assertEqual(vratio["100"],1)
        self.assertEqual(vratio["1"],3)
        aratio=summary["fields"]["amount"][
            "parquet_divided_by_h5_near_factor_within_1pct"]
        self.assertEqual(aratio["1000"],1)
        self.assertEqual(summary["fields"]["amount"]["one_zero"],1)
        self.assertEqual(day["volume_mismatch"],3)
        self.assertEqual(day["amount_mismatch"],2)
        self.assertFalse(summary["inferred_unit_conversion_certified"])

    def test_quantity_diagnostic_matched_keys_only_and_nonmatching_report(self):
        """Parquet-only keys must not dilute the overlap scaling denominator."""
        db=M.db_open(self.dir/"quantity-test.sqlite")
        try:
            db.execute(
                "INSERT INTO h(s,t,o,hi,lo,c,v,a) VALUES(?,?,?,?,?,?,?,?)",
                ("SH600000",202609290935,10,10,10,10,100,1000))
            stats=M.Counter({
                "period":"5min","year":2026,
                "from_date":"2026-09-29","to_date":"2026-09-29"})
            M.check_batch(db,[
                ("SH600000",202609290935,10,10,10,10,10000,1000000),
                ("SZ000001",202609290935,10,10,10,10,10,10),
            ],stats,"5min")
            q=stats["quantity_scale_diagnostics"]
            self.assertEqual(stats["matched_keys"],1)
            self.assertEqual(stats["pq_only_rows"],1)
            self.assertEqual(stats["quantity_mismatch_rows"],1)
            self.assertEqual(q["fields"]["volume"]["compared"],1)
            self.assertEqual(q["fields"]["amount"]["compared"],1)
            self.assertEqual(q["quantity_pair_categories"]["both"],1)
            self.assertEqual(q["fields"]["volume"][
                "parquet_divided_by_h5_near_factor_within_1pct"]["100"],1)
            self.assertEqual(q["fields"]["amount"][
                "parquet_divided_by_h5_near_factor_within_1pct"]["1000"],1)
            self.assertEqual(stats["by_day"]["20260929"]["volume_mismatch"],1)
            self.assertEqual(stats["by_day"]["20260929"]["amount_mismatch"],1)
            self.assertEqual(stats["by_code_prefix_group"]
                             ["SH_other_prefix"]["volume_mismatch"],1)
        finally:
            db.close()

    def test_old_day_reconciliation_does_not_emit_five_minute_unit_theory(self):
        """Daily historical tests preserve previous output and flags."""
        db=M.db_open(self.dir/"quantity-day.sqlite")
        try:
            db.execute(
                "INSERT INTO h(s,t,o,hi,lo,c,v,a) VALUES(?,?,?,?,?,?,?,?)",
                ("SH600000",202609290000,10,10,10,10,100,1000))
            stats=M.Counter({"period":"day"})
            M.check_batch(db,[
                ("SH600000",202609290000,10,10,10,10,10000,1000000)
            ],stats,"day")
            self.assertEqual(stats["quantity_mismatch_rows"],1)
            self.assertNotIn("quantity_scale_diagnostics",stats)
        finally:
            db.close()

    def test_quantity_diagnostic_markdown_is_aggregate_only(self):
        section={
            "period":"5min","year":2026,"scan_complete":True,"issues":[],
            "h5_rows":1,"pq_rows":1,"matched_keys":1,
            "h5_only_rows":0,"pq_only_rows":0,"value_mismatch_rows":1,
            "quantity_scale_diagnostics":{
                "quantity_pair_categories":{
                    "neither":0,"volume_only":0,"amount_only":0,"both":1},
                "fields":{
                    "volume":{
                        "different_by_existing_tolerance":1,
                        "both_zero":0,"one_zero":0,"both_nonzero":1,
                        "parquet_divided_by_h5_near_factor_within_1pct":{
                            "1":0,"100":1,"other":0},
                        "relative_difference_bands_on_nonzero":{
                            "above_5pct":1}
                    },
                    "amount":{
                        "different_by_existing_tolerance":1,
                        "both_zero":0,"one_zero":0,"both_nonzero":1,
                        "parquet_divided_by_h5_near_factor_within_1pct":{
                            "1":0,"1000":1,"other":0},
                        "relative_difference_bands_on_nonzero":{
                            "above_5pct":1}
                    }
                }
            }
        }
        text=M.render_markdown({
            "status":"complete","universe_mode":"a-share-candidate",
            "requested_periods":["5min"],"results":{"5min/2026":section}})
        self.assertIn("成交量/成交额口径诊断",text)
        self.assertIn("Parquet/H5候选倍率",text)
        self.assertIn("100倍=1",text)
        self.assertIn("1000倍=1",text)
        self.assertNotIn("OHLCV原始值",text)

    def test_volume_x100_candidate_reconciles_and_can_make_legacy_match_worse(self):
        """Candidate remains separate; it must not erase remaining conflicts."""
        db=M.db_open(self.dir/"volume100-parallel.sqlite")
        try:
            hvals=[
                ("SH600000",202609290935,10,10,10,10,100,1000),
                ("SH600000",202609290940,10,10,10,10,100,1000),
                ("SH600000",202609290945,10,10,10,10,100,1000),
                ("SH600000",202609290950,10,10,10,10,0,0),
                ("SH600000",202609290955,10,10,10,10,100,1000),
                ("SH600000",202609291000,10,10,10,10,100,1000),
            ]
            db.executemany(
                "INSERT INTO h(s,t,o,hi,lo,c,v,a) VALUES(?,?,?,?,?,?,?,?)",
                hvals)
            pvals=[
                ("SH600000",202609290935,10,10,10,10,10000,1000),
                ("SH600000",202609290940,10,10,10,10,12000,1000),
                ("SH600000",202609290945,10,10,10,10,100,1000),
                ("SH600000",202609290950,10,10,10,10,0,0),
                ("SH600000",202609290955,10,10,10,10,10000,2000000),
                ("SH600000",202609291000,10.02,10,10,10,10000,1000),
                ("SZ000001",202609290935,10,10,10,10,10000,1000),
            ]
            stats=M.Counter({
                "period":"5min","from_date":"2026-09-29",
                "to_date":"2026-09-29"})
            M.check_batch(db,pvals,stats,"5min")
            c=stats["quantity_scale_diagnostics"]["h5_volume_times_100_candidate"]
            self.assertEqual(stats["matched_keys"],6)
            self.assertEqual(stats["pq_only_rows"],1)
            self.assertEqual(stats["quantity_mismatch_rows"],4)
            self.assertEqual(stats["price_mismatch_rows"],1)
            self.assertEqual(stats["value_mismatch_rows"],4)
            self.assertEqual(c["compared_overlap_keys"],6)
            self.assertEqual(c["legacy_volume_mismatch"],4)
            self.assertEqual(c["candidate_volume_mismatch"],2)
            self.assertEqual(c["legacy_mismatch_resolved_by_candidate"],3)
            self.assertEqual(c["legacy_match_broken_by_candidate"],1)
            self.assertEqual(
                c["candidate_value_mismatch_with_original_price_and_amount_rules"],4)
            self.assertEqual(c["candidate_volume_mismatch_by_day"],{"20260929":2})
            self.assertFalse(c["factor_certified"])
            self.assertFalse(c["source_values_modified"])
            # Exact source rows in scratch remain unchanged, candidate never
            # touches persisted source or temporary matching tables.
            self.assertEqual(
                db.execute("SELECT v FROM h WHERE t=202609290935").fetchone()[0],100)
            self.assertEqual(
                db.execute("SELECT v FROM p WHERE t=202609290935").fetchone()[0],10000)
        finally:
            db.close()

    def test_volume_x100_candidate_only_on_matched_bounded_5min(self):
        stats=M.Counter({
            "period":"5min", "from_date":"2026-09-29",
            "to_date":"2026-09-29"})
        db=M.db_open(self.dir/"volume100-only-pq.sqlite")
        try:
            M.check_batch(db,[
                ("SH600000",202609290935,10,10,10,10,10000,1000)
            ],stats,"5min")
            self.assertEqual(stats["pq_only_rows"],1)
            self.assertNotIn("quantity_scale_diagnostics",stats)
            day=M.Counter({"period":"day","from_date":"2026-09-29"})
            M.record_bounded_5min_quantity_evidence(
                day,"SH600000",202609290935,
                (10,10,10,10,10000,1000),(10,10,10,10,100,1000),
                ["volume"],{})
            self.assertNotIn("quantity_scale_diagnostics",day)
        finally:
            db.close()

    def test_volume_x100_candidate_markdown_preserves_original_counts(self):
        section={
            "period":"5min","year":2026,"scan_complete":True,"issues":[],
            "h5_rows":1,"pq_rows":1,"matched_keys":1,
            "h5_only_rows":0,"pq_only_rows":0,"value_mismatch_rows":1,
            "quantity_scale_diagnostics":{
                "quantity_pair_categories":{
                    "neither":0,"volume_only":1,"amount_only":0,"both":0},
                "fields":{
                    "volume":{
                        "different_by_existing_tolerance":1,
                        "both_zero":0,"one_zero":0,"both_nonzero":1,
                        "parquet_divided_by_h5_near_factor_within_1pct":{"100":1},
                        "relative_difference_bands_on_nonzero":{"above_5pct":1}
                    },
                    "amount":{
                        "different_by_existing_tolerance":0,
                        "both_zero":0,"one_zero":0,"both_nonzero":1,
                        "parquet_divided_by_h5_near_factor_within_1pct":{"1":1},
                        "relative_difference_bands_on_nonzero":{"<=0.01pct":1}
                    }
                },
                "h5_volume_times_100_candidate":{
                    "compared_overlap_keys":1,
                    "legacy_volume_mismatch":1,
                    "candidate_volume_mismatch":0,
                    "legacy_mismatch_resolved_by_candidate":1,
                    "legacy_match_broken_by_candidate":0,
                    "candidate_value_mismatch_with_original_price_and_amount_rules":0,
                    "factor_certified":False
                }
            }
        }
        out=M.render_markdown({
            "status":"complete","universe_mode":"a-share-candidate",
            "requested_periods":["5min"],"results":{"5min/2026":section}})
        self.assertIn("H5五分钟成交量×100候选映射",out)
        self.assertIn("原口径成交量冲突 | 1",out)
        self.assertIn("H5成交量×100后冲突 | 0",out)
        self.assertIn("量价差异",out)
        self.assertIn("不能",out)

    def test_date_bounded_resume_fingerprint_and_invalid_ranges(self):
        self.write_h5("day","sh","SH600000",[(202501020000,100,100)])
        self.other_markets("day")
        with self.fake_arrow():
            report=M.run(self.root,self.out,self.scratch,[2025],["day"],512,False,
                         "a-share-candidate","2025-01-02","2025-01-02")
            again=M.run(self.root,self.out,self.scratch,[2025],["day"],512,True,
                        "a-share-candidate","2025-01-02","2025-01-02")
        self.assertEqual(again,report)
        with self.assertRaisesRegex(ValueError,"Resume date window"):
            M.run(self.root,self.out,self.scratch,[2025],["day"],512,True,
                  "a-share-candidate","2025-01-03","2025-01-03")
        with self.assertRaisesRegex(ValueError,"exactly one"):
            M.run(self.root,self.dir/"other.json",self.scratch,[2025,2026],["day"],
                  512,False,"a-share-candidate","2025-01-02","2025-01-02")
        with self.assertRaises(ValueError):
            M.parse_day_range(2025,"2026-01-01","2026-01-01")
        with self.assertRaises(ValueError):
            M.parse_day_range(2025,"2025-01-04","2025-01-03")

    def test_full_year_minute_cli_requires_explicit_opt_in(self):
        module=self.dir/"AStockDataTools"/"H5ParquetReconciler"
        module.mkdir(parents=True)
        with patch.object(M,"MODULE_DIR",module):
            with self.assertRaises(SystemExit):
                M.main([str(self.root),"--years","2025","--periods","5min",
                        "--universe","a-share-candidate","--read-only"])
        self.assertFalse((module/"reports").exists())

    def test_5min_start_time_and_bj_aliases(self):
        self.assertEqual(M.pq_stamp(self.epoch_ms("202607161410"), "5min"), 202607161415)
        self.assertEqual(M.symbol_id("920000.XBSE"), "BJ920000")
        self.assertIsNone(M.symbol_id("not_a_ticker"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
