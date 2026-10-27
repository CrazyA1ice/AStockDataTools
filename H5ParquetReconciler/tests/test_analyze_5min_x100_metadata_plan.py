"""Footer-only Parquet cost estimation; all synthetic, no licensed stock data."""
import importlib.util
import json
import types
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location(
    "focused_metadata_plan", HERE / "analyze-5min-x100-focused-sessions.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
DAY = date(2026, 9, 28)


class FakeGroup:
    def __init__(self, low_ts=None, high_ts=None,
                 low_symbol=None, high_symbol=None, rows=100):
        self.num_rows = rows
        self.total_byte_size = rows * 24
        def stats(low, high):
            if low is None or high is None:
                return None
            return types.SimpleNamespace(has_min_max=True, min=low, max=high)
        self.columns = [
            types.SimpleNamespace(path_in_schema="ts",
                                  statistics=stats(low_ts, high_ts)),
            types.SimpleNamespace(path_in_schema="symbol",
                                  statistics=stats(low_symbol, high_symbol))]
        self.num_columns = len(self.columns)

    def column(self, i):
        return self.columns[i]


class FakeMetadata:
    def __init__(self, groups):
        self.groups = groups
        self.num_row_groups = len(groups)

    def row_group(self, i):
        return self.groups[i]


def fixture():
    _, _, left, right = M.core.parse_day_range(
        2026, DAY.isoformat(), DAY.isoformat())
    return FakeMetadata([
        FakeGroup(left-86400000, left-3600000,
                  "600000.XSHG", "600001.XSHG", rows=900),
        FakeGroup(left, left+60000,
                  "601000.XSHG", "601999.XSHG", rows=400),
        FakeGroup(left, right-60000,
                  "600000.XSHG", "600001.XSHG", rows=100),
        FakeGroup(left, right-60000,
                  None, None, rows=150),
        FakeGroup(None, None, None, None, rows=50),
    ])


class ParquetMetadataPlanTests(unittest.TestCase):
    def test_time_and_symbol_minmax_prune_without_reading_ohlcv(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "2026-pq-5min.parquet"
            result = M.row_group_read_cost(
                [(path, fixture())], ("SH600000",), DAY)
        self.assertEqual(result["parquet_files"], 1)
        self.assertEqual(result["row_groups_total"], 5)
        self.assertEqual(result["row_groups_skipped_by_time_metadata"], 1)
        self.assertEqual(result["row_groups_skipped_by_symbol_min_max"], 1)
        self.assertEqual(result["row_groups_candidate_to_decode"], 3)
        self.assertEqual(result["candidate_source_rows_upper_bound"], 300)
        self.assertEqual(result["candidate_uncompressed_bytes_upper_bound"], 7200)
        self.assertFalse(result["ohlcv_column_values_read"])
        self.assertFalse(result["candidate_rows_are_selected_symbol_rows"])

    def test_complete_locator_filters_before_metadata_with_strict_identity(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "pq.parquet"
            keys = {str(path.resolve()): {2, 4}}
            result = M.row_group_read_cost(
                [(path, fixture())], ("SH600000",), DAY, keys)
            self.assertEqual(result["row_groups_skipped_by_completed_index"], 3)
            self.assertEqual(result["row_groups_skipped_by_time_metadata"], 0)
            self.assertEqual(result["row_groups_candidate_to_decode"], 2)
            self.assertEqual(result["candidate_source_rows_upper_bound"], 150)
            self.assertEqual(result["row_groups_total"], 5)
            with self.assertRaisesRegex(ValueError, "no entry for source"):
                M.row_group_read_cost(
                    [(path, fixture())], ("SH600000",), DAY,
                    {str(Path(d)/"other.parquet"): {2, 4}})

    def test_unavailable_statistics_fail_open_without_dropping_possible_rows(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "pq.parquet"
            meta = FakeMetadata([
                FakeGroup(None, None, None, None, rows=123),
                FakeGroup(None, None, "ZZZ", "AAA", rows=124)])
            out = M.row_group_read_cost([(path, meta)], ("SH600000",), DAY)
            self.assertEqual(out["row_groups_candidate_to_decode"], 2)
            self.assertEqual(out["candidate_source_rows_upper_bound"], 247)

    def test_empty_completed_index_is_safe_when_verified_upstream(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "pq.parquet"
            result = M.row_group_read_cost(
                [(path, fixture())], ("SH600000",), DAY,
                {str(path.resolve()): set()})
            self.assertEqual(result["row_groups_candidate_to_decode"], 0)
            self.assertEqual(result["row_groups_skipped_by_completed_index"], 5)
            self.assertEqual(result["candidate_source_rows_upper_bound"], 0)

    def test_plan_only_cli_never_loads_market_bar_columns(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            module = tmp / "module"
            (module / "reports").mkdir(parents=True)
            (module / "tools").mkdir()
            input_file = tmp / "existing-exact-masks.json"
            input_file.write_text('{"format": "synthetic"}', encoding="utf-8")
            output = module / "reports" / "metadata-plan.json"
            work = module / "work" / "_union_scratch"
            expected = {
                "parquet_files": 1, "row_groups_total": 2,
                "row_groups_candidate_to_decode": 1,
                "candidate_source_rows_upper_bound": 200,
                "ohlcv_column_values_read": False,
            }
            with (patch.object(M, "HERE", module / "tools"),
                  patch.object(M.core, "resolve_module_artifact_paths",
                               return_value=(output, work)),
                  patch.object(M.core, "resolve_safe_paths",
                               return_value=(tmp / "stock", output, work)),
                  patch.object(M, "load_baseline",
                               return_value={"SH600000": {"volume": 1}}),
                  patch.object(M, "plan_with_footers", return_value=expected),
                  patch.object(M.diagnose, "load_h5") as h5,
                  patch.object(M.diagnose, "load_parquet") as pq):
                M.main([str(tmp / "stock"), "--date", "2026-09-28",
                        "--baseline-report", str(input_file),
                        "--plan-only", "--read-only",
                        "--out", str(output)])
            h5.assert_not_called()
            pq.assert_not_called()
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["format"],
                             "AStockDataTools focused parquet metadata read plan v1")
            self.assertEqual(data["parquet_row_group_plan"], expected)
            self.assertFalse(data["parquet_bar_values_read"])
            self.assertFalse(data["safe_to_automatically_union"])

    def test_incomplete_or_stale_locator_fails_before_any_market_scan(self):
        with TemporaryDirectory() as d:
            tmp = Path(d)
            module = tmp / "module"
            (module / "reports").mkdir(parents=True)
            (module / "tools").mkdir()
            baseline = tmp / "exact-masks.json"
            baseline.write_text('{"format": "synthetic"}', encoding="utf-8")
            output = module / "reports" / "should-not-exist.json"
            work = module / "work" / "_union_scratch"
            with (patch.object(M, "HERE", module / "tools"),
                  patch.object(M.core, "resolve_module_artifact_paths",
                               return_value=(output, work)),
                  patch.object(M.core, "resolve_safe_paths",
                               return_value=(tmp / "stock", output, work)),
                  patch.object(M, "load_baseline",
                               return_value={"SH600000": {"volume": 1}}),
                  patch.object(M, "resolve_completed_locator",
                               side_effect=ValueError("Index incomplete or fingerprint mismatch")),
                  patch.object(M, "plan_with_footers") as meta,
                  patch.object(M.diagnose, "load_parquet") as pq):
                with self.assertRaises(SystemExit) as caught:
                    M.main([str(tmp / "stock"), "--date", "2026-09-28",
                            "--baseline-report", str(baseline),
                            "--coverage-index", "work/indexes/pq-5min-2025.sqlite",
                            "--plan-only", "--read-only", "--out", str(output)])
            self.assertEqual(caught.exception.code, 2)
            self.assertFalse(output.exists())
            meta.assert_not_called()
            pq.assert_not_called()

    def test_invalid_negative_row_count_and_bad_symbols_refused(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "pq.parquet"
            with self.assertRaisesRegex(ValueError, "negative"):
                M.row_group_read_cost([
                    (path, FakeMetadata([FakeGroup(rows=-1)]))],
                    ("SH600000",), DAY)
            with self.assertRaisesRegex(ValueError, "Symbol must"):
                M.row_group_read_cost([
                    (path, FakeMetadata([FakeGroup(rows=1)]))],
                    ("NOT_A_STOCK",), DAY)


if __name__ == "__main__":
    unittest.main()
