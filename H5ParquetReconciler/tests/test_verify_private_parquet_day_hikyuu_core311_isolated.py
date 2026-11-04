"""Two narrow checks for native Hikyuu real private DAY verifier.

No real Hikyuu subprocess in tests: local H5 comes from synthetic canary
writer fixture; C++ worker result is mocked. Real core311 check is Windows-only.
"""
import ast
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/"tools"

def load(tag,path):
    spec=importlib.util.spec_from_file_location(tag,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

N=load("synthetic_private_native_checker",
       TOOLS/"verify-private-parquet-day-hikyuu-core311-isolated.py")
FIX=load("synthetic_private_writer_fixture",
         HERE/"test_write_private_parquet_day_to_hikyuu_h5_canary.py")


class NativeRealPrivateDayVerifierTests(unittest.TestCase):
    def setUp(self):
        self.f=FIX.RealHikyuuH5DayCanaryTests(
            "test_actual_h5_dataset_written_and_compound_roundtrip")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.output=self.f.reports/"cpp-native-proof.json"
        self.prior=self.f.run_stage(self.f.bar)
        self.patchers=[
            patch.object(N,"MODULE",self.f.base),
            patch.object(N,"CANARIES",self.f.out),
            patch.object(N,"REPORTS",self.f.reports),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_fictional_core311_worker_compiles_and_private_sha_is_pinned(self):
        ast.parse(N.WORKER)
        self.assertIn("stock.get_kdata",N.WORKER)
        self.assertIn("native_private_h5_all_rows_matched",N.WORKER)
        doc,file=N.audited_source(self.f.safe)
        self.assertEqual(doc["written_h5_integer_rows"],1)
        self.assertTrue(file.is_file())
        with file.open("ab") as fp:
            fp.write(b"synthetic-local-tamper")
        with self.assertRaisesRegex(ValueError,"SHA changed"):
            N.audited_source(self.f.safe)
        self.assertFalse(self.output.exists())

    def test_mocked_native_core311_result_checks_exact_count_and_safe_summary(self):
        result={
            "state":"native_private_h5_all_rows_matched",
            "core311_loaded":True,
            "full_hikyuu_package_imported":False,
            "hikyuu_281_version_confirmed":True,
            "synthetic_registry_initialized":True,
            "stock_manager_initialized":True,
            "native_h5_kdata_method_called":True,
            "native_h5_values_matched":True,
            "per_symbol_matching_rows":{"SH600000":1,"SZ000001":0},
            "source_market_files_accessed":False,
            "production_query_switched":False,
        }
        def runner(*args,**kwargs):
            self.assertIn("ASTOCKTOOLS_NATIVE_H5_281_RESULT:",N.NATIVE.MARKER)
            raw=N.NATIVE.PHASE_MARKER+"finished\n"+N.NATIVE.MARKER+json.dumps(result)+"\n"
            return SimpleNamespace(stdout=raw.encode("ascii"),returncode=0)
        with patch.object(N.CHECK,"_explicit_python",
                          return_value=Path("C:/fake/python.exe")):
            saved=N.verify(self.f.safe,Path("C:/fake/python.exe"),
                           self.output,"123456789abc",runner=runner)
        self.assertEqual(saved["native_krecord_rows_matched"],1)
        self.assertTrue(saved["native_h5_get_kdata_called"])
        self.assertFalse(saved["full_market_h5_mirror_completed"])
        summary=self.output.read_text(encoding="utf-8")
        self.assertNotIn("2026-09-30",summary)
        self.assertNotIn('"SH600000"',summary)
        self.assertNotIn("230000.0",summary)


if __name__=="__main__":
    unittest.main(verbosity=2)
