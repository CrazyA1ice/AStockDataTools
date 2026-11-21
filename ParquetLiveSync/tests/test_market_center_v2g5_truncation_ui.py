"""V2G5: bounded results must disclose a truncated visible table.

Only synthetic Tk observations are used. No market files or QMT calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest import mock

import market_center_v2_preview as base
import market_center_v2e_selected_ui as UI


def observation(symbol):
    return {
        "symbol": symbol, "period": "day", "label_day": "2026-11-20",
        "rows": 1, "physical_status": "ROWS_OBSERVED_UNCERTIFIED",
        "interpretation": "RECORDS_PRESENT_NOT_CERTIFIED", "anomalies": {},
    }


def report(*items):
    return {
        "scope": {"start": "2026-11-20", "end": "2026-11-20",
                  "stocks": [item["symbol"] for item in items],
                  "periods": ["day"]},
        "market_file_writes": False, "qmt_calls": 0,
        "evidence_interpretation": {
            "status": "V2B2_EVIDENCE_GATED_CANDIDATES_NOT_CERTIFIED",
            "allowed_repair_or_backfill": False,
            "source_authenticity_certified": False,
            "confirmed_missing_count": 0,
            "observations": list(items),
        },
    }


class V2G5TruncatedAuditUITests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="v2g5-synthetic-")
        self.addCleanup(temp.cleanup)
        state = Path(temp.name) / "ParquetLiveSync"
        state.mkdir()
        try:
            with mock.patch.object(base, "observe_qmt_connection",
                                   side_effect=AssertionError("QMT forbidden")), \
                 mock.patch.object(base, "inspect_recovery_prerequisites",
                                   side_effect=AssertionError("finance forbidden")), \
                 mock.patch.object(UI, "inventory_historical_versions",
                                   side_effect=AssertionError("finance read forbidden")):
                self.app = UI.MarketCenterV2SelectedUI(state_module=state)
        except tk.TclError as exc:
            if ("display" in str(exc).lower()
                    or "couldn't connect" in str(exc).lower()):
                self.skipTest("No Tk display: " + str(exc))
            raise
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def _one_visible_row(self):
        first = observation("000001.SZ")
        ident = self.app.audit_table.insert(
            "", "end",
            values=("day", first["symbol"], first["label_day"], 1,
                    first["physical_status"], "存在记录，未认证"))
        self.app.audit_table_rows[ident] = first
        return first

    def _poll_no_io(self):
        with mock.patch.object(base.MarketCenterV2, "_poll_audit"):
            self.app._poll_audit()

    def test_truncation_disclosed_and_full_evidence_preserved(self):
        first = self._one_visible_row()
        second = observation("600519.SH")
        self.app.audit_raw_report = json.dumps(
            report(first, second), ensure_ascii=False)
        self.app.audit_evidence_note.set("合成审计 · 已解压候选行：2")
        self._poll_no_io()
        self.assertIn("表格仅展示1/2条", self.app.audit_evidence_note.get())
        self.assertIn("表格展示不完整", self.app.audit_flow_next.get())
        self.assertIn("缩小核验范围", self.app.audit_flow_next.get())
        raw = json.loads(self.app.audit_raw_report)
        self.assertEqual(
            len(raw["evidence_interpretation"]["observations"]), 2)
        self.assertEqual(len(self.app.audit_table.get_children()), 1)
        self.assertEqual(self.app.audit_table.item(
            self.app.audit_table.get_children()[0], "values")[1], "000001.SZ")
        self.assertEqual(str(self.app.audit_repair_disabled["state"]),
                         "disabled")

    def test_complete_visible_rows_does_not_claim_truncation(self):
        first = self._one_visible_row()
        self.app.audit_raw_report = json.dumps(report(first))
        self._poll_no_io()
        self.assertNotIn("表格仅展示", self.app.audit_evidence_note.get())
        self.assertNotIn("表格展示不完整", self.app.audit_flow_next.get())
        self.assertEqual(str(self.app.audit_copy_review["state"]), "normal")

    def test_repoll_does_not_append_duplicate_limit_note(self):
        first = self._one_visible_row()
        self.app.audit_raw_report = json.dumps(
            report(first, observation("600519.SH")))
        self._poll_no_io()
        self._poll_no_io()
        self.assertEqual(
            self.app.audit_evidence_note.get().count("表格仅展示"), 1)

    def test_empty_valid_report_does_not_infer_data_completeness(self):
        self.app.audit_raw_report = json.dumps(report())
        self._poll_no_io()
        self.assertNotIn("表格仅展示", self.app.audit_evidence_note.get())
        self.assertIn("没有可供复核", self.app.audit_flow_title.get())
        self.assertEqual(str(self.app.audit_copy_review["state"]), "disabled")


if __name__ == "__main__":
    unittest.main()
