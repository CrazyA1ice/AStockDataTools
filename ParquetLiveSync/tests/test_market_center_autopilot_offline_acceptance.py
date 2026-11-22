"""Synthetic tests for pinned detached-worktree, no-download QA gateway."""
from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import os
import subprocess
import sys
import unittest

import market_autopilot_offline_acceptance as G

PIN = "a" * 40


def good_git(command, **kwargs):
    if command[-2:] == ["rev-parse", "HEAD"]:
        return SimpleNamespace(returncode=0, stdout=(PIN + "\n").encode())
    if command[-3:] == ["symbolic-ref", "-q", "HEAD"]:
        return SimpleNamespace(returncode=1, stdout=b"")
    raise AssertionError("unexpected_git_command: " + repr(command))


class OfflineAcceptanceTests(unittest.TestCase):
    def setUp(self):
        # Mock PowerShell AST validation only for portable harness tests;
        # the real acceptance gate requires Windows parser success.
        ps = patch.object(G, "powershell_ast", return_value="PASS")
        ps.start()
        self.addCleanup(ps.stop)
        self.temp = TemporaryDirectory(prefix="autopilot-review-fixture-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name) / "work" / "autopilot-s7-review"
        root.mkdir(parents=True)
        (root / ".git").write_text(
            "gitdir: synthetic-fixture-only", encoding="utf-8")
        self.module = root / "ParquetLiveSync"
        (self.module / "tests").mkdir(parents=True)
        for name in G.MODULES:
            (self.module / name).write_text(
                "SAFETY_FIXTURE = True\n", encoding="utf-8")
        for name in G.TESTS:
            (self.module / "tests" / name).write_text(
                "SAFETY_TEST_FIXTURE = True\n", encoding="utf-8")
        (self.module / G.POWER_SHELL).write_text(
            "# synthetic fixture only", encoding="utf-8")
        (self.module / "tests" / "test_market_update_dashboard.py").write_text(
            "DASHBOARD_TEST_FIXTURE = True\n", encoding="utf-8")
        self.calls = []

    def fake_run(self, arguments, **kwargs):
        self.calls.append(tuple(arguments))
        return SimpleNamespace(returncode=0, stdout=b"Ran 1 test\nOK")

    def test_powershell_fixture_matches_the_parser_target(self):
        self.assertEqual(G.POWER_SHELL, "run-scoped-qmt-finance-cache.ps1")
        self.assertTrue((self.module / G.POWER_SHELL).is_file())

    def test_standalone_ast_parses_only_known_sources(self):
        self.assertEqual(G.syntax_check(self.module),
                         len(G.MODULES) + len(G.TESTS))

    def test_attached_main_checkout_denied_before_tests(self):
        (self.module.parent / ".git").unlink()
        (self.module.parent / ".git").mkdir()
        with self.assertRaisesRegex(G.OfflineBlocked, "DETACHED_PINNED"):
            G.review_identity(self.module, PIN, runner=good_git)

    def test_nonpinned_detached_checkout_denied(self):
        with self.assertRaisesRegex(G.OfflineBlocked, "HEAD_MISMATCH"):
            G.review_identity(self.module, "b" * 40,
                              runner=good_git)

    def test_branch_worktree_denied_not_detached(self):
        def branch_git(command, **kw):
            if command[-3:] == ["symbolic-ref", "-q", "HEAD"]:
                return SimpleNamespace(returncode=0, stdout=b"refs/heads/main")
            return good_git(command, **kw)
        with self.assertRaisesRegex(G.OfflineBlocked, "NOT_DETACHED"):
            G.review_identity(self.module, PIN, runner=branch_git)

    def test_invalid_or_missing_python_fails_before_subprocess(self):
        path = self.module / G.MODULES[0]
        path.write_text("def = not_python\n", encoding="utf-8")
        with self.assertRaisesRegex(G.OfflineBlocked, "INVALID_PYTHON_AST"):
            G.acceptance(self.module, PIN, runner=self.fake_run,
                         git_runner=good_git)
        self.assertEqual(self.calls, [])

    def test_eight_synthetic_suites_pass_without_full_regression(self):
        report = G.acceptance(
            self.module, PIN, runner=self.fake_run, git_runner=good_git)
        self.assertEqual(report["status"], "OFFLINE_ACCEPTANCE_PASS")
        self.assertEqual(report["python_ast_files"], 16)
        self.assertFalse(report["approved_for_production"])
        self.assertEqual(len(report["test_suites"]), 8)
        self.assertFalse(report["full_regression_requested"])
        self.assertTrue(all(s["pass"] for s in report["test_suites"]))
        self.assertFalse(any("--apply" in a for call in self.calls
                             for a in call))

    def test_non_windows_parser_skip_cannot_claim_acceptance(self):
        with patch.object(G, "powershell_ast",
                          return_value="SKIPPED_NON_WINDOWS"):
            report = G.acceptance(
                self.module, PIN, runner=self.fake_run,
                git_runner=good_git)
        self.assertEqual(report["status"], "OFFLINE_ACCEPTANCE_FAILED")
        self.assertFalse(report["approved_for_production"])

    def test_first_suite_direct_verbose_launch_avoids_discovery(self):
        report = G.acceptance(
            self.module, PIN, runner=self.fake_run, git_runner=good_git)
        self.assertEqual(report["status"], "OFFLINE_ACCEPTANCE_PASS")
        arguments = self.calls[0]
        self.assertIn("-u", arguments)
        self.assertIn("-B", arguments)
        self.assertIn("-v", arguments)
        self.assertIn("test_market_center_autopilot_shadow.py",
                      " ".join(arguments))
        self.assertNotIn("discover", arguments)

    def test_timeout_retains_partial_verbose_case_name(self):
        def hung(args, **kwargs):
            raise subprocess.TimeoutExpired(
                args, kwargs["timeout"],
                output=b"test_health_case (HealthTests) ... ")
        evidence = G.execute(
            ["python", "-B", "synthetic.py"], self.module, 45, runner=hung)
        self.assertFalse(evidence["pass"])
        self.assertEqual(evidence["error"], "TimeoutExpired")
        self.assertEqual(evidence["timeout_seconds"], 45)
        self.assertEqual(evidence["timeout_phase"],
                         "TEST_IN_PROGRESS_OR_TEARDOWN")
        self.assertIn("test_health_case", evidence["output_tail"])

    def test_timeout_without_output_reports_startup_or_import(self):
        def no_output(args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        evidence = G.execute(
            ["python", "-B", "synthetic.py"], self.module, 30,
            runner=no_output)
        self.assertFalse(evidence["pass"])
        self.assertEqual(evidence["timeout_phase"], "STARTUP_OR_IMPORT")
        self.assertEqual(evidence["output_tail"], "")

    def test_first_suite_timeout_stops_other_suites(self):
        def hung(args, **kwargs):
            self.calls.append(tuple(args))
            raise subprocess.TimeoutExpired(args, kwargs["timeout"],
                                            output=b"test_one ... ")
        report = G.acceptance(
            self.module, PIN, full=True,
            runner=hung, git_runner=good_git)
        self.assertEqual(report["status"], "OFFLINE_ACCEPTANCE_FAILED")
        self.assertEqual(len(report["test_suites"]), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(report["test_suites"][0]["timeout_seconds"], 45)
        self.assertFalse(report["approved_for_production"])

    def test_full_regression_only_after_all_synthetic_pass(self):
        report = G.acceptance(
            self.module, PIN, full=True,
            runner=self.fake_run, git_runner=good_git)
        self.assertEqual(
            len(report["test_suites"]),
            len(G.TESTS) + len(G.regression_files(self.module)) + 1)
        names = [x["suite"] for x in report["test_suites"]]
        self.assertEqual(names[:len(G.TESTS)], list(G.TESTS))
        self.assertEqual(names[len(G.TESTS):-1],
                         list(G.regression_files(self.module)))
        self.assertEqual(names[-1], "OPERATOR_DASHBOARD_REGRESSION")
        self.assertNotIn("FULL_MARKET_CENTER_REGRESSION", names)

    def test_full_regression_matches_every_file_in_review_tree(self):
        extra = self.module / "tests" / "test_market_center_legacy_tk.py"
        extra.write_text("LEGACY_GUI_FIXTURE = True\n", encoding="utf-8")
        expected = sorted([*G.TESTS, extra.name])
        self.assertEqual(G.regression_files(self.module), tuple(expected))
        result = G.acceptance(self.module, PIN, full=True,
                              runner=self.fake_run, git_runner=good_git)
        self.assertEqual(result["status"], "OFFLINE_ACCEPTANCE_PASS")
        stages = result["test_suites"][len(G.TESTS):-1]
        self.assertEqual([x["suite"] for x in stages], expected)
        self.assertTrue(all(x["tests_run"] == 1 for x in stages))
        commands = self.calls[len(G.TESTS):-1]
        self.assertEqual(len(commands), len(expected))
        self.assertTrue(all("discover" in cmd and "-p" in cmd and
                            "test_market_center*.py" not in cmd
                            for cmd in commands))

    def test_exact_file_failure_stops_before_other_regression_modules(self):
        failed = "test_market_center_autopilot_ui.py"
        def file_runner(args, **kwargs):
            self.calls.append(tuple(args))
            if "discover" in args and failed in args:
                return SimpleNamespace(
                    returncode=1, stdout=b"Ran 2 tests in 0.01s\nFAILED")
            return SimpleNamespace(returncode=0,
                                   stdout=b"Ran 1 test in 0.01s\nOK")
        result = G.acceptance(
            self.module, PIN, full=True,
            runner=file_runner, git_runner=good_git)
        self.assertEqual(result["status"], "OFFLINE_ACCEPTANCE_FAILED")
        last = result["test_suites"][-1]
        self.assertEqual(last["suite"], failed)
        self.assertEqual(last["tests_run"], 2)
        self.assertIn("FAILED", last["output_tail"])
        self.assertFalse(any("test_market_update_dashboard.py" in cmd
                             for cmd in self.calls))

    def test_zero_case_regression_file_cannot_green_full_gate(self):
        target = "test_market_center_autopilot_ui.py"
        def empty_runner(args, **kwargs):
            if "discover" in args and target in args:
                return SimpleNamespace(returncode=0,
                                       stdout=b"Ran 0 tests in 0.00s\nOK")
            return SimpleNamespace(returncode=0,
                                   stdout=b"Ran 1 test in 0.00s\nOK")
        result = G.acceptance(self.module, PIN, full=True,
                              runner=empty_runner, git_runner=good_git)
        self.assertEqual(result["status"], "OFFLINE_ACCEPTANCE_FAILED")
        self.assertEqual(result["test_suites"][-1]["suite"], target)
        self.assertEqual(result["test_suites"][-1]["error"],
                         "UNITTEST_NO_TESTS_EXECUTED")

    def test_failed_suite_stops_before_running_remaining_cases(self):
        def fail_second(arguments, **kwargs):
            self.calls.append(tuple(arguments))
            if len(self.calls) == 2:
                return SimpleNamespace(returncode=1, stdout=b"FAIL")
            return SimpleNamespace(returncode=0, stdout=b"Ran 1 test\nOK")
        result = G.acceptance(
            self.module, PIN, full=True,
            runner=fail_second, git_runner=good_git)
        self.assertEqual(result["status"], "OFFLINE_ACCEPTANCE_FAILED")
        self.assertEqual(len(result["test_suites"]), 2)
        self.assertFalse(result["approved_for_production"])

    def test_missing_explicit_flag_blocks_before_git_or_unittest(self):
        stream = io.StringIO()
        with patch.object(G, "acceptance") as run, redirect_stdout(stream):
            rc = G.main(["--expected-head", PIN])
        self.assertEqual(rc, 2)
        run.assert_not_called()
        self.assertIn("EXPLICIT_OFFLINE_OPTIN_REQUIRED", stream.getvalue())

    def test_no_apply_or_live_market_root_arguments(self):
        with patch.object(G, "acceptance") as run:
            with self.assertRaises(SystemExit):
                G.main(["--expected-head", PIN, "--explicit-offline-acceptance",
                        "--apply", "--root", "D:/stock"])
        run.assert_not_called()

    def test_long_success_receipt_is_compact_with_exact_test_count(self):
        output = (b"test_case (Suite) ... ok\n" * 700 +
                  b"\nRan 470 tests in 13.125s\n\nOK\n")
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=output)
        result = G.execute(["python", "-B", "test"], self.module, 20,
                           runner=runner)
        self.assertTrue(result["pass"])
        self.assertEqual(result["tests_run"], 470)
        self.assertEqual(result["elapsed_seconds"], 13.125)
        self.assertNotIn("output_tail", result)
        self.assertLess(len(json.dumps(result)), 250)

    def test_failed_suite_keeps_error_and_displays_test_count(self):
        output = (b"Traceback (most recent call last):\n"
                  b"AssertionError: intentional fixture mismatch\n"
                  b"Ran 1 test in 0.01s\nFAILED (failures=1)\n")
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=1, stdout=output)
        result = G.execute(["python", "-B", "test"], self.module, 20,
                           runner=runner)
        self.assertFalse(result["pass"])
        self.assertEqual(result["exit"], 1)
        self.assertEqual(result["tests_run"], 1)
        self.assertIn("AssertionError:", result["output_tail"])

    def test_successful_exit_with_tcl_theme_error_is_not_green(self):
        output = (b"Ran 2 tests in 0.05s\nOK\n"
                  b"can't invoke \"event\" command: application has been "
                  b"destroyed\n(procedure \"ttk::ThemeChanged\")\n")
        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=output)
        report = G.execute(["python", "-B", "test"], self.module, 10,
                           runner=runner)
        self.assertFalse(report["pass"])
        self.assertEqual(report["error"], "TK_THEME_CALLBACK_AFTER_DESTROY")
        self.assertEqual(report["tests_run"], 2)
        self.assertIn("ThemeChanged", report["output_tail"])

    def test_child_env_removes_inspect_even_if_shell_has_zero_string(self):
        observed = {}
        def fake_process(args, **kwargs):
            observed.update(kwargs)
            return SimpleNamespace(
                returncode=0, stdout=b"Ran 1 test in 0.001s\nOK\n")
        with patch.dict(os.environ, {
            "PYTHONINSPECT": "0", "PYTHONSTARTUP": "unsafe-startup.py"
        }):
            result = G.execute(
                ["python", "-B", "synthetic.py"], self.module, 5,
                runner=fake_process)
        self.assertTrue(result["pass"])
        self.assertEqual(result["tests_run"], 1)
        self.assertNotIn("PYTHONINSPECT", observed["env"])
        self.assertNotIn("PYTHONSTARTUP", observed["env"])
        self.assertEqual(observed["stdin"], subprocess.DEVNULL)
        self.assertEqual(observed["env"]["PYTHONDONTWRITEBYTECODE"], "1")

    def test_real_unittest_discover_exits_with_inherited_inspect_flag(self):
        # Exercise the exact subprocess launch mechanism that used to print
        # >>> and hang for 90s after the individual tests had already passed.
        fixture = self.module / "tests" / "test_market_center_repl_probe.py"
        fixture.write_text(
            "import unittest\n"
            "class Probe(unittest.TestCase):\n"
            "    def test_one(self): self.assertTrue(True)\n",
            encoding="utf-8")
        with patch.dict(os.environ, {"PYTHONINSPECT": "0"}):
            result = G.execute([
                sys.executable, "-u", "-B", "-m", "unittest", "discover",
                "-s", "tests", "-p", fixture.name, "-v",
            ], self.module, 15)
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["tests_run"], 1)
        self.assertNotIn("output_tail", result)

    def test_zero_test_unittest_result_fails_closed(self):
        for output in (b"OK", b"Ran 0 tests in 0.00s\nOK"):
            with self.subTest(output=output):
                def runner(*args, **kwargs):
                    return SimpleNamespace(returncode=0, stdout=output)
                raw = G.execute(["python", "-B", "test"], self.module, 10,
                                runner=runner)
                result = G.require_unittest_result(raw)
                self.assertFalse(result["pass"])
                self.assertEqual(result["error"],
                                 "UNITTEST_NO_TESTS_EXECUTED")

    def test_suite_output_is_bounded_and_no_file_is_persisted(self):
        giant = b"x" * 3000
        def noisy(*args, **kw):
            return SimpleNamespace(returncode=0, stdout=giant)
        outcome = G.execute(["python", "-B", "fake"], self.module, 10,
                            runner=noisy)
        self.assertTrue(outcome["pass"])
        self.assertNotIn("output_tail", outcome)
        self.assertFalse((self.module / "acceptance.json").exists())


if __name__ == "__main__":
    unittest.main()
