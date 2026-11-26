#!/usr/bin/env python3
"""Pure, date-agnostic A-share market-quality triage and NO-IO recovery plans.

This is a policy kernel, NOT a market-data writer or a certification engine.
Adapters provide normalized evidence; they remain responsible for authentic
source bytes, official-day references, calibration and exact exchange grids.
Nothing here calls QMT, downloads, writes Parquet/H5 or clears quarantine.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re

FORMAT = "astock_market_quality_case_v1"
REPORT = "astock_market_quality_triage_readonly_v1"
PERIODS = frozenset(("1min", "5min", "15min", "30min", "60min",
                     "day", "week", "month"))
SYMBOL = re.compile(r"^(SH|SZ|BJ)[0-9]{6}$")
SOURCE = re.compile(r"^[a-zA-Z0-9_.:-]{1,64}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
FIELD_SET = frozenset(("open", "high", "low", "close", "volume", "amount"))
BOOLEAN_FIELDS = (
    "official_stock_day", "grid_complete", "calibration_verified",
    "calibration_drift_confirmed", "receipt_integrity_valid",
    "source_conflict", "cross_period_consistent", "zero_prefix_verified",
    "traded_hlc_verified", "tail_hlc_verified", "producer_quarantined",
    "declared_day_state_conflict", "declared_day_reference_uncertain",
)
ACTIONS = {
    "SOURCE_UNAVAILABLE": "inspect_provider_access_and_retry_policy",
    "MISSING_STOCK_DAY": "inspect_calendar_cache_and_targeted_source_coverage",
    "INCOMPLETE_TIME_GRID": "inspect_native_exchange_grid_and_timestamp_alignment",
    "PRE_TRADE_QUOTE_OPEN": "replay_first_genuine_trade_as_candidate_only",
    "OHLCVA_MISMATCH": "independently_compare_six_fields_calibration_and_adjustment",
    "UNIT_OR_CALIBRATION_DRIFT": "recalibrate_with_independent_source_overlap",
    "ZERO_TRADE_REFERENCE": "preserve_reference_quote_without_fabricating_trades",
    "CROSS_PERIOD_INCONSISTENCY": "recompute_aggregations_and_verify_coverage",
    "SOURCE_CONFLICT": "retain_both_sources_and_check_lineage",
    "STORAGE_OR_RECEIPT_INTEGRITY": "stop_writes_audit_immutable_source_and_rollback",
    "INVALID_VOLUME_AMOUNT_PAIR": "quarantine_inconsistent_trade_units",
    "SOURCE_PROVENANCE_UNVERIFIED": "collect_verified_raw_source_and_reference_sha",
    "OFFICIAL_DAY_EVIDENCE_MISSING": "confirm_independent_day_universe",
    "PRODUCER_QUARANTINED": "retain_original_provider_quarantine_and_replay",
    "DECLARED_DAY_STATE_CONFLICT": "verify_claimed_day_trade_states_with_independent_source_before_market_decision",
    "DECLARED_DAY_REFERENCE_UNCERTAIN": "acquire_authenticated_complete_day_instrument_scope_and_trade_state",
}
MAX_CASES = 10000


class QualityPolicyError(ValueError):
    pass


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def _require(ok, reason):
    if not ok:
        raise QualityPolicyError(reason)


def _positive(value, key):
    _require(isinstance(value, (float, int)) and not isinstance(value, bool),
             "INVALID_" + key.upper())
    _require(math.isfinite(float(value)) and float(value) > 0,
             "NONPOSITIVE_OR_NONFINITE_" + key.upper())
    return float(value)


def _count(value, key, *, maximum=1000000):
    _require(type(value) is int and 0 <= value <= maximum,
             "INVALID_" + key.upper())
    return value


def _bool_or_none(value, key):
    _require(value is None or type(value) is bool,
             "INVALID_" + key.upper())
    return value


def _validated_case(raw):
    _require(isinstance(raw, dict) and raw.get("format") == FORMAT,
             "UNKNOWN_CASE_FORMAT")
    day, symbol, period, source = [raw.get(k) for k in
                                   ("trading_day", "symbol", "period", "source_id")]
    _require(isinstance(day, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day),
             "INVALID_TRADING_DAY")
    try:
        _require(date.fromisoformat(day).isoformat() == day, "INVALID_TRADING_DAY")
    except ValueError as exc:
        raise QualityPolicyError("INVALID_TRADING_DAY") from exc
    _require(isinstance(symbol, str) and SYMBOL.fullmatch(symbol),
             "INVALID_SYMBOL")
    _require(period in PERIODS if isinstance(period, str) else False,
             "INVALID_PERIOD")
    _require(isinstance(source, str) and SOURCE.fullmatch(source),
             "INVALID_SOURCE_ID")
    _require(raw.get("source_state") in ("READY", "UNAVAILABLE", "UNKNOWN"),
             "INVALID_SOURCE_STATE")
    for k in BOOLEAN_FIELDS:
        _bool_or_none(raw.get(k), k)
    for k in ("observed_bars", "expected_bars", "zero_prefix_bars"):
        if raw.get(k) is not None:
            _count(raw[k], k)
    for k in ("raw_source_sha256", "official_reference_sha256"):
        value = raw.get(k)
        _require(value is None or (isinstance(value, str) and HEX64.fullmatch(value)),
                 "INVALID_" + k.upper())
    for k in ("quoted_open", "first_traded_open", "official_open"):
        if raw.get(k) is not None:
            _positive(raw[k], k)
    fields = raw.get("fields_within_tolerance")
    if fields is not None:
        _require(isinstance(fields, dict) and fields
                 and set(fields) <= FIELD_SET, "INVALID_OHLCVA_FIELD_KEYS")
        for k, v in fields.items():
            _require(type(v) is bool, "INVALID_OHLCVA_FIELD_RESULT_" + k)
    # Persist only a JSON-serializable normalized record. This digest is NOT
    # raw source bytes, and does not make arbitrary adapter assertions true.
    try:
        canonical(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise QualityPolicyError("NONCANONICAL_CASE_EVIDENCE") from exc
    return raw


def analyze_case(raw):
    """Explain a single stock/day/source/period; never certify market admission."""
    obj = _validated_case(raw)
    findings = []

    def finding(rule, status, detail):
        findings.append({"rule_id": rule, "status": status,
                         "detail": detail, "suggested_action": ACTIONS[rule]})

    if obj.get("producer_quarantined") is True:
        finding("PRODUCER_QUARANTINED", "DETECTED",
                "ORIGINAL_PRODUCER_QUARANTINE_NOT_RESOLVED")
    if obj.get("declared_day_state_conflict") is True:
        finding("DECLARED_DAY_STATE_CONFLICT", "DETECTED",
                "CLAIMED_SOURCES_DISAGREE_NOT_AN_AUTHENTICATED_MARKET_FAILURE")
    if obj.get("declared_day_reference_uncertain") is True:
        finding("DECLARED_DAY_REFERENCE_UNCERTAIN", "INSUFFICIENT_EVIDENCE",
                "REFERENCE_COVERAGE_OR_TRADING_STATE_NOT_INDEPENDENTLY_VERIFIED")
    state = obj["source_state"]
    bars, expected = obj.get("observed_bars"), obj.get("expected_bars")
    official = obj.get("official_stock_day")
    if state == "UNAVAILABLE":
        finding("SOURCE_UNAVAILABLE", "DETECTED", "PROVIDER_OR_SOURCE_UNAVAILABLE")
    elif state == "UNKNOWN":
        finding("SOURCE_UNAVAILABLE", "INSUFFICIENT_EVIDENCE",
                "SOURCE_STATE_NOT_VERIFIED")
    if official is None:
        finding("OFFICIAL_DAY_EVIDENCE_MISSING", "INSUFFICIENT_EVIDENCE",
                "INDEPENDENT_OFFICIAL_STOCK_DAY_UNKNOWN")
    elif official is False:
        finding("OFFICIAL_DAY_EVIDENCE_MISSING", "INSUFFICIENT_EVIDENCE",
                "NOT_IN_REFERENCED_TRADING_UNIVERSE")
    if bars == 0 and official is True:
        if state == "READY":
            finding("MISSING_STOCK_DAY", "DETECTED", "OFFICIAL_STOCK_DAY_EMPTY_SOURCE")
        else:
            finding("MISSING_STOCK_DAY", "INSUFFICIENT_EVIDENCE",
                    "NEED_AVAILABLE_PROVIDER_TO_CONFIRM_LOCAL_GAP")
    if bars is not None and bars > 0:
        if expected is not None and bars != expected:
            finding("INCOMPLETE_TIME_GRID", "DETECTED",
                    "BAR_COUNT_DIFFERS_FROM_SOURCE_SPECIFIC_EXPECTATION")
        elif obj.get("grid_complete") is False:
            finding("INCOMPLETE_TIME_GRID", "DETECTED",
                    "EXCHANGE_GRID_REJECTED_BY_ADAPTER")
        elif obj.get("grid_complete") is None:
            finding("INCOMPLETE_TIME_GRID", "INSUFFICIENT_EVIDENCE",
                    "EXCHANGE_GRID_NOT_YET_CHECKED")
    if obj.get("receipt_integrity_valid") is False:
        finding("STORAGE_OR_RECEIPT_INTEGRITY", "DETECTED",
                "SOURCE_RECEIPT_OR_FILE_SHA_INVALID")
    if obj.get("calibration_drift_confirmed") is True:
        finding("UNIT_OR_CALIBRATION_DRIFT", "DETECTED",
                "INDEPENDENT_CALIBRATION_CONFLICT_PROVEN")
    elif obj.get("calibration_verified") is not True:
        finding("UNIT_OR_CALIBRATION_DRIFT", "INSUFFICIENT_EVIDENCE",
                "CALIBRATION_NOT_INDEPENDENTLY_VERIFIED")
    if obj.get("cross_period_consistent") is False:
        finding("CROSS_PERIOD_INCONSISTENCY", "DETECTED",
                "ADAPTER_FOUND_CROSS_PERIOD_DISAGREEMENT")
    if obj.get("source_conflict") is True:
        finding("SOURCE_CONFLICT", "DETECTED",
                "INDEPENDENT_PROVIDERS_DISAGREE_UNRESOLVED")
    if obj.get("volume_amount_pair_valid") is False:
        finding("INVALID_VOLUME_AMOUNT_PAIR", "DETECTED",
                "VOLUME_AND_AMOUNT_DO_NOT_COEXIST_AS_VALID_TRADE")
    elif obj.get("volume_amount_pair_valid") not in (None, True):
        raise QualityPolicyError("INVALID_VOLUME_AMOUNT_PAIR_VALID")
    if obj.get("zero_prefix_bars", 0):
        if obj.get("zero_prefix_verified") is True:
            finding("ZERO_TRADE_REFERENCE", "DETECTED",
                    "ZERO_VOLUME_AND_AMOUNT_REFERENCE_PREFIX")
        else:
            finding("ZERO_TRADE_REFERENCE", "INSUFFICIENT_EVIDENCE",
                    "ZERO_PREFIX_HAS_NOT_BEEN_VERIFIED")
    compared = obj.get("fields_within_tolerance") or {}
    bad_fields = sorted(k for k, v in compared.items() if v is False)
    if bad_fields:
        finding("OHLCVA_MISMATCH", "DETECTED",
                "INDEPENDENT_COMPARISON_FAILED_" + "_".join(bad_fields).upper())
    elif len(compared) != len(FIELD_SET):
        finding("OHLCVA_MISMATCH", "INSUFFICIENT_EVIDENCE",
                "SIX_FIELDS_NOT_ALL_INDEPENDENTLY_CHECKED")

    # "First trade matches official" is an advisory clue, not a repair:
    # official/day reference, traded-vs-quote, all-zero prefix and HLC
    # still require independent verification outside this pure policy core.
    quote, first, official_open = (
        obj.get("quoted_open"), obj.get("first_traded_open"),
        obj.get("official_open"))
    if quote is not None and official_open is not None and (
            not math.isclose(float(quote), float(official_open),
                             rel_tol=.006, abs_tol=.04)):
        strict = (first is not None and
                  math.isclose(float(first), float(official_open),
                               rel_tol=0, abs_tol=.0002))
        reliable = (obj.get("zero_prefix_bars", 0) > 0
                    and obj.get("zero_prefix_verified") is True
                    and obj.get("traded_hlc_verified") is True
                    and obj.get("tail_hlc_verified") is True
                    and official is True)
        finding("PRE_TRADE_QUOTE_OPEN",
                "DETECTED" if strict and reliable else "INSUFFICIENT_EVIDENCE",
                ("FIRST_REAL_TRADE_OFFICIAL_OPEN_CANDIDATE_ONLY"
                 if strict and reliable else "FIRST_TRADE_NOT_FULLY_CORROBORATED"))
    elif quote is not None and official_open is None:
        finding("PRE_TRADE_QUOTE_OPEN", "INSUFFICIENT_EVIDENCE",
                "INDEPENDENT_OFFICIAL_OPEN_MISSING")

    if obj.get("raw_source_sha256") is None or (
            official is True and obj.get("official_reference_sha256") is None):
        finding("SOURCE_PROVENANCE_UNVERIFIED", "INSUFFICIENT_EVIDENCE",
                "ORIGINAL_SOURCE_OR_REFERENCE_BYTE_HASH_NOT_SUPPLIED")

    detected = sorted(x["rule_id"] for x in findings if x["status"] == "DETECTED")
    uncertain = sorted(x["rule_id"] for x in findings if x["status"] == "INSUFFICIENT_EVIDENCE")
    actions = sorted({x["suggested_action"] for x in findings})
    scope = {k: obj[k] for k in ("trading_day", "symbol", "period", "source_id")}
    return {
        "format": REPORT,
        "scope": scope,
        "source_snapshot_sha256": obj.get("raw_source_sha256"),
        "official_reference_sha256": obj.get("official_reference_sha256"),
        "input_evidence_json_sha256": sha256(obj),
        "digest_scope": "NORMALIZED_CASE_JSON_NOT_PROVIDER_RAW_BYTES_OR_SIGNATURE",
        "detected_rules": detected, "unverified_rules": uncertain,
        "findings": findings,
        "suggested_readonly_actions": actions,
        "quality_state": "QUARANTINED" if detected else "UNVERIFIED",
        "planned_operation": "READ_ONLY_TRIAGE_NO_IO",
        "qmt_cache_write_authorized": False,
        "market_parquet_or_h5_write_authorized": False,
        "automatic_repair_authorized": False,
        "production_admission_authorized": False,
    }


def analyze_batch(records):
    _require(isinstance(records, list) and 0 < len(records) <= MAX_CASES,
             "INVALID_CASE_COLLECTION_SIZE")
    out = [analyze_case(rec) for rec in records]
    ids = [(x["scope"]["trading_day"], x["scope"]["symbol"],
            x["scope"]["period"], x["scope"]["source_id"],
            x["source_snapshot_sha256"]) for x in out]
    _require(len(ids) == len(set(ids)), "DUPLICATE_SOURCE_STOCK_DAY_SCOPE")
    out.sort(key=lambda x: (x["scope"]["trading_day"], x["scope"]["period"],
                            x["scope"]["symbol"], x["scope"]["source_id"]))
    return {
        "format": REPORT + "_batch",
        "case_count": len(out),
        "by_quality_state": dict(sorted(Counter(x["quality_state"] for x in out).items())),
        "cases": out, "source_data_read_by_engine": False,
        "market_files_modified": False, "source_download_calls": 0,
        "production_admission_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-json", type=Path, required=True,
                        help="Local JSON: either case object or list of cases; no uploads")
    args = parser.parse_args(argv)
    try:
        path = args.evidence_json
        _require(not path.is_symlink() and path.is_file()
                 and path.stat().st_size <= 8 * 1024 * 1024,
                 "EVIDENCE_FILE_MISSING_LINKED_OR_OVERSIZE")
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        result = analyze_batch(raw if isinstance(raw, list) else [raw])
        print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                         indent=2, allow_nan=False))
        return 0
    except (QualityPolicyError, TypeError, ValueError, OSError, OverflowError) as exc:
        print("MARKET_QUALITY_TRIAGE_REVIEW_REQUIRED: " + str(exc)[:180])
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
