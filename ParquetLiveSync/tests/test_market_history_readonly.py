"""Fast synthetic regressions for SHA-bound five-cycle history audit.

Uses temporary Parquet only; no QMT requests or production market data.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
import sys

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import audit_market_history_readonly as A
import local_layout as L
import market_derived_cycles as D
import qmt_1m_pipeline as P


DAY = date(2026, 11, 18)
SYM = "SH600000"
CALIB = {"providers": {"SH_OTHER": {
    "category": "SH_OTHER", "offset_ms": 0,
    "volume": {"factor": 100.}, "amount": {"factor": 1.}
}}}
RULES = {period: {"timestamp_shift_from_1min_last_ms": 0}
         for period in D.PERIODS}


def minute_rows():
    output = []
    for hour, minute in sorted(P.GRID - {(9, 30)}):
        ts = int(datetime(DAY.year, DAY.month, DAY.day,
                          hour, minute, tzinfo=L.UTC8).timestamp() * 1000)
        output.append({"ts": ts, "symbol": SYM,
                       "open": 10., "high": 10., "low": 10.,
                       "close": 10., "volume": 100., "amount": 1000.})
    assert len(output) == 240
    return output


def reference():
    return {(A.day_number(DAY), SYM): {
        "open": 10., "high": 10., "low": 10., "close": 10.,
        "volume": 24000., "amount": 240000.}}


class MarketHistoryReadOnlyTests(unittest.TestCase):
    def test_bounded_months_and_day_number(self):
        self.assertEqual(A.months_between(date(2026, 10, 14), DAY),
                         ["2026-10", "2026-11"])
        self.assertEqual(A.day_number(DAY) + A.EPOCH_ORDINAL,
                         DAY.toordinal())

    def test_all_five_cycles_synthetic_reconcile(self):
        rows = minute_rows()
        baseline = {}
        results = A.Findings()
        with tempfile.TemporaryDirectory() as tmp:
            for period in A.PERIODS:
                if period == "1min":
                    physical = rows
                else:
                    physical = D.aggregate_stock_day(
                        rows, period, one_minute_offset_ms=0,
                        period_label_shift_ms=0)
                target = Path(tmp) / (period + ".parquet")
                pq.write_table(pa.Table.from_pylist(
                    physical, schema=P.PRIVATE_SCHEMA), target,
                    row_group_size=7)
                groups = A.scan_month(target, period, DAY, DAY, results)
                self.assertEqual(len(groups), 1)
                A.evaluate_groups(period, groups, reference(), CALIB, RULES,
                                  results, baseline)
        self.assertEqual(dict(results.counts), {})
        self.assertEqual(len(baseline), 1)
        self.assertEqual(results.per_period["60min"]["physical_stock_days"], 1)

    def test_quote_only_full_day_high_is_flagged_in_all_cycles(self):
        rows = minute_rows()
        rows[0].update({"open": 10.02, "high": 10.02,
                        "low": 10.02, "close": 10.02,
                        "volume": 0., "amount": 0.})
        results = A.Findings()
        baseline = {}
        with tempfile.TemporaryDirectory() as tmp:
            for period in A.PERIODS:
                physical = (rows if period == "1min" else
                            D.aggregate_stock_day(
                                rows, period, one_minute_offset_ms=0,
                                period_label_shift_ms=0))
                target = Path(tmp) / (period + ".parquet")
                pq.write_table(pa.Table.from_pylist(
                    physical, schema=P.PRIVATE_SCHEMA), target)
                groups = A.scan_month(target, period, DAY, DAY, results)
                A.evaluate_groups(period, groups, reference(), CALIB, RULES,
                                  results, baseline)
        for period in A.PERIODS:
            self.assertEqual(
                results.counts[period + ":PRICE_OUTSIDE_OFFICIAL_DAY"], 1)
        self.assertEqual(
            results.counts["1min:UNTRADED_EXTENDS_DAILY_EXTREMA"], 1)

    def test_missing_official_stock_day_is_not_credited_complete(self):
        results = A.Findings()
        references = reference()
        references[(A.day_number(DAY), "SZ000001")] = reference()[
            (A.day_number(DAY), SYM)].copy()
        A.evaluate_groups("1min", {}, references, CALIB, RULES, results, {})
        self.assertEqual(results.per_period["1min"]["missing_stock_days"], 2)

    def test_full_findings_jsonl_cannot_write_into_market_tree(self):
        findings = A.Findings()
        findings.add("1min", "PRICE_OUTSIDE_OFFICIAL_DAY",
                     DAY, SYM, {"high": 10.02})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "stock"
            market = root / "AllCycleAStockData"
            for period in L.PERIODS:
                (market / period).mkdir(parents=True, exist_ok=True)
            destination = Path(tmp) / "readiness" / "issues.jsonl"
            info = A.write_private_findings(root, destination,
                                            findings.all_findings)
            self.assertEqual(info["records"], 1)
            self.assertTrue(destination.is_file())
            self.assertIn("PRICE_OUTSIDE_OFFICIAL_DAY",
                          destination.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                A.write_private_findings(root, destination, findings.all_findings)
            with self.assertRaisesRegex(ValueError, "inside market data tree"):
                A.write_private_findings(
                    root, market / "1min" / "forbidden.jsonl",
                    findings.all_findings)

    def test_after_freeze_is_rejected_before_any_files_are_opened(self):
        with self.assertRaisesRegex(ValueError, "Only 2026"):
            A.audit("D:/stock", "D:/ChatGPT/AStockDataTools",
                    DAY, date(2026, 11, 19))


if __name__ == "__main__":
    unittest.main()
