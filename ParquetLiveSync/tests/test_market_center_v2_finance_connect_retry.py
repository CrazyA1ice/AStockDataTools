"""Offline tests for narrowly typed QMT client reconnect; synthetic only.

These tests never import a real xtquant service, touch the production mutex,
write financial Parquet, or call the production 20:05 task.
"""
from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import qmt_extra_financial_cache_import as Importer
import qmt_extra_financial_cache_worker as Worker

SYMBOLS = ["000756.SZ", "000757.SZ"]


def synthetic_payload(symbols, mode):
    return json.dumps({
        "format": "qmt_financial_cache_batch_v1",
        "mode": mode,
        "symbols": symbols,
        "missing_symbols": [],
        "records": {
            sym: {table: [] for table in Importer.E.FIN_TABLES}
            for sym in symbols},
        "row_counts": {
            sym: {table: 0 for table in Importer.E.FIN_TABLES}
            for sym in symbols},
    }, ensure_ascii=False)


class ConnectionRetryTests(unittest.TestCase):
    def launch(self, exits, *, mode="daily", create_unexpected=False):
        calls = []
        status_codes = list(exits)
        events = []
        def run_mock(cmd, **kwargs):
            calls.append(list(cmd))
            index = len(calls) - 1
            if index >= len(status_codes):
                self.fail("worker invoked beyond the supplied bounded exits")
            code = status_codes[index]
            output = Path(cmd[cmd.index("--output") + 1])
            if code == 0 or (code == 86 and create_unexpected):
                output.write_text(
                    synthetic_payload(
                        cmd[cmd.index("--symbols") + 1].split(","),
                        cmd[cmd.index("--mode") + 1]),
                    encoding="utf-8")
            return SimpleNamespace(returncode=code)
        with TemporaryDirectory() as folder:
            with patch.object(Importer.subprocess, "run", side_effect=run_mock):
                with patch.object(Importer, "sleep") as sleep:
                    try:
                        result = Importer._worker_batch(
                            SYMBOLS, mode, "2026-11-20", 120, Path(folder),
                            180, progress=events.append)
                        return calls, sleep.call_args_list, events, result, None
                    except Exception as exc:
                        return calls, sleep.call_args_list, events, None, exc

    def test_outage_then_success_replays_only_same_uncommitted_batch(self):
        calls, sleeps, events, output, exc = self.launch([86, 0])
        self.assertIsNone(exc)
        self.assertEqual(len(calls), 2)
        self.assertEqual([x.args[0] for x in sleeps], [2])
        self.assertEqual(output[1], [])
        self.assertEqual(sorted(output[0]), SYMBOLS)
        self.assertEqual(sum("QMT_CACHE_BATCH_CONNECT_UNAVAILABLE=" in x
                             for x in events), 1)
        self.assertEqual(sum("QMT_CACHE_BATCH_READ=" in x for x in events), 1)
        self.assertEqual(calls[0][calls[0].index("--symbols") + 1],
                         calls[1][calls[1].index("--symbols") + 1])

    def test_two_disconnects_then_success_stops_at_third_process(self):
        calls, sleeps, _events, output, exc = self.launch([86, 86, 0])
        self.assertIsNone(exc)
        self.assertEqual(len(calls), 3)
        self.assertEqual([x.args[0] for x in sleeps], [2, 4])
        self.assertEqual(sorted(output[0]), SYMBOLS)

    def test_three_disconnects_fail_closed_without_fabricated_pending(self):
        calls, sleeps, events, output, exc = self.launch([86, 86, 86])
        self.assertIsNone(output)
        self.assertIsInstance(exc, Importer.QMTCacheConnectionError)
        self.assertIn("batch not checkpointed", str(exc))
        self.assertEqual(len(calls), 3)
        self.assertEqual([x.args[0] for x in sleeps], [2, 4])
        self.assertEqual(sum("QMT_CACHE_BATCH_READ=" in x for x in events), 0)

    def test_failed_group_does_not_become_pending_or_checkpointed(self):
        events = []
        def fail_worker(*args, **kwargs):
            raise Importer.QMTCacheConnectionError(
                "QMT client unavailable after three isolated worker attempts")
        with patch.object(Importer, "_pending_mark") as pending:
            with patch.object(Importer, "_save_state") as checkpoint:
                with self.assertRaises(Importer.QMTCacheConnectionError):
                    Importer._recover_utf8_group(
                        fail_worker, SYMBOLS, "daily", "2026-11-20", 120,
                        Path("not-read"), 180, events.append)
                pending.assert_not_called()
                checkpoint.assert_not_called()
        self.assertFalse(any("DEFERRED" in event for event in events))

    def test_untyped_exit_one_never_retried(self):
        calls, sleeps, _events, output, exc = self.launch([1])
        self.assertIsNone(output)
        self.assertIsInstance(exc, RuntimeError)
        self.assertNotIsInstance(exc, Importer.QMTCacheConnectionError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(sleeps), 0)

    def test_utf8_decode_remains_exactly_one_retry(self):
        calls, sleeps, _events, output, exc = self.launch([85, 85])
        self.assertIsNone(output)
        self.assertIsInstance(exc, Importer.QMTCacheDecodeError)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(sleeps), 0)

    def test_timeout_still_refused_immediately(self):
        with TemporaryDirectory() as folder:
            with patch.object(Importer.subprocess, "run",
                              side_effect=subprocess.TimeoutExpired("fake", 3)) as invoke:
                with patch.object(Importer, "sleep") as sleeper:
                    with self.assertRaises(TimeoutError):
                        Importer._worker_batch(
                            SYMBOLS, "daily", "2026-11-20", 120, Path(folder), 180)
                    invoke.assert_called_once()
                    sleeper.assert_not_called()

    def test_worker_outage_with_output_file_is_rejected(self):
        calls, sleeps, _events, output, exc = self.launch(
            [86], create_unexpected=True)
        self.assertIsNone(output)
        self.assertIsInstance(exc, ValueError)
        self.assertIn("unexpected output", str(exc))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(sleeps), 0)

    def test_cache_mode_outage_retried_without_any_download_arguments(self):
        calls, sleeps, _events, output, exc = self.launch([86, 0], mode="cache")
        self.assertIsNone(exc)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("--start", calls[0])
        self.assertNotIn("--end", calls[1])
        self.assertEqual(output[1], [])

    def test_mixed_recoverable_errors_still_have_bounded_attempts(self):
        calls, sleeps, _events, output, exc = self.launch([85, 86, 86, 0])
        self.assertIsNone(exc)
        self.assertEqual(len(calls), 4)
        self.assertEqual([x.args[0] for x in sleeps], [2, 4])
        self.assertEqual(output[1], [])


class WorkerExceptionTypingTests(unittest.TestCase):
    def call_worker(self, message, *, during="download", mode="daily"):
        invoked = []
        class FakeXT:
            def download_financial_data2(self, *args, **kwargs):
                invoked.append("download")
                if during == "download":
                    raise Exception(message)
            def get_financial_data(self, *args, **kwargs):
                invoked.append("read")
                if during == "read":
                    raise Exception(message)
                return {}
        fake = ModuleType("xtquant")
        fake.xtdata = FakeXT()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "records.json"
            stderr = io.StringIO()
            with patch.dict(sys.modules, {"xtquant": fake}):
                with redirect_stderr(stderr):
                    try:
                        Worker.main([
                            "--symbols", "000756.SZ", "--output", str(path),
                            "--mode", mode,
                            *(["--start", "20260723", "--end", "20261120"]
                              if mode == "daily" else []),
                        ])
                    except BaseException as exc:
                        return exc, stderr.getvalue(), invoked, path.exists()
            return None, stderr.getvalue(), invoked, path.exists()

    def test_exact_xtquant_connection_message_gets_distinct_code(self):
        exc, diagnostic, invoked, written = self.call_worker(
            "无法连接xtquant服务，请检查QMT-投研版或QMT-极简版是否开启")
        self.assertIsInstance(exc, SystemExit)
        self.assertEqual(exc.code, 86)
        self.assertIn("QMT_CACHE_WORKER_CONNECT_UNAVAILABLE=", diagnostic)
        self.assertEqual(invoked, ["download"])
        self.assertFalse(written)

    def test_disconnect_during_cached_read_also_yields_code_86(self):
        exc, diagnostic, invoked, written = self.call_worker(
            "无法连接xtquant服务，请检查QMT-投研版或QMT-极简版是否开启",
            during="read", mode="cache")
        self.assertIsInstance(exc, SystemExit)
        self.assertEqual(exc.code, 86)
        self.assertIn("QMT_CACHE_WORKER_CONNECT_UNAVAILABLE=", diagnostic)
        self.assertEqual(invoked, ["read"])
        self.assertFalse(written)

    def test_unrelated_worker_exception_keeps_ordinary_error_exit(self):
        exc, diagnostic, invoked, written = self.call_worker(
            "SOURCE_HISTORY_CONFLICT synthetic", during="download")
        self.assertIsInstance(exc, Exception)
        self.assertNotIsInstance(exc, SystemExit)
        self.assertNotIn("QMT_CACHE_WORKER_CONNECT_UNAVAILABLE=", diagnostic)
        self.assertFalse(written)


if __name__ == "__main__":
    unittest.main()
