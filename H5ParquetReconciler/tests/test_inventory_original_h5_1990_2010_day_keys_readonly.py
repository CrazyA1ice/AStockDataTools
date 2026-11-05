"""Fictional Hikyuu daily H5 native-key history inventory contracts.

All test data are synthetic small HDF5 files under TemporaryDirectory.
No user's market files, real purchased bars, stock codes, or production IO.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "native_h5_early_daily_inventory_contract_tests",
    HERE.parent / "tools" /
    "inventory-original-h5-1990-2010-day-keys-readonly.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

DTYPE = np.dtype([
    ("datetime", "<i8"),
    ("openPrice", "<i8"), ("highPrice", "<i8"),
    ("lowPrice", "<i8"), ("closePrice", "<i8"),
    ("transCount", "<i8"), ("transAmount", "<i8"),
])


def stamp(date_str):
    return int(date_str.replace("-", "")) * 10000


class HistoricalDailyH5NativeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.market = self.root / "HikyuuData"
        self.market.mkdir()
        self.sources = {}
        for exchange in M.MARKETS:
            p = self.market / (exchange + "_day.h5")
            with h5py.File(p, "w") as fh:
                fh.create_group("data")
            self.sources[exchange] = p

    def put(self, exchange, symbol, dates):
        p = self.sources[exchange]
        with h5py.File(p, "a") as fh:
            group = fh["data"]
            arr = np.zeros(len(dates), dtype=DTYPE)
            arr["datetime"] = np.array(dates, dtype=np.int64)
            arr["openPrice"] = 10000
            arr["highPrice"] = 11000
            arr["lowPrice"] = 9000
            arr["closePrice"] = 10050
            arr["transCount"] = 100
            arr["transAmount"] = 1200
            group.create_dataset(symbol, data=arr)

    def test_h5_code_candidate_history_and_other_instrument_are_separate(self):
        self.put("sh", "SH600000", [
            stamp("1990-12-19"), stamp("1991-01-02"),
            stamp("2010-12-31"), stamp("2011-01-04")])
        self.put("sz", "SZ000001", [stamp("1991-01-02"),
                                    stamp("2009-12-31")])
        self.put("sh", "SH000001", [stamp("1991-01-02")])
        self.put("sh", "SH900901", [stamp("1992-01-02")])
        self.put("bj", "BJ430001", [stamp("2009-12-31")])
        before = {market: (p.stat().st_size, p.stat().st_mtime_ns)
                  for market, p in self.sources.items()}
        result = M.inventory(self.root, chunk_rows=1024)
        byyear = {row["year"]: row for row in result["annual_coverage"]}
        self.assertEqual(result["h5_a_share_code_candidate_stockdays_total"], 5)
        self.assertEqual(result["h5_other_code_stockdays_total"], 3)
        self.assertEqual(result["source_native_day_keys_projected"], 8)
        self.assertEqual(byyear[1991]["h5_a_share_code_candidate_stockdays"], 2)
        self.assertEqual(byyear[1991]["a_share_candidate_distinct_dates"], 1)
        self.assertEqual(byyear[1991]["h5_other_code_stockdays"], 1)
        self.assertEqual(byyear[2009]["other_code_stockdays_by_market"]["BJ"], 1)
        self.assertEqual(byyear[1990]["candidate_stockdays_by_market"]["SH"], 1)
        self.assertEqual(byyear[2010]["candidate_stockdays_by_market"]["SH"], 1)
        self.assertFalse(result["market_ohlcva_read"])
        self.assertFalse(result["purchased_parquet_pre2011_overlap_verified"])
        self.assertFalse(result["ready_to_merge_into_parquet"])
        self.assertFalse(result["source_security_codes_exported"])
        self.assertFalse(result["production_query_activated"])
        self.assertEqual(before, {market: (p.stat().st_size, p.stat().st_mtime_ns)
                                  for market, p in self.sources.items()})
        self.assertNotIn("SH600000", json.dumps(result))

    def test_empty_market_groups_do_not_fabricate_historical_stockdays(self):
        result = M.inventory(self.root)
        self.assertEqual(result["source_native_day_keys_projected"], 0)
        self.assertEqual(result["years_in_inventory"], 21)
        self.assertTrue(all(x["h5_a_share_code_candidate_stockdays"] == 0
                            for x in result["annual_coverage"]))

    def test_all_2011_and_later_native_keys_are_not_claimed_as_pre2011(self):
        self.put("sh", "SH600000", [stamp("2011-01-04"),
                                   stamp("2026-10-13")])
        summary = M.inventory(self.root)
        self.assertEqual(summary["source_native_day_keys_projected"], 0)
        self.assertEqual(summary["source_datasets_entirely_after_2010"], 1)

    def test_pre1990_source_is_flagged_without_inventing_coverage(self):
        self.put("sh", "SH600000", [stamp("1989-12-29"),
                                   stamp("1990-01-02")])
        summary = M.inventory(self.root)
        self.assertTrue(summary["source_has_keys_before_1990"])
        self.assertEqual(summary["h5_a_share_code_candidate_stockdays_total"], 1)

    def test_malformed_native_calendar_day_rejected(self):
        self.put("sh", "SH600000", [200002300000])
        with self.assertRaisesRegex(ValueError, "calendar date"):
            M.inventory(self.root)

    def test_non_midnight_native_daily_key_rejected(self):
        self.put("sh", "SH600000", [199901040930])
        with self.assertRaisesRegex(ValueError, "Non-midnight"):
            M.inventory(self.root)

    def test_unsorted_and_duplicate_native_day_keys_rejected(self):
        for vals in ([stamp("1992-01-02"), stamp("1992-01-02")],
                     [stamp("1992-01-03"), stamp("1992-01-02")]):
            with self.subTest(vals=vals), tempfile.TemporaryDirectory() as t:
                # The temporary test root avoids rebuilding user or fixture H5.
                new_root = Path(t)
                (new_root/"HikyuuData").mkdir()
                for market in M.MARKETS:
                    with h5py.File(new_root/"HikyuuData"/(market+"_day.h5"),"w") as f:
                        g=f.create_group("data")
                        if market=="sh":
                            a=np.zeros(len(vals),dtype=DTYPE)
                            a["datetime"]=vals
                            g.create_dataset("SH600000",data=a)
                with self.assertRaisesRegex(ValueError, "Duplicate or unsorted|descending"):
                    M.inventory(new_root)

    def test_float_native_datetime_rejected_before_any_key_cast(self):
        wrong = np.dtype([("datetime", "<f8"),
                          *DTYPE.descr[1:]])
        arr = np.zeros(1, dtype=wrong)
        arr["datetime"] = float(stamp("1990-12-19"))
        with h5py.File(self.sources["sh"], "a") as f:
            f["data"].create_dataset("SH600000", data=arr)
        with self.assertRaisesRegex(ValueError, "Nonintegral"):
            M.inventory(self.root)

    def test_scan_budget_fails_closed_without_partial_report(self):
        self.put("sh", "SH600000", [stamp("1990-01-02"),
                                   stamp("1990-01-03")])
        with self.assertRaisesRegex(ValueError, "budget exceeded"):
            M.inventory(self.root, max_rows=1)

    def test_missing_market_source_is_rejected(self):
        self.sources["bj"].unlink()
        with self.assertRaisesRegex(ValueError, "missing or symlinked"):
            M.inventory(self.root)

    def test_root_symlink_input_does_not_write_market_file(self):
        outside = self.root/"alt"
        outside.symlink_to(self.sources["sh"])
        # Source itself is a symlink -> fail closed.
        self.sources["sh"].unlink()
        self.sources["sh"].symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "missing or symlinked"):
            M.inventory(self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
