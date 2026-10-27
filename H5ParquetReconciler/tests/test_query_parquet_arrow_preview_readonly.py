"""Synthetic-only tests for explicitly opted-in Arrow Parquet query preview."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

SCRIPT = (Path(__file__).resolve().parents[1] / "tools" /
          "query-parquet-arrow-preview-readonly.py")
SPEC = importlib.util.spec_from_file_location("parquet_arrow_preview", SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
TZ = timezone(timedelta(hours=8))


def stamp(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(
        tzinfo=TZ).timestamp() * 1000)


class ArrowQueryPreviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "licensed stock data (synthetic only)"
        (self.root / "AllCycleAStockData").mkdir(parents=True)

    def row(self, ts, sym="600000.XSHG", amount=101.0):
        return {
            "ts": stamp(ts), "symbol": sym,
            "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
            "volume": 10.0, "amount": amount,
        }

    def write(self, period, filename, rows, rgsize=2):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
            import pyarrow.dataset
        except ImportError:
            self.skipTest("pyarrow unavailable")
        target = self.root / "AllCycleAStockData" / period / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), str(target),
                       row_group_size=rgsize)
        return target

    def test_day_exact_parity_time_and_provenance_with_safe_summary(self):
        self.write("day", "2026-09.parquet", [
            self.row("2026-09-29 08:00"),
            self.row("2026-09-30 08:00"),
            self.row("2026-09-30 08:00", sym="000001.XSHE")
        ], rgsize=1)
        result = M.query_bars(
            self.root, "SH600000", "day", "2026-09-30",
            "2026-09-30", verify_rowgroup=True)
        self.assertEqual(len(result["bars"]), 1)
        self.assertEqual(result["bars"][0]["source_beijing_time"][-5:], "08:00")
        self.assertTrue(result["safe_summary"][
            "rowgroup_exact_equality_verified_this_invocation"])
        self.assertTrue(result["safe_summary"][
            "production_default_engine_unchanged"])
        self.assertEqual(len(result["safe_summary"]["source_stat_manifest_sha256"]), 64)
        wire = json.dumps(result["safe_summary"])
        self.assertNotIn('"open":', wire)
        self.assertNotIn('"volume":', wire)
        self.assertNotIn('"amount":', wire)
        self.assertTrue(result["safe_summary"]["actual_disk_bytes_read_unknown"])

    def test_minute_and_five_minute_exact_parity_and_labels(self):
        for period, times in (
            ("1min", ("09:30", "09:31", "15:00")),
            ("5min", ("09:30", "09:35", "14:55")),
        ):
            with self.subTest(period=period):
                self.write(period, "2026-09.parquet", [
                    self.row("2026-09-30 " + t) for t in times
                ], rgsize=1)
                result = M.query_bars(
                    self.root, "SH600000", period,
                    "2026-09-30", "2026-09-30", verify_rowgroup=True)
                self.assertEqual(
                    [v["source_beijing_time"][-5:] for v in result["bars"]],
                    list(times))
                self.assertTrue(result["safe_summary"][
                    "rowgroup_exact_equality_verified_this_invocation"])

    def test_opt_in_only_and_empty_symbol_does_not_invent_prices(self):
        self.write("5min", "2026-09.parquet", [
            self.row("2026-09-30 09:30", sym="000001.XSHE")])
        with mock.patch.object(
                M.query, "query_bars",
                side_effect=AssertionError("Preview without verify cannot read legacy")):
            result = M.query_bars(
                self.root, "SH600000", "5min",
                "2026-09-30", "2026-09-30")
        self.assertEqual(result["bars"], [])
        self.assertFalse(result["safe_summary"][
            "rowgroup_exact_equality_verified_this_invocation"])
        self.assertEqual(result["safe_summary"]["matching_bar_count"], 0)
        self.assertFalse(result["safe_summary"][
            "local_private_ohlcva_cache_used"])

    def test_duplicate_and_budget_and_invalid_symbol_fail_closed(self):
        self.write("5min", "2026-09.parquet", [
            self.row("2026-09-30 09:30"), self.row("2026-09-30 09:30")
        ], rgsize=1)
        with self.assertRaisesRegex(ValueError, "Duplicate selected"):
            M.query_bars(self.root, "SH600000", "5min",
                         "2026-09-30", "2026-09-30")
        with self.assertRaisesRegex(ValueError, "exceeds --max-candidate-rows"):
            M.query_bars(self.root, "SH600000", "5min",
                         "2026-09-30", "2026-09-30",
                         max_candidate_rows=1)
        with self.assertRaises(ValueError):
            M.query_bars(self.root, "SZ200019", "5min",
                         "2026-09-30", "2026-09-30")

    def test_compare_detects_corrupted_baseline_without_success(self):
        self.write("day", "2026-09.parquet", [
            self.row("2026-09-30 08:00")])
        original = M.query.query_bars
        def corrupted(*args, **kwargs):
            result = original(*args, **kwargs)
            result["bars"][0]["amount"] += 5
            return result
        with mock.patch.object(M.query, "query_bars", side_effect=corrupted):
            with self.assertRaisesRegex(ValueError, "differs from RowGroup"):
                M.query_bars(self.root, "SH600000", "day",
                             "2026-09-30", "2026-09-30",
                             verify_rowgroup=True)

    def test_source_stat_drift_refuses_preview(self):
        self.write("day", "2026-09.parquet", [self.row("2026-09-30 08:00")])
        original = M.query.private_cache.source_signature
        n = [0]
        def changed(*args, **kwargs):
            value = original(*args, **kwargs)
            n[0] += 1
            if n[0] == 2:
                value = dict(value)
                value["manifest_sha256_stat_only"] = "0" * 64
            return value
        with mock.patch.object(
                M.query.private_cache, "source_signature",
                side_effect=changed):
            with self.assertRaisesRegex(ValueError, "manifest changed"):
                M.query_bars(self.root, "SH600000", "day",
                             "2026-09-30", "2026-09-30")

    def test_cli_report_only_no_ohlcva_no_overwrite(self):
        self.write("day", "2026-09.parquet", [
            self.row("2026-09-30 08:00", amount=9876.54321)])
        fake_module = self.base / "H5ParquetReconciler"
        fake_module.mkdir()
        reports = fake_module / "reports"
        reports.mkdir()
        with (mock.patch.object(M, "MODULE", fake_module),
              mock.patch.object(M.query.core, "resolve_module_artifact_paths",
                                side_effect=lambda out: (
                                    (fake_module / out).resolve(),
                                    (fake_module / "work" / "_union_scratch").resolve())),
              mock.patch.object(M.query.core, "resolve_safe_paths",
                                side_effect=lambda root, out, scratch: (
                                    self.root.resolve(), out, scratch))):
            with redirect_stdout(StringIO()):
                M.main([
                    str(self.root), "--symbol", "SH600000", "--period", "day",
                    "--from-date", "2026-09-30", "--to-date", "2026-09-30",
                    "--read-only", "--out", "reports/preview.json",
                    "--verify-rowgroup",
                ])
            output = (reports / "preview.json").read_text(encoding="utf-8")
            self.assertNotIn("9876.54321", output)
            self.assertNotIn('"amount":', output)
            self.assertTrue(json.loads(output)[
                "rowgroup_exact_equality_verified_this_invocation"])
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                M.main([
                    str(self.root), "--symbol", "SH600000", "--period", "day",
                    "--from-date", "2026-09-30", "--to-date", "2026-09-30",
                    "--read-only", "--out", "reports/preview.json",
                ])

if __name__ == "__main__":
    unittest.main()
