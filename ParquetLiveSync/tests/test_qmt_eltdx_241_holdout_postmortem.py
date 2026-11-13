"""SHA-bound offline 241 opening held-out trade/amount/extrema forensic tests."""
from datetime import date
import hashlib
import importlib.util
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
    "qmt_eltdx_241_holdout_postmortem",
    HERE/"qmt_eltdx_241_holdout_postmortem.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
from test_qmt_eltdx_241_cross_day_holdout import fixture, historical


def one(day,highlow=True,auction_amount_gap=0):
    q,t=fixture(day,highlow=highlow)
    if auction_amount_gap:
        q[0]["amount"]+=auction_amount_gap
    auction,rows,_=M.H.extract_live_page(historical(day),day)
    audited=M.H.per_day(q,t,auction,rows)
    record={
        "format":M.H.FORMAT,"day":str(day),"stock":"600000.SH",
        "formal_0925_source":auction,
        "historical_opening_0930_0931_trades":rows,
        "source_only_candidate_and_separate_validation":audited,
        "market_files_modified":False,"production_merge_authorized":False}
    return q,t,record


class Tests(unittest.TestCase):
    def test_ambiguous_auction_low_stays_unknown_even_when_qmt_knows_it(self):
        day=date(2026,10,16)
        q,t,record=one(day,highlow=False)
        output=M.diagnose(record,q,t,record["historical_opening_0930_0931_trades"])
        self.assertEqual(output["regular_0931"]["unknown_fields"],["low"])
        low=output["unidentifiable_0931_extrema"]["low"]
        self.assertTrue(low["native_merged_extreme_equals_auction"])
        self.assertFalse(low["qmt_oracle_extreme_equals_auction"])
        self.assertFalse(low["independent_field_value_known"])
        self.assertFalse(low["can_promote_unknown_to_production"])
        self.assertTrue(low["trade_volume_matches_reconstructed_regular_volume_strict"])
        self.assertTrue(low["observed_trades_extreme_strict_match_to_qmt"])
        self.assertFalse(low["historical_trade_price_extreme_complete_independently_proven"])
        self.assertTrue(low["source_only_production_field_stays_null"])
        self.assertFalse(output["production_merge_authorized"])

    def test_exact_trade_volume_does_not_guarantee_observed_price_low_is_true_low(self):
        # Simulate a physically possible aggregated trade record sequence:
        # true 09:31 low 10.05 lies below all observed trade prices (10.1),
        # while the native merged minute low equals the auction price (10).
        # The trade rows still sum to the full 09:31 trading volume.
        day=date(2026,10,16)
        q,t,record=one(day,highlow=False)
        q[1]["low"]=10.05
        record["source_only_candidate_and_separate_validation"]=M.H.per_day(
            q,t,record["formal_0925_source"],
            record["historical_opening_0930_0931_trades"])
        result=M.diagnose(record,q,t,record["historical_opening_0930_0931_trades"])
        low=result["unidentifiable_0931_extrema"]["low"]
        self.assertTrue(low["trade_volume_matches_reconstructed_regular_volume_strict"])
        self.assertFalse(low["observed_trades_extreme_strict_match_to_qmt"])
        self.assertFalse(low["historical_trade_price_extreme_complete_independently_proven"])
        self.assertFalse(low["can_promote_unknown_to_production"])
        self.assertIn("low",result["regular_0931"]["unknown_fields"])

    def test_original_0930_0931_amount_strict_gap_and_merged_gap_reported(self):
        day=date(2026,10,15)
        q,t,record=one(day,highlow=True,auction_amount_gap=5)
        out=M.diagnose(record,q,t,record["historical_opening_0930_0931_trades"])
        self.assertEqual(out["auction_0930"]["strict_failed_fields"],["amount"])
        self.assertTrue(out["auction_0930"]["amount_error"]["original_tolerance_match"])
        self.assertFalse(out["auction_0930"]["amount_error"]["strict_match"])
        self.assertNotEqual(out["merged_first_minute_amount_error"][
            "signed_error_basis_points"],0)
        self.assertFalse(out["production_merge_authorized"])

    def test_unchanged_strict_case_does_not_gain_unknown_fields(self):
        day=date(2026,10,15)
        q,t,record=one(day,highlow=True)
        out=M.diagnose(record,q,t,record["historical_opening_0930_0931_trades"])
        self.assertEqual(out["regular_0931"]["unknown_fields"],[])
        self.assertEqual(out["regular_0931"]["strict_failed_fields"],[])
        self.assertEqual(out["auction_0930"]["strict_failed_fields"],[])
        self.assertTrue(out["first_regular_trade_as_returned_strict_open_match"])
        self.assertFalse(out["history_records_chronologically_certified"])

    def test_source_only_result_tampering_is_rejected(self):
        day=date(2026,10,15)
        q,t,record=one(day)
        record["source_only_candidate_and_separate_validation"][
            "source_only_candidate"]["regular_0931_source_only_candidate"]["open"]+=.1
        with self.assertRaisesRegex(ValueError,"no longer reproducible"):
            M.diagnose(record,q,t,record["historical_opening_0930_0931_trades"])

    def test_exact_six_case_local_sha_replay_and_mutation_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"eltdx_1m_probe"/"20261014_20261112"
            work=folder/"auction_0925_split_pilot"/"cross_day_holdout"
            work.mkdir(parents=True)
            qmap={}
            shas={}
            for code in M.H.CODES:
                qall=[]; tall=[]
                for day in M.H.ALLOWED_DAYS:
                    ambiguous=(day==date(2026,10,16) and code=="688001.SH")
                    q,t,record=one(day,highlow=not ambiguous)
                    for row in (*q,*t):
                        row["symbol"]=M.L.normal_symbol(code)
                    qmap[code]=qmap.get(code,[])+q
                    tall.extend(t)
                source=folder/"source_parquet"/(code.replace(".","_")+".parquet")
                source.parent.mkdir(parents=True,exist_ok=True)
                pq.write_table(pa.Table.from_pylist(tall,schema=M.P.PRIVATE_SCHEMA),source)
                shas[code]=M.L.hash_file(source)
            previous={}
            for day in M.H.ALLOWED_DAYS:
                for code in M.H.CODES:
                    ambiguous=(day==date(2026,10,16) and code=="688001.SH")
                    q,t,record=one(day,highlow=not ambiguous)
                    record["stock"]=code
                    record["original_qmt_SHA256_validation_only"]="q-"+code
                    record["original_eltdx_240_SHA256"]=shas[code]
                    payload=M.P.canonical(record)
                    path=work/f"{day:%Y%m%d}_{code.replace('.','_')}_holdout.private.json"
                    path.write_bytes(payload)
                    previous[f"{day}/{code}"]={
                        "status":record["source_only_candidate_and_separate_validation"]["status"],
                        "private_SHA256":hashlib.sha256(payload).hexdigest()}
            M.P.safe_save(
                work/"20261015_20261016_holdout_summary.private.json",
                M.P.canonical({
                    "summary":{"format":M.H.FORMAT,
                               "days":[str(d) for d in M.H.ALLOWED_DAYS],
                               "cases":6,"market_files_modified":False,
                               "production_merge_authorized":False},
                    "stock_days":previous}))
            with patch.object(M.X,"WORK",folder.parent),\
                 patch.object(M.P,"BASE",root),\
                 patch.object(M.X,"verified_cache",
                     side_effect=lambda _folder,code,_stage,remote_only=False:{
                         "source_sha256":shas[code]}),\
                 patch.object(M.X,"read_qmt_source",
                     side_effect=lambda _stage,code:(qmap[code],"q-"+code)):
                result=M.run(logger=lambda _:None)
                self.assertEqual(result["summary"]["stock_days_verified"],6)
                self.assertEqual(result["summary"]["unknown_0931_field_counts"],
                                 {"low":1})
                self.assertTrue((work/"20261015_20261016_source_sha_postmortem.private.json").exists())
                tamper=work/"20261016_688001_SH_holdout.private.json"
                tamper.write_bytes(tamper.read_bytes()+b"tamper")
                with self.assertRaisesRegex(ValueError,"result SHA mismatch"):
                    M.run(logger=lambda _:None)


if __name__=="__main__":
    unittest.main()
