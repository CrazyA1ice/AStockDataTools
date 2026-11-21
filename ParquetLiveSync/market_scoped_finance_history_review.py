"""S4: bounded, read-only nine-table finance history precommit review.

Input is an existing short-lived QMT cache-worker JSON in private staging.
No QMT calls, downloads, Parquet writes, cursor updates, or waiver policies.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from hashlib import sha256
import argparse
import json
from pathlib import Path
import re
import sys

import qmt_extra_data as E
import qmt_extra_financial_cache_import as I

MAX_STOCKS = 5
MAX_STAGE_BYTES = 64 * 1024 * 1024
MAX_LEDGER_BYTES = 2 * 1024 * 1024
MAX_ROWS_PER_TABLE = 100000
SHA = re.compile(r"[0-9a-fA-F]{64}")
YYYYMMDD = re.compile(r"20[0-9]{6}")
RUN_ID = re.compile(r"[0-9a-f]{32}")


class PrecommitBlocked(ValueError):
    """Bad or changing input is not an approved finance refresh."""


def _hash_file(path: Path, maximum: int) -> str:
    E._path_check(path)
    if not path.is_file() or path.is_symlink():
        raise PrecommitBlocked("REQUIRED_PRIVATE_FILE_MISSING_OR_LINKED")
    size = path.stat().st_size
    if not 0 < size <= maximum:
        raise PrecommitBlocked("PRIVATE_FILE_SIZE_LIMIT")
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    if path.stat().st_size != size:
        raise PrecommitBlocked("PRIVATE_FILE_CHANGED_DURING_READ")
    return h.hexdigest()


def _strict_stage(workspace: Path, staged: Path) -> None:
    if (staged.name != "cache.json"
            or not RUN_ID.fullmatch(staged.parent.name)
            or staged.parent.parent != workspace / "scoped-cache-stage"):
        raise PrecommitBlocked("CACHE_JSON_MUST_BE_IN_PRIVATE_JOB_DIRECTORY")
    E._path_check(staged)
    if not staged.parent.is_dir() or staged.parent.is_symlink():
        raise PrecommitBlocked("PRIVATE_JOB_DIRECTORY_INVALID")


def _stock_scope(symbols: str) -> list[str]:
    if not isinstance(symbols, str):
        raise PrecommitBlocked("STOCK_SCOPE_INVALID")
    codes = symbols.split(",")
    if (not 1 <= len(codes) <= MAX_STOCKS
            or codes != sorted(set(codes))):
        raise PrecommitBlocked("STOCK_SCOPE_NOT_SORTED_UNIQUE")
    try:
        if any(E.valid_code(code) != code for code in codes):
            raise PrecommitBlocked("STOCK_SCOPE_INVALID")
    except ValueError as exc:
        raise PrecommitBlocked("STOCK_SCOPE_INVALID") from exc
    return codes


def evaluate(payload: dict, *, stocks: list[str], start: str, end: str,
             extra: Path, asof: str, pending: dict | None = None,
             prior=None, planner=None) -> dict:
    """Compare ALL nine historical tables, even when a first conflict exists.

    The importer itself is the final policy authority: on a conflict we
    DO NOT call it with experimental Capital allowances. On a clean stock
    we additionally ask its strict _plan_symbol for the exact actions.
    """
    prior = I._prior_rows if prior is None else prior
    planner = I._plan_symbol if planner is None else planner
    try:
        first = datetime.strptime(start, "%Y%m%d").date()
        last = datetime.strptime(end, "%Y%m%d").date()
        today = date.fromisoformat(asof)
    except (TypeError, ValueError) as exc:
        raise PrecommitBlocked("ANNOUNCEMENT_WINDOW_DATE_INVALID") from exc
    if (first > last or (last - first).days > 30 or last > today):
        raise PrecommitBlocked("ANNOUNCEMENT_WINDOW_OUT_OF_SCOPE")
    if (type(payload) is not dict
            or payload.get("format") != "qmt_financial_cache_batch_v1"
            or payload.get("mode") != "daily"
            or payload.get("symbols") != stocks
            or payload.get("refresh_start") != start
            or payload.get("refresh_end") != end
            or type(payload.get("records")) is not dict
            or type(payload.get("missing_symbols")) is not list
            or type(payload.get("row_counts")) is not dict
            or YYYYMMDD.fullmatch(start) is None
            or YYYYMMDD.fullmatch(end) is None or start > end):
        raise PrecommitBlocked("QMT_WORKER_ENVELOPE_MISMATCH")
    present = payload["records"]
    missing = payload["missing_symbols"]
    if (set(present) | set(missing) != set(stocks)
            or set(present) & set(missing)
            or len(missing) != len(set(missing))
            or set(payload["row_counts"]) != set(present)):
        raise PrecommitBlocked("QMT_WORKER_STOCK_COVERAGE_INVALID")
    pending = pending if isinstance(pending, dict) else {}
    result = []
    for stock in stocks:
        if stock in missing:
            result.append({
                "symbol": stock, "status": "SOURCE_CACHE_MISSING",
                "tables_checked": 0, "historical_conflicts": [],
                "pending_previously_recorded": stock in pending,
                "can_commit": False,
            })
            continue
        data = present[stock]
        counts = payload["row_counts"].get(stock)
        if (type(data) is not dict or type(counts) is not dict
                or set(data) != set(E.FIN_TABLES)
                or set(counts) != set(E.FIN_TABLES)):
            raise PrecommitBlocked("NINE_FINANCIAL_TABLES_INCOMPLETE")
        conflicts = []
        historical_rows = 0
        source_rows = 0
        for table in E.FIN_TABLES:
            records = data[table]
            expected = counts[table]
            if (type(records) is not list or type(expected) is not int
                    or expected != len(records)
                    or expected > MAX_ROWS_PER_TABLE
                    or any(type(rec) is not dict
                           or type(rec.get("_index")) is not str
                           for rec in records)):
                raise PrecommitBlocked("FINANCE_CACHE_TABLE_SHAPE_INVALID")
            old_date, saved = prior(extra, stock, table)
            if old_date is not None and old_date > asof:
                raise PrecommitBlocked("SAVED_HISTORY_DATE_AFTER_COMPARISON")
            saved = saved or Counter()
            if not isinstance(saved, Counter):
                raise PrecommitBlocked("HISTORY_COUNTER_INVALID")
            current = I._rows(records)
            missing_rows = saved - current
            if missing_rows:
                conflicts.append({
                    "table": table,
                    "historical_rows_missing_or_revised": sum(
                        missing_rows.values()),
                })
            historical_rows += sum(saved.values())
            source_rows += len(records)
        if source_rows == 0 and historical_rows == 0:
            result.append({
                "symbol": stock, "status": "SOURCE_CACHE_MISSING",
                "tables_checked": len(E.FIN_TABLES),
                "historical_conflicts": [],
                "pending_previously_recorded": stock in pending,
                "can_commit": False,
            })
            continue
        if conflicts:
            result.append({
                "symbol": stock, "status": "BLOCKED_HISTORY_CONFLICT",
                "tables_checked": len(E.FIN_TABLES),
                "historical_conflicts": conflicts,
                "previous_records": historical_rows,
                "cache_records": source_rows,
                "pending_previously_recorded": stock in pending,
                "can_commit": False,
            })
            continue
        try:
            # Strict importer semantics without any Capital exception/policy.
            planned, staged = planner(extra, stock, asof, data)
        except ValueError as exc:
            raise PrecommitBlocked("STRICT_IMPORTER_PLAN_REFUSED") from exc
        if set(planned) != set(E.FIN_TABLES) or not set(staged) <= set(E.FIN_TABLES):
            raise PrecommitBlocked("STRICT_IMPORTER_RETURNED_INVALID_TABLE_SET")
        actions = Counter(item.get("action") for item in planned.values())
        if any(action not in ("UNCHANGED", "CREATE_VERSION",
                              "NO_SOURCE_RECORDS") for action in actions):
            raise PrecommitBlocked("STRICT_IMPORTER_UNEXPECTED_ACTION")
        result.append({
            "symbol": stock,
            "status": ("CANDIDATE_NEW_VERSION_NOT_COMMITTED"
                       if actions["CREATE_VERSION"] else
                       "LOCAL_HISTORY_UNCHANGED_NOT_CERTIFIED"),
            "tables_checked": len(E.FIN_TABLES),
            "historical_conflicts": [],
            "previous_records": historical_rows,
            "cache_records": source_rows,
            "table_actions": {
                k: actions[k] for k in sorted(actions)
            },
            "pending_previously_recorded": stock in pending,
            "can_commit": False,
        })
    return {
        "status": "SCOPED_FINANCE_NINE_TABLE_PRECOMMIT_READONLY",
        "symbols_requested": len(stocks),
        "stock_results": result,
        "stocks_history_conflict": sum(
            item["status"] == "BLOCKED_HISTORY_CONFLICT" for item in result),
        "stocks_missing_cache": sum(
            item["status"] == "SOURCE_CACHE_MISSING" for item in result),
        "stocks_candidate_for_review": sum(
            item["status"] == "CANDIDATE_NEW_VERSION_NOT_COMMITTED"
            for item in result),
        "all_nine_tables_locally_compared": all(
            item["tables_checked"] == len(E.FIN_TABLES) for item in result),
        "only_local_qmt_cache_compared": True,
        "source_authenticity_certified": False,
        "multisource_verified": False,
        "can_download": False,
        "can_execute": False,
        "can_commit": False,
        "official_market_writes": 0,
        "financial_ledger_writes": 0,
        "qmt_calls": 0,
    }


def review(*, root: Path, workspace: Path, cache_file: Path,
           expected_cache_sha256: str, expected_progress_sha256: str,
           symbols: str, start: str, end: str) -> dict:
    if (not SHA.fullmatch(expected_cache_sha256)
            or not SHA.fullmatch(expected_progress_sha256)):
        raise PrecommitBlocked("EXPLICIT_SHA256_BOTH_REQUIRED")
    workspace = Path(workspace).absolute()
    if workspace != E.WORK.absolute():
        raise PrecommitBlocked("CANONICAL_FINANCE_WORKSPACE_REQUIRED")
    E._path_check(workspace)
    _strict_stage(workspace, Path(cache_file))
    stock_list = _stock_scope(symbols)
    progress = workspace / I.STATE_FILE
    progress_sha = _hash_file(progress, MAX_LEDGER_BYTES)
    if progress_sha != expected_progress_sha256.lower():
        raise PrecommitBlocked("FINANCE_PROGRESS_SHA_CHANGED")
    cache_sha = _hash_file(cache_file, MAX_STAGE_BYTES)
    if cache_sha != expected_cache_sha256.lower():
        raise PrecommitBlocked("CACHE_STAGE_SHA_CHANGED")
    extra = E._storage(root)
    ledger = I._state(extra, workspace)
    try:
        with Path(cache_file).open("rb") as stream:
            payload = json.load(stream)
    except (ValueError, UnicodeError) as exc:
        raise PrecommitBlocked("CACHE_STAGE_JSON_INVALID") from exc
    asof = datetime.now(E.L.UTC8).date().isoformat()
    answer = evaluate(
        payload, stocks=stock_list, start=start, end=end,
        extra=extra, asof=asof, pending=ledger["pending"])
    if (_hash_file(progress, MAX_LEDGER_BYTES) != progress_sha
            or _hash_file(cache_file, MAX_STAGE_BYTES) != cache_sha):
        raise PrecommitBlocked("PRIVATE_EVIDENCE_CHANGED_DURING_REVIEW")
    answer["progress_sha256"] = progress_sha
    answer["cache_sha256"] = cache_sha
    return answer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--cache-file", type=Path, required=True)
    parser.add_argument("--expected-cache-sha256", required=True)
    parser.add_argument("--expected-progress-sha256", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--explicit-readonly", action="store_true")
    args = parser.parse_args(argv)
    if not args.explicit_readonly:
        print(json.dumps({"status": "SCOPED_FINANCE_REVIEW_OPTIN_REQUIRED",
                          "qmt_calls": 0, "official_market_writes": 0}))
        return 2
    try:
        result = review(
            root=args.root, workspace=args.workspace,
            cache_file=args.cache_file,
            expected_cache_sha256=args.expected_cache_sha256,
            expected_progress_sha256=args.expected_progress_sha256,
            symbols=args.symbols, start=args.start, end=args.end)
    except PrecommitBlocked as exc:
        print(json.dumps({
            "status": "SCOPED_FINANCE_PRECOMMIT_BLOCKED",
            "reason": str(exc)[:120], "qmt_calls": 0,
            "official_market_writes": 0,
        }, sort_keys=True))
        return 2
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        print(json.dumps({
            "status": "SCOPED_FINANCE_PRECOMMIT_BLOCKED",
            "reason": "LOCAL_HISTORY_OR_PAYLOAD_VALIDATION_FAILED",
            "qmt_calls": 0, "official_market_writes": 0,
        }, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
