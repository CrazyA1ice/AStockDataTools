"""Offline tests for read-only QMT Capital pending-family census and classification."""
from __future__ import annotations

from pathlib import Path
import tempfile
import json
import unittest
import qmt_capital_conflict_census_readonly as C


def pending(code, table="Capital", asof="2026-11-18"):
    return {"reason": "SOURCE_HISTORY_CONFLICT",
            "detail": "SOURCE_HISTORY_CONFLICT " + code + " table=" +
                      table + " removed_or_revised=1",
            "asof": asof, "attempts": 1}


class CapitalFamilyCensusTests(unittest.TestCase):
    def test_classify_pending_without_any_qmt_call(self):
        state = {"pending": {
            "688227.SH": pending("688227.SH"),
            "688228.SH": pending("688228.SH"),
            "000001.SZ": pending("000001.SZ", "Income"),
            "688259.SH": {"reason": "CACHE_DECODE_ERROR", "asof": "2026-11-18"}},
            "daily_cursor": "688259.SH", "daily_date": "2026-11-18"}
        x = C.summarize(state)
        self.assertEqual(x["pending_total"], 4)
        self.assertEqual(x["capital_conflict_count"], 2)
        self.assertEqual(x["conflict_table_counts"], {"Capital": 2, "Income": 1})
        self.assertEqual(x["reason_counts"]["CACHE_DECODE_ERROR"], 1)
        self.assertFalse(x["all_pending_are_capital"])
        self.assertFalse(x["provider_revisions_proven"])
        self.assertEqual(x["daily_cursor"], "688259.SH")

    def test_representative_exchange_sampling_is_bounded(self):
        keys = ["000001.SZ", "300001.SZ", "600000.SH", "688227.SH",
                "920001.BJ", "688228.SH"]
        state = {"pending": {s: pending(s) for s in keys}}
        samples = C.representative_capital_symbols(state, 5)
        self.assertEqual(len(samples), 5)
        self.assertEqual(len(set(samples)), 5)
        self.assertTrue(any(s.endswith(".BJ") for s in samples))
        self.assertEqual(C.representative_capital_symbols(state, 0), [])
        with self.assertRaises(ValueError):
            C.representative_capital_symbols(state, 6)

    def test_mquarter_only_legacy_rows_are_not_business_field_changes(self):
        previous = [{"_index": "0", "m_timetag": 20260930,
                     "m_quarter": 0., "total_capital": 100.},
                    {"_index": "1", "m_timetag": 20260630,
                     "m_quarter": 110., "total_capital": 105.}]
        fresh = [dict(record) for record in previous]
        fresh[0]["m_quarter"] = 6750319.
        fresh[1]["m_quarter"] = 4294901760.
        result = C.classify_capital(previous, fresh)
        self.assertEqual(result["classification"], "M_QUARTER_ONLY_CANDIDATE")
        self.assertEqual(result["matched_changed_report_keys"], 2)
        self.assertEqual(result["field_change_frequency"], [("m_quarter", 2)])

    def test_any_business_field_change_is_kept_quarantined(self):
        old = [{"_index": "0", "m_timetag": 20260930,
                "m_quarter": 0., "total_capital": 100.}]
        current = [dict(old[0], m_quarter=3., total_capital=102.)]
        result = C.classify_capital(old, current)
        self.assertEqual(result["classification"], "OTHER_FIELDS_OR_KEYS_CHANGED")

    def test_equal_records_irrespective_of_index_order_are_not_conflicts(self):
        old = [{"_index": "0", "m_timetag": 20260930,
                "m_quarter": 0., "total_capital": 100.}]
        fresh = [dict(old[0], _index="999")]
        result = C.classify_capital(old, fresh)
        self.assertEqual(result["classification"], "NO_CHANGE")

    def test_cached_only_sample_uses_existing_cache_and_no_download(self):
        from unittest.mock import patch
        from contextlib import nullcontext, ExitStack
        from collections import Counter
        import qmt_extra_financial_cache_import as I
        import qmt_extra_data as E
        state = {"pending": {"688227.SH": pending("688227.SH")}}
        old = [{"_index": "0", "m_timetag": 20260930, "m_quarter": 0.,
                "total_capital": 100.}]
        updated = [dict(old[0], m_quarter=6750319.)]
        called = []
        def fake_recover(worker, codes, mode, asof, lookback, workspace,
                         timeout, progress):
            called.append((codes, mode))
            return [("688227.SH", {"Capital": updated}, None)]
        with tempfile.TemporaryDirectory() as temp:
            with ExitStack() as stack:
                stack.enter_context(patch.object(
                    I, "_recover_utf8_group", side_effect=fake_recover))
                stack.enter_context(patch.object(
                    I, "_prior_rows", return_value=(
                        "2026-11-17",
                        Counter({E.canonical_json({
                            k: v for k, v in old[0].items() if k != "_index"
                        }): 1}))))
                stack.enter_context(patch.object(
                    E, "_storage", return_value=Path(temp)))
                stack.enter_context(patch.object(
                    E.LIVE, "exclusive_writer", return_value=nullcontext()))
                result = C.sample_cached_only(
                    Path(temp), state, count=1, timeout=180)
        self.assertEqual(called[0][1], "cache")
        self.assertEqual(result["samples"]["688227.SH"]["classification"],
                         "M_QUARTER_ONLY_CANDIDATE")
        self.assertFalse(result["download_called"])
        self.assertFalse(result["canonical_parquet_modified"])

    def test_default_census_reads_existing_json_without_modifying_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "financial-cache-progress.json"
            content = {"format": "qmt_financial_cache_import_v1",
                       "pending": {"688227.SH": pending("688227.SH")}}
            payload = json.dumps(content, ensure_ascii=False).encode("utf-8")
            path.write_bytes(payload)
            loaded = C.read_progress(path)
            self.assertEqual(C.summarize(loaded)["capital_conflict_count"], 1)
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(len(list(Path(temp).iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
