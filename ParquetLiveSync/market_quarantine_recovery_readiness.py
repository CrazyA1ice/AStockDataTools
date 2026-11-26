#!/usr/bin/env python3
"""Read-only multi-day evidence matrix for quarantined market stock-days.

Bind real daily producer receipts to existing SHA-pinned DAY overlay checks.
A valid DAY row is not a QMT-minute repair, a provider signature, an official
exchange stock universe, or authorization to write Parquet/H5/QMT cache.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path

import market_quality_receipt_adapter as PRODUCER
import market_quality_backlog as BACKLOG
import market_live_day_overlay_audit as DAY

FORMAT = "astock_market_quarantine_readiness_readonly_v1"
STATUS = "QUARANTINE_EVIDENCE_MATRIX_NO_REPAIR_AUTHORITY"
MAX_STOCK_DAYS = 64
ABSOLUTE_MAX_STOCK_DAYS = 128

# Only these absence outcomes are downgraded to "missing reference".
# A digest mismatch, invalid schema, altered receipt or untrusted source is
# never converted into an innocuous absent-day status.
SOFT_DAY_EXCEPTIONS = {
    "DAY_NOT_IN_OVERLAY_WINDOW": "OUTSIDE_THIS_DAY_ADAPTER_WINDOW",
    "DAY_NOT_FOUND_IN_PINNED_LIVE_STATE": "DAY_NOT_REGISTERED_IN_OVERLAY",
    "TARGET_EQUITY_NOT_IN_DAY_EXPORT": "TARGET_NOT_IN_DAY_EXPORT",
    "TARGET_DAY_NOT_ACTIVE_TRADED_REFERENCE": "TARGET_NOT_ACTIVE_IN_DAY_EXPORT",
}

COMMON_BLOCKERS = (
    "ORIGINAL_PRODUCER_QUARANTINE_RETAINED",
    "QMT_NATIVE_MINUTE_BYTES_NOT_INDEPENDENTLY_VERIFIED",
    "TDX_PROVIDER_IDENTITY_NOT_AUTHENTICATED",
    "OFFICIAL_EXCHANGE_STOCK_DAY_UNIVERSE_NOT_CERTIFIED",
    "PAID_MINUTE_SOURCE_CALIBRATION_NOT_INDEPENDENTLY_VERIFIED",
    "SIX_FIELD_NATIVE_MINUTE_VS_DAY_NOT_REVALIDATED",
    "EIGHT_PERIOD_AGGREGATION_NOT_REVALIDATED",
    "TRANSACTIONAL_MARKET_COMMIT_NOT_AUTHORIZED",
)


class ReadinessError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise ReadinessError(reason)


def _is_sha(value):
    return isinstance(value, str) and bool(BACKLOG.Q.HEX64.fullmatch(value))


def _day_evidence(proof, symbol, day):
    require(isinstance(proof, dict) and proof.get("status") == DAY.STATUS,
            "TDX_DAY_PROOF_STATUS_UNRECOGNIZED")
    require(proof.get("day") == day and proof.get("symbol") == symbol,
            "TDX_DAY_PROOF_SCOPE_CHANGED")
    require(proof.get("day_content_fields_and_target_checked") is True and
            all(_is_sha(proof.get(key)) for key in
                ("live_state_bytes_sha256", "day_overlay_receipt_bytes_sha256",
                 "day_overlay_parquet_bytes_sha256")) and
            isinstance(proof.get("target_ohlcva"), dict) and
            set(proof["target_ohlcva"]) == {"open", "high", "low", "close", "volume", "amount"} and
            _is_sha(proof.get("receipt_claimed_raw_tdx_zip_sha256")),
            "TDX_DAY_PROOF_EVIDENCE_INCOMPLETE")
    forbidden_true = (
        "whole_exchange_stock_day_universe_certified",
        "provider_identity_authenticated",
        "qmt_native_1min_verified", "market_candidate_validated",
        "original_nine_quarantines_cleared", "market_data_write_authorized",
        "market_files_written",
    )
    require(all(proof.get(key) is False for key in forbidden_true) and
            proof.get("qmt_history_download_calls") == 0 and
            proof.get("tdx_raw_zip_bytes_verified") is False and
            proof.get("tdx_raw_zip_file_bytes_sha256_if_checked") is None,
            "TDX_DAY_PROOF_AUTHORITY_OR_SOURCE_SCOPE_CHANGED")
    return {
        "state": "LOCAL_TDX_DAY_CONTENT_VERIFIED_PROVIDER_UNAUTHENTICATED",
        "live_state_bytes_sha256": proof["live_state_bytes_sha256"],
        "day_receipt_bytes_sha256": proof["day_overlay_receipt_bytes_sha256"],
        "day_parquet_bytes_sha256": proof["day_overlay_parquet_bytes_sha256"],
        "declared_raw_tdx_zip_sha256_not_verified":
            proof.get("receipt_claimed_raw_tdx_zip_sha256"),
        "target_day_open": proof["target_ohlcva"]["open"],
        "provider_identity_authenticated": False,
        "official_stock_day_membership_certified": False,
        "qmt_minute_data_certified": False,
    }


def _checked_receipt(root, start_day, end_day, reader):
    receipt = reader(root, start_day=start_day, end_day=end_day)
    require(isinstance(receipt, dict) and
            receipt.get("status") == PRODUCER.STATUS and
            receipt.get("production_merge_authorized") is False and
            receipt.get("data_quality_cleared") is False and
            receipt.get("qmt_cache_write_authorized") is False and
            receipt.get("project_market_files_modified") is False and
            receipt.get("official_day_source_independently_certified") is False and
            receipt.get("original_paid_qmt_source_independently_certified") is False,
            "PRODUCER_RECEIPT_AUTHORITY_OR_FORMAT_CHANGED")
    cases = receipt.get("quality_cases")
    require(isinstance(cases, dict), "PRODUCER_QUALITY_BATCH_MISSING")
    issues = BACKLOG.build_backlog(cases)
    require(receipt.get("producer_quarantines_preserved") == issues["case_count"] and
            isinstance(receipt.get("source_receipts"), list) and
            receipt.get("existing_day_receipts_checked") ==
            len(receipt["source_receipts"]),
            "PRODUCER_QUARANTINE_COUNT_OR_DAYS_CHANGED")
    require(all(isinstance(r, dict) for r in receipt["source_receipts"]),
            "PRODUCER_RECEIPT_LIST_INVALID")
    receipt_days = {r.get("day"): r for r in receipt["source_receipts"]}
    require(len(receipt_days) == len(receipt["source_receipts"]) and
            all(type(r.get("reported_quarantined_stock_days")) is int and
                type(r.get("reported_accepted_stock_days")) is int and
                r.get("candidate_physical_sha_matches_receipt") is True and
                r.get("quarantined_raw_qmt_sha_verified") is False and
                r.get("official_day_reference_independently_verified") is False and
                all(_is_sha(r.get(k)) for k in
                    ("producer_receipt_bytes_sha256",
                     "accepted_candidate_parquet_sha256"))
                for r in receipt["source_receipts"]) and
            sum(r["reported_quarantined_stock_days"]
                for r in receipt["source_receipts"]) == issues["case_count"] and
            sum(r["reported_accepted_stock_days"]
                for r in receipt["source_receipts"]) ==
            receipt.get("producer_accepted_stock_days_reported_not_recrossvalidated"),
            "PRODUCER_SOURCE_RECEIPT_EVIDENCE_CHANGED")
    return receipt, issues, receipt_days


def inspect(root, start_day, end_day, *, max_stock_days=MAX_STOCK_DAYS,
            producer_reader=None, day_inspector=None):
    """Review existing quarantine only; no selection of accepted stock-days."""
    require(type(max_stock_days) is int and
            1 <= max_stock_days <= ABSOLUTE_MAX_STOCK_DAYS,
            "INVALID_READONLY_REVIEW_STOCK_DAY_LIMIT")
    module_root = Path(root)
    reader = producer_reader or PRODUCER.classify_daily
    verify_day = day_inspector or DAY.inspect
    producer, backlog, receipts = _checked_receipt(
        module_root, start_day, end_day, reader)
    cases = producer["quality_cases"]["cases"]
    require(len(cases) <= max_stock_days,
            "QUARANTINES_EXCEED_BOUNDED_REVIEW_LIMIT_NO_PARTIAL_SELECTION")

    issues_by_stockday = {}
    for item in backlog["issues"]:
        scope = item["scope"]
        key = (scope["trading_day"], scope["symbol"],
               scope["period"], scope["source_id"])
        issues_by_stockday.setdefault(key, []).append(item["incident_id"])

    entries = []
    day_digests = {}
    seen = set()
    for case in cases:
        scope = case["scope"]
        day, symbol, period, source_id = (
            scope["trading_day"], scope["symbol"],
            scope["period"], scope["source_id"])
        key = (day, symbol, period, source_id)
        require(key not in seen, "DUPLICATE_QUARANTINED_SOURCE_SCOPE")
        seen.add(key)
        require(day in receipts and
                "PRODUCER_QUARANTINED" in case["detected_rules"] and
                case["quality_state"] == "QUARANTINED",
                "PRODUCER_CASE_NOT_AN_ORIGINAL_QUARANTINE")
        require(period in BACKLOG.Q.PERIODS, "UNKNOWN_QUARANTINE_PERIOD")
        day_evidence = None
        state = None
        try:
            day_evidence = _day_evidence(verify_day(module_root, day, symbol),
                                         symbol, day)
            state = day_evidence["state"]
            # Every audited stock on the same day must refer to the same
            # physical TDX DAY state/receipt/Parquet bytes.
            triplet = (day_evidence["live_state_bytes_sha256"],
                       day_evidence["day_receipt_bytes_sha256"],
                       day_evidence["day_parquet_bytes_sha256"])
            if day in day_digests:
                require(day_digests[day] == triplet,
                        "SAME_DAY_TDX_EVIDENCE_CHANGED_BETWEEN_STOCKS")
            else:
                day_digests[day] = triplet
        except (DAY.OverlayError, DAY.DAY.DayContentError) as exc:
            reason = str(exc)
            if reason not in SOFT_DAY_EXCEPTIONS:
                raise ReadinessError("DAY_EVIDENCE_FAILED_CLOSED_" + type(exc).__name__) from exc
            state = SOFT_DAY_EXCEPTIONS[reason]
        blockers = list(COMMON_BLOCKERS)
        if day_evidence is None:
            blockers.append("TDX_DAY_LOCAL_CONTENT_EVIDENCE_NOT_AVAILABLE")
        causes = sorted(set(case["detected_rules"]))
        if "OHLCVA_MISMATCH" in causes:
            blockers.append("EXISTING_OHLCVA_REJECTION_NOT_ADMITTED_AS_REPAIR")
        entries.append({
            "trading_day": day, "symbol": symbol, "period": period,
            "source_id": source_id,
            "producer_original_quarantine": True,
            "original_quality_case_sha256": case["input_evidence_json_sha256"],
            "original_quality_incident_ids":
                sorted(issues_by_stockday.get((day, symbol, period, source_id), [])),
            "existing_quality_detected_rules": causes,
            "producer_receipt_bytes_sha256":
                receipts[day]["producer_receipt_bytes_sha256"],
            "accepted_candidate_parquet_sha256_not_quarantined_raw_data":
                receipts[day]["accepted_candidate_parquet_sha256"],
            "tdx_day_local_evidence": day_evidence,
            "tdx_day_evidence_state": state,
            "readiness": "BLOCKED_REVIEW_ONLY_NO_REPAIR",
            "next_readonly_review": (
                "REPLAY_NATIVE_MINUTE_FIRST_TRADE_WITH_SEPARATE_APPROVAL"
                if "OHLCVA_MISMATCH" in causes else
                "CHECK_NATIVE_MINUTE_SOURCE_COVERAGE_WITH_SEPARATE_APPROVAL"),
            "unresolved_evidence_requirements": blockers,
            "source_independence_authenticated": False,
            "official_stock_day_universe_certified": False,
            "minute_market_candidate_approved": False,
            "production_merge_authorized": False,
            "qmt_history_download_authorized": False,
            "producer_quarantine_cleared": False,
        })
    entries.sort(key=lambda x: (x["trading_day"], x["symbol"],
                                x["period"], x["source_id"]))
    # Re-read ALL bounded producer receipts and candidate physical SHA after
    # the DAY scans; refuse if upstream cases or source files changed.
    last, last_backlog, _ = _checked_receipt(module_root, start_day, end_day, reader)
    require(BACKLOG.digest(producer) == BACKLOG.digest(last) and
            backlog["backlog_sha256"] == last_backlog["backlog_sha256"],
            "PRODUCER_EVIDENCE_CHANGED_DURING_READONLY_AUDIT")

    report = {
        "format": FORMAT, "status": STATUS,
        "window": producer["window"],
        "existing_daily_receipts_checked":
            producer["existing_day_receipts_checked"],
        "producer_accepted_stock_days_reported_not_independently_recounted":
            producer["producer_accepted_stock_days_reported_not_recrossvalidated"],
        "original_producer_quarantined_stock_days":
            producer["producer_quarantines_preserved"],
        "original_quarantined_source_period_records":
            len(cases),
        "distinct_quarantined_stock_days":
            len({(c["scope"]["trading_day"], c["scope"]["symbol"])
                 for c in cases}),
        "original_quality_rule_incidents": backlog["unique_incidents"],
        "original_backlog_sha256": backlog["backlog_sha256"],
        "day_local_evidence_states":
            dict(sorted(Counter(e["tdx_day_evidence_state"] for e in entries).items())),
        "entries": entries,
        "readiness_overall": "BLOCKED_REVIEW_ONLY_NO_REPAIR",
        "native_qmt_minute_data_verified": False,
        "independent_official_stock_day_universe_certified": False,
        "provider_identity_authenticated": False,
        "production_merge_authorized": False,
        "qmt_history_download_authorized": False,
        "qmt_history_download_calls": 0,
        "project_market_files_written": False,
        "original_producer_quarantines_cleared": False,
        "market_quality_cleared": False,
    }
    report["review_sha256"] = BACKLOG.digest(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-root", type=Path, required=True)
    parser.add_argument("--start-day", required=True)
    parser.add_argument("--end-day", required=True)
    parser.add_argument("--max-stock-days", type=int, default=MAX_STOCK_DAYS)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = inspect(args.module_root, args.start_day, args.end_day,
                         max_stock_days=args.max_stock_days)
        shown = ({key: val for key, val in report.items() if key != "entries"}
                 if args.summary_only else report)
        print(json.dumps(shown, ensure_ascii=False, sort_keys=True,
                         indent=2, allow_nan=False))
        return 0
    except (ReadinessError, PRODUCER.AdapterError, BACKLOG.BacklogError,
            DAY.OverlayError, DAY.DAY.DayContentError, DAY.PROOF.ProofError,
            OSError, ValueError, TypeError, KeyError, ImportError,
            RuntimeError) as exc:
        # Never print private local paths or source content.
        print("MARKET_READINESS_REVIEW_REQUIRED: " + type(exc).__name__)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
