"""Synthetic tests for pinned detached-worktree, no-download QA gateway."""
from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
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
        self.calls = []

    def fake_run(self, arguments, **kwargs):
        self.calls.append(tuple(arguments))
        return SimpleNamespace(returncode=0, stdout=b"Ran 1 test\nOK")

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

    def test_full_regression_only_after_all_synthetic_pass(self):
        report = G.acceptance(
            self.module, PIN, full=True,
            runner=self.fake_run, git_runner=good_git)
        self.assertEqual(len(report["test_suites"]), 9)
        self.assertEqual(
            report["test_suites"][-1]["suite"],
            "FULL_MARKET_CENTER_REGRESSION")

    def test_failed_suite_stops_before_running_remaining_cases(self):
        def fail_second(arguments, **kwargs):
            self.calls.append(tuple(arguments))
            if len(self.calls) == 2:
                return SimpleNamespace(returncode=1, stdout=b"FAIL")
            return SimpleNamespace(returncode=0, stdout=b"OK")
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

    def test_suite_output_is_bounded_and_no_file_is_persisted(self):
        giant = b"x" * 3000
        def noisy(*args, **kw):
            return SimpleNamespace(returncode=0, stdout=giant)
        outcome = G.execute(["python", "-B", "fake"], self.module, 10,
                            runner=noisy)
        self.assertTrue(outcome["pass"])
        self.assertEqual(len(outcome["output_tail"]), 1800)
        self.assertFalse((self.module / "acceptance.json").exists())


if __name__ == "__main__":
    unittest.main()
