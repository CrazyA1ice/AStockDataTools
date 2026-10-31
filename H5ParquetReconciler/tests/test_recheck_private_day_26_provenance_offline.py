"""Synthetic offline historical-five-SAFE and version SHA recheck tests."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M=load("provenance_recheck_test",
       HERE.parent/"tools"/"recheck-private-day-26-provenance-offline.py")
F=load("provenance_bridge_fixture_test",
       HERE/"test_audit_private_day_26_factor_evidence_offline.py")


class OfflineProvenanceTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir=Path(td.name)
        self.reports=self.dir/"reports"
        self.reports.mkdir()
        self.old=self.reports/"ten.json"
        self.new=self.reports/"sixteen.json"
        self.bridge=self.reports/"26.json"
        self.output=self.reports/"result.json"
        self.files={}
        for k in M.EXPECTED_ROLES:
            path=self.reports/(k+".json")
            path.write_bytes(json.dumps({"format":"fictional","role":k}).encode())
            self.files[k]=path
        old=F.prior()
        old["five_safe_sha256"]={
            k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in self.files.items()}
        self.old.write_bytes(json.dumps(old,sort_keys=True).encode())
        self.new.write_bytes(json.dumps(F.newer(),sort_keys=True).encode())
        p=patch.object(M.BRIDGE,"REPORTS",self.reports)
        p.start()
        self.addCleanup(p.stop)
        M.BRIDGE.audit(self.old,self.new,self.bridge)
        self.version={
            "version_sha256":M.BRIDGE.VERSION,
            "candidate_total_new_stockday_rows":22274,
            "whole_day_candidate_rows":22191,
            "mixed_stockday_candidate_rows":83,
            "quarantined_2026_07_16_stockday_bars_not_included":5,
            "ready_for_production_query":False,
            "candidate_source_units_certified":False,
        }
        self.registry=patch.object(M.REG,"load_version",return_value=self.version)
        self.load_mock=self.registry.start()
        self.addCleanup(self.registry.stop)
        self.lock=patch.object(M.REG,"LOCK",self.dir/"no-registrar")
        self.lock.start()
        self.addCleanup(self.lock.stop)

    def run_audit(self):
        return M.audit(self.bridge,self.old,self.new,self.files,
                       M.BRIDGE.VERSION,self.output)

    def test_all_seven_actual_file_sha_rehashed_and_version_loaded(self):
        r=self.run_audit()
        self.assertEqual(r["historical_underlying_safe_count"],5)
        self.assertEqual(r["total_aggregate_safe_count"],2)
        self.assertEqual(r["bridge_safe_count"],1)
        self.assertEqual(len(r["source_safe_sha256"]),8)
        self.assertTrue(r["five_underlying_source_safe_files_independently_rehashed"])
        self.assertTrue(r["immutable_version_content_address_and_referenced_safes_rechecked"])
        self.assertGreaterEqual(self.load_mock.call_count,2)
        self.assertFalse(r["original_market_files_reopened"])
        self.assertFalse(r["ready_for_automatic_market_merge"])
        self.assertFalse(r["candidate_source_units_certified"])
        self.assertFalse(r["ready_for_h5_mirror"])
        self.assertFalse(r["vendor_document_examined_or_authenticated"])
        text=self.output.read_text()
        self.assertNotIn("SH600000",text)
        self.assertNotIn(str(self.dir),text)

    def test_tampered_one_historical_original_safe_rejected(self):
        p=self.files["real_raw_stock_day"]
        p.write_bytes(p.read_bytes()+b"\n")
        with self.assertRaisesRegex(ValueError,"byte SHA mismatch"):
            self.run_audit()
        self.load_mock.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_tampered_previous_ten_safe_rejected(self):
        self.old.write_bytes(self.old.read_bytes()+b"\n")
        with self.assertRaisesRegex(ValueError,"content or hashes"):
            self.run_audit()
        self.assertFalse(self.output.exists())

    def test_tampered_sixteen_safe_rejected(self):
        self.new.write_bytes(self.new.read_bytes()+b"\n")
        with self.assertRaisesRegex(ValueError,"content or hashes"):
            self.run_audit()
        self.assertFalse(self.output.exists())

    def test_historical_five_source_path_escape_rejected(self):
        outside=self.dir/"outside.json"
        outside.write_bytes(self.files["real_raw_stock_day"].read_bytes())
        self.files["real_raw_stock_day"]=outside
        with self.assertRaisesRegex(ValueError,"direct"):
            self.run_audit()
        self.assertFalse(self.output.exists())

    def test_duplicate_roles_using_same_file_rejected(self):
        self.files["real_native_stock_day"]=self.files["real_raw_stock_day"]
        with self.assertRaisesRegex(ValueError,"different"):
            self.run_audit()

    def test_unknown_or_missing_roles_rejected(self):
        self.files.pop("real_raw_stock_day")
        with self.assertRaisesRegex(ValueError,"Exactly five"):
            self.run_audit()

    def test_wrong_private_version_disallowed(self):
        with self.assertRaisesRegex(ValueError,"Wrong registered"):
            M.audit(self.bridge,self.old,self.new,self.files,"f"*64,self.output)
        self.load_mock.assert_not_called()

    def test_registry_wrong_candidate_count_rejected(self):
        self.version["candidate_total_new_stockday_rows"]=22273
        with self.assertRaisesRegex(ValueError,"cannot qualify"):
            self.run_audit()
        self.assertFalse(self.output.exists())

    def test_existing_output_never_overwritten(self):
        self.output.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError,"overwrite"):
            self.run_audit()
        self.assertEqual(self.output.read_bytes(),b"keep")

    def test_private_lock_prevents_any_source_audit(self):
        lock=M.REG.LOCK
        lock.write_text("busy")
        with self.assertRaisesRegex(ValueError,"being modified"):
            self.run_audit()
        self.load_mock.assert_not_called()

    def test_prior_bridge_claimed_licensed_units_rejected(self):
        report=json.loads(self.bridge.read_bytes())
        report["candidate_source_units_certified"]=True
        self.bridge.write_bytes(json.dumps(report).encode())
        with self.assertRaisesRegex(ValueError,"authority"):
            self.run_audit()

    def test_registry_change_on_second_check_rejected(self):
        modified={**self.version,"source_priority":"invalid"}
        self.load_mock.side_effect=[self.version,modified]
        with self.assertRaisesRegex(ValueError,"drift"):
            self.run_audit()
        self.assertFalse(self.output.exists())

    def test_source_changes_between_checks_rejected(self):
        original=M.bounded_source
        calls=[0]
        def mutating_read(path):
            calls[0]+=1
            if calls[0]==9:
                chosen=self.files["crossyear_holdout"]
                chosen.write_bytes(chosen.read_bytes()+b"\n")
            return original(path)
        with patch.object(M,"bounded_source",side_effect=mutating_read):
            with self.assertRaises(ValueError):
                self.run_audit()
        self.assertFalse(self.output.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
