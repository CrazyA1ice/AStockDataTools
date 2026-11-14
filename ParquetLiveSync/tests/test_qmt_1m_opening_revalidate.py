"""Offline contracts for opening-price quarantine revalidation and private SHA output."""
from __future__ import annotations

from datetime import date, datetime
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location(
    "qmt_1m_opening_revalidate", HERE / "qmt_1m_opening_revalidate.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def example(day="2026-10-14", first=1):
    d = date.fromisoformat(day)
    ticks = sorted(M.P.GRID)
    rows = []
    for i, (hour, minute) in enumerate(ticks):
        special = i < first
        ts = int(datetime(d.year, d.month, d.day, hour, minute,
                          tzinfo=M.M.CN).timestamp() * 1000)
        rows.append({"ts": ts, "open": 12. if special else 10.,
                     "high": 12. if special else 10.2,
                     "low": 12. if special else 9.8,
                     "close": 12. if special else 10.1,
                     "volume": 0. if special else 1.,
                     "amount": 0. if special else 100.})
    agg = {"open": rows[0]["open"], "high": max(r["high"] for r in rows),
           "low": min(r["low"] for r in rows), "close": rows[-1]["close"]}
    evidence = {
        "reason": M.ORIGINAL_REASON, "qmt": agg,
        "native_totals": {"volume": float(241 - first),
                          "amount": float(100 * (241 - first))},
        "day_reference": {"open": 10., "high": 10.2,
                          "low": 9.8, "close": 10.1}}
    return rows, evidence


class OpeningTests(unittest.TestCase):
    def test_zero_0930_first_0931_preserves_241_native(self):
        rows, evidence = example()
        original = json.dumps(rows)
        valid, detail = M.assess_day(rows, "2026-10-14", evidence)
        self.assertTrue(valid, detail)
        self.assertEqual(detail["first_traded_label"], "09:31")
        self.assertEqual(detail["zero_prefix_bars"], 1)
        self.assertEqual(json.dumps(rows), original)
        self.assertEqual(len(rows), 241)

    def test_0933_first_trade_and_unchanged_zero_minutes(self):
        rows, evidence = example(first=3)
        valid, detail = M.assess_day(rows, "2026-10-14", evidence)
        self.assertTrue(valid, detail)
        self.assertEqual(detail["first_traded_label"], "09:33")
        self.assertEqual(detail["zero_prefix_bars"], 3)

    def test_not_first_traded_open_reject(self):
        rows, evidence = example()
        evidence["day_reference"]["open"] = 10.5
        ok, detail = M.assess_day(rows, "2026-10-14", evidence)
        self.assertFalse(ok)
        self.assertEqual(detail["reason"], "FIRST_TRADED_OPEN_NOT_STRICT")

    def test_first_minute_with_trades_not_auto_accepted(self):
        rows, evidence = example()
        rows[0]["volume"] = 1.
        evidence["native_totals"]["volume"] += 1.
        valid, detail = M.assess_day(rows, "2026-10-14", evidence)
        self.assertFalse(valid)
        self.assertEqual(detail["reason"], "0930_HAS_TRADES")

    def test_ambiguous_volume_and_amount_rejected(self):
        rows, evidence = example()
        rows[2]["amount"] = 0
        evidence["native_totals"]["amount"] -= 100
        ok, reason = M.assess_day(rows, "2026-10-14", evidence)
        self.assertFalse(ok)
        self.assertEqual(reason["reason"], "AMBIGUOUS_VOLUME_AMOUNT_PAIR")

    def test_daily_hlc_conflict_kept_in_quarantine(self):
        rows, evidence = example()
        evidence["day_reference"]["high"] = 10.8
        valid, detail = M.assess_day(rows, "2026-10-14", evidence)
        self.assertFalse(valid)
        self.assertEqual(detail["reason"], "TRADED_MINUTES_HLC_MISMATCH")

    def test_source_snapshot_mismatch_rejected(self):
        rows, evidence = example()
        rows[0]["open"] = 15
        rows[0]["high"] = 15
        rows[0]["low"] = 15
        rows[0]["close"] = 15
        valid, detail = M.assess_day(rows, "2026-10-14", evidence)
        self.assertFalse(valid)
        self.assertEqual(detail["reason"], "SAVED_NATIVE_SNAPSHOT_DISAGREES")

    def test_241_and_day_grid_required(self):
        rows, evidence = example()
        valid, detail = M.assess_day(rows[:-1], "2026-10-14", evidence)
        self.assertFalse(valid)
        self.assertEqual(detail["reason"], "NOT_241_NATIVE_BARS")
        valid, detail = M.assess_day(rows, "2026-10-15", evidence)
        self.assertFalse(valid)
        self.assertEqual(detail["reason"], "NATIVE_GRID_MISMATCH")

    def test_private_receipt_reattach_and_sha_tamper(self):
        rows, evidence = example()
        ok, detail = M.assess_day(rows, "2026-10-14", evidence)
        self.assertTrue(ok)
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "private"
            source = {"2026-10-14": rows}
            provenance = {"source_recovery_receipt_sha256": "source-sha",
                          "source_stage_plan_sha256": "plan-sha"}
            result = M._save_stock(dest, "600000.SH", source,
                                   {"2026-10-14": detail}, {}, provenance)
            self.assertEqual(result["rows"], 241)
            self.assertFalse(result["production_merge_authorized"])
            self.assertFalse(result["market_modified"])
            read = M._reuse(dest, "600000.SH", provenance, {"2026-10-14": evidence})
            self.assertEqual(read["sha256"], result["sha256"])
            with self.assertRaisesRegex(ValueError, "already exists"):
                M._save_stock(dest, "600000.SH", source,
                              {"2026-10-14": detail}, {}, provenance)
            target = dest / "source_parquet" / "600000_SH.parquet"
            with target.open("ab") as f:
                f.write(b"tamper")
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                M._reuse(dest, "600000.SH", provenance, {"2026-10-14": evidence})

    def test_invalid_receipt_provenance_cannot_reuse(self):
        rows, _ = example()
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "private"
            p = {"source_recovery_receipt_sha256": "x",
                 "source_stage_plan_sha256": "y"}
            M._save_stock(dest, "600000.SH", {"2026-10-14": rows},
                          {"2026-10-14": {"reason": "VERIFIED_FIRST_TRADED_OPEN"}},
                          {}, p)
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                M._reuse(dest, "600000.SH",
                         {"source_recovery_receipt_sha256": "changed",
                          "source_stage_plan_sha256": "y"},
                         {"2026-10-14": {}})

    def test_end_to_end_readonly_and_idempotent_private_source(self):
        rows, evidence = example()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "ParquetLiveSync"
            stage = root / "work" / "qmt_1min_market" / "20261014_20261112"
            receipt_dir = stage / "day_recovery" / "receipts"
            receipt_dir.mkdir(parents=True)
            (stage / "plan.json").write_text('{"format":"test-plan"}', encoding="utf-8")
            receipt = {"format": M.R.FORMAT, "status": "private_day_subset_only",
                       "symbol": "600000.SH", "approved_days": [],
                       "quarantined_days": {"2026-10-14": evidence}, "rows": 0,
                       "sha256": None, "market_modified": False,
                       "production_merge_authorized": False}
            (receipt_dir / "600000_SH.json").write_text(
                json.dumps(receipt), encoding="utf-8")
            (stage / "day_recovery" / "latest_report.json").write_text(
                json.dumps({"remaining_stock_day_gaps": 1,
                            "quarantined_reason_counts": {M.ORIGINAL_REASON: 1}}),
                encoding="utf-8")
            datadir = Path(temp) / "QMT_DAT"
            dat = datadir / "SH" / "60" / "600000.DAT"
            dat.parent.mkdir(parents=True)
            dat.write_bytes(b"native-DAT")
            calls = []
            def reader(code, directory):
                calls.append(code)
                return rows, "TEST_ONLY", None
            with patch.object(M, "__file__", str(root / "qmt_1m_opening_revalidate.py")):
                checked = M.run(stage, datadir, native_reader=reader,
                                progress=lambda _: None)
                self.assertEqual(checked["newly_passed_stock_days"], 1)
                self.assertFalse(checked["private_written"])
                self.assertFalse((stage / "opening_first_trade_v1").exists())
                saved = M.run(stage, datadir, native_reader=reader,
                              write_private=True, progress=lambda _: None)
                self.assertEqual(saved["newly_passed_stock_days"], 1)
                self.assertTrue(saved["private_written"])
                reuse = M.run(stage, datadir, native_reader=reader,
                              write_private=True, progress=lambda _: None)
                self.assertEqual(reuse["reused_stocks"], 1)
                self.assertEqual(len(calls), 2)  # no repeat local DAT extraction
                self.assertEqual(dat.read_bytes(), b"native-DAT")
                self.assertFalse(saved["production_merge_authorized"])
            self.assertTrue((stage / "opening_first_trade_v1" / "receipts"
                             / "600000_SH.json").exists())


if __name__ == "__main__":
    unittest.main()
