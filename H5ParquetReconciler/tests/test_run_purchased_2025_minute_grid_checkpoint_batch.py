"""Checkpointed 2025 private source-key index batch, real synthetic files."""
import contextlib
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "purchased_2025_checkpoint_batch_tests",
    HERE.parent / "tools" / "run-purchased-2025-minute-grid-checkpoint-batch.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


class Checkpointed2025BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / "private-receipts"
        self.index = self.root / "private-indexes"
        (self.root / "HikyuuData").mkdir()
        for period in ("1min", "5min"):
            (self.root / "HikyuuData" / ("sh_" + period + ".h5")).touch()
            folder = self.root / "AllCycleAStockData" / period / "2025"
            folder.mkdir(parents=True)
            stamps = []
            for day in (date(2025, 1, 2), date(2025, 2, 3)):
                keys = sorted(B.A.D.normalized_native_keys(day, period).values())
                if period == "1min":
                    keys = [B.A.I.day_epoch_ms(day) + 570 * 60000, *keys]
                stamps.extend(keys)
            pq.write_table(pa.table({
                "ts": pa.array(stamps, type=pa.int64()),
                "symbol": ["SH600000"] * len(stamps),
            }), folder / "2025.parquet")

    @contextlib.contextmanager
    def private(self):
        with patch.object(B, "WORK", self.work), \
             patch.object(B.A.I, "STORE", self.index):
            yield

    def test_two_months_checkpointed_reused_without_recopy(self):
        with self.private():
            a = B.run(self.root, "2025-01", "2025-02",
                      max_new_index_months=1, allow_build=True)
            self.assertEqual(a["status"], "partial_verified_resume_with_same_command")
            self.assertEqual(a["verified_months"], ["2025-01"])
            self.assertEqual(a["pending_months"], ["2025-02"])
            self.assertEqual(a["private_indexes_created_this_run"], 1)
            self.assertEqual(len(list(self.index.glob("*.sqlite"))), 1)
            b = B.run(self.root, "2025-01", "2025-02",
                      max_new_index_months=1, allow_build=True)
            self.assertEqual(b["status"],
                             "complete_private_key_grid_receipts_not_exchange_calendar")
            self.assertEqual(b["private_indexes_created_this_run"], 1)
            self.assertEqual(len(list(self.index.glob("*.sqlite"))), 2)
            self.assertEqual(b["source_only_stockday_totals"]["1min"],
                             {"stockdays": 2, "keys": 482})
            self.assertEqual(b["source_only_stockday_totals"]["5min"],
                             {"stockdays": 2, "keys": 96})
            with patch.object(B.A.G.E, "ensure",
                              side_effect=AssertionError("No index rebuild")):
                c = B.run(self.root, "2025-01", "2025-02",
                          max_new_index_months=0, allow_build=False)
            self.assertEqual(c["verified_months"], ["2025-01", "2025-02"])
            self.assertEqual(c["private_indexes_created_this_run"], 0)
            self.assertEqual(len(list(self.index.glob("*.sqlite"))), 2)
            self.assertFalse(c["purchased_ohlcva_read_or_copied"])
            self.assertFalse(c["production_activated"])

    def test_no_index_build_permission_only_marks_pending(self):
        with self.private():
            out = B.run(self.root, "2025-01", "2025-02",
                        max_new_index_months=0, allow_build=False)
        self.assertEqual(out["verified_months"], [])
        self.assertEqual(out["pending_months"], ["2025-01", "2025-02"])
        self.assertFalse(self.work.exists())
        self.assertFalse(self.index.exists())

    def test_source_metadata_drift_rejects_old_receipt(self):
        with self.private():
            B.run(self.root, "2025-01", "2025-01",
                  max_new_index_months=1, allow_build=True)
            p = self.root / "HikyuuData" / "sh_1min.h5"
            with p.open("ab") as f:
                f.write(b"changed")
            with self.assertRaisesRegex(ValueError, "stale"):
                B.run(self.root, "2025-01", "2025-01",
                      max_new_index_months=0, allow_build=False)

    def test_receipt_tamper_rejected_not_recomputed(self):
        with self.private():
            B.run(self.root, "2025-01", "2025-01",
                  max_new_index_months=1, allow_build=True)
            p = B._file("2025-01")
            data = json.loads(p.read_text(encoding="utf-8"))
            data["audit"]["periods"]["1min"]["keys"] = 1
            p.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "conservation"):
                B.run(self.root, "2025-01", "2025-01",
                      max_new_index_months=0, allow_build=False)

    def test_invalid_months_fail_before_source_read(self):
        for a, z in (("2024-01", "2025-02"), ("2025-02", "2025-01"),
                     ("2025-00", "2025-01")):
            with self.subTest(a=a, z=z), self.assertRaises(ValueError):
                B.months(a, z)

    def test_monthly_receipt_absence_not_marked_source_gap(self):
        with self.private():
            out = B.run(self.root, "2025-01", "2025-01",
                        max_new_index_months=1, allow_build=True)
            receipt = json.loads(B._file("2025-01").read_text(encoding="utf-8"))
        audit = receipt["audit"]
        self.assertIn("2025-01-01",
                      audit["weekday_dates_without_purchased_source_evidence"])
        self.assertFalse(audit["full_exchange_calendar_coverage_certified"])
        self.assertFalse(out["exchange_calendar_certified"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
