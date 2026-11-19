"""2026-11-18 zero-volume price boundary regressions; synthetic inputs only.

No QMT network calls, live market writes, or production file access.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import local_layout as L
import update_market as U


DAY = date(2026, 11, 18)
CODE = "600000.SH"
GATE = {"providers": {"SH_OTHER": {
    "category": "SH_OTHER", "offset_ms": 0,
    "volume": {"factor": 100.}, "amount": {"factor": 1.},
}}}


def minute_day():
    rows = []
    for h, m in sorted(U.P.GRID):
        stamp = datetime(DAY.year, DAY.month, DAY.day, h, m,
                         tzinfo=L.UTC8).isoformat()
        rows.append({
            "datetime_cn": stamp, "symbol": CODE,
            "open": 10., "high": 10.2, "low": 9.8, "close": 10.,
            "volume": 0. if (h, m) == (9, 30) else 2.,
            "amount": 0. if (h, m) == (9, 30) else 200.,
        })
    assert len(rows) == 241
    return rows


def daily(rows, close=10.):
    return {"open": 10., "high": 10.2, "low": 9.8, "close": close,
            "volume": sum(r["volume"] for r in rows) * 100.,
            "amount": sum(r["amount"] for r in rows)}


class ZeroVolumeOhlcGateTests(unittest.TestCase):
    def test_terminal_zero_volume_official_close_beats_last_traded_close(self):
        # Reproduces 688129.SH closing-price semantics without real prices.
        rows = minute_day()
        rows[-4]["close"] = 10.2  # 14:57 is last traded, not official close
        for bar in rows[-3:-1]:
            bar.update({"open": 10.2, "high": 10.2, "low": 10.2,
                        "close": 10.2, "volume": 0., "amount": 0.})
        rows[-1].update({"open": 10., "high": 10., "low": 10.,
                         "close": 10., "volume": 0., "amount": 0.})
        accepted = U.normal_qmt_day(rows, CODE, DAY, daily(rows), GATE)
        self.assertEqual(accepted.num_rows, 240)
        self.assertAlmostEqual(accepted["close"][-1].as_py(), 10.)
        self.assertAlmostEqual(accepted["volume"][-1].as_py(), 0.)

    def test_zero_volume_opening_quote_exceeding_daily_high_is_rejected(self):
        # Reproduces 300472.SZ: 09:31 zero-volume quote > official DAY high.
        rows = minute_day()
        rows[1].update({"open": 10.22, "high": 10.22, "low": 10.22,
                        "close": 10.22, "volume": 0., "amount": 0.})
        with self.assertRaisesRegex(ValueError, "extrema exceed official DAY envelope"):
            U.normal_qmt_day(rows, CODE, DAY, daily(rows), GATE)

    def test_zero_volume_bucket_extremum_within_day_envelope_is_rejected(self):
        # DAY high exists later; quote-only high must not poison 09:31-09:35.
        rows = minute_day()
        for bar in rows[1:6]:
            bar["high"] = 10.1
        rows[3].update({"open": 10.2, "high": 10.2, "low": 10.2,
                        "close": 10.2, "volume": 0., "amount": 0.})
        with self.assertRaisesRegex(ValueError, "untraded minute extends traded bucket OHLC"):
            U.normal_qmt_day(rows, CODE, DAY, daily(rows), GATE)

    def test_bad_zero_volume_terminal_close_cannot_pass_using_last_trade(self):
        # Previously traded[-1].close agreed while persisted close disagreed.
        rows = minute_day()
        rows[-1].update({"open": 10.2, "high": 10.2, "low": 10.2,
                         "close": 10.2, "volume": 0., "amount": 0.})
        with self.assertRaisesRegex(ValueError, "materialized OHLC discrepancy: close"):
            U.normal_qmt_day(rows, CODE, DAY, daily(rows), GATE)

    def test_normal_241_grid_is_accepted_without_price_edits(self):
        rows = minute_day()
        accepted = U.normal_qmt_day(rows, CODE, DAY, daily(rows), GATE)
        self.assertEqual(accepted.num_rows, 240)
        self.assertAlmostEqual(accepted["close"][-1].as_py(), 10.)
        self.assertAlmostEqual(accepted["high"][0].as_py(), 10.2)


if __name__ == "__main__":
    unittest.main()
