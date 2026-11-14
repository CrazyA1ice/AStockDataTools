"""Offline source-only formal auction 240->241 candidate and sealed QMT oracle tests."""
from datetime import date,datetime
import hashlib
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
    "qmt_eltdx_source_independent_241_pilot",
    HERE/"qmt_eltdx_source_independent_241_pilot.py")
R=importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
from test_qmt_eltdx_opening_ticks_241_probe import stock


def opening(day=date(2026,10,14)):
    return SimpleNamespace(
        time_label="09:25",event_kind="opening_match",
        is_opening_match=True,status_raw=2,price=10.,
        volume=1,trade_amount_yuan=1000.,
        trade_datetime=datetime(day.year,day.month,day.day,9,25))


def records():
    return [
        {"minute":570,"price":10.1,"lots":1.,"absolute_index":0},
        {"minute":570,"price":10.1,"lots":1.,"absolute_index":1},
        {"minute":571,"price":10.1,"lots":1.,"absolute_index":2},
        {"minute":571,"price":10.1,"lots":1.,"absolute_index":3},
    ]


class Tests(unittest.TestCase):
    def test_auction_from_raw_source_and_conservative_missing_low(self):
        day,q,t,pilot=stock()
        formal=R.formal_event(opening(),day)
        derived=R.derive_source_only(t[0],formal,records())
        self.assertEqual(derived["auction_0930_source_only"],{
            "open":10.,"high":10.,"low":10.,"close":10.,
            "volume":1.,"amount":1000.})
        self.assertEqual(derived["regular_0931_source_only_candidate"][
            "volume"],2.)
        self.assertEqual(derived["regular_0931_source_only_candidate"][
            "amount"],2020.)
        self.assertIsNone(derived["regular_0931_source_only_candidate"]["low"])
        self.assertEqual(derived["identified_field_count"],5)
        self.assertFalse(derived["independent_0931_open_certified"])
        validate=R.reference_check(derived,q)
        self.assertTrue(validate["0930_auction"]["all_six_known"])
        self.assertFalse(validate["0931_regular"]["all_six_known"])
        self.assertTrue(validate["0931_regular"]["all_known_tolerantly_match"])
        self.assertFalse(derived["production_merge_authorized"])

    def test_high_low_are_identifiable_if_native_extrema_beyond_auction(self):
        day,q,t,pilot=stock()
        t[0]["low"]=9.9
        q[1]["low"]=9.9
        derived=R.derive_source_only(t[0],R.formal_event(opening(),day),
                                     records())
        self.assertEqual(derived["identified_field_count"],6)
        self.assertEqual(derived["high_reason"],"merged_high_above_auction")
        self.assertEqual(derived["low_reason"],"merged_low_below_auction")
        self.assertEqual(derived["regular_0931_source_only_candidate"]["low"],9.9)
        ref=R.reference_check(derived,q)
        self.assertTrue(ref["0931_regular"]["all_six_known"])
        self.assertTrue(ref["0931_regular"]["all_known_tolerantly_match"])
        # All six fitting a separate QMT reference still does not establish
        # trade order or independence of the historical tick provider.
        self.assertFalse(derived["trade_sequence_chronology_certified"])
        self.assertFalse(derived["production_merge_authorized"])

    def test_native_low_equal_auction_but_real_trade_at_auction_identifies_low(self):
        day,q,t,pilot=stock()
        rec=records()
        rec[1]["price"]=10.
        derived=R.derive_source_only(t[0],R.formal_event(opening(),day),rec)
        self.assertEqual(derived["low_reason"],
                         "regular_trade_observed_at_auction_low")
        self.assertEqual(derived["regular_0931_source_only_candidate"]["low"],10.)
        self.assertFalse(derived["independent_0931_open_certified"])

    def test_virtual_auction_wrong_day_and_nonpositive_are_rejected(self):
        day,q,t,pilot=stock()
        bad=opening()
        bad.event_kind="auction_snapshot"
        with self.assertRaisesRegex(ValueError,"formally executed"):
            R.formal_event(bad,day)
        with self.assertRaisesRegex(ValueError,"date mismatch"):
            R.formal_event(opening(),date(2026,10,15))
        bad=opening()
        bad.volume=0
        with self.assertRaisesRegex(ValueError,"price/volume"):
            R.formal_event(bad,day)
        bad=opening()
        bad.trade_amount_yuan=2000
        with self.assertRaisesRegex(ValueError,"Inconsistent calculated"):
            R.formal_event(bad,day)

    def test_disallow_synthetic_regular_ohlc_or_negative_auction_subtraction(self):
        day,q,t,pilot=stock()
        x=R.formal_event(opening(),day)
        with self.assertRaisesRegex(ValueError,"No historical"):
            R.derive_source_only(t[0],x,[])
        x["volume_lots"]=1000.
        with self.assertRaisesRegex(ValueError,"Auction subtraction"):
            R.derive_source_only(t[0],x,records())
        x=R.formal_event(opening(),day)
        t[0]["low"]=10.5
        with self.assertRaisesRegex(ValueError,"not consistent with auction"):
            R.derive_source_only(t[0],x,records())

    def test_end_to_end_original_sha_and_source_only_trial_is_private(self):
        day,q,t,pilot=stock()
        rr=records()
        class Client:
            def __init__(self):
                self.trades=SimpleNamespace(opening_match_history=
                    lambda *args,**kwargs:opening())
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"eltdx_1m_probe"/"20261014_20261112"
            src=folder/"source_parquet"/"600000_SH.parquet"
            src.parent.mkdir(parents=True)
            pq.write_table(pa.Table.from_pylist(t,schema=R.P.PRIVATE_SCHEMA),src)
            tsha=R.L.hash_file(src)
            qsha="verified_fixture_qmt"
            pilot["source_parquet_sha256"]=tsha
            pilot["qmt_sha256"]=qsha
            work=folder/"auction_0925_split_pilot"
            work.mkdir()
            R.P.safe_save(work/"20261014_summary.private.json",
                R.P.canonical({
                    "format":R.A.FORMAT,"day":str(day),
                    "stocks":{"600000.SH":pilot},
                    "market_files_modified":False,
                    "production_merge_authorized":False}))
            subset=R.P.canonical({
                "format":R.T.FORMAT,"day":str(day),
                "stock":"600000.SH",
                "source_qmt_sha256":qsha,
                "source_tdx_1m_sha256":tsha,
                "limited_actual_trade_rows":rr,
                "market_files_modified":False,
                "production_merge_authorized":False})
            subsetsha=hashlib.sha256(subset).hexdigest()
            (work/"20261014_600000_SH_opening_trade_rows.private.json").write_bytes(subset)
            R.P.safe_save(work/"20261014_historical_ticks_feasibility.private.json",
                R.P.canonical({"format":R.T.FORMAT,"day":str(day),
                    "market_files_modified":False,
                    "production_merge_authorized":False,
                    "stocks":{"600000.SH":{
                        "status":"OBSERVED_TICK_BUCKET_ALL_SIX_FIELDS_FIT_BUT_SEQUENCE_NOT_CERTIFIED",
                        "opening_trade_subset_sha256":subsetsha,
                        "selected_opening_trade_record_count":4}}}))
            with patch.object(R.X,"WORK",folder.parent),\
                 patch.object(R.P,"BASE",root),\
                 patch.object(R.X,"verified_cache",
                     return_value={"source_sha256":tsha}),\
                 patch.object(R.X,"read_qmt_source",
                     return_value=(q,qsha)):
                result=R.run(day,stocks=("600000.SH",),
                    client_factory=Client,logger=lambda _:None)
                outcome=result["stocks"]["600000.SH"]
                self.assertEqual(outcome["status"],"SOURCE_CANDIDATE_NOT_FULLY_VALIDATED")
                self.assertTrue(outcome["candidate"][
                    "source_only_candidate_does_not_use_qmt_answers"])
                self.assertFalse(result["production_merge_authorized"])
                private=work/"20261014_600000_SH_source_only_241_candidate.private.json"
                self.assertTrue(private.is_file())
                blob=private.read_bytes()
                self.assertEqual(hashlib.sha256(blob).hexdigest(),
                    outcome["private_source_only_candidate_sha256"])
                self.assertIn(b"trade_amount_yuan_derived",blob)
                with src.open("ab") as stream:
                    stream.write(b"source-mutated")
                error=R.run(day,stocks=("600000.SH",),
                    client_factory=Client,logger=lambda _:None)
                self.assertEqual(error["stocks"]["600000.SH"]["status"],
                                 "SOURCE_INDEPENDENT_PILOT_ERROR")


if __name__=="__main__":
    unittest.main()
