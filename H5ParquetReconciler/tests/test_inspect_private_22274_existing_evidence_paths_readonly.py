"""Metadata-only existing 22274 candidate evidence locator contracts."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "private_22274_existing_evidence_locator_tests",
    HERE.parent / "tools" /
    "inspect-private-22274-existing-evidence-paths-readonly.py")
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class ExistingEvidencePathInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module=Path(self.tmp.name)
        (self.module/"reports").mkdir()
        self.version="e"*64
        self.entry={
            "candidate_total_new_stockday_rows":22274,
            "whole_day_candidate_rows":22191,
            "mixed_stockday_candidate_rows":83,
            "mixed_stage_safe_basename":"mixed-private.json",
            "original_preflight_safe_basename":"original-private.json",
            "fresh_recheck_safe_basename":"fresh-private.json",
        }

    def inspect(self, **kwargs):
        with patch.object(M,"MODULE",self.module), \
             patch.object(M.REG,"load_version",return_value=self.entry) as registry:
            result=M.inspect(self.version,**kwargs)
        registry.assert_called_once_with(self.version)
        return result

    def test_valid_registered_version_scans_filename_only_and_does_not_write(self):
        p=self.module/"reports"/"historical-day-exact-2016-example.json"
        p.write_text("not parsed, no market input",encoding="utf-8")
        original=list((self.module/"reports").iterdir())
        result=self.inspect()
        self.assertEqual(result["candidate_rows"],22274)
        self.assertEqual(result["evidence_file_discovery"]["source_2016"]["file_count"],1)
        self.assertEqual(result["evidence_file_discovery"]["source_2016"]["sample_names"],[p.name])
        self.assertFalse(result["market_data_opened"])
        self.assertFalse(result["config_written"])
        self.assertFalse(result["automatic_evidence_selection_permitted"])
        self.assertEqual(original,list((self.module/"reports").iterdir()))

    def test_bad_version_is_rejected_without_opening_registry(self):
        with patch.object(M.REG,"load_version",side_effect=AssertionError("should not load")):
            with self.assertRaisesRegex(ValueError,"registered SHA256"):
                M.inspect("latest")

    def test_directory_budget_stops_discovery(self):
        for n in range(3):
            (self.module/"reports"/f"example-{n}.json").write_text("{}")
        with self.assertRaisesRegex(ValueError,"budget"):
            self.inspect(max_files=2)

    def test_missing_reports_directory_is_rejected(self):
        (self.module/"reports").rmdir()
        with self.assertRaisesRegex(ValueError,"reports directory"):
            self.inspect()


if __name__=="__main__":
    unittest.main(verbosity=2)
