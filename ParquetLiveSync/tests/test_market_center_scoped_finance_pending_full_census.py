"""S9 pending census: synthetic ledger and filename-only tests.

Fixtures may write dummy .parquet-named bytes in an OS TemporaryDirectory:
the census never opens or certifies Parquet content or QMT source records.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import io
import json
import unittest

import market_scoped_finance_pending_full_census as C
import qmt_extra_data as E
import qmt_extra_financial_cache_import as I

STOCK = "000010.SZ"
ALT = "000036.SZ"
DECODE = "000055.SZ"
DAY = "2026-11-17"
OLDER = "2026-11-16"
FAKE = "0123456789abcdef"
CLOCK = datetime(2026, 11, 22, 10, 15, tzinfo=timezone(timedelta(hours=8)))


def conflict(code, table="Capital", rows=2):
    return {
        "reason": "SOURCE_HISTORY_CONFLICT",
        "asof": "2026-11-20", "attempts": 3,
        "detail": ("SOURCE_HISTORY_CONFLICT " + code + " table=" + table
                   + " removed_or_revised=" + str(rows)),
    }


def decode():
    return {
        "reason": "CACHE_DECODE_ERROR",
        "asof": "2026-11-20", "attempts": 2,
        "detail": "synthetic provider decode failure",
    }


class PendingCensusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="s9-pending-census-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        repo = base / "AStockDataTools"
        (repo / ".git").mkdir(parents=True)
        self.workspace = repo / "ParquetLiveSync" / "work" / "qmt_extra"
        self.workspace.mkdir(parents=True)
        self.root = base / "stock"
        market = self.root / "AllCycleAStockData"
        for period in E.L.PERIODS:
            (market / period).mkdir(parents=True)
        self.extra = E._storage(self.root)
        self.finance = self.extra / "financial"
        self.finance.mkdir(parents=True)
        self.state = {
            "format": I.FORMAT, "root": str(self.extra.resolve()),
            "import_cursor": "", "daily_date": "2026-11-21",
            "daily_cursor": "", "pending_retry_cursor": "", "pending": {},
            "daily_sweep_start": "", "daily_sweep_reached_end": False,
            "daily_sweep_finished": "",
        }
        self.save()

    def save(self):
        I._save_state(self.workspace, self.state)

    def add(self, stock=STOCK, table="Capital", day=DAY, *, pin=False,
            fingerprint=FAKE):
        directory = self.finance / table / stock
        snapshots = directory / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        name = day + "-" + fingerprint + ".parquet"
        target = snapshots / name
        target.write_bytes(b"synthetic-not-a-real-parquet")
        if pin:
            active = directory / "active"
            active.mkdir(parents=True, exist_ok=True)
            (active / (day + ".json")).write_text(json.dumps({
                "format": "qmt_financial_active_v1",
                "symbol": stock, "table": table, "asof": day,
                "filename": name, "sha256": "0" * 64,
            }), encoding="utf-8")
        return target

    def inspect(self, **kwargs):
        return C.census(self.root, self.workspace, now=CLOCK, **kwargs)

    def test_empty_pending_ledger_not_falsely_claimed_complete_market(self):
        r = self.inspect()
        self.assertEqual(r["ledger_pending_total"], 0)
        self.assertEqual(r["rows_on_page"], [])
        self.assertTrue(r["all_pending_ledger_symbols_enumerated"])
        self.assertFalse(r["all_historical_versions_verified"])
        self.assertFalse(r["can_commit"])
        self.assertEqual(r["qmt_calls"], 0)

    def test_stock_conflict_and_decode_reason_are_retained(self):
        self.state["pending"] = {STOCK: conflict(STOCK), DECODE: decode()}
        self.save()
        r = self.inspect(page_size=2)
        self.assertEqual(r["pending_by_reason"], {
            "CACHE_DECODE_ERROR": 1, "SOURCE_HISTORY_CONFLICT": 1})
        self.assertEqual(r["cache_decode_error_stocks"], [DECODE])
        by_stock = {x["symbol"]: x for x in r["rows_on_page"]}
        self.assertEqual(by_stock[STOCK]["first_recorded_conflict_table"],
                         "Capital")
        self.assertEqual(by_stock[STOCK]["first_recorded_conflict_kind"],
                         "REMOVED_OR_REVISED_UNVERIFIED")
        self.assertEqual(by_stock[STOCK][
            "reported_removed_or_revised_rows_unverified"], 2)
        self.assertIsNone(by_stock[DECODE]["first_recorded_conflict_table"])

    def test_per_share_absent_means_only_no_local_snapshot(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        self.add()
        result = self.inspect()
        self.assertEqual(result["per_share_without_local_snapshots"], 1)
        self.assertFalse(result["per_share_qmt_source_empty_proven"])
        stock = result["rows_on_page"][0]
        self.assertEqual(stock["nine_table_states"]["PerShare"], "M")
        self.assertEqual(stock["nine_table_states"]["Capital"], "U")
        self.assertFalse(result["all_snapshot_contents_sha256_verified"])

    def test_pinned_metadata_not_mislabeled_as_content_verified(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        self.add(pin=True)
        r = self.inspect()
        self.assertEqual(r["rows_on_page"][0]["nine_table_states"]["Capital"],
                         "P")
        self.assertFalse(r["source_authenticity_certified"])
        self.assertFalse(r["all_snapshot_contents_sha256_verified"])

    def test_partial_pins_across_dates_are_exposed(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        self.add(day=OLDER, pin=False)
        self.add(day=DAY, pin=True)
        result = self.inspect()
        self.assertEqual(result["rows_on_page"][0]["nine_table_states"]["Capital"],
                         "R")
        self.assertEqual(result["rows_on_page"][0]["nine_table_file_counts"][
            "Capital"]["unpinned_days"], 1)

    def test_same_day_unpinned_multiple_versions_marked_ambiguous(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        self.add(pin=False)
        self.add(pin=False, fingerprint="ffffffffffffffff")
        report = self.inspect()
        self.assertEqual(report["rows_on_page"][0]["nine_table_states"]["Capital"],
                         "A")

    def test_per_share_local_snapshot_and_pin_are_counted_not_suppressed(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        self.add(table="PerShare", pin=True)
        r = self.inspect()
        self.assertEqual(r["per_share_without_local_snapshots"], 0)
        self.assertEqual(r["rows_on_page"][0]["nine_table_states"]["PerShare"],
                         "P")
        self.assertFalse(r["per_share_qmt_source_empty_proven"])

    def test_future_dated_snapshot_metadata_is_refused(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        self.add(day="2099-01-01")
        with self.assertRaisesRegex(
                C.CensusBlocked, "FUTURE_FINANCIAL_SNAPSHOT_DATE"):
            self.inspect()

    def test_pin_rewritten_during_scan_is_refused(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        self.add(pin=True)
        original = C._table
        written = [False]
        def mutate(finance, code, table, evidence):
            record = original(finance, code, table, evidence)
            if table == "Capital" and not written[0]:
                written[0] = True
                pin = (self.finance / "Capital" / STOCK / "active" /
                       (DAY + ".json"))
                obj = json.loads(pin.read_text(encoding="utf-8"))
                obj["sha256"] = "1" * 64
                pin.write_text(json.dumps(obj), encoding="utf-8")
            return record
        with patch.object(C, "_table", side_effect=mutate):
            with self.assertRaisesRegex(
                    C.CensusBlocked, "FINANCE_FILES_CHANGED_DURING_CENSUS"):
                self.inspect()

    def test_pin_reference_to_missing_local_candidate_is_blocked(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        target = self.add(pin=True)
        target.unlink()
        with self.assertRaises(C.P3.SnapshotReviewBlocked):
            self.inspect()

    def test_malformed_pin_sha_field_is_rejected(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        self.add(pin=True)
        pin = (self.finance / "Capital" / STOCK /
               "active" / (DAY + ".json"))
        obj = json.loads(pin.read_text(encoding="utf-8"))
        obj["sha256"] = "invalid"
        pin.write_text(json.dumps(obj), encoding="utf-8")
        with self.assertRaises(C.P3.SnapshotReviewBlocked):
            self.inspect()

    def test_full_85_stocks_are_scanned_not_only_sampled(self):
        self.state["pending"] = {
            f"{i:06d}.SZ": conflict(f"{i:06d}.SZ")
            for i in range(1, 86) if i != 55}
        self.state["pending"][DECODE] = decode()
        self.save()
        r = self.inspect()
        self.assertEqual(r["ledger_pending_total"], 85)
        self.assertEqual(r["per_share_without_local_snapshots"], 85)
        self.assertEqual(r["pending_by_reason"]["SOURCE_HISTORY_CONFLICT"], 84)
        self.assertEqual(r["first_recorded_conflict_table_counts"]["Capital"],
                         84)
        self.assertEqual(r["cache_decode_error_stocks"], [DECODE])
        self.assertEqual(r["total_pages"], 29)
        self.assertEqual(r["rows_on_page_count"], 3)
        self.assertEqual(r["rows_on_page"][0]["symbol"], DECODE)
        self.assertFalse(r["page_is_complete_pending_census"])

    def test_pages_are_bounded_but_aggregates_are_still_full_scope(self):
        self.state["pending"] = {
            STOCK: conflict(STOCK), ALT: conflict(ALT), DECODE: decode()}
        self.save()
        first = self.inspect(page=1, page_size=2)
        second = self.inspect(page=2, page_size=2)
        self.assertEqual(first["ledger_pending_total"], 3)
        self.assertEqual(second["ledger_pending_total"], 3)
        self.assertEqual(first["total_pages"], 2)
        self.assertEqual(second["rows_on_page_count"], 1)
        self.assertFalse(first["page_is_complete_pending_census"])

    def test_invalid_page_options_refused_before_reads(self):
        for kw in ({"page": 0}, {"page": 257}, {"page_size": 0},
                   {"page_size": 21}, {"page": True}):
            with self.subTest(kwargs=kw):
                with self.assertRaises(C.CensusBlocked):
                    self.inspect(**kw)

    def test_overbroad_pending_scope_refused(self):
        self.state["pending"] = {
            f"{i:06d}.SZ": conflict(f"{i:06d}.SZ")
            for i in range(257)}
        self.save()
        with self.assertRaisesRegex(
                C.CensusBlocked, "PENDING_LEDGER_SCOPE_OVER_BUDGET"):
            self.inspect()

    def test_2005_writer_window_refused_before_read(self):
        when = datetime(2026, 11, 22, 20, 5,
                        tzinfo=timezone(timedelta(hours=8)))
        with patch.object(C.P2, "summarize_pending") as summary:
            with self.assertRaisesRegex(
                    C.CensusBlocked, "RESERVED_2005"):
                C.census(self.root, self.workspace, now=when)
        summary.assert_not_called()

    def test_existing_journal_is_exposed_without_replay(self):
        directory = self.workspace / "scoped-finance-transaction-journals"
        directory.mkdir()
        (directory / (STOCK + ".json")).write_text(
            '{"phase":"PREPARED"}', encoding="utf-8")
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        r = self.inspect()
        self.assertEqual(r["journal_counts"][
            "scoped-finance-transaction-journals"], 1)
        self.assertFalse(r["can_apply"])

    def test_file_added_during_census_fails_closed(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        self.add()
        original = C._table
        called = [False]
        def mutate(finance, code, table, evidence):
            value = original(finance, code, table, evidence)
            if table == "Capital" and not called[0]:
                called[0] = True
                self.add(stock=STOCK, table="Capital",
                         fingerprint="ffffffffffffffff")
            return value
        with patch.object(C, "_table", side_effect=mutate):
            with self.assertRaisesRegex(
                    C.CensusBlocked, "FINANCE_FILES_CHANGED_DURING_CENSUS"):
                self.inspect()

    def test_ledger_mutation_during_scan_fails_closed(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        original = C._table
        touched = [False]
        def mutate(finance, code, table, evidence):
            if not touched[0]:
                touched[0] = True
                self.state["pending"][STOCK]["attempts"] = 4
                self.save()
            return original(finance, code, table, evidence)
        with patch.object(C, "_table", side_effect=mutate):
            with self.assertRaisesRegex(
                    C.CensusBlocked, "LEDGER_CHANGED_DURING_CENSUS"):
                self.inspect()

    def test_global_file_budget_is_enforced(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        self.add()
        with patch.object(C, "MAX_GLOBAL_FILES", 0):
            with self.assertRaisesRegex(
                    C.CensusBlocked, "FINANCE_METADATA_GLOBAL_BUDGET"):
                self.inspect()

    def test_canonical_checkout_gate_refuses_detached(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        dotgit = self.workspace.parent.parent.parent / ".git"
        dotgit.rmdir()
        dotgit.write_text("gitdir: synthetic", encoding="utf-8")
        with self.assertRaises(C.S8.PreflightBlocked):
            self.inspect()

    def test_no_cli_optin_never_scans_disk(self):
        out = io.StringIO()
        with patch.object(C, "census") as compute, redirect_stdout(out):
            rc = C.main([
                "--root", str(self.root), "--workspace",
                str(self.workspace)])
        self.assertEqual(rc, 2)
        compute.assert_not_called()
        self.assertIn("S9_EXPLICIT_READONLY_REQUIRED", out.getvalue())

    def test_cli_cannot_accept_apply_or_download_arguments(self):
        with patch.object(C, "census") as compute, \
             redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                C.main(["--root", str(self.root),
                        "--workspace", str(self.workspace), "--apply"])
        compute.assert_not_called()

    def test_cli_returns_summary_without_mutating_pending_or_snapshot(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        target = self.add()
        before = ((self.workspace / I.STATE_FILE).read_bytes(),
                  target.read_bytes())
        out = io.StringIO()
        with redirect_stdout(out), \
             patch.object(C, "_no_writer_window"):
            rc = C.main([
                "--root", str(self.root), "--workspace",
                str(self.workspace), "--explicit-readonly"])
        self.assertEqual(rc, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["ledger_pending_total"], 1)
        self.assertFalse(result["can_commit"])
        self.assertEqual(
            before, ((self.workspace / I.STATE_FILE).read_bytes(),
                     target.read_bytes()))

    def test_ledger_first_blocker_is_not_all_nine_history_comparison(self):
        self.state["pending"] = {STOCK: conflict(STOCK, "Balance", 3)}
        self.save()
        r = self.inspect()
        self.assertEqual(r["first_recorded_conflict_table_counts"],
                         {"Balance": 1})
        self.assertTrue(r["first_conflict_only_not_all_nine_source_differences"])
        self.assertFalse(r["all_historical_versions_verified"])

    def test_unknown_provider_state_is_never_reclassified_as_no_cache(self):
        self.state["pending"] = {STOCK: conflict(STOCK)}
        self.save()
        r = self.inspect()
        self.assertEqual(r["pending_by_reason"], {"SOURCE_HISTORY_CONFLICT": 1})
        self.assertEqual(r["per_share_without_local_snapshots"], 1)
        self.assertFalse(r["per_share_qmt_source_empty_proven"])


if __name__ == "__main__":
    unittest.main()
