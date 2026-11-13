"""Offline minute-start vs minute-end tests for historical 0x0fc6 trade rows."""
from datetime import date
import importlib.util
import hashlib
from pathlib import Path
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
    "qmt_eltdx_opening_tick_alignment",
    HERE/"qmt_eltdx_opening_tick_alignment.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
from test_qmt_eltdx_opening_ticks_241_probe import stock


def fixture():
    day,q,t,pilot=stock()
    q[2]["volume"]=3.
    q[2]["amount"]=3030.
    t[1]["volume"]=300.
    t[1]["amount"]=3030.
    rows=[{"minute":570,"price":10.1,"lots":.1,
           "absolute_index":i} for i in range(20)]
    rows.extend({"minute":571,"price":10.1,"lots":.15,
                 "absolute_index":i+20} for i in range(20))
    # A fresh score guarantees exact old-study SHA source pairing.
    pilot=M.A.evaluate(q,t,auction_price=10.,
                       auction_lots=1,auction_amount=1000.)
    return day,q,t,pilot,rows


class Tests(unittest.TestCase):
    def test_trade_start_times_match_next_qmt_end_times(self):
        day,q,t,pilot,rows=fixture()
        out=M.assess(rows,q,t)
        self.assertEqual(out["status"],
            "HISTORICAL_TRADES_0930_0931_MATCH_NEXT_END_LABELED_MINUTES")
        self.assertTrue(out["minute_label_forward_strict_volume_amount_fit"])
        self.assertFalse(out["minute_label_same_strict_volume_amount_fit"])
        self.assertEqual(out["historical_trade_index_sequence"],"monotone_increasing")
        self.assertTrue(out["comparisons"]["trade_0930_to_qmt_0931"][
            "strict_volume_and_amount_fit"])
        self.assertTrue(out["comparisons"]["trade_0931_to_qmt_0932"][
            "strict_volume_and_amount_fit"])
        self.assertFalse(out["production_merge_authorized"])

    def test_missing_intraminute_high_does_not_invalidate_volume_alignment(self):
        day,q,t,pilot,rows=fixture()
        q[1]["high"]=10.2
        t[0]["high"]=10.2
        out=M.assess(rows,q,t)
        first=out["comparisons"]["trade_0930_to_qmt_0931"]
        self.assertFalse(first["strict_fields"]["high"])
        self.assertTrue(first["high_observed_inside_target"])
        self.assertTrue(first["strict_volume_and_amount_fit"])
        self.assertFalse(out["production_merge_authorized"])

    def test_forward_label_when_tick_amount_close_but_not_one_yuan_exact(self):
        day,q,t,pilot,rows=fixture()
        q[1]["amount"]+=5.
        t[0]["amount"]+=5.
        q[2]["amount"]+=6.
        t[1]["amount"]+=6.
        out=M.assess(rows,q,t)
        self.assertEqual(out["status"],
            "NEXT_MINUTE_LABEL_SUPPORTED_BY_EXACT_VOLUME_AND_TOLERANT_AMOUNT")
        self.assertTrue(out["minute_label_forward_volume_strict_amount_tolerant_fit"])
        self.assertFalse(out["minute_label_forward_strict_volume_amount_fit"])
        for key in ("trade_0930_to_qmt_0931","trade_0931_to_qmt_0932"):
            check=out["comparisons"][key]
            self.assertTrue(check["strict_fields"]["volume"])
            self.assertFalse(check["strict_fields"]["amount"])
            self.assertTrue(check["tolerant_fields"]["amount"])
            self.assertGreater(check["amount_relative_error_basis_points"],0.)
        self.assertFalse(out["production_merge_authorized"])

    def test_first_minute_high_low_are_not_always_independently_identifiable(self):
        day,q,t,pilot,rows=fixture()
        inferred=M.infer_0931_bounds(q,t,rows)
        self.assertTrue(inferred["high_uniquely_determined_by_merged_extreme"])
        self.assertFalse(inferred["low_uniquely_determined_by_merged_extreme"])
        self.assertIsNone(inferred["known_field_match_to_qmt"]["low"])
        self.assertTrue(inferred["known_field_match_to_qmt"]["close"])
        self.assertTrue(inferred["known_field_match_to_qmt"]["volume"])
        self.assertTrue(inferred["known_field_match_to_qmt"]["amount"])
        self.assertTrue(inferred["trade_0930_first_as_returned_open_match"])
        self.assertFalse(inferred["all_six_0931_fields_source_independently_certified"])
        self.assertTrue(inferred["auction_values_from_qmt_oracle_for_feasibility_only"])
        self.assertFalse(inferred["production_merge_authorized"])
        # Even if trade subset min == independently known min, the combined
        # 240-bar low equal to auction price leaves a nonunique inverse.
        q[1]["low"]=9.9
        t[0]["low"]=9.9
        inferred=M.infer_0931_bounds(q,t,rows)
        self.assertTrue(inferred["low_uniquely_determined_by_merged_extreme"])
        self.assertTrue(inferred["known_field_match_to_qmt"]["low"])


    def test_same_label_hypothesis_and_incomplete_result(self):
        day,q,t,pilot,rows=fixture()
        for i,row in enumerate(rows):
            if row["minute"]==570:
                row["price"]=10.
                row["lots"]=.05
            else:
                row["lots"]=.1
        out=M.assess(rows,q,t)
        self.assertEqual(out["status"],
            "HISTORICAL_TRADES_MATCH_SAME_LABELED_MINUTES")
        self.assertTrue(out["minute_label_same_strict_volume_amount_fit"])
        self.assertFalse(out["minute_label_forward_strict_volume_amount_fit"])

    def test_invalid_records_and_grid_fail_closed(self):
        day,q,t,pilot,rows=fixture()
        rows[0]["minute"]=572
        with self.assertRaisesRegex(ValueError,"out of original opening window"):
            M.assess(rows,q,t)
        day,q,t,pilot,rows=fixture()
        rows[1]["lots"]=-1.
        with self.assertRaisesRegex(ValueError,"Nonpositive"):
            M.assess(rows,q,t)
        day,q,t,pilot,rows=fixture()
        t[1]["ts"]=t[0]["ts"]
        with self.assertRaisesRegex(ValueError,"timestamp grid"):
            M.assess(rows,q,t)

    def test_integrated_saved_trade_subset_sha_and_qmt_tdx_hash(self):
        day,q,t,pilot,rows=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"eltdx_1m_probe"/"20261014_20261112"
            work=folder/"auction_0925_split_pilot"
            work.mkdir(parents=True)
            source=folder/"source_parquet"/"600000_SH.parquet"
            source.parent.mkdir()
            pq.write_table(pa.Table.from_pylist(t,schema=M.P.PRIVATE_SCHEMA),source)
            tdxsha=M.L.hash_file(source)
            qmtsha="test-bound-qmt-sha"
            pilot["qmt_sha256"]=qmtsha
            pilot["source_parquet_sha256"]=tdxsha
            subset=M.P.canonical({
                "format":M.T.FORMAT,"day":str(day),"stock":"600000.SH",
                "source_qmt_sha256":qmtsha,
                "source_tdx_1m_sha256":tdxsha,
                "limited_actual_trade_rows":rows,
                "market_files_modified":False,
                "production_merge_authorized":False})
            subsetsha=hashlib.sha256(subset).hexdigest()
            (work/"20261014_600000_SH_opening_trade_rows.private.json").write_bytes(subset)
            M.P.safe_save(work/"20261014_summary.private.json",
                M.P.canonical({
                    "format":M.A.FORMAT,"day":str(day),
                    "market_files_modified":False,
                    "production_merge_authorized":False,
                    "stocks":{"600000.SH":pilot}}))
            M.P.safe_save(work/"20261014_historical_ticks_feasibility.private.json",
                M.P.canonical({
                    "format":M.T.FORMAT,"day":str(day),
                    "market_files_modified":False,
                    "production_merge_authorized":False,
                    "stocks":{"600000.SH":{
                        "status":"OBSERVED_TICK_BUCKET_ALL_SIX_FIELDS_FIT_BUT_SEQUENCE_NOT_CERTIFIED",
                        "opening_trade_subset_sha256":subsetsha,
                        "selected_opening_trade_record_count":40}}}))
            # The other two original stocks are intentionally excluded in this
            # integration fixture: an unauthorized partial live report is
            # supposed to be rejected instead of manufacturing evidence.
            with patch.object(M.X,"WORK",folder.parent),\
                 patch.object(M.P,"BASE",root),\
                 patch.object(M.X,"verified_cache",
                     return_value={"source_sha256":tdxsha}),\
                 patch.object(M.X,"read_qmt_source",
                     return_value=(q,qmtsha)):
                with self.assertRaisesRegex(ValueError,"no cached stock"):
                    M.run(day,logger=lambda _:None)
            # Ensure exact source SHA verification remains a hard gate.
            with source.open("ab") as stream:
                stream.write(b"tamper")
            with patch.object(M.X,"WORK",folder.parent),\
                 patch.object(M.P,"BASE",root),\
                 patch.object(M.X,"verified_cache",
                     return_value={"source_sha256":tdxsha}),\
                 patch.object(M.X,"read_qmt_source",
                     return_value=(q,qmtsha)):
                with self.assertRaises(ValueError):
                    M.run(day,logger=lambda _:None)


if __name__=="__main__":
    unittest.main()
