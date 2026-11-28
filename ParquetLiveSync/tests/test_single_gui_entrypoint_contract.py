"""Guard one canonical ParquetLiveSync operator UI, no system or market IO."""
from __future__ import annotations
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SingleGUIEntrypointContract(unittest.TestCase):
    def test_01_only_canonical_python_gui_exists(self):
        self.assertTrue((ROOT / "market_update_dashboard.py").is_file())
        self.assertFalse((ROOT / "gui.py").exists())
        self.assertFalse((ROOT / "gui_simple.py").exists())

    def test_02_powershell_gui_launcher_targets_dashboard(self):
        script = (ROOT / "run-gui.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("'market_update_dashboard.py'", script)
        self.assertNotIn("'gui_simple.py'", script)
        self.assertNotIn("'gui.py'", script)
        self.assertNotIn("test_*.py", script)
        self.assertNotIn("eight_cycle_asof_20261013", script)

    def test_03_compat_cmd_launcher_targets_same_dashboard(self):
        script = (ROOT / "start-market-update-dashboard.cmd").read_text(
            encoding="utf-8-sig")
        self.assertIn("market_update_dashboard.py", script)
        self.assertNotIn("gui_simple.py", script)

    def test_04_canonical_dashboard_has_shared_protected_runner(self):
        code = (ROOT / "market_update_dashboard.py").read_text(
            encoding="utf-8-sig")
        self.assertIn('scheduled-afternoon-update.ps1', code)
        self.assertIn('if os.name != "nt" or not (REPO / ".git").is_dir():',code)
        self.assertIn('args.append("-Apply")', code)

    def test_05_no_changes_to_windows_scheduler_from_gui_launchers(self):
        for name in ("run-gui.ps1", "start-market-update-dashboard.cmd"):
            code = (ROOT / name).read_text(encoding="utf-8-sig")
            for forbidden in ("Register-ScheduledTask", "Unregister-ScheduledTask",
                              "SCHTASKS /CREATE", "update-market.ps1 -Mode",
                              "DeleteFile(", "Remove-Item"):
                self.assertNotIn(forbidden, code)


if __name__ == "__main__":
    unittest.main()
