"""Synthetic-only decimal scaling; no licensed Parquet or real Hikyuu data."""
import importlib.util
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock,patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "hikyuu_synthetic_numeric_gate",
    HERE.parent/"tools"/"synthetic-parquet-to-hikyuu-h5-numeric-gate.py")
G=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


class NumericContractTests(unittest.TestCase):
    def test_all_six_fictional_rows_encode_exactly(self):
        for seed in (1,2):
            for ix,row in enumerate(G.synthetic_decoded_rows(seed)):
                native=G.encode_day_row(row)
                base=10000+seed*50+ix*100
                self.assertEqual(native["datetime"],G.DATES[ix])
                self.assertEqual(native["openPrice"],base)
                self.assertEqual(native["highPrice"],base+200)
                self.assertEqual(native["lowPrice"],base-200)
                self.assertEqual(native["closePrice"],base+50)
                self.assertEqual(native["transAmount"],
                                 100000+seed*1000+ix*100)
                self.assertEqual(native["transCount"],1200+seed*10+ix)

    def test_reject_price_precision_loss_instead_of_rounding(self):
        for value in ("12.0001","0.0005","0.000000001"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,"cannot represent"):
                    G.encode_exact(value,G.PRICE_SCALE,G.U32_MAX,"open")
        self.assertEqual(
            G.encode_exact("12.001",G.PRICE_SCALE,G.U32_MAX,"open"),12001)

    def test_amount_volume_precision_loss(self):
        with self.assertRaisesRegex(ValueError,"cannot represent"):
            G.encode_exact("10.05",G.AMOUNT_SCALE,G.U64_MAX,"amount")
        with self.assertRaisesRegex(ValueError,"cannot represent"):
            G.encode_exact("1.5",G.VOLUME_SCALE,G.U64_MAX,"volume")
        self.assertEqual(G.encode_exact("10.1",G.AMOUNT_SCALE,
                                        G.U64_MAX,"amount"),101)

    def test_nonfinite_negative_float_null_and_bool_rejected(self):
        for value in (float("nan"),float("inf"),1.0,False,True,
                      None,"NaN","Infinity","-0.1","bad"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    G.encode_exact(value,G.AMOUNT_SCALE,G.U64_MAX,"amount")

    def test_unsigned_integer_range_enforced(self):
        self.assertEqual(G.encode_exact(
            Decimal(G.U32_MAX)/1000,G.PRICE_SCALE,G.U32_MAX,"price"),
            G.U32_MAX)
        self.assertEqual(G.encode_exact(
            Decimal(G.U64_MAX)/10,G.AMOUNT_SCALE,G.U64_MAX,"amount"),
            G.U64_MAX)
        for maximum,scale in ((G.U32_MAX,G.PRICE_SCALE),
                              (G.U64_MAX,G.AMOUNT_SCALE)):
            with self.subTest(maximum=maximum):
                with self.assertRaisesRegex(ValueError,"overflow"):
                    G.encode_exact((Decimal(maximum)+1)/scale,
                                   scale,maximum,"price")

    def test_day_date_validation_and_illegal_ohlc(self):
        base=G.synthetic_decoded_rows(1)[0]
        for date in (202602300000,202609301000,2026093000,
                     202613010000,202609300001,"202609300000",-1,True):
            with self.subTest(date=date):
                row=dict(base,datetime=date)
                with self.assertRaises(ValueError):
                    G.encode_day_row(row)
        row=dict(base,low="20",high="10")
        with self.assertRaisesRegex(ValueError,"OHLC"):
            G.encode_day_row(row)
        row=dict(base,open="100")
        with self.assertRaisesRegex(ValueError,"OHLC"):
            G.encode_day_row(row)

    def test_no_implicit_float_and_no_extra_fields(self):
        row=G.synthetic_decoded_rows(1)[0]
        with self.assertRaisesRegex(ValueError,"no float"):
            G.encode_day_row(dict(row,close=10.1))
        with self.assertRaisesRegex(ValueError,"exactly 7"):
            G.encode_day_row(dict(row,stock="SH600000"))
        with self.assertRaisesRegex(ValueError,"exactly 7"):
            G.encode_day_row({k:v for k,v in row.items() if k!="high"})


class SyntheticParquetH5GateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)/"H5ParquetReconciler"
        self.root=root
        self.reports=root/"reports"
        self.canarydir=root/"work"/"h5_mirror"/"baseline"
        self.canarydir.mkdir(parents=True)
        self.reports.mkdir()
        self.canary=self.reports/"canary.json"
        self.canary.write_text("{}",encoding="utf-8")
        self.native=self.reports/"hikyuu-native-confirmed.json"
        self.target=root/"work"/"h5_mirror"/"synthetic_decimal_test"
        self.out=self.reports/"synthetic-decimal-safe.json"
        self.canary_hash="a"*64
        proof={
            "format":G.NATIVE_FORMAT,
            "canary_safe_summary_sha256":self.canary_hash,
            "native_hikyuu_runtime_version_expected":"2.8.1",
            "native_h5_read_status":"native_h5_six_synthetic_rows_matched",
            "last_native_phase":"finished",
            "per_symbol_matching_rows":{"SH600000":3,"SZ000001":3},
        }
        for key in (
                "canary_h5_hashes_reverified","synthetic_only",
                "verified_prior_core311_only_safe_proof","native_core311_loaded",
                "native_stock_manager_initialized","native_h5_get_kdata_called",
                "native_h5_synthetic_six_records_matched",
                "native_h5_compatibility_certified_for_synthetic_v1",
                "no_licensed_market_data_read","no_raw_ohlcva_in_safe_summary",
                "native_worker_stdout_stderr_not_saved"):
            proof[key]=True
        for key in (
                "full_hikyuu_package_imported",
                "licensed_parquet_to_h5_mapping_certified",
                "ready_for_full_market_mirror","original_market_files_modified",
                "production_query_route_modified","private_overlay_activated"):
            proof[key]=False
        self.native.write_text(json.dumps(proof),encoding="utf-8")
        self.check={
            "report_sha256":self.canary_hash,
            "isolated_canary_dir":self.canarydir,
            "source_file_details":{
                "sh_day.h5":{"sha256":"b"*64,"size_bytes":123},
                "sz_day.h5":{"sha256":"c"*64,"size_bytes":123}
            }
        }
        for mod,key,val in (
                (G,"WORK",root/"work"),(G,"MIRRORS",root/"work"/"h5_mirror"),
                (G.CHECK,"WORK",root/"work"),
                (G.CHECK,"MIRRORS",root/"work"/"h5_mirror"),
                (G.CHECK,"REPORTS",self.reports)):
            p=patch.object(mod,key,val)
            p.start()
            self.addCleanup(p.stop)
        p=patch.object(G.CHECK,"verify_canary",return_value=self.check)
        self.verifier=p.start()
        self.addCleanup(p.stop)

    def test_matching_native_proof_accepted_without_io(self):
        self.assertTrue(G.require_native_proof(self.native,self.check))

    def test_false_native_proof_status_and_missing_certification_fail_closed(self):
        original=json.loads(self.native.read_text(encoding="utf-8"))
        for edits in (
            {"canary_safe_summary_sha256":"f"*64},
            {"native_h5_read_status":"native_subprocess_timeout"},
            {"native_h5_synthetic_six_records_matched":False},
            {"licensed_parquet_to_h5_mapping_certified":True},
            {"ready_for_full_market_mirror":True},
            {"per_symbol_matching_rows":{"SH600000":3,"SZ000001":2}},
        ):
            with self.subTest(edits=edits):
                self.native.write_text(json.dumps(dict(original,**edits)),
                                       encoding="utf-8")
                with self.assertRaisesRegex(ValueError,"native synthetic"):
                    G.generate(self.canary,self.native,self.target,self.out)
                self.assertFalse(self.target.exists())
                self.assertFalse(self.out.exists())
        self.native.write_text(json.dumps(original),encoding="utf-8")

    def test_output_cannot_overwrite_or_escape_module(self):
        self.target.mkdir()
        with self.assertRaisesRegex(ValueError,"NEW isolated"):
            G.destinations(self.target,self.out)
        with self.assertRaisesRegex(ValueError,"NEW isolated"):
            G.destinations(self.root/"not-module"/"else",self.out)
        self.target.rmdir()
        self.out.write_text("original",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            G.destinations(self.target,self.out)

    def test_binary_layout_matches_native_certified_contract(self):
        self.assertEqual(G.LAYOUT,(
            ("closePrice","<u4"),("datetime","<u8"),("highPrice","<u4"),
            ("lowPrice","<u4"),("openPrice","<u4"),
            ("transAmount","<u8"),("transCount","<u8"),
        ))
        self.assertEqual((G.PRICE_SCALE,G.AMOUNT_SCALE,G.VOLUME_SCALE),
                         (Decimal(1000),Decimal(10),Decimal(1)))

    def test_numpy_dtype_descriptor_must_be_list_and_offsets_are_exact(self):
        # Regression for Windows: np.dtype(G.LAYOUT) interprets a seven-
        # element tuple as (base_dtype, shape) and raises TypeError.
        import numpy as np
        dtype=G.native_h5_dtype(np)
        self.assertEqual(dtype.itemsize,40)
        self.assertEqual(dtype.names,tuple(name for name,_ in G.LAYOUT))
        self.assertEqual(
            {name:dtype.fields[name][1] for name in dtype.names},
            {"closePrice":0,"datetime":4,"highPrice":12,"lowPrice":16,
             "openPrice":20,"transAmount":24,"transCount":32})
        self.assertEqual(tuple(dtype.fields[name][0].itemsize
                               for name in dtype.names),(4,8,4,4,4,8,8))

    def test_synthetic_parquet_to_h5_roundtrip_matches_real_native_read_baseline(self):
        try:
            import numpy as np
            import h5py
            import tables
            import pyarrow
        except ImportError:
            self.skipTest("optional synthetic Parquet/PyTables dependencies missing")
        dtype=G.native_h5_dtype(np)
        for sym,(filename,seed) in G.STOCKS.items():
            values=np.zeros(3,dtype=dtype)
            for i,row in enumerate(G.synthetic_decoded_rows(seed)):
                encoded=G.encode_day_row(row)
                for field,value in encoded.items():
                    values[i][field]=value
            with tables.open_file(str(self.canarydir/filename),"w") as h5:
                group=h5.create_group("/","data")
                table=h5.create_table(group,sym,description=dtype)
                table.append(values)
                table.flush()
        report=G.generate(self.canary,self.native,self.target,self.out)
        self.assertTrue(report[
            "all_six_synthetic_records_exactly_matched_native_baseline"])
        self.assertEqual(report["per_symbol_records"],
                         {"SH600000":3,"SZ000001":3})
        self.assertFalse(report["actual_purchased_parquet_units_verified"])
        self.assertFalse(report["new_h5_files_tested_by_native_driver"])
        self.assertFalse(report["ready_for_full_market_mirror"])
        self.assertTrue((self.target/"sh_day.h5").is_file())
        self.assertTrue((self.target/"sz_day.h5").is_file())
        self.assertEqual(len(report["generated_synthetic_files"]),2)
        self.assertNotIn("openPrice",self.out.read_text(encoding="utf-8"))
        self.assertNotIn("transAmount",self.out.read_text(encoding="utf-8"))
        for sym,(filename,_) in G.STOCKS.items():
            with h5py.File(self.target/filename,"r") as fh:
                self.assertEqual(fh["data"][sym].shape,(3,))


if __name__=="__main__":
    unittest.main(verbosity=2)
