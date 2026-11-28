"""Synthetic-only, read-only pending DAT filename profile and mtime tests."""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import inspect as introspect
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_finance_pending_dat_profile_readonly as S


class PendingDATProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.module = root / "module"
        self.work = self.module / "work" / "qmt_extra"
        self.work.mkdir(parents=True)
        self.stock_root = root / "stock"
        self.extra = self.stock_root / "AllCycleAStockData" / "qmt_extra"
        self.extra.mkdir(parents=True)
        for period in S.LEDGER.EXTRA.L.PERIODS:
            (self.extra.parent / period).mkdir()
        self.finance = root / "Finance"
        self.sz = self.finance / "SZ" / "86400"
        self.sz.mkdir(parents=True)
        self.sh = self.finance / "SH" / "86400"
        self.sh.mkdir(parents=True)
        self.code = "000001.SZ"

    def pending(self, stock, reason="SOURCE_HISTORY_CONFLICT"):
        return {
            "reason": reason, "attempts": 1, "asof": "2026-11-25",
        }

    def ledger(self, entries=None):
        if entries is None:
            entries = {self.code: self.pending(self.code)}
        obj = {
            "format": S.LEDGER.CACHE.FORMAT,
            "root": str(self.extra.resolve()),
            "import_cursor": "920992.BJ",
            "daily_cursor": "002639.SZ",
            "daily_date": "2026-11-25",
            "daily_sweep_reached_end": False,
            "pending": entries,
        }
        raw = json.dumps(obj, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
        (self.work / S.TRIAGE.NAME).write_bytes(raw)
        return sha256(raw).hexdigest()

    def add(self, code="000001.SZ", suffix=7000, data=b"a",
            mtime=None):
        folder = self.sh if code.endswith(".SH") else self.sz
        path = folder / (code[:6] + "_" + str(suffix) + ".DAT")
        path.write_bytes(data)
        if mtime is not None:
            ns = int(mtime.timestamp() * 10**9)
            os.utime(path, ns=(ns, ns))
        return path

    def eight(self, code="000001.SZ", first=7000):
        return [self.add(code, suffix=n)
                for n in range(first, first + 8)]

    def prepared(self, ledger=None):
        ledger = ledger or self.ledger()
        physical = S.DAT.inspect(
            self.module, self.stock_root, self.finance, ledger)
        return ledger, physical["metadata_only_manifest_sha256"]

    def run_scan(self, ledger=None, manifest=None):
        if manifest is None:
            ledger, manifest = self.prepared(ledger)
        return S.inspect(self.module, self.stock_root, self.finance,
                         ledger, manifest)

    def test_01_one_stock_exactly_eight_names_is_now_per_stock_proven(self):
        self.eight()
        out = self.run_scan()
        self.assertEqual(out["saved_pending_stocks"], 1)
        self.assertEqual(out["matching_DAT_filenames"], 8)
        c = out["by_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["stocks_with_exactly_8_names"], 1)
        self.assertEqual(c["stocks_with_8_positive_names"], 1)
        self.assertEqual(c["file_count_histogram_8"], 1)
        self.assertEqual(c["distinct_filename_suffix_sets"], 1)
        self.assertFalse(out["dat_content_bytes_read"])
        self.assertFalse(out["financial_pending_resolved"])

    def test_02_seven_and_nine_names_have_mean_eight_not_each_eight(self):
        for n in range(7000, 7007):
            self.add(suffix=n)
        for n in range(7000, 7009):
            self.add("000002.SZ", suffix=n)
        ledger = self.ledger({
            "000001.SZ": self.pending("000001.SZ"),
            "000002.SZ": self.pending("000002.SZ")})
        out = self.run_scan(ledger)
        c = out["by_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(out["matching_DAT_filenames"], 16)
        self.assertEqual(c["file_count_histogram_7"], 1)
        self.assertEqual(c["file_count_histogram_9"], 1)
        self.assertEqual(c["stocks_with_exactly_8_names"], 0)
        self.assertEqual(c["stocks_with_non_8_count"], 2)

    def test_03_eight_each_but_different_suffix_sets_are_reported(self):
        self.eight()
        self.eight("000002.SZ", first=7001)
        ledger = self.ledger({
            "000001.SZ": self.pending("000001.SZ"),
            "000002.SZ": self.pending("000002.SZ")})
        c = self.run_scan(ledger)["by_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["stocks_with_exactly_8_names"], 2)
        self.assertEqual(c["distinct_filename_suffix_sets"], 2)
        self.assertEqual(c["largest_shared_suffix_set_stock_count"], 1)

    def test_04_equal_suffix_sets_are_detected_without_table_claim(self):
        self.eight()
        self.eight("000002.SZ")
        ledger = self.ledger({
            "000001.SZ": self.pending("000001.SZ"),
            "000002.SZ": self.pending("000002.SZ")})
        out = self.run_scan(ledger)
        c = out["by_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["distinct_filename_suffix_sets"], 1)
        self.assertEqual(c["largest_shared_suffix_set_stock_count"], 2)
        self.assertTrue(out["filename_suffixes_not_financial_table_proof"])

    def test_05_zero_byte_file_is_a_name_not_a_full_cache_table(self):
        self.add(data=b"")
        out = self.run_scan()
        c = out["by_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["matching_file_names"], 1)
        self.assertEqual(c["positive_file_count_histogram_0"], 1)
        self.assertEqual(c["zero_byte_file_names"], 1)
        self.assertFalse(out["financial_nine_table_completeness_certified"])

    def test_06_empty_directories_do_not_mean_missing_finance_data(self):
        out = self.run_scan()
        c = out["by_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["file_count_histogram_0"], 1)
        self.assertEqual(out["matching_DAT_filenames"], 0)
        self.assertFalse(out["new_finance_raw_rows_read"])

    def test_07_history_conflict_and_decode_exception_stay_separate(self):
        self.eight()
        self.add("600001.SH", 7000, b"exception")
        ledger = self.ledger({
            "000001.SZ": self.pending("000001.SZ"),
            "600001.SH": self.pending("600001.SH", "CACHE_DECODE_ERROR")})
        out = self.run_scan(ledger)
        self.assertEqual(out["by_pending_reason"]
                         ["SOURCE_HISTORY_CONFLICT"]["file_count_histogram_8"], 1)
        self.assertEqual(out["by_pending_reason"]
                         ["CACHE_DECODE_ERROR"]["file_count_histogram_1"], 1)
        self.assertFalse(out["fresh_vs_old_finance_compared"])

    def test_08_UTC_month_histogram_is_filesystem_time_only(self):
        oct_day = datetime(2026, 10, 2, tzinfo=timezone.utc)
        nov_day = datetime(2026, 11, 25, tzinfo=timezone.utc)
        self.add(suffix=7000, mtime=oct_day)
        self.add(suffix=7001, mtime=nov_day)
        out = self.run_scan()
        self.assertEqual(out["filesystem_mtime_utc_month_filename_counts"],
                         {"2026-10": 1, "2026-11": 1})
        self.assertTrue(out["filesystem_mtime_not_financial_report_date"])
        c = out["by_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["stock_metadata_mtime_spread_over_7d"], 1)

    def test_09_small_metadata_mtime_spread_under_24_hours(self):
        base = datetime(2026, 11, 1, tzinfo=timezone.utc)
        ns = int(base.timestamp() * 10**9)
        a = self.add(suffix=7000)
        b = self.add(suffix=7001)
        os.utime(a, ns=(ns, ns))
        os.utime(b, ns=(ns + 3600 * 10**9, ns + 3600 * 10**9))
        c = self.run_scan()["by_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["stock_metadata_mtime_spread_within_1d"], 1)

    def test_10_medium_metadata_mtime_spread_under_seven_days(self):
        base = datetime(2026, 11, 1, tzinfo=timezone.utc)
        ns = int(base.timestamp() * 10**9)
        a = self.add(suffix=7000)
        b = self.add(suffix=7001)
        os.utime(a, ns=(ns, ns))
        os.utime(b, ns=(ns + 3 * S.DAY_NS, ns + 3 * S.DAY_NS))
        c = self.run_scan()["by_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["stock_metadata_mtime_spread_within_7d"], 1)

    def test_11_equal_file_metadata_mtime_is_zero_skew(self):
        a = self.add(suffix=7000)
        b = self.add(suffix=7001)
        ns = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()*10**9)
        for f in (a, b):
            os.utime(f, ns=(ns, ns))
        c = self.run_scan()["by_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
        self.assertEqual(c["stock_metadata_mtime_spread_0d"], 1)

    def test_12_wrong_saved_ledger_sha_blocks_profile(self):
        self.eight()
        self.ledger()
        with self.assertRaisesRegex(
                S.DAT.DATError, "FINANCE_DAT_LEDGER_SHA_CHANGED"):
            S.inspect(self.module, self.stock_root, self.finance,
                      "f"*64, "f"*64)

    def test_13_wrong_p324_metadata_sha_blocks_profile(self):
        self.eight()
        ledger = self.ledger()
        with self.assertRaisesRegex(
                S.ProfileError, "FINANCE_DAT_PROFILE_OLD_METADATA_MANIFEST_MISMATCH"):
            S.inspect(self.module, self.stock_root, self.finance,
                      ledger, "f"*64)

    def test_14_metadata_drift_between_scan_and_collect_blocks(self):
        self.add(suffix=7000)
        ledger, manifest = self.prepared()
        def mutate(root, pending):
            self.add(suffix=7001)
            return {}, [], "f"*64, 2
        with mock.patch.object(S, "_collect", side_effect=mutate):
            with self.assertRaisesRegex(
                    S.ProfileError,
                    "FINANCE_DAT_PROFILE_COLLECTED_METADATA_DIFFERS_FROM_P324"):
                S.inspect(self.module, self.stock_root, self.finance,
                          ledger, manifest)

    def test_15_postflight_metadata_drift_blocks_success(self):
        self.add()
        ledger, manifest = self.prepared()
        original = S.DAT.inspect
        calls = [0]
        def spoof(*args):
            calls[0] += 1
            value = original(*args)
            if calls[0] == 2:
                value = dict(value)
                value["matching_pending_file_names"] = 123
            return value
        with mock.patch.object(S.DAT, "inspect", side_effect=spoof):
            with self.assertRaisesRegex(
                    S.ProfileError,
                    "FINANCE_DAT_PROFILE_POSTFLIGHT_METADATA_CHANGED"):
                S.inspect(self.module, self.stock_root, self.finance,
                          ledger, manifest)

    def test_16_scoped_link_is_denied_when_supported(self):
        target = self.add(suffix=7000)
        alias = self.sz / "000001_7001.DAT"
        try:
            alias.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink not permitted on this machine")
        with self.assertRaises(S.DAT.DATError):
            self.run_scan()

    def test_17_cli_error_is_sanitized_without_private_cache_path(self):
        output = StringIO()
        with mock.patch.object(
                S, "inspect", side_effect=ValueError(
                    "D:/software/JHQMT/datadir/Finance/private-records")):
            with contextlib.redirect_stdout(output):
                rc = S.main([
                    "--module-root", str(self.module),
                    "--stock-root", str(self.stock_root),
                    "--finance-dir", str(self.finance),
                    "--expected-ledger-sha256", "f"*64,
                    "--expected-dat-metadata-sha256", "f"*64])
        self.assertEqual(rc, 3)
        self.assertIn("PINNED_PENDING_DAT_FILENAME_PROFILE_READONLY_REVIEW_REQUIRED",
                      output.getvalue())
        self.assertNotIn("D:/software", output.getvalue())

    def test_18_no_DAT_reads_QMT_downloads_writer_or_unittest_runner_shadow(self):
        self.assertIs(type(self).run, unittest.TestCase.run)
        code = introspect.getsource(S)
        for forbidden in (
                ".read_bytes(", ".read_text(", ".open(", "open(",
                "xtquant", "get_financial_data(", "download_financial_data",
                "download_history_data(", "get_market_data_ex(",
                ".write_bytes(", "write_table(", ".mkdir(",
                "os.replace(", ".unlink(", ".rename(",
                "IMPORT._worker_batch(", "IMPORT._commit_symbol("):
            self.assertNotIn(forbidden, code)
        self.assertEqual(S.STATUS,
            "PINNED_PENDING_DAT_FILENAME_PROFILE_ONLY_NO_FRESH_FINANCE_CONTENT")


if __name__ == "__main__":
    unittest.main()
