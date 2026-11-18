"""P65: default-off exact-stock Capital-only semantic comparison rehearsal.

All tests use temporary synthetic Parquet; never access real QMT or data.
A scoped bypass is only supplied directly to _plan_symbol/_commit_symbol.
The scheduled run() has no approval argument and must remain strict.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I


CODE = "002237.SZ"
OTHER = "688367.SH"
ASOF_OLD = "2026-11-17"
ASOF_NEW = "2026-11-18"
BASE = {"_index": "0", "m_timetag": 20260930, "m_quarter": 0.,
        "m_anntime": 20261028, "total_capital": 100.,
        "circulating_capital": 80.}
CURRENT = dict(BASE, m_quarter=6750319.)


def tables(capital=None, other=None):
    data = {table: [] for table in E.FIN_TABLES}
    data["Capital"] = [dict(CURRENT if capital is None else capital)]
    if other is not None:
        data["Income"] = [other]
    return data


def old_capital(extra, code=CODE, records=None, asof=ASOF_OLD,
                workspace=None):
    if records is None:
        records = [BASE]
    path = E._snapshot_write(
        extra, "financial/Capital/" + code, asof,
        E.snapshot_table(asof, code, "Capital", records),
        workspace=workspace)
    return path


def old_income(extra, code=CODE, value=10., asof=ASOF_OLD,
               workspace=None):
    old = [{"_index": "0", "m_timetag": 20260930, "revenue": value}]
    E._snapshot_write(
        extra, "financial/Income/" + code, asof,
        E.snapshot_table(asof, code, "Income", old),
        workspace=workspace)


class ScopedCapitalComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.extra = Path(self.temporary.name) / "qmt_extra"
        self.work = Path(self.temporary.name) / "private"
        self.original_path = self.extra / "financial" / "Capital" / CODE / "snapshots"
        old_capital(self.extra, workspace=self.work)

    def test_normal_importer_still_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_HISTORY_CONFLICT"):
            I._plan_symbol(self.extra, CODE, ASOF_NEW, tables())

    def test_unlisted_stock_cannot_inherit_another_stock_approval(self):
        with self.assertRaisesRegex(ValueError, "must name exactly"):
            I._plan_symbol(self.extra, CODE, ASOF_NEW, tables(),
                           capital_approved_symbol=OTHER)

    def test_exact_stock_meta_only_is_candidate_not_general_exception(self):
        summary, staged = I._plan_symbol(
            self.extra, CODE, ASOF_NEW, tables(),
            capital_approved_symbol=CODE)
        self.assertEqual(summary["Capital"]["action"], "CREATE_VERSION")
        self.assertEqual(summary["Capital"]["extra_records"], 1)
        self.assertTrue(
            summary["Capital"]["scoped_m_quarter_semantic_exception"]
            ["business_fields_verified"])
        self.assertEqual(set(staged), {"Capital"})
        self.assertEqual(staged["Capital"], [CURRENT])

    def test_total_capital_change_stays_blocked_with_approval(self):
        changed = dict(CURRENT, total_capital=101.)
        with self.assertRaisesRegex(ValueError, "BUSINESS_OR_DATE_FIELD_CHANGED"):
            I._plan_symbol(self.extra, CODE, ASOF_NEW, tables(changed),
                           capital_approved_symbol=CODE)

    def test_circulating_capital_change_stays_blocked_with_approval(self):
        changed = dict(CURRENT, circulating_capital=81.)
        with self.assertRaisesRegex(ValueError, "BUSINESS_OR_DATE_FIELD_CHANGED"):
            I._plan_symbol(self.extra, CODE, ASOF_NEW, tables(changed),
                           capital_approved_symbol=CODE)

    def test_report_date_addition_stays_blocked_on_scoped_candidate(self):
        source = tables()
        source["Capital"].append(dict(CURRENT, _index="1", m_timetag=20261030))
        with self.assertRaisesRegex(ValueError, "REPORT_KEYS_ADDED_OR_REMOVED"):
            I._plan_symbol(self.extra, CODE, ASOF_NEW, source,
                           capital_approved_symbol=CODE)

    def test_missing_report_date_stays_blocked(self):
        source = tables()
        source["Capital"] = []
        with self.assertRaisesRegex(ValueError, "REPORT_KEYS_ADDED_OR_REMOVED"):
            I._plan_symbol(self.extra, CODE, ASOF_NEW, source,
                           capital_approved_symbol=CODE)

    def test_capital_missing_mquarter_does_not_pass(self):
        no_quarter = dict(CURRENT)
        no_quarter.pop("m_quarter")
        with self.assertRaisesRegex(ValueError, "M_QUARTER_FIELD_MISSING"):
            I._plan_symbol(self.extra, CODE, ASOF_NEW, tables(no_quarter),
                           capital_approved_symbol=CODE)

    def test_other_eight_tables_still_require_original_history_exactness(self):
        old_income(self.extra, workspace=self.work)
        source = tables(other={
            "_index": "0", "m_timetag": 20260930, "revenue": 11.})
        with self.assertRaisesRegex(ValueError, "table=Income"):
            I._plan_symbol(self.extra, CODE, ASOF_NEW, source,
                           capital_approved_symbol=CODE)

    def test_preexisting_economic_history_revisions_stay_blocked(self):
        old_capital(self.extra, records=[
            dict(BASE, _index="0", total_capital=200., m_quarter=99.)],
            asof="2026-11-16", workspace=self.work)
        with self.assertRaisesRegex(ValueError, "HISTORICAL_BUSINESS_FIELD_REVISION"):
            I._plan_symbol(self.extra, CODE, ASOF_NEW, tables(),
                           capital_approved_symbol=CODE)

    def test_real_synthetic_version_commit_keeps_old_snapshot_immutable(self):
        prior = E._financial_snapshot_file(self.extra, CODE, "Capital", ASOF_OLD)
        old_sha = E.L.hash_file(prior)
        result = I._commit_symbol(
            self.extra, self.work, CODE, ASOF_NEW, tables(),
            capital_approved_symbol=CODE)
        self.assertEqual(result["Capital"]["action"], "CREATE_VERSION")
        self.assertEqual(E.L.hash_file(prior), old_sha)
        self.assertEqual(E._financial_snapshot_rows(
            self.extra, CODE, "Capital", ASOF_OLD), [BASE])
        new_file = E._financial_snapshot_file(self.extra, CODE, "Capital", ASOF_NEW)
        self.assertTrue(new_file.is_file())
        self.assertNotEqual(new_file, prior)
        self.assertEqual(E._financial_snapshot_rows(
            self.extra, CODE, "Capital", ASOF_NEW), [CURRENT])
        self.assertTrue((self.work / "financial-coverage.jsonl").is_file())

    def test_repeated_manual_pilot_is_idempotent_even_with_old_raw_version(self):
        first = I._commit_symbol(
            self.extra, self.work, CODE, ASOF_NEW, tables(),
            capital_approved_symbol=CODE)
        path = E._financial_snapshot_file(self.extra, CODE, "Capital", ASOF_NEW)
        original_sha = E.L.hash_file(path)
        second = I._commit_symbol(
            self.extra, self.work, CODE, ASOF_NEW, tables(),
            capital_approved_symbol=CODE)
        self.assertEqual(first["Capital"]["action"], "CREATE_VERSION")
        self.assertEqual(second["Capital"]["action"], "UNCHANGED")
        self.assertEqual(E.L.hash_file(path), original_sha)
        self.assertEqual(len(list(
            self.original_path.glob("2026-11-18-*.parquet"))), 1)
        # Default importer STILL quarantines this symbol, even after commit.
        with self.assertRaisesRegex(ValueError, "SOURCE_HISTORY_CONFLICT"):
            I._plan_symbol(self.extra, CODE, "2026-11-19", tables())

    def test_same_asof_old_pin_and_raw_bytes_survive_new_candidate(self):
        old_capital(self.extra, asof=ASOF_NEW, workspace=self.work)
        old_file = E._financial_snapshot_file(
            self.extra, CODE, "Capital", ASOF_NEW)
        old_hash = E.L.hash_file(old_file)
        result = I._commit_symbol(
            self.extra, self.work, CODE, ASOF_NEW, tables(),
            capital_approved_symbol=CODE)
        self.assertEqual(result["Capital"]["action"], "CREATE_VERSION")
        new_file = E._financial_snapshot_file(
            self.extra, CODE, "Capital", ASOF_NEW)
        self.assertNotEqual(old_file, new_file)
        self.assertEqual(E.L.hash_file(old_file), old_hash)
        self.assertEqual(len(list(self.original_path.glob(
            "2026-11-18-*.parquet"))), 2)
        self.assertTrue(E._financial_active_path(
            self.extra, CODE, "Capital", ASOF_NEW).is_file())

    def test_failure_after_old_pin_does_not_lose_original_snapshot(self):
        from unittest.mock import patch
        old_capital(self.extra, asof=ASOF_NEW, workspace=self.work)
        old_file = E._financial_snapshot_file(
            self.extra, CODE, "Capital", ASOF_NEW)
        old_hash = E.L.hash_file(old_file)
        with patch.object(E, "_snapshot_write",
                          side_effect=OSError("injected write failure")):
            with self.assertRaisesRegex(OSError, "injected write failure"):
                I._commit_symbol(self.extra, self.work, CODE, ASOF_NEW,
                                 tables(), capital_approved_symbol=CODE)
        self.assertEqual(E.L.hash_file(old_file), old_hash)
        self.assertEqual(E._financial_snapshot_file(
            self.extra, CODE, "Capital", ASOF_NEW), old_file)
        self.assertEqual(len(list(
            self.original_path.glob("2026-11-18-*.parquet"))), 1)

    def test_other_table_revision_blocks_before_any_capital_write(self):
        old_income(self.extra, workspace=self.work)
        with self.assertRaisesRegex(ValueError, "table=Income"):
            I._commit_symbol(
                self.extra, self.work, CODE, ASOF_NEW,
                tables(other={"_index": "0", "m_timetag": 20260930,
                              "revenue": 900.}),
                capital_approved_symbol=CODE)
        self.assertEqual(len(list(self.original_path.glob(
            "2026-11-18-*.parquet"))), 0)
        self.assertFalse((self.work / "financial-coverage.jsonl").exists())

    def test_another_stock_stays_strict_even_after_pilot(self):
        old_capital(self.extra, code=OTHER, workspace=self.work)
        I._commit_symbol(self.extra, self.work, CODE, ASOF_NEW, tables(),
                         capital_approved_symbol=CODE)
        with self.assertRaisesRegex(ValueError, "SOURCE_HISTORY_CONFLICT"):
            I._plan_symbol(self.extra, OTHER, ASOF_NEW, tables())

    def test_importer_run_exposes_no_pilot_approval_argument(self):
        import inspect
        self.assertNotIn("capital_approved_symbol", inspect.signature(I.run).parameters)


if __name__ == "__main__":
    unittest.main()
