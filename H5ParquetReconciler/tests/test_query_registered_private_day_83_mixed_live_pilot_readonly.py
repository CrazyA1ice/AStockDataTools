"""Fictional, market-I/O-free checks for the SHA-bound 83 mixed daily pilot."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "mixed_private_day_sha_source_pilot_tests",
    HERE.parent / "tools" /
    "query-registered-private-day-83-mixed-live-pilot-readonly.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
EVIDENCE = {
    "version_sha256": M.EXPECTED_VERSION,
    "live_safe": "fictional-live.json",
    "private_keys": "fictional-keys.json",
    "history_ledger": "fictional-ledger.json",
    "source_2016": "fictional-2016.json",
    "source_2026": "fictional-2026.json",
    "mixed_plan": "fictional-mixed.json",
}
SAMPLE_DAY = "2026-01-08"
SAMPLE = ("SH600000", SAMPLE_DAY)


def approved_keys():
    # SH600000..SH600081 represent 82 different 2026 synthetic stockdays;
    # one 2016 item rounds the exact keyset to the prior audited 83.
    keys = {("SH600099", 201609300000)}
    keys.update((f"SH600{i:03d}", 202601080000) for i in range(82))
    return keys


def safe_live():
    symbol, day = SAMPLE
    return {
        "bars": [{
            "symbol": symbol, "period": "day", "trading_date": day,
            "value_source": "private_h5_mixed_stockday_candidate",
            "open": 10.0, "high": 11.0, "low": 9.0,
            "close": 10.5, "volume": 100.0, "amount": 1200.0,
        }],
        "safe_summary": {
            "matching_bar_count": 1,
            "bars_by_source": {
                "purchased_parquet": 0,
                "private_h5_whole_date_candidate": 0,
                "private_h5_mixed_stockday_candidate": 1,
            },
            "period": "day", "symbol": symbol,
            "from_day": day, "through_day": day,
            "registered_private_day_version_sha256": M.EXPECTED_VERSION,
            "registered_private_22274_day_overlay_explicitly_enabled": True,
            "routing": "explicit_immutable_22274_day_live_verified_purchased_first",
            "purchased_source_priority": True,
            "production_query_activated": False,
            "new_market_or_index_files_written": False,
            "original_market_files_modified": False,
            "no_raw_ohlcva_in_safe_summary": True,
        },
    }


class RegisteredMixedDayPilotTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("D:/stock")
        self.config = Path("nonexistent-private-config.json")

    def test_verified_full_keyset_yields_deterministic_2026_sample(self):
        self.assertEqual(M.sample_2026_mixed_key(approved_keys()), SAMPLE)

    def test_rejects_short_or_incomplete_83_keyset(self):
        keys = approved_keys()
        keys.pop()
        with self.assertRaisesRegex(ValueError, "exactly 83"):
            M.sample_2026_mixed_key(keys)

    def test_rejects_quarantined_2026_07_16(self):
        keys = approved_keys()
        keys.remove(("SH600001", 202601080000))
        keys.add(("SH600001", 202607160000))
        with self.assertRaisesRegex(ValueError, "quarantined"):
            M.sample_2026_mixed_key(keys)

    def test_rejects_wrong_2016_2026_distribution(self):
        keys = approved_keys()
        keys.remove(("SH600001", 202601080000))
        keys.add(("SH600001", 201609300000))
        with self.assertRaisesRegex(ValueError, "2016/2026"):
            M.sample_2026_mixed_key(keys)

    def test_rejects_source_symbol_outside_a_share(self):
        keys = approved_keys()
        keys.remove(("SH600001", 202601080000))
        keys.add(("SH900901", 202601080000))
        with self.assertRaisesRegex(ValueError, "approved A-share"):
            M.sample_2026_mixed_key(keys)

    def test_rejects_non_daily_timestamp(self):
        keys = approved_keys()
        keys.remove(("SH600001", 202601080000))
        keys.add(("SH600001", 202601080001))
        with self.assertRaisesRegex(ValueError, "Non-daily"):
            M.sample_2026_mixed_key(keys)

    def test_offline_sample_checks_version_config_and_sha_verified_keys(self):
        with patch.object(M.EVIDENCE, "resolve", return_value=EVIDENCE) as re, \
             patch.object(M.ALL, "load_private_day_config", return_value=EVIDENCE), \
             patch.object(M.KEYS, "verified_existing_plan",
                          return_value=({"a":1}, {2016: [], 2026: []})), \
             patch.object(M.MIXED, "read_verified_key_manifest",
                          return_value=(None,None,None,None,None,approved_keys())):
            proof, symbol, day = M.offline_sample(M.EXPECTED_VERSION, self.config)
        self.assertEqual(proof, EVIDENCE)
        self.assertEqual((symbol, day), SAMPLE)
        re.assert_called_once_with(M.EXPECTED_VERSION)

    def test_offline_rejects_changed_config_before_any_live_query(self):
        with patch.object(M.EVIDENCE, "resolve", return_value=EVIDENCE), \
             patch.object(M.ALL, "load_private_day_config",
                          return_value={**EVIDENCE, "mixed_plan": "wrong"}), \
             patch.object(M.ALL, "query_bars",
                          side_effect=AssertionError("No source I/O permitted")):
            with self.assertRaisesRegex(ValueError, "does not match"):
                M.offline_sample(M.EXPECTED_VERSION, self.config)

    def test_exact_mixed_source_live_result_summary_has_no_symbol_or_prices(self):
        with patch.object(M, "offline_sample",
                          return_value=(EVIDENCE, *SAMPLE)), \
             patch.object(M.ALL, "query_bars", return_value=safe_live()) as query:
            summary = M.query_one(self.root, M.EXPECTED_VERSION, self.config)
        self.assertEqual(summary["bars_by_source"]["private_h5_mixed_stockday_candidate"], 1)
        self.assertTrue(summary["source_security_identifier_redacted"])
        self.assertTrue(summary["live_original_h5_and_purchased_parquet_rechecked"])
        self.assertNotIn(SAMPLE[0], json.dumps(summary))
        self.assertNotIn("open", summary)
        self.assertEqual(query.call_args.kwargs["max_result_bars"], 3)
        self.assertEqual(query.call_args.kwargs["private_day_evidence"], EVIDENCE)

    def test_rejects_unverified_purchased_or_whole_day_source(self):
        for source in ("purchased_parquet", "private_h5_whole_date_candidate"):
            with self.subTest(source=source):
                wrong = safe_live()
                wrong["bars"][0]["value_source"] = source
                with patch.object(M, "offline_sample",
                                  return_value=(EVIDENCE, *SAMPLE)), \
                     patch.object(M.ALL, "query_bars", return_value=wrong):
                    with self.assertRaisesRegex(ValueError, "verified one-stockday"):
                        M.query_one(self.root, M.EXPECTED_VERSION, self.config)

    def test_wrong_counts_are_not_accepted_as_verified(self):
        wrong = safe_live()
        wrong["safe_summary"]["bars_by_source"]["purchased_parquet"] = 1
        with patch.object(M, "offline_sample",
                          return_value=(EVIDENCE, *SAMPLE)), \
             patch.object(M.ALL, "query_bars", return_value=wrong):
            with self.assertRaisesRegex(ValueError, "unsafe or wrong provenance"):
                M.query_one(self.root, M.EXPECTED_VERSION, self.config)

    def test_no_production_activation_allowed(self):
        wrong = safe_live()
        wrong["safe_summary"]["production_query_activated"] = True
        with patch.object(M, "offline_sample",
                          return_value=(EVIDENCE, *SAMPLE)), \
             patch.object(M.ALL, "query_bars", return_value=wrong):
            with self.assertRaisesRegex(ValueError, "unsafe or wrong provenance"):
                M.query_one(self.root, M.EXPECTED_VERSION, self.config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
