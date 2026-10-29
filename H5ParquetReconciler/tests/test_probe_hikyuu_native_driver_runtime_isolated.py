"""Synthetic, offline Hikyuu runtime capability probe tests (no Hikyuu needed)."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import h5py
import numpy as np

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "hikyuu_runtime_probe_under_test",
    HERE.parent/"tools"/"probe-hikyuu-native-driver-runtime-isolated.py")
P=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)

DTYPE=np.dtype([
    ("closePrice","<u4"),("datetime","<u8"),("highPrice","<u4"),
    ("lowPrice","<u4"),("openPrice","<u4"),("transAmount","<u8"),
    ("transCount","<u8")])


class IsolatedRuntimePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)/"H5ParquetReconciler"
        self.reports=root/"reports"
        self.mirrors=root/"work"/"h5_mirror"
        self.folder=self.mirrors/"isolated_canary"
        self.folder.mkdir(parents=True)
        self.reports.mkdir()
        blobs=[]
        for stock,file in P.STOCKS.items():
            with h5py.File(self.folder/file,"w") as fh:
                group=fh.create_group("data")
                arr=np.zeros(3,dtype=DTYPE)
                arr["datetime"]=P.DATES
                ds=group.create_dataset(stock,data=arr)
                ds.attrs["CLASS"]=b"TABLE"
            path=self.folder/file
            blobs.append({
                "stock":stock,
                "relative_output":"work/h5_mirror/isolated_canary/"+file,
                "synthetic_rows":3,
                "dtype_itemsize_bytes":40,
                "pytables_table":True,
                "h5py_and_pytables_roundtrip_values_equal":True,
                "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        self.canary=self.reports/"canary-safe.json"
        self.canary.write_text(json.dumps({
            "format":P.CANARY_FORMAT,
            "synthetic_only":True,
            "synthetic_record_count":6,
            "source_market_files_read":False,
            "original_hikyuu_h5_read":False,
            "purchased_parquet_read":False,
            "original_market_files_modified":False,
            "hikyuu_native_driver_tested":False,
            "safe_for_full_market_h5_mirror":False,
            "symbols":list(P.STOCKS),
            "generated_files":blobs,
        }),encoding="utf-8")
        self.out=self.reports/"native-runtime-probe-v1.json"
        for name,value in (
                ("MODULE",root),("REPORTS",self.reports),
                ("WORK",root/"work"),("MIRRORS",self.mirrors)):
            m=patch.object(P,name,value)
            m.start()
            self.addCleanup(m.stop)

    def valid_worker(self):
        payload={
            "module_imported":True,
            "runtime_status":"hikyuu_imported_without_initializing",
            "installed_distribution_version":"2.8.test",
            "public_api_presence":{"StockManager":True,
                                   "DataDriverFactory":False},
            "native_h5_driver_called":False,
            "stock_manager_initialized":False,
            "default_hikyuu_config_loaded":False}
        return SimpleNamespace(
            stdout="untrusted splash\n"+P.MARKER+json.dumps(payload)+"\n",
            returncode=0)

    def test_hikyuu_present_still_never_claims_native_driver_read(self):
        runner=Mock(return_value=self.valid_worker())
        result=P.runtime_preflight(self.canary,self.out,runner=runner)
        self.assertTrue(self.out.is_file())
        self.assertEqual(
            result["hikyuu_runtime_status"],"hikyuu_imported_without_initializing")
        self.assertEqual(result["installed_hikyuu_version"],"2.8.test")
        self.assertFalse(result["native_h5_driver_read_executed"])
        self.assertFalse(result["hikyuu_h5_compatibility_certified"])
        self.assertTrue(result["canary_file_hashes_reverified"])
        self.assertNotIn("untrusted splash",self.out.read_text(encoding="utf-8"))
        cmd=runner.call_args.args[0]
        self.assertEqual(cmd[1:3],["-I","-c"])
        self.assertNotIn("from hikyuu.interactive",cmd[3])
        self.assertNotIn("hikyuu_init(",cmd[3])
        self.assertIn("HOME",runner.call_args.kwargs["env"])
        self.assertTrue(runner.call_args.kwargs["cwd"].is_relative_to(self.folder))

    def test_explicit_alternate_python_path_without_installing_packages(self):
        # A real user could supply a pre-existing Anaconda python.exe.
        # This synthetic path is only invoked through a mock subprocess.
        alternate=self.folder/"alternate"/"python.exe"
        alternate.parent.mkdir()
        alternate.write_bytes(b"test-only interpreter placeholder")
        runner=Mock(return_value=self.valid_worker())
        safe=P.runtime_preflight(
            self.canary,self.out,runner=runner,python_exe=alternate)
        command=runner.call_args.args[0]
        self.assertEqual(command[0],str(alternate.resolve()))
        self.assertEqual(command[1:3],["-I","-c"])
        self.assertEqual(
            safe["hikyuu_runtime_status"],
            "hikyuu_imported_without_initializing")
        self.assertTrue(safe["explicit_alternate_python_requested"])
        self.assertTrue(safe["no_python_executable_path_in_safe_summary"])
        self.assertNotIn(str(alternate),self.out.read_text(encoding="utf-8"))
        self.assertFalse(safe["hikyuu_h5_compatibility_certified"])
        self.assertFalse(safe["native_h5_driver_read_executed"])
        # Argparse produces a concrete WindowsPath/PosixPath. A plain str
        # supplied by a Python API caller must remain supported too.
        string_out=self.reports/"native-runtime-string-path-v1.json"
        str_runner=Mock(return_value=self.valid_worker())
        string_result=P.runtime_preflight(
            self.canary,string_out,runner=str_runner,
            python_exe=str(alternate))
        self.assertEqual(
            str_runner.call_args.args[0][0],str(alternate.resolve()))
        self.assertTrue(string_result["explicit_alternate_python_requested"])
        self.assertFalse(string_result["native_h5_driver_read_executed"])

    def test_default_python_mode_remains_backward_compatible(self):
        runner=Mock(return_value=self.valid_worker())
        safe=P.runtime_preflight(self.canary,self.out,runner=runner)
        self.assertEqual(
            runner.call_args.args[0][0],
            str(Path(P.sys.executable).resolve()))
        self.assertFalse(safe["explicit_alternate_python_requested"])

    def test_reject_missing_relative_symlink_and_non_python_interpreter(self):
        nonexistent=self.folder/"missing"/"python.exe"
        invalids=[
            "python",nonexistent,self.folder/"other.bat",42,
        ]
        script=self.folder/"other.bat"
        script.write_bytes(b"nonexecutable")
        symlink=self.folder/"python.exe"
        try:
            symlink.symlink_to(script)
            invalids.append(symlink)
        except OSError:
            pass
        runner=Mock(side_effect=AssertionError("Must not spawn child"))
        for n,alternate in enumerate(invalids):
            with self.subTest(case=n):
                target=self.reports/("reject"+str(n)+".json")
                with self.assertRaisesRegex(ValueError,
                                            "absolute path|existing"):
                    P.runtime_preflight(
                        self.canary,target,runner=runner,python_exe=alternate)
                self.assertFalse(target.exists())
        runner.assert_not_called()

    def test_environment_scrubs_other_python_and_hikyuu_configuration(self):
        target=self.folder/"_isolated"
        with patch.dict(P.os.environ,{
                "HIKYUU_CONFIG":"real-data-unsafe",
                "HKU_HOME":"real-home-unsafe",
                "PYTHONPATH":"untrusted-path",
                "PYTHONHOME":"untrusted-python-home",
                "VIRTUAL_ENV":"another-venv",
                "CONDA_PREFIX":"another-conda"},clear=False):
            env=P._sandbox_env(target)
        for item in ("HIKYUU_CONFIG","HKU_HOME","PYTHONPATH",
                     "PYTHONHOME","VIRTUAL_ENV","CONDA_PREFIX"):
            self.assertNotIn(item,env)
        self.assertEqual(env["HOME"],str(target))
        self.assertEqual(env["USERPROFILE"],str(target))
        self.assertEqual(env["PYTHONNOUSERSITE"],"1")

    def test_hikyuu_missing_reports_unknown_compatibility_not_pass(self):
        worker=self.valid_worker()
        status=json.loads(worker.stdout.split(P.MARKER)[1])
        status["module_imported"]=False
        status["runtime_status"]="hikyuu_not_installed_in_this_interpreter"
        status["installed_distribution_version"]=None
        status["public_api_presence"]={}
        worker.stdout=P.MARKER+json.dumps(status)+"\n"
        safe=P.runtime_preflight(
            self.canary,self.out,runner=Mock(return_value=worker))
        self.assertFalse(safe["hikyuu_h5_compatibility_certified"])
        self.assertEqual(safe["hikyuu_runtime_status"],
                         "hikyuu_not_installed_in_this_interpreter")

    def test_byte_tamper_fails_before_subprocess_or_safe_report(self):
        with (self.folder/"sh_day.h5").open("ab") as fh:
            fh.write(b"mutation")
        runner=Mock(side_effect=AssertionError("must not invoke hikyuu"))
        with self.assertRaisesRegex(ValueError,"digest"):
            P.runtime_preflight(self.canary,self.out,runner=runner)
        runner.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_reject_untrusted_canary_provenance(self):
        data=json.loads(self.canary.read_text(encoding="utf-8"))
        data["original_market_files_modified"]=True
        self.canary.write_text(json.dumps(data),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"untrusted|non-synthetic"):
            P.verify_canary(self.canary)

    def test_reject_report_outside_module_and_existing_output(self):
        elsewhere=self.reports.parent/"other.json"
        elsewhere.write_text(self.canary.read_text(encoding="utf-8"),
                             encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"existing module reports"):
            P.verify_canary(elsewhere)
        self.out.write_text("{}")
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            P.runtime_preflight(self.canary,self.out)

    def test_timeout_or_child_crash_does_not_certify_native_driver(self):
        import subprocess
        cases=(
            subprocess.TimeoutExpired(["python"],1),
            SimpleNamespace(stdout="bad",returncode=5),
        )
        for i,event in enumerate(cases):
            target=self.reports/("safe"+str(i)+".json")
            runner=Mock(side_effect=event) if isinstance(
                event,Exception) else Mock(return_value=event)
            safe=P.runtime_preflight(self.canary,target,runner=runner)
            self.assertIn(safe["hikyuu_runtime_status"],
                          ("hikyuu_subprocess_startup_timeout","hikyuu_subprocess_failed"))
            self.assertFalse(safe["native_h5_driver_read_executed"])
            self.assertFalse(safe["hikyuu_h5_compatibility_certified"])

    def test_timeout_phases_distinguish_import_vs_exit_wait(self):
        self.assertEqual(
            P.timeout_phase(None),"hikyuu_subprocess_startup_timeout")
        # subprocess.TimeoutExpired.stdout is bytes on Python 3.11, even
        # when text=True. Use actual newline characters, NOT literal
        # backslash+n, to represent print(..., flush=True) output.
        lf=chr(10)
        before=(P.PHASE_MARKER+"before_import"+lf).encode("utf-8")
        self.assertEqual(P.timeout_phase(before),"hikyuu_import_timeout")
        after=before+(P.PHASE_MARKER+"after_import"+lf).encode("utf-8")
        self.assertEqual(
            P.timeout_phase(after),"hikyuu_post_import_probe_timeout")
        complete=after+(P.PHASE_MARKER+"after_probe"+lf).encode("utf-8")
        self.assertEqual(
            P.timeout_phase(complete),"hikyuu_subprocess_exit_timeout")
        self.assertEqual(P.timeout_phase("random import logs"),
                         "hikyuu_subprocess_startup_timeout")

        # Last line can be truncated at timeout without a newline.
        self.assertEqual(
            P.timeout_phase(P.PHASE_MARKER+"before_import"),
            "hikyuu_import_timeout")
        self.assertEqual(
            P.timeout_phase((P.PHASE_MARKER+"after_import").encode("utf-8")),
            "hikyuu_post_import_probe_timeout")
        # Literal escaped characters are NOT a complete phase marker.
        self.assertEqual(
            P.timeout_phase(P.PHASE_MARKER+r"before_import\n"),
            "hikyuu_subprocess_startup_timeout")

    def test_isolated_worker_bypasses_hanging_atexit_with_fake_hikyuu(self):
        # A synthetic hikyuu stub registers the exact type of problematic
        # atexit hook. The subprocess MUST exit rather than waiting on it.
        import subprocess
        import sys
        compile(P.WORKER,"hikyuu_runtime_probe_worker","exec")
        fake='''import atexit,sys,time,types
fake_hk=types.ModuleType("hikyuu")
sys.modules["hikyuu"]=fake_hk
atexit.register(lambda: time.sleep(15))
'''
        proc=subprocess.run(
            [sys.executable,"-I","-c",fake+P.WORKER],
            capture_output=True,text=True,timeout=7,check=False)
        self.assertEqual(proc.returncode,0)
        result=P.parse_worker(proc.stdout,proc.returncode)
        self.assertTrue(result["module_imported"])
        self.assertEqual(result["runtime_status"],
                         "hikyuu_imported_without_initializing")
        self.assertIn(P.PHASE_MARKER+"after_probe",proc.stdout)

    def test_unbounded_timeout_rejected_before_child_process(self):
        runner=Mock(side_effect=AssertionError("Must not spawn child"))
        for value in (0,5,121,True,"45"):
            with self.subTest(timeout=value):
                with self.assertRaisesRegex(ValueError,"between 10 and 120"):
                    P.runtime_preflight(
                        self.canary,self.out,runner=runner,timeout=value)
        runner.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_reject_worker_lying_about_native_driver_execution(self):
        worker=self.valid_worker()
        status=json.loads(worker.stdout.split(P.MARKER)[1])
        status["native_h5_driver_called"]=True
        worker.stdout=P.MARKER+json.dumps(status)+"\n"
        with self.assertRaisesRegex(ValueError,"invalid"):
            P.parse_worker(worker.stdout,0)

    def test_during_worker_byte_mutation_rejects_report(self):
        def mutate(*args,**kwargs):
            with (self.folder/"sz_day.h5").open("ab") as fh:
                fh.write(b"changed")
            return self.valid_worker()
        with self.assertRaisesRegex(ValueError,"changed during"):
            P.runtime_preflight(self.canary,self.out,runner=mutate)
        self.assertFalse(self.out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
