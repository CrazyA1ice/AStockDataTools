"""Safe immutable 22,274 daily candidate registry inventory synthetic tests."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "registered_daily_mainline_readiness_contracts",
    HERE.parent / "tools" /
    "inspect-registered-private-day-22274-readiness-readonly.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class PrivateRegisteredDayReadinessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder=Path(tmp.name)
        self.valid = "f"*64
        self.safe = {
            "candidate_total_new_stockday_rows": 22274,
            "ready_for_production_query": False,
            "source_market_files_written": False,
            "private_or_production_active_pointer_modified": False,
        }

    def call(self, *, version_return=None):
        with patch.object(M.REG, "VERSIONS", self.folder), \
             patch.object(M.REG, "safe_private", return_value=None), \
             patch.object(M.REG, "load_version",
                          return_value=version_return or self.safe) as reg:
            result=M.inspect()
        return result, reg

    def test_no_registered_versions_does_not_claim_h5_passed(self):
        out, reg=self.call()
        self.assertEqual(out["registered_immutable_version_count"],0)
        self.assertEqual(out["status"],"no_registered_22274_private_day_versions")
        self.assertFalse(out["live_h5_purchased_source_reverified_by_this_inventory"])
        self.assertFalse(out["ready_for_production"])
        self.assertFalse(out["source_market_bars_opened"])
        reg.assert_not_called()

    def test_one_registered_version_only_static_sha_read(self):
        (self.folder/(self.valid+".json")).write_text("placeholder",encoding="utf-8")
        out,reg=self.call()
        self.assertEqual(out["registered_immutable_versions"],[self.valid])
        self.assertEqual(out["registered_immutable_version_count"],1)
        self.assertEqual(out["candidate_whole_date_rows_per_version"],22191)
        self.assertEqual(out["candidate_mixed_stockday_rows_per_version"],83)
        self.assertFalse(out["new_private_version_or_report_written"])
        reg.assert_called_once_with(self.valid)

    def test_filename_outside_sha_version_form_fail_closed(self):
        (self.folder/"latest.json").write_text("placeholder",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Unrecognized"):
            self.call()

    def test_unsafe_candidate_version_status_rejected(self):
        (self.folder/(self.valid+".json")).write_text("placeholder",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Invalid private"):
            self.call(version_return={**self.safe,
                "ready_for_production_query": True})

    def test_budget_rejects_many_unknown_versions_before_load(self):
        (self.folder/"other").write_text("unsafe",encoding="utf-8")
        with patch.object(M.REG,"VERSIONS",self.folder), \
             patch.object(M.REG,"safe_private",return_value=None):
            with self.assertRaisesRegex(ValueError,"budget"):
                M.inspect(max_versions=0)
            with self.assertRaisesRegex(ValueError,"Unrecognized"):
                M.inspect(max_versions=1)


if __name__=="__main__":
    unittest.main(verbosity=2)
