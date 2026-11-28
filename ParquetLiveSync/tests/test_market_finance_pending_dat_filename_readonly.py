"""Synthetic offline-only financial Finance/DAT filename pending census tests."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_finance_pending_dat_filename_readonly as S


class FinancePendingDATFilenameTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        t = Path(self.temp.name)
        self.module = t / "module"
        self.work = self.module / "work" / "qmt_extra"
        self.work.mkdir(parents=True)
        self.stock_root = t / "stock"
        self.extra = self.stock_root / "AllCycleAStockData" / "qmt_extra"
        self.extra.mkdir(parents=True)
        for period in S.LEDGER.EXTRA.L.PERIODS:
            (self.extra.parent / period).mkdir()
        self.finance_root = t / "Finance"
        self.finance_root.mkdir()
        self.dat = self.finance_root / "SZ" / "86400"
        self.dat.mkdir(parents=True)
        self.original = "000001.SZ"

    def ledger(self, pending=None):
        if pending is None:
            pending = {self.original: {
                "reason": "SOURCE_HISTORY_CONFLICT",
                "asof": "2026-11-25", "attempts": 1}}
        obj = {"format": S.LEDGER.CACHE.FORMAT,
               "root": str(self.extra.resolve()),
               "import_cursor": "920992.BJ",
               "daily_cursor": "002639.SZ",
               "daily_date": "2026-11-25",
               "daily_sweep_reached_end": False,
               "pending": pending}
        raw = json.dumps(obj, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
        (self.work / S.TRIAGE.NAME).write_bytes(raw)
        return sha256(raw).hexdigest()

    def name(self, name="000001_7000.DAT", data=b"unread private DAT bytes"):
        path = self.dat / name
        path.write_bytes(data)
        return path

    def inspect(self, ledger=None):
        return S.inspect(self.module, self.stock_root,
                         self.finance_root, ledger or self.ledger())

    def test_01_no_files_never_claims_finance_data_complete(self):
        result = self.inspect()
        self.assertEqual(result["matching_pending_file_names"], 0)
        self.assertEqual(result["saved_pending_stock_count"], 1)
        self.assertEqual(result["by_reason"]["SOURCE_HISTORY_CONFLICT"]
                         ["stocks_with_no_matching_filename"], 1)
        self.assertFalse(result["fresh_finance_original_rows_available"])
        self.assertFalse(result["source_financial_nine_table_coverage_certified"])
        self.assertFalse(result["financial_repair_authorized"])

    def test_02_one_matching_nonempty_DAT_filename_is_only_metadata(self):
        path = self.name()
        out = self.inspect()
        self.assertEqual(out["matching_pending_file_names"], 1)
        reason = out["by_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(reason["stocks_with_matching_filename"], 1)
        self.assertEqual(reason["stocks_with_nonempty_filename"], 1)
        self.assertEqual(reason["observed_file_bytes"], path.stat().st_size)
        self.assertFalse(out["finance_dat_contents_read"])
        self.assertFalse(out["finance_dat_file_sha256_verified"])

    def test_03_two_pending_reasons_are_never_conflated(self):
        self.name()
        self.name("000002_7001.DAT", b"another")
        pending = {
            "000001.SZ": {"reason": "SOURCE_HISTORY_CONFLICT", "attempts": 1},
            "000002.SZ": {"reason": "CACHE_DECODE_ERROR", "attempts": 5}}
        out = self.inspect(self.ledger(pending))
        self.assertEqual(out["saved_pending_stock_count"], 2)
        self.assertEqual(out["by_reason"]["SOURCE_HISTORY_CONFLICT"]
                         ["matched_file_names"], 1)
        self.assertEqual(out["by_reason"]["CACHE_DECODE_ERROR"]
                         ["matched_file_names"], 1)
        self.assertFalse(out["financial_pending_resolved"])

    def test_04_case_insensitive_dat_suffix_is_scoped(self):
        self.name("000001_7000.dat")
        out = self.inspect()
        self.assertEqual(out["matching_pending_file_names"], 1)

    def test_05_missing_exchange_trees_reported_not_created(self):
        out = self.inspect()
        self.assertFalse(out["market_directories"]["SH"]["present"])
        self.assertFalse(out["market_directories"]["BJ"]["present"])
        self.assertFalse((self.finance_root / "SH").exists())

    def test_06_unrelated_stock_DAT_name_never_treated_as_pending(self):
        self.name("600000_7000.DAT")
        out = self.inspect()
        self.assertEqual(out["matching_pending_file_names"], 0)
        self.assertEqual(out["direct_directory_entries_seen"], 1)
        self.assertNotIn("600000", json.dumps(out))

    def test_07_malformed_or_nonfinancial_filename_is_ignored(self):
        self.name("000001_6000.DAT")
        self.name("000001_7000.parquet")
        self.name("000001_7AA0.DAT")
        out = self.inspect()
        self.assertEqual(out["matching_pending_file_names"], 0)
        self.assertEqual(out["direct_directory_entries_seen"], 3)

    def test_08_zero_byte_cache_file_is_not_nonempty_evidence(self):
        self.name(data=b"")
        out = self.inspect()
        c = out["by_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["stocks_only_zero_byte_files"], 1)
        self.assertEqual(c["nonempty_file_names"], 0)
        self.assertEqual(c["zero_byte_file_names"], 1)

    def test_09_multiple_matching_files_for_one_pending_stock(self):
        self.name("000001_7000.DAT", b"a")
        self.name("000001_7999.DAT", b"bc")
        out = self.inspect()
        c = out["by_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["stocks_with_matching_filename"], 1)
        self.assertEqual(c["matched_file_names"], 2)
        self.assertEqual(c["observed_file_bytes"], 3)

    def test_10_symlink_to_pending_file_is_denied_when_supported(self):
        target = self.name("000001_7000.DAT")
        linked = self.dat / "000001_7001.DAT"
        try:
            linked.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable on this user account")
        with self.assertRaisesRegex(S.DATError,
                                    "FINANCE_DAT_SCOPED_SYMLINK"):
            self.inspect()

    def test_11_market_root_symlink_blocked_if_supported(self):
        origin = self.dat
        linked = self.finance_root / "SH"
        try:
            linked.symlink_to(origin.parent, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlink unavailable")
        with self.assertRaisesRegex(S.DATError,
                                    "FINANCE_DAT_DIRECTORY_SYMLINK"):
            self.inspect()

    def test_12_scoped_per_market_entry_limit_is_enforced(self):
        self.name()
        self.name("unrelated.txt")
        with mock.patch.object(S, "MAX_DIRECT_ENTRIES_PER_MARKET", 1):
            with self.assertRaisesRegex(S.DATError,
                                        "FINANCE_DAT_DIRECT_ENTRY_BUDGET_EXCEEDED"):
                self.inspect()

    def test_13_scoped_total_direct_entry_limit_is_enforced(self):
        self.name()
        self.name("other.bin")
        with mock.patch.object(S, "MAX_TOTAL_DIRECT_ENTRIES", 1):
            with self.assertRaisesRegex(S.DATError,
                                        "FINANCE_DAT_DIRECT_ENTRY_BUDGET_EXCEEDED"):
                self.inspect()

    def test_14_scoped_matching_file_limit_is_enforced(self):
        self.name()
        with mock.patch.object(S, "MAX_MATCHED_FILES", 0):
            with self.assertRaisesRegex(S.DATError,
                                        "FINANCE_DAT_MATCHED_FILE_BUDGET_EXCEEDED"):
                self.inspect()

    def test_15_saved_pending_ledger_pin_required_and_strict(self):
        self.name()
        self.ledger()
        with self.assertRaisesRegex(
                S.DATError, "FINANCE_DAT_LEDGER_SHA_CHANGED"):
            S.inspect(self.module, self.stock_root, self.finance_root,
                      "f"*64)
        with self.assertRaisesRegex(
                S.DATError, "FINANCE_DAT_EXPECTED_LEDGER_SHA_REQUIRED"):
            S.inspect(self.module, self.stock_root, self.finance_root,
                      "not-a-digest")

    def test_16_metadata_drift_between_two_scans_denied(self):
        self.name()
        real = S._scan
        calls = [0]

        def change(root, pending):
            calls[0] += 1
            if calls[0] == 2:
                self.name("000001_7001.DAT")
            return real(root, pending)

        with mock.patch.object(S, "_scan", side_effect=change):
            with self.assertRaisesRegex(
                    S.DATError, "FINANCE_DAT_METADATA_CHANGED_DURING_CENSUS"):
                self.inspect()

    def test_17_cli_failure_is_sanitized_no_private_dat_path(self):
        output = StringIO()
        with mock.patch.object(
                S, "inspect", side_effect=ValueError(
                    "D:/software/JHQMT/datadir/Finance/private-data")):
            with contextlib.redirect_stdout(output):
                code = S.main([
                    "--module-root", str(self.module),
                    "--stock-root", str(self.stock_root),
                    "--finance-dir", str(self.finance_root),
                    "--expected-ledger-sha256", "f"*64])
        self.assertEqual(code, 3)
        self.assertIn("FINANCE_PENDING_DAT_FILENAME_CENSUS_REVIEW_REQUIRED",
                      output.getvalue())
        self.assertNotIn("D:/software", output.getvalue())

    def test_18_no_provider_APIs_or_content_readers_or_unittest_shadowing(self):
        self.assertIs(type(self).run, unittest.TestCase.run)
        source = introspect.getsource(S)
        for forbidden in (
                "open(", ".read_bytes(", ".read_text(",
                "get_financial_data(", "download_financial_data",
                "download_history_data(", "get_market_data_ex(",
                "write_bytes(", "write_table(", ".mkdir(",
                "os.replace(", ".unlink(", ".rename(",
                "IMPORT._worker_batch(", "IMPORT._commit_symbol("):
            self.assertNotIn(forbidden, source)
        self.assertEqual(S.STATUS,
            "PENDING_FINANCE_DAT_FILENAME_PRESENCE_ONLY_FRESH_RAW_NOT_VERIFIED")


if __name__ == "__main__":
    unittest.main()
