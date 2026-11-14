"""Offline fake historical trade pages for the 241-first-minute reconstruction test."""
from datetime import date
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location(
    "qmt_eltdx_opening_ticks_241_probe",
    HERE/"qmt_eltdx_opening_ticks_241_probe.py")
T=importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
from test_qmt_eltdx_auction_241_probe import sample


def stock():
    day,q,t=sample()
    q[0]["volume"]=1.
    q[0]["amount"]=1000.
    q[1]["volume"]=2.
    q[1]["amount"]=2020.
    t[0]["volume"]=300.
    t[0]["amount"]=3020.
    for i in range(1,240):t[i]["volume"]=q[i+1]["volume"]*100.
    pilot=T.A.evaluate(q,t,auction_price=10.,
                       auction_lots=1,auction_amount=1000.)
    return day,q,t,pilot


def event(minute,price,volume,kind="trade",idx=0):
    return SimpleNamespace(time_minutes=minute,price=price,volume=volume,
        event_kind=kind,status_raw=8 if kind=="auction_snapshot" else 2,
        absolute_index=idx,is_after_hours_fixed_price=False)


def page(*ticks,day=date(2026,10,14)):
    return SimpleNamespace(ticks=ticks,count=len(ticks),trading_date=day)


class Tests(unittest.TestCase):
    def test_separate_0925_and_0931_ohlcva_all_six_match_but_not_production(self):
        day,q,t,pilot=stock()
        tickpage=page(event(565,10.,1,kind="opening_match"),
            event(571,10.1,1,idx=2),event(571,10.1,1,idx=3),
            event(571,9.,999,kind="auction_snapshot"))
        out=T.inspect(q,t,pilot,tickpage)
        self.assertEqual(out["status"],
            "OBSERVED_TICK_BUCKET_ALL_SIX_FIELDS_FIT_BUT_SEQUENCE_NOT_CERTIFIED")
        self.assertEqual(out["opening"]["status"],"FORMAL_0925_MATCHES_QMT_0930")
        self.assertEqual(out["selected_opening_trade_record_count"],2)
        trial=[x for x in out["bucket_trials"] if x["group"]=="minute_0931"][0]
        self.assertTrue(trial["all_six_fit"])
        self.assertFalse(out["production_merge_authorized"])
        self.assertTrue(out["price_row_sequence_not_certified"])

    def test_missed_actual_trade_is_not_certified(self):
        day,q,t,pilot=stock()
        out=T.inspect(q,t,pilot,page(event(565,10.,1,kind="opening_match"),
            event(571,10.1,1)))
        self.assertEqual(out["status"],
            "HISTORICAL_TICK_BUCKET_CANNOT_RECONSTRUCT_QMT_0931")
        self.assertFalse(out["production_merge_authorized"])

    def test_auction_snapshot_never_contributes_regular_volume(self):
        self.assertIsNone(T.trade_entry(
            event(571,99.,200,kind="auction_snapshot")))
        self.assertIsNone(T.trade_entry(
            event(565,10.,1,kind="opening_match")))
        self.assertIsNone(T.trade_entry(event(572,10.,1)))
        with self.assertRaisesRegex(ValueError,"Invalid historical"):
            T.trade_entry(event(571,10.,-3.))

    def test_0931_first_close_order_ambiguity_explicit(self):
        day,q,t,pilot=stock()
        b=q[1]
        b["high"]=10.2
        b["close"]=10.2
        b["amount"]=3030. # 1 lot at 10.1 + 2 lots at 10.1? diagnostic values only
        # Instead test bucket-only order without source-proof coupling.
        ticks=[{"minute":571,"price":10.1,"lots":1., "absolute_index":0},
               {"minute":571,"price":10.2,"lots":1., "absolute_index":1}]
        expected={"open":10.1,"high":10.2,"low":10.1,"close":10.2,
                  "volume":2.,"amount":2030.}
        out=T.bucket_trial(ticks,expected)
        trial=next(x for x in out if x["group"]=="minute_0931")
        self.assertTrue(trial["all_six_fit"])
        self.assertTrue(trial["price_order_not_chronologically_certified"])

    def test_nonunique_formal_opening_rejected(self):
        day,q,t,pilot=stock()
        x=event(565,10.,1,kind="opening_match")
        out=T.inspect(q,t,pilot,page(x,x,event(571,10.1,1)))
        self.assertEqual(out["status"],
            "HISTORICAL_FORMAL_0925_INCONSISTENT_WITH_QMT")

    def test_end_to_end_old_sha_verified_private_report_and_no_market_write(self):
        day,q,t,pilot=stock()
        remote=page(event(565,10.,1,kind="opening_match"),
                    event(571,10.1,1),event(571,10.1,1))
        class Client:
            def __init__(self):
                self.trades=SimpleNamespace(all_history=lambda *a,**k:remote)
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"eltdx_probe"/"20261014_20261112"
            src=folder/"source_parquet"/"600000_SH.parquet"
            src.parent.mkdir(parents=True)
            pq.write_table(pa.Table.from_pylist(t,schema=T.P.PRIVATE_SCHEMA),src)
            h=T.L.hash_file(src)
            pilot["source_parquet_sha256"]=h
            pilot["qmt_sha256"]="offline_qmt_hash"
            work=folder/"auction_0925_split_pilot"
            work.mkdir()
            T.P.safe_save(work/"20261014_summary.private.json",
                T.P.canonical({"format":T.A.FORMAT,"day":str(day),
                    "stocks":{"600000.SH":pilot},
                    "market_files_modified":False,
                    "production_merge_authorized":False}))
            with patch.object(T.X,"WORK",folder.parent),\
                 patch.object(T.P,"BASE",root),\
                 patch.object(T.X,"verified_cache",
                     return_value={"source_sha256":h}),\
                 patch.object(T.X,"read_qmt_source",
                     return_value=(q,"offline_qmt_hash")):
                result=T.run(day=day,stocks=("600000.SH",),
                             workspace=work,client_factory=Client,
                             logger=lambda _:None)
                self.assertEqual(result["stocks"]["600000.SH"]["status"],
                    "OBSERVED_TICK_BUCKET_ALL_SIX_FIELDS_FIT_BUT_SEQUENCE_NOT_CERTIFIED")
            self.assertTrue((work/"20261014_historical_ticks_feasibility.private.json").exists())
            self.assertTrue((work/"20261014_600000_SH_opening_trade_rows.private.json").exists())
            self.assertFalse(result["production_merge_authorized"])


if __name__=="__main__":
    unittest.main()
