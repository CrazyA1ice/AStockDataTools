"""Offline contract tests for the nine-table read-only Capital repair preview."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from unittest.mock import patch
import unittest

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I
import qmt_capital_nine_table_repair_preview as R


CAPITAL = {"_index": "0", "m_timetag": 20260930,
           "m_quarter": 0., "total_capital": 100.,
           "circulating_capital": 80., "m_anntime": 20261028}


def _raw(rows):
    return Counter(E.canonical_json({
        k: value for k, value in row.items() if k != "_index"
    }) for row in rows)


def _tables():
    result = {table: [] for table in E.FIN_TABLES}
    result["Capital"] = [dict(CAPITAL, m_quarter=6750319.)]
    result["Balance"] = [{"_index": "0", "m_timetag": 20260930,
                          "assets": 123.}]
    return result


def _prior(extra, code, table):
    if table == "Capital":
        return "2026-11-17", _raw([CAPITAL])
    if table == "Balance":
        return "2026-11-17", _raw([
            {"_index": "0", "m_timetag": 20260930, "assets": 123.}])
    return None, None


class NineTableRepairPreviewTests(unittest.TestCase):
    def test_exact_other_eight_tables_and_meta_only_capital_is_preview_candidate(self):
        with patch.object(I, "_prior_rows", side_effect=_prior):
            result = R.plan_symbol(Path("/unused"), "002237.SZ", "2026-11-18",
                                   _tables())
        self.assertEqual(result["status"], "ELIGIBLE_FOR_MANUAL_PILOT_PREVIEW")
        self.assertEqual(result["blockers"], [])
        self.assertEqual(len(result["table_checks"]), 9)
        self.assertFalse(result["would_modify_parquet"])
        self.assertTrue(result["requires_separate_authorization"])
        self.assertFalse(result["pending_modified"])

    def test_balance_business_revision_cannot_be_skipped(self):
        fresh = _tables()
        fresh["Balance"][0]["assets"] = 999.
        with patch.object(I, "_prior_rows", side_effect=_prior):
            result = R.plan_symbol(Path("/unused"), "002237.SZ", "2026-11-18",
                                   fresh)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertTrue(any(x.startswith("Balance:") for x in result["blockers"]))
        self.assertEqual(result["proposed_action"], "NONE")

    def test_new_balance_record_not_provisionally_released(self):
        fresh = _tables()
        fresh["Balance"].append({"_index": "1", "m_timetag": 20261031,
                                 "assets": 456.})
        with patch.object(I, "_prior_rows", side_effect=_prior):
            result = R.plan_symbol(Path("/unused"), "002237.SZ", "2026-11-18",
                                   fresh)
        self.assertIn("Balance:NEW_RECORDS_REQUIRE_INDEPENDENT_REVIEW",
                      result["blockers"])

    def test_capital_economic_field_change_stays_quarantined(self):
        fresh = _tables()
        fresh["Capital"][0]["total_capital"] = 99.
        with patch.object(I, "_prior_rows", side_effect=_prior):
            result = R.plan_symbol(Path("/unused"), "002237.SZ", "2026-11-18",
                                   fresh)
        self.assertIn("Capital:BUSINESS_OR_DATE_FIELD_CHANGED", result["blockers"])

    def test_capital_new_report_date_is_not_a_meta_only_repair(self):
        fresh = _tables()
        fresh["Capital"].append(dict(CAPITAL, _index="1",
                                     m_timetag=20261030))
        with patch.object(I, "_prior_rows", side_effect=_prior):
            result = R.plan_symbol(Path("/unused"), "002237.SZ", "2026-11-18",
                                   fresh)
        self.assertIn("Capital:REPORT_KEYS_ADDED_OR_REMOVED", result["blockers"])

    def test_missing_financial_table_does_not_pass(self):
        fresh = _tables()
        del fresh["Top10Holder"]
        result = R.plan_symbol(Path("/unused"), "002237.SZ", "2026-11-18",
                               fresh)
        self.assertEqual(result["blockers"], ["MISSING_NINE_TABLE_PAYLOAD"])
        self.assertFalse(result["would_modify_parquet"])

    def test_asof_rollback_fails_closed(self):
        with patch.object(I, "_prior_rows", return_value=(
                "2026-11-19", _raw([CAPITAL]))):
            result = R.plan_symbol(Path("/unused"), "002237.SZ", "2026-11-18",
                                   _tables())
        self.assertTrue(any("SOURCE_OBSERVATION_OLDER_THAN_BASELINE" in x
                            for x in result["blockers"]))

    def test_bad_capital_row_fails_closed(self):
        fresh = _tables()
        fresh["Capital"] = [dict(CAPITAL, _index=123)]
        with patch.object(I, "_prior_rows", side_effect=_prior):
            result = R.plan_symbol(Path("/unused"), "002237.SZ", "2026-11-18",
                                   fresh)
        self.assertIn("Capital:INVALID_SOURCE_RECORDS", result["blockers"])

    def test_reject_more_than_five_symbols_without_live_calls(self):
        with self.assertRaisesRegex(ValueError, "1..5"):
            R.preview(Path("/unused"), Path("/unused"),
                      [f"{i:06d}.SH" for i in range(6)])


if __name__ == "__main__":
    unittest.main()
