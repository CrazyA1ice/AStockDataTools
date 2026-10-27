"""Synthetic Parquet ts/symbol rowgroup membership pilot tests; no paid K-lines."""
import importlib.util
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location(
    "pilot_2026_5min_month", HERE / "probe-parquet-5min-rowgroup-membership.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
DAY = date(2026, 9, 28)
TARGETS = ("SH688629", "SH688017", "SH688172")


def ms(y, mo, d, h, minute):
    return int(datetime(y, mo, d, h, minute,
                        tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000)


class FakeGroup:
    def __init__(self, low, high, rows, symbol_min=None, symbol_max=None):
        self.num_rows = rows
        self.total_byte_size = rows * 4
        def stats(a, b):
            return (types.SimpleNamespace(has_min_max=True, min=a, max=b)
                    if a is not None and b is not None else None)
        self._cols = [
            types.SimpleNamespace(path_in_schema="ts",
                                  statistics=stats(low, high)),
            types.SimpleNamespace(path_in_schema="symbol",
                                  statistics=stats(symbol_min, symbol_max))
        ]
        self.num_columns = 2

    def column(self, i):
        return self._cols[i]


class FakeBatch:
    def __init__(self, rows):
        self.rows = rows
        self.num_columns = 2
        self.num_rows = len(rows)

    def column(self, i):
        return types.SimpleNamespace(to_pylist=lambda: [
            row[i] for row in self.rows])


class FakeParquetFile:
    schema_arrow = types.SimpleNamespace(
        names=["ts", "symbol", "open", "high", "low", "close", "volume", "amount"])

    def __init__(self, group_rows, bounds=None):
        self.group_rows = group_rows
        if bounds is None:
            bounds = [(None, None)] * len(group_rows)
        self.metadata = types.SimpleNamespace(
            num_row_groups=len(group_rows),
            row_group=lambda i: FakeGroup(
                bounds[i][0], bounds[i][1],
                len(group_rows[i]))
        )
        self.columns_requested = []

    def iter_batches(self, *, row_groups, columns, batch_size, use_threads):
        self.columns_requested.append(list(columns))
        if columns != ["ts", "symbol"]:
            raise AssertionError("Attempted reading licensed OHLCV")
        for group in row_groups:
            yield FakeBatch(self.group_rows[group])


class PilotFiveMinuteMembershipTests(unittest.TestCase):
    def test_evenly_spread_candidate_rowgroup_positions(self):
        self.assertEqual(M.chosen_positions(47, 3), [0, 23, 46])
        self.assertEqual(M.chosen_positions(3, 8), [0, 1, 2])
        self.assertEqual(M.chosen_positions(1, 3), [0])
        self.assertEqual(M.chosen_positions(0, 3), [])
        with self.assertRaises(ValueError):
            M.chosen_positions(47, 0)
        with self.assertRaises(ValueError):
            M.chosen_positions(47, 9)

    def test_2026_metadata_filter_keeps_untrusted_range_and_excludes_past_month(self):
        old = [[(ms(2026, 8, 20, 9, 30), "688629.XSHG")]]
        sept = [[(ms(2026, 9, 28, 9, 30), "688629.XSHG")]]
        pf0 = FakeParquetFile(old, [
            (ms(2026, 8, 20, 9, 30), ms(2026, 8, 20, 9, 30))])
        pf1 = FakeParquetFile(sept, [
            (ms(2026, 9, 28, 9, 30), ms(2026, 9, 28, 9, 30))])
        candidates, total = M.candidate_groups(
            [(Path("2026-08.parquet"), pf0),
             (Path("2026-09.parquet"), pf1)],
            TARGETS, DAY)
        self.assertEqual(total, 2)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0].name, "2026-09.parquet")

    def test_key_only_sample_counts_selected_stocks_and_exact_slots(self):
        source = [
            (ms(2026, 9, 28, 9, 30), "688629.XSHG"),
            (ms(2026, 9, 28, 9, 35), "688629.XSHG"),
            (ms(2026, 9, 28, 9, 35), "688629.XSHG"),
            (ms(2026, 9, 28, 9, 30), "688017.XSHG"),
            (ms(2026, 9, 28, 9, 30), "600000.XSHG"),
            (ms(2026, 9, 27, 9, 30), "688629.XSHG"),
        ]
        result = M.summarize_two_column_batches(
            [FakeBatch(source)], 2026, 20260928, TARGETS)
        self.assertEqual(result["source_rows_examined_in_group"], 6)
        self.assertEqual(result["all_symbol_valid_5min_rows_on_target_day"], 5)
        sh = result["selected_symbols"]["SH688629"]
        self.assertEqual(sh["source_rows_same_symbol_day"], 3)
        self.assertEqual(sh["unique_regular_five_minute_slots"], 2)
        self.assertEqual(sh["duplicate_slot_rows"], 1)
        self.assertFalse(result["selected_symbols"]["SH688172"][
            "symbol_day_present_in_this_group"])
        self.assertTrue(result["sampled_group_contains_any_selected_symbol_day"])

    def test_separated_presence_cannot_license_skipping_unseen_groups(self):
        data = [
            [(ms(2026, 9, 28, 9, 30), "600000.XSHG")],
            [(ms(2026, 9, 28, 9, 30), "688629.XSHG")],
            [(ms(2026, 9, 28, 9, 30), "600001.XSHG")],
            [(ms(2026, 9, 28, 9, 30), "688172.XSHG")],
            [(ms(2026, 9, 28, 9, 30), "600002.XSHG")]
        ]
        pf = FakeParquetFile(data)
        r = M.run_probe([(Path("2026-09.parquet"), pf)], TARGETS, DAY, 3)
        self.assertEqual(r["row_groups_matching_existing_metadata_filter"], 5)
        self.assertEqual(r["sampled_group_count"], 3)
        self.assertEqual(r["sampled_groups_without_selected_keys"], 3)
        self.assertEqual(r["sampled_groups_with_selected_keys"], 0)
        self.assertEqual(r["sampled_source_rows_total"], 3)
        self.assertFalse(r["unsampled_groups_proven_empty"])
        self.assertFalse(r["result_is_eligible_for_query_pruning"])
        self.assertIsNone(r["extrapolated_full_month_speedup"])
        self.assertEqual(pf.columns_requested,
                         [["ts", "symbol"]] * 3)

    def test_sampled_anomalous_time_and_symbol_are_recorded_not_hidden(self):
        source = [
            (None, "688629.XSHG"),
            (ms(2026, 9, 28, 11, 33), "688629.XSHG"),
            (ms(2026, 9, 28, 9, 30), "not-stock"),
        ]
        result = M.summarize_two_column_batches(
            [FakeBatch(source)], 2026, 20260928, TARGETS)
        counts = result["key_parse_anomaly_counts_in_sampled_group"]
        self.assertEqual(counts["bad_timestamp"], 1)
        self.assertEqual(counts["unexpected_session_stamp"], 1)
        self.assertEqual(counts["unrecognized_symbol"], 1)
        self.assertEqual(result["all_symbol_valid_5min_rows_on_target_day"], 0)

    def test_missing_columns_or_mismatched_rows_fail_before_output(self):
        pf = FakeParquetFile([
            [(ms(2026, 9, 28, 9, 30), "688629.XSHG")]])
        pf.schema_arrow = types.SimpleNamespace(names=["symbol", "open"])
        with self.assertRaisesRegex(ValueError, "key columns"):
            M.run_probe([(Path("2026-09.parquet"), pf)], TARGETS, DAY, 1)
        class BrokenParquet(FakeParquetFile):
            def iter_batches(self, *, row_groups, columns, batch_size, use_threads):
                yield FakeBatch([])
        broken = BrokenParquet([[
            (ms(2026, 9, 28, 9, 30), "688629.XSHG")]])
        with self.assertRaisesRegex(ValueError, "differs from footer"):
            M.run_probe([(Path("2026-09.parquet"), broken)], TARGETS, DAY, 1)


if __name__ == "__main__":
    unittest.main()
