"""Offline 0925 formal match + 0931 merged bar vs QMT 241 source tests."""
from datetime import date,datetime
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location(
    "qmt_eltdx_auction_241_probe",HERE/"qmt_eltdx_auction_241_probe.py")
A=importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


def sample():
    day=date(2026,10,14)
    q=[]
    for h,m in sorted(A.P.GRID):
        stamp=int(datetime(day.year,day.month,day.day,h,m,
                           tzinfo=A.P.CN).timestamp()*1000)
        price=10. if (h,m)==(9,30) else 10.1
        q.append({"ts":stamp,"symbol":"SH600000",
            "open":price,"high":price,"low":price,"close":price,
            "volume":100. if (h,m)==(9,30) else 150.,
            "amount":1000. if (h,m)==(9,30) else 1500.})
    t=[dict(r) for r in q[1:]]
    t[0]=dict(t[0],open=10.,high=10.1,low=10.,close=10.1,
              volume=250.,amount=2500.)
    return day,q,t


class Tests(unittest.TestCase):
    def test_real_auction_100_shares_plus_0931_aggregate_match_241_qmt(self):
        day,q,t=sample()
        r=A.evaluate(q,t,auction_price=10.,auction_lots=1,auction_amount=1000.)
        self.assertEqual(r["status"],
            "FORMAL_0925_MATCHES_QMT_0930_AND_TDX_0931_MERGE")
        self.assertTrue(r["first_minute_all_fields_fit"])
        self.assertTrue(r["auction_0930_candidate_matches_qmt"])
        self.assertEqual(r["opening_volume_unit_factors_compatible"],[100.])
        self.assertTrue(r["cannot_derive_regular_0931_open_from_merged_kline_alone"])
        self.assertFalse(r["production_merge_authorized"])

    def test_fake_price_or_inconsistent_amount_are_rejected(self):
        day,q,t=sample()
        wrong=A.evaluate(q,t,auction_price=9.,auction_lots=1,auction_amount=900.)
        self.assertEqual(wrong["status"],"FIRST_MINUTE_SPLIT_REQUIRES_REVIEW")
        t[0]["amount"]+=5000
        wrong=A.evaluate(q,t,auction_price=10.,auction_lots=1,auction_amount=1000.)
        self.assertFalse(wrong["first_minute_all_fields_fit"])
        self.assertFalse(wrong["production_merge_authorized"])

    def test_incomplete_or_missing_auction_keeps_guard(self):
        day,q,t=sample()
        self.assertEqual(A.evaluate(q[:-1],t,auction_price=10.,
            auction_lots=1,auction_amount=1000.)["status"],"SOURCE_INCOMPLETE")
        self.assertEqual(A.evaluate(q,t,auction_price=10.,
            auction_lots=0,auction_amount=0.)["status"],"INVALID_FORMAL_AUCTION")

    def test_bounded_end_to_end_with_sha_source_and_fake_0925_event(self):
        day,q,t=sample()
        class Client:
            def __init__(self):
                self.trades=SimpleNamespace(opening_match_history=lambda *a,**k:
                    SimpleNamespace(time_label="09:25",event_kind="opening_match",
                        is_opening_match=True,price=10.,volume=1,
                        trade_amount_yuan=1000.))
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            private=folder/"20261014_20261112"
            src=private/"source_parquet"/"600000_SH.parquet"
            src.parent.mkdir(parents=True)
            pq.write_table(pa.Table.from_pylist(t,schema=A.P.PRIVATE_SCHEMA),src)
            cached={"source_sha256":A.L.hash_file(src)}
            with patch.object(A.X,"WORK",private.parent),\
                 patch.object(A.P,"BASE",folder),\
                 patch.object(A.X,"verified_cache",return_value=cached),\
                 patch.object(A.X,"read_qmt_source",
                              return_value=(q,"synthetic-qmt-sha")):
                actual=A.run(day=day,stocks=("600000.SH",),
                    workspace=folder/"private-results",
                    client_factory=Client,logger=lambda _:None)
            self.assertEqual(actual["stocks"]["600000.SH"]["status"],
                "FORMAL_0925_MATCHES_QMT_0930_AND_TDX_0931_MERGE")
            self.assertEqual(actual["stocks"]["600000.SH"]["qmt_sha256"],
                "synthetic-qmt-sha")
            self.assertFalse(actual["production_merge_authorized"])
            self.assertTrue((folder/"private-results"/"20261014_summary.private.json").exists())
            # Any later alteration to the private source must stop the pilot.
            with src.open("ab") as handle:
                handle.write(b"tampered")
            with patch.object(A.X,"WORK",private.parent),\
                 patch.object(A.P,"BASE",folder),\
                 patch.object(A.X,"verified_cache",return_value=cached),\
                 patch.object(A.X,"read_qmt_source",
                              return_value=(q,"synthetic-qmt-sha")):
                again=A.run(day=day,stocks=("600000.SH",),
                    workspace=folder/"private-results",
                    client_factory=Client,logger=lambda _:None)
            self.assertEqual(again["stocks"]["600000.SH"]["status"],
                "HISTORICAL_AUCTION_PILOT_ERROR")


if __name__=="__main__":
    unittest.main()
