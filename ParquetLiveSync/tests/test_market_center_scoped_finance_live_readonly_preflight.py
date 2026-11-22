"""S8: safe local-source evidence scan with synthetic finance snapshot fixtures."""
from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import inspect
import io
import json
import unittest

import market_scoped_finance_live_readonly_preflight as P
import qmt_extra_data as E
import qmt_extra_financial_cache_import as I


STOCK = "000001.SZ"
OTHER = "000002.SZ"
ASOF = "2026-11-21"


class LocalFinanceReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="finance-readiness-s8-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        repo = base / "AStockDataTools"
        (repo / ".git").mkdir(parents=True)
        self.workspace = repo / "ParquetLiveSync" / "work" / "qmt_extra"
        self.workspace.mkdir(parents=True)
        self.root = base / "stock"
        series = self.root / "AllCycleAStockData"
        for period in E.L.PERIODS:
            (series / period).mkdir(parents=True)
        self.extra = E._storage(self.root)
        self.extra.mkdir(parents=True)
        self.initial = {
            "format": I.FORMAT, "root": str(self.extra.resolve()),
            "import_cursor": "", "daily_date": ASOF, "daily_cursor": "",
            "pending_retry_cursor": "", "pending": {},
            "daily_sweep_start": "", "daily_sweep_reached_end": False,
            "daily_sweep_finished": "",
        }
        self.save_state()

    def save_state(self):
        I._save_state(self.workspace, self.initial)

    def add_snapshot(self, code=STOCK, *, day=ASOF, table="Capital", pin=True,
                     value="100"):
        records = [{"_index": "0", "m_timetag": "20260930",
                    "m_quarter": "2026Q3", "amount": value}]
        group = "financial/" + table + "/" + code
        arrow = E.snapshot_table(day, code, table, records)
        path = E._snapshot_path(self.extra, group, day, arrow)
        E._snapshot_write(self.extra, group, day, arrow, self.workspace)
        if pin:
            E._pin_financial_snapshot(self.extra, code, table, day, path)
        return path

    def inspect(self, **kwargs):
        return P.inspect(self.root, self.workspace, **kwargs)

    def test_empty_evidence_is_review_only_not_fake_green(self):
        r = self.inspect()
        self.assertEqual(r["status"],
                         "S8_REAL_ENVIRONMENT_READONLY_REVIEW_REQUIRED")
        self.assertEqual(r["stocks_sampled"], [])
        self.assertIn("NO_FINANCIAL_SAMPLE_IDENTITIES", r["issues"])
        self.assertFalse(r["can_commit"])
        self.assertFalse(r["multisource_verified"])
        self.assertFalse(r["qmt_live_connection_checked"])

    def test_sample_pending_stock_verifies_pinned_capital_and_nine_tables(self):
        self.initial["pending"] = {
            STOCK: {"reason": "SOURCE_HISTORY_CONFLICT",
                    "attempts": 1, "asof": ASOF}}
        self.save_state()
        target = self.add_snapshot()
        before = E.L.hash_file(target)
        ledger = self.workspace / I.STATE_FILE
        ledger_before = ledger.read_bytes()
        r = self.inspect()
        self.assertEqual(r["stocks_sampled"], [STOCK])
        self.assertEqual(r["stocks"][0]["tables_inspected"], 9)
        selected = [t for t in r["stocks"][0]["table_summaries"]
                    if t["table"] == "Capital"][0]
        self.assertEqual(selected["state"],
                         "LATEST_PIN_AND_SNAPSHOT_VERIFIED")
        self.assertEqual(selected["latest_selected_rows"], 1)
        self.assertEqual(r["pending_total"], 1)
        self.assertEqual(r["pending_by_reason"]["SOURCE_HISTORY_CONFLICT"], 1)
        self.assertEqual(E.L.hash_file(target), before)
        self.assertEqual(ledger.read_bytes(), ledger_before)
        self.assertEqual(r["official_market_writes"], 0)

    def test_explicit_stock_without_pending_is_readonly(self):
        self.add_snapshot()
        r = self.inspect(symbols=STOCK)
        self.assertEqual(r["sample_selection"], "USER_EXPLICIT")
        self.assertEqual(r["stocks_sampled"], [STOCK])
        self.assertFalse(r["stocks"][0]["pending"])
        self.assertFalse(r["can_apply"])

    def test_latest_legacy_without_pin_requires_review(self):
        self.add_snapshot(pin=False)
        r = self.inspect(symbols=STOCK)
        self.assertIn("LEGACY_LATEST_SNAPSHOT_UNPINNED", r["issues"])
        self.assertFalse(r["can_commit"])

    def test_latest_only_does_not_claim_full_historical_scan(self):
        self.add_snapshot(day="2026-11-19", value="99")
        self.add_snapshot(day=ASOF)
        r = self.inspect(symbols=STOCK)
        capital = next(t for t in r["stocks"][0]["table_summaries"]
                       if t["table"] == "Capital")
        self.assertEqual(capital["older_snapshot_dates_unverified"], 1)
        self.assertEqual(capital["latest_snapshot_day"], ASOF)
        self.assertFalse(r["all_historical_versions_verified"])

    def test_malformed_residue_refused_even_if_valid_parquet_exists(self):
        p = self.add_snapshot()
        (p.parent / "leftover.parquet.qmt-part").write_bytes(b"test")
        with self.assertRaisesRegex(
                P.PreflightBlocked, "UNEXPECTED_FINANCIAL_FILE"):
            self.inspect(symbols=STOCK)

    def test_orphan_active_pin_refused(self):
        self.add_snapshot()
        for p in (self.extra / "financial" / "Capital" / STOCK /
                  "snapshots").glob("*.parquet"):
            p.unlink()
        with self.assertRaisesRegex(P.PreflightBlocked,
                                    "ACTIVE_PIN_WITHOUT_SNAPSHOT"):
            self.inspect(symbols=STOCK)

    def test_tampered_active_pin_fails_closed(self):
        self.add_snapshot()
        pin = E._financial_active_path(self.extra, STOCK, "Capital", ASOF)
        record = json.loads(pin.read_text(encoding="utf-8"))
        record["sha256"] = "0" * 64
        pin.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.inspect(symbols=STOCK)

    def test_existing_transaction_journal_is_global_blocker(self):
        j = self.workspace / "scoped-finance-transaction-journals"
        j.mkdir()
        (j / (OTHER + ".json")).write_text(
            json.dumps({"phase": "PREPARED"}), encoding="utf-8")
        r = self.inspect(symbols=STOCK)
        self.assertEqual(r["journal_counts"][
            "scoped-finance-transaction-journals"], 1)
        self.assertIn("EXISTING_TRANSACTION_JOURNAL_NEEDS_MANUAL_REVIEW",
                      r["issues"])
        self.assertFalse(r["can_commit"])

    def test_pending_first_scope_is_bounded_and_deterministic(self):
        self.initial["pending"] = {
            x: {"reason": "NO_CACHE", "attempts": 1, "asof": ASOF}
            for x in ("000003.SZ", STOCK, OTHER)}
        self.save_state()
        r = self.inspect(sample_count=2)
        self.assertEqual(r["stocks_sampled"], [STOCK, OTHER])
        self.assertEqual(r["pending_total"], 3)
        self.assertEqual(r["pending_by_reason"], {"NO_CACHE": 3})

    def test_journal_creation_during_inventory_is_detected(self):
        created = self.workspace / "scoped-finance-transaction-journals"
        original = P._latest_table
        once = [False]
        def mutate(extra, code, table, evidence):
            if not once[0]:
                once[0] = True
                created.mkdir()
                (created / (OTHER + ".json")).write_text(
                    '{"phase":"PREPARED"}', encoding="utf-8")
            return original(extra, code, table, evidence)
        with patch.object(P, "_latest_table", side_effect=mutate):
            with self.assertRaisesRegex(
                    P.PreflightBlocked, "FINANCIAL_DIRECTORY_CHANGED"):
                self.inspect(symbols=STOCK)

    def test_future_dated_snapshot_is_refused(self):
        self.add_snapshot(day="2099-01-01")
        with self.assertRaisesRegex(
                P.PreflightBlocked, "FUTURE_FINANCIAL_SNAPSHOT_DAY"):
            self.inspect(symbols=STOCK)

    def test_invalid_scope_and_large_sample_rejected(self):
        for kwargs in (
            {"symbols": "000002.SZ,000001.SZ"},
            {"symbols": "bad"},
            {"symbols": ""},
            {"sample_count": 6},
            {"sample_count": 0},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(P.PreflightBlocked):
                    self.inspect(**kwargs)

    def test_invalid_noncanonical_workspace_refused(self):
        with self.assertRaisesRegex(
                P.PreflightBlocked, "CANONICAL_WORKSPACE"):
            P.inspect(self.root, Path(self.tmp.name))

    def test_finance_ledger_changed_during_read_is_refused(self):
        original = P.REVIEW._hash_file
        observed = [0]
        def unstable(path, maximum):
            observed[0] += 1
            h = original(path, maximum)
            if observed[0] == 2:
                return "0" * 64 if h != "0" * 64 else "1" * 64
            return h
        with patch.object(P.REVIEW, "_hash_file", side_effect=unstable):
            with self.assertRaisesRegex(
                    P.PreflightBlocked, "FINANCE_LEDGER_CHANGED"):
                self.inspect(symbols=STOCK)

    def test_cli_requires_explicit_readonly_before_disk_access(self):
        with patch.object(P, "inspect") as scan:
            out = io.StringIO()
            with redirect_stdout(out):
                result = P.main([
                    "--root", str(self.root),
                    "--workspace", str(self.workspace)])
        self.assertEqual(result, 2)
        scan.assert_not_called()
        self.assertIn("S8_EXPLICIT_READONLY_REQUIRED", out.getvalue())

    def test_cli_has_no_apply_or_qmt_download_switches(self):
        with self.assertRaises(SystemExit):
            P.main(["--apply", "--root", str(self.root),
                    "--workspace", str(self.workspace)])

    def test_cli_reports_no_commit_even_with_valid_sample(self):
        self.add_snapshot()
        out = io.StringIO()
        with redirect_stdout(out):
            rc = P.main(["--root", str(self.root),
                         "--workspace", str(self.workspace),
                         "--symbols", STOCK, "--explicit-readonly"])
        self.assertEqual(rc, 0)
        receipt = json.loads(out.getvalue())
        self.assertFalse(receipt["can_apply"])
        self.assertFalse(receipt["can_commit"])
        self.assertFalse(receipt["all_historical_versions_verified"])
        self.assertEqual(receipt["qmt_calls"], 0)

    def test_no_source_module_uses_finance_writers_or_downloads(self):
        source = inspect.getsource(P)
        for forbidden in ("xtquant", "download_financial_data2(",
                          "._snapshot_write(", "._pin_financial_snapshot(",
                          "._save_state(", "._commit_symbol(",
                          "LIVE.exclusive_writer("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
