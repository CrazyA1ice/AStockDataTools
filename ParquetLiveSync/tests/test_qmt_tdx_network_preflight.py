"""Synthetic TDX TCP and 1m validation; never opens a real network socket."""
from datetime import datetime,timedelta
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location("qmt_tdx_network_preflight",HERE/"qmt_tdx_network_preflight.py")
N=importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)


def bars(base=datetime(2026,11,12,14,10,tzinfo=N.D.CN),step=1,count=48):
    return [{"datetime":(base+timedelta(minutes=i*step)).strftime("%Y-%m-%d %H:%M"),
             "open":10.0,"high":10.01,"low":9.99,"close":10.0,
             "vol":100.0+i,"amount":10000.0+i*100} for i in range(count)]


class FakeTDX:
    def __init__(self,category=None,broken=False,latest=None):
        self.category=category
        self.broken=broken
        self.latest=latest
        self.calls=[]
    def connect(self,ip,port,time_out=3):
        self.calls.append(("connect",ip,port))
        if self.broken:raise ConnectionError("SYNTHETIC_SOCKET_DOWN")
        return True
    def disconnect(self):
        self.calls.append(("disconnect",))
    def get_security_bars(self,category,market,code,start,count):
        self.calls.append(("bars",category,market,code))
        if category!=self.category:return None
        return self.latest if self.latest is not None else bars()


class PreflightTests(unittest.TestCase):
    def test_real_1m_48_records_and_reject_5m(self):
        stamp=datetime(2026,11,13,10,0,tzinfo=N.D.CN)
        self.assertEqual(N.validate_real_1m(bars(),"600000.SH",stamp)["bar_count"],48)
        with self.assertRaisesRegex(ValueError,"16_TO_48"):
            N.validate_real_1m(bars(count=10),"600000.SH",stamp)
        with self.assertRaisesRegex(ValueError,"1MIN_KLINE_CADENCE"):
            N.validate_real_1m(bars(step=5,count=20),"600000.SH",stamp)

    def test_reject_old_endpoint_and_corrupt_ohlc(self):
        stamp=datetime(2026,11,13,10,0,tzinfo=N.D.CN)
        with self.assertRaisesRegex(ValueError,"STALE"):
            N.validate_real_1m(bars(base=datetime(2026,5,20,14,10,tzinfo=N.D.CN)),
                              "600000.SH",stamp)
        broken=bars()
        broken[3]["low"]=12.
        with self.assertRaisesRegex(ValueError,"Invalid TDX"):
            N.validate_real_1m(broken,"600000.SH",stamp)

    def test_fallback_category7_requires_real_1m_grid(self):
        calls=[]
        def factory():
            index=len(calls)
            api=FakeTDX(category=7)
            calls.append(api)
            return api
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)/"profile.json"
            result=N.probe(hosts=[("192.0.2.20",7709)],client_factory=factory,
                           now=datetime(2026,11,13,10,0,tzinfo=N.D.CN),
                           profile=home,max_hosts=1,logger=lambda x:None)
            self.assertEqual(result["category"],7)
            self.assertEqual(result["status"],"REAL_1MIN_7709_CONFIRMED")
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[0].calls[1][1],8)
            self.assertEqual(calls[1].calls[1][1],7)
            self.assertTrue(home.exists())

    def test_all_real_minute_protocols_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/"profile.json"
            with self.assertRaisesRegex(ConnectionError,"No independently verified"):
                N.probe(hosts=[("192.0.2.20",7709)],client_factory=lambda:FakeTDX(broken=True),
                        now=datetime(2026,11,13,10,0,tzinfo=N.D.CN),
                        profile=target,max_hosts=1,logger=lambda _:None)
            self.assertFalse(target.exists())

    def test_profile_passed_to_minute_provider(self):
        with patch.dict(os.environ,{"ASTOCK_TDX_HOST":"111.229.247.189",
                                    "ASTOCK_TDX_PORT":"7709",
                                    "ASTOCK_TDX_CATEGORY":"7"}):
            client=N.D.TdxPages(client_factory=lambda:FakeTDX(category=7))
            self.assertEqual(client.hosts[0],("111.229.247.189",7709))
            self.assertEqual(client.category,7)

if __name__=="__main__":
    unittest.main()
