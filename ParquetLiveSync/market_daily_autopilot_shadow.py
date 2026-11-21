"""Read-only daily autopilot health classification for AStockDataTools.

SHADOW ONLY: no scheduler, notifier, QMT API, downloads or market data writes.
Report execution, coverage and verification as SEPARATE dimensions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

STAGES = ("EIGHT_PERIODS", "SECTORS", "ADJUSTMENTS_ROTATING", "FINANCIAL_DAILY")
VALIDATION = frozenset(("PASS", "PARTIAL", "FAIL", "UNVERIFIED", "NOT_RUN"))
REASONS = frozenset(("SOURCE_HISTORY_CONFLICT", "CACHE_DECODE_ERROR", "NO_CACHE"))
MAX_RECEIPT = 2 * 1024 * 1024
MAX_PROGRESS = 2 * 1024 * 1024
MASS_CONFLICT_LIMIT = 500
STOCK = re.compile(r"[0-9]{6}\.(?:SZ|SH|BJ)")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class HealthBlocked(ValueError):
    """Invalid evidence cannot be converted into a green daily status."""


def _regular_file(path: Path, limit: int) -> tuple[dict, str]:
    if (not path.is_absolute()
            or any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file()):
        raise HealthBlocked("missing_or_redirected_daily_health_source")
    if not 0 < path.stat().st_size <= limit:
        raise HealthBlocked("daily_health_source_size_budget")
    raw = path.read_bytes()
    if not raw or len(raw) > limit:
        raise HealthBlocked("daily_health_source_read_budget")
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise HealthBlocked("malformed_daily_health_source_json") from exc
    if type(obj) is not dict:
        raise HealthBlocked("daily_health_source_not_object")
    return obj, sha256(raw).hexdigest()


def _run_day(receipt: dict) -> str:
    start = receipt.get("china_start")
    if type(start) is not str or len(start) < 10:
        raise HealthBlocked("daily_receipt_run_day_missing")
    d = start[:10]
    if DATE.fullmatch(d) is None:
        raise HealthBlocked("daily_receipt_run_day_invalid")
    try:
        if date.fromisoformat(d).isoformat() != d:
            raise ValueError("noncanonical")
    except ValueError as exc:
        raise HealthBlocked("daily_receipt_run_day_invalid") from exc
    return d


def classify(receipt: dict, ledger: dict) -> dict:
    """Pure, conservative classification. No side effects or permission grants."""
    if (type(receipt) is not dict
            or receipt.get("format") != "qmt_daily_single_trigger_v3"
            or receipt.get("mode") != "UNIFIED_SINGLE_RUN"
            or receipt.get("status") not in ("SUCCESS", "PARTIAL", "FAILED")
            or type(receipt.get("stage_records")) is not dict
            or type(receipt.get("errors")) is not list
            or type(ledger) is not dict
            or ledger.get("format") != "qmt_financial_cache_import_v1"
            or type(ledger.get("pending")) is not dict
            or type(ledger.get("daily_cursor")) is not str
            or type(ledger.get("daily_date")) is not str):
        raise HealthBlocked("incompatible_daily_receipt_or_ledger")
    run_day = _run_day(receipt)
    counts = Counter()
    for stock, item in ledger["pending"].items():
        if (type(stock) is not str or STOCK.fullmatch(stock) is None
                or type(item) is not dict
                or item.get("reason") not in REASONS
                or type(item.get("attempts")) is not int
                or item["attempts"] < 1):
            raise HealthBlocked("invalid_pending_entry_for_health_classification")
        counts[item["reason"]] += 1
    section_source = receipt.get("validation")
    sections = (section_source.get("sections")
                if type(section_source) is dict else None)
    stages = []
    errors = []
    unverified = []
    quality_failures = []
    planned = []
    for name in STAGES:
        record = receipt["stage_records"].get(name)
        if type(record) is not dict or type(record.get("exit_code")) is not int:
            errors.append(name + "_MISSING_OR_INVALID_EXIT")
            exit_code = None
        else:
            exit_code = record["exit_code"]
            if exit_code != 0:
                errors.append(name + "_NONZERO_EXIT")
        section = sections.get(name) if type(sections) is dict else None
        qa = section.get("data_validation") if type(section) is dict else None
        cross = section.get("cross_validation") if type(section) is dict else None
        if qa not in VALIDATION:
            qa = "UNVERIFIED"
        if cross not in VALIDATION:
            cross = "UNVERIFIED"
        if qa == "FAIL" or cross == "FAIL":
            quality_failures.append(name)
        if qa in ("UNVERIFIED", "NOT_RUN") or cross in ("UNVERIFIED", "NOT_RUN"):
            unverified.append(name)
        if exit_code == 0 and qa == "PARTIAL" and name in (
                "FINANCIAL_DAILY", "ADJUSTMENTS_ROTATING"):
            planned.append(name)
        stages.append({
            "stage": name, "exit_code": exit_code,
            "data_validation": qa, "cross_validation": cross,
        })
    if any(type(e) is not str for e in receipt["errors"]):
        raise HealthBlocked("invalid_daily_runner_error_list")
    if receipt["errors"]:
        errors.append("RUNNER_REPORTED_ERRORS")
    if receipt.get("qmt_preflight_status") == "QMT_SERVICE_UNAVAILABLE":
        errors.append("QMT_SERVICE_UNAVAILABLE")
    if ledger["daily_date"] != run_day:
        errors.append("FINANCE_PROGRESS_DATE_DIFFERS_FROM_RUN")
    if counts["SOURCE_HISTORY_CONFLICT"] >= MASS_CONFLICT_LIMIT:
        errors.append("FINANCE_MASS_CONFLICT_SAFETY_REVIEW")
    finance = (sections.get("FINANCIAL_DAILY")
               if type(sections) is dict else None)
    remaining = (finance.get("remaining_unvisited")
                 if type(finance) is dict else None)
    processed = finance.get("processed") if type(finance) is dict else None
    if type(remaining) is not int or remaining < 0:
        remaining = None
    if type(processed) is not int or processed < 0:
        processed = None
    reached_end = ledger.get("daily_sweep_reached_end")
    if type(reached_end) is not bool:
        reached_end = None
    if not errors and not quality_failures:
        if type(sections) is not dict:
            state, alert = "EXECUTED_VERIFICATION_MISSING", "REVIEW"
        else:
            state, alert = "ROUTINE_CONTINUATION", "NONE"
    else:
        state, alert = "ATTENTION_REQUIRED", "ACTION"
    if quality_failures and alert != "ACTION":
        state, alert = "ATTENTION_REQUIRED", "ACTION"
    # Coverage is not a binary success flag. Pending may remain even after
    # reaching the end of a stock universe.
    if reached_end is False:
        coverage = "SWEEP_IN_PROGRESS"
    elif reached_end is True:
        coverage = "SWEEP_REACHED_END_PENDING_SEPARATE"
    else:
        coverage = "SWEEP_STATUS_UNVERIFIED"
    return {
        "status": "DAILY_AUTOPILOT_SHADOW_REPORT_NO_EXECUTION",
        "run_day": run_day,
        "receipt_execution_status": receipt["status"],
        "execution_health": state,
        "alert_policy_preview": alert,
        "daily_notification_needed": alert == "ACTION",
        "stage_checks": stages,
        "stage_execution_errors": errors,
        "stage_quality_failures": sorted(set(quality_failures)),
        "unverified_stage_labels": sorted(set(unverified)),
        "normal_partial_stages": sorted(set(planned)),
        "coverage": {
            "financial_sweep": coverage,
            "financial_daily_cursor": ledger["daily_cursor"],
            "financial_daily_sweep_start": ledger.get("daily_sweep_start"),
            "financial_daily_sweep_finished": ledger.get("daily_sweep_finished"),
            "financial_today_processed": processed,
            "financial_remaining_unvisited": remaining,
            "pending_total": len(ledger["pending"]),
            "pending_by_reason": {
                reason: counts[reason] for reason in sorted(REASONS)
            },
            "financial_history_completeness_certified": False,
        },
        "data_quality": {
            "current_run_validation": (section_source.get("data_validation")
                                       if type(section_source) is dict
                                       else "UNVERIFIED"),
            "cross_source_validation": (section_source.get("cross_validation")
                                        if type(section_source) is dict
                                        else "UNVERIFIED"),
            "cannot_assume_unverified_means_pass": True,
            "pending_versions_not_auto_approved": True,
        },
        "notification_delivery_enabled": False,
        "scheduler_modified": False,
        "can_retry_financial_updates": False,
        "can_download": False,
        "can_write_market": False,
        "qmt_calls": 0,
        "writes": 0,
    }


def inspect(module: Path | str) -> dict:
    root = Path(module)
    if (not root.is_absolute() or root.name.lower() != "parquetlivesync"
            or not root.is_dir()
            or any(p.is_symlink() for p in (root, *root.parents))):
        raise HealthBlocked("canonical_parquetlivesync_module_required")
    receipt_path = root / "work" / "last-afternoon-unified.json"
    progress_path = root / "work" / "qmt_extra" / "financial-cache-progress.json"
    receipt, receipt_sha = _regular_file(receipt_path, MAX_RECEIPT)
    progress, progress_sha = _regular_file(progress_path, MAX_PROGRESS)
    report = classify(receipt, progress)
    for path, sha, limit in (
            (receipt_path, receipt_sha, MAX_RECEIPT),
            (progress_path, progress_sha, MAX_PROGRESS)):
        # A concurrent scheduled commit invalidates an old comparison.
        if (path.is_symlink() or path.stat().st_size > limit
                or sha256(path.read_bytes()).hexdigest() != sha):
            raise HealthBlocked("daily_health_source_changed_during_read")
    report["receipt_sha256"] = receipt_sha
    report["financial_progress_sha256"] = progress_sha
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-module", type=Path, required=True)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({
            "status": "DAILY_AUTOPILOT_EXPLICIT_READONLY_REQUIRED",
            "qmt_calls": 0, "writes": 0,
        }, ensure_ascii=False))
        return 2
    try:
        report = inspect(args.state_module)
    except (HealthBlocked, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "DAILY_AUTOPILOT_SHADOW_BLOCKED",
            "reason": str(exc)[:160], "qmt_calls": 0, "writes": 0,
        }, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
