"""Synthetic contracts for explicit purchased-first, SHA-checked minute research query.

No licensed market rows are included. Tests use a private temporary Parquet
and mocks for all purchased index/source reads; no H5/vendor source modified.
"""
import contextlib
import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "purchased_primary_minute_query_under_test",
    HERE.parent / "tools" /
    "query-purchased-primary-minute-with-private-gap-readonly.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class PurchasedFirstRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.day = date(2026, 10, 13)
        self.sym = "SH600000"
        self.stamp = M.D.I.day_epoch_ms(self.day) + 571 * 60000

    def _run(self, purchased, *, private=False, read_purchased=None,
             read_h5=None, period="1min", limit=1000):
        index = patch.object(M, "locate_index", return_value=Path("unused.sqlite"))
        lookup = patch.object(
            M.D.I, "query_index",
            return_value=({self.sym: purchased} if purchased is not None else {}, {}))
        original = patch.object(
            M.Q, "query_bars", side_effect=read_purchased or
            AssertionError("Original Parquet must not be read"))
        fallback = patch.object(
            M, "_read_verified_private_gap", side_effect=read_h5 or
            AssertionError("Private H5 fallback must not run"))
        with index, lookup, original, fallback:
            return M.query_bars(self.root, self.sym, period,
                                str(self.day), str(self.day),
                                allow_verified_private_h5=private,
                                max_result_bars=limit)

    def _bar(self):
        return {"symbol": self.sym, "period": "1min",
                "trading_date": str(self.day), "source_timestamp_ms": self.stamp,
                "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
                "volume": 100.0, "amount": 1000.0}

    def test_purchased_stockday_always_wins_without_h5_probe(self):
        res = self._run({self.stamp}, private=True,
                        read_purchased=lambda *a, **k: {"bars": [self._bar()]})
        self.assertEqual(res["safe_summary"]["dates"][str(self.day)]["source"],
                         "purchased_parquet")
        self.assertEqual(res["bars"][0]["value_source"], "purchased_parquet")
        self.assertEqual(res["bars"][0]["h5_native_datetime"], None)
        self.assertEqual(res["bars"][0]["symbol"], self.sym)
        self.assertFalse(res["safe_summary"]["production_query_activated"])

    def test_partial_purchased_stockday_still_owns_day(self):
        # A non-full purchased day is NOT permission for H5 to replace it.
        res = self._run({self.stamp}, private=True,
                        read_purchased=lambda *a, **k: {"bars": [self._bar()]})
        self.assertEqual(len(res["bars"]), 1)

    def test_private_gap_requires_explicit_opt_in(self):
        res = self._run(None)
        self.assertEqual(res["bars"], [])
        self.assertEqual(res["safe_summary"]["dates"][str(self.day)]["source"],
                         "no_purchased_source_h5_not_enabled")

    def test_verified_private_gap_used_only_when_purchased_absent(self):
        calls = []
        def fallback(*a, **kw):
            calls.append(a)
            return [dict(self._bar(), value_source="h5_only_complete_stockday")]
        res = self._run(None, private=True, read_h5=fallback)
        self.assertEqual(res["safe_summary"]["bars_by_source"],
                         {"verified_private_h5_gap": 1})
        self.assertEqual(len(calls), 1)
        self.assertTrue(res["safe_summary"]["h5_private_physical_SHA_checked"])

    def test_no_private_receipt_does_not_create_market_rows(self):
        res = self._run(None, private=True, read_h5=lambda *a, **k: [])
        self.assertEqual(res["bars"], [])
        self.assertEqual(res["safe_summary"]["dates"][str(self.day)]["source"],
                         "no_verified_source")

    def test_mismatched_purchased_index_and_rows_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "disagrees"):
            self._run({self.stamp}, read_purchased=lambda *a, **k: {"bars": []})

    def test_missing_index_fails_closed_before_source_read(self):
        with patch.object(M, "locate_index", side_effect=ValueError("No index")):
            with self.assertRaisesRegex(ValueError, "No index"):
                M.query_bars(self.root, self.sym, "1min",
                             str(self.day), str(self.day),
                             allow_verified_private_h5=True)

    def test_read_budget_is_enforced_before_fallback(self):
        res = self._run(None, private=True, limit=1,
                        read_h5=lambda *a, **k: [
                            dict(self._bar(), value_source="h5_only_complete_stockday")])
        self.assertEqual(len(res["bars"]), 1)


class PrivateGapPhysicalChecks(unittest.TestCase):
    def setUp(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.day = date(2026, 10, 13)
        self.symbol = "SH600000"
        self.period = "1min"
        self.relative = (
            "work/unified_parquet/minute_complete_day/minute_123456789abc/"
            "1min-2026-10-13.parquet")
        self.path = self.base / self.relative
        self.path.parent.mkdir(parents=True)
        self.safe = self.base / "reports" / "receipt.json"
        self.safe.parent.mkdir()
        pair = sorted(M.D.normalized_native_keys(self.day, self.period).items())
        self.arrays = {
            "ts": [ts for _, ts in pair],
            "symbol": [self.symbol] * len(pair),
            "period": [self.period] * len(pair),
            "value_source": ["h5_only_complete_stockday"] * len(pair),
            "h5_native_datetime": [native for native, _ in pair],
            "open": [10.0] * len(pair),
            "high": [11.0] * len(pair),
            "low": [9.0] * len(pair),
            "close": [10.5] * len(pair),
            "volume": [100.0] * len(pair),
            "amount": [1000.0] * len(pair),
        }
        self.pa, self.pq = pa, pq
        self._write()
        self._receipt()

    def _write(self):
        self.pq.write_table(self.pa.table(self.arrays), self.path)

    def _receipt(self):
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.safe.write_text(json.dumps({
            "source_day": str(self.day),
            "status": "purchased_first_1min_5min_physical_parquet_unified_readback_only",
            "original_purchased_parquet_or_hikyuu_h5_modified": False,
            "periods": {
                "1min": {
                    "period": "1min",
                    "source_rows": {"h5_only_complete_stockday": 240},
                    "full_merged_source_rows_and_vendor_extra_columns_readback_verified": True,
                    "unified_parquet_relative_file": self.relative,
                    "unified_parquet_sha256": self.sha,
                },
            },
        }), encoding="utf-8")

    @contextlib.contextmanager
    def mocked_previous_verifier(self):
        with patch.object(M.W, "MODULE", self.base), patch.object(
                M.W, "REPORTS", self.base / "reports"), patch.object(
                M.W, "verified_existing_batch", return_value={
                    "safe": str(self.safe), "1min": 240, "5min": 0}):
            yield

    def test_real_synthetic_parquet_sha_and_native_time_checked(self):
        with self.mocked_previous_verifier():
            rows = M._read_verified_private_gap(
                self.day, self.period, self.symbol, max_result_bars=241)
        self.assertEqual(len(rows), 240)
        self.assertEqual(rows[0]["value_source"], "h5_only_complete_stockday")

    def test_modified_parquet_rejected_by_sha(self):
        self.arrays["close"][0] = 10.8
        self._write()
        with self.mocked_previous_verifier():
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                M._read_verified_private_gap(
                    self.day, self.period, self.symbol, max_result_bars=241)

    def test_purchased_provenance_in_fallback_rejected(self):
        self.arrays["value_source"][0] = "purchased_parquet"
        self._write()
        self._receipt()
        with self.mocked_previous_verifier():
            with self.assertRaisesRegex(ValueError, "provenance"):
                M._read_verified_private_gap(
                    self.day, self.period, self.symbol, max_result_bars=241)

    def test_invalid_native_mapping_rejected(self):
        self.arrays["h5_native_datetime"][0] = 202610130932
        self._write()
        self._receipt()
        with self.mocked_previous_verifier():
            with self.assertRaisesRegex(ValueError, "time mapping"):
                M._read_verified_private_gap(
                    self.day, self.period, self.symbol, max_result_bars=241)

    def test_fallback_bar_count_budget_rejected(self):
        with self.mocked_previous_verifier():
            with self.assertRaisesRegex(ValueError, "budget"):
                M._read_verified_private_gap(
                    self.day, self.period, self.symbol, max_result_bars=100)



class MultiSecurityContracts(unittest.TestCase):
    """Batch wrapper must preserve original single-security routing guarantees."""

    def setUp(self):
        self.base = Path("D:/stock")
        self.first = "2026-10-13"
        self.last = "2026-10-13"
        self.stamp = M.D.I.day_epoch_ms(date(2026, 10, 13)) + 571 * 60000

    def _mocked(self, root, symbol, period, first, last, **kwargs):
        source = ("purchased_parquet" if symbol == "SH600000"
                  else "verified_private_h5_gap")
        return {
            "bars": [{
                "symbol": symbol, "source_timestamp_ms": self.stamp,
                "trading_date": self.first, "value_source": source,
            }],
            "safe_summary": {
                "matching_bar_count": 1, "bars_by_source": {source: 1}
            },
        }

    def test_two_security_batch_keeps_source_provenance(self):
        with patch.object(M, "query_bars", side_effect=self._mocked):
            r = M.query_many(
                self.base, ["SH600000", "SZ000001"], "1min",
                self.first, self.last, allow_verified_private_h5=True)
        self.assertEqual(r["safe_summary"]["matching_bar_count"], 2)
        self.assertEqual(r["safe_summary"]["bars_by_source"],
                         {"purchased_parquet": 1,
                          "verified_private_h5_gap": 1})
        self.assertEqual([row["symbol"] for row in r["bars"]],
                         ["SH600000", "SZ000001"])
        self.assertTrue(r["safe_summary"]["no_raw_ohlcva_in_safe_summary"])

    def test_duplicate_security_rejected_before_source_access(self):
        with patch.object(M, "query_bars", side_effect=AssertionError(
                "Purchased should not be read")):
            with self.assertRaisesRegex(ValueError, "Duplicate symbol"):
                M.query_many(
                    self.base, ["SH600000", "SH600000"], "1min",
                    self.first, self.last)

    def test_batch_budget_cannot_silently_truncate(self):
        with patch.object(M, "query_bars", side_effect=self._mocked):
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                M.query_many(
                    self.base, ["SH600000", "SZ000001"], "1min",
                    self.first, self.last, max_total_result_bars=1)

    def test_wrong_security_result_rejected(self):
        def wrong(*args, **kwargs):
            response = self._mocked(*args, **kwargs)
            response["bars"][0]["symbol"] = "SH600001"
            return response
        with patch.object(M, "query_bars", side_effect=wrong):
            with self.assertRaisesRegex(ValueError, "does not belong"):
                M.query_many(
                    self.base, ["SH600000"], "1min",
                    self.first, self.last)

    def test_bad_symbol_or_too_many_symbols_fails_closed(self):
        with self.assertRaises(ValueError):
            M.query_many(self.base, ["600000"], "1min",
                         self.first, self.last)
        with self.assertRaisesRegex(ValueError, "1..8 symbols"):
            M.query_many(self.base, ["SH600000"]*9, "1min",
                         self.first, self.last)

    def test_batch_keeps_h5_opt_in_disabled_by_default(self):
        seen = []
        def capture(*args, **kwargs):
            seen.append(kwargs["allow_verified_private_h5"])
            return self._mocked(*args, **kwargs)
        with patch.object(M, "query_bars", side_effect=capture):
            M.query_many(self.base, ["SH600000"], "1min",
                         self.first, self.last)
        self.assertEqual(seen, [False])


if __name__ == "__main__":
    unittest.main(verbosity=2)
