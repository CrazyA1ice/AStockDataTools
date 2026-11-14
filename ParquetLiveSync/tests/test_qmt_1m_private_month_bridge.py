"""Offline tests for three-layer QMT private monthly 1m bridge, no market files."""
from __future__ import annotations

from datetime import date
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
import qmt_1m_private_month_bridge as B


def bars(days, symbol="SH600000"):
    rows = []
    for d in days:
        for time in sorted(B.P.expected_minute_grid(date.fromisoformat(d))):
            rows.append({"ts": B.P.stamp_ms(time), "symbol": symbol,
                         "open": 10., "high": 10.2, "low": 9.8,
                         "close": 10., "volume": 2., "amount": 200.})
    return pa.Table.from_pylist(rows, schema=B.P.PRIVATE_SCHEMA)


class PrivateMonthTests(unittest.TestCase):
    def _sealed_fixture(self, folder):
        stage = Path(folder) / "private_stage"
        orig = stage / "receipts"
        rec = stage / "day_recovery" / "receipts"
        orig.mkdir(parents=True)
        rec.mkdir(parents=True)
        days = ("2026-10-14", "2026-10-15")
        original = {"symbol": "600000.SH", "status": "private_ohlcva_source_verified",
                    "market_modified": False, "traded_days": list(days)}
        recovered = {"symbol": "000001.SZ", "format": B.R.FORMAT,
                     "status": "private_day_subset_only", "market_modified": False,
                     "production_merge_authorized": False,
                     "approved_days": [days[0]],
                     "quarantined_days": {days[1]: {"reason": "INVALID_OHLCVA"}}}
        (orig / "600000_SH.json").write_bytes(B.P.canonical(original))
        (rec / "000001_SZ.json").write_bytes(B.P.canonical(recovered))
        # The original DAY month hash is a past *pinned reference*, not the
        # presently mutable D:/stock/day month file.
        sources = {"physical": {"2026-10.parquet": "a" * 64},
                   "tdx_overlay": {"2026-10-14": "b" * 64}}
        keys = sorted((day, code) for day in days
                      for code in ("600000.SH", "000001.SZ"))
        calendar = B.P.sha_bytes(B.P.canonical({
            "physical_month_sha256": sources["physical"],
            "used_tdx_day_overlay_sha256": sources["tdx_overlay"],
            "days": keys}))
        cal_base = Path(folder) / "calibration"
        cal_base.mkdir()
        providers = {}
        anchors = (("SH_OTHER", "600000.SH"), ("SZ", "000001.SZ"),
                   ("STAR", "688001.SH"))
        for category, code in anchors:
            paid = Path(folder) / (category + ".parquet")
            paid.write_bytes(("purchased-source-" + category).encode())
            providers[category] = {
                "symbol": code, "paid_source_path": str(paid),
                "paid_source_sha256": B.L.hash_file(paid)}
        calibration = {"calibration_passed": True, "providers": providers}
        (cal_base / "latest.json").write_bytes(B.P.canonical(calibration))
        plan = {"format": B.P.FORMAT, "window": [str(B.START), str(B.END)],
                "stock_count": 2, "trading_days": list(days),
                "day_file_sha256": sources, "calendar_sha256": calendar,
                "calibration_sha256": B.P.sha_bytes(B.P.canonical(calibration))}
        (stage / "plan.json").write_bytes(B.P.canonical(plan))
        return stage, cal_base, plan

    def test_sealed_universe_unchanged_by_later_day_month_update(self):
        with tempfile.TemporaryDirectory() as temp:
            stage, cal_base, plan = self._sealed_fixture(temp)
            newer_day = Path(temp) / "current_2026_10.parquet"
            newer_day.write_bytes(b"updated-DAY-source-v2")
            with (patch.object(B.P, "BASE", cal_base),
                  patch.object(B.P, "official_day_universe",
                               side_effect=AssertionError("MUST NOT READ CURRENT DAY"))):
                expected, stocks, sealed, calib = B.load_sealed_context(
                    stage, min_daily_stocks=1)
                self.assertEqual(len(stocks), 2)
                self.assertEqual(len(expected), 2)
                self.assertEqual(sealed["calendar_sha256"], plan["calendar_sha256"])
                newer_day.write_bytes(b"updated-DAY-source-v3")
                again = B.load_sealed_context(stage, min_daily_stocks=1)
                self.assertEqual(again[2], sealed)

    def test_sealed_original_calendar_sha_tamper_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            stage, cal_base, plan = self._sealed_fixture(temp)
            plan["day_file_sha256"]["physical"]["2026-10.parquet"] = "f" * 64
            (stage / "plan.json").write_bytes(B.P.canonical(plan))
            with patch.object(B.P, "BASE", cal_base):
                with self.assertRaisesRegex(ValueError, "calendar SHA mismatch"):
                    B.load_sealed_context(stage, min_daily_stocks=1)

    def test_sealed_receipt_day_membership_tamper_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            stage, cal_base, plan = self._sealed_fixture(temp)
            file = stage / "day_recovery" / "receipts" / "000001_SZ.json"
            doc = json.loads(file.read_bytes())
            doc["approved_days"] = []
            file.write_bytes(B.P.canonical(doc))
            with patch.object(B.P, "BASE", cal_base):
                with self.assertRaisesRegex(ValueError, "calendar SHA mismatch"):
                    B.load_sealed_context(stage, min_daily_stocks=1)

    def test_sealed_purchased_calibration_sha_tamper_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            stage, cal_base, plan = self._sealed_fixture(temp)
            (Path(temp) / "SH_OTHER.parquet").write_bytes(b"changed-paid-source")
            with patch.object(B.P, "BASE", cal_base):
                with self.assertRaisesRegex(ValueError, "purchased source SHA changed"):
                    B.load_sealed_context(stage, min_daily_stocks=1)

    def test_calibration_time_volume_amount_and_values(self):
        t = bars(["2026-10-14"]).slice(0, 1)
        output = B.calibrate_table(t, {"offset_ms": 60000,
                                      "volume_factor": 100.,
                                      "amount_factor": 1.}, "2026-10")
        self.assertEqual(output["ts"][0].as_py(), t["ts"][0].as_py() + 60000)
        self.assertEqual(output["volume"][0].as_py(), 200.)
        self.assertEqual(output["amount"][0].as_py(), 200.)
        self.assertEqual(t["volume"][0].as_py(), 2.)

    def test_reject_uncertified_factors(self):
        sample = {"providers": {"SH_OTHER": {"category": "SH_OTHER",
                   "offset_ms": 0, "volume": {"factor": 100.},
                   "amount": {"factor": 1.}}}}
        self.assertEqual(B._calibration(sample, "600000.SH")["volume_factor"], 100.)
        sample["providers"]["SH_OTHER"]["volume"]["factor"] = -100.
        with self.assertRaisesRegex(ValueError, "Uncertified"):
            B._calibration(sample, "600000.SH")

    def test_validate_exact_native_minute_grid_not_240(self):
        day = "2026-10-14"
        whole = bars([day])
        entry = {"code": "600000.SH", "days": [day]}
        grid = B._expected_timestamps({date.fromisoformat(day): {}})
        B.validate_source_table(whole, entry, grid)
        with self.assertRaisesRegex(ValueError, "schema/row count"):
            B.validate_source_table(whole.slice(1), entry, grid)
        columns = whole.to_pylist()
        columns[0]["ts"] += 60000
        broken = pa.Table.from_pylist(columns, schema=B.P.PRIVATE_SCHEMA)
        with self.assertRaisesRegex(ValueError, "grid/ordering"):
            B.validate_source_table(broken, entry, grid)

    def test_logical_digest_is_stable_across_arrow_chunks_and_parquet(self):
        day = "2026-10-14"
        source = bars([day])
        split = pa.concat_tables([source.slice(0, 120),
                                  source.slice(120, 121)])
        self.assertEqual(source.to_pylist(), split.to_pylist())
        self.assertEqual(B._arrow_digest(source), B._arrow_digest(split))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "roundtrip.parquet"
            pq.write_table(split, path, compression="zstd")
            from_disk = pq.read_table(path)
            self.assertEqual(source.to_pylist(), from_disk.to_pylist())
            self.assertEqual(B._arrow_digest(source), B._arrow_digest(from_disk))
        altered = source.to_pylist()
        altered[0]["amount"] += 1.
        changed = pa.Table.from_pylist(altered, schema=B.P.PRIVATE_SCHEMA)
        self.assertNotEqual(B._arrow_digest(source), B._arrow_digest(changed))

    def test_source_ownership_prevents_duplicate_stock_day(self):
        ledger = []
        seen = {}
        day = date(2026, 10, 14)
        expected = {day: {"600000.SH": {}, "000001.SZ": {}}}
        B._add_entry(ledger, seen, expected, "600000.SH", [str(day)],
                     "original", "source", "a" * 64, "b" * 64)
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            B._add_entry(ledger, seen, expected, "600000.SH", [str(day)],
                         "opening", "source2", "c" * 64, "d" * 64)
        with self.assertRaisesRegex(ValueError, "absent"):
            B._add_entry(ledger, seen, expected, "600000.SH", ["2026-10-15"],
                         "recovery", "source3", "a" * 64, "b" * 64)

    def _fake_plan(self, workspace):
        stage = Path(workspace)
        source = stage / "source_stock.parquet"
        accepted = ["2026-10-14", "2026-11-02"]
        table = bars(accepted)
        pq.write_table(table, source, compression="zstd")
        gate = {"category": "SH_OTHER", "offset_ms": 0,
                "volume": {"factor": 100.}, "amount": {"factor": 1.}}
        entry = {"code": "600000.SH", "days": accepted, "kind": "original",
                 "path": str(source), "receipt_sha256": "a" * 64,
                 "source_sha256": B.L.hash_file(source)}
        return {"entries": [entry], "expected": {
                    date(2026, 10, 14): {"600000.SH": {}},
                    date(2026, 11, 2): {"600000.SH": {}}},
                "calib": {"providers": {"SH_OTHER": gate}},
                "identity_sha256": "b" * 64, "gaps": [],
                "months": {k: {"stock_days_expected": 1,
                               "stock_days_accepted": 1,
                               "stock_days_quarantined": 0,
                               "minute_rows_expected_from_accepted": 241,
                               "incomplete_window": k == "2026-10"}
                           for k in B.MONTHS},
                "original": 2, "recovered": 0, "opening": 0,
                "total_expected": 2,
                "plan": {"calibration_sha256": "c" * 64}}

    def test_preview_never_creates_output(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self._fake_plan(temp)
            with patch.object(B, "resolve", return_value=fixture):
                result = B.build(temp, temp, progress=lambda _: None)
            self.assertEqual(result["total_accepted_stock_days"], 2)
            self.assertFalse(result["private_written"])
            self.assertFalse((Path(temp) / B.TARGET).exists())

    def test_build_months_readback_reuse_and_tamper_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self._fake_plan(temp)
            with (patch.object(B, "resolve", return_value=fixture),
                  patch.object(B, "_output_allowed", return_value=None)):
                written = B.build(temp, temp, write_private=True,
                                  progress=lambda _: None)
                self.assertTrue(written["private_written"])
                folder = Path(temp) / B.TARGET
                for mon in B.MONTHS:
                    p = folder / (mon + ".parquet")
                    rec = json.loads((folder / (mon + ".receipt.json")).read_bytes())
                    self.assertEqual(rec["rows"], 241)
                    self.assertEqual(rec["groups"][0]["source_kind"], "original")
                    self.assertEqual(pq.read_table(p)["volume"][0].as_py(), 200.)
                    self.assertFalse(rec["production_merge_authorized"])
                reused = B.build(temp, temp, write_private=True,
                                 progress=lambda _: None)
                self.assertEqual(reused["total_accepted_stock_days"], 2)
                with (folder / "2026-10.parquet").open("ab") as stream:
                    stream.write(b"modified")
                with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                    B.build(temp, temp, write_private=True,
                            progress=lambda _: None)

    def test_source_sha_changed_blocks_any_month_write(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self._fake_plan(temp)
            Path(fixture["entries"][0]["path"]).write_bytes(b"changed")
            with (patch.object(B, "resolve", return_value=fixture),
                  patch.object(B, "_output_allowed", return_value=None)):
                with self.assertRaisesRegex(ValueError, "SHA-verified input"):
                    B.build(temp, temp, write_private=True,
                            progress=lambda _: None)
            self.assertFalse((Path(temp) / B.TARGET / "2026-10.parquet").exists())


if __name__ == "__main__":
    unittest.main()
