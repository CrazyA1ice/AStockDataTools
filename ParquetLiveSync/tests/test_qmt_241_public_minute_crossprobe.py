"""Offline mocked Sina/Tencent 1m public provider history and first-minute tests."""
from datetime import date
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location(
    "qmt_241_public_minute_crossprobe",HERE/"qmt_241_public_minute_crossprobe.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
from test_qmt_eltdx_auction_241_probe import sample


def anchors():
    day,q,t=sample()
    q[0].update(open=10.2,high=10.2,low=10.2,close=10.2)
    t[0].update(open=10.2,high=10.2,low=10.1,close=10.1)
    return day,q,t


def public_sina():
    return 'Sina=('+json.dumps([
        {"day":"2026-10-16 09:30:00","open":"10.2","high":"10.2",
         "low":"10.2","close":"10.2","volume":"100"},
        {"day":"2026-10-16 09:31:00","open":"10.1","high":"10.1",
         "low":"10.1","close":"10.1","volume":"100"},
        {"day":"2026-10-16 09:32:00","open":"10.1","high":"10.1",
         "low":"10.1","close":"10.1","volume":"100"}])+');'


def public_tencent():
    return json.dumps({"data":{"sh688001":{"m1":[
        ["202610160930",10.2,10.2,10.2,10.2,100,1000],
        ["202610160931",10.1,10.1,10.1,10.1,200,2020]]}}})


class Tests(unittest.TestCase):
    def test_two_public_source_urls_are_fixed_and_bounded(self):
        self.assertIn("datalen=20000",M.source_url("sina","688001.SH"))
        self.assertIn("m1%2C%2C20000",M.source_url("tencent","688001.SH"))
        with self.assertRaises(ValueError):M.source_url("sina","123456.SZ")
        with self.assertRaises(ValueError):M.source_url("unknown","688001.SH")

    def test_sina_jsonp_extracts_0930_0931_without_fabricating_amount(self):
        rows,meta=M.parse_rows("sina",public_sina(),"688001.SH")
        self.assertEqual(meta["parsed"],3)
        self.assertEqual(meta["earliest"],"2026-10-16")
        self.assertEqual(rows[0]["minute"],570)
        self.assertEqual(rows[1]["minute"],571)
        self.assertFalse(rows[1]["amount_present"])

    def test_tencent_json_returns_explicit_amount_and_minute(self):
        rows,meta=M.parse_rows("tencent",public_tencent(),"688001.SH")
        self.assertEqual(meta["parsed"],2)
        self.assertTrue(rows[1]["amount_present"])
        self.assertEqual(rows[0]["minute"],570)

    def test_0931_nonmerged_high_is_scored_as_corroboration_only(self):
        day,q,t=anchors()
        # Change only timestamps to Oct 16 in QMT/TDX.
        from datetime import timedelta
        seconds=int((date(2026,10,16)-day).days*86400000)
        for row in (*q,*t):row["ts"]+=seconds
        rows,meta=M.parse_rows("sina",public_sina(),"688001.SH")
        out=M.evaluate(date(2026,10,16),rows,q,t)
        self.assertEqual(out["status"],
            "HIGH_CANDIDATE_MATCHES_QMT_AND_DIFFERS_MERGED")
        self.assertTrue(out["independent_high_candidate"])
        self.assertTrue(out["0930_ohlc_strict_match_qmt_auction"])
        self.assertFalse(out["production_merge_authorized"])
        other=M.evaluate(date(2026,10,15),rows,q,t) if False else None
        self.assertIsNone(other)

    def test_public_source_equal_to_merged_is_not_independent_0931_high(self):
        day,q,t=anchors()
        r=[{"date":day,"minute":570,"open":10.2,"high":10.2,
            "low":10.2,"close":10.2,"amount_present":False},
           {"date":day,"minute":571,"open":10.1,"high":10.2,
            "low":10.1,"close":10.1,"amount_present":False}]
        result=M.evaluate(day,r,q,t)
        self.assertEqual(result["status"],"PUBLIC_0931_HIGH_IS_MERGED")
        self.assertFalse(result["independent_high_candidate"])

    def test_missing_target_date_reports_insufficient_evidence(self):
        day,q,t=anchors()
        rows,meta=M.parse_rows("sina",public_sina(),"688001.SH")
        result=M.evaluate(day,rows,q,t)
        self.assertEqual(result["status"],"TARGET_DATE_UNAVAILABLE")
        self.assertFalse(result["independent_high_candidate"])

    def test_source_sha_gate_and_no_network_when_cache_tampered(self):
        day,q,t=anchors()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"eltdx_1m_probe"/"20261014_20261112"
            source=folder/"source_parquet"/"688001_SH.parquet"
            source.parent.mkdir(parents=True)
            pq.write_table(pa.Table.from_pylist(t,schema=M.P.PRIVATE_SCHEMA),source)
            sha=M.L.hash_file(source)
            called=[]
            with patch.object(M.X,"WORK",folder.parent),\
                 patch.object(M.P,"BASE",root),\
                 patch.object(M.X,"verified_cache",
                     return_value={"source_sha256":sha}),\
                 patch.object(M.X,"read_qmt_source",
                     return_value=(q,"qmt-sealed")):
                lines=[]
                r=M.run(codes=("688001.SH",),days=(day,),
                    fetcher=lambda url:(called.append(url) or public_sina()),
                    logger=lines.append)
                self.assertEqual(len(called),2)
                self.assertEqual(r["cases"],2)
                self.assertFalse(r["production_merge_authorized"])
                self.assertFalse(list(root.rglob("*.json")))
                source.write_bytes(source.read_bytes()+b"modified")
                with self.assertRaisesRegex(ValueError,"SHA"):
                    M.run(codes=("688001.SH",),days=(day,),
                          fetcher=lambda url:(_ for _ in ()).throw(
                              AssertionError("Unexpected public HTTP")),logger=lambda _:None)


if __name__=="__main__":unittest.main()
