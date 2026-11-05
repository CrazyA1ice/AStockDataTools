"""Synthetic source-only 2025 official 300114 -> 302132 timeline contracts."""
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
    "2025_official_code_transition_source_timeline",
    HERE.parent / "tools" /
    "audit-purchased-2025-302132-code-transition-readonly.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class Official2025CodeTransitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        folder = self.root / "AllCycleAStockData" / "5min"
        folder.mkdir(parents=True)
        self.path = folder / "2025.parquet"
        self.rows = []
        self.add_day("SZ302132", date(2025, 1, 2))
        self.add_day("SZ300114", date(2025, 2, 14))
        self.add_day("SZ302132", date(2025, 2, 17))
        self.add_day("SZ302999", date(2025, 2, 18))
        self.add_day("SH600000", date(2025, 2, 18))
        self.write()

    def add_day(self, symbol, day):
        self.rows += [(ts, symbol) for ts in sorted(
            M.SOURCE.D.normalized_native_keys(day, "5min").values())]

    def write(self):
        pq.write_table(pa.table({
            "ts": pa.array([i[0] for i in self.rows], type=pa.int64()),
            "symbol": [i[1] for i in self.rows],
        }), self.path, row_group_size=65)

    def run_audit(self):
        return M.audit_rows(self.root, [self.path], max_source_rows=1000)

    def test_vendor_historic_new_code_flagged_pre_official_change(self):
        result = self.run_audit()
        self.assertEqual(result["scanned_2025_5min_source_rows"], 240)
        self.assertEqual(result["sz302_prefix_actual_source_stockdays"], 3)
        self.assertEqual(result["sz302_prefix_actual_source_rows"], 144)
        self.assertEqual(result["src_302132_pre_effective_history_stockdays"], 1)
        self.assertTrue(result["historical_new_code_present_before_official_code_change"])
        self.assertEqual(result["official_code_change_day"], "2025-02-17")
        self.assertEqual(result["issuer_code_change_old"], "SZ300114")
        self.assertEqual(result["issuer_code_change_new"], "SZ302132")
        self.assertEqual(result["target_security_code_evidence"]["SZ302132"]["observed_stockdays"], 2)
        self.assertEqual(result["target_security_code_evidence"]["SZ300114"]["observed_stockdays"], 1)
        self.assertEqual(result["target_security_code_evidence"]["SZ302999"]["observed_stockdays"], 1)
        self.assertFalse(result["A_share_alias_auto_applied"])
        self.assertFalse(result["source_ohlcva_read"])

    def test_correctly_bounded_actual_old_code_before_new(self):
        self.rows = []
        self.add_day("SZ300114", date(2025, 2, 14))
        self.add_day("SZ302132", date(2025, 2, 17))
        self.write()
        result = self.run_audit()
        self.assertEqual(result["src_302132_pre_effective_history_stockdays"], 0)
        self.assertFalse(result["historical_new_code_present_before_official_code_change"])
        self.assertEqual(result["target_security_code_evidence"]["SZ302132"]["after_or_on_official_effective_stockdays"], 1)

    def test_existing_alias_spellings_are_normalized_without_new_code_mapping(self):
        self.rows = []
        self.add_day("SZSE.302132", date(2025, 2, 17))
        self.write()
        result = self.run_audit()
        self.assertEqual(result["target_security_code_evidence"]["SZ302132"]["observed_stockdays"], 1)
        self.assertEqual(result["raw_symbol_spellings_per_canonical_code"]["SZ302132"], ["SZSE.302132"])

    def test_target_duplicate_key_fails_closed(self):
        self.rows.append(self.rows[0])
        self.write()
        with self.assertRaisesRegex(ValueError, "Duplicate target"):
            self.run_audit()

    def test_no_ohlcva_columns_accessed(self):
        original = pq.ParquetFile.iter_batches
        seen = []
        def restricted(pf, *args, **kwargs):
            seen.append(kwargs.get("columns"))
            if kwargs.get("columns") != ["ts", "symbol"]:
                raise AssertionError("Disallowed licensed bar-column projection")
            yield from original(pf, *args, **kwargs)
        with patch.object(pq.ParquetFile, "iter_batches", restricted):
            result = self.run_audit()
        self.assertEqual(result["src_302132_pre_effective_history_stockdays"], 1)
        self.assertTrue(seen)
        self.assertTrue(all(x == ["ts", "symbol"] for x in seen))

    def test_row_budget_blocks_source_read(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            M.audit_rows(self.root, [self.path], max_source_rows=100)

    def test_source_original_stat_unchanged(self):
        before = (self.path.stat().st_size, self.path.stat().st_mtime_ns)
        self.run_audit()
        self.assertEqual(before, (self.path.stat().st_size,
                                  self.path.stat().st_mtime_ns))


if __name__ == "__main__":
    unittest.main(verbosity=2)
