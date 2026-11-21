"""Offline synthetic tests: limited finance history metadata (no Parquet reads)."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import market_center_finance_pending_snapshot_review as R

CN = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 21, 21, 47, tzinfo=CN)


def make_fixture(root, items=None):
    module = root / "ParquetLiveSync"
    ledger = module / "work" / "qmt_extra" / "financial-cache-progress.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({
        "format": "qmt_financial_cache_import_v1",
        "daily_date": "2026-11-21", "daily_cursor": "001266.SZ",
        "pending": items or {},
    }), encoding="utf-8")
    market = root / "AllCycleAStockData"
    (market / "qmt_extra" / "financial").mkdir(parents=True)
    return module, market, ledger


def pending(code, table="Capital", *, proof="REPORT_KEYS_ADDED_OR_REMOVED",
            asof="2026-11-19", attempts=1):
    detail = "SOURCE_HISTORY_CONFLICT " + code + " table=" + table + " "
    detail += ("scoped_m_quarter_proof=" + proof if table == "Capital"
               else "removed_or_revised=1")
    return {"reason": "SOURCE_HISTORY_CONFLICT", "detail": detail,
            "asof": asof, "attempts": attempts}


def snapshot(market, code, table, day="2026-11-18", pin=False):
    stock = market / "qmt_extra" / "financial" / table / code
    path = stock / "snapshots" / (day + "-0123456789abcdef.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic-not-parquet-payload")
    if pin:
        folder = stock / "active"
        folder.mkdir()
        (folder / (day + ".json")).write_text(json.dumps({
            "format": "qmt_financial_active_v1", "symbol": code,
            "table": table, "asof": day, "filename": path.name,
            "sha256": "a" * 64,
        }), encoding="utf-8")
    return path


class SnapshotMetadataTests(unittest.TestCase):
    def test_capital_proof_classes_and_two_samples(self):
        with TemporaryDirectory() as tmp:
            a, b, c = "000001.SZ", "000002.SZ", "000003.SZ"
            items = {
                a: pending(a, proof="REPORT_KEYS_ADDED_OR_REMOVED"),
                b: pending(b, proof="BUSINESS_OR_DATE_FIELD_CHANGED",
                           asof="2026-11-21", attempts=3),
                c: pending(c, proof="FRESH_DUPLICATE_REPORT_KEY",
                           asof="2026-11-20"),
            }
            module, market, ledger = make_fixture(Path(tmp), items)
            snapshot(market, a, "Capital", pin=True)
            snapshot(market, b, "Capital")
            result = R.review(module, market, now=NOW)
            self.assertEqual(result["sample_count"], 2)
            self.assertEqual(result["capital_proof_rejections_grouped"], 3)
            self.assertEqual(
                {x["proof_class"]: x["count"] for x in
                 result["capital_proof_rejection_counts"]},
                {"REPORT_KEYS_ADDED_OR_REMOVED": 1,
                 "BUSINESS_OR_DATE_FIELD_CHANGED": 1,
                 "FRESH_DUPLICATE_REPORT_KEY": 1})
            self.assertEqual(
                {x["stock"] for x in result["samples"]}, {a, b})
            self.assertFalse(result["historical_business_fields_compared"])
            self.assertFalse(result["can_repair"])
            self.assertEqual(result["qmt_calls"], 0)

    def test_all_four_first_tables_sample_only_their_own_snapshot_tree(self):
        with TemporaryDirectory() as tmp:
            items = {}
            for idx, table in enumerate(("Capital", "Top10Holder",
                                         "Top10FlowHolder", "HolderNum")):
                code = "00000" + str(idx+1) + ".SZ"
                items[code] = pending(code, table)
            module, market, _ = make_fixture(Path(tmp), items)
            for code, item in items.items():
                table = R.T._parse_first_conflict(code, item["detail"])[0]
                snapshot(market, code, table)
            result = R.review(module, market, now=NOW)
            self.assertEqual(result["sample_count"], 4)
            self.assertTrue(all(x["immutable_snapshot_candidates"] == 1
                                for x in result["samples"]))
            self.assertTrue(result["only_first_blocking_table_inspected"])

    def test_missing_history_is_observation_not_completeness(self):
        with TemporaryDirectory() as tmp:
            c = "000001.SZ"
            module, market, _ = make_fixture(Path(tmp), {c: pending(c)})
            result = R.review(module, market, now=NOW)
            self.assertEqual(result["sample_count"], 1)
            self.assertFalse(result["samples"][0]["local_snapshot_candidates_exist"])
            self.assertFalse(result["immutable_snapshot_content_verified"])
            self.assertFalse(result["source_authenticity_certified"])

    def test_wrong_active_pin_reference_fails_closed(self):
        with TemporaryDirectory() as tmp:
            c = "000001.SZ"
            module, market, _ = make_fixture(Path(tmp), {c: pending(c)})
            snap = snapshot(market, c, "Capital", pin=True)
            pin = snap.parent.parent / "active" / "2026-11-18.json"
            data = json.loads(pin.read_text())
            data["filename"] = "2026-11-18-ffffffffffffffff.parquet"
            pin.write_text(json.dumps(data))
            with self.assertRaisesRegex(R.SnapshotReviewBlocked, "unmatched"):
                R.review(module, market, now=NOW)

    def test_symlinked_snapshot_rejected(self):
        with TemporaryDirectory() as tmp:
            c = "000001.SZ"
            module, market, _ = make_fixture(Path(tmp), {c: pending(c)})
            snap = snapshot(market, c, "Capital")
            link = snap.parent / "2026-11-19-0123456789abcdef.parquet"
            try:
                link.symlink_to(snap)
            except (OSError, NotImplementedError):
                self.skipTest("Creating test symlinks needs privileges")
            with self.assertRaisesRegex(R.SnapshotReviewBlocked, "redirected"):
                R.review(module, market, now=NOW)

    def test_reserved_scheduled_window_blocks_before_ledger_read(self):
        with patch.object(R.T, "summarize_pending") as read:
            with self.assertRaisesRegex(R.SnapshotReviewBlocked, "reserved"):
                R.review("/not/available", "/not/available", now=datetime(
                    2026, 11, 21, 20, 5, tzinfo=CN))
            read.assert_not_called()

    def test_explicit_cli_optin_required(self):
        with patch.object(R, "review") as read:
            with redirect_stdout(io.StringIO()) as out:
                code = R.main(["--state-module", "/private/ParquetLiveSync",
                               "--market-root", "/private/AllCycleAStockData"])
        self.assertEqual(code, 2)
        read.assert_not_called()
        self.assertIn("EXPLICIT_READONLY_REQUIRED", out.getvalue())

    def test_concurrently_changed_ledger_rejected(self):
        with TemporaryDirectory() as tmp:
            c = "000001.SZ"
            module, market, ledger = make_fixture(Path(tmp), {c: pending(c)})
            snapshot(market, c, "Capital")
            orig = R._inventory
            def mutate(*args):
                result = orig(*args)
                ledger.write_bytes(ledger.read_bytes() + b" ")
                return result
            with patch.object(R, "_inventory", side_effect=mutate):
                with self.assertRaisesRegex(R.SnapshotReviewBlocked, "changed"):
                    R.review(module, market, now=NOW)

    def test_unknown_proof_status_not_treated_as_valid_exception(self):
        with TemporaryDirectory() as tmp:
            c = "000001.SZ"
            module, market, _ = make_fixture(Path(tmp), {
                c: pending(c, proof="UNEXPECTED_NEW_CLASS"),
            })
            result = R.review(module, market, now=NOW)
            self.assertEqual(result["capital_proof_rejection_counts"], [{
                "proof_class": "UNRECOGNIZED_PROOF_STATUS", "count": 1,
            }])
            self.assertFalse(result["can_execute"])


if __name__ == "__main__":
    unittest.main()
