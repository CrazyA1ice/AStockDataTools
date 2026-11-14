"""Offline public Sina JSON/JSONP and Tencent fallback fail-closed tests."""
import importlib.util
from datetime import date
from pathlib import Path
import json
import sys
import tempfile
import unittest
from urllib.error import URLError
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location(
    "qmt_241_public_minute_recovery_probe",
    HERE/"qmt_241_public_minute_recovery_probe.py")
R=importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
from test_qmt_eltdx_auction_241_probe import sample


def rows(day="2026-10-16"):
    return [{"day":day+" 09:30:00","open":"10.2","high":"10.2",
            "low":"10.2","close":"10.2","volume":"100"},
            {"day":day+" 09:31:00","open":"10.1","high":"10.1",
             "low":"10.1","close":"10.1","volume":"150"}]


def q_t():
    d,q,t=sample()
    shift=(date(2026,10,16)-d).days*86400000
    for bar in (*q,*t):bar["ts"]+=shift
    q[0].update(open=10.2,high=10.2,low=10.2,close=10.2)
    t[0].update(open=10.2,high=10.2,low=10.,close=10.1)
    return q,t


class Tests(unittest.TestCase):
    def test_approved_source_alternates(self):
        sina=R.requests_for("sina")
        tencent=R.requests_for("tencent")
        self.assertEqual(len(sina),2)
        self.assertIn("datalen=1970",sina[0][1])
        self.assertIn("json_v2.php",sina[1][1])
        self.assertIn("proxy.finance.qq.com",tencent[0][1])
        self.assertIn("m1%2C%2C8000",tencent[0][1])
        self.assertIn("web.ifzq.gtimg.cn",tencent[1][1])

    def test_sina_correct_jsonp_and_json_array_are_parsed(self):
        payload=json.dumps(rows())
        for form in ("cache=("+payload+");",payload,
                     "jsonp=("+payload+")"):
            parsed,meta=R.parse_sina(form)
            self.assertEqual(meta["parsed"],2)
            self.assertEqual(parsed[1]["minute"],571)
        with self.assertRaisesRegex(ValueError,"NONARRAY"):
            R.parse_sina("<!doctype html><title>403</title>")
        with self.assertRaisesRegex(ValueError,"NONARRAY"):
            R.parse_sina("null")

    def test_tencent_proxy_first_tls_failure_second_valid_no_date(self):
        calls=[]
        def fake(url):
            calls.append(url)
            if len(calls)==1:
                raise URLError("SSL TLS disconnect")
            return json.dumps({"data":{"sh688001":{"m1":[
                ["202611131400","10","10","10","10","200","2000"]]}}})
        chosen,attempts=R.test_api(provider="tencent",fetcher=fake)
        self.assertEqual(len(calls),2)
        self.assertEqual(attempts[0]["status"],"NETWORK_TLS_OR_TRANSPORT")
        self.assertEqual(attempts[1]["status"],"HISTORY_RECEIVED_BUT_TARGET_ABSENT")
        self.assertEqual(chosen[1],"tencent_direct_800")

    def test_first_successful_target_date_avoids_redundant_public_request(self):
        called=[]
        def fake(url):
            called.append(url)
            return "Sina=("+json.dumps(rows())+");"
        chosen,attempts=R.test_api(provider="sina",fetcher=fake)
        self.assertEqual(len(called),1)
        self.assertEqual(attempts[0]["status"],"TARGET_DATE_IN_HISTORY")
        self.assertEqual(chosen[1],"sina_jsonp_1970")

    def test_public_source_metadata_does_not_print_raw_ohlc_values(self):
        q,t=q_t()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"eltdx_1m_probe"/"20261014_20261112"
            source=folder/"source_parquet"/"688001_SH.parquet"
            source.parent.mkdir(parents=True)
            pq.write_table(pa.Table.from_pylist(t,schema=R.P.PRIVATE_SCHEMA),source)
            sha=R.L.hash_file(source)
            called=[]
            def fake(url):
                called.append(url)
                if "sina.cn" in url:
                    return "Sina=("+json.dumps(rows())+");"
                raise URLError("TLS disconnected")
            logs=[]
            with patch.object(R.X,"WORK",folder.parent),\
                 patch.object(R.P,"BASE",root),\
                 patch.object(R.X,"verified_cache",return_value={
                     "source_sha256":sha}),\
                 patch.object(R.X,"read_qmt_source",return_value=(
                     q,"qmt-stable-fixture")):
                result=R.run(fetcher=fake,logger=logs.append)
                self.assertEqual(len(logs),3)
                self.assertEqual(result["stocks"],1)
                self.assertEqual(len(called),3)
                self.assertEqual(result["source_statuses"][
                    "HIGH_CANDIDATE_MATCHES_QMT_AND_DIFFERS_MERGED"],1)
                self.assertFalse(result["production_merge_authorized"])
                self.assertFalse(list(root.rglob("*.json")))
                source.write_bytes(source.read_bytes()+b"tamper")
                with self.assertRaisesRegex(ValueError,"SHA"):
                    R.run(fetcher=lambda u:(_ for _ in ()).throw(
                        AssertionError("Should not connect")),logger=lambda _:None)

    def test_all_network_failures_are_not_claimed_to_be_historical_absence(self):
        _,attempts=R.test_api(provider="tencent",
                            fetcher=lambda url:(_ for _ in ()).throw(
                                URLError("SSL unexpected EOF")))
        self.assertEqual(len(attempts),2)
        self.assertTrue(all(a["status"]=="NETWORK_TLS_OR_TRANSPORT"
                            for a in attempts))


if __name__=="__main__":unittest.main()
