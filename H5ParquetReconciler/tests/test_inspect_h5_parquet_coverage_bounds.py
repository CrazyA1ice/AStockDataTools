"""Synthetic metadata-only tests for the two-source 5min window selector."""
import importlib.util
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import h5py
import numpy as np

SOURCE = (Path(__file__).resolve().parents[1] / "tools" /
          "inspect-h5-parquet-coverage-bounds.py")
SPEC = importlib.util.spec_from_file_location("inspect_5min_source_bounds", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
DTYPE = np.dtype([("datetime", "<u8"),
                  ("openPrice", "<i4"), ("closePrice", "<i4")])
ZONE = timezone(timedelta(hours=8))


def epoch_ms(stamp):
    return int(datetime.strptime(str(stamp), "%Y%m%d%H%M")
               .replace(tzinfo=ZONE).timestamp() * 1000)


def rg(lo, hi):
    stats = None if lo is None else types.SimpleNamespace(
        has_min_max=True, min=epoch_ms(lo), max=epoch_ms(hi))
    return types.SimpleNamespace(
        num_columns=1, num_rows=10,
        column=lambda idx: types.SimpleNamespace(
            path_in_schema="ts", statistics=stats))


class CoverageBoundsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "stock"
        self.h5 = self.root / "HikyuuData"
        self.pq = self.root / "AllCycleAStockData" / "5min"
        self.h5.mkdir(parents=True)
        self.pq.mkdir(parents=True)

    def write_h5(self, sym, stamps):
        fname = self.h5 / (sym[:2].lower() + "_5min.h5")
        if fname.exists():
            with h5py.File(fname, "a") as h5:
                group = h5["data"]
                data = np.zeros(len(stamps), dtype=DTYPE)
                data["datetime"] = stamps
                group.create_dataset(sym, data=data)
            return
        with h5py.File(fname, "w") as h5:
            group = h5.create_group("data")
            data = np.zeros(len(stamps), dtype=DTYPE)
            data["datetime"] = stamps
            group.create_dataset(sym, data=data)

    def markets_complete(self):
        for prefix in ("sh", "sz", "bj"):
            p = self.h5 / f"{prefix}_5min.h5"
            if not p.exists():
                with h5py.File(p, "w") as h5:
                    h5.create_group("data")

    def test_exact_h5_2026_year_edges_from_multiyear_dataset(self):
        self.write_h5("SH600000", [
            202501020935, 202609290935, 202609301500, 202701020935])
        self.markets_complete()
        info = M.inspect_h5(self.root, 2026)
        self.assertEqual(info["candidate_datasets_with_year_records"], 1)
        self.assertEqual(info["earliest_candidate_year_bar_end"], 202609290935)
        self.assertEqual(info["latest_candidate_year_bar_end"], 202609301500)
        self.assertEqual(info["last_record_month_dataset_counts"], {"202609": 1})
        self.assertEqual(info["missing_market_files"], [])

    def test_suggested_window_stops_at_earlier_source_latest(self):
        h = {"earliest_candidate_year_bar_end": 202609010935,
             "latest_candidate_year_bar_end": 202610151500,
             "missing_market_files": [], "invalid_candidate_datasets": 0}
        p = {"earliest_footer_candidate_bar_end": 202608010935,
             "latest_footer_candidate_bar_end": 202609301500,
             "groups_without_usable_ts_footer": 0}
        candidate = M.proposed_window(h, p, 2026)
        self.assertTrue(candidate["available"])
        self.assertEqual(candidate["to_date"], "2026-09-30")
        self.assertEqual(candidate["from_date"], "2026-09-24")
        self.assertFalse(candidate["proves_real_overlap"])

    def test_real_report_shape_suggests_h5_newer_2026_oct_frontier(self):
        h = {"earliest_candidate_year_bar_end": 202601050935,
             "latest_candidate_year_bar_end": 202610131500,
             "missing_market_files": [], "invalid_candidate_datasets": 0}
        p = {"files": 9,
             "earliest_footer_candidate_bar_end": 202601050935,
             "latest_footer_candidate_bar_end": 202609301500,
             "groups_without_usable_ts_footer": 0}
        window = M.proposed_h5_newer_window(h, p, 2026)
        self.assertTrue(window["available"])
        self.assertEqual(window["from_date"], "2026-10-07")
        self.assertEqual(window["to_date"], "2026-10-13")
        self.assertEqual(window["parquet_last_footer_candidate_date"],
                         "2026-09-30")
        self.assertFalse(window["proves_h5_only_keys"])
        self.assertEqual(M.proposed_window(h,p,2026)["to_date"],"2026-09-30")

    def test_newer_tail_is_false_when_h5_does_not_extend_after_parquet(self):
        h = {"earliest_candidate_year_bar_end": 202609010935,
             "latest_candidate_year_bar_end": 202609301500,
             "missing_market_files": [], "invalid_candidate_datasets": 0}
        p = {"files": 1, "latest_footer_candidate_bar_end": 202609301500,
             "groups_without_usable_ts_footer": 0}
        result = M.proposed_h5_newer_window(h,p,2026)
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"],"no_later_h5_date_envelope")
        h["latest_candidate_year_bar_end"] = 202609291500
        self.assertFalse(M.proposed_h5_newer_window(h,p,2026)["available"])

    def test_newer_frontier_guard_missing_h5_or_footer(self):
        h = {"earliest_candidate_year_bar_end": 202601050935,
             "latest_candidate_year_bar_end": 202610131500,
             "missing_market_files": [], "invalid_candidate_datasets": 0}
        p = {"files": 9,"latest_footer_candidate_bar_end": 202609301500,
             "groups_without_usable_ts_footer": 0}
        for changed in (
            {"missing_market_files": ["sz_5min.h5"]},
            {"invalid_candidate_datasets": 1},
        ):
            with self.subTest(changed=changed):
                self.assertFalse(M.proposed_h5_newer_window(
                    dict(h, **changed),p,2026)["available"])
        for changed in (
            {"groups_without_usable_ts_footer": 1},
            {"files": 0},
            {"latest_footer_candidate_bar_end": None},
        ):
            with self.subTest(changed=changed):
                self.assertFalse(M.proposed_h5_newer_window(
                    h,dict(p,**changed),2026)["available"])
        with self.assertRaisesRegex(ValueError,"Window limit"):
            M.proposed_h5_newer_window(h,p,2026,max_calendar_days=0)
        with self.assertRaisesRegex(ValueError,"Window limit"):
            M.proposed_h5_newer_window(h,p,2026,max_calendar_days=32)

    def test_unknown_footer_or_missing_market_fails_closed(self):
        h = {"earliest_candidate_year_bar_end": 202609010935,
             "latest_candidate_year_bar_end": 202609301500,
             "missing_market_files": [], "invalid_candidate_datasets": 0}
        p = {"earliest_footer_candidate_bar_end": 202609010935,
             "latest_footer_candidate_bar_end": 202609301500,
             "groups_without_usable_ts_footer": 1}
        self.assertFalse(M.proposed_window(h, p, 2026)["available"])
        p["groups_without_usable_ts_footer"] = 0
        h["missing_market_files"] = ["sz_5min.h5"]
        self.assertFalse(M.proposed_window(h, p, 2026)["available"])

    def test_parquet_footer_only_integration_produces_bounded_candidate(self):
        self.write_h5("SH600000", [
            202608030935, 202609300935, 202609301500])
        self.write_h5("SZ300747", [
            202608010935, 202609290935])
        self.markets_complete()
        path = self.pq / "2026.parquet"
        path.write_bytes(b"synthetic-footer-placeholder")
        row_groups = [rg("202609290930", "202609301455"),
                      rg("202609010930", "202609020935")]
        fake = types.ModuleType("pyarrow.parquet")
        class FakeParquet:
            def __init__(self, name):
                self.metadata = types.SimpleNamespace(
                    num_row_groups=len(row_groups),
                    row_group=lambda idx: row_groups[idx])
        fake.ParquetFile = FakeParquet
        pyarrow = types.ModuleType("pyarrow")
        pyarrow.__path__ = []
        pyarrow.parquet = fake
        with mock.patch.dict(sys.modules, {"pyarrow": pyarrow,
                                          "pyarrow.parquet": fake}):
            report = M.make_report(self.root, 2026)
        self.assertTrue(report["scan_complete_for_source_bounds"])
        self.assertEqual(report["parquet"]["files"], 1)
        self.assertEqual(report["parquet"]["row_groups_total"], 2)
        self.assertEqual(report["parquet"]["latest_footer_candidate_bar_end"],
                         202609301500)
        self.assertEqual(report["h5"]["latest_candidate_year_bar_end"],
                         202609301500)
        self.assertEqual(report["suggested_bounded_window"]["to_date"],
                         "2026-09-30")
        self.assertFalse(report["validates_exact_overlap_or_absence"])
        self.assertFalse(report["safe_to_automatically_union"])
        self.assertTrue(report["parquet"]["no_parquet_data_rows_read"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
