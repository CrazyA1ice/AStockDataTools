"""Offline last-stock QMT finance partial recovery tests (no QMT/network)."""
from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I
import qmt_extra_financial_partial_recovery as P


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows
        self.index = list(range(len(rows)))

    def to_dict(self, orient=None):
        if orient != "records":
            raise AssertionError("Unexpected pandas conversion")
        return self.rows


class FakeQMT:
    def __init__(self, *, break_table=None):
        self.calls = []
        self.break_table = break_table

    def get_financial_data(self, codes, tables, **kwargs):
        code, table = codes[0], tables[0]
        assert codes == [P.KNOWN_SYMBOL] and len(tables) == 1
        self.calls.append(table)
        if table == P.KNOWN_BAD_TABLE:
            raise AssertionError("Corrupt Top10Holder must not be read")
        if table == self.break_table:
            raise UnicodeDecodeError("utf-8", b"\xe2", 0, 1,
                                     "unexpected end of data")
        if table == "PerShare":
            return {code: {}}
        return {code: {table: FakeFrame([{"m_timetag": 20260930,
                                          "sample": 4.0}])}}


class CapitalPartialRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "stock"
        self.extra = self.root / "AllCycleAStockData" / "qmt_extra"
        for cycle in E.L.PERIODS:
            (self.root / "AllCycleAStockData" / cycle).mkdir(
                parents=True, exist_ok=True)
        self.workspace = Path(tmp.name) / "work"
        self.workspace.mkdir()
        self.previous_day = "2026-11-17"
        original = [{"_index": "0", "m_timetag": 20260930,
                     "holderName": "preserved only"}]
        E._snapshot_write(
            self.extra,
            "financial/Top10Holder/" + P.KNOWN_SYMBOL,
            self.previous_day,
            E.snapshot_table(self.previous_day, P.KNOWN_SYMBOL,
                             "Top10Holder", original),
            workspace=self.workspace)
        self.previous = E._financial_snapshot_file(
            self.extra, P.KNOWN_SYMBOL, "Top10Holder", self.previous_day)
        self.prev_sha = E.L.hash_file(self.previous)
        state = I._state(self.extra, self.workspace)
        state["pending"][P.KNOWN_SYMBOL] = {
            "reason": "CACHE_DECODE_ERROR", "attempts": 5,
            "asof": "2026-11-23", "detail": "QMT UTF8 error"}
        I._save_state(self.workspace, state)
        self.ledger = self.workspace / I.STATE_FILE
        self.sha = hashlib.sha256(self.ledger.read_bytes()).hexdigest()

    def test_preflight_no_qmt_and_no_write(self):
        qmt = FakeQMT()
        result = P.recover(self.root, self.workspace, self.sha,
                           xt=qmt, apply=False,
                           now=datetime(2026, 11, 23, 16, 30,
                                        tzinfo=E.L.UTC8),
                           progress=lambda _: None)
        self.assertEqual(result["status"],
                         "QMT_FINANCE_PARTIAL_TOP10HOLDER_PREFLIGHT")
        self.assertEqual(qmt.calls, [])
        self.assertEqual(self.sha, hashlib.sha256(
            self.ledger.read_bytes()).hexdigest())

    def test_seven_healthy_tables_committed_preserving_corrupted_table_pending(self):
        qmt = FakeQMT()
        clock = datetime.now(E.L.UTC8)
        if 19 * 60 + 20 <= clock.hour * 60 + clock.minute < 20 * 60 + 40:
            self.skipTest("market protected window")
        res = P.recover(self.root, self.workspace, self.sha,
                        xt=qmt, apply=True, now=clock,
                        progress=lambda _: None)
        self.assertEqual(res["status"],
                         "QMT_FINANCE_PARTIAL_HEALTHY_TABLES_COMMITTED")
        self.assertEqual(set(qmt.calls),
                         set(E.FIN_TABLES) - {P.KNOWN_BAD_TABLE})
        self.assertEqual(len(qmt.calls), 8)
        self.assertEqual(res["excluded_table_read_calls"], 0)
        self.assertEqual(res["new_snapshots"], 7)
        self.assertEqual(res["bad_table_action"], "SOURCE_EMPTY_OLD_RETAINED")
        self.assertEqual(E.L.hash_file(self.previous), self.prev_sha)
        self.assertIsNone(E._financial_snapshot_file(
            self.extra, P.KNOWN_SYMBOL, P.KNOWN_BAD_TABLE,
            clock.date().isoformat()))
        for name in E.FIN_TABLES:
            if name not in ("Top10Holder", "PerShare"):
                rows = E._financial_snapshot_rows(
                    self.extra, P.KNOWN_SYMBOL, name,
                    clock.date().isoformat())
                self.assertEqual(len(rows), 1)
        self.assertEqual(hashlib.sha256(self.ledger.read_bytes()).hexdigest(),
                         self.sha)
        self.assertEqual(I._state(self.extra, self.workspace)["pending"]
                         [P.KNOWN_SYMBOL]["reason"], "CACHE_DECODE_ERROR")

    def test_other_table_decode_error_stops_before_any_new_snapshots(self):
        qmt = FakeQMT(break_table="CashFlow")
        clock = datetime.now(E.L.UTC8)
        if 19 * 60 + 20 <= clock.hour * 60 + clock.minute < 20 * 60 + 40:
            self.skipTest("market protected window")
        with self.assertRaises(UnicodeDecodeError):
            P.recover(self.root, self.workspace, self.sha, xt=qmt,
                      now=clock, apply=True, progress=lambda _: None)
        self.assertEqual(E.L.hash_file(self.previous), self.prev_sha)
        self.assertIsNone(E._financial_snapshot_file(
            self.extra, P.KNOWN_SYMBOL, "Balance",
            clock.date().isoformat()))
        self.assertEqual(hashlib.sha256(self.ledger.read_bytes()).hexdigest(),
                         self.sha)

    def test_bad_ledger_sha_denied_before_reads(self):
        fake = FakeQMT()
        with self.assertRaisesRegex(P.PartialRecoveryBlocked,
                                    "FINANCIAL_LEDGER_SHA_CHANGED"):
            P.recover(self.root, self.workspace, "a" * 64,
                      xt=fake, apply=True, progress=lambda _: None)
        self.assertEqual(fake.calls, [])

    def test_known_symbol_and_failure_reason_required(self):
        data = I._state(self.extra, self.workspace)
        data["pending"][P.KNOWN_SYMBOL]["reason"] = "NO_CACHE"
        I._save_state(self.workspace, data)
        sha = hashlib.sha256(self.ledger.read_bytes()).hexdigest()
        with self.assertRaisesRegex(P.PartialRecoveryBlocked,
                                    "ONLY_KNOWN_TOP10HOLDER"):
            P.recover(self.root, self.workspace, sha, xt=FakeQMT(),
                      progress=lambda _: None)


if __name__ == "__main__":
    unittest.main()
