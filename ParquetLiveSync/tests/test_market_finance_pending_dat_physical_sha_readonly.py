"""Synthetic physical byte hashing, no-QMT read-only pending Finance DAT audit."""
from __future__ import annotations

import contextlib
from hashlib import sha256
from io import StringIO
import inspect as introspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_finance_pending_dat_physical_sha_readonly as S


class PendingDATPhysicalSHAOnlyTests(unittest.TestCase):
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
        self.finance = t / "Finance"
        self.sz = self.finance / "SZ" / "86400"
        self.sh = self.finance / "SH" / "86400"
        self.sz.mkdir(parents=True)
        self.sh.mkdir(parents=True)
        self.stock = "000001.SZ"

    def pending(self, reason="SOURCE_HISTORY_CONFLICT"):
        return {"reason": reason, "attempts": 1, "asof": "2026-11-25"}

    def ledger(self, items=None):
        if items is None:
            items = {self.stock: self.pending()}
        obj = {
            "format": S.LEDGER.CACHE.FORMAT,
            "root": str(self.extra.resolve()),
            "import_cursor": "920992.BJ",
            "daily_cursor": "002639.SZ",
            "daily_date": "2026-11-25",
            "daily_sweep_reached_end": False,
            "pending": items
        }
        payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        (self.work / S.TRIAGE.NAME).write_bytes(payload)
        return sha256(payload).hexdigest()

    def add(self, name="000001_7000.DAT", payload=b"first local native file",
            market="SZ"):
        d = self.sz if market == "SZ" else self.sh
        path = d / name
        path.write_bytes(payload)
        return path

    def pins(self, ledger=None):
        ledger = ledger or self.ledger()
        saved = S.DAT.inspect(self.module, self.stock_root,
                              self.finance, ledger)
        return ledger, saved["metadata_only_manifest_sha256"]

    def run_scan(self, ledger=None, meta=None):
        if meta is None:
            ledger, meta = self.pins(ledger)
        return S.inspect(self.module, self.stock_root, self.finance,
                         ledger, meta)

    def test_01_single_real_byte_hash_not_just_metadata(self):
        p = self.add()
        out = self.run_scan()
        self.assertEqual(out["scoped_DAT_files_double_hashed"], 1)
        self.assertEqual(out["scoped_DAT_bytes_per_pass"], p.stat().st_size)
        self.assertEqual(out["total_DAT_content_bytes_read_two_passes"],
                         2 * p.stat().st_size)
        self.assertTrue(out["physical_DAT_bytes_read_for_hashing_only"])
        self.assertFalse(out["raw_DAT_format_decoded"])
        self.assertFalse(out["physical_DAT_manifest_proves_provider_origin"])
        self.assertFalse(out["financial_pending_resolved"])
        self.assertEqual(len(out["physical_DAT_file_manifest_sha256"]), 64)

    def test_02_both_reasons_keep_separate_source_counts(self):
        self.add(payload=b"abc")
        self.add("600001_7001.DAT", b"Z"*7, market="SH")
        ledger = self.ledger({
            self.stock: self.pending(),
            "600001.SH": self.pending("CACHE_DECODE_ERROR")
        })
        out = self.run_scan(ledger)
        self.assertEqual(out["saved_pending_stocks"], 2)
        self.assertEqual(out["scoped_DAT_bytes_per_pass"], 10)
        self.assertEqual(out["per_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
                         ["DAT_file_bytes_per_read_pass"], 3)
        self.assertEqual(out["per_pending_reason"]["CACHE_DECODE_ERROR"]
                         ["DAT_file_bytes_per_read_pass"], 7)

    def test_03_canonical_physical_manifest_changes_on_bytes_not_size(self):
        p = self.add(payload=b"aaaa")
        old = self.run_scan()
        st = p.stat()
        p.write_bytes(b"bbbb")
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
        revised = self.run_scan()
        self.assertEqual(
            old["pinned_P324_metadata_only_manifest_sha256"],
            revised["pinned_P324_metadata_only_manifest_sha256"])
        self.assertNotEqual(old["physical_DAT_file_manifest_sha256"],
                            revised["physical_DAT_file_manifest_sha256"])
        self.assertEqual(old["scoped_DAT_bytes_per_pass"], 4)
        self.assertEqual(revised["scoped_DAT_bytes_per_pass"], 4)

    def test_04_zero_byte_DAT_is_hashed_not_called_source_rows(self):
        self.add(payload=b"")
        out = self.run_scan()
        self.assertEqual(out["scoped_DAT_bytes_per_pass"], 0)
        self.assertEqual(out["total_DAT_content_bytes_read_two_passes"], 0)
        self.assertEqual(out["per_pending_reason"]["SOURCE_HISTORY_CONFLICT"]
                         ["zero_byte_DAT_files"], 1)
        self.assertFalse(out["fresh_finance_raw_rows_authenticated"])

    def test_05_no_DAT_preserves_pending_reason_bucket(self):
        out = self.run_scan()
        self.assertEqual(out["saved_pending_stocks"], 1)
        self.assertEqual(out["scoped_DAT_files_double_hashed"], 0)
        self.assertEqual(out["per_pending_reason"],
                         {"SOURCE_HISTORY_CONFLICT": {}})
        self.assertFalse(out["financial_repair_authorized"])

    def test_06_unrelated_stock_DAT_bytes_are_never_opened(self):
        foreign = self.add("000002_7001.DAT", b"unrelated")
        original = S._hash_two_passes
        def guard(path, metadata):
            self.assertNotEqual(Path(path).resolve(), foreign.resolve())
            return original(path, metadata)
        with mock.patch.object(S, "_hash_two_passes", side_effect=guard):
            out = self.run_scan()
        self.assertEqual(out["scoped_DAT_files_double_hashed"], 0)

    def test_07_nonfinancial_DAT_suffix_is_never_opened(self):
        self.add("000001_6001.DAT", b"not finance pending")
        self.add("000001_7001.txt", b"not DAT")
        with mock.patch.object(S, "_hash_two_passes",
                               side_effect=AssertionError("wrong path")):
            out = self.run_scan()
        self.assertEqual(out["scoped_DAT_files_double_hashed"], 0)

    def test_08_bad_ledger_pin_blocks_byte_read(self):
        self.add()
        self.ledger()
        with mock.patch.object(S, "_hash_two_passes",
                               side_effect=AssertionError("should not read")):
            with self.assertRaises(S.DAT.DATError):
                S.inspect(self.module, self.stock_root, self.finance,
                          "f"*64, "f"*64)

    def test_09_bad_metadata_manifest_pin_blocks_byte_read(self):
        self.add()
        ledger = self.ledger()
        with mock.patch.object(S, "_hash_two_passes",
                               side_effect=AssertionError("should not read")):
            with self.assertRaisesRegex(
                    S.PROFILE.ProfileError,
                    "FINANCE_DAT_PROFILE_OLD_METADATA_MANIFEST_MISMATCH"):
                S.inspect(self.module, self.stock_root, self.finance,
                          ledger, "f"*64)

    def test_10_per_file_physical_read_size_limit_before_bytes(self):
        self.add(payload=b"test")
        with mock.patch.object(S, "MAX_SINGLE_DAT_BYTES", 1):
            with self.assertRaisesRegex(
                    S.PhysicalError,
                    "FINANCE_DAT_SINGLE_PHYSICAL_READ_BUDGET"):
                self.run_scan()

    def test_11_total_physical_budget_checked_before_open(self):
        self.add(payload=b"test")
        with mock.patch.object(S, "MAX_ALL_DAT_BYTES", 1):
            with self.assertRaisesRegex(
                    S.PhysicalError,
                    "FINANCE_DAT_TOTAL_PHYSICAL_READ_BUDGET"):
                self.run_scan()

    def test_12_fewer_allowed_scoped_files_fail_closed(self):
        self.add(payload=b"a")
        with mock.patch.object(S, "MAX_SCOPED_FILES", 0):
            with self.assertRaisesRegex(
                    S.PhysicalError,
                    "FINANCE_DAT_PHYSICAL_SCOPED_FILE_BUDGET"):
                self.run_scan()

    def test_13_symlink_pending_file_rejected_when_supported(self):
        target = self.add()
        link = self.sz / "000001_7001.DAT"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable for this user")
        with self.assertRaises(S.DAT.DATError):
            self.run_scan()

    def test_14_same_length_changed_bytes_during_two_reads_denied(self):
        p = self.add(payload=b"aaaa")
        original = S._hash_once
        calls = [0]
        def change(path, identity):
            value = original(path, identity)
            calls[0] += 1
            if calls[0] == 1:
                previous = p.stat()
                p.write_bytes(b"bbbb")
                os.utime(p, ns=(previous.st_atime_ns, previous.st_mtime_ns))
            return value
        with mock.patch.object(S, "_hash_once", side_effect=change):
            with self.assertRaisesRegex(
                    S.PhysicalError,
                    "FINANCE_DAT_PHYSICAL_TWO_READS_DIFFER"):
                self.run_scan()

    def test_15_metadata_drift_before_read_denied(self):
        self.add()
        ledger, meta = self.pins()
        with mock.patch.object(S, "_read_scoped",
                               side_effect=S.PhysicalError(
                                   "FINANCE_DAT_PHYSICAL_METADATA_MANIFEST_DIFFERS")):
            with self.assertRaisesRegex(
                    S.PhysicalError,
                    "FINANCE_DAT_PHYSICAL_METADATA_MANIFEST_DIFFERS"):
                S.inspect(self.module, self.stock_root, self.finance,
                          ledger, meta)

    def test_16_postflight_metadata_drift_denied(self):
        self.add()
        ledger, meta = self.pins()
        original = S.PROFILE.inspect
        calls = [0]
        def changed(*args):
            calls[0] += 1
            result = original(*args)
            if calls[0] == 2:
                result = dict(result)
                result["matching_DAT_filenames"] = -1
            return result
        with mock.patch.object(S.PROFILE, "inspect", side_effect=changed):
            with self.assertRaisesRegex(
                    S.PhysicalError,
                    "FINANCE_DAT_PHYSICAL_POSTFLIGHT_METADATA_CHANGED"):
                S.inspect(self.module, self.stock_root, self.finance,
                          ledger, meta)

    def test_17_error_cli_does_not_leak_DAT_paths_or_raw_bytes(self):
        output = StringIO()
        with mock.patch.object(
                S, "inspect", side_effect=OSError(
                    "D:/software/JHQMT/datadir/Finance/000001_private")):
            with contextlib.redirect_stdout(output):
                status = S.main([
                    "--module-root", str(self.module),
                    "--stock-root", str(self.stock_root),
                    "--finance-dir", str(self.finance),
                    "--expected-ledger-sha256", "f"*64,
                    "--expected-dat-metadata-sha256", "f"*64])
        self.assertEqual(status, 3)
        self.assertIn("PENDING_DAT_PHYSICAL_SHA_READONLY_REVIEW_REQUIRED",
                      output.getvalue())
        self.assertNotIn("D:/software", output.getvalue())

    def test_18_no_DAT_decode_QMT_download_writer_or_unittest_shadow(self):
        self.assertIs(type(self).run, unittest.TestCase.run)
        code = introspect.getsource(S)
        for forbidden in (
                "get_financial_data(", "download_financial_data",
                "get_market_data_ex(", "download_history_data(",
                ".write_bytes(", "write_table(", ".mkdir(", ".unlink(",
                ".rename(", "os.replace(", "xtquant",
                "json.loads(", "pandas.read_", "pq.read_table("):
            self.assertNotIn(forbidden, code)
        self.assertEqual(S.STATUS,
            "PENDING_FINANCE_DAT_LOCAL_PHYSICAL_BYTES_VERIFIED_NO_SOURCE_DECODE")


    def test_19_windows_crt_fstat_zero_ino_still_matches_kernel_handles(self):
        self.add(payload=b"existing four bytes")
        original_fstat = os.fstat

        def crt_style(fd):
            info = original_fstat(fd)
            return SimpleNamespace(
                st_mode=info.st_mode, st_dev=0, st_ino=0,
                st_size=info.st_size, st_mtime_ns=info.st_mtime_ns)

        def stable_kernel_id(fd):
            info = original_fstat(fd)
            return info.st_dev, info.st_ino

        with mock.patch.object(S, "_is_windows", return_value=True):
            with mock.patch.object(S.os, "fstat", side_effect=crt_style):
                with mock.patch.object(S, "_windows_handle_id",
                                       side_effect=stable_kernel_id):
                    out = self.run_scan()
        self.assertEqual(out["scoped_DAT_files_double_hashed"], 1)
        self.assertEqual(out["total_DAT_content_bytes_read_two_passes"], 38)

    def test_20_windows_different_kernel_handles_fail_closed(self):
        self.add(payload=b"aaaa")
        ids = iter(((55, 100), (55, 101)))
        with mock.patch.object(S, "_is_windows", return_value=True):
            with mock.patch.object(S, "_windows_handle_id",
                                   side_effect=lambda fd: next(ids)):
                with self.assertRaisesRegex(
                        S.PhysicalError,
                        "FINANCE_DAT_FILE_IDENTITY_CHANGED_BEFORE_READ"):
                    self.run_scan()


if __name__ == "__main__":
    unittest.main()
