"""Tencent genuine 1-minute source from upstream a-stock-data, no guessed amount."""
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.parse

import pyarrow.parquet as pq

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tencent_m1 as T

def response(symbol="SH600000",*,rows=None):
    if rows is None:
        rows=[
            ["202611110930","9.99","10.00","10.01","9.98","100","0","12.30"],
            ["202611110931","10.00","10.01","10.02","9.99","120","0","13.50"],
            ["202611111301","10.02","10.03","10.04","10.01","50","0","14.40"],
        ]
    return json.dumps({"code":0,"data":{symbol.lower():{"m1":rows}}}).encode()

class TencentMinuteSource(unittest.TestCase):
    def test_genuine_m1_endpoint_matches_upstream_and_count(self):
        url=T.url_for("SH600000")
        self.assertIn("/appstock/app/kline/mkline",url)
        self.assertEqual(
            urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["param"],
            ["sh600000,m1,,320"])
        with self.assertRaisesRegex(ValueError,"1..320"):
            T.url_for("SH600000",count=800)
        with self.assertRaisesRegex(ValueError,"no Beijing"):
            T.url_for("BJ920021")

    def test_exact_open_high_low_close_not_eastmoney_trend(self):
        rows=T.decode(response(),"SH600000")
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]["open"],9.99)
        self.assertEqual(rows[0]["close"],10.00)
        self.assertEqual(rows[0]["high"],10.01)
        self.assertEqual(rows[0]["low"],9.98)
        self.assertEqual(rows[0]["source_volume"],100)
        self.assertEqual(rows[0]["turnover_rate_basis_points"],12.30)
        self.assertEqual(rows[2]["local_time"],"13:01")

    def test_share_vs_lot_semantics_for_star_and_main_board(self):
        self.assertEqual(T.decode(response("SH688981"),"SH688981")[0][
            "source_volume_unit"],"shares")
        self.assertEqual(T.decode(response("SH689009"),"SH689009")[0][
            "source_volume_unit"],"shares")
        self.assertEqual(T.decode(response("SH600000"),"SH600000")[0][
            "source_volume_unit"],"lots_100_shares")
        self.assertEqual(T.decode(response("SZ000001"),"SZ000001")[0][
            "source_volume_unit"],"lots_100_shares")

    def test_fail_on_wrong_symbol_even_though_market_price_valid(self):
        with self.assertRaisesRegex(ValueError,"wrong stock"):
            T.decode(response("SZ000001"),"SH600000")

    def test_duplicate_minute_time_refused(self):
        src=json.loads(response())
        src["data"]["sh600000"]["m1"].append(
            src["data"]["sh600000"]["m1"][0])
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            T.decode(json.dumps(src).encode(),"SH600000")

    def test_real_1m_traded_record_but_no_amount_column_in_private_arrow(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw=response()
            inputs=[]
            def requester(url):
                inputs.append(url)
                return raw
            report=T.collect("SH600000",work=Path(tmp),requester=requester,
                             hosts=T.HOSTS[:1],logger=lambda _:None)
            self.assertEqual(len(inputs),1)
            self.assertEqual(report["count"],3)
            self.assertEqual(report["status"],"TENCENT_REAL_M1_OHLCV_NO_AMOUNT")
            self.assertFalse(report["amount_cny_available"])
            self.assertFalse(report["full_1min_ohlcva_certified"])
            self.assertFalse(report["current_market_parquet_modified"])
            self.assertEqual(hashlib.sha256(
                Path(report["source_json_path"]).read_bytes()).hexdigest(),
                report["source_sha256"])
            data=pq.read_table(report["ohlcv_only_parquet_path"])
            self.assertEqual(data.num_rows,3)
            self.assertNotIn("amount",data.column_names)
            self.assertNotIn("turnover_rate_basis_points",data.column_names)
            self.assertEqual(data["close"][1].as_py(),10.01)
            again=T.collect("SH600000",work=Path(tmp),requester=requester,
                            hosts=T.HOSTS[:1],logger=lambda _:None)
            self.assertEqual(again["ohlcv_only_parquet_sha256"],
                             report["ohlcv_only_parquet_sha256"])

    def test_request_failover_to_second_host(self):
        record=response()
        attempts=[]
        def requester(url):
            attempts.append(url)
            if len(attempts)==1:
                raise ConnectionResetError("simulated upstream reset")
            return record
        with tempfile.TemporaryDirectory() as tmp:
            proof=T.collect("SH600000",work=Path(tmp),requester=requester,
                            hosts=T.HOSTS[:2],pause=0,logger=lambda _:None)
        self.assertEqual(len(attempts),2)
        self.assertIn(T.HOSTS[1],proof["source_url"])

    def test_short_invalid_row_or_zero_close_fails(self):
        raw=response(rows=[["202611110931","10","10.1"]])
        with self.assertRaisesRegex(ValueError,"missing timestamp"):
            T.decode(raw,"SH600000")
        raw=response(rows=[
            ["202611110931","10","0","10.1","9.9","100"]])
        with self.assertRaisesRegex(ValueError,"price/volume invalid"):
            T.decode(raw,"SH600000")

    def test_1m_cannot_hide_13_01_open_semantics_or_auction(self):
        bars=T.decode(response(),"SH600000")
        self.assertEqual(bars[0]["local_time"],"09:30")
        self.assertEqual(bars[2]["local_time"],"13:01")
        self.assertNotEqual(bars[2]["open"],bars[2]["close"])

if __name__=="__main__":
    unittest.main()
