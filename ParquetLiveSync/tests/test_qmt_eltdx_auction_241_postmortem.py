"""Synthetic offline case-level 09:25/09:31 source-model diagnostics."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pyarrow as pa
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location(
    "qmt_eltdx_auction_241_postmortem",
    HERE/"qmt_eltdx_auction_241_postmortem.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

# Use the existing synthetic 241/240 QMT/TDX opening fixture.
from test_qmt_eltdx_auction_241_probe import sample


def pilot(q,t):
    result=M.A.evaluate(q,t,auction_price=10.,
                         auction_lots=1,auction_amount=1000.)
    return result


class Tests(unittest.TestCase):
    def test_exact_first_auction_merge_and_239_regular_field_fits(self):
        day,q,t=sample()
        d=M.diagnostic(q,t,pilot(q,t))
        self.assertEqual(d["model"],"OPENING_0930_PLUS_0931_MERGE_ALL_SIX")
        self.assertEqual(d["merged_failed_fields"],[])
        self.assertEqual(d["remaining_239_field_fit_counts"],
                         {field:239 for field in M.FIELDS})
        self.assertEqual(d["direct_failed_fields"],["open","low","volume","amount"])
        self.assertFalse(d["production_merge_authorized"])

    def test_amount_only_mismatch_does_not_claim_reconstructible(self):
        day,q,t=sample()
        t[0]["amount"]*=2
        d=M.diagnostic(q,t,pilot(q,t))
        self.assertEqual(d["model"],"MERGE_OHLC_VOLUME_MATCH_AMOUNT_DIFFERENCE")
        self.assertEqual(d["merged_failed_fields"],["amount"])
        self.assertFalse(d["regular_0931_OHLC_recovery_proven"])

    def test_100x_wire_volume_only_matches_after_diagnostic_scale(self):
        day,q,t=sample()
        for bar in t:
            bar["volume"]*=100.
        result=M.diagnostic(q,t,pilot(q,t))
        self.assertEqual(result["merged_failed_fields"],["volume"])
        self.assertEqual(result["remaining_239_field_fit_counts"].get("volume",0),0)
        self.assertEqual(result["remaining_239_field_fit_counts"]["amount"],239)
        proof=result["volume_unit_evidence"]
        self.assertEqual(proof["tdx_raw_volume_to_qmt_candidate_factor"],.01)
        self.assertEqual(proof["candidate_fit_positive_counts"]["0.01"],240)
        self.assertEqual(result["volume_after_candidate_scale_all_240_fit"],240)
        self.assertEqual(result["model"],
            "OPENING_MERGE_MATCH_AFTER_RESEARCH_ONLY_VOLUME_UNIT_ALIGNMENT")
        self.assertFalse(proof["volume_scale_applied_to_source"])
        self.assertFalse(result["production_merge_authorized"])
        self.assertFalse(result["regular_0931_OHLC_recovery_proven"])

    def test_zero_minutes_do_not_masquerade_as_100x_validation(self):
        day,q,t=sample()
        for bar in t:
            bar["volume"]*=100.
        q[3]["volume"]=0.
        t[2]["volume"]=0.
        evidence=M.diagnostic(q,t,pilot(q,t))["volume_unit_evidence"]
        self.assertEqual(evidence["both_zero_minute_pairs"],1)
        self.assertEqual(evidence["positive_minute_pairs"],239)
        self.assertEqual(evidence["candidate_fit_positive_counts"]["0.01"],239)
        self.assertEqual(evidence["tdx_raw_volume_to_qmt_candidate_factor"],.01)
        # One-sided zeroes indicate a genuine source conflict, not unit scaling.
        q[3]["volume"]=200.
        result=M.diagnostic(q,t,pilot(q,t))
        self.assertEqual(result["volume_unit_evidence"]["one_sided_zero_minute_pairs"],1)
        self.assertIsNone(result["volume_unit_evidence"][
            "tdx_raw_volume_to_qmt_candidate_factor"])
        self.assertNotEqual(result["model"],
            "OPENING_MERGE_MATCH_AFTER_RESEARCH_ONLY_VOLUME_UNIT_ALIGNMENT")

    def test_small_sample_cannot_prove_unit(self):
        left=[{"volume":100.} for _ in range(4)]
        right=[{"volume":10000.} for _ in range(4)]
        evidence=M.volume_factor_evidence(left,right)
        self.assertIsNone(evidence["tdx_raw_volume_to_qmt_candidate_factor"])
        self.assertFalse(evidence["candidate_identified_for_research"])

    def test_price_only_mismatch_is_not_volume_amount_failure(self):
        day,q,t=sample()
        t[0]["high"]=11.0
        d=M.diagnostic(q,t,pilot(q,t))
        self.assertEqual(d["model"],"MERGE_VOLUME_AMOUNT_ONLY_PRICE_DISAGREES")
        self.assertEqual(d["merged_failed_fields"],["high"])
        self.assertEqual(d["remaining_239_field_fit_counts"]["high"],239)

    def test_timestamp_or_stored_score_tampering_is_refused(self):
        day,q,t=sample()
        data=pilot(q,t)
        data["combined_first_1m_field_fits"]["volume"]=False
        with self.assertRaisesRegex(ValueError,"Earlier live auction"):
            M.diagnostic(q,t,data)
        _,q,t=sample()
        t[100]["ts"]+=60000
        with self.assertRaisesRegex(ValueError,"Timestamp grid"):
            M.diagnostic(q,t,pilot(q,t))

    def test_full_existing_report_sha_pinned_offline_no_reconnect(self):
        day,q,t=sample()
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            xroot=folder/"private"/"20261014_20261112"
            source=xroot/"source_parquet"/"600000_SH.parquet"
            source.parent.mkdir(parents=True)
            pq.write_table(pa.Table.from_pylist(t,schema=M.P.PRIVATE_SCHEMA),source)
            report=xroot/"auction_0925_split_pilot"/"20261014_summary.private.json"
            report.parent.mkdir()
            audit=pilot(q,t)
            audit["source_parquet_sha256"]=M.L.hash_file(source)
            audit["qmt_sha256"]="qmt-sha"
            M.P.safe_save(report,M.P.canonical({
                "format":M.A.FORMAT,"day":str(day),"stocks":{"600000.SH":audit},
                "market_files_modified":False,
                "production_merge_authorized":False}))
            with patch.object(M.X,"WORK",xroot.parent),\
                 patch.object(M.P,"BASE",folder),\
                 patch.object(M.X,"verified_cache",
                     return_value={"source_sha256":M.L.hash_file(source)}),\
                 patch.object(M.X,"read_qmt_source",return_value=(q,"qmt-sha")):
                output=M.run(day=day,logger=lambda _:None)
            self.assertEqual(
                output["stocks"]["600000.SH"]["model"],
                "OPENING_0930_PLUS_0931_MERGE_ALL_SIX")
            self.assertTrue((report.parent/"20261014_field_postmortem.private.json").is_file())
            with source.open("ab") as handle:handle.write(b"corruption")
            with patch.object(M.X,"WORK",xroot.parent),\
                 patch.object(M.P,"BASE",folder),\
                 patch.object(M.X,"verified_cache",
                     return_value={"source_sha256":audit["source_parquet_sha256"]}),\
                 patch.object(M.X,"read_qmt_source",return_value=(q,"qmt-sha")):
                with self.assertRaisesRegex(ValueError,"TDX SHA"):
                    M.run(day=day,logger=lambda _:None)


if __name__=="__main__":
    unittest.main()
