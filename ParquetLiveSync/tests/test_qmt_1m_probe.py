"""Offline contract tests for the source-only QMT 1-minute probe."""
import importlib.util
from datetime import date
from pathlib import Path
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "qmt_1m_probe.py"
spec = importlib.util.spec_from_file_location("qmt_1m_probe", SRC)
qmt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qmt)


class FakeFrame:
    columns = ("open", "high", "low", "close", "volume", "amount")
    def __init__(self, rows):
        self.rows = rows
    def iterrows(self):
        yield from self.rows


def sample(day="20261014", amount=12000):
    return FakeFrame([(day+"093000", {"open":10.0,"high":11.0,"low":9.0,
        "close":10.5,"volume":100.0,"amount":amount})])


class FakeXtdata:
    def __init__(self, frames):
        self.frames=frames
        self.downloads=[]
        self.requests=[]
    def download_history_data(self, *args, **kwargs):
        self.downloads.append((args, kwargs))
    def get_market_data_ex(self, **kwargs):
        self.requests.append(kwargs)
        return {kwargs["stock_list"][0]:self.frames[kwargs["stock_list"][0]]}


class QmtProbeTests(unittest.TestCase):
    def test_code_mapping(self):
        self.assertEqual(qmt.normalize_code("SH600000"), "600000.SH")
        self.assertEqual(qmt.normalize_code("000001.sz"), "000001.SZ")
        with self.assertRaises(ValueError):
            qmt.normalize_code("BJ920021")

    def test_session_and_amount(self):
        rows=qmt.normalize_frame(sample(), "600000.SH",
            date(2026,10,14),date(2026,11,12))
        self.assertEqual(rows[0]["amount"],12000)
        self.assertEqual(rows[0]["datetime_cn"][:10],"2026-10-14")

    def test_reject_invalid_values_and_dates(self):
        with self.assertRaises(ValueError):
            qmt.normalize_frame(sample("20261013"),"600000.SH",date(2026,10,14),date(2026,11,12))
        with self.assertRaises(ValueError):
            qmt.normalize_frame(sample(amount=float("nan")),"600000.SH",
                date(2026,10,14),date(2026,11,12))
        bad=sample()
        bad.rows[0][1]["high"]=9.5
        with self.assertRaises(ValueError):
            qmt.normalize_frame(bad,"600000.SH",date(2026,10,14),date(2026,11,12))

    def test_probe_no_market_write_and_sha_idempotence(self):
        fake=FakeXtdata({"600000.SH":sample(),"000001.SZ":sample()})
        with tempfile.TemporaryDirectory() as d:
            a=qmt.probe(("SH600000","SZ000001"),date(2026,10,14),
                        date(2026,11,12),Path(d),fake)
            b=qmt.probe(("SH600000","SZ000001"),date(2026,10,14),
                        date(2026,11,12),Path(d),fake)
            self.assertEqual([x["sha256"] for x in a],[x["sha256"] for x in b])
            self.assertTrue(all(x["coverage_not_certified"] for x in a))
            self.assertEqual(len(list(Path(d).glob("*.jsonl"))),2)
            self.assertEqual(fake.requests[0]["period"],"1m")
            self.assertFalse(fake.requests[0]["fill_data"])
            self.assertEqual(fake.requests[0]["dividend_type"],"none")

if __name__=="__main__":
    unittest.main()
