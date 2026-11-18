#!/usr/bin/env python3
"""Read-only QMT Capital conflict triage, with optional small cached-only sample.

Default path accesses ONLY financial-cache-progress.json: no broker import, no
network calls, no Parquet reads, no state/ledger modifications.
Optional --sample-size N uses ONE isolated existing-cache-only QMT batch
for at most 5 pending symbols, only in the canonical checkout (shared lock).
It never downloads QMT history and never writes canonical data, private
cursors or source snapshots. The existing writer-lock marker may be touched.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import tempfile

CN = timezone(timedelta(hours=8))
TABLE_RE = re.compile(r"(?:^|\s)table=([A-Za-z0-9_]+)(?:\s|$)")
MAX_SAMPLE = 5


def read_progress(path: Path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Expected canonical, non-symlink financial progress JSON")
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict) or not isinstance(obj.get("pending"), dict):
        raise ValueError("Invalid cached-finance progress / pending shape")
    if obj.get("format") != "qmt_financial_cache_import_v1":
        raise ValueError("Unexpected financial progress format")
    return obj


def conflict_table(entry):
    if not isinstance(entry, dict):
        return None
    match = TABLE_RE.search(str(entry.get("detail", "")))
    return match.group(1) if match else None


def summarize(state):
    pending = state["pending"]
    by_reason, by_table, by_date = Counter(), Counter(), Counter()
    capital, unknown, other = [], [], []
    for code, entry in sorted(pending.items()):
        if not isinstance(entry, dict):
            raise ValueError("Invalid financial pending entry")
        why = str(entry.get("reason", "UNCLASSIFIED"))
        table = conflict_table(entry) if why == "SOURCE_HISTORY_CONFLICT" else None
        by_reason[why] += 1
        if why == "SOURCE_HISTORY_CONFLICT":
            by_table[table or "UNKNOWN_TABLE"] += 1
            if table == "Capital":
                capital.append(code)
            elif table is None:
                unknown.append(code)
            else:
                other.append(code)
        if isinstance(entry.get("asof"), str):
            by_date[entry["asof"]] += 1
    return {
        "format": "capital_readonly_pending_family_triage_v1",
        "read_only": True,
        "pending_total": len(pending),
        "source_history_conflict_count": by_reason.get("SOURCE_HISTORY_CONFLICT", 0),
        "capital_conflict_count": len(capital),
        "capital_share_of_history_conflicts_pct": round(
            len(capital) / by_reason["SOURCE_HISTORY_CONFLICT"] * 100, 2)
            if by_reason["SOURCE_HISTORY_CONFLICT"] else None,
        "conflicts_unknown_table": len(unknown),
        "other_history_conflict_count": len(other),
        "reason_counts": dict(sorted(by_reason.items())),
        "conflict_table_counts": dict(sorted(by_table.items())),
        "pending_observation_dates": dict(sorted(by_date.items())),
        "capital_symbols_by_exchange": dict(sorted(Counter(
            code.split(".")[-1] for code in capital).items())),
        "capital_symbol_samples": capital[:12],
        "other_history_symbol_samples": other[:12],
        "daily_date": state.get("daily_date"),
        "daily_cursor": state.get("daily_cursor"),
        "daily_sweep_reached_end": state.get("daily_sweep_reached_end"),
        "daily_sweep_finished": state.get("daily_sweep_finished"),
        "import_cursor": state.get("import_cursor"),
        "all_pending_are_capital": len(capital) == len(pending),
        "provider_revisions_proven": False,
        "historical_financial_data_modified": False,
    }


def representative_capital_symbols(state, count):
    if not 0 <= count <= MAX_SAMPLE:
        raise ValueError("Sample must be 0..5")
    candidates = [
        code for code, entry in state["pending"].items()
        if isinstance(code, str)
        and isinstance(entry, dict)
        and entry.get("reason") == "SOURCE_HISTORY_CONFLICT"
        and conflict_table(entry) == "Capital"
    ]
    candidates = sorted(set(candidates))
    groups = [
        [s for s in candidates if s.endswith(".SZ") and s.startswith("00")],
        [s for s in candidates if s.endswith(".SZ") and s.startswith("30")],
        [s for s in candidates if s.endswith(".SH") and s.startswith("60")],
        [s for s in candidates if s.endswith(".SH") and s.startswith("68")],
        [s for s in candidates if s.endswith(".BJ")],
    ]
    selected = []
    for group in groups:
        if group and len(selected) < count:
            selected.append(group[len(group) // 2])
    for code in candidates:
        if len(selected) >= count:
            break
        if code not in selected:
            selected.append(code)
    return sorted(selected)


def classify_capital(old_records, fresh_records):
    import qmt_extra_financial_conflict_diagnose as D
    comparison = D.compare(old_records, fresh_records)
    changed = comparison["report_key_differences"]
    fields = {key for key, count in changed["changed_field_frequency_top"]
              if count > 0}
    exact = (comparison["old_missing_from_new"] == 0
             and comparison["new_not_in_old"] == 0
             and comparison["old_rows"] == comparison["new_rows"])
    only_mquarter = (
        not exact and
        comparison["old_rows"] == comparison["new_rows"] and
        changed["matched_unique_report_keys"] == comparison["old_rows"] and
        changed["matched_changed"] ==
        comparison["old_missing_from_new"] ==
        comparison["new_not_in_old"] > 0 and
        fields == {"m_quarter"}
    )
    classification = ("NO_CHANGE" if exact else
                      "M_QUARTER_ONLY_CANDIDATE" if only_mquarter else
                      "OTHER_FIELDS_OR_KEYS_CHANGED")
    return {"classification": classification,
            "old_rows": comparison["old_rows"],
            "current_rows": comparison["new_rows"],
            "old_missing_rows": comparison["old_missing_from_new"],
            "new_rows_not_in_baseline": comparison["new_not_in_old"],
            "matched_changed_report_keys": changed["matched_changed"],
            "field_change_frequency": changed["changed_field_frequency_top"],
            "important": "m_quarter-only is a classification, not permission to overwrite previous snapshots"}


def sample_cached_only(stock_root, state, count, timeout):
    if count <= 0:
        return {"status": "NO_QMT_CALLS", "sampled": 0}
    from qmt_extra_financial_cache_import import (
        _worker_batch, _recover_utf8_group, _prior_rows
    )
    from qmt_extra_data import _storage, LIVE
    import qmt_capital_semantic_proof as PROOF
    codes = representative_capital_symbols(state, count)
    if not codes:
        return {"status": "NO_CAPITAL_PENDING_TO_SAMPLE", "sampled": 0}
    extra = _storage(Path(stock_root))
    now = datetime.now(CN).date().isoformat()
    # The only file write is an ephemeral worker output inside OS TEMP,
    # automatically deleted by TemporaryDirectory.  No QMT download.
    with tempfile.TemporaryDirectory(prefix="capital-readonly-sample-") as temp:
        with LIVE.exclusive_writer():
            recovered = _recover_utf8_group(
                _worker_batch, codes, "cache", now, 120, Path(temp), timeout,
                progress=lambda line: None)
            observations = {}
            for code, data, reason in recovered:
                if reason is not None:
                    observations[code] = {
                        "classification": "QMT_CACHE_UNAVAILABLE",
                        "provider_reason": reason}
                    continue
                if not isinstance(data, dict) or "Capital" not in data:
                    observations[code] = {"classification": "QMT_CACHE_MISSING_CAPITAL"}
                    continue
                # Reuse the EXACT official importer history-union reader.
                # A newest-only comparison could miss old business revisions.
                day, saved_raw = _prior_rows(extra, code, "Capital")
                if saved_raw is None:
                    observations[code] = {"classification": "BASELINE_MISSING"}
                    continue
                item = PROOF.prove_historical_union(
                    saved_raw, data["Capital"])
                item["baseline_latest_asof"] = day
                observations[code] = item
    return {"status": "CACHE_ONLY_SAMPLE_DONE",
            "download_called": False, "canonical_parquet_modified": False,
            "private_ledger_modified": False, "sampled": len(codes),
        "all_old_selected_history_checked": True,
        "repair_apply_enabled": False,
            "samples": observations,
            "class_counts": dict(Counter(
                entry["classification"] for entry in observations.values()))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("D:/ChatGPT/AStockDataTools"))
    parser.add_argument("--stock-root", type=Path, default=Path("D:/stock"))
    parser.add_argument("--sample-size", type=int, default=0,
                        help="0: only JSON pending census; 1..5: ONE cached-only QMT batch")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    if not 0 <= args.sample_size <= MAX_SAMPLE:
        parser.error("sample-size must be 0..5")
    if not 30 <= args.timeout_seconds <= 3600:
        parser.error("timeout-seconds must be 30..3600")
    ledger = args.repo / "ParquetLiveSync" / "work" / "qmt_extra" / "financial-cache-progress.json"
    state = read_progress(ledger)
    census = summarize(state)
    print("QMT_CAPITAL_PENDING_CENSUS=" +
          json.dumps(census, ensure_ascii=False, sort_keys=True))
    if args.sample_size:
        # Shared exclusive writer lock is anchored to the real repository
        # path. A detached worktree has its own lock, so it is intentionally
        # forbidden for QMT cache sampling. Offline census remains portable.
        source_repo = Path(__file__).resolve().parent.parent
        if source_repo != args.repo.resolve():
            raise ValueError(
                "LIVE_SAMPLE_REQUIRES_CANONICAL_CHECKOUT: use only offline "
                "census from a detached Preview worktree")
        sampled = sample_cached_only(args.stock_root, state, args.sample_size,
                                     args.timeout_seconds)
        print("QMT_CAPITAL_CACHED_SAMPLE=" +
              json.dumps(sampled, ensure_ascii=False, sort_keys=True))
    else:
        print("QMT_CAPITAL_PENDING_CENSUS_READONLY_COMPLETE")


if __name__ == "__main__":
    main()
