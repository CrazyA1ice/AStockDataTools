"""V2-B2 conservative interpretation of V2-B read-only physical observations.

A locally supplied, explicitly SHA-pinned eligibility manifest can help label
non-trading, prelisting and suspension records. Its hash validates file
integrity ONLY; it is NOT a trusted independent exchange/source attestation.

No classification in this module authorizes data downloads or market writes.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re

FORMAT = "market_center_v2b2_eligibility_snapshot_v1"
MAX_BYTES = 64 * 1024
MAX_DAYS = 31
MAX_STOCKS = 20
SHA = re.compile(r"^[0-9a-f]{64}$")
SYMBOL = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
PERIODS = ("1min", "5min", "15min", "30min", "60min", "day", "week", "month")
CALENDAR_VALUES = ("TRADING", "NOT_TRADING", "UNKNOWN")
STOCK_VALUES = ("ELIGIBLE", "SUSPENDED", "UNKNOWN")


class EvidenceBlocked(ValueError):
    """Input evidence missing, inconsistent, or unverifiable; fail closed."""


def _strict_date(text: str) -> date:
    if type(text) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) is None:
        raise EvidenceBlocked("invalid_date_format")
    try:
        day = date.fromisoformat(text)
    except ValueError as exc:
        raise EvidenceBlocked("invalid_date_value") from exc
    if day.isoformat() != text:
        raise EvidenceBlocked("noncanonical_date")
    return day


def _days(start: str, end: str) -> list[str]:
    lo, hi = _strict_date(start), _strict_date(end)
    if hi < lo or (hi - lo).days >= MAX_DAYS:
        raise EvidenceBlocked("date_scope_not_supported")
    return [(lo + timedelta(days=i)).isoformat()
            for i in range((hi - lo).days + 1)]


def _validate(snapshot: dict, scope: dict) -> None:
    """Reject incomplete scope so no missing-date record can be mistaken."""
    if type(snapshot) is not dict or snapshot.get("format") != FORMAT:
        raise EvidenceBlocked("unknown_evidence_format")
    if type(scope) is not dict:
        raise EvidenceBlocked("missing_observation_scope")
    days = _days(scope.get("start"), scope.get("end"))
    stocks = scope.get("stocks")
    if (type(stocks) is not list or not 1 <= len(stocks) <= MAX_STOCKS
            or len(set(stocks)) != len(stocks)
            or any(type(s) is not str or SYMBOL.fullmatch(s) is None for s in stocks)):
        raise EvidenceBlocked("invalid_observation_stock_scope")
    if snapshot.get("scope") != {
        "start": scope["start"], "end": scope["end"], "stocks": stocks
    }:
        raise EvidenceBlocked("eligibility_scope_not_exactly_equal")
    calendar = snapshot.get("exchange_calendar")
    records = snapshot.get("stocks")
    provenance = snapshot.get("provenance")
    if (type(calendar) is not dict or type(records) is not dict
            or type(provenance) is not dict):
        raise EvidenceBlocked("missing_evidence_components")
    if set(records) != set(stocks):
        raise EvidenceBlocked("stock_eligibility_scope_incomplete")
    for key in ("calendar_source", "listing_source", "suspension_source"):
        val = provenance.get(key)
        if type(val) is not str or not 1 <= len(val.strip()) <= 200:
            raise EvidenceBlocked("missing_source_identity_" + key)
    used_exchanges = {s.split(".")[1] for s in stocks}
    if set(calendar) != used_exchanges:
        raise EvidenceBlocked("exchange_calendar_scope_incomplete")
    for exchange, entries in calendar.items():
        if type(entries) is not dict or set(entries) != set(days):
            raise EvidenceBlocked("exchange_calendar_days_incomplete_" + exchange)
        if any(val not in CALENDAR_VALUES for val in entries.values()):
            raise EvidenceBlocked("unknown_calendar_state_" + exchange)
    for symbol in stocks:
        info = records[symbol]
        if type(info) is not dict:
            raise EvidenceBlocked("invalid_stock_lifecycle_" + symbol)
        listed = _strict_date(info.get("listed_on"))
        ending = info.get("valid_through")
        if ending is not None:
            end_date = _strict_date(ending)
            if end_date < listed:
                raise EvidenceBlocked("invalid_stock_listing_window_" + symbol)
        states = info.get("day_states")
        if type(states) is not dict or set(states) != set(days):
            raise EvidenceBlocked("stock_status_days_incomplete_" + symbol)
        if any(state not in STOCK_VALUES for state in states.values()):
            raise EvidenceBlocked("unknown_stock_day_state_" + symbol)
        if any(day > date.today().isoformat() for day in days):
            # Never accept future assertions as authoritative.
            raise EvidenceBlocked("future_eligibility_claim_refused")


def load_pinned_evidence(path: str | Path, sha256: str, scope: dict) -> dict:
    """Explicit file path and expected SHA; no search or network access."""
    if type(sha256) is not str or SHA.fullmatch(sha256) is None:
        raise EvidenceBlocked("explicit_64_hex_sha256_required")
    target = Path(path)
    if (not target.is_absolute() or not target.is_file()
            or any(p.is_symlink() for p in (target, *target.parents))):
        raise EvidenceBlocked("unlinked_absolute_evidence_file_required")
    if target.stat().st_size > MAX_BYTES:
        raise EvidenceBlocked("eligibility_file_exceeds_64kb")
    original = target.read_bytes()
    if len(original) > MAX_BYTES or hashlib.sha256(original).hexdigest() != sha256:
        raise EvidenceBlocked("eligibility_sha256_mismatch")
    try:
        snapshot = json.loads(original.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise EvidenceBlocked("eligibility_json_invalid") from exc
    _validate(snapshot, scope)
    return {"document": snapshot, "sha256": sha256,
            "integrity_verified": True,
            "authenticity_independently_certified": False}


def classify(report: dict, evidence: dict | None = None) -> dict:
    """Add interpretations but never upgrade to CERTIFIED_MISSING or WRITE."""
    if (type(report) is not dict
            or report.get("status") != "V2B_BOUNDED_READONLY_OBSERVATION_NOT_CERTIFIED"
            or report.get("allowed_market_write") is not False):
        raise EvidenceBlocked("physical_observation_not_accepted")
    scope = report.get("scope")
    if type(scope) is not dict or type(report.get("observations")) is not list:
        raise EvidenceBlocked("invalid_observation_payload")
    if evidence is not None:
        if (type(evidence) is not dict
                or evidence.get("integrity_verified") is not True
                or evidence.get("authenticity_independently_certified") is not False):
            raise EvidenceBlocked("evidence_integrity_gate_failed")
        _validate(evidence.get("document"), scope)
    cal = evidence["document"]["exchange_calendar"] if evidence else {}
    lifecycle = evidence["document"]["stocks"] if evidence else {}
    absent_partitions = {
        (item.get("period"), item.get("partition"))
        for item in report.get("missing_partitions", [])
        if type(item) is dict
    }
    buckets = Counter()
    enriched = []
    for row in report["observations"]:
        if (type(row) is not dict or type(row.get("period")) is not str
                or row["period"] not in PERIODS
                or row.get("symbol") not in scope["stocks"]
                or row.get("timestamp_label_day") not in _days(scope["start"], scope["end"])
                or type(row.get("rows")) is not int or row["rows"] < 0
                or type(row.get("anomalies")) is not dict):
            raise EvidenceBlocked("invalid_observation_record")
        period, symbol = row["period"], row["symbol"]
        day = row["timestamp_label_day"]
        physical = row.get("status")
        if physical == "ANOMALY_OBSERVED":
            outcome = "PHYSICAL_ANOMALY_NEEDS_REVIEW"
        elif row["rows"] > 0 and physical == "ROWS_OBSERVED_UNCERTIFIED":
            outcome = "RECORDS_PRESENT_NOT_CERTIFIED"
        elif row["rows"] != 0 or physical != "NO_ROWS_OBSERVED":
            raise EvidenceBlocked("inconsistent_observation_status")
        elif period in ("week", "month"):
            outcome = "LONG_CYCLE_LABEL_NEEDS_CLOSURE_PROOF"
        elif (period, day[:7]) in absent_partitions:
            # An absent physical shard is a file-level issue, not proof that
            # each chosen stock is individually missing an expected bar.
            outcome = "PHYSICAL_PARTITION_MISSING_STOCK_GAP_UNDETERMINED"
        elif not evidence:
            outcome = "NO_ROWS_CALENDAR_AND_ELIGIBILITY_UNKNOWN"
        else:
            exchange = symbol.rsplit(".", 1)[-1]
            trading = cal[exchange][day]
            item = lifecycle[symbol]
            first = item["listed_on"]
            last = item["valid_through"]
            state = item["day_states"][day]
            if trading == "NOT_TRADING":
                outcome = "NO_ROWS_NONTRADING_DECLARED_UNCERTIFIED"
            elif day < first:
                outcome = "NO_ROWS_PRELISTING_DECLARED_UNCERTIFIED"
            elif last is not None and day > last:
                outcome = "NO_ROWS_POSTLISTING_DECLARED_UNCERTIFIED"
            elif trading == "TRADING" and state == "SUSPENDED":
                outcome = "NO_ROWS_SUSPENDED_DECLARED_UNCERTIFIED"
            elif trading == "TRADING" and state == "ELIGIBLE":
                outcome = "MISSING_CANDIDATE_SOURCE_AUTHENTICITY_UNVERIFIED"
            else:
                outcome = "NO_ROWS_ELIGIBILITY_INDETERMINATE"
        buckets[outcome] += 1
        enriched.append({
            "period": period, "symbol": symbol, "label_day": day,
            "rows": row["rows"], "physical_status": physical,
            "interpretation": outcome, "anomalies": row["anomalies"],
        })
    return {
        "status": "V2B2_EVIDENCE_GATED_CANDIDATES_NOT_CERTIFIED",
        "source_integrity_checked": bool(evidence),
        "source_authenticity_certified": False,
        "calendar_complete_for_scope": bool(evidence),
        "listing_and_suspension_evidence_complete_for_scope": bool(evidence),
        "source_crosscheck_completed": False,
        "actual_trading_calendar_verified": False,
        "confirmed_missing_count": 0,
        "allowed_repair_or_backfill": False,
        "market_file_writes": False,
        "qmt_calls": 0,
        "evidence_sha256": evidence["sha256"] if evidence else None,
        "summary": dict(buckets),
        "observations": enriched,
    }
