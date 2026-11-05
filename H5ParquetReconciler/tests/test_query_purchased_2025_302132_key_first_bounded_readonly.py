"""Two-phase original 2025 302132 Parquet read-only query source-key gates."""
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "2025_302132_key_first_ohlcva_budget_test",
    HERE.parent / "tools" /
    "query-purchased-2025-302132-key-first-bounded-readonly.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class KeyFirstSourceProbeTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        folder = self.root / "AllCycleAStockData" / "5min"
        folder.mkdir(parents=True)
        self.path = folder / "2025.parquet"
        self.day = date(2025, 2, 17)
        self.keys = sorted(
            M.Q.core.symbol_id("SZ302132") and
            M._load("2025_test_grid_reference",
                    "preview-minute-exact-key-diff-readonly.py"
                    ).normalized_native_keys(self.day, "5min").values())
        self.rows = (
            [(ts, "SZ000001") for ts in self.keys] +
            [(ts, "SZ302132") for ts in self.keys] +
            [(ts, "SH600000") for ts in self.keys]
        )
        self.write()

    def write(self, *, row_group_size=48):
        data = pa.table({
            "ts": pa.array([ts for ts, _ in self.rows], type=pa.int64()),
            "symbol": [sym for _, sym in self.rows],
            "open": [10.] * len(self.rows),
            "high": [12.] * len(self.rows),
            "low": [9.] * len(self.rows),
            "close": [11.] * len(self.rows),
            "volume": [100.] * len(self.rows),
            "amount": [1200.] * len(self.rows),
        })
        pq.write_table(data, self.path, row_group_size=row_group_size)

    def q(self, **kwargs):
        return M.query_bars(
            self.root, "SZ302132", "5min", "2025-02-17",
            "2025-02-17", max_candidate_rows=2000,
            max_result_bars=1000, **kwargs)

    def test_key_first_finds_only_target_rowgroup_before_ohlcva(self):
        observed = []
        orig = pq.ParquetFile.iter_batches
        def tracked(pf, *args, **kwargs):
            observed.append((tuple(kwargs.get("row_groups", [])),
                             tuple(kwargs.get("columns", []))))
            yield from orig(pf, *args, **kwargs)
        with patch.object(pq.ParquetFile, "iter_batches", tracked), \
             patch.object(M.Q.diagnose, "might_contain_symbols", return_value=True):
            result = self.q()
        safe = result["safe_summary"]
        self.assertEqual(safe["matching_bar_count"], 48)
        self.assertEqual(safe["physical_ohlcva_rowgroups_read"], 1)
        self.assertEqual(safe["physical_ohlcva_source_rows_read"], 48)
        self.assertEqual(safe["key_only_source_rows_scanned"], 144)
        paid = [(r,c) for r,c in observed if "open" in c]
        self.assertEqual(paid, [((1,), tuple(M.Q.NEEDED))])
        self.assertTrue(all(c == ("ts","symbol") for r,c in observed if "open" not in c))
        self.assertTrue(safe["keys_equal_between_key_probe_and_ohlcva"])
        self.assertFalse(safe["production_query_activated"])
        self.assertFalse(safe["licensed_bar_cache_written"])

    def test_ohlcva_budget_stops_after_key_only_discovery(self):
        orig = pq.ParquetFile.iter_batches
        def refuse_paid(pf, *args, **kwargs):
            if "open" in kwargs.get("columns", []):
                raise AssertionError("OHLCVA columns must remain unopened")
            yield from orig(pf, *args, **kwargs)
        with patch.object(pq.ParquetFile, "iter_batches", refuse_paid), \
             self.assertRaisesRegex(ValueError, "OHLCVA rowgroup budget"):
            self.q(max_ohlcva_rows=40)

    def test_nonstandard_target_keys_fail_before_ohlcva_columns(self):
        # A source day with only 47 purchased five-minute keys must NEVER
        # advance to paid bar values, even if its full physical RG fits.
        self.rows.remove((self.keys[-1], "SZ302132"))
        self.write()
        original = pq.ParquetFile.iter_batches
        def refuse_paid(pf, *args, **kwargs):
            if "open" in kwargs.get("columns", []):
                raise AssertionError("Paid columns opened before native session grid")
            yield from original(pf, *args, **kwargs)
        with patch.object(pq.ParquetFile, "iter_batches", refuse_paid), \\
             self.assertRaisesRegex(ValueError, "nonstandard time keys before OHLCVA"):
            self.q()

    def test_evidence_scoped_2250000_cap_is_not_unbounded(self):
        self.assertEqual(M.MAX_OHLCVA_ROWS, 2250000)
        result = self.q()
        safe = result["safe_summary"]
        self.assertTrue(safe["native_session_grid_checked_before_ohlcva"])
        self.assertTrue(safe["generic_purchased_query_budget_unchanged"])
        self.assertEqual(safe["physical_ohlcva_rows_budget"], 2000)
        with self.assertRaisesRegex(ValueError, "bounded"):
            self.q(max_ohlcva_rows=M.MAX_OHLCVA_ROWS+1)

    def test_key_only_preflight_budget_fails_before_any_value_read(self):
        with self.assertRaisesRegex(ValueError, "key-only metadata budget"):
            self.q(max_key_only_rows=50)

    def test_empty_target_day_returns_no_ohlcva_reads(self):
        self.rows = [(stamp, "SZ000001") for stamp in self.keys]
        self.write()
        result = self.q()
        self.assertEqual(result["bars"], [])
        self.assertEqual(result["safe_summary"]["physical_ohlcva_rowgroups_read"], 0)

    def test_duplicate_target_keys_rejected_before_paid_decoding(self):
        self.rows.append(self.rows[48])
        self.write()
        with self.assertRaisesRegex(ValueError, "Duplicate original target timestamp"):
            self.q()

    def test_no_bshare_or_unknown_code_permission(self):
        for symbol in ("SH900901", "SZ200123", "SZ302999", "SZ300114"):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                M.query_bars(self.root, symbol, "5min",
                             "2025-02-17", "2025-02-17")

    def test_query_source_parquet_mtime_and_size_not_modified(self):
        before = (self.path.stat().st_size, self.path.stat().st_mtime_ns)
        self.q()
        self.assertEqual(before, (self.path.stat().st_size,
                                  self.path.stat().st_mtime_ns))


if __name__ == "__main__":
    unittest.main(verbosity=2)
