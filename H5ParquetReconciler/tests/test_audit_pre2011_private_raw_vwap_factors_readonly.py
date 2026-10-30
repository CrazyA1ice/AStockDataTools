"""Synthetic historical RAW annual candidate VWAP ratio evidence; no source market."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


V=load("pre2011_vwap_raw_candidates_under_test",
       HERE.parent/"tools"/"audit-pre2011-private-raw-vwap-factors-readonly.py")
F=load("pre2011_full21_vwap_raw_fixture",
       HERE/"test_audit_pre2011_raw_numeric_profile_readonly.py")


@contextmanager
def synthetic():
    with tempfile.TemporaryDirectory() as temp:
        home=Path(temp)
        report=home/"reports"
        report.mkdir()
        private=home/"work"/"unified_parquet"/"pre2011_native_h5_raw"
        private.mkdir(parents=True)
        full=report/"full21.json"
        profile=report/"numeric-profile.json"
        out=report/"vwap-factor-evidence.json"
        with (patch.object(V.P,"REPORTS",report),
              patch.object(V.P,"TOTAL_ROWS",21),
              patch.object(V.SINGLE,"PRIVATE",private),
              patch.object(V.SINGLE,"MODULE",home)):
            F.make_21(private,full)
            yield private,full,profile,out


def modify(private,full,year,**fields):
    import pyarrow as pa
    import pyarrow.parquet as pq
    folder=private/("native_pre2011_"+str(year)+"_012345abcdef")
    path=folder/"h5-native-day.parquet"
    original=pq.read_table(path).to_pylist()[0]
    original.update(fields)
    pq.write_table(pa.Table.from_pylist([original],schema=V.SINGLE.schema(pa)),
                   path,compression="zstd")
    sha=V.SINGLE.hash_file(path)
    manifest=folder/"manifest.json"
    m=json.loads(manifest.read_text(encoding="utf-8"))
    m["full_private_parquet_sha256"]=sha
    manifest.write_text(json.dumps(m),encoding="utf-8")
    report=json.loads(full.read_text(encoding="utf-8"))
    report["yearly"][year-1990]["parquet_sha256"]=sha
    full.write_text(json.dumps(report),encoding="utf-8")


class HistoricalPrivateRawVwapFactorTests(unittest.TestCase):
    def test_candidate_scale_factor_exact_and_strict_positive(self):
        matching=[f for f in V.FACTOR_GRID if V.vwap_candidate_matches(
            10,100,1000,1000,f)]
        self.assertEqual(matching,[10000])
        self.assertFalse(V.vwap_candidate_matches(0,100,1000,1100,10000))
        self.assertFalse(V.vwap_candidate_matches(10,0,1000,1100,10000))
        self.assertFalse(V.vwap_candidate_matches(10,100,0,1100,10000))
        self.assertFalse(V.vwap_candidate_matches(10,100,1101,1100,10000))
        self.assertFalse(V.vwap_candidate_matches(10,100,1000,1100,42))

    def test_numeric_integer_bounds_no_wraparound(self):
        big=2**63+10
        self.assertTrue(V.vwap_candidate_matches(
            big,big,10000,10000,10000))
        self.assertFalse(V.vwap_candidate_matches(
            big,big,10000,10000,1000))
        self.assertTrue(V.vwap_candidate_matches(
            10,100,995,995,10000))
        self.assertFalse(V.vwap_candidate_matches(
            10,100,994,994,10000))

    def test_full21_positive_synthetic_candidate_matrix(self):
        with synthetic() as (private,full,profile,out):
            modify(private,full,1992,transAmount=10,transCount=100,
                   lowPrice=1000,highPrice=1000,
                   openPrice=1000,closePrice=1000)
            V.P.run(full,profile)
            before={p:p.read_bytes() for p in private.rglob("*") if p.is_file()}
            result=V.run(full,profile,out)
            self.assertEqual(result["years_audited"],21)
            self.assertEqual(result["rows_audited"],21)
            self.assertEqual(result["positive_volume_amount_rows_eligible"],21)
            self.assertEqual(result["total_factor_matches"]["10000"],1)
            self.assertEqual(result["total_factor_matches"]["1000"],0)
            self.assertFalse(result["historical_physical_units_or_corporate_actions_certified"])
            self.assertFalse(result["new_native_h5_mirror_created"])
            self.assertFalse(result["original_h5_or_purchased_parquet_opened"])
            doc=out.read_text(encoding="utf-8")
            for secret in ("SH600000","HikyuuData","20260930",
                           "h5-native-day.parquet"):
                self.assertNotIn(secret,doc)
            self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_early_zero_states_excluded_and_verified_against_profile(self):
        with synthetic() as (private,full,profile,out):
            modify(private,full,1990,transAmount=0)
            modify(private,full,1991,transCount=0,transAmount=1)
            modify(private,full,1992,transCount=0,transAmount=0)
            V.P.run(full,profile)
            result=V.run(full,profile,out)
            self.assertEqual(result["positive_volume_amount_rows_eligible"],18)
            self.assertEqual(result["rows_audited"],21)
            self.assertEqual(result["per_year_aggregate"][0][
                "zero_states_excluded_from_factor_counts"][
                "volume_nonzero_amount_zero"],1)
            self.assertEqual(result["per_year_aggregate"][1][
                "zero_states_excluded_from_factor_counts"][
                "volume_zero_amount_nonzero"],1)
            self.assertEqual(result["per_year_aggregate"][2][
                "zero_states_excluded_from_factor_counts"][
                "volume_and_amount_both_zero"],1)

    def test_missing_or_tampered_numeric_profile_rejected_before_output(self):
        with synthetic() as (private,full,profile,out):
            with self.assertRaises(ValueError):
                V.run(full,profile,out)
            V.P.run(full,profile)
            doc=json.loads(profile.read_text(encoding="utf-8"))
            doc["yearly_aggregate_counts"][0]["volume_nonzero_amount_zero"]=1
            profile.write_text(json.dumps(doc),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"contradicted"):
                V.run(full,profile,out)
            self.assertFalse(out.exists())

    def test_private_raw_or_full21_checksum_tamper_rejected(self):
        with synthetic() as (private,full,profile,out):
            V.P.run(full,profile)
            data=private/"native_pre2011_1991_012345abcdef"/"h5-native-day.parquet"
            with data.open("ab") as stream:
                stream.write(b"corruption")
            with self.assertRaisesRegex(ValueError,"SHA"):
                V.run(full,profile,out)
            self.assertFalse(out.exists())
        with synthetic() as (private,full,profile,out):
            V.P.run(full,profile)
            doc=json.loads(full.read_text(encoding="utf-8"))
            doc["yearly"][3]["parquet_sha256"]="f"*64
            full.write_text(json.dumps(doc),encoding="utf-8")
            with self.assertRaises(ValueError):
                V.run(full,profile,out)
            self.assertFalse(out.exists())

    def test_output_overwrite_refused(self):
        with synthetic() as (private,full,profile,out):
            V.P.run(full,profile)
            out.write_text("protected",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"new direct-child"):
                V.run(full,profile,out)
            self.assertEqual(out.read_text(encoding="utf-8"),"protected")


if __name__=="__main__":
    unittest.main(verbosity=2)
