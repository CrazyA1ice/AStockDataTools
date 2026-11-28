"""Synthetic-only original-production vs P3.21 saved-old finance union parity."""
from __future__ import annotations

import contextlib
from collections import Counter
from hashlib import sha256
from io import StringIO
import inspect as introspect
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_finance_original_reader_parity_readonly as S


class OriginalPriorReaderParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.module = base / "module"
        self.work = self.module / "work" / "qmt_extra"
        self.work.mkdir(parents=True)
        self.stock_root = base / "stock"
        self.extra = self.stock_root / "AllCycleAStockData" / "qmt_extra"
        self.extra.mkdir(parents=True)
        for period in S.PRIOR.EXTRA.L.PERIODS:
            (self.extra.parent / period).mkdir()
        (self.extra / "financial").mkdir()
        self.code = "000001.SZ"
        self.table = "Top10Holder"
        self.day = "2026-11-23"

    def record(self, reason="SOURCE_HISTORY_CONFLICT", table=None,
               stock=None, detail=None):
        stock = stock or self.code
        table = table or self.table
        return {"reason": reason, "attempts": 1, "asof": "2026-11-25",
                "detail": detail or ("SOURCE_HISTORY_CONFLICT " + stock +
                    " table=" + table + " removed_or_revised=2")}

    def ledger(self, pending=None):
        if pending is None:
            pending = {self.code: self.record()}
        obj = {"format": S.LEDGER.CACHE.FORMAT,
               "root": str(self.extra.resolve()),
               "daily_date": "2026-11-25", "daily_cursor": "002639.SZ",
               "import_cursor": "", "daily_sweep_reached_end": False,
               "pending": pending}
        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
        (self.work / S.PRIOR.NAME).write_bytes(raw)
        return sha256(raw).hexdigest()

    def snapshot(self, *, rows=None, day=None, table=None, stock=None):
        stock = stock or self.code
        table = table or self.table
        day = day or self.day
        rows = rows if rows is not None else [{"_index": "0", "amount": 100}]
        arrow = S.PRIOR.EXTRA.snapshot_table(day, stock, table, rows)
        path = S.PRIOR.EXTRA._snapshot_path(
            self.extra, "financial/" + table + "/" + stock, day, arrow)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(arrow, path, compression="zstd")
        pin = path.parent.parent / "active" / (day + ".json")
        pin.parent.mkdir(parents=True, exist_ok=True)
        pin.write_text(json.dumps({
            "format": "qmt_financial_active_v1",
            "symbol": stock, "table": table, "asof": day,
            "filename": path.name,
            "sha256": sha256(path.read_bytes()).hexdigest()}),
            encoding="utf-8")
        return path

    def pins(self, ledger):
        original = S.RAW.inspect(self.module, self.stock_root, ledger,
            S.PRIOR.inspect(self.module, self.stock_root,
                ledger)["physical_snapshot_manifest_sha256"])
        return (original["verified_prior_snapshot_manifest_sha256"],
                original["prior_content_union_manifest_sha256"])

    def run_scan(self, ledger, pins=None):
        phys, union = pins or self.pins(ledger)
        return S.inspect(self.module, self.stock_root, ledger, phys, union)

    def test_01_one_old_snapshot_original_reader_exact_union(self):
        self.snapshot()
        ledger = self.ledger()
        result = self.run_scan(ledger)
        self.assertEqual(result["old_conflict_scopes_original_reader_parity_checked"], 1)
        self.assertEqual(result["original_reader_union_distinct_total"], 1)
        self.assertEqual(result["original_reader_union_multiset_total"], 1)
        self.assertEqual(result["old_active_snapshots_accepted_p321"], 1)
        self.assertTrue(result["production_saved_old_multiset_semantics_matched"])
        self.assertFalse(result["fresh_qmt_or_finance_source_queried"])
        self.assertFalse(result["financial_pending_resolved"])

    def test_02_two_days_union_is_max_multiplicity_not_sum(self):
        self.snapshot(rows=[{"_index": "1", "value": 42},
                            {"_index": "2", "value": 42}])
        self.snapshot(day="2026-11-24",
                      rows=[{"_index": "3", "value": 42}])
        ledger = self.ledger()
        result = self.run_scan(ledger)
        self.assertEqual(result["old_active_snapshots_accepted_p321"], 2)
        self.assertEqual(result["old_raw_rows_accepted_p321"], 3)
        self.assertEqual(result["original_reader_union_distinct_total"], 1)
        self.assertEqual(result["original_reader_union_multiset_total"], 2)

    def test_03_empty_stored_conflict_scope_does_not_authorize_repair(self):
        ledger = self.ledger({})
        result = self.run_scan(ledger)
        self.assertEqual(result["old_conflict_scopes_original_reader_parity_checked"], 0)
        self.assertEqual(result["matched_old_union_manifest_sha256"],
                         sha256(b"").hexdigest())
        self.assertFalse(result["all_historical_finance_coverage_certified"])
        self.assertFalse(result["financial_repair_authorized"])

    def test_04_mismatched_saved_ledger_sha_blocks_original_reader(self):
        self.snapshot()
        self.ledger()
        with mock.patch.object(
                S.IMPORT, "_prior_rows",
                side_effect=AssertionError("original reader should not run")):
            with self.assertRaises(S.PRIOR.SnapshotError):
                S.inspect(self.module, self.stock_root, "f"*64,
                          "f"*64, "f"*64)

    def test_05_wrong_physical_manifest_refused(self):
        self.snapshot()
        ledger = self.ledger()
        _, union = self.pins(ledger)
        with self.assertRaisesRegex(
                S.RAW.ContentError,
                "PRIOR_FINANCE_PINNED_SNAPSHOT_MANIFEST_SHA_MISMATCH"):
            S.inspect(self.module, self.stock_root, ledger, "f"*64, union)

    def test_06_wrong_prior_content_union_sha_refused(self):
        self.snapshot()
        ledger = self.ledger()
        physical, _ = self.pins(ledger)
        with self.assertRaisesRegex(
                S.ParityError, "PRIOR_CONTENT_SHA_DIFFERENT_FROM_ACCEPTED_WINDOWS_PROOF"):
            S.inspect(self.module, self.stock_root, ledger, physical, "f"*64)

    def test_07_original_reader_altered_history_detected(self):
        self.snapshot()
        ledger = self.ledger()
        key = S.PRIOR.EXTRA.canonical_json({"amount": 10})
        with mock.patch.object(S.IMPORT, "_prior_rows",
                               return_value=(self.day, Counter({key: 1}))):
            with self.assertRaisesRegex(
                    S.ParityError,
                    "ORIGINAL_READER_CONTENT_UNION_DIGEST_DIVERGES_FROM_P321"):
                self.run_scan(ledger)

    def test_08_original_reader_last_day_mismatch_fails_closed(self):
        self.snapshot()
        ledger = self.ledger()
        with mock.patch.object(
                S.IMPORT, "_prior_rows",
                return_value=("2026-11-25", Counter({"a": 1}))):
            with self.assertRaisesRegex(
                    S.ParityError, "ORIGINAL_READER_OLD_ASOF_DATES_DIFFER"):
                self.run_scan(ledger)

    def test_09_reader_non_counter_result_never_used(self):
        self.snapshot()
        ledger = self.ledger()
        with mock.patch.object(S.IMPORT, "_prior_rows",
                               return_value=(self.day, {"k": 1})):
            with self.assertRaisesRegex(S.ParityError,
                                        "ORIGINAL_READER_UNION_NOT_COUNTER"):
                self.run_scan(ledger)

    def test_10_reader_bad_negative_row_count_rejected(self):
        self.snapshot()
        ledger = self.ledger()
        with mock.patch.object(S.IMPORT, "_prior_rows",
                               return_value=(self.day, Counter({"k": -1}))):
            with self.assertRaisesRegex(S.ParityError,
                                        "ORIGINAL_READER_UNION_ENTRY_INVALID"):
                self.run_scan(ledger)

    def test_11_reader_non_string_canonical_row_key_rejected(self):
        self.snapshot()
        ledger = self.ledger()
        with mock.patch.object(S.IMPORT, "_prior_rows",
                               return_value=(self.day, Counter({1: 2}))):
            with self.assertRaisesRegex(S.ParityError,
                                        "ORIGINAL_READER_UNION_ENTRY_INVALID"):
                self.run_scan(ledger)

    def test_12_reader_union_multiplicity_budget_refused(self):
        self.snapshot()
        ledger = self.ledger()
        with mock.patch.object(
                S.IMPORT, "_prior_rows",
                return_value=(self.day, Counter({"a": 2}))):
            with mock.patch.object(S, "MAX_TOTAL_OLD_UNION_MULTIPLICITY", 1):
                with self.assertRaisesRegex(
                        S.ParityError,
                        "ORIGINAL_READER_UNION_MULTIPLICITY_BUDGET"):
                    self.run_scan(ledger)

    def test_13_missing_prior_snapshot_never_replayed_or_created(self):
        ledger = self.ledger()
        with self.assertRaisesRegex(
                S.RAW.ContentError,
                "PRIOR_FINANCE_MISSING_OLD_SNAPSHOT_SCOPE"):
            self.run_scan(ledger)
        self.assertFalse((self.extra/"financial"/self.table/self.code).exists())

    def test_14_original_reader_errors_sanitized(self):
        self.snapshot()
        ledger = self.ledger()
        with mock.patch.object(
                S.IMPORT, "_prior_rows",
                side_effect=ValueError("D:/private/stock/secret.parquet")):
            output = StringIO()
            with contextlib.redirect_stdout(output):
                rc = S.main([
                    "--module-root", str(self.module),
                    "--stock-root", str(self.stock_root),
                    "--expected-ledger-sha256", ledger,
                    "--expected-snapshot-manifest-sha256", self.pins(ledger)[0],
                    "--expected-old-union-sha256", self.pins(ledger)[1]])
        self.assertEqual(rc, 3)
        self.assertIn("PRODUCTION_PRIOR_READER_PARITY_READONLY_REVIEW_REQUIRED",
                      output.getvalue())
        self.assertNotIn("D:/private", output.getvalue())

    def test_15_two_table_scopes_in_same_ledger(self):
        self.snapshot()
        self.snapshot(table="HolderNum", stock="000002.SZ",
                      rows=[{"_index": "a", "owners": 9}])
        pending = {
            self.code: self.record(),
            "000002.SZ": self.record(stock="000002.SZ", table="HolderNum")}
        ledger = self.ledger(pending)
        result = self.run_scan(ledger)
        self.assertEqual(result["old_conflict_scopes_original_reader_parity_checked"], 2)
        self.assertEqual(result["by_table"]["Top10Holder"]["source_conflict_scopes"], 1)
        self.assertEqual(result["by_table"]["HolderNum"]["source_conflict_scopes"], 1)
        self.assertEqual(result["original_reader_union_multiset_total"], 2)

    def test_16_saved_other_reason_is_not_an_old_conflict_scope(self):
        ledger = self.ledger({
            self.code: {"reason": "CACHE_DECODE_ERROR",
                        "attempts": 5, "asof": "2026-11-25"}})
        result = self.run_scan(ledger)
        self.assertEqual(result["saved_ledger_pending_count_unchanged"], 1)
        self.assertEqual(result["old_conflict_scopes_original_reader_parity_checked"], 0)

    def test_17_postflight_old_source_changed_is_detected(self):
        self.snapshot()
        ledger = self.ledger()
        physical, union = self.pins(ledger)
        real_inspect = S.RAW.inspect
        calls = [0]

        def simulate_changed(*a):
            calls[0] += 1
            value = real_inspect(*a)
            if calls[0] == 2:
                value = dict(value)
                value["prior_content_union_manifest_sha256"] = "f"*64
            return value

        with mock.patch.object(S.RAW, "inspect",
                               side_effect=simulate_changed):
            with self.assertRaisesRegex(
                    S.ParityError,
                    "ORIGINAL_READER_OLD_CONTENT_CHANGED_DURING_PARITY_CHECK"):
                S.inspect(self.module, self.stock_root,
                          ledger, physical, union)

    def test_18_source_security_non_writing_and_unshadowed_runner(self):
        self.assertIs(type(self).run, unittest.TestCase.run)
        source = introspect.getsource(S)
        for forbidden in ("download_history_data(", "get_market_data_ex(",
                          "write_table(", "write_bytes(", "mkdir(", "unlink(",
                          "os.replace(", "rename(", "GAP.verify_original(",
                          "AUDIT.audit(", "IMPORT.run("):
            self.assertNotIn(forbidden, source)
        self.assertEqual(S.MAX_SCOPES, 128)
        self.assertEqual(S.STATUS,
            "PRODUCTION_READER_OLD_HISTORICAL_UNION_MATCHED_FRESH_NOT_CHECKED")


if __name__ == "__main__":
    unittest.main()
