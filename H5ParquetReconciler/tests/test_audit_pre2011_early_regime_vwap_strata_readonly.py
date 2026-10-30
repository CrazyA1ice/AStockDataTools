"""Synthetic early H5 RAW date/market VWAP candidate regime, SAFE-only output."""
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


R=load("pre2011_early_regime_raw_test",
       HERE.parent/"tools"/"audit-pre2011-early-regime-vwap-strata-readonly.py")
F=load("pre2011_early_regime_fixture",
       HERE/"test_audit_pre2011_raw_numeric_profile_readonly.py")


@contextmanager
def synthetic():
    with tempfile.TemporaryDirectory() as temp:
        home=Path(temp)
        reports=home/"reports"
        reports.mkdir()
        private=home/"work"/"unified_parquet"/"pre2011_native_h5_raw"
        private.mkdir(parents=True)
        full=reports/"full21.json"
        profile=reports/"numeric.json"
        factor=reports/"factors.json"
        out=reports/"early-regime.json"
        with (patch.object(R.P,"REPORTS",reports),
              patch.object(R.P,"TOTAL_ROWS",21),
              patch.object(R.SINGLE,"PRIVATE",private),
              patch.object(R.SINGLE,"MODULE",home),
              patch.object(R,"EXPECTED_ROWS",7)):
            F.make_21(private,full)
            yield private,full,profile,factor,out


def change_record(private,full,year,**fields):
    import pyarrow as pa
    import pyarrow.parquet as pq
    folder=private/("native_pre2011_"+str(year)+"_012345abcdef")
    file=folder/"h5-native-day.parquet"
    row=pq.read_table(file).to_pylist()[0]
    row.update(fields)
    pq.write_table(pa.Table.from_pylist([row],schema=R.SINGLE.schema(pa)),
                   file,compression="zstd")
    sha=R.SINGLE.hash_file(file)
    manifest=folder/"manifest.json"
    m=json.loads(manifest.read_text(encoding="utf-8"))
    m["full_private_parquet_sha256"]=sha
    manifest.write_text(json.dumps(m),encoding="utf-8")
    summary=json.loads(full.read_text(encoding="utf-8"))
    summary["yearly"][year-1990]["parquet_sha256"]=sha
    full.write_text(json.dumps(summary),encoding="utf-8")


def prepare(full,profile,factor):
    R.P.run(full,profile)
    R.V.run(full,profile,factor)


class EarlyYearVwapRegimeCohortTests(unittest.TestCase):
    def test_21year_chain_seven_year_market_quarter_safe_only(self):
        with synthetic() as (private,full,profile,factor,out):
            change_record(private,full,1992,openPrice=1000,highPrice=1000,
                          lowPrice=1000,closePrice=1000,
                          transCount=100,transAmount=10)
            prepare(full,profile,factor)
            originals={p:p.read_bytes() for p in private.rglob("*") if p.is_file()}
            d=R.run(full,profile,factor,out)
            self.assertEqual(d["rows_stratified"],7)
            self.assertEqual([x["year"] for x in d["years"]],
                             list(range(1990,1997)))
            self.assertEqual(d["total_candidate_factor_hits"]["10000"],1)
            self.assertTrue(d["private_source_sha_chain_verified_for_21_years"])
            self.assertFalse(d["physical_units_corporate_actions_or_securities_certified"])
            self.assertFalse(d["original_h5_or_purchased_parquet_opened"])
            self.assertFalse(d["standardized_purchased_parquet_or_h5_created"])
            s=out.read_text(encoding="utf-8")
            for forbidden in ("SH600000","20260930","HikyuuData",
                              "h5-native-day.parquet"):
                self.assertNotIn(forbidden,s)
            self.assertEqual(originals,{p:p.read_bytes() for p in originals})

    def test_market_quarter_and_zero_cases_synthetic(self):
        with synthetic() as (private,full,profile,factor,out):
            change_record(private,full,1991,symbol="SZ000001",
                          datetime=199107010000,transCount=0,transAmount=0)
            change_record(private,full,1992,transAmount=0)
            prepare(full,profile,factor)
            d=R.run(full,profile,factor,out)
            year1991=d["years"][1]["market_quarter_strata"]
            self.assertEqual(len(year1991),1)
            self.assertEqual((year1991[0]["market"],year1991[0]["quarter"]),
                             ("SZ",3))
            self.assertEqual(year1991[0]["volume_and_amount_both_zero"],1)
            self.assertEqual(d["years"][2]["excluded_zero_state_counts"][
                "volume_nonzero_amount_zero"],1)
            self.assertEqual(d["total_candidate_factor_hits"]["10000"],0)

    def test_factor_safe_inconsistent_yearly_match_rejected(self):
        with synthetic() as (_private,full,profile,factor,out):
            prepare(full,profile,factor)
            s=json.loads(factor.read_text(encoding="utf-8"))
            s["per_year_aggregate"][0][
                "candidate_raw_amount_multiplier_hits"]["10000"]+=1
            factor.write_text(json.dumps(s),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"do not match"):
                R.run(full,profile,factor,out)
            self.assertFalse(out.exists())

    def test_prior_factor_safe_source_binding_rejected(self):
        with synthetic() as (_private,full,profile,factor,out):
            prepare(full,profile,factor)
            s=json.loads(factor.read_text(encoding="utf-8"))
            s["full21_source_safe_sha256"]="f"*64
            factor.write_text(json.dumps(s),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"SHA chain"):
                R.run(full,profile,factor,out)
            self.assertFalse(out.exists())

    def test_private_file_digest_tamper_refused(self):
        with synthetic() as (private,full,profile,factor,out):
            prepare(full,profile,factor)
            file=private/"native_pre2011_1990_012345abcdef"/"h5-native-day.parquet"
            with file.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError,"SHA"):
                R.run(full,profile,factor,out)
            self.assertFalse(out.exists())

    def test_wrong_month_and_ohlc_structure_rejected(self):
        with synthetic() as (private,full,profile,factor,out):
            change_record(private,full,1992,datetime=199301010000)
            prepare(full,profile,factor)
            with self.assertRaisesRegex(ValueError,"outside selected"):
                R.run(full,profile,factor,out)
            self.assertFalse(out.exists())
        with synthetic() as (private,full,profile,factor,out):
            change_record(private,full,1992,lowPrice=2000,highPrice=1000)
            prepare(full,profile,factor)
            with self.assertRaisesRegex(ValueError,"OHLC"):
                R.run(full,profile,factor,out)
            self.assertFalse(out.exists())

    def test_never_overwrite_existing_safe(self):
        with synthetic() as (_private,full,profile,factor,out):
            prepare(full,profile,factor)
            out.write_text("protected",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"new direct-child"):
                R.run(full,profile,factor,out)
            self.assertEqual(out.read_text(encoding="utf-8"),"protected")


if __name__=="__main__":
    unittest.main(verbosity=2)
