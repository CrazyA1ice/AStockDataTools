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
        "state":state,"hikyuu_imported":True,
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
        stdout="Hikyuu banner not for SAFE\n"+N.MARKER+
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
            self.manifest,self.out,self.alt,runner=runner,**kwargs)
        return report,runner

    def test_native_worker_is_valid_python_and_has_no_default_initializer(self):
        compile(N.WORKER,"hikyuu_native_281_worker","exec")
        self.assertNotIn("hikyuu_init(",N.WORKER)
        self.assertNotIn("hikyuu.interactive",N.WORKER)
        self.assertIn('stock.get_kdata(hk.Query(0,3,hk.Query.DAY))',N.WORKER)
        self.assertIn('base=p(type="sqlite3",db=str(db))',N.WORKER)
        self.assertIn('kdata=p(type="hdf5",sh_day=str(sh),sz_day=str(sz))',N.WORKER)
        self.assertIn('load_history_finance=False',N.WORKER)

    def test_success_requires_six_exact_synthetic_native_krecords(self):
        safe,runner=self.runmock()
        self.assertTrue(safe["native_h5_compatibility_certified_for_synthetic_v1"])
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
        self.assertEqual(runner.call_args.kwargs["cwd"],
                         self.folder/"_native_h5_281"/"run")
        self.assertEqual(len(args),7)
        self.assertEqual(args[-2:],[str(self.folder/"sh_day.h5"),
                                    str(self.folder/"sz_day.h5")])

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
        safe=N.native_read(self.manifest,self.out,self.alt,runner=runner)
        self.assertEqual(safe["native_h5_read_status"],"native_subprocess_timeout")
        self.assertFalse(safe["native_h5_compatibility_certified_for_synthetic_v1"])

    def test_reject_existing_scratch_and_report_without_running(self):
        self.out.write_text("existing",encoding="utf-8")
        runner=Mock(side_effect=AssertionError("must not run"))
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            N.native_read(self.manifest,self.out,self.alt,runner=runner)
        self.out.unlink()
        folder=self.folder/"_native_h5_281"
        folder.mkdir()
        with self.assertRaisesRegex(ValueError,"already exists"):
            N.native_read(self.manifest,self.out,self.alt,runner=runner)
        runner.assert_not_called()

    def test_cannot_run_without_explicit_valid_python(self):
        runner=Mock(side_effect=AssertionError("never run"))
        with self.assertRaisesRegex(ValueError,"--python-exe"):
            N.native_read(self.manifest,self.out,None,runner=runner)
        for value in ("python",self.root/"missing"/"python.exe"):
            with self.assertRaisesRegex(ValueError,"absolute path|existing"):
                N.native_read(self.manifest,self.out,value,runner=runner)
        runner.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_source_tamper_during_child_rejected_without_report(self):
        good=dict(self.file_check)
        changed=dict(good)
        changed["source_file_details"]=dict(good["source_file_details"])
        changed["source_file_details"]["sz_day.h5"]={
            "sha256":"0"*64,"size_bytes":5}
        self.verifier.side_effect=[good,changed]
        runner=Mock(return_value=result())
        with self.assertRaisesRegex(ValueError,"changed during"):
            N.native_read(self.manifest,self.out,self.alt,runner=runner)
        self.assertFalse(self.out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
