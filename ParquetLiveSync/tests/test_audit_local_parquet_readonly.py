"""Isolated offline tests: never touch real D:/stock, QMT or scheduled tasks."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

import audit_local_parquet_readonly as A
import local_layout as L


UTC8 = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 17, 21, 45, tzinfo=UTC8)


def market_shard(path, date, *, stats=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = int(datetime(date.year, date.month, date.day, 15, 0,
                      tzinfo=UTC8).timestamp() * 1000)
    frame = pa.table({
        "ts": pa.array([ts], type=pa.int64()),
        "symbol": pa.array(["SH600000"], type=pa.string()),
        **{c: pa.array([1.0], type=pa.float64()) for c in L.COLS[2:]},
    })
    pq.write_table(frame, path, write_statistics=stats)


def simple_snapshot(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"asof": ["2026-11-17"],
                             "symbol": ["600000.SH"]}), path)


class LocalParquetAuditTests(unittest.TestCase):
    def fixture(self, directory):
        stock = Path(directory) / "stock"
        root = stock / "AllCycleAStockData"
        for name in L.PERIODS:
            latest = (datetime(2026, 11, 13) if name == "week"
                      else datetime(2026, 10, 31) if name == "month"
                      else datetime(2026, 11, 17))
            market_shard(root / name / "2026-11.parquet", latest.date())
        work = Path(directory) / "work"
        (work / "market_update").mkdir(parents=True)
        (work / "qmt_extra").mkdir(parents=True)
        (work / "market_update" / "commits.json").write_text(
            json.dumps({"periods": {"1min": {
                "2026-11": {"days": ["2026-11-16", "2026-11-17"]}}}}),
            encoding="utf-8")
        (work / "qmt_extra" / "financial-cache-progress.json").write_text(
            json.dumps({"daily_date": "2026-11-17",
                        "daily_sweep_reached_end": False,
                        "daily_cursor": "000001.SZ",
                        "pending": {"000001.SZ": {"reason": "SOURCE_HISTORY_CONFLICT"}}}),
            encoding="utf-8")
        return stock, work

    def test_eight_market_folders_current_but_hist_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            stock, work = self.fixture(tmp)
            report = A.audit(stock, work, NOW)
            self.assertTrue(report["read_only"])
            self.assertTrue(report["all_eight_files_exist"])
            self.assertEqual(report["market"]["periods"]["day"]["latest_bar_date"],
                             "2026-11-17")
            self.assertEqual(report["equity_periods_not_proven_current"], [])
            self.assertEqual(report["market"]["periods"]["week"]["date_check"],
                             "CLOSED_PERIOD_LABEL_REQUIRES_RULE_AUDIT")
            self.assertIn("2011.parquet",
                          report["market"]["periods"]["1min"]["missing_prior_years"])
            self.assertFalse(report["completeness_certified"])
            self.assertEqual(report["private_progress"]["financial_pending_count"], 1)
            self.assertFalse(report["private_progress"]["financial_daily_sweep_reached_end"])

    def test_supplementary_nine_tables_and_snapshot_latest_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            stock, work = self.fixture(tmp)
            base = stock / "AllCycleAStockData" / "qmt_extra"
            simple_snapshot(base / "sectors" / "snapshots" /
                            "2026-11-17-abcdef1234567890.parquet")
            simple_snapshot(base / "adjustments" / "600000.SH" / "snapshots" /
                            "2026-11-17-abcdef1234567890.parquet")
            for table in A.FIN_TABLES:
                simple_snapshot(base / "financial" / table / "600000.SH" /
                                "snapshots" / "2026-11-16-abcdef1234567890.parquet")
            report = A.audit(stock, work, NOW)
            extra = report["qmt_extra"]
            self.assertEqual(extra["sectors"]["latest_asof"], "2026-11-17")
            self.assertEqual(extra["adjustments"]["securities_with_snapshots"], 1)
            self.assertEqual(extra["adjustments"]["observed_today_securities"], 1)
            self.assertEqual(len(extra["financial_nine_tables"]), 9)
            self.assertTrue(all(t["securities_with_snapshots"] == 1
                                for t in extra["financial_nine_tables"].values()))
            self.assertTrue(all(t["latest_observation_asof"] == "2026-11-16"
                                for t in extra["financial_nine_tables"].values()))

    def test_missing_ts_statistics_not_misreported_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            stock, work = self.fixture(tmp)
            market_shard(stock / "AllCycleAStockData" / "day" /
                         "2026-11.parquet", NOW.date(), stats=False)
            report = A.audit(stock, work, NOW)
            self.assertEqual(report["market"]["periods"]["day"]["date_check"],
                             "UNVERIFIED_FOOTER_TS")
            self.assertIn("day", report["equity_periods_not_proven_current"])

    def test_read_only_preserves_all_fixture_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            stock, work = self.fixture(tmp)
            before = {(str(f), f.stat().st_size) for f in Path(tmp).rglob("*")
                      if f.is_file()}
            A.audit(stock, work, NOW)
            after = {(str(f), f.stat().st_size) for f in Path(tmp).rglob("*")
                     if f.is_file()}
            self.assertEqual(before, after)

    def test_weekday_cutoff_and_weekend(self):
        self.assertEqual(A._expected_day(
            datetime(2026, 11, 17, 16, 29, tzinfo=UTC8)).isoformat(),
            "2026-11-16")
        self.assertEqual(A._expected_day(NOW).isoformat(), "2026-11-17")
        self.assertEqual(A._expected_day(
            datetime(2026, 11, 22, 18, 0, tzinfo=UTC8)).isoformat(),
            "2026-11-20")


if __name__ == "__main__":
    unittest.main()
