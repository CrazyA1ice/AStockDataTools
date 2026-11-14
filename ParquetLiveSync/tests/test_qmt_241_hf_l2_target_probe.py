"""Offline safe Hugging Face 20261016 Level2 discovery/row-group tests."""
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "qmt_241_hf_l2_target_probe",HERE/"qmt_241_hf_l2_target_probe.py")
R=importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


class Meta:
    def __init__(self,ranges,sizes=None):
        self.ranges=ranges
        self.num_row_groups=len(ranges)
        self.schema=SimpleNamespace(names=["wind_code","time","price","volume"])
        self.sizes=sizes or [1000]*len(ranges)
    def row_group(self,n):
        a,b=self.ranges[n]
        class Column:
            def __init__(self,i):
                self.statistics=(SimpleNamespace(has_min_max=True,min=a,max=b)
                                 if i==0 else None)
                self.total_compressed_size=1000
        return SimpleNamespace(num_rows=self.sizes[n],
                               column=lambda idx: Column(idx))


class Tests(unittest.TestCase):
    def test_hf_public_metadata_preflight_does_not_fetch_market(self):
        listing=[
            {"path":"20261016/行情.parquet","type":"file"},
            {"path":"20261016/逐笔成交.parquet","type":"file"},
            {"path":"20261016/逐笔委托.parquet","type":"file"}]
        args=[]
        def fake(url,credential):
            args.append((url,credential))
            return json.dumps(listing)
        with patch.object(R,"token",return_value=None):
            result=R.report_access(fetch=fake,logger=lambda _:None)
        self.assertEqual(result["status"],"TARGET_DAY_BOTH_STREAM_FILES_LISTED")
        self.assertEqual(result["data_rows_downloaded"],0)
        self.assertFalse(result["production_merge_authorized"])
        self.assertIn("tree/main/20261016",args[0][0])
        self.assertIsNone(args[0][1])

    def test_access_denied_separate_from_target_day_missing(self):
        def blocked(url,cred):
            raise HTTPError(url,403,"private gated",None,None)
        with patch.object(R,"token",return_value=None):
            denied=R.report_access(fetch=blocked,logger=lambda _:None)
            nofiles=R.report_access(
                fetch=lambda u,t:json.dumps([]),logger=lambda _:None)
        self.assertEqual(denied["status"],"HF_DATASET_ACCESS_REQUIRES_APPROVAL")
        self.assertEqual(nofiles["status"],"TARGET_DAY_FILES_NOT_LISTED")

    def test_no_token_appears_in_preflight_log_or_uri(self):
        with patch.object(R,"token",return_value="hf_secret_fake_avoid_logging"):
            logs=[]
            response=R.report_access(fetch=lambda url,credential:
                                     json.dumps([{
                                         "path":"20261016/行情.parquet","type":"file"}]),
                                     logger=logs.append)
        self.assertTrue(response["credentials_present"])
        self.assertNotIn("hf_secret_fake_avoid_logging","".join(logs))

    def test_row_group_min_max_stock_pruning(self):
        m=Meta([("000001.SH","600000.SH"),
                ("688000.SH","688001.SH"),
                ("688002.SH","900000.SH")])
        self.assertEqual(R.choose_groups(m,m.schema.names),[1])
        self.assertEqual(R.compressed_budget(m,[1],m.schema.names),4000)

    def test_fail_closed_on_missing_stats_missing_column_or_high_cost(self):
        m=Meta([("000001.SH","688001.SH")]*6)
        with self.assertRaisesRegex(ValueError,"Too many"):
            R.choose_groups(m,m.schema.names)
        m=Meta([("688001.SH","688001.SH")])
        with self.assertRaisesRegex(ValueError,"Missing expected"):
            R.compressed_budget(m,[0],["symbol"])
        with self.assertRaisesRegex(ValueError,"bounded"):
            R.compressed_budget(m,[0],["price"],max_bytes=100)
        with self.assertRaisesRegex(ValueError,"row cap"):
            R.compressed_budget(Meta([("688001.SH","688001.SH")],
                                     [R.MAX_ROWS_PER_STREAM+1]),[0],["price"])

    def test_exchange_millisecond_clock(self):
        self.assertEqual(R.clock(93001250),9*3600000+30*60000+1250)
        self.assertEqual(R.clock(92500010),9*3600000+25*60000+10)
        with self.assertRaisesRegex(ValueError,"Invalid"):
            R.clock(93600010)
        with self.assertRaisesRegex(ValueError,"Invalid"):
            R.clock(1000000000)

    def test_trade_cancel_exclusion_auction_and_regular(self):
        trades=[
            {"wind_code":"688001.SH","date":20261016,"time":92500010,
             "trade_id":1,"trade_code":"0","price":102000,"volume":10000},
            {"wind_code":"688001.SH","date":20261016,"time":93000150,
             "trade_id":2,"trade_code":"0","price":101000,"volume":100},
            {"wind_code":"688001.SH","date":20261016,"time":93020000,
             "trade_id":3,"trade_code":"0","price":100500,"volume":100},
            {"wind_code":"688001.SH","date":20261016,"time":93025000,
             "trade_id":4,"trade_code":"C","price":99000,"volume":999999},
            {"wind_code":"688001.SH","date":20261016,"time":93040000,
             "trade_id":5,"trade_code":"0","price":101200,"volume":100},
            {"wind_code":"600000.SH","date":20261016,"time":93045000,
             "trade_id":6,"trade_code":"0","price":111100,"volume":100},
        ]
        out=R.trade_evidence(trades)
        self.assertEqual(out["status"],"OBSERVED_0930_REGULAR_TRADES")
        self.assertEqual(out["regular"]["count"],3)
        self.assertEqual(out["regular"]["shares"],300)
        self.assertAlmostEqual(out["regular"]["high"],10.12)
        self.assertAlmostEqual(out["regular"]["low"],10.05)
        self.assertEqual(out["auction"]["count"],1)
        self.assertEqual(out["event_code_counts"],{"0":4,"C":1})
        with self.assertRaisesRegex(ValueError,"Unrecognized"):
            R.trade_evidence([dict(trades[1],trade_code="T")])

    def test_fails_if_data_date_wrong_or_target_stock_absent(self):
        with self.assertRaisesRegex(ValueError,"Wrong trading day"):
            R.trade_evidence([{"wind_code":"688001.SH","date":20261015,
                "time":93000100,"trade_code":"0","price":100000,"volume":100}])
        out=R.trade_evidence([])
        self.assertEqual(out["status"],"NO_0930_REGULAR_TRADES")

if __name__=="__main__":unittest.main()
