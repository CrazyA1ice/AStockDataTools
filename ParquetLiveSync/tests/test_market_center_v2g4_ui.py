"""V2G4 compact evidence-first audit results; synthetic Tk only."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest import mock

import market_center_v2_preview as base
import market_center_v2e_selected_ui as UI


def sample_row(symbol="000001.SZ"):
    return {
        "symbol": symbol, "period": "day", "label_day": "2026-11-20",
        "rows": 1, "physical_status": "ROWS_OBSERVED_UNCERTIFIED",
        "interpretation": "RECORDS_PRESENT_NOT_CERTIFIED", "anomalies": {},
    }


def sample_report(*rows):
    return {
        "scope": {
            "start": "2026-11-20", "end": "2026-11-20",
            "periods": ["day"], "stocks": [r["symbol"] for r in rows],
        },
        "market_file_writes": False, "qmt_calls": 0,
        "evidence_interpretation": {
            "status": "V2B2_EVIDENCE_GATED_CANDIDATES_NOT_CERTIFIED",
            "allowed_repair_or_backfill": False,
            "source_authenticity_certified": False,
            "confirmed_missing_count": 0,
            "observations": list(rows),
        },
    }


class V2G4CompactResultsUITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="v2g4-synthetic-")
        self.addCleanup(self.temp.cleanup)
        module = Path(self.temp.name) / "ParquetLiveSync"
        module.mkdir()
        try:
            with mock.patch.object(base, "observe_qmt_connection",
                                   side_effect=AssertionError("autoQMT")), \
                 mock.patch.object(base, "inspect_recovery_prerequisites",
                                   side_effect=AssertionError("autoFinance")):
                self.app = UI.MarketCenterV2SelectedUI(state_module=module)
        except tk.TclError as exc:
            if ("display" in str(exc).lower()
                    or "couldn't connect" in str(exc).lower()):
                self.skipTest("No Tk display: " + str(exc))
            raise
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def test_action_bar_is_above_resizable_table_and_always_visible(self):
        children = self.app.audit_page.pack_slaves()
        actions = self.app.audit_retry_scope.master
        self.assertLess(children.index(actions),
                        children.index(self.app.audit_split))
        self.assertEqual(len(self.app.audit_split.panes()), 2)

    def test_default_is_human_explanation_not_full_technical_json(self):
        self.assertEqual(self.app.audit_selection_guide.grid_info()["row"], 0)
        self.assertFalse(self.app.audit_raw_visible)
        self.assertEqual(self.app.audit_result_text.winfo_manager(), "")
        self.assertEqual(self.app.audit_raw_scroll.winfo_manager(), "")
        self.assertIn("展开原始", self.app.audit_raw_toggle["text"])
        self.assertEqual(
            str(self.app.audit_repair_disabled["state"]), "disabled")

    def test_raw_toggle_can_reopen_full_original_evidence_without_read(self):
        self.app.audit_raw_report = '{"scope":"synthetic","qmt_calls":0}'
        self.app._set_audit_text(self.app.audit_raw_report)
        with mock.patch.object(self.app, "run_readonly_audit",
                               side_effect=AssertionError("rescanned")):
            self.app.toggle_audit_raw_json()
            self.assertEqual(self.app.audit_result_text.winfo_manager(),
                             "grid")
            self.assertEqual(self.app.audit_raw_scroll.winfo_manager(),
                             "grid")
            self.assertIn("synthetic",
                          self.app.audit_result_text.get("1.0", "end"))
            self.app.toggle_audit_raw_json()
        self.assertFalse(self.app.audit_raw_visible)
        self.assertEqual(self.app.audit_result_text.winfo_manager(), "")

    def test_stock_and_date_are_not_shrunk_below_readable_width(self):
        self.assertGreaterEqual(int(self.app.audit_table.column("symbol")["width"]), 100)
        self.assertGreaterEqual(int(self.app.audit_table.column("date")["width"]), 100)
        total = sum(int(self.app.audit_table.column(col)["width"])
                    for col in self.app.audit_table["columns"])
        self.assertLessEqual(total, 550)

    def test_completed_readonly_report_selects_first_row_and_localizes_status(self):
        first = sample_row()
        second = sample_row("600519.SH")
        self.app.audit_raw_report = json.dumps(sample_report(first, second))
        one = self.app.audit_table.insert(
            "", "end", values=("day", "000001.SZ", "2026-11-20", 1,
                               "ROWS_OBSERVED_UNCERTIFIED", "存在记录，未认证"))
        two = self.app.audit_table.insert(
            "", "end", values=("day", "600519.SH", "2026-11-20", 1,
                               "ROWS_OBSERVED_UNCERTIFIED", "存在记录，未认证"))
        self.app.audit_table_rows[one] = first
        self.app.audit_table_rows[two] = second
        with mock.patch.object(base.MarketCenterV2, "_poll_audit"):
            self.app._poll_audit()
        self.assertEqual(self.app.audit_table.selection(), (one,))
        self.assertEqual(self.app.audit_table.item(one, "values")[1],
                         "000001.SZ")
        self.assertEqual(self.app.audit_table.item(two, "values")[1],
                         "600519.SH")
        self.assertEqual(self.app.audit_table.item(one, "values")[4],
                         "有记录")
        self.assertEqual(self.app.audit_table_rows[one]["physical_status"],
                         "ROWS_OBSERVED_UNCERTIFIED")
        self.assertIn("未认证", self.app.audit_selected_title.get())
        self.assertEqual(str(self.app.audit_copy_review["state"]), "normal")
        self.assertFalse(self.app.audit_raw_visible)
        self.assertEqual(str(self.app.audit_repair_disabled["state"]),
                         "disabled")

    def test_table_renders_bad_physical_status_without_fake_certification(self):
        row = sample_row()
        row["physical_status"] = "ANOMALY_OBSERVED"
        row["interpretation"] = "PHYSICAL_ANOMALY_NEEDS_REVIEW"
        ident = self.app.audit_table.insert(
            "", "end", values=("day", "000001.SZ", "2026-11-20", 1,
                               "ANOMALY_OBSERVED", "物理异常待复核"))
        self.app.audit_table_rows[ident] = row
        self.app.audit_raw_report = json.dumps(sample_report(row))
        with mock.patch.object(base.MarketCenterV2, "_poll_audit"):
            self.app._poll_audit()
        self.assertEqual(self.app.audit_table.item(ident, "values")[4],
                         "物理异常")
        self.assertIn("待复核", self.app.audit_selected_title.get())
        self.assertEqual(str(self.app.audit_repair_disabled["state"]),
                         "disabled")


if __name__ == "__main__":
    unittest.main()
