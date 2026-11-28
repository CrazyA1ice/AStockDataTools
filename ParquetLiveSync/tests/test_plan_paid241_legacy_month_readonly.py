"""Pure contract checks for the read-only legacy-240 migration inventory."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plan_paid241_legacy_month_readonly as M


class NovemberMigrationPlannerTests(unittest.TestCase):
    def test_01_some_241_source_days_are_insufficient_for_full_month(self):
        result=M.summarize(
            ["2026-11-02","2026-11-03","2026-11-13"],
            [{"code":"600000.SH","days":["2026-11-02","2026-11-03"]},
             {"code":"000001.SZ","days":["2026-11-03"]}],
            "2026-11")
        self.assertEqual(result["old_days_without_pinned_qmt_241_source"],1)
        self.assertEqual(result["old_days_with_any_pinned_qmt_241_source"],2)
        self.assertEqual(result["source_241_verified_stock_days"],3)
        self.assertFalse(result["old_month_full_241_replacement_authorized"])
        self.assertFalse(result["source_complete_for_all_old_stock_days_certified"])

    def test_02_same_dates_do_not_certify_entire_stock_universe(self):
        result=M.summarize(["2026-11-12"],
                           [{"code":"600000.SH","days":["2026-11-12"]}],
                           "2026-11")
        self.assertEqual(result["old_days_without_pinned_qmt_241_source"],0)
        self.assertFalse(result["source_complete_for_all_old_stock_days_certified"])

    def test_03_old_month_absent_rejected(self):
        with self.assertRaisesRegex(ValueError,"OLD_MONTH_DAY_SET_INVALID"):
            M.summarize([],[],"2026-11")

    def test_04_mixed_month_dates_rejected(self):
        with self.assertRaisesRegex(ValueError,"OLD_MONTH_DAY_SET_INVALID"):
            M.summarize(["2026-10-30"],[],"2026-11")

    def test_05_broken_source_entries_rejected(self):
        with self.assertRaisesRegex(ValueError,"SOURCE_ENTRIES_INVALID"):
            M.summarize(["2026-11-12"],[{"code":"600000.SH"}],"2026-11")

    def test_06_refuses_october_until_legacy_240_fragments_proved(self):
        with self.assertRaisesRegex(ValueError,"ONLY_NOVEMBER_PILOT"):
            M.inspect("D:/stock","D:/QMT","2026-10")


if __name__ == "__main__":
    unittest.main()
