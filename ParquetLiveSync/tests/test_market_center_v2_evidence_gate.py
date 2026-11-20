"""Synthetic tests for V2-B2 eligibility evidence; never touch production."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import market_center_v2_readonly_audit as A
import market_center_v2_evidence_gate as E
import market_center_v2_audit_cli as CLI

START, END = "2026-11-16", "2026-11-19"
STOCK = "000001.SZ"
DAYS = [(date(2026, 11, 16) + timedelta(days=i)).isoformat()
        for i in range(4)]


def observation(day, count=0, period="day", anomalies=None):
    anomalies = anomalies or {}
    status = ("ANOMALY_OBSERVED" if anomalies else
              "NO_ROWS_OBSERVED" if count == 0 else
              "ROWS_OBSERVED_UNCERTIFIED")
    return {"period": period, "symbol": STOCK,
            "timestamp_label_day": day, "rows": count,
            "status": status, "anomalies": anomalies}


def base_report(rows=None):
    return {
        "status": "V2B_BOUNDED_READONLY_OBSERVATION_NOT_CERTIFIED",
        "scope": {"start": START, "end": END, "stocks": [STOCK],
                  "periods": ["day"]},
        "allowed_market_write": False,
        "observations": rows or [
            observation(DAYS[0]), observation(DAYS[1]),
            observation(DAYS[2]), observation(DAYS[3], count=1)
        ],
    }


def base_evidence():
    return {
        "format": E.FORMAT,
        "scope": {"start": START, "end": END, "stocks": [STOCK]},
        "provenance": {
            "calendar_source": "synthetic_mock_calendar_fixture",
            "listing_source": "synthetic_mock_listed_date",
            "suspension_source": "synthetic_mock_suspension_fixture",
        },
        "exchange_calendar": {
            "SZ": {DAYS[0]: "TRADING", DAYS[1]: "TRADING",
                   DAYS[2]: "NOT_TRADING", DAYS[3]: "TRADING"}
        },
        "stocks": {STOCK: {
            "listed_on": "1991-04-03", "valid_through": None,
            "day_states": {
                DAYS[0]: "ELIGIBLE", DAYS[1]: "SUSPENDED",
                DAYS[2]: "UNKNOWN", DAYS[3]: "ELIGIBLE",
            }
        }},
    }


def pin(snapshot, folder):
    path = folder / "evidence.json"
    raw = json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


class EvidenceGatedClassificationTests(unittest.TestCase):
    def test_without_manifest_no_missing_is_certified(self):
        got = E.classify(base_report())
        self.assertEqual(got["confirmed_missing_count"], 0)
        self.assertFalse(got["source_authenticity_certified"])
        self.assertFalse(got["allowed_repair_or_backfill"])
        self.assertEqual(got["summary"]["NO_ROWS_CALENDAR_AND_ELIGIBILITY_UNKNOWN"], 3)
        self.assertEqual(got["summary"]["RECORDS_PRESENT_NOT_CERTIFIED"], 1)

    def test_manifest_labels_are_candidates_not_certificates(self):
        with TemporaryDirectory() as temp:
            path, sha = pin(base_evidence(), Path(temp))
            evidence = E.load_pinned_evidence(path, sha, base_report()["scope"])
            got = E.classify(base_report(), evidence)
            names = [x["interpretation"] for x in got["observations"]]
            self.assertEqual(names, [
                "MISSING_CANDIDATE_SOURCE_AUTHENTICITY_UNVERIFIED",
                "NO_ROWS_SUSPENDED_DECLARED_UNCERTIFIED",
                "NO_ROWS_NONTRADING_DECLARED_UNCERTIFIED",
                "RECORDS_PRESENT_NOT_CERTIFIED",
            ])
            self.assertTrue(got["source_integrity_checked"])
            self.assertFalse(got["source_authenticity_certified"])
            self.assertFalse(got["actual_trading_calendar_verified"])
            self.assertEqual(got["confirmed_missing_count"], 0)
            self.assertFalse(got["allowed_repair_or_backfill"])
            self.assertFalse(got["market_file_writes"])
            self.assertEqual(got["qmt_calls"], 0)

    def test_missing_physical_shard_is_not_labeled_stock_day_missing(self):
        report = base_report([observation(DAYS[0])])
        report["missing_partitions"] = [
            {"period": "day", "partition": "2026-11",
             "reason": "PHYSICAL_PARTITION_NOT_FOUND"}]
        with TemporaryDirectory() as temp:
            path, sha = pin(base_evidence(), Path(temp))
            proof = E.load_pinned_evidence(path, sha, report["scope"])
            got = E.classify(report, proof)
            self.assertEqual(
                got["observations"][0]["interpretation"],
                "PHYSICAL_PARTITION_MISSING_STOCK_GAP_UNDETERMINED")
            self.assertEqual(got["confirmed_missing_count"], 0)
            self.assertFalse(got["allowed_repair_or_backfill"])

    def test_wrong_sha_rejected_before_claims(self):
        with TemporaryDirectory() as temp:
            path, _ = pin(base_evidence(), Path(temp))
            with self.assertRaisesRegex(E.EvidenceBlocked, "sha256_mismatch"):
                E.load_pinned_evidence(path, "0" * 64, base_report()["scope"])

    def test_missing_calendar_day_rejected(self):
        snapshot = base_evidence()
        snapshot["exchange_calendar"]["SZ"].pop(DAYS[2])
        with TemporaryDirectory() as temp:
            path, sha = pin(snapshot, Path(temp))
            with self.assertRaisesRegex(E.EvidenceBlocked, "calendar_days_incomplete"):
                E.load_pinned_evidence(path, sha, base_report()["scope"])

    def test_missing_stock_status_day_rejected(self):
        snapshot = base_evidence()
        snapshot["stocks"][STOCK]["day_states"].pop(DAYS[0])
        with TemporaryDirectory() as temp:
            path, sha = pin(snapshot, Path(temp))
            with self.assertRaisesRegex(E.EvidenceBlocked, "status_days_incomplete"):
                E.load_pinned_evidence(path, sha, base_report()["scope"])

    def test_scope_mismatch_rejected_even_when_sha_matches(self):
        snapshot = base_evidence()
        snapshot["scope"]["end"] = "2026-11-18"
        with TemporaryDirectory() as temp:
            path, sha = pin(snapshot, Path(temp))
            with self.assertRaisesRegex(E.EvidenceBlocked, "scope_not_exactly_equal"):
                E.load_pinned_evidence(path, sha, base_report()["scope"])

    def test_prelisting_does_not_count_as_missing_candidate(self):
        snapshot = base_evidence()
        snapshot["stocks"][STOCK]["listed_on"] = "2026-11-18"
        with TemporaryDirectory() as temp:
            path, sha = pin(snapshot, Path(temp))
            got = E.classify(
                base_report(), E.load_pinned_evidence(path, sha, base_report()["scope"]))
            self.assertEqual(got["observations"][0]["interpretation"],
                             "NO_ROWS_PRELISTING_DECLARED_UNCERTIFIED")
            self.assertEqual(got["confirmed_missing_count"], 0)

    def test_week_month_cannot_derive_daily_holes(self):
        with TemporaryDirectory() as temp:
            path, sha = pin(base_evidence(), Path(temp))
            report = base_report([observation(DAYS[0], period="week")])
            got = E.classify(report, E.load_pinned_evidence(path, sha, report["scope"]))
            self.assertEqual(got["observations"][0]["interpretation"],
                             "LONG_CYCLE_LABEL_NEEDS_CLOSURE_PROOF")

    def test_physical_anomaly_precedes_any_external_eligibility(self):
        report = base_report([observation(DAYS[0], count=1, anomalies={
            "OHLC_INVALID": 1})])
        got = E.classify(report)
        self.assertEqual(got["observations"][0]["interpretation"],
                         "PHYSICAL_ANOMALY_NEEDS_REVIEW")

    def test_inconsistent_report_rejected(self):
        report = base_report([observation(DAYS[0], count=0)])
        report["observations"][0]["status"] = "ROWS_OBSERVED_UNCERTIFIED"
        with self.assertRaisesRegex(E.EvidenceBlocked, "inconsistent"):
            E.classify(report)

    def test_manifest_only_proves_integrity_not_source_identity(self):
        with TemporaryDirectory() as temp:
            snapshot = base_evidence()
            snapshot["provenance"]["calendar_source"] = "untrusted_manual_statement"
            path, sha = pin(snapshot, Path(temp))
            result = E.load_pinned_evidence(path, sha, base_report()["scope"])
            self.assertFalse(result["authenticity_independently_certified"])
            self.assertTrue(result["integrity_verified"])
            interpretation = E.classify(base_report(), result)
            self.assertFalse(interpretation["source_authenticity_certified"])

    def test_no_evidence_and_sha_only_are_not_accepted_together(self):
        with self.assertRaisesRegex(E.EvidenceBlocked, "together"):
            CLI.audited_query(root="notused", start=START, end=END,
                              symbols=[STOCK], periods=["day"], explicit_readonly=True,
                              evidence_sha256="0" * 64)

    def test_no_market_write_even_if_report_contains_false_permission(self):
        report = base_report()
        report["allowed_market_write"] = True
        with self.assertRaisesRegex(E.EvidenceBlocked, "not_accepted"):
            E.classify(report)

    def test_declaration_conflict_does_not_override_physical_records(self):
        with TemporaryDirectory() as temp:
            path, sha = pin(base_evidence(), Path(temp))
            report = base_report([observation(DAYS[1], count=1)])
            evidence = E.load_pinned_evidence(path, sha, report["scope"])
            got = E.classify(report, evidence)
            self.assertEqual(got["observations"][0]["interpretation"],
                             "PHYSICAL_SOURCE_DECLARATION_CONFLICT_UNVERIFIED")
            self.assertEqual(got["confirmed_missing_count"], 0)

    def test_read_budget_releases_before_1955(self):
        cn = timezone(timedelta(hours=8))
        early = datetime(2026, 11, 20, 19, 30, tzinfo=cn)
        late = datetime(2026, 11, 20, 19, 54, tzinfo=cn)
        cutoff = datetime(2026, 11, 20, 19, 54, 40, tzinfo=cn)
        self.assertEqual(CLI._read_budget_seconds(early), 45.0)
        self.assertEqual(CLI._read_budget_seconds(late), 30.0)
        with self.assertRaisesRegex(A.AuditBlocked, "too_close"):
            CLI._read_budget_seconds(cutoff)

    def test_bounded_scan_exits_when_monotonic_deadline_elapsed(self):
        with patch.object(A.time, "monotonic", return_value=100.0):
            with self.assertRaisesRegex(A.AuditBlocked, "wall_clock_budget"):
                A._check_deadline(100.0)
            A._check_deadline(101.0)

    def test_unknown_stock_status_does_not_create_missing_candidate(self):
        snapshot = base_evidence()
        snapshot["stocks"][STOCK]["day_states"][DAYS[0]] = "UNKNOWN"
        with TemporaryDirectory() as temp:
            path, sha = pin(snapshot, Path(temp))
            proof = E.load_pinned_evidence(path, sha, base_report()["scope"])
            got = E.classify(base_report(), proof)
            self.assertEqual(got["observations"][0]["interpretation"],
                             "NO_ROWS_ELIGIBILITY_INDETERMINATE")


if __name__ == "__main__":
    unittest.main()
