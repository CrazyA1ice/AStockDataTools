"""Offline bounded source-only A-share minute candidate batch and resume."""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import minute_batch as B
import local_layout as L

def fixture(root):
    folder=root/"AllCycleAStockData"
    for period in L.PERIODS:
        (folder/period).mkdir(parents=True,exist_ok=True)
    # 2026-11-11 at Shanghai 9:30 AM, 2,005 unique equities.
    ts=int(datetime(2026,11,11,9,30,tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)
    syms=[f"SH{600000+x:06}" for x in range(2005)]
    schema=pa.schema([("ts",pa.int64()),("symbol",pa.string())])
    pq.write_table(pa.table({"ts":[ts]*len(syms),"symbol":syms},schema=schema),
                   folder/"day"/"2026-11.parquet")
    return syms

class MinuteBatchPilot(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root=Path(td.name)/"stock"
        self.work=Path(td.name)/"work"
        self.work.mkdir()
        self.symbols=fixture(self.root)
        self.progress=self.work/"progress.json"

    def accepted(self,*args,**kwargs):
        return {"status":"PROBE_COMPLETE_CANDIDATE_ONLY","failed":[]}

    def test_one_minute_raw_trend_and_four_real_kline_candidates_count_as_cached_only(self):
        stock="SH600000"
        payload={"status":"PROBE_PARTIAL_NOT_MERGED","periods":{
            p:{stock:{"status":("SOURCE_DOWNLOADED_BUT_OHLCVA_UNVERIFIED"
                                  if p=="1min" else "CANDIDATE_ONLY_NOT_MERGED"),
                      "reason":("EASTMONEY_TRENDS2_NOT_OHLCVA source trend not Kline"
                                if p=="1min" else ""),
                      "raw_source_sha256":"a"*64}}
            for p in B.PERIODS}}
        self.assertTrue(B.source_package_cached(payload,stock))
        payload["periods"]["5min"][stock]["status"]="UNAVAILABLE_OR_UNVERIFIED"
        self.assertFalse(B.source_package_cached(payload,stock))
        payload["periods"]["5min"][stock]["status"]="CANDIDATE_ONLY_NOT_MERGED"
        payload["periods"]["1min"][stock]["reason"]="Bad 1min source market identity"
        self.assertFalse(B.source_package_cached(payload,stock))

    def test_universe_uses_actual_day_month_not_untrusted_stock_names(self):
        day,stocks=B.active_market_symbols(self.root)
        self.assertEqual(day,date(2026,11,11))
        self.assertEqual(stocks,self.symbols)

    def test_resumes_multiple_batches_without_redownloaded_accepted_stock(self):
        requested=[]
        def sample(symbols,**kwargs):
            requested.extend(symbols)
            return self.accepted()
        with patch.object(B,"read_state",return_value={"days":{"2026-11-11":{}}}):
            first=B.run(self.root,limit=3,collector=sample,
                        progress=self.progress,logger=lambda _:None)
            second=B.run(self.root,limit=2,collector=sample,
                         progress=self.progress,logger=lambda _:None)
        self.assertEqual(first["current_completed_stocks"],3)
        self.assertEqual(second["current_completed_stocks"],5)
        self.assertEqual(len(requested),5)
        self.assertEqual(len(set(requested)),5)
        self.assertFalse(second["market_files_modified"])
        self.assertFalse(second["complete_full_market_minute_coverage_verified"])
        self.assertTrue(self.progress.exists())

    def test_candidate_not_approved_on_partial_5period_error(self):
        def failure(symbols,**kwargs):
            return {"status":"PROBE_PARTIAL_NOT_MERGED",
                    "failed":[{"symbol":symbols[0],"period":"5min"}]}
        with patch.object(B,"read_state",return_value={"days":{"2026-11-11":{}}}):
            result=B.run(self.root,limit=1,collector=failure,
                         progress=self.progress,logger=lambda _:None)
        self.assertEqual(result["current_completed_stocks"],0)
        self.assertEqual(len(result["failed_stock_symbols"]),1)
        self.assertFalse(result["complete_full_market_minute_coverage_verified"])

    def test_previous_stock_universe_sha_change_fails(self):
        with patch.object(B,"read_state",return_value={"days":{"2026-11-11":{}}}):
            B.run(self.root,limit=1,collector=self.accepted,
                  progress=self.progress,logger=lambda _:None)
            saved=json.loads(self.progress.read_text(encoding="utf-8"))
            saved["stock_universe_sha256"]="z"*64
            self.progress.write_text(json.dumps(saved),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"changed"):
                B.run(self.root,limit=1,collector=self.accepted,
                      progress=self.progress,logger=lambda _:None)

    def test_stop_before_network_does_not_claim_completion(self):
        with patch.object(B,"read_state",return_value={"days":{"2026-11-11":{}}}):
            with patch.object(B,"collect",side_effect=AssertionError("no download")):
                result=B.run(self.root,limit=4,stop=lambda:True,
                             progress=self.progress,logger=lambda _:None)
        self.assertEqual(result["current_completed_stocks"],0)

if __name__=="__main__":
    unittest.main()
