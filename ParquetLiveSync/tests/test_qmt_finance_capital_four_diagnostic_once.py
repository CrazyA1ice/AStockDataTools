"""Offline-only Capital root-cause and selected-snapshot provenance tests."""
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


mod = Path(__file__).resolve().parent.parent / "qmt_finance_capital_four_diagnostic_once.py"
spec = importlib.util.spec_from_file_location("capital_four_cause", mod)
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


class E:
    FIN_TABLES = ("Balance", "Income", "CashFlow", "Capital",
                  "Top10FlowHolder", "Top10Holder", "HolderNum",
                  "PershareIndex", "PerShare")

    @staticmethod
    def canonical_json(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))

    @staticmethod
    def _path_check(path):
        return None

    @staticmethod
    def _financial_snapshot_file(root, code, table, asof):
        path = root / "financial" / table / code / "snapshots" / (asof+"-"+("0"*16)+".parquet")
        return path if path.is_file() else None

    @staticmethod
    def _financial_snapshot_rows(root, code, table, asof):
        p = E._financial_snapshot_file(root, code, table, asof)
        return json.loads(p.read_text(encoding="utf-8")) if p else None


class F:
    E = E

    @staticmethod
    def _rows(rows):
        return Counter(D.raw(row, E) for row in rows)

    @staticmethod
    def _prior_rows(root, code, table):
        folder = root / "financial" / table / code / "snapshots"
        days = sorted({p.name[:10] for p in folder.glob("*.parquet")})
        combined = Counter()
        for day in days:
            combined |= F._rows(E._financial_snapshot_rows(root, code, table, day))
        return (max(days), combined) if days else (None, None)


def rec(key=20260331, quarter=1., capital=100., index="0"):
    return {"_index": index, "m_timetag": key,
            "m_quarter": quarter, "total_capital": capital}


def counter(*rs):
    return F._rows(rs)


def write_snapshot(root, code, day, records):
    folder = root / "financial" / "Capital" / code / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (day + "-" + "0"*16 + ".parquet")
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return path


def make_workspace(base):
    root = base / "private"
    root.mkdir()
    ledger = base / "work" / "qmt_extra" / "financial-cache-progress.json"
    ledger.parent.mkdir(parents=True)
    pending = {
        code: {"reason": "SOURCE_HISTORY_CONFLICT",
               "detail": "table=" + D.TARGET[code]} for code in D.CODES
    }
    pending["688259.SH"] = {"reason": "CACHE_DECODE_ERROR"}
    for i in range(54-len(pending)):
        pending["9{:05d}.SZ".format(i)] = {
            "reason": "SOURCE_HISTORY_CONFLICT", "detail": "table=Top10Holder"}
    assert len(pending) == 54
    state = {"format": D.LEDGER_FORMAT, "daily_date": D.LEDGER_DATE,
             "root": str(root), "pending": pending}
    ledger.write_text(json.dumps(state), encoding="utf-8")
    return root, ledger


class AnalyzeTests(unittest.TestCase):
    def test_additive_one_key(self):
        o = counter(rec())
        x = D.analyze_capital(o, [rec(quarter=2.), rec(20260930, 3., index="1")], E)
        self.assertEqual(x["classification"], "ADDITIVE_REPORT_KEYS_REVIEW")
        self.assertEqual(x["new_report_keys"], ["20260930"])
        self.assertEqual(x["removed_report_keys_count"], 0)
        self.assertEqual(x["m_quarter_variant_shared_keys"], 1)
        self.assertFalse(x["approval_granted"])

    def test_history_raw_duplicate_count_not_silently_ignored(self):
        o = counter(rec(), rec(index="1"))
        self.assertEqual(o[D.raw(rec(), E)], 2)
        x = D.analyze_capital(o, [rec()], E)
        self.assertEqual(x["classification"], "HISTORICAL_RAW_DUPLICATES_REVIEW")
        self.assertEqual(x["historical_duplicate_raw_extra_rows"], 1)

    def test_same_key_different_quarter_is_not_same_raw_duplicate(self):
        o = counter(rec(), rec(quarter=2.))
        x = D.analyze_capital(o, [rec(quarter=2.)], E)
        self.assertEqual(x["classification"], "M_QUARTER_OR_RAW_VERSION_REVIEW")
        self.assertEqual(x["historical_duplicate_raw_extra_rows"], 0)
        self.assertEqual(x["historical_duplicate_report_keys_count"], 1)

    def test_missing_old_report_key_is_highest_priority(self):
        o = counter(rec(), rec(20260630, 1., index="1"))
        x = D.analyze_capital(o, [rec(20260630, 1.)], E)
        self.assertEqual(x["classification"], "REPORT_KEYS_MISSING_FROM_CURRENT")
        self.assertEqual(x["removed_report_keys"], ["20260331"])

    def test_fresh_duplicate_key(self):
        o = counter(rec())
        x = D.analyze_capital(o, [rec(), rec(quarter=2., index="1")], E)
        self.assertEqual(x["classification"], "CURRENT_DUPLICATE_REPORT_KEY")

    def test_historical_economic_field_conflict(self):
        o = counter(rec(), rec(capital=110., quarter=2.))
        x = D.analyze_capital(o, [rec()], E)
        self.assertEqual(x["classification"], "HISTORICAL_BUSINESS_CONFLICT")
        self.assertEqual(x["historical_economic_conflict_keys"], 1)

    def test_shared_economic_revision(self):
        x = D.analyze_capital(counter(rec()), [rec(capital=101.)], E)
        self.assertEqual(x["classification"], "SHARED_ECONOMIC_FIELD_CHANGE")
        self.assertEqual(x["shared_economic_changed_keys"], 1)

    def test_identical_raw_version(self):
        x = D.analyze_capital(counter(rec()), [rec()], E)
        self.assertEqual(x["classification"], "RAW_MATCH")
        self.assertEqual(x["old_unmatched_raw_rows"], 0)

    def test_mquarter_only(self):
        x = D.analyze_capital(counter(rec()), [rec(quarter=4.)], E)
        self.assertEqual(x["classification"], "M_QUARTER_OR_RAW_VERSION_REVIEW")
        self.assertEqual(x["shared_economic_changed_keys"], 0)

    def test_invalid_current_index_refused(self):
        r = rec()
        del r["_index"]
        with self.assertRaisesRegex(ValueError, "CURRENT_INDEX_INVALID"):
            D.analyze_capital(counter(rec()), [r], E)

    def test_invalid_key_refused(self):
        with self.assertRaisesRegex(ValueError, "REPORT_KEY_MALFORMED"):
            D.analyze_capital(counter(rec()), [rec(key=0)], E)

    def test_missing_mquarter_refused(self):
        bad = rec()
        del bad["m_quarter"]
        with self.assertRaisesRegex(ValueError, "FIELD_LAYOUT_CHANGED"):
            D.analyze_capital(counter(rec()), [bad], E)

    def test_invalid_historical_counter_refused(self):
        with self.assertRaisesRegex(ValueError, "HISTORICAL_COUNTER_REQUIRED"):
            D.analyze_capital([], [rec()], E)

    def test_no_raw_financial_data_in_evidence(self):
        a = rec(capital=123456789.)
        x = D.analyze_capital(counter(a), [rec(capital=987654321.)], E)
        out = json.dumps(x)
        self.assertNotIn("123456789", out)
        self.assertNotIn("987654321", out)


class SelectedSnapshotTests(unittest.TestCase):
    def test_same_raw_row_in_two_snapshot_days_not_a_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_snapshot(root, D.CODES[0], "2026-11-17", [rec()])
            write_snapshot(root, D.CODES[0], "2026-11-18", [rec()])
            union, days = D.selected_snapshot_diagnostics(root, D.CODES[0], E, F)
            self.assertEqual(sum(union.values()), 1)
            self.assertEqual(sum(x["duplicate_raw_extra_rows"] for x in days), 0)
            self.assertEqual(len(days), 2)
            self.assertTrue(all(len(x["selected_file_sha256"]) == 64 for x in days))

    def test_exact_duplicate_within_single_snapshot_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_snapshot(root, D.CODES[0], "2026-11-17", [rec(), rec(index="1")])
            union, days = D.selected_snapshot_diagnostics(root, D.CODES[0], E, F)
            self.assertEqual(sum(union.values()), 2)
            self.assertEqual(days[0]["duplicate_raw_extra_rows"], 1)
            self.assertEqual(days[0]["duplicate_report_keys"], 1)

    def test_nonstandard_snapshot_filename_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_snapshot(root, D.CODES[0], "2026-11-17", [rec()])
            folder = root / "financial" / "Capital" / D.CODES[0] / "snapshots"
            (folder / "other.parquet").write_text("bad")
            with self.assertRaisesRegex(ValueError, "INVALID_SNAPSHOT_FILENAME"):
                D.selected_snapshot_diagnostics(root, D.CODES[0], E, F)

    def test_missing_snapshot_folder_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "SNAPSHOT_FOLDER_MISSING"):
                D.selected_snapshot_diagnostics(Path(tmp), D.CODES[0], E, F)

    def test_union_reconciliation_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_snapshot(root, D.CODES[0], "2026-11-17", [rec()])
            class BrokenF(F):
                @staticmethod
                def _prior_rows(root, code, table):
                    return "2026-11-17", Counter()
            with self.assertRaisesRegex(RuntimeError, "UNION_RECONCILIATION_FAILED"):
                D.selected_snapshot_diagnostics(root, D.CODES[0], E, BrokenF)


class RunBoundaryTests(unittest.TestCase):
    def test_schedule_protection(self):
        tz = timezone(timedelta(hours=8))
        with self.assertRaisesRegex(RuntimeError, "NIGHTLY_SCHEDULE_WINDOW"):
            D.protect_time(datetime(2026, 11, 25, 20, 5, tzinfo=tz))
        D.protect_time(datetime(2026, 11, 25, 12, 40, tzinfo=tz))

    def test_no_broken_utf8_symbol_selected(self):
        self.assertEqual(len(D.CODES), 4)
        self.assertEqual(sorted(D.CODES), list(D.CODES))
        self.assertNotIn("688259.SH", D.CODES)

    def test_ledger_epoch_changed_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, ledger = make_workspace(Path(tmp))
            state = json.loads(ledger.read_text())
            D.verify_epoch(state, D.LEDGER_SHA)
            with self.assertRaisesRegex(RuntimeError, "VERIFIED_LEDGER_SHA_CHANGED"):
                D.verify_epoch(state, "0"*64)

    def test_changed_target_table_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, ledger = make_workspace(Path(tmp))
            state = json.loads(ledger.read_text())
            state["pending"]["002328.SZ"]["detail"] = "table=Capital"
            with self.assertRaisesRegex(RuntimeError, "TARGET_PENDING_CHANGED_002328"):
                D.verify_epoch(state, D.LEDGER_SHA)

    def test_read_only_four_stock_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, ledger = make_workspace(base)
            for code in D.CODES:
                write_snapshot(root, code, "2026-11-17", [rec()])
            class WorkerF(F):
                @staticmethod
                def _worker_batch(codes, mode, asof, lookback, folder, timeout, progress):
                    assert codes == list(D.CODES) and mode == "cache"
                    return {code: {table: ([rec(), rec(20260930, 2., index="1")]
                                           if table == "Capital" else [])
                                   for table in E.FIN_TABLES} for code in codes}, []
            with patch.object(D, "file_sha", return_value=D.LEDGER_SHA), \
                 patch.object(D, "protect_time"), redirect_stdout(io.StringIO()) as sink:
                D.run(base, E, WorkerF)
            output = sink.getvalue()
            self.assertEqual(output.count("CAPITAL_ROOT_CAUSE="), 4)
            self.assertIn("CAPITAL_FOUR_ROOT_CAUSE_SUMMARY=", output)
            self.assertIn("FINANCE_CAPITAL_FOUR_DIAG_COMPLETE_NO_DEPLOY", output)
            self.assertLess(output.index("CAPITAL_DIAG_LEDGER_UNCHANGED_VERIFIED"),
                            output.index("CAPITAL_ROOT_CAUSE="))

    def test_changed_ledger_suppresses_all_success_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, ledger = make_workspace(base)
            for code in D.CODES:
                write_snapshot(root, code, "2026-11-17", [rec()])
            class WorkerF(F):
                @staticmethod
                def _worker_batch(codes, mode, asof, lookback, folder, timeout, progress):
                    ledger.write_text(ledger.read_text() + " ")
                    return {code: {table: ([rec()] if table == "Capital" else [])
                                   for table in E.FIN_TABLES} for code in codes}, []
            seq = iter((D.LEDGER_SHA, "0"*64))
            with patch.object(D, "file_sha", side_effect=lambda _: next(seq)), \
                 patch.object(D, "protect_time"), redirect_stdout(io.StringIO()) as sink:
                with self.assertRaisesRegex(RuntimeError, "LEDGER_CHANGED_DURING_READ"):
                    D.run(base, E, WorkerF)
            self.assertNotIn("CAPITAL_ROOT_CAUSE=", sink.getvalue())
            self.assertNotIn("FINANCE_CAPITAL_FOUR_DIAG_COMPLETE_NO_DEPLOY", sink.getvalue())


if __name__ == "__main__":
    unittest.main()
