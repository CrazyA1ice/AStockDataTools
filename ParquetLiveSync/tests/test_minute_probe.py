"""Offline Eastmoney SH/SZ/BJ 1m and 5/15/30/60 OHLCVA source probe."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import minute_probe as P

def fixture(url):
    from urllib.parse import parse_qs,urlparse
    params=parse_qs(urlparse(url).query)
    code=params["secid"][0].split(".")[-1]
    start="2026-11-11 09:31"
    record=f"{start},10.0,10.5,11.0,9.5,100,150000.00,10.12"
    data={"code":code,"trends":[record]} if "trends2" in url else {
        "code":code,"klines":[record]}
    out={"rc":0,"data":data}
    raw=json.dumps(out).encode()
    return raw,out

class PublicMinuteProbe(unittest.TestCase):
    def test_transient_remote_disconnected_recovers_with_new_request(self):
        from http.client import RemoteDisconnected
        from urllib.parse import urlparse
        _,doc=fixture(P.endpoint("30min","SH600000"))
        payload=json.dumps(doc).encode()
        counters={"attempts":0}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):return False
            def read(self,_max):return payload
        def flaky(req,*,timeout):
            counters["attempts"]+=1
            if counters["attempts"]<=2:
                raise RemoteDisconnected("Remote end closed connection")
            return Response()
        pauses=[]
        raw,result=P.fetch(P.endpoint("30min","SH600000"),
                           retries=4,pause=pauses.append,opener=flaky)
        self.assertEqual(counters["attempts"],3)
        self.assertEqual(len(pauses),2)
        self.assertEqual(raw,payload)
        self.assertEqual(result,doc)

    def test_invalid_public_json_not_retried_or_accepted(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):return False
            def read(self,_max):return b"Not official JSON"
        count=[]
        def invalid(req,*,timeout):
            count.append(1)
            return Response()
        with self.assertRaisesRegex(ValueError,"not plain JSON"):
            P.fetch(P.endpoint("15min","SZ000001"),
                    pause=lambda _:None,opener=invalid,retries=4)
        self.assertEqual(len(count),1)

    def test_prefix_and_beijing_exchange_id(self):
        self.assertEqual(P.secid("SH600000"),"1.600000")
        self.assertEqual(P.secid("SZ000001"),"0.000001")
        self.assertEqual(P.secid("BJ920021"),"0.920021")
        with self.assertRaisesRegex(ValueError,"Invalid symbol"):
            P.parse_symbols("600000")

    def test_all_five_minute_urls_have_amount_and_nofq(self):
        for period in P.PERIODS:
            url=P.endpoint(period,"BJ920021")
            self.assertIn("f57",url)
            self.assertIn("secid=0.920021",url)
            if period=="1min":
                self.assertIn("ndays=5",url)
                self.assertIn("trends2/get",url)
            else:
                self.assertIn("fqt=0",url)
                self.assertIn("kline/get",url)

    def test_ohlcva_real_schema_parse_for_each_period(self):
        for period in ("5min","15min","30min","60min"):
            url=P.endpoint(period,"SH600000")
            _,d=fixture(url)
            data=P.parse_bars(d,period,"SH600000")
            self.assertEqual(len(data),1)
            self.assertEqual(data[0]["amount_yuan"],150000.0)
            self.assertEqual(data[0]["provider_volume"],100.)
            self.assertEqual(data[0]["local_time"],"09:31")
            self.assertEqual(data[0]["symbol"],"SH600000")

    def test_source_1min_is_trend_not_ohlc_even_when_nonzero_prices(self):
        _,data=fixture(P.endpoint("1min","SH600000"))
        with self.assertRaisesRegex(
                ValueError,"EASTMONEY_TRENDS2_NOT_OHLCVA"):
            P.parse_bars(data,"1min","SH600000")

    def test_1min_auction_open_not_reconstructed_from_avg_price(self):
        _,data=fixture(P.endpoint("1min","SH600000"))
        data["data"]["trends"].insert(
            0,"2026-11-06 09:30,0,9.91,9.91,9.91,3771,3737061,9.91")
        with self.assertRaisesRegex(ValueError,"f53 is average price"):
            P.parse_bars(data,"1min","SH600000")

    def test_missing_amount_rejected_without_zero_fill(self):
        _,d=fixture(P.endpoint("5min","SH600000"))
        d["data"]["klines"][0]="2026-11-11 09:35,10,10.5,11,9.5,100"
        with self.assertRaisesRegex(ValueError,"missing"):
            P.parse_bars(d,"5min","SH600000")

    def test_amount_volume_inconsistent_rejected(self):
        _,d=fixture(P.endpoint("5min","SH600000"))
        d["data"]["klines"][0]="2026-11-11 09:35,10,10.5,11,9.5,100,0"
        with self.assertRaisesRegex(ValueError,"Invalid"):
            P.parse_bars(d,"5min","SH600000")

    def test_unsafe_or_duplicate_timestamp_rejected(self):
        _,d=fixture(P.endpoint("15min","SZ000001"))
        d["data"]["klines"].append(d["data"]["klines"][0])
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            P.parse_bars(d,"15min","SZ000001")

    def test_market_identity_check_bj_not_shenzhen(self):
        _,d=fixture(P.endpoint("30min","BJ920021"))
        with self.assertRaisesRegex(ValueError,"differs"):
            P.parse_bars(d,"30min","SZ000001")

    def test_private_sha_pilot_all_five_periods_three_markets_no_production(self):
        with tempfile.TemporaryDirectory() as td:
            events=[]
            result=P.run(work=Path(td)/"minute_source_trials",
                         requester=fixture,pause=0,logger=events.append)
            self.assertEqual(result["status"],"PROBE_PARTIAL_NOT_MERGED")
            self.assertFalse(result["production_full_market_approved"])
            self.assertFalse(result["market_files_modified"])
            self.assertFalse(result["volume_units_certified"])
            self.assertEqual(len(result["periods"]),5)
            self.assertEqual(sum(len(v) for v in result["periods"].values()),15)
            for period,payloads in result["periods"].items():
                for symbol,item in payloads.items():
                    path=Path(item["private_source_file"])
                    self.assertTrue(path.is_file())
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                     item["raw_source_sha256"])
                    if period=="1min":
                        self.assertEqual(
                            item["status"],
                            "SOURCE_DOWNLOADED_BUT_OHLCVA_UNVERIFIED")
                    else:
                        self.assertEqual(item["status"],"CANDIDATE_ONLY_NOT_MERGED")
            self.assertFalse((Path(td)/"AllCycleAStockData").exists())
            self.assertTrue(any("MINUTE_SOURCE_CANDIDATE" in m for m in events))

    def test_real_traded_0931_missing_open_saves_raw_but_never_merged(self):
        with tempfile.TemporaryDirectory() as td:
            url=P.endpoint("1min","SH600000")
            raw,doc=fixture(url)
            doc["data"]["trends"][0]=(
                "2026-11-06 09:31,0,9.88,9.95,9.84,41050,40618125,9.90")
            raw=json.dumps(doc).encode()
            def source(_url):
                return raw,doc
            report=P.run(["SH600000"],periods=("1min",),
                         work=Path(td),requester=source,pause=0,
                         logger=lambda _:None)
            self.assertEqual(report["status"],"PROBE_PARTIAL_NOT_MERGED")
            rec=report["periods"]["1min"]["SH600000"]
            self.assertEqual(rec["status"],"SOURCE_DOWNLOADED_BUT_OHLCVA_UNVERIFIED")
            path=Path(rec["private_source_file"])
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(),raw)
            self.assertFalse(report["market_files_modified"])

    def test_partial_source_failure_cannot_claim_all_markets_updated(self):
        with tempfile.TemporaryDirectory() as td:
            def requester(url):
                if "920021" in url:
                    raise ValueError("BJ source unavailable")
                return fixture(url)
            result=P.run(work=Path(td),requester=requester,
                         periods=("1min","5min"),pause=0,logger=lambda _:None)
            self.assertEqual(result["status"],"PROBE_PARTIAL_NOT_MERGED")
            self.assertEqual(len(result["failed"]),4)
            self.assertFalse(result["market_files_modified"])

    def test_safe_stop_after_first_source_does_not_claim_complete(self):
        with tempfile.TemporaryDirectory() as td:
            count={"i":0}
            def requester(url):
                count["i"]+=1
                return fixture(url)
            result=P.run(work=Path(td),requester=requester,pause=0,
                         stop=lambda:count["i"]>=1,logger=lambda _:None)
            self.assertEqual(result["status"],"STOPPED_INCOMPLETE_TRIAL")
            self.assertEqual(count["i"],1)

if __name__=="__main__":
    unittest.main()
