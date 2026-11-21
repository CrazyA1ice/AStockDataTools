"""Synthetic, read-only finance pending ledger classification tests."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import io
import json
from contextlib import redirect_stdout
import unittest

import market_center_finance_pending_triage as T


def write_ledger(root, pending):
    module = root / "ParquetLiveSync"
    path = module / "work" / "qmt_extra" / "financial-cache-progress.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "format": "qmt_financial_cache_import_v1",
        "daily_date": "2026-11-21", "daily_cursor": "001266.SZ",
        "pending": pending,
    }), encoding="utf-8")
    return module, path


def item(reason, detail, attempts=1):
    return {
        "reason": reason, "detail": detail,
        "attempts": attempts, "asof": "2026-11-21",
    }


class PendingTriageTests(unittest.TestCase):
    def test_exact_first_blocker_counts_only_not_all_nine_tables(self):
        with TemporaryDirectory() as tmp:
            module, path = write_ledger(Path(tmp), {
                "000001.SZ": item(
                    "SOURCE_HISTORY_CONFLICT",
                    "SOURCE_HISTORY_CONFLICT 000001.SZ table=Capital "
                    "removed_or_revised=3", 3),
                "000002.SZ": item(
                    "SOURCE_HISTORY_CONFLICT",
                    "SOURCE_HISTORY_CONFLICT 000002.SZ table=Top10Holder "
                    "removed_or_revised=2"),
                "000003.SZ": item("CACHE_DECODE_ERROR", "source decode", 6),
            })
            result = T.summarize_pending(module)
            self.assertEqual(result["conflict_total"], 2)
            self.assertEqual(result["conflict_first_table_classified"], 2)
            self.assertEqual(result["pending_total"], 3)
            self.assertEqual(result["first_blocking_table_counts"], [
                {"table": "Capital", "count": 1},
                {"table": "Top10Holder", "count": 1},
            ])
            self.assertEqual(result["attempts_by_reason"][-1]["reason"],
                             "SOURCE_HISTORY_CONFLICT")
            self.assertFalse(result["all_nine_tables_checked"])
            self.assertFalse(result["pending_repair_approved"])
            self.assertEqual(result["qmt_calls"], 0)
            self.assertFalse(result["market_file_writes"])
            self.assertEqual(path.read_bytes()[:1], b"{")

    def test_table_substring_is_not_extra_table_match(self):
        with TemporaryDirectory() as tmp:
            module, _ = write_ledger(Path(tmp), {
                "000001.SZ": item(
                    "SOURCE_HISTORY_CONFLICT",
                    "SOURCE_HISTORY_CONFLICT 000001.SZ table=Top10FlowHolder "
                    "removed_or_revised=1"),
            })
            result = T.summarize_pending(module)
            self.assertEqual(result["first_blocking_table_counts"], [
                {"table": "Top10FlowHolder", "count": 1},
            ])

    def test_mismatched_stock_and_unparseable_detail_are_quarantined(self):
        with TemporaryDirectory() as tmp:
            module, _ = write_ledger(Path(tmp), {
                "000001.SZ": item(
                    "SOURCE_HISTORY_CONFLICT",
                    "SOURCE_HISTORY_CONFLICT 000002.SZ table=Capital "
                    "removed_or_revised=3"),
                "000003.SZ": item(
                    "SOURCE_HISTORY_CONFLICT", "SOURCE_HISTORY_CONFLICT unknown"),
            })
            result = T.summarize_pending(module)
            self.assertEqual(result["conflict_first_table_unclassified"], 2)
            self.assertEqual(result["first_blocking_table_counts"], [
                {"table": "UNCLASSIFIED", "count": 2},
            ])

    def test_scoped_m_quarter_proof_is_not_auto_approved(self):
        with TemporaryDirectory() as tmp:
            module, _ = write_ledger(Path(tmp), {
                "000001.SZ": item(
                    "SOURCE_HISTORY_CONFLICT",
                    "SOURCE_HISTORY_CONFLICT 000001.SZ table=Capital "
                    "scoped_m_quarter_proof=BUSINESS_FIELDS_DIFFER"),
            })
            result = T.summarize_pending(module)
            self.assertEqual(result["first_blocker_kind_counts"], [{
                "table": "Capital",
                "kind": "SCOPED_M_QUARTER_PROOF_REJECTED",
                "count": 1,
            }])
            self.assertFalse(result["source_authenticity_certified"])

    def test_invalid_pending_entry_blocks_without_silent_drop(self):
        with TemporaryDirectory() as tmp:
            module, _ = write_ledger(Path(tmp), {
                "invalid": item("SOURCE_HISTORY_CONFLICT", "bad"),
            })
            with self.assertRaises(T.PendingTriageBlocked):
                T.summarize_pending(module)

    def test_explicit_cli_optin_required_before_ledger_reads(self):
        with patch.object(T, "summarize_pending") as scan:
            with redirect_stdout(io.StringIO()) as out:
                code = T.main(["--state-module", "/not/a/real/module"])
        self.assertEqual(code, 2)
        scan.assert_not_called()
        self.assertIn("FINANCE_PENDING_TRIAGE_EXPLICIT_OPTIN_REQUIRED",
                      out.getvalue())

    def test_valid_empty_pending_never_certifies_history(self):
        with TemporaryDirectory() as tmp:
            module, _ = write_ledger(Path(tmp), {})
            result = T.summarize_pending(module)
            self.assertEqual(result["pending_total"], 0)
            self.assertFalse(result["history_complete_certified"])

    def test_changed_ledger_is_rejected(self):
        with TemporaryDirectory() as tmp:
            module, path = write_ledger(Path(tmp), {})
            original = T._read_ledger
            def switched(p):
                result = original(p)
                p.write_text(p.read_text() + " ", encoding="utf-8")
                return result
            with patch.object(T, "_read_ledger", side_effect=switched):
                with self.assertRaisesRegex(T.PendingTriageBlocked, "changed"):
                    T.summarize_pending(module)
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
