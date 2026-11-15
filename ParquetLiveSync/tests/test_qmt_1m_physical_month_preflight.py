"""Offline tests of physical 1min target read-only inventory and overlap blocker."""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import qmt_1m_physical_month_preflight as F


def table_for(stamps, symbol="SH600000"):
    return pa.Table.from_pylist([
        {"ts": F.B.P.stamp_ms(datetime.fromisoformat(s).replace(
            tzinfo=F.L.UTC8).isoformat()), "symbol": symbol,
         "open": 10., "high": 10.1, "low": 9.9,
         "close": 10., "volume": 100., "amount": 10000.}
        for s in stamps
    ], schema=F.B.P.PRIVATE_SCHEMA)


class PhysicalMonthPreflightTests(unittest.TestCase):
    def fixture(self, folder):
        root = Path(folder)
        storage = root / "AllCycleAStockData"
        for name in F.L.PERIODS:
            (storage / name).mkdir(parents=True, exist_ok=True)
        stage = root / "sealed"
        output = stage / F.B.TARGET
        output.mkdir(parents=True)
        days = (date(2026, 10, 14), date(2026, 11, 2))
        plan = {"expected": {d: {"600000.SH": {}} for d in days},
                "identity_sha256": "a" * 64,
                "plan": {"calibration_sha256": "b" * 64,
                         "calendar_sha256": "c" * 64},
                "months": {
                    month: {"stock_days_expected": 1, "stock_days_accepted": 1,
                            "stock_days_quarantined": 0,
                            "minute_rows_expected_from_accepted": 1}
                    for month in F.B.MONTHS
                }, "original": 2, "recovered": 0, "opening": 0, "gaps": []}
        for month, stamp in (("2026-10", "2026-10-14T09:31:00"),
                             ("2026-11", "2026-11-02T09:31:00")):
            t = table_for([stamp])
            p = output / (month + ".parquet")
            pq.write_table(t, p, row_group_size=1)
            manifest = {"format": F.B.FORMAT, "status": "PRIVATE_MONTH_ONLY",
                        "month": month, "identity_sha256": plan["identity_sha256"],
                        "calibration_sha256": plan["plan"]["calibration_sha256"],
                        "month_coverage": plan["months"][month],
                        "remaining_quarantined_keys": [], "rows": 1,
                        "groups": [{"symbol": "SH600000", "rows": 1,
                                    "arrow_sha256": F.B._arrow_digest(t)}],
                        "sha256": F.L.hash_file(p),
                        "market_modified": False,
                        "production_merge_authorized": False}
            (output / (month + ".receipt.json")).write_bytes(
                F.B.P.canonical(manifest))
        return root, stage, plan

    def test_scan_physical_full_month_day_counts_sha_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            month = Path(temp) / "2026-10.parquet"
            pq.write_table(table_for(["2026-10-13T09:31:00",
                                      "2026-10-13T09:32:00",
                                      "2026-10-14T09:31:00"]), month)
            sha = F.L.hash_file(month)
            result = F.scan_physical_month(month, "2026-10", progress=lambda _: None)
            self.assertEqual(result["rows"], 3)
            self.assertEqual(result["days"],
                             {"2026-10-13": 2, "2026-10-14": 1})
            self.assertEqual(result["sha256"], sha)
            self.assertEqual(F.L.hash_file(month), sha)

    def test_target_disjoint_october_november_missing_readonly(self):
        with tempfile.TemporaryDirectory() as temp:
            root, stage, plan = self.fixture(temp)
            oct_file = root / "AllCycleAStockData" / "1min" / "2026-10.parquet"
            pq.write_table(table_for(["2026-10-13T09:31:00"]), oct_file)
            original = F.L.hash_file(oct_file)
            with patch.object(F.B, "resolve", return_value=plan):
                result = F.inspect(root, stage, progress=lambda _: None)
            self.assertTrue(result["date_disjoint_gate_passed"])
            self.assertEqual(result["target_months"]["2026-10"]["status"],
                             "DATE_DISJOINT_CANDIDATE")
            self.assertEqual(result["target_months"]["2026-11"]["status"],
                             "TARGET_ABSENT_CANDIDATE")
            self.assertFalse(result["production_merge_authorized"])
            self.assertTrue(result["exact_key_overlap_audit_not_yet_completed"])
            self.assertEqual(F.L.hash_file(oct_file), original)
            self.assertFalse((root / "AllCycleAStockData" / "1min" /
                              "2026-11.parquet").exists())

    def test_shared_date_blocked_without_any_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root, stage, plan = self.fixture(temp)
            oct_file = root / "AllCycleAStockData" / "1min" / "2026-10.parquet"
            pq.write_table(table_for(["2026-10-14T09:30:00"]), oct_file)
            sha = F.L.hash_file(oct_file)
            with patch.object(F.B, "resolve", return_value=plan):
                result = F.inspect(root, stage, progress=lambda _: None)
            self.assertEqual(result["blocked_by_shared_dates"], ["2026-10"])
            self.assertFalse(result["date_disjoint_gate_passed"])
            self.assertEqual(result["target_months"]["2026-10"]["shared_trading_days"],
                             ["2026-10-14"])
            self.assertFalse(result["production_merge_authorized"])
            self.assertEqual(F.L.hash_file(oct_file), sha)

    def test_corrupt_private_receipt_file_fails_before_market_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            root, stage, plan = self.fixture(temp)
            private = stage / F.B.TARGET / "2026-10.parquet"
            with private.open("ab") as output:
                output.write(b"tamper")
            with patch.object(F.B, "resolve", return_value=plan):
                with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                    F.inspect(root, stage, progress=lambda _: None)

    def test_annual_2026_target_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root, stage, plan = self.fixture(temp)
            (root / "AllCycleAStockData" / "1min" / "2026.parquet").write_bytes(
                b"annual-file-do-not-touch")
            with patch.object(F.B, "resolve", return_value=plan):
                with self.assertRaisesRegex(ValueError, "annual 1min"):
                    F.inspect(root, stage, progress=lambda _: None)

    def test_out_of_month_physical_timestamp_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "2026-10.parquet"
            pq.write_table(table_for(["2026-11-02T09:31:00"]), path)
            with self.assertRaisesRegex(ValueError, "out-of-month"):
                F.scan_physical_month(path, "2026-10", progress=lambda _: None)

    def test_incoming_manifest_gap_map_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, stage, plan = self.fixture(temp)
            receipt = stage / F.B.TARGET / "2026-11.receipt.json"
            doc = json.loads(receipt.read_bytes())
            doc["remaining_quarantined_keys"] = [{"day": "2026-11-02",
                                                    "symbol": "600000.SH"}]
            receipt.write_bytes(F.B.P.canonical(doc))
            with patch.object(F.B, "resolve", return_value=plan):
                with self.assertRaisesRegex(ValueError, "gap map"):
                    F.inspect(root, stage, progress=lambda _: None)


if __name__ == "__main__":
    unittest.main()
