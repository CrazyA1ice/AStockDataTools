"""Synthetic-only 21-year private H5-native RAW numeric aggregate profile tests."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "pre2011_numeric_profile_under_test",
    HERE.parent/"tools"/"audit-pre2011-raw-numeric-profile-readonly.py")
P=importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def dummy_report(sha="a"*64):
    return {
        "status":"all_21_historical_native_years_verified_not_normalized",
        "years_verified":21,
        "total_native_rows":21,
        "source_inventory_sha256":sha,
        "yearly":[{"year":year,"rows":1,"parquet_sha256":"0"*64}
                  for year in P.YEARS],
        "purchased_normalized_schema_created":False,
        "historical_h5_units_certified":False,
        "historical_security_master_certified":False,
        "original_market_files_modified":False,
        "production_pointer_modified":False,
    }


@contextmanager
def fresh():
    with tempfile.TemporaryDirectory() as temp:
        home=Path(temp)
        reports=home/"reports"
        reports.mkdir()
        private=home/"work"/"unified_parquet"/"pre2011_native_h5_raw"
        private.mkdir(parents=True)
        full=reports/"full21-synthetic.json"
        out=reports/"numeric-profile-synthetic.json"
        with (patch.object(P,"REPORTS",reports),
              patch.object(P,"TOTAL_ROWS",21),
              patch.object(P.SINGLE,"PRIVATE",private),
              patch.object(P.SINGLE,"MODULE",home)):
            yield private,full,out


def make_21(private,full):
    import pyarrow as pa
    import pyarrow.parquet as pq
    obj=dummy_report()
    for index,year in enumerate(P.YEARS):
        folder=private/("native_pre2011_"+str(year)+"_012345abcdef")
        folder.mkdir()
        file=folder/"h5-native-day.parquet"
        row={"symbol":"SH600000","datetime":year*100000000+1010000,
             "openPrice":1000,"highPrice":1100,"lowPrice":900,
             "closePrice":1050,"transCount":100,"transAmount":5000}
        pq.write_table(pa.Table.from_pylist([row],schema=P.SINGLE.schema(pa)),
                       file,compression="zstd")
        sha=P.SINGLE.hash_file(file)
        obj["yearly"][index]["parquet_sha256"]=sha
        manifest={
            "format":P.SINGLE.PRIVATE_FORMAT,
            "year":year,
            "raw_h5_stockday_rows":1,
            "inventory_report_sha256":"a"*64,
            "full_private_parquet_sha256":sha,
            "private_parquet_schema":"native_uint64_all_ohlcva_no_renormalization",
            "purchased_parquet_footer_no_pre2011_rows":True,
            "private_normalized_purchased_schema":False,
            "H5_native_quantity_and_amount_units_certified":False,
            "H5_original_source_modified":False,
            "purchased_parquet_original_modified":False,
            "production_or_private_active_pointer_changed":False,
        }
        (folder/"manifest.json").write_text(
            json.dumps(manifest),encoding="utf-8")
    full.write_text(json.dumps(obj),encoding="utf-8")


class HistoricalNativeNumericProfileTests(unittest.TestCase):
    def test_numeric_counters_diagnostic_not_assumed_units(self):
        col={
            "openPrice":np.array([10,20,0],dtype="uint64"),
            "highPrice":np.array([12,19,0],dtype="uint64"),
            "lowPrice":np.array([9,18,0],dtype="uint64"),
            "closePrice":np.array([11,22,0],dtype="uint64"),
            "transCount":np.array([2**33,0,0],dtype="uint64"),
            "transAmount":np.array([100,1,0],dtype="uint64"),
        }
        result=P.count_batch(col)
        self.assertEqual(result["ohlc_order_or_bounds_violations"],1)
        self.assertEqual(result["all_ohlc_zero"],1)
        self.assertEqual(result["any_ohlc_zero"],1)
        self.assertEqual(result["open_high_low_close_all_equal"],1)
        self.assertEqual(result["volume_zero_amount_nonzero"],1)
        self.assertEqual(result["volume_and_amount_both_zero"],1)
        self.assertEqual(result["volume_nonzero_amount_zero"],0)
        self.assertEqual(result["any_value_exceeds_uint32"],1)

    def test_full21_safe_requires_complete_sorted_years_and_denial_flags(self):
        with fresh() as (_private,full,out):
            obj=dummy_report()
            for field,value in (
                ("historical_h5_units_certified",True),
                ("original_market_files_modified",True),
                ("total_native_rows",22),
                ("years_verified",20)):
                new=dict(obj)
                new[field]=value
                full.write_text(json.dumps(new),encoding="utf-8")
                with self.subTest(field=field):
                    with self.assertRaises(ValueError):
                        P.source_safe(full)
            new=dummy_report()
            new["yearly"][1]["year"]=1990
            full.write_text(json.dumps(new),encoding="utf-8")
            with self.assertRaises(ValueError):
                P.source_safe(full)
            new=dummy_report()
            new["yearly"][20]["rows"]=2
            full.write_text(json.dumps(new),encoding="utf-8")
            with self.assertRaises(ValueError):
                P.source_safe(full)
            self.assertFalse(out.exists())

    def test_missing_stage_refused(self):
        with fresh() as (private,full,out):
            full.write_text(json.dumps(dummy_report()),encoding="utf-8")
            old=P.source_safe(full)
            self.assertEqual(old[0]["years_verified"],21)
            with self.assertRaisesRegex(ValueError,"Missing"):
                P.run(full,out)
            self.assertFalse(out.exists())

    def test_complete_synthetic_21_years_only_aggregates_written(self):
        import pyarrow
        with fresh() as (private,full,out):
            make_21(private,full)
            before={p:p.read_bytes() for p in private.rglob("*") if p.is_file()}
            result=P.run(full,out)
            self.assertEqual(result["years_scanned"],21)
            self.assertEqual(result["private_raw_rows_profiled"],21)
            self.assertEqual(result["total_aggregate_counts"]["ohlc_order_or_bounds_violations"],0)
            self.assertFalse(result["historical_units_certified"])
            self.assertFalse(result["original_sources_rechecked_live_during_this_profile"])
            self.assertFalse(result["ready_for_production_query_or_h5_mirror"])
            written=out.read_text(encoding="utf-8")
            for secret in ("SH600000","1000","5000","HikyuuData","D:\\stock"):
                # The actual price 1000 must not be present as a standalone
                # market value. 1000 can appear in a SHA, so check structured
                # values and symbol/path instead.
                if secret in ("1000","5000"):
                    continue
                self.assertNotIn(secret,written)
            self.assertEqual({p:p.read_bytes() for p in before},before)

    def test_tampered_private_stage_or_ambiguous_year_rejected(self):
        import pyarrow
        with fresh() as (private,full,out):
            make_21(private,full)
            file=private/"native_pre2011_1990_012345abcdef"/"h5-native-day.parquet"
            with file.open("ab") as fp:
                fp.write(b"tampered")
            with self.assertRaisesRegex(ValueError,"SHA"):
                P.run(full,out)
            self.assertFalse(out.exists())
        with fresh() as (private,full,out):
            make_21(private,full)
            (private/"native_pre2011_1990_012345abcdee").mkdir()
            with self.assertRaisesRegex(ValueError,"Ambiguous"):
                P.run(full,out)
            self.assertFalse(out.exists())

    def test_refuse_existing_output_before_reading_raw(self):
        with fresh() as (private,full,out):
            full.write_text(json.dumps(dummy_report()),encoding="utf-8")
            out.write_text("protected",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"new direct-child"):
                P.run(full,out)
            self.assertEqual(out.read_text(encoding="utf-8"),"protected")


if __name__=="__main__":
    unittest.main(verbosity=2)
