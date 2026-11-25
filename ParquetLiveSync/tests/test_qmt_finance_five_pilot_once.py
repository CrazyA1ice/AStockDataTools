"""Offline contract tests for the five-stock QMT cache-only pilot.

All cache calls are fake, all paths are temp, no xtquant or Parquet required.
"""
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def module(name, basename):
    path = Path(__file__).resolve().parent.parent / basename
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


A = module("finance_five_pilot", "qmt_finance_five_pilot_once.py")
P = module("recovery_preview", "qmt_finance_versioned_recovery_preview.py")


class FakeE:
    FIN_TABLES = ("Balance", "Income", "CashFlow", "Capital",
                  "Top10FlowHolder", "Top10Holder", "HolderNum",
                  "PershareIndex", "PerShare")

    @staticmethod
    def canonical_json(obj):
        return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))

    @staticmethod
    def _path_check(path):
        return None


class FakeF:
    E = FakeE

    @staticmethod
    def _rows(rows):
        return Counter(FakeE.canonical_json({k: v for k, v in x.items()
                                            if k != "_index"}) for x in rows)


def fixture():
    # Five cases use compact synthetic source records with the same observed
    # field shapes as the owner's real QMT data.
    old = {
        "002178.SZ": {"endDate": "20260930", "name": "Old A",
                      "type": "QFII机构", "shares": 11},
        "002188.SZ": {"m_timetag": 20260331, "m_quarter": 1.,
                      "total_capital": 10},
        "002310.SZ": {"endDate": "20260930", "name": "Old B",
                      "type": "公司", "shares": 13},
        "002328.SZ": {"endDate": "20260930", "declareDate": "20261029",
                      "shareholder": 57896., "shareholderA": 57896.},
        "002388.SZ": {"endDate": "20260930", "declareDate": "20261022",
                      "name": "Holder", "type": "公司", "shares": 99},
    }
    new = {
        "002178.SZ": [dict(old["002178.SZ"], name="New A", type="公司")],
        "002188.SZ": [dict(old["002188.SZ"], m_quarter=2.),
                      {"m_timetag": 20260930, "m_quarter": 3., "total_capital": 10}],
        "002310.SZ": [dict(old["002310.SZ"], name="New B")],
        "002328.SZ": [dict(old["002328.SZ"], declareDate="20261012",
                          shareholder=57900., shareholderA=57900.)],
        "002388.SZ": [dict(old["002388.SZ"], declareDate="20261027",
                          type="机构投资账户")],
    }
    return old, new


def evidence_document(old, new):
    cases = []
    for code, table, mode in A.CASES:
        if mode != "ISSUER_DISPUTED":
            continue
        fields = {
            "002178.SZ": ["name", "type"],
            "002310.SZ": ["name"],
            "002328.SZ": ["declareDate", "shareholder", "shareholderA"],
        }[code]
        raw_a = P.encode(old[code], FakeF)
        raw_b = P.encode(new[code][0], FakeF)
        stable = P._projection(old[code], frozenset(fields), FakeF)
        cases.append({
            "symbol": code, "table": table, "endDate": "20260930",
            "manual_approval_required": True, "pairing_unambiguous": True,
            "changed_fields": fields,
            "prior_record_sha256": P.digest(raw_a),
            "current_record_sha256": P.digest(raw_b),
            "stable_projection_sha256": P.digest(stable),
            "issuer_source": "https://example.org/test-issuer",
            "issuer_confirmation": "REVIEW_ONLY",
        })
    return {
        "schema": "astock_finance_source_disclosure_proof_v1",
        "format": "unused", "cases": cases,
        "default_action": "HOLD_PENDING_NO_COMMIT",
        "allow_auto_clear": False,
        "allow_snapshot_mutation": False,
        "allow_provider_cache_mutation": False,
        "ledger_sha256_unchanged": A.KNOWN_LEDGER_SHA256,
    }


def workspace(root, *, mutate=None):
    root = Path(root)
    private = root / "private"
    private.mkdir()
    state_path = root / "work" / "qmt_extra" / "financial-cache-progress.json"
    state_path.parent.mkdir(parents=True)
    pending = {
        code: {
            "reason": "SOURCE_HISTORY_CONFLICT",
            "detail": "SOURCE_HISTORY_CONFLICT table=" + table
        } for code, table, mode in A.CASES
    }
    pending["688259.SH"] = {"reason": "CACHE_DECODE_ERROR"}
    for i in range(A.KNOWN_PENDING - len(pending)):
        pending["9{:05d}.SZ".format(i)] = {
            "reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Top10Holder"}
    assert len(pending) == A.KNOWN_PENDING
    state = {
        "format": A.LEDGER_FORMAT,
        "root": str(private), "daily_date": A.KNOWN_LEDGER_DATE,
        "pending": pending
    }
    if mutate:
        mutate(state)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return state_path


class LedgerTests(unittest.TestCase):
    def test_cohort_is_five_and_never_includes_utf8_bad_symbol(self):
        self.assertEqual(len(A.CASES), 5)
        self.assertEqual([x[0] for x in A.CASES], sorted(x[0] for x in A.CASES))
        self.assertNotIn("688259.SH", [x[0] for x in A.CASES])

    def test_schedule_guard(self):
        tz = timezone(timedelta(hours=8))
        for hour, minute in [(18, 45), (20, 5), (23, 34)]:
            with self.assertRaisesRegex(RuntimeError, "NIGHTLY_WINDOW"):
                A.protect_time(datetime(2026, 11, 25, hour, minute, tzinfo=tz))
        for hour, minute in [(11, 0), (18, 44), (23, 35)]:
            A.protect_time(datetime(2026, 11, 25, hour, minute, tzinfo=tz))

    def test_verified_history_epoch_bound(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = workspace(td)
            state = json.loads(ledger.read_text())
            A.verify_ledger(state, A.KNOWN_LEDGER_SHA256)
            with self.assertRaisesRegex(ValueError, "CHANGED_SINCE_VERIFIED_AUDIT"):
                A.verify_ledger(state, "0" * 64)

    def test_missing_case_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = workspace(td)
            state = json.loads(ledger.read_text())
            del state["pending"]["002188.SZ"]
            with self.assertRaisesRegex(ValueError, "VERIFIED_AUDIT_SCOPE_CHANGED"):
                A.verify_ledger(state, A.KNOWN_LEDGER_SHA256)

    def test_replaced_case_table_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = workspace(td)
            state = json.loads(ledger.read_text())
            state["pending"]["002310.SZ"]["detail"] = "table=Capital"
            with self.assertRaisesRegex(ValueError, "PENDING_TABLE_CHANGED"):
                A.verify_ledger(state, A.KNOWN_LEDGER_SHA256)

    def test_known_bad_utf8_case_cannot_disappear(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = workspace(td)
            state = json.loads(ledger.read_text())
            state["pending"]["688259.SH"]["reason"] = "NO_CACHE"
            with self.assertRaisesRegex(ValueError, "KNOWN_UTF8_QUARANTINE_CHANGED"):
                A.verify_ledger(state, A.KNOWN_LEDGER_SHA256)

    def test_manifest_requires_no_auto_clear(self):
        old, new = fixture()
        doc = evidence_document(old, new)
        A.verify_evidence(doc)
        doc["allow_auto_clear"] = True
        with self.assertRaisesRegex(ValueError, "NOT_FAIL_CLOSED"):
            A.verify_evidence(doc)

    def test_manifest_no_mutation_flags_required(self):
        old, new = fixture()
        doc = evidence_document(old, new)
        doc["allow_provider_cache_mutation"] = True
        with self.assertRaisesRegex(ValueError, "NOT_FAIL_CLOSED"):
            A.verify_evidence(doc)

    def test_manifest_case_scope_fixed(self):
        old, new = fixture()
        doc = evidence_document(old, new)
        doc["cases"][0]["symbol"] = "000001.SZ"
        with self.assertRaisesRegex(ValueError, "ISSUER_CASE_SCOPE_CHANGED"):
            A.verify_evidence(doc)


class PilotTests(unittest.TestCase):
    def _run(self, changed=None, changed_ledger=False, drift_after_evidence=None):
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name)
        ledger = workspace(base)
        old, new = fixture()
        if changed:
            changed(old, new)
        doc = evidence_document(old, new)
        # Freeze the expected source hashes before simulating provider drift.
        if drift_after_evidence:
            drift_after_evidence(old, new)
        manifest = base / "evidence.json"
        manifest.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        class WorkingF(FakeF):
            @staticmethod
            def _prior_rows(root, code, table):
                wanted = dict((a, b) for a, b, _ in A.CASES)
                if table == wanted[code]:
                    return "2026-11-17", FakeF._rows([old[code]])
                return None, None

            @staticmethod
            def _worker_batch(codes, mode, asof, lookback, folder, timeout, progress):
                if mode != "cache" or "688259.SH" in codes:
                    raise AssertionError("BAD_QMT_WORKER_MODE")
                out = {}
                for code in codes:
                    table = next(t for c, t, m in A.CASES if c == code)
                    payload = {name: [] for name in FakeE.FIN_TABLES}
                    payload[table] = [dict(row, _index=str(i)) for i, row in enumerate(new[code])]
                    out[code] = payload
                if changed_ledger:
                    ledger.write_text(ledger.read_text() + " ", encoding="utf-8")
                return out, []
        # Fixture cannot match pinned real SHA, but can force the sha pin
        # to the model's known immutable audit epoch without mutating files.
        before = A.digest_file
        if changed_ledger:
            seq = iter([A.KNOWN_LEDGER_SHA256, "0" * 64])
            digester = lambda x: next(seq)
        else:
            digester = lambda x: A.KNOWN_LEDGER_SHA256
        sink = io.StringIO()
        with patch.object(A, "digest_file", side_effect=digester), \
             patch.object(A, "protect_time"), \
             redirect_stdout(sink):
            if changed_ledger:
                with self.assertRaisesRegex(RuntimeError, "LEDGER_CHANGED_DURING_RUN_STOP"):
                    A.run(base, manifest, FakeE, WorkingF, P)
                result = None
            else:
                result = A.run(base, manifest, FakeE, WorkingF, P)
        out = sink.getvalue()
        tmp.cleanup()
        return result, out

    def test_all_five_reach_review_only_without_data_write(self):
        result, out = self._run()
        self.assertEqual(result["review_only"], 5)
        self.assertEqual(result["blocked"], 0)
        self.assertFalse(result["allow_auto_clear"])
        self.assertFalse(result["allow_apply"])
        self.assertEqual(out.count("PILOT_REVIEW="), 5)
        self.assertIn("FINANCE_FIVE_STOCK_PREVIEW_COMPLETE_NO_COMMIT", out)
        self.assertNotIn("688259.SH", out)

    def test_numeric_case_remains_review_only_not_approved(self):
        result, out = self._run()
        item = next(x for x in result["evidence_only"] if x["symbol"] == "002328.SZ")
        self.assertEqual(item["classification"], "ISSUER_DISPUTED_REVIEW_REQUIRED")
        self.assertIn('"approval_granted": false', out)

    def test_changing_capital_old_business_value_blocks(self):
        def mutate(old, new):
            new["002188.SZ"][0]["total_capital"] = 11
        result, out = self._run(changed=mutate)
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(result["review_only"], 4)
        self.assertIn("PILOT_BLOCKED=", out)

    def test_shareholder_count_drift_fails_special_row_hash(self):
        def mutate(old, new):
            new["002328.SZ"][0]["shareholder"] = 57901.0
        result, out = self._run(drift_after_evidence=mutate)
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(result["review_only"], 4)
        self.assertIn("SPECIAL_RECORD_FINGERPRINT_CHANGED", out)

    def test_ledger_mutation_is_detected_even_after_worker(self):
        _, out = self._run(changed_ledger=True)
        self.assertNotIn("FINANCE_FIVE_STOCK_PREVIEW_COMPLETE_NO_COMMIT", out)
        self.assertNotIn("FINANCE_LEDGER_UNCHANGED_VERIFIED", out)
        self.assertNotIn("PILOT_REVIEW=", out)
        self.assertNotIn("PILOT_SUMMARY=", out)

    def test_success_marker_only_after_final_sha_check(self):
        _, out = self._run()
        checked = out.index("FINANCE_LEDGER_UNCHANGED_VERIFIED")
        review = out.index("PILOT_REVIEW=")
        summary = out.index("PILOT_SUMMARY=")
        complete = out.index("FINANCE_FIVE_STOCK_PREVIEW_COMPLETE_NO_COMMIT")
        self.assertLess(checked, review)
        self.assertLess(review, summary)
        self.assertLess(summary, complete)


if __name__ == "__main__":
    unittest.main()
