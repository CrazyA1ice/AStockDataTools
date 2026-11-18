"""P67: exact-date read-only persistent-policy consumer, synthetic Parquet only.

No QMT calls, no real policy writer, no production --apply, no auto activation.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I
import qmt_capital_scoped_policy_reader as P


CODE = "002237.SZ"
OTHER = "688367.SH"
OLD_DAY = "2026-11-17"
NEW_DAY = "2026-11-18"
NEXT_DAY = "2026-11-19"
OLD = {"_index": "0", "m_timetag": 20260930, "m_quarter": 0.,
       "total_capital": 100., "circulating_capital": 80.,
       "m_anntime": 20261028}
FRESH = dict(OLD, m_quarter=6750319.)


def source(capital=None):
    values = {table: [] for table in E.FIN_TABLES}
    values["Capital"] = [dict(FRESH if capital is None else capital)]
    return values


class ScopedPolicyReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.extra = root / "qmt_extra"
        self.work = root / "work"
        self.work.mkdir()
        self.old_file = E._snapshot_path(
            self.extra, "financial/Capital/" + CODE, OLD_DAY,
            E.snapshot_table(OLD_DAY, CODE, "Capital", [OLD]))
        E._snapshot_write(
            self.extra, "financial/Capital/" + CODE, OLD_DAY,
            E.snapshot_table(OLD_DAY, CODE, "Capital", [OLD]),
            workspace=self.work)
        I._commit_symbol(
            self.extra, self.work, CODE, NEW_DAY, source(),
            capital_approved_symbol=CODE)
        self.new_file = E._financial_snapshot_file(
            self.extra, CODE, "Capital", NEW_DAY)
        self.policy = {
            "format": P.FORMAT, "status": "ACTIVE",
            "field": "m_quarter", "symbol": CODE,
            "root": str(self.extra.resolve()),
            "activation_asof": NEW_DAY, "baseline_asof": OLD_DAY,
            "baseline_snapshot": self.old_file.name,
            "baseline_snapshot_sha256": E.L.hash_file(self.old_file),
            "candidate_snapshot": self.new_file.name,
            "candidate_snapshot_sha256": E.L.hash_file(self.new_file),
            "allowed_records": [{
                "report_key": E.canonical_json(20260930),
                "business_sha256": P._business_sha(FRESH),
                "approved_quarter": E.canonical_json(FRESH["m_quarter"]),
                "allowed_historical_quarters": sorted([
                    E.canonical_json(OLD["m_quarter"]),
                    E.canonical_json(FRESH["m_quarter"])])
            }]}

    def checked(self, asof=NEXT_DAY, code=CODE, original=None, policy=None):
        return I._plan_symbol(
            self.extra, code, asof,
            source() if original is None else original,
            capital_policy=self.policy if policy is None else policy)

    def test_next_day_same_cache_passes_and_is_idempotent(self):
        plan, staged = self.checked()
        self.assertEqual(plan["Capital"]["action"], "UNCHANGED")
        self.assertEqual(staged, {})
        gate = plan["Capital"]["scoped_m_quarter_semantic_exception"]
        self.assertTrue(gate["persistent_policy_checked"])
        self.assertEqual(gate["m_quarter_differences"], 1)
        self.assertEqual(gate["allowed_report_dates"], 1)

    def test_strict_default_runner_still_rejects_next_day(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_HISTORY_CONFLICT"):
            I._plan_symbol(self.extra, CODE, NEXT_DAY, source())

    def test_manual_existing_policy_object_not_enabled_by_scheduled_run(self):
        import inspect
        self.assertNotIn("capital_policy", inspect.signature(I.run).parameters)
        self.assertNotIn("capital_policy",
                         inspect.signature(I.main).parameters)

    def test_reject_cross_stock_policy_reuse(self):
        policy = dict(self.policy, symbol=OTHER)
        with self.assertRaisesRegex(ValueError, "IDENTITY_OR_STATUS_MISMATCH"):
            self.checked(policy=policy)

    def test_reject_cross_root_policy_reuse(self):
        policy = dict(self.policy, root=str(self.extra) + "-different")
        with self.assertRaisesRegex(ValueError, "IDENTITY_OR_STATUS_MISMATCH"):
            self.checked(policy=policy)

    def test_revoked_policy_never_provides_exception(self):
        policy = dict(self.policy, status="REVOKED")
        with self.assertRaisesRegex(ValueError, "IDENTITY_OR_STATUS_MISMATCH"):
            self.checked(policy=policy)

    def test_candidate_snapshot_sha_mismatch(self):
        policy = dict(self.policy, candidate_snapshot_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "IMMUTABLE_SNAPSHOT_SHA256_CHANGED"):
            self.checked(policy=policy)

    def test_old_raw_snapshot_sha_mismatch(self):
        policy = dict(self.policy, baseline_snapshot_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "IMMUTABLE_SNAPSHOT_SHA256_CHANGED"):
            self.checked(policy=policy)

    def test_unapproved_new_quarter_value_rejected(self):
        changed = dict(FRESH, m_quarter=9999.)
        with self.assertRaisesRegex(ValueError, "APPROVED_BUSINESS_OR_QUARTER_DRIFT"):
            self.checked(original=source(changed))

    def test_true_total_capital_revision_stays_blocked(self):
        changed = dict(FRESH, total_capital=101.)
        with self.assertRaisesRegex(ValueError, "APPROVED_BUSINESS_OR_QUARTER_DRIFT"):
            self.checked(original=source(changed))

    def test_true_circulating_capital_revision_stays_blocked(self):
        changed = dict(FRESH, circulating_capital=81.)
        with self.assertRaisesRegex(ValueError, "APPROVED_BUSINESS_OR_QUARTER_DRIFT"):
            self.checked(original=source(changed))

    def test_new_report_date_requires_separate_review(self):
        values = source()
        values["Capital"].append(dict(FRESH, _index="1", m_timetag=20261231))
        with self.assertRaisesRegex(ValueError, "ADDED_OR_REMOVED_REPORT_DATE"):
            self.checked(original=values)

    def test_unapproved_extra_quarter_whitelist_value_fails_closed(self):
        policy = dict(self.policy)
        policy["allowed_records"] = [
            dict(self.policy["allowed_records"][0])]
        policy["allowed_records"][0]["allowed_historical_quarters"] = (
            policy["allowed_records"][0]["allowed_historical_quarters"]
            + [E.canonical_json(1234.)])
        with self.assertRaisesRegex(ValueError, "EXTRA_OR_MISSING_APPROVED_QUARTER"):
            self.checked(policy=policy)

    def test_missing_exception_rule_fails_closed(self):
        policy = dict(self.policy, allowed_records=[])
        with self.assertRaisesRegex(ValueError, "INVALID_ALLOWED_REPORT_DATE_COUNT"):
            self.checked(policy=policy)

    def test_policy_file_missing_means_no_implicit_approval(self):
        self.assertIsNone(P.read_policy(self.extra, CODE, self.work))

    def test_policy_file_can_be_read_but_not_activated_automatically(self):
        folder = self.work / "capital-approved-policies"
        folder.mkdir()
        path = folder / (CODE + ".json")
        path.write_text(json.dumps(self.policy), encoding="utf-8")
        observed = P.read_policy(self.extra, CODE, self.work)
        self.assertEqual(observed["symbol"], CODE)
        with self.assertRaisesRegex(ValueError, "SOURCE_HISTORY_CONFLICT"):
            I._plan_symbol(self.extra, CODE, NEXT_DAY, source())

    def test_other_financial_table_changed_still_blocks_with_valid_policy(self):
        E._snapshot_write(
            self.extra, "financial/Income/" + CODE, OLD_DAY,
            E.snapshot_table(OLD_DAY, CODE, "Income", [
                {"_index": "0", "m_timetag": 20260930, "revenue": 100.}]),
            workspace=self.work)
        values = source()
        values["Income"] = [
            {"_index": "0", "m_timetag": 20260930, "revenue": 101.}]
        with self.assertRaisesRegex(ValueError, "table=Income"):
            self.checked(original=values)

    def test_new_active_candidate_replaces_pinned_expected_one_fails_closed(self):
        other = [dict(FRESH, m_quarter=1234.)]
        E._snapshot_write(
            self.extra, "financial/Capital/" + CODE, NEW_DAY,
            E.snapshot_table(NEW_DAY, CODE, "Capital", other),
            workspace=self.work)
        replacement = E._snapshot_path(
            self.extra, "financial/Capital/" + CODE, NEW_DAY,
            E.snapshot_table(NEW_DAY, CODE, "Capital", other))
        E._pin_financial_snapshot(
            self.extra, CODE, "Capital", NEW_DAY, replacement)
        with self.assertRaisesRegex(ValueError, "APPROVED_CANDIDATE_NOT_ACTIVE"):
            self.checked()

    def test_same_day_original_raw_unpinned_still_verified(self):
        E._snapshot_write(
            self.extra, "financial/Capital/" + CODE, NEW_DAY,
            E.snapshot_table(NEW_DAY, CODE, "Capital", [OLD]),
            workspace=self.work)
        old_same_day = E._snapshot_path(
            self.extra, "financial/Capital/" + CODE, NEW_DAY,
            E.snapshot_table(NEW_DAY, CODE, "Capital", [OLD]))
        policy = dict(self.policy, baseline_asof=NEW_DAY,
                      baseline_snapshot=old_same_day.name,
                      baseline_snapshot_sha256=E.L.hash_file(old_same_day))
        plan, staged = self.checked(policy=policy)
        self.assertEqual(plan["Capital"]["action"], "UNCHANGED")
        self.assertEqual(staged, {})

    def test_persistent_policy_and_symbol_rehearsal_cannot_mix(self):
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            I._plan_symbol(
                self.extra, CODE, NEXT_DAY, source(),
                capital_policy=self.policy, capital_approved_symbol=CODE)

    def test_commit_interface_using_valid_policy_no_new_snapshot(self):
        old_hash = E.L.hash_file(self.new_file)
        plan = I._commit_symbol(
            self.extra, self.work, CODE, NEXT_DAY, source(),
            capital_policy=self.policy)
        self.assertEqual(plan["Capital"]["action"], "UNCHANGED")
        self.assertEqual(E.L.hash_file(self.new_file), old_hash)
        self.assertEqual(len(list(self.new_file.parent.glob(
            "2026-11-19-*.parquet"))), 0)

    def test_historical_economic_revision_not_exempted_by_policy(self):
        E._snapshot_write(
            self.extra, "financial/Capital/" + CODE, "2026-11-16",
            E.snapshot_table("2026-11-16", CODE, "Capital", [
                dict(OLD, total_capital=101.)]),
            workspace=self.work)
        with self.assertRaisesRegex(ValueError, "UNAPPROVED_BUSINESS_HISTORY_VARIANT"):
            self.checked()


if __name__ == "__main__":
    unittest.main()
