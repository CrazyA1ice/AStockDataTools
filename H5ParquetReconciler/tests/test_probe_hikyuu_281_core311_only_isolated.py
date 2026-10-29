"""Pure offline contract checks for core311-only Hikyuu 2.8.1 preflight."""
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
    "core311_only_probe_under_test",
    HERE.parent/"tools"/"probe-hikyuu-281-core311-only-isolated.py")
P=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def worker(valid=True):
    result={
        "status":"core311_bindings_ready" if valid else "core311_bindings_incomplete",
        "distribution_version":"2.8.1","python311_confirmed":True,
        "package_location_verified":True,"core_loaded":True,
        "public_core_apis":{name:(valid or name!="KRecord")
                            for name in P.REQUIRED_APIS},
        "top_level_hikyuu_initializer_executed":False,
        "stock_manager_initialized":False,
        "native_h5_driver_called":False,
    }
    return SimpleNamespace(stdout="irrelevant log must be discarded\n"+
        P.PHASE_MARKER+"before_lookup\n"+
        P.PHASE_MARKER+"before_core_import\n"+
        P.PHASE_MARKER+"core_imported\n"+
        P.MARKER+json.dumps(result)+"\n",returncode=0)


class Core311OnlyPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)/"H5ParquetReconciler"
        self.root=root
        self.report_dir=root/"reports"
        self.canary_dir=root/"work"/"h5_mirror"/"isolated_canary"
        self.canary_dir.mkdir(parents=True)
        self.report_dir.mkdir()
        self.canary=self.report_dir/"synthetic.json"
        self.canary.write_text("{}",encoding="utf-8")
        self.output=self.report_dir/"core311.json"
        self.python=root/"python311"/"python.exe"
        self.python.parent.mkdir()
        self.python.write_text("dummy interpreter",encoding="utf-8")
        verified={
            "isolated_canary_dir":self.canary_dir,
            "report_sha256":"e"*64,
            "source_file_details":{
                "sh_day.h5":{"sha256":"a"*64,"size_bytes":123},
                "sz_day.h5":{"sha256":"b"*64,"size_bytes":123}
            }}
        self.verified=verified
        patches=[
            patch.object(P.CHECK,"verify_canary",return_value=verified),
            patch.object(P.CHECK,"REPORTS",self.report_dir),
            patch.object(P.CHECK,"WORK",root/"work"),
            patch.object(P.CHECK,"MIRRORS",root/"work"/"h5_mirror"),
        ]
        for one in patches:
            one.start()
            self.addCleanup(one.stop)

    def test_worker_is_core_only_without_stock_manager_init(self):
        compile(P.WORKER,"isolated_core311_preflight","exec")
        self.assertIn('sys.modules["hikyuu"]=package',P.WORKER)
        self.assertIn('importlib.import_module("hikyuu.core")',P.WORKER)
        self.assertIn('os._exit(0)',P.WORKER)
        self.assertNotIn("stock_manager.init(",P.WORKER.lower())
        self.assertNotIn('importlib.import_module("hikyuu.draw")',P.WORKER)
        self.assertNotIn("hikyuu_init(",P.WORKER)
        self.assertIn("find_spec",P.WORKER)

    def test_valid_core311_bindings_never_certify_native_h5(self):
        run=Mock(return_value=worker())
        safe=P.probe_core(self.canary,self.output,self.python,runner=run)
        self.assertTrue(safe["core311_bindings_ready"])
        self.assertEqual(safe["hikyuu_core311_status"],"core311_bindings_ready")
        self.assertEqual(safe["last_core311_phase"],"core_imported")
        self.assertTrue(all(safe["public_core_api_presence"].values()))
        self.assertFalse(safe["native_h5_driver_read_executed"])
        self.assertFalse(safe["hikyuu_h5_compatibility_certified"])
        self.assertFalse(safe["full_market_mirror_allowed"])
        self.assertNotIn("irrelevant log",self.output.read_text(encoding="utf-8"))
        cmd=run.call_args.args[0]
        self.assertEqual(cmd[:3],[str(self.python.resolve()),"-I","-c"])
        self.assertEqual(cmd[3],P.WORKER)
        self.assertTrue(run.call_args.kwargs["cwd"].is_relative_to(
            self.canary_dir))
        self.assertNotIn(str(self.python),self.output.read_text(encoding="utf-8"))

    def test_incomplete_bindings_are_not_ready(self):
        run=Mock(return_value=worker(valid=False))
        safe=P.probe_core(self.canary,self.output,self.python,runner=run)
        self.assertFalse(safe["core311_bindings_ready"])
        self.assertFalse(safe["native_h5_driver_read_executed"])
        self.assertEqual(safe["hikyuu_core311_status"],
                         "core311_bindings_incomplete")

    def test_reject_forged_success_missing_core_api_or_unsafe_side_effect(self):
        r=json.loads(worker().stdout.split(P.MARKER,1)[1])
        r["public_core_apis"]["KRecord"]=False
        self.assertIsNone(P.parse_core_worker(P.MARKER+json.dumps(r),0))
        r["public_core_apis"]["KRecord"]=True
        r["stock_manager_initialized"]=True
        self.assertIsNone(P.parse_core_worker(P.MARKER+json.dumps(r),0))
        self.assertIsNone(P.parse_core_worker(worker().stdout,7))
        self.assertIsNone(P.parse_core_worker(worker().stdout+worker().stdout,0))

    def test_timeout_phase_is_allowlisted_and_stdout_not_saved(self):
        stdout=("secret stack and private path\n"+P.PHASE_MARKER+
                "before_lookup\n"+P.PHASE_MARKER+"before_core_import\n")
        run=Mock(side_effect=subprocess.TimeoutExpired(
            ["python"],35,output=stdout.encode("utf-8")))
        safe=P.probe_core(self.canary,self.output,self.python,runner=run)
        self.assertEqual(safe["hikyuu_core311_status"],"core311_import_timeout")
        self.assertEqual(safe["last_core311_phase"],"before_core_import")
        self.assertFalse(safe["core311_bindings_ready"])
        self.assertNotIn("secret stack",self.output.read_text(encoding="utf-8"))
        self.assertEqual(P.last_phase(P.PHASE_MARKER+"secret"),
                         None)
        self.assertEqual(P.last_phase(None),None)

    def test_missing_explicit_python_and_unbounded_timeout_rejected(self):
        run=Mock(side_effect=AssertionError("unexpected child"))
        for value in (None,"python",self.root/"missing"/"python.exe"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    P.probe_core(self.canary,self.output,value,runner=run)
        for bad in (-2,5,91,True,"35"):
            with self.subTest(timeout=bad):
                with self.assertRaisesRegex(ValueError,"10..90"):
                    P.probe_core(self.canary,self.output,self.python,
                                 runner=run,timeout=bad)
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_existing_safe_output_rejected_before_subprocess(self):
        self.output.write_text("do not overwrite",encoding="utf-8")
        run=Mock(side_effect=AssertionError("must not run"))
        with self.assertRaisesRegex(ValueError,"NEW SAFE"):
            P.probe_core(self.canary,self.output,self.python,runner=run)
        run.assert_not_called()

    def test_source_tampering_rejected_without_safe_report(self):
        mutated=dict(self.verified)
        mutated["source_file_details"]={
            **self.verified["source_file_details"],
            "sz_day.h5":{"sha256":"d"*64,"size_bytes":123}}
        with patch.object(P.CHECK,"verify_canary",
                          side_effect=(self.verified,mutated)):
            with self.assertRaisesRegex(ValueError,"changed"):
                P.probe_core(self.canary,self.output,self.python,
                             runner=Mock(return_value=worker()))
        self.assertFalse(self.output.exists())

    def test_child_crash_not_certified(self):
        run=Mock(return_value=SimpleNamespace(
            stdout=P.PHASE_MARKER+"before_core_import\n",
            returncode=3221225477))
        safe=P.probe_core(self.canary,self.output,self.python,runner=run)
        self.assertEqual(safe["hikyuu_core311_status"],
                         "core311_subprocess_failed")
        self.assertFalse(safe["core311_bindings_ready"])


if __name__=="__main__":
    unittest.main(verbosity=2)
