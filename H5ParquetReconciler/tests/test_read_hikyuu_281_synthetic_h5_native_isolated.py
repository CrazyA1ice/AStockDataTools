"""Offline native Hikyuu 2.8.1 runner contract tests; NO live Hikyuu needed."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "native_h5_281_under_test",
    HERE.parent/"tools"/"read-hikyuu-281-synthetic-h5-native-isolated.py")
N=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(N)


def result(state="native_h5_six_synthetic_rows_matched"):
    passed=state=="native_h5_six_synthetic_rows_matched"
    data={
        "state":state,"core311_loaded":True,
        "full_hikyuu_package_imported":False,
        "hikyuu_281_version_confirmed":True,
        "synthetic_registry_initialized":True,
        "stock_manager_initialized":True,
        "native_h5_kdata_method_called":True,
        "native_h5_values_matched":passed,
        "per_symbol_matching_rows":{
            "SH600000":3 if passed else 2,
            "SZ000001":3 if passed else 0},
        "source_market_files_accessed":False,
        "production_query_switched":False
    }
    return SimpleNamespace(
        stdout="Hikyuu banner not for SAFE\n"+
               N.PHASE_MARKER+"finished\n"+N.MARKER+
               json.dumps(data)+"\n",returncode=0)


class Hikyuu281NativeIsolatedTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)/"H5ParquetReconciler"
        self.reports=self.root/"reports"
        self.folder=self.root/"work"/"h5_mirror"/"synthetic_canary"
        self.folder.mkdir(parents=True)
        self.reports.mkdir()
        self.manifest=self.reports/"synthetic-canary.json"
        self.manifest.write_text("{}",encoding="utf-8")
        self.out=self.reports/"hikyuu-native-test-safe.json"
        self.core_proof=self.reports/"verified-core311-safe.json"
        self.core_proof.write_text(json.dumps({
            "format":N.CORE_PROOF_FORMAT,
            "canary_safe_summary_sha256":"a"*64,
            "canary_file_hashes_reverified":True,
            "isolated_core311_only":True,
            "explicit_python_executable_used":True,
            "hikyuu_core311_status":"core311_bindings_ready",
            "last_core311_phase":"finished",
            "hikyuu_distribution_version":"2.8.1",
            "public_core_api_presence":{
                name:True for name in N.REQUIRED_CORE_APIS},
            "core311_bindings_ready":True,
            "hikyuu_full_package_imported":False,
            "stock_manager_initialized":False,
            "native_h5_driver_read_executed":False,
            "hikyuu_h5_compatibility_certified":False,
            "licensed_parquet_to_h5_mapping_certified":False,
            "full_market_mirror_allowed":False,
            "no_licensed_market_data_read":True,
            "original_market_files_modified":False,
            "original_hikyuu_config_modified":False,
            "private_overlay_activated":False,
            "no_raw_ohlcva_or_worker_logs_in_safe_summary":True,
        }),encoding="utf-8")
        self.alt=self.root/"python311"/"python.exe"
        self.alt.parent.mkdir()
        self.alt.write_bytes(b"offline mock interpreter")
        self.file_check={
            "isolated_canary_dir":self.folder,
            "report_sha256":"a"*64,
            "source_file_details":{
                "sh_day.h5":{"sha256":"b"*64,"size_bytes":4},
                "sz_day.h5":{"sha256":"c"*64,"size_bytes":4},
            }}
        for mod,key,val in (
                (N,"MODULE",self.root),(N,"REPORTS",self.reports),
                (N,"WORK",self.root/"work"),
                (N,"MIRRORS",self.root/"work"/"h5_mirror"),
                (N.CHECK,"REPORTS",self.reports)):
            p=patch.object(mod,key,val)
            p.start()
            self.addCleanup(p.stop)
        p=patch.object(N.CHECK,"verify_canary",return_value=self.file_check)
        self.verifier=p.start()
        self.addCleanup(p.stop)

    def runmock(self,process=None,**kwargs):
        runner=Mock(return_value=process or result())
        report=N.native_read(
            self.manifest,self.out,self.alt,runner=runner,
            core_proof=self.core_proof,**kwargs)
        return report,runner

    def test_native_worker_is_valid_python_and_has_no_default_initializer(self):
        compile(N.WORKER,"hikyuu_native_281_worker","exec")
        self.assertNotIn("hikyuu_init(",N.WORKER)
        self.assertNotIn("\nimport hikyuu.interactive\n",N.WORKER)
        self.assertIn('stock.get_kdata(hk.Query(0,3,hk.Query.DAY))',N.WORKER)
        self.assertIn('hk=importlib.import_module("hikyuu.core")',N.WORKER)
        self.assertIn('sys.modules["hikyuu"]=package',N.WORKER)
        self.assertNotIn(chr(10)+"    import hikyuu as hk"+chr(10),N.WORKER)
        self.assertIn("hikyuu.cpp.core311",N.WORKER)
        self.assertIn('base=p(type="sqlite3",db=str(db))',N.WORKER)
        self.assertIn('kdata=p(type="hdf5",sh_day=str(sh),sz_day=str(sz))',N.WORKER)
        self.assertIn('load_history_finance=False',N.WORKER)
        self.assertIn("os._exit(0)",N.WORKER)
        self.assertIn("print(PREFIX+json.dumps(out,sort_keys=True),flush=True)",N.WORKER)

    def test_success_requires_six_exact_synthetic_native_krecords(self):
        safe,runner=self.runmock()
        self.assertTrue(safe["native_h5_compatibility_certified_for_synthetic_v1"])
        self.assertTrue(safe["verified_prior_core311_only_safe_proof"])
        self.assertTrue(safe["native_core311_loaded"])
        self.assertEqual(safe["last_native_phase"],"finished")
        self.assertFalse(safe["full_hikyuu_package_imported"])
        self.assertTrue(safe["native_h5_synthetic_six_records_matched"])
        self.assertFalse(safe["licensed_parquet_to_h5_mapping_certified"])
        self.assertFalse(safe["ready_for_full_market_mirror"])
        self.assertTrue(safe["native_worker_stdout_stderr_not_saved"])
        self.assertEqual(safe["per_symbol_matching_rows"],
                         {"SH600000":3,"SZ000001":3})
        self.assertNotIn("Hikyuu banner",self.out.read_text(encoding="utf-8"))
        args=runner.call_args.args[0]
        self.assertEqual(args[:3],[str(self.alt.resolve()),"-I","-c"])
        self.assertEqual(args[3],N.WORKER)
        # Never allow Windows text-mode GBK/CP936 log decoding in reader threads.
        self.assertIs(runner.call_args.kwargs["text"],False)
        self.assertEqual(runner.call_args.kwargs["cwd"],
                         self.folder/"_native_h5_281"/"run001")
        self.assertEqual(len(args),7)
        self.assertEqual(args[-2:],[str(self.folder/"sh_day.h5"),
                                    str(self.folder/"sz_day.h5")])

    def test_native_mixed_encoding_windows_bytes_are_parsed_without_gbk(self):
        # Chinese native/C++ logs can mix UTF-8 and invalid GBK sequences.
        # Only ASCII SAFE markers and JSON are relevant to success.
        worker=result()
        raw=(b"native log: "+bytes([0xac,0xff,0x81])+bytes([10])
             +bytes([0xe4,0xb8,0xad,0xe6,0x96,0x87])+bytes([13,10])
             +worker.stdout.encode("ascii")
             +bytes([10])+b"invalid trailing log "+bytes([0x81,0xac]))
        proc=SimpleNamespace(stdout=raw,stderr=bytes([0xac]),
                             returncode=0)
        safe,runner=self.runmock(process=proc)
        self.assertEqual(safe["last_native_phase"],"finished")
        self.assertEqual(safe["per_symbol_matching_rows"],
                         {"SH600000":3,"SZ000001":3})
        self.assertTrue(safe["native_h5_synthetic_six_records_matched"])
        self.assertTrue(safe["native_h5_compatibility_certified_for_synthetic_v1"])
        self.assertIs(runner.call_args.kwargs["text"],False)
        reported=self.out.read_text(encoding="utf-8")
        self.assertNotIn("native log",reported)
        self.assertNotIn("invalid trailing log",reported)
        self.assertNotIn("Hikyuu banner",reported)

    def test_none_stdout_or_bad_binary_cannot_claim_native_success(self):
        for index,payload in enumerate((
            None,
            b"unstructured native logs only "+bytes([0xac,0xff]),
            N.PHASE_MARKER.encode("ascii")+b"finished"+bytes([10])
                +N.MARKER.encode("ascii")+b"{bad json",
        )):
            with self.subTest(index=index):
                if index:
                    self.out.unlink()
                proc=SimpleNamespace(stdout=payload,stderr=None,
                                     returncode=0)
                safe,_=self.runmock(process=proc,run_id="run"+str(index+100))
                self.assertEqual(safe["native_h5_read_status"],
                                 "native_subprocess_invalid_or_crashed")
                self.assertFalse(safe["native_h5_synthetic_six_records_matched"])
                self.assertFalse(safe["native_h5_compatibility_certified_for_synthetic_v1"])
                self.assertFalse(safe["native_h5_get_kdata_called"])
        self.assertIsNone(N.parse_native(None,0))
        self.assertIsNone(N.last_native_phase(None))

    def test_duplicate_or_invalid_binary_safe_markers_fail_closed(self):
        worker=result()
        ascii_payload=worker.stdout.encode("ascii")
        twice=ascii_payload+ascii_payload
        self.assertIsNone(N.parse_native(twice,0))
        self.assertIsNone(N.parse_native(ascii_payload,3221225477))
        # Corrupt the structured JSON marker, not just unrelated noise.
        invalid=ascii_payload.replace(
            N.MARKER.encode("ascii")+b"{",
            N.MARKER.encode("ascii")+bytes([0xac])+b"{")
        self.assertIsNone(N.parse_native(invalid,0))
        self.assertIsNone(N.last_native_phase(
            N.PHASE_MARKER.encode("ascii")+bytes([0xac])+b"finished"))

    def test_partial_rows_never_certified(self):
        safe,runner=self.runmock(process=result("native_h5_value_mismatch"))
        self.assertFalse(safe["native_h5_synthetic_six_records_matched"])
        self.assertFalse(safe["native_h5_compatibility_certified_for_synthetic_v1"])
        self.assertEqual(safe["native_h5_read_status"],"native_h5_value_mismatch")

    def test_bad_return_and_forged_green_status_fail_closed(self):
        forged=json.loads(result().stdout.split(N.MARKER,1)[1])
        forged["per_symbol_matching_rows"]["SZ000001"]=1
        r=N.parse_native(N.MARKER+json.dumps(forged),0)
        self.assertIsNone(r)
        self.assertIsNone(N.parse_native(N.MARKER+json.dumps(forged),5))
        self.assertIsNone(N.parse_native("banner only",0))
        forged["per_symbol_matching_rows"]["SZ000001"]=3
        forged["source_market_files_accessed"]=True
        self.assertIsNone(N.parse_native(N.MARKER+json.dumps(forged),0))

    def test_child_crash_and_timeout_are_not_certified(self):
        crash=SimpleNamespace(stdout="",returncode=3221225477)
        safe,_=self.runmock(process=crash)
        self.assertEqual(safe["native_h5_read_status"],
                         "native_subprocess_invalid_or_crashed")
        self.assertFalse(safe["native_h5_compatibility_certified_for_synthetic_v1"])
        self.out.unlink()
        # New scratch must be a new child directory for every run.
        # Simulate fresh test by removing only test-created scratch.
        import shutil
        shutil.rmtree(self.folder/"_native_h5_281")
        runner=Mock(side_effect=subprocess.TimeoutExpired(["python"],1))
        safe=N.native_read(self.manifest,self.out,self.alt,runner=runner,
                      core_proof=self.core_proof)
        self.assertEqual(safe["native_h5_read_status"],"native_subprocess_timeout")
        self.assertFalse(safe["native_h5_compatibility_certified_for_synthetic_v1"])

    def test_reject_existing_scratch_and_report_without_running(self):
        self.out.write_text("existing",encoding="utf-8")
        runner=Mock(side_effect=AssertionError("must not run"))
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            N.native_read(self.manifest,self.out,self.alt,runner=runner,
                      core_proof=self.core_proof)
        self.out.unlink()
        folder=self.folder/"_native_h5_281"/"run001"
        folder.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,"already exists"):
            N.native_read(self.manifest,self.out,self.alt,runner=runner,
                      core_proof=self.core_proof)
        runner.assert_not_called()

    def test_separate_run_id_allows_retry_without_reusing_scratch(self):
        first,_=self.runmock()
        self.assertTrue(first["native_h5_synthetic_six_records_matched"])
        self.out.unlink()
        retry=N.native_read(
            self.manifest,self.out,self.alt,
            runner=Mock(return_value=result()),run_id="run002",
            core_proof=self.core_proof)
        self.assertTrue(retry["native_h5_synthetic_six_records_matched"])
        self.assertTrue((self.folder/"_native_h5_281"/"run001").is_dir())
        self.assertTrue((self.folder/"_native_h5_281"/"run002").is_dir())
        self.out.unlink()
        for bad in ("..","run/a","",1):
            with self.subTest(run_id=bad):
                with self.assertRaisesRegex(ValueError,"safe --run-id"):
                    N.native_read(
                        self.manifest,self.out,self.alt,
                        runner=Mock(side_effect=AssertionError("must not run")),
                        run_id=bad,core_proof=self.core_proof)
                self.assertFalse(self.out.exists())

    def test_cannot_run_without_explicit_valid_python(self):
        runner=Mock(side_effect=AssertionError("never run"))
        with self.assertRaisesRegex(ValueError,"--python-exe"):
            N.native_read(self.manifest,self.out,None,runner=runner,
                          core_proof=self.core_proof)
        for value in ("python",self.root/"missing"/"python.exe"):
            with self.assertRaisesRegex(ValueError,"absolute path|existing"):
                N.native_read(self.manifest,self.out,value,runner=runner,
                              core_proof=self.core_proof)
        runner.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_only_matching_successful_core311_proof_can_allow_trial(self):
        runner=Mock(side_effect=AssertionError("must not execute child"))
        with self.assertRaisesRegex(ValueError,"--core-proof"):
            N.native_read(self.manifest,self.out,self.alt,runner=runner)
        baseline=json.loads(self.core_proof.read_text(encoding="utf-8"))
        edits=(
            {"hikyuu_core311_status":"core311_import_timeout"},
            {"canary_safe_summary_sha256":"0"*64},
            {"hikyuu_full_package_imported":True},
            {"native_h5_driver_read_executed":True},
            {"public_core_api_presence":dict(
                baseline["public_core_api_presence"],Query=False)},
            {"full_market_mirror_allowed":True},
            {"hikyuu_distribution_version":"2.8.0"},
        )
        for edit in edits:
            with self.subTest(edit=edit):
                self.core_proof.write_text(
                    json.dumps(dict(baseline,**edit)),encoding="utf-8")
                with self.assertRaisesRegex(
                        ValueError,"core311 SAFE proof|required APIs"):
                    N.native_read(self.manifest,self.out,self.alt,
                                  runner=runner,core_proof=self.core_proof)
                self.assertFalse(self.out.exists())
        self.core_proof.write_text(json.dumps(baseline),encoding="utf-8")
        runner.assert_not_called()

    def test_native_phase_progress_and_missing_finished_marker(self):
        trace=chr(10).join((
            N.PHASE_MARKER+"before_core311",
            N.PHASE_MARKER+"core311_loaded",
            N.PHASE_MARKER+"registry_ready",
            N.PHASE_MARKER+"before_stock_manager",
        ))
        self.assertEqual(N.last_native_phase(trace),"before_stock_manager")
        self.assertEqual(
            N.last_native_phase((trace+chr(10)+"private stack trace").encode()),
            "before_stock_manager")
        self.assertIsNone(N.last_native_phase("untrusted path only"))
        self.assertIsNone(N.last_native_phase(
            N.PHASE_MARKER+"unknown_stage"))
        success=result()
        success.stdout=success.stdout.replace(
            N.PHASE_MARKER+"finished"+chr(10),"")
        safe,_=self.runmock(process=success)
        self.assertFalse(safe["native_h5_synthetic_six_records_matched"])
        self.assertFalse(
            safe["native_h5_compatibility_certified_for_synthetic_v1"])
        self.assertIsNone(safe["last_native_phase"])

    def test_native_timeout_reports_safe_progress_only(self):
        stdout=(N.PHASE_MARKER+"before_core311"+chr(10)
                +N.PHASE_MARKER+"core311_loaded"+chr(10)
                +N.PHASE_MARKER+"before_stock_manager"+chr(10)
                +"secret path should never appear in SAFE JSON")
        run=Mock(side_effect=subprocess.TimeoutExpired(
            ["python"],45,output=stdout.encode("utf-8")))
        safe=N.native_read(self.manifest,self.out,self.alt,
                           runner=run,core_proof=self.core_proof)
        self.assertEqual(safe["native_h5_read_status"],
                         "native_subprocess_timeout")
        self.assertEqual(safe["last_native_phase"],
                         "before_stock_manager")
        self.assertFalse(safe["native_h5_synthetic_six_records_matched"])
        self.assertNotIn("secret path",
                         self.out.read_text(encoding="utf-8"))

    def test_native_success_forged_without_core311_rejected(self):
        payload=json.loads(result().stdout.split(N.MARKER,1)[1])
        payload["core311_loaded"]=False
        self.assertIsNone(N.parse_native(N.MARKER+json.dumps(payload),0))
        payload["core311_loaded"]=True
        payload["full_hikyuu_package_imported"]=True
        self.assertIsNone(N.parse_native(N.MARKER+json.dumps(payload),0))

    def test_source_tamper_during_child_rejected_without_report(self):
        good=dict(self.file_check)
        changed=dict(good)
        changed["source_file_details"]=dict(good["source_file_details"])
        changed["source_file_details"]["sz_day.h5"]={
            "sha256":"0"*64,"size_bytes":5}
        self.verifier.side_effect=[good,changed]
        runner=Mock(return_value=result())
        with self.assertRaisesRegex(ValueError,"changed during"):
            N.native_read(self.manifest,self.out,self.alt,runner=runner,
                      core_proof=self.core_proof)
        self.assertFalse(self.out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
