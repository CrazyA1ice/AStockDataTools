"""Provider-call boundary tests for QMT financial disconnect typing.

Tests use a fake xtquant module and temporary paths only. They neither
connect to a real QMT client nor invoke the financial importer/production job.
"""
from __future__ import annotations

from contextlib import redirect_stderr
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest
from unittest.mock import patch

import qmt_extra_financial_cache_worker as Worker

DISCONNECT = "无法连接xtquant服务，请检查QMT-投研版或QMT-极简版是否开启"
STOCK = "000756.SZ"


class ProviderBoundaryTests(unittest.TestCase):
    def _run(self, fake_api, *, patch_local=None):
        xt = ModuleType("xtquant")
        xt.xtdata = fake_api
        with TemporaryDirectory(prefix="qmt-provider-boundary-") as folder:
            output = Path(folder) / "records.json"
            args = ["--symbols", STOCK, "--output", str(output),
                    "--mode", "cache"]
            with patch.dict(sys.modules, {"xtquant": xt}):
                with redirect_stderr(io.StringIO()) as stderr:
                    try:
                        if patch_local is not None:
                            with patch_local:
                                Worker.main(args)
                        else:
                            Worker.main(args)
                    except BaseException as exc:
                        return exc, stderr.getvalue(), output.exists()
            return None, stderr.getvalue(), output.exists()

    def test_local_path_check_with_same_message_not_typed_as_connection(self):
        class API:
            def get_financial_data(self, *args, **kwargs):
                self.fail("should not reach provider")
        exc, diagnostic, written = self._run(
            API(), patch_local=patch.object(
                Worker.E, "_path_check", side_effect=RuntimeError(DISCONNECT)))
        self.assertIsInstance(exc, RuntimeError)
        self.assertNotIsInstance(exc, Worker.QMTCacheProviderDisconnected)
        self.assertIn("无法连接xtquant服务", str(exc))
        self.assertNotIn("QMT_CACHE_WORKER_CONNECT_UNAVAILABLE=", diagnostic)
        self.assertFalse(written)

    def test_local_conversion_after_successful_qmt_read_not_retried(self):
        class API:
            def get_financial_data(self, *args, **kwargs):
                return {STOCK: {}}
        exc, diagnostic, written = self._run(
            API(), patch_local=patch.object(
                Worker.E, "dataframe_records",
                side_effect=RuntimeError(DISCONNECT)))
        self.assertIsInstance(exc, RuntimeError)
        self.assertNotIsInstance(exc, Worker.QMTCacheProviderDisconnected)
        self.assertNotIn("QMT_CACHE_WORKER_CONNECT_UNAVAILABLE=", diagnostic)
        self.assertFalse(written)

    def test_qmt_api_disconnect_still_returns_dedicated_86(self):
        class API:
            def get_financial_data(self, *args, **kwargs):
                raise Exception(DISCONNECT)
        exc, diagnostic, written = self._run(API())
        self.assertIsInstance(exc, SystemExit)
        self.assertEqual(exc.code, 86)
        self.assertIn("QMT_CACHE_WORKER_CONNECT_UNAVAILABLE=", diagnostic)
        self.assertFalse(written)


if __name__ == "__main__":
    unittest.main()
