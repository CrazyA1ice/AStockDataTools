"""Offline deep-TDX minute source tests; do not require QMT/pytdx network."""
from datetime import date,datetime,timedelta
from pathlib import Path
import importlib.util
import tempfile
import sys
import unittest

import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location("qmt_tdx_1m_depth",HERE/"qmt_tdx_1m_depth.py")
D=importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


def grid(day):
    return [datetime(day.year,day.month,day.day,h,m,tzinfo=D.CN)
            for h,m in sorted(D.P.GRID)]


def qmt_rows(day=date(2026,10,14)):
    return [{"ts":int(dt.timestamp()*1000),"symbol":"SH600000",
             "open":10.,"high":10.02,"low":9.99,"close":10.01,
             "volume":100.,"amount":10000.} for dt in grid(day)]


def tdx_240(day=date(2026,10,14),*,shift=0):
    slots=grid(day)[1:]
    return [{"ts":int((x+timedelta(minutes=shift)).timestamp()*1000),
             "symbol":"SH600000","open":10.,"high":10.02,
             "low":9.99,"close":10.01,
             "volume":100.,"amount":10000.} for x in slots]


class FakeAPI:
    def __init__(self,pages):
        self.pages=pages
        self.requests=[]
    def connect(self,ip,port,time_out):
        return True
    def disconnect(self):pass
    def get_security_bars(self,category,market,code,start,count):
        self.requests.append((category,market,code,start,count))
        return self.pages.get(start,[])


def raw_page(day):
    return [{"datetime":x.strftime("%Y-%m-%d %H:%M"),"open":10.,
             "high":10.02,"low":9.99,"close":10.01,
             "vol":100.,"amount":10000.} for x in grid(day)[1:]]


class TdxTests(unittest.TestCase):
    def test_qmt_241_tdx_240_exact_240_minute_comparison(self):
        report=D.score_day(qmt_rows(),tdx_240())
        self.assertEqual(report["status"],"MATCHED_1MIN_OHLCVA")
        self.assertEqual(report["compared"],240)
        self.assertEqual(report["tdx_to_qmt_time_offset_ms"],0)
        self.assertEqual(report["qmt_only_count"],1)
        self.assertEqual(report["volume_factor"]["factor_tdx_to_qmt"],1.)

    def test_native_start_end_one_minute_alignment_diagnostic(self):
        report=D.score_day(qmt_rows(),tdx_240(shift=-1))
        self.assertEqual(report["tdx_to_qmt_time_offset_ms"],60000)
        self.assertEqual(report["status"],"MATCHED_1MIN_OHLCVA")

    def test_date_by_date_amount_mismatch_is_not_silent_success(self):
        source=tdx_240()
        for row in source:
            row["amount"]*=2.
        report=D.score_day(qmt_rows(),source)
        self.assertEqual(report["status"],"MINUTE_SOURCE_DIFFERENCE_REVIEW")
        self.assertEqual(report["amount_factor"]["factor_tdx_to_qmt"],.5)
        self.assertLess(report["amount_minute_raw_fit"],.2)

    def test_normalizer_rejects_bad_ohlc_and_normalizes_denormal(self):
        stamp=datetime(2026,10,14,9,31,tzinfo=D.CN)
        source=[{"datetime":stamp.strftime("%Y-%m-%d %H:%M"),
                "open":10.,"high":10.01,"low":9.99,"close":10.,
                "vol":5.877e-39,"amount":5.877e-39}]
        parsed=D.normalized_tdx(source,"600000.SH")
        self.assertEqual(parsed[0]["volume"],0.)
        self.assertEqual(parsed[0]["amount"],0.)
        source[0]["close"]=12.
        with self.assertRaisesRegex(ValueError,"Invalid TDX"):
            D.normalized_tdx(source,"600000.SH")

    def test_backward_pagination_reaches_window_without_320_bar_limit(self):
        first=date(2026,10,14)
        # Dense synthetic 6-day historical pages, newest first.
        data=[]
        for k in range(6):
            data+=raw_page(first+timedelta(days=k))
        # Service pages end up ascending within each page, latest page requested at 0.
        pages={}
        for n in range(0,len(data),800):
            pages[n]=data[max(0,len(data)-n-800):len(data)-n]
        fake=FakeAPI(pages)
        client=D.TdxPages(client_factory=lambda:fake,pause=0,sleep=lambda s:None)
        rows,info=client.fetch("600000.SH",start=first,end=first+timedelta(days=5))
        self.assertEqual(len(rows),6*240)
        self.assertGreater(info["pages"],1)
        self.assertTrue(all(x[0]==8 for x in fake.requests))
        self.assertEqual(fake.requests[0][-1],800)
        client.close()

    def test_explicit_source_sha_and_receipt_reuse(self):
        rows=tdx_240()
        days={"2026-10-14":D.score_day(qmt_rows(),rows)}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            doc=D.private_save_stock(root,"600000.SH",rows,days,
                                     {"pages":1,"source_endpoint":"fake"},"fp")
            self.assertEqual(D.reuse_stock(root,"600000.SH","fp")["sha256"],doc["sha256"])
            with self.assertRaisesRegex(ValueError,"existing|Existing"):
                D.private_save_stock(root,"600000.SH",rows,days,{},"fp")
            with (root/"source_parquet"/"600000_SH.parquet").open("ab") as f:
                f.write(b"TAMPER")
            with self.assertRaisesRegex(ValueError,"SHA"):
                D.reuse_stock(root,"600000.SH","fp")

    def test_source_reuse_fails_on_changed_plan(self):
        rows=tdx_240()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            D.private_save_stock(root,"600000.SH",rows,{},{},"plan-a")
            with self.assertRaisesRegex(ValueError,"version mismatch"):
                D.reuse_stock(root,"600000.SH","plan-b")

if __name__=="__main__":
    unittest.main()
