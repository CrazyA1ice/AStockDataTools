"""Read-only multi-day quarantine readiness tests with REAL producer adapter.

All project source receipts and candidate Parquet bytes are synthetic and
created under TemporaryDirectory; native QMT and real market data never read.
"""
from __future__ import annotations
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import market_quarantine_recovery_readiness as M
import market_quality_receipt_adapter as A
import market_live_day_overlay_audit as O


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "ParquetLiveSync"
        self.dir = self.root / "work" / "market_update" / "daily"
        self.dir.mkdir(parents=True)
        self.calls = []
        self.day = "2025-06-18"
        self.symbols = ("SH600036", "SZ300119")
        self.create_day(self.day, self.symbols)

    def create_day(self, day, symbols, *, accepted=3, reasons=None):
        folder = self.dir
        parquet = folder / (day + ".parquet")
        parquet.write_bytes(("synthetic-day-candidate-" + day).encode())
        if reasons is None:
            reasons = [
                "ValueError: Independent official DAY materialized OHLC discrepancy: open",
                "ValueError: QMT returned no original OHLCVA 1m: 300119.SZ",
            ]
        doc = {
            "format": A.FORMAT, "date": day,
            "sha256": sha256(parquet.read_bytes()).hexdigest(),
            "rows": accepted * 240, "stock_days_accepted": accepted,
            "expected_stock_days": accepted + len(symbols),
            "quarantined": dict(zip(symbols, reasons)),
            "source_family": "QMT_AND_TDX_OFFICIAL_DAY",
            "production_merge_authorized": False,
        }
        (folder / (day + ".json")).write_text(json.dumps(doc), encoding="utf-8")

    def fake_day(self, root, day, symbol):
        self.calls.append((str(root), day, symbol))
        return {
            "status": O.STATUS, "day": day, "symbol": symbol,
            "day_content_fields_and_target_checked": True,
            "live_state_bytes_sha256": "a" * 64,
            "day_overlay_receipt_bytes_sha256": "b" * 64,
            "day_overlay_parquet_bytes_sha256": "c" * 64,
            "receipt_claimed_raw_tdx_zip_sha256": "d" * 64,
            "target_ohlcva": {"open": 10.0, "high": 10.5, "low": 9.5,
                             "close": 10.2, "volume": 200.0, "amount": 2000.0},
            "whole_exchange_stock_day_universe_certified": False,
            "provider_identity_authenticated": False,
            "qmt_native_1min_verified": False,
            "market_candidate_validated": False,
            "original_nine_quarantines_cleared": False,
            "market_data_write_authorized": False,
            "market_files_written": False,
            "qmt_history_download_calls": 0,
            "tdx_raw_zip_bytes_verified": False,
            "tdx_raw_zip_file_bytes_sha256_if_checked": None,
        }

    def run_day(self, **kwargs):
        return M.inspect(self.root, self.day, self.day,
                         day_inspector=self.fake_day, **kwargs)

    def test_real_producer_adapter_readable_synthetic_receipt(self):
        out = self.run_day()
        self.assertEqual(out["original_producer_quarantined_stock_days"], 2)
        self.assertEqual(len(out["entries"]), 2)
        self.assertEqual(out["producer_accepted_stock_days_reported_not_independently_recounted"], 3)
        self.assertFalse(out["market_quality_cleared"])
        self.assertFalse(out["production_merge_authorized"])
        self.assertFalse(out["original_producer_quarantines_cleared"])
        self.assertEqual(out["qmt_history_download_calls"], 0)

    def test_each_stock_has_day_evidence_and_blocked_state(self):
        out = self.run_day()
        for item in out["entries"]:
            self.assertEqual(item["readiness"], "BLOCKED_REVIEW_ONLY_NO_REPAIR")
            self.assertEqual(item["tdx_day_local_evidence"]["target_day_open"], 10.0)
            self.assertFalse(item["source_independence_authenticated"])
            self.assertFalse(item["minute_market_candidate_approved"])
            self.assertFalse(item["producer_quarantine_cleared"])
            self.assertIn("ORIGINAL_PRODUCER_QUARANTINE_RETAINED",
                          item["unresolved_evidence_requirements"])
            self.assertIn("QMT_NATIVE_MINUTE_BYTES_NOT_INDEPENDENTLY_VERIFIED",
                          item["unresolved_evidence_requirements"])

    def test_original_ohlcva_rejection_needs_separate_first_trade_replay(self):
        item = next(x for x in self.run_day()["entries"] if x["symbol"] == "SH600036")
        self.assertIn("OHLCVA_MISMATCH", item["existing_quality_detected_rules"])
        self.assertIn("EXISTING_OHLCVA_REJECTION_NOT_ADMITTED_AS_REPAIR",
                      item["unresolved_evidence_requirements"])
        self.assertEqual(item["next_readonly_review"],
                         "REPLAY_NATIVE_MINUTE_FIRST_TRADE_WITH_SEPARATE_APPROVAL")

    def test_missing_raw_stock_remains_not_certified_by_day(self):
        item = next(x for x in self.run_day()["entries"] if x["symbol"] == "SZ300119")
        self.assertNotIn("OHLCVA_MISMATCH", item["existing_quality_detected_rules"])
        self.assertEqual(item["next_readonly_review"],
                         "CHECK_NATIVE_MINUTE_SOURCE_COVERAGE_WITH_SEPARATE_APPROVAL")
        self.assertFalse(item["tdx_day_local_evidence"]["qmt_minute_data_certified"])

    def test_quality_backlog_issue_ids_preserved(self):
        report = self.run_day()
        self.assertGreater(report["original_quality_rule_incidents"], 2)
        for item in report["entries"]:
            self.assertTrue(item["original_quality_incident_ids"])
            self.assertTrue(all(len(s) == 64 for s in
                                item["original_quality_incident_ids"]))

    def test_read_only_file_bytes_and_mtime_unchanged(self):
        files = {str(x): (x.read_bytes(), x.stat().st_mtime_ns)
                 for x in self.root.rglob("*") if x.is_file()}
        self.run_day()
        after = {str(x): (x.read_bytes(), x.stat().st_mtime_ns)
                 for x in self.root.rglob("*") if x.is_file()}
        self.assertEqual(files, after)

    def test_report_digest_is_derived_from_entire_nonself_result(self):
        result = self.run_day()
        sha = result.pop("review_sha256")
        self.assertEqual(sha, M.BACKLOG.digest(result))

    def test_second_distinct_day_and_stock_is_reused(self):
        day = "2025-07-18"
        self.create_day(day, ("BJ920021",), reasons=("QMT returned no original OHLCVA 1m",))
        out = M.inspect(self.root, self.day, day, day_inspector=self.fake_day)
        self.assertEqual(out["original_producer_quarantined_stock_days"], 3)
        self.assertEqual({x["trading_day"] for x in out["entries"]},
                         {self.day, day})
        self.assertEqual(len(self.calls), 3)

    def test_day_missing_from_tdx_state_is_review_not_a_trade_halt(self):
        def missing(*args):
            raise O.OverlayError("DAY_NOT_FOUND_IN_PINNED_LIVE_STATE")
        r = M.inspect(self.root, self.day, self.day, day_inspector=missing)
        self.assertEqual(r["day_local_evidence_states"],
                         {"DAY_NOT_REGISTERED_IN_OVERLAY": 2})
        self.assertTrue(all(x["tdx_day_local_evidence"] is None for x in r["entries"]))
        self.assertFalse(r["independent_official_stock_day_universe_certified"])

    def test_old_day_outside_adapter_scope_remains_pending(self):
        def outside(*args):
            raise O.OverlayError("DAY_NOT_IN_OVERLAY_WINDOW")
        r = M.inspect(self.root, self.day, self.day, day_inspector=outside)
        self.assertEqual(r["day_local_evidence_states"],
                         {"OUTSIDE_THIS_DAY_ADAPTER_WINDOW": 2})
        self.assertFalse(r["market_quality_cleared"])

    def test_target_not_present_or_no_active_trade_is_not_equivalent_to_missing_qmt(self):
        for reason, expected in [
            ("TARGET_EQUITY_NOT_IN_DAY_EXPORT", "TARGET_NOT_IN_DAY_EXPORT"),
            ("TARGET_DAY_NOT_ACTIVE_TRADED_REFERENCE", "TARGET_NOT_ACTIVE_IN_DAY_EXPORT"),
        ]:
            with self.subTest(reason=reason):
                def missing(*args):
                    raise O.DAY.DayContentError(reason)
                r = M.inspect(self.root, self.day, self.day, day_inspector=missing)
                self.assertEqual(r["day_local_evidence_states"], {expected: 2})

    def test_corrupted_tdx_receipt_fails_closed(self):
        def corrupt(*args):
            raise O.OverlayError("DAY_OVERLAY_RECEIPT_CHAIN_INVALID")
        with self.assertRaisesRegex(M.ReadinessError, "DAY_EVIDENCE_FAILED_CLOSED"):
            M.inspect(self.root, self.day, self.day, day_inspector=corrupt)

    def test_mismatched_tdx_physical_digest_fails_closed(self):
        def corrupt(*args):
            raise O.DAY.DayContentError("DAY_FILE_SHA_CHANGED")
        with self.assertRaisesRegex(M.ReadinessError, "DAY_EVIDENCE_FAILED_CLOSED"):
            M.inspect(self.root, self.day, self.day, day_inspector=corrupt)

    def test_unverified_provider_marked_true_is_rejected(self):
        def malicious(*args):
            p = self.fake_day(*args)
            p["provider_identity_authenticated"] = True
            return p
        with self.assertRaisesRegex(M.ReadinessError, "AUTHORITY_OR_SOURCE_SCOPE"):
            M.inspect(self.root, self.day, self.day, day_inspector=malicious)

    def test_forged_day_admission_or_market_write_rejected(self):
        for field in ("market_candidate_validated", "market_data_write_authorized",
                      "market_files_written", "original_nine_quarantines_cleared"):
            with self.subTest(field=field):
                def malicious(*args):
                    p = self.fake_day(*args)
                    p[field] = True
                    return p
                with self.assertRaisesRegex(M.ReadinessError, "AUTHORITY_OR_SOURCE_SCOPE"):
                    M.inspect(self.root, self.day, self.day, day_inspector=malicious)

    def test_raw_zip_already_verified_claim_requires_other_contract(self):
        def certified(*args):
            p = self.fake_day(*args)
            p["tdx_raw_zip_bytes_verified"] = True
            return p
        with self.assertRaisesRegex(M.ReadinessError, "AUTHORITY_OR_SOURCE_SCOPE"):
            M.inspect(self.root, self.day, self.day, day_inspector=certified)

    def test_wrong_day_or_symbol_in_provider_proof_rejected(self):
        for field, value in (("day", "2024-01-01"), ("symbol", "SH999999")):
            with self.subTest(field=field):
                def malicious(*args):
                    p = self.fake_day(*args)
                    p[field] = value
                    return p
                with self.assertRaisesRegex(M.ReadinessError, "PROOF_SCOPE_CHANGED"):
                    M.inspect(self.root, self.day, self.day, day_inspector=malicious)

    def test_same_day_tdx_evidence_changing_between_stock_checks_rejected(self):
        def changing(root, day, symbol):
            p = self.fake_day(root, day, symbol)
            if symbol == self.symbols[1]:
                p["day_overlay_parquet_bytes_sha256"] = "f" * 64
            return p
        with self.assertRaisesRegex(M.ReadinessError, "SAME_DAY_TDX_EVIDENCE_CHANGED"):
            M.inspect(self.root, self.day, self.day, day_inspector=changing)

    def test_producer_receipt_modified_while_day_inspection_refused(self):
        def mutate(root, day, symbol):
            doc_path = self.dir / (self.day + ".json")
            doc_path.write_bytes(doc_path.read_bytes() + b" ")
            return self.fake_day(root, day, symbol)
        with self.assertRaisesRegex(M.ReadinessError, "PRODUCER_EVIDENCE_CHANGED"):
            M.inspect(self.root, self.day, self.day, day_inspector=mutate)

    def test_candidate_parquet_modified_while_day_inspection_refused(self):
        def mutate(root, day, symbol):
            data_path = self.dir / (self.day + ".parquet")
            data_path.write_bytes(b"wrong data")
            return self.fake_day(root, day, symbol)
        with self.assertRaises(A.AdapterError):
            M.inspect(self.root, self.day, self.day, day_inspector=mutate)

    def test_limit_prevents_partial_case_selection(self):
        with self.assertRaisesRegex(M.ReadinessError, "QUARANTINES_EXCEED"):
            self.run_day(max_stock_days=1)
        self.assertEqual(self.calls, [])

    def test_invalid_limit_and_no_automatic_raise(self):
        for limit in (0, 129, -1, None, True):
            with self.subTest(limit=limit), self.assertRaises(M.ReadinessError):
                self.run_day(max_stock_days=limit)

    def test_zero_original_quarantines_does_not_certify_clean_market(self):
        day = "2024-12-31"
        self.create_day(day, (), accepted=3, reasons=())
        report = M.inspect(self.root, day, day, day_inspector=self.fake_day)
        self.assertEqual(report["original_producer_quarantined_stock_days"], 0)
        self.assertEqual(report["entries"], [])
        self.assertFalse(report["market_quality_cleared"])
        self.assertEqual(report["readiness_overall"], "BLOCKED_REVIEW_ONLY_NO_REPAIR")

    def test_malformed_producer_metadata_refused(self):
        p = self.dir / (self.day + ".json")
        doc = json.loads(p.read_text())
        doc["production_merge_authorized"] = True
        p.write_text(json.dumps(doc))
        with self.assertRaises(A.AdapterError):
            self.run_day()

    def test_duplicate_quarantine_case_rejected(self):
        original = A.classify_daily(self.root, start_day=self.day, end_day=self.day)
        bad = deepcopy(original)
        bad["quality_cases"]["cases"].append(deepcopy(bad["quality_cases"]["cases"][0]))
        bad["quality_cases"]["case_count"] += 1
        bad["producer_quarantines_preserved"] += 1
        with self.assertRaisesRegex(M.ReadinessError, "DUPLICATE_QUARANTINED_SOURCE_SCOPE"):
            M.inspect(self.root, self.day, self.day, producer_reader=lambda *a, **kw: deepcopy(bad),
                      day_inspector=self.fake_day)

    def test_summary_cli_omits_individual_stock_codes(self):
        with mock.patch.object(M.DAY, "inspect", side_effect=self.fake_day):
            output = StringIO()
            with redirect_stdout(output):
                result = M.main(["--module-root", str(self.root),
                                 "--start-day", self.day, "--end-day", self.day,
                                 "--summary-only"])
        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertNotIn("entries", payload)
        self.assertEqual(payload["original_producer_quarantined_stock_days"], 2)
        self.assertIn("review_sha256", payload)

    def test_cli_no_private_paths_on_failure(self):
        out = StringIO()
        with redirect_stdout(out):
            result = M.main(["--module-root", "/hidden/example",
                             "--start-day", self.day, "--end-day", self.day])
        self.assertEqual(result, 3)
        self.assertNotIn("/hidden", out.getvalue())

    def test_no_provider_io_or_market_writer_in_source(self):
        import inspect
        source = inspect.getsource(M)
        for string in ("download_history_data(", "pq.write_table(", "os.replace(", "xtquant"):
            self.assertNotIn(string, source)


if __name__ == "__main__":
    unittest.main()
