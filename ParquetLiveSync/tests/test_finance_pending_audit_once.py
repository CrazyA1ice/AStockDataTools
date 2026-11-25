"""Offline tests; no xtquant, local QMT, network or Parquet needed."""
import importlib.util
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("finance_audit", Path(__file__).resolve().parent.parent / "finance_pending_audit_once.py")
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


class FakeE:
    @staticmethod
    def canonical_json(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


class FakeF:
    E = FakeE

    @staticmethod
    def _rows(records):
        return Counter(FakeE.canonical_json({k: v for k, v in row.items() if k != "_index"}) for row in records)


def rows(*items):
    return FakeF._rows(items)


def capital(key, quarter, amount=100):
    return {"m_timetag": key, "m_quarter": quarter, "amount": amount, "_index": "1"}


class HolderTests(unittest.TestCase):
    def test_unchanged(self):
        a = {"endDate": "20260930", "name": "A", "declareDate": "20261022", "type": "company", "shares": 55}
        x = D.holder_result(rows(a), [a], "Top10FlowHolder", FakeF)
        self.assertEqual(x["classification"], "RAW_MATCH")
        self.assertEqual(x["old_unmatched"], 0)

    def test_date_only(self):
        a = {"name": "A", "declareDate": "20261022", "shares": 55}
        b = dict(a, declareDate="20261027", _index="7")
        x = D.holder_result(rows(a), [b], "Top10Holder", FakeF)
        self.assertEqual(x["classification"], "DATE_OR_TYPE_ONLY")
        self.assertEqual(x["changed_fields"], ["declareDate"])

    def test_type_and_date(self):
        a = {"name": "A", "declareDate": "20261022", "type": "company", "shares": 55}
        b = dict(a, declareDate="20261027", type="institution")
        x = D.holder_result(rows(a), [b], "Top10FlowHolder", FakeF)
        self.assertEqual(x["classification"], "DATE_OR_TYPE_ONLY")
        self.assertEqual(x["changed_fields"], ["declareDate", "type"])

    def test_holder_num_type_is_not_ignored(self):
        a = {"name": "A", "type": "company", "declareDate": "20261022"}
        b = dict(a, type="institution")
        self.assertEqual(D.holder_result(rows(a), [b], "HolderNum", FakeF)["classification"], "OTHER_FIELD_OR_ROW_CHANGE")

    def test_business_change(self):
        a = {"name": "A", "shares": 55, "declareDate": "20261022"}
        b = dict(a, shares=56, declareDate="20261027")
        self.assertEqual(D.holder_result(rows(a), [b], "Top10Holder", FakeF)["classification"], "OTHER_FIELD_OR_ROW_CHANGE")

    def test_ambiguous_projection(self):
        a = {"name": "A", "shares": 55, "declareDate": "20261022"}
        b = dict(a, declareDate="20261027")
        x = D.holder_result(rows(a, a), [b, b], "Top10Holder", FakeF)
        self.assertEqual(x["classification"], "DATE_OR_TYPE_ONLY")
        self.assertEqual(x["ambiguous_projection_rows"], 2)

    def test_invalid_table(self):
        with self.assertRaises(ValueError):
            D.holder_result(Counter(), [], "Capital", FakeF)

    def test_row_count_change(self):
        a = {"name": "A", "shares": 55}
        b = {"name": "B", "shares": 56}
        self.assertEqual(D.holder_result(rows(a, b), [a], "Top10Holder", FakeF)["classification"], "OTHER_FIELD_OR_ROW_CHANGE")


class CapitalTests(unittest.TestCase):
    def test_one_new_key_and_old_quarter_variants(self):
        hist = rows(capital("20250630", "Q2"), capital("20250630", "Q4"))
        fresh = [capital("20250630", "Q4"), capital("20250930", "Q3")]
        x = D.capital_result(hist, fresh, FakeF)
        self.assertEqual(x["classification"], "CAPITAL_ADDITIVE_KEYS_WITH_PRIOR_VARIANTS")
        self.assertEqual(x["new_report_keys"], 1)
        self.assertEqual(x["missing_old_report_keys"], 0)
        self.assertEqual(x["historical_business_conflict_keys"], 0)

    def test_missing_old_key_blocked(self):
        x = D.capital_result(rows(capital("20250331", "Q1"), capital("20250630", "Q2")), [capital("20250630", "Q2")], FakeF)
        self.assertEqual(x["classification"], "CAPITAL_REPORT_OR_BUSINESS_CONFLICT")
        self.assertEqual(x["missing_old_report_keys"], 1)

    def test_changed_business_blocked(self):
        x = D.capital_result(rows(capital("20250630", "Q2")), [capital("20250630", "Q2", 101)], FakeF)
        self.assertEqual(x["classification"], "CAPITAL_REPORT_OR_BUSINESS_CONFLICT")
        self.assertEqual(x["shared_business_changed_keys"], 1)

    def test_same_keys_without_business_change(self):
        x = D.capital_result(rows(capital("20250630", "Q2")), [capital("20250630", "Q3")], FakeF)
        self.assertEqual(x["classification"], "CAPITAL_SAME_KEYS_RAW_VERSION_COMPARE")

    def test_historical_business_conflict_blocked(self):
        x = D.capital_result(rows(capital("20250630", "Q2", 100), capital("20250630", "Q3", 101)), [capital("20250630", "Q3", 101)], FakeF)
        self.assertEqual(x["classification"], "CAPITAL_REPORT_OR_BUSINESS_CONFLICT")
        self.assertEqual(x["historical_business_conflict_keys"], 1)

    def test_duplicate_fresh_key_blocked(self):
        x = D.capital_result(rows(capital("20250630", "Q2")), [capital("20250630", "Q2"), capital("20250630", "Q3")], FakeF)
        self.assertEqual(x["classification"], "CAPITAL_REPORT_OR_BUSINESS_CONFLICT")
        self.assertEqual(x["current_duplicate_report_keys"], 1)

    def test_missing_quarter_field(self):
        a = capital("20250630", "Q2")
        del a["m_quarter"]
        self.assertEqual(D.capital_result(rows(a), [a], FakeF)["classification"], "CAPITAL_UNVERIFIABLE_LAYOUT")


class ScopeTests(unittest.TestCase):
    def test_three_types_plus_known_utf8(self):
        p = {"pending": {
            "002388.SZ": {"reason": "SOURCE_HISTORY_CONFLICT", "detail": "SOURCE_HISTORY_CONFLICT table=Top10FlowHolder"},
            "002188.SZ": {"reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Capital scoped_m_quarter_proof=REPORT_KEYS_ADDED_OR_REMOVED"},
            "688259.SH": {"reason": "CACHE_DECODE_ERROR", "detail": "bad UTF8"},
            "000001.SZ": {"reason": "NO_CACHE", "detail": ""}
        }}
        with patch("builtins.print") as echo:
            got, unknown = D.selected_cases(p)
        self.assertEqual(got, {"002188.SZ": "Capital", "002388.SZ": "Top10FlowHolder"})
        self.assertEqual(unknown, [("000001.SZ", "NO_CACHE")])
        echo.assert_called_once()

    def test_unknown_history_table_not_silently_approved(self):
        p = {"pending": {"000001.SZ": {"reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Balance"}}}
        cases, unknown = D.selected_cases(p)
        self.assertEqual(cases, {})
        self.assertEqual(unknown, [("000001.SZ", "SOURCE_HISTORY_CONFLICT")])

    def test_batched_sorted(self):
        self.assertEqual(D.plan_batches(["3", "2", "1"], 2), [["1", "2"], ["3"]])

    def test_invalid_batch(self):
        with self.assertRaises(ValueError):
            D.plan_batches(["A"], 21)

    def test_schedule_guard(self):
        tz = timezone(timedelta(hours=8))
        for h, minute in [(18, 45), (20, 5), (23, 34)]:
            with self.assertRaises(RuntimeError):
                D.guarded_time(datetime(2026, 11, 25, h, minute, tzinfo=tz))
        for h, minute in [(11, 40), (18, 44), (23, 35)]:
            D.guarded_time(datetime(2026, 11, 25, h, minute, tzinfo=tz))

    def test_ledger_hash_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a"
            p.write_bytes(b"abc")
            self.assertEqual(D.blob_sha256(p), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


class EndToEndOfflineTests(unittest.TestCase):
    def _workspace(self):
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name)
        root = base / "private"
        root.mkdir()
        path = base / "work" / "qmt_extra" / "financial-cache-progress.json"
        path.parent.mkdir(parents=True)
        p = {"format": "qmt_financial_cache_import_v1", "root": str(root),
             "daily_date": "2026-11-24", "daily_cursor": "002420.SZ",
             "pending_retry_cursor": "688259.SH", "pending": {
                 "002188.SZ": {"reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Capital scoped_m_quarter_proof=REPORT_KEYS_ADDED_OR_REMOVED"},
                 "002388.SZ": {"reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Top10FlowHolder removed_or_revised=9"},
                 "688259.SH": {"reason": "CACHE_DECODE_ERROR", "detail": "UTF8"}}}
        path.write_text(json.dumps(p), encoding="utf-8")
        return tmp, base, path

    def test_full_audit_with_two_mocked_stocks(self):
        tmp, base, ledger = self._workspace()
        with tmp:
            history = {
                "002188.SZ": rows(capital("20250331", "Q1"), capital("20250331", "Q2")),
                "002388.SZ": rows({"name": "ABC", "endDate": "20260930", "declareDate": "20261022", "shares": 50})}
            current = {
                "002188.SZ": {"Capital": [capital("20250331", "Q2"), capital("20250630", "Q2")]},
                "002388.SZ": {"Top10FlowHolder": [{"name": "ABC", "endDate": "20260930", "declareDate": "20261027", "shares": 50}]}}
            class LocalF(FakeF):
                @staticmethod
                def _prior_rows(root, code, table):
                    return "2026-11-17", history[code]
                @staticmethod
                def _recover_utf8_group(worker, group, mode, asof, lookback, workspace, timeout, progress):
                    if mode != "cache": raise AssertionError("must use cache only")
                    return [(code, current[code], None) for code in group]
                _worker_batch = object()
            with patch("builtins.print") as out:
                D.audit(base, LocalF, max_minutes=10, batch_size=10)
            rendered = "\n".join(" ".join(str(v) for v in a.args) for a in out.call_args_list)
            self.assertIn("FINANCE_PENDING_COMPREHENSIVE_CACHE_AUDIT_PASS_NO_COMMIT", rendered)
            self.assertIn("CAPITAL_ADDITIVE_KEYS_WITH_PRIOR_VARIANTS", rendered)
            self.assertIn("DATE_OR_TYPE_ONLY", rendered)
            self.assertIn("FINANCE_LEDGER_UNCHANGED_VERIFIED", rendered)
            self.assertEqual(json.loads(ledger.read_text())["pending_retry_cursor"], "688259.SH")

    def test_ledger_mutation_during_worker_is_detected(self):
        tmp, base, ledger = self._workspace()
        with tmp:
            class BadF(FakeF):
                @staticmethod
                def _recover_utf8_group(*args, **kwargs):
                    ledger.write_text(ledger.read_text() + "\n", encoding="utf-8")
                    return []
                _worker_batch = object()
            with patch("builtins.print"):
                with self.assertRaisesRegex(RuntimeError, "FINANCE_PENDING_LEDGER_CHANGED_DURING_AUDIT_STOP"):
                    D.audit(base, BadF)


if __name__ == "__main__":
    unittest.main()
