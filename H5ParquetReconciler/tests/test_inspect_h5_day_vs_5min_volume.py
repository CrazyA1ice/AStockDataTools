"""Synthetic-only tests for H5 day vs 5min volume candidate conservation."""
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import h5py
import numpy as np

SRC = (Path(__file__).resolve().parents[1] / "tools" /
       "inspect-h5-day-vs-5min-volume.py")
SPEC = importlib.util.spec_from_file_location("h5_cross_volume", SRC)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
DTYPE = np.dtype([("datetime", "<u8"), ("transCount", "<u8"),
                  ("openPrice", "<i4"), ("transAmount", "<u8")])


class H5CrossCycleVolumeTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name) / "stock"
        (self.root / "HikyuuData").mkdir(parents=True)
        self.markets = {
            market: {period: {} for period in ("day", "5min")}
            for market in ("sh", "sz", "bj")
        }

    def write(self, symbol, period, stamps_and_volume):
        self.markets[symbol[:2].lower()][period][symbol] = stamps_and_volume

    def flush(self):
        for market, periods in self.markets.items():
            for period, symbols in periods.items():
                path = self.root / "HikyuuData" / (market + "_" + period + ".h5")
                with h5py.File(path, "w") as f:
                    g = f.create_group("data")
                    for symbol, data in symbols.items():
                        arr = np.zeros(len(data), dtype=DTYPE)
                        arr["datetime"] = [stamp for stamp, _ in data]
                        arr["transCount"] = [v for _, v in data]
                        arr["openPrice"] = 10000
                        arr["transAmount"] = 1
                        g.create_dataset(symbol, data=arr)

    def bars(self, day, quantity=100):
        times = sorted(M.REGULAR_FIVE_MINUTE_ENDS)
        amounts = [2] * 47 + [quantity - 94]
        return [(day * 10000 + t, q) for t, q in zip(times, amounts)]

    def test_regular_end_labels_exactly_48(self):
        self.assertEqual(len(M.REGULAR_FIVE_MINUTE_ENDS), 48)
        self.assertIn(935, M.REGULAR_FIVE_MINUTE_ENDS)
        self.assertIn(1130, M.REGULAR_FIVE_MINUTE_ENDS)
        self.assertIn(1305, M.REGULAR_FIVE_MINUTE_ENDS)
        self.assertIn(1500, M.REGULAR_FIVE_MINUTE_ENDS)
        self.assertNotIn(1300, M.REGULAR_FIVE_MINUTE_ENDS)

    def test_day_and_minute_candidate_vs_baseline(self):
        self.write("SH600000", "day", [(202609240000, 100)])
        self.write("SH600000", "5min", self.bars(20260924, 100))
        self.flush()
        r = M.make_report(self.root, 2026, "2026-09-24", "2026-09-24")
        t = r["totals"]
        self.assertEqual(t["stock_days_with_both_cycles"], 1)
        self.assertEqual(t["complete_48_bar_stock_days_compared"], 1)
        self.assertEqual(t["baseline_day_minute_volume_agree_0_1pct"], 0)
        self.assertEqual(t["candidate_day_minute_volume_agree_0_1pct"], 1)
        self.assertEqual(t["h5_raw_daily_equals_sum_minute_raw_exact"], 1)
        self.assertEqual(t["day_minute_raw_mismatch_above_0_1pct"], 0)
        self.assertTrue(r["scan_complete"])
        self.assertFalse(r["unit_mapping_certified"])
        self.assertFalse(r["safe_to_automatically_union"])
        self.assertFalse(r["does_not_validate_parquet_units"] is False)
        self.assertNotIn("10000", str(r))
        self.assertEqual(r["by_day"]["20260924"]["complete_48_bar_stock_days_compared"],1)

    def test_incomplete_noon_and_missing_cycle_are_not_false_matches(self):
        self.write("SH600000", "day", [(202609240000, 100)])
        self.write("SH600000", "5min", self.bars(20260924,100) + [(202609241300, 0)])
        self.write("SZ300001", "day", [(202609240000, 60)])
        self.write("BJ920025", "5min", self.bars(20260924, 100))
        self.flush()
        r = M.make_report(self.root, 2026, "2026-09-24", "2026-09-24")
        t = r["totals"]
        self.assertEqual(t["candidate_stock_days_either_cycle"],3)
        self.assertEqual(t["stock_days_with_both_cycles"],1)
        self.assertEqual(t["stock_days_only_day"],1)
        self.assertEqual(t["stock_days_only_minute"],1)
        self.assertEqual(t["five_minute_session_not_48_exact"],1)
        self.assertEqual(t.get("complete_48_bar_stock_days_compared",0),0)
        self.assertEqual(t.get("candidate_day_minute_volume_agree_0_1pct",0),0)

    def test_candidate_explicitly_rejects_nonconserving_sum(self):
        self.write("SH600000", "day", [(202609240000,100)])
        self.write("SH600000", "5min", self.bars(20260924,110))
        self.flush()
        r = M.make_report(self.root, 2026, "2026-09-24", "2026-09-24")
        t = r["totals"]
        self.assertEqual(t["complete_48_bar_stock_days_compared"],1)
        self.assertEqual(t["candidate_day_minute_volume_agree_0_1pct"],0)
        self.assertEqual(t["day_minute_raw_mismatch_above_0_1pct"],1)
        self.assertEqual(t["h5_raw_daily_equals_sum_minute_raw_exact"],0)

    def test_only_code_prefix_candidate_datasets_counted(self):
        self.write("SH000001", "day", [(202609240000, 100)])
        self.write("SH000001", "5min", self.bars(20260924,100))
        self.write("SH600000", "day", [(202609240000, 100)])
        self.write("SH600000", "5min", self.bars(20260924,100))
        self.flush()
        r = M.make_report(self.root,2026,"2026-09-24","2026-09-24")
        self.assertEqual(r["totals"]["candidate_stock_days_either_cycle"],1)

    def test_refuse_missing_market_file(self):
        self.write("SH600000", "day",[(202609240000, 100)])
        self.write("SH600000", "5min",self.bars(20260924,100))
        self.flush()
        (self.root/"HikyuuData"/"bj_5min.h5").unlink()
        with self.assertRaisesRegex(ValueError,"Missing or symlinked H5"):
            M.make_report(self.root,2026,"2026-09-24","2026-09-24")


if __name__ == "__main__":
    unittest.main(verbosity=2)
