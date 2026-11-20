"""V2-C non-certifying analysis of already observed minute timestamp labels.

Two common *hypotheses* are compared: session-open and session-close labels.
Neither is inferred to be the actual vendor contract, and no missing label
may be used for an automated backfill until separately authenticated.
This module never touches disk, QMT, the internet or user data sources.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re

CN = timezone(timedelta(hours=8))
PERIOD_MINUTES = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "60min": 60}
SESSIONS = ((9 * 60 + 30, 11 * 60 + 30), (13 * 60, 15 * 60))
MAX_LABELS = 512
MAX_SAMPLE = 8


class GridScopeError(ValueError):
    """Reject malformed minutes; never upgrade inference to certification."""


def _expected(period: str, profile: str) -> set[int]:
    if period not in PERIOD_MINUTES or profile not in ("OPEN", "CLOSE"):
        raise GridScopeError("unsupported_grid_profile")
    step = PERIOD_MINUTES[period]
    result = set()
    for first, last in SESSIONS:
        if (last - first) % step != 0:
            raise GridScopeError("nonintegral_session_period")
        start = first if profile == "OPEN" else first + step
        stop = last if profile == "OPEN" else last + 1
        result.update(range(start, stop, step))
    return result


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def inspect_minute_labels(*, period: str, day: str,
                          timestamps_ms: set[int] | tuple[int, ...] | list[int]) -> dict:
    """Analyze at most one stock/day/period of observed timestamp labels.

    No calendar/listing/auction contract is assumed. Candidate missing/excess
    labels are observational discrepancies to standard grid hypotheses ONLY.
    """
    if period not in PERIOD_MINUTES:
        raise GridScopeError("not_a_minute_period")
    if type(day) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is None:
        raise GridScopeError("bad_day_format")
    try:
        chosen_day = date.fromisoformat(day)
    except ValueError as exc:
        raise GridScopeError("bad_day_value") from exc
    if chosen_day.isoformat() != day:
        raise GridScopeError("noncanonical_day")
    if type(timestamps_ms) not in (set, tuple, list):
        raise GridScopeError("invalid_timestamp_collection")
    if len(timestamps_ms) > MAX_LABELS:
        raise GridScopeError("bounded_grid_label_count_exceeded")
    if any(type(value) is not int for value in timestamps_ms):
        raise GridScopeError("timestamp_must_be_int64_milliseconds")
    if len(timestamps_ms) != len(set(timestamps_ms)):
        raise GridScopeError("duplicate_timestamp_observation_unexpected")

    observed_clock = set()
    seconds_not_zero = 0
    outside_continuous = 0
    for stamp in timestamps_ms:
        try:
            dt = datetime.fromtimestamp(stamp / 1000, CN)
        except (ValueError, OverflowError, OSError) as exc:
            raise GridScopeError("timestamp_unrepresentable") from exc
        if dt.date() != chosen_day:
            raise GridScopeError("timestamp_day_mismatch")
        minute = dt.hour * 60 + dt.minute
        observed_clock.add(minute)
        if dt.second or dt.microsecond:
            seconds_not_zero += 1
        if not any(first <= minute <= last for first, last in SESSIONS):
            outside_continuous += 1

    base = {
        "period": period, "label_day": day,
        "observed_unique_timestamps": len(timestamps_ms),
        "off_minute_boundary_count": seconds_not_zero,
        "outside_continuous_sessions_count": outside_continuous,
        "grid_profile_source_certified": False,
        "official_exchange_calendar_verified": False,
        "stock_eligibility_verified": False,
        "minute_label_complete_certified": False,
        "allowed_to_backfill": False,
        "market_file_writes": False,
        "qmt_calls": 0,
    }
    if not timestamps_ms:
        return {
            **base, "status": "NO_MINUTE_ROWS_EXPECTATION_NOT_ESTABLISHED",
            "candidate_profile": None, "candidate_missing_labels": None,
            "candidate_extra_labels": None, "missing_sample": [],
            "extra_sample": [],
        }
    profiles = []
    for hypothesis in ("OPEN", "CLOSE"):
        expected = _expected(period, hypothesis)
        missing = expected - observed_clock
        extra = observed_clock - expected
        profiles.append({
            "profile": hypothesis, "missing": missing, "extra": extra,
            "distance": len(missing) + len(extra),
        })
    shortest = min(item["distance"] for item in profiles)
    closest = [item for item in profiles if item["distance"] == shortest]
    if len(closest) != 1:
        return {
            **base, "status": "TIME_LABEL_PROFILE_AMBIGUOUS_UNCERTIFIED",
            "candidate_profile": None, "candidate_missing_labels": None,
            "candidate_extra_labels": None, "missing_sample": [],
            "extra_sample": [],
            "hypothesis_distances": {item["profile"]: item["distance"]
                                     for item in profiles},
        }
    choice = closest[0]
    return {
        **base, "status": "TIME_LABEL_PROFILE_CANDIDATE_NOT_CERTIFIED",
        "candidate_profile": choice["profile"],
        "candidate_missing_labels": len(choice["missing"]),
        "candidate_extra_labels": len(choice["extra"]),
        "missing_sample": [_clock(x) for x in sorted(choice["missing"])[:MAX_SAMPLE]],
        "extra_sample": [_clock(x) for x in sorted(choice["extra"])[:MAX_SAMPLE]],
        "hypothesis_distances": {item["profile"]: item["distance"]
                                 for item in profiles},
    }
