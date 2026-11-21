"""Pinned detached-worktree OFFLINE acceptance for Daily Autopilot S1-S6.

The gate does not fetch QMT data, launch the daily updater, edit a scheduler,
or write official market files. Unit-test fixtures may write temporary data.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

MODULES = (
    "market_daily_autopilot_shadow.py",
    "market_daily_autopilot_view.py",
    "market_simple_ui_model.py",
    "market_daily_calendar_read.py",
    "market_simple_desktop.py",
    "market_scoped_finance_history_review.py",
    "market_scoped_finance_transaction_intent.py",
    "market_scoped_finance_transaction_sandbox.py",
)
TESTS = (
    "test_market_center_autopilot_shadow.py",
    "test_market_center_autopilot_ui.py",
    "test_market_center_simple_desktop.py",
    "test_market_center_scoped_finance_cache.py",
    "test_market_center_scoped_finance_history_review.py",
    "test_market_center_scoped_finance_transaction_intent.py",
    "test_market_center_scoped_finance_transaction_sandbox.py",
    "test_market_center_autopilot_offline_acceptance.py",
)


class OfflineBlocked(ValueError):
    pass


def review_identity(module, head, *, runner=subprocess.run):
    module = Path(module)
    if (not module.is_absolute() or module.is_symlink()
            or module.name != "ParquetLiveSync"
            or not module.is_dir()
            or any(p.is_symlink() for p in module.parents)
            or module.parent.parent.name.lower() != "work"
            or not (module.parent / ".git").is_file()
            or (module.parent / ".git").is_symlink()
            or re.fullmatch(r"[0-9a-f]{40}", head) is None):
        raise OfflineBlocked("DETACHED_PINNED_REVIEW_WORKTREE_REQUIRED")
    def git(*arguments):
        try:
            return runner(
                ["git", "-C", str(module.parent), *arguments],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=12, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OfflineBlocked("GIT_IDENTITY_CHECK_FAILED") from exc
    current = git("rev-parse", "HEAD")
    symbolic = git("symbolic-ref", "-q", "HEAD")
    if (current.returncode != 0 or
            current.stdout.decode("ascii", "ignore").strip() != head or
            symbolic.returncode == 0):
        raise OfflineBlocked("HEAD_MISMATCH_OR_NOT_DETACHED")
    return head


def syntax_check(module):
    names = MODULES + tuple("tests/" + t for t in TESTS)
    for item in names:
        path = module / item
        if (path.is_symlink() or not path.is_file()
                or not 0 < path.stat().st_size <= 1_000_000):
            raise OfflineBlocked("MISSING_OR_LINKED_SOURCE_" + path.name)
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (SyntaxError, UnicodeError, OSError) as exc:
            raise OfflineBlocked("INVALID_PYTHON_AST_" + path.name) from exc
    return len(names)


def execute(args, module, timeout, *, runner=subprocess.run):
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
               PYTHONINSPECT="0", PYTHONPATH=str(module))
    try:
        p = runner(args, cwd=str(module), env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                   timeout=timeout, check=False)
        output = p.stdout or b""
        return {"pass": p.returncode == 0, "exit": p.returncode,
                "output_tail": output.decode("utf-8", "replace")[-1800:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"pass": False, "exit": None,
                "error": type(exc).__name__, "output_tail": ""}


def powershell_ast(module, *, runner=subprocess.run):
    script = module / "run-scoped-qmt-finance-cache.ps1"
    if not script.is_file() or script.is_symlink():
        raise OfflineBlocked("FINANCE_POWERSHELL_MISSING")
    if os.name != "nt":
        return "SKIPPED_NON_WINDOWS"
    quoted = str(script).replace("'", "''")
    code = ("$t=$null;$e=$null;"
            "[System.Management.Automation.Language.Parser]::"
            "ParseFile('" + quoted +
            "',[ref]$t,[ref]$e)|Out-Null;"
            "if($e.Count -ne 0){exit 2};exit 0")
    result = execute(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-Command", code], module, 20, runner=runner)
    if not result["pass"]:
        raise OfflineBlocked("FINANCE_POWERSHELL_AST_FAILED")
    return "PASS"


def acceptance(module, head, *, full=False, runner=subprocess.run,
               git_runner=subprocess.run):
    review_identity(module, head, runner=git_runner)
    parsed = syntax_check(module)
    powershell = powershell_ast(module, runner=runner)
    checks = []
    for name in TESTS:
        result = execute(
            [sys.executable, "-B", "-m", "unittest", "discover",
             "-s", "tests", "-p", name, "-q"],
            module, 180, runner=runner)
        checks.append({"suite": name, **result})
        if not result["pass"]:
            break
    if full and len(checks) == len(TESTS) and all(x["pass"] for x in checks):
        result = execute(
            [sys.executable, "-B", "-m", "unittest", "discover",
             "-s", "tests", "-p", "test_market_center*.py", "-q"],
            module, 600, runner=runner)
        checks.append({"suite": "FULL_MARKET_CENTER_REGRESSION", **result})
    all_pass = (len(checks) >= len(TESTS)
                and all(item["pass"] for item in checks)
                and powershell == "PASS")
    return {
        "status": ("OFFLINE_ACCEPTANCE_PASS" if all_pass
                   else "OFFLINE_ACCEPTANCE_FAILED"),
        "review_head": head,
        "python_ast_files": parsed,
        "powershell_ast": powershell,
        "full_regression_requested": full,
        "test_suites": checks,
        "approved_for_production": False,
        "direct_qmt_download_calls": 0,
        "direct_official_data_writes": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--explicit-offline-acceptance", action="store_true")
    parser.add_argument("--full-regression", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_offline_acceptance:
        print(json.dumps({"status": "EXPLICIT_OFFLINE_OPTIN_REQUIRED",
                          "approved_for_production": False}))
        return 2
    try:
        report = acceptance(
            Path(__file__).absolute().parent, args.expected_head,
            full=args.full_regression)
    except OfflineBlocked as exc:
        print(json.dumps({"status": "OFFLINE_ACCEPTANCE_BLOCKED",
                          "reason": str(exc)[:120],
                          "approved_for_production": False}))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "OFFLINE_ACCEPTANCE_PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
