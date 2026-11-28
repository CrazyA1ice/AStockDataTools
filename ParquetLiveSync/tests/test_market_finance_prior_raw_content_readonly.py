"""Synthetic old QMT finance Parquet content and historical union read tests."""
from __future__ import annotations

import contextlib
from hashlib import sha256
from io import StringIO
import inspect as introspect
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_finance_prior_raw_content_readonly as S


class PriorRawContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.module = t / "module"
        self.work = self.module / "work" / "qmt_extra"
        self.work.mkdir(parents=True)
        self.stock_root = t / "stock"
        self.extra = self.stock_root / "AllCycleAStockData" / "qmt_extra"
        self.extra.mkdir(parents=True)
        for period in S.EXTRA.L.PERIODS:
            (self.extra.parent / period).mkdir()
        (self.extra / "financial").mkdir()
        self.code = "000001.SZ"
        self.table = "Top10Holder"
        self.day = "2026-11-23"

    def progress(self, pending=None):
        if pending is None:
            pending = {self.code: {
                "reason": "SOURCE_HISTORY_CONFLICT",
                "asof": "2026-11-25",
                "attempts": 1,
                "detail": ("SOURCE_HISTORY_CONFLICT " + self.code +
                           " table=" + self.table + " removed_or_revised=2")}}
        doc = {"format": S.LEDGER.CACHE.FORMAT,
               "root": str(self.extra.resolve()),
               "import_cursor": "",
               "daily_date": "2026-11-25",
               "daily_cursor": "002639.SZ",
               "daily_sweep_reached_end": False,
               "pending": pending}
        raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        (self.work / S.PRIOR.NAME).write_bytes(raw)
        return sha256(raw).hexdigest()

    def snapshot(self, *, day=None, rows=None, table_name=None,
                 stock=None, force_name=None, arrow=None, pin=True):
        day = day or self.day
        stock = stock or self.code
        name = table_name or self.table
        if arrow is None:
            if rows is None:
                rows = [{"_index": "1", "value": 100.0}]
            arrow = S.EXTRA.snapshot_table(day, stock, name, rows)
        folder = self.extra / "financial" / name / stock / "snapshots"
        folder.mkdir(parents=True, exist_ok=True)
        expected = S.EXTRA._snapshot_path(
            self.extra, "financial/" + name + "/" + stock,
            day, arrow)
        path = folder / (force_name or expected.name)
        pq.write_table(arrow, path, compression="zstd")
        if pin:
            target = folder.parent / "active" / (day + ".json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({
                "format": "qmt_financial_active_v1",
                "symbol": stock, "table": name, "asof": day,
                "filename": path.name,
                "sha256": sha256(path.read_bytes()).hexdigest()}),
                encoding="utf-8")
        return path

    def run(self, *, ledger=None, manifest=None):
        if ledger is None:
            ledger = self.progress()
        if manifest is None:
            manifest = S.PRIOR.inspect(
                self.module, self.stock_root,
                ledger)["physical_snapshot_manifest_sha256"]
        return S.inspect(self.module, self.stock_root, ledger, manifest)

    def test_01_single_valid_snapshot_schema_fingerprint_rows_union(self):
        self.snapshot()
        out = self.run()
        self.assertEqual(out["conflict_scopes_checked"], 1)
        self.assertEqual(out["active_old_snapshot_files_content_verified"], 1)
        self.assertEqual(out["active_old_raw_rows_checked"], 1)
        self.assertEqual(out["table_scoped_counts"][self.table]["old_union_distinct_raw_rows"], 1)
        self.assertEqual(out["table_scoped_counts"][self.table]["old_union_multiset_rows"], 1)
        self.assertTrue(out["old_selected_historical_counter_union_computed"])
        self.assertTrue(out["all_physical_old_snapshot_manifest_rechecked"])
        self.assertFalse(out["new_and_old_finance_records_compared"])
        self.assertFalse(out["full_history_coverage_certified"])
        self.assertFalse(out["original_quarantines_cleared"])

    def test_02_two_dates_union_uses_max_multiplicity_not_sum(self):
        self.snapshot(rows=[{"_index": "1", "amount": 10},
                            {"_index": "2", "amount": 10}])
        self.snapshot(day="2026-11-24",
                      rows=[{"_index": "3", "amount": 10}])
        out = self.run()
        counts = out["table_scoped_counts"][self.table]
        self.assertEqual(counts["active_snapshot_days_checked"], 2)
        self.assertEqual(counts["raw_rows_checked"], 3)
        self.assertEqual(counts["old_union_distinct_raw_rows"], 1)
        self.assertEqual(counts["old_union_multiset_rows"], 2)

    def test_03_no_source_conflicts_correct_empty_union_not_admission(self):
        ledger = self.progress({})
        result = self.run(ledger=ledger)
        self.assertEqual(result["conflict_scopes_checked"], 0)
        self.assertEqual(result["active_old_raw_rows_checked"], 0)
        self.assertEqual(len(result["prior_content_union_manifest_sha256"]), 64)
        self.assertFalse(result["financial_repair_authorized"])

    def test_04_missing_old_snapshot_directory_is_hard_block(self):
        ledger = self.progress()
        manifest = S.PRIOR.inspect(
            self.module, self.stock_root, ledger)["physical_snapshot_manifest_sha256"]
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_MISSING_OLD_SNAPSHOT_SCOPE"):
            self.run(ledger=ledger, manifest=manifest)

    def test_05_wrong_expected_ledger_sha_blocks_before_parquet(self):
        self.snapshot()
        ledger = self.progress()
        with self.assertRaisesRegex(
                S.PRIOR.SnapshotError, "PINNED_LEDGER_SHA_MISMATCH"):
            self.run(ledger="f"*64, manifest="f"*64)

    def test_06_wrong_expected_manifest_sha_blocks_arrow(self):
        self.snapshot()
        ledger = self.progress()
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_PINNED_SNAPSHOT_MANIFEST_SHA_MISMATCH"):
            self.run(ledger=ledger, manifest="f"*64)

    def test_07_missing_per_date_active_pin_blocks_content_promotion(self):
        path = self.snapshot(pin=False)
        ledger = self.progress()
        manifest = S.PRIOR.inspect(
            self.module, self.stock_root, ledger)["physical_snapshot_manifest_sha256"]
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_OLD_SNAPSHOT_ACTIVE_PIN_NOT_UNIQUE"):
            self.run(ledger=ledger, manifest=manifest)
        self.assertTrue(path.exists())

    def test_08_two_versions_same_day_fail_closed_even_with_valid_pin(self):
        path = self.snapshot(rows=[{"_index": "1", "amount": 10}])
        arrow = S.EXTRA.snapshot_table(
            self.day, self.code, self.table,
            [{"_index": "2", "amount": 15}])
        other = S.EXTRA._snapshot_path(
            self.extra, "financial/"+self.table+"/"+self.code,
            self.day, arrow)
        pq.write_table(arrow, other, compression="zstd")
        self.assertNotEqual(path.name, other.name)
        ledger = self.progress()
        manifest = S.PRIOR.inspect(
            self.module, self.stock_root, ledger)["physical_snapshot_manifest_sha256"]
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_OLD_SNAPSHOT_ACTIVE_PIN_NOT_UNIQUE"):
            self.run(ledger=ledger, manifest=manifest)

    def test_09_arrow_schema_must_match_original_raw_schema(self):
        arrow = pa.Table.from_pylist([{"different": "schema"}])
        self.snapshot(arrow=arrow)
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_ARROW_SCHEMA_MISMATCH"):
            self.run()

    def test_10_snapshot_wrong_symbol_fails_original_row_identity(self):
        arrow = S.EXTRA.snapshot_table(
            self.day, "600000.SH", self.table,
            [{"_index": "1", "amount": 10}])
        self.snapshot(arrow=arrow)
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_ORIGINAL_ROW_AND_FILENAME_PROOF_FAILED"):
            self.run()

    def test_11_snapshot_canonical_filename_fingerprint_required(self):
        self.snapshot(force_name="2026-11-23-"+("a"*16)+".parquet")
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_ORIGINAL_ROW_AND_FILENAME_PROOF_FAILED"):
            self.run()

    def test_12_invalid_payload_json_fails_after_row_metadata(self):
        arrow = S.EXTRA.snapshot_table(self.day, self.code, self.table,
                                       [{"_index": "1"}])
        raw = arrow.to_pylist()
        raw[0]["payload_json"] = "{not-json"
        arrow = pa.Table.from_pylist(raw, schema=S.EXTRA.RAW_SCHEMA)
        self.snapshot(arrow=arrow)
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_PAYLOAD_INVALID_JSON"):
            self.run()

    def test_13_payload_needs_original_index_field(self):
        self.snapshot(rows=[{"value": 10}])
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_PAYLOAD_ROW_INDEX_INVALID"):
            self.run()

    def test_14_duplicate_payload_keys_fail_closed(self):
        raw = S.EXTRA.snapshot_table(self.day, self.code, self.table,
                                     [{"_index": "1", "amount": 10}]).to_pylist()
        raw[0]["payload_json"] = '{"_index":"1","amount":10,"amount":11}'
        arrow = pa.Table.from_pylist(raw, schema=S.EXTRA.RAW_SCHEMA)
        self.snapshot(arrow=arrow)
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_PAYLOAD_INVALID_JSON"):
            self.run()

    def test_15_nonfinite_json_constant_rejected(self):
        raw = S.EXTRA.snapshot_table(self.day, self.code, self.table,
                                     [{"_index": "1", "amount": 10}]).to_pylist()
        raw[0]["payload_json"] = '{"_index":"1","amount":NaN}'
        arrow = pa.Table.from_pylist(raw, schema=S.EXTRA.RAW_SCHEMA)
        self.snapshot(arrow=arrow)
        with self.assertRaisesRegex(
                S.ContentError, "PRIOR_FINANCE_NON_FINITE_JSON_LITERAL"):
            self.run()

    def test_16_small_pretend_byte_budget_refuses_instead_of_skipping(self):
        self.snapshot()
        with mock.patch.object(S, "MAX_TOTAL_ROWS", 0):
            with self.assertRaisesRegex(
                    S.ContentError, "PRIOR_FINANCE_TOTAL_ARROW_BUDGET"):
                self.run()

    def test_17_single_parquet_row_budget_checked_before_decode(self):
        self.snapshot()
        with mock.patch.object(S, "MAX_SNAPSHOT_ROWS", 0):
            with self.assertRaisesRegex(
                    S.ContentError, "PRIOR_FINANCE_SNAPSHOT_ROW_LIMIT"):
                self.run()

    def test_18_saved_metadata_read_drift_fails_closed(self):
        self.snapshot()
        ledger = self.progress()
        manifest = S.PRIOR.inspect(
            self.module, self.stock_root, ledger)["physical_snapshot_manifest_sha256"]
        with mock.patch.object(S, "_read_old_selected",
                               side_effect=lambda *a: ([], 0, 0, 0)):
            with self.assertRaisesRegex(
                    S.ContentError, "PRIOR_FINANCE_METADATA_DRIFT"):
                self.run(ledger=ledger, manifest=manifest)

    def test_19_postflight_manifest_change_refused(self):
        self.snapshot()
        ledger = self.progress()
        old = S.PRIOR.inspect(self.module, self.stock_root, ledger)
        changed = dict(old)
        changed["physical_snapshot_manifest_sha256"] = "f"*64
        with mock.patch.object(S.PRIOR, "inspect",
                               side_effect=[old, changed]):
            with self.assertRaisesRegex(
                    S.ContentError,
                    "PRIOR_FINANCE_PINNED_SNAPSHOT_PHYSICAL_MANIFEST_CHANGED"):
                self.run(ledger=ledger,
                         manifest=old["physical_snapshot_manifest_sha256"])

    def test_20_cli_error_hides_user_paths(self):
        stream = StringIO()
        with mock.patch.object(S, "inspect",
                               side_effect=RuntimeError("D:/secret/financial")):
            with contextlib.redirect_stdout(stream):
                code = S.main(["--module-root", str(self.module),
                               "--stock-root", str(self.stock_root),
                               "--expected-ledger-sha256", "f"*64,
                               "--expected-snapshot-manifest-sha256", "f"*64])
        self.assertEqual(code, 3)
        self.assertIn("PRIOR_FINANCE_RAW_CONTENT_READONLY_REVIEW_REQUIRED",
                      stream.getvalue())
        self.assertNotIn("D:/secret", stream.getvalue())

    def test_21_no_qmt_or_writer_or_receipt_bypass_paths(self):
        source = introspect.getsource(S)
        for forbidden in ("download_history_data(", "get_market_data_ex(",
                          "write_table(", "write_bytes(", "mkdir(", "unlink(",
                          "os.replace(", "rename(", "GAP.verify_original(",
                          "AUDIT.audit("):
            self.assertNotIn(forbidden, source)
        self.assertFalse(S.MAX_TOTAL_ROWS > 1000000)
        self.assertFalse(S.MAX_TOTAL_UNCOMPRESSED > 256*1024*1024)
        self.assertEqual(S.STATUS,
                         "VERIFIED_STORED_PRIOR_RAW_ROWS_ONLY_FRESH_SOURCE_NOT_CHECKED")


if __name__ == "__main__":
    unittest.main()
