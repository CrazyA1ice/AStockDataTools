"""Synthetic selected-snapshot Top10Holder duplicate provenance. NO QMT/Parquet."""
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

source = Path(__file__).resolve().parent.parent / "qmt_finance_top10holder_duplicate_audit_once.py"
spec = importlib.util.spec_from_file_location("holder_duplicate_audit", source)
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


class E:
    FIN_TABLES = ("Balance", "Income", "CashFlow", "Capital",
                  "Top10FlowHolder", "Top10Holder", "HolderNum",
                  "PershareIndex", "PerShare")

    @staticmethod
    def canonical_json(row):
        return json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _path_check(path):
        return None

    @staticmethod
    def _financial_snapshot_file(root, code, table, asof):
        f = root / "financial" / table / code / "snapshots" / (asof+"-"+"0"*16+".parquet")
        return f if f.is_file() else None

    @staticmethod
    def _financial_snapshot_rows(root, code, table, asof):
        p = E._financial_snapshot_file(root, code, table, asof)
        return json.loads(p.read_text(encoding="utf-8")) if p else None


class F:
    E = E

    @staticmethod
    def _rows(rows):
        return Counter(E.canonical_json({k: v for k, v in r.items() if k != "_index"})
                       for r in rows)

    @staticmethod
    def _prior_rows(root, code, table):
        folder = root / "financial" / table / code / "snapshots"
        days = sorted({p.name[:10] for p in folder.glob("*.parquet")})
        union = Counter()
        for day in days:
            union |= F._rows(E._financial_snapshot_rows(root, code, table, day))
        return (max(days), union) if days else (None, None)


def row(index="0", name="Company A", end="20260930", amount=11):
    return {"_index": str(index), "name": name, "endDate": end,
            "shares": amount}


def workspace(root):
    base = Path(root)
    private = base / "private"
    private.mkdir()
    ledger = base / "work" / "qmt_extra" / "financial-cache-progress.json"
    ledger.parent.mkdir(parents=True)
    pending = {
        D.CODE: {"reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Capital"},
        "688259.SH": {"reason": "CACHE_DECODE_ERROR"}
    }
    for i in range(52):
        pending["9{:05d}.SZ".format(i)] = {
            "reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Top10Holder"}
    assert len(pending) == 54
    ledger.write_text(json.dumps({
        "format": "qmt_financial_cache_import_v1",
        "daily_date": D.LEDGER_DATE, "root": str(private),
        "pending": pending}), encoding="utf-8")
    return private, ledger


def selected(private, day, rows):
    folder = private / "financial" / D.TABLE / D.CODE / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / (day + "-" + "0"*16 + ".parquet")
    file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return file


class PureEvidenceTests(unittest.TestCase):
    def test_raw_duplicate_in_one_snapshot(self):
        old = {"2026-11-17": [row("0"), row("1")]}
        summary, groups, union, daily = D.examine(old, [row("0")], F)
        self.assertEqual(summary["historical_extra_raw_occurrences"], 1)
        self.assertEqual(summary["historical_distinct_raw_records"], 1)
        self.assertEqual(groups[0]["history_union_max_count"], 2)
        self.assertEqual(groups[0]["current_cache_count"], 1)
        self.assertEqual(groups[0]["selected_snapshot_days"][0]["distinct_snapshot_row_positions"], 2)
        self.assertFalse(summary["allow_deduplication"])
        self.assertFalse(groups[0]["allow_deduplication"])

    def test_same_raw_record_across_days_not_double_counted(self):
        old = {"2026-11-17": [row()], "2026-11-18": [row()]}
        summary, groups, union, daily = D.examine(old, [row()], F)
        self.assertEqual(summary["historical_extra_raw_occurrences"], 0)
        self.assertEqual(summary["historical_distinct_raw_records"], 1)
        self.assertEqual(groups, [])

    def test_two_duplicates_on_one_day_and_three_on_next_max_three(self):
        old = {"2026-11-17": [row("0"), row("1")],
               "2026-11-18": [row("0"), row("1"), row("2")]}
        summary, groups, union, daily = D.examine(old, [row()], F)
        self.assertEqual(summary["historical_records_with_multiplicity"], 3)
        self.assertEqual(summary["historical_extra_raw_occurrences"], 2)
        self.assertEqual(groups[0]["present_in_snapshot_days"] if "present_in_snapshot_days" in groups[0] else len(groups[0]["selected_snapshot_days"]), 2)

    def test_names_redacted_in_emitted_analysis(self):
        name = "Private Holder Name ABC"
        _, groups, _, _ = D.examine({"2026-11-17": [row("0", name), row("1", name)]},
                                     [row("0", name)], F)
        self.assertNotIn(name, json.dumps(groups))
        self.assertRegex(groups[0]["raw_sha256"], "^[a-f0-9]{64}$")

    def test_duplicate_row_is_not_equivalent_to_two_different_holders(self):
        old = {"2026-11-17": [row("0", "A"), row("1", "B")]}
        summary, groups, _, _ = D.examine(old, old["2026-11-17"], F)
        self.assertEqual(summary["historical_extra_raw_occurrences"], 0)
        self.assertEqual(len(groups), 0)

    def test_changed_business_value_not_categorized_as_same_raw(self):
        old = {"2026-11-17": [row("0", "A", amount=100)]}
        summary, groups, _, _ = D.examine(old, [row("0", "A", amount=101)], F)
        self.assertEqual(summary["missing_historical_occurrences_in_current"], 1)
        self.assertEqual(summary["new_current_occurrences"], 1)

    def test_current_duplicate_exceeds_history(self):
        old = {"2026-11-17": [row("0")]}
        summary, groups, _, _ = D.examine(old, [row("0"), row("1")], F)
        self.assertEqual(summary["current_extra_raw_occurrences"], 1)
        self.assertEqual(summary["new_current_occurrences"], 1)

    def test_duplicate_only_in_second_selected_day_is_attributed(self):
        old = {
            "2026-11-17": [row("0")],
            "2026-11-18": [row("0"), row("1")],
        }
        summary, groups, _, _ = D.examine(old, [row("0")], F)
        self.assertEqual(summary["historical_extra_raw_occurrences"], 1)
        self.assertEqual([x["raw_row_occurrences"] for x in
                          groups[0]["selected_snapshot_days"]], [1, 2])
        self.assertEqual(groups[0]["current_cache_count"], 1)
        self.assertFalse(groups[0]["allow_deduplication"])

    def test_missing_days_rejected(self):
        with self.assertRaisesRegex(ValueError, "DAYS_INVALID"):
            D.examine({}, [], F)

    def test_bad_snapshot_payload_rejected(self):
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_ROW_INVALID"):
            D.examine({"2026-11-17": [False]}, [], F)

    def test_invalid_day_rejected(self):
        with self.assertRaisesRegex(ValueError, "PER_DAY_INVALID"):
            D.examine({"bad-date": []}, [], F)

    def test_missing_current_rows_rejected(self):
        with self.assertRaisesRegex(ValueError, "CURRENT_ROWS_INVALID"):
            D.examine({"2026-11-17": [row()]}, None, F)

    def test_hash_determinism_order_independent(self):
        a = {"2026-11-17": [row("0"), row("1")]}
        b = {"2026-11-17": [row("1"), row("0")]}
        s1, g1, _, _ = D.examine(a, [row("0")], F)
        s2, g2, _, _ = D.examine(b, [row("0")], F)
        self.assertEqual(s1["historical_union_sha256"], s2["historical_union_sha256"])


class RunContractTests(unittest.TestCase):
    def test_time_boundary(self):
        tz = timezone(timedelta(hours=8))
        with self.assertRaisesRegex(RuntimeError, "SCHEDULE_WINDOW"):
            D.guard_clock(datetime(2026, 11, 25, 20, 5, tzinfo=tz))
        D.guard_clock(datetime(2026, 11, 25, 12, 50, tzinfo=tz))

    def test_epoch_identity(self):
        with tempfile.TemporaryDirectory() as td:
            private, ledger = workspace(td)
            data = json.loads(ledger.read_text())
            D.verify_ledger(data, D.LEDGER_SHA)
            with self.assertRaisesRegex(RuntimeError, "LEDGER_PIN_CHANGED"):
                D.verify_ledger(data, "0" * 64)

    def test_wrong_target_stays_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            private, ledger = workspace(td)
            data = json.loads(ledger.read_text())
            data["pending"][D.CODE]["detail"] = "table=Top10Holder"
            with self.assertRaisesRegex(RuntimeError, "PENDING_SCOPE_CHANGED"):
                D.verify_ledger(data, D.LEDGER_SHA)

    def _run(self, mutate=False, reconcile_break=False):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            private, ledger = workspace(base)
            selected(private, "2026-11-17", [row("0"), row("1")])
            selected(private, "2026-11-18", [row("0")])
            class Worker(F):
                @staticmethod
                def _worker_batch(codes, mode, date, lookback, tmp, timeout, progress):
                    if codes != [D.CODE] or mode != "cache":
                        raise AssertionError("NOT_CACHE_ONLY_ONE_STOCK")
                    if mutate:
                        ledger.write_text(ledger.read_text() + " ")
                    return {D.CODE: {
                        t: ([row("0")] if t == D.TABLE else [])
                        for t in E.FIN_TABLES
                    }}, []
                @staticmethod
                def _prior_rows(root, code, table):
                    if reconcile_break:
                        return "2026-11-18", Counter()
                    return F._prior_rows(root, code, table)
            original = D.sha_file
            def sha(path):
                if Path(path) == ledger:
                    return "0"*64 if ledger.read_text().endswith(" ") else D.LEDGER_SHA
                return original(path)
            sink = io.StringIO()
            with patch.object(D, "sha_file", side_effect=sha), \
                 patch.object(D, "guard_clock"), redirect_stdout(sink):
                if mutate:
                    with self.assertRaisesRegex(RuntimeError, "LEDGER_CHANGED_DURING_RUN"):
                        D.run(base, E, Worker)
                    result = None
                elif reconcile_break:
                    with self.assertRaisesRegex(RuntimeError, "COUNTER_MAX_UNION_MISMATCH"):
                        D.run(base, E, Worker)
                    result = None
                else:
                    result = D.run(base, E, Worker)
            return result, sink.getvalue()

    def test_one_symbol_cache_only_and_pin_verified(self):
        result, output = self._run()
        self.assertEqual(len(result["snapshots"]), 2)
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["summary"]["historical_extra_raw_occurrences"], 1)
        self.assertIn("DUPLICATE_AUDIT_COMPLETE_NO_DEPLOY", output)
        self.assertIn("DUPLICATE_AUDIT_ROW_PROVENANCE=", output)
        self.assertLess(output.index("DUPLICATE_AUDIT_LEDGER_UNCHANGED_VERIFIED"),
                        output.index("DUPLICATE_AUDIT_ROW_PROVENANCE="))

    def test_changed_ledger_does_not_emit_provenance(self):
        _, output = self._run(mutate=True)
        self.assertNotIn("DUPLICATE_AUDIT_ROW_PROVENANCE=", output)
        self.assertNotIn("DUPLICATE_AUDIT_SUMMARY=", output)
        self.assertNotIn("DUPLICATE_AUDIT_COMPLETE_NO_DEPLOY", output)

    def test_mismatched_production_union_fails_closed(self):
        _, output = self._run(reconcile_break=True)
        self.assertNotIn("DUPLICATE_AUDIT_COMPLETE_NO_DEPLOY", output)


if __name__ == "__main__":
    unittest.main()
