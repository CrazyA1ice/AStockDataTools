"""V2-D2C read-only *historical* finance metadata inventory regression tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import io
import json
import unittest

import market_center_v2_finance_history_scope as H
import market_center_v2_finance_history_scope_cli as CLI

CN = timezone(timedelta(hours=8))
WHEN = datetime(2026, 11, 20, 23, 20, tzinfo=CN)
GROUP = ["000756.SZ", "000757.SZ", "000758.SZ",
         "000759.SZ", "000761.SZ"]
OLDER = "2026-10-30"


def fixture(root: Path):
    module = root / "ParquetLiveSync"
    market = root / "AllCycleAStockData"
    module.mkdir()
    market.mkdir()
    (market / "qmt_extra" / "financial").mkdir(parents=True)
    base_report = {
        "status": "V2D2B_READONLY_RECOVERY_INVENTORY_NOT_EXECUTABLE",
        "run_day": "2026-11-20", "failed_batch": GROUP,
        "receipt_sha256": "a" * 64,
        "finance_progress_sha256": "b" * 64,
        "code_fingerprints": [{"name": "synthetic.py", "approved": False}],
        "finance_storage_found": True,
        "static_evidence_preview_status": "PREVIEW_CHECKS_PASSED_EXECUTION_STILL_DISABLED",
        "can_execute": False,
    }
    return module, market, base_report


def put_snapshot(root: Path, symbol=GROUP[0], table="Capital",
                 day=OLDER, suffix="0123456789abcdef", *, pinned=False):
    stock = root / "qmt_extra" / "financial" / table / symbol
    snaps = stock / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    filename = day + "-" + suffix + ".parquet"
    path = snaps / filename
    path.write_bytes(b"synthetic-parquet-marker-only")
    if pinned:
        active = stock / "active"
        active.mkdir(exist_ok=True)
        doc = {
            "format": "qmt_financial_active_v1",
            "symbol": symbol, "table": table,
            "asof": day, "filename": filename,
            "sha256": "b" * 64,
        }
        (active / (day + ".json")).write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


class HistoricalVersionClosureTests(unittest.TestCase):
    def scan(self, module, market, basic):
        with patch.object(H, "inspect_recovery_prerequisites",
                          return_value=basic) as inspect_mock:
            result = H.inventory_historical_versions(
                state_module=module, market_root=market, now=WHEN)
        inspect_mock.assert_called_once()
        return result

    def test_empty_run_day_scope_cannot_certify_no_historical_versions(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            result = self.scan(module, market, basic)
            self.assertEqual(result["scope_count"], 45)
            self.assertEqual(result["historical_candidate_bytes"], 0)
            self.assertTrue(result["zero_run_day_bytes_do_not_mean_no_historical_versions"])
            self.assertFalse(result["backups_created"])
            self.assertFalse(result["rollback_verified"])
            self.assertFalse(result["can_execute"])
            self.assertFalse(result["can_download"])
            self.assertEqual(result["qmt_calls"], 0)
            self.assertEqual(result["files_created"], 0)

    def test_prior_day_snapshot_and_pin_are_in_scope(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            snap = put_snapshot(market, pinned=True)
            before = (snap.read_bytes(), snap.stat().st_mtime_ns)
            result = self.scan(module, market, basic)
            self.assertEqual(result["historical_snapshot_count"], 1)
            self.assertEqual(result["historical_active_pin_count"], 1)
            self.assertGreater(result["historical_candidate_bytes"], len(before[0]))
            self.assertEqual((snap.read_bytes(), snap.stat().st_mtime_ns), before)
            self.assertFalse(result["snapshot_content_sha256_verified"])
            self.assertFalse(result["can_execute"])

    def test_two_old_immutable_versions_are_both_counted(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            put_snapshot(market, suffix="0123456789abcdef", pinned=True)
            put_snapshot(market, suffix="fedcba9876543210")
            result = self.scan(module, market, basic)
            self.assertEqual(result["historical_snapshot_count"], 2)
            self.assertEqual(result["historical_active_pin_count"], 1)
            self.assertFalse(result["rollback_verified"])

    def test_pin_without_immutable_snapshot_is_rejected(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            path = put_snapshot(market, pinned=True)
            path.unlink()
            with patch.object(H, "inspect_recovery_prerequisites",
                              return_value=basic):
                with self.assertRaisesRegex(
                        H.PreflightBlocked, "active_pin_refers_to_missing_snapshot"):
                    H.inventory_historical_versions(
                        state_module=module, market_root=market, now=WHEN)

    def test_wrong_symbol_and_table_in_active_pin_rejected(self):
        for field, wrong in (("symbol", "000001.SZ"), ("table", "Income"),
                             ("asof", "2026-09-30")):
            with self.subTest(field=field), TemporaryDirectory() as tmp:
                module, market, basic = fixture(Path(tmp))
                put_snapshot(market, pinned=True)
                pin = (market / "qmt_extra" / "financial" / "Capital" /
                       GROUP[0] / "active" / (OLDER + ".json"))
                data = json.loads(pin.read_text(encoding="utf-8"))
                data[field] = wrong
                pin.write_text(json.dumps(data), encoding="utf-8")
                with patch.object(H, "inspect_recovery_prerequisites",
                                  return_value=basic):
                    with self.assertRaisesRegex(
                            H.PreflightBlocked, "active_identity_mismatch"):
                        H.inventory_historical_versions(
                            state_module=module, market_root=market, now=WHEN)

    def test_malformed_historical_pin_rejected(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            put_snapshot(market, pinned=True)
            pin = (market / "qmt_extra" / "financial" / "Capital" /
                   GROUP[0] / "active" / (OLDER + ".json"))
            pin.write_text("{", encoding="utf-8")
            with patch.object(H, "inspect_recovery_prerequisites",
                              return_value=basic):
                with self.assertRaisesRegex(
                        H.PreflightBlocked, "malformed_historical_finance_pin"):
                    H.inventory_historical_versions(
                        state_module=module, market_root=market, now=WHEN)

    def test_nonmatching_historical_snapshot_name_is_refused(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            path = put_snapshot(market)
            bad = path.with_name("unknown.parquet")
            path.rename(bad)
            with patch.object(H, "inspect_recovery_prerequisites",
                              return_value=basic):
                with self.assertRaisesRegex(
                        H.PreflightBlocked, "unknown_finance_snapshot_name"):
                    H.inventory_historical_versions(
                        state_module=module, market_root=market, now=WHEN)

    def test_unexpected_staging_part_file_is_not_ignored(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            put_snapshot(market)
            dirname = (market / "qmt_extra" / "financial" / "Capital" /
                       GROUP[0] / "snapshots")
            (dirname / "unfinished.qmt-part").write_text("x", encoding="utf-8")
            with patch.object(H, "inspect_recovery_prerequisites",
                              return_value=basic):
                with self.assertRaisesRegex(
                        H.PreflightBlocked, "unexpected_finance_history_entry"):
                    H.inventory_historical_versions(
                        state_module=module, market_root=market, now=WHEN)

    def test_old_pin_filename_bad_date_refused(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            put_snapshot(market, pinned=True)
            directory = (market / "qmt_extra" / "financial" / "Capital" /
                         GROUP[0] / "active")
            (directory / (OLDER + ".json")).rename(directory / "2026-02-30.json")
            with patch.object(H, "inspect_recovery_prerequisites",
                              return_value=basic):
                with self.assertRaisesRegex(
                        H.PreflightBlocked, "noncanonical_finance_active_date"):
                    H.inventory_historical_versions(
                        state_module=module, market_root=market, now=WHEN)

    def test_single_scope_file_budget_fails_closed(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            for n in range(4):
                put_snapshot(market, suffix=f"{n:016x}")
            with patch.object(H, "MAX_FILES_PER_STOCK_TABLE", 3):
                with patch.object(H, "inspect_recovery_prerequisites",
                                  return_value=basic):
                    with self.assertRaisesRegex(
                            H.PreflightBlocked, "file_count_limit"):
                        H.inventory_historical_versions(
                            state_module=module, market_root=market, now=WHEN)

    def test_aggregate_byte_budget_fails_closed(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            put_snapshot(market)
            with patch.object(H, "MAX_TOTAL_CANDIDATE_BYTES", 5):
                with patch.object(H, "inspect_recovery_prerequisites",
                                  return_value=basic):
                    with self.assertRaisesRegex(
                            H.PreflightBlocked, "global_byte_budget"):
                        H.inventory_historical_versions(
                            state_module=module, market_root=market, now=WHEN)

    def test_symlinked_finance_snapshot_not_followed(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            snaps = (market / "qmt_extra" / "financial" / "Capital" /
                     GROUP[0] / "snapshots")
            snaps.mkdir(parents=True)
            outside = Path(tmp) / "outside.txt"
            outside.write_text("private information", encoding="utf-8")
            try:
                (snaps / (OLDER + "-0123456789abcdef.parquet")).symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks require privileges on this Windows host")
            with patch.object(H, "inspect_recovery_prerequisites",
                              return_value=basic):
                with self.assertRaisesRegex(H.PreflightBlocked, "redirected"):
                    H.inventory_historical_versions(
                        state_module=module, market_root=market, now=WHEN)

    def test_glob_does_not_claim_all_market_finance_backup_is_covered(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            result = self.scan(module, market, basic)
            self.assertTrue(result["scope_is_limited_to_original_failed_stock_batch"])
            self.assertTrue(result["progress_ledger_bytes_not_included_in_estimate"])
            self.assertFalse(result["canonical_worker_hash_approved"])
            self.assertFalse(result["writer_mutex_owned"])

    def test_cross_day_auto_replay_still_prohibited(self):
        with TemporaryDirectory() as tmp:
            module, market, basic = fixture(Path(tmp))
            result = self.scan(module, market, basic)
            self.assertFalse(result["cross_day_old_daily_replay_allowed"])
            self.assertIn("daily_sweep_cross_day_policy_not_approved",
                          result["execution_blockers"])

    def test_cli_requires_explicit_readonly(self):
        with patch.object(CLI, "inventory_historical_versions") as invoke:
            with patch("sys.stdout", io.StringIO()) as output:
                ret = CLI.main([
                    "--state-module", "D:/fake/ParquetLiveSync",
                    "--market-root", "D:/fake/AllCycleAStockData"])
        self.assertEqual(ret, 2)
        invoke.assert_not_called()
        self.assertIn("EXPLICIT_READONLY_REQUIRED", output.getvalue())

    def test_cli_success_is_still_no_exec(self):
        with patch.object(CLI, "inventory_historical_versions", return_value={
                "status": "V2D2C_HISTORICAL_FINANCE_METADATA_NOT_RESTORABLE",
                "can_execute": False, "can_download": False, "qmt_calls": 0,
                "market_file_writes": False}):
            with patch("sys.stdout", io.StringIO()) as output:
                ret = CLI.main([
                    "--state-module", "D:/fake/ParquetLiveSync",
                    "--market-root", "D:/fake/AllCycleAStockData",
                    "--explicit-readonly"])
        self.assertEqual(ret, 0)
        obj = json.loads(output.getvalue())
        self.assertFalse(obj["can_execute"])
        self.assertEqual(obj["qmt_calls"], 0)


if __name__ == "__main__":
    unittest.main()
