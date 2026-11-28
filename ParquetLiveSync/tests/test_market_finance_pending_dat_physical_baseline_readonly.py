"""Offline contract tests: no real QMT, no native DAT, no data writes."""
from __future__ import annotations

import contextlib
from io import StringIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_finance_pending_dat_physical_baseline_readonly as G

A, B, C = "a" * 64, "b" * 64, "c" * 64


class PhysicalBaselineTests(unittest.TestCase):
    def setUp(self):
        self.reader_calls = []
        self.observed = {
            "format": "astock_finance_pending_dat_physical_sha_readonly_v1",
            "status": G.PHYSICAL_STATUS,
            "pinned_saved_financial_ledger_sha256": A,
            "pinned_P324_metadata_only_manifest_sha256": B,
            "physical_DAT_file_manifest_sha256": C,
            "physical_DAT_bytes_read_for_hashing_only": True,
            "qmt_download_calls": 0,
            "scoped_DAT_files_double_hashed": 616,
            "scoped_DAT_bytes_per_pass": 70748048,
            "total_DAT_content_bytes_read_two_passes": 141496096,
        }
        self.observed.update({k: False for k in G.DENIED})
        def reader(*args):
            self.reader_calls.append(args)
            return dict(self.observed)
        self.provider = SimpleNamespace(
            inspect=reader, MAX_SCOPED_FILES=2048,
            MAX_ALL_DAT_BYTES=256 * 1024 * 1024)
        patch = mock.patch.dict(sys.modules, {G.PHYSICAL_MODULE: self.provider})
        patch.start()
        self.addCleanup(patch.stop)

    def scan(self, a=A, b=B, c=C):
        return G.inspect("module", "stock", "finance", a, b, c)

    def test_01_matching_manifest_is_snapshot_only(self):
        out = self.scan()
        self.assertTrue(out["physical_baseline_match"])
        self.assertFalse(out["financial_pending_resolved"])
        self.assertFalse(out["physical_DAT_manifest_proves_provider_origin"])
        self.assertEqual(len(self.reader_calls), 1)
        self.assertEqual(self.reader_calls[0][-2:], (A, B))

    def test_02_mismatched_physical_digest_fails_closed(self):
        self.observed["physical_DAT_file_manifest_sha256"] = "d" * 64
        with self.assertRaisesRegex(G.BaselineError, "PHYSICAL_SHA_MISMATCH"):
            self.scan()

    def test_03_empty_physical_pin_rejected_before_any_file_access(self):
        with self.assertRaisesRegex(G.BaselineError, "PHYSICAL_SHA_REQUIRED"):
            self.scan(c="")
        self.assertEqual(self.reader_calls, [])

    def test_04_invalid_ledger_pin_rejected_before_any_file_access(self):
        with self.assertRaisesRegex(G.BaselineError, "LEDGER_SHA_REQUIRED"):
            self.scan(a="not-hex")
        self.assertEqual(self.reader_calls, [])

    def test_05_invalid_metadata_pin_rejected_before_any_file_access(self):
        with self.assertRaisesRegex(G.BaselineError, "METADATA_SHA_REQUIRED"):
            self.scan(b="0" * 63)
        self.assertEqual(self.reader_calls, [])

    def test_06_uppercase_pin_canonicalized(self):
        got = self.scan(a=A.upper(), b=B.upper(), c=C.upper())
        self.assertEqual(got["pinned_physical_DAT_file_manifest_sha256"], C)

    def test_07_changed_ledger_proof_refused(self):
        self.observed["pinned_saved_financial_ledger_sha256"] = "d" * 64
        with self.assertRaisesRegex(G.BaselineError, "PRIOR_PINS_CHANGED"):
            self.scan()

    def test_08_changed_metadata_proof_refused(self):
        self.observed["pinned_P324_metadata_only_manifest_sha256"] = "d" * 64
        with self.assertRaisesRegex(G.BaselineError, "PRIOR_PINS_CHANGED"):
            self.scan()

    def test_09_false_provider_cert_refused(self):
        self.observed["physical_DAT_manifest_proves_provider_origin"] = True
        with self.assertRaisesRegex(G.BaselineError, "AUTHORITY_FLAGS_INVALID"):
            self.scan()

    def test_10_qmt_download_refused(self):
        self.observed["qmt_download_calls"] = 1
        with self.assertRaisesRegex(G.BaselineError, "AUTHORITY_FLAGS_INVALID"):
            self.scan()

    def test_11_bad_total_byte_count_refused(self):
        self.observed["total_DAT_content_bytes_read_two_passes"] -= 1
        with self.assertRaisesRegex(G.BaselineError, "READ_COUNTS_INVALID"):
            self.scan()

    def test_12_unsupported_reader_status_refused(self):
        self.observed["status"] = "NOT_A_PROOF"
        with self.assertRaisesRegex(G.BaselineError, "READER_STATUS_INVALID"):
            self.scan()

    def test_13_error_cli_sanitizes_private_path(self):
        self.observed["physical_DAT_file_manifest_sha256"] = "d" * 64
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            code = G.main(["--module-root", "D:/private/source", "--stock-root", "D:/stock",
                           "--finance-dir", "D:/private/Finance", "--expected-ledger-sha256", A,
                           "--expected-dat-metadata-sha256", B,
                           "--expected-dat-physical-sha256", C])
        self.assertEqual(code, 3)
        self.assertNotIn("private", buf.getvalue())
        self.assertIn("REVIEW_REQUIRED", buf.getvalue())

    def test_14_cli_success_produces_only_group_proof(self):
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            code = G.main(["--module-root", "module", "--stock-root", "stock",
                           "--finance-dir", "finance", "--expected-ledger-sha256", A,
                           "--expected-dat-metadata-sha256", B,
                           "--expected-dat-physical-sha256", C])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(buf.getvalue())["physical_baseline_match"])
        self.assertNotIn("000001", buf.getvalue())

    def test_15_rejects_nonboolean_authority_flag(self):
        self.observed["financial_pending_resolved"] = 0
        with self.assertRaisesRegex(G.BaselineError, "AUTHORITY_FLAGS_INVALID"):
            self.scan()


class PhysicalBaselineIntegrationTests(unittest.TestCase):
    def test_16_real_P326_synthetic_double_hash_reconfirmed(self):
        try:
            from test_market_finance_pending_dat_physical_sha_readonly import (
                PendingDATPhysicalSHAOnlyTests as P326Fixture)
            import market_finance_pending_dat_physical_sha_readonly as P326
        except ImportError as exc:
            self.skipTest("P3.26/pyarrow integration unavailable: " + type(exc).__name__)
        fixture = P326Fixture(methodName="test_01_single_real_byte_hash_not_just_metadata")
        fixture.setUp()
        try:
            fixture.add(payload=b"native sample")
            ledger, metadata = fixture.pins()
            first = P326.inspect(fixture.module, fixture.stock_root,
                                  fixture.finance, ledger, metadata)
            expected = first["physical_DAT_file_manifest_sha256"]
            result = G.inspect(fixture.module, fixture.stock_root,
                               fixture.finance, ledger, metadata, expected)
            self.assertTrue(result["physical_baseline_match"])
            self.assertEqual(result["scoped_DAT_files_double_hashed"], 1)
        finally:
            fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
