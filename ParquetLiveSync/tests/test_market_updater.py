"""Synthetic regression for one-command daily updater; temporary files only."""
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
import market_month_storage as S
import market_source_adapters as X
import update_market as U
import local_layout as L


def stock_day(day="2026-11-13", code="600000.SH"):
    minute_grid = sorted(U.P.GRID)
    rows = []
    for i, (hour, minute) in enumerate(minute_grid):
        rows.append({
            "datetime_cn": datetime.fromisoformat(
                day + "T" + f"{hour:02}:{minute:02}:00").replace(
                    tzinfo=L.UTC8).isoformat(),
            "symbol": code,
            "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0,
            "volume": 0.0 if i == 0 else 2.0,
            "amount": 0.0 if i == 0 else 200.0})
    return rows


def canonical(rows, style="SH600000"):
    return pa.Table.from_pylist([{"symbol": style, **x}
                                 for x in rows], schema=S.SCHEMA)


def fixture(root):
    base = Path(root) / "AllCycleAStockData"
    for period in L.PERIODS:
        (base / period).mkdir(parents=True, exist_ok=True)
    return base


class MarketUpdaterTests(unittest.TestCase):
    def test_provider_cross_fit_one_minute_clock_shift(self):
        q = [{"ts": 1000000 + 60000 * i, "open": 10., "high": 10.2,
              "low": 9.8, "close": 10., "volume": 2., "amount": 200.}
             for i in range(240)]
        external = [{**x, "ts": x["ts"] - 60000, "volume": 200.}
                    for x in q]
        result = X.compare_minutes(q, external)
        self.assertEqual(result["status"], "AGREE")
        self.assertEqual(result["offset_ms"], 60000)
        self.assertEqual(result["volume_ratio"]["status"], "STABLE")
        wrong = [{**x, "open": 15., "high": 15.2, "low": 14.8, "close": 15.}
                 for x in external]
        self.assertEqual(X.compare_minutes(q, wrong)["status"], "PRICE_DISAGREES")

    def test_qmt_241_to_240_and_independent_daily_reference(self):
        raw = stock_day()
        gate = {"providers": {"SH_OTHER": {
            "category": "SH_OTHER", "offset_ms": 0,
            "volume": {"factor": 100.}, "amount": {"factor": 1.}}}}
        day = date(2026, 11, 13)
        official = {"open": 10., "high": 10.2, "low": 9.8,
                    "close": 10., "volume": 48000., "amount": 48000.}
        candidate = U.normal_qmt_day(raw, "600000.SH", day, official, gate)
        self.assertEqual(candidate.num_rows, 240)
        self.assertEqual(S._daily_group_rows(candidate), ["2026-11-13"])
        self.assertEqual(candidate["volume"][0].as_py(), 200.0)
        self.assertEqual(L.market_ts_day(candidate["ts"][0].as_py()), day)

    def test_nonzero_0930_and_official_price_mismatch_fail(self):
        raw = stock_day()
        gate = {"providers": {"SH_OTHER": {
            "category": "SH_OTHER", "offset_ms": 0,
            "volume": {"factor": 100.}, "amount": {"factor": 1.}}}}
        ref = {"open": 10., "high": 10.2, "low": 9.8,
               "close": 10., "volume": 48000., "amount": 48000.}
        raw[0]["volume"] = 5.
        with self.assertRaisesRegex(ValueError, "09:30"):
            U.normal_qmt_day(raw, "600000.SH", date(2026, 11, 13), ref, gate)
        raw[0]["volume"] = 0.
        ref["open"] = 12.
        with self.assertRaisesRegex(ValueError, "OHLC"):
            U.normal_qmt_day(raw, "600000.SH", date(2026, 11, 13), ref, gate)

    def test_qmt_private_241_zero_placeholder_filter(self):
        raw = stock_day("2026-10-14")
        rows = [{"ts": U.P.stamp_ms(r["datetime_cn"]), "symbol": "SH600000",
                 **{k: r[k] for k in U.FIELDS}} for r in raw]
        t = canonical(rows)
        output, removed = S.adapt_241_private(t, 0, "2026-10")
        self.assertEqual(removed, 1)
        self.assertEqual(output.num_rows, 240)
        self.assertEqual(output["ts"][0].as_py(), rows[1]["ts"])
        rows[0]["amount"] = 1.
        with self.assertRaisesRegex(ValueError, "zero-trade"):
            S.adapt_241_private(canonical(rows), 0, "2026-10")

    def test_canonical_month_append_idempotence_and_old_vendor_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = fixture(tmp)
            work = Path(tmp) / "work"
            september = base / "1min" / "2026-09.parquet"
            prior = canonical([{"ts": U.P.stamp_ms(
                datetime(2026, 9, 30, 9, 31, tzinfo=L.UTC8).isoformat()),
                **{k: 10.0 for k in U.FIELDS}}],
                style="600000.SH")
            pq.write_table(prior, september)
            before = L.hash_file(september)
            day = "2026-11-13"
            one = canonical([{"ts": U.P.stamp_ms(
                datetime(2026, 11, 13, 9, 31, tzinfo=L.UTC8).isoformat()),
                **{k: 10.0 for k in U.FIELDS}}])
            a = S.install_month(tmp, "2026-11", iter([one]),
                                source_id="TEST:one", days=[day],
                                workspace=work, progress=lambda _: None)
            self.assertEqual(a["status"], "COMMITTED")
            target = base / "1min" / "2026-11.parquet"
            saved = pq.read_table(target)
            self.assertEqual(saved["symbol"][0].as_py(), "600000.SH")
            b = S.install_month(tmp, "2026-11", iter([one]),
                                source_id="TEST:one", days=[day],
                                workspace=work, progress=lambda _: None)
            self.assertEqual(b["status"], "ALREADY_INSTALLED")
            self.assertEqual(L.hash_file(september), before)
            later = canonical([{"ts": U.P.stamp_ms(
                datetime(2026, 11, 16, 9, 31, tzinfo=L.UTC8).isoformat()),
                **{k: 10.0 for k in U.FIELDS}}])
            c = S.install_month(tmp, "2026-11", iter([later]),
                                source_id="TEST:two", days=["2026-11-16"],
                                workspace=work, progress=lambda _: None)
            self.assertEqual(c["rows"], 2)
            self.assertEqual(len(pq.read_table(target)["symbol"]), 2)
            with self.assertRaisesRegex(ValueError, "Overlapping trading date"):
                S.install_month(tmp, "2026-11", iter([one]),
                                source_id="TEST:three", days=[day],
                                workspace=work, progress=lambda _: None)
            self.assertTrue((work / "backups").is_dir())

    def test_month_external_edit_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = fixture(tmp)
            work = Path(tmp) / "work"
            target = base / "1min" / "2026-11.parquet"
            one = canonical([{"ts": U.P.stamp_ms(
                datetime(2026, 11, 13, 9, 31, tzinfo=L.UTC8).isoformat()),
                **{k: 10.0 for k in U.FIELDS}}])
            S.install_month(tmp, "2026-11", iter([one]), source_id="T1",
                            days=["2026-11-13"], workspace=work, progress=lambda _: None)
            with target.open("ab") as f:
                f.write(b"external-write")
            with self.assertRaisesRegex(ValueError, "changed since"):
                S.install_month(tmp, "2026-11", iter([one]), source_id="T2",
                                days=["2026-11-16"], workspace=work,
                                progress=lambda _: None)

    def test_dry_run_requires_no_qmt_or_market_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture(tmp)
            with (patch.object(U.B, "resolve", return_value={
                    "expected": {date(2026, 10, 14): {"600000.SH": {}}},
                    "original": 1, "recovered": 0, "opening": 0,
                    "gaps": [], "months": {}, "identity_sha256": "a" * 64}),
                  patch.object(U.S, "recover_intent",
                               return_value={"periods": {"1min": {}}})):
                with self.assertRaisesRegex(ValueError, "source count changed"):
                    U.bootstrap(tmp, apply=False, progress=lambda _: None)


if __name__ == "__main__":
    unittest.main()
