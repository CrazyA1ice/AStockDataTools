"""Synthetic selected-stock finance cache operation contract tests.

Never calls QMT, spawns the worker, or writes official market data.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
import os
import tkinter as tk
import unittest

import market_simple_ui_model as M
import market_simple_desktop as GUI
import market_update_dashboard as LEGACY


def plan(stocks="000001.SZ,600519.SH", *, mode="增量更新",
         scope="自选股票", modules=None,
         start="2026-11-20", end="2026-11-20"):
    return M.preview_request(
        mode=mode, scope=scope, stocks=stocks,
        start=start, end=end, modules=modules or ["财务"],
        cutoff=date(2026, 11, 21))


class SelectedFinanceContractTests(unittest.TestCase):
    def test_exact_selected_finance_small_window_can_be_staged(self):
        result = M.finance_cache_refresh_scope(plan())
        self.assertEqual(result["symbols"], ["000001.SZ", "600519.SH"])
        self.assertTrue(result["official_finance_parquet_not_modified"])
        self.assertTrue(result["financial_history_conflicts_not_auto_approved"])
        self.assertEqual(result["status"],
                         "QMT_CACHE_REFRESH_SCOPE_VALIDATED_NOT_EXECUTED")

    def test_five_stocks_supported_six_blocked(self):
        code = ",".join(f"{i:06d}.SZ" for i in range(1, 6))
        self.assertEqual(len(M.finance_cache_refresh_scope(
            plan(code))["symbols"]), 5)
        with self.assertRaises(M.InvalidSimplePlan):
            M.finance_cache_refresh_scope(plan(code + ",000006.SZ"))

    def test_31_day_announcements_allowed_32_blocked(self):
        self.assertEqual(M.finance_cache_refresh_scope(
            plan(start="2026-10-21", end="2026-11-20"))["end"],
            "2026-11-20")
        with self.assertRaises(M.InvalidSimplePlan):
            M.finance_cache_refresh_scope(
                plan(start="2026-10-20", end="2026-11-20"))

    def test_no_all_market_or_nonfinancial_side_effect(self):
        for selected in (
            plan(scope="全市场"),
            plan(modules=["八周期行情", "财务"]),
            plan(modules=["板块"]),
            plan(mode="重新下载并比对"),
        ):
            with self.subTest(selected=selected):
                with self.assertRaises(M.InvalidSimplePlan):
                    M.finance_cache_refresh_scope(selected)

    def test_script_reuses_mutex_and_has_bounded_timeout(self):
        script = (Path(__file__).resolve().parents[1] /
                  "run-scoped-qmt-finance-cache.ps1").read_text(
                      encoding="utf-8-sig")
        self.assertIn(r"Local\AStockDataTools2005AllStages", script)
        self.assertIn("WaitOne(0)", script)
        self.assertIn("WaitForExit(300000)", script)
        self.assertIn("SCOPED_FINANCE_CACHE_FAILED=", script)
        self.assertIn("SCOPED_FINANCE_CACHE_READY", script)
        self.assertIn("--mode daily", script)
        self.assertIn("qmt_extra_financial_cache_worker.py", script)
        self.assertIn("Remove-Item -LiteralPath $jobDir", script)
        self.assertNotIn("qmt_extra_financial_cache_import.py", script)
        self.assertNotIn("scheduled-afternoon-update.ps1", script)
        self.assertNotIn(" --apply", script.lower())

    def test_script_requires_canonical_checkout_and_explicit_optin(self):
        script = (Path(__file__).resolve().parents[1] /
                  "run-scoped-qmt-finance-cache.ps1").read_text(
                      encoding="utf-8-sig")
        self.assertIn("EXPLICIT_QMT_CACHE_REFRESH_OPTIN_REQUIRED", script)
        self.assertIn("CANONICAL_CHECKOUT_REQUIRED", script)
        self.assertIn("SCHEDULED_2005_GUARD_WINDOW", script)
        self.assertIn("DATE_AFTER_SAFE_CUTOFF", script)
        self.assertIn("SCOPED_FINANCE_CANONICAL_PARQUET_UNCHANGED=TRUE",
                      script)


class SelectedFinanceGuiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="selected-finance-ui-")
        self.addCleanup(self.temp.cleanup)
        module = Path(self.temp.name) / "ParquetLiveSync"
        (module / "work" / "market_update").mkdir(parents=True)
        work = module / "work"
        try:
            with mock.patch.object(GUI, "WORK", work), \
                 mock.patch.object(LEGACY, "WORK", work), \
                 mock.patch.object(LEGACY, "MODULE", module), \
                 mock.patch.object(GUI.SimpleMarketDashboard,
                                   "_resolve_default_session",
                                   return_value=None):
                self.app = GUI.SimpleMarketDashboard()
        except tk.TclError as exc:
            if "display" in str(exc).lower() or "couldn't connect" in str(exc).lower():
                self.skipTest("Tk display unavailable")
            raise
        self.app.withdraw()
        self.addCleanup(self.app.destroy)

    def _scoped(self):
        self.app.update_scope.set("自选股票")
        self.app._toggle_stock_entry()
        for name, var in self.app.module_vars.items():
            var.set(name == "财务")
        self.app._apply_default_day("2026-11-20", "synthetic fixture")

    def test_scoped_button_enabled_only_for_supported_subset(self):
        self.assertEqual(str(self.app.selected_run_button["state"]),
                         "disabled")
        self._scoped()
        self.assertEqual(str(self.app.selected_run_button["state"]),
                         "normal")
        self.app.update_mode.set("重新下载并比对")
        self.assertEqual(str(self.app.selected_run_button["state"]),
                         "disabled")

    def test_invalid_execution_never_spawns_powershell(self):
        self._scoped()
        self.app.module_vars["八周期行情"].set(True)
        with mock.patch.object(GUI.subprocess, "Popen") as launch, \
             mock.patch.object(GUI.messagebox, "showerror") as error:
            self.app.run_scoped_finance_cache()
        launch.assert_not_called()
        error.assert_called_once()

    @unittest.skipUnless(os.name == "nt",
                         "Only Windows launches native PowerShell")
    def test_approved_scope_still_requires_user_confirmation(self):
        self._scoped()
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "AStockDataTools"
            module = repo / "ParquetLiveSync"
            (repo / ".git").mkdir(parents=True)
            (repo / ".venv" / "Scripts").mkdir(parents=True)
            (repo / ".venv" / "Scripts" / "python.exe").touch()
            module.mkdir()
            (module / "run-scoped-qmt-finance-cache.ps1").touch()
            with mock.patch.object(GUI, "REPO", repo), \
                 mock.patch.object(GUI, "MODULE", module), \
                 mock.patch.object(GUI.messagebox, "askyesno",
                                   return_value=False) as approval, \
                 mock.patch.object(GUI.subprocess, "Popen") as launch:
                self.app.run_scoped_finance_cache()
            approval.assert_called_once()
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
