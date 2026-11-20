"""Offline QMT service probe tests: never import xtquant or contact QMT."""
from __future__ import annotations

from types import SimpleNamespace
import subprocess
import sys
import unittest
from unittest.mock import patch

import qmt_connect_preflight as Q


def completed(*, code=0, stdout=Q.CONNECT_SENTINEL + "\n", stderr=""):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


class ProbeContractTests(unittest.TestCase):
    def test_successful_get_client_marker(self):
        calls = []
        def fake_run(argv, **options):
            calls.append((argv, options))
            return completed()
        ready, detail = Q.probe_once(runner=fake_run)
        self.assertTrue(ready)
        self.assertEqual(detail, "xtdata_get_client_connected")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][:4], [sys.executable, "-u", "-B", "-c"])
        self.assertIn("xtdata.get_client()", calls[0][0][4])
        self.assertNotIn("download", calls[0][0][4])
        self.assertTrue(calls[0][1]["capture_output"])
        self.assertEqual(calls[0][1]["timeout"], 25)

    def test_nonzero_exit_is_unavailable_even_with_marker(self):
        ready, detail = Q.probe_once(runner=lambda *a, **k: completed(
            code=1, stderr="Exception: 无法连接xtquant服务"))
        self.assertFalse(ready)
        self.assertIn("xtdata_exit_1", detail)
        self.assertIn("无法连接", detail)

    def test_zero_exit_without_marker_fails_closed(self):
        ready, detail = Q.probe_once(
            runner=lambda *a, **k: completed(stdout="vendor printed but never connected"))
        self.assertFalse(ready)
        self.assertIn("sentinel_missing", detail)

    def test_vendor_startup_hang_is_bounded(self):
        def blocked(_args, **kwargs):
            self.assertEqual(kwargs["timeout"], 25)
            raise subprocess.TimeoutExpired(cmd="qmt", timeout=25)
        ready, detail = Q.probe_once(runner=blocked)
        self.assertFalse(ready)
        self.assertEqual(detail, "client_probe_timeout_25s")

    def test_worker_spawn_failure_not_reported_connected(self):
        def blocked(_args, **kwargs):
            raise FileNotFoundError("fictional missing interpreter")
        ready, detail = Q.probe_once(runner=blocked)
        self.assertFalse(ready)
        self.assertIn("FileNotFoundError", detail)

    def test_invalid_timeout_rejected_before_vendor_call(self):
        def must_not_call(*args, **kwargs):
            self.fail("vendor runner must never be called")
        for value in (0, 31, 4, True, "25"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    Q.probe_once(timeout_seconds=value, runner=must_not_call)

    def test_cli_success_and_failure_codes_without_qmt(self):
        with patch.object(Q, "probe_once", return_value=(True, "ok")):
            self.assertEqual(Q.main([]), 0)
        with patch.object(Q, "probe_once", return_value=(False, "offline")):
            self.assertEqual(Q.main([]), 3)

    def test_probe_is_one_attempt_not_self_retrying(self):
        count = [0]
        def rejected(*args, **kwargs):
            count[0] += 1
            return completed(code=1, stdout="", stderr="connection unavailable")
        self.assertFalse(Q.probe_once(runner=rejected)[0])
        self.assertEqual(count[0], 1)

    def test_static_child_only_tests_connection(self):
        self.assertIn("xtdata.get_client()", Q.CHILD)
        for forbidden in ("download_history", "download_financial",
                          "get_market_data", "get_financial_data", "write_parquet"):
            self.assertNotIn(forbidden, Q.CHILD)


if __name__ == "__main__":
    unittest.main()
