#!/usr/bin/env python3
"""One existing-cache-only 002188 Capital review of PINNED 9 holder raw duplicates.

All original Top10Holder row multiplicities are preserved (779 distinct/788
total). QMT is never downloaded; no private Parquet, pin or ledger is written.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

CODE, HOLDER_TABLE = "002188.SZ", "Top10Holder"
LEDGER_SHA = "4b90a4eaa1a12ff8f6ac6ebc132b59f6d3dba41a2a0b424d493b2e8d0fa5f2b1"
LEDGER_DATE = "2026-11-24"
NAME = re.compile(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{16}\.parquet\Z")
BJ = timezone(timedelta(hours=8))


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def protect_clock(now=None):
    now = now or datetime.now(BJ)
    minutes = now.hour * 60 + now.minute
    if 18*60 + 30 <= minutes < 23*60 + 35:
        raise RuntimeError("PINNED_002188_NIGHTLY_TASK_WINDOW_STOP")


def validate_ledger(state, before):
    if before != LEDGER_SHA:
        raise RuntimeError("PINNED_002188_LEDGER_DRIFT_STOP")
    if (not isinstance(state, dict)
            or state.get("format") != "qmt_financial_cache_import_v1"
            or state.get("daily_date") != LEDGER_DATE
            or not isinstance(state.get("root"), str)
            or not isinstance(state.get("pending"), dict)
            or len(state["pending"]) != 54):
        raise RuntimeError("PINNED_002188_VERIFIED_EPOCH_CHANGED_STOP")
    item = state["pending"].get(CODE)
    invalid = state["pending"].get("688259.SH")
    if (not isinstance(item, dict)
            or item.get("reason") != "SOURCE_HISTORY_CONFLICT"
            or re.search(r"\btable=Capital\b", str(item.get("detail", ""))) is None
            or not isinstance(invalid, dict)
            or invalid.get("reason") != "CACHE_DECODE_ERROR"):
        raise RuntimeError("PINNED_002188_PENDING_SCOPE_CHANGED_STOP")


def prepare_evidence(doc, P):
    if (not isinstance(doc, dict)
            or doc.get("format") != "qmt_002188_top10holder_exact_multiplicity_pin_v1"
            or doc.get("allow_deduplication") is not False
            or doc.get("allow_apply") is not False
            or doc.get("allow_pending_clear") is not False
            or doc.get("human_approval_granted") is not False
            or doc.get("ledger_sha256") != LEDGER_SHA
            or doc.get("historical_union_sha256") != P.PINNED_002188_UNION_SHA256
            or doc.get("duplicate_row_sha256") != sorted(P.PINNED_002188_RAW_SHA256)
            or doc.get("selected_snapshots") != P.PINNED_002188_SNAPSHOTS
            or doc.get("capital_additive_review_scope") != {
                "historical_report_keys": 108,
                "current_report_keys": 109,
                "exact_new_report_key": "20261119",
                "historical_capital_raw_versions": 110,
                "removed_report_keys": 0,
                "shared_economic_changed_keys": 0,
            }):
        raise RuntimeError("PINNED_002188_MANIFEST_MISMATCH_STOP")
    return dict(doc)


def check_selected_holder_files(root, E, F, P):
    folder = root / "financial" / HOLDER_TABLE / CODE / "snapshots"
    E._path_check(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise RuntimeError("PINNED_002188_SNAPSHOT_FOLDER_INVALID")
    names = [p.name for p in folder.glob("*.parquet")]
    if not names or any(NAME.fullmatch(name) is None for name in names):
        raise RuntimeError("PINNED_002188_SNAPSHOT_NAMES_INVALID")
    days = sorted({name[:10] for name in names})
    if days != sorted(P.PINNED_002188_SNAPSHOTS):
        raise RuntimeError("PINNED_002188_SNAPSHOT_DATES_CHANGED")
    verified = {}
    union = Counter()
    for day in days:
        protect_clock()
        selected = E._financial_snapshot_file(root, CODE, HOLDER_TABLE, day)
        if selected is None or selected.is_symlink() or not selected.is_file():
            raise RuntimeError("PINNED_002188_ACTIVE_SNAPSHOT_MISSING")
        E._path_check(selected)
        checksum = file_sha(selected)
        rows = E._financial_snapshot_rows(root, CODE, HOLDER_TABLE, day)
        if not isinstance(rows, list) or checksum != file_sha(selected):
            raise RuntimeError("PINNED_002188_SNAPSHOT_CHANGED_DURING_READ")
        counts = F._rows(rows)
        data = {
            "filename": selected.name,
            "sha256": checksum,
            "rows": len(rows),
            "distinct_raw_records": len(counts),
            "extra_raw_occurrences": sum(n - 1 for n in counts.values() if n > 1),
        }
        if data != P.PINNED_002188_SNAPSHOTS[day]:
            raise RuntimeError("PINNED_002188_SNAPSHOT_CONTENT_OR_SELECTION_CHANGED")
        verified[day] = data
        union |= counts
    latest, actual = F._prior_rows(root, CODE, HOLDER_TABLE)
    if latest != days[-1] or actual != union:
        raise RuntimeError("PINNED_002188_SELECTED_COUNTER_MAX_UNION_MISMATCH")
    return verified, union


def run(base, manifest, E, F, P):
    base = Path(base)
    ledger = base / "work" / "qmt_extra" / "financial-cache-progress.json"
    before = file_sha(ledger)
    try:
        protect_clock()
        state = json.loads(ledger.read_text(encoding="utf-8"))
        validate_ledger(state, before)
        manifest = Path(manifest)
        E._path_check(manifest)
        if manifest.is_symlink() or not manifest.is_file():
            raise RuntimeError("PINNED_002188_MANIFEST_FILE_INVALID")
        evidence = prepare_evidence(
            json.loads(manifest.read_text(encoding="utf-8")), P)
        root = Path(state["root"])
        E._path_check(root)
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError("PINNED_002188_SOURCE_ROOT_INVALID")
        verified, historical_union = check_selected_holder_files(root, E, F, P)
        # Complete all ledger / selected-snapshot identity checks BEFORE QMT.
        with tempfile.TemporaryDirectory(prefix="finance-002188-review-cacheonly-") as temp:
            protect_clock()
            cache, missing = F._worker_batch(
                [CODE], "cache", LEDGER_DATE, 120, temp, 120,
                progress=lambda msg: print("PINNED_002188_QMT_CACHE=" + msg, flush=True))
            if missing or set(cache) != {CODE}:
                raise RuntimeError("PINNED_002188_QMT_CACHE_INCOMPLETE")
            source = cache[CODE]
            if not isinstance(source, dict) or set(source) != set(E.FIN_TABLES):
                raise RuntimeError("PINNED_002188_ALL_NINE_QMT_TABLES_REQUIRED")
            selected = {}
            for table in E.FIN_TABLES:
                protect_clock()
                _, counter = F._prior_rows(root, CODE, table)
                if counter is None:
                    counter = Counter()
                if not isinstance(counter, Counter):
                    raise RuntimeError("PINNED_002188_INVALID_VERIFIED_HISTORY_" + table)
                selected[table] = counter
            if selected[HOLDER_TABLE] != historical_union:
                raise RuntimeError("PINNED_002188_HISTORY_CHANGED_DURING_READ")
            evidence["verified_active_snapshots"] = verified
            preview = P.preview_symbol(
                CODE, "CAPITAL_ADDITIVE", "Capital",
                selected, source, F,
                ledger_sha256=before, duplicate_evidence=evidence)
            if (preview.get("classification") != "CAPITAL_ADDITIVE_REVIEW_REQUIRED"
                    or preview.get("allow_apply") is not False
                    or preview.get("allow_auto_clear") is not False
                    or preview.get("pinned_top10holder_duplicate_proof") is None
                    or P._verify_pinned_002188_capital_scope(
                        preview.get("proof")) is not True):
                raise RuntimeError("PINNED_002188_UNSAFE_PREVIEW_RESULT")
            # Do not publish review result until the final ledger hash is known.
            result = {
                "symbol": CODE, "table": "Capital",
                "classification": preview["classification"],
                "preview_sha256": preview["preview_sha256"],
                "capital": preview["proof"],
                "top10holder": preview["pinned_top10holder_duplicate_proof"],
                "verified_selected_snapshots": verified,
                "ledger_before_sha256": before,
                "approval_granted": False,
                "allow_apply": False, "allow_auto_clear": False,
                "allow_deduplication": False,
            }
    finally:
        after = file_sha(ledger)
        if after != before:
            raise RuntimeError("PINNED_002188_LEDGER_CHANGED_DURING_RUN_STOP")
        print("PINNED_002188_LEDGER_UNCHANGED_VERIFIED sha256=" + after, flush=True)
    print("PINNED_002188_REVIEW=" +
          json.dumps(result, sort_keys=True, ensure_ascii=True), flush=True)
    print("PINNED_002188_REVIEW_COMPLETE_NO_COMMIT", flush=True)
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.base.is_dir() or args.base.is_symlink():
        parser.error("invalid canonical production base")
    protect_clock()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(1, str(args.base))
    import qmt_extra_financial_cache_import as F
    import qmt_extra_data as E
    import qmt_finance_versioned_recovery_preview as P
    run(args.base, args.manifest, E, F, P)


if __name__ == "__main__":
    main()
