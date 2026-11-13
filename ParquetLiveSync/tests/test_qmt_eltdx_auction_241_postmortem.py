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
        self.assertEqual(d["model"],"MERGE_PRICES_ONLY_VOLUME_AMOUNT_DISAGREE")
        self.assertEqual(d["merged_failed_fields"],["amount"])
        self.assertFalse(d["regular_0931_OHLC_recovery_proven"])

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
