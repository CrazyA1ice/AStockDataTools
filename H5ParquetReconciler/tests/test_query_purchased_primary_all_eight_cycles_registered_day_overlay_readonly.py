"""Explicit registered 22,274-day research overlay for the eight-cycle reader.

Only fictional synthetic records and mocks, no real H5/Parquet, prices,
production pointers, user-derived securities, or live paid-source scans.
"""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "allcycle_registered_daily_research_overlay_tests",
    HERE.parent / "tools" /
    "query-purchased-primary-all-eight-cycles-readonly.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

EVIDENCE = {
    "version_sha256": "a" * 64,
    "live_safe": "fictional-live-safe.json",
    "private_keys": "fictional-key-manifest.json",
    "history_ledger": "fictional-ledger.json",
    "source_2016": "fictional-2016-report.json",
    "source_2026": "fictional-2026-report.json",
    "mixed_plan": "fictional-mixed-plan.json",
}
UTC8 = timezone(timedelta(hours=8))


def bar(day, source):
    d = datetime.fromisoformat(day).replace(tzinfo=UTC8)
    return {
        "symbol": "SH600000", "period": "day", "trading_date": day,
        "source_timestamp_ms": int(d.timestamp() * 1000),
        "value_source": source,
        "open": 10.0, "high": 11.0, "low": 9.0,
        "close": 10.5, "volume": 100.0, "amount": 1000.0,
    }


def fake_combined(purchased=1, whole=1, mixed=1):
    grouped = {
        "purchased_parquet": [bar("2026-10-09", "purchased_parquet")][:purchased],
        "private_h5_whole_date_candidate": [
            bar("2026-10-12", "private_h5_whole_date_candidate")][:whole],
        "private_h5_mixed_stockday_candidate": [
            bar("2026-10-13", "private_h5_mixed_stockday_candidate")][:mixed],
    }
    rows = [r for group in grouped.values() for r in group]
    return {
        "bars": rows,
        "safe_summary": {
            "private_combined_version_sha256": EVIDENCE["version_sha256"],
            "matching_stockday_bars": len(rows),
            "total_candidate_rows_in_registered_version": 22274,
            "matched_purchased_stockday_bars": len(grouped["purchased_parquet"]),
            "matched_private_whole_day_stockday_bars":
                len(grouped["private_h5_whole_date_candidate"]),
            "matched_private_mixed_day_stockday_bars":
                len(grouped["private_h5_mixed_stockday_candidate"]),
            "ready_for_production_query": False,
            "ready_for_automatic_market_merge": False,
            "source_market_files_written": False,
            "private_or_production_active_pointer_modified": False,
            "purchased_parquet_replaced": False,
            "no_raw_ohlcva_in_safe": True,
            "candidate_source_units_certified": False,
        },
    }


class EightCycleDayOverlayContracts(unittest.TestCase):
    def setUp(self):
        self.root = Path("D:/stock")
        self.version = {
            "ready_for_production_query": False,
            "candidate_total_new_stockday_rows": 22274,
        }

    def _run(self, response=None, first="2026-10-09", last="2026-10-13",
             period="day", evidence=EVIDENCE):
        with patch.object(M.DAY_PRIVATE.REG, "load_version",
                          return_value=self.version) as loader, \
             patch.object(M.DAY_PRIVATE, "query",
                          return_value=response or fake_combined()) as query:
            result = M.query_bars(
                self.root, "SH600000", period, first, last,
                max_candidate_rows=12000, max_result_bars=20,
                private_day_evidence=evidence)
        return result, loader, query

    def test_explicit_three_source_day_query_preserves_priority_and_provenance(self):
        output, registry, query = self._run()
        safe = output["safe_summary"]
        self.assertEqual(len(output["bars"]), 3)
        self.assertEqual(safe["bars_by_source"], {
            "purchased_parquet": 1,
            "private_h5_whole_date_candidate": 1,
            "private_h5_mixed_stockday_candidate": 1,
        })
        self.assertEqual(safe["registered_private_day_version_sha256"], "a" * 64)
        self.assertTrue(safe["registered_private_22274_day_overlay_explicitly_enabled"])
        self.assertTrue(safe["purchased_source_priority"])
        self.assertFalse(safe["production_query_activated"])
        self.assertFalse(safe["new_market_or_index_files_written"])
        self.assertEqual(query.call_args.kwargs["max_candidate_rows"], 12000)
        self.assertFalse(query.call_args.kwargs["fast_bounded_h5_scan"])
        self.assertEqual(query.call_args.kwargs["max_overlay_source_rows"], 30000)
        self.assertEqual(registry.call_count, 1)
        argv = query.call_args.args
        self.assertNotEqual(argv[-2], argv[-1])
        self.assertIn("eight-cycle-day-22274-live-", str(argv[-2]))
        self.assertIn("eight-cycle-day-22274-safe-", str(argv[-1]))

    def test_non_day_with_private_overlay_is_rejected_before_market(self):
        for period in ("1min", "5min", "15min", "week", "month"):
            with self.subTest(period=period), \
                 self.assertRaisesRegex(ValueError, "exclusively day"):
                M.query_bars(self.root, "SH600000", period,
                             "2026-10-09", "2026-10-13",
                             private_day_evidence=EVIDENCE)

    def test_requires_exact_named_seven_field_evidence(self):
        with self.assertRaisesRegex(ValueError, "seven named"):
            M.query_bars(
                self.root, "SH600000", "day",
                "2026-10-09", "2026-10-13",
                private_day_evidence={"version_sha256": "a" * 64})
        with self.assertRaisesRegex(ValueError, "seven named"):
            M.validate_private_day_evidence({**EVIDENCE, "skip_sha": True})

    def test_rejects_invalid_sha_before_source_query(self):
        with self.assertRaisesRegex(ValueError, "SHA256"):
            M.validate_private_day_evidence({**EVIDENCE, "version_sha256": "latest"})

    def test_outside_validated_2016_2026_years_rejected(self):
        for first, last in (("2025-01-02", "2025-01-03"),
                            ("2016-12-30", "2017-01-02"),
                            ("2026-12-31", "2027-01-01")):
            with self.subTest(first=first), self.assertRaisesRegex(
                    ValueError, "only 2016 or 2026"):
                self._run(first=first, last=last)

    def test_registration_not_found_propagates_fail_closed(self):
        with patch.object(M.DAY_PRIVATE.REG, "load_version",
                          side_effect=ValueError("version absent")), \
             patch.object(M.DAY_PRIVATE, "query",
                          side_effect=AssertionError("should not query")):
            with self.assertRaisesRegex(ValueError, "version absent"):
                M.query_bars(self.root, "SH600000", "day",
                             "2026-10-09", "2026-10-13",
                             private_day_evidence=EVIDENCE)

    def test_declared_production_ready_version_is_rejected(self):
        self.version["ready_for_production_query"] = True
        with self.assertRaisesRegex(ValueError, "not research-only"):
            self._run()

    def test_stale_overlay_source_safe_fields_rejected(self):
        for key, val in (
            ("source_market_files_written", True),
            ("ready_for_production_query", True),
            ("no_raw_ohlcva_in_safe", False),
            ("candidate_source_units_certified", True),
            ("total_candidate_rows_in_registered_version", 22273),
        ):
            with self.subTest(key=key):
                fake = fake_combined()
                fake["safe_summary"][key] = val
                with self.assertRaisesRegex(ValueError, "unsafe or missing"):
                    self._run(response=fake)

    def test_private_provenance_rows_and_safe_counts_must_agree(self):
        fake = fake_combined()
        fake["safe_summary"]["matched_private_mixed_day_stockday_bars"] = 2
        with self.assertRaisesRegex(ValueError, "does not conserve"):
            self._run(response=fake)

    def test_private_row_source_cannot_be_unknown(self):
        fake = fake_combined()
        fake["bars"][1]["value_source"] = "unverified_h5"
        with self.assertRaisesRegex(ValueError, "does not conserve"):
            self._run(response=fake)

    def test_both_private_permission_types_cannot_mix(self):
        with self.assertRaisesRegex(ValueError, "exclusively day"):
            M.query_bars(self.root, "SH600000", "day",
                         "2026-10-09", "2026-10-13",
                         allow_verified_private_h5=True,
                         private_day_evidence=EVIDENCE)

    def test_json_config_path_and_duplicates_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            tools = parent / "tools"
            tools.mkdir()
            conf = parent / "work" / "unified_parquet"
            conf.mkdir(parents=True)
            config = conf / "private_day_research_config.json"
            config.write_text(json.dumps(EVIDENCE), encoding="utf-8")
            with patch.object(M, "HERE", tools):
                loaded = M.load_private_day_config(config)
                self.assertEqual(loaded, EVIDENCE)
                config.write_text('{"version_sha256":"'+("a"*64)+'",'
                                  '"version_sha256":"'+("a"*64)+'"}',
                                  encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Repeated key"):
                    M.load_private_day_config(config)
                outsider = parent / "not_private.json"
                outsider.write_text(json.dumps(EVIDENCE), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "work/unified_parquet"):
                    M.load_private_day_config(outsider)

    def test_default_eight_cycle_does_not_invoke_private_day(self):
        with patch.object(M.DAY_PRIVATE, "query",
                          side_effect=AssertionError("must not access H5")), \
             patch.object(M.PURCHASED, "query_bars",
                          return_value={"bars": [], "safe_summary": {}}):
            safe = M.query_bars(self.root, "SH600000", "day",
                                "2026-10-09", "2026-10-09")["safe_summary"]
        self.assertFalse(safe["registered_private_22274_day_overlay_explicitly_enabled"])
        self.assertFalse(safe["verified_private_h5_fallback_enabled"])
        self.assertEqual(safe["bars_by_source"], {"purchased_parquet": 0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
