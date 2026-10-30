"""Synthetic-only 1990-1993 volume/amount zero-state strata audits."""
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
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E=load("pre2011_early_zero_amount_strata_under_test",
       HERE.parent/"tools"/"audit-pre2011-early-zero-amount-strata-readonly.py")
F=load("pre2011_21year_raw_synthetic_fixture",
       HERE/"test_audit_pre2011_raw_numeric_profile_readonly.py")


@contextmanager
def synthetic():
    with tempfile.TemporaryDirectory() as tmp:
        home=Path(tmp)
        reports=home/"reports"
        reports.mkdir()
        private=home/"work"/"unified_parquet"/"pre2011_native_h5_raw"
        private.mkdir(parents=True)
        full=reports/"full21.json"
        profile=reports/"numeric-profile.json"
        out=reports/"early-zero-strata.json"
        with (patch.object(E.P,"REPORTS",reports),
              patch.object(E.P,"TOTAL_ROWS",21),
              patch.object(E,"EXPECTED_ROWS",4),
              patch.object(E.SINGLE,"PRIVATE",private),
              patch.object(E.SINGLE,"MODULE",home)):
            F.make_21(private,full)
            yield private,full,profile,out


def change_record(private,full,year,**fields):
    import pyarrow as pa
    import pyarrow.parquet as pq
    folder=private/("native_pre2011_"+str(year)+"_012345abcdef")
    data=folder/"h5-native-day.parquet"
    row=pq.read_table(data).to_pylist()[0]
    row.update(fields)
    pq.write_table(pa.Table.from_pylist([row],schema=E.SINGLE.schema(pa)),
                   data,compression="zstd")
    sha=E.SINGLE.hash_file(data)
    manifest=folder/"manifest.json"
    old=json.loads(manifest.read_text(encoding="utf-8"))
    old["full_private_parquet_sha256"]=sha
    manifest.write_text(json.dumps(old),encoding="utf-8")
    obj=json.loads(full.read_text(encoding="utf-8"))
    obj["yearly"][year-1990]["parquet_sha256"]=sha
    full.write_text(json.dumps(obj),encoding="utf-8")


class HistoricalAmountVolumeZeroStrataTests(unittest.TestCase):
    def test_21_year_prerequisite_four_year_private_only_aggregate(self):
        with synthetic() as (private,full,profile,out):
            E.P.run(full,profile)
            before={p:p.read_bytes() for p in private.rglob("*") if p.is_file()}
            result=E.run(full,profile,out)
            self.assertEqual(result["rows_profiled"],4)
            self.assertEqual(result["years_profiled"],[1990,1991,1992,1993])
            self.assertEqual(result["total_state_count"]["both_positive"],4)
            self.assertEqual(result["total_state_count"]["volume_positive_amount_zero"],0)
            self.assertTrue(result["full21_private_raw_files_sha_verified"])
            self.assertFalse(result["historical_original_h5_or_purchased_parquet_opened"])
            self.assertFalse(result["historical_units_or_adjustment_certified"])
            self.assertFalse(result["historical_standard_parquet_or_new_h5_written"])
            self.assertFalse(result["invalid_zero_amount_rows_auto_repaired_or_dropped"])
            doc=out.read_text(encoding="utf-8")
            for secret in ("SH600000","20260930","HikyuuData","h5-native-day.parquet"):
                self.assertNotIn(secret,doc)
            self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_actual_early_one_sided_zero_and_flat_cross_market_counts(self):
        with synthetic() as (private,full,profile,out):
            change_record(private,full,1990,transAmount=0)
            change_record(private,full,1991,transCount=0,transAmount=5)
            change_record(private,full,1992,transCount=0,transAmount=0)
            change_record(private,full,1993,openPrice=1000,highPrice=1000,
                          lowPrice=1000,closePrice=1000,transAmount=0)
            E.P.run(full,profile)
            result=E.run(full,profile,out)
            self.assertEqual(result["total_state_count"][
                "volume_positive_amount_zero"],2)
            self.assertEqual(result["total_state_count"][
                "volume_zero_amount_positive"],1)
            self.assertEqual(result["total_state_count"]["both_zero"],1)
            self.assertEqual(result["total_state_count"]["both_positive"],0)
            self.assertEqual(result["yearly_market_zero_state_aggregate"][0][
                "market_zero_state_count"]["SH"]["volume_positive_amount_zero"],1)
            self.assertEqual(result["yearly_market_zero_state_aggregate"][3][
                "zero_state_flat_ohlc_count"]["volume_positive_amount_zero"],1)
            self.assertFalse(result["historical_units_or_adjustment_certified"])

    def test_missing_numeric_prerequisite_no_output(self):
        with synthetic() as (_private,full,profile,out):
            with self.assertRaises(ValueError):
                E.run(full,profile,out)
            self.assertFalse(out.exists())

    def test_profile_hash_chain_rejects_full21_change(self):
        with synthetic() as (_private,full,profile,out):
            E.P.run(full,profile)
            d=json.loads(full.read_text(encoding="utf-8"))
            d["source_inventory_sha256"]="b"*64
            full.write_text(json.dumps(d),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"not qualified"):
                E.run(full,profile,out)
            self.assertFalse(out.exists())

    def test_profile_year_zero_counts_tamper_rejected(self):
        with synthetic() as (_private,full,profile,out):
            E.P.run(full,profile)
            d=json.loads(profile.read_text(encoding="utf-8"))
            d["yearly_aggregate_counts"][1]["volume_nonzero_amount_zero"]=1
            profile.write_text(json.dumps(d),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"prior numeric profile"):
                E.run(full,profile,out)
            self.assertFalse(out.exists())

    def test_private_year_sha_tamper_rejected(self):
        with synthetic() as (private,full,profile,out):
            E.P.run(full,profile)
            path=private/"native_pre2011_1993_012345abcdef"/"h5-native-day.parquet"
            with path.open("ab") as fp:
                fp.write(b"tamper")
            with self.assertRaisesRegex(ValueError,"SHA"):
                E.run(full,profile,out)
            self.assertFalse(out.exists())

    def test_reject_existing_safe_does_not_overwrite(self):
        with synthetic() as (_private,full,profile,out):
            E.P.run(full,profile)
            out.write_text("existing",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"new direct-child"):
                E.run(full,profile,out)
            self.assertEqual(out.read_text(encoding="utf-8"),"existing")

    def test_categorization_boundaries(self):
        cases={
            (1,1):"both_positive",
            (1,0):"volume_positive_amount_zero",
            (0,1):"volume_zero_amount_positive",
            (0,0):"both_zero",
        }
        for pair,expected in cases.items():
            self.assertEqual(E.classify(*pair),expected)
        with self.assertRaises(ValueError):
            E.classify(-1,0)


if __name__=="__main__":
    unittest.main(verbosity=2)
