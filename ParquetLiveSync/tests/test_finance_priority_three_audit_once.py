"""Offline tests of three high-risk finance revisions; no QMT/network/Parquet."""
import importlib.util
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "finance_priority_three", Path(__file__).resolve().parent.parent /
    "finance_priority_three_audit_once.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class FakeE:
    @staticmethod
    def canonical_json(value):
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _path_check(path):
        return None


class FakeF:
    E = FakeE

    @staticmethod
    def _rows(records):
        return Counter(FakeE.canonical_json({k: v for k, v in row.items()
                                            if k != "_index"}) for row in records)


def oldrows(*records):
    return FakeF._rows(records)


class PairTests(unittest.TestCase):
    def test_name_and_type_revision(self):
        a = {"endDate": "20260930", "name": "甲", "type": "公司", "shares": 8}
        b = dict(a, name="乙", type="机构投资账户")
        x = M.analyze_single_pair(oldrows(a), [b], frozenset(("name", "type")), FakeF)
        self.assertEqual(x["classification"], "EXACT_SCOPED_CHANGE_REVIEW_REQUIRED")
        self.assertEqual(x["observed_fields"], ["name", "type"])
        self.assertTrue(x["stable_projection_equal"])
        self.assertEqual(x["candidate_old_projection_count"], 1)
        self.assertEqual(x["candidate_new_projection_count"], 1)
        self.assertNotIn("甲", json.dumps(x, ensure_ascii=False))
        self.assertNotIn("乙", json.dumps(x, ensure_ascii=False))
        self.assertIn("公司", json.dumps(x, ensure_ascii=False))

    def test_name_only(self):
        a = {"name": "旧名", "endDate": "20260930", "shares": 10}
        b = dict(a, name="新名")
        x = M.analyze_single_pair(oldrows(a), [b], frozenset(("name",)), FakeF)
        self.assertEqual(x["classification"], "EXACT_SCOPED_CHANGE_REVIEW_REQUIRED")
        self.assertEqual(x["changes"]["name"]["old"]["characters"], 2)

    def test_holder_num_date_two_quantity_fields(self):
        a = {"endDate": "20260930", "declareDate": "20261022",
             "shareholder": 1000, "shareholderA": 990}
        b = dict(a, declareDate="20261027", shareholder=990, shareholderA=980)
        x = M.analyze_single_pair(
            oldrows(a), [b], frozenset(("declareDate", "shareholder", "shareholderA")), FakeF)
        self.assertEqual(x["classification"], "EXACT_SCOPED_CHANGE_REVIEW_REQUIRED")
        self.assertEqual(x["changes"]["shareholder"]["difference_new_minus_old"], "-10")
        self.assertEqual(x["changes"]["shareholder"]["change_percent"], "-1")
        self.assertEqual(x["report_period_old"], "20260930")

    def test_numeric_string_values(self):
        x = M.numeric_delta("200", "220")
        self.assertEqual(x["difference_new_minus_old"], "20")
        self.assertEqual(x["change_percent"], "10")

    def test_numeric_zero_baseline(self):
        x = M.numeric_delta(0, 1)
        self.assertEqual(x["difference_new_minus_old"], "1")
        self.assertNotIn("change_percent", x)

    def test_numeric_invalid(self):
        self.assertEqual(M.numeric_delta("N/A", "100")["numeric_comparison"], "UNAVAILABLE")
        self.assertEqual(M.numeric_delta(True, 100)["numeric_comparison"], "UNAVAILABLE")

    def test_unicode_name_normalization_only(self):
        a = M.name_evidence("Ａ Ｂ", "AB")
        self.assertTrue(a["normalization_only_candidate"])
        self.assertTrue(a["same_after_nfkc_whitespace"])

    def test_name_change_not_automatically_equivalent(self):
        x = M.name_evidence("股东甲", "股东乙")
        self.assertFalse(x["normalization_only_candidate"])

    def test_business_field_change_blocks(self):
        a = {"name": "旧名", "shares": 100}
        b = {"name": "新名", "shares": 200}
        x = M.analyze_single_pair(oldrows(a), [b], frozenset(("name",)), FakeF)
        self.assertEqual(x["classification"], "BLOCKED_SCOPE_OR_IDENTITY_MISMATCH")
        self.assertIn("shares", x["observed_fields"])
        self.assertNotIn("changes", x)

    def test_wrong_expected_field_set_blocks(self):
        a = {"name": "旧名", "type": "机构", "shares": 100}
        b = {"name": "新名", "type": "机构", "shares": 100}
        x = M.analyze_single_pair(
            oldrows(a), [b], frozenset(("name", "type")), FakeF)
        self.assertEqual(x["classification"], "BLOCKED_SCOPE_OR_IDENTITY_MISMATCH")

    def test_two_unmatched_pairs_are_not_forced(self):
        a = [{"name": "甲", "shares": 100}, {"name": "乙", "shares": 200}]
        b = [{"name": "丙", "shares": 100}, {"name": "丁", "shares": 200}]
        x = M.analyze_single_pair(FakeF._rows(a), b, frozenset(("name",)), FakeF)
        self.assertEqual(x["classification"], "BLOCKED_UNEXPECTED_CARDINALITY")

    def test_no_differences_are_not_misclassified(self):
        a = {"name": "甲", "shares": 100}
        x = M.analyze_single_pair(oldrows(a), [a], frozenset(("name",)), FakeF)
        self.assertEqual(x["classification"], "BLOCKED_UNEXPECTED_CARDINALITY")

    def test_nonunique_projection_blocks_pair(self):
        unchanged = {"name": "甲", "endDate": "20260930", "shares": 100}
        changing = {"name": "乙", "endDate": "20260930", "shares": 100}
        changed = dict(changing, name="丙")
        x = M.analyze_single_pair(oldrows(unchanged, changing), [unchanged, changed],
                                  frozenset(("name",)), FakeF)
        self.assertEqual(x["classification"], "BLOCKED_NONUNIQUE_PAIR")
        self.assertEqual(x["candidate_old_projection_count"], 2)
        self.assertEqual(x["candidate_new_projection_count"], 2)
        self.assertNotIn("changes", x)

    def test_order_and_duplicate_unmatched_counts(self):
        a = {"name": "甲", "shares": 100}
        b = {"name": "乙", "shares": 100}
        x = M.analyze_single_pair(oldrows(a, a), [b, b], frozenset(("name",)), FakeF)
        self.assertEqual(x["classification"], "BLOCKED_UNEXPECTED_CARDINALITY")
        self.assertEqual(x["old_unmatched"], 2)
        self.assertEqual(x["new_unmatched"], 2)

    def test_missing_changed_field_blocks(self):
        a = {"name": "甲", "shares": 100}
        b = {"shares": 100}
        x = M.analyze_single_pair(oldrows(a), [b], frozenset(("name",)), FakeF)
        self.assertEqual(x["classification"], "EXACT_SCOPED_CHANGE_REVIEW_REQUIRED")
        self.assertEqual(x["changes"]["name"]["new"]["characters"], len(str(M.ABSENT)))


class BoundaryTests(unittest.TestCase):
    def test_schedule_protection(self):
        tz = timezone(timedelta(hours=8))
        for hour, minute in ((18, 45), (20, 5), (23, 34)):
            with self.assertRaises(RuntimeError):
                M.check_time(datetime(2026, 11, 25, hour, minute, tzinfo=tz))
        for hour, minute in ((11, 0), (18, 44), (23, 35)):
            M.check_time(datetime(2026, 11, 25, hour, minute, tzinfo=tz))

    def test_scope_is_exactly_three(self):
        self.assertEqual(sorted(M.CASES), ["002178.SZ", "002310.SZ", "002328.SZ"])
        self.assertNotIn("688259.SH", M.CASES)

    def test_hash_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            path.write_bytes(b"abc")
            self.assertEqual(M.file_sha256(path),
                             "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


class IntegrationTests(unittest.TestCase):
    def _make(self):
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name)
        root = base / "private"
        ledger = base / "work" / "qmt_extra" / "financial-cache-progress.json"
        ledger.parent.mkdir(parents=True)
        root.mkdir()
        pending = {}
        for code, (table, _) in M.CASES.items():
            pending[code] = {"reason": "SOURCE_HISTORY_CONFLICT",
                             "detail": "SOURCE_HISTORY_CONFLICT " + code + " table=" + table}
            snap = root / "financial" / table / code / "snapshots"
            snap.mkdir(parents=True)
            (snap / "2026-11-17-1234567890abcdef.parquet").write_text("fixture", encoding="utf-8")
        state = {"format": M.EXPECTED_FORMAT, "root": str(root),
                 "daily_date": "2026-11-24", "pending": pending}
        ledger.write_text(json.dumps(state), encoding="utf-8")
        return tmp, base, ledger

    def test_end_to_end_three_stocks_no_ledger_changes(self):
        tmp, base, ledger = self._make()
        with tmp:
            old = {
                "002178.SZ": {"name": "旧", "type": "公司", "endDate": "20260930", "shares": 123},
                "002310.SZ": {"name": "旧", "endDate": "20260930", "shares": 123},
                "002328.SZ": {"declareDate": "20261022", "endDate": "20260930",
                              "shareholder": 100, "shareholderA": 99},
            }
            new = {
                "002178.SZ": dict(old["002178.SZ"], name="新", type="机构"),
                "002310.SZ": dict(old["002310.SZ"], name="新"),
                "002328.SZ": dict(old["002328.SZ"], declareDate="20261027",
                                  shareholder=101, shareholderA=100),
            }
            class LocalF(FakeF):
                @staticmethod
                def _worker_batch(codes, mode, asof, lookback_days, workspace,
                                  timeout, progress):
                    self = {code: {M.CASES[code][0]: [new[code]]} for code in codes}
                    if mode != "cache":
                        raise AssertionError("cache-only mandatory")
                    return self, []
                @staticmethod
                def _prior_rows(root, code, table):
                    return "2026-11-17", oldrows(old[code])
            before = M.file_sha256(ledger)
            with patch.object(M, "check_time"), patch("builtins.print") as calls:
                M.audit(base, LocalF)
            emitted = "\n".join(" ".join(str(a) for a in call.args)
                                for call in calls.call_args_list)
            self.assertIn("FINANCE_PRIORITY_THREE_EVIDENCE_COMPLETE_NO_COMMIT", emitted)
            self.assertIn('"EXACT_SCOPED_CHANGE_REVIEW_REQUIRED": 3', emitted)
            self.assertEqual(M.file_sha256(ledger), before)

    def test_missing_pending_stops_before_query(self):
        tmp, base, ledger = self._make()
        with tmp:
            state = json.loads(ledger.read_text())
            state["pending"].pop("002328.SZ")
            ledger.write_text(json.dumps(state))
            class NoWorker(FakeF):
                @staticmethod
                def _worker_batch(*args, **kwargs):
                    raise AssertionError("worker should not be invoked")
            with patch.object(M, "check_time"), patch("builtins.print"):
                with self.assertRaisesRegex(ValueError, "PENDING_CASE_CHANGED"):
                    M.audit(base, NoWorker)

    def test_ledger_change_in_worker_is_detected(self):
        tmp, base, ledger = self._make()
        with tmp:
            class BadWorker(FakeF):
                @staticmethod
                def _worker_batch(*args, **kwargs):
                    ledger.write_text(ledger.read_text() + " ")
                    raise RuntimeError("simulated data-source failure")
            with patch.object(M, "check_time"), patch("builtins.print"):
                with self.assertRaisesRegex(RuntimeError, "FINANCE_LEDGER_CHANGED_DURING_AUDIT_STOP"):
                    M.audit(base, BadWorker)


if __name__ == "__main__":
    unittest.main()
