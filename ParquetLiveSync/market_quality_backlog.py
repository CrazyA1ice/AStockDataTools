#!/usr/bin/env python3
"""Reusable, stable-ID, read-only quality-incident backlog for market sources.

Accepts generic quality-engine output or the SHA-checked daily receipt adapter.
Never treats an absent failure or a new source revision as permission to close
older quarantines. Never performs remediation, downloads, or market-data writes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path

import market_quality_engine as Q

FORMAT = "astock_market_quality_backlog_readonly_v1"
SEVERE = frozenset({"STORAGE_OR_RECEIPT_INTEGRITY"})
HIGH = frozenset({"PRODUCER_QUARANTINED", "MISSING_STOCK_DAY",
                  "INCOMPLETE_TIME_GRID", "OHLCVA_MISMATCH",
                  "INVALID_VOLUME_AMOUNT_PAIR"})
MAX_ISSUES = 200000
MAX_JSON_BYTES = 16 * 1024 * 1024


class BacklogError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise BacklogError(message)


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(obj):
    return sha256(canonical(obj)).hexdigest()


def _is_sha(val):
    return isinstance(val, str) and bool(Q.HEX64.fullmatch(val))


def _validate_scope(scope):
    require(isinstance(scope, dict) and set(scope) ==
            {"trading_day", "symbol", "period", "source_id"}, "INVALID_INCIDENT_SCOPE")
    require(isinstance(scope["trading_day"], str), "INVALID_INCIDENT_DATE")
    try:
        from datetime import date
        require(date.fromisoformat(scope["trading_day"]).isoformat() ==
                scope["trading_day"], "INVALID_INCIDENT_DATE")
    except ValueError as exc:
        raise BacklogError("INVALID_INCIDENT_DATE") from exc
    require(isinstance(scope["symbol"], str) and Q.SYMBOL.fullmatch(scope["symbol"]),
            "INVALID_INCIDENT_SYMBOL")
    require(scope["period"] in Q.PERIODS, "INVALID_INCIDENT_PERIOD")
    require(isinstance(scope["source_id"], str) and Q.SOURCE.fullmatch(scope["source_id"]),
            "INVALID_INCIDENT_SOURCE")


def build_backlog(quality_batch):
    """Deterministic across case/finding order; evidence revisions never auto-close."""
    require(isinstance(quality_batch, dict) and quality_batch.get("format") ==
            Q.REPORT + "_batch", "UNKNOWN_QUALITY_BATCH_FORMAT")
    cases = quality_batch.get("cases")
    require(isinstance(cases, list) and len(cases) <= Q.MAX_CASES and
            type(quality_batch.get("case_count")) is int and
            quality_batch["case_count"] == len(cases), "QUALITY_CASE_COUNT_MISMATCH")
    groups = defaultdict(dict)
    original_observations = 0
    for case in cases:
        require(isinstance(case, dict) and case.get("format") == Q.REPORT,
                "INVALID_QUALITY_CASE_FORMAT")
        scope = case.get("scope")
        _validate_scope(scope)
        identity_hash = case.get("input_evidence_json_sha256")
        require(_is_sha(identity_hash), "QUALITY_EVIDENCE_DIGEST_MISSING")
        source_hash = case.get("source_snapshot_sha256")
        require(source_hash is None or _is_sha(source_hash),
                "INVALID_SOURCE_SNAPSHOT_DIGEST")
        require(case.get("production_admission_authorized") is False and
                case.get("qmt_cache_write_authorized") is False and
                case.get("market_parquet_or_h5_write_authorized") is False,
                "UPSTREAM_AUTHORITY_CHANGED_STOP")
        findings = case.get("findings")
        require(isinstance(findings, list), "MISSING_QUALITY_FINDINGS")
        seen_rules = set()
        detected, unknown = set(), set()
        for f in findings:
            require(isinstance(f, dict), "INVALID_FINDING")
            rule, state = f.get("rule_id"), f.get("status")
            require(isinstance(rule, str) and rule in Q.ACTIONS and
                    rule not in seen_rules, "DUPLICATE_OR_UNKNOWN_RULE")
            require(state in ("DETECTED", "INSUFFICIENT_EVIDENCE"),
                    "INVALID_FINDING_STATUS")
            require(f.get("suggested_action") == Q.ACTIONS[rule],
                    "UNTRUSTED_FINDING_ACTION")
            seen_rules.add(rule)
            (detected if state == "DETECTED" else unknown).add(rule)
            key = digest({"scope": scope, "rule_id": rule})
            version = {"case_evidence_json_sha256": identity_hash.lower(),
                       "raw_source_sha256_if_supplied":
                           source_hash.lower() if source_hash else None,
                       "finding_status": state}
            variant_hash = digest(version)
            prior = groups[key].get(variant_hash)
            if prior is not None:
                require(prior["finding"] == version, "REVISION_HASH_COLLISION_STOP")
                prior["observed_count"] += 1
            else:
                groups[key][variant_hash] = {
                    "scope": scope.copy(), "rule_id": rule, "finding": version,
                    "observed_count": 1}
            original_observations += 1
        require(detected == set(case.get("detected_rules", [])) and
                unknown == set(case.get("unverified_rules", [])),
                "FINDING_SUMMARY_MISMATCH")
        expected_state = "QUARANTINED" if detected else "UNVERIFIED"
        require(case.get("quality_state") == expected_state,
                "QUALITY_STATE_INCONSISTENT_WITH_FINDINGS")
    require(len(groups) <= MAX_ISSUES, "TOO_MANY_INCIDENTS")
    issues = []
    for issue_id, variants in groups.items():
        elements = sorted(variants.values(), key=lambda x:
                          (x["finding"]["case_evidence_json_sha256"],
                           x["finding"]["finding_status"],
                           x["finding"]["raw_source_sha256_if_supplied"] or ""))
        item = elements[0]
        statuses = {part["finding"]["finding_status"] for part in elements}
        state = "OPEN_QUARANTINED" if "DETECTED" in statuses else "NEEDS_EVIDENCE"
        rule = item["rule_id"]
        priority = ("P0" if rule in SEVERE and state == "OPEN_QUARANTINED" else
                    "P1" if rule in HIGH and state == "OPEN_QUARANTINED" else
                    "P2" if state == "OPEN_QUARANTINED" else "P3")
        revision = len(elements) > 1
        issues.append({
            "incident_id": issue_id,
            "scope": item["scope"],
            "rule_id": rule,
            "priority": priority,
            "state": state,
            "evidence_versions": [e["finding"] for e in elements],
            "evidence_version_count": len(elements),
            "repeated_observations": sum(e["observed_count"] for e in elements),
            "revision_review_required": revision,
            "review_reason": "SOURCE_EVIDENCE_REVISIONS_NOT_AUTO_RESOLVED" if revision else None,
            "recommended_readonly_action": Q.ACTIONS[rule],
            "market_repair_authorized": False,
            "automatic_closure_authorized": False,
        })
    issues.sort(key=lambda x: (x["priority"], x["scope"]["trading_day"],
                               x["scope"]["symbol"], x["scope"]["period"],
                               x["scope"]["source_id"], x["rule_id"]))
    report = {
        "format": FORMAT,
        "case_count": len(cases),
        "findings_observed_including_repeats": original_observations,
        "unique_incidents": len(issues),
        "issue_counts_by_state": dict(sorted(Counter(i["state"] for i in issues).items())),
        "issues_requiring_revision_review": sum(i["revision_review_required"] for i in issues),
        "issues": issues,
        "source_evidence_sha_scope": "NORMALIZED_CASE_JSON_ONLY_UNLESS_RAW_SOURCE_HASH_EXPLICIT",
        "automatic_repair_authorized": False,
        "automatic_closure_authorized": False,
        "qmt_cache_download_calls": 0,
        "market_files_written": False,
        "market_quality_cleared": False,
    }
    report["backlog_sha256"] = digest(report)
    return report


def from_daily_receipts(root, *, start_day, end_day, reader=None):
    """Read and hash existing producer receipts; never write or infer closed days."""
    if reader is None:
        from market_quality_receipt_adapter import classify_daily
        reader = classify_daily
    receipt = reader(root, start_day=start_day, end_day=end_day)
    require(isinstance(receipt, dict) and receipt.get("status") ==
            "READ_ONLY_DAILY_QUARANTINE_QUALITY_TRIAGE", "BAD_DAILY_ADAPTER_RECEIPT")
    require(receipt.get("project_market_files_modified") is False and
            receipt.get("data_quality_cleared") is False and
            receipt.get("production_merge_authorized") is False,
            "DAILY_ADAPTER_AUTHORITY_CHANGED_STOP")
    output = build_backlog(receipt["quality_cases"])
    output["daily_receipts_checked"] = receipt["existing_day_receipts_checked"]
    output["original_producer_quarantines_preserved"] = receipt["producer_quarantines_preserved"]
    output["accepted_stock_days_reported_not_independently_verified"] = receipt[
        "producer_accepted_stock_days_reported_not_recrossvalidated"]
    output["official_day_independently_certified"] = False
    output["original_raw_qmt_independently_certified"] = False
    output["backlog_sha256"] = digest({k: v for k, v in output.items()
                                      if k != "backlog_sha256"})
    return output


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--module-root", type=Path)
    p.add_argument("--start-day")
    p.add_argument("--end-day")
    p.add_argument("--quality-json", type=Path)
    args = p.parse_args(argv)
    try:
        if args.quality_json is not None:
            require(args.module_root is None and args.start_day is None
                    and args.end_day is None, "SELECT_ONLY_ONE_READ_SOURCE")
            path = args.quality_json
            require(path.is_file() and not path.is_symlink() and
                    0 < path.stat().st_size <= MAX_JSON_BYTES,
                    "QUALITY_JSON_MISSING_LINKED_OR_OVERSIZE")
            def unique_keys(pairs):
                data = {}
                for key, value in pairs:
                    require(key not in data, "DUPLICATE_JSON_KEY")
                    data[key] = value
                return data
            src = json.loads(path.read_text(encoding="utf-8-sig"),
                             object_pairs_hook=unique_keys)
            result = build_backlog(src)
        else:
            require(args.module_root is not None and args.start_day is not None
                    and args.end_day is not None, "DATE_RANGE_AND_MODULE_ROOT_REQUIRED")
            result = from_daily_receipts(args.module_root,
                                         start_day=args.start_day,
                                         end_day=args.end_day)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True,
                         allow_nan=False))
        return 0
    except (BacklogError, OSError, ValueError, TypeError, KeyError) as exc:
        print("MARKET_BACKLOG_REVIEW_REQUIRED: " + str(exc)[:180])
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
