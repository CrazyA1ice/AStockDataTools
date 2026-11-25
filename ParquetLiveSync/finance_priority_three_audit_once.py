#!/usr/bin/env python3
"""Read-only, targeted evidence for three material QMT finance revisions.

No market-data downloads, source mutations, Parquet commits, pending clearing,
cursor updates, scheduled-task changes, lossy decoding, or policy activation.
Run only with the existing Windows runner mutex and idle-task guard.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unicodedata

CASES = {
    "002178.SZ": ("Top10Holder", frozenset(("name", "type"))),
    "002310.SZ": ("Top10Holder", frozenset(("name",))),
    "002328.SZ": ("HolderNum", frozenset(("declareDate", "shareholder", "shareholderA"))),
}
EXPECTED_FORMAT = "qmt_financial_cache_import_v1"
PROTECTED_START_MIN = 18 * 60 + 45
PROTECTED_END_MIN = 23 * 60 + 35
ABSENT = object()


def _china_now():
    return datetime.now(timezone(timedelta(hours=8)))


def check_time(now=None):
    current = now or _china_now()
    minutes = current.hour * 60 + current.minute
    if PROTECTED_START_MIN <= minutes < PROTECTED_END_MIN:
        raise RuntimeError("NIGHTLY_TASK_WINDOW_STOP")


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(v, F):
    return F.E.canonical_json(v)


def text_fingerprint(value):
    text = str(value)
    return {"characters": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def normalized_name(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def name_evidence(old, new):
    if not isinstance(old, str) or not isinstance(new, str):
        return {"old": text_fingerprint(old), "new": text_fingerprint(new), "string_values": False}
    a, b = normalized_name(old), normalized_name(new)
    return {
        "old": text_fingerprint(old),
        "new": text_fingerprint(new),
        "same_after_nfkc_whitespace": a == b,
        "normalization_only_candidate": (old != new and a == b),
        "similarity_ratio": round(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 4),
    }


def numeric_delta(old, new):
    if isinstance(old, bool) or isinstance(new, bool) or old is ABSENT or new is ABSENT:
        return {"numeric_comparison": "UNAVAILABLE"}
    try:
        a, b = Decimal(str(old)), Decimal(str(new))
    except (InvalidOperation, TypeError, ValueError):
        return {"numeric_comparison": "UNAVAILABLE"}
    if not a.is_finite() or not b.is_finite():
        return {"numeric_comparison": "UNAVAILABLE"}
    result = {"numeric_comparison": "AVAILABLE", "difference_new_minus_old": str(b-a)}
    if a != 0:
        result["change_percent"] = str((b-a)*Decimal(100)/a)
    return result


def safe_field_evidence(field, old, new):
    if field == "name":
        return name_evidence(old, new)
    if field in ("shareholder", "shareholderA"):
        return {
            "old_value": None if old is ABSENT else old,
            "new_value": None if new is ABSENT else new,
            **numeric_delta(old, new),
        }
    if field in ("declareDate", "type"):
        def brief(v):
            if v is ABSENT:
                return "<ABSENT>"
            if isinstance(v, str) and len(v) > 120:
                return text_fingerprint(v)
            return v
        return {"old_value": brief(old), "new_value": brief(new)}
    # Never emit unexpected raw source fields.
    return {"old_fingerprint": text_fingerprint(old),
            "new_fingerprint": text_fingerprint(new)}


def _selected_snapshots(extra, code, table, F):
    folder = extra / "financial" / table / code / "snapshots"
    F.E._path_check(folder)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("HISTORICAL_SNAPSHOT_DIR_MISSING_OR_LINKED")
    names = sorted(x.name for x in folder.glob("*.parquet"))
    if any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{16}\.parquet", name)
           for name in names):
        raise ValueError("UNEXPECTED_SNAPSHOT_NAME")
    return sorted({name[:10] for name in names})


def analyze_single_pair(prior, fresh, expected, F):
    """Exactly one old-only and one new-only raw row are required for pairing.

    The only permitted diagnostic projection removes the fields already
    identified by the 53-stock audit. A match does NOT grant data approval.
    """
    current = F._rows(fresh)
    removed = prior - current
    added = current - prior
    n_removed = sum(removed.values())
    n_added = sum(added.values())
    result = {
        "old_unmatched": n_removed,
        "new_unmatched": n_added,
        "matched_raw_records": sum((prior & current).values()),
    }
    if n_removed != 1 or n_added != 1:
        return {"classification": "BLOCKED_UNEXPECTED_CARDINALITY", **result}
    old = json.loads(next(iter(removed)))
    new = json.loads(next(iter(added)))
    if not isinstance(old, dict) or not isinstance(new, dict):
        return {"classification": "BLOCKED_MALFORMED_RECORD", **result}
    fields = sorted(set(old) | set(new))
    changed = sorted(k for k in fields if
                     (canonical(old[k], F) if k in old else "<ABSENT>") !=
                     (canonical(new[k], F) if k in new else "<ABSENT>"))
    result["observed_fields"] = changed
    result["expected_fields"] = sorted(expected)
    old_stable = canonical({k: v for k, v in old.items() if k not in expected}, F)
    new_stable = canonical({k: v for k, v in new.items() if k not in expected}, F)
    result["stable_projection_equal"] = old_stable == new_stable
    result["stable_projection_sha256"] = hashlib.sha256(old_stable.encode("utf-8")).hexdigest() if old_stable == new_stable else None
    # A single unmatched row per side is not sufficient evidence of identity
    # if several historical/current records collapse to the same projection.
    old_keys = Counter()
    new_keys = Counter()
    for raw, multiplicity in prior.items():
        old_keys[canonical({k: v for k, v in json.loads(raw).items()
                            if k not in expected}, F)] += multiplicity
    for raw, multiplicity in current.items():
        new_keys[canonical({k: v for k, v in json.loads(raw).items()
                            if k not in expected}, F)] += multiplicity
    result["candidate_old_projection_count"] = old_keys[old_stable]
    result["candidate_new_projection_count"] = new_keys[new_stable]
    if old_stable == new_stable and (old_keys[old_stable] != 1 or new_keys[new_stable] != 1):
        result["classification"] = "BLOCKED_NONUNIQUE_PAIR"
        return result
    result["old_record_sha256"] = hashlib.sha256(canonical(old, F).encode("utf-8")).hexdigest()
    result["new_record_sha256"] = hashlib.sha256(canonical(new, F).encode("utf-8")).hexdigest()
    result["report_period_old"] = old.get("endDate")
    result["report_period_new"] = new.get("endDate")
    if set(changed) != set(expected) or old_stable != new_stable:
        result["classification"] = "BLOCKED_SCOPE_OR_IDENTITY_MISMATCH"
        # Unexpected source fields are not printed or normalized.
        return result
    result["classification"] = "EXACT_SCOPED_CHANGE_REVIEW_REQUIRED"
    result["changes"] = {
        field: safe_field_evidence(field, old.get(field, ABSENT),
                                   new.get(field, ABSENT))
        for field in changed
    }
    return result


def audit(base, F):
    base = Path(base)
    ledger = base / "work" / "qmt_extra" / "financial-cache-progress.json"
    before = file_sha256(ledger)
    try:
        check_time()
        state = json.loads(ledger.read_text(encoding="utf-8"))
        if state.get("format") != EXPECTED_FORMAT or not isinstance(state.get("pending"), dict):
            raise ValueError("FINANCE_PROGRESS_IDENTITY_FAILED")
        private = Path(state["root"])
        F.E._path_check(private)
        if not private.is_dir() or private.is_symlink():
            raise ValueError("PRIVATE_SNAPSHOT_ROOT_INVALID")
        for code, (table, _) in sorted(CASES.items()):
            item = state["pending"].get(code)
            if not isinstance(item, dict) or item.get("reason") != "SOURCE_HISTORY_CONFLICT":
                raise ValueError("PENDING_CASE_CHANGED_" + code)
            if re.search(r"\btable="+re.escape(table)+r"\b", str(item.get("detail", ""))) is None:
                raise ValueError("PENDING_TABLE_CHANGED_" + code)
        print("AUDIT_SCOPE=3_MATERIAL_FIELD_CASES")
        print("LEDGER_DATE=" + str(state.get("daily_date")))
        print("PENDING_COUNT=" + str(len(state["pending"])))
        codes = sorted(CASES)
        # The original cache worker reads all nine finance tables from existing cache.
        # This deliberately excludes 688259.SH's already-isolated broken Top10Holder.
        with tempfile.TemporaryDirectory(prefix="finance-priority3-cache-") as tmp:
            cache, missing = F._worker_batch(
                codes, "cache", state["daily_date"], 120, tmp, 120,
                progress=lambda line: print("CACHE_WORKER=" + line, flush=True))
            if missing or set(cache) != set(codes):
                raise RuntimeError("QMT_PRIORITY3_CACHE_INCOMPLETE")
            classifications = Counter()
            for code in codes:
                check_time()
                table, expected = CASES[code]
                prior_day, prior = F._prior_rows(private, code, table)
                if prior is None:
                    raise RuntimeError("MISSING_VERIFIED_HISTORICAL_SNAPSHOT_" + code)
                if not isinstance(cache[code], dict) or table not in cache[code]:
                    raise RuntimeError("FINANCE_TABLE_NOT_RETURNED_" + code)
                result = analyze_single_pair(prior, cache[code][table], expected, F)
                result.update({
                    "symbol": code, "table": table, "prior_latest_day": prior_day,
                    "historical_snapshot_days": _selected_snapshots(private, code, table, F),
                    "historical_raw_versions": sum(prior.values()),
                    "current_table_rows": len(cache[code][table]),
                })
                classifications[result["classification"]] += 1
                print("PRIORITY_EVIDENCE=" + json.dumps(
                    result, ensure_ascii=True, sort_keys=True, default=str), flush=True)
            print("CLASSIFICATION_SUMMARY=" + json.dumps(
                dict(sorted(classifications.items())), sort_keys=True))
        print("FINANCE_PRIORITY_THREE_EVIDENCE_COMPLETE_NO_COMMIT")
    finally:
        after = file_sha256(ledger)
        if before != after:
            raise RuntimeError("FINANCE_LEDGER_CHANGED_DURING_AUDIT_STOP")
        print("FINANCE_LEDGER_UNCHANGED_VERIFIED sha256=" + after)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path, help="Canonical production ParquetLiveSync path")
    args = parser.parse_args(argv)
    if not args.base.is_dir() or args.base.is_symlink():
        parser.error("Invalid production base")
    check_time()
    sys.path.insert(0, str(args.base))
    import qmt_extra_financial_cache_import as F
    audit(args.base, F)


if __name__ == "__main__":
    main()
