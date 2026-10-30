"""Offline contracts for native reread of generated SYNTHETIC Decimal H5."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "synthetic_decimal_native_recheck_test",
    HERE.parent/"tools"/"recheck-synthetic-decimal-h5-native-core311-isolated.py")
R=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def fake_worker_result(state="native_h5_six_synthetic_rows_matched"):
    passed=state=="native_h5_six_synthetic_rows_matched"
    obj={
      "state":state,"core311_loaded":True,
      "full_hikyuu_package_imported":False,
      "hikyuu_281_version_confirmed":True,
      "synthetic_registry_initialized":True,
      "stock_manager_initialized":True,
      "native_h5_kdata_method_called":True,
      "native_h5_values_matched":passed,
      "per_symbol_matching_rows":{"SH600000":3 if passed else 2,
                                  "SZ000001":3 if passed else 0},
      "source_market_files_accessed":False,
      "production_query_switched":False,
    }
    return SimpleNamespace(
        stdout=(b"mixed native log: "+bytes([0xac,0xff])+bytes([10])
                +R.NATIVE.PHASE_MARKER.encode()+b"finished"+bytes([10])
                +R.NATIVE.MARKER.encode()+json.dumps(obj).encode()+bytes([10])),
        returncode=0)


class SyntheticDecimalNativeRereadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)/"H5ParquetReconciler"
        self.reports=root/"reports"
        self.mirrors=root/"work"/"h5_mirror"
        self.original=self.mirrors/"native_canary"
        self.synthetic=self.mirrors/"synthetic_decimal_bridge_v1"
        self.reports.mkdir(parents=True)
        self.original.mkdir(parents=True)
        self.synthetic.mkdir()
        self.canary=self.reports/"native-canary.json"
        self.canary.write_text("{}",encoding="utf-8")
        self.decimal=self.reports/"synthetic-decimal.json"
        self.core=self.reports/"core-proof.json"
        self.core.write_text("{}",encoding="utf-8")
        self.out=self.reports/"synthetic-native-reread.json"
        self.python=root/"python311"/"python.exe"
        self.python.parent.mkdir()
        self.python.write_bytes(b"fictional python")
        self.check={
            "isolated_canary_dir":self.original,
            "report_sha256":"d"*64,
            "source_file_details":{
                "sh_day.h5":{"sha256":"1"*64,"size_bytes":100},
                "sz_day.h5":{"sha256":"2"*64,"size_bytes":100}
            }
        }
        src={
            "format":R.BRIDGE.FORMAT,
            "canary_safe_summary_sha256":self.check["report_sha256"],
            "native_h5_unsigned_price_width_bits":32,
            "native_h5_unsigned_amount_volume_width_bits":64,
            "per_symbol_records":{"SH600000":3,"SZ000001":3},
        }
        for key in (
          "verified_previous_native_h5_six_rows",
          "synthetic_parquet_generation_only",
          "prices_in_hikyuu_driver_units_only",
          "amounts_in_hikyuu_driver_units_only",
          "volumes_in_hikyuu_driver_units_only","exact_decimal_no_rounding",
          "all_six_synthetic_records_exactly_matched_native_baseline",
          "no_raw_ohlcva_in_safe_summary"):
            src[key]=True
        for key in (
          "new_h5_files_tested_by_native_driver",
          "actual_purchased_parquet_units_verified",
          "licensed_parquet_to_h5_mapping_certified",
          "ready_for_full_market_mirror","licensed_market_data_read",
          "original_market_files_modified","production_query_route_modified"):
            src[key]=False
        generated=[]
        for stock,h5 in R.STOCKS.items():
            h5_path=self.synthetic/h5
            pq_path=self.synthetic/(stock.lower()+"_synthetic.parquet")
            h5_path.write_bytes(("H5 synthetic "+stock).encode())
            pq_path.write_bytes(("Parquet synthetic "+stock).encode())
            generated.append({
                "kind":"fictional_parquet_and_h5",
                "symbol":stock,
                "parquet_sha256":R.BRIDGE.sha256(pq_path),
                "h5_sha256":R.BRIDGE.sha256(h5_path),
                "verified_integer_records":3,
            })
        src["generated_synthetic_files"]=generated
        self.decimal.write_text(json.dumps(src),encoding="utf-8")
        for obj,name,value in (
            (R.NATIVE,"WORK",root/"work"),
            (R.NATIVE,"MIRRORS",self.mirrors),
            (R.NATIVE.CHECK,"WORK",root/"work"),
            (R.NATIVE.CHECK,"MIRRORS",self.mirrors),
            (R.NATIVE.CHECK,"REPORTS",self.reports)):
            p=patch.object(obj,name,value)
            p.start();self.addCleanup(p.stop)
        p=patch.object(R.CHECK,"verify_canary",return_value=self.check)
        p.start();self.addCleanup(p.stop)
        p=patch.object(R.NATIVE,"verify_core_proof",return_value=True)
        p.start();self.addCleanup(p.stop)

    def run_it(self,runner=None,**kwargs):
        return R.native_recheck(
            self.canary,self.decimal,self.core,self.synthetic,
            self.python,self.out,
            runner=runner or Mock(return_value=fake_worker_result()),
            **kwargs)

    def test_verified_synthetic_files_only_matching_sha_and_manifest(self):
        self.assertEqual(set(R.verify_decimal_bridge(
            self.decimal,self.check,self.synthetic)),set(R.STOCKS))
        self.assertEqual(
            R._guard_synthetic_dir(self.synthetic),self.synthetic.resolve())

    def test_real_worker_reused_for_six_native_record_validation(self):
        runner=Mock(return_value=fake_worker_result())
        result=self.run_it(runner=runner)
        self.assertTrue(result["new_generated_h5_six_native_records_matched"])
        self.assertTrue(result["new_generated_h5_native_driver_certified"])
        self.assertEqual(result["per_symbol_matching_rows"],
                         {"SH600000":3,"SZ000001":3})
        self.assertEqual(result["last_native_phase"],"finished")
        self.assertFalse(result["licensed_parquet_units_verified"])
        self.assertFalse(result["ready_for_full_market_mirror"])
        self.assertTrue(result["input_safe_proof_bytes_unchanged_during_native_reread"])
        self.assertEqual(set(result["input_safe_proofs_sha256"]),
                         {"synthetic_canary","synthetic_decimal_bridge","isolated_core311"})
        self.assertEqual(result["input_safe_proofs_sha256"]["synthetic_decimal_bridge"],
                         R.BRIDGE.sha256(self.decimal))
        self.assertNotIn("mixed native log",self.out.read_text(encoding="utf-8"))
        args=runner.call_args.args[0]
        self.assertEqual(args[:3],[str(self.python.resolve()),"-I","-c"])
        self.assertEqual(args[3],R.NATIVE.WORKER)
        self.assertEqual(
            args[-2:],
            [str(self.synthetic/"sh_day.h5"),str(self.synthetic/"sz_day.h5")])
        self.assertEqual(
            runner.call_args.kwargs["cwd"],
            self.synthetic/"_native_h5_281"/"run001")
        self.assertIs(runner.call_args.kwargs["text"],False)

    def test_bad_h5_parquet_sha_blocks_native_execution(self):
        runner=Mock(side_effect=AssertionError("must not call native driver"))
        self.synthetic.joinpath("sh_day.h5").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError,"hash changed"):
            self.run_it(runner=runner)
        runner.assert_not_called()
        self.assertFalse(self.out.exists())
        self.assertFalse((self.synthetic/"_native_h5_281").exists())

    def test_forged_bridge_safe_report_rejected(self):
        runner=Mock(side_effect=AssertionError("unsafe native call"))
        original=json.loads(self.decimal.read_text(encoding="utf-8"))
        for edit in (
            {"canary_safe_summary_sha256":"a"*64},
            {"all_six_synthetic_records_exactly_matched_native_baseline":False},
            {"licensed_parquet_to_h5_mapping_certified":True},
            {"new_h5_files_tested_by_native_driver":True},
            {"per_symbol_records":{"SH600000":3,"SZ000001":2}},
            {"generated_synthetic_files":[]},
        ):
            with self.subTest(edit=edit):
                self.decimal.write_text(
                    json.dumps(dict(original,**edit)),encoding="utf-8")
                with self.assertRaisesRegex(
                        ValueError,"Decimal bridge|synthetic|fictional"):
                    self.run_it(runner=runner)
                self.assertFalse(self.out.exists())
        runner.assert_not_called()

    def test_child_crash_and_timeout_do_not_certify(self):
        runner=Mock(return_value=SimpleNamespace(
            stdout=b"untrusted C++ log "+bytes([0xac]),returncode=7))
        result=self.run_it(runner=runner)
        self.assertFalse(result["new_generated_h5_native_driver_certified"])
        self.assertEqual(result["new_native_h5_read_status"],
                         "native_subprocess_invalid_or_crashed")
        self.out.unlink()
        runner2=Mock(side_effect=subprocess.TimeoutExpired(
            ["python"],45,output=R.NATIVE.PHASE_MARKER.encode()+
            b"before_stock_manager"+bytes([10])))
        result2=self.run_it(runner=runner2,run_id="run002")
        self.assertEqual(result2["new_native_h5_read_status"],
                         "native_subprocess_timeout")
        self.assertEqual(result2["last_native_phase"],
                         "before_stock_manager")
        self.assertFalse(result2["new_generated_h5_six_native_records_matched"])

    def test_modified_source_during_worker_rejected_without_safe(self):
        def tamper(*args,**kwargs):
            self.synthetic.joinpath("sz_day.h5").write_bytes(b"changed midway")
            return fake_worker_result()
        with self.assertRaisesRegex(ValueError,"hash changed"):
            self.run_it(runner=Mock(side_effect=tamper))
        self.assertFalse(self.out.exists())

    def test_proof_bytes_changed_during_worker_rejected_even_if_semantically_same(self):
        # Newline-only changes remain parseable and may preserve all JSON flags;
        # exact SHA provenance must still fail closed for all THREE proof files.
        for ix,source in enumerate((self.canary,self.decimal,self.core),1):
            with self.subTest(source=source.name):
                original=source.read_bytes()
                def tamper_proof(*args,**kwargs):
                    source.write_bytes(original+b"\\n")
                    return fake_worker_result()
                try:
                    with self.assertRaisesRegex(
                            ValueError,"SAFE proof bytes changed during native reread"):
                        self.run_it(runner=Mock(side_effect=tamper_proof),
                                    run_id=f"run00{ix}")
                    self.assertFalse(self.out.exists())
                finally:
                    source.write_bytes(original)

    def test_original_canary_changed_during_worker_fails_closed(self):
        changed={
            **self.check,
            "source_file_details":{
                **self.check["source_file_details"],
                "sz_day.h5":{"sha256":"b"*64,"size_bytes":999}}}
        with patch.object(R.CHECK,"verify_canary",
                          side_effect=[self.check,changed]):
            with self.assertRaisesRegex(ValueError,"Original synthetic"):
                self.run_it()
        self.assertFalse(self.out.exists())

    def test_new_report_and_run_id_required_to_avoid_overwrite(self):
        self.out.write_text("original",encoding="utf-8")
        runner=Mock(side_effect=AssertionError("must not overwrite"))
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            self.run_it(runner=runner)
        self.out.unlink()
        self.run_it()
        self.out.unlink()
        with self.assertRaisesRegex(ValueError,"already exists"):
            self.run_it(runner=runner)
        runner.assert_not_called()

    def test_oversized_proof_rejected_before_native_spawn(self):
        self.core.write_bytes(b"x"*(R.MAX_PROOF_BYTES+1))
        runner=Mock(side_effect=AssertionError("must never spawn native worker"))
        with self.assertRaisesRegex(ValueError,"bounded synthetic SAFE proof"):
            self.run_it(runner=runner)
        runner.assert_not_called()
        self.assertFalse((self.synthetic/"_native_h5_281").exists())

    def test_never_allow_real_market_input_path_or_unbounded_timeout(self):
        runner=Mock(side_effect=AssertionError("must not access other source"))
        outsider=self.original/"actual_market"
        outsider.mkdir()
        with self.assertRaisesRegex(ValueError,"Only an existing direct"):
            R.native_recheck(self.canary,self.decimal,self.core,outsider,
                             self.python,self.out,runner=runner)
        for invalid in (0,9,121,True,"45"):
            with self.subTest(timeout=invalid):
                with self.assertRaisesRegex(ValueError,"10..120"):
                    self.run_it(runner=runner,timeout=invalid)
        for invalid in ("../foo","run/dir","",True):
            with self.subTest(run_id=invalid):
                with self.assertRaisesRegex(ValueError,"run-id"):
                    self.run_it(runner=runner,run_id=invalid)
        runner.assert_not_called()


if __name__=="__main__":
    unittest.main(verbosity=2)
