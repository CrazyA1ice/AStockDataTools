"""Synthetic explicit private daily overlay query; never touches user market data."""
import importlib.util
import json
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


Q = load("query_private_day_overlay_tested", HERE.parent / "tools" /
         "query-parquet-primary-day-overlay-readonly.py")
FIXTURE = load("query_private_day_overlay_fixture",
               HERE / "test_build_parquet_primary_day_overlay.py")


@contextmanager
def prepared_synthetic():
    with FIXTURE.ready() as (root, module, report, gate, original,
                             stage_dir, staged):
        plan = FIXTURE.M.prepare(root, gate, report, [stage_dir])
        with patch.object(Q, "versioner", FIXTURE.M):
            yield root, module, report, gate, original, stage_dir, plan


class ExplicitPrivateDayQueryTests(unittest.TestCase):
    def query(self, root, sha, start="2026-09-30", end="2026-10-08",
              symbol="SH600000", limit=20):
        return Q.query_private_day_overlay(root, symbol, start, end, sha,
                                           max_result_bars=limit)

    def test_purchased_earlier_day_and_private_only_day_exact_once(self):
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            source_sha = FIXTURE.M.stage_tool.file_digest(original)
            result = self.query(root, plan["version_sha256"])
            rows = result["bars"]
            self.assertEqual(len(rows), 2)
            self.assertEqual([x["trading_date"] for x in rows],
                             ["2026-09-30", "2026-10-08"])
            self.assertEqual([x["value_source"] for x in rows], [
                "purchased_parquet", "private_hikyuu_h5_gap_candidate"])
            self.assertEqual(rows[0]["source_beijing_time"][-5:], "00:00")
            self.assertEqual(rows[1]["source_beijing_time"][-5:], "00:00")
            self.assertEqual(rows[1]["open"], 12.3)
            self.assertEqual(rows[1]["volume"], 15000.0)
            safe = result["safe_summary"]
            self.assertEqual(safe["matching_bar_count"], 2)
            self.assertEqual(safe["purchased_parquet_bars_returned"], 1)
            self.assertEqual(safe["private_overlay_bars_returned"], 1)
            self.assertEqual(safe["private_overlay_dates_live_rechecked"],
                             ["2026-10-08"])
            self.assertTrue(safe["no_production_query_switch"])
            self.assertTrue(safe["no_raw_ohlcva_in_safe_summary"])
            self.assertFalse(safe["local_cache_used"])
            self.assertFalse(safe["no_h5_read"])
            self.assertTrue(safe["source_quantity_unit_rescaling_applied"])
            self.assertNotIn('"open": 12.3', json.dumps(safe))
            self.assertNotIn('"volume": 15000', json.dumps(safe))
            self.assertEqual(safe["purchased_parquet_source_rows_scanned"], 1)
            self.assertEqual(
                safe["purchased_parquet_source_rows_per_purchased_bar"], 1.0)
            self.assertEqual(
                safe["private_stage_key_rows_decoded_during_version_verification"], 1)
            self.assertTrue(
                safe["private_stage_version_verification_reads_all_prepared_days"])
            self.assertEqual(
                safe["known_minimum_purchased_plus_stage_rows_decoded"], 3)
            self.assertEqual(safe["known_minimum_rows_per_combined_returned_bar"], 1.5)
            self.assertTrue(safe["known_minimum_excludes_live_h5_pq_absence_recheck_io"])
            self.assertIsNone(safe["source_rows_read_per_returned_bar"])
            self.assertTrue(safe["inherited_source_rows_per_returned_bar_suppressed"])
            self.assertGreaterEqual(safe["query_elapsed_seconds_this_invocation"],
                                    safe["purchased_query_elapsed_seconds_this_invocation"])
            self.assertTrue(safe["elapsed_time_includes_version_stage_checks_and_live_audit"])
            self.assertEqual(FIXTURE.M.stage_tool.file_digest(original),
                             source_sha)

    def test_explicit_query_rechecks_gap_with_one_bounded_live_scan(self):
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            real_batch = FIXTURE.M.stage_tool.verify_live_absence_dates
            with patch.object(
                    FIXTURE.M.stage_tool, "verify_live_absence_dates",
                    wraps=real_batch) as batch, \
                    patch.object(
                        FIXTURE.M.stage_tool, "verify_live_absence",
                        side_effect=AssertionError("redundant per-day scan")):
                result = self.query(root, plan["version_sha256"],
                                    start="2026-10-08", end="2026-10-08")
            batch.assert_called_once()
            self.assertEqual(
                batch.call_args.args[2], {"2026-10-08": 1})
            safe = result["safe_summary"]
            self.assertTrue(safe["live_absence_recheck_single_bounded_scan"])
            self.assertEqual(safe["live_absence_recheck_scan_count"], 1)
            self.assertEqual(safe["live_absence_recheck_h5_in_window_rows"], 1)
            self.assertEqual(safe["live_absence_recheck_purchased_in_window_rows"], 0)
            self.assertEqual(len(result["bars"]), 1)

    def test_baseline_only_query_does_not_claim_private_selected_day_reads(self):
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            result = self.query(root, plan["version_sha256"],
                                start="2026-09-30", end="2026-09-30")
            safe = result["safe_summary"]
            self.assertEqual(len(result["bars"]), 1)
            self.assertEqual(safe["private_overlay_dates_live_rechecked"], [])
            self.assertEqual(safe["live_absence_recheck_scan_count"], 0)
            self.assertFalse(safe["live_absence_recheck_single_bounded_scan"])
            self.assertEqual(safe["private_overlay_bars_returned"], 0)
            self.assertEqual(safe["private_stage_rows_decoded_for_selected_dates"], 0)
            self.assertTrue(safe["no_h5_read"])
            self.assertFalse(safe["source_quantity_unit_rescaling_applied"])
            self.assertIsNone(safe["source_rows_read_per_returned_bar"])
            self.assertEqual(
                safe["private_stage_key_rows_decoded_during_version_verification"], 1)
            self.assertEqual(
                safe["known_minimum_purchased_plus_stage_rows_decoded"],
                safe["purchased_parquet_source_rows_scanned"] + 1)

    def test_empty_unified_result_has_no_false_amplification_ratio(self):
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            result = self.query(root, plan["version_sha256"],
                                start="2026-10-08", end="2026-10-08",
                                symbol="SZ000001")
            safe = result["safe_summary"]
            self.assertEqual(result["bars"], [])
            self.assertIsNone(safe["known_minimum_rows_per_combined_returned_bar"])
            self.assertIsNone(safe["purchased_parquet_source_rows_per_purchased_bar"])
            self.assertEqual(safe["private_stage_rows_decoded_for_selected_dates"], 1)
            self.assertEqual(
                safe["known_minimum_purchased_plus_stage_rows_decoded"],
                safe["purchased_parquet_source_rows_scanned"] + 2)

    def test_prepared_version_not_implicitly_activated(self):
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            self.assertFalse(FIXTURE.M.ACTIVE.exists())
            with patch.object(FIXTURE.M, "read_active",
                              side_effect=AssertionError(
                                  "must not read active production pointer")):
                result = self.query(root, plan["version_sha256"],
                                    start="2026-10-08")
            self.assertEqual(result["safe_summary"]["private_overlay_bars_returned"], 1)
            self.assertFalse(FIXTURE.M.ACTIVE.exists())

    def test_empty_symbol_result_is_not_fabricated(self):
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            response = self.query(root, plan["version_sha256"],
                                  start="2026-10-08", symbol="SZ000001")
            self.assertEqual(response["bars"], [])
            self.assertEqual(response["safe_summary"]["matching_bar_count"], 0)

    def test_nonexistent_version_sha_and_illegal_budget_rejected(self):
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            with self.assertRaisesRegex(ValueError, "Missing private immutable version"):
                self.query(root, "f" * 64)
            with self.assertRaisesRegex(ValueError, "bounded private overlay source-row budget"):
                Q.query_private_day_overlay(
                    root, "SH600000", "2026-10-08", "2026-10-08",
                    plan["version_sha256"], max_overlay_source_rows=0)

    def test_stage_parquet_corruption_blocks_private_query(self):
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            with (stage_dir / "day.parquet").open("ab") as fp:
                fp.write(b"changed-after-private-prepare")
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                self.query(root, plan["version_sha256"],
                           start="2026-10-08")

    def test_new_purchased_day_bar_blocks_expired_gap_evidence(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            target = original.parent / "2026-10.parquet"
            pq.write_table(pa.Table.from_pylist([{
                "ts": FIXTURE.TEST_STAGE.stamp_ms(date(2026, 10, 8)),
                "symbol": "600000.XSHG", "open": 12.3, "high": 12.5,
                "low": 12.2, "close": 12.4, "volume": 15000.0,
                "amount": 1800000.0, "source": "new_purchased"
            }]), target)
            with self.assertRaisesRegex(ValueError, "Live source recheck"):
                self.query(root, plan["version_sha256"],
                           start="2026-10-08")

    def test_combined_result_limit_applies_after_source_merge(self):
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            with self.assertRaisesRegex(ValueError, "Combined private day query"):
                self.query(root, plan["version_sha256"], limit=1)

    def test_tampered_version_envelope_does_not_authorize_query(self):
        with prepared_synthetic() as (root, module, report, gate, original,
                                      stage_dir, plan):
            target = FIXTURE.M.VERSIONS / (plan["version_sha256"] + ".json")
            info = json.loads(target.read_text(encoding="utf-8"))
            info["rows_in_overlay"] = 100
            target.write_text(json.dumps(info), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Tampered"):
                self.query(root, plan["version_sha256"],
                           start="2026-10-08")


if __name__ == "__main__":
    unittest.main(verbosity=2)
