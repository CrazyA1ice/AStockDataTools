"""Offline eltdx Rust Kline integration tests: real 1m pages, SHA and QMT."""
from datetime import date,datetime,timedelta
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location("qmt_eltdx_1m_probe",HERE/"qmt_eltdx_1m_probe.py")
X=importlib.util.module_from_spec(spec)
spec.loader.exec_module(X)


def make_bar(dt,base=10.0,vol=100.0,amount=10000.):
    return SimpleNamespace(time=dt,open=base,high=base+.02,
          low=base-.02,close=base+.01,volume_wire_value=vol,
          volume_lots=vol/100,amount=amount)


def make_days():
    # Source returns 240 bars on each synthetic trading day.
    data=[]
    for day in (date(2026,10,13),date(2026,10,14),
                date(2026,10,15),date(2026,10,16),date(2026,11,12)):
        for hour,minute in sorted(X.P.GRID):
            if (hour,minute)==(9,30):continue
            dt=datetime(day.year,day.month,day.day,hour,minute,tzinfo=X.P.CN)
            data.append(make_bar(dt,base=10.+minute/10000.,
                   vol=100.+minute,amount=10000.+minute*2))
    return data


class FakeBars:
    def __init__(self,source):
        self.source=source
        self.calls=[]
    def get(self,code,*,period,start,count,adjust,bar_time,include_raw):
        self.calls.append((code,period,start,count,adjust,bar_time,include_raw))
        # Simulate newest-first pages with oldest-first bars within page.
        end=len(self.source)-start
        first=max(0,end-count)
        subset=self.source[first:end] if end>0 else []
        return SimpleNamespace(bars=tuple(subset),count=len(subset))


class FakeClient:
    def __init__(self,source):
        self.bars=FakeBars(source)
    def __enter__(self):return self
    def __exit__(self,*args):return False


class Tests(unittest.TestCase):
    def test_eltdx_provides_actual_ohlcva_and_wire_volume(self):
        stamp=datetime(2026,11,12,9,31,tzinfo=X.P.CN)
        source=make_bar(stamp,vol=1234,amount=98765)
        obj=X.canon_bar(source,"600000.SH")
        self.assertEqual(obj["volume"],1234)
        self.assertEqual(obj["amount"],98765)
        self.assertEqual(obj["symbol"],"SH600000")
        self.assertEqual(X.eltdx_code("000001.SZ"),"sz000001")

    def test_bounded_true_minute_history_paging_until_date_boundary(self):
        fake=FakeClient(make_days())
        rows,meta=X.fetch_history(fake,"600000.SH",max_pages=8)
        self.assertEqual(len(rows),4*240)
        self.assertEqual(meta["dense_days"],4)
        self.assertEqual(meta["source_earliest_day"],"2026-10-13")
        self.assertEqual(meta["target_day_counts"]["2026-11-12"],240)
        self.assertEqual(fake.bars.calls[0][:4],("sh600000","1m",0,800))
        self.assertTrue(all(x[5]=="start" and x[4] is None for x in fake.bars.calls))
        self.assertLessEqual(len(fake.bars.calls),3)

    def test_reject_incomplete_server_history_even_when_some_new_bars_present(self):
        fake=FakeClient(make_days()[480:])
        with self.assertRaisesRegex(ValueError,"too shallow"):
            X.fetch_history(fake,"600000.SH",max_pages=6)

    def test_refuse_non_kline_and_wrong_page_size(self):
        with self.assertRaisesRegex(ValueError,"non-KlineSeries"):
            X.page_rows([], "600000.SH")
        with self.assertRaisesRegex(ValueError,"count/page mismatch"):
            X.page_rows(SimpleNamespace(count=99,bars=[make_days()[0]]),"600000.SH")

    def test_empty_tdx_vs_complete_qmt_is_not_false_positive(self):
        q=[]
        for h,m in sorted(X.P.GRID):
            when=datetime(2026,10,14,hour=h,minute=m,tzinfo=X.P.CN)
            q.append(X.canon_bar(make_bar(when),"600000.SH"))
        t=[x for x in q if datetime.fromtimestamp(x["ts"]/1000,X.P.CN).strftime("%H:%M")!="09:30"]
        proof=X.compare_rows(q,t)
        self.assertEqual(proof["2026-10-14"]["compared"],240)
        self.assertEqual(proof["2026-10-14"]["qmt_only_count"],1)

    def test_private_sources_sha_and_read_only_receipt(self):
        rows=[X.canon_bar(x,"600000.SH") for x in make_days()[:5]]
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            evidence=X.save_private(base,"600000.SH",rows,{"pages":1},{})
            self.assertEqual(evidence["rows"],5)
            self.assertFalse(evidence["market_files_modified"])
            self.assertFalse(evidence["production_merge_authorized"])
            receipt=base/"receipts"/"600000_SH.json"
            self.assertEqual(json.loads(receipt.read_text())["source_sha256"],evidence["source_sha256"])
            with self.assertRaisesRegex(ValueError,"exists or redirected"):
                X.save_private(base,"600000.SH",rows,{},{})

    def test_full_probe_remote_only_synthetic_no_vendor_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            report=X.probe(symbols=("600000.SH",),hosts=("127.0.0.1:7709",),
                           max_hosts=1,remote_only=True,work=Path(temp),
                           client_factory=lambda host:FakeClient(make_days()),
                           log=lambda message:None)
            self.assertEqual(report["summary"]["real_minute_success"],1)
            self.assertEqual(report["summary"]["qmt_minute_compared_stocks"],0)
            self.assertTrue((Path(temp)/"20261014_20261112"/"latest_summary.json").exists())

if __name__=="__main__":
    unittest.main()
