"""Offline SHA-bounded two-date independent eltdx->241 holdout tests."""
from datetime import date
import importlib.util
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location(
    "qmt_eltdx_241_cross_day_holdout",
    HERE/"qmt_eltdx_241_cross_day_holdout.py")
H=importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)
from test_qmt_eltdx_opening_ticks_241_probe import stock
from test_qmt_eltdx_source_independent_241_pilot import opening


def fixture(day=date(2026,10,15),*,highlow=True):
    _,q,t,pilot=stock()
    delta=(day-date(2026,10,14)).days*86400000
    for b in (*q,*t):
        b["ts"]+=delta
    q[2]["volume"]=3.
    q[2]["amount"]=3030.
    t[1]["volume"]=300.
    t[1]["amount"]=3030.
    if highlow:
        q[1]["low"]=9.9
        t[0]["low"]=9.9
    for i in range(1,240):
        t[i]["volume"]=q[i+1]["volume"]*100.
    return q,t


def historical(day=date(2026,10,15)):
    f=opening(day)
    f.time_minutes=565
    def item(minute,price,lots,absolute):
        return SimpleNamespace(
            event_kind="trade",time_minutes=minute,
            price=price,volume=lots,
            status_raw=2,is_after_hours_fixed_price=False,
            absolute_index=absolute)
    ticks=(f,item(570,10.1,1.,0),item(570,10.1,1.,1),
           item(571,10.1,1.5,2),item(571,10.1,1.5,3),
           item(570,99.,999,4))
    ticks=list(ticks)
    ticks[-1].status_raw=8
    ticks[-1].event_kind="auction_snapshot"
    return SimpleNamespace(ticks=ticks,count=len(ticks),trading_date=day)


class Tests(unittest.TestCase):
    def test_two_next_day_minute_buckets_have_proven_volume_and_amount(self):
        day=date(2026,10,15)
        q,t=fixture(day)
        auction,rows,count=H.extract_live_page(historical(day),day)
        self.assertEqual(count,{"09:30":2,"09:31":2})
        result=H.per_day(q,t,auction,rows)
        self.assertEqual(result["status"],
            "HOLDOUT_ALL_SIX_STRICTLY_MATCH_SOURCE_CANDIDATE")
        self.assertEqual(result["remaining_239_volume_exact_after_factor_001"],239)
        self.assertTrue(all(v==239 for v in result[
            "remaining_239_ohlc_amount_tolerant_match_counts"].values()))
        self.assertTrue(all(result[
            "minute_label_trades_to_next_kline_evidence"].values()))
        self.assertEqual(result["source_only_candidate"]["identified_field_count"],6)
        self.assertFalse(result["production_merge_authorized"])

    def test_source_only_can_be_tolerant_but_not_strict_on_auction_amount(self):
        day=date(2026,10,15)
        q,t=fixture(day)
        q[0]["amount"]+=5
        auction,rows,count=H.extract_live_page(historical(day),day)
        result=H.per_day(q,t,auction,rows)
        self.assertEqual(result["status"],
            "HOLDOUT_ALL_SIX_TOLERANTLY_MATCH_NOT_STRICT")
        self.assertFalse(result["qmt_validation_only"]["0930_auction"][
            "all_known_strictly_match"])
        self.assertTrue(result["qmt_validation_only"]["0930_auction"][
            "all_known_tolerantly_match"])

    def test_equal_auction_extreme_without_regular_witness_remains_unknown(self):
        day=date(2026,10,16)
        q,t=fixture(day,highlow=False)
        auction,rows,count=H.extract_live_page(historical(day),day)
        result=H.per_day(q,t,auction,rows)
        self.assertEqual(result["status"],
            "HOLDOUT_PRICE_EXTREME_OR_FIELD_NOT_IDENTIFIABLE")
        self.assertEqual(result["source_only_candidate"]["identified_field_count"],5)
        self.assertIsNone(result["source_only_candidate"][
            "regular_0931_source_only_candidate"]["low"])
        self.assertFalse(result["production_merge_authorized"])

    def test_bad_page_formal_event_missing_wrong_date_and_virtual_exclusion(self):
        day=date(2026,10,15)
        fake=historical(day)
        fake.trading_date=date(2026,10,16)
        with self.assertRaisesRegex(ValueError,"date mismatch"):
            H.extract_live_page(fake,day)
        fake=historical(day)
        fake.ticks[0].event_kind="auction_snapshot"
        with self.assertRaisesRegex(ValueError,"missing or nonunique"):
            H.extract_live_page(fake,day)
        fake=historical(day)
        fake.ticks.append(fake.ticks[0])
        fake.count+=1
        with self.assertRaisesRegex(ValueError,"missing or nonunique"):
            H.extract_live_page(fake,day)

    def test_preflight_two_dates_does_not_create_remote_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"eltdx_1m_probe"/"20261014_20261112"
            source=folder/"source_parquet"/"600000_SH.parquet"
            source.parent.mkdir(parents=True)
            q=[];t=[]
            for day in H.ALLOWED_DAYS:
                qi,ti=fixture(day)
                q.extend(qi);t.extend(ti)
            pq.write_table(pa.Table.from_pylist(t,schema=H.P.PRIVATE_SCHEMA),source)
            sha=H.L.hash_file(source)
            fake_receipt={"source_sha256":sha}
            with patch.object(H.X,"WORK",folder.parent),\
                 patch.object(H.P,"BASE",root),\
                 patch.object(H.X,"verified_cache",return_value=fake_receipt),\
                 patch.object(H.X,"read_qmt_source",return_value=(q,"qmt-test")):
                checked=H.run(days=H.ALLOWED_DAYS,
                    stocks=("600000.SH",),preflight_only=True,
                    client_factory=lambda: (_ for _ in ()).throw(
                        AssertionError("Must not connect in preflight")),
                    logger=lambda _:None)
                self.assertTrue(checked["preflight_only"])
                class Client:
                    def __init__(self):
                        self.trades=SimpleNamespace(all_history=
                            lambda code,when,**kw:historical(date.fromisoformat(when)))
                    def __enter__(self):return self
                    def __exit__(self,*args):pass
                finished=H.run(days=H.ALLOWED_DAYS,
                    stocks=("600000.SH",),client_factory=Client,
                    logger=lambda _:None)
                self.assertEqual(len(finished["stock_days"]),2)
                for case in finished["stock_days"].values():
                    self.assertEqual(case["status"],
                        "HOLDOUT_ALL_SIX_STRICTLY_MATCH_SOURCE_CANDIDATE")
                    self.assertFalse(case["production_merge_authorized"])
                private=folder/"auction_0925_split_pilot"/"cross_day_holdout"
                self.assertTrue((private/"20261015_20261016_holdout_summary.private.json").is_file())
                self.assertEqual(len(list(private.glob("*_holdout.private.json"))),2)
                with source.open("ab") as f:
                    f.write(b"tampered")
                with self.assertRaisesRegex(ValueError,"Source SHA"):
                    H.run(days=H.ALLOWED_DAYS,stocks=("600000.SH",),
                          preflight_only=True,logger=lambda _:None)

    def test_only_two_approved_trading_dates_are_permitted(self):
        with self.assertRaisesRegex(ValueError,"explicit"):
            H.run(days=(date(2026,10,17),),preflight_only=True)
        with self.assertRaisesRegex(ValueError,"explicit"):
            H.run(days=(date(2026,10,15),)*2,preflight_only=True)
        with self.assertRaisesRegex(ValueError,"three anchor"):
            H.run(stocks=("600000.SH","999999.SH"),preflight_only=True)


if __name__=="__main__":
    unittest.main()
