"""P4 synthetic bounded original snapshot integrity, without QMT calls."""
from __future__ import annotations

from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import market_center_finance_pending_snapshot_integrity as I
import market_center_finance_pending_snapshot_review as P3
import qmt_extra_data as E
import pyarrow.parquet as pq

STOCK = "000001.SZ"
DAY = "2026-11-18"


def fixture(root, *, pin=False):
    module = root / "ParquetLiveSync"
    ledger = module / "work" / "qmt_extra" / "financial-cache-progress.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({
        "format": "qmt_financial_cache_import_v1",
        "daily_date": "2026-11-21", "daily_cursor": "001266.SZ",
        "pending": {
            STOCK: {"reason": "SOURCE_HISTORY_CONFLICT",
                    "asof": "2026-11-21", "attempts": 1,
                    "detail": "SOURCE_HISTORY_CONFLICT " + STOCK
                              + " table=Capital "
                              + "scoped_m_quarter_proof=REPORT_KEYS_ADDED_OR_REMOVED"}
        },
    }), encoding="utf-8")
    market = root / "AllCycleAStockData"
    extra = market / "qmt_extra"
    records = [{"_index": "0", "m_timetag": "20240930",
                "m_quarter": "2024Q3", "m_totalShare": 200}]
    arrow = E.snapshot_table(DAY, STOCK, "Capital", records)
    folder = extra / "financial" / "Capital" / STOCK / "snapshots"
    folder.mkdir(parents=True)
    path = E._snapshot_path(extra, "financial/Capital/" + STOCK, DAY, arrow)
    pq.write_table(arrow, path, compression="zstd")
    if pin:
        pins = folder.parent / "active"
        pins.mkdir()
        (pins / (DAY + ".json")).write_text(json.dumps({
            "format": "qmt_financial_active_v1", "symbol": STOCK,
            "table": "Capital", "asof": DAY,
            "filename": path.name, "sha256": sha256(path.read_bytes()).hexdigest(),
        }), encoding="utf-8")
    return module, market, ledger, path


class SnapshotIntegrityTests(unittest.TestCase):
    def _run(self, module, market, ledger):
        original = P3.review
        # Existing P3 uses wallclock, not a user-selected historical date.
        # Fixture paths are unique and its time guard is independent of asof.
        return I.verify(module, market, sha256(ledger.read_bytes()).hexdigest())

    def test_verified_content_addressed_snapshot_readonly_counts(self):
        with TemporaryDirectory() as tmp:
            module, market, ledger, path = fixture(Path(tmp))
            got = self._run(module, market, ledger)
            self.assertEqual(got["immutable_snapshot_files_verified"], 1)
            self.assertEqual(got["samples"][0]["snapshot_checks"][0]
                             ["historical_report_keys_observed"], 1)
            self.assertTrue(got["local_file_integrity_only"])
            self.assertFalse(got["fresh_qmt_report_keys_compared"])
            self.assertFalse(got["can_repair"])
            self.assertEqual(got["qmt_calls"], 0)
            self.assertTrue(path.is_file())

    def test_valid_active_pin_sha256_verified(self):
        with TemporaryDirectory() as tmp:
            module, market, ledger, path = fixture(Path(tmp), pin=True)
            got = self._run(module, market, ledger)
            self.assertEqual(got["active_pin_sha256_verified"], 1)

    def test_wrong_pin_sha256_rejected_not_auto_corrected(self):
        with TemporaryDirectory() as tmp:
            module, market, ledger, path = fixture(Path(tmp), pin=True)
            pin = path.parent.parent / "active" / (DAY + ".json")
            doc = json.loads(pin.read_text(encoding="utf-8"))
            doc["sha256"] = "0" * 64
            pin.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(ValueError):
                self._run(module, market, ledger)

    def test_wrong_content_address_filename_rejected(self):
        with TemporaryDirectory() as tmp:
            module, market, ledger, path = fixture(Path(tmp))
            bad = path.with_name(DAY + "-ffffffffffffffff.parquet")
            path.rename(bad)
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                self._run(module, market, ledger)

    def test_mismatched_ledger_sha_stops_before_parquet(self):
        with TemporaryDirectory() as tmp:
            module, market, ledger, path = fixture(Path(tmp))
            with patch.object(I, "_snapshot") as verify_snapshot:
                with self.assertRaisesRegex(I.IntegrityBlocked, "ledger_sha"):
                    I.verify(module, market, "f" * 64)
                verify_snapshot.assert_not_called()

    def test_excess_snapshot_bytes_rejected_before_decode(self):
        with TemporaryDirectory() as tmp:
            module, market, ledger, path = fixture(Path(tmp))
            with patch.object(I, "MAX_TOTAL_BYTES", 1):
                with patch.object(I, "_snapshot") as read:
                    with self.assertRaisesRegex(I.IntegrityBlocked, "byte_budget"):
                        self._run(module, market, ledger)
                    read.assert_not_called()

    def test_missing_explicit_readonly_flag_never_reads(self):
        with patch.object(I, "verify") as verify:
            with redirect_stdout(io.StringIO()) as out:
                rc = I.main(["--state-module", "/x",
                             "--market-root", "/y",
                             "--expected-progress-sha256", "a"*64])
            verify.assert_not_called()
        self.assertEqual(rc, 2)
        self.assertIn("EXPLICIT_READONLY_REQUIRED", out.getvalue())

    def test_reject_nonhex_expected_sha(self):
        with TemporaryDirectory() as tmp:
            module, market, ledger, path = fixture(Path(tmp))
            with patch.object(P3, "review") as preview:
                with self.assertRaisesRegex(I.IntegrityBlocked, "sha_required"):
                    I.verify(module, market, "INVALID")
                preview.assert_not_called()


if __name__ == "__main__":
    unittest.main()
