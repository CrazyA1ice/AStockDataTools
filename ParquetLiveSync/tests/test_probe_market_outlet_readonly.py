"""Read-only market outlet probe: no QMT downloads, subscription or data writes."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import unittest

import probe_market_outlet_readonly as M


NOW = datetime(2026, 11, 18, 9, 42, tzinfo=M.CN)
TS = int(datetime(2026, 11, 18, 9, 41, tzinfo=M.CN).timestamp() * 1000)


class FakeFrame:
    columns = ["time", "close"]
    def __init__(self, stamp):
        self.stamp = stamp
    def __len__(self):
        return 1
    def __getitem__(self, key):
        return self
    def tolist(self):
        return [self.stamp]


class FakeXt:
    def __init__(self, stamp=TS):
        self.stamp = stamp
        self.calls = []
    def get_full_tick(self, symbols):
        self.calls.append("get_full_tick")
        return {symbol: {"time": self.stamp, "lastPrice": 12.5}
                for symbol in symbols}
    def get_market_data_ex(self, **kwargs):
        self.calls.append("get_market_data_ex")
        if kwargs["period"] != "1m" or kwargs["count"] > 5:
            raise AssertionError("Unexpected wide/full history request")
        return {symbol: FakeFrame(self.stamp)
                for symbol in kwargs["stock_list"]}
    def __getattr__(self, key):
        if key.startswith("download") or key.startswith("subscribe"):
            raise AssertionError("Read-only probe requested modifying QMT operation")
        raise AttributeError(key)


class OutletProbeTests(unittest.TestCase):
    def test_current_quotes_and_minute_observed_without_writes(self):
        xt = FakeXt()
        out = M.probe(xt, now=NOW, sources={
            "eltdx": lambda symbol, day: [{"ts": TS}],
            "tencent": lambda symbol, day: [{"ts": TS}],
        })
        self.assertTrue(out["qmt_live_quote_observed"])
        self.assertTrue(out["qmt_local_minute_observed"])
        self.assertFalse(out["daily_closed_bar_validated"])
        self.assertEqual(out["independent_sources"]["eltdx"]["status"],
                         "TODAY_SAMPLE_AVAILABLE")
        self.assertEqual(out["independent_sources"]["tencent"]["status"],
                         "TODAY_SAMPLE_AVAILABLE")
        self.assertEqual(xt.calls.count("get_full_tick"), 1)
        self.assertEqual(xt.calls.count("get_market_data_ex"), 2)

    def test_stale_quote_cannot_prove_live(self):
        stale = int(datetime(2026, 11, 17, 14, 0, tzinfo=M.CN).timestamp() * 1000)
        out = M.probe(FakeXt(stamp=stale), now=NOW, sources={})
        self.assertFalse(out["qmt_live_quote_observed"])
        self.assertFalse(out["qmt_local_minute_observed"])
        self.assertEqual(out["qmt"]["600000.SH"]["tick"]["status"], "NOT_TODAY")

    def test_probe_unavailable_independent_does_not_forge_success(self):
        def unavailable(*args):
            raise OSError("source unavailable")
        out = M.probe(FakeXt(), now=NOW, sources={"eltdx": unavailable})
        self.assertEqual(out["independent_sources"]["eltdx"]["status"], "PROBE_FAILED")
        self.assertTrue(out["qmt_live_quote_observed"])

    def test_auction_is_separate_from_closed_daily_market(self):
        xt = FakeXt()
        out = M.probe(xt, now=datetime(2026, 11, 18, 9, 28, tzinfo=M.CN), sources={})
        self.assertEqual(out["continuous_auction_or_market"], "PRE_CONTINUOUS_OR_AUCTION")
        self.assertFalse(out["daily_closed_bar_validated"])


if __name__ == "__main__":
    unittest.main()
