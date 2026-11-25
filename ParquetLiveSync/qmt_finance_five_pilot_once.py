#!/usr/bin/env python3
"""Guarded cache-only five-stock rehearsal for versioned financial revisions.

Selected immutable snapshot union and all nine live cache tables are compared
via the already audited PURE qmt_finance_versioned_recovery_preview module.
NO download, approval, Parquet commit, active-pin change, or pending clearance.
The known broken 688259.SH Top10Holder provider entry is never requested.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

CASES = (
    ("002178.SZ", "Top10Holder", "ISSUER_DISPUTED"),
    ("002188.SZ", "Capital", "CAPITAL_ADDITIVE"),
    ("002310.SZ", "Top10Holder", "ISSUER_DISPUTED"),
    ("002328.SZ", "HolderNum", "ISSUER_DISPUTED"),
    ("002388.SZ", "Top10FlowHolder", "HOLDER_METADATA"),
)
LEDGER_FORMAT = "qmt_financial_cache_import_v1"
KNOWN_LEDGER_DATE = "2026-11-24"
KNOWN_LEDGER_SHA256 = "4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1"
KNOWN_PENDING = 54
HEX = re.compile(r"[0-9a-f]{64}\Z")
BEIJING_TZ = timezone(timedelta(hours=8))


def china_now():
    return datetime.now(BEIJING_TZ)


def protect_time(now=None):
    now = now or china_now()
    m = now.hour * 60 + now.minute
    if 18 * 60 + 45 <= m < 23 * 60 + 35:
        raise RuntimeError("PILOT_NIGHTLY_WINDOW_STOP")


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_ledger(state, ledger_hash):
    if ledger_hash != KNOWN_LEDGER_SHA256:
        raise ValueError("PILOT_LEDGER_CHANGED_SINCE_VERIFIED_AUDIT")
    if (not isinstance(state, dict) or state.get("format") != LEDGER_FORMAT
            or state.get("daily_date") != KNOWN_LEDGER_DATE
            or not isinstance(state.get("root"), str)
            or not isinstance(state.get("pending"), dict)
            or len(state["pending"]) != KNOWN_PENDING):
        raise ValueError("PILOT_VERIFIED_AUDIT_SCOPE_CHANGED")
    pending = state["pending"]
    if (not isinstance(pending.get("688259.SH"), dict)
            or pending["688259.SH"].get("reason") != "CACHE_DECODE_ERROR"):
        raise ValueError("PILOT_KNOWN_UTF8_QUARANTINE_CHANGED")
    for code, table, _ in CASES:
        item = pending.get(code)
        if not isinstance(item, dict) or item.get("reason") != "SOURCE_HISTORY_CONFLICT":
            raise ValueError("PILOT_PENDING_STATUS_CHANGED_" + code)
        if re.search(r"\btable=" + re.escape(table) + r"\b",
                     str(item.get("detail", ""))) is None:
            raise ValueError("PILOT_PENDING_TABLE_CHANGED_" + code)


def verify_evidence(doc):
    if (not isinstance(doc, dict)
            or doc.get("schema") != "astock_finance_source_disclosure_proof_v1"
            or doc.get("allow_auto_clear") is not False
            or doc.get("allow_snapshot_mutation") is not False
            or doc.get("allow_provider_cache_mutation") is not False
            or doc.get("default_action") != "HOLD_PENDING_NO_COMMIT"
            or doc.get("ledger_sha256_unchanged") != KNOWN_LEDGER_SHA256):
        raise ValueError("PILOT_EVIDENCE_MANIFEST_NOT_FAIL_CLOSED")
    cases = doc.get("cases")
    if (not isinstance(cases, list) or len(cases) != 3
            or {x.get("symbol") for x in cases if isinstance(x, dict)}
            != {"002178.SZ", "002310.SZ", "002328.SZ"}):
        raise ValueError("PILOT_ISSUER_CASE_SCOPE_CHANGED")
    if any(not isinstance(x, dict) or x.get("manual_approval_required") is not True
           or x.get("pairing_unambiguous") is not True for x in cases):
        raise ValueError("PILOT_ISSUER_APPROVAL_SCOPE_CHANGED")
    return {
        "format": doc["schema"],
        "allow_auto_clear": doc["allow_auto_clear"],
        "default_action": doc["default_action"],
        "cases": cases,
    }


def verified_histories(extra, code, E, F):
    """_prior_rows verifies every selected/pinned historical Parquet snapshot."""
    history = {}
    summary = {}
    for table in E.FIN_TABLES:
        latest, old = F._prior_rows(extra, code, table)
        if old is None:
            old = Counter()
        if not isinstance(old, Counter):
            raise ValueError("PILOT_INVALID_VERIFIED_COUNTER_" + code + "_" + table)
        history[table] = old
        summary[table] = {
            "selected_latest_asof": latest,
            "raw_versions": sum(old.values()),
            # Fingerprint full selected record multiset without emitting source data.
            "selected_union_sha256": hashlib.sha256(
                E.canonical_json(sorted(old.items())).encode("utf-8")).hexdigest()
        }
    return history, summary


def run(base, manifest_path, E, F, P, *, expected_ledger_sha=KNOWN_LEDGER_SHA256):
    base = Path(base)
    ledger = base / "work" / "qmt_extra" / "financial-cache-progress.json"
    before = digest_file(ledger)
    try:
        protect_time()
        if before != expected_ledger_sha:
            raise ValueError("PILOT_EXPLICIT_LEDGER_PIN_CHANGED")
        state = json.loads(ledger.read_text(encoding="utf-8"))
        verify_ledger(state, before)
        source_root = Path(state["root"])
        E._path_check(source_root)
        if not source_root.is_dir() or source_root.is_symlink():
            raise ValueError("PILOT_SOURCE_ROOT_INVALID")
        manifest_path = Path(manifest_path)
        E._path_check(manifest_path)
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ValueError("PILOT_ISSUER_MANIFEST_PATH_INVALID")
        evidence = verify_evidence(json.loads(manifest_path.read_text(encoding="utf-8")))
        # All source/provenance scope checks above happen before calling QMT.
        codes = [code for code, _, _ in CASES]
        assert codes == sorted(set(codes)) and "688259.SH" not in codes
        print("PILOT_COHORT=5_CACHE_ONLY", flush=True)
        print("PILOT_LEDGER_BEFORE_SHA256=" + before)
        print("PILOT_LEDGER_DAILY_DATE=" + state["daily_date"])
        with tempfile.TemporaryDirectory(prefix="finance-five-pilot-readonly-") as tmp:
            protect_time()
            cache, missing = F._worker_batch(
                codes, "cache", state["daily_date"], 120, tmp, 120,
                progress=lambda msg: print("PILOT_CACHE_WORKER=" + msg, flush=True))
            if missing or set(cache) != set(codes):
                raise RuntimeError("PILOT_QMT_EXISTING_CACHE_NOT_COMPLETE")
            history = {}
            versions = {}
            for code, table, mode in CASES:
                protect_time()
                past, summary = verified_histories(source_root, code, E, F)
                if not past[table]:
                    raise ValueError("PILOT_TARGET_HISTORICAL_SNAPSHOT_MISSING_" + code)
                history[code] = past
                versions[code] = summary
            cases = [{"symbol": code, "table": table, "mode": mode}
                     for code, table, mode in CASES]
            # The source-version preview is a pure function: NO apply route.
            report = P.preview_cohort(
                cases, history, cache, F, evidence=evidence,
                ledger_sha256=before, expected_count=5)
            if (report.get("symbols") != 5 or report.get("allow_apply") is not False
                    or report.get("allow_auto_clear") is not False
                    or report.get("records_modified") is not False
                    or report.get("snapshots_modified") is not False
                    or report.get("review_only", -1) + report.get("blocked", -1) != 5):
                raise RuntimeError("PILOT_UNSAFE_PREVIEW_RESULT")
            for item in report["evidence_only"]:
                code = item["symbol"]
                print("PILOT_REVIEW=" + json.dumps({
                    **item,
                    "target_historical_versions":
                        versions[code][next(t for c, t, m in CASES if c == code)]["raw_versions"],
                    "nine_table_selected_union_sha256": hashlib.sha256(
                        E.canonical_json(versions[code]).encode("utf-8")).hexdigest(),
                    "approval_granted": False,
                }, ensure_ascii=True, sort_keys=True), flush=True)
            for item in report["quarantined"]:
                print("PILOT_BLOCKED=" + json.dumps(item, sort_keys=True), flush=True)
            print("PILOT_SUMMARY=" + json.dumps({
                "review_only": report["review_only"],
                "blocked": report["blocked"],
                "cohort_sha256": report["cohort_sha256"],
                "ledger_before_sha256": before,
                "allow_apply": False, "allow_auto_clear": False,
                "no_data_commit": True
            }, sort_keys=True), flush=True)
    finally:
        after = digest_file(ledger)
        if after != before:
            raise RuntimeError("PILOT_FINANCE_LEDGER_CHANGED_DURING_RUN_STOP")
        print("FINANCE_LEDGER_UNCHANGED_VERIFIED sha256=" + after, flush=True)
    # A successful preview is not complete until the final ledger integrity
    # check has returned successfully. Never print a success marker from the
    # try body; a finally exception must prevent it.
    print("FINANCE_FIVE_STOCK_PREVIEW_COMPLETE_NO_COMMIT", flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger-sha", default=KNOWN_LEDGER_SHA256)
    args = parser.parse_args(argv)
    if args.ledger_sha != KNOWN_LEDGER_SHA256:
        parser.error("ledger SHA must match the already verified audit epoch")
    if not args.base.is_dir() or args.base.is_symlink():
        parser.error("invalid production directory")
    protect_time()
    # First import PURE preview from staged code, production modules from
    # the explicit canonical source directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(1, str(args.base))
    import qmt_extra_financial_cache_import as F
    import qmt_extra_data as E
    import qmt_finance_versioned_recovery_preview as P
    run(args.base, args.manifest, E, F, P,
        expected_ledger_sha=args.ledger_sha)


if __name__ == "__main__":
    main()
