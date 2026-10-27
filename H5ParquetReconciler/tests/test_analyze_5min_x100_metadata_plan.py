"""Footer-only Parquet cost estimation; all synthetic, no licensed stock data."""
import importlib.util
import types
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

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
