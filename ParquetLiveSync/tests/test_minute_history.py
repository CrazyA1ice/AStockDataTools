"""Offline public OHLCVA historical date pagination, duplicate/changed source safety."""
from datetime import date,datetime,timedelta
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import minute_history as H

def row(day,hour,minute,close):
    stamp=f"{day} {hour:02}:{minute:02}"
    return f"{stamp},{close},{close},{close},{close},100,100000"

def window_pages(url):
    query=parse_qs(urlparse(url).query)
    end=query.get("end",["20261111"])[0]
    limit=date(int(end[:4]),int(end[4:6]),int(end[6:8]))
    bars=[
        row("2026-09-30",9,35,10.0),
        row("2026-10-14",9,35,11.0),
        row("2026-10-15",9,35,12.0),
        row("2026-10-16",9,35,13.0),
        row("2026-11-11",9,35,14.0),
    ]
    recent=[x for x in bars
            if date.fromisoformat(x[:10])<=limit]
    if limit>=date(2026,11,1):
        recent=recent[-2:]
    else:
        recent=recent[-3:]
    doc={"rc":0,"data":{"code":query["secid"][0][2:],
                        "klines":recent}}
    return json.dumps(doc).encode(),doc

class MinutePageBackfill(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work=Path(temp.name)
        self.start=date(2026,10,14)
        self.end=date(2026,11,11)

    def test_paginates_real_end_back_to_start_and_cache_reuse(self):
        calls=[]
        def requester(url):
            calls.append(parse_qs(urlparse(url).query)["end"][0])
            return window_pages(url)
        proof,bars=H.collect_one("5min","SH600000",self.start,self.end,
                                 root=self.work,requester=requester,pause=0,
                                 logger=lambda _:None)
        self.assertGreaterEqual(len(calls),2)
        self.assertEqual(proof["count"],4)
        self.assertEqual(len(proof["pages"]),2)
        self.assertEqual(proof["covered_days"],
                         ["2026-10-14","2026-10-15","2026-10-16","2026-11-11"])
        self.assertEqual(len(set(x["ts"] for x in bars)),4)
        with patch.object(H,"fetch",side_effect=AssertionError("cache should be reused")):
            same,records=H.collect_one("5min","SH600000",self.start,self.end,
                                       root=self.work,requester=lambda *_:(
                                           1/0),pause=0,logger=lambda _:None)
        self.assertEqual(same["count"],4)
        self.assertEqual(records,bars)
        self.assertFalse(proof["physical_allcycle_parquet_modified"])

    def test_fake_source_ignoring_end_rejected_before_merged_bars(self):
        def wrong(url):
            raw,doc=window_pages(url)
            doc["data"]["klines"].append(row("2026-12-01",9,35,15.))
            raw=json.dumps(doc).encode()
            return raw,doc
        with self.assertRaisesRegex(ValueError,"MINUTE_HISTORY_END_NOT_RESPECTED"):
            H.collect_one("15min","SZ000001",self.start,self.end,
                          root=self.work,requester=wrong,pause=0,logger=lambda _:None)

    def test_one_minute_trend_source_always_denied_as_ohlcva(self):
        with self.assertRaisesRegex(ValueError,"NOT minute OHLCVA"):
            H.collect_one("1min","SH600000",self.start,self.end,
                          root=self.work,requester=lambda *_:(
                              1/0),pause=0,logger=lambda _:None)

    def test_backfill_window_cannot_exceed_safety_boundary(self):
        with self.assertRaisesRegex(ValueError,"<=180"):
            H.collect_one("5min","SH600000",date(2026,1,1),self.end,
                          root=self.work,requester=lambda *_:(
                              1/0),pause=0,logger=lambda _:None)

    def test_tamper_cached_raw_page_refused(self):
        H.collect_one("5min","SH600000",self.start,self.end,
                      root=self.work,requester=window_pages,pause=0,
                      logger=lambda _:None)
        p=self.work/"5min"/"SH600000"/"20261111.json"
        p.write_bytes(b'{"rc":0,"data":{"code":"600000","klines":[]}}')
        with self.assertRaises(ValueError):
            H.collect_one("5min","SH600000",self.start,self.end,
                          root=self.work,requester=window_pages,pause=0,
                          logger=lambda _:None)

    def test_safe_stop_before_source_request(self):
        with self.assertRaises(InterruptedError):
            H.collect_one("60min","BJ920021",self.start,self.end,
                          root=self.work,requester=lambda *_:(
                              1/0),pause=0,stop=lambda:True,logger=lambda _:None)

if __name__=="__main__":
    unittest.main()
