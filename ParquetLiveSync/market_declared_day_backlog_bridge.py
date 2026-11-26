#!/usr/bin/env python3
"""Attach *declared* DAY symbol-state differences to the generic quality backlog.

Never authenticate exchange-wide completeness, provider identities, native QMT
minutes, or modify/close any original producer quarantine. Read-only inputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import market_day_universe_crosscheck as U
import market_quality_engine as Q
import market_quality_backlog as B

FORMAT = "astock_declared_day_backlog_bridge_readonly_v1"
SOURCE_ID = "tdx-day-declared-compare"
CONFLICT_GROUPS = frozenset((
    "declared_traded_missing_in_overlay",
    "declared_traded_zero_in_overlay",
    "declared_no_trade_but_active_in_overlay",
))
UNCERTAIN_GROUPS = frozenset((
    "overlay_code_not_in_declared_reference",
    "declared_unknown_present_in_overlay",
    "declared_unknown_absent_from_overlay",
))
AGREEMENT_GROUPS = frozenset((
    "declared_traded_and_overlay_active",
    "declared_no_trade_and_zero_in_overlay",
    "declared_no_trade_absent_from_overlay",
))
GROUPS = CONFLICT_GROUPS | UNCERTAIN_GROUPS | AGREEMENT_GROUPS

class BridgeError(ValueError):
    pass

def require(ok, reason):
    if not ok:
        raise BridgeError(reason)

def _sha(s):
    return isinstance(s, str) and bool(Q.HEX64.fullmatch(s))

def validate_report(report):
    """Validate normalized diagnostic structure, NOT source authenticity."""
    require(isinstance(report, dict) and report.get("status") == U.STATUS,
            "UNRECOGNIZED_CROSSCHECK_REPORT")
    required_false = (
        "independent_reference_provider_authenticated",
        "reference_full_stock_day_universe_certified",
        "tdx_provider_identity_authenticated", "instrument_membership_authenticated",
        "source_independence_authenticated", "native_qmt_1min_certified",
        "original_producer_quarantines_cleared", "market_quality_cleared",
        "market_write_authorized", "market_files_written",
    )
    require(all(report.get(k) is False for k in required_false) and
            report.get("qmt_history_download_calls") == 0,
            "CROSSCHECK_CLAIMS_UNSUPPORTED_AUTHORITY")
    require(_sha(report.get("comparison_json_sha256")) and
            report["comparison_json_sha256"] == U.sha({
                k: v for k, v in report.items() if k != "comparison_json_sha256"}),
            "CROSSCHECK_DIAGNOSTIC_DIGEST_CHANGED")
    day, anchor = report.get("day"), report.get("anchor_symbol")
    require(isinstance(day, str) and isinstance(anchor, str) and
            bool(Q.SYMBOL.fullmatch(anchor)), "INVALID_CROSSCHECK_DAY_OR_ANCHOR")
    from datetime import date
    try:
        require(date.fromisoformat(day).isoformat() == day,
                "INVALID_CROSSCHECK_DAY_OR_ANCHOR")
    except (ValueError, TypeError) as exc:
        raise BridgeError("INVALID_CROSSCHECK_DAY_OR_ANCHOR") from exc
    for k in ("tdx_overlay_parquet_bytes_sha256", "reference_bytes_sha256",
              "tdx_overlay_state_bytes_sha256", "tdx_overlay_receipt_bytes_sha256"):
        require(_sha(report.get(k)), "MISSING_CROSSCHECK_BYTE_SHA_" + k)
    require(isinstance(report.get("declared_reference_source_id"), str) and
            bool(Q.SOURCE.fullmatch(report["declared_reference_source_id"])),
            "INVALID_REFERENCE_SOURCE_LABEL")
    require(report.get("declared_reference_coverage_claim") in
            ("PARTIAL_DECLARED", "FULL_DECLARED"), "INVALID_REFERENCE_COVERAGE_CLAIM")
    groups, counts = report.get("groups"), report.get("counts")
    require(isinstance(groups, dict) and set(groups) == GROUPS and
            isinstance(counts, dict) and set(counts) == GROUPS,
            "CROSSCHECK_BUCKET_SCHEMA_CHANGED")
    seen = set()
    for name in sorted(GROUPS):
        values = groups[name]
        require(isinstance(values, list) and values == sorted(set(values)) and
                type(counts[name]) is int and counts[name] == len(values),
                "CROSSCHECK_BUCKET_NOT_UNIQUE_SORTED_OR_COUNTED")
        for sym in values:
            require(isinstance(sym, str) and bool(Q.SYMBOL.fullmatch(sym)) and
                    sym not in seen, "CROSSCHECK_SYMBOL_DUPLICATED_OR_INVALID")
            seen.add(sym)
    conflict = any(groups[k] for k in CONFLICT_GROUPS)
    require(report.get("has_declared_conflict") is conflict,
            "CROSSCHECK_CONFLICT_SUMMARY_CHANGED")
    require(len(seen) <= U.MAX_REFERENCE_SYMBOLS + U.DAY.MAX_ROWS,
            "CROSSCHECK_TOO_MANY_SYMBOLS")
    return day

def to_quality_batch(report):
    day = validate_report(report)
    cases = []
    for bucket in sorted(CONFLICT_GROUPS | UNCERTAIN_GROUPS):
        for symbol in report["groups"][bucket]:
            is_conflict = bucket in CONFLICT_GROUPS
            evidence = {
                "format": Q.FORMAT,
                "trading_day": day, "symbol": symbol, "period": "day",
                "source_id": SOURCE_ID, "source_state": "READY",
                # No independently authenticated official security-day scope.
                "official_stock_day": None,
                # SHA of actual accepted TDX DAY Parquet bytes, NOT raw QMT.
                "raw_source_sha256": report["tdx_overlay_parquet_bytes_sha256"],
                "official_reference_sha256": None,
                "receipt_integrity_valid": True,
                "calibration_verified": None,
                "declared_day_state_conflict": is_conflict,
                "declared_day_reference_uncertain": not is_conflict,
                "declared_difference_bucket": bucket,
                "declared_reference_bytes_sha256": report["reference_bytes_sha256"],
                "declared_reference_source_id": report["declared_reference_source_id"],
                "declared_reference_coverage_claim": report["declared_reference_coverage_claim"],
                "source_provenance_scope": "LOCAL_DAY_BYTES_AND_DECLARED_REFERENCE_ONLY",
            }
            cases.append(evidence)
    require(len(cases) <= Q.MAX_CASES, "CROSSCHECK_CASE_LIMIT_EXCEEDED")
    if cases:
        return Q.analyze_batch(cases)
    return {"format": Q.REPORT + "_batch", "case_count": 0, "cases": [],
            "source_data_read_by_engine": False, "market_files_modified": False,
            "source_download_calls": 0, "production_admission_authorized": False}

def make_backlog(report, *, producer_batch=None, producer_quarantine_count=None):
    """Aggregate separately sourced declarations without closing old issues."""
    comparison = to_quality_batch(report)
    cases = list(comparison["cases"])
    producer_cases = 0
    if producer_batch is not None:
        # Validates original producer records' no-write scope and rule IDs.
        B.build_backlog(producer_batch)
        producer_cases = producer_batch["case_count"]
        require(type(producer_quarantine_count) is int and
                producer_cases == producer_quarantine_count,
                "PRODUCER_QUARANTINE_COUNT_MISMATCH")
        cases.extend(producer_batch["cases"])
    require(len(cases) <= Q.MAX_CASES, "COMBINED_QUALITY_CASE_LIMIT_EXCEEDED")
    batch = {"format": Q.REPORT + "_batch", "case_count": len(cases),
             "cases": cases}
    backlog = B.build_backlog(batch)
    return {
        "format": FORMAT,
        "crosscheck_report_sha256": report["comparison_json_sha256"],
        "declared_conflicting_stock_days": sum(len(report["groups"][k])
                                               for k in CONFLICT_GROUPS),
        "declared_uncertain_stock_days": sum(len(report["groups"][k])
                                             for k in UNCERTAIN_GROUPS),
        "producer_quarantines_included_unmodified": producer_cases,
        "generic_backlog": backlog,
        "declared_source_comparison_is_official_market_verification": False,
        "provider_identity_authenticated": False,
        "official_stock_day_universe_certified": False,
        "native_qmt_minutes_certified": False,
        "production_market_admission_authorized": False,
        "automatic_quarantine_closure_authorized": False,
        "qmt_history_download_calls": 0,
        "market_files_written": False,
        "market_quality_cleared": False,
    }

def inspect(module_root, day, anchor, reference_root, reference_relative,
            reference_sha256, *, include_producer_quarantines=False):
    cross = U.inspect(module_root, day, anchor, reference_root=reference_root,
                      reference_relative=reference_relative,
                      reference_sha256=reference_sha256)
    if include_producer_quarantines:
        from market_quality_receipt_adapter import classify_daily
        existing = classify_daily(module_root, start_day=day, end_day=day)
        require(existing.get("status") == "READ_ONLY_DAILY_QUARANTINE_QUALITY_TRIAGE" and
                existing.get("project_market_files_modified") is False and
                existing.get("data_quality_cleared") is False and
                existing.get("production_merge_authorized") is False,
                "PRODUCER_RECEIPT_AUTHORITY_CHANGED")
        return make_backlog(cross, producer_batch=existing["quality_cases"],
                            producer_quarantine_count=existing["producer_quarantines_preserved"])
    return make_backlog(cross)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--module-root", type=Path, required=True)
    p.add_argument("--trading-day", required=True)
    p.add_argument("--anchor-symbol", required=True)
    p.add_argument("--reference-root", type=Path, required=True)
    p.add_argument("--reference-relative", required=True)
    p.add_argument("--reference-sha256", required=True)
    p.add_argument("--include-existing-producer-quarantines", action="store_true")
    p.add_argument("--summary-only", action="store_true")
    args = p.parse_args(argv)
    try:
        out = inspect(args.module_root, args.trading_day, args.anchor_symbol,
                      args.reference_root, args.reference_relative,
                      args.reference_sha256,
                      include_producer_quarantines=args.include_existing_producer_quarantines)
        if args.summary_only:
            out = {**out, "generic_backlog": {k: v for k, v in
                 out["generic_backlog"].items() if k != "issues"}}
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True,
                         allow_nan=False))
        return 0
    except (BridgeError, U.CrosscheckError, Q.QualityPolicyError,
            B.BacklogError, OSError, ValueError, TypeError, KeyError,
            ImportError, RuntimeError) as exc:
        print("DAY_DECLARATION_BACKLOG_REVIEW_REQUIRED: " + type(exc).__name__)
        return 3

if __name__ == "__main__":
    raise SystemExit(main())
