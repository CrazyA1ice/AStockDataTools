"""Offline read-only three-way LC1/LC5 vs eltdx-240 and QMT-241 tests."""
import importlib.util
from datetime import date
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location(
    "tdx_local_lc_vs_eltdx_qmt",HERE/"tdx_local_lc_vs_eltdx_qmt.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
from test_qmt_eltdx_auction_241_probe import sample


def market():
    day,q,t=sample()
    # Synthetic eltdx wire shares vs the native QMT lots.
    for bar in t:
        bar["volume"]*=100.
    return day,q,t


def local(online):
    return [M.normal_day_bar(x) for x in online]


def save_lc(root,code,period,bars,day):
    path=M.T.path_for(root,code,period)
    path.parent.mkdir(parents=True,exist_ok=True)
    packed=(day.year-2004)*2048+day.month*100+day.day
    path.write_bytes(b"".join(M.T.BAR.pack(
        packed,x["minute"],
        x["open"],x["high"],x["low"],x["close"],
        x["amount"],int(x["volume"]),0) for x in bars))
    return path


class Tests(unittest.TestCase):
    def test_all_240_local_equal_online_and_aggregated_qmt_volume_001(self):
        day,q,t=market()
        one=local(t)
        five=M.local_to_five(one)
        result=M.evaluate(day,one,five,t,q)
        self.assertEqual(result["status"],"LOCAL_LC1_MATCHES_ONLINE_FULL_DAY")
        self.assertEqual(result["volume_factor_local_to_online"],1.)
        self.assertEqual(result["volume_factor_local_to_qmt_merged"],.01)
        self.assertEqual(result["local_1min_vs_online_eltdx_240"][
            "strict_field_match_counts"]["high"],240)
        self.assertEqual(result["local_1min_vs_qmt_aggregated_240"][
            "strict_field_match_counts"]["amount"],240)
        self.assertEqual(result["local_1min_rolled_to_local_5min"][
            "strict_field_match_counts"]["high"],48)
        self.assertFalse(result["opening_0931_high_evidence"][
            "local_source_independently_certifies_regular_high"])
        self.assertFalse(result["production_merge_authorized"])

    def test_local_first_high_differs_from_online_and_matches_qmt_reg_high(self):
        day,q,t=market()
        one=local(t)
        one[0]["high"]=10.2
        q[1]["high"]=10.2
        five=M.local_to_five(one)
        r=M.evaluate(day,one,five,t,q)
        first=r["opening_0931_high_evidence"]
        self.assertEqual(r["status"],"LOCAL_AND_ONLINE_PRICE_DIFFERENCES")
        self.assertFalse(first["local_merged_high_equals_online_merged_high_strict"])
        self.assertTrue(first["local_merged_high_equals_qmt_regular_high_strict"])
        self.assertTrue(first["local_merged_high_above_qmt_auction_high"])
        self.assertFalse(first["local_source_independently_certifies_regular_high"])
        self.assertFalse(r["production_merge_authorized"])

    def test_same_auction_high_does_not_resolve_regular_high(self):
        day,q,t=market()
        q[0].update(open=10.2,high=10.2,low=10.2,close=10.2)
        t[0].update(open=10.2,high=10.2)
        one=local(t)
        five=M.local_to_five(one)
        r=M.evaluate(day,one,five,t,q)
        first=r["opening_0931_high_evidence"]
        self.assertTrue(first["local_merged_high_equals_online_merged_high_strict"])
        self.assertTrue(first["local_merged_high_equals_qmt_auction_high_strict"])
        self.assertFalse(first["local_merged_high_equals_qmt_regular_high_strict"])
        self.assertTrue(first["qmt_regular_high_below_auction_high"])
        self.assertFalse(first["local_merged_high_above_qmt_auction_high"])
        self.assertTrue(first["unresolved_0931_high_not_filled_from_qmt"])

    def test_lc5_mismatch_is_reported_separately(self):
        day,q,t=market()
        one=local(t)
        five=M.local_to_five(one)
        five[0]["high"]+=1.
        r=M.evaluate(day,one,five,t,q)
        self.assertEqual(r["local_1min_rolled_to_local_5min"][
            "strict_field_match_counts"]["high"],47)
        self.assertEqual(r["local_1min_vs_online_eltdx_240"][
            "strict_field_match_counts"]["high"],240)

    def test_real_32_byte_local_read_and_sha_fail_closed(self):
        day,q,t=market()
        with tempfile.TemporaryDirectory() as tmp:
            p=save_lc(tmp,"600000.SH",1,local(t),day)
            data,sha=M.read_local(p,period=1,days=(day,))
            self.assertEqual(len(data[day]),240)
            self.assertEqual(data[day][0]["minute"],571)
            self.assertEqual(sha,M.L.hash_file(p))
            old=M.T.scan_file(p,period=1,days=(day,))
            bytes_=bytearray(p.read_bytes())
            bytes_[5]^=1
            p.write_bytes(bytes_)
            with patch.object(M.T,"scan_file",return_value=old):
                with self.assertRaisesRegex(ValueError,"SHA changed"):
                    M.read_local(p,period=1,days=(day,))

    def test_end_to_end_sha_sources_local_lc1_and_5_only_console(self):
        day,q,t=market()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            vipdoc=root/"TDX"/"vipdoc"
            one=local(t)
            save_lc(vipdoc,"600000.SH",1,one,day)
            save_lc(vipdoc,"600000.SH",5,M.local_to_five(one),day)
            stage=root/"private_qmt"/"20261014_20261112"
            online_root=root/"eltdx_1m_probe"/"20261014_20261112"
            file=online_root/"source_parquet"/"600000_SH.parquet"
            file.parent.mkdir(parents=True)
            pq.write_table(pa.Table.from_pylist(t,schema=M.P.PRIVATE_SCHEMA),file)
            sha=M.L.hash_file(file)
            logs=[]
            with patch.object(M.X,"WORK",online_root.parent),\
                 patch.object(M.P,"BASE",stage.parent),\
                 patch.object(M.X,"verified_cache",
                              return_value={"source_sha256":sha}),\
                 patch.object(M.X,"read_qmt_source",
                              return_value=(q,"fixture-sha")):
                result=M.run(vipdoc=vipdoc,days=(day,),
                             codes=("600000.SH",),logger=logs.append)
                self.assertEqual(result["summary"]["stock_days"],1)
                self.assertTrue(result["summary"]["no_network"])
                self.assertTrue(result["summary"]["output_files_written"] is False)
                self.assertEqual(len(logs),2)
                self.assertFalse(list(root.rglob("*.json")))
                self.assertFalse(result["summary"]["production_merge_authorized"])
                # Changing the source bytes breaks the original online receipt.
                with file.open("ab") as stream:
                    stream.write(b"tampered")
                with self.assertRaisesRegex(ValueError,"SHA binding"):
                    M.run(vipdoc=vipdoc,days=(day,),codes=("600000.SH",),
                          logger=lambda _:None)

    def test_reject_wrong_grid_and_unapproved_days(self):
        day,q,t=market()
        one=local(t)
        with self.assertRaisesRegex(ValueError,"Missing 240/241"):
            M.evaluate(day,one[:-1],M.local_to_five(one),t,q)
        with self.assertRaisesRegex(ValueError,"Only original three Oct"):
            M.run(vipdoc=".",days=(date(2026,10,17),))


if __name__=="__main__":
    unittest.main()
